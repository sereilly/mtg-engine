"""What a seat's lands produce instead, while an effect says so (CR 611.2).

``Permanent.metadata["produced_mana_swaps"]`` is the other half of this idea and
it is deliberately not this one. That record names *one land* and one symbol
("If target Plains is tapped for mana, it produces colorless mana instead of
white mana" — Quarum Trench Gnomes), so it lives on the permanent it changes and
dies with it (CR 400.7). Deep Water's sentence — "Until end of turn, if you tap
a land you control for mana, it produces {U} instead of any other type" — names
a **class** and a **window**:

- the class includes lands that have not entered the battlefield yet, so there
  is no permanent to write it on and nothing to update when one arrives;
- which lands a seat controls is answered when a land is tapped, not when the
  ability resolved, so a record stamped on the board at resolution would be
  wrong the moment control changed;
- "until end of turn" needs a sweep, and the per-permanent record has none.

So the record hangs off the **player**, exactly as ``engine/shields.py`` and
``engine/damage_redirects.py`` hang theirs — an attribute rather than a
``PlayerState`` field, so a new kind of swap needs no new field and no new
clearing line, and the cleanup step's one call expires it.

**Where it is read** is the tap seam, ``Game.tap_land_for_mana``, and the
payment planner. It cannot be read by ``Permanent.effective_produced_mana``:
that is a property with no game, so it cannot ask who controls the land — and
the property is bypassed anyway on any land with a compiled mana ability, which
runs and writes into the pool itself. The tap seam is the one place both
branches meet, which is also the place the sentence describes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .shields import END_OF_TURN  # noqa: F401  (one duration vocabulary)


@dataclass
class LandManaSwap:
    """One "your lands produce <symbol> instead" record on a seat.

    produced   -- the symbol every covered land makes instead
    lands      -- the printed noun phrase it covers, as a filter payload. Held
                  to what ``subject_filters.subject_matches`` can test, by the
                  lowering, for the reason every filter in this engine is: a
                  restriction the matcher drops is a swap over strictly more
                  lands than the card prints.
    lifetime   -- END_OF_TURN; the sweep that clears shields clears these.
    source_name-- the card that armed it, for the log.
    """

    produced: str
    lands: dict = field(default_factory=dict)
    lifetime: str = END_OF_TURN
    source_name: str | None = None


#: Where the list hangs off a player, for the reason ``engine/shields.py`` uses
#: an attribute: a ``PlayerState`` carries it without learning what a swap is.
_SWAPS_ATTR = "_land_mana_swaps"


def swaps_on(player) -> list[LandManaSwap]:
    """The swaps armed by *player*, created on first use."""
    records = getattr(player, _SWAPS_ATTR, None)
    if records is None:
        records = []
        setattr(player, _SWAPS_ATTR, records)
    return records


def add_swap(player, swap: LandManaSwap) -> LandManaSwap:
    """Put *swap* on *player* and return it."""
    swaps_on(player).append(swap)
    return swap


def clear_swaps(player, lifetime: str | None = None) -> None:
    """Expire records whose duration has run out — the same shape
    ``shields.clear_shields`` and ``damage_redirects.clear_redirects`` have, so
    a turn-step sweep stays one call."""
    records = swaps_on(player)
    records[:] = [r for r in records if lifetime is not None and r.lifetime != lifetime]


def swapped_symbol(game, land) -> str | None:
    """The symbol *land* produces instead of whatever it would have, or None.

    Asked of the **controller's** records and nobody else's: "a land **you**
    control" is CR 109.5's you, the seat whose ability armed the swap, so an
    opponent's Deep Water says nothing about this land. The controller is read
    through the control seam rather than off the permanent, because that is the
    one answer to who controls what.

    The last record wins where a seat has two, which is CR 613.7's timestamp
    order: a second "instead of any other type" applies to the first one's
    answer, and the answer is a single symbol either way.
    """
    from .subject_filters import subject_matches

    seat = game.controller_index_of(land)
    if seat is None:
        return None
    found: str | None = None
    for record in swaps_on(game.players[seat]):
        if subject_matches(game, land, record.lands, observer=seat):
            found = record.produced
    return found


__all__ = [
    "END_OF_TURN", "LandManaSwap", "add_swap", "clear_swaps", "swapped_symbol",
    "swaps_on",
]
