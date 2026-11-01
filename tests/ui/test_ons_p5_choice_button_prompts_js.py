"""Every prompt drawn by ``applyChoiceButtonPrompt`` renders its buttons.

Found in Onslaught's post-promotion pass: Meddle resolved and its "Choose a new
target" panel showed no buttons, with "Cannot convert undefined or null to
object" in the hint. The shared renderer destructured ``{ ..., valueOf }`` from
its options; a caller that did not pass one got ``Object.prototype.valueOf``
(an inherited property is still read by destructuring), and calling it unbound
threw on the first option. Every caller but Mind Bend's relied on that default
— Meddle's retarget, the player choice ("an opponent chooses", Callous
Oppressor), the graveyard-pile choice (Entrails Feaster), the library end and
the cast choice — so each was a prompt a person could not answer, for two
months, while the text-level tests passed over it.

Each renderer is run here on the payload its prompt sends (the retarget one as
the server sent it for Meddle in the browser) with the page's elements stubbed,
and must produce one button per option carrying the value the action expects.
"""
from __future__ import annotations

import pytest

from tests.helpers import run_app_js

_PRELUDE = r"""
var seat = 0;
const SENT = [];
function makeEl(id) {
  return {
    id, textContent: "", disabled: false, _html: "",
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    set innerHTML(v) { this._html = v; }, get innerHTML() { return this._html; },
    querySelectorAll() { return []; },
  };
}
const ELS = {};
function q(id) { if (!ELS[id]) ELS[id] = makeEl(id); return ELS[id]; }
function escapeHtml(s) { return String(s); }
async function sendAction(body) { SENT.push(body); }
"""

_BODY = r"""
const fn = globalThis[INPUT.renderer] || eval(INPUT.renderer);
fn(INPUT.info);
const html = q("promptSteps").innerHTML;
const values = [...html.matchAll(/data-choice-value="([^"]*)"/g)].map((m) => m[1]);
return { title: q("promptTitle").textContent, values };
"""

_CASES = [
    (
        "applyRetargetChoicePrompt",
        # As the server sent it while Meddle resolved over a Shock.
        {"card_name": "Meddle", "prompt": "Choose the new target for Shock.", "options": [
            {"index": 0, "name": "Wirewood Elf", "kind": "permanent"},
            {"index": 1, "name": "Exalted Angel", "kind": "permanent"},
            {"index": 2, "name": "Elvish Pioneer", "kind": "permanent"},
            {"index": 3, "name": "Face-down creature", "kind": "permanent"},
        ]},
        ["0", "1", "2", "3"],
    ),
    (
        "applyPlayerChoicePrompt",
        {"card_name": "Callous Oppressor", "prompt": "Choose an opponent.", "options": [
            {"seat": 1, "name": "Bob"}, {"seat": 2, "name": "Cara"},
        ]},
        ["1", "2"],
    ),
    (
        "applyGraveyardPilePrompt",
        {"card_name": "Entrails Feaster", "prompt": "Choose a graveyard.", "options": [
            {"seat": 0, "name": "Player 1", "legal_cards": 1},
            {"seat": 1, "name": "AI", "legal_cards": 2},
        ]},
        ["0", "1"],
    ),
    (
        "applyCastChoicePrompt",
        {"card_name": "Backdraft", "prompt": "Choose a spell.", "options": [
            {"index": 0, "name": "Shock", "damage": 2},
        ]},
        ["0"],
    ),
    (
        "applyLibraryEndPrompt",
        {"card_name": "Hinder", "moved_name": "Shock", "owner_name": "AI"},
        ["0", "1"],
    ),
    (
        "applyTextChangeVocabularyPrompt",
        {"card_name": "Mind Bend", "permanent_name": "Cover of Darkness", "options": [
            {"from": "black", "to": "white", "mode": "color_word"},
        ]},
        ["color_word"],
    ),
]


@pytest.mark.parametrize("renderer, info, values", _CASES, ids=[case[0] for case in _CASES])
def test_a_choice_button_prompt_renders_one_button_per_option(renderer, info, values):
    out = run_app_js(
        ["applyChoiceButtonPrompt", renderer],
        _BODY, {"renderer": renderer, "info": info}, prelude=_PRELUDE,
    )
    assert out["values"] == values, out
    assert out["title"], out
