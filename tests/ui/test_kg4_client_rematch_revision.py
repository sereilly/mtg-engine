"""A seat that missed the rematch event still lands on the new game.

The client discards a state "older" than the one on screen, so a slow response
cannot step the board back (``renderState``). Its only version was the log's
length — and a rematch starts a new, shorter log. The new game was let through
only by the event naming it (``rematch_start``), so a seat that missed that
event discarded every fetch of the new game: its stream reconnecting (the
fetch on reopen does not skip the guard), or the next event replacing it in the
server's one-slot queue (``web/events``). Driven at kg4 with two browser tabs on
one human-vs-human session: the loser voted first, its stream dropped and came
back after the second vote, and it sat on the finished game's Defeat screen,
"Waiting for opponent…", while the new game waited on its choice of who plays
first — fetching a discarded state at every event the other seat caused, which
is the shape of the Legions GET runs ("runs of 100–500 consecutive GETs from
one seat with no POST, one right after a rematch").

Every state payload now carries ``revision`` — how many changes the session
has announced — and the client orders states by it (``stateIsStale``), falling
back to the log's length only between two payloads of one revision.
"""
from __future__ import annotations

import shutil

import pytest

from tests.helpers import app_js_function_body, client, run_app_js
from web.app import store

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is not on PATH; the client half cannot run",
)


def _session():
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 4407,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    return sid


def _state(sid, seat):
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _finish(sid):
    """Seat 0 loses: its life pasted to 0 after the log has grown, as a played
    game's has."""
    for _ in range(12):
        client.post(f"/api/sessions/{sid}/raw-state", json={"state": _state(sid, 1), "seat": 1})
    state = _state(sid, 1)
    state["players"][0]["life"] = 0
    out = client.post(f"/api/sessions/{sid}/raw-state", json={"state": state, "seat": 1}).json()
    assert out["winner"] == 1
    return out


def _stale(incoming, current):
    return run_app_js(
        ["stateIsStale"], "return stateIsStale(INPUT.incoming, INPUT.current);",
        {"incoming": incoming, "current": current},
    )


def test_every_change_announced_is_a_newer_revision():
    sid = _session()
    first = _state(sid, 0)
    assert isinstance(first["revision"], int)
    # A read changes nothing: the same revision, for either seat.
    assert _state(sid, 1)["revision"] == first["revision"]
    out = client.post(f"/api/sessions/{sid}/raw-state", json={"state": first, "seat": 0}).json()
    assert out["revision"] > first["revision"]
    assert _state(sid, 0)["revision"] == out["revision"]


@needs_node
def test_the_rematch_is_newer_than_the_finished_game_for_the_seat_that_voted_first():
    sid = _session()
    finished = _finish(sid)
    # The loser votes first: its own response is still the finished game.
    voted = client.post(f"/api/sessions/{sid}/rematch", json={"seat": 0}).json()
    assert voted["winner"] == 1 and voted["rematch"]["you_requested"] is True
    # The winner's vote starts the next game.
    client.post(f"/api/sessions/{sid}/rematch", json={"seat": 1})
    assert store.get(sid).status == "active"
    # What the first voter fetches when its stream comes back: a new game,
    # with a shorter log than the one on its screen.
    fetched = _state(sid, 0)
    assert fetched["winner"] is None
    assert len(fetched["log"]) < len(voted["log"])
    assert fetched["revision"] > voted["revision"] > finished["revision"]

    # The guard as it was (the log's length, asserted shorter above)
    # discarded it — the stuck seat. The guard as it is lets it through, and still refuses the finished game
    # arriving late over the new one.
    assert _stale(fetched, voted) is False
    assert _stale(voted, fetched) is True


@needs_node
def test_within_one_revision_the_log_still_decides_and_undo_is_newer():
    shown = {"revision": 7, "log": ["a", "b", "c"]}
    assert _stale({"revision": 7, "log": ["a", "b"]}, shown) is True
    assert _stale({"revision": 7, "log": ["a", "b", "c", "d"]}, shown) is False
    # An undo: a later revision with a shorter log.
    assert _stale({"revision": 8, "log": ["a"]}, shown) is False
    # A late response from before the undo, with the longer log.
    assert _stale({"revision": 6, "log": ["a", "b", "c", "d", "e"]}, shown) is True
    # A payload without a revision (an older server) is read by the log alone.
    assert _stale({"log": ["a"]}, shown) is True
    assert _stale({"log": ["a"]}, None) is False


def test_render_state_asks_the_one_guard():
    body = app_js_function_body("renderState")
    assert "stateIsStale(state, currentState)" in body
    assert "log.length" not in body.split("noteStateForRefetchBackoff")[0]
