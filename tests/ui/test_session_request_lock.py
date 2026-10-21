"""One request at a time per session, and a payload that is one moment.

Found at Torment's Phase 5 (2026-10-21) by reading the browser's own
responses: a ``GET …/state`` answered "declare_blockers" with a log already
ending "Declare blockers step complete", at the length of the state after the
action that leaves the step. The client's version guard is the log's length,
so the torn state rendered as current, its stalled-declare-blockers sender
sent ``next_phase``, and the server applied it to the game it had: the
player's second main phase, left unplayed.

Two causes, both closed by ``web.runtime.one_request_at_a_time``: the routes
ran concurrently in a thread pool (a read part-way through an action), and
FastAPI encoded the returned dict after the route returned while the dict
held the game's own log list (a later action's lines in an earlier payload).
The first test pauses an action part-way through and asks for the state from
a second thread: it must wait. The second asks that a payload does not change
when the game does. The third holds every session route to the lock, so a
route added later cannot quietly read beside an action.
"""

from __future__ import annotations

import threading

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from web.app import app, store

client = TestClient(app)


class _PausingLog(list):
    """A game log that stops the thread appending to it, once, until told to
    go on — the action is then provably part-way through."""

    def __init__(self, items):
        super().__init__(items)
        self.armed = False
        self.paused = threading.Event()
        self.release = threading.Event()

    def append(self, item):
        super().append(item)
        if self.armed:
            self.armed = False
            self.paused.set()
            self.release.wait(timeout=10)

    def __deepcopy__(self, memo):
        # The undo history copies the game before an action; a copy is a log.
        return list(self)


def _session():
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 51041,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    session.current_turn = 0
    session.pregame_phase = None
    game = session.game
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    game.priority_player_index = 0
    return sid, session


def test_a_state_read_waits_for_the_action_in_progress():
    sid, session = _session()
    log = _PausingLog(session.game.log)
    session.game.log = log
    before = len(log)

    action_result = {}

    def act():
        action_result["response"] = client.post(
            f"/api/sessions/{sid}/action", json={"seat": 0, "action": "pass_priority"},
        )

    acting = threading.Thread(target=act)
    log.armed = True
    acting.start()
    assert log.paused.wait(timeout=10), "the action never reached its first log line"

    read = {}

    def look():
        read["state"] = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()

    looking = threading.Thread(target=look)
    looking.start()
    looking.join(timeout=1.0)
    torn = None if looking.is_alive() else read.get("state")
    log.release.set()
    acting.join(timeout=10)
    looking.join(timeout=10)

    assert torn is None, (
        "the state was read while the action was part-way through: "
        f"{len(torn['log']) - before} line(s) of it, step {torn['current_step']}"
    )
    assert action_result["response"].status_code == 200, action_result["response"].text
    finished = action_result["response"].json()
    assert read["state"]["log"] == finished["log"], "the read saw the action finished"
    assert read["state"]["current_step"] == finished["current_step"]


def test_a_state_payload_does_not_change_when_the_game_does():
    """The route's own return value, before FastAPI encodes it: built from
    the game, it must not *be* the game. It held ``session.game.log`` itself,
    so a line the next action appended appeared in this response."""
    from web.app import get_state

    sid, session = _session()
    payload = get_state(sid, seat=0)
    lines = list(payload["log"])

    session.game.log.append("a later action's line")

    assert payload["log"] == lines


def test_every_session_route_holds_the_session_lock():
    """A route about one session — everything under ``/api/sessions/{id}/``
    but the event stream, which lives for the whole game and reads nothing —
    runs under that session's lock."""
    unguarded = [
        f"{sorted(route.methods)} {route.path}"
        for route in app.routes
        if isinstance(route, APIRoute)
        and route.path.startswith("/api/sessions/{session_id}/")
        and route.path != "/api/sessions/{session_id}/events"
        and not getattr(route.endpoint, "holds_session_lock", False)
    ]
    assert unguarded == []


def test_other_sessions_are_not_held_up():
    """The lock is per session: an action paused in one game does not stop a
    read of another."""
    sid, session = _session()
    other_sid, _other = _session()
    log = _PausingLog(session.game.log)
    session.game.log = log

    acting = threading.Thread(target=lambda: client.post(
        f"/api/sessions/{sid}/action", json={"seat": 0, "action": "pass_priority"},
    ))
    log.armed = True
    acting.start()
    assert log.paused.wait(timeout=10)
    try:
        response = client.get(f"/api/sessions/{other_sid}/state", params={"seat": 0})
        assert response.status_code == 200
    finally:
        log.release.set()
        acting.join(timeout=10)
