"""CR 616.1e for a dying permanent, through the web layer.

A permanent dying is one event with three spellings in the replacement
registry (``would_die``, ``would_leave_battlefield``, ``put_into_graveyard``),
and since round kg4 `asks` its controller chooses among every effect of all
three (``tests/regressions/test_kg4_asks_contended_moves.py`` is the engine's
census). This is the check that a person is in fact shown the question for
CR 616.1f's own example — Forbidden Crypt beside Gravebane Zombie — held to
it while the destroy spell waits on the stack, and that the answer is what
happens to the card.
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
        "host_colors": 2, "guest_colors": 2, "seed": 4244,
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


@pytest.mark.parametrize("option, library, exile", [
    (0, ["Gravebane Zombie"], []),   # its own "top of its owner's library"
    (1, [], ["Gravebane Zombie"]),   # Forbidden Crypt's exile
])
def test_a_destroyed_creature_asks_its_controller_and_the_answer_is_where_it_goes(
    option, library, exile,
):
    sid, game = _session()
    _put(game, 0, "Forbidden Crypt")
    zombie = _put(game, 0, "Gravebane Zombie")
    game.players[0].library = []
    game.players[1].hand.append(_SHIPPED["Lightning Bolt"])
    cast = _act(
        sid, seat=1, action="cast", card_name="Lightning Bolt", target_seat=0,
        target_permanent_id=zombie.permanent_id,
    )
    assert cast.status_code == 200, cast.text
    for seat in (1, 0):
        passed = _act(sid, seat=seat, action="pass_priority")
        assert passed.status_code == 200, passed.text

    state = _state(sid)
    prompt = state["effect_order"]
    assert prompt is not None, "armed and never rendered"
    assert prompt["player_seat"] == 0 and prompt["event_kind"] == "would_die"
    assert len(prompt["options"]) == 2
    assert "Gravebane Zombie" in prompt["options"][0]
    assert "Forbidden Crypt" in prompt["options"][1]
    assert state["waiting_on_prompt"] is True
    # The Zombie has left the battlefield and is in no zone while its
    # controller chooses (CR 614.6: nothing in the set leaves it there).
    assert not game.is_on_battlefield(zombie)
    assert _names(game.players[0].graveyard) == []
    assert _names(game.players[0].library) == [] and _names(game.players[0].exile) == []
    # The other seat is shown nothing of its own and cannot act around it.
    assert _state(sid, seat=1)["effect_order"] is None
    for seat in (0, 1):
        assert _act(sid, seat=seat, action="pass_priority").status_code == 400
    assert _act(
        sid, seat=1, action="effect_order_confirm", option_index=option,
    ).status_code == 400

    answered = _act(sid, seat=0, action="effect_order_confirm", option_index=option)
    assert answered.status_code == 200, answered.text
    assert answered.json()["effect_order"] is None
    assert _names(game.players[0].library) == library
    assert _names(game.players[0].exile) == exile
    assert _names(game.players[0].graveyard) == []
    assert not game.effect_order_answers
