"""Web-API test for Rock Hydra's two-activated-ability UI flow.

Rock Hydra was reported FAILED in-game: "Rock Hydra has 2 activated abilities. It
should let me choose which one to activate when I click on the card." The fix adds
a client-side ability picker that sends the chosen ability as `ability_index` on
the `activate` action. This test drives the exact HTTP request the picker now
issues and asserts each ability resolves to the right effect.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from engine import load_cards
from engine.models import Permanent
from web.app import app, store

client = TestClient(app)

_CARDS = {c.name: c for c in load_cards(Path(__file__).resolve().parent.parent / "lea_cards.json")}


def _new_hvh_session() -> str:
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 90210,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    return sid


def _hydra_session():
    sid = _new_hvh_session()
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    hydra = Permanent(card=_CARDS["Rock Hydra"])
    hydra.metadata["summoning_sickness_turn"] = -99
    # Entered with X=3 counters; without them it is a 0/0 and dies (704.5f).
    hydra.power_bonus = 3
    hydra.toughness_bonus = 3
    game.players[0].battlefield = [hydra]
    session.current_turn = 0
    game.active_player_index = 0
    game._set_phase_and_step("beginning", "upkeep")
    return sid, game, hydra


def _activate(sid: str, ability_index: int):
    return client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "activate",
            "permanent_name": "Rock Hydra",
            "permanent_index": 0,
            "ability_index": ability_index,
        },
    )


def test_ability_index_one_adds_a_counter_via_api():
    sid, game, hydra = _hydra_session()
    before = hydra.effective_power

    resp = _activate(sid, 1)  # {R}{R}{R}: put a +1/+1 counter

    assert resp.status_code == 200, resp.text
    game.resolve_stack()  # resolve the queued ability
    assert hydra.effective_power == before + 1


def test_ability_index_zero_is_the_prevention_ability_via_api():
    sid, game, hydra = _hydra_session()
    before = hydra.effective_power

    resp = _activate(sid, 0)  # {R}: prevent the next 1 damage

    assert resp.status_code == 200, resp.text
    game.resolve_stack()  # resolve the queued ability
    # The prevention ability does not add a counter (distinct from ability 1).
    assert hydra.effective_power == before
