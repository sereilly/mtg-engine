"""Which permanent a seat sacrifices when the effect reads what it ate.

"As an additional cost to cast this spell, sacrifice an artifact. Put X +1/+1
counters on target creature, where X is the sacrificed artifact's mana value."
(Forge Armor.) A seat that names no victim pays with the engine's
deterministic pick (``Game.default_sacrifice_pick``: the smallest power
first), which is right for a cost that is only a price and wrong for one the
effect is measured by — Forge Armor gave up a Great Furnace and put no counter
anywhere, beside a four-mana artifact that would have made it four. Six cast
cards read the cost this way (Burnt Offering, Carrion, Fling, Forge Armor,
Metamorphosis, Worthy Cause), all through one payload key
(``x_from_count.cost_sacrifice_characteristic``), so the reading is the key's
and names no card.

What the victim is *worth* is not decided here: the candidates are the
distinct readings the board offers — one permanent per value of the
characteristic, the cheapest to lose among equals — and the cast chooser
rehearses each (``ai_casts._cast_naming_its_sacrifice``). A tie keeps the
cheaper permanent, so a board where the reading cannot matter pays as the
default always paid.
"""

from __future__ import annotations

from .ai_standing import permanent_worth
from .ai_weighed_cast import _effect_steps
from .models import Permanent

#: The payload key a count spec reads the sacrificed permanent through
#: (``handlers/_amounts.py``), and the characteristics it names.
SACRIFICE_READ_KEY = "cost_sacrifice_characteristic"

#: How many distinct readings a cast is rehearsed at, the largest first.
#: Tuning: each is a rehearsal of the whole turn, and a limited board rarely
#: offers more distinct values than this.
VICTIM_READINGS_WEIGHED = 4


def characteristic_read_off_the_sacrifice(instructions) -> str | None:
    """The characteristic ("mana_value", "power", "toughness") *instructions*
    read off the permanent their sacrifice cost ate, or None when no step
    does. Wrappers opened, so "you may …" and a sequence read the same."""
    for instruction in instructions or ():
        if instruction is None:
            continue
        for step in (instruction, *_effect_steps(instruction)):
            for value in (step.payload or {}).values():
                if isinstance(value, dict) and value.get(SACRIFICE_READ_KEY):
                    return str(value[SACRIFICE_READ_KEY])
    return None


def sacrificed_reading(permanent: Permanent, characteristic: str) -> int:
    """What *characteristic* reads off *permanent* if it is sacrificed now —
    the handler's own read (``handlers/_amounts.py``): a mana value off the
    card, power and toughness off the permanent as layer 7 has them."""
    if characteristic == "mana_value":
        return int(getattr(permanent.card, "cmc", 0) or 0)
    return int(getattr(permanent, f"effective_{characteristic}", 0) or 0)


def victims_to_weigh(
    candidates: "list[Permanent]", characteristic: str, sacrifice_key,
) -> "list[Permanent]":
    """One permanent per distinct reading of *characteristic* among
    *candidates*: the one cheapest to lose (its lasting worth, then
    *sacrifice_key* — ``Game.sacrifice_preference_key``), at most
    :data:`VICTIM_READINGS_WEIGHED` readings, the largest kept. Returned
    cheapest first, so a caller keeping the first of equal results keeps the
    cheaper permanent."""
    cheapest: dict[int, Permanent] = {}

    def cost(permanent) -> tuple:
        return (permanent_worth(permanent, now=False), sacrifice_key(permanent))

    for permanent in candidates:
        reading = sacrificed_reading(permanent, characteristic)
        held = cheapest.get(reading)
        if held is None or cost(permanent) < cost(held):
            cheapest[reading] = permanent
    kept = [cheapest[reading] for reading in sorted(cheapest, reverse=True)]
    return sorted(kept[:VICTIM_READINGS_WEIGHED], key=cost)


__all__ = [
    "SACRIFICE_READ_KEY",
    "VICTIM_READINGS_WEIGHED",
    "characteristic_read_off_the_sacrifice",
    "sacrificed_reading",
    "victims_to_weigh",
]
