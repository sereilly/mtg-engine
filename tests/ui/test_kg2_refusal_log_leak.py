"""A refused cast or activation tells the actor why and the table nothing.

``game.log`` is one list served whole to every seat. Every refusal site wrote
its reason into it, so the opponent's ``/state`` read "insufficient mana for
Exalted Angel" about a card in the actor's hand — on every drag-cast from an
empty pool, because the client sends the cast first and offers Auto-Tap on the
refusal — and a person who confirmed the printed cost, was refused and then
cast the card face down had named the face-down card (Onslaught's Phase 5,
``scratch/ons/p5/repro/refusal_log_leak.py``). CR 733.1: the illegal action is
reversed; CR 733.2: the actor keeps priority and may redo it. So the reason
travels in the response to the actor's own request — the HTTP 400 ``detail``
the client already shows — and nowhere else (``engine/refusals.py``).
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.face_down import FACE_DOWN_NAME
from engine.models import Permanent
from web.app import app, store

client = TestClient(app)
_CATALOG = {card.name: card for card in load_catalog()}


def _table(hand, lands=0):
    """A two-person table, seat 0 in its precombat main phase with priority,
    holding *hand* over *lands* untapped Plains and an empty pool."""
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "H", "host_colors": 2,
        "guest_colors": 2, "seed": 3,
    }).json()
    sid = created["session_id"]
    session = store.get(sid)
    game = session.game
    session.pregame_phase = None
    session.current_turn = 0
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    seat, other = game.players
    seat.hand[:] = [_CATALOG[name] for name in hand]
    seat.battlefield[:] = []
    for _ in range(lands):
        plains = Permanent(card=_CATALOG["Plains"])
        plains.metadata["summoning_sickness_turn"] = -99
        seat.battlefield.append(plains)
    other.battlefield[:] = []
    seat.mana_pool = {key: 0 for key in seat.mana_pool}
    game._sync_control()
    game.start_priority_window(0)
    return sid, game


def _state(sid, seat):
    response = client.get(f"/api/sessions/{sid}/state", params={"seat": seat})
    assert response.status_code == 200, response.text
    return response.json()


def _act(sid, **body):
    return client.post(f"/api/sessions/{sid}/action", json={"seat": 0, **body})


def _named(payload, names):
    text = json.dumps(payload)
    return [name for name in names if name in text]


def test_a_refused_cast_and_a_refused_hand_activation_name_nothing_to_the_table():
    sid, game = _table(["Exalted Angel", "Akroma's Blessing"])
    log_before = list(game.log)

    cast = _act(sid, action="cast", card_name="Exalted Angel")
    entry = next(
        e for e in _state(sid, 0)["hand_abilities"]
        if e["name"] == "Akroma's Blessing"
    )
    cycle = _act(
        sid, action="activate_hand", card_name="Akroma's Blessing",
        hand_index=entry["hand_index"], ability_index=entry["ability_index"],
    )

    # The actor is answered, in its own response, with the reason unchanged.
    assert cast.status_code == 400
    assert cast.json()["detail"] == "insufficient mana for Exalted Angel"
    assert cycle.status_code == 400
    assert cycle.json()["detail"] == "H cannot pay for Akroma's Blessing's ability"
    # Nothing was played: both cards are still in the hand and priority stayed.
    assert [c.name for c in game.players[0].hand] == [
        "Exalted Angel", "Akroma's Blessing",
    ]
    assert game.priority_player_index == 0
    # And the table was told nothing — not the opponent, not a spectator.
    assert game.log == log_before
    for viewer in (1, None):
        payload = (
            _state(sid, viewer) if viewer is not None
            else client.get(f"/api/sessions/{sid}/state").json()
        )
        assert _named(payload, ("Exalted Angel", "Akroma")) == [], payload["log"]


def test_a_face_down_cast_after_a_refused_printed_cost_never_names_the_card():
    """The smoke games' sequence: the printed cost confirmed with an empty
    pool and refused, then the card cast face down (CR 702.37c) through the
    Auto-Tap. Only the controller may know what the 2/2 is (CR 708.5)."""
    sid, game = _table(["Exalted Angel"], lands=4)

    refused = _act(sid, action="cast", card_name="Exalted Angel")
    assert refused.status_code == 400
    assert refused.json()["detail"] == "insufficient mana for Exalted Angel"

    cast = _act(
        sid, action="cast", card_name="Exalted Angel",
        alternative_cost=True, auto_tap=True,
    )
    assert cast.status_code == 200, cast.text
    (item,) = game.stack
    assert item.card.name == FACE_DOWN_NAME

    theirs = _state(sid, 1)
    assert _named(theirs, ("Exalted Angel", "{2}{W}{W}")) == [], theirs["log"]
    assert not any("Exalted Angel" in line for line in game.log), game.log
    # The controller does see it (the other half, and proof there was
    # something to hide).
    assert "Exalted Angel" in json.dumps(_state(sid, 0))


def test_a_refused_permanent_activation_is_answered_the_same_way():
    """A permanent's ability refused for want of mana is about a public
    object, and is answered the same way all the same: CR 733.1 leaves no
    event to announce either way, and one rule for every refusal is the rule
    that stays right when the object is face down."""
    sid, game = _table([])
    dragon = Permanent(card=_CATALOG["Shivan Dragon"])
    dragon.metadata["summoning_sickness_turn"] = -99
    game.players[0].battlefield.append(dragon)
    game._sync_control()
    log_before = list(game.log)

    response = _act(
        sid, action="activate", permanent_name="Shivan Dragon",
        permanent_id=dragon.permanent_id,
    )

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "insufficient mana to activate Shivan Dragon"
    assert game.log == log_before
