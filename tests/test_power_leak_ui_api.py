"""Web-API test for Power Leak's "pay mana to prevent damage" upkeep prompt.

Power Leak was reported FAILED in-game: "I didn't get any prompt." Power Leak
("...that player may pay any amount of mana. This Aura deals 2 damage to that
player. Prevent X of that damage...") needs an interactive amount prompt on the
enchanted enchantment's controller's upkeep. The engine already supported a
`mana_prevention` amount; the web layer never gathered or surfaced it. These tests
drive the HTTP flow the prompt now uses.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from engine import load_cards
from engine.models import Permanent
import web.app as web_app
from web.app import app, store

client = TestClient(app)

_CARDS = {c.name: c for c in load_cards(Path(__file__).resolve().parent.parent / "lea_cards.json")}


def _power_leak_session(prevention_mana: int):
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_ai", "host_name": "H", "host_colors": 2, "guest_colors": 2, "seed": 11},
    ).json()
    sid = created["session_id"]
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    # Human (seat 0) controls an enchantment; Power Leak enchants it.
    bad_moon = Permanent(card=_CARDS["Bad Moon"])
    game.players[0].battlefield = [bad_moon]
    game.players[0].hand = [_CARDS["Power Leak"]]
    game.players[0].life = 20
    game.players[0].mana_pool = {"C": prevention_mana}
    game.cast_from_hand(0, "Power Leak", target_player_index=0, target_permanent_index=0)
    game.resolve_stack()
    session.current_turn = 0
    game.active_player_index = 0
    game._set_phase_and_step("beginning", "upkeep")
    # Gather the upkeep decisions exactly as the turn-begin flow does for a human.
    web_app._gather_upkeep_decisions(session, 0)
    return sid, session, game


def test_power_leak_surfaces_a_prevention_prompt():
    sid, session, game = _power_leak_session(prevention_mana=2)

    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    info = state["upkeep_mana_prevention"]
    assert info is not None
    assert info["pending"][0]["card_name"] == "Power Leak"
    assert info["pending"][0]["damage"] == 2
    assert info["available_mana"] == 2


def test_paying_full_prevents_all_damage():
    sid, session, game = _power_leak_session(prevention_mana=2)

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "pay_upkeep_prevention", "card_name": "Power Leak", "amount": 2},
    )
    assert resp.status_code == 200, resp.text
    assert game.players[0].life == 20  # all 2 damage prevented
    assert game.players[0].mana_pool.get("C", 0) == 0  # the 2 mana was spent


def test_paying_nothing_takes_full_damage():
    sid, session, game = _power_leak_session(prevention_mana=2)

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "pay_upkeep_prevention", "card_name": "Power Leak", "amount": 0},
    )
    assert resp.status_code == 200, resp.text
    assert game.players[0].life == 18  # took the full 2 damage (nothing prevented)
