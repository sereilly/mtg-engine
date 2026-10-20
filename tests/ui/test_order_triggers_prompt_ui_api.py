"""CR 603.3b over the wire: a human seat is shown the triggered abilities it put
on the stack together, the game waits on it, and the order it sends is the
order they resolve in.

The engine half is ``tests/rules/test_603_3b_trigger_order.py``; this is what a
browser sees and sends — the rendered ``order_triggers`` payload, the action
gate's ``waiting_on_prompt`` that keeps the client's auto-pass off, the 400s
for an answer that is not an order, and the stack the next state shows.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.named_counters import counters_on
from tests.helpers import app_js_function_body
from web.app import app, store

client = TestClient(app)
_CARDS = {card.name: card for card in load_catalog()}


def _session_at_human_upkeep(names) -> tuple[str, object]:
    """A human-vs-AI session whose human seat (0) controls *names*, its upkeep
    just begun."""
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_ai", "host_name": "Host", "host_colors": 2,
              "guest_colors": 2, "seed": 6033},
    ).json()
    sid = created["session_id"]
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    game.players[0].battlefield = []
    game.players[1].battlefield = []
    for name in names:
        game._put_permanent_onto_battlefield(0, Permanent(card=_CARDS[name]), None)
    game.stack.clear()
    game.pending_choices.clear()
    game.interactive_seats = {0}
    session.current_turn = 0
    game.active_player_index = 0
    game.turn += 1
    game.begin_turn_bookkeeping(0)
    game.resolve_upkeep(0, defer_priority=True)
    return sid, game


def _state(sid, seat=0) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _act(sid, **body):
    return client.post(f"/api/sessions/{sid}/action", json={"seat": 0, **body})


def test_r4_the_order_is_rendered_and_the_game_waits_on_it():
    sid, game = _session_at_human_upkeep(["Tangle Wire"] + ["Forest"] * 4)
    state = _state(sid)

    prompt = state["order_triggers"]
    assert prompt["player_seat"] == 0
    assert [t["index"] for t in prompt["triggers"]] == [0, 1]
    assert [t["text"][:28] for t in prompt["triggers"]] == [
        "At the beginning of each pla", "At the beginning of your upk",
    ], "top first: the tap resolves first unless the seat moves it"
    assert all(t["card"]["name"] == "Tangle Wire" for t in prompt["triggers"])
    assert state["waiting_on_prompt"] is True
    assert len(state["stack"]) == 2

    # Nothing else may be done while the order is owed; the other seat
    # does not see the prompt at all.
    assert _act(sid, action="pass_priority").status_code == 400
    assert _state(sid, seat=1)["order_triggers"] is None


@pytest.mark.parametrize(
    "bad", [[0], [0, 0], [1, 2], None], ids=["short", "repeat", "range", "absent"],
)
def test_r4_an_answer_that_is_not_an_order_is_refused(bad):
    sid, _game = _session_at_human_upkeep(["Tangle Wire"])
    response = _act(sid, action="order_triggers_confirm", trigger_order=bad)
    assert response.status_code == 400
    assert _state(sid)["order_triggers"] is not None


@pytest.mark.parametrize(
    "order, tapped", [([0, 1], 4), ([1, 0], 3)], ids=["tap-first", "fade-first"],
)
def test_r4_the_order_sent_is_the_order_they_resolve_in(order, tapped):
    """Tangle Wire on its controller's upkeep: fade first leaves three counters
    for the tap to count; tap first counts four."""
    sid, game = _session_at_human_upkeep(["Tangle Wire"] + ["Forest"] * 5)
    texts = [t["text"] for t in _state(sid)["order_triggers"]["triggers"]]

    assert _act(sid, action="order_triggers_confirm", trigger_order=order).status_code == 200

    state = _state(sid)
    assert state["order_triggers"] is None
    assert state["waiting_on_prompt"] is False
    assert [item["ability_text"] for item in state["stack"]] == [texts[i] for i in order]
    assert any("ordered their triggered abilities (603.3b)" in line for line in state["log"])

    # Pass the step's priority until both have resolved; the tap's own choice
    # (which permanents) is the human's, taken here by its default.
    for _ in range(6):
        if not game.stack and not game.pending_choices:
            break
        if game.pending_choices:
            game.auto_resolve_pending_choices()
        else:
            _act(sid, action="pass_priority")
    wire = next(p for p in game.controlled_by(0) if p.card.name == "Tangle Wire")
    assert counters_on(wire, "fade") == 3
    assert sum(p.tapped for p in game.controlled_by(0)) == tapped


def test_r4_the_client_reads_the_prompt_and_sends_the_order():
    """The getter reads ``state.order_triggers``, the panel is in the prompt
    cascade, the answer carries ``trigger_order``, and the priority prompt
    stands aside while it is open."""
    getter = app_js_function_body("getOrderTriggersInfo")
    assert "state.order_triggers" in getter
    panel = app_js_function_body("applyOrderTriggersPrompt")
    assert 'action: "order_triggers_confirm"' in panel
    assert "trigger_order" in panel
    assert "applyOrderTriggersPrompt(orderTriggersInfo)" in app_js_function_body(
        "renderActivationPrompt"
    )
    assert "getOrderTriggersInfo(state)" in app_js_function_body("shouldShowPriorityPrompt")
