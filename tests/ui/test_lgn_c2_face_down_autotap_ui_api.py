"""The auto-tap of a face-down cast leaves the card's own turn-up payable —
Onslaught's Phase 5 board, through the wire.

Four Plains, three Mountains and Exalted Angel cast face down for {3}. Phase 5
recorded the auto-tap planning three Plains, so the Angel's morph cost
{2}{W}{W} could not be paid; round kg2 drained the neighbouring board (the
Angel already face down while something else is cast) and Phase 5 drove this
one again on 2026-11-01 to the same three Plains. The engine's purpose for a
face-down cast names the 2/2 (CR 702.37c), which the payer's wants did not
read as the Angel leaving the hand with its turn-up still owed (CR 702.37e);
``mana_wants.wants_brought_by`` reads it so. The preview is what the cast taps,
and the Angel then turns up through the route.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.face_down import is_face_down
from engine.models import Permanent
from tests.helpers import resolve_stack
from web.app import app, store

client = TestClient(app)
_CARDS = {card.name: card for card in load_catalog()}


def _session(board, hand):
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 4245,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    session.pregame_phase = None
    game.enforce_mana_costs = True
    game.players[0].battlefield = []
    game.players[1].battlefield = []
    for name in board:
        permanent = Permanent(card=_CARDS[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        permanent.tapped = False
    game._recompute_continuous_effects()
    game.players[0].hand = [_CARDS[name] for name in hand]
    game.players[0].library = [_CARDS["Plains"]] * 5
    game.stack.clear()
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, game


def test_the_angel_cast_face_down_leaves_its_turn_up_payable():
    sid, game = _session(["Plains"] * 4 + ["Mountain"] * 3, ["Exalted Angel"])
    body = {
        "seat": 0, "action": "cast", "card_name": "Exalted Angel",
        "alternative_cost": True,
    }

    preview = client.post(f"/api/sessions/{sid}/payment_plan", json=body)
    assert preview.status_code == 200, preview.text
    plan = preview.json()
    assert plan["payable"] is True
    assert plan["cost"].get("generic") == 3, plan["cost"]
    assert sum(tap["name"] == "Plains" for tap in plan["taps"]) <= 2, plan["taps"]

    response = client.post(f"/api/sessions/{sid}/action", json={**body, "auto_tap": True})
    assert response.status_code == 200, response.text
    tapped = sorted(p.permanent_id for p in game.controlled_by(0) if p.tapped)
    assert tapped == sorted(tap["id"] for tap in plan["taps"])
    resolve_stack(game)
    (angel,) = [p for p in game.controlled_by(0) if p.is_creature]
    assert is_face_down(angel)
    untapped = [
        p.card.name for p in game.controlled_by(0) if p.has_type("land") and not p.tapped
    ]
    assert untapped.count("Plains") >= 2 and len(untapped) == 4, untapped

    game.priority_player_index = 0
    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "special_action",
        "permanent_id": angel.permanent_id, "special_action_kind": "turn_face_up",
    })
    assert response.status_code == 200, response.text
    assert not is_face_down(angel) and angel.card.name == "Exalted Angel"
    assert all(p.tapped for p in game.controlled_by(0) if p.has_type("land"))
