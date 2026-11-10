"""Fatespinner's choice says what is chosen in its heading, not "Choose one".

"At the beginning of each opponent's upkeep, that player chooses draw step,
main phase, or combat phase. The player skips each instance of the chosen step
or phase this turn." The Mirrodin client round put the question in the body
(``question``: "Choose the step or phase you skip this turn.") and whose
ability asks it (``controller_name``); the panel's heading still read "Choose
one". The server now sends ``title`` beside ``question`` and the heading reads
"Fatespinner — skip a step or phase", in the shape of the other choice
prompts' headings ("Shared Fate — exile instead of drawing"). A modal ability
the server says nothing more about keeps "Choose one" — the printed form.

Driven in a browser: Fatespinner on the AI's side, the person's upkeep.
"""
from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from engine.models import Permanent
from tests.helpers import run_app_js
from web.app import app, store

client = TestClient(app)

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)

_DOM_PRELUDE = """
let seat = 0, currentState = null;
const els = {};
function q(id) {
  if (!els[id]) {
    els[id] = { id, textContent: "", innerHTML: "", disabled: false,
      classList: { add() {}, remove() {}, toggle() {} },
      querySelectorAll() { return []; }, querySelector() { return null; } };
  }
  return els[id];
}
function escapeHtml(value) { return String(value); }
async function sendAction() {}
"""


def _fatespinner_upkeep(set_pool):
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 4242,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    session.pregame_phase = None
    game = session.game
    for player in game.players:
        player.battlefield = []
        player.hand = []
    game.interactive_seats = set(range(len(game.players)))
    session.current_turn = 0
    game.active_player_index = 0
    spinner = Permanent(card=set_pool("MRD")["Fatespinner"])
    game._put_permanent_onto_battlefield(1, spinner, None)
    game._sync_control()
    game.current_phase = "beginning"
    game.current_turn_phase, game.current_step = "beginning", "upkeep"
    game.resolve_upkeep(0)
    response = client.get(f"/api/sessions/{sid}/state?seat=0")
    assert response.status_code == 200, response.text
    return response.json()


def test_the_skip_choice_carries_its_title(set_pool):
    info = _fatespinner_upkeep(set_pool)["mode_choice"]
    assert info is not None
    assert info["card_name"] == "Fatespinner"
    assert info["title"] == "skip a step or phase"
    assert info["question"] == "Choose the step or phase you skip this turn."


@needs_node
def test_the_panel_heading_says_what_is_chosen(set_pool):
    info = _fatespinner_upkeep(set_pool)["mode_choice"]
    out = run_app_js(
        ["applyModeChoicePrompt"],
        """
        applyModeChoicePrompt(INPUT.info);
        const skip = { title: q("promptTitle").textContent, body: q("promptBody").textContent };
        applyModeChoicePrompt({ card_name: "Trufflesnout", modes: [{ index: 0, label: "Gain 4 life." }] });
        return { skip, modal: q("promptTitle").textContent };
        """,
        {"info": info},
        prelude=_DOM_PRELUDE,
    )
    assert out["skip"]["title"] == "Fatespinner — skip a step or phase"
    assert out["skip"]["body"] == "Joiner's Fatespinner: Choose the step or phase you skip this turn."
    assert out["modal"] == "Choose one"
