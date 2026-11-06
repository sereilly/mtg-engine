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
(``ZoneFunnelsMixin.entering_together``), and once it closes each newcomer's
entry state is performed in turn — none sees another, because none is on the
battlefield yet (CR 614.12's "continuous effects that already exist") — and
then the rest of every entry: all appended, one recompute, then each one's
"enters" announcement with every newcomer present. Its records share
``together``, and an event whose members ask waits as one — finished at the
last answer any of them owes, never one member at a time.

**The event is a thing, not a block** (``EntryEvent``). Each entry made
while one is open is *handed in* (``DeferredEntry``: the arguments of the
call, and an id stamped at once, CR 400.7, so a caller recording what it put
down records an identity) and nothing else of it happens until the event
closes. Then every newcomer's entry state is performed — **in APNAP order**
of the seat it enters under, the active player's first and then each other
player's in turn order, a seat's own in the order they were handed in (CR
101.4's choices, CR 613.7m's timestamps) — and only then are they all
appended and announced. Show and Tell's rulings are the shape (2008-04-01:
"After all choices are made, the cards are put onto the battlefield
simultaneously"; 2004-10-04: "If the cards being put onto the battlefield
also require choices, those choices are made after all players choose their
card. The active player makes choices for their card (if any), then the other
players … in turn order").

An event can outlive a decision. "Each player may put …" (Show and Tell)
asks every seat in turn, and each answer arrives after the call that asked
has returned (``engine/resumption.py``). A prompt armed while an event is
open carries it (``ENTRY_EVENT``, stamped by
``replacement_choices.stamp_resolving``), its answer re-joins it
(``ZoneFunnelsMixin.rejoining_entry_event``), and the event closes once the
loop that opened it has run its last step (``opener_done``) and no prompt it
stamped is still owed — at the last answer, whichever seat gives it.

Nothing here imports the engine's game: the records are data, the Game-side
work is in ``engine/mixins/zone_funnels.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

#: The key a prompt armed inside an open event carries it under
#: (``replacement_choices.stamp_resolving``): the answer is one more part of
#: the same event, so the entries it makes join the others.
ENTRY_EVENT = "_entry_event"


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


@dataclass(eq=False)
class DeferredEntry:
    """One entry handed to an open event: what ``_enter_battlefield`` was
    called with, kept until the event closes and performs it (CR 603.6a)."""

    permanent: object
    controller_index: int
    target_player_index: "int | None" = None
    was_cast: bool = False
    from_zone: "str | None" = None
    played_as_land: bool = False
    then: "Callable[[], None] | None" = field(default=None, repr=False)


@dataclass(eq=False)
class EntryEvent:
    """One event putting permanents onto the battlefield (CR 603.6a).

    ``puts`` are the entries handed in, in call order. ``opener_done`` is set
    when whatever opened the event — a ``with`` block, or a resumable loop's
    last step — is finished handing them in; ``closed`` once the entries have
    been performed. *item* is the stack object resolving when it opened, so
    the object's release can close an event its loop never came back for.
    Identity, not equality (``eq=False``)."""

    puts: list = field(default_factory=list)
    opener_done: bool = False
    closed: bool = False
    item: object = field(default=None, repr=False)


def apnap_order(game, puts) -> list:
    """*puts* in APNAP order of the seat each enters under (CR 101.4, CR
    613.7m) — the active player's first, then each other seat in turn order;
    a stable sort, so one seat's keep the order they were handed in."""
    count = len(game.players) or 1
    active = game.active_player_index or 0
    return sorted(puts, key=lambda put: (put.controller_index - active) % count)


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
    "DeferredEntry",
    "ENTRY_EVENT",
    "EntryEvent",
    "EntryInProgress",
    "apnap_order",
    "awaited_entries",
    "entered_together",
    "entry_in_progress",
    "entry_is_awaited",
]
