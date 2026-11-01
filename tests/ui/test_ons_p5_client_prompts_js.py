"""Two client prompts Onslaught's post-promotion pass found wrong in the browser,
asked of ``app.js``'s own functions with the payload the server really sent.

* **Holding priority at your own upkeep showed no panel.** The phase rail lets
  a seat hold at its upkeep and draw step (Words of Worship's "{1}: the next
  time you would draw a card this turn, you gain 5 life instead" is activated
  there), the server hands it priority, and ``shouldShowPriorityPrompt``
  answered yes only for main phases, combat, the end step and the opponent's
  turn: the panel stayed hidden over "No pending activation.", and only the
  rail's Next Phase could move the game on.
* **A free life gain was a payment.** Renewed Faith's "when you cycle this card,
  you may gain 2 life" was titled "Pay for Life?" with a "Pay" button over an
  empty cost, because the free test (``optionalOfferIsFree`` now) required the
  offer to gain no life.
"""
from __future__ import annotations

import re

from fastapi.testclient import TestClient

from tests.helpers import app_js_function_body, run_app_js
from web.app import app, store

client = TestClient(app)


def _session():
    created = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "H",
        "host_colors": 2, "guest_colors": 2, "seed": 11,
    }).json()
    sid = created["session_id"]
    session = store.get(sid)
    return sid, session, session.game


def _state(sid, seat=0):
    return client.get(f"/api/sessions/{sid}/state?seat={seat}").json()


def _should_show_priority(state, seat=0):
    """``shouldShowPriorityPrompt`` over *state*, every prompt getter it consults
    stubbed to "nothing owed" so the answer is the step rule's."""
    body = app_js_function_body("shouldShowPriorityPrompt")
    getters = sorted(set(re.findall(r"\b(get\w+Info)\(state\)", body)))
    prelude = (
        f"var seat = {seat};\n"
        'const NO_PRIORITY_STEPS = new Set(["untap", "cleanup"]);\n'
        + "".join(f"function {name}() {{ return null; }}\n" for name in getters)
        + "function combatPromptNeedsConfirmation() { return false; }\n"
    )
    return run_app_js(
        ["shouldShowPriorityPrompt"], "return shouldShowPriorityPrompt(INPUT);", state,
        prelude=prelude,
    )


def test_holding_priority_at_your_own_upkeep_shows_the_panel():
    sid, session, game = _session()
    session.pregame_phase = None
    session.current_turn = 0
    game.active_player_index = 0
    game._set_phase_and_step("beginning", "upkeep")
    game.priority_player_index = 0
    state = _state(sid)
    assert state["current_step"] == "upkeep" and state["current_turn"] == 0
    assert state["priority_player"] == 0
    assert _should_show_priority(state) is True

    # The same hold at the draw step; and no panel where priority is never
    # given (CR 502.4, 514.3) or while the other seat holds it.
    assert _should_show_priority({**state, "current_step": "draw"}) is True
    assert _should_show_priority({**state, "current_step": "untap"}) is False
    assert _should_show_priority({**state, "priority_player": 1}) is False


def test_renewed_faiths_free_life_gain_is_a_yes_or_no(set_pool):
    sid, session, game = _session()
    game.active_player_index = 0
    game.priority_player_index = 0
    game.enforce_mana_costs = False
    game.players[1].hand.clear()
    game.players[0].hand.append(set_pool("ONS")["Renewed Faith"])
    entry = next(e for e in _state(sid)["hand_abilities"] if e["name"] == "Renewed Faith")
    assert client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "activate_hand", "card_name": "Renewed Faith",
        "hand_index": entry["hand_index"], "ability_index": entry["ability_index"],
    }).status_code == 200
    assert client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "pass_priority",
    }).status_code == 200
    offer = _state(sid)["optional_pay"]["pending"][0]
    assert offer["card_name"] == "Renewed Faith" and offer["life"] == 2, offer

    functions = ["optionalOfferIsFree", "manaCostText"]
    assert run_app_js(functions, "return optionalOfferIsFree(INPUT);", offer) is True
    # A priced offer is still a payment, and a decline that deals damage is not free.
    assert run_app_js(functions, "return optionalOfferIsFree(INPUT);",
                      {**offer, "cost": {"generic": 1}}) is False
    assert run_app_js(functions, "return optionalOfferIsFree(INPUT);",
                      {**offer, "damage": 3}) is False
    # The renderer reads the helper, and titles a free offer before a life gain.
    renderer = app_js_function_body("applyOptionalPayPrompt")
    assert "optionalOfferIsFree(current)" in renderer
    assert renderer.index('? "Optional Effect"') < renderer.index('? "Pay for Life?"')
