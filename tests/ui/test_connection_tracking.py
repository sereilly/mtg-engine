"""Per-seat presence over the event streams (web/presence.py).

A player's one live connection is their SSE stream; these tests drive the
presence counters directly (and the stream wrapper where the loop matters)
because holding a real EventSource open is a browser's job:

- a lobby player whose stream stays gone is kicked (their slot reopens);
- a started game marks the seat disconnected instead, which the state payload
  carries for the remaining players' "waiting to rejoin" dialog;
- ``/rejoin`` hands the seat back — same name, same deck, same board — and
  refuses seats that are connected, AI, or still in an open lobby.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

import web.app as web_app
import web.presence as presence
from web.app import app, store


client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean_presence():
    yield
    presence._open_streams.clear()


def _create_lobby_session(seed: int) -> str:
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": seed,
            "enable_pregame": True,
        },
    )
    assert created.status_code == 200
    return created.json()["session_id"]


def _create_started_session(seed: int) -> str:
    sid = _create_lobby_session(seed)
    joined = client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    assert joined.status_code == 200
    started = client.post(f"/api/sessions/{sid}/start", json={"seat": 0})
    assert started.status_code == 200
    assert store.get(sid).game_started
    return sid


def _connect_then_drop(sid: str, seat: int) -> None:
    """One stream opens and closes for the seat; with no event loop running the
    grace period collapses to zero, so the disconnect applies immediately."""
    presence.connection_opened(sid, seat)
    presence.connection_closed(sid, seat)


# ── Lobby: a vanished player is kicked, not waited for ───────────────────────


def test_guest_dropping_from_open_lobby_is_kicked():
    sid = _create_lobby_session(9101)
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    assert session.joined_seats == {0, 1}

    _connect_then_drop(sid, 1)

    assert session.joined_seats == {0}
    assert store.open_human_seats(session) == [1]
    assert session.disconnected_seats == set()

    state = client.get(f"/api/sessions/{sid}/state").json()
    assert state["lobby"]["game_started"] is False
    assert state["lobby"]["open_seats"] == [1]
    assert state["lobby"]["seats"][1]["joined"] is False

    # The freed slot is joinable again — by anyone, the kicked player included.
    rejoined = client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    assert rejoined.status_code == 200
    assert rejoined.json()["seat"] == 1
    assert session.joined_seats == {0, 1}


def test_host_dropping_from_open_lobby_keeps_their_seat():
    sid = _create_lobby_session(9102)
    session = store.get(sid)

    _connect_then_drop(sid, 0)

    assert 0 in session.joined_seats
    assert session.disconnected_seats == set()


def test_ffa_open_seat_player_dropping_is_kicked():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "free_for_all",
            "seats": [
                {"name": "Host", "is_ai": False, "colors": 2},
                {"name": "", "is_ai": False, "colors": 2},
                {"name": "", "is_ai": True, "colors": 2},
            ],
            "seed": 9103,
            "enable_pregame": True,
        },
    )
    assert created.status_code == 200
    sid = created.json()["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Drifter"})
    session = store.get(sid)
    assert session.joined_seats == {0, 1, 2}

    _connect_then_drop(sid, 1)

    assert session.joined_seats == {0, 2}
    assert store.open_human_seats(session) == [1]


def test_reconnect_within_grace_is_not_a_disconnect():
    sid = _create_lobby_session(9104)
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)

    async def _drop_and_reconnect():
        # Inside a running loop the close only schedules the grace check…
        presence.connection_opened(sid, 1)
        presence.connection_closed(sid, 1)
        presence.connection_opened(sid, 1)

    asyncio.run(_drop_and_reconnect())
    # …and when it fires, the reconnected stream makes it a no-op.
    presence._apply_seat_disconnect(sid, 1)

    assert session.joined_seats == {0, 1}


def test_grace_timer_fires_on_the_event_loop(monkeypatch):
    monkeypatch.setattr(presence, "DISCONNECT_GRACE_SECONDS", 0.05)
    sid = _create_lobby_session(9105)
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)

    async def _stream_briefly():
        stream = presence._stream_session_events_with_presence(sid, 1)
        first = await asyncio.wait_for(stream.__anext__(), timeout=1)
        assert first == ": connected\n\n"
        assert presence.seat_is_connected(sid, 1)
        await stream.aclose()
        assert not presence.seat_is_connected(sid, 1)
        assert session.joined_seats == {0, 1}  # grace still running
        await asyncio.sleep(0.2)

    asyncio.run(_stream_briefly())
    assert session.joined_seats == {0}


# ── Started game: the seat is disconnected, waited for, and rejoinable ───────


def test_disconnect_after_start_marks_seat_and_state():
    sid = _create_started_session(9106)
    session = store.get(sid)

    presence.connection_opened(sid, 0)  # the host stays live
    _connect_then_drop(sid, 1)

    assert session.joined_seats == {0, 1}  # never unseated
    assert session.disconnected_seats == {1}

    state = client.get(f"/api/sessions/{sid}/state").json()
    assert state["disconnected_seats"] == [1]
    # ``connected`` is live presence — the open stream, not the grace flag.
    assert state["lobby"]["seats"][0]["connected"] is True
    assert state["lobby"]["seats"][1]["connected"] is False


def test_connected_flag_is_live_presence_not_membership():
    # A started game where nobody holds a stream (a REST client, or the server
    # came back up): every human seat reads disconnected, so the rejoin picker
    # offers exactly what /rejoin would accept.
    sid = _create_started_session(9114)
    state = client.get(f"/api/sessions/{sid}/state").json()
    assert state["lobby"]["seats"][0]["connected"] is False
    assert state["lobby"]["seats"][1]["connected"] is False


def test_stream_coming_back_clears_the_disconnect():
    sid = _create_started_session(9107)
    session = store.get(sid)
    _connect_then_drop(sid, 1)
    assert session.disconnected_seats == {1}

    presence.connection_opened(sid, 1)

    assert session.disconnected_seats == set()
    state = client.get(f"/api/sessions/{sid}/state").json()
    assert state["disconnected_seats"] == []


def test_rejoin_returns_the_same_seat_name_and_deck():
    sid = _create_started_session(9108)
    session = store.get(sid)
    library_before = list(session.game.players[1].library)
    _connect_then_drop(sid, 1)

    rejoined = client.post(f"/api/sessions/{sid}/rejoin", json={"seat": 1})
    assert rejoined.status_code == 200
    body = rejoined.json()
    assert body["seat"] == 1
    assert body["state"]["players"][1]["name"] == "Joiner"

    assert session.disconnected_seats == set()
    # Nothing was rebuilt: the seat still holds the library it had.
    assert [c.name for c in session.game.players[1].library] == [c.name for c in library_before]


def test_rejoin_refuses_lobby_ai_connected_and_out_of_range_seats():
    # Still an open lobby: /join is the path, not /rejoin.
    lobby_sid = _create_lobby_session(9109)
    refused = client.post(f"/api/sessions/{lobby_sid}/rejoin", json={"seat": 1})
    assert refused.status_code == 400
    assert "join it instead" in refused.json()["detail"]

    sid = _create_started_session(9110)

    out_of_range = client.post(f"/api/sessions/{sid}/rejoin", json={"seat": 5})
    assert out_of_range.status_code == 400

    # A seat with a live stream cannot be displaced.
    presence.connection_opened(sid, 0)
    try:
        held = client.post(f"/api/sessions/{sid}/rejoin", json={"seat": 0})
        assert held.status_code == 400
        assert "still connected" in held.json()["detail"]
    finally:
        presence.connection_closed(sid, 0)

    # AI seats have no player to come back.
    hvai = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_ai",
            "host_name": "Solo",
            "guest_name": "AI",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 9111,
        },
    ).json()
    ai_refused = client.post(f"/api/sessions/{hvai['session_id']}/rejoin", json={"seat": 1})
    assert ai_refused.status_code == 400
    assert "AI seat" in ai_refused.json()["detail"]

    # …while the human seat of that solo game is rejoinable (nobody holds it).
    resumed = client.post(f"/api/sessions/{hvai['session_id']}/rejoin", json={"seat": 0})
    assert resumed.status_code == 200
    assert resumed.json()["seat"] == 0


def test_disconnect_never_fires_for_ai_seats():
    hvai = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_ai",
            "host_name": "Solo",
            "guest_name": "AI",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 9112,
        },
    ).json()
    sid = hvai["session_id"]
    session = store.get(sid)

    presence._apply_seat_disconnect(sid, 1)

    assert session.disconnected_seats == set()
    assert session.joined_seats == {0, 1}


def test_events_route_registers_presence_for_a_seated_stream():
    # The route function directly rather than over HTTP: TestClient cannot
    # close an endless SSE response without hanging, and what matters here is
    # which generator the route picks and that its lifetime drives presence.
    sid = _create_started_session(9113)

    async def _drive():
        response = await web_app.stream_session_events(sid, seat=1)
        stream = response.body_iterator
        first = await asyncio.wait_for(stream.__anext__(), timeout=1)
        assert first.startswith(": connected")
        assert presence.seat_is_connected(sid, 1)
        await stream.aclose()
        assert not presence.seat_is_connected(sid, 1)

        # An out-of-range seat gets the spectator stream: no presence at all.
        response = await web_app.stream_session_events(sid, seat=7)
        stream = response.body_iterator
        await asyncio.wait_for(stream.__anext__(), timeout=1)
        assert not presence.seat_is_connected(sid, 7)
        await stream.aclose()

    asyncio.run(_drive())
