from fastapi.testclient import TestClient

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
    assert payload["seat"] == 0


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


def test_web_session_requires_paid_mana_before_cast():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 999,
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
    mountain = _mk_card(
        name="Mountain",
        mana_cost="",
        type_line="Basic Land - Mountain",
        oracle_text="{T}: Add {R}.",
        produced_mana=("R",),
    )

    session.game.players[0].hand = [bolt]
    session.game.players[0].battlefield = [Permanent(card=mountain)]
    session.game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}
    session.game.players[1].life = 20

    unpaid_cast = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Bolt Test", "target_seat": 1},
    )
    assert unpaid_cast.status_code == 400
    assert "insufficient mana" in unpaid_cast.json()["detail"].lower()

    tap_land = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "activate", "permanent_name": "Mountain", "target_seat": 0},
    )
    assert tap_land.status_code == 200

    paid_cast = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Bolt Test", "target_seat": 1},
    )
    assert paid_cast.status_code == 200
    assert store.get(sid).game.players[1].life == 17


def test_web_cast_accepts_explicit_x_value():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 4041,
        },
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    stream = _mk_card(
        name="Stream of Life",
        mana_cost="{X}{G}",
        type_line="Sorcery",
        oracle_text="Target player gains X life.",
    )
    session.game.players[0].hand = [stream]
    session.game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 1, "C": 1}
    session.game.players[0].life = 10

    response = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Stream of Life", "target_seat": 0, "x_value": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["players"][0]["life"] == 11
    assert any("Stream of Life" in entry and "10 -> 11" in entry for entry in payload["log"])


def test_stream_of_life_defaults_to_self_target():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 4042,
        },
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    stream = _mk_card(
        name="Stream of Life",
        mana_cost="{X}{G}",
        type_line="Sorcery",
        oracle_text="Target player gains X life.",
    )
    session.game.players[0].hand = [stream]
    session.game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 1, "C": 1}
    session.game.players[0].life = 10

    response = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Stream of Life", "x_value": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["players"][0]["life"] == 11
    assert payload["players"][1]["life"] == 20
    assert any("Stream of Life" in entry and "10 -> 11" in entry for entry in payload["log"])


def test_stream_of_life_x_spends_generic_mana_from_pool():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 4043,
        },
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    stream = _mk_card(
        name="Stream of Life",
        mana_cost="{X}{G}",
        type_line="Sorcery",
        oracle_text="Target player gains X life.",
    )
    session.game.players[0].hand = [stream]
    session.game.players[0].mana_pool = {"W": 0, "U": 0, "B": 1, "R": 0, "G": 1, "C": 0}
    session.game.players[0].life = 10

    response = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Stream of Life", "target_seat": 0, "x_value": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["players"][0]["life"] == 11
    assert payload["players"][0]["mana_pool"]["G"] == 0
    assert payload["players"][0]["mana_pool"]["B"] == 0


def test_stream_of_life_updates_life_total_and_log_in_response():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 4040,
        },
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    stream = _mk_card(
        name="Stream of Life",
        mana_cost="{X}{G}",
        type_line="Sorcery",
        oracle_text="Target player gains X life.",
    )
    session.game.players[0].hand = [stream]
    session.game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 1, "C": 1}
    session.game.players[0].life = 10

    response = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Stream of Life", "target_seat": 0},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["players"][0]["life"] == 11
    assert any("Stream of Life" in entry and "10 -> 11" in entry for entry in payload["log"])


def test_tap_action_on_land_adds_mana_and_cannot_retap():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 2026,
        },
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    mountain = _mk_card(
        name="Mountain",
        mana_cost="",
        type_line="Basic Land - Mountain",
        oracle_text="{T}: Add {R}.",
        produced_mana=("R",),
    )
    session.game.players[0].battlefield = [Permanent(card=mountain)]
    session.game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}

    first_tap = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "tap", "permanent_name": "Mountain"},
    )
    assert first_tap.status_code == 200
    assert store.get(sid).game.players[0].mana_pool["R"] == 1

    second_tap = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "tap", "permanent_name": "Mountain"},
    )
    assert second_tap.status_code == 400


def test_activate_land_uses_permanent_index_when_duplicate_names_exist():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 2027,
        },
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    forest = _mk_card(
        name="Forest",
        mana_cost="",
        type_line="Basic Land - Forest",
        oracle_text="{T}: Add {G}.",
        produced_mana=("G",),
    )

    first_forest = Permanent(card=forest)
    second_forest = Permanent(card=forest)
    session.game.players[0].battlefield = [first_forest, second_forest]
    session.game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}

    tap_second = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "activate",
            "permanent_name": "Forest",
            "permanent_index": 1,
            "target_seat": 0,
        },
    )

    assert tap_second.status_code == 200
    assert session.game.players[0].battlefield[0].tapped is False
    assert session.game.players[0].battlefield[1].tapped is True
    assert session.game.players[0].mana_pool["G"] == 1


def test_activate_with_mana_cost_requires_payment_before_tap():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 3030,
        },
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    tome = _mk_card(
        name="Jayemdae Tome",
        mana_cost="{4}",
        type_line="Artifact",
        oracle_text="{4}, {T}: Draw a card.",
    )
    island = _mk_card(
        name="Island",
        mana_cost="",
        type_line="Basic Land - Island",
        oracle_text="{T}: Add {U}.",
        produced_mana=("U",),
    )

    session.game.players[0].battlefield = [Permanent(card=tome)]
    session.game.players[0].library = [island]
    session.game.players[0].mana_pool = {"W": 0, "U": 3, "B": 0, "R": 0, "G": 0, "C": 0}

    unpaid = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "activate", "permanent_name": "Jayemdae Tome", "target_seat": 1},
    )
    assert unpaid.status_code == 400
    assert "insufficient mana" in unpaid.json()["detail"].lower()
    assert store.get(sid).game.players[0].battlefield[0].tapped is False

    session.game.players[0].mana_pool = {"W": 0, "U": 4, "B": 0, "R": 0, "G": 0, "C": 0}
    paid = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "activate", "permanent_name": "Jayemdae Tome", "target_seat": 1},
    )
    assert paid.status_code == 200
    assert store.get(sid).game.players[0].battlefield[0].tapped is True


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

    off_turn_cast = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Sorcery Test", "target_seat": 1},
    )
    assert off_turn_cast.status_code == 400
    assert "non-instant" in off_turn_cast.json()["detail"].lower()


def test_instant_allowed_on_opponent_turn():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 12345,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})

    session = store.get(sid)
    instant = _mk_card(
        name="Bolt Test",
        mana_cost="{R}",
        type_line="Instant",
        oracle_text="Bolt Test deals 3 damage to any target.",
    )
    mountain = _mk_card(
        name="Mountain",
        mana_cost="",
        type_line="Basic Land - Mountain",
        oracle_text="{T}: Add {R}.",
        produced_mana=("R",),
    )
    session.game.players[0].hand = [instant]
    session.game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 1, "G": 0, "C": 0}
    session.game.players[0].battlefield = [Permanent(card=mountain)]
    session.game.players[1].life = 20

    client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "end_turn"})
    assert store.get(sid).current_turn == 1

    tap_mountain = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "activate", "permanent_name": "Mountain", "target_seat": 0},
    )
    assert tap_mountain.status_code == 200

    off_turn_instant = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Bolt Test", "target_seat": 1},
    )
    assert off_turn_instant.status_code == 200
    assert store.get(sid).game.players[1].life == 17


def test_only_one_land_play_per_turn_then_resets_next_turn():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 22334,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})

    session = store.get(sid)
    plains_a = _mk_card(
        name="Plains A",
        mana_cost="",
        type_line="Basic Land - Plains",
        oracle_text="{T}: Add {W}.",
        produced_mana=("W",),
    )
    plains_b = _mk_card(
        name="Plains B",
        mana_cost="",
        type_line="Basic Land - Plains",
        oracle_text="{T}: Add {W}.",
        produced_mana=("W",),
    )
    session.game.players[0].hand = [plains_a, plains_b]

    first_land = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Plains A", "target_seat": 0},
    )
    assert first_land.status_code == 200

    second_land_same_turn = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Plains B", "target_seat": 0},
    )
    assert second_land_same_turn.status_code == 400
    assert "already played a land" in second_land_same_turn.json()["detail"].lower()

    client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "end_turn"})
    seat1_end = client.post(f"/api/sessions/{sid}/action", json={"seat": 1, "action": "end_turn"})
    if seat1_end.status_code == 200 and seat1_end.json().get("cleanup_discard"):
        client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 1, "action": "cleanup_select", "hand_index": 0},
        )
        client.post(f"/api/sessions/{sid}/action", json={"seat": 1, "action": "next_phase"})

    second_land_next_turn = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Plains B", "target_seat": 0},
    )
    assert second_land_next_turn.status_code == 200


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
    session.game.current_phase = "main"

    response = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "next_phase"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["current_phase"] == "combat"
    assert payload["players"][0]["mana_pool"]["R"] == 0


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
    session.game.current_phase = "combat"
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
