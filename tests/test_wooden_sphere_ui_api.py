"""Web-API tests for Wooden Sphere's "pay {1} to gain life" prompt.

Wooden Sphere was reported FAILED in-game: "I don't get a prompt when a green
spell is cast." The color rods now defer their optional "you may pay {1}. If you
do, gain 1 life" trigger to a yes/no prompt, surfaced as `optional_pay` and
completed via the `resolve_optional_pay` action (AI auto-pays).
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
            "seed": 909,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    game.players[0].battlefield = [Permanent(card=_CARDS["Wooden Sphere"])]
    game.players[0].hand = [_CARDS["Grizzly Bears"]]  # a green spell
    game.players[0].mana_pool = {"C": 1}
    game.players[0].life = 20
    session.current_turn = 0
    game.active_player_index = 0
    # A green spell resolving triggers Wooden Sphere for its controller (seat 0).
    game.cast_from_hand(0, "Grizzly Bears")
    return sid, session, game


def test_green_spell_surfaces_the_pay_prompt():
    sid, session, game = _session()

    info = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()["optional_pay"]
    assert info is not None
    assert info["pending"][0]["card_name"] == "Wooden Sphere"
    assert info["pending"][0]["life"] == 1


def test_accepting_pays_one_and_gains_life():
    sid, session, game = _session()

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "resolve_optional_pay", "card_name": "Wooden Sphere", "accept": True},
    )
    assert resp.status_code == 200, resp.text
    assert game.players[0].life == 21
    assert game.players[0].mana_pool.get("C", 0) == 0
    assert game.pending_optional_pays == []


def test_declining_keeps_life_and_mana():
    sid, session, game = _session()

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "resolve_optional_pay", "card_name": "Wooden Sphere", "accept": False},
    )
    assert resp.status_code == 200, resp.text
    assert game.players[0].life == 20  # declined — no life gained
    assert game.players[0].mana_pool.get("C", 0) == 1  # mana kept
    assert game.pending_optional_pays == []
