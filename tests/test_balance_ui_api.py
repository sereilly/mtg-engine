"""Web-API tests for Balance's interactive sacrifice/discard prompt.

Balance was reported FAILED in-game: "Balance should give me a prompt to let me
choose which creatures and lands get destroyed. The prompt should show the number
selected/total for each type." The effect now defers to a per-player choice,
surfaced as `balance_select` and completed via the `balance_confirm` action.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from engine import load_cards
from engine.models import Permanent
from web.app import app, store

client = TestClient(app)

_CARDS = {c.name: c for c in load_cards(Path(__file__).resolve().parent.parent / "lea_cards.json")}


def _session():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 5150,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    # Seat 0: 2 lands + 1 creature; Seat 1: 1 land + 2 creatures.
    game.players[0].battlefield = [
        Permanent(card=_CARDS["Plains"]),
        Permanent(card=_CARDS["Plains"]),
        Permanent(card=_CARDS["Grizzly Bears"]),
    ]
    game.players[0].hand = [_CARDS["Balance"]]
    game.players[1].battlefield = [
        Permanent(card=_CARDS["Plains"]),
        Permanent(card=_CARDS["Grizzly Bears"]),
        Permanent(card=_CARDS["Grizzly Bears"]),
    ]
    game.players[1].hand = []
    session.current_turn = 0
    game.active_player_index = 0
    game.cast_from_hand(0, "Balance", target_player_index=1)
    return sid, session, game


def test_balance_surfaces_a_sacrifice_plan_with_counts():
    sid, session, game = _session()

    info = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()["balance_select"]
    assert info is not None
    assert info["lands_to_sacrifice"] == 1  # 2 lands down to the lowest count (1)
    assert info["creatures_to_sacrifice"] == 0  # already at the minimum
    assert len(info["lands"]) == 2  # both lands shown to choose from


def test_player_chooses_which_land_to_sacrifice():
    sid, session, game = _session()

    # Sacrifice the second Plains (battlefield index 1); keep index 0 and the Bear.
    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "balance_confirm", "land_indices": [1]},
    )
    assert resp.status_code == 200, resp.text
    lands = [p for p in game.players[0].battlefield if p.card.primary_type == "land"]
    assert len(lands) == 1
    assert any(c.name == "Plains" for c in game.players[0].graveyard)
    # Seat 0's plan is resolved; only seat 1's remains.
    assert 0 not in (game.pending_balance or {"plans": {}})["plans"]


def test_wrong_count_is_rejected():
    sid, session, game = _session()

    # The plan requires exactly 1 land sacrificed; submitting zero is illegal.
    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "balance_confirm", "land_indices": []},
    )
    assert resp.status_code == 400
