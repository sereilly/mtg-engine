"""The mana a cost was paid with, remembered on the permanent that charged it.

"Note the type of mana spent to pay this activation cost." (Jeweled Amulet.)
"…note the type **and amount** of mana spent to pay this activation cost."
(Ice Cauldron.) CR 107.4b's mana symbols are the record: what the ability adds
later is not "a mana" but *that* mana, and nothing in the game state answers the
question after the pool has emptied (CR 500.4).

**The record hangs off the permanent, not off the seat.** The card says "**this
artifact's** last noted type", so two copies of the same artifact each remember
their own payment, and a permanent that leaves takes its note with it (CR 400.7
— the one that comes back is a new object with nothing noted). That is why this
is a store keyed by permanent, the same shape ``engine/named_counters.py`` has
and for the same reason.

The record is a symbol dict, exactly like every mana cost and every mana pool in
this engine — so "the type" and "the type and amount" are the same record read
two ways rather than two records, and the difference is entirely in what the
*adding* ability does with it.
"""

from __future__ import annotations

#: Where the note lives on a ``Permanent``. Named once, because two modules read
#: it and a second spelling of the string is how they come apart.
_KEY = "noted_mana"


def note_mana_spent(permanent, spent: dict[str, int]) -> None:
    """Record what a payment cost, replacing whatever was noted before.

    "**Last** noted type" is the printed word: a second activation overwrites
    the first rather than adding to it. A payment of nothing is still a note —
    of nothing — because an ability activated for free noted no type, and the
    adding ability then has none to add.
    """
    if permanent is None:
        return
    permanent.metadata[_KEY] = {
        symbol: int(count) for symbol, count in spent.items() if int(count) > 0
    }


def noted_mana(permanent) -> dict[str, int]:
    """What *permanent* last noted, as a symbol dict. Empty when nothing was."""
    if permanent is None:
        return {}
    return dict(permanent.metadata.get(_KEY) or {})


def noted_mana_types(permanent) -> tuple[str, ...]:
    """The *types* noted, without their counts — "one mana of this artifact's
    last noted type" (Jeweled Amulet).

    Sorted so the answer is deterministic when a payment spent more than one
    kind; the card that reads this is charged a single generic pip, so the pool
    holds one type in every game the pool can produce.
    """
    return tuple(sorted(noted_mana(permanent)))


__all__ = ["note_mana_spent", "noted_mana", "noted_mana_types"]
