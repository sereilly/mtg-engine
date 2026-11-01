"""An "as it enters" choice, from the client's side (CR 614.12a).

Found in Legions' Phase 5: while a person's Ward Sliver colour prompt was open,
every Sliver showed "Protection from red", the engine's provisional default,
and Canopy Crawler sat on the board as a settled 2/2 while its amplify reveal
was still open. C1 built the wire half: the battlefield is sent as it reads
before any entering permanent's choice, and the entering permanent carries
``entering: true`` (the key is absent otherwise). This is the client half:

1. **An entering permanent is drawn as arriving**: its printed card ghosted
   under an ENTERING ribbon, with no keyword band, P/T or counter badges.
2. **A person's entry prompts open with nothing chosen.** ``enter_choice`` used
   to pre-select ``default_color``, ``default_creature_type``,
   ``default_land_type(s)`` and ``default_chosen_card_name``, which are what an
   AI seat takes; the prompt now starts empty and refuses to send until each
   field holds something. ``entry_reveal`` (where "Reveal nothing" is a real
   answer) and ``number_choice`` already opened empty, and are pinned here.

Driven in a browser on port 8075 (``scratch/lgn/p5``).
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine.models import Permanent
from tests.helpers import app_js_function_body, run_app_js
from web.app import app, store
from web.runtime import CARD_BY_NAME
from web.state_view import build_state

client = TestClient(app)
STATIC = Path(__file__).resolve().parents[2] / "web" / "static"

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)


def _card(name: str):
    return CARD_BY_NAME[name.casefold()]


def _table(hand: list[str], board: list[str] = ()):
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_human", "host_name": "Alice", "guest_name": "Bob",
              "host_colors": 2, "guest_colors": 2, "seed": 6114},
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Bob"})
    session = store.get(sid)
    session.pregame_phase = None
    game = session.game
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    for player in game.players:
        player.hand[:] = []
    game.remove_all_from_battlefield(list(game.all_permanents()))
    game.stack.clear()
    for name in board:
        permanent = Permanent(card=_card(name))
        permanent.metadata["summoning_sickness_turn"] = -99
        game.players[0].battlefield.append(permanent)
    game._sync_control()
    game._recompute_continuous_effects()
    game.players[0].hand[:] = [_card(name) for name in hand]
    game.active_player_index = session.current_turn = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", "precombat_main"
    game.start_priority_window(0)
    return sid, session, game


def _open_entry_prompt(sid: str, name: str) -> None:
    cast = client.post(f"/api/sessions/{sid}/action",
                       json={"seat": 0, "action": "cast", "card_name": name})
    assert cast.status_code == 200, cast.text
    passed = client.post(f"/api/sessions/{sid}/action",
                         json={"seat": 0, "action": "pass_priority"})
    assert passed.status_code == 200, passed.text
    passed = client.post(f"/api/sessions/{sid}/action",
                         json={"seat": 1, "action": "pass_priority"})
    assert passed.status_code == 200, passed.text


def _on_board(state: dict, name: str) -> dict:
    return next(p for p in state["players"][0]["battlefield"] if p["name"] == name)


# --- 1. an entering permanent is drawn as arriving ----------------------------

#: The whole canvas file, evaluated in the global scope (it declares and never
#: touches the page as it loads), its card face drawn into a context that
#: records every word it writes.
_DRAW_PRELUDE = r"""
(0, eval)(src + "\n;globalThis.BattlefieldCanvas = BattlefieldCanvas;");
function recordingContext() {
  const words = [];
  const ctx = new Proxy({ words, globalAlpha: 1 }, {
    get(target, key) {
      if (key in target) return target[key];
      if (key === "fillText") return (text) => words.push(String(text));
      if (key === "measureText") return (text) => ({ width: String(text).length * 5 });
      if (key === "createLinearGradient") return () => ({ addColorStop() {} });
      return () => {};
    },
    set(target, key, value) { target[key] = value; return true; },
  });
  return ctx;
}
function draw(card) {
  const canvas = Object.create(BattlefieldCanvas.prototype);
  canvas.zoom = 1;
  canvas.reducedMotion = true;
  canvas.theme = {};
  canvas._loadImage = () => null;
  const ctx = recordingContext();
  canvas._drawCardFace(ctx, 0, 0, 100, 140, card, {}, null);
  return ctx.words;
}
"""

_DRAW_HELPERS: list[str] = []


@needs_node
def test_an_entering_permanent_is_drawn_arriving_in_both_seats():
    """Feral Throwback cast from a person's hand with a Beast to reveal: while
    the reveal is open both seats are sent it ``entering``, and the canvas
    draws it ENTERING with none of its badges; once revealed it is a settled
    5/5 with "Provoke" and "+1/+1 ×2"."""
    sid, session, game = _table(["Feral Throwback", "Krosan Vorine"])
    _open_entry_prompt(sid, "Feral Throwback")
    assert game.waiting_prompt() is not None and game.waiting_prompt().kind == "entry_reveal"
    sent = {viewer: _on_board(build_state(session, viewer), "Feral Throwback") for viewer in (0, 1)}
    assert all(card.get("entering") is True for card in sent.values()), sent

    words = run_app_js(
        _DRAW_HELPERS, "return { mine: draw(INPUT.mine), theirs: draw(INPUT.theirs) };",
        {"mine": sent[0], "theirs": sent[1]}, prelude=_DRAW_PRELUDE,
        scripts=("battlefield-canvas.js",),
    )
    for viewer, written in words.items():
        assert "ENTERING" in written, (viewer, written)
        assert not any("Provoke" in w or "+1/+1" in w or "/" in w for w in written), (viewer, written)

    revealed = client.post(f"/api/sessions/{sid}/action",
                           json={"seat": 0, "action": "entry_reveal_confirm",
                                 "hand_indices": [0]})
    assert revealed.status_code == 200, revealed.text
    settled = _on_board(build_state(session, 1), "Feral Throwback")
    assert "entering" not in settled
    written = run_app_js(_DRAW_HELPERS, "return draw(INPUT.card);", {"card": settled},
                         prelude=_DRAW_PRELUDE, scripts=("battlefield-canvas.js",))
    assert "ENTERING" not in written
    assert "Provoke" in written and any(w.startswith("+1/+1") for w in written), written


def test_a_flyer_entering_does_not_float():
    """A flying creature bobs off the table once it is there; one still
    entering stays put under its ribbon."""
    canvas = (STATIC / "battlefield-canvas.js").read_text(encoding="utf-8")
    assert "if (_isFlyer(card) && !_isEntering(card)) {" in canvas


# --- 2. a person's entry prompts open with nothing chosen -----------------------

_CHOICE_PRELUDE = r"""
var seat = 0;
let enterChoiceSelectedColor = null;
let enterChoiceDraft = null;
const ENTER_CHOICE_LAND_LETTERS = { plains: "W", island: "U", swamp: "B", mountain: "R", forest: "G" };
function escapeHtml(s) { return String(s); }
"""


@needs_node
def test_ward_slivers_colour_prompt_opens_with_no_colour_and_refuses_to_send_without_one():
    sid, session, game = _table(["Ward Sliver"], board=["Plated Sliver"])
    _open_entry_prompt(sid, "Ward Sliver")
    states = {viewer: build_state(session, viewer) for viewer in (0, 1)}
    info = states[0]["enter_choice"]
    assert info["needs_color"] and info.get("default_color"), info  # the AI's default stays on the wire
    for viewer, state in states.items():
        for name in ("Ward Sliver", "Plated Sliver"):
            keywords = [str(k).lower() for k in _on_board(state, name).get("keywords", [])]
            assert not any("protection" in k for k in keywords), (viewer, name, keywords)
        assert _on_board(state, "Ward Sliver").get("entering") is True

    seen = run_app_js(
        ["enterChoiceDraftFor", "enterChoiceMissing", "enterChoicePayload", "enterChoiceSelectHtml"],
        r"""
        const info = INPUT.info;
        const opened = { missing: enterChoiceMissing(info), color: enterChoiceSelectedColor };
        enterChoiceSelectedColor = "U";
        const chosen = { missing: enterChoiceMissing(info), payload: enterChoicePayload(info) };
        const select = enterChoiceSelectHtml("creatureType", ["goblin", "sliver"], "");
        return { opened, chosen, select };
        """,
        {"info": info}, prelude=_CHOICE_PRELUDE,
    )
    assert seen["opened"] == {"missing": ["a color"], "color": None}
    assert seen["chosen"]["missing"] == []
    assert seen["chosen"]["payload"]["mana_color"] == "U"
    # A select opens on its blank entry, not the first type or the AI's.
    assert seen["select"].index('<option value="" selected disabled>') < seen["select"].index("goblin")

    answered = client.post(f"/api/sessions/{sid}/action",
                           json={**seen["chosen"]["payload"]})
    assert answered.status_code == 200, answered.text
    plated = _on_board(build_state(session, 1), "Plated Sliver")
    assert any("protection" in str(k).lower() for k in plated.get("keywords", [])), plated


@needs_node
def test_every_enter_choice_field_starts_empty():
    """Each shape the prompt has (a colour, a creature type, a land type, two
    land types, a card name), opened with the AI's defaults on the payload."""
    info = {
        "card_name": "Anything", "needs_color": True, "needs_creature_type": True,
        "needs_land_type": True, "needs_land_types": True, "needs_card_name": True,
        "colors": ["W", "U", "B", "R", "G"], "creature_types": ["goblin", "sliver"],
        "chosen_land_types": ["swamp", "desert"], "land_types": ["forest", "island"],
        "default_color": "R", "default_creature_type": "goblin", "default_land_type": "swamp",
        "default_land_types": ["forest", "island"], "default_chosen_card_name": "Hill Giant",
    }
    seen = run_app_js(
        ["enterChoiceDraftFor", "enterChoiceMissing"],
        "const draft = enterChoiceDraftFor(INPUT.info); "
        "return { draft: { ...draft, key: undefined }, missing: enterChoiceMissing(INPUT.info) };",
        {"info": info}, prelude=_CHOICE_PRELUDE,
    )
    assert seen["draft"] == {
        "cardName": "", "creatureType": "", "landType": "", "landTypeFirst": "", "landTypeSecond": "",
    }
    assert seen["missing"] == [
        "a color", "a creature type", "a land type", "two basic land types", "a card name",
    ]


def test_the_prompts_read_no_ai_default_and_confirm_waits_for_an_answer():
    panel = app_js_function_body("applyEnterChoicePrompt")
    answers = "".join(app_js_function_body(name) for name in (
        "enterChoiceDraftFor", "enterChoicePayload", "applyEnterChoicePrompt",
    ))
    assert "info.default_" not in answers
    assert 'data-enter-confirm="1" disabled' in panel
    assert "enterChoiceMissing(info)" in panel
    # The opponent's pill sends the fields with it, so it waits for them too.
    assert "enterChoiceMissing(enterChoiceInfo)" in app_js_function_body("getPromptBoardTargeting")
    # Amplify opens on no card revealed, "Reveal nothing" being an answer; a
    # number is one click per number, none of them the AI's.
    reveal = app_js_function_body("applyEntryRevealPrompt")
    assert "entryRevealSelected = [];" in reveal and '"Reveal nothing"' in reveal
    assert "default" not in app_js_function_body("applyNumberChoicePrompt").replace(
        "defaults", "")
