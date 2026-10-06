"""The web layer's AI seat answers "as though it weren't blocked" on its merits.

The third of the three places a default assignment is supplied — the engine's
own auto-resolve and the simulator's driver are held by
``tests/ai/test_ai_unblocked_offer.py``. An AI attacker here took the offer
whatever stood in front of it; it now keeps its damage on a blocker that would
die, with one blocker (the engine's step, reached through the web flow) and
with two (``web/combat_prompts._ai_assign_combat_damage``, the web layer's own
default). Driven the way a client drives a game: the human defender declares
blocks and passes, and the AI seat is stepped.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from engine.combat_assignment import AS_THOUGH_UNBLOCKED_LOG
from engine.models import Permanent
from web.app import app, store

from tests.helpers import _mk_creature_card

client = TestClient(app)

OFFER = "You may have this creature assign its combat damage as though it weren't blocked."


def _act(sid: str, **body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def _state(sid: str, seat: int) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _ai_attacks_into(blockers, *, life: int = 20):
    """An AI seat's 5/5 with the offer attacks a human whose *blockers* all
    block it; the combat is played out through client actions."""
    created = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 51011,
    }).json()
    sid = created["session_id"]
    session = store.get(sid)
    game = session.game
    beast = Permanent(card=_mk_creature_card("Slipping Beast", 5, 5, OFFER))
    walls = [
        Permanent(card=_mk_creature_card(f"Wall {number}", power, toughness))
        for number, (power, toughness) in enumerate(blockers)
    ]
    game.players[1].battlefield = [beast]
    game.players[0].battlefield = list(walls)
    game.players[0].hand = []
    game.players[1].hand = []
    game.players[0].life = life
    game.players[1].life = 20
    session.current_turn = 1
    game.active_player_index = 1
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(1, [0], defending_player_index=0)
    assert ok, why

    asked = False
    for _ in range(12):
        state = _state(sid, 0)
        asked = asked or state["unblocked_assignment"] is not None
        if state["current_turn_phase"] != "combat":
            break
        if state["current_step"] == "declare_blockers" and not state["combat"]["blockers_locked"]:
            pairs = {str(slot): 0 for slot in range(len(walls))}
            assert _act(sid, seat=0, action="declare_blockers",
                        blocker_pairs=pairs).status_code == 200
        elif state.get("priority_player") == 0:
            assert _act(sid, seat=0, action="pass_priority").status_code == 200
        else:
            assert _act(sid, seat=0, action="ai_step").status_code == 200
    assert _state(sid, 0)["current_turn_phase"] != "combat", "combat never finished"
    assert not asked, "the human defender has no choice to make (CR 510.1)"
    return game, beast, walls


@pytest.mark.parametrize("blockers", [[(1, 4)], [(1, 4), (0, 9)]])
def test_an_ai_attacker_kills_the_blocker_it_can_rather_than_walk_past_it(blockers):
    game, _beast, walls = _ai_attacks_into(blockers)

    assert game.players[0].life == 20, game.log[-8:]
    assert not game.is_on_battlefield(walls[0]), "the blocker it could kill is dead"
    assert not any(AS_THOUGH_UNBLOCKED_LOG in line for line in game.log)


@pytest.mark.parametrize("blockers", [[(1, 4)], [(1, 4), (0, 9)]])
def test_an_ai_attacker_walks_past_its_blockers_for_the_last_points_of_life(blockers):
    game, _beast, walls = _ai_attacks_into(blockers, life=5)

    assert game.players[0].life == 0, game.log[-8:]
    assert all(wall.damage_marked == 0 for wall in walls)
    assert any(AS_THOUGH_UNBLOCKED_LOG in line for line in game.log)
