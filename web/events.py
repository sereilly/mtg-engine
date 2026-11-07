"""Server-sent events: the one thing the web layer *pushes*.

Everything else in the API is polled. A lobby, or a second browser watching the
same table, learns that a session changed through
:func:`_notify_session_change`, which fans a one-line payload out to whatever
streams :func:`_stream_session_events` is holding open.

**A route that notifies runs on a worker thread.** Every game route is a plain
``def``, which FastAPI runs in its threadpool, and each stream's queue belongs
to the event loop the stream runs on. ``asyncio.Queue`` is not thread-safe: a
``put_nowait`` from a worker thread completes the waiting ``get`` from the
wrong thread and does not wake the loop, so a loop waiting in its selector
need not notice until something else wakes it — another request, or the
stream's own 30-second keepalive (measured at kg4: not reproduced on the
Windows proactor loop, where delivery happened to be prompt). So every
hand-off is scheduled on the stream's own loop (``loop.call_soon_threadsafe``),
which wakes it; called from the loop itself it is the same call.

**One undelivered event per stream, and it remembers every reason.** A stream
that has not yet sent its last event is given the next one in its place — one
re-fetch answers both — but a reason is something a client acts on (the
"Match Restarting" banner is ``match_restart``'s), so an event given in
another's place carries every reason since the last one sent (``reasons``),
the newest as ``reason``. The state itself never depends on an event arriving: a client
orders payloads by ``revision`` (below) and re-fetches on reconnect.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict


class _Stream:
    """One open stream: its loop, and the event it has not sent yet (or
    None). Touched only on the loop's own thread."""

    __slots__ = ("loop", "pending", "ready")

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.pending: dict | None = None
        self.ready = asyncio.Event()

    def offer(self, reason: str) -> None:
        """Hold *reason* for the next send, beside any reason not yet sent:
        ``{"reason": …}`` alone, or — once two have waited together —
        ``reasons`` too, oldest first."""
        if self.pending is None:
            self.pending = {"reason": reason}
        else:
            earlier = self.pending.get("reasons") or [self.pending["reason"]]
            self.pending = {"reason": reason, "reasons": [*earlier, reason]}
        self.ready.set()

    def take(self) -> dict | None:
        event, self.pending = self.pending, None
        self.ready.clear()
        return event


_session_streams: dict[str, set[_Stream]] = defaultdict(set)

#: How many changes each session has announced: one more at every
#: :func:`_notify_session_change`, whoever is listening. Served on every state
#: payload as ``revision`` (``state_view``), so a client can tell a newer state
#: from an older one without reading the log: the log's length is not a
#: version across games — a rematch or a restart starts a new, shorter one,
#: and so does an undo — and the client's stale-response guard, which
#: compared lengths, discarded the new game for any seat that missed the
#: event naming the reset (a stream reconnecting, or an undelivered event
#: replaced by the next one). That seat sat on the finished game's Defeat
#: screen, fetching a discarded state at every event.
_session_revisions: dict[str, int] = defaultdict(int)


def session_revision(session_id: str) -> int:
    """How many changes *session_id* has announced (:data:`_session_revisions`)."""
    return _session_revisions.get(session_id, 0)


def _notify_session_change(session_id: str, reason: str) -> None:
    """Count the change (synchronously: the payload the calling route builds
    next carries the new ``revision``) and hand *reason* to every open
    stream, on that stream's own loop."""
    _session_revisions[session_id] += 1
    streams = _session_streams.get(session_id)
    if not streams:
        return
    for stream in tuple(streams):
        try:
            stream.loop.call_soon_threadsafe(stream.offer, reason)
        except RuntimeError:
            # The loop has closed (a test's portal, a server shutting down):
            # nobody is listening on it any more.
            streams.discard(stream)


async def _stream_session_events(session_id: str):
    stream = _Stream(asyncio.get_running_loop())
    _session_streams[session_id].add(stream)
    try:
        yield ": connected\n\n"
        while True:
            try:
                await asyncio.wait_for(stream.ready.wait(), timeout=30)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            event = stream.take()
            if event is None:
                continue
            yield f"event: state\ndata: {json.dumps(event)}\n\n"
    finally:
        streams = _session_streams.get(session_id)
        if streams is None:
            return
        streams.discard(stream)
        if not streams:
            _session_streams.pop(session_id, None)
