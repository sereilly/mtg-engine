"""Web-API tests for a substituted block chooser (Melee).

"You choose which creatures block this combat and how those creatures block."
CR 509.1a's chooser moves to another seat while the declaration itself stays the
defending player's — their creatures block, their entry in ``combat_blockers``
is the one written, and CR 509.1d-f still charges them.

Three things the wire has to get right, and each of them used to have its own
answer to "who declares this defender's blocks?":

- the state payload names the chooser per defending seat, so the board can
  offer the declaration to whoever owes it;
- the action endpoint takes a declaration from a seat that is not defending,
  made *for* the defender, and refuses the defender's own;
- the AI stepper prompts the chooser's seat rather than the defender's, so a
  human defender is not waited on for a decision an AI is making.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine import load_cards
from engine.models import Permanent
from web.app import app, store
from web.game_flow import _advance_phase
from tests.helpers import LEA_PATH

client = TestClient(app)

_CARDS = {c.name: c for c in load_cards(LEA_PATH)}


def _session(mode: str = "human_vs_human"):
    created = client.post(
        "/api/sessions",
        json={"mode": mode, "host_name": "H", "host_colors": 2, "guest_colors": 2, "seed": 5},
    ).json()
    sid = created["session_id"]
    session = store.get(sid)
    # The guest seat acts only once joined (web/actions.py's seat gate).
    session.joined_seats.add(1)
    return sid, session, session.game


def _combat(game, attacker_seat: int, defender_seat: int):
    """One attacker each side, stopped at declare_blockers."""
    attacker = Permanent(card=_CARDS["Grizzly Bears"])
    attacker.metadata["summoning_sickness_turn"] = -99
    blocker = Permanent(card=_CARDS["Hill Giant"])
    blocker.metadata["summoning_sickness_turn"] = -99
    game.players[attacker_seat].battlefield = [attacker]
    game.players[defender_seat].battlefield = [blocker]
    game.active_player_index = attacker_seat
    game._set_phase_and_step("combat", "declare_attackers")
    game.combat_defending_player_index = defender_seat
    game.declare_attackers(attacker_seat, [0])
    game.advance_combat_phase()  # -> declare_blockers
    assert game.current_step == "declare_blockers"
    return attacker, blocker


def test_the_state_names_the_chooser_for_each_defending_seat():
    sid, session, game = _session()
    session.current_turn = 0
    _combat(game, attacker_seat=0, defender_seat=1)

    ordinary = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    # Every seat maps to itself until something substitutes one, so a reader may
    # consult the map unconditionally.
    assert ordinary["combat"]["block_chooser"] == {"1": 1}

    game.combat_block_chooser = 0
    substituted = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    assert substituted["combat"]["block_chooser"] == {"1": 0}


def test_the_chooser_declares_the_defenders_blocks_and_the_defender_may_not():
    sid, session, game = _session()
    session.current_turn = 0
    _attacker, blocker = _combat(game, attacker_seat=0, defender_seat=1)
    game.combat_block_chooser = 0

    refused = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 1, "action": "declare_blockers", "blocker_pairs": {0: 0}},
    )
    assert refused.status_code == 400
    assert "chooses which creatures block" in refused.json()["detail"]

    accepted = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "declare_blockers",
            "target_seat": 1,
            "blocker_pairs": {0: 0},
        },
    )
    assert accepted.status_code == 200, accepted.json()
    # The defender's own entry, with the defender's own creature in it.
    assert game.combat_blockers == {1: {0: [0]}}
    assert blocker.blocking_attacker_index == 0


def test_an_ai_chooser_blocks_with_nothing_and_does_not_wait_on_the_defender():
    """The human is the defending player and an AI is choosing their blocks, so
    the rail must not stop for the human — and an AI choosing for the seat it is
    attacking declares no blocks, which is the play the card is cast for."""
    sid, session, game = _session(mode="human_vs_ai")
    # Seat 1 is the AI in human_vs_ai; make it the attacker and the chooser.
    session.current_turn = 1
    _combat(game, attacker_seat=1, defender_seat=0)
    game.combat_block_chooser = 1

    # The rail's own step, driven directly: `next_phase` belongs to the active
    # player and the AI is the one holding the turn here.
    _advance_phase(session)

    assert game.combat_blockers == {}
    assert game.combat_blockers_locked is True
