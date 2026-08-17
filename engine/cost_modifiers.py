"""Text-keyed cost modification (CR 601.2f, 118.9).

"White spells cost {3} more to cast." / "Activated abilities of white
enchantments cost {3} more to activate." — Gloom's wording, and a template
Magic reprints constantly with different colours, types and amounts. The tax is
derived from oracle text here rather than registered per card name, so a card
printed with one of these templates needs no registration.

Each modifier is a filter plus an amount. The filter says which spells (or which
permanents' abilities) are taxed; the amount is added to the generic part of the
cost, once per taxing permanent on any battlefield — two Glooms tax {6}.

**Reductions** ("costs {1} less to cast") arrived with the cards that needed
them, which is what this file's scope note used to promise: Watcher of the
Spheres taxes downward from a permanent, and Stormwing Entity reduces *its own*
cost. They are not increases with a minus sign — CR 118.7a–d says a generic
reduction touches only the generic component, a coloured one falls back to
generic where the cost has no mana of that colour, and an excess coloured
reduction spills the difference onto generic. That arithmetic is
:func:`reduce_cost`, in one place, because getting it wrong makes a spell
castable that is not.

Two shapes, and they are genuinely different mechanisms rather than one with a
scope flag. A **permanent's** modifier is a board effect: it is found by
scanning battlefields and it applies to other objects. A **spell's own**
reduction is a property of the card being cast, read off its own text and gated
on a condition about the caster's turn — no permanent is involved, so no scan
would find it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from .oracle_types import _COLOR_WORD_TO_SYMBOL

# Card types a cost modifier can name. "spell" is the unfiltered form; the "non"
# forms are the printed negation (Vryn Wingmare), not a separate mechanism.
_TYPES = "noncreature|artifact|creature|enchantment|instant|sorcery|land"
_COLOURS = "|".join(_COLOR_WORD_TO_SYMBOL)
_MANA_SYMBOLS = frozenset({"W", "U", "B", "R", "G", "C"})


@dataclass(frozen=True)
class CostModifier:
    """A cost change this permanent applies to other objects.

    amount     -- generic mana added to (or, when *reduces*, taken off) each
                  affected cost
    applies_to -- "cast" for spells, "activate" for activated abilities
    reduces    -- whether this takes mana off rather than adding it
    colour     -- mana symbol the affected object must have, or None for any
    card_type  -- card type the affected object must have, or None for any;
                  a "non"-prefixed name excludes instead of requiring
    keyword    -- keyword the affected object must have, or None for any
    controller -- "you" when the modifier says "you cast", or None for anyone's
    """

    amount: int
    applies_to: str
    reduces: bool = False
    colour: str | None = None
    card_type: str | None = None
    keyword: str | None = None
    controller: str | None = None


@dataclass(frozen=True)
class CostReduction:
    """How much comes off a cost, split the way CR 118.7 splits it."""

    generic: int = 0
    colored: tuple[tuple[str, int], ...] = ()

    def __bool__(self) -> bool:
        return bool(self.generic or self.colored)


# "<colour>? <type>? spells [with <keyword>] [you cast] cost {N} more/less to cast"
_SPELL_TAX = re.compile(
    rf"(?:(?P<colour>{_COLOURS}) )?(?:(?P<type>{_TYPES}) )?spells"
    r"(?: with (?P<keyword>[a-z]+))?(?P<controller> you cast)? cost "
    r"\{(?P<amount>\d+)\} (?P<direction>more|less) to cast"
)

# "activated abilities of <colour>? <type>s cost {N} more to activate"
_ABILITY_TAX = re.compile(
    rf"activated abilities of (?:(?P<colour>{_COLOURS}) )?(?P<type>{_TYPES})s? cost "
    r"\{(?P<amount>\d+)\} more to activate"
)


@lru_cache(maxsize=None)
def cost_modifiers_for(oracle_text: str) -> tuple[CostModifier, ...]:
    """Every cost modifier *oracle_text* grants. Cached on the text, which is
    immutable on a CardDefinition, so the per-permanent scan on each cast stays
    as cheap as the name-keyed lookup it replaced."""
    text = oracle_text.lower()
    if "more to" not in text and "less to" not in text:
        return ()
    modifiers: list[CostModifier] = []
    for match in _SPELL_TAX.finditer(text):
        modifiers.append(
            CostModifier(
                amount=int(match.group("amount")),
                applies_to="cast",
                reduces=match.group("direction") == "less",
                colour=_COLOR_WORD_TO_SYMBOL.get(match.group("colour") or ""),
                card_type=match.group("type"),
                keyword=match.group("keyword"),
                controller="you" if match.group("controller") else None,
            )
        )
    for match in _ABILITY_TAX.finditer(text):
        modifiers.append(
            CostModifier(
                amount=int(match.group("amount")),
                applies_to="activate",
                colour=_COLOR_WORD_TO_SYMBOL.get(match.group("colour") or ""),
                card_type=match.group("type"),
            )
        )
    return tuple(modifiers)


def cost_modifier_claims_line(line: str) -> bool:
    """Whether *line* is, in its entirety, one of the templates above.

    ``cost_modifiers_for`` scans for the templates anywhere in a card's text,
    which is what a tax needs — the clause can sit in any sentence. This asks
    the stricter question the grammar needs: does the template account for the
    *whole* line, leaving nothing over? "White spells cost {3} more to cast."
    does; "This spell costs {1} more to cast for each target beyond the first."
    matches no template at all (Fireball's surcharge is applied in
    mixins/stack/ instead).

    A spell's own reduction is claimed here too, from the same reading: what
    makes a line supported is that a table implements it end to end, and both
    tables live in this module.
    """
    text = line.strip().lower().rstrip(".")
    if ability_self_reduction(line) is not None:
        return True
    if any(
        (match := pattern.match(text)) is not None and match.end() == len(text)
        for pattern in (_SPELL_TAX, _ABILITY_TAX)
    ):
        return True
    return self_reduction_claims_line(line)


def _matches(modifier: CostModifier, card) -> bool:
    if modifier.colour and modifier.colour not in (card.colors or ()):
        return False
    if modifier.card_type:
        # "Noncreature spells" is the printed negation of the same word, so it
        # is read as one rather than as a type of its own — the type line is
        # asked the same question and the answer is inverted.
        wanted = modifier.card_type
        negated = wanted.startswith("non")
        if negated:
            wanted = wanted[3:]
        if (wanted in card.type_line.lower()) == negated:
            return False
    if modifier.keyword and modifier.keyword not in {
        word.lower() for word in (card.keywords or ())
    }:
        return False
    return True


def _tax(
    game, card, applies_to: str, *, wanted: str, controller_index: int | None = None
) -> tuple[int, list[str]]:
    """The total *wanted* ("more" or "less") change to *card*'s cost from every
    permanent on any battlefield, and those permanents' names for the log.

    One application per permanent — two Glooms tax {6} — and the scan covers
    every battlefield, because a cost modifier is not scoped to its own
    controller's side unless the card says so.
    """
    total = 0
    names: list[str] = []
    for seat, permanent in game.permanents_with_controller():
        # effective_card: a colour word rewritten by Sleight of Mind (CR 613
        # layer 3) changes which spells this taxes, and the tax table should
        # not have to know that text can change.
        for modifier in cost_modifiers_for(permanent.effective_card.oracle_text):
            if modifier.applies_to != applies_to or not _matches(modifier, card):
                continue
            if modifier.reduces != (wanted == "less"):
                continue
            # "…**you cast**" (Watcher of the Spheres) is the modifier's own
            # controller (CR 109.5), so it needs the seat casting the spell.
            if modifier.controller == "you" and (
                controller_index is None or seat != controller_index
            ):
                continue
            total += modifier.amount
            names.append(permanent.card.name)
    return total, names


def spell_cost_tax(game, caster_index: int, card) -> tuple[int, list[str]]:
    """Extra generic mana for casting *card*, plus the taxing permanents' names."""
    return _tax(game, card, "cast", wanted="more", controller_index=caster_index)


def spell_cost_reduction(game, caster_index: int, card) -> tuple[CostReduction, list[str]]:
    """What comes off *card*'s cost from permanents on the battlefield.

    Generic only: a permanent's modifier is printed as ``{N}``, so the regex
    reads a number. A coloured reduction from a permanent would be a new
    spelling, and :func:`reduce_cost` already knows what to do with one.
    """
    generic, names = _tax(
        game, card, "cast", wanted="less", controller_index=caster_index
    )
    return CostReduction(generic), names


def ability_cost_tax(game, controller_index: int, source) -> tuple[int, list[str]]:
    """Extra generic mana for activating *source*'s ability, plus the taxing
    permanents' names. Matched against the source's *effective* card so a
    copied or animated permanent is taxed on what it currently is."""
    return _tax(
        game, source.effective_card, "activate", wanted="more",
        controller_index=controller_index,
    )


# ---------------------------------------------------------------------------
# A spell's own reduction (CR 601.2f), and the arithmetic every reduction uses
# ---------------------------------------------------------------------------


# "[During your turn, ]this spell costs {…} less to cast[ if <condition>]."
_SELF_REDUCTION = re.compile(
    r"(?:(?P<during>during your turn), )?this spell costs (?P<pips>(?:\{[^}]+\})+) "
    r"less to cast(?: if (?P<condition>[^.]+))?\.?$"
)

# The conditions a self-reduction may be gated on, mapped to the question the
# caster's own state answers. A wording outside this table refuses the line —
# reading an unrecognized condition as "true" would make the spell cheaper than
# it is, which is the one direction a cost error must never go.
_SELF_CONDITIONS: dict[str, str] = {
    "you've cast an instant or sorcery spell this turn": "cast_instant_or_sorcery",
    "you've gained 3 or more life this turn": "gained_three_life",
}


# "This ability costs {N} less to activate for each <noun phrase>."
# (Sanctum of Tranquil Light.) A *self* reduction on an activated ability, sized
# by a board count rather than printed flat — which is the whole reason it is a
# separate template from the flat taxes above: the number is not in the text.
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
    from .subject_filters import TESTABLE_SUBJECT_FILTER_KEYS

    match = _ABILITY_SELF_REDUCTION.match(line.strip().lower())
    if match is None:
        return None
    described = subject_filter_payload(match.group("subject"), plural=True)
    if described is None:
        return None
    if set(described) - set(TESTABLE_SUBJECT_FILTER_KEYS):
        # A key the matcher cannot answer would be dropped, and the count would
        # then be taken over a wider set than the card names — a bigger discount
        # than the card gives.
        return None
    return AbilitySelfReduction(int(match.group("generic")), described)


def ability_self_reduction_amount(game, controller_index: int, source) -> int:
    """How much generic mana comes off *source*'s activation cost right now.

    Counted through the control seam and the shared matcher, and read off the
    permanent's *effective* card so an animated or copied permanent is discounted
    on what it currently is — the same rule ``ability_cost_tax`` follows one
    function above.
    """
    from .handlers._common import permanent_matches_filter

    total = 0
    # Split into *sentences*, not lines: the reduction is printed inside an
    # activated ability's own line ("{5}{W}: Tap target creature. This ability
    # costs …"), so a line-wise scan only ever sees text beginning with the cost
    # symbols and matches nothing. The claim predicate stays anchored and
    # whole-sentence — the two questions differ exactly as ``cost_modifiers_for``
    # and ``cost_modifier_claims_line`` already differ above.
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


@lru_cache(maxsize=None)
def self_cost_reduction(oracle_text: str) -> SelfCostReduction | None:
    """The reduction *oracle_text*'s own first line applies to itself, if any."""
    for line in oracle_text.lower().split("\n"):
        match = _SELF_REDUCTION.match(line.strip())
        if match is None:
            continue
        condition = match.group("condition")
        if condition is not None:
            key = _SELF_CONDITIONS.get(condition.strip())
            if key is None:
                return None
            condition = key
        generic = 0
        colored: dict[str, int] = {}
        for symbol in re.findall(r"\{([^}]+)\}", match.group("pips").upper()):
            if symbol.isdigit():
                generic += int(symbol)
            elif symbol in _MANA_SYMBOLS:
                colored[symbol] = colored.get(symbol, 0) + 1
            else:
                # {X} and the hybrid symbols reduce by an amount this cannot
                # compute; refuse rather than under-charging.
                return None
        return SelfCostReduction(
            reduction=CostReduction(generic, tuple(sorted(colored.items()))),
            condition=condition,
            during_your_turn=match.group("during") is not None,
        )
    return None


def self_reduction_claims_line(line: str) -> bool:
    """Whether *line* is, in its entirety, a self-reduction this can apply."""
    return self_cost_reduction(line.strip()) is not None


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
    return described.reduction


def cost_reduction_for_cast(
    game, caster_index: int, card
) -> tuple[CostReduction, list[str]]:
    """Everything that comes off *card*'s cost as *caster_index* casts it.

    The two mechanisms meet here and nowhere else: a permanent's modifier, found
    by scanning battlefields, and the spell's own, read off its text. One
    function because two callers need the answer — the cast path and the AI's
    affordability read — and a discount only one of them can see is a spell the
    AI declines to cast or tries to cast and cannot.
    """
    board, names = spell_cost_reduction(game, caster_index, card)
    own = self_cost_reduction_for_cast(game, caster_index, card)
    combined = CostReduction(
        board.generic + own.generic,
        tuple(sorted((dict(board.colored) | dict(own.colored)).items())),
    )
    if own and not names:
        names = [card.name]
    return combined, names


def reduce_cost(required: dict[str, int], reduction: CostReduction) -> dict[str, int]:
    """Apply *reduction* to a parsed cost, per CR 118.7a–d.

    - 118.7a a generic reduction touches only the generic component;
    - 118.7b a coloured reduction against a cost with no mana of that colour
      comes off generic instead;
    - 118.7c a coloured reduction larger than that colour's component takes it
      to nothing and the difference comes off generic.

    Nothing goes below zero (CR 601.2f). Written as one function because these
    four sentences are the whole of what a reduction *is*, and a caller doing
    the subtraction itself is a caller that will get 118.7b wrong.
    """
    cost = dict(required)
    for symbol, amount in reduction.colored:
        paid = min(cost.get(symbol, 0), amount)
        cost[symbol] = cost.get(symbol, 0) - paid
        spill = amount - paid
        if spill:
            cost["generic"] = max(0, cost.get("generic", 0) - spill)
    cost["generic"] = max(0, cost.get("generic", 0) - reduction.generic)
    return cost
