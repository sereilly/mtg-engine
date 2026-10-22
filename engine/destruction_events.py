"""A permanent is destroyed (CR 701.8): one event, and who caused it.

"Whenever a spell or ability an opponent controls **destroys** a noncreature
permanent you control" (Karmic Justice) is a question the board cannot answer
once it has happened. A destroyed artifact, a sacrificed one and one a
state-based action put there are the same card in the same graveyard, and CR
701.8b says only the first was destroyed:

    The only ways a permanent can be destroyed are as a result of an effect
    that uses the word "destroy" or as a result of the state-based actions
    that check for lethal damage (704.5g) or damage from a source with
    deathtouch (704.5h). If a permanent is put into its owner's graveyard for
    any other reason, it hasn't been "destroyed."

So destruction is announced where it is *decided* — the two destroy paths,
``mixins/effects._destroy_target_permanent`` and
``mixins/helpers._destroy_swept_permanents``, once indestructibility
(CR 702.12b), a regeneration shield (CR 701.8c) and a land's destruction shield
have each declined to replace it — and nowhere else. It is the discard seam's
arrangement one zone over (``Game._discard_card``), for the discard seam's
reason: a list of fire sites is only ever as complete as the last card that
touched it.

**The event says who caused it**, because that is the half nothing can
reconstruct. :data:`RESOLVING` is CR 109.5's controller of the spell or ability
resolving right now (``Game.resolving_seats``), which is the answer for every
effect handler and so the default. Three callers know better and say so:

* a **delayed** destruction ("destroy that creature at end of combat", "…at the
  beginning of the next end step") runs in a turn step, long after the
  resolution that set it up has gone. CR 603.7d–e give the delayed ability to
  the player who controlled the spell or ability that created it, so the mark
  records that seat when it is set (:func:`mark_delayed_destruction`) and the
  step passes it back;
* a **state-based** destruction passes :data:`NO_SPELL_OR_ABILITY`. Lethal
  damage destroys a creature whoever dealt the damage, and a state-based action
  can be checked *inside* a resolution (a trigger resolving in a priority
  window, a prompt answered mid-effect) — so "nobody" has to be said by the
  caller rather than read off whatever happens to be resolving;
* a move that is **not a destruction** at all passes
  :data:`NOT_A_DESTRUCTION`. The sweep seam is also what carries CR 704.5f's
  zero toughness, 704.5i's zero loyalty, 704.5m's unattached Aura and two
  sacrifices to the graveyard; none of those is CR 701.8's action and none is
  announced.

**A replaced move is still a destruction.** "If it would die, exile it instead"
changes where the permanent goes, not what was done to it — Fumigate's ruling
(2024-11-08) counts "creatures destroyed this way … even if they're put into a
zone other than a graveyard", and Rest in Peace's (2018-03-16) says a destroyed
Rest in Peace "will be exiled". The announcement is made before the move for
that reason, which is also the order ``destroyed_this_way`` has always counted
in.

**It looks back in time** (CR 603.10a). A destruction moves a permanent off the
battlefield, so what a trigger sees is the permanent as it last existed there:
the filter is asked while it is still listed — an animated land is a creature
at the moment it is destroyed — and the watcher itself may be one of the
permanents leaving. "If a spell or ability an opponent controls destroys Karmic
Justice, Karmic Justice's ability will trigger" (its ruling, 2023-09-01). A
sweep removes its victims a seat, or a permanent, at a time, so a watcher
already taken in the same simultaneous event is remembered for the rest of it
(:attr:`DestructionLedger.departed`).

**And the triggers wait for the resolution to finish** (CR 603.3b: an ability
that has triggered is put on the stack the next time a player would receive
priority). That is true of every trigger and this engine puts most of them on
the stack the moment they fire; here it is load-bearing, because the ability
that watches a destruction usually *targets* — and a target chosen half-way
through a sweep is chosen off a board the sweep has not finished with. They are
held on the ledger and released when nothing is resolving any more.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .oracle_types import EVENT_SUBJECT_LAST_KNOWN

if TYPE_CHECKING:
    from .game import Game
    from .models import Permanent


#: The trigger-condition kind, as ``engine/oracle.py``'s table spells it.
PERMANENT_DESTROYED = "permanent_destroyed"

#: What is appended to a delayed destruction's mark to name the key its cause
#: is recorded under — ``destroy_at_end_of_combat`` beside
#: ``destroy_at_end_of_combat_cause_seat``. The seat CR 603.7d–e give the
#: delayed ability. One key per mark rather than one for the permanent, because
#: a creature can carry two marks set by two players' effects (a Berserk and a
#: Basilisk's block), and the step that destroys it asks about the one firing.
DELAYED_CAUSE_SUFFIX = "_cause_seat"


class _Cause:
    """One of the three things a caller may say instead of naming a seat."""

    __slots__ = ("_label",)

    def __init__(self, label: str) -> None:
        self._label = label

    def __repr__(self) -> str:
        return f"<destruction cause: {self._label}>"


#: The spell or ability resolving right now caused it (CR 109.5).
RESOLVING = _Cause("whatever is resolving")

#: It was destroyed, and by no spell or ability: CR 704.5g / 704.5h.
NO_SPELL_OR_ABILITY = _Cause("no spell or ability")

#: The move is not CR 701.8's destruction, so nothing is announced.
NOT_A_DESTRUCTION = _Cause("not a destruction")


@dataclass
class DestructionLedger:
    """What the destroy seam is holding between an event and the stack."""

    #: Triggered abilities a destruction has triggered, waiting for the
    #: resolution that destroyed to finish (CR 603.3b).
    held: list = field(default_factory=list)
    #: Watchers destroyed earlier in the same simultaneous event, as
    #: ``(permanent, seat, triggers)`` — CR 603.10a's look back, for a sweep
    #: that takes its victims one battlefield or one permanent at a time.
    departed: list = field(default_factory=list)
    #: How deep the instruction that began that event was running
    #: (``len(Game.resolving_seats)``): the event ends when it returns.
    depth: int = 0
    #: How many effects have said "I am still destroying" from outside a
    #: resolution — see :func:`holding_destruction_triggers`.
    holds: int = 0


def cause_seat(game: "Game", cause=RESOLVING) -> int | None:
    """The seat *cause* names, or None when no spell or ability destroyed it.

    A seat the caller froze is returned as it is; :data:`RESOLVING` is whatever
    ``Game.resolving_seats`` holds — and nothing, outside a resolution, which
    is the honest answer for a turn-based action.
    """
    if cause is NO_SPELL_OR_ABILITY or cause is NOT_A_DESTRUCTION:
        return None
    if isinstance(cause, int) and not isinstance(cause, bool):
        return cause if 0 <= cause < len(game.players) else None
    return game.resolving_seats[-1] if game.resolving_seats else None


def mark_delayed_destruction(
    game: "Game", permanent: "Permanent", mark: str, value=True
) -> None:
    """Set *permanent*'s delayed-destruction *mark*, and record who set it.

    **The one writer of those marks** ("destroy_at_end_of_combat" and its
    siblings), so that a mark cannot exist without its cause: the handler
    calls this while the spell or ability creating the delayed ability is
    still resolving — CR 603.7d–e make its controller the delayed ability's —
    and by the step that carries the destruction out nothing is resolving at
    all. A mark written directly would be destroyed by nobody, or by whoever
    set the previous one; ``tests/regressions/test_ody_w2g4_destroy_seam.py``
    fails a second writer.

    *value* is what the mark holds where it is more than a flag (the
    seat-turn stamp of "…at the beginning of **that turn's** end step").
    """
    permanent.metadata[mark] = value
    seat = cause_seat(game)
    if seat is None:
        permanent.metadata.pop(mark + DELAYED_CAUSE_SUFFIX, None)
    else:
        permanent.metadata[mark + DELAYED_CAUSE_SUFFIX] = seat


def delayed_destruction_cause(permanent: "Permanent", mark: str):
    """What the step destroying *permanent* under *mark* passes as its cause:
    the seat :func:`mark_delayed_destruction` recorded, and "no spell or
    ability" for a mark nothing recorded one for."""
    seat = permanent.metadata.get(mark + DELAYED_CAUSE_SUFFIX)
    if isinstance(seat, int) and not isinstance(seat, bool):
        return seat
    return NO_SPELL_OR_ABILITY


def announce_destroyed(game: "Game", permanent: "Permanent", cause=RESOLVING) -> None:
    """*permanent* is being destroyed: collect what that triggers.

    Called by the two destroy seams and by nothing else, with the permanent
    still on its battlefield (CR 603.10a). What it collects is *held* — see
    :func:`destruction_finished`.
    """
    if cause is NOT_A_DESTRUCTION:
        return
    # Taken here rather than at module load, as ``damage_events`` takes its
    # own: the effect handlers import this module for the delayed marks, and
    # the event bus imports the handlers' shared matcher.
    from .events import Event, collect, destroyed_trigger_applies
    from .trigger_utils import make_trigger_event, matching_triggers

    seat = game.controller_index_of(permanent)
    causer = cause_seat(game, cause)
    payload = {
        # Who caused it, or None: the one fact this seam exists to keep.
        "cause_seat": causer,
        # The destroyed permanent, frozen the way every event about an object
        # freezes its subject — by resolution it is a card in a graveyard, or
        # in exile, and CR 400.7 has made it a new object.
        "event_subject_permanent_id": permanent.permanent_id,
        "event_subject_name": permanent.effective_card.name,
        "event_subject_controller": seat,
        EVENT_SUBJECT_LAST_KNOWN: permanent,
    }
    if causer is not None:
        # "…destroy target permanent **that opponent** controls": the player
        # the condition named, under the one key every "that player" is read
        # from (``handlers/_targets._THAT_PLAYER_CONTEXT_KEYS``).
        payload["event_subject_player"] = causer
    event = Event(kind=PERMANENT_DESTROYED, payload=payload, subject=permanent)
    ledger = game.destruction
    triggered = collect(game, event)
    for observer, observer_seat, triggers in ledger.departed:
        if game.is_on_battlefield(observer):
            # Still listed — a sweep removes a battlefield's victims together —
            # so the scan above has already asked it.
            continue
        for trig in triggers:
            if destroyed_trigger_applies(game, observer, observer_seat, trig, event):
                triggered.append(make_trigger_event(
                    observer_seat, observer, trig, trigger_context=dict(payload),
                ))
    ledger.held.extend(triggered)
    if seat is None:
        return
    watching = tuple(matching_triggers(
        permanent.effective_card, condition_kinds={PERMANENT_DESTROYED},
    ))
    if watching:
        if not ledger.departed:
            ledger.depth = len(game.resolving_seats)
        ledger.departed.append((permanent, seat, watching))


def _release(game: "Game") -> None:
    ledger = game.destruction
    ledger.departed.clear()
    if ledger.held:
        held, ledger.held = ledger.held, []
        game._enqueue_triggered_batch(held)


def destruction_finished(game: "Game") -> None:
    """A destroy seam has returned; put what it triggered on the stack if no
    resolution is still running (CR 603.3b)."""
    ledger = game.destruction
    if not (ledger.held or ledger.departed):
        return
    if (
        game.resolving_seats
        or game.resolving_items
        or ledger.holds
        # A resolution that stopped to ask is being carried on from the answer
        # (``_answer_pending_choice``): still one resolution, CR 608.2.
        or game.resolving_stack_item is not None
    ):
        return
    _release(game)


def begin_destruction_hold(game: "Game") -> None:
    """An effect is about to destroy over **several** seam calls and may be
    doing so after a player's answer, when nothing is resolving any more.

    ``Game.resolving_seats`` is what says "still resolving" for an effect
    handler, and it is empty once a resolution has stopped to ask: the rest of
    the effect runs from the prompt's answer (``engine/resumption.py``). An
    effect whose destructions are spread across such answers — "For each land,
    destroy that land unless any player pays 1 life" (Cleansing) — would
    otherwise put each land's trigger on the stack as that land went, and a
    Karmic Justice would be choosing among lands the same spell has not judged
    yet. So the effect says where it starts and where it ends.

    Paired with :func:`end_destruction_hold`; a loop that can suspend calls the
    second from its own final step, which is the only place such a loop may
    put work it owes (``resumption``'s standing rule).
    """
    game.destruction.holds += 1


def end_destruction_hold(game: "Game") -> None:
    """The effect that called :func:`begin_destruction_hold` has finished."""
    ledger = game.destruction
    ledger.holds = max(0, ledger.holds - 1)
    destruction_finished(game)


@contextmanager
def holding_destruction_triggers(game: "Game"):
    """The same pair for an effect that destroys inside one Python call."""
    begin_destruction_hold(game)
    try:
        yield
    finally:
        end_destruction_hold(game)


def instruction_finished(game: "Game") -> None:
    """One instruction has returned (``_execute_oracle_instruction``).

    Two things end here. The **simultaneous event** a watcher was destroyed in
    ends with the instruction that began it — a later sentence of the same
    spell is a later event, and a Karmic Justice destroyed by the first does
    not see the second. And when that was the outermost instruction of
    something that is not a stack object's resolution (an upkeep effect, an
    inline trigger), the held triggers go on the stack.
    """
    ledger = game.destruction
    if ledger.departed and len(game.resolving_seats) < ledger.depth:
        ledger.departed.clear()
    destruction_finished(game)


__all__ = [
    "DELAYED_CAUSE_SUFFIX",
    "DestructionLedger",
    "NOT_A_DESTRUCTION",
    "NO_SPELL_OR_ABILITY",
    "PERMANENT_DESTROYED",
    "RESOLVING",
    "announce_destroyed",
    "begin_destruction_hold",
    "cause_seat",
    "delayed_destruction_cause",
    "destruction_finished",
    "end_destruction_hold",
    "holding_destruction_triggers",
    "instruction_finished",
    "mark_delayed_destruction",
]
