"""One seat owing two ``order_triggers`` prompts at once — one per round of
CR 603.3b — answers both, in order, over the wire.

    603.3b … Then the game once again checks for and performs state-based
    actions until none are performed, then abilities that triggered during
    this process go on the stack. This process repeats …

Since Scourge's Phase 5 an ability set off while a triggered ability is put on
the stack goes on in the next round (``StackItem.trigger_round``), and the
ordering is asked once per seat per round — so one seat can owe two prompts at
once. Whether the client answers both was unwatched: the re-check found no
board that arms two.

The board: on its controller's upkeep, Sulfuric Vortex and Spiteful Bully
trigger together (round 0, two abilities of two sources). Bully's "3 damage to
target creature you control" is aimed at Task Force as it goes on the stack —
and that announcement sets off two more of the same seat's abilities, Task
Force's "becomes the target … gets +0/+3" and Cowardice's "whenever a creature
becomes the target … return that creature" (round 1). The seat owes the round-0
order and the round-1 order at the same moment.

Driven in a browser too (kg4, port 8022): the Bully's target clicked on the
canvas, the round-0 list shown and re-ordered, "Put on the stack", the round-1
list shown at once and re-ordered, and the four resolved in the orders sent.
"""
from __future__ import annotations

import shutil

import pytest

from tests.helpers import run_app_js
from tests.ui.test_order_triggers_prompt_ui_api import _act, _session_at_human_upkeep, _state

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is not on PATH; the client half cannot run",
)

_BOARD = ["Spiteful Bully", "Sulfuric Vortex", "Task Force", "Cowardice"]


def _names(prompt):
    return [entry["card_name"] for entry in prompt["triggers"]]


def _client_reading(state):
    """What the browser's readers make of a state: the prompt it renders and
    the key its order draft is filed under (a new key starts a new draft)."""
    return run_app_js(
        ["getOrderTriggersInfo", "orderTriggersKey"],
        "const info = getOrderTriggersInfo(INPUT);"
        " return info && { names: info.triggers.map((t) => t.card_name), key: orderTriggersKey(info) };",
        state,
        prelude="let seat = 0; let currentState = null;",
    )


@needs_node
def test_both_rounds_are_ordered_one_after_the_other():
    sid, game = _session_at_human_upkeep(_BOARD)
    ids = {permanent.card.name: permanent.permanent_id for permanent in game.controlled_by(0)}

    # Round 0 is owed with Bully's target still to be chosen.
    state = _state(sid)
    assert state["trigger_target"]["card_name"] == "Spiteful Bully"
    assert sorted(_names(state["order_triggers"])) == ["Spiteful Bully", "Sulfuric Vortex"]

    aimed = _act(sid, action="trigger_target_confirm", target_permanent_id=ids["Task Force"])
    assert aimed.status_code == 200, aimed.text

    # The announcement set off round 1: the seat now owes two orders at once.
    owed = [choice for choice in game.pending_choices if choice.kind == "order_triggers"]
    assert len(owed) == 2 and all(choice.player_index == 0 for choice in owed)
    first = _state(sid)
    assert first["waiting_on_prompt"] is True
    assert sorted(_names(first["order_triggers"])) == ["Spiteful Bully", "Sulfuric Vortex"]
    first_seen = _client_reading(first)
    assert sorted(first_seen["names"]) == ["Spiteful Bully", "Sulfuric Vortex"]

    # Round 0: Bully first.
    bully_first = [entry["index"] for entry in first["order_triggers"]["triggers"]
                   if entry["card_name"] == "Spiteful Bully"]
    bully_first += [entry["index"] for entry in first["order_triggers"]["triggers"]
                    if entry["card_name"] != "Spiteful Bully"]
    assert _act(sid, action="order_triggers_confirm", trigger_order=bully_first).status_code == 200

    # The second prompt is the one now rendered — and to the client a new
    # prompt, whose draft starts from the order the server offered.
    second = _state(sid)
    assert second["waiting_on_prompt"] is True
    assert sorted(_names(second["order_triggers"])) == ["Cowardice", "Task Force"]
    second_seen = _client_reading(second)
    assert sorted(second_seen["names"]) == ["Cowardice", "Task Force"]
    assert second_seen["key"] != first_seen["key"]

    # Round 1: Task Force first.
    force_first = [entry["index"] for entry in second["order_triggers"]["triggers"]
                   if entry["card_name"] == "Task Force"]
    force_first += [entry["index"] for entry in second["order_triggers"]["triggers"]
                    if entry["card_name"] != "Task Force"]
    assert _act(sid, action="order_triggers_confirm", trigger_order=force_first).status_code == 200

    done = _state(sid)
    assert done["order_triggers"] is None
    assert not any(choice.kind == "order_triggers" for choice in game.pending_choices)
    # Top first: round 1 above round 0, each in the order its prompt sent.
    assert [item["card"]["name"] for item in done["stack"]] == [
        "Task Force", "Cowardice", "Spiteful Bully", "Sulfuric Vortex",
    ]
    ordered = [line for line in done["log"] if "ordered their triggered abilities (603.3b)" in line]
    assert len(ordered) == 2
    assert ordered[0].index("Spiteful Bully") < ordered[0].index("Sulfuric Vortex")
    assert ordered[1].index("Task Force") < ordered[1].index("Cowardice")
