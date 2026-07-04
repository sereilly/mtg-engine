"""Tests for Free-For-All (3-4 player) session creation and lifecycle in the
web layer: ``SessionStore._create_ffa`` / ``restart`` and the
``POST /api/sessions`` endpoint's "free_for_all" mode."""

from fastapi.testclient import TestClient

from web.app import app, store

client = TestClient(app)


def _ffa_payload(seat_count: int = 3, **overrides) -> dict:
    seats = [
        {"name": f"Player {i + 1}", "is_ai": i != 0, "colors": 2}
        for i in range(seat_count)
    ]
    payload = {"mode": "free_for_all", "seats": seats, "seed": 4242}
    payload.update(overrides)
    return payload


def test_create_ffa_session_with_three_seats():
    resp = client.post("/api/sessions", json=_ffa_payload(3))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    session = store.get(body["session_id"])
    assert len(session.game.players) == 3
    assert session.mode == "free_for_all"
    assert session.seat_types == {0: "human", 1: "ai", 2: "ai"}
    assert session.joined_seats == {0, 1, 2}


def test_create_ffa_session_with_four_seats():
    resp = client.post("/api/sessions", json=_ffa_payload(4))
    assert resp.status_code == 200, resp.text
    session = store.get(resp.json()["session_id"])
    assert len(session.game.players) == 4
    assert session.seat_types[3] == "ai"


def test_create_ffa_session_rejects_invalid_seat_count():
    resp = client.post("/api/sessions", json=_ffa_payload(2))
    assert resp.status_code == 400
    resp5 = client.post("/api/sessions", json=_ffa_payload(5))
    assert resp5.status_code == 400


def test_ffa_session_players_have_distinct_names_and_decks():
    resp = client.post("/api/sessions", json=_ffa_payload(4))
    session = store.get(resp.json()["session_id"])
    names = [p.name for p in session.game.players]
    assert names == ["Player 1", "Player 2", "Player 3", "Player 4"]
    # Different seeds per seat (seed + i) should build independent decks.
    libraries = [tuple(c.name for c in p.library) for p in session.game.players]
    assert len(set(libraries)) > 1


def test_ffa_state_endpoint_accepts_seats_beyond_1():
    resp = client.post("/api/sessions", json=_ffa_payload(4))
    sid = resp.json()["session_id"]
    for seat in range(4):
        state = client.get(f"/api/sessions/{sid}/state", params={"seat": seat})
        assert state.status_code == 200
    out_of_range = client.get(f"/api/sessions/{sid}/state", params={"seat": 4})
    assert out_of_range.status_code == 400


def test_ffa_restart_rebuilds_same_seats():
    resp = client.post("/api/sessions", json=_ffa_payload(3))
    sid = resp.json()["session_id"]
    session = store.get(sid)
    original_names = [p.name for p in session.game.players]

    store.restart(session)
    assert session.mode == "free_for_all"
    assert len(session.game.players) == 3
    assert [p.name for p in session.game.players] == original_names
