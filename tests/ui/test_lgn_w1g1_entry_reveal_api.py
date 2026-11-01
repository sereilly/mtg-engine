"""Amplify's reveal (CR 702.38a) on the wire: rendered to the seat that owes it
and to nobody else, gating that seat's other actions, and answered by
``entry_reveal_confirm`` with the hand slots to reveal.

This holds the server half. The client half is ``applyEntryRevealPrompt`` in
``web/static/app.js``, run over this payload by
``tests/ui/test_lgn_w2g1_client_ui_api.py``.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_cards, load_catalog, manifest_set_path
from engine.models import Permanent
from engine.named_counters import counters_on
from web.app import app, store

client = TestClient(app)
_CARDS = {card.name: card for card in load_catalog()}
_LGN = {card.name: card for card in load_cards(manifest_set_path("LGN", include_measured=True))}


def _session(hand):
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
            "host_colors": 2, "guest_colors": 2, "seed": 3802,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    game.players[0].battlefield = []
    game.players[1].battlefield = [Permanent(card=_CARDS["Mountain"])]
    game.players[0].hand = list(hand)
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, game


def _rogon_entering():
    sid, game = _session([
        _LGN["Glowering Rogon"], _LGN["Canopy Crawler"], _CARDS["Island"],
        _LGN["Feral Throwback"],
    ])
    assert game.cast_from_hand(0, "Glowering Rogon").supported
    game.resolve_top_of_stack()
    assert game.pending_choice_of("entry_reveal", 0) is not None
    return sid, game


def test_the_reveal_is_rendered_to_its_chooser_alone():
    sid, _game = _rogon_entering()
    mine = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    prompt = mine["entry_reveal"]
    assert prompt["card_name"] == "Glowering Rogon"
    assert prompt["counters_each"] == 1 and prompt["any_number"] is True
    assert prompt["creature_types"] == ["beast"]
    assert prompt["choices"] == [
        {"hand_index": 0, "name": "Canopy Crawler"},
        {"hand_index": 2, "name": "Feral Throwback"},
    ]
    theirs = client.get(f"/api/sessions/{sid}/state", params={"seat": 1}).json()
    assert theirs.get("entry_reveal") is None


def test_the_reveal_gates_the_seat_and_is_answered_by_its_action():
    sid, game = _rogon_entering()
    url = f"/api/sessions/{sid}/action"
    blocked = client.post(url, json={"seat": 0, "action": "pass_priority"})
    assert blocked.status_code == 400

    outside = client.post(url, json={"seat": 0, "action": "entry_reveal_confirm",
                                     "hand_indices": [1]})
    assert outside.status_code == 400
    assert game.pending_choice_of("entry_reveal", 0) is not None

    answered = client.post(url, json={"seat": 0, "action": "entry_reveal_confirm",
                                      "hand_indices": [0, 2]})
    assert answered.status_code == 200, answered.text
    rogon = next(p for p in game.controlled_by(0) if p.card.name == "Glowering Rogon")
    assert counters_on(rogon, "+1/+1") == 2
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 1}).json()
    assert state.get("entry_reveal") is None
    shown = next(c for c in state["players"][0]["battlefield"] if c["name"] == "Glowering Rogon")
    assert (shown["power"], shown["toughness"]) == (6, 6)


def test_revealing_nothing_is_an_answer():
    sid, game = _rogon_entering()
    answered = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "entry_reveal_confirm", "hand_indices": [],
    })
    assert answered.status_code == 200, answered.text
    assert game.pending_choice_of("entry_reveal", 0) is None
