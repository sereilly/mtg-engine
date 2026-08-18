"""Counters with no rules meaning of their own (CR 122.1, CR 122.3).

"Put a **page** counter on this artifact" (Mazemind Tome). A counter whose kind
is a word the card invents: nothing in the rules reacts to it, and the only
thing that reads it is the card that put it there. That is exactly why it is
separate from ``engine/pt.py``'s +1/+1 channel and from the loyalty one — those
counters *do* have rules meaning (layer 7d, CR 606), and routing an inert marker
through either would make it change a creature's size or a walker's survival.

One dict on the permanent's metadata, keyed by the printed word. A dict rather
than a field per kind, because the kinds are open: the next set invents another
word and needs no code here.

The counters travel with the permanent and die with it, which CR 400.7 already
gives for free — a permanent that leaves and returns is a new object with no
counters, and nothing has to clear them.
"""

from __future__ import annotations

COUNTERS_KEY = "named_counters"


def counters_on(permanent, kind: str) -> int:
    """How many *kind* counters are on *permanent*."""
    return int((permanent.metadata.get(COUNTERS_KEY) or {}).get(kind, 0))


def add_counters(permanent, kind: str, count: int = 1) -> int:
    """Put *count* counters of *kind* on *permanent*; returns the new total.

    No CR 614 event and no replacement contention, unlike
    ``Game.place_plus1_counters``: a counter with no rules meaning has nothing
    to modify and nothing to trigger on its own. A card that *does* react to one
    reads the total, which is what Mazemind Tome's state trigger does.
    """
    if count <= 0:
        return counters_on(permanent, kind)
    held = dict(permanent.metadata.get(COUNTERS_KEY) or {})
    held[kind] = held.get(kind, 0) + count
    permanent.metadata[COUNTERS_KEY] = held
    return held[kind]


__all__ = ["COUNTERS_KEY", "add_counters", "counters_on"]
