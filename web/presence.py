"""Who is actually connected: per-seat presence, read off the event streams.

Everything else in the API is stateless polling, so the one live connection a
browser holds — its :mod:`web.events` stream — is what tells the server the
player behind a seat is still there. :func:`connection_opened` /
:func:`connection_closed` count those streams per ``(session id, seat)``; when
a seat's count reaches zero and stays there for :data:`DISCONNECT_GRACE_SECONDS`
(a browser ``EventSource`` reconnects on its own after a blip, well inside the
grace), the seat is disconnected:

- in a still-open lobby the player is removed (``SessionStore.leave``) — their
  slot reopens and the roster updates;
- in a started game the seat goes into ``Session.disconnected_seats``, which
  the state payload carries so every remaining player's client can show the
  "waiting for them to rejoin" dialog. The stream coming back (or the
  ``/rejoin`` route) clears it.

The seat-type check in :func:`_apply_seat_disconnect` keeps this human-only:
an AI seat has no browser, so nothing here ever fires for one.
"""

from __future__ import annotations

import asyncio
from collections import Counter

from .runtime import store
from .events import _notify_session_change, _stream_session_events


# How long a seat's last event stream may stay gone before the player counts as
# disconnected. Long enough for an EventSource auto-reconnect (browsers retry
# after ~1-3s), short enough that the other players aren't left guessing.
DISCONNECT_GRACE_SECONDS = 5.0

# Live event streams per (session id, seat). A seat can hold several (two tabs
# on the same game); the player is gone only when the count reaches zero.
_open_streams: Counter[tuple[str, int]] = Counter()


def seat_is_connected(session_id: str, seat: int) -> bool:
    """Whether some browser currently holds this seat's event stream open."""
    return _open_streams[(session_id, seat)] > 0


def connection_opened(session_id: str, seat: int) -> None:
    key = (session_id, seat)
    first = _open_streams[key] == 0
    _open_streams[key] += 1
    mark_seat_connected(session_id, seat)
    if first:
        # A seat going live changes every viewer's roster badges (the rejoin
        # response is built before the rejoiner's own stream opens, so without
        # this the other clients would keep showing them disconnected).
        _notify_session_change(session_id, "presence")


def connection_closed(session_id: str, seat: int) -> None:
    key = (session_id, seat)
    remaining = max(0, _open_streams[key] - 1)
    if remaining:
        _open_streams[key] = remaining
        return
    # Drop zero entries rather than storing them, so finished sessions don't
    # accumulate in the counter for the life of the process.
    _open_streams.pop(key, None)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No event loop (a synchronous caller, e.g. a test): nothing to wait
        # on, so the grace period collapses to zero.
        _apply_seat_disconnect(session_id, seat)
        return
    # No timer bookkeeping: the check re-reads the live count when it fires, so
    # a reconnect inside the grace simply makes every pending check a no-op.
    loop.call_later(DISCONNECT_GRACE_SECONDS, _apply_seat_disconnect, session_id, seat)


def mark_seat_connected(session_id: str, seat: int) -> None:
    """The player behind ``seat`` is back — their stream reconnected, or they
    rejoined explicitly. Clears the disconnect flag and tells every client."""
    try:
        session = store.get(session_id)
    except KeyError:
        return
    if seat in session.disconnected_seats:
        session.disconnected_seats.discard(seat)
        _notify_session_change(session_id, "player_rejoined")


def _apply_seat_disconnect(session_id: str, seat: int) -> None:
    """The grace period ran out with the seat's stream still gone."""
    if seat_is_connected(session_id, seat):
        return  # reconnected inside the grace period
    try:
        session = store.get(session_id)
    except KeyError:
        return
    if session.seat_types.get(seat) != "human" or seat not in session.joined_seats:
        return
    if not session.game_started:
        # An open lobby: the player is kicked rather than waited for. The host
        # (seat 0) is the exception — the session's configuration is theirs,
        # and ``join`` can only fill guest seats.
        if seat != 0:
            store.leave(session, seat)
            _notify_session_change(session_id, "lobby_leave")
        return
    if seat not in session.disconnected_seats:
        session.disconnected_seats.add(seat)
        _notify_session_change(session_id, "player_disconnected")


async def _stream_session_events_with_presence(session_id: str, seat: int):
    """The event stream, with its open and close driving this seat's presence."""
    connection_opened(session_id, seat)
    try:
        async for chunk in _stream_session_events(session_id):
            yield chunk
    finally:
        connection_closed(session_id, seat)
