"""Server-sent events: the one thing the web layer *pushes*.

Everything else in the API is polled. A lobby, or a second browser watching the
same table, learns that a session changed through
:func:`_notify_session_change`, which fans a one-line payload out to whatever
queues :func:`_stream_session_events` is holding open.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict


_session_event_queues: dict[str, set[asyncio.Queue[dict[str, str]]]] = defaultdict(set)


def _notify_session_change(session_id: str, reason: str) -> None:
    queues = _session_event_queues.get(session_id)
    if not queues:
        return

    event = {"reason": reason}
    for queue in tuple(queues):
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            continue


async def _stream_session_events(session_id: str):
    queue: asyncio.Queue[dict[str, str]] = asyncio.Queue(maxsize=1)
    _session_event_queues[session_id].add(queue)
    try:
        yield ": connected\n\n"
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            yield f"event: state\ndata: {json.dumps(event)}\n\n"
    finally:
        queues = _session_event_queues.get(session_id)
        if queues is None:
            return
        queues.discard(queue)
        if not queues:
            _session_event_queues.pop(session_id, None)
