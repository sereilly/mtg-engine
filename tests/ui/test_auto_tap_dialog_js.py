"""The auto-tap dialog is a renderer of the server's plan — run for real.

``tests/ui/test_auto_tap_plan_census.py`` holds the server's plan to the
castable glow. This is the other half: the client functions that ask for that
plan, decide whether the button may be pressed, and send the paying action,
lifted out of ``app.js`` and run in node against payloads the server really
sent — and the body they build posted back, as built.

What cannot be run here is the click itself (the dialog is a branch of a
DOM-bound renderer); that was driven in a browser.
"""
from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import app_js_function_body, run_app_js
from web.app import app, store

client = TestClient(app)
_CARDS = {card.name: card for card in load_catalog()}

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)

#: The module state the lifted functions close over, and the page they touch.
_PRELUDE = r'''
const _CAST_ACTIONS = new Set(["cast", "debug_cast_free", "debug_cast_free_opponent"]);
let seat = 0;
let sessionId = "S";
let currentState = INPUT.state || null;
let pendingAutoTap = null;
let pendingCastModeIndex = null;
let pendingCastFromZone = null;
let pendingCastZoneWay = null;
let pendingCastCost = null;
const posted = [];
const sent = [];
const hints = [];
let renders = 0;
let cleared = 0;
let reply = INPUT.reply || null;
function getCurrentPlayerState(state = currentState) { return state ? state.players[seat] : null; }
function postJson(url, body) {
  posted.push({ url, body });
  return reply && reply.error ? Promise.reject(new Error(reply.error)) : Promise.resolve(reply);
}
function sendAction(body) { sent.push(body); return Promise.resolve(); }
function renderActivationPrompt() { renders += 1; }
function updateActionHint(message) { hints.push(message); }
function clearPendingHandCast() { cleared += 1; }
'''

_FUNCTIONS = [
    "autoTapStateKey", "autoTapActionBody", "refreshAutoTapPlan",
    "autoTapIsPayable", "autoTapPlanLines", "autoTapChargedCost",
    "autoTapPromptText", "performAutoTap", "isManaRefusal",
    "carryCastMode", "carryCastZoneAndCost",
]


def _session(board, hand):
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 4245,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    session.pregame_phase = None
    game.enforce_mana_costs = True
    game.players[0].battlefield = []
    game.players[1].battlefield = []
    for name in board:
        permanent = Permanent(card=_CARDS[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        permanent.tapped = False
    game._recompute_continuous_effects()
    game.players[0].hand = [_CARDS[name] for name in hand]
    game.stack.clear()
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, game


def _state(sid):
    return client.get(f"/api/sessions/{sid}/state?seat=0").json()


@needs_node
def test_the_dialog_asks_the_server_and_sends_what_it_was_shown():
    """The whole exchange, with the server on the other end of both requests:
    the cast is refused, the client asks ``payment_plan`` with that very body,
    the button is live, and the body it then sends — posted as built — taps
    the Sol Ring and the Elf through the engine and casts the card."""
    sid, game = _session(["Sol Ring", "Forest", "Llanowar Elves"], ["Juggernaut"])
    body = {"seat": 0, "action": "cast", "card_name": "Juggernaut", "target_seat": 1}
    refused = client.post(f"/api/sessions/{sid}/action", json=body)
    assert refused.status_code == 400
    assert refused.json()["detail"] == "insufficient mana for Juggernaut"

    asked = run_app_js(
        _FUNCTIONS,
        """
        pendingAutoTap = { card: { name: "Juggernaut", mana_cost: "{4}" }, cardName: "Juggernaut", actionBody: INPUT.body };
        refreshAutoTapPlan();
        return { posted, payable: autoTapIsPayable(pendingAutoTap), text: autoTapPromptText(pendingAutoTap) };
        """,
        {"state": _state(sid), "body": body},
        prelude=_PRELUDE,
    )
    # Asked once, of the preview route, with the refused action itself; and
    # until the answer is in the button stays dead.
    assert [entry["url"] for entry in asked["posted"]] == ["/api/sessions/S/payment_plan"]
    assert asked["posted"][0]["body"] == body
    assert asked["payable"] is False
    assert "Asking what could pay" in asked["text"]

    plan = client.post(f"/api/sessions/{sid}/payment_plan", json=asked["posted"][0]["body"]).json()
    shown = run_app_js(
        _FUNCTIONS,
        """
        pendingAutoTap = { card: { name: "Juggernaut" }, cardName: "Juggernaut", actionBody: INPUT.body };
        refreshAutoTapPlan();
        await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
        const pending = pendingAutoTap;
        const view = {
          payable: autoTapIsPayable(pending), text: autoTapPromptText(pending),
          lines: autoTapPlanLines(pending.plan), cost: autoTapChargedCost(pending.plan), renders,
        };
        await performAutoTap();
        return { ...view, sent, hints, cleared, stillPending: pendingAutoTap !== null };
        """,
        {"state": _state(sid), "body": body, "reply": plan},
        prelude=_PRELUDE,
    )
    assert shown["payable"] is True
    assert shown["renders"] >= 1
    assert shown["lines"] == [
        "Forest for {G}", "Sol Ring for {C}", "Llanowar Elves for {G}",
    ]
    assert shown["cost"] == "{4}"
    assert "Auto-Tap will tap 3 permanents" in shown["text"]
    # One request: the pending action with ``auto_tap`` — no tap of its own.
    assert shown["sent"] == [{**body, "auto_tap": True}]
    assert shown["stillPending"] is False and shown["cleared"] == 1

    paid = client.post(f"/api/sessions/{sid}/action", json=shown["sent"][0])
    assert paid.status_code == 200, paid.text
    assert all(p.tapped for p in game.controlled_by(0))
    assert "Sol Ring produced {C}{C}" in game.log
    assert "Llanowar Elves produced {G}" in game.log
    assert [item.card.name for item in game.stack] == ["Juggernaut"]


@needs_node
def test_the_button_is_dead_where_the_server_says_nothing_pays():
    sid, _game = _session(["Forest", "Llanowar Elves"], ["Craw Wurm"])
    body = {"seat": 0, "action": "cast", "card_name": "Craw Wurm", "target_seat": 1}
    plan = client.post(f"/api/sessions/{sid}/payment_plan", json=body).json()

    shown = run_app_js(
        _FUNCTIONS,
        """
        pendingAutoTap = { card: { name: "Craw Wurm" }, cardName: "Craw Wurm", actionBody: INPUT.body };
        refreshAutoTapPlan();
        await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
        return {
          payable: autoTapIsPayable(pendingAutoTap), text: autoTapPromptText(pendingAutoTap),
          lines: autoTapPlanLines(pendingAutoTap.plan), cost: autoTapChargedCost(pendingAutoTap.plan),
        };
        """,
        {"state": _state(sid), "body": body, "reply": plan},
        prelude=_PRELUDE,
    )

    assert shown["payable"] is False and shown["lines"] == []
    assert shown["cost"] == "{4}{G}{G}"
    assert shown["text"] == (
        "Nothing you could tap pays for Craw Wurm (insufficient mana for Craw Wurm). "
        "Add mana yourself, or cancel."
    )


@needs_node
def test_the_plan_is_asked_again_only_when_the_board_under_it_moves():
    """The dialog's renderer calls ``refreshAutoTapPlan`` on every state. The
    same pool and the same taps are one question; a land tapped by hand is a
    new one."""
    sid, game = _session(["Forest", "Forest", "Forest"], ["Grizzly Bears"])
    body = {"seat": 0, "action": "cast", "card_name": "Grizzly Bears", "target_seat": 1}
    before = _state(sid)
    forest = next(iter(game.controlled_by(0)))
    tapped = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "tap", "permanent_id": forest.permanent_id, "mana_color": "G",
    })
    assert tapped.status_code == 200, tapped.text

    counted = run_app_js(
        _FUNCTIONS,
        """
        pendingAutoTap = { card: { name: "Grizzly Bears" }, cardName: "Grizzly Bears", actionBody: INPUT.body };
        refreshAutoTapPlan();
        refreshAutoTapPlan();
        const afterTwo = posted.length;
        currentState = INPUT.after;
        refreshAutoTapPlan();
        return { afterTwo, afterMove: posted.length };
        """,
        {"state": before, "after": _state(sid), "body": body, "reply": {"payable": True, "taps": []}},
        prelude=_PRELUDE,
    )

    assert counted == {"afterTwo": 1, "afterMove": 2}


@needs_node
def test_the_preview_carries_the_announcement_the_cast_will():
    """A chosen mode, the zone a card is cast from and a cost already named
    ride module state, not the body a prompt built. ``sendAction`` adds them;
    the preview has to, or it plans a different cast from the one it is
    shown beside."""
    out = run_app_js(
        _FUNCTIONS,
        """
        pendingCastModeIndex = 2;
        pendingCastFromZone = "graveyard";
        pendingCastCost = { cost_hand_index: 1, optional_cost_payments: { "{2}{G}": 1 } };
        pendingAutoTap = { cardName: "X", actionBody: INPUT.body };
        refreshAutoTapPlan();
        return { asked: posted[0].body, untouched: INPUT.body };
        """,
        {"body": {"seat": 0, "action": "cast", "card_name": "X"}},
        prelude=_PRELUDE,
    )

    assert out["asked"] == {
        "seat": 0, "action": "cast", "card_name": "X", "mode_index": 2,
        "from_zone": "graveyard", "cost_hand_index": 1,
        "optional_cost_payments": {"{2}{G}": 1},
    }
    assert out["untouched"] == {"seat": 0, "action": "cast", "card_name": "X"}


@needs_node
def test_both_wordings_of_a_mana_refusal_open_the_dialog():
    """A cast and a permanent's ability say "insufficient mana …"; an ability
    activated from a hand says "… cannot pay for …'s ability". The second is
    the engine's real sentence, read off the wire here."""
    sid, _game = _session(["Forest", "Forest"], ["Drifting Meadow"])
    refused = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "activate_hand", "card_name": "Drifting Meadow",
        "hand_index": 0, "ability_index": 0,
    })
    assert refused.status_code == 400

    answers = run_app_js(
        ["isManaRefusal"],
        "return INPUT.map((message) => isManaRefusal(message));",
        [
            refused.json()["detail"], "insufficient mana for Juggernaut",
            "insufficient mana to activate Rod of Ruin",
            "you do not currently have priority", "", None,
        ],
    )

    assert answers == [True, True, True, False, False, False]


def test_no_planner_is_left_in_the_client():
    """The four functions that planned a payment in the browser are gone, and
    the paying click sends one request: nothing in it taps a land itself."""
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[2]
        / "web" / "static" / "app.js"
    ).read_text(encoding="utf-8")
    for gone in (
        "computeAutoTapPlan", "computeAutoTapLands", "canAutoTapSatisfyCost",
        "inferLandProducedMana",
    ):
        assert gone not in source, gone

    pay = app_js_function_body("performAutoTap")
    assert "auto_tap: true" in pay
    assert 'action: "tap"' not in pay and "mana_pool" not in pay

    plan = app_js_function_body("refreshAutoTapPlan")
    assert "/payment_plan" in plan and "autoTapActionBody(pending)" in plan


def test_the_dialog_and_the_second_click_read_the_plan():
    """The two places that decide whether the payment may go ahead — the
    dialog's button and a second click on the card — ask ``autoTapIsPayable``,
    and the dialog is what keeps the plan current."""
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[2]
        / "web" / "static" / "app.js"
    ).read_text(encoding="utf-8")
    dialog = source[source.index("  if (pendingAutoTap) {\n"):]
    dialog = dialog[:dialog.index("if (pendingModalChoice) {")]
    assert "refreshAutoTapPlan();" in dialog
    assert "autoTapBtn.disabled = !autoTapIsPayable(pendingAutoTap);" in dialog
    assert source.count("autoTapIsPayable(pendingAutoTap)") >= 2


def test_a_hand_ability_the_pool_cannot_pay_for_opens_the_dialog():
    body = app_js_function_body("renderHandAbilities")

    assert "isManaRefusal(e.message)" in body
    assert "pendingAutoTap = {" in body
    assert body.index("isManaRefusal(e.message)") < body.index("pendingAutoTap = {")
