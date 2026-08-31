"""Permanents that are sacrificed when their keeper stops controlling a source.

"Put that card onto the battlefield under your control. **Sacrifice the creature
when you lose control of this creature.**" (Seraph, Krovikan Vampire.)

CR 603.7's delayed trigger, and the event it watches has no single fire site:
you lose control of a permanent when it leaves the battlefield, when a control
effect hands it to somebody else, and when one that had handed it to you ends.
Wiring a hook into each of those is the thirty-fire-sites problem CR 903.9b's
seam exists for, so this is a *record* the state-based sweep re-checks instead —
the arrangement ``engine/control.py``'s ``LINKED_CONTROL_CONDITIONS`` already
uses one question over, where the consequence is ending a contribution rather
than sacrificing something.

The record lives on the **reanimated** permanent, which is the one that gets
sacrificed, and names its keeper by seat and its source by ``permanent_id``. By
id and not by object, because the question is "is *that* Seraph still here": a
Seraph that left and came back is a new object (CR 400.7) and its old link is
correctly broken. By seat and not by "the source's current controller", because
the printed words are "when **you** lose control" — the Seraph changing hands is
exactly the case the card is about.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .game import Game
    from .models import Permanent

#: Where the link is stamped. One key holding both halves, because neither is
#: an answer without the other.
LINKED_SACRIFICE = "sacrifice_when_control_of_source_lost"


def link_sacrifice_to_source(permanent: "Permanent", source: "Permanent", seat: int) -> None:
    """Record that *permanent* is sacrificed when *seat* loses control of
    *source*."""
    permanent.metadata[LINKED_SACRIFICE] = {
        "source_id": source.permanent_id,
        "seat": int(seat),
    }


def linked_sacrifices_owed(game: "Game") -> list["Permanent"]:
    """Every permanent whose keeper has lost control of its source.

    Read through the control seam, never off a battlefield list: "controls" is a
    seat question (CR 109.5), and a Seraph an opponent has stolen is one its
    original controller has lost control of even though nothing moved zones.
    """
    owed = []
    for permanent in game.all_permanents():
        record = permanent.metadata.get(LINKED_SACRIFICE)
        if not isinstance(record, dict):
            continue
        source = game.permanent_by_id(record.get("source_id"))
        if source is None or game.controller_index_of(source) != record.get("seat"):
            owed.append(permanent)
    return owed


__all__ = [
    "LINKED_SACRIFICE", "link_sacrifice_to_source", "linked_sacrifices_owed",
]
