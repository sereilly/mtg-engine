"""A triggered ability whose target is a **spell**, through the wire a browser
uses: "When this creature enters, counter target spell." (Mystic Snake.)

CR 603.3d chooses a trigger's target as it is put on the stack, and for a
permanent or a player that has long been the ``trigger_target`` prompt. A spell
had no place in it — the payload carried seats and permanent ids, the client
rendered neither for a stack object — so every seat took the engine's default
(the topmost opposing spell) and a human who put a Snake onto the battlefield
with two spells waiting was never asked which. What is pinned here:

* the prompt reaches the trigger's controller with one ``stack`` candidate per
  legal spell, each carrying the position the client's stack cascade shows it
  at (``stack_index``, topmost 0 — a cast's ``target_stack_index`` convention);
* the answer is that same field on ``trigger_target_confirm``, held to the
  candidates the prompt offered and never to the stack alone;
* the neighbouring shapes still answer as they did (a permanent by id).

Driven in a browser as a human seat for wave 2 (Elvish Piper putting the Snake
onto the battlefield over a Lightning Bolt and a Shock, the lower spell
clicked); the text-level test at the bottom is the ratchet on what was driven
and not a substitute for it. The engine half is in
``tests/sets/test_apc_creatures.py``.

Armed directly on the session's game: the web catalog is the shipped pool and
Apocalypse is a measured set until promotion, so the Snake is read from its set
file and put onto the battlefield by the engine.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from engine.models import Permanent
from web.app import app, store
from tests.helpers import app_js_function_body

client = TestClient(app)


def _session(set_pool):
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 6033,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    # What the action preamble sets before every action; the trigger below is
    # put on the stack on the engine directly, before any action has run.
    game.interactive_seats = {0, 1}
    for player in game.players:
        player.battlefield.clear()
        player.hand.clear()
    lea, sth = set_pool("LEA"), set_pool("STH")
    game.players[1].hand.extend([lea["Lightning Bolt"], sth["Shock"]])
    session.current_turn = 1
    game.start_turn(1)
    game._settle()
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert game.queue_from_hand(1, "Shock", target_player_index=0).supported
    game._put_permanent_onto_battlefield(
        0, Permanent(card=set_pool("APC")["Mystic Snake"]), None
    )
    return sid, game


def _state(sid: str, seat: int) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _act(sid: str, **body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def test_the_prompt_offers_each_spell_by_where_the_client_shows_it(set_pool):
    sid, game = _session(set_pool)

    state = _state(sid, 0)
    prompt = state["trigger_target"]
    assert prompt is not None and prompt["player_seat"] == 0
    assert prompt["card_name"] == "Mystic Snake"
    assert prompt["candidates"] == [
        {"kind": "stack", "stack_index": 1, "seat": 1, "name": "Shock"},
        {"kind": "stack", "stack_index": 2, "seat": 1, "name": "Lightning Bolt"},
    ]
    # The index is into the stack the same payload serializes, topmost first,
    # with the trigger itself on top of both spells.
    labels = [item["label"] for item in state["stack"]]
    assert labels[1] == "Shock" and labels[2] == "Lightning Bolt"
    assert "Mystic Snake" in labels[0]


def test_a_position_the_prompt_did_not_offer_is_refused(set_pool):
    sid, game = _session(set_pool)

    for index in (0, 3, 7):
        refused = _act(sid, seat=0, action="trigger_target_confirm", target_stack_index=index)
        assert refused.status_code == 400, index
    # Not the other seat's to answer, and not answerable by passing.
    assert _act(sid, seat=1, action="trigger_target_confirm", target_stack_index=2).status_code == 400
    assert _act(sid, seat=0, action="pass_priority").status_code == 400
    assert _act(sid, seat=0, action="trigger_target_confirm").status_code == 400
    assert game.stack[-1].target_stack_item is None
    assert _state(sid, 0)["trigger_target"] is not None


def test_the_lower_spell_can_be_named_and_is_the_one_countered(set_pool):
    sid, game = _session(set_pool)
    bolt = game.stack[0]

    answered = _act(sid, seat=0, action="trigger_target_confirm", target_stack_index=2)
    assert answered.status_code == 200, answered.text

    trigger = game.stack[-1]
    assert trigger.target_stack_item is bolt
    state = _state(sid, 0)
    assert state["trigger_target"] is None
    assert state["stack"][0]["target_stack_name"] == "Lightning Bolt"
    assert "Mystic Snake: targets Lightning Bolt" in state["log"]

    game.resolve_top_of_stack()
    assert "Lightning Bolt was countered by Mystic Snake and moved to graveyard" in game.log
    assert [item.card.name for item in game.stack] == ["Shock"]


def test_a_spectator_is_shown_the_question_and_cannot_answer_it(set_pool):
    """The kind is ``spectator_visible``: a seatless viewer sees what the game
    is waiting on, spell candidates included, in the same shape."""
    sid, _game = _session(set_pool)

    watching = client.get(f"/api/sessions/{sid}/state").json()["trigger_target"]
    assert [c["kind"] for c in watching["candidates"]] == ["stack", "stack"]
    assert _state(sid, 1)["trigger_target"] is None


def test_the_client_reads_a_stack_candidate_and_answers_on_the_stack():
    """The ratchet on what was driven in the browser: the board-targeting
    descriptor collects ``stack`` candidates and answers with
    ``target_stack_index``; a click on the stack cascade reaches it; the
    cascade glows for it; and the prompt has a panel saying what to click."""
    targeting = app_js_function_body("getPromptBoardTargeting")
    assert 'c.kind === "stack"' in targeting
    assert "stackIndices.push(Number(c.stack_index))" in targeting
    assert "target_stack_index: stackIndex" in targeting

    descriptor = app_js_function_body("promptTargeting")
    assert "stackIndices" in descriptor and "onStack" in descriptor

    glow = app_js_function_body("renderStack")
    assert "activePromptBoardTargeting(currentState)?.stackIndices" in glow

    canvas = app_js_function_body("initBattlefieldCanvas")
    assert "promptStackTargeting.onStack(info.index)" in canvas

    panel = app_js_function_body("applyTriggerTargetPrompt")
    assert "a glowing spell on the stack" in panel
    dispatch = app_js_function_body("renderActivationPrompt")
    assert "applyTriggerTargetPrompt(triggerTargetPrompt)" in dispatch
