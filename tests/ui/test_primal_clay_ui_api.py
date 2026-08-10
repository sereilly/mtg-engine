"""Web-API tests for Primal Clay's "choose your body" prompt.

Primal Clay reads "As this creature enters, it becomes your choice of a 3/3
creature, a 2/2 creature with flying, or a 1/6 Wall creature with defender."
The engine armed the choice for a human controller and stopped there: there
was no renderer, no action, and no auto-answer, so the prompt was never shown,
never answerable, and never cleared — the controller silently got the first
printed body. That is the failure the pending-choice registry exists to make
impossible, and these tests are the behavioural half of the fix.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_cards, manifest_set_paths
from web.app import app, store

client = TestClient(app)

_CARDS = {c.name: c for path in manifest_set_paths() for c in load_cards(path)}


def _session():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 909,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    game.players[0].hand = [_CARDS["Primal Clay"]]
    session.current_turn = 0
    game.active_player_index = 0
    game.cast_from_hand(0, "Primal Clay")
    return sid, session, game


def test_body_choice_is_surfaced_to_the_controller():
    sid, _session_obj, _game = _session()

    info = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()["body_choice"]
    assert info is not None
    assert info["card_name"] == "Primal Clay"
    assert [(o["power"], o["toughness"]) for o in info["options"]] == [(3, 3), (2, 2), (1, 6)]

    # It belongs to its controller — the opponent is not shown someone else's choice.
    assert client.get(f"/api/sessions/{sid}/state", params={"seat": 1}).json()["body_choice"] is None


def test_controller_chooses_the_body():
    sid, _session_obj, game = _session()
    clay = game.players[0].battlefield[0]
    # The first printed body applies immediately, so headless play never blocks.
    assert (clay.effective_power, clay.effective_toughness) == (3, 3)

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "body_choice_confirm", "hand_index": 2},
    )
    assert resp.status_code == 200, resp.text
    assert (clay.effective_power, clay.effective_toughness) == (1, 6)
    assert game._has_keyword(clay, "defender") is True
    assert game.pending_body_choice is None


def test_the_prompt_holds_the_controller_until_it_is_answered():
    sid, _session_obj, _game = _session()

    resp = client.post(
        f"/api/sessions/{sid}/action", json={"seat": 0, "action": "pass_priority"}
    )
    assert resp.status_code == 400
    assert "body" in resp.json()["detail"]

    client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "body_choice_confirm", "hand_index": 0},
    )
    # Answering releases the hold. (Whether this scripted board has a priority
    # window open is a different question, so assert on the reason, not the code.)
    resp = client.post(
        f"/api/sessions/{sid}/action", json={"seat": 0, "action": "pass_priority"}
    )
    assert "body" not in resp.text
