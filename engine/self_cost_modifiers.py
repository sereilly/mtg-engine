"""A spell's or an ability's change to its own cost (CR 601.2f).

The second of ``engine/cost_modifiers.py``'s two shapes. "This spell costs {N}
less to cast [if …]" (Stormwing Entity, Prophecy's Avatars), "This ability
costs {N} less to activate for each …" (Sanctum of Tranquil Light), and "This
spell costs {1} more to cast for each target beyond the first" (Fireball). It
is a property of the card being cast, read off its own text and gated on a
condition about the cast, so no permanent is involved and no battlefield scan
would find it.

Split out of ``engine/cost_modifiers.py`` at the 2,000-line cap.
``cost_modifiers.cost_reduction_for_cast`` folds these in with the board's
reductions, and ``cost_modifiers.cost_modifier_claims_line`` claims their
lines.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from .oracle_types import compilation_cache, strip_ability_word
from .cost_modifier_lines import _MANA_SYMBOLS, CostReduction


# ---------------------------------------------------------------------------
# A spell's own reduction (CR 601.2f), and the arithmetic every reduction uses
# ---------------------------------------------------------------------------


# "[If <condition>, ][During your turn, ]this spell costs {…} less to cast[ if
# <condition>]."
#
# The condition is printed in **either** position: trailing on Stormwing Entity,
# fronted on Prophecy's five Avatars ("If you have 3 or less life, this spell
# costs {6} less to cast"). One sentence in two English word orders, so one
# pattern with two delimiting groups rather than two tables — and a line
# printing both is refused below, because two conditions is a conjunction
# nothing here was asked to read.
#
# "…less to cast **for each basic land type among lands you control**."
# (Stratadon, Draco.) The third way the size is not the printed number: a
# multiplier, delimited here as the whole "for each …" clause and read by the
# grammar's own per-each reader (``grammar.per_each_count_spec_for``) rather
# than by a second pattern for what may be counted.
_SELF_REDUCTION = re.compile(
    r"(?:if (?P<fronted>.+?), )?"
    r"(?:(?P<during>during your turn), )?this spell costs (?P<pips>(?:\{[^}]+\})+) "
    r"less to cast(?: (?P<per_each>for each [^.]+?))?(?: if (?P<condition>[^.]+))?"
    r"(?:, where x is (?P<counted>[^.]+))?\.?$"
)

# The "where X is …" clauses a self-reduction may be sized by, mapped to the
# question asked of the caster at CR 601.2f. A wording outside this table
# refuses the line — an unrecognized count read as zero would merely fail to
# discount, but read as anything else would under-charge, and refusing keeps the
# card visibly unsupported instead of quietly mispriced.
_SELF_REDUCTION_COUNTS: dict[str, str] = {
    "the total power of creatures you control": "total_power_you_control",
    "the total amount of noncombat damage dealt to your opponents this turn":
        "noncombat_damage_to_opponents_this_turn",
}


# The conditions a self-reduction may be gated on, mapped to the question the
# caster's own state answers. A wording outside this table refuses the line —
# reading an unrecognized condition as "true" would make the spell cheaper than
# it is, which is the one direction a cost error must never go.
#
# **Closed at these two.** Every other condition is read by the grammar's own
# condition reader (``grammar.condition_payload_for``) and answered by
# ``handlers/control_flow.evaluate_condition`` — the pair every printed
# intervening-if already goes through — and is gated below on the kinds a
# cast-time question can answer. These two stay because the grammar does not
# read the "you've" contraction or a spell-type narrowing on the cast record;
# retiring them means teaching it both, not adding a row here.
_SELF_CONDITIONS: dict[str, str] = {
    "you've cast an instant or sorcery spell this turn": "cast_instant_or_sorcery",
    "you've gained 3 or more life this turn": "gained_three_life",
}

#: The lowered condition kinds a spell's own reduction may stand behind (CR
#: 601.2f), and so the ones :func:`_cast_time_gate` admits. Every one is a
#: question about the board, the zones or the life totals **as they are now**:
#: a reduction is calculated while the spell is being cast, when nothing has
#: fired, nothing has resolved and nothing was recorded "this way", so a kind
#: reading a trigger's frozen context or a resolution's scratchpad would be
#: answered off an empty record — False forever, or worse, true by default.
_CAST_TIME_CONDITION_KINDS = frozenset({
    "controls", "on_battlefield", "zone_card_count", "player_life",
    "cards_in_zones",
})

#: The seat words those kinds may carry. "You" is the caster; "opponent" is the
#: existential the evaluator answers over every living opponent. Any other word
#: names a target, an event's player or a superlative, none of which a spell in
#: the middle of being cast has.
_CAST_TIME_SEATS = frozenset({"you", "opponent"})


def _cast_time_gate(payload: dict) -> bool:
    """Whether a lowered condition is one a cast-time reduction can answer.

    Refusing is the safe direction here and only here: a reduction whose gate
    could not be asked would be read as unconditional, which is a spell cheaper
    than it prints.
    """
    kind = payload.get("kind")
    if kind in ("all_of", "any_of"):
        parts = payload.get("conditions") or ()
        return bool(parts) and all(_cast_time_gate(part) for part in parts)
    if kind not in _CAST_TIME_CONDITION_KINDS:
        return False
    if any(
        key in payload and payload[key] not in _CAST_TIME_SEATS
        for key in ("who", "player")
    ):
        return False
    # "another"/"other": the asking object is a card in a hand, not a permanent,
    # and an exclusion of it is a sentence no spell prints about itself.
    described = payload.get("filter") or {}
    return not (described.get("exclude_self") or described.get("exclude_event_subject"))


def _gate_holds(game, caster_index: int, card, gate: dict) -> bool:
    """Ask *gate* of the caster's game now, through the one evaluator."""
    from .game_types import OracleExecutionContext
    from .handlers.control_flow import evaluate_condition

    caster = game.players[caster_index]
    # ``target`` is the caster only because the context needs one: no kind
    # :func:`_cast_time_gate` admits reads it.
    return evaluate_condition(
        game, OracleExecutionContext(caster=caster, target=caster, card=card), gate,
    )


# "This ability costs {N} less to activate for each <noun phrase>."
# (Sanctum of Tranquil Light.) A *self* reduction on an activated ability, sized
# by a board count rather than printed flat — which is the whole reason it is a
# separate template from the flat taxes ``cost_modifier_lines`` reads: the
# number is not in the text.
_ABILITY_SELF_REDUCTION = re.compile(
    r"this ability costs \{(?P<generic>\d+)\} less to activate for each "
    r"(?P<subject>.+?)\.?$"
)


@dataclass(frozen=True)
class AbilitySelfReduction:
    """"This ability costs {1} less to activate for each Shrine you control."

    *per_each* is the ``permanent_matches_filter`` payload of the printed noun
    phrase, so the count asks the same question of a permanent that every other
    reader of those words asks. A phrase the matcher cannot test is not recorded
    at all — the reduction refuses rather than counting a set it cannot describe,
    because reading a narrowing as satisfied makes the ability cheaper than it
    is, and cheaper is the one direction a cost error must never go.
    """

    generic: int
    per_each: dict


@lru_cache(maxsize=None)
def ability_self_reduction(line: str) -> "AbilitySelfReduction | None":
    """The per-object activation reduction *line* states, if it is one."""
    from .grammar import subject_filter_payload
    from .subject_filters import untestable_filter_keys

    match = _ABILITY_SELF_REDUCTION.match(line.strip().lower())
    if match is None:
        return None
    described = subject_filter_payload(match.group("subject"), plural=True)
    if described is None:
        return None
    if untestable_filter_keys(described):
        # A key the matcher cannot answer would be dropped, and the count would
        # then be taken over a wider set than the card names — a bigger discount
        # than the card gives.
        return None
    return AbilitySelfReduction(int(match.group("generic")), described)


def ability_self_reduction_amount(game, controller_index: int, source) -> int:
    """How much generic mana comes off *source*'s activation cost right now.

    Counted through the control seam and the shared matcher, and read off the
    permanent's *effective* card so an animated or copied permanent is discounted
    on what it currently is — the same rule ``cost_modifiers.ability_cost_tax``
    follows.
    """
    from .handlers._filters import permanent_matches_filter

    total = 0
    # Split into *sentences*, not lines: the reduction is printed inside an
    # activated ability's own line ("{5}{W}: Tap target creature. This ability
    # costs …"), so a line-wise scan only ever sees text beginning with the cost
    # symbols and matches nothing. The claim predicate stays anchored and
    # whole-sentence — the two questions differ exactly as ``cost_modifiers_for``
    # and ``cost_modifiers.cost_modifier_claims_line`` already differ.
    text = (source.effective_card.oracle_text or "").replace("\n", ". ")
    for sentence in text.split("."):
        reduction = ability_self_reduction(sentence)
        if reduction is None:
            continue
        matched = sum(
            1
            for perm in game.controlled_by(controller_index)
            if permanent_matches_filter(perm, reduction.per_each)
        )
        total += reduction.generic * matched
    return total


@dataclass(frozen=True)
class SelfCostReduction:
    """"This spell costs {2}{U} less to cast if …" (Stormwing Entity)."""

    reduction: CostReduction
    condition: str | None = None
    during_your_turn: bool = False
    #: "This spell costs **{X}** less to cast, where X is …" (Volcanic Salvo,
    #: Chandra's Incinerator). The reduction is generic and its size is not in
    #: the text — which is why {X} was refused outright above: a symbol this
    #: table could not compute would have under-charged the spell, and a cost
    #: error in that direction is the one that must never happen. Named here as
    #: the *question* to ask rather than as a number, and answered against the
    #: caster's board or history at CR 601.2f, when the cost is calculated.
    counted: str | None = None
    #: "**If an opponent controls seven or more lands**, this spell costs {6}
    #: less to cast." (Avatar of Fury.) Any condition outside
    #: ``_SELF_CONDITIONS``, as the grammar's own condition reader lowers it —
    #: the payload ``handlers/control_flow.evaluate_condition`` answers for
    #: every intervening-if in the pool, asked here of the caster at CR 601.2f.
    #: None when the reduction is unconditional or gated by a row of the table.
    gate: dict | None = None
    #: "This spell costs {1} less to cast **for each basic land type among
    #: lands you control**." (Stratadon; {2} on Draco.) The count ``reduction``
    #: is taken **once per**: the spec ``handlers/_amounts.evaluate_count``
    #: answers for every other sentence that spends one, read off the caster's
    #: board through the layers at CR 601.2f. A spec rather than a row of
    #: ``_SELF_REDUCTION_COUNTS`` because the phrase is an ordinary noun phrase
    #: in an ordinary count position — the grammar reads it, so a card
    #: counting artifacts instead needs no code. None when the size is printed.
    per_each: dict | None = None


# ``@compilation_cache`` since a reduction may be sized by a count: the spec
# in ``per_each`` comes out of the grammar's lowering, so a caller that swaps
# a piece of that out and back (``tests/engine/test_domain_count.py`` swaps
# the very line that makes a domain count a count of *types*) must be able to
# empty this too — left holding the swapped answer, Stratadon would count
# lands for the rest of the process with every instrument reading green.
@compilation_cache
@lru_cache(maxsize=None)
def self_cost_reduction(oracle_text: str) -> SelfCostReduction | None:
    """The reduction *oracle_text*'s own first line applies to itself, if any."""
    for line in oracle_text.lower().split("\n"):
        # CR 207.2c: "Domain — This spell costs …". An ability word has no
        # rules meaning, and the compiler and the grammar both drop it before
        # they read the line, so this reader has to as well — it is handed the
        # card's text as printed, and an anchored pattern that kept the word
        # would claim the line through one door and never apply it through
        # this one.
        match = _SELF_REDUCTION.match(strip_ability_word(line.strip()))
        if match is None:
            continue
        condition = match.group("condition")
        fronted = match.group("fronted")
        if condition is not None and fronted is not None:
            # Two printed conditions, one in each position: a conjunction
            # nothing here reads, and either half alone is a cheaper spell.
            return None
        condition = fronted if fronted is not None else condition
        gate = None
        if condition is not None:
            key = _SELF_CONDITIONS.get(condition.strip())
            if key is None:
                from .grammar import condition_payload_for

                gate = condition_payload_for(condition)
                if gate is None or not _cast_time_gate(gate):
                    return None
            condition = key
        # "{X} … where X is <count>" (Volcanic Salvo). A generic reduction whose
        # size is a question rather than a number; the pips must be exactly
        # "{X}" and the clause must name a count this table knows, or the line
        # refuses as it always did.
        counted_clause = match.group("counted")
        if counted_clause is not None:
            if match.group("pips").upper() != "{X}":
                return None
            if match.group("per_each") is not None:
                # Two sizes for one reduction; neither alone is the card.
                return None
            counted = _SELF_REDUCTION_COUNTS.get(counted_clause.strip())
            if counted is None:
                return None
            return SelfCostReduction(
                CostReduction(0), condition=condition,
                during_your_turn=bool(match.group("during")), counted=counted,
                gate=gate,
            )
        generic = 0
        colored: dict[str, int] = {}
        for symbol in re.findall(r"\{([^}]+)\}", match.group("pips").upper()):
            if symbol.isdigit():
                generic += int(symbol)
            elif symbol in _MANA_SYMBOLS:
                colored[symbol] = colored.get(symbol, 0) + 1
            else:
                # {X} and the hybrid symbols reduce by an amount this cannot
                # compute; refuse rather than under-charging. A "{X} … where X
                # is <count>" clause is handled above and never reaches here.
                return None
        # "…less to cast **for each basic land type among lands you control**."
        # (Stratadon.) The printed pips are one repetition and the clause says
        # how many. Read by the grammar's per-each reader, and refused when it
        # refuses: a multiplier this could not count would leave the flat
        # reduction standing — a discount the card gives only to a board that
        # earned it.
        per_each = None
        per_each_clause = match.group("per_each")
        if per_each_clause is not None:
            if colored or not generic or condition is not None or gate is not None:
                # A coloured pip repeated per object is CR 118.7b–c's spill
                # arithmetic once per repetition, and a gate beside a
                # multiplier is two riders on one cost; neither is printed and
                # either read alone is a cheaper spell.
                return None
            from .grammar import per_each_count_spec_for

            per_each = per_each_count_spec_for(per_each_clause)
            if per_each is None:
                return None
        return SelfCostReduction(
            reduction=CostReduction(generic, tuple(sorted(colored.items()))),
            condition=condition,
            during_your_turn=match.group("during") is not None,
            gate=gate,
            per_each=per_each,
        )
    return None


def self_reduction_claims_line(line: str) -> bool:
    """Whether *line* is, in its entirety, a self-reduction this can apply."""
    return self_cost_reduction(line.strip()) is not None


# ---------------------------------------------------------------------------
# A spell's own increase, sized by how many targets it chose (CR 601.2f)
# ---------------------------------------------------------------------------

# "This spell costs {1} more to cast for each target beyond the first."
# (Fireball.) / "This spell costs 3 life more to cast for each target."
# (Phyrexian Purge.) The *increase* twin of the self-reduction above, and one
# template rather than two: what differs between the pool's two printings is
# the resource and whether the first target is free, and both of those are
# payload.
#
# It is a **self** tax, so no scan of any battlefield could find it -- exactly
# the split ``engine/cost_modifiers.py``'s header draws between a permanent's
# modifier and a spell's own. And its size is not in the sentence: CR 601.2c
# chooses targets before 601.2f calculates the cost, which is the ordering that
# makes "for each target" answerable at all.
#
# Fireball's half of it used to be a substring test inside
# `mixins/stack/casting.queue_from_hand`, and a literal in parse_coverage's
# `_MIXIN_TEXT_SCANS` claiming it -- one card's sentence written out twice.
# Phyrexian Purge is the second card that shares the shape, which is the bar
# `card_hooks.py` states for staying out of it.
_SELF_PER_TARGET_TAX = re.compile(
    r"^this spell costs (?:\{(?P<generic>\d+)\}|(?P<life>\d+) life) more to "
    r"cast for each target(?P<beyond> beyond the first)?$"
)


@dataclass(frozen=True)
class SelfPerTargetTax:
    """How much more a spell costs itself, per target it chose.

    ``life`` is the resource, not a flag on an amount: CR 118.3b pays a life
    cost with life, and folding it into the generic mana total would let a
    Mountain pay it -- the same reason ``CostModifier.life`` is its own field.

    ``beyond_first`` is Fireball's exemption. Charging its absence would tax the
    first target too, which is a spell costing more than it prints; charging its
    presence where it is not printed is the other direction, and worse.
    """

    amount: int
    life: bool = False
    beyond_first: bool = False

    def owed(self, targets: int) -> int:
        """What *targets* chosen targets cost, in this tax's resource."""
        charged = targets - 1 if self.beyond_first else targets
        return self.amount * max(0, charged)


@lru_cache(maxsize=None)
def self_per_target_tax(oracle_text: str) -> "SelfPerTargetTax | None":
    """The per-target increase *oracle_text* applies to itself, if any.

    Read per line and anchored at both ends, exactly as
    :func:`self_cost_reduction` reads its own: a template found in the middle of
    a longer sentence would be a cost the card does not print.
    """
    for line in oracle_text.lower().split("\n"):
        match = _SELF_PER_TARGET_TAX.match(line.strip().rstrip("."))
        if match is None:
            continue
        generic = match.group("generic")
        return SelfPerTargetTax(
            amount=int(generic if generic is not None else match.group("life")),
            life=generic is None,
            beyond_first=match.group("beyond") is not None,
        )
    return None


def self_per_target_tax_claims_line(line: str) -> bool:
    """Whether *line* is, in its entirety, a per-target increase this charges."""
    return self_per_target_tax(line.strip()) is not None


def _counted_reduction(game, caster_index: int, counted: str) -> int:
    """How large a "where X is …" self-reduction currently is.

    One function per named count, and each is a *different* kind of question:
    one reads the board, the other a turn history. Neither is an
    ``ObjectFilter`` — "total power" is an aggregate rather than a tally, and
    damage dealt this turn is not on any battlefield — which is why they are
    named clauses here rather than routed through ``count_spec``.
    """
    caster = game.players[caster_index]
    if counted == "total_power_you_control":
        # The *computed* power (CR 613), so a pumped or animated permanent
        # counts for what it currently is. Negative power contributes nothing:
        # CR 107.1b has no negative amounts, and a -3/-3 creature must not make
        # the spell cost more.
        return sum(
            max(0, perm.effective_power)
            for perm in game.controlled_by(caster_index)
            if perm.is_creature
        )
    if counted == "noncombat_damage_to_opponents_this_turn":
        # A turn history rather than a board read: the damage is gone the
        # instant it is dealt, so nothing on any battlefield could answer this.
        return int(caster.noncombat_damage_dealt_to_opponents_this_turn)
    return 0


def self_cost_reduction_for_cast(game, caster_index: int, card) -> CostReduction:
    """*card*'s own reduction, if its condition holds as it is being cast."""
    described = self_cost_reduction(card.oracle_text or "")
    if described is None:
        return CostReduction()
    if described.during_your_turn and game.active_player_index != caster_index:
        return CostReduction()
    caster = game.players[caster_index]
    if described.condition == "cast_instant_or_sorcery":
        if not any(
            "instant" in spell.type_line.lower() or "sorcery" in spell.type_line.lower()
            for spell in caster.spells_cast_this_turn
        ):
            return CostReduction()
    elif described.condition == "gained_three_life":
        if caster.life_gained_this_turn < 3:
            return CostReduction()
    # "If you have 3 or less life, …" (Avatar of Hope). Asked now, at CR
    # 601.2f, which is when a cost is calculated — so the AI's affordability
    # read, the client's playable highlight and the cast itself all see the
    # same answer, because all three come through ``cost_reduction_for_cast``.
    if described.gate is not None and not _gate_holds(
        game, caster_index, card, described.gate
    ):
        return CostReduction()
    # "…where X is <count>": the size is asked of the caster now, at CR 601.2f,
    # which is when a cost is calculated — not at announcement and not at
    # resolution, so a creature entering in response does not change what was
    # already paid.
    if described.counted is not None:
        return CostReduction(_counted_reduction(game, caster_index, described.counted))
    # "…for each basic land type among lands you control" (Stratadon, Draco).
    # The same moment and the same reader as the branch above — the cost is
    # being determined, so the count is the caster's board *now*, through the
    # layers (a Blood Moon or a Phantasmal Terrain changes what a land is, and
    # ``evaluate_count`` asks the computed types). CR 601.2f locks the total in
    # once it is determined, so a land lost in response changes nothing.
    # ``reduce_cost`` floors the result at zero: five types take {10} off
    # Draco's {16} and five off Stratadon's {10}, and a reduction larger than
    # the generic component simply stops there.
    if described.per_each is not None:
        from .handlers._amounts import evaluate_count

        repetitions = evaluate_count(game, caster, described.per_each)
        return CostReduction(described.reduction.generic * max(0, repetitions))
    return described.reduction
