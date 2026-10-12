"""CR 616.1e over a bought-back spell, through the web layer.

A spell whose buyback was paid resolves under a "would be put into your
graveyard … exile it instead" effect: two replacement effects over one move,
and the spell's controller chooses (``tests/rules/
test_buyback_against_exile_instead.py`` is the engine's census; Yawgmoth's
Will's ruling is the sentence). The engine arms the ``effect_order`` prompt
every contended event uses — which is the whole reason this needed no client
change — and this file is the check that a person is in fact shown it, held to
it and able to answer it, with the card in exactly one place at each step.
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
    """Seat 0 in its main phase with Forbidden Crypt out and Capsize in hand;
    seat 1 has a Sol Ring to bounce."""
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 4242,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    game.players[0].battlefield, game.players[1].battlefield = [], []
    game._put_permanent_onto_battlefield(
        0, Permanent(card=_SHIPPED["Forbidden Crypt"]), None
    )
    ring = Permanent(card=_SHIPPED["Sol Ring"])
    game._put_permanent_onto_battlefield(1, ring, None)
    game.players[0].hand = [_SHIPPED["Capsize"]]
    game.players[0].graveyard, game.players[0].exile = [], []
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, game


def _state(sid: str, seat: int = 0) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _act(sid: str, **body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def _names(cards) -> list[str]:
    return [card.name for card in cards]


def _cast_and_let_it_resolve(sid: str, game) -> dict:
    cast = _act(
        sid, seat=0, action="cast", card_name="Capsize", target_seat=1,
        target_permanent_index=0, optional_cost_payments={"{3}": 1},
    )
    assert cast.status_code == 200, cast.text
    for seat in (0, 1):
        passed = _act(sid, seat=seat, action="pass_priority")
        assert passed.status_code == 200, passed.text
    return _state(sid)


@pytest.mark.parametrize("option, hand, exile", [
    (0, ["Capsize"], []),      # the buyback
    (1, [], ["Capsize"]),      # Forbidden Crypt's exile
])
def test_the_spells_controller_is_asked_and_the_answer_is_what_happens(
    option, hand, exile,
):
    sid, game = _session()
    state = _cast_and_let_it_resolve(sid, game)

    prompt = state["effect_order"]
    assert prompt is not None, "armed and never rendered"
    assert prompt["player_seat"] == 0
    assert prompt["event_kind"] == "bought_back_spell"
    assert len(prompt["options"]) == 2
    assert prompt["options"][0].startswith("Buyback")
    assert "Capsize" in prompt["options"][1]
    # The spell did what it does; only its last step is waiting (CR 608.2n).
    assert _names(game.players[1].hand).count("Sol Ring") == 1
    assert _names(game.players[0].hand) == [] and _names(game.players[0].exile) == []
    assert [item["label"] for item in state["stack"]] == ["Capsize"]
    assert state["stack"][0]["resolution_held"] is True
    assert state["waiting_on_prompt"] is True
    # The other seat sees no prompt of its own and cannot act around this one.
    assert _state(sid, seat=1)["effect_order"] is None
    for seat in (0, 1):
        assert _act(sid, seat=seat, action="pass_priority").status_code == 400

    # Not the opponent's to answer.
    assert _act(
        sid, seat=1, action="effect_order_confirm", option_index=option,
    ).status_code == 400
    answered = _act(sid, seat=0, action="effect_order_confirm", option_index=option)
    assert answered.status_code == 200, answered.text
    assert _names(game.players[0].hand) == hand
    assert _names(game.players[0].exile) == exile
    assert _names(game.players[0].graveyard) == []
    after = answered.json()
    assert after["effect_order"] is None and after["stack"] == []


def test_with_no_competing_effect_nobody_is_asked():
    sid, game = _session()
    crypt = next(p for p in game.controlled_by(0) if p.card.name == "Forbidden Crypt")
    game.remove_from_battlefield(crypt)
    state = _cast_and_let_it_resolve(sid, game)
    assert state["effect_order"] is None
    assert _names(game.players[0].hand) == ["Capsize"]
    assert state["stack"] == []
