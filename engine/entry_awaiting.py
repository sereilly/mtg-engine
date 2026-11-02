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

**Permanents one event puts onto the battlefield enter together** (CR
603.6a: "Each time an event puts one or more permanents onto the battlefield,
all permanents on the battlefield (including the newcomers) are checked for
any enters-the-battlefield triggers that match the event"). A caller that
puts several opens one event around them
(``ZoneFunnelsMixin.entering_together``): each newcomer's entry state is
performed in turn as its call is made — none sees another, because none is on
the battlefield yet (CR 614.12's "continuous effects that already exist") —
and the rest of every entry is done once the event closes: all appended, one
recompute, then each one's "enters" announcement with every newcomer
present. Its records share ``together``, and an event whose members ask
waits as one — finished at the last answer any of them owes, never one
member at a time.

Nothing here imports the engine's game: the records are data, the Game-side
work is in ``engine/mixins/zone_funnels.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(eq=False)
class EntryInProgress:
    """One permanent between "would enter" and "is on the battlefield".

    ``finish`` is None while the entry state is being performed — and, for a
    member of an event still putting others onto the battlefield, until that
    event closes — and is set when the entry waits for an answer; it removes
    the record (every record of its event) and completes the entry. Identity,
    not equality (``eq=False``): two look-alike permanents entering together
    are two entries (CR 400.7).

    The rest is what completing the entry needs, kept on the record so an
    event's members can be completed together, whenever that is:
    *target_player_index* and *was_cast* as ``_enter_battlefield`` was handed
    them, *then* the caller's continuation (run once the permanent is there),
    and *together* every record of the event this one entered in (CR
    603.6a), itself included — empty for an entry made alone.
    """

    permanent: object
    controller_index: int
    finish: "Callable[[], None] | None" = None
    target_player_index: "int | None" = None
    was_cast: bool = False
    then: "Callable[[], None] | None" = None
    together: tuple = ()


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


def entered_together(record: EntryInProgress) -> tuple[EntryInProgress, ...]:
    """Every record of the event *record* entered in, itself included."""
    return record.together or (record,)


def entry_is_awaited(game, permanent) -> bool:
    """Whether *permanent*'s entry is waiting for its "as it enters" choice."""
    record = entry_in_progress(game, permanent)
    return record is not None and record.finish is not None


__all__ = [
    "EntryInProgress",
    "awaited_entries",
    "entered_together",
    "entry_in_progress",
    "entry_is_awaited",
]
