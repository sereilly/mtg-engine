"""Krark's Thumb's "ignore one" on the wire and in the client (kg5 `coins`).

The flipper's seat is served the ``ignore_coin`` prompt — every coin the flip
became, every other coin flipped with it, the permanents that made the extra
coins and the text of what is flipping — and answers it with
``ignore_coin_confirm`` and ``option_index`` (0 keeps the win, 1 the loss).
The board is Puppet's Verdict under the Thumb, one coin won and one lost, at
a table of two people; the client half runs the real ``app.js`` functions over
the payload the server sent and posts back what their buttons send.
"""
from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import run_app_js
from web.app import app, store

client = TestClient(app)
_POOL = {card.name: card for card in load_catalog()}

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)


def _put(game, seat, name):
    permanent = Permanent(card=_POOL[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _verdict_session(monkeypatch):
    """Seat 0 casts Puppet's Verdict over its Thumb, Llanowar Elves and
    Grizzly Bears against Bob's Craw Wurm; the coins come up a win and a
    loss. Returns the session id with the flip waiting on seat 0."""
    import engine.handlers.control_flow as control_flow

    coins = iter([True, False])
    monkeypatch.setattr(control_flow, "flip_coin", lambda *_: next(coins, True))
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 705,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    session.pregame_phase = None
    game = session.game
    for player in game.players:
        player.battlefield, player.hand, player.graveyard, player.exile = [], [], [], []
    game.interactive_seats = {0, 1}
    game.enforce_mana_costs = False
    session.current_turn = 0
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    for name in ("Krark's Thumb", "Llanowar Elves", "Grizzly Bears"):
        _put(game, 0, name)
    _put(game, 1, "Craw Wurm")
    game.players[0].hand = [_POOL["Puppet's Verdict"]]
    game.start_priority_window(0)
    cast = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "cast", "card_name": "Puppet's Verdict",
    })
    assert cast.status_code == 200, cast.text
    # Both seats pass: the spell resolves and its flip asks seat 0.
    for seat in (0, 1):
        state = _state(sid, seat)
        if state.get("ignore_coin"):
            break
        client.post(f"/api/sessions/{sid}/action", json={"seat": seat, "action": "pass_priority"})
    return sid, session


def _state(sid, seat):
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _names(permanents):
    return sorted(p.card.name for p in permanents)


def test_the_flippers_seat_is_served_every_coin_and_the_two_answers(monkeypatch):
    sid, session = _verdict_session(monkeypatch)
    state = _state(sid, 0)
    prompt = state["ignore_coin"]
    assert prompt["player_seat"] == 0
    assert prompt["card_name"] == "Puppet's Verdict"
    assert prompt["wins"] is True
    assert prompt["coins"] == ["won", "lost"]
    assert prompt["ignored_by"] == ["Krark's Thumb"]
    assert "power 3 or greater" in prompt["effect_text"]
    assert [o["result"] for o in prompt["options"]] == ["won", "lost"]
    assert state["prompt_owed_by"]["seat"] == 0
    assert state["prompt_owed_by"]["doing"] == "choose which coin to keep"
    # The other seat is not served the chooser's prompt, and the spell waits.
    assert _state(sid, 1)["ignore_coin"] is None
    assert [item["card"]["name"] for item in state["stack"]] == ["Puppet's Verdict"]


def test_the_prompt_gates_everything_but_its_answer(monkeypatch):
    sid, _session = _verdict_session(monkeypatch)
    url = f"/api/sessions/{sid}/action"
    refused = client.post(url, json={"seat": 0, "action": "pass_priority"})
    assert refused.status_code == 400
    assert refused.json()["detail"] == "choose which coin to keep before other actions"
    assert client.post(url, json={"seat": 0, "action": "ignore_coin_confirm"}).status_code == 400
    assert client.post(url, json={"seat": 0, "action": "ignore_coin_confirm", "option_index": 2}).status_code == 400
    assert client.post(url, json={"seat": 1, "action": "ignore_coin_confirm", "option_index": 1}).status_code == 400
    assert _state(sid, 0)["ignore_coin"] is not None


@pytest.mark.parametrize("option, mine, theirs", [
    (1, ["Grizzly Bears", "Krark's Thumb", "Llanowar Elves"], []),
    (0, ["Krark's Thumb"], ["Craw Wurm"]),
])
def test_each_answer_on_the_wire_is_the_coin_kept(monkeypatch, option, mine, theirs):
    sid, session = _verdict_session(monkeypatch)
    answered = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "ignore_coin_confirm", "option_index": option,
    })
    assert answered.status_code == 200, answered.text
    game = session.game
    assert _names(game.players[0].battlefield) == mine
    assert _names(game.players[1].battlefield) == theirs
    state = _state(sid, 0)
    assert state["ignore_coin"] is None
    assert state["stack"] == []
    kept = "the loss" if option == 1 else "the win"
    assert f"Puppet's Verdict: Host won 1 of 2 coins and keeps {kept} (Krark's Thumb)" in game.log


_DOM_PRELUDE = """
let seat = 0, currentState = { stack: [] };
const sent = [];
const els = {};
function q(id) {
  if (!els[id]) {
    els[id] = {
      id, textContent: "", innerHTML: "", disabled: false,
      classList: { add() {}, remove() {}, toggle() {} },
      querySelector() { return null; },
      querySelectorAll(selector) {
        const attr = selector.replace(/^\\[|\\]$/g, "");
        const found = [];
        const pattern = new RegExp(attr + '="(\\\\d+)">([^<]*)<', "g");
        let match;
        while ((match = pattern.exec(this.innerHTML))) {
          const button = { dataset: { ignoreCoin: match[1] }, label: match[2], handlers: [],
            addEventListener(_kind, fn) { this.handlers.push(fn); } };
          found.push(button);
        }
        this.buttons = found;
        return found;
      },
    };
  }
  return els[id];
}
function escapeHtml(value) { return String(value); }
function updateActionHint() {}
async function sendAction(body) { sent.push(body); }
"""


@needs_node
def test_the_client_renders_the_served_prompt_and_sends_the_answer(monkeypatch):
    sid, _session = _verdict_session(monkeypatch)
    state = _state(sid, 0)
    out = run_app_js(
        ["getIgnoreCoinInfo", "applyIgnoreCoinPrompt"],
        """
        const info = getIgnoreCoinInfo(INPUT);
        applyIgnoreCoinPrompt(info);
        const steps = q("promptSteps");
        const labels = steps.buttons.map((b) => b.label);
        for (const fn of steps.buttons[1].handlers) await fn();
        return { title: q("promptTitle").textContent, body: q("promptBody").textContent,
                 steps: steps.innerHTML, labels, sent };
        """,
        state,
        prelude=_DOM_PRELUDE,
    )
    assert out["title"] == "Puppet's Verdict — keep which coin?"
    assert "won, lost" in out["body"] and "Krark's Thumb" in out["body"]
    assert "power 3 or greater" in out["steps"]
    assert out["labels"] == ["Keep the win", "Keep the loss"]
    assert out["sent"] == [{"seat": 0, "action": "ignore_coin_confirm", "option_index": 1}]
    # What the button sent is what the route takes.
    answered = client.post(f"/api/sessions/{sid}/action", json=out["sent"][0])
    assert answered.status_code == 200, answered.text
    assert _names(store.get(sid).game.players[1].battlefield) == []


@needs_node
def test_another_seats_prompt_is_not_rendered_for_this_seat(monkeypatch):
    sid, _session = _verdict_session(monkeypatch)
    state = _state(sid, 0)
    out = run_app_js(
        ["getIgnoreCoinInfo"],
        "seat = 1; return getIgnoreCoinInfo(INPUT);",
        state,
        prelude=_DOM_PRELUDE,
    )
    assert out is None
