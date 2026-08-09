"""Text-keyed cost modification (CR 601.2f, 118.9).

"White spells cost {3} more to cast." / "Activated abilities of white
enchantments cost {3} more to activate." — Gloom's wording, and a template
Magic reprints constantly with different colours, types and amounts. The tax is
derived from oracle text here rather than registered per card name, so a card
printed with one of these templates needs no registration.

Each modifier is a filter plus an amount. The filter says which spells (or which
permanents' abilities) are taxed; the amount is added to the generic part of the
cost, once per taxing permanent on any battlefield — two Glooms tax {6}.

Scope: **increases only**. Cost reduction ("costs {1} less to cast") is at least
as common in later sets, but it clamps at zero and interacts with alternative
costs, and there is no card in the current pool to verify an implementation
against. Adding it should come with the card that needs it, not before.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from .oracle_types import _COLOR_WORD_TO_SYMBOL

# Card types a cost modifier can name. "spell" is the unfiltered form.
_TYPES = "artifact|creature|enchantment|instant|sorcery|land"
_COLOURS = "|".join(_COLOR_WORD_TO_SYMBOL)


@dataclass(frozen=True)
class CostModifier:
    """A tax this permanent applies.

    amount     -- generic mana added to each affected cost
    applies_to -- "cast" for spells, "activate" for activated abilities
    colour     -- mana symbol the affected object must have, or None for any
    card_type  -- card type the affected object must have, or None for any
    """

    amount: int
    applies_to: str
    colour: str | None = None
    card_type: str | None = None


# "<colour>? <type>? spells cost {N} more to cast"
_SPELL_TAX = re.compile(
    rf"(?:(?P<colour>{_COLOURS}) )?(?:(?P<type>{_TYPES}) )?spells cost "
    r"\{(?P<amount>\d+)\} more to cast"
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
    if "more to" not in oracle_text.lower():
        return ()
    text = oracle_text.lower()
    modifiers: list[CostModifier] = []
    for match in _SPELL_TAX.finditer(text):
        modifiers.append(
            CostModifier(
                amount=int(match.group("amount")),
                applies_to="cast",
                colour=_COLOR_WORD_TO_SYMBOL.get(match.group("colour") or ""),
                card_type=match.group("type"),
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
    mixins/stack_casting.py instead).
    """
    text = line.strip().lower().rstrip(".")
    return any(
        (match := pattern.match(text)) is not None and match.end() == len(text)
        for pattern in (_SPELL_TAX, _ABILITY_TAX)
    )


def _matches(modifier: CostModifier, card) -> bool:
    if modifier.colour and modifier.colour not in (card.colors or ()):
        return False
    if modifier.card_type and modifier.card_type not in card.type_line.lower():
        return False
    return True


def _tax(game, card, applies_to: str) -> tuple[int, list[str]]:
    """Total tax on *card* from every taxing permanent on any battlefield, and
    the taxing permanents' names for the log. One application per permanent."""
    total = 0
    names: list[str] = []
    for permanent in game.all_permanents():
        for modifier in cost_modifiers_for(permanent.card.oracle_text):
            if modifier.applies_to != applies_to or not _matches(modifier, card):
                continue
            total += modifier.amount
            names.append(permanent.card.name)
    return total, names


def spell_cost_tax(game, caster_index: int, card) -> tuple[int, list[str]]:
    """Extra generic mana for casting *card*, plus the taxing permanents' names."""
    return _tax(game, card, "cast")


def ability_cost_tax(game, controller_index: int, source) -> tuple[int, list[str]]:
    """Extra generic mana for activating *source*'s ability, plus the taxing
    permanents' names. Matched against the source's *effective* card so a
    copied or animated permanent is taxed on what it currently is."""
    return _tax(game, source.effective_card, "activate")
