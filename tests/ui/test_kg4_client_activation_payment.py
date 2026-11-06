"""The "Pay activation cost" prompt asks the server whether the pool pays.

An ability with a mana cost and nothing to choose opens a prompt ("Press OK to
start paying"), and once the player has tapped what they mean to tap the
activation goes out by itself. Whether the pool covered the cost was the
client's own judgement — ``manaPoolCanPayCost`` over its parse of the printed
cost — which knows no hybrid symbol, no spending restriction and no cost an
effect changed, so the prompt could promise "Cost is covered" and send an
activation the engine refused, or wait for ever on one it would have taken.
A fixed mana ability with a mana cost (a filter land) was sent at once on the
same judgement.

Now both send through ``sendAction``, whose payment preview
(``previewPayingAction``, ``POST …/payment_plan``) raises "insufficient mana"
without a request when the pool is short; the prompt stays up and asks again
when the pool, the tapped permanents or the log change. The functions are run
in node with the page stubbed out: the real source, a fake server.
"""
from __future__ import annotations

import shutil

import pytest

from tests.helpers import app_js_function_body, run_app_js

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is not on PATH; the client half cannot run",
)

_PRELUDE = r"""
let seat = 0;
let KEY = "k1";
let pendingActivation = null;
const sent = [];
const hints = [];
let answers = [];
function autoTapStateKey() { return KEY; }
function renderActivationPrompt() {}
function withPermanentId(body) { return body; }
function updateActionHint(message, isError) { hints.push([message, !!isError]); }
async function sendAction(body) {
  sent.push(body);
  const next = answers.shift();
  if (next instanceof Error) throw next;
  return next;
}
function shortOf(cost) {
  const refusal = new Error("insufficient mana");
  refusal.paymentPlan = { payable: true, taps: [{ id: 7, name: "Mountain" }], cost };
  return refusal;
}
"""


@needs_node
def test_the_prompt_waits_for_the_server_to_say_the_pool_pays():
    out = run_app_js(
        ["attemptPendingActivation", "isManaRefusal"],
        r"""
        pendingActivation = {
          cardName: "Shivan Dragon", permanentIndex: 2, targetSeat: 1, abilityIndex: null,
          activationCost: "{R}", manaRequirement: { R: 1 }, awaitingApproval: false,
        };
        const steps = [];
        // The pool is short: the preview raises, nothing is cleared.
        answers = [shortOf({ R: 1 })];
        await attemptPendingActivation();
        steps.push([sent.length, !!pendingActivation, pendingActivation.shortPlan.cost]);
        // Nothing the answer depends on moved: nothing is asked.
        await attemptPendingActivation();
        steps.push([sent.length, !!pendingActivation]);
        // A land tapped by hand: a new state, asked again, and it pays.
        KEY = "k2";
        answers = [{ ok: true }];
        await attemptPendingActivation();
        steps.push([sent.length, pendingActivation, hints[hints.length - 1]]);
        return { steps, body: sent[0] };
        """,
        prelude=_PRELUDE,
    )
    assert out["steps"] == [
        [1, True, {"R": 1}],
        [1, True],
        [2, None, ["Activated Shivan Dragon.", False]],
    ]
    assert out["body"] == {
        "seat": 0, "action": "activate", "permanent_name": "Shivan Dragon",
        "permanent_index": 2, "target_seat": 1,
    }


@needs_node
def test_a_refusal_for_anything_but_mana_closes_the_prompt_with_its_reason():
    out = run_app_js(
        ["attemptPendingActivation", "isManaRefusal"],
        r"""
        pendingActivation = {
          cardName: "Rock Hydra", permanentIndex: 0, targetSeat: 1, abilityIndex: 1,
          activationCost: "{R}{R}{R}", manaRequirement: { R: 3 }, awaitingApproval: false,
        };
        answers = [new Error("Rock Hydra: only during your upkeep")];
        await attemptPendingActivation();
        return { pending: pendingActivation, hint: hints[hints.length - 1], index: sent[0].ability_index };
        """,
        prelude=_PRELUDE,
    )
    assert out == {
        "pending": None, "hint": ["Rock Hydra: only during your upkeep", True], "index": 1,
    }


def test_no_payment_prompt_judges_the_pool_itself():
    for name in ("renderActivationPrompt", "attemptPendingActivation", "startActivationPrompt"):
        assert "manaPoolCanPayCost(" not in app_js_function_body(name), name
    assert "sendAction(activateBody)" in app_js_function_body("attemptPendingActivation")
