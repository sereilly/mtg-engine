"""An X in a morph cost through the one action endpoint (CR 107.3d, 702.37f).

Legions' "Morph {X}{X}{R}" (Warbreak Trumpeter): the controller's state lists
the ``turn_face_up`` special action with its printed ``morph_cost``, how many
``{X}`` it prints (``x_symbols``) and the largest X the seat could pay now
(``max_x``); ``{"action": "special_action", "special_action_kind":
"turn_face_up", "x_value": N, …}`` pays X generic per symbol on the server and
the face-up trigger reads that X. An X the lands cannot pay is a 400 with
nothing tapped. The client half (an X box bounded by ``max_x``) is the
wave-2 client group's.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.face_down import FACE_DOWN_NAME, face_down_card
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
    p1.hand[:] = []
    trumpeter = Permanent(card=face_down_card(set_pool("LGN")["Warbreak Trumpeter"]))
    trumpeter.metadata["summoning_sickness_turn"] = -99
    p1.battlefield[:] = [trumpeter]
    for _ in range(5):
        mountain = Permanent(card=_CATALOG["Mountain"])
        mountain.metadata["summoning_sickness_turn"] = -99
        p1.battlefield.append(mountain)
    p2.battlefield[:] = []
    game._sync_control()
    return sid, game, trumpeter


def _state(sid, seat):
    response = client.get(f"/api/sessions/{sid}/state", params={"seat": seat})
    assert response.status_code == 200, response.text
    return response.json()


def test_the_offer_carries_its_x(table):
    sid, _game, trumpeter = table
    offers = [o for o in _state(sid, 0)["special_actions"] if o["kind"] == "turn_face_up"]
    assert offers == [{
        "permanent_id": trumpeter.permanent_id, "name": FACE_DOWN_NAME,
        "kind": "turn_face_up", "morph_cost": "{X}{X}{R}",
        "x_symbols": 2, "max_x": 2,
    }]


def test_x_value_is_paid_and_read_by_the_trigger(table):
    sid, game, trumpeter = table
    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "special_action",
        "permanent_id": trumpeter.permanent_id,
        "special_action_kind": "turn_face_up", "x_value": 2,
    })
    assert response.status_code == 200, response.text
    assert trumpeter.card.name == "Warbreak Trumpeter"
    assert sum(p.tapped for p in game.players[0].battlefield if p.has_type("land")) == 5
    _resolve_top_stack(sid, 0)
    goblins = [p for p in game.players[0].battlefield if p.card.name == "Goblin Token"]
    assert len(goblins) == 2, game.log[-6:]


def test_an_unpayable_x_is_refused(table):
    sid, game, trumpeter = table
    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "special_action",
        "permanent_id": trumpeter.permanent_id,
        "special_action_kind": "turn_face_up", "x_value": 3,
    })
    assert response.status_code == 400
    assert trumpeter.card.name == FACE_DOWN_NAME
    assert not any(p.tapped for p in game.players[0].battlefield)
