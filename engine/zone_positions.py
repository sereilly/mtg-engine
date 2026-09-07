"""Which end of an ordered zone the printed word "top" names.

Two zones in this engine are ordered lists of cards, and **they disagree about
which end of the list is the top**:

* a **library** is drawn from the front — ``PlayerState.draw`` is
  ``library.pop(0)`` — so the printed top card is ``library[0]`` (CR 121.1: a
  draw takes the top card of the library, and CR 401.2 is why that order means
  something);
* a **graveyard** is appended to — CR 404.1 puts every arriving object *on top*
  of its owner's graveyard, and this engine appends — so the printed top card is
  ``graveyard[-1]``.

Nothing in the code makes that difference visible at a call site. ``zone[0]``
and ``zone[-1]`` are both perfectly ordinary expressions, and a reader written
for one zone and later pointed at the other keeps working, silently naming the
wrong card. That is the whole reason this module exists: one table, so "the top
card of your ⟨zone⟩" is asked once and answered once, and a card printed about a
library's top card reaches the same reader a card printed about a graveyard's
does.

Positions rather than a card, for :mod:`engine.graveyard_order`'s reason: a zone
holds ``CardDefinition`` objects and ``load_cards`` dedupes by ``oracle_id``, so
two copies of one card in one zone are the **same Python object** and a caller
handed only the card cannot say which copy it named. :func:`top_index` is the
answer; :func:`top_card` is the convenience over it for the readers that only
want to look.
"""

from __future__ import annotations

from typing import Any

#: The zone names this module can be asked about, mapped to the list index the
#: printed word "top" refers to. A zone absent from here raises rather than
#: guessing: guessing is exactly the failure above, and the two candidate
#: answers are each other's opposite.
TOP_INDEX: dict[str, int] = {
    # CR 121.1 — a draw takes the top card, and ``PlayerState.draw`` pops
    # index 0.
    "library": 0,
    # CR 404.1 — an arriving object is put on top, and this engine appends.
    "graveyard": -1,
}

#: The zones an ordered-position phrase may name, for a caller validating a
#: parsed word before it builds a payload out of it.
ORDERED_ZONES = frozenset(TOP_INDEX)


def top_index(zone: str, cards: list) -> int | None:
    """The index of the top card of *cards*, or None when the zone is empty.

    *zone* is one of :data:`ORDERED_ZONES`; anything else is a programming
    error and raises, because both plausible answers are wrong half the time.
    """
    if zone not in TOP_INDEX:
        raise KeyError(f"no ordered position defined for zone {zone!r}")
    if not cards:
        return None
    return TOP_INDEX[zone] % len(cards)


def top_card(zone: str, cards: list) -> Any | None:
    """The top card of *cards*, or None when the zone is empty."""
    index = top_index(zone, cards)
    return None if index is None else cards[index]


def zone_cards(player: Any, zone: str) -> list:
    """The list *player* keeps *zone* in.

    Through ``getattr`` on the validated name rather than a second mapping:
    :data:`TOP_INDEX`'s keys are the ``PlayerState`` attribute names, so a zone
    this module admits is one it can also fetch, and adding a third ordered zone
    is one row.
    """
    if zone not in TOP_INDEX:
        raise KeyError(f"no ordered position defined for zone {zone!r}")
    return getattr(player, zone)


__all__ = ["ORDERED_ZONES", "TOP_INDEX", "top_card", "top_index", "zone_cards"]
