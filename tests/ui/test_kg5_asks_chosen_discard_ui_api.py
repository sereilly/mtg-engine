"""CR 616.1e for a card the player chose to discard, through the web layer.

Since round kg5 `asks` a chosen discard's destination is the forced discard's
one CR 616.1 process (``Game.discarded_card_destination``;
``tests/regressions/test_kg5_asks_chosen_discard.py`` is the engine's census).
This is the check that a person is shown the question once they have picked
the card — Dodecapod beside Forbidden Crypt, on an opponent's Mind Rot — held
to it while Mind Rot waits on the stack, and that the answer is where the card
goes; and that Library of Leng is offered on the card an opponent's Coercion
picked, which no discard prompt offered it on.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from web.app import app, store

client = TestClient(app)

_SHIPPED = {card.name: card for card in load_catalog()}


def _session():
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 4245,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    for player in game.players:
        player.battlefield = []
    session.current_turn = 1
    game.active_player_index = 1
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(1)
    return sid, game


def _put(game, seat: int, name: str) -> Permanent:
    permanent = Permanent(card=_SHIPPED[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    game.pending_choices.clear()
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _state(sid: str, seat: int = 0) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _act(sid: str, **body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def _names(cards) -> list[str]:
    return [card.name for card in cards]


def _cast_and_pass(sid: str, game, name: str) -> None:
    game.players[1].hand.append(_SHIPPED[name])
    cast = _act(sid, seat=1, action="cast", card_name=name, target_seat=0)
    assert cast.status_code == 200, cast.text
    for seat in (1, 0):
        passed = _act(sid, seat=seat, action="pass_priority")
        assert passed.status_code == 200, passed.text


@pytest.mark.parametrize("option, on_battlefield, exile", [
    (0, ["Dodecapod"], []),   # its own battlefield
    (1, [], ["Dodecapod"]),   # Forbidden Crypt's exile
])
def test_a_chosen_discard_asks_its_player_and_the_answer_is_where_it_goes(
    option, on_battlefield, exile,
):
    sid, game = _session()
    _put(game, 0, "Forbidden Crypt")
    game.players[0].hand = [_SHIPPED["Dodecapod"]]
    _cast_and_pass(sid, game, "Mind Rot")

    assert _state(sid)["discard_select"] is not None
    picked = _act(sid, seat=0, action="discard_confirm", discard_indices=[0])
    assert picked.status_code == 200, picked.text

    state = _state(sid)
    prompt = state["effect_order"]
    assert prompt is not None, "armed and never rendered"
    assert prompt["player_seat"] == 0 and prompt["event_kind"] == "discard"
    assert len(prompt["options"]) == 2
    assert "Dodecapod" in prompt["options"][0]
    assert "Forbidden Crypt" in prompt["options"][1]
    assert state["waiting_on_prompt"] is True
    # Discarded, and in no zone while its player chooses.
    assert _names(game.players[0].hand) == []
    assert _names(game.players[0].graveyard) == [] and _names(game.players[0].exile) == []
    assert _state(sid, seat=1)["effect_order"] is None
    for seat in (0, 1):
        assert _act(sid, seat=seat, action="pass_priority").status_code == 400

    answered = _act(sid, seat=0, action="effect_order_confirm", option_index=option)
    assert answered.status_code == 200, answered.text
    assert answered.json()["effect_order"] is None
    assert [p.card.name for p in game.players[0].battlefield
            if p.card.name == "Dodecapod"] == on_battlefield
    assert _names(game.players[0].exile) == exile
    assert _names(game.players[0].graveyard) == []
    assert not game.effect_order_answers


@pytest.mark.parametrize("to_library, library_top, graveyard", [
    (True, "Grizzly Bears", []),
    (False, None, ["Grizzly Bears"]),
])
def test_library_of_leng_is_offered_on_the_card_an_opponent_picked(
    to_library, library_top, graveyard,
):
    sid, game = _session()
    _put(game, 0, "Library of Leng")
    game.players[0].hand = [_SHIPPED["Grizzly Bears"]]
    game.players[0].library = [_SHIPPED["Island"]] * 3
    _cast_and_pass(sid, game, "Coercion")

    pick = _state(sid, seat=1)["revealed_hand_pick"]
    assert pick is not None
    picked = _act(sid, seat=1, action="revealed_hand_pick_confirm", hand_index=0)
    assert picked.status_code == 200, picked.text

    offer = _state(sid)["leng_discard"]
    assert offer is not None, "the Library was never offered"
    assert offer["player_seat"] == 0 and offer["card"]["name"] == "Grizzly Bears"
    assert _state(sid, seat=1)["leng_discard"] is None

    answered = _act(sid, seat=0, action="leng_discard_confirm", to_library=to_library)
    assert answered.status_code == 200, answered.text
    assert _names(game.players[0].graveyard) == graveyard
    if library_top is not None:
        assert game.players[0].library[0].name == library_top
    else:
        assert "Grizzly Bears" not in _names(game.players[0].library)
