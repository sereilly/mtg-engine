"""Complicate's cycle trigger, both seats, through the bodies the client sends
(W2G3).

"When you cycle Complicate, you may counter target spell unless its
controller pays {1}." The trigger's target is a **spell** (``trigger_target``
with a ``stack`` candidate, answered with ``target_stack_index``), the "may"
is ``resolve_optional_pay``, and the spell's controller then owes a
``mana_payment`` (``confirm_mana_payment`` with ``accept``). Driven in the
browser at the W2G3 round with no client change needed: this pins the order
a person meets the three prompts in, at two seats, both ways the last one
can be answered.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from web.app import app, store

client = TestClient(app)


def _act(sid: str, **body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def _state(sid: str, seat: int) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _seeker_on_the_stack(set_pool):
    """Bob (seat 1, active) casts Glory Seeker; Alice holds Complicate and has
    priority with it on the stack."""
    sid = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Alice", "guest_name": "Bob",
        "host_colors": 2, "guest_colors": 2, "seed": 43,
    }).json()["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Bob"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    ons = set_pool("ONS")
    game.players[0].hand[:] = [ons["Complicate"]]
    game.players[1].hand[:] = [ons["Glory Seeker"]]
    for player in game.players:
        player.battlefield[:] = []
    session.current_turn = 1
    game.active_player_index = 1
    game.current_turn_phase = game.current_step = "precombat_main"
    game.priority_player_index = 1
    assert _act(sid, seat=1, action="cast", card_name="Glory Seeker").status_code == 200
    assert _act(sid, seat=1, action="pass_priority").status_code == 200
    return sid, game


@pytest.mark.parametrize("pays", [True, False])
def test_w2g3_complicate_targets_the_spell_and_its_controller_answers(set_pool, pays):
    sid, game = _seeker_on_the_stack(set_pool)
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update({"U": 1, "C": 2})
    game.players[1].mana_pool.update({"C": 1})
    entry = _state(sid, 0)["hand_abilities"][0]
    assert entry["cost_text"] == "Cycling {2}{U}"
    assert _act(sid, seat=0, action="activate_hand", card_name="Complicate",
                hand_index=entry["hand_index"], ability_index=entry["ability_index"]).status_code == 200

    prompt = _state(sid, 0)["trigger_target"]
    (candidate,) = prompt["candidates"]
    assert (candidate["kind"], candidate["name"]) == ("stack", "Bob's Glory Seeker")
    assert "controller_seat" not in prompt, "Alice controls her own trigger"
    assert _act(sid, seat=0, action="trigger_target_confirm",
                target_stack_index=candidate["stack_index"]).status_code == 200

    for seat in (0, 1):
        assert _act(sid, seat=seat, action="pass_priority").status_code == 200
    assert _act(sid, seat=0, action="resolve_optional_pay", card_name="Complicate",
                accept=True).status_code == 200
    owed = _state(sid, 1)["mana_payment"]
    assert (owed["spell_name"], owed["cost"]) == ("Glory Seeker", "{1}")
    assert _state(sid, 0)["mana_payment"] is None, "the spell's controller is asked"
    assert _act(sid, seat=1, action="confirm_mana_payment", accept=pays).status_code == 200

    for _ in range(6):
        if not game.stack:
            break
        seat = game.priority_player_index
        assert _act(sid, seat=seat, action="pass_priority").status_code == 200
    seeker_on_board = any(p.card.name == "Glory Seeker" for p in game.players[1].battlefield)
    assert seeker_on_board is pays
    assert ("Glory Seeker" in [c.name for c in game.players[1].graveyard]) is (not pays)
