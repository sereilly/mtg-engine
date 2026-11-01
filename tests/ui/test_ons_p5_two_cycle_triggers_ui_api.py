"""Two triggers from one cycle, one of them targeted, under a human seat: the
target and the order are both owed at once, and each must be answerable.

Found in Onslaught's post-promotion smoke game (turn 12): Astral Slide on the
battlefield, Solar Blast cycled. The cycle puts two of the human's triggers on
the stack together — Solar Blast's own "when you cycle this card" and Astral
Slide's "whenever a player cycles a card, you may exile target creature" — so
the seat owes ``trigger_target`` (Astral Slide's target, CR 603.3d) **and**
``order_triggers`` (CR 603.3b) at the same moment. The browser shows the target
first (``renderActivationPrompt``). The action gate (``web.prompts.
blocking_prompt``) refused every action that did not answer *each* pending
prompt, so each of the two refused the other's answer:

* the target click: 400 "choose the order of your triggered abilities before
  other actions";
* the order: 400 "choose the triggered ability's target before other actions".

Neither could ever be sent, and the game waited on the seat for good — the
cycling deck is the set's archetype, so any Astral Slide or Lightning Rift
beside a card with its own cycle trigger reached it.

The gate now takes the pending prompts in their registered order (the order
``Game.waiting_prompt`` reports and the browser's cascade renders them in): an
answer to the first decision the seat owes goes through, and the later one
waits for it.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from engine.models import Permanent
from tests.helpers import app_js_function_body
from web.app import app, store

client = TestClient(app)


def _session(set_pool):
    """A human-vs-AI session: seat 0 controls Astral Slide and holds Solar
    Blast with priority in its main phase; seat 1 controls one creature.

    The AI's hand is emptied so its answer to the cycle cannot depend on what
    it was dealt (``test_ons_w1g3_cycle_trigger_wire``'s reason)."""
    created = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "H",
        "host_colors": 2, "guest_colors": 2, "seed": 11,
    }).json()
    sid = created["session_id"]
    game = store.get(sid).game
    game.active_player_index = 0
    game.priority_player_index = 0
    game.enforce_mana_costs = False
    game.players[1].hand.clear()
    ons = set_pool("ONS")
    game._put_permanent_onto_battlefield(0, Permanent(card=ons["Astral Slide"]), None)
    theirs = Permanent(card=ons["Hystrodon"])
    game._put_permanent_onto_battlefield(1, theirs, None)
    game._sync_control()
    game.players[0].hand.append(ons["Solar Blast"])
    return sid, game, theirs


def _state(sid, seat=0):
    return client.get(f"/api/sessions/{sid}/state?seat={seat}").json()


def _act(sid, **body):
    return client.post(f"/api/sessions/{sid}/action", json={"seat": 0, **body})


def _cycle(sid, name):
    entry = next(e for e in _state(sid)["hand_abilities"] if e["name"] == name)
    assert entry["cost_text"].startswith("Cycling ")
    response = _act(
        sid, action="activate_hand", card_name=name,
        hand_index=entry["hand_index"], ability_index=entry["ability_index"],
    )
    assert response.status_code == 200, response.text


def test_the_target_and_the_order_owed_together_are_both_answerable(set_pool):
    sid, game, theirs = _session(set_pool)
    _cycle(sid, "Solar Blast")

    state = _state(sid)
    assert state["waiting_on_prompt"] is True
    target = state["trigger_target"]
    order = state["order_triggers"]
    assert target is not None and target["card_name"] == "Astral Slide", target
    assert order is not None and len(order["triggers"]) == 2, order
    assert {t["card_name"] for t in order["triggers"]} == {"Solar Blast", "Astral Slide"}
    # Neither is shown to the other seat.
    other = _state(sid, seat=1)
    assert other["trigger_target"] is None and other["order_triggers"] is None

    # The target comes first — the order the browser renders them in — so the
    # order waits for it rather than refusing it.
    early = _act(sid, action="order_triggers_confirm", trigger_order=[0, 1])
    assert early.status_code == 400
    assert "target" in early.json()["detail"]

    # The body app.js's `onPermanent` builds for a trigger_target prompt.
    response = _act(
        sid, action="trigger_target_confirm", target_permanent_id=theirs.permanent_id,
    )
    assert response.status_code == 200, response.text

    # Any further target the cycle's triggers ask is answered the same way;
    # then the order, which is still owed while both are on the stack.
    for _ in range(3):
        state = _state(sid)
        if state["trigger_target"] is None:
            break
        candidates = [c for c in state["trigger_target"]["candidates"] if c.get("kind") == "permanent"]
        response = _act(
            sid, action="trigger_target_confirm", target_permanent_id=candidates[0]["id"],
        )
        assert response.status_code == 200, response.text
    state = _state(sid)
    assert state["trigger_target"] is None
    assert state["order_triggers"] is not None, "both triggers are still on the stack"
    response = _act(sid, action="order_triggers_confirm", trigger_order=[0, 1])
    assert response.status_code == 200, response.text

    state = _state(sid)
    assert state["order_triggers"] is None
    assert state["waiting_on_prompt"] is False
    slide = next(item for item in game.stack if item.card.name == "Astral Slide")
    assert slide.target_permanent_id == [theirs.permanent_id]


def test_the_browser_renders_the_target_before_the_order():
    """The server's precedence is only half of it: the browser must show the
    prompt the server will accept first. ``renderActivationPrompt`` reaches the
    trigger's target before the order, as ``table.py`` registers them."""
    body = app_js_function_body("renderActivationPrompt")
    assert body.index("applyTriggerTargetPrompt(") < body.index("applyOrderTriggersPrompt(")
