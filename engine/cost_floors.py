"""A floor under a spell's total cost (CR 601.2f, its last step).

"As long as this artifact is untapped, each spell that would cost less than
three mana to cast costs three mana to cast." (Trinisphere.) Not a tax and not
a reduction: CR 601.2f determines the total cost — "the mana cost or
alternative cost …, plus all additional costs and cost increases, and minus
all cost reductions" — and only then "any effects that directly affect the
total cost are applied", before the total is locked in. Trinisphere is one of
those. Its 2020-08-07 ruling says the same in order: "start with the mana cost
or alternative cost you're paying, add any cost increases, then apply any cost
reductions. Finally, apply Trinisphere's effect if the mana component of the
spell's cost is less than three mana."

So the floor is asked of the **finished** total and of nothing earlier, which
is why it is a function over a cost dict rather than a ``CostModifier``: a
modifier is summed into the total, and a floor summed in would be a tax of
three on every spell. The difference it adds is generic mana — the card's own
reminder ("Additional mana in the cost may be paid with any color of mana or
colorless mana. For example, a spell that would cost {1}{B} to cast costs
{2}{B} to cast instead.") — and it reaches every spell whatever its cost was
made of: an {X} counted at the X announced (CR 107.3), an alternative cost, and
"without paying its mana cost", which CR 118.9 calls an alternative cost too
(a total of {0}, raised to {3}). The spell's mana value is untouched (the same
ruling), because nothing here touches its mana cost.

**Every reader of a cast's price asks it**, for the reason
``cost_modifiers.cast_mana_charge`` gives for being one reader: the payment
(``pool_payment._pay_cast_cost``, the one funnel the three cast branches pay
through), the price the client is shown (``cast_mana_charge``,
``Game.alternative_cost_mana``) and the AI's affordability read
(``ai_payment``). A floor only the payment knew is a one-mana spell the AI
proposes with two lands and the cast refuses, every turn.

The condition is read off the source at the moment the price is asked: an
untapped Trinisphere imposes it and a tapped one does not. The ruling's other
half — Trinisphere tapped or untapped *as a cost* of the very spell is still
counted as it stood, the total being locked in first — is the order this
engine pays in already: the total is determined, then mana is spent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from .oracle_types import _NUMBER_WORDS

#: The printed line, lowercased, reminder text and full stop gone
#: (``line_normalization.normalize_creature_line``). The threshold and the
#: amount are one number printed twice; a card printing two different numbers
#: is a sentence this does not read, so the backreference refuses it. The
#: "as long as this <noun> is untapped" prefix is optional, so a printing that
#: imposes the floor unconditionally needs no row.
_FLOOR = re.compile(
    r"^(?:as long as this (?P<noun>artifact|creature|enchantment|permanent) "
    r"is untapped, )?each spell that would cost less than (?P<count>[a-z]+) "
    r"mana to cast costs (?P=count) mana to cast$"
)


@dataclass(frozen=True)
class CostFloor:
    """One printed floor: the least total a spell may cost, and whether the
    source must be untapped for it to apply."""

    amount: int
    while_untapped: bool = False


def cost_floor_for_line(normalized_line: str) -> CostFloor | None:
    """The floor *normalized_line* imposes in full, or None."""
    match = _FLOOR.match(normalized_line.strip().rstrip("."))
    if match is None:
        return None
    amount = _NUMBER_WORDS.get(match.group("count"))
    if not amount:
        # An unreadable number word refuses: a floor read as zero is a static
        # that never applies while its card reports supported.
        return None
    return CostFloor(int(amount), while_untapped=match.group("noun") is not None)


@lru_cache(maxsize=None)
def _floors_in_text(oracle_text: str) -> tuple[CostFloor, ...]:
    """Every floor *oracle_text* prints, one per line — cached on the text,
    which is immutable on a ``CardDefinition``, so the per-permanent scan on
    each price stays cheap."""
    if "would cost less than" not in (oracle_text or "").lower():
        return ()
    from .line_normalization import normalize_creature_line

    found = []
    for line in (oracle_text or "").splitlines():
        floor = cost_floor_for_line(normalize_creature_line(line))
        if floor is not None:
            found.append(floor)
    return tuple(found)


def spell_cost_floor(game) -> tuple[int, list[str]]:
    """The highest floor in force over a spell's total cost right now, and
    the names of the permanents imposing it (for the log).

    "**Each** spell": every caster's, so no seat is asked. Read through the
    control seam and each permanent's effective text, so a floor whose
    abilities are gone (CR 613.1f) is no floor. Two floors do not add — the
    higher is the one every spell under both must meet.
    """
    best = 0
    names: list[str] = []
    for _seat, permanent in game.permanents_with_controller():
        for floor in _floors_in_text(permanent.effective_card.oracle_text or ""):
            if floor.while_untapped and permanent.tapped:
                continue
            if floor.amount > best:
                best, names = floor.amount, [permanent.effective_card.name]
            elif floor.amount == best:
                names.append(permanent.effective_card.name)
    return best, names


def apply_cost_floor(cost: dict[str, int], floor: int) -> dict[str, int]:
    """*cost* raised to a mana component of *floor*, the difference in
    generic mana; unchanged when it already meets it."""
    total = sum(max(0, int(amount)) for amount in cost.values())
    if floor <= 0 or total >= floor:
        return cost
    raised = dict(cost)
    raised["generic"] = int(raised.get("generic", 0)) + (floor - total)
    return raised


def floored_spell_cost(game, cost: dict[str, int]) -> dict[str, int]:
    """*cost* — a spell's finished total — under every floor in force."""
    floor, _names = spell_cost_floor(game)
    return apply_cost_floor(cost, floor)


__all__ = [
    "CostFloor",
    "apply_cost_floor",
    "cost_floor_for_line",
    "floored_spell_cost",
    "spell_cost_floor",
]
