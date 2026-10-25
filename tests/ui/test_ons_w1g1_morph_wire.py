"""Morph through the one action endpoint: what a client sends and sees.

The wire half of CR 702.37 (``engine/face_down.py``), for the wave-2 client to
build on: the hand card's cast-cost offer names the face-down cast and its
{3}; ``{"action": "cast", "alternative_cost": true}`` casts it face down; the
controller's state carries ``hidden_card`` and a ``turn_face_up`` special
action with its ``morph_cost``; ``{"action": "special_action",
"special_action_kind": "turn_face_up", "permanent_id": …}`` turns it up,
tapping lands for the morph cost on the server; the opponent's state shows a
2/2 called "Face-down creature" until then.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.face_down import FACE_DOWN_NAME
from engine.models import Permanent
from tests.helpers import _resolve_top_stack
from web.app import app, store

client = TestClient(app)
_CATALOG = {card.name: card for card in load_catalog()}


@pytest.fixture
def table(set_pool):
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_human", "host_name": "H", "host_colors": 2,
              "guest_colors": 2, "seed": 3},
    ).json()
    sid = created["session_id"]
    session = store.get(sid)
    game = session.game
    session.current_turn = 0
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game.priority_player_index = 0
    p1, p2 = game.players
    p1.hand[:] = [set_pool("ONS")["Whipcorder"]]
    p1.battlefield[:] = []
    for _ in range(4):
        plains = Permanent(card=_CATALOG["Plains"])
        plains.metadata["summoning_sickness_turn"] = -99
        p1.battlefield.append(plains)
    p2.battlefield[:] = []
    game._sync_control()
    return sid, game


def _state(sid, seat):
    response = client.get(f"/api/sessions/{sid}/state", params={"seat": seat})
    assert response.status_code == 200, response.text
    return response.json()


def test_the_morph_card_offers_its_face_down_cast(table):
    """The offer the ``card_target_spec`` route serves as ``cost_offers``
    (``Game.cast_cost_offers``): the face-down cast, named as one, payable
    from the four Plains. Asked of the engine here because the route looks
    the card up in the shipped catalog, which a measured set is not in."""
    _sid, game = table
    (offer,) = [
        offer for offer in game.cast_cost_offers(
            0, game.players[0].hand[0], spell_hand_index=0,
        )
        if offer["kind"] == "alternative"
    ]
    assert offer["label"] == "cast it face down as a 2/2 creature for {3}"
    assert offer["payable"] is True


def test_cast_face_down_then_turn_face_up_through_the_route(table):
    sid, game = table
    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "cast", "card_name": "Whipcorder",
        "alternative_cost": True, "auto_tap": True,
    })
    assert response.status_code == 200, response.text
    _resolve_top_stack(sid, 0)
    assert not game.stack, game.log[-6:]
    (face_down,) = [p for p in game.players[0].battlefield if p.is_creature]
    assert sum(p.tapped for p in game.players[0].battlefield) == 3, "{3} paid"

    theirs = _state(sid, 1)["players"][0]["battlefield"]
    (seen,) = [p for p in theirs if p["face_down"]]
    assert seen["name"] == FACE_DOWN_NAME and "hidden_card" not in seen
    assert "Whipcorder" not in str(_state(sid, 1))

    mine = _state(sid, 0)
    (own,) = [p for p in mine["players"][0]["battlefield"] if p["face_down"]]
    assert own["hidden_card"]["name"] == "Whipcorder"
    game.priority_player_index = 0
    mine = _state(sid, 0)
    offers = [o for o in mine["special_actions"] if o["kind"] == "turn_face_up"]
    assert offers == [{
        "permanent_id": face_down.permanent_id, "name": FACE_DOWN_NAME,
        "kind": "turn_face_up", "morph_cost": "{W}",
    }]

    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "special_action",
        "permanent_id": face_down.permanent_id,
        "special_action_kind": "turn_face_up",
    })
    assert response.status_code == 200, response.text
    assert face_down.card.name == "Whipcorder"
    assert sum(p.tapped for p in game.players[0].battlefield if p.has_type("land")) == 4
    theirs = _state(sid, 1)["players"][0]["battlefield"]
    (seen,) = [p for p in theirs if p["id"] == face_down.permanent_id]
    assert seen["name"] == "Whipcorder" and seen["face_down"] is False


def test_the_opponent_cannot_turn_it_up(table):
    sid, game = table
    game.enforce_mana_costs = False
    assert game.queue_from_hand(0, "Whipcorder", alternative_cost=True).supported
    game.resolve_top_of_stack()
    (face_down,) = [p for p in game.players[0].battlefield if p.is_creature]
    game.priority_player_index = 1
    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 1, "action": "special_action",
        "permanent_id": face_down.permanent_id,
        "special_action_kind": "turn_face_up",
    })
    assert response.status_code == 400
    assert face_down.card.name == FACE_DOWN_NAME
