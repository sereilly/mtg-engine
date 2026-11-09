"""Mindslaver (CR 723) through the web layer, both directions.

A person controlling the AI seat's turn plays it — every action sent as the
controlled seat with ``controller_seat`` naming the sender, the seat's
prompts shown to them and its hand visible to them (CR 723.4) — and the AI
does not act for that seat. An AI controlling a person's turn plays it from
the person's ``ai_step`` (nothing optional, ``engine/ai_player_control.py``),
and the person may do nothing but concede (CR 723.6). The rulings
(2024-04-12): "You can't make the affected player concede. That player may
choose to concede at any time, even while you're controlling that player."
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import resolve_stack
from web.app import app, store
from web.turn_steps import _end_turn

client = TestClient(app)

_SHIPPED = {card.name: card for card in load_catalog()}


def _session(active: int):
    created = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "Host", "guest_name": "AI",
        "host_colors": 2, "guest_colors": 2, "seed": 4244, "enable_pregame": False,
    }).json()
    sid = created["session_id"]
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    for player in game.players:
        player.battlefield = []
    session.current_turn = active
    game.active_player_index = active
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.pending_choices.clear()
    game.start_priority_window(active)
    return sid, session, game


def _put(game, seat: int, card) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _state(sid: str, seat: int) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _act(sid: str, **body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def _the_person_controls_the_ai(set_pool):
    """The person activates Mindslaver at the AI and ends the turn: the AI
    seat's turn begins under the person's control."""
    sid, session, game = _session(0)
    slaver = _put(game, 0, set_pool("MRD")["Mindslaver"])
    game.players[1].hand = [_SHIPPED["Grizzly Bears"], _SHIPPED["Forest"]]
    activated = _act(
        sid, seat=0, action="activate",
        permanent_index=game.players[0].battlefield.index(slaver), target_seat=1,
    )
    assert activated.status_code == 200, activated.json()
    assert _act(sid, seat=0, action="pass_priority").status_code == 200
    assert _state(sid, 0)["player_controls_waiting"] == {"1": 0}
    assert _act(sid, seat=0, action="end_turn").status_code == 200
    return sid, session, game


def test_a_person_controlling_the_ai_seat_is_its_decider(set_pool):
    sid, _session_, game = _the_person_controls_the_ai(set_pool)
    state = _state(sid, 0)
    assert state["current_turn"] == 1
    assert state["player_controls"] == {"1": 0}
    assert state["decider_types"] == {"0": "human", "1": "human"}
    assert state["act_as"] == 1
    # CR 723.4: the controller sees the controlled player's hand.
    names = [card["name"] for card in state["players"][1]["hand"]]
    assert "Grizzly Bears" in names
    # The AI does not play a turn a person decides.
    refused = _act(sid, seat=0, action="ai_step")
    assert refused.status_code == 400
    # A request for the AI seat that does not come from its controller.
    impostor = _act(sid, seat=1, action="next_phase")
    assert impostor.status_code == 400
    assert "controls you this turn" in impostor.json()["detail"]
    # CR 723.6: the controller can't make the controlled player concede.
    conceded = _act(sid, seat=1, controller_seat=0, action="concede")
    assert conceded.status_code == 400
    assert not game.players[1].lost
    # The person plays the AI seat's land drop, as the AI seat.
    played = _act(sid, seat=1, controller_seat=0, action="cast", card_name="Forest")
    assert played.status_code == 200, played.json()
    assert "Forest" in [p.card.name for p in game.players[1].battlefield]
    assert [card.name for card in game.players[1].hand].count("Grizzly Bears") == 1


def test_the_controlled_ai_seats_prompt_is_the_persons_to_answer(set_pool):
    sid, _session_, game = _the_person_controls_the_ai(set_pool)
    scepter = _put(game, 1, _SHIPPED["Disrupting Scepter"])
    activated = _act(
        sid, seat=1, controller_seat=0, action="activate",
        permanent_index=game.players[1].battlefield.index(scepter), target_seat=1,
    )
    assert activated.status_code == 200, activated.json()
    resolve = _act(sid, seat=1, controller_seat=0, action="pass_priority")
    assert resolve.status_code == 200, resolve.json()
    if game.stack:
        assert _act(sid, seat=0, action="pass_priority").status_code == 200
    # The discard is the controlled seat's decision: shown to the person
    # looking through that seat, and not answered by the AI.
    state = _state(sid, 1)
    assert state["discard_select"] is not None
    assert state["act_as"] == 1
    held = len(game.players[1].hand)
    answered = _act(
        sid, seat=1, controller_seat=0, action="discard_confirm", discard_indices=[0],
    )
    assert answered.status_code == 200, answered.json()
    assert len(game.players[1].hand) == held - 1


def _the_ai_controls_the_person(set_pool):
    sid, session, game = _session(1)
    _put(game, 1, set_pool("MRD")["Mindslaver"])
    for _ in range(3):
        _put(game, 0, _SHIPPED["Forest"])
    _put(game, 0, _SHIPPED["Grizzly Bears"])
    game.players[0].hand = [
        _SHIPPED["Grizzly Bears"], _SHIPPED["Forest"], _SHIPPED["Lightning Bolt"],
    ]
    result = game.activate_permanent_ability(1, "Mindslaver", target_player_index=0)
    assert result.supported, result.details
    resolve_stack(game)
    _end_turn(session)
    return sid, session, game


def test_an_ai_controlling_the_persons_turn_plays_it_for_them(set_pool):
    sid, _session_, game = _the_ai_controls_the_person(set_pool)
    state = _state(sid, 0)
    assert state["current_turn"] == 0
    assert state["player_controls"] == {"0": 1}
    assert state["decider_types"]["0"] == "ai"
    # The person is asked nothing and may play nothing.
    refused = _act(sid, seat=0, action="cast", card_name="Forest")
    assert refused.status_code == 400
    assert "you may only concede" in refused.json()["detail"]
    lands_before = sum(p.card.name == "Forest" for p in game.players[0].battlefield)
    for _ in range(40):
        if _state(sid, 0)["current_turn"] != 0:
            break
        stepped = _act(sid, seat=0, action="ai_step")
        assert stepped.status_code == 200, stepped.json()
    state = _state(sid, 0)
    assert state["current_turn"] == 1
    assert state["player_controls"] == {}
    # The AI deciding for the person played nothing optional for them.
    assert sum(p.card.name == "Forest" for p in game.players[0].battlefield) == lands_before
    assert "Host declared 0 attacker(s)" in game.log


def test_a_controlled_person_may_still_concede(set_pool):
    sid, _session_, game = _the_ai_controls_the_person(set_pool)
    conceded = _act(sid, seat=0, action="concede")
    assert conceded.status_code == 200, conceded.json()
    assert game.players[0].lost
