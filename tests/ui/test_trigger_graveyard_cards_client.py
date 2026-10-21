"""Gravegouger's targets in the browser: several cards from a single
graveyard, picked together (CR 603.3d, CR 601.2c).

"When this creature enters, exile up to two target cards from a single
graveyard." The ``trigger_target`` prompt carries ``max_targets`` and
``single_graveyard``, and the route takes ``target_seat`` with
``graveyard_indices`` (W2G2). The panel sent one ``graveyard_index`` per
click — an answer, and never the second card. It now toggles cards within
the pile of the first pick, holds Confirm to the printed count, and sends
the pile with its slots in one request; "Name no target" sends an empty
list. These run the real ``app.js`` functions over the payload the server
sent and post what they build.
"""
from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from tests.helpers import app_js_function_body, resolve_stack, run_app_js
from web.app import app, store

client = TestClient(app)

_POOL: dict = {}
for _card in load_cards(manifest_set_paths(include_measured=True)):
    _POOL.setdefault(_card.name, _card)

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)

_FUNCTIONS = [
    "graveyardOwnerLabel", "triggerNamesSeveralGraveyardCards",
    "triggerGraveyardPicksFor", "applyTriggerGraveyardCardsPrompt",
]

#: The panel's nodes, buttons rebuilt from the markup the renderer writes, and
#: what was sent recorded.
_PAGE = r'''
let seat = 0;
let currentState = INPUT.state;
let triggerGraveyardPicks = null;
function escapeHtml(text) { return String(text); }
const sent = [];
const hints = [];
function submitPromptAction(body) { sent.push(body); }
function updateActionHint(message) { hints.push(message); }
function button(markup) {
  const pick = /data-trigger-graveyard-pick="(\d+)"/.exec(markup);
  const id = /id="([^"]+)"/.exec(markup);
  return {
    dataset: pick ? { triggerGraveyardPick: pick[1] } : {},
    id: id ? id[1] : null,
    text: markup.replace(/<[^>]*>/g, ""),
    listeners: {},
    addEventListener(type, fn) { this.listeners[type] = fn; },
    click() { this.listeners.click(); },
  };
}
const steps = {
  buttons: [], markup: "",
  set innerHTML(html) {
    this.markup = html;
    this.buttons = (html.match(/<button[^>]*>[^<]*<\/button>/g) || []).map(button);
  },
  querySelectorAll() { return this.buttons.filter((b) => b.dataset.triggerGraveyardPick !== undefined); },
};
const okBtn = {
  textContent: "", disabled: false, onclick: null, hidden: true,
  classList: { remove() { okBtn.hidden = false; }, add() { okBtn.hidden = true; } },
};
const nodes = {
  promptTitle: { textContent: "" }, promptBody: { textContent: "" },
  promptSteps: steps, promptOkBtn: okBtn,
};
function q(id) { return nodes[id]; }
const document = {
  getElementById: (id) => steps.buttons.find((b) => b.id === id) || null,
};
function show() { applyTriggerGraveyardCardsPrompt(currentState.trigger_target); }
function labelled() { return steps.buttons.map((b) => b.text); }
function pick(name) { steps.buttons.find((b) => b.text.endsWith(name)).click(); }
'''


def _session():
    """Gravegouger entered on seat 0's battlefield, its trigger waiting on
    seat 0: one card in seat 0's graveyard, three in seat 1's."""
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "H", "guest_name": "G",
        "host_colors": 2, "guest_colors": 2, "seed": 603,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "G"})
    session = store.get(sid)
    session.current_turn = 0
    session.pregame_phase = None
    game = Game(players=[
        PlayerState(name="P0", hand=[_POOL["Gravegouger"]], library=[_POOL["Forest"]] * 5,
                    graveyard=[_POOL["Giant Growth"]]),
        PlayerState(name="P1", library=[_POOL["Forest"]] * 5,
                    graveyard=[_POOL[n] for n in ("Lightning Bolt", "Grizzly Bears", "Shock")]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game.queue_from_hand(0, "Gravegouger")
    game.resolve_top_of_stack()
    game.interactive_seats = {0, 1}
    session.game = game
    return sid, game


def _state(sid, seat=0):
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


@needs_node
def test_two_cards_from_one_pile_are_named_together():
    sid, game = _session()
    state = _state(sid)
    assert state["trigger_target"]["single_graveyard"] is True

    out = run_app_js(
        _FUNCTIONS,
        """
        const several = triggerNamesSeveralGraveyardCards(currentState.trigger_target);
        show();
        const opened = { body: nodes.promptBody.textContent, ok: okBtn.disabled, labels: labelled() };
        pick("Giant Growth");
        // Another pile is refused while a card of this one is chosen.
        pick("Lightning Bolt");
        const refused = hints.slice();
        pick("Giant Growth");
        pick("Shock");
        pick("Lightning Bolt");
        // A third card is past the printed two.
        pick("Grizzly Bears");
        const chosen = { labels: labelled(), ok: okBtn.disabled, text: okBtn.textContent };
        okBtn.onclick();
        return { several, opened, refused, chosen, sent };
        """,
        {"state": state},
        prelude=_PAGE,
    )

    assert out["several"] is True
    assert out["opened"]["body"] == (
        "Gravegouger: its triggered ability names up to 2 target cards from a "
        "single graveyard. Click each, then confirm."
    )
    assert out["opened"]["ok"] is True  # nothing chosen: Confirm waits
    assert out["refused"][0].startswith("Gravegouger takes its cards from a single graveyard")
    assert out["chosen"]["ok"] is False and out["chosen"]["text"] == "Confirm 2 targets"
    assert "1. Shock" in out["chosen"]["labels"] and "2. Lightning Bolt" in out["chosen"]["labels"]
    assert "Grizzly Bears" in out["chosen"]["labels"]  # not taken
    assert out["sent"] == [{
        "seat": 0, "action": "trigger_target_confirm", "target_seat": 1, "graveyard_indices": [2, 0],
    }]

    response = client.post(f"/api/sessions/{sid}/action", json=out["sent"][0])
    assert response.status_code == 200, response.text
    resolve_stack(game)
    assert sorted(card.name for card in game.players[1].exile) == ["Lightning Bolt", "Shock"]
    assert [card.name for card in game.players[1].graveyard] == ["Grizzly Bears"]


@needs_node
def test_name_no_target_is_an_empty_list():
    sid, game = _session()
    out = run_app_js(
        _FUNCTIONS,
        """
        show();
        steps.buttons.find((b) => b.id === "triggerGraveyardNoneBtn").click();
        return sent;
        """,
        {"state": _state(sid)},
        prelude=_PAGE,
    )
    assert out == [{
        "seat": 0, "action": "trigger_target_confirm", "target_seat": 0, "graveyard_indices": [],
    }]
    response = client.post(f"/api/sessions/{sid}/action", json=out[0])
    assert response.status_code == 200, response.text
    resolve_stack(game)
    assert game.players[1].exile == [] and len(game.players[1].graveyard) == 3


def test_the_panel_routes_a_several_graveyard_prompt_to_the_picker():
    panel = app_js_function_body("applyTriggerTargetPrompt")
    assert "if (triggerNamesSeveralGraveyardCards(info)) {" in panel
    assert panel.index("triggerNamesSeveralGraveyardCards(info)") < panel.index("data-trigger-graveyard=")
