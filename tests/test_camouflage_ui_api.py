"""Web-API tests for Camouflage's pile-division flow.

Camouflage replaces the declare-blockers step: the defending player divides
their untapped creatures into numbered piles (one per attacker; piles may be
empty), and the engine matches each pile to a different attacker at random.

- A human defender is prompted via the ``camouflage`` state info and answers
  with an ``assign_camouflage_piles`` action (Player-vs-Player and the
  AI-attacks-human case).
- An AI defender resolves with random piles when the human attacker advances
  the step (Player-vs-AI).
- Normal ``declare_blockers`` declarations are rejected while it is active.
"""
from __future__ import annotations

import random
from pathlib import Path

from fastapi.testclient import TestClient

from engine import load_cards
from engine.models import Permanent
from web.app import app, store

client = TestClient(app)

_CARDS = {c.name: c for c in load_cards(Path(__file__).resolve().parent.parent / "lea_cards.json")}


def _session(mode: str = "human_vs_ai"):
    created = client.post(
        "/api/sessions",
        json={"mode": mode, "host_name": "H", "host_colors": 2, "guest_colors": 2, "seed": 5},
    ).json()
    sid = created["session_id"]
    session = store.get(sid)
    return sid, session, session.game


def _setup_camouflage_combat(game, attacker_seat: int, defender_seat: int):
    """Two attackers vs two untapped defending creatures, at declare_blockers
    with Camouflage active this turn."""
    a1 = Permanent(card=_CARDS["Grizzly Bears"])
    a2 = Permanent(card=_CARDS["Hill Giant"])
    for a in (a1, a2):
        a.metadata["summoning_sickness_turn"] = -99
    d1 = Permanent(card=_CARDS["Grizzly Bears"])
    d2 = Permanent(card=_CARDS["Gray Ogre"])
    game.players[attacker_seat].battlefield = [a1, a2]
    game.players[defender_seat].battlefield = [d1, d2]
    game.active_player_index = attacker_seat
    game._set_phase_and_step("combat", "declare_attackers")
    game.combat_defending_player_index = defender_seat
    game.declare_attackers(attacker_seat, [0, 1])
    game.advance_combat_phase()  # -> declare_blockers
    game.camouflage_active_turn = game.turn
    assert game.current_step == "declare_blockers"


def test_human_defender_gets_camouflage_prompt_and_flag():
    # AI attacks (seat 1), human defends (seat 0): the prompt targets the human.
    sid, session, game = _session()
    session.current_turn = 1
    _setup_camouflage_combat(game, attacker_seat=1, defender_seat=0)

    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    assert state["combat"]["camouflage_active"] is True
    # Individually declarable blocks don't exist under Camouflage.
    assert state["combat"]["legal_blocker_assignments"] == []
    info = state["camouflage"]
    assert info is not None
    assert info["defender_seat"] == 0
    assert info["pile_count"] == 2
    assert sorted(c["index"] for c in info["divide_creatures"]) == [0, 1]

    # The attacking viewer sees the flag but not the defender's prompt.
    attacker_state = client.get(f"/api/sessions/{sid}/state", params={"seat": 1}).json()
    assert attacker_state["combat"]["camouflage_active"] is True
    assert attacker_state["camouflage"] is None


def test_normal_declare_blockers_rejected_while_camouflage_active():
    sid, session, game = _session()
    session.current_turn = 1
    _setup_camouflage_combat(game, attacker_seat=1, defender_seat=0)

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "declare_blockers", "blocker_pairs": {0: 0}},
    )
    assert resp.status_code == 400
    assert "Camouflage" in resp.json()["detail"]


def test_defender_assigns_piles_via_action():
    sid, session, game = _session()
    session.current_turn = 1
    _setup_camouflage_combat(game, attacker_seat=1, defender_seat=0)

    random.seed(7)
    # Both creatures into pile 0 (pile 1 empty): one random attacker gets both.
    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "assign_camouflage_piles", "camouflage_piles": {0: 0, 1: 0}},
    )
    assert resp.status_code == 200
    assert game.combat_blockers_locked is True
    blocked_attackers = {
        a for blocker_map in game.combat_blockers.values() for atks in blocker_map.values() for a in atks
    }
    assert len(blocked_attackers) == 1
    assert sorted(game.combat_blockers.get(0, {})) == [0, 1]
    # The prompt is gone once blocks are locked in.
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    assert state["camouflage"] is None


def test_only_defender_may_assign_piles():
    sid, session, game = _session()
    session.current_turn = 1
    _setup_camouflage_combat(game, attacker_seat=1, defender_seat=0)

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 1, "action": "assign_camouflage_piles", "camouflage_piles": {}},
    )
    assert resp.status_code == 400


def test_empty_pile_division_means_no_blocks():
    sid, session, game = _session()
    session.current_turn = 1
    _setup_camouflage_combat(game, attacker_seat=1, defender_seat=0)

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "assign_camouflage_piles", "camouflage_piles": {}},
    )
    assert resp.status_code == 200
    assert game.combat_blockers_locked is True
    assert game.combat_blockers == {}


def test_ai_defender_resolves_random_piles_on_advance():
    # Human attacks (seat 0), AI defends (seat 1): advancing the step makes the
    # AI divide its creatures into random piles instead of declaring blocks.
    sid, session, game = _session()
    session.current_turn = 0
    _setup_camouflage_combat(game, attacker_seat=0, defender_seat=1)

    random.seed(11)
    resp = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "next_phase"})
    assert resp.status_code == 200
    assert game.combat_blockers_locked is True
    assert any("Camouflage matched" in line for line in game.log)


def test_human_vs_human_defender_prompted():
    sid, session, game = _session(mode="human_vs_human")
    session.joined_seats.add(1)  # the guest seat acts only once joined
    session.awaiting_opponent = False
    session.current_turn = 0
    _setup_camouflage_combat(game, attacker_seat=0, defender_seat=1)

    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 1}).json()
    info = state["camouflage"]
    assert info is not None
    assert info["defender_seat"] == 1
    assert info["pile_count"] == 2

    # Splitting the creatures across both piles blocks both attackers.
    random.seed(3)
    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 1, "action": "assign_camouflage_piles", "camouflage_piles": {0: 0, 1: 1}},
    )
    assert resp.status_code == 200
    assert game.combat_blockers_locked is True
    blocked_attackers = {
        a for blocker_map in game.combat_blockers.values() for atks in blocker_map.values() for a in atks
    }
    assert blocked_attackers == {0, 1}
