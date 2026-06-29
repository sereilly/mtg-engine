import asyncio
from fastapi.testclient import TestClient
import json
import web.app as web_app
import web.session_store as web_session_store

from engine.models import CardDefinition, Permanent
from web.app import app, store


client = TestClient(app)


def _mk_card(
    name: str,
    mana_cost: str,
    type_line: str,
    oracle_text: str,
    produced_mana: tuple[str, ...] = (),
):
    return CardDefinition(
        name=name,
        mana_cost=mana_cost,
        cmc=1.0,
        type_line=type_line,
        oracle_text=oracle_text,
        colors=(),
        color_identity=(),
        keywords=(),
        produced_mana=produced_mana,
        raw={"name": name, "type_line": type_line},
    )


def _mk_creature_card(name: str, power: int, toughness: int, oracle_text: str = ""):
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line="Creature - Test",
        oracle_text=oracle_text,
        colors=(),
        color_identity=(),
        keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test", "power": str(power), "toughness": str(toughness)},
    )


def _pass_priority(session_id: str, seat: int):
    session = store.get(session_id)
    if seat == 1 and seat not in session.joined_seats and session.mode == "human_vs_human":
        client.post(f"/api/sessions/{session_id}/join", json={"guest_name": "Joiner"})
    return client.post(
        f"/api/sessions/{session_id}/action",
        json={"seat": seat, "action": "pass_priority"},
    )


def _resolve_top_stack(session_id: str, first_pass_seat: int):
    first = _pass_priority(session_id, first_pass_seat)
    assert first.status_code == 200
    second = _pass_priority(session_id, 1 - first_pass_seat)
    assert second.status_code == 200
    return second


def test_create_human_vs_human_session_returns_join_url():
    response = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 3,
            "seed": 123,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"]
    assert "join_url" in payload
    assert "lan_join_url" in payload
    assert payload["seat"] == 0






def test_create_session_keeps_request_host_in_join_url():
    response = client.post(
        "/api/sessions",
        headers={"host": "localhost:8010"},
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 3,
            "seed": 124,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["join_url"].startswith("http://localhost:8010/index.html?session=")


def test_create_session_returns_lan_join_url_when_local_ip_is_available(monkeypatch):
    monkeypatch.setattr(web_app, "_detect_local_ip", lambda: "192.168.1.77")

    response = client.post(
        "/api/sessions",
        headers={"host": "localhost:8010"},
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 3,
            "seed": 125,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["lan_join_url"].startswith("http://192.168.1.77:8010/index.html?session=")


def test_join_hvh_session_and_get_redacted_state():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 555,
        },
    ).json()
    sid = created["session_id"]

    joined = client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    assert joined.status_code == 200
    assert joined.json()["seat"] == 1

    state_for_host = client.get(f"/api/sessions/{sid}/state?seat=0")
    assert state_for_host.status_code == 200
    payload = state_for_host.json()
    assert payload["players"][1]["hand_count"] == len(payload["players"][1]["hand"])
    assert all(card == "<hidden>" for card in payload["players"][1]["hand"])


def _read_sse_event_lines(response):
    lines = []
    for raw_line in response.iter_lines():
        line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
        if line == "":
            if lines:
                return lines
            continue
        if line.startswith(":"):
            continue
        lines.append(line)
    return lines


def test_session_events_stream_join_notification():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 556,
        },
    ).json()
    sid = created["session_id"]

    async def _collect_join_event() -> str:
        stream = web_app._stream_session_events(sid)
        try:
            first_chunk = await asyncio.wait_for(stream.__anext__(), timeout=1)
            assert first_chunk == ": connected\n\n"

            joined = await asyncio.to_thread(client.post, f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
            assert joined.status_code == 200

            return await asyncio.wait_for(stream.__anext__(), timeout=1)
        finally:
            await stream.aclose()

    event_chunk = asyncio.run(_collect_join_event())
    event_lines = [line for line in event_chunk.splitlines() if line]

    assert "event: state" in event_lines
    data_line = next(line for line in event_lines if line.startswith("data: "))
    assert json.loads(data_line.removeprefix("data: ")) == {"reason": "join"}


def test_session_events_stream_action_notification():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 557,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})

    async def _collect_action_event() -> str:
        stream = web_app._stream_session_events(sid)
        try:
            first_chunk = await asyncio.wait_for(stream.__anext__(), timeout=1)
            assert first_chunk == ": connected\n\n"

            action = await asyncio.to_thread(client.post, f"/api/sessions/{sid}/action", json={"seat": 0, "action": "end_turn"})
            assert action.status_code == 200

            return await asyncio.wait_for(stream.__anext__(), timeout=1)
        finally:
            await stream.aclose()

    event_chunk = asyncio.run(_collect_action_event())
    event_lines = [line for line in event_chunk.splitlines() if line]

    assert "event: state" in event_lines
    data_line = next(line for line in event_lines if line.startswith("data: "))
    assert json.loads(data_line.removeprefix("data: ")) == {"reason": "action"}


def test_human_vs_ai_rejects_human_action_for_ai_seat():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_ai",
            "host_name": "Host",
            "guest_name": "Bot",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 888,
        },
    ).json()
    sid = created["session_id"]

    # End host turn first, then try issuing human action from AI seat.
    end_turn = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "end_turn"})
    assert end_turn.status_code == 200

    bad = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 1, "action": "end_turn"},
    )
    assert bad.status_code == 400


def test_human_vs_ai_defaults_guest_name_to_ai():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_ai",
            "host_name": "Host",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 1888,
        },
    ).json()

    assert created["state"]["players"][1]["name"] == "AI"


def test_human_vs_ai_keeps_custom_guest_name():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_ai",
            "host_name": "Host",
            "guest_name": "Sparky",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 1889,
        },
    ).json()

    assert created["state"]["players"][1]["name"] == "Sparky"


def test_networked_hvh_waits_for_opponent_before_starting():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "host_colors": 2,
            "seed": 7100,
            "enable_pregame": True,
        },
    ).json()
    sid = created["session_id"]

    # The game is held: no pregame, opponent's deck/hand not built yet.
    assert created["state"]["awaiting_opponent"] is True
    assert created["state"]["pregame"] is None
    assert created["state"]["players"][1]["hand_count"] == 0

    # The host cannot act until the opponent joins.
    blocked = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "pass_priority"},
    )
    assert blocked.status_code == 400
    assert "opponent" in blocked.json()["detail"]


def test_networked_hvh_join_sets_name_and_starts_game():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "host_colors": 2,
            "seed": 7101,
            "enable_pregame": True,
        },
    ).json()
    sid = created["session_id"]

    joined = client.post(
        f"/api/sessions/{sid}/join",
        json={"guest_name": "Joiner", "guest_colors": 3},
    )
    assert joined.status_code == 200
    state = joined.json()["state"]
    assert state["awaiting_opponent"] is False
    assert state["players"][1]["name"] == "Joiner"
    # Game has begun: the coin-flip pregame phase is now active.
    assert state["pregame"]["phase"] == "coin_flip"


def _make_started_hvh_session(seed: int) -> str:
    """Create a human_vs_human session with both players joined and the game live."""
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "host_colors": 2,
            "seed": seed,
            "enable_pregame": True,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    return sid


def test_rematch_requires_both_players_then_rebuilds_game():
    sid = _make_started_hvh_session(7200)
    session = store.get(sid)
    # Force a finished game: host (seat 0) has lost.
    session.game.players[0].life = 0
    finished = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    assert finished["winner"] == 1
    assert finished["status"] == "finished"

    # First vote: not enough — the game stays finished, opponent is told to wait.
    first = client.post(f"/api/sessions/{sid}/rematch", json={"seat": 0})
    assert first.status_code == 200
    body = first.json()
    assert body["status"] == "finished"
    assert body["rematch"]["you_requested"] is True
    assert body["rematch"]["opponent_requested"] is False

    # The other player sees the pending request.
    opp_view = client.get(f"/api/sessions/{sid}/state?seat=1").json()
    assert opp_view["rematch"]["opponent_requested"] is True

    # Second vote: both agree -> a fresh game is rebuilt in the same session.
    second = client.post(f"/api/sessions/{sid}/rematch", json={"seat": 1}).json()
    assert second["status"] == "active"
    assert second["winner"] is None
    assert second["pregame"]["phase"] == "coin_flip"
    # Same session id and players, full life restored, votes cleared.
    assert second["session_id"] == sid
    assert second["players"][0]["life"] == 20
    assert second["players"][1]["life"] == 20
    assert second["rematch"]["votes"] == []


def test_rematch_rejected_before_game_finishes():
    sid = _make_started_hvh_session(7201)
    resp = client.post(f"/api/sessions/{sid}/rematch", json={"seat": 0})
    assert resp.status_code == 400
    assert "finished" in resp.json()["detail"]


def test_rematch_rejected_for_non_hvh_mode():
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_ai", "host_name": "Solo", "host_colors": 2, "seed": 7202},
    ).json()
    sid = created["session_id"]
    store.get(sid).game.players[1].life = 0  # AI loses
    resp = client.post(f"/api/sessions/{sid}/rematch", json={"seat": 0})
    assert resp.status_code == 400
    assert "human vs human" in resp.json()["detail"]


def test_networked_hvh_join_builds_guest_deck_off_host_seed(monkeypatch):
    captured_seeds = []
    stub_deck = [_mk_card("Island", "", "Basic Land - Island", "") for _ in range(40)]

    def _fake_build_random_deck(_cards_path, _colors, seed):
        captured_seeds.append(seed)
        return list(stub_deck), ["U"]

    monkeypatch.setattr(web_session_store, "build_random_deck", _fake_build_random_deck)

    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "host_colors": 2,
            "seed": 7102,
            "enable_pregame": True,
        },
    ).json()
    sid = created["session_id"]

    # Only the host deck is built up front (seed). The guest deck is deferred.
    assert captured_seeds == [7102]

    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})

    # The guest deck is built on join, deterministically off the host's seed + 1.
    assert captured_seeds == [7102, 7103]


def test_create_session_with_inline_personal_deck_cards():
    # Personal decks live only in the browser, so the client posts their cards
    # inline; the server builds the seat library straight from them (no id).
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_ai",
            "host_name": "Host",
            "host_deck_cards": [{"name": "Island", "count": 40}],
            "seed": 555,
            "enable_pregame": True,  # defers dealing, so the full library is intact
        },
    ).json()
    session = store.get(created["session_id"])

    library = session.game.players[0].library
    assert len(library) == 40
    assert all(card.name == "Island" for card in library)
    # Inline cards are persisted so a rematch can rebuild the same deck.
    assert session.host_deck_cards == [{"name": "Island", "count": 40}]


def test_inline_personal_deck_cards_take_precedence_over_id():
    # When both an id and inline cards are sent, the inline cards win (the id may
    # be a stale server reference; the browser's personal deck is authoritative).
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_ai",
            "host_name": "Host",
            "host_deck_id": "does-not-exist",
            "host_deck_cards": [{"name": "Mountain", "count": 30}],
            "seed": 99,
            "enable_pregame": True,
        },
    )
    assert created.status_code == 200
    session = store.get(created.json()["session_id"])
    assert all(card.name == "Mountain" for card in session.game.players[0].library)


def test_shared_deck_writes_are_rejected_for_clients():
    body = {"name": "Client Deck", "cards": [{"name": "Island", "count": 1}]}
    assert client.post("/api/decks", json=body).status_code == 403
    assert client.put("/api/decks/whatever", json=body).status_code == 403
    assert client.delete("/api/decks/whatever").status_code == 403


def test_shared_deck_writes_allowed_when_server_opts_in(monkeypatch):
    monkeypatch.setattr(web_app, "ALLOW_SHARED_DECK_WRITES", True)
    body = {
        "name": "Server Shared Deck",
        "description": "Mono-blue control.",
        "cards": [{"name": "Island", "count": 1}],
    }
    created = client.post("/api/decks", json=body)
    assert created.status_code == 200
    deck = created.json()
    assert deck["scope"] == "shared"
    assert deck["description"] == "Mono-blue control."
    try:
        # The description round-trips through both the summary list and detail get.
        listed = client.get("/api/decks").json()["decks"]
        assert any(d["id"] == deck["id"] for d in listed)
        fetched = client.get(f"/api/decks/{deck['id']}").json()
        assert fetched["description"] == "Mono-blue control."
        # Updating replaces the description.
        updated = client.put(
            f"/api/decks/{deck['id']}",
            json={"name": "Server Shared Deck", "description": "Now aggro.", "cards": body["cards"]},
        ).json()
        assert updated["description"] == "Now aggro."
    finally:
        web_app.deck_store.delete(deck["id"])
















def test_spell_stays_on_stack_until_both_players_pass_priority():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 40431,
        },
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    bolt = _mk_card(
        name="Bolt Test",
        mana_cost="{R}",
        type_line="Instant",
        oracle_text="Bolt Test deals 3 damage to any target.",
    )
    session.game.players[0].hand = [bolt]
    session.game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 1, "G": 0, "C": 0}
    session.game.players[1].life = 20

    cast = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Bolt Test", "target_seat": 1},
    )
    assert cast.status_code == 200
    cast_payload = cast.json()
    assert len(cast_payload["stack"]) == 1
    assert cast_payload["players"][1]["life"] == 20

    _resolve_top_stack(sid, 0)
    resolved = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    assert resolved["players"][1]["life"] == 17
    assert resolved["stack"] == []


def test_modal_spell_serializes_modes_in_hand():
    """A "Choose one —" modal spell exposes its selectable modes (with target
    kinds) on each hand card so the UI can render a generic mode prompt."""
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_human", "seed": 7777},
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    salve = _mk_card(
        name="Salve Modal Test",
        mana_cost="{W}",
        type_line="Instant",
        oracle_text=(
            "Choose one —\n"
            "• Target player gains 3 life.\n"
            "• Prevent the next 3 damage that would be dealt to any target this turn."
        ),
    )
    session.game.players[0].hand = [salve]

    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    hand = state["players"][0]["hand"]
    card = next(c for c in hand if c["name"] == "Salve Modal Test")
    modes = card["modes"]
    assert len(modes) == 2
    assert modes[0]["label"] == "Target player gains 3 life"
    assert modes[0]["target_kind"] == "player"
    assert modes[0]["supported"] is True
    # "Prevent the next 3 damage ... to any target" can shield a creature or player.
    assert modes[1]["target_kind"] == "any"


def test_modal_spell_resolves_chosen_mode_via_action():
    """Casting a modal spell with mode_index resolves that mode's effect."""
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_human", "seed": 7778},
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    salve = _mk_card(
        name="Salve Resolve Test",
        mana_cost="{W}",
        type_line="Instant",
        oracle_text=(
            "Choose one —\n"
            "• Target player gains 3 life.\n"
            "• Prevent the next 3 damage that would be dealt to any target this turn."
        ),
    )
    session.game.players[0].hand = [salve]
    session.game.players[0].mana_pool = {"W": 1, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}
    session.game.players[0].life = 17

    cast = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "cast",
            "card_name": "Salve Resolve Test",
            "target_seat": 0,
            "mode_index": 1,
        },
    )
    assert cast.status_code == 200
    _resolve_top_stack(sid, 0)

    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    assert state["players"][0]["life"] == 17, "Prevention mode should not gain life"


def test_activate_emblem_grants_prevention_and_requires_priority():
    """The Guardian Angel emblem is activatable via the activate_emblem action,
    gated on priority, and grants a prevention shield to the chosen target."""
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_human", "seed": 5151},
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    p0 = session.game.players[0]
    p0.prevent_one_damage_emblems = [{"target_player_index": 0, "target_permanent_index": None}]
    p0.mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 1}

    # The emblem is serialized for the controller (with preview fields).
    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    assert len(state["players"][0]["emblems"]) == 1
    emblem = state["players"][0]["emblems"][0]
    assert emblem["kind"] == "prevent_one_damage"
    assert emblem["index"] == 0
    assert "{1}" in emblem["oracle_text"]

    # Without priority the action is rejected.
    session.game.priority_player_index = 1
    rejected = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "activate_emblem", "emblem_index": 0},
    )
    assert rejected.status_code == 400

    # With priority it succeeds and applies the shield to the stored target.
    session.game.priority_player_index = 0
    ok = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "activate_emblem", "emblem_index": 0},
    )
    assert ok.status_code == 200
    assert session.game.players[0].damage_prevention_pool == 1


def test_both_players_passing_empty_stack_auto_advances_phase():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 40435,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})

    session = store.get(sid)
    session.game.current_turn_phase = "precombat_main"
    session.game.current_step = "precombat_main"
    session.game.current_phase = "main"
    session.current_turn = 0
    session.game.active_player_index = 0
    session.game.start_priority_window(0)

    first = _pass_priority(sid, 0)
    assert first.status_code == 200
    second = _pass_priority(sid, 1)
    assert second.status_code == 200

    payload = second.json()
    assert payload["current_turn_phase"] == "combat"
    assert payload["current_step"] == "beginning_of_combat"
    assert payload["current_phase"] == "combat"


def test_both_players_passing_end_step_advances_to_cleanup():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 404351,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})

    session = store.get(sid)
    session.current_turn = 0
    session.game.active_player_index = 0
    session.game.players[0].hand = [
        _mk_card(name=f"Spell {idx}", mana_cost="", type_line="Sorcery", oracle_text="") for idx in range(9)
    ]
    session.game.current_turn_phase = "ending"
    session.game.current_step = "end"
    session.game.current_phase = "end"
    session.game.start_priority_window(0)

    first = _pass_priority(sid, 0)
    assert first.status_code == 200
    second = _pass_priority(sid, 1)
    assert second.status_code == 200

    payload = second.json()
    assert payload["current_turn_phase"] == "ending"
    assert payload["current_step"] == "cleanup"
    assert payload["current_phase"] == "cleanup"

    active_state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    assert active_state["cleanup_discard"]["required_count"] == 2
    assert active_state["cleanup_discard"]["selected_indices"] == []






def test_pass_priority_triggers_ai_auto_pass_when_no_response():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_ai",
            "host_name": "Host",
            "guest_name": "AI",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 40434,
        },
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    session.game.players[1].hand = []

    passed = _pass_priority(sid, 0)
    assert passed.status_code == 200
    payload = passed.json()
    assert payload["stack"] == []
    assert payload["priority_player"] == 0
    assert payload["priority_pass_count"] == 0
















def test_non_instant_rejected_on_opponent_turn():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 1235,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})

    session = store.get(sid)
    sorcery = _mk_card(
        name="Sorcery Test",
        mana_cost="{R}",
        type_line="Sorcery",
        oracle_text="Target player loses 3 life.",
    )
    session.game.players[0].hand = [sorcery]
    session.game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 1, "G": 0, "C": 0}

    client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "end_turn"})
    assert store.get(sid).current_turn == 1

    # Active player passes so the nonactive player can try to cast in response.
    passed = _pass_priority(sid, 1)
    assert passed.status_code == 200

    off_turn_cast = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Sorcery Test", "target_seat": 1},
    )
    assert off_turn_cast.status_code == 400
    assert "on your turn" in off_turn_cast.json()["detail"].lower() or "non-instant" in off_turn_cast.json()["detail"].lower()








def test_next_phase_advances_phase_and_clears_mana():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 98999,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})

    session = store.get(sid)
    session.game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 1, "G": 0, "C": 0}
    session.game.current_turn_phase = "precombat_main"
    session.game.current_step = "precombat_main"
    session.game.current_phase = "main"

    response = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "next_phase"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["current_phase"] == "combat"
    assert payload["current_step"] == "beginning_of_combat"
    assert payload["players"][0]["mana_pool"]["R"] == 0


def test_next_phase_advances_through_combat_substeps_then_second_main():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 99011,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})

    session = store.get(sid)
    session.game.current_turn_phase = "precombat_main"
    session.game.current_step = "precombat_main"
    session.game.current_phase = "main"
    session.game.start_priority_window(0)

    to_combat = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "next_phase"})
    assert to_combat.status_code == 200
    assert to_combat.json()["current_step"] == "beginning_of_combat"

    steps = [
        "declare_attackers",
        "declare_blockers",
        "end_of_combat",
    ]
    for expected in steps:
        session.game.start_priority_window(0)
        response = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "next_phase"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["current_phase"] == "combat"
        assert payload["current_step"] == expected
        if expected == "declare_attackers":
            declare = client.post(
                f"/api/sessions/{sid}/action",
                json={"seat": 0, "action": "declare_attackers", "attacker_indices": []},
            )
            assert declare.status_code == 200
        if expected == "declare_blockers":
            session.game.priority_player_index = 1
            declare = client.post(
                f"/api/sessions/{sid}/action",
                json={"seat": 1, "action": "declare_blockers", "blocker_pairs": {}},
            )
            assert declare.status_code == 200

    response = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "next_phase"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["current_phase"] == "main"
    assert payload["current_turn_phase"] == "postcombat_main"
    assert payload["current_step"] == "postcombat_main"


def test_next_phase_in_blockers_step_auto_advances_after_ai_declares_none():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_ai",
            "host_name": "Host",
            "guest_name": "Bot",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 99060,
        },
    ).json()
    sid = created["session_id"]
    session = store.get(sid)

    attacker = _mk_creature_card("Attacker", 3, 3)
    session.game.players[0].battlefield = [Permanent(card=attacker)]
    session.game.players[1].battlefield = []
    session.game.players[1].hand = []

    response = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "next_phase"})
    assert response.status_code == 200
    assert response.json()["current_step"] == "beginning_of_combat"

    response = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "next_phase"})
    assert response.status_code == 200
    assert response.json()["current_step"] == "declare_attackers"

    declare = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "declare_attackers", "attacker_indices": [0]},
    )
    assert declare.status_code == 200

    response = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "next_phase"})
    assert response.status_code == 200
    assert response.json()["current_step"] == "declare_blockers"

    response = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "next_phase"})
    assert response.status_code == 200
    assert response.json()["current_step"] == "end_of_combat"


def test_next_phase_from_attackers_step_auto_advances_when_no_legal_attackers():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 99062,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})

    session = store.get(sid)
    session.game.players[0].battlefield = []
    session.game.players[1].battlefield = []
    session.game.current_turn_phase = "combat"
    session.game.current_step = "declare_attackers"
    session.game.current_phase = "combat"
    session.current_turn = 0
    session.game.start_priority_window(0)

    response = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "next_phase"})
    assert response.status_code == 200
    assert response.json()["current_step"] == "declare_blockers"

    response = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "next_phase"})
    assert response.status_code == 200
    assert response.json()["current_step"] == "end_of_combat"


def test_combat_actions_declare_attackers_and_blockers():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 99031,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})

    session = store.get(sid)
    attacker = _mk_creature_card("Attacker", 3, 3)
    blocker = _mk_creature_card("Blocker", 2, 2)
    session.game.players[0].battlefield = [Permanent(card=attacker)]
    session.game.players[1].battlefield = [Permanent(card=blocker)]
    session.game.current_turn_phase = "combat"
    session.game.current_step = "declare_attackers"
    session.game.current_phase = "combat"
    session.current_turn = 0

    declare_attack = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "declare_attackers", "attacker_indices": [0], "target_seat": 1},
    )
    assert declare_attack.status_code == 200
    assert declare_attack.json()["combat"]["attackers"] == [{"attacker_index": 0, "defending_player_index": 1}]

    session.game.current_step = "declare_blockers"
    session.game.priority_player_index = 1
    declare_block = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 1, "action": "declare_blockers", "blocker_pairs": {"0": 0}},
    )
    assert declare_block.status_code == 200
    assert declare_block.json()["combat"]["blockers"] == [{"blocker_index": 0, "attacker_index": 0}]


def test_no_spells_during_declare_attackers_assignment_then_priority_after():
    """CR 508.1/508.4: declaring attackers is a turn-based action taken before any
    player has priority, so no spell can be cast during the assignment portion. Once
    attackers are declared, the active player receives priority and may cast."""
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 99033,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})

    session = store.get(sid)
    attacker = _mk_creature_card("Attacker", 3, 3)
    bolt = _mk_card(
        name="Bolt Test",
        mana_cost="{R}",
        type_line="Instant",
        oracle_text="Bolt Test deals 3 damage to any target.",
    )
    session.game.players[0].battlefield = [Permanent(card=attacker)]
    session.game.players[0].hand = [bolt]
    session.game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 1, "G": 0, "C": 0}
    session.game.current_turn_phase = "combat"
    session.game.current_step = "declare_attackers"
    session.game.current_phase = "combat"
    session.current_turn = 0
    session.game.clear_priority_window()  # assignment portion: nobody has priority

    blocked = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Bolt Test", "target_seat": 1},
    )
    assert blocked.status_code == 400
    assert "priority" in blocked.json()["detail"].lower()

    declared = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "declare_attackers", "attacker_indices": [0], "target_seat": 1},
    )
    assert declared.status_code == 200
    assert declared.json()["priority_player"] == 0

    # With priority now held, the active player can cast in the declare attackers step.
    cast = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Bolt Test", "target_seat": 1},
    )
    assert cast.status_code == 200
    assert len(cast.json()["stack"]) == 1


def test_no_spells_during_declare_blockers_assignment():
    """CR 509.1: declaring blockers is the defending player's turn-based action; no
    spell can be cast during the assignment portion (no priority window is open)."""
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 99034,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})

    session = store.get(sid)
    attacker = _mk_creature_card("Attacker", 3, 3)
    blocker = _mk_creature_card("Blocker", 2, 2)
    bolt = _mk_card(
        name="Bolt Test",
        mana_cost="{R}",
        type_line="Instant",
        oracle_text="Bolt Test deals 3 damage to any target.",
    )
    session.game.players[0].battlefield = [Permanent(card=attacker)]
    session.game.players[1].battlefield = [Permanent(card=blocker)]
    session.game.players[1].hand = [bolt]
    session.game.players[1].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 1, "G": 0, "C": 0}
    session.game.current_turn_phase = "combat"
    session.game.current_step = "declare_attackers"
    session.game.current_phase = "combat"
    session.current_turn = 0

    client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "declare_attackers", "attacker_indices": [0], "target_seat": 1},
    )
    # Advance into the declare blockers step (active player held priority, passes it).
    session.game.current_step = "declare_blockers"
    session.game.clear_priority_window()  # blocker-assignment portion: no priority

    # The defending player can't cast before declaring blockers.
    blocked = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 1, "action": "cast", "card_name": "Bolt Test", "target_seat": 0},
    )
    assert blocked.status_code == 400
    assert "priority" in blocked.json()["detail"].lower()

    # After blockers are declared, the active player receives priority (CR 509.4).
    declared = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 1, "action": "declare_blockers", "blocker_pairs": {"0": 0}},
    )
    assert declared.status_code == 200
    assert declared.json()["priority_player"] == 0


def test_assign_combat_damage_endpoint_changes_life():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 99032,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})

    session = store.get(sid)
    attacker = _mk_creature_card("Trampler", 5, 5, "Trample")
    blocker = _mk_creature_card("Blocker", 2, 2)
    session.game.players[0].battlefield = [Permanent(card=attacker)]
    session.game.players[1].battlefield = [Permanent(card=blocker)]
    session.game.current_turn_phase = "combat"
    session.game.current_phase = "combat"
    session.current_turn = 0
    session.game.start_priority_window(0)

    session.game.current_step = "declare_attackers"
    client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "declare_attackers", "attacker_indices": [0], "target_seat": 1},
    )
    session.game.current_step = "declare_blockers"
    session.game.priority_player_index = 1
    client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 1, "action": "declare_blockers", "blocker_pairs": {"0": 0}},
    )

    session.game.current_step = "combat_damage"
    session.game.priority_player_index = 0
    assign = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "assign_combat_damage", "attacker_damage": {"0": {"0": 2}}},
    )
    assert assign.status_code == 200
    assert assign.json()["players"][1]["life"] == 17


def _mk_banding_card(name: str, power: int, toughness: int):
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line="Creature - Test",
        oracle_text="Banding",
        colors=(),
        color_identity=(),
        keywords=("Banding",),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test", "power": str(power), "toughness": str(toughness)},
    )


def test_banding_declare_attack_with_band_and_route_blocker_damage():
    """End-to-end (CR 702.22): a band is declared via the API, the lone blocker is
    forced to block the whole band, and the active player routes its damage onto the
    expendable bander so the beater survives."""
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 99077,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})

    session = store.get(sid)
    beater = _mk_creature_card("Beater", 3, 3)
    bander = _mk_banding_card("Bander", 1, 1)
    blocker = _mk_creature_card("Blocker", 3, 3)
    session.game.players[0].battlefield = [Permanent(card=beater), Permanent(card=bander)]
    session.game.players[1].battlefield = [Permanent(card=blocker)]
    session.game.current_turn_phase = "combat"
    session.game.current_phase = "combat"
    session.game.current_step = "declare_attackers"
    session.current_turn = 0
    session.game.start_priority_window(0)

    declare = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "declare_attackers",
            "attacker_indices": [0, 1],
            "bands": [[0, 1]],
            "target_seat": 1,
        },
    )
    assert declare.status_code == 200, declare.text
    assert session.game.combat_bands == [[0, 1]]

    session.game.current_step = "declare_blockers"
    session.game.priority_player_index = 1
    block = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 1, "action": "declare_blockers", "blocker_pairs": {"0": 0}},
    )
    assert block.status_code == 200, block.text
    # 702.22h: blocking the beater also blocks the bander.
    assert session.game.combat_band_blocks.get(1) == [0]

    session.game.current_step = "combat_damage"
    session.game.start_priority_window(0)
    damage = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "assign_combat_damage",
            "blocker_damage": {"0": 1},  # route the blocker's damage onto the bander
        },
    )
    assert damage.status_code == 200, damage.text

    names_p0 = {p.card.name for p in session.game.players[0].battlefield}
    names_p1 = {p.card.name for p in session.game.players[1].battlefield}
    assert "Beater" in names_p0       # saved
    assert "Bander" not in names_p0   # absorbed the blocker's damage
    assert "Blocker" not in names_p1  # 3 + 1 killed it


def test_next_phase_ai_defender_auto_declares_blockers_and_advances_when_no_instant():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_ai",
            "host_name": "Host",
            "guest_name": "AI",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 99201,
        },
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    attacker = _mk_creature_card("Attacker", 3, 3)
    blocker = _mk_creature_card("Blocker", 2, 2)
    session.game.players[0].battlefield = [Permanent(card=attacker)]
    session.game.players[1].battlefield = [Permanent(card=blocker)]
    session.current_turn = 0
    session.game.active_player_index = 0
    session.game.current_turn_phase = "combat"
    session.game.current_step = "declare_attackers"
    session.game.current_phase = "combat"

    declared = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "declare_attackers", "attacker_indices": [0], "target_seat": 1},
    )
    assert declared.status_code == 200

    to_blockers = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "next_phase"},
    )
    assert to_blockers.status_code == 200
    assert to_blockers.json()["current_step"] == "declare_blockers"

    ai_block = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "next_phase"},
    )
    assert ai_block.status_code == 200
    payload = ai_block.json()
    assert payload["current_step"] == "end_of_combat"
    assert payload["combat"]["blockers_locked"] is True




def test_human_defender_can_declare_blockers_while_ai_attacker_holds_priority():
    """Regression: on the AI's turn the active (AI) player holds priority during the
    declare-blockers step. Declaring blockers is the defending player's turn-based
    action, so the human defender must be able to confirm blockers even though the
    AI attacker holds priority (previously rejected with "you do not have priority")."""
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_ai",
            "host_name": "Host",
            "guest_name": "AI",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 99210,
        },
    ).json()
    sid = created["session_id"]
    session = store.get(sid)
    session.seat_types = {0: "human", 1: "ai"}

    attacker = _mk_creature_card("Attacker", 3, 3)
    blocker = _mk_creature_card("Blocker", 2, 2)
    session.game.players[1].battlefield = [Permanent(card=attacker)]
    session.game.players[0].battlefield = [Permanent(card=blocker)]
    session.current_turn = 1
    session.game.active_player_index = 1
    session.game.current_turn_phase = "combat"
    session.game.current_step = "declare_attackers"
    session.game.current_phase = "combat"
    session.game.start_priority_window(1)

    ok, _ = session.game.declare_attackers(1, [0], defending_player_index=0)
    assert ok
    session.game.current_step = "declare_blockers"
    session.game.start_priority_window(1)  # active (AI) player holds priority

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "declare_blockers", "blocker_pairs": {"0": 0}},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["combat"]["blockers"] == [{"blocker_index": 0, "attacker_index": 0}]
    # After blockers are declared the active player receives priority so the AI's
    # turn can resume.
    assert payload["priority_player"] == 1


def test_debug_cast_free_opponent_returns_priority_to_caster():
    """Regression: debug-casting a creature for the AI opponent left priority with the
    AI on the human's turn, so the spell stranded on the stack (the AI never got a turn
    to pass). Priority must return to the acting human so they can resolve it."""
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_ai",
            "host_name": "Host",
            "guest_name": "AI",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 99211,
        },
    ).json()
    sid = created["session_id"]
    session = store.get(sid)
    session.seat_types = {0: "human", 1: "ai"}
    session.current_turn = 0
    session.game.active_player_index = 0
    session.game.current_turn_phase = "precombat_main"
    session.game.current_step = "precombat_main"
    session.game.current_phase = "main"
    session.game.start_priority_window(0)

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "debug_cast_free_opponent", "card_name": "Hill Giant"},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert len(payload["stack"]) == 1
    assert payload["stack"][0]["caster_index"] == 1
    # Priority is with the human caster (not the AI), so the spell is not stranded.
    assert payload["priority_player"] == 0


def test_next_phase_runs_end_then_cleanup_then_next_turn():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 99002,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})

    session = store.get(sid)
    session.game.current_turn_phase = "postcombat_main"
    session.game.current_step = "postcombat_main"
    session.game.current_phase = "main"
    session.game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 1, "G": 0, "C": 0}
    session.game.players[0].hand = [
        _mk_card(name=f"Spell {idx}", mana_cost="", type_line="Sorcery", oracle_text="")
        for idx in range(9)
    ]

    end_step = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "next_phase"})
    assert end_step.status_code == 200
    assert end_step.json()["current_phase"] == "end"
    assert end_step.json()["current_turn"] == 0

    cleanup_step = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "next_phase"})
    assert cleanup_step.status_code == 200
    cleanup_payload = cleanup_step.json()
    assert cleanup_payload["current_phase"] == "cleanup"
    assert cleanup_payload["current_turn"] == 0
    assert cleanup_payload["players"][0]["mana_pool"]["R"] == 0
    assert len(cleanup_payload["players"][0]["hand"]) == 9
    assert cleanup_payload["cleanup_discard"]["required_count"] == 2
    assert cleanup_payload["cleanup_discard"]["selected_indices"] == []

    cannot_advance = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "next_phase"})
    assert cannot_advance.status_code == 400
    assert "select cleanup discards" in cannot_advance.json()["detail"].lower()

    pick_first = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cleanup_select", "hand_index": 0},
    )
    assert pick_first.status_code == 200
    first_payload = pick_first.json()
    assert first_payload["cleanup_discard"]["selected_count"] == 1
    assert first_payload["cleanup_discard"]["selected_indices"] == [0]

    pick_second = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cleanup_select", "hand_index": 8},
    )
    assert pick_second.status_code == 200
    second_payload = pick_second.json()
    assert second_payload["current_phase"] == "main"
    assert second_payload["current_turn"] == 1
    assert second_payload["cleanup_discard"] is None
    assert len(second_payload["players"][1]["hand"]) == 8
    assert len(second_payload["players"][0]["graveyard"]) == 2




def test_cleanup_cast_action_falls_back_to_discard_selection():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 99003,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})

    session = store.get(sid)
    session.game.current_turn_phase = "ending"
    session.game.current_step = "cleanup"
    session.game.current_phase = "cleanup"
    session.current_turn = 0
    session.cleanup_required_discards = 2
    session.game.players[0].hand = [
        _mk_card(name="Spell A", mana_cost="", type_line="Sorcery", oracle_text=""),
        _mk_card(name="Spell B", mana_cost="", type_line="Sorcery", oracle_text=""),
        _mk_card(name="Spell C", mana_cost="", type_line="Sorcery", oracle_text=""),
        _mk_card(name="Spell D", mana_cost="", type_line="Sorcery", oracle_text=""),
        _mk_card(name="Spell E", mana_cost="", type_line="Sorcery", oracle_text=""),
        _mk_card(name="Spell F", mana_cost="", type_line="Sorcery", oracle_text=""),
        _mk_card(name="Spell G", mana_cost="", type_line="Sorcery", oracle_text=""),
        _mk_card(name="Spell H", mana_cost="", type_line="Sorcery", oracle_text=""),
        _mk_card(name="Spell I", mana_cost="", type_line="Sorcery", oracle_text=""),
    ]

    pick_one = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Spell A", "target_seat": 1},
    )
    assert pick_one.status_code == 200
    first_payload = pick_one.json()
    assert first_payload["cleanup_discard"]["selected_count"] == 1

    pick_two = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Spell B", "target_seat": 1},
    )
    assert pick_two.status_code == 200
    second_payload = pick_two.json()
    assert second_payload["current_phase"] == "main"
    assert second_payload["current_turn"] == 1
    assert len(second_payload["players"][1]["hand"]) == 8
    assert len(second_payload["players"][0]["graveyard"]) == 2


# ---------------------------------------------------------------------------
# Regression: drag-to-battlefield and target+mana prompt flow
# ---------------------------------------------------------------------------


def _make_session_with_card_in_hand(seed: int, card, mana_pool: dict | None = None):
    """Create a session and inject *card* into seat-0's hand with optional mana."""
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": seed,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    session.game.players[0].hand = [card]
    if mana_pool is not None:
        session.game.players[0].mana_pool = mana_pool
    return sid


def test_cast_without_mana_returns_insufficient_mana_error():
    """Backend returns 'insufficient mana' when cast is attempted with empty mana pool.

    Regression: the frontend drag path and target-resolve path both check for an
    error message starting with 'insufficient mana' to decide whether to show the
    auto-tap prompt instead of swallowing the failure silently.
    """
    bolt = _mk_card(
        name="Bolt Rg",
        mana_cost="{R}",
        type_line="Instant",
        oracle_text="Bolt Rg deals 3 damage to any target.",
    )
    sid = _make_session_with_card_in_hand(70001, bolt, mana_pool={"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0})

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Bolt Rg", "target_seat": 1},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"].lower().startswith("insufficient mana")


def test_cast_targeted_spell_without_mana_returns_insufficient_mana_error():
    """Backend returns 'insufficient mana' for a targeted spell with no mana tapped.

    Regression: resolvePendingCastTarget (click/drag path after target selection)
    must receive this error to trigger the auto-tap prompt rather than silently
    failing.
    """
    bolt = _mk_card(
        name="Target Bolt",
        mana_cost="{R}",
        type_line="Instant",
        oracle_text="Target Bolt deals 3 damage to any target.",
    )
    sid = _make_session_with_card_in_hand(70002, bolt, mana_pool={"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0})

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Target Bolt", "target_seat": 1},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"].lower().startswith("insufficient mana")


def test_cast_targeted_spell_succeeds_after_mana_tapped():
    """Casting a targeted spell succeeds once sufficient mana is in the pool.

    Regression: this is the successful end-state of the auto-tap + cast flow that
    both the drag path and the target-resolve path lead to.
    """
    from engine.models import Permanent

    bolt = _mk_card(
        name="Target Bolt 2",
        mana_cost="{R}",
        type_line="Instant",
        oracle_text="Target Bolt 2 deals 3 damage to any target.",
    )
    land = _mk_card(
        name="Mountain",
        mana_cost="",
        type_line="Basic Land — Mountain",
        oracle_text="",
        produced_mana=("R",),
    )
    sid = _make_session_with_card_in_hand(70003, bolt)
    session = store.get(sid)
    session.game.players[0].battlefield = [Permanent(card=land, tapped=False)]

    tap = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "tap", "permanent_index": 0},
    )
    assert tap.status_code == 200

    cast = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Target Bolt 2", "target_seat": 1},
    )
    assert cast.status_code == 200
    assert len(cast.json()["stack"]) == 1


# ---------------------------------------------------------------------------
# Fork: the copy goes on the stack and may be given new targets, driven through
# the real HTTP cast action the UI sends (stack target + a new permanent target).
# ---------------------------------------------------------------------------


def test_fork_serializes_copies_spell_flag_in_hand():
    """A Fork in hand carries copies_spell=True so the UI runs the copy-retarget
    flow; a plain counterspell does not."""
    from engine.card_loader import load_cards as _load

    cards = {c.name: c for c in _load("lea_cards.json")}
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_human", "host_colors": 2, "guest_colors": 2, "seed": 51001},
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    session.game.players[0].hand = [cards["Fork"], cards["Counterspell"]]

    hand = client.get(f"/api/sessions/{sid}/state?seat=0").json()["players"][0]["hand"]
    fork = next(c for c in hand if c["name"] == "Fork")
    counter = next(c for c in hand if c["name"] == "Counterspell")
    assert fork["target_spec"]["kind"] == "stack"
    assert fork["target_spec"]["copies_spell"] is True
    assert counter["target_spec"].get("copies_spell") is False


def test_fork_copy_retargets_to_a_second_creature_via_http():
    """Cast Giant Growth on one creature, then Fork it and retarget the copy to a
    second creature — the exact two action bodies the UI sends. Both creatures end
    up buffed, proving the copy is an independent spell with its own target."""
    from engine.card_loader import load_cards as _load
    from engine.models import Permanent

    cards = {c.name: c for c in _load("lea_cards.json")}
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_human", "host_colors": 2, "guest_colors": 2, "seed": 51002},
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    session.game.enforce_mana_costs = False

    bears_a = Permanent(card=cards["Grizzly Bears"])
    bears_b = Permanent(card=cards["Grizzly Bears"])
    session.game.players[0].battlefield = [bears_a, bears_b]
    session.game.players[0].hand = [cards["Giant Growth"], cards["Fork"]]

    # 1) Cast Giant Growth on bears_a (seat 0, permanent_index 0).
    gg = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0, "action": "cast", "card_name": "Giant Growth",
            "target_seat": 0, "permanent_index": 0,
        },
    )
    assert gg.status_code == 200
    assert len(gg.json()["stack"]) == 1

    # 2) Cast Fork: copy the spell at stack index 0 (Giant Growth) and choose
    #    bears_b (permanent_index 1) as the copy's new target.
    fork = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0, "action": "cast", "card_name": "Fork",
            "target_stack_index": 0, "target_seat": 0, "permanent_index": 1,
        },
    )
    assert fork.status_code == 200
    assert len(fork.json()["stack"]) == 2  # Giant Growth + Fork

    # Resolve everything by passing priority back and forth.
    for _ in range(12):
        if not store.get(sid).game.stack:
            break
        _pass_priority(sid, 0)
        _pass_priority(sid, 1)

    game = store.get(sid).game
    assert not game.stack
    # Original Giant Growth buffed bears_a; the Fork copy buffed bears_b.
    assert game.players[0].battlefield[0].effective_power == 5
    assert game.players[0].battlefield[1].effective_power == 5


# ---------------------------------------------------------------------------
# Bug regression: hold priority during opponent's (AI) turn
# ---------------------------------------------------------------------------


def _make_ai_turn_session(seed: int):
    """Create a human_vs_ai session and advance to the AI's (seat 1) main phase."""
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_ai",
            "host_name": "Host",
            "guest_name": "AI",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": seed,
        },
    ).json()
    sid = created["session_id"]
    session = store.get(sid)
    # Advance to AI's turn by directly updating session and game state.
    session.current_turn = 1
    session.game.active_player_index = 1
    session.game.priority_player_index = 1
    session.game.priority_pass_count = 0
    session.game.enforce_mana_costs = False
    return sid


def test_ai_step_queues_spell_and_gives_human_priority():
    """When the AI casts a spell on its turn, the human opponent should receive priority
    before the spell resolves (hold-priority regression)."""
    bolt = _mk_card(
        name="AI Bolt",
        mana_cost="{R}",
        type_line="Instant",
        oracle_text="AI Bolt deals 3 damage to any target.",
    )
    sid = _make_ai_turn_session(80001)
    session = store.get(sid)
    session.game.players[1].hand = [bolt]

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "ai_step"},
    )
    assert resp.status_code == 200
    payload = resp.json()

    # Spell must be on the stack — not yet resolved.
    assert len(payload["stack"]) == 1
    assert payload["stack"][0]["card"]["name"] == "AI Bolt"
    # Human (seat 0) must have priority so hold-priority can work.
    assert payload["priority_player"] == 0
    # Turn must still belong to the AI — not ended yet.
    assert payload["current_turn"] == 1


def test_human_passing_priority_resolves_ai_spell():
    """After the AI queues a spell and passes priority to the human, the human
    passing priority should resolve the spell and complete the AI's turn."""
    bolt = _mk_card(
        name="AI Bolt Resolve",
        mana_cost="{R}",
        type_line="Instant",
        oracle_text="AI Bolt Resolve deals 3 damage to any target.",
    )
    sid = _make_ai_turn_session(80002)
    session = store.get(sid)
    session.game.players[1].hand = [bolt]
    session.game.players[0].life = 20

    # AI casts its spell and pauses for priority.
    client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "ai_step"})

    # Human passes priority — spell resolves, then the AI continues its turn.
    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "pass_priority"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["stack"] == []
    # The spell resolved and dealt 3 damage to the human (default target = opponent).
    assert payload["players"][0]["life"] == 17


def test_ai_step_while_human_has_priority_does_not_crash():
    """Regression: calling ai_step a second time while the human holds priority must
    not raise 'player does not have priority'.  The server should return 200 with the
    game still paused (spell on stack, human still has priority)."""
    bolt = _mk_card(
        name="AI Bolt 2",
        mana_cost="{R}",
        type_line="Instant",
        oracle_text="AI Bolt 2 deals 3 damage to any target.",
    )
    sid = _make_ai_turn_session(80003)
    session = store.get(sid)
    session.game.players[1].hand = [bolt]

    # First ai_step: AI queues the spell and passes priority to the human.
    first = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "ai_step"})
    assert first.status_code == 200
    assert first.json()["priority_player"] == 0  # human has priority

    # Second ai_step while human still has priority — was crashing before the fix.
    second = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "ai_step"})
    assert second.status_code == 200
    payload = second.json()
    # State must be unchanged: spell still on stack, human still has priority.
    assert len(payload["stack"]) == 1
    assert payload["priority_player"] == 0
    assert payload["current_turn"] == 1


def test_ai_demonic_tutor_search_resolves_automatically():
    """Regression: when the AI resolves a tutor effect, it must search its own
    library immediately instead of leaving the game stuck on pending_search_library."""
    tutor = _mk_card(
        name="AI Tutor",
        mana_cost="{B}",
        type_line="Sorcery",
        oracle_text="Search your library for a card, put that card into your hand, then shuffle.",
    )
    sid = _make_ai_turn_session(80004)
    session = store.get(sid)
    session.game.players[1].hand = [tutor]
    library_before = len(session.game.players[1].library)
    assert library_before > 0

    # AI casts the tutor and passes priority to the human.
    first = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "ai_step"})
    assert first.status_code == 200
    assert len(first.json()["stack"]) == 1

    # Human passes priority — tutor resolves and the AI must complete its search.
    resp = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "pass_priority"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["stack"] == []
    assert payload["search_library"] is None
    assert session.game.pending_search_library is None
    # The tutored card moved from the library into the AI's hand.
    assert len(session.game.players[1].hand) == 1
    assert len(session.game.players[1].library) == library_before - 1

    # The game is not stuck: the human can keep acting normally.
    follow_up = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "ai_step"})
    assert follow_up.status_code == 200


# ---------------------------------------------------------------------------
# Phase-rail hold-priority on the opponent's (AI's) turn.
# ---------------------------------------------------------------------------


def test_ai_holds_priority_for_human_at_beginning_of_combat():
    """Flagging beginning of combat must pause the AI's turn there and hand the
    human priority (the original BC hold)."""
    sid = _make_ai_turn_session(80101)
    session = store.get(sid)
    session.game.players[1].hand = []
    session.game._set_phase_and_step("precombat_main", "precombat_main")
    session.game.start_priority_window(1)

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "ai_step", "stop_steps": ["beginning_of_combat"]},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["current_turn"] == 1  # still the AI's turn
    assert payload["current_step"] == "beginning_of_combat"
    assert payload["priority_player"] == 0  # human holds priority


def test_ai_holds_priority_for_human_at_end_step():
    """Flagging the end step must pause the AI's turn at the end step and hand the
    human priority — the reported EN regression."""
    sid = _make_ai_turn_session(80102)
    session = store.get(sid)
    session.game.players[1].hand = []
    session.game._set_phase_and_step("postcombat_main", "postcombat_main")
    session.game.start_priority_window(1)

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "ai_step", "stop_steps": ["end"]},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["current_turn"] == 1  # turn has NOT ended
    assert payload["current_step"] == "end"
    assert payload["priority_player"] == 0  # human holds priority at the end step


def test_human_passing_at_held_end_step_completes_ai_turn():
    """After holding at the AI's end step, the human passing priority must finish the
    AI's turn and pass the turn to the human."""
    sid = _make_ai_turn_session(80103)
    session = store.get(sid)
    session.game.players[1].hand = []
    session.game._set_phase_and_step("postcombat_main", "postcombat_main")
    session.game.start_priority_window(1)

    client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "ai_step", "stop_steps": ["end"]},
    )
    resp = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "pass_priority"})
    assert resp.status_code == 200
    assert resp.json()["current_turn"] == 0  # the AI's turn ended; now the human's


def test_ai_holds_priority_for_human_at_upkeep_on_turn_start():
    """Flagging upkeep must pause at the AI's upkeep step — exercising the turn-start
    path that the AI normally resolves itself."""
    sid = _make_ai_turn_session(80104)
    session = store.get(sid)
    # Hand the turn back to the human so ending it begins a fresh AI turn.
    session.current_turn = 0
    session.game.active_player_index = 0
    session.game._set_phase_and_step("postcombat_main", "postcombat_main")
    session.game.start_priority_window(0)
    session.game.players[0].hand = session.game.players[0].hand[:5]  # avoid cleanup discard

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "end_turn", "stop_steps": ["upkeep"]},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["current_turn"] == 1  # now the AI's turn
    assert payload["current_step"] == "upkeep"
    assert payload["priority_player"] == 0  # human holds priority at the AI's upkeep


def test_ai_resolves_combat_damage_for_multi_blocked_attacker():
    """A double-blocked attacker requires manual damage assignment, which the engine
    defers to a player. When the active player is an AI the driver must assign damage
    itself instead of spinning forever on the combat_damage step (the deadlock bug)."""
    sid = _make_ai_turn_session(80301)
    session = store.get(sid)
    session.seat_types = {0: "ai", 1: "ai"}
    game = session.game

    attacker = Permanent(card=_mk_creature_card("Big Attacker", 3, 3))
    attacker.attacking = True
    attacker.blocked = True
    wall_a = Permanent(card=_mk_creature_card("Wall A", 0, 2))
    wall_b = Permanent(card=_mk_creature_card("Wall B", 0, 2))
    game.players[1].battlefield = [attacker]
    game.players[0].battlefield = [wall_a, wall_b]
    game.players[1].hand = []

    # Stand the engine up exactly where it deadlocked: locked combat with a
    # double-blocked attacker, sitting on an unresolved combat_damage step.
    game.combat_defending_player_index = 0
    game.combat_attackers = {0: 0}
    game.combat_blockers = {0: [0], 1: [0]}
    game.combat_attackers_locked = True
    game.combat_blockers_locked = True
    game.combat_damage_resolved = False
    game.combat_first_strike_done = False
    game._set_phase_and_step("combat", "combat_damage")

    assert game._needs_manual_damage_assignment()

    web_app._advance_phase(session)

    assert game.combat_damage_resolved
    assert game.current_step != "combat_damage"  # progressed past the damage step
    # One wall took the attacker's full 3 power and died; the other survived.
    survivors = [p.card.name for p in game.players[0].battlefield]
    graveyard = [c.name for c in game.players[0].graveyard]
    assert sorted(survivors) == ["Wall B"]
    assert graveyard == ["Wall A"]


def test_ai_does_not_cast_sorcery_speed_spell_during_combat_damage():
    """choose_cast_action covers sorcery-speed plays (enchantments, creatures, ...).
    The AI must not cast them outside its main phase — the enchantment-during-damage
    bug came from _ai_step running at the (stuck) combat_damage step."""
    sid = _make_ai_turn_session(80302)
    session = store.get(sid)
    session.seat_types = {0: "ai", 1: "ai"}  # no human => casts resolve immediately
    creature = _mk_creature_card("Vanilla Bear", 2, 2)
    game = session.game
    game.players[1].battlefield = []

    # Control: during the AI's main phase it readily plays the creature.
    game.players[1].hand = [creature]
    game._set_phase_and_step("precombat_main", "precombat_main")
    game.start_priority_window(1)
    web_app._ai_step(session)
    assert any(p.card.name == "Vanilla Bear" for p in game.players[1].battlefield)
    assert not any(c.name == "Vanilla Bear" for c in game.players[1].hand)

    # During the combat damage step the same play must be refused.
    game.players[1].battlefield = []
    game.players[1].hand = [creature]
    game._set_phase_and_step("combat", "combat_damage")
    game.combat_damage_resolved = True  # damage already resolved; AI just has priority
    game.start_priority_window(1)
    web_app._ai_step(session)
    assert any(c.name == "Vanilla Bear" for c in game.players[1].hand)
    assert not any(p.card.name == "Vanilla Bear" for p in game.players[1].battlefield)


def test_ai_turn_does_not_hold_when_nothing_flagged():
    """With no stop steps flagged, the AI's turn runs through to completion as before."""
    sid = _make_ai_turn_session(80105)
    session = store.get(sid)
    session.game.players[1].hand = []
    session.game._set_phase_and_step("postcombat_main", "postcombat_main")
    session.game.start_priority_window(1)

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "ai_step", "stop_steps": []},
    )
    assert resp.status_code == 200
    # No hold: the AI completed its turn and play passed to the human.
    assert resp.json()["current_turn"] == 0


# ---------------------------------------------------------------------------
# Playtest fixes: Fireball multi-target prompt, Unsummon targeting, regame order
# ---------------------------------------------------------------------------


def _make_main_phase_session(seed: int, hand_card, mana_pool=None, opp_battlefield=None):
    """HvH session with seat 0 on the play in its main phase, holding priority."""
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": seed,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    session.game.players[0].hand = [hand_card]
    if mana_pool is not None:
        session.game.players[0].mana_pool = mana_pool
    if opp_battlefield is not None:
        session.game.players[1].battlefield = opp_battlefield
    session.game.current_turn_phase = "precombat_main"
    session.game.current_step = "precombat_main"
    session.game.current_phase = "main"
    session.current_turn = 0
    session.game.active_player_index = 0
    session.game.start_priority_window(0)
    return sid


_FIREBALL_TEXT = (
    "This spell costs {1} more to cast for each target beyond the first.\n"
    "Fireball deals X damage divided evenly, rounded down, among any number of targets."
)


def test_fireball_splits_damage_among_multiple_creatures_via_api():
    fireball = _mk_card(
        name="Fireball",
        mana_cost="{X}{R}",
        type_line="Sorcery",
        oracle_text=_FIREBALL_TEXT,
    )
    creatures = [_mk_creature_card("Goblin A", 2, 2), _mk_creature_card("Goblin B", 2, 2)]
    sid = _make_main_phase_session(
        90101,
        fireball,
        mana_pool={"W": 0, "U": 0, "B": 0, "R": 1, "G": 0, "C": 5},
        opp_battlefield=[Permanent(card=c) for c in creatures],
    )

    # X=4 over two targets => 2 damage each; the extra target costs {1} more, so
    # the total is R + 4 + 1 = 6 mana.
    cast = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "cast",
            "card_name": "Fireball",
            "target_seat": 1,
            "target_permanent_indices": [0, 1],
            "x_value": 4,
        },
    )
    assert cast.status_code == 200, cast.json()
    assert len(cast.json()["stack"]) == 1

    _resolve_top_stack(sid, 0)
    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    assert state["players"][1]["battlefield"] == []


def test_fireball_extra_target_cost_makes_underfunded_cast_fail_via_api():
    fireball = _mk_card(
        name="Fireball",
        mana_cost="{X}{R}",
        type_line="Sorcery",
        oracle_text=_FIREBALL_TEXT,
    )
    creatures = [_mk_creature_card("Goblin A", 2, 2), _mk_creature_card("Goblin B", 2, 2)]
    # Only 5 mana (R + 4 generic): two targets need 6, so the cast is rejected.
    sid = _make_main_phase_session(
        90102,
        fireball,
        mana_pool={"W": 0, "U": 0, "B": 0, "R": 1, "G": 0, "C": 4},
        opp_battlefield=[Permanent(card=c) for c in creatures],
    )

    cast = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "cast",
            "card_name": "Fireball",
            "target_seat": 1,
            "target_permanent_indices": [0, 1],
            "x_value": 4,
        },
    )
    assert cast.status_code == 400


def test_fireball_all_damage_to_face_via_api():
    fireball = _mk_card(
        name="Fireball",
        mana_cost="{X}{R}",
        type_line="Sorcery",
        oracle_text=_FIREBALL_TEXT,
    )
    sid = _make_main_phase_session(
        90103,
        fireball,
        mana_pool={"W": 0, "U": 0, "B": 0, "R": 1, "G": 0, "C": 6},
    )
    cast = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Fireball", "target_seat": 1, "x_value": 6},
    )
    assert cast.status_code == 200, cast.json()
    _resolve_top_stack(sid, 0)
    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    assert state["players"][1]["life"] == 14


def test_unsummon_returns_the_chosen_creature_via_api():
    unsummon = _mk_card(
        name="Unsummon",
        mana_cost="{U}",
        type_line="Instant",
        oracle_text="Return target creature to its owner's hand.",
    )
    bear = _mk_creature_card("Bear", 2, 2)
    ogre = _mk_creature_card("Ogre", 3, 3)
    sid = _make_main_phase_session(
        90104,
        unsummon,
        mana_pool={"W": 0, "U": 1, "B": 0, "R": 0, "G": 0, "C": 0},
        opp_battlefield=[Permanent(card=bear), Permanent(card=ogre)],
    )

    # Target the second creature (index 1, the Ogre).
    cast = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "cast",
            "card_name": "Unsummon",
            "target_seat": 1,
            "permanent_index": 1,
        },
    )
    assert cast.status_code == 200, cast.json()
    _resolve_top_stack(sid, 0)

    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    remaining = [p["name"] for p in state["players"][1]["battlefield"]]
    assert remaining == ["Bear"]


def test_rematch_loser_chooses_who_plays_first():
    sid = _make_started_hvh_session(90200)
    session = store.get(sid)
    # Seat 0 loses the game; seat 1 is the winner.
    session.game.players[0].life = 0
    assert client.get(f"/api/sessions/{sid}/state?seat=0").json()["winner"] == 1

    # Both players agree to a rematch.
    client.post(f"/api/sessions/{sid}/rematch", json={"seat": 0})
    second = client.post(f"/api/sessions/{sid}/rematch", json={"seat": 1}).json()

    # No coin flip: the previous loser (seat 0) is the chooser.
    pregame = second["pregame"]
    assert pregame["phase"] == "coin_flip"
    assert pregame["is_loser_choice"] is True
    assert pregame["winner_seat"] == 0  # the chooser is the loser

    loser_view = client.get(f"/api/sessions/{sid}/state?seat=0").json()["pregame"]
    assert loser_view["is_my_turn"] is True
    winner_view = client.get(f"/api/sessions/{sid}/state?seat=1").json()["pregame"]
    assert winner_view["is_my_turn"] is False

    # The winner cannot make the choice.
    rejected = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 1, "action": "coin_flip_choose", "hand_index": 0},
    )
    assert rejected.status_code == 400

    # The loser chooses to go first; the new game starts with them on the play.
    chosen = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "coin_flip_choose", "hand_index": 0},
    )
    assert chosen.status_code == 200
    assert store.get(sid).pregame_starting_player == 0


def test_fresh_game_coin_flip_is_not_a_loser_choice():
    sid = _make_started_hvh_session(90201)
    pregame = client.get(f"/api/sessions/{sid}/state?seat=0").json()["pregame"]
    assert pregame["phase"] == "coin_flip"
    assert pregame["is_loser_choice"] is False
