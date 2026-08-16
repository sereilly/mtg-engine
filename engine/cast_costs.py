"""Text-keyed *additional* costs a spell prints in its own text (CR 601.2b).

The same model as ``cast_restrictions.py``, and for the same reason: "As an
additional cost to cast this spell, sacrifice a creature" means the same thing
on every card that prints it, so it is a table keyed by the canonical phrase
rather than four per-card hooks. A new card printed with a known phrase needs no
registration at all.

**What this replaced was not a gap, it was worse than one.** The phrase sat in
``SUPPORTED_SPELL_PATTERNS`` — a substring whitelist whose match produces a
marker instruction with no handler — so Village Rites compiled to "draw two
cards" plus a no-op, reported ``supported``, and cast **for free**: the cost was
claimed, never paid, and nothing in the engine knew the difference. Thrill of
Possibility's discard did not even get the marker. Alpha's Sacrifice and
Metamorphosis escaped only because a *card hook* folded the cost into their
effect, which is why the general form had never been needed.

A cost is not an effect, so none of this is an instruction. The compiler asks
this table whether a line is a cost (which is what stops the line being reported
"too complex"), and ``queue_from_hand`` asks it twice more: once before any
payment, because CR 601.2h says an unpayable cost can't be paid and CR 601.2h's
failure is *the spell can't be cast*, and once after, to perform it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import CardDefinition


@dataclass(frozen=True)
class AdditionalCost:
    """One printed additional cost.

    ``sacrifice_type`` is the noun the sacrifice must match — never ``None``
    meaning "anything", the way ``ActivatedAbilityCost.sacrifice_type`` is not:
    an empty filter would let the payment be a land.
    """

    phrase: str
    sacrifice_type: str | None = None
    discard_cards: int = 0

    def describe(self) -> str:
        if self.sacrifice_type:
            return f"sacrifice a {self.sacrifice_type}"
        return f"discard {self.discard_cards} card(s)"


# Canonical lowercase phrases, matched against a whole normalized line. Both
# shapes the pool prints; a third goes here beside them.
ADDITIONAL_COSTS: tuple[AdditionalCost, ...] = (
    AdditionalCost(
        "as an additional cost to cast this spell, sacrifice a creature",
        sacrifice_type="creature",
    ),
    AdditionalCost(
        "as an additional cost to cast this spell, discard a card",
        discard_cards=1,
    ),
)


def additional_cost_for_line(line: str) -> AdditionalCost | None:
    """The cost *line* states, or None when it states none.

    Matched on the line's whole text (minus a trailing period) rather than as a
    substring, because a substring match is how the whitelist this replaced came
    to claim things it did not implement.
    """
    text = line.strip().lower().rstrip(".")
    for cost in ADDITIONAL_COSTS:
        if text == cost.phrase:
            return cost
    return None


def additional_costs(card: CardDefinition) -> tuple[AdditionalCost, ...]:
    """Every additional cost *card* prints, in printed order."""
    found = [
        cost
        for line in (card.oracle_text or "").split("\n")
        if (cost := additional_cost_for_line(line)) is not None
    ]
    return tuple(found)


def cast_cost_claims_line(line: str) -> bool:
    """Whether this table reads *line*.

    The support gate and the parse-coverage report both ask this, so what the
    engine implements and what it claims to have read cannot drift — the same
    seam ``enter_effects.enter_effect_line`` is.
    """
    return additional_cost_for_line(line) is not None


__all__ = [
    "ADDITIONAL_COSTS",
    "AdditionalCost",
    "additional_cost_for_line",
    "additional_costs",
    "cast_cost_claims_line",
]
