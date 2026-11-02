"""The controller names which opponent chooses, over the wire (CR 700.2e,
601.7a): a four-seat free-for-all, every seat a person. Fatal Lore cast by
seat 0 serves seat 0 a ``player_choice`` prompt offering the three
opponents; ``player_choice_confirm`` naming seat 2 hands the mode prompt to
seat 2 alone, and the spell waits on the stack until it is answered.

The engine half is ``tests/regressions/test_kg3_choosers_opponent_picks.py``;
this is the payload each seat is served and the answer a client sends, with
no client change: the naming reuses the ``player_choice`` prompt Backdraft
and Wormfang Crab already render.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import _mk_creature_card
from web.app import app, store

client = TestClient(app)


@pytest.fixture(scope="module")
def by_name():
    return {card.name: card for card in load_catalog()}


def _table(by_name):
    created = client.post("/api/sessions", json={
        "mode": "free_for_all", "seed": 11,
        "seats": [{"name": f"P{i}", "is_ai": False} for i in range(4)],
    }).json()
    sid = created["session_id"]
    session = store.get(sid)
    session.pregame_phase = None
    game = session.game
    game.enforce_mana_costs = False
    for player in game.players:
        player.hand.clear()
    game.remove_all_from_battlefield(list(game.all_permanents()))
    game.stack.clear()
    game.pending_choices.clear()
    for seat in range(4):
        game._put_permanent_onto_battlefield(
            seat, Permanent(card=_mk_creature_card(f"Bear{seat}", 2, 2)), None
        )
    game.players[0].hand = [by_name["Fatal Lore"]]
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, game


def _state(sid, seat):
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def test_the_caster_is_served_the_naming_and_the_named_seat_the_mode(by_name):
    sid, game = _table(by_name)
    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "cast", "card_name": "Fatal Lore",
    })
    assert response.status_code == 200, response.text
    naming = _state(sid, 0).get("player_choice")
    assert naming, _state(sid, 0).get("waiting_on_prompt")
    assert [option["seat"] for option in naming["options"]] == [1, 2, 3]
    assert [c.kind for c in game.pending_choices] == ["player_choice"]
    assert [item.card.name for item in game.stack] == ["Fatal Lore"]

    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "player_choice_confirm", "chosen_seat": 2,
    })
    assert response.status_code == 200, response.text
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("opponent_mode_choice", 2)
    ]
    assert _state(sid, 2).get("opponent_mode_choice")
    assert not _state(sid, 1).get("opponent_mode_choice")
    # The spell is still being announced: nothing has resolved it.
    assert [item.card.name for item in game.stack] == ["Fatal Lore"]
