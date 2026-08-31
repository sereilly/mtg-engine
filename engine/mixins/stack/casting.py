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
from ...cast_costs import AdditionalCost, additional_costs
from ...auras import controller_cast_ban
from ...cast_restrictions import check_cast_timing
from ...damage_ledger import record_cast
from ...hand_locks import hand_lock_reason, playable_hand_index
from ...classifier import classify_card
from ...cost_modifiers import (
    CostReduction, cost_reduction_for_cast, reduce_cost, sacrifice_taxes,
    spell_cost_tax, spell_life_tax,
)
from ...game_types import SimulationResult, StackItem
from ...handlers._common import graveyard_card_matches, permanent_matches_filter
from ...models import CardDefinition, Permanent, PlayerState
from ...oracle import _COLOR_WORD_TO_SYMBOL, compile_card_oracle
from ...oracle_types import x_spend_color_from_text
from ...restricted_mana import CAST, PaymentPurpose
from ...target_restrictions import forbidden_target
from ...targeting import bounce_subject_filter, graveyard_target_spec
from ...subject_filters import filter_head_noun, subject_matches
from ...targeting import (derive_cast_spec, enchant_subject_seat, spec_roles,
                          targets_mana_value_x)

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
        )
        if not queued.supported:
            return queued

        # Resolve the spell, then drain any triggers it (or the deaths it causes)
        # put on the stack, interleaving state-based-action checks (CR 704.3/603.3).
        self._settle()
        self.clear_priority_window()
        return SimulationResult(queued.card_name, True, queued.effect_kind, "resolved")
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

        if not mode_choices:
            return (), None
        program = compile_card_oracle(card)
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
        # rather than clamped when the caster cannot pay: CR 118.4 makes an
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
        )
        if named_refusal is not None:
            self.log.append(named_refusal)
            return SimulationResult(card.name, False, classification.effect_kind, named_refusal)

        # A divided spell's cross-seat target list: sanity-check every entry so a
        # stale battlefield index can't crash resolution.
        if divided_targets is not None:
            cleaned: list[tuple[int, int | None]] = []
            for entry in divided_targets:
                seat, index = entry
                if not (isinstance(seat, int) and 0 <= seat < len(self.players)):
                    return SimulationResult(card.name, False, classification.effect_kind, "invalid divided target seat")
                if index is not None and not (
                    isinstance(index, int) and 0 <= index < len(self.players[seat].battlefield)
                ):
                    return SimulationResult(card.name, False, classification.effect_kind, "invalid divided target")
                cleaned.append((seat, index))
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

        x_color = x_spend_color_from_text(card.oracle_text)
        resolved_x_value = x_value
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
                caster, card.mana_cost, extra_generic_tax, x_color=x_color,
                reduction=cost_reduction,
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

        # "Spells cost an additional "Sacrifice a Swamp" to cast for each black
        # mana symbol in their mana costs." (Drought.) An additional cost
        # imposed from a *board* rather than printed on the spell, so it is
        # asked here beside the printed ones and at the same moment (CR 601.2f
        # determines it, CR 601.2h pays it), and refused rather than clamped:
        # CR 118.4 makes an unpayable cost an uncastable spell, not a free one.
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
        ):
            waiver = permission_for(self, caster_index, card, "hand")
            if waiver is not None and from_zone == "hand":
                free_grant = waiver
                if permission is None:
                    permission = waiver
        if free_grant is not None and card.primary_type != "land":
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
            cost = reduce_cost(
                self._parse_mana_cost(
                    card.mana_cost, x_value=resolved_x_value,
                    extra_generic=extra_generic_tax, x_color=x_color,
                ),
                cost_reduction,
            )
            if not self._pay_mana_cost(
                caster, cost, purpose=PaymentPurpose(CAST, card=card)
            ):
                details = f"insufficient mana for {card.name}"
                if x_color is not None:
                    details = f"insufficient mana for {card.name} (X can be paid only with {x_color} mana)"
                self.log.append(details)
                return SimulationResult(card.name, False, classification.effect_kind, details)

        card = source_zone.pop(hand_index)
        # Now, and not before: the spell is no longer in the hand, so it cannot
        # be discarded to pay for itself, and the creature it eats is gone from
        # the battlefield before the spell is on the stack.
        sacrificed_for_cost = self._pay_additional_costs(
            caster_index, card, cast_costs,
            cost_permanent_index=cost_permanent_index,
            cost_hand_card=cost_hand_card,
            x_value=resolved_x_value,
        )
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
                        "sacrificed_for_cost": sacrificed_for_cost,
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
            self._apply_spell_cast_any_triggers(caster_index, card, from_zone)
            self._apply_cast_triggers(caster_index, card)
            return SimulationResult(card.name, True, classification.effect_kind, "queued")

        self._resolve_card(
            caster_index=caster_index,
            card=card,
            classification=classification,
            target_player_index=target_player_index,
            target_permanent_index=target_permanent_index,
            x_value=resolved_x_value,
            choices={"sacrificed_for_cost": sacrificed_for_cost},
        )
        return SimulationResult(card.name, True, classification.effect_kind, "resolved")
    # ------------------------------------------------------------------
    # Printed additional costs (CR 601.2b)
    # ------------------------------------------------------------------

    def _additional_cost_candidates(self, caster_index: int, cost: AdditionalCost) -> list[Permanent]:
        """The permanents that could pay *cost*'s sacrifice, by identity.

        Never by index: an index would be held across the removal that paying
        performs, and would then name whichever permanent slid into the slot.
        """
        if cost.sacrifice_filter is None:
            return []
        return [
            perm
            for perm in self.controlled_by(caster_index)
            # The observer is the payer: "a creature **you control**" is a
            # seat comparison, and a payload carrying one with no observer to
            # compare against refuses every candidate.
            if subject_matches(
                self, perm, cost.sacrifice_filter, observer=caster_index
            )
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
            # CR 118.4: a player may pay life only down to 0, and CR 601.2h then
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
                available = len(caster.hand)
                if from_zone == "hand" and spell_hand_index is not None:
                    available -= 1
                if available < cost.discard_cards:
                    return (
                        f"{card.name} can't be cast: not enough cards in hand to "
                        f"discard for its additional cost (CR 601.2h)"
                    )
        return None

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
        if cost_hand_index is None or not any(cost.discard_cards for cost in costs):
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
        return hand[cost_hand_index], None

    def _pay_additional_costs(
        self,
        caster_index: int,
        card: CardDefinition,
        costs: tuple[AdditionalCost, ...],
        *,
        cost_permanent_index: int | None,
        cost_hand_card: "CardDefinition | None",
        x_value: int | None = None,
    ) -> Permanent | None:
        """Perform *card*'s printed additional costs, returning what was
        sacrificed (for the spell whose effect asks about it).

        The payer chooses (CR 601.2b), and the choice arrives with the action
        rather than through the pending-choice queue — a queued prompt would put
        the spell on the stack before its cost was collected, which is the
        reasoning ``activate_permanent_ability`` already records for the
        identically-shaped activation costs. A seat that names nothing gets a
        deterministic pick so AI and headless play stay unblocked.
        """
        caster = self.players[caster_index]
        sacrificed: Permanent | None = None
        for cost in costs:
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
                    index = 0
                    if cost_hand_card is not None:
                        index = next(
                            (
                                i for i, held in enumerate(caster.hand)
                                if held is cost_hand_card
                            ),
                            0,
                        )
                        cost_hand_card = None  # one named card pays once
                    discarded = caster.hand.pop(index)
                    self._discard_card(caster, discarded)
                    self.log.append(
                        f"{caster.name} discarded {discarded.name} to cast {card.name}"
                    )
                    # One named index pays one card; the rest take the default.
                    cost_hand_index = None
        return sacrificed

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
            if chosen.is_creature and not self._can_be_targeted(
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
            caster = self.players[caster_index]
            any_card = bool(primary.payload.get("any_card"))
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
                if slots and target_player_index is not None and target_player_index != caster_index:
                    return False, f"no valid target for {card.name}"
                if len(slots) > targets_desc["count"]:
                    return False, f"too many targets for {card.name}"
                for slot in slots:
                    if not isinstance(slot, int) or not (0 <= slot < len(caster.graveyard)):
                        return False, f"no valid target for {card.name}"
                    if not graveyard_card_matches(primary.payload, caster.graveyard[slot]):
                        return False, f"no valid target for {card.name}"
            elif isinstance(target_permanent_index, int):
                if target_player_index is not None and target_player_index != caster_index:
                    return False, f"no valid target for {card.name}"
                if not (0 <= target_permanent_index < len(caster.graveyard)) or (
                    not graveyard_card_matches(
                        primary.payload, caster.graveyard[target_permanent_index]
                    )
                ):
                    return False, f"no valid target for {card.name}"
            elif not any(
                graveyard_card_matches(primary.payload, c) for c in caster.graveyard
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
        x_color: str | None = None, reduction: CostReduction | None = None,
    ) -> int:
        # The reduction is applied before X is inferred, because X is whatever
        # is left after the rest of the cost is paid — inferring it from the
        # undiscounted cost would spend the discount on nothing.
        required = reduce_cost(
            self._parse_mana_cost(mana_cost, x_value=0, extra_generic=extra_generic),
            reduction or CostReduction(),
        )
        temp = {symbol: player.mana_pool.get(symbol, 0) for symbol in ("W", "U", "B", "R", "G", "C")}

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

        if x_color in {"W", "U", "B", "R", "G", "C"}:
            # X may only be paid in one color: reserve it by covering the generic
            # part from the other colors first.
            other_available = available_generic - max(0, temp.get(x_color, 0))
            generic_from_x_color = max(0, required["generic"] - other_available)
            return max(0, temp.get(x_color, 0) - generic_from_x_color)

        return available_generic - required["generic"]
    def _parse_mana_cost(
        self, mana_cost: str, x_value: int | None, extra_generic: int = 0, x_color: str | None = None
    ) -> dict[str, int]:
        required = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "generic": max(0, extra_generic)}
        if not mana_cost:
            return required

        for token in re.findall(r"\{([^}]+)\}", mana_cost.upper()):
            if token.isdigit():
                required["generic"] += int(token)
                continue
            if token == "X":
                # "Spend only black mana on X" (Drain Life): the X portion is a
                # colored requirement, not generic payable from anything.
                if x_color in {"W", "U", "B", "R", "G", "C"}:
                    required[x_color] += max(0, x_value or 0)
                else:
                    required["generic"] += max(0, x_value or 0)
                continue
            if token in {"W", "U", "B", "R", "G", "C"}:
                required[token] += 1
        return required
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
        pool = {sym: int(player.mana_pool.get(sym, 0)) for sym in ("W", "U", "B", "R", "G", "C")}
        colored_pips = sum(required[sym] for sym in ("W", "U", "B", "R", "G"))
        total = sum(pool.values())
        if total < colored_pips + required["C"] + required["generic"]:
            return False
        if pool["C"] < required["C"] + max(0, colored_pips - (total - pool["C"])):
            # The colourless the cost names is not reachable: too much of the
            # pool has already been claimed by pips no coloured unit can cover.
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
