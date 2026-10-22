"""Whether a cast's announced targets are legal (CR 601.2c).

``_validate_cast_targets`` is the gate the UI's target enumerator also runs
through (``engine/legality.py``), so a target the picker offers is one
resolution will accept. Beside it: a roles announcement read in role order
(``_named_role_targets``), the noun phrase a "destroy target …" names
(``_destroy_target_legal``), and the X a "with mana value X" target fixes
(``_x_implied_by_target``). ``_settled_cast_division`` is the step of
``_cast_onto_stack`` that counts the named targets and checks the division
once X is a number (CR 601.2c–d), over ``_divided_total`` and its siblings.

The Aura enchant-noun helpers live here because an Aura chooses what it
attaches to as it is cast (CR 303.4a). ``permanent_matches_enchant_noun`` is
the *gate* — asked by the cast check below, the target picker,
``aura_attachment.aura_attach_refusal`` and the CR 704.5m sweep — and
``engine/enchant_targets.py`` reads the same line for the claim and the
picker; the two share a vocabulary deliberately (see its
``enchant_line_subject``).

Split out of ``casting.py`` at the 2,000-line cap, and composed onto ``Game``
with the other parts of ``SpellCastingMixin``, directly after it.
"""

from __future__ import annotations

import dataclasses
import re

from ...auras import aura_enchant_clause
from ...handlers._filters import graveyard_card_matches
from ...models import CardDefinition, Permanent
from ...oracle import compile_card_oracle
from ...oracle_types import (carries_x_bound, substitute_x_bounds,
                             without_x_bounds)
from ...target_restrictions import forbidden_target
from ...targeting import (bounce_subject_filter, destroy_subject_filter,
                          graveyard_target_spec)
from ...subject_filters import subject_matches
from ...enchant_targets import (_ENCHANT_LAND_SUBTYPES,
                                enchant_subject_colours,
                                enchant_subject_keyword_exclusion,
                                enchant_subject_seat)
from ...targeting import (derive_cast_spec, role_is_stack, spec_roles,
                          targets_mana_value_x)
from ...target_roles import role_is_seat
from ...cost_x_definitions import defines_cast_x
from ...divided_damage import (
    CARD_DIVIDED, EACH, EVENLY, FIXED, card_shares, divided_description,
    division_refusal, stamp_card_shares,
)
from ...game_types import SimulationResult
from ...targeting import instructions_as_announced
from .cast_announcement import _mode_announcements


# Maps an "enchant X" noun to a predicate matching legal battlefield targets.
# "creature" uses Permanent.is_creature so animated lands (Kormus Bell / Living
# Lands) accept creature Auras while they are creatures.
_ENCHANT_TARGET_MATCHERS = {
    "artifact": lambda perm: perm.has_type("artifact"),
    "creature": lambda perm: perm.is_creature,
    "land": lambda perm: perm.has_type("land"),
    "enchantment": lambda perm: perm.has_type("enchantment"),
    "wall": lambda perm: perm.has_type("wall"),
    # "Enchant **permanent**" (Faith's Fetters). Everything on the battlefield
    # is one (CR 110.1), so the answer is yes — written out rather than left to
    # the fallback below, which says yes for a noun nobody has read.
    "permanent": lambda perm: True,
    # "Enchant **Swamp**" (Spreading Algae). A land subtype, from the same
    # vocabulary catalog `enchant_targets._ENCHANT_LAND_SUBTYPES` builds the picker's
    # spec out of, so the hosts offered and the hosts allowed are one reading.
    #
    # This row is the half that would otherwise be missing, and its absence is
    # not a refusal: the noun would fall through to the permissive fallback
    # below, so an Aura whose *whole* effect is destroying the land it sits on
    # could be put on any permanent at all while reporting the restriction
    # implemented. That is Roots' failure exactly — one gate hiding two bugs —
    # which is why this table and `_ENCHANT_NOUN_TO_SPEC` grow together.
    **{
        subtype: (lambda word: lambda perm: perm.has_type(word))(subtype)
        for subtype in _ENCHANT_LAND_SUBTYPES
    },
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
    ``aura_attachment.aura_attach_refusal`` and by the CR 704.5m sweep that puts the Aura
    into the graveyard when its host stops satisfying the clause. The split
    itself is ``enchant_targets.enchant_subject_seat``, which the picker's spec is
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
    ``aura_attachment.aura_attach_refusal`` and the CR 704.5m sweep — one answer, so the
    list offered and the rule enforced cannot drift.
    """
    noun = enchant_subject_seat(noun)[0]
    excluded = None
    negated = _NON_SUBTYPE_ENCHANT.match(noun)
    if negated is not None:
        excluded, noun = negated.group("subtype"), negated.group("noun")
    # "Enchant creature **without flying**" (Roots). The keyword half of
    # CR 702.5's [quality], split by the reader `enchant_targets.enchant_subject_spec`
    # builds the picker from — so the hosts offered and the hosts allowed are
    # one reading. Through ``Permanent.has_keyword``, which is CR 613 layer 6's
    # answer: a creature *granted* flying stops being a legal host (and
    # ``unattach_illegal_equipment``'s sibling sweep, CR 704.5m, then puts the
    # Aura in the graveyard), while one that has lost it becomes one.
    #
    # The word itself is validated where the clause is *claimed*
    # (`enchant_targets.enchant_line_subject`): a keyword nothing implements answers
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
        from ...handlers._filters import permanent_effective_colors

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
            return False
        return any(matcher(permanent) for matcher in matchers)
    matcher = _ENCHANT_TARGET_MATCHERS.get(noun)
    if matcher is None:
        # A noun nobody has read: **no** host, not every host.
        #
        # Both fallbacks used to answer True, on the reasoning that refusing
        # would make such an Aura uncastable rather than loud. It is already
        # loud, and one step earlier: an unread noun fails
        # ``enchant_targets.enchant_line_subject``'s vocabulary, so the enchant line
        # is unclaimed, the card compiles **unsupported** ("unimplemented aura
        # effect: enchant equipment") and no player can put it in a deck. What
        # the permissive answer bought was therefore nothing, and what it cost
        # was the one way the three vocabularies can drift apart: this table is
        # the *gate*, ``enchant_targets._ENCHANT_NOUNS`` is the *claim* and
        # ``enchant_targets._ENCHANT_NOUN_TO_SPEC`` is the *picker*, and a noun added
        # to the other two and not to this one is a supported, deckable Aura
        # whose printed restriction nothing tests — Roots' failure exactly, and
        # a restriction that fails open is wrong in the player's favour and
        # silent.
        #
        # Failing closed makes that drift a card that attaches to nothing,
        # which is visible in one game. ``test_enchant_vocabularies.py`` makes
        # it a failing test instead, which is visible without one.
        return False
    if excluded is not None and permanent.has_type(excluded):
        return False
    return matcher(permanent)


def _divided_total(payload: dict, x_value: int | None) -> int:
    """How much a divided instruction has to divide, as announced.

    The same two keys the handler adds together — the amount and Meteor
    Shower's "X **plus 1**" bonus — read here so CR 601.2d's "the division must
    total this" is checked against the number the spell will really deal.
    """
    from ...handlers._amounts import resolve_amount

    # ``count`` for a distributed *counter* placement (Spoils of War) and
    # ``amount`` for damage: one sentence in CR 601.2d covers both, and the two
    # instruction families spell their quantity with the words their own
    # handlers read. Named here rather than normalized at the lowering, because
    # renaming one would be a payload key changed for the gate's convenience.
    quantity = payload.get("amount", payload.get("count", 0))
    return int(resolve_amount(quantity, x_value)) + int(
        payload.get("amount_bonus", 0) or 0
    )


def _card_divided_target_count(targets: dict, x_value: int | None) -> int | None:
    """How many targets a card-dictated division prints, or None.

    None for every spell whose target count is open — which is every divided
    spell in the pool before Weatherlight — so the caller may ask
    unconditionally and treat None as "CR 601.2c prints no number here".

    ``target_count`` is a literal (Cone of Flame's three) or the string ``"x"``
    (Firestorm's "each of **X** targets"). Resolved through the announced X
    rather than off the card, because CR 107.3a's announcement is the only place
    that number exists. Its own key rather than the ``count`` a several-targets
    description carries -- see ``card_divided_target_description``.
    """
    from ...handlers._amounts import resolve_amount

    count = targets.get("target_count")
    if count is None or isinstance(count, bool):
        return None
    if isinstance(count, int):
        return count
    if count == "x":
        return max(0, int(resolve_amount(count, x_value)))
    return None


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
    ``creatures_only`` / ``land_filter`` narrowing ``legality_enumeration._enumerate_targets``
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


class CastTargetValidationMixin:
    def _x_implied_by_target(
        self, card, target_player_index, target_permanent_index, target_stack_item,
        target_permanent_ids=None,
    ) -> int | None:
        """The X a "with mana value X" spell's chosen target fixes, or None.

        None whenever the spell does not print that restriction, or no target
        was named — those are the ordinary cases and they fall through to the
        pool-based inference. The stack item is read first because a spell being
        countered is the only kind of target Spell Blast has; Detonate's is a
        permanent on some seat's battlefield.

        **A permanent named by id is read before one named by slot** (CR 400.7:
        the id is the object). This read the slot alone, so an announcement
        made the way the engine asks for one fixed no X and was held to none:
        Detonate cast by id with X=4 at a zero-cost artifact was accepted,
        destroyed it and dealt 4 — the printed "with mana value X" enforced on
        the index spelling of a target and on no other.
        """
        if not targets_mana_value_x(compile_card_oracle(card).instructions):
            return None
        if target_stack_item is not None:
            return int(getattr(target_stack_item.card, "cmc", 0) or 0)
        named = next(
            (pid for pid in (target_permanent_ids or ()) if isinstance(pid, int)),
            None,
        )
        if named is not None:
            chosen = self.permanent_by_id(named)
            return None if chosen is None else int(getattr(chosen.card, "cmc", 0) or 0)
        if not isinstance(target_permanent_index, int):
            return None
        seat = target_player_index if target_player_index is not None else None
        if seat is None or not (0 <= seat < len(self.players)):
            return None
        chosen = self.permanent_at(self.players[seat], target_permanent_index)
        return None if chosen is None else int(getattr(chosen.card, "cmc", 0) or 0)

    def _destroy_target_legal(
        self, payload: dict, perm: Permanent, *,
        observer: int | None = None,
        source: "Permanent | None" = None,
        defending: int | None = None,
        that_player: int | None = None,
    ) -> bool:
        """Whether *perm* is in the noun phrase a ``destroy_target_permanent``
        instruction printed. Shared by cast validation and the legality
        enumerator so a destroy ability (Royal Assassin's "target tapped
        creature", Northern Paladin's "target black permanent") offers exactly
        the permanents it can legally destroy.

        **Through ``subject_matches``, never the pure matcher.** This asked
        ``permanent_matches_filter`` — the half of the question that is readable
        off the permanent alone — and so it dropped, silently, every key that
        needs the game: a keyword is layer 6 (CR 613.1f), a controller and an
        owner are seats, and "blocking this creature" is a combat relation. The
        gate answered yes and the ability was activated with the cost paid.
        Merfolk Assassin's "target creature **with islandwalk**" destroyed a
        vanilla Bear; Pit Trap's "attacking creature **without flying**" and
        Despotic Scepter's "nontoken permanent **you own**" read the same way.
        Nothing crashed and nothing was missing — the ability simply worked more
        often than the card allows, which is the one direction a target gate must
        never fail in.

        The four seats are the ones ``subject_matches`` refuses without: a caller
        that cannot say whose ability this is must not be handed a narrowing it
        would then ignore. Every one is supplied by the two callers below and by
        ``legality_enumeration._ability_target_legal``.

        Deliberately silent about "…with mana value X" (Detonate), which is the
        one restriction with no literal to test — ``destroy_subject_filter``
        drops the key and says why. The picker calls this before any X exists,
        and "X is not chosen yet" is not "no restriction": it is *every* mana
        value still being reachable, since the caster announces the target and
        the X together (CR 601.2b, then 601.2c). Narrowing here would offer
        nothing at all; the pair is checked in `_validate_cast_targets`, where
        both halves are known.
        """
        return subject_matches(
            self, perm, destroy_subject_filter(payload),
            observer=observer, source=source,
            defending=defending, that_player=that_player,
        )
    def _named_role_targets(
        self, caster_index: int, target_player_index, target_permanent_index,
        target_permanent_ids, roles=(), target_stack_item=None,
        role_seats=None,
    ) -> list:
        """The objects a roles announcement named, in role order.

        Ids first, exactly as the CR 702.16b loop below reads them, and for the
        same reason: the roles of one spell may sit on **two** battlefields - a
        Wall the defender controls and the attacker it blocked - so a list of
        slots against one ``target_seat`` cannot address them both. The index
        form is kept for a caller with one seat in hand (a test, the AI), and a
        slot that resolves to nothing stays None so the count check above sees a
        short announcement rather than a silently shifted one.

        **A role whose object is a player is filled from
        ``target_player_index``**, and that is a reuse rather than a special
        case: a stack item has carried "the player this spell targets" under
        that name since the first spell to name one, the resolution reads it
        back as ``context.target``, and Donate's "**target player** gains
        control of target permanent you control" means exactly that. Inventing
        a per-slot seat list beside it would be a second arity on a channel this
        repo has already recorded the cost of splitting
        (``StackItem.target_permanent_id``, 119 reader sites).

        Which slot is the player's comes from *roles*, never from the shape of
        the announcement: an id list positional in role order carries ``None``
        in that slot, and guessing "the None one is the player" would fill a
        permanent slot whose permanent has left.

        **A role whose object is a spell is filled from the stack channel**
        (*target_stack_item*), on the same argument one field over: "the spell
        this one targets" has been ``StackItem.target_stack_item`` since
        Counterspell, the resolution reads it back as ``context.stack_target``,
        and "Counter **target spell** and … deals 3 damage to target creature"
        (Suffocating Blast) means exactly that. So that announcement is a
        stack index beside ``[None, creature_id]``, and a stack slot with no
        spell named stays None — which the count check reads as the incomplete
        announcement it is.

        **Two player roles are filled from *role_seats***, the per-slot list a
        roles announcement of several seats carries (``target_roles.ROLE_SEATS``).
        "Choose any number of creatures **target player** controls. Choose the
        same number of creatures **another target player** controls."
        (Cultural Exchange.) The paragraph above stands for every announcement
        naming one player, and it could not say this one: read off the scalar
        both slots are one seat, which the walk's CR 115.3 distinctness then
        refuses — so the card could not be announced at all. A slot the list
        leaves empty, or names a seat that does not exist for, stays None.
        """
        player_slots = {
            index for index, role in enumerate(roles)
            if isinstance(role, dict) and role_is_seat(role)
        }

        def seat_at(index: int):
            if role_seats is None:
                return seated
            named = role_seats[index] if index < len(role_seats) else None
            if (
                isinstance(named, int) and not isinstance(named, bool)
                and 0 <= named < len(self.players)
            ):
                return self.players[named]
            return None

        stack_slots = {
            index for index, role in enumerate(roles)
            if isinstance(role, dict) and role_is_stack(role)
        }
        seated = (
            self.players[target_player_index]
            if isinstance(target_player_index, int)
            and 0 <= target_player_index < len(self.players)
            else None
        )
        if target_permanent_ids:
            return [
                seat_at(index) if index in player_slots
                else target_stack_item if index in stack_slots
                else (
                    self.permanent_by_id(permanent_id)
                    if permanent_id is not None else None
                )
                for index, permanent_id in enumerate(target_permanent_ids)
            ]
        slots = (
            target_permanent_index
            if isinstance(target_permanent_index, list)
            else [target_permanent_index]
        )
        # …and where a player role has taken ``target_player_index`` for its own
        # answer, that field no longer says which board the indices count into,
        # so the caster's is the only board left to mean. Without this an
        # announcement donating to seat 1 would look its own permanent up on
        # seat 1's battlefield — the silent wrong-permanent read the id channel
        # exists to abolish, arriving through the legacy one.
        seat = (
            caster_index if player_slots
            else (
                target_player_index if target_player_index is not None
                else caster_index
            )
        )
        return [
            seat_at(index) if index in player_slots
            else target_stack_item if index in stack_slots
            else self.permanent_at(seat, slot)
            for index, slot in enumerate(slots)
        ]

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
        optional_cost_payments: dict | None = None,
        target_role_seats: "list | None" = None,
    ) -> tuple[bool, str]:
        """Return (True, 'valid') if all required targets exist, else (False, reason).

        Only instants and sorceries execute effects at cast time; permanents enter
        the battlefield regardless of whether their activated abilities have targets.

        For a "Choose one —" modal spell, the chosen mode's instruction (not the
        first one) determines what the spell targets.

        *optional_cost_payments* is CR 601.2b's answer so far, for CR 702.33g:
        "If this spell was kicked, prevent all combat damage **another target
        creature** would deal this turn" (Falling Timber) announces its second
        target only when the kicker was. This gate re-derives the spell's spec
        to count its roles, so it has to derive the one the *announcement*
        describes — read as the card's whole program, an unkicked Falling
        Timber was refused "requires 2 targets" and one named with two was
        accepted. None reads every arm, which is the question a caller with no
        announcement in hand is asking.

        *target_role_seats* is the announcement's seat **per role**, where it
        named more than one player (``target_roles.ROLE_SEATS``); the roles gate
        below fills each player slot from it, and every seat in it is held to
        the same name-protection question the scalar is.
        """
        # Protection from this spell's *name* (Runed Halo, CR 702.16i): the
        # player can't be chosen as a target, which under CR 601.2c makes the
        # spell uncastable at them rather than ineffective. Asked of the chosen
        # player before the per-type checks below, because it applies whatever
        # the spell's type is.
        from ...named_protection import protected_from

        for named_seat in dict.fromkeys(
            [target_player_index, *(target_role_seats or ())]
        ):
            if (
                isinstance(named_seat, int)
                and 0 <= named_seat < len(self.players)
                and protected_from(self, named_seat, card)
            ):
                details = (
                    f"{self.players[named_seat].name} has protection from "
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
                        #
                        # "Cards in graveyards can't be the targets of spells
                        # or abilities." (Ground Seal.) This arm is a list of
                        # its own — it predates ``_enumerate_graveyard_creatures``,
                        # where every other graveyard target is asked the
                        # question — so an Aura spell that enchants a card in
                        # a graveyard (CR 303.4a: it targets what it will
                        # enchant) has to be asked here as well. The picker
                        # already offered nothing; the cast went through.
                        from ...target_immunity import graveyard_cards_untargetable

                        if graveyard_cards_untargetable(self) is not None:
                            return False, f"no valid target for {card.name}"
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
        # "Gain control of target creature with mana value **X or less**."
        # (Dominate.) CR 601.2b announces X before CR 601.2c chooses the target,
        # so the bound is checked against the announced number — the
        # substitution the dispatcher makes at resolution, made here so every arm
        # below reads an integer. A probe made before X exists (the picker
        # enumerating ahead of the X prompt) cannot answer the bound and leaves
        # it out; the announcement and the resolution re-ask it with the number.
        if carries_x_bound(primary.payload):
            primary = dataclasses.replace(
                primary,
                payload=(
                    substitute_x_bounds(primary.payload, x_value)
                    if x_value is not None else without_x_bounds(primary.payload)
                ),
            )

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
        # **Of the mode announced** (CR 601.2b). Derived as mode 0's whatever
        # was chosen, the count and the roles below were another mode's: Hull
        # Breach's third mode ("destroy target artifact and target
        # enchantment") was two roles nothing counted, and Reign of Chaos'
        # second ("target Island and target blue creature") was refused for
        # not naming a Plains and a white creature.
        cast_spec = derive_cast_spec(
            card, program, optional_cost_payments=optional_cost_payments,
            mode_index=mode_index,
        ) or {}
        maximum = cast_spec.get("max_targets")
        if isinstance(maximum, int) and announced is not None and announced > maximum:
            return False, f"too many targets for {card.name}"
        # CR 702.33g's other direction: a target printed only in the kicked
        # half is not chosen by a cast that was not kicked. The roles gate
        # below counts the slots a kicked cast names; this is the same count
        # for the cast that declined, whose spec has no roles left to count
        # against — so without it an unkicked Falling Timber naming two
        # creatures was simply accepted, the second one recorded on the stack
        # item as a target the spell does not have.
        if (
            optional_cost_payments is not None
            and not spec_roles(cast_spec)
            and spec_roles(
                derive_cast_spec(card, program, mode_index=mode_index) or {}
            )
        ):
            named = (
                [pid for pid in target_permanent_ids if pid is not None]
                if target_permanent_ids
                else (
                    target_permanent_index
                    if isinstance(target_permanent_index, list) else []
                )
            )
            if len(named) > 1:
                return False, (
                    f"{card.name} names one target unless it was kicked "
                    f"(CR 702.33g)"
                )

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
                target_permanent_ids, roles, target_stack_item,
                role_seats=target_role_seats,
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
                target_permanent_ids,
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

        def _may_name_nobody() -> bool:
            # CR 601.2c: "up to N target", "any number of target" and "X
            # target" at an X of zero are legal announcements naming nobody, so
            # the arms below must not refuse them for having nobody to name.
            # Asked only where an arm is about to refuse an *unnamed* cast, and
            # through the reader `no_legal_cast_target_refusal` uses, so the
            # arms and that gate cannot disagree about which spells need one.
            from ...legality import cast_may_name_no_target

            return cast_may_name_no_target(
                card, program, x_value=x_value, mode_index=mode_index,
            )

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
                    primary.payload, battlefield[target_permanent_index],
                    observer=caster_index,
                ):
                    return False, f"no valid target for {card.name}"
            else:
                # No specific choice: destruction can target a permanent controlled
                # by anyone, so a legal target on the caster's own battlefield (e.g.
                # Disenchant on one's own artifact) is enough to make the cast legal.
                has_target = any(
                    self._destroy_target_legal(
                        primary.payload, p, observer=caster_index
                    )
                    for p in self.all_permanents()
                )
                if not has_target and not _may_name_nobody():
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
            ) and not _may_name_nobody():
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
            elif not any(
                _legal_pump_target(p) for p in self.all_permanents()
            ) and not _may_name_nobody():
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

                # The target named **by id** is checked here too. Every other
                # narrowing reaches it through ``cast_target_refusal``'s
                # enumeration, but that probe runs before X exists — so "mana
                # value **X or less**" (Dominate) is asked of the named creature
                # only here, with the announced X substituted above. Left to
                # the resolution, an id that fails the bound falls through
                # ``pick_target_permanent``'s scan and steals a creature nobody
                # named.
                named = next(
                    (pid for pid in (target_permanent_ids or []) if isinstance(pid, int)),
                    None,
                )
                if named is not None:
                    chosen = self.permanent_by_id(named)
                    if chosen is None or not _legal_steal_target(chosen):
                        return False, f"no valid target for {card.name}"
                elif isinstance(target_permanent_index, int):
                    chosen = self.permanent_at(target_idx, target_permanent_index)
                    if chosen is None or not _legal_steal_target(chosen):
                        return False, f"no valid target for {card.name}"
                elif not any(
                    _legal_steal_target(p) for p in self.all_permanents()
                ) and not _may_name_nobody():
                    return False, f"no valid target for {card.name}"

        elif primary.kind in ("tap_target_permanent", "untap_target_permanent"):
            # "Is there anything to tap?" — asked of **every** battlefield, and
            # only of a cast that named nothing and must name something.
            #
            # It was ``if not target.battlefield``: the battlefield of whichever
            # seat the caller named, or the *opposing* one by default — so it
            # judged a board the target was not on. Burst of Energy ("Untap
            # target permanent") aimed by id at the caster's own land was
            # refused whenever the opponent controlled nothing, because an id
            # names no seat and the default seat's board was empty; and "Tap
            # **up to three** target creatures" (Tidal Surge) was refused for
            # having nobody to name. What a *named* permanent has to be is
            # ``cast_target_refusal``'s question, asked of the picker's list.
            named = isinstance(target_permanent_index, (int, list)) or any(
                isinstance(pid, int) for pid in (target_permanent_ids or ())
            )
            if (
                not named
                and not any(True for _ in self.all_permanents())
                and not _may_name_nobody()
            ):
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
            printed = targets_desc.get("count") if isinstance(targets_desc, dict) else None
            several = isinstance(printed, int) and printed > 1
            # "Return **up to X** target cards from your graveyard to your
            # hand" (Reap). The same announcement as the printed "up to two"
            # below and the same rule: CR 601.2c lets the caster name zero
            # targets, so an empty graveyard is a legal cast that does nothing
            # rather than a spell that cannot be cast. Read off the
            # *quantifier*, not off the letter: "X target creature cards"
            # (Shattered Crypt) is an exact count and does need X legal ones.
            #
            # The ceiling on such a list is a board count and is checked where
            # that count is known (``legality_cast_spec.announced_cast_x``), which is why
            # the maximum below asks whether the printed count is a number
            # before comparing to it.
            if printed == "x" and targets_desc.get("quantifier") == "up_to":
                several = True
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
                if isinstance(printed, int) and len(slots) > printed:
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
            ) and not _may_name_nobody():
                # "Return **X** target creature cards from your graveyard"
                # (Restless Dreams) at an X of zero names nobody, which CR
                # 601.2c allows -- the same question every arm above asks
                # before refusing an unnamed cast. Its X is the number of
                # cards discarded as its cost, so an empty graveyard is a
                # cast that discards nothing and returns nothing, not one
                # that cannot be made. At an X of one or more the exact count
                # is ``cast_target_count_refusal``'s, asked once X is final.
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

    def _settled_cast_division(
        self, *, announced_x, card, caster_index, chosen_modes, classification,
        divided_targets, from_zone, mode_index, named_no_division_targets,
        optional_paid, resolved_x_value, target_permanent_ids,
        target_permanent_index, target_player_index, target_stack_item,
        x_value,
    ):
        """CR 601.2c's count and CR 601.2d's division, once X is a number.

        Each announced mode names as many targets as it prints; a spell that
        divides nothing refuses a division; a divided spell's shares are
        checked against its total, an "up to" division that named nobody is
        written down as that, and a card's printed shares are stamped onto the
        announcement.

        A step of ``_cast_onto_stack``, moved out of it whole and called from
        it in its place: "above" and "below" in its comments are places in the
        cast as that method runs it.

        Returns the refusal, or ``(divided_targets, target_player_index)``.
        """
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
        #
        # **Of the steps this announcement will run** (CR 702.33g): a kicked
        # Magma Burst divides over two targets and an unkicked one names one
        # the ordinary way, and Pollen Remedy's shares total 3 or 6 — so which
        # divided step is the spell's is CR 601.2b's answer, read through the
        # same view the picker's spec is.
        # CR 601.2c's **count**, here because here is where X is a number:
        # "two target creatures" names two and "Tap X target creatures" names
        # X (`legality_cast_gates.cast_target_count_refusal`). Once per announced mode,
        # like the gates above. An X the caller announced (or the card
        # defined) is counted; one this function inferred from the pool a few
        # lines up is not — the caster never said it.
        counted_x = (
            resolved_x_value
            if x_value is not None or announced_x is not None
            or defines_cast_x(card.oracle_text)
            else None
        )
        for (
            announced_mode, mode_seat, mode_slot, mode_ids, _mode_stack_item,
        ) in _mode_announcements(
            chosen_modes, mode_index, target_player_index,
            target_permanent_index, target_permanent_ids, target_stack_item,
        ):
            miscounted = self.cast_target_count_refusal(
                caster_index, card,
                target_player_index=mode_seat,
                target_permanent_index=mode_slot,
                target_permanent_ids=mode_ids,
                x_value=counted_x,
                optional_cost_payments=optional_paid,
                mode_index=announced_mode,
            )
            if miscounted is not None:
                self.log.append(miscounted)
                return SimulationResult(
                    card.name, False, classification.effect_kind, miscounted,
                )

        found = divided_description(
            instructions_as_announced(
                card, compile_card_oracle(card), optional_paid,
                mode_index=mode_index,
            )
        )
        if found is None and divided_targets:
            # CR 601.2d is about a spell that **divides or distributes**. A
            # division announced for one that does not is not an announcement
            # this spell can make — and it was accepted: nothing above looks at
            # the list unless a divided step exists, while every damage handler
            # reads `choices["divided_targets"]` whenever it is present. So
            # `cast_from_hand(0, "Lightning Bolt", divided_targets=[(1, None),
            # (0, None)])` split its 3 between two faces, and 483 of the pool's
            # 910 non-divided instants and sorceries took the list the same
            # way. Neither the client nor the AI sends one; the engine's own
            # announcement API was laxer than the rule. Of the steps this
            # announcement will run, so a division printed only in a kicked
            # arm or in one mode belongs to that cast alone.
            refusal = f"{card.name} divides nothing among targets (CR 601.2d)"
            self.log.append(refusal)
            return SimulationResult(
                card.name, False, classification.effect_kind, refusal,
            )
        if found is not None:
            division = found[1].get("division", EVENLY)
            total = _divided_total(found[0], resolved_x_value)
            # "…to **each of X targets**" (Firestorm), "…and 3 damage to a third
            # target" (Cone of Flame). How many targets the card prints, which
            # for Firestorm is the X the caster has just announced — so it is
            # resolved here, one step after CR 601.2b and one before the
            # CR 601.2c check that reads it.
            exact = (
                _card_divided_target_count(found[1], resolved_x_value)
                if division in CARD_DIVIDED else None
            )
            named_outside = _named_divided_targets(
                card, from_zone, target_player_index,
                target_permanent_index, target_permanent_ids,
            )
            refusal = division_refusal(
                total,
                divided_targets or (),
                division=division,
                max_targets=found[1].get("max_targets"),
                named_targets=named_outside,
                exact_targets=exact,
                # The announcement of no targets is written down just below
                # and read at resolution (``announced_no_targets``).
                carries_no_targets=True,
            )
            if refusal is not None:
                self.log.append(f"{card.name}: {refusal}")
                return SimulationResult(
                    card.name, False, classification.effect_kind, refusal,
                )
            # "…to each of **up to** three targets" (Shower of Coals), cast
            # naming nobody (CR 115.6). Written onto the announcement as the
            # empty list it is — and an *explicit* empty list is that
            # announcement whatever seat the cast also carries, because every
            # cast over the wire carries one. Without the mark the resolution
            # could not tell "nobody" from "nothing said", and a spell that
            # targets nothing went looking for the default opponent's face.
            #
            # The seat is dropped with it: a spell that chose no target has
            # none (CR 115.6 — "targeted only if one or more targets have been
            # chosen"), and a seat left on the stack object would be read back
            # as a player it targets. A *permanent* named outside the list is
            # a target and keeps the announcement what it was.
            names_a_permanent = bool(target_permanent_ids) or (
                target_permanent_index is not None
            )
            if (
                division == EACH
                and found[1].get("max_targets") is not None
                and not divided_targets
                and not names_a_permanent
                and (named_no_division_targets or not named_outside)
            ):
                divided_targets = []
                target_player_index = None
            # The card's own shares, written onto the announcement now that it
            # is known to be legal. Here rather than at resolution because the
            # share has to ride its target: a target that has left is dropped
            # from the list (CR 608.2b), and a share read by position after that
            # would slide Cone of Flame's 3 onto the creature it assigned 2.
            #
            # **Printed shares only** (:data:`FIXED`). An :data:`EACH` entry
            # was stamped too, with "the whole amount" — a number the
            # resolution settles, not the announcement (CR 608.2h): Shower of
            # Coals deals 2 or 4 by the graveyard it finds, and its entries
            # read 4 on a board where it would deal 2. ``divide`` has never
            # read the stamp for ``EACH``, so the number said nothing true and
            # nothing was asked of it; an entry with no amount is what "the
            # card supplies it as it resolves" looks like.
            if division == FIXED and divided_targets:
                divided_targets = stamp_card_shares(
                    divided_targets,
                    card_shares(
                        total, len(divided_targets),
                        division=division, shares=found[1].get("shares"),
                    ),
                )
        return divided_targets, target_player_index
