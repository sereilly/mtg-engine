"""Casting a spell from hand (CR 601): put it on the stack, having chosen
targets, modes and X, and paid its cost.

Everything here runs *before* the spell resolves. ``cast_from_hand`` is the
entry point and ``queue_from_hand`` does the work; ``_validate_cast_targets`` is
the gate the UI's target enumerator also runs through
(``engine/legality.py``), so a target the picker offers is one resolution will
accept.

The Aura enchant-noun helpers live here because an Aura chooses what it attaches
to as it is cast. ``engine/targeting.py`` answers the same question from the
compiled program and the two share a vocabulary deliberately — see its
``enchant_line_subject``.
"""

from __future__ import annotations

import re

from .._constants import _MANA_SYMBOLS as _POOL_SYMBOLS
from ...cast_permissions import consume as consume_permission, permission_for
from ...auras import aura_enchant_clause
from ...alternative_costs import AlternativeCost, alternative_costs
from ...cast_costs import AdditionalCost, OptionalManaCost, additional_costs
from ...auras import controller_cast_ban
from ...cast_restrictions import (check_cast_timing, chosen_name_ban,
                                  global_cast_ban)
from ...cast_timing import (CAST_AT_INSTANT_SPEED, a_sorcery_could_be_cast,
                            sacrifices_at_cleanup_if_cast_at_instant_speed)
from ...cost_x_definitions import (caps_cast_x, cast_x_ceiling,
                                   cast_x_value, defines_cast_x)
from ...damage_ledger import record_cast
from ...divided_damage import (
    EVENLY, divided_description, divided_entry, division_refusal,
)
from ...hand_locks import hand_lock_reason, playable_hand_index
from ...classifier import classify_card
from ...cost_modifiers import (
    CostReduction, cost_reduction_for_cast, reduce_cost, sacrifice_taxes,
    spell_cost_tax, spell_life_tax, spell_symbol_tax,
)
from ...game_types import SimulationResult, StackItem
from ...handlers._common import graveyard_card_matches, permanent_matches_filter
from ...models import CardDefinition, Permanent, PlayerState
from ...oracle import _COLOR_WORD_TO_SYMBOL, compile_card_oracle
from ...oracle_types import x_spend_colors_from_text
from ...restricted_mana import CAST, PaymentPurpose
from ...target_restrictions import forbidden_target
from ...targeting import bounce_subject_filter, graveyard_target_spec
from ...subject_filters import card_matches_any, filter_head_noun, subject_matches
from ...targeting import (derive_cast_spec, enchant_subject_colours,
                          enchant_subject_keyword_exclusion,
                          enchant_subject_seat, spec_roles, targets_mana_value_x)

def _optional_cost_offers(
    costs: "tuple[AdditionalCost, ...]",
) -> dict[str, OptionalManaCost]:
    """Every CR 601.2b optional mana offer *costs* prints, by its canonical
    spelling.

    One dict for the whole cast rather than a walk per question, because the
    read-back at resolution is keyed the same way: "for each additional {1}{R}
    you paid" names the offer by its symbols, and two sentences of one card must
    not disagree about which offer that is.
    """
    return {
        offer.symbols: offer
        for cost in costs
        for offer in cost.optional_mana
    }


def _optional_cost_announcement(
    card: CardDefinition,
    costs: "tuple[AdditionalCost, ...]",
    announced: dict[str, int] | None,
) -> tuple[dict[str, int], str | None]:
    """How many times each optional additional cost is being paid, or a refusal.

    CR 601.2b: the caster announces this as the spell is cast, before targets
    and long before payment, and the announcement is *checked* here — an
    announcement naming an offer the card does not print, or taking a
    non-repeating offer twice, is an illegal proposal that CR 601.2e rewinds
    rather than a payment to clamp. Nothing has been spent at this point, so a
    refusal costs the caster exactly nothing.

    An absent or empty announcement declines every offer, which is what
    *optional* means and the only default that cannot charge a player for a
    price they did not accept.
    """
    offers = _optional_cost_offers(costs)
    taken: dict[str, int] = {}
    for symbols, times in (announced or {}).items():
        count = int(times or 0)
        if count <= 0:
            continue
        offer = offers.get(str(symbols))
        if offer is None:
            printed = ", ".join(sorted(offers)) or "none"
            return {}, (
                f"{card.name} prints no additional cost of {symbols} "
                f"(it offers: {printed}) (CR 601.2b)"
            )
        if count > 1 and not offer.repeatable:
            return {}, (
                f"{card.name}'s additional cost of {offer.symbols} may be paid "
                f"once, not {count} times (CR 601.2b)"
            )
        taken[offer.symbols] = count
    return taken, None


def _optional_cost_totals(
    costs: "tuple[AdditionalCost, ...]", taken: dict[str, int]
) -> "list[tuple[OptionalManaCost, int]]":
    """The offers actually taken, paired with how many times.

    Read back off the printed offers rather than off the announcement's keys, so
    the mana charged is the mana the *card* prints — a caller that sent a
    canonical-looking key nothing prints was already refused above, and this
    keeps the charge and the record derived from one list.
    """
    offers = _optional_cost_offers(costs)
    return [
        (offers[symbols], times)
        for symbols, times in taken.items()
        if symbols in offers
    ]


# Maps an "enchant X" noun to a predicate matching legal battlefield targets.
# "creature" uses Permanent.is_creature so animated lands (Kormus Bell / Living
# Lands) accept creature Auras while they are creatures.
_ENCHANT_TARGET_MATCHERS = {
    "artifact": lambda perm: perm.has_type("artifact"),
    "creature": lambda perm: perm.is_creature,
    "land": lambda perm: perm.card.primary_type == "land",
    "enchantment": lambda perm: perm.has_type("enchantment"),
    "wall": lambda perm: perm.has_type("wall"),
    # "Enchant **permanent**" (Faith's Fetters). Everything on the battlefield
    # is one (CR 110.1), so the answer is yes — written out rather than left to
    # the fallback below, which says yes for a noun nobody has read.
    "permanent": lambda perm: True,
}

#: "Enchant **non-Wall** creature" (Aggression). The negation is a *prefix* on
#: the noun the table above already knows, so it is read here rather than
#: becoming a row per excluded subtype — "non-Wall creature" and "non-Zombie
#: creature" are one clause with the word as payload.
#:
#: Without it the whole phrase missed the table and the fallback said yes, so
#: Aggression could be put on a Wall — the restriction printed on the card, the
#: card reported supported, and nothing anywhere enforcing it. Through
#: ``has_type`` so it is CR 613 layer 4's answer: a creature an effect has made
#: a Wall is a Wall to this clause, and one whose Wall type was removed is not.
_NON_SUBTYPE_ENCHANT = re.compile(r"^non-(?P<subtype>[a-z]+) (?P<noun>.+)$")


def aura_enchant_noun(card: CardDefinition) -> str | None:
    """Return the battlefield enchant noun for an Aura card, or None.

    Returns None for non-Auras and for Auras that don't enchant battlefield
    permanents (e.g. Animate Dead's "enchant creature card in a graveyard").

    The enchant line is *found*, not assumed to be the first one. Every Aura in
    the shipped pool prints it first, so reading line 0 was right until Capture
    Sphere printed "Flash" above it — and the failure was silent in the worst
    way: the Aura resolved, entered the battlefield, and attached to nothing.
    """
    if "Aura" not in card.type_line:
        return None
    for raw_line in card.oracle_text.lower().split("\n"):
        line = re.sub(r"\([^)]*\)", "", raw_line).strip()  # drop reminder text
        if not line.startswith("enchant "):
            continue
        noun = line[len("enchant "):].strip()
        return None if "graveyard" in noun else noun
    return None


def enchant_noun_seat(noun: str) -> str | None:
    """Which seat an enchant clause restricts the host to, or None.

    ``"you"`` for "Enchant creature **you control**" (Cocoon), ``"opponent"``
    for "Enchant artifact **an opponent controls**" (Relic Bind), None for a
    clause that names no seat.

    The seat half of the clause, separated from the type half because the type
    is a question about the permanent alone while this one needs two seats —
    asked by the cast gate (CR 601.2c), by the AI's target picker, by
    ``auras.aura_attach_refusal`` and by the CR 704.5m sweep that puts the Aura
    into the graveyard when its host stops satisfying the clause. The split
    itself is ``targeting.enchant_subject_seat``, which the picker's spec is
    also built from, so the offered list and the enforced rule cannot drift.
    """
    return enchant_subject_seat(noun)[1]


def enchant_seat_satisfied(game, aura_seat: int | None, host_seat: int | None, noun: str) -> bool:
    """Whether *host_seat* satisfies *noun*'s seat clause for an Aura
    controlled by *aura_seat*.

    One answer rather than an ``== aura_seat`` here and a ``!= aura_seat``
    there: "an opponent controls" is not the negation of "you control" at a
    multiplayer table (CR 102.3 — a player is never their own opponent, but
    neither is a teammate an opponent), so the opponent half asks the game.
    """
    seat = enchant_noun_seat(noun)
    if seat is None:
        return True
    if aura_seat is None or host_seat is None:
        return False
    if seat == "you":
        return host_seat == aura_seat
    return host_seat in game.opponents_of(aura_seat)


def permanent_matches_enchant_noun(permanent: Permanent, noun: str) -> bool:
    """Whether *permanent* is a legal host for an Aura printing "enchant *noun*".

    Read by the cast gate (CR 601.2c), the target picker,
    ``auras.aura_attach_refusal`` and the CR 704.5m sweep — one answer, so the
    list offered and the rule enforced cannot drift.
    """
    noun = enchant_subject_seat(noun)[0]
    excluded = None
    negated = _NON_SUBTYPE_ENCHANT.match(noun)
    if negated is not None:
        excluded, noun = negated.group("subtype"), negated.group("noun")
    # "Enchant creature **without flying**" (Roots). The keyword half of
    # CR 702.5's [quality], split by the reader `targeting.enchant_subject_spec`
    # builds the picker from — so the hosts offered and the hosts allowed are
    # one reading. Through ``Permanent.has_keyword``, which is CR 613 layer 6's
    # answer: a creature *granted* flying stops being a legal host (and
    # ``unattach_illegal_equipment``'s sibling sweep, CR 704.5m, then puts the
    # Aura in the graveyard), while one that has lost it becomes one.
    #
    # The word itself is validated where the clause is *claimed*
    # (`targeting.enchant_line_subject`): a keyword nothing implements answers
    # no for every creature, which would make this exclusion match them all.
    noun, without_keyword = enchant_subject_keyword_exclusion(noun)
    if without_keyword is not None and permanent.has_keyword(without_keyword):
        return False
    # "Enchant **black** creature" (Decomposition) / "**red or green**" (Mind
    # Harness) / "**nonblack**" (Armor of Thorns). The colour half of CR 702.5's
    # [quality], split by the same reader the picker builds its spec from — so
    # the hosts offered and the hosts allowed stay one reading. Through
    # `permanent_effective_colors`, which is CR 613 layer 5's answer: a creature
    # an effect has recoloured is judged on what it is now, and the CR 704.5m
    # sweep then puts the Aura in the graveyard if that made it illegal.
    noun, colours, colours_excluded = enchant_subject_colours(noun)
    if colours:
        from ...handlers._common import permanent_effective_colors

        present = permanent_effective_colors(permanent) & set(colours)
        if bool(present) is colours_excluded:
            return False
    # "Enchant **artifact or creature**" (Teferi's Curse). A printed union is an
    # OR, so any one member is enough — asked of the same matcher table a single
    # noun uses, which is what keeps a union from being a second vocabulary.
    if " or " in noun:
        parts = [part.strip() for part in noun.split(" or ")]
        matchers = [_ENCHANT_TARGET_MATCHERS.get(part) for part in parts]
        if any(matcher is None for matcher in matchers):
            return True
        return any(matcher(permanent) for matcher in matchers)
    matcher = _ENCHANT_TARGET_MATCHERS.get(noun)
    if matcher is None:
        # A noun nobody has read. Every one the pool prints has a row above, so
        # this is unreachable today and is kept as the permissive answer rather
        # than made strict: a printed clause reaching here is a gap to fill, and
        # refusing every host would make the Aura uncastable instead of loud.
        return True
    if excluded is not None and permanent.has_type(excluded):
        return False
    return matcher(permanent)


def _divided_total(payload: dict, x_value: int | None) -> int:
    """How much a divided instruction has to divide, as announced.

    The same two keys the handler adds together — the amount and Meteor
    Shower's "X **plus 1**" bonus — read here so CR 601.2d's "the division must
    total this" is checked against the number the spell will really deal.
    """
    from ...handlers._common import resolve_amount

    # ``count`` for a distributed *counter* placement (Spoils of War) and
    # ``amount`` for damage: one sentence in CR 601.2d covers both, and the two
    # instruction families spell their quantity with the words their own
    # handlers read. Named here rather than normalized at the lowering, because
    # renaming one would be a payload key changed for the gate's convenience.
    quantity = payload.get("amount", payload.get("count", 0))
    return int(resolve_amount(quantity, x_value)) + int(
        payload.get("amount_bonus", 0) or 0
    )



def _named_divided_targets(
    card: CardDefinition, from_zone: str, target_player_index,
    target_permanent_index, target_permanent_ids,
) -> int:
    """How many targets a divided spell's caster named *outside* the division.

    CR 601.2d asks for a division "among one or more targets", and the division
    list is not the only way to name one: every scripted duel, most of this
    engine's own tests and the four "any target" burn spells still announce
    through ``target_permanent_index`` / ``target_player_index``, which is a
    lawful one-target announcement (that target takes the whole amount). So the
    floor in :func:`division_refusal` refuses a caster who named *nothing*
    rather than one who named a target the older way.

    **Whether a seat is a target at all is the spec's answer, not this
    function's.** "…among any number of **target creatures**" (Fire Covenant,
    Pyrokinesis) and "…among all creatures target opponent controls" (Dwarven
    Catapult) name no player, so a `target_player_index` on one of those is the
    seat every cast carries rather than a target — read through the same
    ``creatures_only`` / ``land_filter`` narrowing ``legality._enumerate_targets``
    consults before it offers a face, so the gate and the picker cannot
    disagree about what a legal target is.
    """
    named = len([pid for pid in (target_permanent_ids or []) if isinstance(pid, int)])
    if isinstance(target_permanent_index, list):
        named += len([i for i in target_permanent_index if isinstance(i, int)])
    elif isinstance(target_permanent_index, int):
        named += 1
    if named or target_player_index is None:
        return named
    spec = derive_cast_spec(
        card, compile_card_oracle(card), from_zone=from_zone
    ) or {}
    if spec.get("creatures_only") or spec.get("land_filter"):
        return 0
    return 1


def _x_mana_actually_spent(
    allocation: dict[str, int], cost: dict[str, int]
) -> dict[str, int]:
    """The allocation, clamped to what the *reduced* cost really charged.

    A coloured cost reduction (CR 118.7b, "this spell costs {B} less to cast")
    comes off a flat symbol dict in which the printed {B} pip and a black mana
    put on X are the same entry, so the rules do not say which half of it the
    reduction takes. The caster would take it off the pip, keeping as much black
    on X as they can — which is exactly this clamp: X's share is whatever the
    cost still charges in that colour, up to what was allocated to X.

    Nothing is inflated. An over-reported symbol is life gained for mana nobody
    spent, and "not more than the amount of {B} spent on X" is a limit that must
    never err upward.
    """
    return {
        symbol: min(count, cost.get(symbol, 0))
        for symbol, count in allocation.items()
        if min(count, cost.get(symbol, 0)) > 0
    }


class SpellCastingMixin:
    def cast_from_hand(
        self,
        caster_index: int,
        card_name: str,
        target_player_index: int | None = None,
        target_permanent_index: int | None = None,
        # The chosen targets' stable ids, when the caller already knows them.
        # A pair of targets may sit on two battlefields, which one
        # `target_player_index` cannot express — see `_stack_push`.
        target_permanent_ids: list[int | None] | None = None,
        x_value: int | None = None,
        new_color: str | None = None,
        target_stack_index: int | None = None,
        mode_index: int | None = None,
        # "Choose one **or more** —" (Sublime Epiphany). Every chosen mode, with
        # each one's own targets: a list of dicts shaped like ``ChosenMode``'s
        # fields (``index`` plus optional ``target_player_index`` /
        # ``target_permanent_index`` / ``target_stack_index``). None or one entry
        # behaves exactly as ``mode_index`` alone always has.
        mode_choices: list[dict] | None = None,
        old_color: str | None = None,
        divided_targets: list[tuple[int, int | None]] | None = None,
        from_zone: str = "hand",
        use_free_permission: bool | None = None,
        # Which permanent / which card in hand pays a printed additional cost
        # (CR 601.2b). The same shape `activate_permanent_ability` takes, and
        # for the same reason: the payer chooses, a cost is paid *during*
        # casting, and a queued prompt would put the spell on the stack before
        # its cost was collected. A seat that names neither gets the
        # deterministic pick, which keeps AI and headless play unblocked.
        cost_permanent_index: int | None = None,
        cost_hand_index: int | None = None,
        # CR 118.9's choice, forwarded whole for the reason the cost fields
        # above are: dropping it here would resolve the spell having quietly
        # paid the mana cost the caller said they were replacing.
        alternative_cost: bool | None = None,
        alternative_cost_hand_index: int | None = None,
        # CR 601.2b's *optional* additional cost, and how many times each offer
        # was taken: ``{"{1}{R}": 2, "{1}{G}": 1}``. Announced with the cast for
        # the reason every other cost choice here is — 601.2b is one step, and a
        # queued prompt would put the spell on the stack before its price was
        # known. Absent means the offers were declined, which is what an
        # *optional* cost means and the only default that cannot overcharge.
        optional_cost_payments: dict[str, int] | None = None,
    ) -> SimulationResult:
        queued = self.queue_from_hand(
            caster_index,
            card_name,
            target_player_index=target_player_index,
            target_permanent_index=target_permanent_index,
            target_permanent_ids=target_permanent_ids,
            x_value=x_value,
            new_color=new_color,
            target_stack_index=target_stack_index,
            mode_index=mode_index,
            mode_choices=mode_choices,
            old_color=old_color,
            divided_targets=divided_targets,
            from_zone=from_zone,
            use_free_permission=use_free_permission,
            cost_permanent_index=cost_permanent_index,
            cost_hand_index=cost_hand_index,
            alternative_cost=alternative_cost,
            alternative_cost_hand_index=alternative_cost_hand_index,
            optional_cost_payments=optional_cost_payments,
        )
        if not queued.supported:
            return queued

        # Resolve the spell, then drain any triggers it (or the deaths it causes)
        # put on the stack, interleaving state-based-action checks (CR 704.3/603.3).
        self._settle()
        self.clear_priority_window()
        return SimulationResult(queued.card_name, True, queued.effect_kind, "resolved")
    def _arm_opponent_mode_choice(self, caster_index: int, card, spell_item) -> None:
        """CR 700.2e: hand the mode choice to a player other than the caster.

        Nothing is armed for an ordinary modal spell — the caster already named
        its mode as part of the announcement — so this is a no-op for every card
        but the three that print the head.

        **Which opponent** is the caster's choice when there is more than one
        (CR 700.2e's second sentence), and this takes the first living one
        instead of asking. That is a decision the engine does not model yet and
        it is recorded as such rather than hidden: in a duel, the rule's
        "if there is more than one" clause never applies and the seat is the
        only opponent there is.
        """
        program = compile_card_oracle(card)
        if program.mode_chooser is None or not program.modes:
            return
        chooser = next(
            (
                seat for seat in self.opponents_of(caster_index)
                if not self.players[seat].lost
            ),
            None,
        )
        if chooser is None:
            # CR 700.2e names a player who has to exist; with none left the
            # spell has nobody to ask and the first printed mode stands, which
            # is the same stated policy the non-interactive default takes.
            from ...game_types import ChosenMode

            spell_item.chosen_mode_index = 0
            spell_item.chosen_modes = (ChosenMode(index=0),)
            return
        self.arm_pending_choice(
            "opponent_mode_choice", chooser,
            card_name=card.name,
            labels=[mode.label for mode in program.modes],
            _item=spell_item,
        )
        self.log.append(
            f"{self.players[chooser].name} chooses a mode for {card.name}"
        )

    def arm_modal_mode_targets(self, spell_item, chooser_seat: int) -> None:
        """CR 601.2c for a mode somebody else chose (CR 700.2e).

        The rules order is modes (601.2b) then targets (601.2c), and for these
        spells the two belong to different players — so the caster cannot name a
        target while casting: they do not yet know which mode they are naming it
        for, and a mode the opponent then declines to pick would have published
        the caster's intentions for nothing.

        So the targets are asked for *after* the answer, and the prompt is armed
        by that answer. The spell is on the stack by then, which is a departure
        from the rules' internal order and not from anything observable:
        `opponent_mode_choice` and this prompt both block every seat, so no
        player has had priority between CR 601.2i and this — the whole
        announcement is still one uninterruptible moment.

        The picker is the one `legality._enumerate_targets` builds for every
        other spell, with the chooser's seat supplied beside the
        ``that_player_only`` flag the mode's own noun phrase produced ("up to
        two target creatures **that player** controls"). Nothing else can supply
        it: the seat came into existence when the mode was chosen.

        A mode that targets nothing arms nothing, which is every mode of every
        other card that prints this head.
        """
        from ...targeting import _from_instructions

        program = compile_card_oracle(spell_item.card)
        index = spell_item.chosen_mode_index
        if index is None or not 0 <= index < len(program.modes):
            return
        instruction = program.modes[index].instruction
        if instruction is None:
            return
        spec = _from_instructions((instruction,))
        if spec is None:
            return
        if spec.get("that_player_only"):
            spec = {**spec, "that_player_index": chooser_seat}
        candidates = self._enumerate_targets(
            spell_item.caster_index, spell_item.card, spec, for_cast=True,
        )
        offered = []
        for candidate in candidates:
            if candidate.get("kind") != "permanent":
                continue
            perm = self.permanent_at(candidate["seat"], candidate["index"])
            if perm is None:
                continue
            offered.append({
                "seat": candidate["seat"],
                "permanent_index": candidate["index"],
                "permanent_id": perm.permanent_id,
                "name": perm.card.name,
            })
        if not offered:
            # CR 601.2c names as many targets as the spell requires and no more.
            # "**Up to** two" requires none, so a board with nothing to destroy
            # is a legal announcement and not a refusal — the mode simply
            # destroys nothing. A mode with a *mandatory* target and no legal
            # one could not have been chosen at all (CR 700.2a), which is a
            # gate on the choice rather than on this prompt; no card in the pool
            # prints one, and the refusal it would need is named in ROADMAP.md.
            self.log.append(
                f"{spell_item.card.name}: the chosen mode has no legal target"
            )
            return
        self.arm_pending_choice(
            "modal_mode_targets", spell_item.caster_index,
            card_name=spell_item.card.name,
            mode_label=program.modes[index].label,
            targets=offered,
            max_targets=int(spec.get("max_targets") or 1),
            _item=spell_item,
        )

    def _resolve_chosen_modes(
        self, card, mode_choices: list[dict] | None
    ) -> tuple[tuple, str | None]:
        """The ``ChosenMode`` list for this cast, or a refusal naming the fault.

        CR 601.2b: the modes are chosen as the spell is cast, and how many is
        what the head printed. Three things are checked, because each is a way a
        caller could otherwise get a spell the card does not describe:

        * a card whose head is not "one **or more**" gets at most one mode —
          otherwise any modal spell would perform every bullet;
        * every index names a real mode of *this* card;
        * no mode is chosen twice (CR 700.2d: the same mode may be chosen again
          only if the card says so, and none in this pool does).

        The list comes back in **printed** order whatever order it arrived in,
        because that is the order the modes resolve in (CR 608.2c) — sorting
        once here is what lets the resolution loop be a loop rather than a sort.
        """
        from ...game_types import ChosenMode

        program = compile_card_oracle(card)
        # "**An opponent** chooses one —" (CR 700.2e). The choice is made at the
        # same moment (CR 601.2b) but by somebody else, so an announcement that
        # names a mode is not a legal announcement — it is the caster taking the
        # half of the card that suits them, which on all three cards printing
        # this head is the opposite of what the card does. Refused rather than
        # ignored: a dropped mode choice is a client quietly getting a different
        # spell from the one it asked for.
        if program.mode_chooser is not None:
            if mode_choices:
                return (), (
                    f"{card.name}: an opponent chooses this spell's mode"
                )
            return (), None
        if not mode_choices:
            return (), None
        if not program.modes:
            return (), f"{card.name} has no modes to choose"
        if len(mode_choices) > 1 and not program.modes_at_least:
            return (), f"{card.name} chooses one mode, not {len(mode_choices)}"
        seen: set[int] = set()
        chosen: list[ChosenMode] = []
        for entry in mode_choices:
            index = entry.get("index")
            if not isinstance(index, int) or not 0 <= index < len(program.modes):
                return (), f"{card.name}: no mode {index!r}"
            if index in seen:
                return (), f"{card.name}: mode {index} was chosen twice"
            seen.add(index)
            stack_index = entry.get("target_stack_index")
            stack_item = (
                self.stack[stack_index]
                if isinstance(stack_index, int) and 0 <= stack_index < len(self.stack)
                else None
            )
            chosen.append(ChosenMode(
                index=index,
                target_player_index=entry.get("target_player_index"),
                target_permanent_index=entry.get("target_permanent_index"),
                target_stack_item=stack_item,
            ))
        chosen.sort(key=lambda mode: mode.index)
        return tuple(chosen), None

    def queue_from_hand(self, *args, **kwargs) -> SimulationResult:
        """Cast a spell — CR 601, start to finish — leaving it on the stack.

        A wrapper around the whole process for one reason, and the reason is the
        wrapper's shape: **everything CR 601.2 describes is one announcement**,
        and a trigger that fires part-way through it waits for the end of that
        announcement rather than going on the stack in the middle. Goremand
        sacrifices a creature to be cast; Havoc Jester's answer to that belongs
        *above* the Demon, not under it. See ``deferring_triggers``.
        """
        with self.deferring_triggers():
            return self._cast_onto_stack(*args, **kwargs)

    def _cast_onto_stack(
        self,
        caster_index: int,
        card_name: str,
        target_player_index: int | None = None,
        target_permanent_index: int | None = None,
        # The chosen targets' stable ids, when the caller already knows them.
        # A pair of targets may sit on two battlefields, which one
        # `target_player_index` cannot express — see `_stack_push`.
        target_permanent_ids: list[int | None] | None = None,
        x_value: int | None = None,
        new_color: str | None = None,
        target_stack_index: int | None = None,
        mode_index: int | None = None,
        # "Choose one **or more** —" (Sublime Epiphany). Every chosen mode, with
        # each one's own targets: a list of dicts shaped like ``ChosenMode``'s
        # fields (``index`` plus optional ``target_player_index`` /
        # ``target_permanent_index`` / ``target_stack_index``). None or one entry
        # behaves exactly as ``mode_index`` alone always has.
        mode_choices: list[dict] | None = None,
        old_color: str | None = None,
        divided_targets: list[tuple[int, int | None]] | None = None,
        from_zone: str = "hand",
        use_free_permission: bool | None = None,
        # Which permanent / which card in hand pays a printed additional cost
        # (CR 601.2b). The same shape `activate_permanent_ability` takes, and
        # for the same reason: the payer chooses, a cost is paid *during*
        # casting, and a queued prompt would put the spell on the stack before
        # its cost was collected. A seat that names neither gets the
        # deterministic pick, which keeps AI and headless play unblocked.
        cost_permanent_index: int | None = None,
        cost_hand_index: int | None = None,
        # CR 118.9's choice: whether to pay the spell's printed *alternative*
        # cost rather than its mana cost, and which card in hand pays the exile
        # half of it. Announced with the cast for the reason the additional
        # costs' choices are (CR 601.2b announces both, before targets and long
        # before payment), and defaulting to None — "pay the mana cost" — because
        # CR 118.9b makes an alternative cost optional and a default that took
        # it would cast every Force of Will for a life and a card.
        alternative_cost: bool | None = None,
        alternative_cost_hand_index: int | None = None,
        # CR 601.2b's *optional* additional cost, and how many times each offer
        # was taken: ``{"{1}{R}": 2, "{1}{G}": 1}``. Announced with the cast for
        # the reason every other cost choice here is — 601.2b is one step, and a
        # queued prompt would put the spell on the stack before its price was
        # known. Absent means the offers were declined, which is what an
        # *optional* cost means and the only default that cannot overcharge.
        optional_cost_payments: dict[str, int] | None = None,
    ) -> SimulationResult:
        caster = self.players[caster_index]
        # Casting from the hand is a rule; casting from anywhere else is an
        # effect (CR 601.3), asked of the permission seam. The lookup prefers a
        # covered occurrence so a duplicate without permission cannot shadow
        # the copy that has it.
        permission = None
        if from_zone == "hand":
            source_zone = caster.hand
            # A card in hand can be *held* and not playable — Firestorm Phoenix
            # returns itself "revealed in their hand and can't play it" until
            # its owner's next turn. The lookup asks for the first copy that may
            # be played rather than the first copy at all, the same preference
            # the permission lookup below makes and for the same reason: two
            # copies of one card are indistinguishable, so a restriction on one
            # of them is a restriction on how *many* may be played.
            hand_index = playable_hand_index(self, caster_index, card_name)
            if hand_index is None:
                if not any(card.name == card_name for card in caster.hand):
                    raise ValueError(f"Card not in hand: {card_name}")
                denial = hand_lock_reason(self, caster_index, card_name) or (
                    f"{card_name} can't be played"
                )
                self.log.append(denial)
                return SimulationResult(card_name, False, None, denial)
        elif from_zone == "command":
            # CR 903.8 is a *rule*, not an effect: "a player may cast a
            # commander they own from the command zone". So it needs no
            # CastPermission — the permission seam is CR 601.3's "an effect
            # allows it", and asking it here would refuse the one cast the rules
            # themselves grant. What it does need is the ownership test, which
            # is the whole of the rule's restriction.
            source_zone = caster.command_zone
            hand_index = next(
                (i for i, card in enumerate(source_zone) if card.name == card_name), None
            )
            if hand_index is None:
                raise ValueError(f"Card not in command zone: {card_name}")
            if not self.may_cast_from_command_zone(caster_index, source_zone[hand_index]):
                details = (
                    f"{card_name} is not {caster.name}'s commander and cannot be cast "
                    f"from the command zone (CR 903.8)"
                )
                self.log.append(details)
                return SimulationResult(
                    card_name, False,
                    classify_card(source_zone[hand_index]).effect_kind, details,
                )
        else:
            if from_zone not in ("graveyard", "exile"):
                raise ValueError(f"cannot cast from {from_zone!r}")
            source_zone = getattr(caster, from_zone)
            hand_index = None
            for i, candidate in enumerate(source_zone):
                if candidate.name != card_name:
                    continue
                if hand_index is None:
                    hand_index = i
                grant = permission_for(
                    self, caster_index, candidate, from_zone,
                    as_land=candidate.primary_type == "land",
                )
                if grant is not None:
                    hand_index, permission = i, grant
                    break
            if hand_index is None:
                raise ValueError(f"Card not in {from_zone}: {card_name}")
            if permission is None:
                details = (
                    f"no effect allows playing {card_name} from "
                    f"{caster.name}'s {from_zone} (CR 601.3)"
                )
                self.log.append(details)
                return SimulationResult(
                    card_name, False,
                    classify_card(source_zone[hand_index]).effect_kind, details,
                )

        card = source_zone[hand_index]
        classification = classify_card(card)
        extra_generic_tax = 0
        # The *coloured* half of the same taxes (Derelor's "{B}"). Its own
        # total because it is its own resource: a generic pip is payable with
        # anything and a coloured one is not (CR 202.1), so the two cannot
        # share a number without the tax becoming cheaper than the card.
        extra_pip_tax: dict[str, int] = {}

        if self.enforce_mana_costs and card.primary_type == "land":
            refusal = self._land_play_refusal(caster_index)
            if refusal is not None:
                details = refusal
                self.log.append(details)
                return SimulationResult(card.name, False, classification.effect_kind, details)

        banning_card = self._set_lockout_banning_card(card)
        if banning_card is not None:
            details = f"can't cast or play {card.name}: banned by {banning_card}"
            self.log.append(details)
            return SimulationResult(card.name, False, classification.effect_kind, details)

        # "Enchanted creature's controller can't cast creature spells."
        # (Brand of Ill Omen.) A restriction imposed on a *player* by something
        # on the battlefield rather than a timing gate the spell prints about
        # itself, which is why it is asked here beside the lockout above and not
        # through `check_cast_timing` — that reader looks at the casting card's
        # own oracle text, and this sentence is on a card the caster may not
        # even control.
        forbidding_aura = controller_cast_ban(self, caster_index, card)
        if forbidding_aura is not None:
            details = f"can't cast {card.name}: {forbidding_aura}"
            self.log.append(details)
            return SimulationResult(card.name, False, classification.effect_kind, details)

        # "Creature spells can't be cast." (Aether Storm.) The same CR 601.3a
        # prohibition with no seat in the sentence, so it is asked of every
        # battlefield and binds the enchantment's own controller too. Beside the
        # Aura ban above rather than folded into it: what differs is the scope,
        # and the two sentences say it in different words.
        forbidding_permanent = global_cast_ban(self, card)
        if forbidding_permanent is not None:
            details = f"can't cast {card.name}: {forbidding_permanent}"
            self.log.append(details)
            return SimulationResult(card.name, False, classification.effect_kind, details)

        # "Spells with the chosen names can't be cast **and lands with the
        # chosen names can't be played**." (Null Chamber.) The same CR 601.3a
        # prohibition keyed on what a card is *called* rather than on its type,
        # and one gate for both halves of the printed sentence: playing a land
        # reaches this function too, and the land-drop refusal above is behind
        # `enforce_mana_costs` while a prohibition is not.
        naming_permanent = chosen_name_ban(self, card)
        if naming_permanent is not None:
            details = f"can't play {card.name}: {naming_permanent}"
            self.log.append(details)
            return SimulationResult(card.name, False, classification.effect_kind, details)

        # What the spell points at, computed once: both taxes whose scope is
        # "that target this creature" need it, and the mana one is charged at
        # CR 601.2f while the life one is charged at 601.2h — the same fact,
        # asked at two moments.
        aimed_at = [
            found
            for found in (
                self.permanent_by_id(pid)
                for pid in (target_permanent_ids or [])
                if isinstance(pid, int)
            )
            if found is not None
        ]
        if not aimed_at and target_permanent_index is not None:
            found = self.permanent_at(
                target_player_index
                if target_player_index is not None else caster_index,
                target_permanent_index,
            )
            if found is not None:
                aimed_at = [found]

        spell_tax, taxing_names = spell_cost_tax(self, caster_index, card, aimed_at)
        if spell_tax:
            extra_generic_tax += spell_tax
            self.log.append(f"{card.name} is taxed by {', '.join(taxing_names)}")

        # "Black spells you cast cost {B} more to cast." (Derelor.) Charged
        # beside the generic tax and at the same moment (CR 601.2f), into the
        # coloured part of the cost — so a caster with only Forests cannot pay
        # it, which is the whole difference between this and a {1}.
        pip_tax, pip_taxing_names = spell_symbol_tax(
            self, caster_index, card, aimed_at
        )
        if pip_tax:
            for symbol, count in pip_tax.items():
                extra_pip_tax[symbol] = extra_pip_tax.get(symbol, 0) + count
            self.log.append(
                f"{card.name} is taxed by {', '.join(pip_taxing_names)}"
            )

        # CR 903.8: the commander tax, {2} per previous cast of this commander
        # from the command zone. An additional cost like any other (CR 601.2f),
        # so it joins the same generic total rather than getting a payment path
        # of its own — which is what makes it interact correctly with the cost
        # increases above and with a cost reduction below.
        if from_zone == "command":
            commander_tax = self.commander_tax(caster_index, card)
            if commander_tax:
                extra_generic_tax += commander_tax
                self.log.append(
                    f"{card.name} costs an additional {{{commander_tax}}} "
                    f"(CR 903.8: commander tax)"
                )

        # "…that target this creature cost an additional 3 life to cast."
        # (Terror of the Peaks.) A tax in life rather than mana, scoped to what
        # the spell *targets* — so it is charged here, where the chosen targets
        # are known (CR 601.2c chooses them before 601.2h pays), and refused
        # rather than clamped when the caster cannot pay: CR 119.4 caps the
        # payment at the payer's life total and CR 601.2h makes an
        # unpayable cost an uncastable spell, not a free one.
        life_tax, life_taxing_names = spell_life_tax(self, caster_index, aimed_at)
        if life_tax:
            if caster.life < life_tax:
                details = (
                    f"{caster.name} cannot pay {life_tax} life to cast {card.name} "
                    f"({', '.join(life_taxing_names)})"
                )
                self.log.append(details)
                return SimulationResult(
                    card.name, False, classification.effect_kind, details
                )
            caster.life -= life_tax
            self.log.append(
                f"{caster.name} paid {life_tax} life to cast {card.name} "
                f"({', '.join(life_taxing_names)})"
            )

        # CR 601.2f: increases first, then reductions.
        cost_reduction, reducing_names = cost_reduction_for_cast(self, caster_index, card)
        if cost_reduction:
            self.log.append(f"{card.name} costs less to cast ({', '.join(reducing_names)})")

        # Accept cards with supported triggered abilities (match classifier logic)
        if not classification.supported:
            if classification.reason == "unsupported triggered ability":
                # `compile_card_oracle` is imported at module level. The
                # function-level `from .oracle import ...` that stood here
                # resolved to `engine.mixins.stack.oracle`, which does not
                # exist — a leftover from the stack decomposition that raised
                # ModuleNotFoundError on every card reaching this branch.
                # Nothing caught it because it is only reachable for an
                # *unsupported* card, and every card in the pool was supported
                # until M21 arrived with 33 of them.
                program = compile_card_oracle(card)
                if any(getattr(program, "triggered_abilities", ())):
                    if any(t.supported for t in program.triggered_abilities):
                        return SimulationResult(card.name, True, program.effect_kind, "supported triggered ability")
            self.log.append(f"Unsupported card: {card.name} ({classification.reason})")
            return SimulationResult(card.name, False, classification.effect_kind, classification.reason)

        timing_denial = check_cast_timing(self, caster_index, card.oracle_text.lower())
        if timing_denial is not None:
            self.log.append(timing_denial)
            return SimulationResult(card.name, False, classification.effect_kind, timing_denial)

        # A printed additional cost (CR 601.2b). Only the costs this *zone*
        # charges: Demonic Embrace prints one card with two prices —
        # {1}{B}{B} from the hand and {1}{B}{B} plus 3 life plus a card from the
        # graveyard — so a cost naming a zone applies to that zone alone, and
        # an unmarked cost ("as an additional cost to cast this spell") applies
        # wherever the spell is cast from.
        #
        # Gathered here and *checked* below, once X has been announced. See the
        # gate's own note for why the check moved.
        cast_costs = tuple(
            cost for cost in additional_costs(card)
            if cost.from_zone is None or cost.from_zone == from_zone
        )

        # CR 601.2b's optional additional costs, announced now and folded into
        # the mana below. **Not** part of `_unpayable_additional_cost`: an offer
        # is not a price, so declining one cannot make a spell uncastable, and
        # taking one past what the pool holds is refused by the mana payment
        # itself — which is where CR 601.2h puts an unpayable mana cost, and
        # which spends nothing on the way to refusing.
        optional_paid, optional_denial = _optional_cost_announcement(
            card, cast_costs, optional_cost_payments,
        )
        if optional_denial is not None:
            self.log.append(optional_denial)
            return SimulationResult(
                card.name, False, classification.effect_kind, optional_denial,
            )
        for offer, times in _optional_cost_totals(cast_costs, optional_paid):
            for symbol, count in offer.cost.items():
                if symbol == "generic":
                    extra_generic_tax += count * times
                else:
                    extra_pip_tax[symbol] = (
                        extra_pip_tax.get(symbol, 0) + count * times
                    )

        # Resolve the named discard **here**, while `cost_hand_index` still
        # indexes the hand the caster was looking at. The spell leaves that hand
        # further down, and every card after it slides up a slot — so an index
        # read afterwards names the neighbour, and one past the shortened end
        # fell through to a bare `0` and discarded the *first* card in hand. A
        # cast that names a card it cannot pay with is refused rather than
        # silently repointed, before any mana is spent.
        cost_hand_card, cost_denial = self._resolve_discard_cost_card(
            caster_index, card, cast_costs,
            cost_hand_index=cost_hand_index,
            spell_hand_index=hand_index if from_zone == "hand" else None,
        )
        if cost_denial is not None:
            self.log.append(cost_denial)
            return SimulationResult(card.name, False, classification.effect_kind, cost_denial)

        # The **alternative** cost (CR 118.9), announced in the same step as the
        # additional costs above (CR 601.2b) and resolved here for the same
        # reason the discard is: the card that pays it is named by an index into
        # the hand the caster is looking at, and that hand still holds the spell.
        # A cast that names a card it cannot pay with is refused before anything
        # is spent, never repointed at a neighbour.
        chosen_alternative, alternative_card, alternative_denial = (
            self._resolve_alternative_cost(
                caster_index, card,
                taking_it=alternative_cost,
                named_hand_index=alternative_cost_hand_index,
                spell_hand_index=hand_index if from_zone == "hand" else None,
            )
        )
        if alternative_denial is not None:
            self.log.append(alternative_denial)
            return SimulationResult(
                card.name, False, classification.effect_kind, alternative_denial
            )

        # "Choose one or more —": the modes are chosen as the spell is cast
        # (CR 601.2b) and are checked here, before any mana leaves the pool, so
        # a card that does not print the head cannot be handed two modes.
        chosen_modes, mode_denial = self._resolve_chosen_modes(card, mode_choices)
        if mode_denial is not None:
            self.log.append(mode_denial)
            return SimulationResult(card.name, False, classification.effect_kind, mode_denial)
        if chosen_modes:
            # Everything that reads one mode reads the first chosen one
            # (CR 608.2c resolves them in printed order, and the list is held in
            # that order), so a single-mode reader sees a mode this spell really
            # has rather than None.
            mode_index = chosen_modes[0].index

        # Resolve an explicitly chosen target spell on the stack (Counterspell,
        # Fork). target_stack_index indexes into self.stack (bottom-first).
        target_stack_item = None
        if target_stack_index is not None and 0 <= target_stack_index < len(self.stack):
            target_stack_item = self.stack[target_stack_index]

        target_ok, target_reason = self._validate_cast_targets(
            card, caster_index, target_player_index, target_permanent_index, target_stack_item,
            mode_index=mode_index, x_value=x_value,
            target_permanent_ids=target_permanent_ids,
        )
        if not target_ok:
            self.log.append(target_reason)
            return SimulationResult(card.name, False, classification.effect_kind, target_reason)

        # CR 601.2c for the target the caller *named*, beside the per-kind arms
        # above rather than inside them: a spell whose primary instruction is a
        # `sequence` wrapper reaches no arm at all, so "Destroy target artifact.
        # You gain life equal to its mana value" could be cast on a Grizzly
        # Bears — the destroy then found nothing and the life was gained anyway.
        # Still before any mana leaves the pool.
        named_refusal = self.cast_target_refusal(
            caster_index, card,
            target_player_index=target_player_index,
            target_permanent_index=target_permanent_index,
            target_permanent_ids=target_permanent_ids,
            from_zone=from_zone,
            # CR 601.2b is announced above; CR 601.2c's target count follows
            # from it for a spell that prints "for each additional <cost> you
            # paid, … another target …". The gate is the only reader that can
            # see both announcements at once.
            optional_cost_payments=optional_paid,
        )
        if named_refusal is not None:
            self.log.append(named_refusal)
            return SimulationResult(card.name, False, classification.effect_kind, named_refusal)

        # A divided spell's cross-seat target list: sanity-check every entry so a
        # stale battlefield index can't crash resolution.
        if divided_targets is not None:
            cleaned: list[tuple] = []
            for entry in divided_targets:
                seat, index, share = divided_entry(entry)
                if not (isinstance(seat, int) and 0 <= seat < len(self.players)):
                    return SimulationResult(card.name, False, classification.effect_kind, "invalid divided target seat")
                if index is not None and not (
                    isinstance(index, int) and 0 <= index < len(self.players[seat].battlefield)
                ):
                    return SimulationResult(card.name, False, classification.effect_kind, "invalid divided target")
                # The two-tuple is kept where no share was announced: it is what
                # every evenly-divided spell and every non-interactive caller
                # sends, and normalizing it to a three-tuple would say a
                # division was announced when none was.
                cleaned.append((seat, index) if share is None else (seat, index, share))
            divided_targets = cleaned or None

        # Fireball-style spells cost {1} more to cast for each target beyond the
        # first. Count the chosen targets (the cross-seat divided list, a list of
        # creature indices, or a single creature/player) and tax the extras as
        # generic mana.
        if "costs {1} more to cast for each target beyond the first" in card.oracle_text.lower():
            if divided_targets is not None:
                num_targets = len(divided_targets)
            elif isinstance(target_permanent_index, list):
                num_targets = len([i for i in target_permanent_index if isinstance(i, int)])
            else:
                num_targets = 1
            extra_generic_tax += max(0, num_targets - 1)

        x_colors = x_spend_colors_from_text(card.oracle_text)
        # What the payment below actually put on X, per colour. Empty until
        # then, and legitimately empty afterwards for a waived cast (CR
        # 107.3b locks a waived X to 0) or a game not enforcing costs.
        x_mana_spent: dict[str, int] = {}
        resolved_x_value = x_value
        # CR 107.3c: some spells define X themselves, and then the caster does
        # not announce it — the definition wins over anything the wire sent, the
        # way it does for an activated ability's cost one table over. A card
        # that defines an X this cast cannot compute refuses, because the
        # alternative is letting the caster pick a number the card fixed.
        if defines_cast_x(card.oracle_text):
            defined = cast_x_value(self, caster_index, card.oracle_text)
            if defined is None:
                refusal = f"{card.name}: X cannot be determined for this cast"
                self.log.append(refusal)
                return SimulationResult(
                    card.name, False, classification.effect_kind, refusal,
                )
            resolved_x_value = defined
        if resolved_x_value is None and "{X}" in card.mana_cost.upper():
            # "…with mana value X" (Spell Blast, Detonate). The target and the X
            # are announced together (CR 601.2b before 601.2c), and only one X
            # makes the pair legal — so a caster who named the target and not the
            # number named the number too. Inferring from the mana pool instead
            # produced a legal cast that then did nothing, which is a spell
            # spending its cost on the wrong value rather than on a choice.
            resolved_x_value = self._x_implied_by_target(
                card, target_player_index, target_permanent_index, target_stack_item,
            )
        if resolved_x_value is None and "{X}" in card.mana_cost.upper():
            resolved_x_value = self._infer_x_value(
                caster, card.mana_cost, extra_generic_tax, x_colors=x_colors,
                reduction=cost_reduction, extra_pips=extra_pip_tax,
            )

        # CR 601.2b's *bound*: "X can't be greater than the number of snow
        # lands you control." (Winter's Chill.) Unlike a definition the caster
        # still announces X, so this is checked against whatever they announced
        # — after the inference above, which is where an unstated X becomes a
        # number, and before any cost is paid so CR 601.2e can return the game
        # to the moment before an illegal proposal. A bound the board cannot be
        # counted for refuses too, for the definition's reason one block up:
        # the alternative is announcing past a limit the card prints.
        if caps_cast_x(card.oracle_text):
            bound = cast_x_ceiling(self, caster_index, card.oracle_text)
            if bound is None or int(resolved_x_value or 0) > bound[0]:
                allowed = "none" if bound is None else str(bound[0])
                printed = "" if bound is None else f" ({bound[1]})"
                refusal = (
                    f"{card.name}: X can't be greater than {allowed}{printed}"
                )
                self.log.append(refusal)
                return SimulationResult(
                    card.name, False, classification.effect_kind, refusal,
                )

        # CR 601.2d, after X is announced (601.2b) and before any cost is paid:
        # the division is part of *proposing* the spell, and CR 601.2e returns
        # the game to the moment before a proposal that turns out to be illegal.
        # Below the X resolution because a division of X cannot be measured
        # until X is a number — the same ordering CR 601.2 puts them in, and the
        # same lesson Fire Covenant's "pay X life" taught the cost gate below.
        #
        # **Asked of every divided spell, not only of one that announced a
        # division.** The gate used to run under `if divided_targets is not
        # None`, so a caster who announced *nothing* — no division, no target —
        # walked past it: Contagion and Bounty of the Hunt were castable with
        # both battlefields empty, and Spoils of War, shipped, with them.
        # CR 601.2d divides "among one or more targets", so that is an illegal
        # proposal, and the refusal has to be here rather than at resolution
        # because CR 601.2e returns the game to before a proposal and a
        # resolution-time answer would already have spent the mana.
        found = divided_description(compile_card_oracle(card).instructions)
        if found is not None:
            refusal = division_refusal(
                _divided_total(found[0], resolved_x_value),
                divided_targets or (),
                division=found[1].get("division", EVENLY),
                max_targets=found[1].get("max_targets"),
                named_targets=_named_divided_targets(
                    card, from_zone, target_player_index,
                    target_permanent_index, target_permanent_ids,
                ),
            )
            if refusal is not None:
                self.log.append(f"{card.name}: {refusal}")
                return SimulationResult(
                    card.name, False, classification.effect_kind, refusal,
                )

        # The printed additional costs, checked now: CR 601.2h says an unpayable
        # cost can't be paid, and the consequence is that the spell can't be
        # cast at all — not that it is cast for free, which is what happened
        # while the phrase lived in the spell-pattern whitelist.
        #
        # **Here** rather than beside the gathering above, and the move is the
        # whole of Fire Covenant's fix: "pay X life" cannot be measured until X
        # is announced (CR 601.2b, CR 107.3), and the gate used to run first —
        # so the clause was left out of the cost table entirely and the card,
        # already `supported` on its damage line, was cast for nothing. This is
        # also where CR 601.2 puts the check: 601.2h is after 601.2b's
        # announcements and 601.2c's targets, and nothing between the two
        # positions spends anything, so a refusal here costs the caster exactly
        # what a refusal above it did.
        unpayable = self._unpayable_additional_cost(
            caster_index, card, cast_costs, spell_hand_index=hand_index,
            from_zone=from_zone, x_value=resolved_x_value,
        )
        if unpayable is not None:
            self.log.append(unpayable)
            return SimulationResult(card.name, False, classification.effect_kind, unpayable)

        # The announced alternative cost, checked in the same step and for the
        # same rule (CR 601.2h). Below the additional costs only in source
        # order; nothing between the two spends anything, so a refusal from
        # either costs the caster the same nothing.
        unpayable = self._unpayable_alternative_cost(
            caster_index, card, chosen_alternative,
            spell_hand_index=hand_index if from_zone == "hand" else None,
        )
        if unpayable is not None:
            self.log.append(unpayable)
            return SimulationResult(card.name, False, classification.effect_kind, unpayable)

        # "Spells cost an additional "Sacrifice a Swamp" to cast for each black
        # mana symbol in their mana costs." (Drought.) An additional cost
        # imposed from a *board* rather than printed on the spell, so it is
        # asked here beside the printed ones and at the same moment (CR 601.2f
        # determines it, CR 601.2h pays it), and refused rather than clamped:
        # CR 601.2h makes an unpayable cost an uncastable spell, not a free one.
        sacrifice_demands = sacrifice_taxes(
            self, caster_index, card.mana_cost or "", "cast"
        )
        owed = self._sacrifice_tax_victims(caster_index, sacrifice_demands)
        if isinstance(owed, str):
            details = f"{card.name} can't be cast: {owed} (CR 601.2h)"
            self.log.append(details)
            return SimulationResult(card.name, False, classification.effect_kind, details)

        # A cost waiver ("cast spells from your hand without paying their mana
        # costs", Chandra, Flame's Catalyst's −8). An X spell defaults to
        # *paying*, because a waived {X} is locked to 0 (CR 107.3b) and paying
        # for X=5 usually beats a free X=0 — an explicit request wins either way.
        free_grant = permission if (permission is not None and permission.free) else None
        if (
            free_grant is None
            and card.primary_type != "land"
            and use_free_permission is not False
            and (use_free_permission or "{X}" not in card.mana_cost.upper())
            # CR 118.9a: "A player can't apply two alternative methods of
            # casting or two alternative costs to a single spell." A cost waiver
            # is an alternative cost (`CastPermission.free` cites the same rule),
            # so a caster who announced the spell's own printed one is not also
            # handed a waiver — which would otherwise make the printed cost a
            # pure loss, paid on top of a spell that was already free.
            and chosen_alternative is None
        ):
            waiver = permission_for(self, caster_index, card, "hand")
            if waiver is not None and from_zone == "hand":
                free_grant = waiver
                if permission is None:
                    permission = waiver
        if chosen_alternative is not None and card.primary_type != "land":
            # CR 118.9: the alternative cost is paid **rather than** the mana
            # cost, so the mana payment below is skipped whole. Not a reduction
            # and not a waiver: the cost itself is charged just below, once the
            # spell is off the hand, beside the additional costs CR 118.9d keeps
            # in force.
            #
            # CR 118.9c is what this branch does *not* do: nothing here touches
            # `card.mana_cost`, so the taxes above, the commander tax and every
            # "with mana value X" reader still see the printed cost.
            if "{X}" in card.mana_cost.upper():
                # CR 107.3b: X is 0 when neither the mana cost nor an
                # alternative cost that includes X is paid. No card in the pool
                # prints both an {X} and an alternative cost; this is the rule's
                # answer rather than a guess at one.
                resolved_x_value = 0
            self.log.append(
                f"{card.name} cast for its alternative cost "
                f"({chosen_alternative.describe()})"
            )
        elif free_grant is not None and card.primary_type != "land":
            if "{X}" in card.mana_cost.upper():
                resolved_x_value = 0  # CR 107.3b: the only legal choice for X
            self.log.append(
                f"{card.name} cast without paying its mana cost"
                + (f" ({free_grant.source_name})" if free_grant.source_name else "")
            )
        elif self.enforce_mana_costs and card.primary_type != "land":
            # CR 118.6: an object with no mana cost (as opposed to {0}) has an
            # unpayable cost — attempting to cast it is illegal. (118.6a: a
            # waiver above is an alternative cost and may still be paid.)
            if not card.mana_cost.strip():
                details = f"{card.name} has no mana cost; the cost is unpayable (CR 118.6)"
                self.log.append(details)
                return SimulationResult(card.name, False, classification.effect_kind, details)
            x_mana_spent = self._pay_cast_cost(
                caster, card, resolved_x_value, x_colors,
                extra_generic=extra_generic_tax, reduction=cost_reduction,
                extra_pips=extra_pip_tax,
            )
            if x_mana_spent is None:
                details = f"insufficient mana for {card.name}"
                if x_colors:
                    spelling = " and/or ".join(f"{{{sym}}}" for sym in x_colors)
                    details = (
                        f"insufficient mana for {card.name} "
                        f"(X can be paid only with {spelling} mana)"
                    )
                self.log.append(details)
                return SimulationResult(card.name, False, classification.effect_kind, details)

        card = source_zone.pop(hand_index)
        # Now, and not before: the spell is no longer in the hand, so it cannot
        # be discarded to pay for itself, and the creature it eats is gone from
        # the battlefield before the spell is on the stack.
        # CR 118.9d keeps the additional costs in force alongside an
        # alternative one, so both are paid, in the order CR 601.2h leaves free.
        self._pay_alternative_cost(
            caster_index, card, chosen_alternative, alternative_card,
        )
        cost_spoils = self._pay_additional_costs(
            caster_index, card, cast_costs,
            cost_permanent_index=cost_permanent_index,
            cost_hand_card=cost_hand_card,
            x_value=resolved_x_value,
        )
        sacrificed_for_cost = cost_spoils["sacrificed_for_cost"]
        exiled_for_cost = cost_spoils["exiled_for_cost"]
        # Drought's imposed sacrifices, paid with the printed ones and at the
        # same moment. The victims were picked before the mana was spent, so a
        # board that has not changed since pays exactly what the gate measured.
        self._pay_sacrifice_tax(owed, f"to cast {card.name}")
        if permission is not None:
            consume_permission(self, permission, card)
        if from_zone == "command":
            # CR 903.8's "each previous time" is counted once the cast is
            # announced and paid for, so the tax charged above is the one this
            # cast owed and the next one is {2} higher. A cast that failed
            # anywhere above returned before here and costs nothing.
            self.record_commander_cast(caster_index, card)
        if from_zone != "hand":
            self.log.append(f"{card.name} cast from {caster.name}'s {from_zone}")

        if card.primary_type != "land":
            # Determine which stack spell this one targets. An explicit choice
            # (target_stack_item) wins; otherwise fall back to the topmost legal
            # spell so AI and untargeted casts still work.
            target_stack_item_val = target_stack_item
            if target_stack_item_val is None and self.stack and "counter target" in card.oracle_text.lower():
                color_match = re.search(r"counter target (\w+) spell", card.oracle_text.lower())
                color_filter: str | None = None
                if color_match:
                    color_filter = _COLOR_WORD_TO_SYMBOL.get(color_match.group(1))
                matching = [it for it in self.stack if not color_filter or color_filter in it.card.colors]
                if matching:
                    target_stack_item_val = matching[-1]
            spell_item = StackItem(
                    card=card,
                    caster_index=caster_index,
                    target_player_index=target_player_index,
                    target_permanent_index=target_permanent_index,
                    target_permanent_id=target_permanent_ids,
                    x_value=resolved_x_value,
                    target_stack_item=target_stack_item_val,
                    chosen_mode_index=mode_index,
                    chosen_modes=chosen_modes,
                    cast_from_zone=from_zone,
                    exile_instead_of_graveyard=bool(
                        permission is not None and permission.exile_instead
                    ),
                    choices={
                        "divided_targets": divided_targets,
                        "new_color": new_color,
                        "old_color": old_color,
                        # What the additional cost ate, for the spell whose
                        # effect asks about it ("…equal to the sacrificed
                        # creature's mana value"). The Permanent is off the
                        # battlefield by now, so this is last-known information
                        # (CR 608.2h) held on the stack item rather than a
                        # second lookup that could not succeed.
                        # How many times each CR 601.2b optional additional
                        # cost was taken. The pool is empty by resolution
                        # (CR 500.4) and the spell is on the stack, so nothing
                        # in the game state can answer "for each additional
                        # {1}{R} you paid" — this is where the announcement
                        # survives, beside the other costs' spoils and for the
                        # same reason.
                        "additional_costs_paid": optional_paid,
                        "sacrificed_for_cost": sacrificed_for_cost,
                        # …and what an *exile* cost ate, on the channel the
                        # activation path already records it on. Last-known
                        # information for the same reason (CR 608.2h): the
                        # permanent left the battlefield before the spell was
                        # on the stack, so nothing on the board can be asked
                        # what it was.
                        "exiled_for_cost": exiled_for_cost,
                        # CR 601.2h's answer to "the amount of {B} spent on X"
                        # (Soul Burn). Decided as the cost was built rather than
                        # measured as a pool delta afterwards: this card costs
                        # {X}{2}{B}, so a black unit missing from the pool may
                        # have paid the mandatory pip, the generic {2} or X, and
                        # a delta cannot tell those apart. The allocation is the
                        # cost, so the number is exact.
                        "x_mana_spent": x_mana_spent,
                        # "If you cast it any time a sorcery couldn't have been
                        # cast, …" (Mirage's five flash Auras). Answered *here*
                        # because here is the only moment it can be: CR 601.3d's
                        # timing is about the game state as the spell is
                        # announced, and by resolution the stack has emptied
                        # down to this spell and the step may have moved on.
                        # Stamped only for a card whose text asks — see
                        # `cast_permissions`, whose whole rider this feeds.
                        CAST_AT_INSTANT_SPEED: (
                            sacrifices_at_cleanup_if_cast_at_instant_speed(
                                card.oracle_text or ""
                            )
                            and not a_sorcery_could_be_cast(self, caster_index)
                        ),
                    },
            )
            self._stack_push(spell_item)
            self.log.append(f"{card.name} added to stack")
            # "Whenever a player casts a [color] spell" triggers (Rod/Cup/Sphere)
            # and "whenever you cast an X spell" triggers (Verduran Enchantress)
            # fire now, as the spell is put on the stack, and go on the stack above
            # it (CR 603.3) — so the trigger resolves while the triggering spell is
            # still on the stack, not after it has already resolved.
            # The record every ordinal reads — "you've cast an instant or
            # sorcery spell this turn" (Stormwing Entity), "their second spell
            # each turn" (Mangara), "other than the first instant spell that
            # player casts each turn" (Ichneumon Druid). CR 601.2i finishes the
            # casting before anything can respond, so the spell is on the list
            # before *any* of the announcements below, not just the ones that
            # used to follow it: it was appended inside `_apply_cast_triggers`,
            # which runs second, so an opponent-scoped ordinal counted a list
            # missing the very spell that fired it and every such trigger was
            # one cast late.
            if 0 <= caster_index < len(self.players):
                self.players[caster_index].spells_cast_this_turn.append(card)
            # The same record, by the identity that list cannot carry: a
            # `CardDefinition` is shared by every copy in every deck, so two
            # casts of one sorcery are one entry there and two here. Backdraft's
            # "one of those sorcery spells" is a choice **between** them.
            record_cast(self, spell_item)
            self._apply_spell_cast_any_triggers(
                caster_index, card, from_zone, item=spell_item
            )
            self._apply_cast_triggers(caster_index, card)
            # "An opponent chooses one —" (CR 700.2e): the other player chooses
            # "when the spell's controller normally would", which is CR 601.2b.
            # Armed here rather than earlier because CR 601.2i finishes the
            # casting first — the spell is on the stack and the cast triggers
            # are announced, and the prompt holds priority, so nobody acts
            # between the two. A non-interactive chooser takes the default where
            # this stands (`default_at_arm`), which is what keeps AI and
            # headless play from stopping on a decision nobody will make.
            self._arm_opponent_mode_choice(caster_index, card, spell_item)
            return SimulationResult(card.name, True, classification.effect_kind, "queued")

        self._resolve_card(
            caster_index=caster_index,
            card=card,
            classification=classification,
            target_player_index=target_player_index,
            target_permanent_index=target_permanent_index,
            x_value=resolved_x_value,
            choices=dict(cost_spoils),
        )
        return SimulationResult(card.name, True, classification.effect_kind, "resolved")
    # ------------------------------------------------------------------
    # Printed additional costs (CR 601.2b)
    # ------------------------------------------------------------------

    def _additional_cost_candidates(
        self, caster_index: int, cost: AdditionalCost, *, giving_up: str = "sacrifice",
    ) -> list[Permanent]:
        """The permanents that could pay *cost*'s sacrifice or exile, by identity.

        Never by index: an index would be held across the removal that paying
        performs, and would then name whichever permanent slid into the slot.

        One enumeration for both verbs, because they ask one question — which
        permanents on the payer's own battlefield the printed noun phrase names
        (CR 601.2b). What differs is where the object goes afterwards, which is
        the payment's business and not the candidate list's.
        """
        described = (
            cost.sacrifice_filter if giving_up == "sacrifice" else cost.exile_filter
        )
        if described is None:
            return []
        return [
            perm
            for perm in self.controlled_by(caster_index)
            # The observer is the payer: "a creature **you control**" is a
            # seat comparison, and a payload carrying one with no observer to
            # compare against refuses every candidate.
            if subject_matches(self, perm, described, observer=caster_index)
        ]

    def _sacrifice_tax_victims(
        self, payer_index: int, demands: tuple
    ) -> "list[Permanent] | str":
        """The permanents that will pay every imposed sacrifice, or the reason
        they cannot (CR 601.2h).

        Picked once, across *all* the demands together: two Droughts want two
        Swamps each and one Swamp cannot pay both, which is what asking each
        demand its own question would have said. The picks are removed from the
        pool as they are made, and the payer's own deterministic order is the
        one every other sacrifice cost uses.

        Shared by the cast path and the activation path, because CR 601.2b and
        CR 602.2b are the same announcement step — the same reason
        ``AdditionalCost.sacrifice_filter`` is one vocabulary.
        """
        chosen: list[Permanent] = []
        for demand in demands:
            for _ in range(demand.count):
                available = [
                    perm
                    for perm in self.controlled_by(payer_index)
                    if subject_matches(
                        self, perm, demand.described, observer=payer_index
                    )
                    and not any(taken is perm for taken in chosen)
                ]
                if not available:
                    return (
                        f"no {demand.noun.title()} left to sacrifice for "
                        f"{demand.source_name}"
                    )
                chosen.append(self.default_sacrifice_pick(available))
        return chosen

    def _pay_sacrifice_tax(self, victims: "list[Permanent]", why: str) -> None:
        """Sacrifice what ``_sacrifice_tax_victims`` picked. By identity, never
        by slot: each removal renumbers the battlefield behind it."""
        for victim in victims:
            name = victim.card.name
            if self.sacrifice_permanent(victim) is not None:
                self.log.append(f"{name} was sacrificed {why}")

    def _unpayable_additional_cost(
        self,
        caster_index: int,
        card: CardDefinition,
        costs: tuple[AdditionalCost, ...],
        *,
        spell_hand_index: int | None,
        from_zone: str,
        x_value: int | None = None,
    ) -> str | None:
        """Why *card*'s printed additional costs can't be paid, or None.

        CR 601.2h: "Unpayable costs can't be paid" — and CR 601.2 makes the
        whole casting a rewind, so the answer is that the spell is not cast,
        never that it is cast without the cost. Asked before any mana leaves the
        pool, so a refusal costs the caster nothing.

        *x_value* is the announced X (CR 601.2b), for the one cost whose amount
        is not printed: Fire Covenant's "pay X life". It reaches both this and
        the payment through ``AdditionalCost.life_charged``, so the gate and the
        charge cannot come to disagree about the number.
        """
        caster = self.players[caster_index]
        for cost in costs:
            if cost.sacrifice_filter is not None:
                if not self._additional_cost_candidates(caster_index, cost):
                    return (
                        f"{card.name} can't be cast: no "
                        f"{filter_head_noun(cost.sacrifice_filter)} to "
                        f"sacrifice for its additional cost (CR 601.2h)"
                    )
            # "…, **exile a creature you control**." (Soul Exchange.) Gated
            # beside the sacrifice and for the same rule: CR 601.2h makes an
            # unpayable cost an uncastable spell, never a free one.
            if cost.exile_filter is not None:
                if not self._additional_cost_candidates(
                    caster_index, cost, giving_up="exile"
                ):
                    return (
                        f"{card.name} can't be cast: no "
                        f"{filter_head_noun(cost.exile_filter)} to "
                        f"exile for its additional cost (CR 601.2h)"
                    )
            # CR 119.4: a player may pay life only down to 0, and CR 601.2h then
            # makes an unpayable cost an uncastable spell rather than a free
            # one. Checked with the others, before anything is spent.
            life = cost.life_charged(x_value)
            if life and caster.life < life:
                return (
                    f"{card.name} can't be cast: {caster.name} cannot pay "
                    f"{life} life with {caster.life} remaining "
                    f"(CR 601.2h)"
                )
            if cost.discard_cards:
                # The spell itself is still in the zone it is being cast from,
                # and it is about to be on the stack — so it cannot be one of
                # the cards discarded to pay for itself.
                #
                # Counted over the cards the printed phrase *names* rather than
                # over the whole hand ("discard a **red or green** card", Surge
                # of Strength), through the same matcher the payment picks with
                # — a gate that counted the hand would admit a cast the payment
                # then could not collect, and the payment would fall back to
                # discarding whatever was first.
                payable = self._discard_cost_payers(
                    caster_index, cost,
                    spell_hand_index=(
                        spell_hand_index if from_zone == "hand" else None
                    ),
                )
                if len(payable) < cost.discard_cards:
                    shortfall = (
                        "no card in hand answers this cost"
                        if cost.discard_filters
                        else "not enough cards in hand to discard"
                    )
                    return (
                        f"{card.name} can't be cast: {shortfall} "
                        f"for its additional cost (CR 601.2h)"
                    )
        return None

    def _discard_cost_payers(
        self,
        caster_index: int,
        cost: AdditionalCost,
        *,
        spell_hand_index: int | None,
    ) -> list["CardDefinition"]:
        """The cards in hand that may pay *cost*'s discard, in hand order.

        One enumeration for the gate, the named-card check and the payment, so
        what is admitted and what is collected cannot disagree — the same
        arrangement ``_additional_cost_candidates`` makes for the sacrifice and
        the exile one zone over. The narrowing is read through
        ``card_matches_any``, which is what the activation path's identical
        discard cost is matched with (CR 601.2b and CR 602.2b are one
        announcement step).

        The spell is excluded **by index**, never by identity: a deck repeats
        one immutable ``CardDefinition`` per copy, so a second copy of the spell
        in hand is the *same object* and an identity filter would refuse the
        card that may legitimately pay.
        """
        return [
            held
            for position, held in enumerate(self.players[caster_index].hand)
            if position != spell_hand_index
            and card_matches_any(held, cost.discard_filters)
        ]

    def _resolve_discard_cost_card(
        self,
        caster_index: int,
        card: CardDefinition,
        costs: tuple[AdditionalCost, ...],
        *,
        cost_hand_index: int | None,
        spell_hand_index: int | None,
    ) -> tuple["CardDefinition | None", str | None]:
        """The card a named ``cost_hand_index`` picks, or why it picks none.

        CR 601.2b's choices are announced while the spell is still being cast,
        so the index is into the hand the caster can see — the one that still
        holds the spell. Resolving it to a *card* here is what makes the answer
        survive the spell leaving that hand: an index is only meaningful
        alongside the list it was read from, which is the instability this
        engine addresses with ids on the battlefield and cannot here, because a
        hand holds ``CardDefinition``s and two copies of a card are one object.

        The spell itself is refused: CR 601.2a puts it on the stack before its
        costs are paid, so it is not in the hand to be discarded. Nothing named
        means the deterministic default, which keeps AI and headless play
        unblocked.
        """
        discarding = next((cost for cost in costs if cost.discard_cards), None)
        if cost_hand_index is None or discarding is None:
            return None, None
        hand = self.players[caster_index].hand
        if not 0 <= cost_hand_index < len(hand):
            return None, (
                f"{card.name} can't be cast: no card at hand position "
                f"{cost_hand_index} to discard for its additional cost"
            )
        if cost_hand_index == spell_hand_index:
            return None, (
                f"{card.name} can't be cast: it is on the stack (CR 601.2a) and "
                "cannot be discarded to pay for itself"
            )
        # A named card that does not answer the printed phrase is an error, not
        # a cheaper cost — refused rather than quietly slid onto a legal one,
        # which is the same answer the activation path gives the identical cost.
        if not card_matches_any(hand[cost_hand_index], discarding.discard_filters):
            return None, (
                f"{card.name} can't be cast: {hand[cost_hand_index].name} does "
                f"not answer its additional cost (CR 601.2b)"
            )
        return hand[cost_hand_index], None

    # ------------------------------------------------------------------
    # The printed alternative cost (CR 118.9)
    # ------------------------------------------------------------------

    def _alternative_cost_payers(
        self,
        caster_index: int,
        cost: AlternativeCost,
        *,
        spell_hand_index: int | None,
    ) -> list["CardDefinition"]:
        """The cards in hand that could pay *cost*'s exile, in hand order.

        One enumeration for the gate, the named-card check and the payment, the
        arrangement ``_discard_cost_payers`` and ``_additional_cost_candidates``
        both make and for the same reason: a gate that counted a different set
        from the one the payment picks from would admit a cast the payment
        cannot collect.

        The spell is withheld **by index**, never by identity. CR 601.2a puts it
        on the stack before costs are paid, so it cannot pay for itself — but a
        *second copy* in hand is a different card that legitimately can, and a
        deck repeats one immutable ``CardDefinition`` per copy, so an identity
        filter would refuse it along with the spell.
        """
        return [
            held
            for position, held in enumerate(self.players[caster_index].hand)
            if position != spell_hand_index
            and card_matches_any(held, cost.exile_from_hand or ())
        ]

    def _resolve_alternative_cost(
        self,
        caster_index: int,
        card: CardDefinition,
        *,
        taking_it: bool | None,
        named_hand_index: int | None,
        spell_hand_index: int | None,
    ) -> "tuple[AlternativeCost | None, CardDefinition | None, str | None]":
        """CR 601.2b's announcement: ``(cost taken, card that pays it, refusal)``.

        Three answers rather than a boolean, because the announcement decides
        three things at once and every one of them has to survive the spell
        leaving the hand: *which* alternative cost is being paid (CR 118.9a
        allows one), *which card* pays its exile half (an index is only
        meaningful beside the list it was read from, so it is resolved to a card
        here), and whether the announcement is legal at all.

        ``taking_it`` is None for "pay the mana cost", which is the default and
        the behaviour every caller had before this existed. CR 118.9b makes an
        alternative cost optional, so nothing is inferred: a caster who did not
        ask pays the printed cost even when they could not afford it, because the
        alternative is the engine spending a life total the player never offered.

        The affordability question is **not** asked here. It belongs beside the
        additional costs' gate at CR 601.2h, after X and the targets are
        announced, and asking it twice would be two answers to one question.
        """
        printed = alternative_costs(card)
        if not taking_it:
            return None, None, None
        if not printed:
            return None, None, (
                f"{card.name} can't be cast that way: it prints no alternative "
                f"cost (CR 118.9)"
            )
        if len(printed) > 1:
            # CR 118.9a: only one alternative cost may be applied. No card in
            # the pool prints two, so rather than invent a choice nobody has to
            # make, the cast is refused and names the rule — a silent "take the
            # first" would be this engine picking which price the player pays.
            return None, None, (
                f"{card.name} prints more than one alternative cost and only "
                f"one may be applied (CR 118.9a)"
            )
        cost = printed[0]
        if cost.exile_from_hand is None:
            return cost, None, None
        payable = self._alternative_cost_payers(
            caster_index, cost, spell_hand_index=spell_hand_index
        )
        if named_hand_index is None:
            # Nothing named is the deterministic default, which keeps AI and
            # headless play unblocked — the same answer every other cost choice
            # on this path gives. An empty list is not a refusal here: the gate
            # at CR 601.2h says so, in one place, with the rule's own wording.
            return cost, (payable[0] if payable else None), None
        hand = self.players[caster_index].hand
        if not 0 <= named_hand_index < len(hand):
            return None, None, (
                f"{card.name} can't be cast: no card at hand position "
                f"{named_hand_index} to exile for its alternative cost"
            )
        if named_hand_index == spell_hand_index:
            return None, None, (
                f"{card.name} can't be cast: it is on the stack (CR 601.2a) and "
                "cannot be exiled to pay for itself"
            )
        if not any(held is hand[named_hand_index] for held in payable):
            # A named card that does not answer the printed phrase is an error,
            # not a cheaper cost: refused rather than quietly slid onto a legal
            # one, so a stale click cannot exile the card the player meant to
            # keep. The same answer the discard cost beside it gives.
            return None, None, (
                f"{card.name} can't be cast: {hand[named_hand_index].name} does "
                f"not answer its alternative cost (CR 118.9)"
            )
        return cost, hand[named_hand_index], None

    def _unpayable_alternative_cost(
        self,
        caster_index: int,
        card: CardDefinition,
        cost: "AlternativeCost | None",
        *,
        spell_hand_index: int | None,
    ) -> str | None:
        """Why the announced alternative cost can't be paid, or None.

        CR 601.2h: "Unpayable costs can't be paid", and CR 601.2e makes the
        whole casting a rewind — so the answer is that the spell is not cast,
        never that it is cast without the cost. Which for an *alternative* cost
        is the sharper version of the same rule: a dropped additional cost is a
        spell cast for less than it prints, and a dropped alternative cost is a
        spell cast for **nothing at all**, because the mana payment has already
        been replaced by whatever this was supposed to collect.

        Asked beside ``_unpayable_additional_cost`` and at the same moment, so a
        refusal here costs the caster exactly what a refusal there does: nothing.
        """
        if cost is None:
            return None
        caster = self.players[caster_index]
        # CR 119.4: a player may pay life only down to 0.
        if cost.pay_life and caster.life < cost.pay_life:
            return (
                f"{card.name} can't be cast: {caster.name} cannot pay "
                f"{cost.pay_life} life with {caster.life} remaining (CR 601.2h)"
            )
        if cost.exile_from_hand is not None and not self._alternative_cost_payers(
            caster_index, cost, spell_hand_index=spell_hand_index
        ):
            return (
                f"{card.name} can't be cast: no card in hand answers its "
                f"alternative cost, {cost.describe()} (CR 601.2h)"
            )
        return None

    def _pay_alternative_cost(
        self,
        caster_index: int,
        card: CardDefinition,
        cost: "AlternativeCost | None",
        chosen: "CardDefinition | None",
    ) -> None:
        """Perform the announced alternative cost (CR 601.2h).

        Called once the spell is off the hand and on the stack (CR 601.2a), so
        the spell itself cannot pay and a second copy of it still can — which is
        the whole reason the *choice* was resolved to a card upstream while the
        index still meant something.

        The card leaves through ``Game.take_card_from_hand``: a deck repeats one
        immutable ``CardDefinition`` per copy, so every copy in a hand is the
        same Python object and the obvious identity filter would exile all of
        them while this puts exactly one into exile.
        """
        if cost is None:
            return
        caster = self.players[caster_index]
        if cost.pay_life:
            caster.life -= cost.pay_life
            self.log.append(
                f"{caster.name} paid {cost.pay_life} life to cast {card.name}"
            )
        if cost.exile_from_hand is None:
            return
        paying = chosen
        if paying is None or not any(held is paying for held in caster.hand):
            # The announcement's pick is re-checked rather than trusted: a hand
            # that changed between announcement and payment is a board this
            # engine cannot rewind, and re-picking is the honest half-step.
            paying = next(
                (
                    held for held in caster.hand
                    if card_matches_any(held, cost.exile_from_hand)
                ),
                None,
            )
        if paying is None:
            return  # gated above; a hand that changed since is a no-op
        self.take_card_from_hand(caster, paying)
        caster.exile.append(paying)
        self.log.append(
            f"{caster.name} exiled {paying.name} to cast {card.name}"
        )

    def _pay_additional_costs(
        self,
        caster_index: int,
        card: CardDefinition,
        costs: tuple[AdditionalCost, ...],
        *,
        cost_permanent_index: int | None,
        cost_hand_card: "CardDefinition | None",
        x_value: int | None = None,
    ) -> dict:
        """Perform *card*'s printed additional costs, returning what they ate.

        A record rather than one permanent, keyed by the same channel names the
        activation path records its costs on (``sacrificed_for_cost``,
        ``exiled_for_cost``) — so a spell reading back what its cost consumed
        asks the same question whether a cast or an activation paid it. Soul
        Exchange's "if the exiled creature was a Thrull" is the first reader on
        the cast side.

        The payer chooses (CR 601.2b), and the choice arrives with the action
        rather than through the pending-choice queue — a queued prompt would put
        the spell on the stack before its cost was collected, which is the
        reasoning ``activate_permanent_ability`` already records for the
        identically-shaped activation costs. A seat that names nothing gets a
        deterministic pick so AI and headless play stay unblocked.
        """
        caster = self.players[caster_index]
        sacrificed: Permanent | None = None
        exiled: Permanent | None = None
        for cost in costs:
            # "…, **exile a creature you control**." (Soul Exchange.) Paid
            # before the sacrifice beside it only in source order; both are one
            # payment moment (CR 601.2h), and no card in the pool prints both.
            if cost.exile_filter is not None:
                candidates = self._additional_cost_candidates(
                    caster_index, cost, giving_up="exile"
                )
                if candidates:
                    named = (
                        self.permanent_at(caster, cost_permanent_index)
                        if isinstance(cost_permanent_index, int)
                        else None
                    )
                    # `in` compares Permanents by value and would match a
                    # look-alike; membership is by identity.
                    chosen = (
                        named
                        if any(perm is named for perm in candidates)
                        else self.default_sacrifice_pick(candidates)
                    )
                    owner_index = self.owner_index_of(chosen)
                    exiled_card = chosen.card
                    self.remove_from_battlefield(chosen)
                    self.players[
                        owner_index if owner_index is not None else caster_index
                    ].exile.append(exiled_card)
                    exiled = chosen
                    self.log.append(
                        f"{caster.name} exiled {exiled_card.name} to cast {card.name}"
                    )
            if cost.sacrifice_filter is not None:
                candidates = self._additional_cost_candidates(caster_index, cost)
                if not candidates:
                    continue  # gated above; a board that changed since is a no-op
                named = (
                    self.permanent_at(caster, cost_permanent_index)
                    if isinstance(cost_permanent_index, int)
                    else None
                )
                chosen = (
                    named
                    # `in` compares Permanents by value and would match a
                    # look-alike; membership is by identity.
                    if any(perm is named for perm in candidates)
                    else self.default_sacrifice_pick(candidates)
                )
                name = chosen.card.name
                if self.sacrifice_permanent(chosen) is not None:
                    sacrificed = chosen
                    self.log.append(
                        f"{caster.name} sacrificed {name} to cast {card.name}"
                    )
            life = cost.life_charged(x_value)
            if life:
                caster.life -= life
                self.log.append(
                    f"{caster.name} paid {life} life to cast {card.name}"
                )
            if cost.discard_cards:
                for _ in range(cost.discard_cards):
                    if not caster.hand:
                        break
                    # The chosen card was resolved before the spell left the
                    # hand; find it by identity now. Two copies of one card are
                    # the same object, which is fine — either pays the cost, and
                    # discarding "the first equal one" is the whole choice.
                    #
                    # The default is the first card the printed phrase *names*,
                    # never a bare index 0: "discard a red or green card" paid
                    # with the first card in hand is a different, cheaper cost.
                    # The spell has already left the hand by now (it is on the
                    # stack, CR 601.2a), so nothing needs excluding here.
                    index = next(
                        (
                            i for i, held in enumerate(caster.hand)
                            if card_matches_any(held, cost.discard_filters)
                        ),
                        None,
                    )
                    if index is None:
                        break  # gated above; a hand that changed since is a no-op
                    if cost_hand_card is not None:
                        index = next(
                            (
                                i for i, held in enumerate(caster.hand)
                                if held is cost_hand_card
                            ),
                            index,
                        )
                        cost_hand_card = None  # one named card pays once
                    discarded = caster.hand.pop(index)
                    self._discard_card(caster, discarded)
                    self.log.append(
                        f"{caster.name} discarded {discarded.name} to cast {card.name}"
                    )
                    # One named index pays one card; the rest take the default.
                    cost_hand_index = None
        return {"sacrificed_for_cost": sacrificed, "exiled_for_cost": exiled}

    def _x_implied_by_target(
        self, card, target_player_index, target_permanent_index, target_stack_item
    ) -> int | None:
        """The X a "with mana value X" spell's chosen target fixes, or None.

        None whenever the spell does not print that restriction, or no target
        was named — those are the ordinary cases and they fall through to the
        pool-based inference. The stack item is read first because a spell being
        countered is the only kind of target Spell Blast has; Detonate's is a
        permanent on some seat's battlefield.
        """
        if not targets_mana_value_x(compile_card_oracle(card).instructions):
            return None
        if target_stack_item is not None:
            return int(getattr(target_stack_item.card, "cmc", 0) or 0)
        if not isinstance(target_permanent_index, int):
            return None
        seat = target_player_index if target_player_index is not None else None
        if seat is None or not (0 <= seat < len(self.players)):
            return None
        chosen = self.permanent_at(self.players[seat], target_permanent_index)
        return None if chosen is None else int(getattr(chosen.card, "cmc", 0) or 0)

    def _destroy_target_legal(self, payload: dict, perm: Permanent) -> bool:
        """Whether *perm* satisfies a ``destroy_target_permanent`` instruction's
        target filters (type/subtype/colour/tapped + exclusions). Shared by cast
        validation and the legality enumerator so a destroy ability (Royal
        Assassin's "target tapped creature", Northern Paladin's "target black
        permanent") offers exactly the permanents it can legally destroy.

        Deliberately silent about "…with mana value X" (Detonate), which is the
        one restriction with no literal to test. The picker calls this before any
        X exists, and "X is not chosen yet" is not "no restriction" — it is
        *every* mana value still being reachable, since the caster announces the
        target and the X together (CR 601.2b, then 601.2c). Narrowing here would
        offer nothing at all; the pair is checked in `_validate_cast_targets`,
        where both halves are known.
        """
        return permanent_matches_filter(perm, payload)
    def _named_role_targets(
        self, caster_index: int, target_player_index, target_permanent_index,
        target_permanent_ids,
    ) -> list:
        """The permanents a roles announcement named, in role order.

        Ids first, exactly as the CR 702.16b loop below reads them, and for the
        same reason: the roles of one spell may sit on **two** battlefields - a
        Wall the defender controls and the attacker it blocked - so a list of
        slots against one ``target_seat`` cannot address them both. The index
        form is kept for a caller with one seat in hand (a test, the AI), and a
        slot that resolves to nothing stays None so the count check above sees a
        short announcement rather than a silently shifted one.
        """
        if target_permanent_ids:
            return [
                self.permanent_by_id(permanent_id) if permanent_id is not None else None
                for permanent_id in target_permanent_ids
            ]
        slots = (
            target_permanent_index
            if isinstance(target_permanent_index, list)
            else [target_permanent_index]
        )
        seat = (
            target_player_index if target_player_index is not None else caster_index
        )
        return [self.permanent_at(seat, slot) for slot in slots]

    def _validate_cast_targets(
        self,
        card: CardDefinition,
        caster_index: int,
        target_player_index: int | None,
        target_permanent_index: int | None = None,
        target_stack_item=None,
        mode_index: int | None = None,
        x_value: int | None = None,
        target_permanent_ids: list[int | None] | None = None,
    ) -> tuple[bool, str]:
        """Return (True, 'valid') if all required targets exist, else (False, reason).

        Only instants and sorceries execute effects at cast time; permanents enter
        the battlefield regardless of whether their activated abilities have targets.

        For a "Choose one —" modal spell, the chosen mode's instruction (not the
        first one) determines what the spell targets.
        """
        # Protection from this spell's *name* (Runed Halo, CR 702.16i): the
        # player can't be chosen as a target, which under CR 601.2c makes the
        # spell uncastable at them rather than ineffective. Asked of the chosen
        # player before the per-type checks below, because it applies whatever
        # the spell's type is.
        from ...named_protection import protected_from

        if (
            target_player_index is not None
            and 0 <= target_player_index < len(self.players)
            and protected_from(self, target_player_index, card)
        ):
            details = (
                f"{self.players[target_player_index].name} has protection from "
                f"{card.name}"
            )
            return False, details
        if card.primary_type not in ("instant", "sorcery"):
            # Aura spells are always targeted: a legal enchant target must be
            # chosen when the spell is cast (MTG Rules 115.1b, 601.2c)
            if "Aura" in card.type_line:
                enchant_noun = aura_enchant_noun(card)
                if enchant_noun is not None:
                    if not isinstance(target_permanent_index, int):
                        return False, f"{card.name} requires a target"
                    target_idx = target_player_index if target_player_index is not None else (1 - caster_index)
                    if target_idx < 0 or target_idx >= len(self.players):
                        target_idx = 1 - caster_index
                    # Resolved once, through the control seam, and then asked
                    # four questions. It was four subscripts of the same slot:
                    # the same permanent every time, so the repetition bought
                    # nothing and each copy was another positional read of a
                    # list whose indices move.
                    chosen = self.permanent_at(target_idx, target_permanent_index)
                    if chosen is None or not permanent_matches_enchant_noun(
                        chosen, enchant_noun
                    ):
                        return False, f"no valid target for {card.name}"
                    # "Enchant creature **you control**" (Cocoon), "Enchant
                    # artifact **an opponent controls**" (Relic Bind): the seat
                    # half of the clause, CR 601.2c — an illegal choice makes
                    # the spell uncastable, not merely ineffective.
                    if not enchant_seat_satisfied(
                        self, caster_index, self.controller_index_of(chosen), enchant_noun
                    ):
                        return False, (
                            f"{card.name} can only enchant {enchant_noun}"
                        )
                    # "You can't choose an untapped creature as this spell's
                    # target as you cast it." (Enthralling Hold.) CR 601.2c: an
                    # illegal choice makes the spell uncastable, not merely
                    # ineffective, so this refuses here rather than letting the
                    # Aura resolve and do nothing.
                    if forbidden_target(self, card, chosen, caster_index):
                        return False, (
                            f"{chosen.card.name} can't be chosen as "
                            f"{card.name}'s target"
                        )
                    # A permanent that "can't be enchanted by other Auras" (Consecrate
                    # Land) is an illegal target for any other Aura spell.
                    if self._cant_be_enchanted(chosen):
                        return False, f"{chosen.card.name} can't be enchanted by other Auras"
                    # CR 702.16b/c: an Aura with a quality can't be cast targeting a
                    # permanent with protection from that quality (or hexproof
                    # from an opponent's side, CR 702.11b).
                    if not self._can_be_targeted(
                        chosen, card, caster_index=caster_index
                    ):
                        return False, f"no valid target for {card.name}"
                else:
                    clause = aura_enchant_clause(card.oracle_text)
                    if clause is not None and "graveyard" in clause:
                        # e.g. "enchant creature card in a graveyard" (Animate Dead).
                        # If the player chose a specific graveyard card, validate that
                        # choice; otherwise require at least one legal creature card.
                        if isinstance(target_permanent_index, int):
                            gy_idx = target_player_index if target_player_index is not None else caster_index
                            if gy_idx < 0 or gy_idx >= len(self.players):
                                gy_idx = caster_index
                            graveyard = self.players[gy_idx].graveyard
                            if not (0 <= target_permanent_index < len(graveyard)) or (
                                graveyard[target_permanent_index].primary_type != "creature"
                            ):
                                return False, f"no valid target for {card.name}"
                        else:
                            has_target = any(
                                c.primary_type == "creature"
                                for player in self.players
                                for c in player.graveyard
                            )
                            if not has_target:
                                return False, f"no valid target for {card.name}"
            return True, "valid"

        program = compile_card_oracle(card)
        if (
            mode_index is not None
            and program.modes
            and 0 <= mode_index < len(program.modes)
            and program.modes[mode_index].instruction is not None
        ):
            primary = program.modes[mode_index].instruction
        else:
            primary = next(
                (instr for instr in program.instructions if instr.kind != "spell_pattern"),
                None,
            )
        if primary is None:
            return True, "valid"

        # CR 601.2c: the caster announces how many targets a variable-target
        # spell will have, and the maximum is what the card printed. The picker
        # and the AI both cap themselves, so this is the re-check of a number
        # they were *told* (idiom #9) — read from `derive_cast_spec`, the same
        # derivation that told them, so the cap and the prompt cannot disagree.
        # Fewer is legal, including none. Which permanents were named is not
        # checkable here: the slots are indices on one seat and a several-target
        # description may legitimately span two battlefields, so the identities
        # only exist as the ids on the stack item and the handler enforces them
        # there.
        #
        # Placed above the per-kind arms rather than in one: a card whose
        # `primary` is a `sequence` wrapper (Frost Breath) reaches none of them,
        # so a cast naming three targets was accepted and the handler silently
        # capped at two.
        announced = (
            len(target_permanent_index)
            if isinstance(target_permanent_index, list)
            else None
        )
        cast_spec = derive_cast_spec(card, program) or {}
        maximum = cast_spec.get("max_targets")
        if isinstance(maximum, int) and announced is not None and announced > maximum:
            return False, f"too many targets for {card.name}"

        # A spell naming several targets of **different kinds** (Glyph of
        # Delusion). Gated here, above every per-kind arm below, because none of
        # them can see the two facts that make such an announcement legal: the
        # later target's legality depends on the earlier one, and CR 601.2c
        # forbids naming one object twice. Both are asked through
        # ``role_target_options`` — the very call the picker was built from.
        #
        # Only a *complete* announcement is checked here, and that is what keeps
        # the enumeration behind it from recursing: the per-candidate probe
        # inside ``_enumerate_targets(for_cast=True)`` re-enters this function
        # with one slot, never a list.
        roles = spec_roles(cast_spec)
        if roles:
            chosen = self._named_role_targets(
                caster_index, target_player_index, target_permanent_index,
                target_permanent_ids,
            )
            if len(chosen) != len(roles):
                return False, f"{card.name} requires {len(roles)} targets"
            if not self._role_targets_legal(
                caster_index, card, cast_spec, chosen, for_cast=True
            ):
                return False, f"no valid target for {card.name}"
            return True, "valid"

        # "…with mana value X" (Spell Blast, Detonate). Here rather than in an
        # arm below, for the same reason the count check is: Detonate prints two
        # sentences, so its destroy is a step of a `sequence` and `primary` is
        # the wrapper. Only an X the caller *named* is checked — an unnamed one
        # was just derived from this very target, so comparing it would be the
        # engine checking its own arithmetic.
        if x_value is not None and targets_mana_value_x(program.instructions):
            implied = self._x_implied_by_target(
                card, target_player_index, target_permanent_index, target_stack_item,
            )
            if implied is not None and implied != int(x_value):
                return False, (
                    f"{card.name} targets an object with mana value X, and X={x_value} "
                    f"does not match {implied}"
                )

        target_idx = target_player_index if target_player_index is not None else (1 - caster_index)
        if target_idx < 0 or target_idx >= len(self.players):
            target_idx = 1 - caster_index
        target = self.players[target_idx]

        # CR 702.16b: a spell can't be cast targeting a creature with protection
        # from the spell's quality (or with shroud). Reject the illegal target at
        # cast time, mirroring the resolution-time check, so it is never offered.
        # Every chosen slot is checked, not just the first: a spell naming "up to
        # two target creatures" chooses each of them separately (CR 601.2c), and
        # one illegal choice makes the cast illegal however many others are fine.
        #
        # **Only where the slot is a battlefield slot.** A graveyard target's
        # index counts into a different list, and reading it here refused Raise
        # Dead over a White Knight the spell never named: CR 702.16b is about
        # the spell's own targets, and a card in a graveyard is not a permanent
        # (CR 115.2), so it has no protection to check in the first place.
        #
        # **The ids are read first, and that is a fix rather than a
        # convenience.** A caller may name its targets by stable id and leave
        # the slot out entirely — the addressing CLAUDE.md asks for, since an
        # index renumbers under anything that leaves — and this gate used to
        # look only at the slot. So `cast_from_hand(..., target_permanent_ids=
        # [...])` skipped CR 702.16b altogether: Drain Life was cast at a White
        # Knight it has protection from, and Tunnel destroyed a Wall of Shadows
        # that can't be its target. Nothing crashed, and the web layer never
        # showed it because `web/actions.py` resolves the ids to
        # `target_permanent_indices` and passes both — which is exactly the
        # shape of hazard this repo keeps naming: one caller's spelling
        # enforced, another's silently not.
        if graveyard_target_spec(card, program, mode_index=mode_index) is not None:
            chosen_targets: list = []
        elif target_permanent_ids:
            chosen_targets = [
                self.permanent_by_id(permanent_id)
                for permanent_id in target_permanent_ids
                if permanent_id is not None
            ]
        else:
            slots = (
                target_permanent_index
                if isinstance(target_permanent_index, list)
                else [target_permanent_index]
            )
            chosen_targets = [
                target.battlefield[slot]
                for slot in slots
                if isinstance(slot, int) and 0 <= slot < len(target.battlefield)
            ]
        for chosen in chosen_targets:
            if chosen is None:
                continue
            # **Every permanent, not every creature.** CR 115 is about objects,
            # and the `is_creature` test that stood here was true of every card
            # in the pool that had ever printed a targeting restriction — every
            # shroud, every protection, every "can't be the target of Aura
            # spells" sat on a creature or on an Aura enchanting one. Raiding
            # Party prints one on an *enchantment*, and the narrowing was
            # dropped: the picker offered it to Disenchant, the announcement was
            # allowed, and CR 608.2b caught it one step too late — the spell was
            # countered on resolution rather than being an illegal cast, so the
            # caster lost a card to an announcement CR 601.2c forbids.
            if not self._can_be_targeted(
                chosen, card, caster_index=caster_index
            ):
                return False, f"{chosen.card.name} is an illegal target for {card.name}"

        if primary.kind == "destroy_target_permanent":
            if isinstance(target_permanent_index, int):
                # A specific target was chosen — it must itself be legal (601.2c).
                battlefield = target.battlefield
                if not (0 <= target_permanent_index < len(battlefield)) or not self._destroy_target_legal(
                    primary.payload, battlefield[target_permanent_index]
                ):
                    return False, f"no valid target for {card.name}"
            else:
                # No specific choice: destruction can target a permanent controlled
                # by anyone, so a legal target on the caster's own battlefield (e.g.
                # Disenchant on one's own artifact) is enough to make the cast legal.
                has_target = any(
                    self._destroy_target_legal(primary.payload, p)
                    for p in self.all_permanents()
                )
                if not has_target:
                    return False, f"no valid target for {card.name}"

        elif primary.kind == "counter_top_stack_spell":
            color_filter = primary.payload.get("color_filter")
            if not self.stack:
                return False, f"no valid target for {card.name}"
            if target_stack_item is not None:
                # A specific spell was chosen — it must itself be a legal target.
                if target_stack_item not in self.stack:
                    return False, f"no valid target for {card.name}"
                if color_filter and color_filter not in self._stack_item_colors(target_stack_item):
                    return False, f"no valid target for {card.name}"
            elif color_filter and not any(color_filter in self._stack_item_colors(item) for item in self.stack):
                return False, f"no valid target for {card.name}"

        elif primary.kind == "bounce_target_creature":
            # "Return target <noun> to its owner's hand" can name a permanent
            # controlled by ANY player. **The noun is payload**: Unsummon prints
            # "creature", Boomerang "permanent", Flash Flood "Mountain", and the
            # instruction is the same one for all three — so what makes a chosen
            # slot legal is the filter the lowering carried, asked through the
            # same ``subject_matches`` the picker enumerates with and the handler
            # resolves with. Reading ``is_creature`` here was one card's printed
            # noun standing in for every card printing the sentence, and it is
            # the gate that would have refused Boomerang on a land the spell
            # legally targeted.
            bounce_filter = bounce_subject_filter(primary.payload)

            def _legal_bounce_target(perm) -> bool:
                return subject_matches(
                    self, perm, bounce_filter, observer=caster_index
                )

            if isinstance(target_permanent_index, int):
                chosen = self.permanent_at(target_idx, target_permanent_index)
                if chosen is None or not _legal_bounce_target(chosen):
                    return False, f"no valid target for {card.name}"
            elif not any(
                _legal_bounce_target(p) for p in self.all_permanents()
            ):
                return False, f"no valid target for {card.name}"

        elif primary.kind in (
            "pump_target_creature_until_eot",
            "grant_target_flying_until_eot",
            "grant_regeneration_to_target_creature",
            "berserk_pump",
            "grant_unlimited_blocking",
            "exile_target_creature_until_eot",
            "exile_creature_gain_life_equal_to_power",
        ):
            # These spells can target a creature controlled by ANY player (Death
            # Ward regenerates your own creature; Swords to Plowshares exiles any
            # creature). A specific choice must itself be a creature; otherwise any
            # creature on any battlefield makes the cast legal.
            blocking_only = bool(primary.payload.get("blocking_only"))

            def _legal_pump_target(p) -> bool:
                if not p.is_creature:
                    return False
                # Righteousness only targets a creature that is currently blocking.
                if blocking_only and not self._is_blocking_creature(p):
                    return False
                return True

            if isinstance(target_permanent_index, int):
                battlefield = target.battlefield
                if not (0 <= target_permanent_index < len(battlefield)) or not _legal_pump_target(
                    battlefield[target_permanent_index]
                ):
                    return False, f"no valid target for {card.name}"
            elif not any(_legal_pump_target(p) for p in self.all_permanents()):
                return False, f"no valid target for {card.name}"

        elif primary.kind in (
            "gain_control_of_target", "gain_control_until_eot",
        ):
            # "Gain control of target **nonartifact, nonblack** creature."
            # (Ritual of the Machine.) The printed narrowing rides the target
            # description, and this chain is where a cast-side narrowing is
            # enforced — ``derive_cast_spec`` reduces both these kinds to a bare
            # ``{"kind": "creature"}`` picker, exactly as it does for Terror,
            # and Terror's exclusions are honoured by *its* arm here rather than
            # by the spec. Without an arm the announcement was legal, the
            # additional sacrifice was paid, and the steal then found nothing at
            # resolution: a card lost to a cast CR 601.2c forbids.
            #
            # Asked through the same ``subject_matches`` the bounce arm above
            # uses, over the same description the handler re-checks with, so the
            # picker's enumeration (which probes through this method) and the
            # gate cannot disagree.
            if not primary.payload.get("permanents_from"):
                # The bound spelling (Disharmony, Ray of Command) chose nothing
                # at announcement: the object comes from an earlier step of the
                # same resolution, so there is no named target to check.
                steal_filter = (primary.payload.get("targets") or {}).get("filter") or {}

                def _legal_steal_target(perm) -> bool:
                    return subject_matches(
                        self, perm, steal_filter, observer=caster_index
                    )

                if isinstance(target_permanent_index, int):
                    chosen = self.permanent_at(target_idx, target_permanent_index)
                    if chosen is None or not _legal_steal_target(chosen):
                        return False, f"no valid target for {card.name}"
                elif not any(
                    _legal_steal_target(p) for p in self.all_permanents()
                ):
                    return False, f"no valid target for {card.name}"

        elif primary.kind in ("tap_target_permanent", "untap_target_permanent"):
            if not target.battlefield:
                return False, f"no valid target for {card.name}"

        elif primary.kind == "recolor_target_from_text":
            # "Target spell or permanent becomes [color]" (the Lace cards). A spell
            # on the stack is a legal target, as is any permanent on any battlefield.
            if target_stack_item is not None:
                if target_stack_item not in self.stack:
                    return False, f"no valid target for {card.name}"
            else:
                any_target = bool(self.stack) or any(p.battlefield for p in self.players)
                if not any_target:
                    return False, f"no valid target for {card.name}"

        elif primary.kind in (
            "return_creature_from_graveyard_to_hand",
            "reanimate_creature_to_battlefield",
            "reanimate_creature",
        ):
            # Raise Dead / Resurrection target a creature card in *your* graveyard,
            # so an opponent's graveyard is never a legal target. Regrowth targets
            # "target card" — any type (any_card in the parsed payload). Only
            # enforce the ownership/index check when the caster made an explicit
            # graveyard pick; an untargeted cast just needs a legal card there.
            #
            # **Whose graveyard is the payload's answer, not this arm's.** "Put
            # target creature card **from a graveyard** onto the battlefield"
            # (Hymn of Rebirth) lowers to ``any_graveyard``, and the handler
            # already reads the named seat's pile; this arm refused the seat
            # anyway, so the one card in the pool printing the phrase could not
            # be cast at a card in an opponent's graveyard at all. The seats
            # searched here are the same ones ``_enumerate_graveyard_creatures``
            # offers for the derived spec — the picker's list and the re-check
            # are one answer (idiom #9).
            caster = self.players[caster_index]
            any_graveyard = bool(primary.payload.get("any_graveyard"))
            sources = list(self.players) if any_graveyard else [caster]
            # The pile the caller pointed at: the named seat's when the phrase
            # reads any graveyard, the caster's own otherwise. Resolved once and
            # asked by both branches, because "whose graveyard" is one question
            # and two copies of the answer is how they come to disagree.
            wrong_seat = (
                not any_graveyard
                and target_player_index is not None
                and target_player_index != caster_index
            )
            named = (
                self.players[target_player_index]
                if any_graveyard
                and target_player_index is not None
                and 0 <= target_player_index < len(self.players)
                else caster
            )
            targets_desc = primary.payload.get("targets") or {}
            several = (
                isinstance(targets_desc, dict)
                and isinstance(targets_desc.get("count"), int)
                and targets_desc["count"] > 1
            )
            if several:
                # "Up to two target creature cards ...": CR 601.2c lets the
                # caster announce *zero* targets, so an empty graveyard is not a
                # reason to refuse the cast. What is refused is a named slot that
                # is not a legal choice - the picker's list is a hint and this is
                # the re-check (idiom #9).
                slots = (
                    target_permanent_index
                    if isinstance(target_permanent_index, list)
                    else ([] if target_permanent_index is None else [target_permanent_index])
                )
                if slots and wrong_seat:
                    return False, f"no valid target for {card.name}"
                if len(slots) > targets_desc["count"]:
                    return False, f"too many targets for {card.name}"
                for slot in slots:
                    if not isinstance(slot, int) or not (0 <= slot < len(named.graveyard)):
                        return False, f"no valid target for {card.name}"
                    if not graveyard_card_matches(primary.payload, named.graveyard[slot]):
                        return False, f"no valid target for {card.name}"
            elif isinstance(target_permanent_index, int):
                if wrong_seat:
                    return False, f"no valid target for {card.name}"
                if not (0 <= target_permanent_index < len(named.graveyard)) or (
                    not graveyard_card_matches(
                        primary.payload, named.graveyard[target_permanent_index]
                    )
                ):
                    return False, f"no valid target for {card.name}"
            elif not any(
                graveyard_card_matches(primary.payload, c)
                for player in sources
                for c in player.graveyard
            ):
                return False, f"no valid target for {card.name}"

        elif primary.kind == "simulacrum_redirect":
            # Simulacrum deals damage to "target creature you control" — only a
            # creature the caster controls is a legal target. A specific choice must
            # be one of the caster's creatures (targeting an opponent's creature is
            # illegal); with no explicit choice, the caster just needs one creature.
            caster = self.players[caster_index]
            if isinstance(target_permanent_index, int):
                if target_player_index is not None and target_player_index != caster_index:
                    return False, f"no valid target for {card.name}"
                battlefield = caster.battlefield
                if not (0 <= target_permanent_index < len(battlefield)) or (
                    not battlefield[target_permanent_index].is_creature
                ):
                    return False, f"no valid target for {card.name}"
            elif not any(p.is_creature for p in self.controlled_by(caster)):
                return False, f"no valid target for {card.name}"

        elif primary.kind == "copy_top_stack_spell":
            # Fork copies a target instant or sorcery spell, so it requires one on
            # the stack (excluding Fork itself, which isn't on the stack yet).
            if target_stack_item is not None:
                if target_stack_item not in self.stack or target_stack_item.card.primary_type not in ("instant", "sorcery"):
                    return False, f"no valid target for {card.name}"
            elif not any(item.card.primary_type in ("instant", "sorcery") for item in self.stack):
                return False, f"no valid target for {card.name}"

        return True, "valid"
    def _infer_x_value(
        self, player: PlayerState, mana_cost: str, extra_generic: int = 0,
        x_colors: tuple[str, ...] = (), reduction: CostReduction | None = None,
        extra_pips: dict[str, int] | None = None,
    ) -> int:
        # The reduction is applied before X is inferred, because X is whatever
        # is left after the rest of the cost is paid — inferring it from the
        # undiscounted cost would spend the discount on nothing.
        required = reduce_cost(
            self._parse_mana_cost(
                mana_cost, x_value=0, extra_generic=extra_generic,
                extra_pips=extra_pips,
            ),
            reduction or CostReduction(),
        )
        temp = {symbol: player.mana_pool.get(symbol, 0) for symbol in ("W", "U", "B", "R", "G", "C")}

        # "You may spend mana as though it were mana of any color." (Chromatic
        # Orrery.) The permission `_pay_mana_cost_directly` honours, asked here
        # too -- and it was not, for as long as both existed. The cascade below
        # tests each coloured pip against its own symbol, so a colourless pool
        # inferred X = 0 for **every** {X} spell with a coloured pip in it, and
        # the spell then resolved with X = 0 having spent nothing: Fireball
        # dealt 0 damage off four mana. A permission honoured at one payment
        # site out of several is an ability that works less often than the card
        # allows, which is the quieter half of `activation_restrictions`'
        # failure and just as silent.
        #
        # Ahead of the coloured cascade *and* of the restricted-X branch below.
        # "Spend only black mana on X" (Drain Life) is satisfied by every unit
        # under this permission, so the two questions collapse into one: what is
        # left after the pips and the printed generic are paid.
        if player.spends_mana_as_any_color:
            from ...mana_payment import fungible_colors_headroom

            headroom = fungible_colors_headroom(temp, required)
            return 0 if headroom is None else headroom

        if temp.get("W", 0) < required["W"]:
            return 0
        if temp.get("U", 0) < required["U"]:
            return 0
        if temp.get("B", 0) < required["B"]:
            return 0
        if temp.get("G", 0) < required["G"]:
            return 0
        if temp.get("C", 0) < required["C"]:
            return 0

        available_red = temp.get("R", 0)
        if player.can_spend_white_as_red:
            available_red += temp.get("W", 0)
        if available_red < required["R"]:
            return 0

        temp["W"] -= required["W"]
        temp["U"] -= required["U"]
        temp["B"] -= required["B"]
        temp["G"] -= required["G"]
        temp["C"] -= required["C"]

        red_to_pay = required["R"]
        from_red = min(temp.get("R", 0), red_to_pay)
        temp["R"] -= from_red
        red_to_pay -= from_red
        if red_to_pay > 0:
            if not player.can_spend_white_as_red:
                return 0
            if temp.get("W", 0) < red_to_pay:
                return 0
            temp["W"] -= red_to_pay

        available_generic = sum(max(0, temp.get(sym, 0)) for sym in ("C", "W", "U", "B", "R", "G"))
        if available_generic < required["generic"]:
            return 0

        restricted = tuple(sym for sym in x_colors if sym in _POOL_SYMBOLS)
        if restricted:
            # X may be paid only in these colours (CR 601.2h): reserve them by
            # covering the generic part from every *other* symbol first. A tuple
            # rather than one symbol -- "black and/or red" pools both, and asking
            # about black alone under-reported the affordable X by every red
            # mana the pool held.
            reserved = sum(max(0, temp.get(sym, 0)) for sym in restricted)
            other_available = available_generic - reserved
            generic_from_reserved = max(0, required["generic"] - other_available)
            return max(0, reserved - generic_from_reserved)

        return available_generic - required["generic"]
    def _parse_mana_cost(
        self, mana_cost: str, x_value: int | None, extra_generic: int = 0,
        x_allocation: dict[str, int] | None = None,
        extra_pips: dict[str, int] | None = None,
    ) -> dict[str, int]:
        """*mana_cost* as a symbol dict, with X worth *x_value*.

        *x_allocation* is how much of X is being paid in each colour -- the
        caster's CR 601.2h choice, already made. "Spend only black mana on X"
        (Drain Life) allocates all of X to {B}; "black and/or red" (Soul Burn)
        splits it, and ``_x_color_allocations`` below is what picks the split.
        Whatever X is not allocated stays generic, which is the unrestricted
        case with an empty allocation.

        A dict rather than the single ``x_color`` symbol this used to take: one
        symbol cannot describe a two-colour restriction, and it also cannot
        answer the question the split exists for -- how much {B} paid X, as
        opposed to the mandatory {B} pip or the {2} beside it.
        """
        required = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "generic": max(0, extra_generic)}
        # A coloured tax (Derelor's "{B}") joins the pips rather than the
        # generic part, which is what makes it unpayable from the wrong colour.
        for symbol, count in (extra_pips or {}).items():
            if symbol in _POOL_SYMBOLS:
                required[symbol] += max(0, int(count))
        if not mana_cost:
            return required

        allocation = {
            sym: max(0, int(count))
            for sym, count in (x_allocation or {}).items()
            if sym in _POOL_SYMBOLS
        }
        for token in re.findall(r"\{([^}]+)\}", mana_cost.upper()):
            if token.isdigit():
                required["generic"] += int(token)
                continue
            if token == "X":
                remaining = max(0, x_value or 0)
                for sym, count in allocation.items():
                    spent = min(remaining, count)
                    required[sym] += spent
                    remaining -= spent
                required["generic"] += remaining
                continue
            if token in _POOL_SYMBOLS:
                required[token] += 1
        return required

    @staticmethod
    def _x_color_allocations(
        x_colors: tuple[str, ...], x_value: int
    ) -> tuple[dict[str, int], ...]:
        """Every way to split *x_value* among *x_colors*, best split first.

        "Best" is as much as possible on the colour the card names first, then
        as much as possible on the next -- the caster's CR 601.2h choice, which
        this engine has no channel to ask for. The printed order is the
        preference because it is the only thing about the split the card itself
        says, and for the one card that can tell the difference it is also the
        caster-favourable reading: Soul Burn's life gain is capped by the {B}
        spent on X, and {B} is what it names first.

        Every split is returned, not just the best one, because the best one may
        not be payable -- X wholly in black cannot also leave a black for the
        mandatory {B} pip -- and the caller walks the list until the pool pays.
        Costing the whole cost each time is what makes that exact: the printed
        pips and the generic remainder are in the same question as the split.
        """
        if not x_colors:
            return ({},)
        wanted = max(0, x_value)
        if len(x_colors) == 1:
            return ({x_colors[0]: wanted},)
        head, tail = x_colors[0], x_colors[1:]
        return tuple(
            {head: taken, **rest}
            for taken in range(wanted, -1, -1)
            for rest in SpellCastingMixin._x_color_allocations(tail, wanted - taken)
        )

    def _pay_cast_cost(
        self, caster: PlayerState, card, x_value: int | None,
        x_colors: tuple[str, ...], *, extra_generic: int,
        reduction: CostReduction | None,
        extra_pips: dict[str, int] | None = None,
    ) -> dict[str, int] | None:
        """Pay *card*'s mana cost, and report what X was paid with.

        None when the pool cannot pay it under **any** split of X, and then
        nothing has been spent: ``_pay_mana_cost`` leaves the pool untouched on
        failure, so walking the candidate splits costs the caster nothing and
        the first one that pays is the payment that happened.
        """
        for allocation in self._x_color_allocations(x_colors, max(0, x_value or 0)):
            cost = reduce_cost(
                self._parse_mana_cost(
                    card.mana_cost, x_value=x_value,
                    extra_generic=extra_generic, x_allocation=allocation,
                    extra_pips=extra_pips,
                ),
                reduction or CostReduction(),
            )
            if self._pay_mana_cost(
                caster, cost, purpose=PaymentPurpose(CAST, card=card)
            ):
                return _x_mana_actually_spent(allocation, cost)
        return None
    def _pay_mana_cost(
        self, player: PlayerState, required: dict[str, int], *, purpose=None
    ) -> bool:
        """Pay *required* from *player*'s pool, or leave the pool untouched.

        Two steps, and the order is what makes the second one honest. The
        ordinary payment goes first; only when it cannot pay is a CR 609.4
        "you may spend mana as though…" grant spent (North Star). A grant tried
        first would be consumed by a spell that never needed it — "for **one**
        spell this turn" is a bounded permission, and the player would choose
        the spell that could not otherwise be cast.

        An activated ability is not a spell, so no grant applies to one: the
        clause says "that **spell's** mana cost", and *purpose* not naming a
        cast is that rule rather than a missing argument.
        """
        from ...restricted_mana import CAST

        if self._pay_mana_cost_directly(player, required, purpose=purpose):
            return True
        if purpose is None or purpose.kind != CAST:
            return False
        spell = purpose.card
        grant = next(
            (g for g in player.spend_mana_as_though_grants if int(g.get("spells", 0)) > 0),
            None,
        )
        if grant is None:
            return False
        paid = (
            self._pay_with_fungible_types(player, required)
            if grant.get("any_type")
            else self._pay_with_fungible_colors(player, required)
        )
        if not paid:
            return False
        # Spent only when it actually paid, so a grant is never burned by a
        # cost the pool could not have covered under any permission.
        grant["spells"] = int(grant["spells"]) - 1
        self.log.append(
            f"{player.name} spent mana as though it were mana of any "
            f"{'type' if grant.get('any_type') else 'color'} to cast "
            f"{getattr(spell, 'name', 'a spell')}"
        )
        return True

    def _pay_mana_cost_directly(
        self, player: PlayerState, required: dict[str, int], *, purpose=None
    ) -> bool:
        # "Spend this mana only to…" (CR 106.6): a restricted bucket joins the
        # pool only for a payment its own restriction admits, and whatever the
        # payment consumes is attributed to the restricted bucket first (its
        # units are otherwise lost, so spending them first is the only rational
        # attribution).
        #
        # *purpose* is what the payment is for — a cast, an activation, an
        # upkeep cost. It used to be the card being cast, which made every
        # restriction a claim about a *spell* and left the other two payment
        # paths unable to spend restricted mana at all.
        from ...restricted_mana import (debit_restricted_mana,
                                        spendable_restricted_mana)

        restricted = spendable_restricted_mana(player, purpose)
        if restricted and any(restricted.values()):
            snapshot = dict(player.mana_pool)
            player.mana_pool = {
                sym: snapshot.get(sym, 0) + restricted.get(sym, 0)
                for sym in ("W", "U", "B", "R", "G", "C")
            }
            if not self._pay_mana_cost_directly(player, required):
                player.mana_pool = snapshot
                return False
            for sym in ("W", "U", "B", "R", "G", "C"):
                spent = snapshot.get(sym, 0) + restricted.get(sym, 0) - player.mana_pool.get(sym, 0)
                from_restricted = min(spent, restricted.get(sym, 0))
                if from_restricted:
                    debit_restricted_mana(player, purpose, sym, from_restricted)
                snapshot[sym] = snapshot.get(sym, 0) - (spent - from_restricted)
            player.mana_pool = snapshot
            return True
        pool = player.mana_pool

        # "You may spend mana as though it were mana of any color." (Chromatic
        # Orrery.) Every unit in the pool pays a coloured pip, colourless
        # included — the Orrery's own five {C} are what the card is for. Handled
        # before the per-colour cascade rather than woven through it: with the
        # permission the five checks below are one check about a total, and
        # threading a substitution through each of them is how the narrow
        # white-as-red permission ended up appearing in five places.
        #
        # A **{C} in the cost still wants colourless**, because colourless is not
        # a colour (CR 105.1) and this line grants colours. So the generic and
        # colourless halves are unchanged.
        if player.spends_mana_as_any_color:
            return self._pay_with_fungible_colors(player, required)

        if pool.get("W", 0) < required["W"]:
            return False
        if pool.get("U", 0) < required["U"]:
            return False
        if pool.get("B", 0) < required["B"]:
            return False
        if pool.get("G", 0) < required["G"]:
            return False
        if pool.get("C", 0) < required["C"]:
            return False

        available_red = pool.get("R", 0)
        if player.can_spend_white_as_red:
            available_red += pool.get("W", 0)
        if available_red < required["R"]:
            return False

        temp = {symbol: pool.get(symbol, 0) for symbol in ("W", "U", "B", "R", "G", "C")}
        temp["W"] -= required["W"]
        temp["U"] -= required["U"]
        temp["B"] -= required["B"]
        temp["G"] -= required["G"]
        temp["C"] -= required["C"]

        red_to_pay = required["R"]
        from_red = min(temp.get("R", 0), red_to_pay)
        temp["R"] -= from_red
        red_to_pay -= from_red
        if red_to_pay > 0:
            if not player.can_spend_white_as_red:
                return False
            if temp.get("W", 0) < red_to_pay:
                return False
            temp["W"] -= red_to_pay

        generic = required["generic"]
        if generic > 0:
            available_generic = sum(max(0, temp.get(sym, 0)) for sym in ("C", "W", "U", "B", "R", "G"))
            if available_generic < generic:
                return False

            for sym in ("C", "W", "U", "B", "R", "G"):
                spend = min(temp.get(sym, 0), generic)
                temp[sym] -= spend
                generic -= spend
                if generic == 0:
                    break

        player.mana_pool = temp
        return True

    def _pay_with_fungible_types(
        self, player: PlayerState, required: dict[str, int]
    ) -> bool:
        """Pay *required* while every unit in the pool counts as any mana
        *type* — CR 106.1b's five colours **and** colorless.

        Its own function rather than a flag on the colour version above,
        because the two differ in exactly one place and it is the place that
        matters: with colorless in the set, a {C} the cost names is payable by
        a coloured mana, so there is nothing to reserve and no way for a pip to
        starve one. The payment collapses to a single question about the total,
        which is why this is short where that one is careful.
        """
        pool = {sym: int(player.mana_pool.get(sym, 0)) for sym in _POOL_SYMBOLS}
        owed = sum(required.get(sym, 0) for sym in _POOL_SYMBOLS)
        owed += required.get("generic", 0)
        if sum(pool.values()) < owed:
            return False
        for sym in _POOL_SYMBOLS:
            spend = min(pool[sym], owed)
            pool[sym] -= spend
            owed -= spend
            if owed == 0:
                break
        player.mana_pool = pool
        return True

    def _pay_with_fungible_colors(
        self, player: PlayerState, required: dict[str, int]
    ) -> bool:
        """Pay *required* while every unit in the pool counts as any colour.

        Three buckets in order, and the order is the only thing that makes the
        payment maximal: the coloured pips first (they are the pickiest, and
        under this permission any unit satisfies one), then {C}, which nothing
        else can pay, then the generic remainder from whatever is left.

        Colourless is spent *last* among the coloured pips, so a cost that also
        wants {C} is not starved by a pip that a coloured unit could have paid.
        """
        from ...mana_payment import fungible_colors_headroom

        pool = {sym: int(player.mana_pool.get(sym, 0)) for sym in ("W", "U", "B", "R", "G", "C")}
        colored_pips = sum(required[sym] for sym in ("W", "U", "B", "R", "G"))
        # Whether it can be paid at all is `mana_payment`'s arithmetic, not a
        # second copy here: the X inference and the client's affordability
        # display ask the same question of the same permission, and the three
        # answers have to agree. What stays here is the *spending*, which is
        # the only half of the job those two do not want.
        if fungible_colors_headroom(pool, required) is None:
            return False

        temp = dict(pool)
        owed = colored_pips
        for sym in ("W", "U", "B", "R", "G", "C"):
            if owed <= 0:
                break
            # Leave enough colourless behind for the {C} the cost names.
            spendable = temp[sym] - (required["C"] if sym == "C" else 0)
            spend = max(0, min(spendable, owed))
            temp[sym] -= spend
            owed -= spend
        if owed > 0:
            return False

        if temp["C"] < required["C"]:
            return False
        temp["C"] -= required["C"]

        generic = required["generic"]
        for sym in ("C", "W", "U", "B", "R", "G"):
            if generic <= 0:
                break
            spend = min(temp[sym], generic)
            temp[sym] -= spend
            generic -= spend
        if generic > 0:
            return False

        player.mana_pool = temp
        return True
