"""Web-API tests for a prompt one player owes about *another* player's zone.

Every other pending choice in this engine is owed by the player it is about, so
"whose seat answers" and "whose cards are shown" have always been the same
number. Duress separates them: the caster chooses, the opponent's hand is what
they choose from, and the hand is public from the moment the card revealed it
(CR 701.20). These pin what each side of the wire sees.

M21 is measured, not shipped, so no deck can hold Duress and the Debug Menu
cannot inject it — the cards are placed into the session directly, which is what
the cast-from-zone suite does for the same reason.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine import load_cards
from engine.card_loader import manifest_set_path
from web.app import app, store

client = TestClient(app)

_M21 = {c.name: c for c in load_cards(manifest_set_path("M21", include_measured=True))}


def _session():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 404,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    game.players[0].hand = [_M21["Duress"]]
    game.players[0].library = [_M21["Swamp"]] * 3
    game.players[1].hand = [
        _M21["Alpine Watchdog"],   # creature — not choosable
        _M21["Shock"],
        _M21["Island"],            # land — not choosable
        _M21["Volcanic Salvo"],
    ]
    session.current_turn = 0
    game.active_player_index = 0
    game.cast_from_hand(0, "Duress", target_player_index=1)
    return sid, session, game


def _state(sid: str, seat: int = 0) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def test_the_prompt_reaches_the_caster_and_shows_the_revealed_hand():
    sid, _sess, _game = _session()

    prompt = _state(sid, seat=0)["revealed_hand_pick"]
    assert prompt is not None
    assert prompt["player_seat"] == 0, "the caster chooses"
    assert prompt["victim_seat"] == 1
    assert [card["name"] for card in prompt["cards"]] == [
        "Alpine Watchdog", "Shock", "Island", "Volcanic Salvo",
    ], "the whole hand — the card revealed it, so hiding any of it shows less than the game does"
    assert prompt["legal_indices"] == [1, 3]


def test_the_caster_cannot_act_around_the_open_prompt():
    sid, _sess, _game = _session()

    refused = client.post(
        f"/api/sessions/{sid}/action", json={"seat": 0, "action": "pass_priority"}
    )
    assert refused.status_code == 400
    assert "revealed hand" in refused.json()["detail"]


def test_an_excluded_card_is_refused_on_the_wire():
    sid, _sess, game = _session()

    refused = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "revealed_hand_pick_confirm", "hand_index": 0},
    )
    assert refused.status_code == 400
    assert game.players[1].graveyard == []


def test_a_seat_that_is_not_the_caster_cannot_answer():
    sid, _sess, game = _session()

    refused = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 1, "action": "revealed_hand_pick_confirm", "hand_index": 1},
    )
    assert refused.status_code == 400
    assert game.players[1].graveyard == []


def test_confirming_discards_the_chosen_card_and_clears_the_prompt():
    sid, _sess, game = _session()

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "revealed_hand_pick_confirm", "hand_index": 3},
    )
    assert resp.status_code == 200, resp.text

    assert [c.name for c in game.players[1].graveyard] == ["Volcanic Salvo"]
    assert _state(sid)["revealed_hand_pick"] is None
