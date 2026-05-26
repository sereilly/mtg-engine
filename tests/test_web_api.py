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
            "seed": 1234,
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
            "seed": 99001,
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
            "seed": 99061,
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
