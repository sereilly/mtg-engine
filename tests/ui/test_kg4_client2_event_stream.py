"""The event stream is handed its events on its own loop, and keeps every
reason it has not sent yet.

Every game route is a plain ``def``, run on a worker thread, and
``_notify_session_change`` is called from it. It used to ``put_nowait`` into
each stream's ``asyncio.Queue`` from that thread — which hands the waiting
``get`` its value without waking the loop the stream runs on, so the stream
stayed asleep in its selector until something else woke it: another request,
or its own 30-second keepalive. And the queue held one event, dropping the
older: a ``match_restart`` replaced by the next ``action`` before it was sent
was a restart nobody's banner announced.

Both are driven here as the server meets them: a stream running on one
thread's loop, notified from another thread with nothing else to wake it.
On the base the first test waits out its timeout (the event arrives only at
the keepalive), and the second reads ``{"reason": "action"}`` alone.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time

from web import events


def _stream_in_a_thread(session_id: str):
    """Run one stream of *session_id* on a loop of its own thread; return the
    chunks it yields (a list it appends to), a started flag and a stop."""
    chunks: list[str] = []
    started = threading.Event()
    loop = asyncio.new_event_loop()
    stop = {"task": None}

    async def consume():
        stream = events._stream_session_events(session_id)
        try:
            async for chunk in stream:
                chunks.append(chunk)
                started.set()
        finally:
            await stream.aclose()

    def run():
        asyncio.set_event_loop(loop)
        stop["task"] = loop.create_task(consume())
        try:
            loop.run_until_complete(stop["task"])
        except asyncio.CancelledError:
            pass
        finally:
            loop.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert started.wait(5), "the stream never connected"

    def close():
        loop.call_soon_threadsafe(stop["task"].cancel)
        thread.join(5)

    return chunks, close


def _events_in(chunks):
    return [
        json.loads(line.removeprefix("data: "))
        for chunk in chunks for line in chunk.splitlines() if line.startswith("data: ")
    ]


def _wait_for(predicate, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_a_notification_from_a_worker_thread_reaches_an_idle_stream_at_once():
    session_id = "kg4-client2-idle-stream"
    chunks, close = _stream_in_a_thread(session_id)
    try:
        assert chunks == [": connected\n\n"]
        before = events.session_revision(session_id)
        events._notify_session_change(session_id, "action")
        assert events.session_revision(session_id) == before + 1
        # Nothing else touches that loop: only the hand-off itself can wake it.
        assert _wait_for(lambda: _events_in(chunks), 3), chunks
        assert _events_in(chunks) == [{"reason": "action"}]
    finally:
        close()


def test_an_event_not_yet_sent_is_replaced_by_one_carrying_both_reasons():
    stream = events._Stream(asyncio.new_event_loop())
    try:
        stream.offer("match_restart")
        stream.offer("action")
        assert stream.take() == {"reason": "action", "reasons": ["match_restart", "action"]}
        assert stream.take() is None
        stream.offer("join")
        assert stream.take() == {"reason": "join"}
    finally:
        stream.loop.close()


def test_a_restart_then_an_action_before_the_send_still_names_the_restart():
    """Two notifications in a row, from a worker thread, before the stream's
    loop has run: the one event sent names both."""
    session_id = "kg4-client2-coalesced"
    chunks, close = _stream_in_a_thread(session_id)
    try:
        streams = events._session_streams[session_id]
        (stream,) = tuple(streams)
        hold = threading.Event()
        released = threading.Event()

        def block():
            # Hold the stream's loop so both offers land before it sends.
            released.set()
            hold.wait(5)

        stream.loop.call_soon_threadsafe(block)
        assert released.wait(5)
        events._notify_session_change(session_id, "match_restart")
        events._notify_session_change(session_id, "action")
        hold.set()
        assert _wait_for(lambda: _events_in(chunks), 3), chunks
        sent = _events_in(chunks)
        assert sent == [{"reason": "action", "reasons": ["match_restart", "action"]}], sent
    finally:
        close()


def test_a_closed_loop_is_forgotten_not_raised():
    session_id = "kg4-client2-closed-loop"
    loop = asyncio.new_event_loop()
    stream = events._Stream(loop)
    events._session_streams[session_id].add(stream)
    loop.close()
    events._notify_session_change(session_id, "action")
    assert stream not in events._session_streams.get(session_id, set())
    events._session_streams.pop(session_id, None)
