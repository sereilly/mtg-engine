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


def _ffa_lobby_payload(**overrides) -> dict:
    # Seat 0 is the host (human), seat 1 is an open human seat (no deck/name
    # configured up front — it joins over the network), seat 2 is AI.
    seats = [
        {"name": "Host", "is_ai": False, "colors": 2},
        {"name": "Player 2", "is_ai": False, "colors": 2},
        {"name": "AI", "is_ai": True, "colors": 2},
    ]
    payload = {"mode": "free_for_all", "seats": seats, "seed": 9001, "enable_pregame": True}
    payload.update(overrides)
    return payload


def test_ffa_networked_join_waits_for_open_seat_then_starts():
    created = client.post("/api/sessions", json=_ffa_lobby_payload()).json()
    sid = created["session_id"]
    state = created["state"]

    assert state["lobby"]["game_started"] is False
    assert state["lobby"]["open_seats"] == [1]
    # The open seat has no roster info yet; the host and AI seats do.
    assert state["lobby"]["seats"][1]["joined"] is False
    assert state["lobby"]["seats"][1]["name"] is None
    assert state["lobby"]["seats"][0]["joined"] is True
    assert state["lobby"]["seats"][2]["joined"] is True

    # Actions are blocked while the lobby is open.
    blocked = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "pass_priority"})
    assert blocked.status_code == 400

    # Starting before everyone has joined is rejected.
    early_start = client.post(f"/api/sessions/{sid}/start", json={"seat": 0})
    assert early_start.status_code == 400

    joined = client.post(
        f"/api/sessions/{sid}/join",
        json={"guest_name": "Joiner", "guest_colors": 1, "guest_deck_name": "Mono White"},
    )
    assert joined.status_code == 200
    joined_body = joined.json()
    assert joined_body["seat"] == 1
    lobby = joined_body["state"]["lobby"]
    assert lobby["game_started"] is False
    assert lobby["open_seats"] == []
    assert lobby["seats"][1]["joined"] is True
    assert lobby["seats"][1]["name"] == "Joiner"
    assert lobby["seats"][1]["deck_name"] == "Mono White"

    started = client.post(f"/api/sessions/{sid}/start", json={"seat": 1})
    assert started.status_code == 200
    body = started.json()
    assert body["lobby"]["game_started"] is True
    # Pregame is underway (exact phase depends on who won the coin flip and
    # whether that seat is AI, which auto-advances past its own decisions).
    assert body["pregame"] is not None
