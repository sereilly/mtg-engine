"""A CR 116.2d offer priced in graveyard cards reaches the server whole.

"Its controller may exile three cards from their graveyard for that player to
ignore this effect until end of turn." (Lost in Thought.) The offer is
Volrath's Curse's at a second price (``engine/special_actions.py``), and the
wire carries two things the Curse never needed: the state entry says how many
cards the price takes (``exile_from_graveyard``), so a client can ask which
ones, and the action names them by graveyard slot on the channel an activated
ability's graveyard price already uses (``cost_graveyard_indices``).

Judgment is a measured set, so no deck in the running app holds the card: the
session is real and the permanents are put on its board by hand, as the
Licid's wire test does with a shipped one. The client half — a button for this
kind and a picker for the three cards — is the wave-2 client group's;
``web/static`` has no label for ``ignore_attached_static_until_eot`` yet, so
today it drops the button (Volrath's Curse's as well).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from engine.aura_attachment import attach_aura
from engine.card_loader import load_cards, manifest_set_path
from engine.models import Permanent
from web.app import app, store
from web.runtime import CARD_BY_NAME

client = TestClient(app)

_JUD = {card.name: card for card in load_cards(manifest_set_path("JUD", include_measured=True))}


def _lost_in_thought_on_the_humans_creature():
    """Seat 1's Lost in Thought on seat 0's Grizzly Bears; seat 0 holds four
    cards in its graveyard and has priority."""
    created = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "H",
        "host_colors": 2, "guest_colors": 2, "seed": 5,
    }).json()
    sid = created["session_id"]
    game = store.get(sid).game
    game.active_player_index = 0
    game.priority_player_index = 0

    bear = Permanent(card=CARD_BY_NAME["grizzly bears"])
    aura = Permanent(card=_JUD["Lost in Thought"])
    game._put_permanent_onto_battlefield(0, bear, None)
    bear.metadata["summoning_sickness_turn"] = -99  # only the Aura holds it back
    game._put_permanent_onto_battlefield(1, aura, None)
    attach_aura(aura, bear)
    game._refresh_dynamic_creatures()
    game.players[0].graveyard[:] = [
        CARD_BY_NAME["forest"], CARD_BY_NAME["island"],
        CARD_BY_NAME["swamp"], CARD_BY_NAME["mountain"],
    ]
    return sid, game, aura, bear


def _offer(sid):
    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    return [
        entry for entry in state["special_actions"]
        if entry["kind"] == "ignore_attached_static_until_eot"
    ]


def test_the_state_says_how_many_graveyard_cards_the_offer_takes():
    sid, _game, aura, _bear = _lost_in_thought_on_the_humans_creature()

    assert _offer(sid) == [{
        "permanent_id": aura.permanent_id, "name": "Lost in Thought",
        "kind": "ignore_attached_static_until_eot", "exile_from_graveyard": 3,
    }]


def test_the_named_graveyard_cards_are_the_ones_exiled():
    sid, game, aura, bear = _lost_in_thought_on_the_humans_creature()

    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "special_action",
        "permanent_id": aura.permanent_id,
        "special_action_kind": "ignore_attached_static_until_eot",
        "cost_graveyard_indices": [0, 2, 3],
    })

    assert response.status_code == 200, response.text
    assert [card.name for card in game.players[0].graveyard] == ["Island"]
    assert sorted(card.name for card in game.players[0].exile) == [
        "Forest", "Mountain", "Swamp",
    ]
    assert game.can_attack(bear, 1)
    assert _offer(sid) == [], "one turn's relief, bought once"


def test_a_wrong_count_is_refused_and_nothing_moves():
    sid, game, aura, bear = _lost_in_thought_on_the_humans_creature()

    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "special_action",
        "permanent_id": aura.permanent_id,
        "special_action_kind": "ignore_attached_static_until_eot",
        "cost_graveyard_indices": [0, 1],
    })

    assert response.status_code == 400
    assert len(game.players[0].graveyard) == 4 and game.players[0].exile == []
    assert not game.can_attack(bear, 1)
