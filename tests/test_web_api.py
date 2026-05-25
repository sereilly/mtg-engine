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


def test_create_session_uses_random_seed_by_default(monkeypatch):
    captured_seeds = []
    stub_deck = [_mk_card("Island", "", "Basic Land - Island", "") for _ in range(40)]

    def _fake_build_random_deck(_cards_path, _colors, seed):
        captured_seeds.append(seed)
        return list(stub_deck), ["U"]

    monkeypatch.setattr(web_session_store, "build_random_deck", _fake_build_random_deck)
    monkeypatch.setattr(web_session_store.secrets, "randbits", lambda _bits: 424242)

    response = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 3,
        },
    )

    assert response.status_code == 200
    assert captured_seeds == [424242, 424243]


def test_create_session_uses_custom_seed_when_enabled(monkeypatch):
    captured_seeds = []
    stub_deck = [_mk_card("Island", "", "Basic Land - Island", "") for _ in range(40)]

    def _fake_build_random_deck(_cards_path, _colors, seed):
        captured_seeds.append(seed)
        return list(stub_deck), ["U"]

    monkeypatch.setattr(web_session_store, "build_random_deck", _fake_build_random_deck)
    monkeypatch.setattr(web_session_store.secrets, "randbits", lambda _bits: 111111)

    response = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 3,
            "use_custom_seed": True,
            "custom_seed": 9001,
        },
    )

    assert response.status_code == 200
    assert captured_seeds == [9001, 9002]


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

    with client.stream("GET", f"/api/sessions/{sid}/events") as response:
        assert response.status_code == 200
        joined = client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
        assert joined.status_code == 200

        event_lines = _read_sse_event_lines(response)

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

    with client.stream("GET", f"/api/sessions/{sid}/events") as response:
        assert response.status_code == 200
        action = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "end_turn"})
        assert action.status_code == 200

        event_lines = _read_sse_event_lines(response)

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


def test_card_search_endpoint_returns_autocomplete_matches():
    response = client.get("/api/cards/search?query=air&limit=5")
    assert response.status_code == 200
    payload = response.json()
    assert "cards" in payload
    assert len(payload["cards"]) <= 5
    assert any(card["name"] == "Air Elemental" for card in payload["cards"])


def test_debug_action_adds_card_to_human_hand_case_insensitive_lookup():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 9090,
        },
    ).json()
    sid = created["session_id"]

    before_count = len(store.get(sid).game.players[0].hand)
    response = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "debug_add_to_hand", "card_name": "air elemental"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["players"][0]["hand"]) == before_count + 1
    assert payload["players"][0]["hand"][-1]["name"] == "Air Elemental"
    assert any("[Debug]" in entry and "Air Elemental" in entry for entry in payload["log"])


def test_debug_action_casts_card_for_free():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 9091,
        },
    ).json()
    sid = created["session_id"]

    response = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "debug_cast_free", "card_name": "lightning bolt"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["players"][1]["life"] == 17
    assert any("[Debug]" in entry and "Lightning Bolt" in entry for entry in payload["log"])


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


def test_web_activate_black_lotus_accepts_mana_color_choice():
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
    lotus = _mk_card(
        name="Black Lotus",
        mana_cost="{0}",
        type_line="Artifact",
        oracle_text="{T}, Sacrifice Black Lotus: Add three mana of any one color.",
    )
    session.game.players[0].battlefield = [Permanent(card=lotus)]
    session.game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}

    response = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "activate",
            "permanent_name": "Black Lotus",
            "target_seat": 0,
            "mana_color": "B",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["players"][0]["mana_pool"]["B"] == 3
    assert payload["players"][0]["mana_pool"]["G"] == 0
    assert payload["players"][0]["battlefield"] == []


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


def test_fastbond_allows_extra_land_and_deals_damage():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 92334,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})

    session = store.get(sid)
    fastbond = _mk_card(
        name="Fastbond",
        mana_cost="{G}",
        type_line="Enchantment",
        oracle_text=(
            "You may play any number of lands on each of your turns.\n"
            "Whenever you play a land, if it wasn't the first land you played this turn, "
            "this enchantment deals 1 damage to you."
        ),
    )
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
    session.game.players[0].hand = [fastbond, plains_a, plains_b]
    session.game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 1, "C": 0}
    session.game.players[0].life = 20

    cast_fastbond = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Fastbond", "target_seat": 0},
    )
    assert cast_fastbond.status_code == 200

    first_land = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Plains A", "target_seat": 0},
    )
    assert first_land.status_code == 200

    second_land_same_turn = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Plains B", "target_seat": 0},
    )
    assert second_land_same_turn.status_code == 200
    assert store.get(sid).game.players[0].life == 19


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
    session.game.current_turn_phase = "combat"
    session.game.current_step = "beginning_of_combat"
    session.game.current_phase = "combat"

    steps = [
        "declare_attackers",
        "declare_blockers",
        "end_of_combat",
    ]
    for expected in steps:
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

    session.game.current_step = "declare_attackers"
    client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "declare_attackers", "attacker_indices": [0], "target_seat": 1},
    )
    session.game.current_step = "declare_blockers"
    client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 1, "action": "declare_blockers", "blocker_pairs": {"0": 0}},
    )

    session.game.current_step = "combat_damage"
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


def test_next_phase_ai_defender_casts_instant_after_declaring_blockers():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_ai",
            "host_name": "Host",
            "guest_name": "AI",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 99202,
        },
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    attacker = _mk_creature_card("Attacker", 3, 3)
    blocker = _mk_creature_card("Blocker", 2, 2)
    bolt = _mk_card(
        name="Lightning Bolt",
        mana_cost="{R}",
        type_line="Instant",
        oracle_text="Lightning Bolt deals 3 damage to any target.",
    )
    mountain = _mk_card(
        name="Mountain",
        mana_cost="",
        type_line="Basic Land - Mountain",
        oracle_text="{T}: Add {R}.",
        produced_mana=("R",),
    )

    session.game.players[0].battlefield = [Permanent(card=attacker)]
    session.game.players[0].life = 20
    session.game.players[1].battlefield = [Permanent(card=blocker), Permanent(card=mountain)]
    session.game.players[1].hand = [bolt]
    session.game.players[1].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}
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

    ai_block_and_cast = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "next_phase"},
    )
    assert ai_block_and_cast.status_code == 200
    payload = ai_block_and_cast.json()
    assert payload["current_step"] == "declare_blockers"
    assert payload["combat"]["blockers_locked"] is True
    assert payload["players"][0]["life"] == 17


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


def test_winter_orb_turn_start_requires_untap_land_selection_for_human_player():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 99110,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})

    session = store.get(sid)
    forest = _mk_card(
        name="Forest",
        mana_cost="",
        type_line="Basic Land - Forest",
        oracle_text="{T}: Add {G}.",
        produced_mana=("G",),
    )
    winter_orb = _mk_card(
        name="Winter Orb",
        mana_cost="{2}",
        type_line="Artifact",
        oracle_text="As long as this artifact is untapped, players can't untap more than one land during their untap steps.",
    )

    session.current_turn = 0
    session.game.active_player_index = 0
    session.game.players[0].battlefield = [Permanent(card=winter_orb, tapped=False)]
    session.game.players[1].battlefield = [
        Permanent(card=forest, tapped=True),
        Permanent(card=forest, tapped=True),
    ]
    session.game.current_turn_phase = "postcombat_main"
    session.game.current_step = "postcombat_main"
    session.game.current_phase = "main"

    end_turn = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "end_turn"})
    assert end_turn.status_code == 200

    seat1_state = client.get(f"/api/sessions/{sid}/state?seat=1")
    assert seat1_state.status_code == 200
    state_payload = seat1_state.json()
    assert state_payload["current_turn"] == 1
    assert state_payload["current_step"] == "untap"
    assert state_payload["untap_land_selection"]["max_count"] == 1
    assert state_payload["untap_land_selection"]["selected_indices"] == []

    blocked = client.post(f"/api/sessions/{sid}/action", json={"seat": 1, "action": "next_phase"})
    assert blocked.status_code == 400
    assert "select untap lands" in blocked.json()["detail"].lower()

    pick_land = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 1, "action": "untap_select", "permanent_index": 0},
    )
    assert pick_land.status_code == 200
    pick_payload = pick_land.json()
    assert pick_payload["untap_land_selection"]["selected_indices"] == [0]

    confirm = client.post(f"/api/sessions/{sid}/action", json={"seat": 1, "action": "untap_confirm"})
    assert confirm.status_code == 200
    confirm_payload = confirm.json()
    assert confirm_payload["current_phase"] == "main"
    assert confirm_payload["current_step"] == "precombat_main"
    assert confirm_payload["untap_land_selection"] is None
    assert confirm_payload["players"][1]["battlefield"][0]["tapped"] is False
    assert confirm_payload["players"][1]["battlefield"][1]["tapped"] is True


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
