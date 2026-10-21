"""A divided spell whose pool cannot pay is offered the payment dialog, with
its division kept (CR 601.2d, then CR 601.2g-h).

``confirmCastDivision`` — the "Divide N damage" panel every divided spell
with a share per target ends in (Arc Lightning, Fire, Violent Eruption) —
answered an "insufficient mana" refusal with a hint and dropped the targets
and the shares, where every other send opens the Auto-Tap dialog with the
body kept. Found driving Violent Eruption's madness cast in a browser, and
reproduced on a shipped card: Arc Lightning cast from a hand beside three
untapped Mountains, divided 1 and 2, came back "insufficient mana for Arc
Lightning" with nothing to press, and the division dialog stayed on the
panel behind a cast that was no longer pending.
"""
from __future__ import annotations

import shutil

import pytest

from tests.helpers import run_app_js

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)

_PRELUDE = """
let seat = 0;
let pendingAutoTap = null;
let renders = 0;
let cleared = 0;
const hints = [];
let pendingCastDivision = null;
const renderActivationPrompt = () => { renders += 1; };
const updateActionHint = (text) => hints.push(text);
const clearPendingHandCast = () => { cleared += 1; };
const withPermanentId = (body) => body;
const getActivatedAbilityCost = () => "";
let refusal = null;
const sent = [];
const sendAction = async (body) => { sent.push(body); if (refusal) throw new Error(refusal); };
"""


def _run(refusal):
    return run_app_js(
        ["isManaRefusal", "divisionRemaining", "confirmCastDivision"],
        """
        refusal = INPUT.refusal;
        pendingCastDivision = {
          card: { name: "Arc Lightning", mana_cost: "{2}{R}" },
          cardName: "Arc Lightning", castAction: "cast", total: 3,
          entries: [{ seat: 1, index: 0 }, { seat: 1, index: 1 }],
          shares: [1, 2],
        };
        confirmCastDivision();
        await new Promise((resolve) => setTimeout(resolve, 0));
        return {
          sent, cleared, renders, hints,
          autoTap: pendingAutoTap && { cardName: pendingAutoTap.cardName, body: pendingAutoTap.actionBody },
        };
        """,
        {"refusal": refusal},
        prelude=_PRELUDE,
    )


@needs_node
def test_a_mana_refusal_keeps_the_division_for_the_payment_dialog():
    out = _run("insufficient mana for Arc Lightning")
    divided = [{"seat": 1, "index": 0, "amount": 1}, {"seat": 1, "index": 1, "amount": 2}]
    assert out["sent"] == [{
        "seat": 0, "action": "cast", "card_name": "Arc Lightning", "divided_targets": divided,
    }]
    assert out["autoTap"] == {"cardName": "Arc Lightning", "body": out["sent"][0]}
    # The cast is still pending (its payment is owed), and the panel redraws.
    assert out["cleared"] == 0 and out["renders"] >= 1


@needs_node
def test_any_other_refusal_ends_the_cast_and_says_why():
    out = _run("Arc Lightning can't be cast: a target is illegal")
    assert out["autoTap"] is None
    assert out["cleared"] == 1 and out["renders"] >= 1
    assert out["hints"][-1] == "Arc Lightning can't be cast: a target is illegal"
