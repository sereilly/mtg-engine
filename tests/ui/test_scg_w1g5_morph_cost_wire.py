"""A morph cost that is not mana, through the one action endpoint (CR 702.37e).

Scourge's four: "Morph—Return a Bird you control to its owner's hand"
(Raven Guild Initiate), "Morph—Discard a Zombie card" (Putrid Raptor), "Morph—
Pay 5 life" (Zombie Cutthroat), "Morph—Sacrifice two Mountains" (Skirk
Volcanist). The controller's state lists the ``turn_face_up`` special action
with its printed ``morph_cost`` and what its clauses take — ``pay_life``,
``cost_permanents`` (verb, count and the permanents that may pay, by id) and
``cost_hand_choices`` (the hand cards that may pay, by position). The action
names the payers on the channels an activation's cost already travels on —
``cost_permanent_ids``, ``cost_hand_index`` — and a payer the price does not
take is a 400 with nothing paid. The opponent is offered nothing and sees no
morph cost (CR 708.5).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.face_down import FACE_DOWN_NAME, face_down_card
from engine.models import Permanent
from web.app import app, store

client = TestClient(app)
_CATALOG = {card.name: card for card in load_catalog()}


def _permanent(card, *, face_down=False):
    permanent = Permanent(card=face_down_card(card) if face_down else card)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


@pytest.fixture
def table():
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_human", "host_name": "H", "host_colors": 2,
              "guest_colors": 2, "seed": 3},
    ).json()
    sid = created["session_id"]
    game = store.get(sid).game
    store.get(sid).current_turn = 0
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game.priority_player_index = 0
    p1, p2 = game.players
    p1.hand[:] = []
    p1.battlefield[:] = []
    p2.battlefield[:] = []
    return sid, game


def _state(sid, seat):
    response = client.get(f"/api/sessions/{sid}/state", params={"seat": seat})
    assert response.status_code == 200, response.text
    return response.json()


def _turn_up(sid, permanent, **fields):
    return client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "special_action",
        "permanent_id": permanent.permanent_id,
        "special_action_kind": "turn_face_up", **fields,
    })


def _offer(sid, seat=0):
    return [o for o in _state(sid, seat)["special_actions"] if o["kind"] == "turn_face_up"]


def test_a_return_cost_names_the_bird_it_returns(table, set_pool):
    sid, game = table
    scg = set_pool("SCG")
    initiate = _permanent(scg["Raven Guild Initiate"], face_down=True)
    farseer, liberator = _permanent(scg["Aven Farseer"]), _permanent(scg["Aven Liberator"])
    game.players[0].battlefield[:] = [initiate, farseer, liberator]
    game._sync_control()
    (offer,) = _offer(sid)
    assert offer["morph_cost"] == "Return a Bird you control to its owner's hand"
    assert offer["cost_permanents"]["verb"] == "return"
    assert offer["cost_permanents"]["count"] == 1
    assert {c["permanent_id"] for c in offer["cost_permanents"]["choices"]} == {
        farseer.permanent_id, liberator.permanent_id,
    }
    assert _offer(sid, seat=1) == []

    refused = _turn_up(sid, initiate, cost_permanent_ids=[initiate.permanent_id])
    assert refused.status_code == 400 and initiate.card.name == FACE_DOWN_NAME
    response = _turn_up(sid, initiate, cost_permanent_ids=[farseer.permanent_id])
    assert response.status_code == 200, response.text
    assert initiate.card.name == "Raven Guild Initiate"
    assert [card.name for card in game.players[0].hand] == ["Aven Farseer"]


def test_a_discard_cost_names_the_card_it_discards(table, set_pool):
    sid, game = table
    scg = set_pool("SCG")
    raptor = _permanent(scg["Putrid Raptor"], face_down=True)
    game.players[0].battlefield[:] = [raptor]
    game.players[0].hand[:] = [_CATALOG["Island"], scg["Zombie Cutthroat"]]
    game._sync_control()
    (offer,) = _offer(sid)
    assert offer["cost_hand_choices"] == [{"hand_index": 1, "name": "Zombie Cutthroat"}]
    assert offer["cost_hand_verb"] == "discard"

    assert _turn_up(sid, raptor, cost_hand_index=0).status_code == 400
    assert len(game.players[0].hand) == 2
    assert _turn_up(sid, raptor, cost_hand_index=1).status_code == 200
    assert [card.name for card in game.players[0].graveyard] == ["Zombie Cutthroat"]


def test_a_life_cost_is_shown_and_paid(table, set_pool):
    sid, game = table
    cutthroat = _permanent(set_pool("SCG")["Zombie Cutthroat"], face_down=True)
    game.players[0].battlefield[:] = [cutthroat]
    game._sync_control()
    (offer,) = _offer(sid)
    assert offer["pay_life"] == 5 and offer["morph_cost"] == "Pay 5 life"
    # The opponent's view of the permanent carries no morph cost (CR 708.5).
    theirs = _state(sid, 1)
    assert "Pay 5 life" not in str(theirs["players"][0])
    assert _turn_up(sid, cutthroat).status_code == 200
    assert game.players[0].life == 15


def test_a_counted_sacrifice_takes_exactly_the_mountains_named(table, set_pool):
    sid, game = table
    volcanist = _permanent(set_pool("SCG")["Skirk Volcanist"], face_down=True)
    mountains = [_permanent(_CATALOG["Mountain"]) for _ in range(3)]
    game.players[0].battlefield[:] = [volcanist, *mountains]
    game._sync_control()
    (offer,) = _offer(sid)
    assert offer["cost_permanents"]["count"] == 2
    one = _turn_up(sid, volcanist, cost_permanent_ids=[mountains[0].permanent_id])
    assert one.status_code == 400 and volcanist.card.name == FACE_DOWN_NAME
    two = _turn_up(sid, volcanist, cost_permanent_ids=[
        mountains[0].permanent_id, mountains[2].permanent_id,
    ])
    assert two.status_code == 200, two.text
    assert [p for p in game.players[0].battlefield if p.card.name == "Mountain"] == [mountains[1]]
