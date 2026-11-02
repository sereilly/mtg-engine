"""A permanent on its way onto the battlefield, while its "as it enters"
choice is made (CR 614.12a).

CR 614.12a: *"If a replacement effect that modifies how a permanent enters
the battlefield requires a choice, that choice is made before the permanent
enters the battlefield."* So the entry state
(``PermanentStateMixin._initialize_permanent_state``) is performed with the
permanent in **no zone**, and when it leaves a choice owed at a table that
holds for answers (``Game.holds_for_answers``: a person, or the simulator's
prompt driver) the entry waits for that choice: everything from the
battlefield append onward — the recompute, the "…then" rider, the "whenever
a creature enters" announcement, its own enter trigger, and what the caller
does to the permanent once it is there (``then``) — is the record's
``finish``, run by the answer funnel once the permanent's last entry prompt
is answered (``ZoneFunnelsMixin._finish_answered_entries``). Meanwhile the
permanent is on no battlefield, so no static of its reaches anything, no
state-based check sees it and no "enters" trigger has fired.

One record per permanent, on ``Game.entries_in_progress``, from the moment its
entry state starts until it is on the battlefield. What the record answers:

* **who controls it** while it is on its way (CR 614.12: a permanent about to
  enter is judged "as it would exist on the battlefield") —
  ``Game.controller_index_of`` reads the record, so a replacement on the
  counters it enters with, or "creatures **you** control" asked of it, has a
  seat to compare;
* **that a resolution's loop is waiting on it** — an entry still owed is an
  owed suspension (``PendingChoicesMixin.owed_suspensions``), so "return it to
  the battlefield, then it gains haste" stops at the entry and resumes once
  the permanent is there;
* **that no copy may be made of the table** (``ai_rehearsal.held_for_an_answer``):
  ``finish`` is a closure over this game.

Nothing here imports the engine's game: the records are data, the Game-side
work is in ``engine/mixins/zone_funnels.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(eq=False)
class EntryInProgress:
    """One permanent between "would enter" and "is on the battlefield".

    ``finish`` is None while the entry state is being performed and is set
    when the entry waits for an answer; it removes the record and completes
    the entry. Identity, not equality (``eq=False``): two look-alike
    permanents entering together are two entries (CR 400.7).
    """

    permanent: object
    controller_index: int
    finish: "Callable[[], None] | None" = None


def entry_in_progress(game, permanent) -> EntryInProgress | None:
    """The record of *permanent*'s entry, by identity, or None."""
    for record in getattr(game, "entries_in_progress", ()) or ():
        if record.permanent is permanent:
            return record
    return None


def awaited_entries(game) -> tuple[EntryInProgress, ...]:
    """The entries waiting on an answer — those with a ``finish`` set."""
    return tuple(
        record for record in getattr(game, "entries_in_progress", ()) or ()
        if record.finish is not None
    )


def entry_is_awaited(game, permanent) -> bool:
    """Whether *permanent*'s entry is waiting for its "as it enters" choice."""
    record = entry_in_progress(game, permanent)
    return record is not None and record.finish is not None


__all__ = [
    "EntryInProgress",
    "awaited_entries",
    "entry_in_progress",
    "entry_is_awaited",
]
