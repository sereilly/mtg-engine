"""Legions' post-promotion client round: five things a person met in the browser.

1. **An offer says what saying yes costs.** Dermoplasm's turn-up offer read
   "you may put a creature card with a morph ability from your hand onto the
   battlefield face up." and stopped: the next sentence, "If you do, return
   this creature to its owner's hand.", was not shown. ``offer_wording`` now
   carries the "If you do, …" / "Otherwise, …" sentences after the offer.
2. **The stack-target hint names what each object is.** Willbender's "target
   spell or ability" listed a Goblin Dynamo *ability* among the "Spells it can
   target"; the hint now reads the served stack item (``type``,
   ``is_triggered``).
3. **Rail offers and counter badges cover nothing.** Two turn-up offers ran
   out of the phase rail over the graveyard pile, and a "+1/+1 ×4" badge sat
   on Feral Throwback's "Provoke" band.
4. **A top-right hint lasts as long as its moment.** "Declare attackers by
   clicking creatures…" stayed into the next main phase and the opponent's
   turn, "Auto-passing priority until your turn ends." into the opponent's
   turn; each hint now carries the moment it describes and the default tip
   comes back when that moment has passed.
5. **"Play Again" is the next game of a match (CR 103.1).** Against the AI it
   was a fresh session with a fresh coin flip; now the previous game's loser
   chooses — a person is asked, the AI plays first — and after a draw the seat
   that chose last time chooses again.

Each was driven in a browser on port 8075 (``scratch/lgn/p5``).
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.face_down import face_down_card
from engine.models import Permanent
from tests.helpers import run_app_js
from web.app import app, store
from web.prompt_values import offer_wording

client = TestClient(app)
STATIC = Path(__file__).resolve().parents[2] / "web" / "static"

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)


# --- 1. an offer and what it costs -----------------------------------------

class _Card:
    def __init__(self, text: str):
        self.oracle_text = text


class _Context:
    def __init__(self, text: str, line: str = ""):
        self.card = _Card(text)
        self.ability_text = line


def test_an_offer_carries_the_sentence_that_says_what_yes_costs(set_pool):
    dermoplasm = set_pool("LGN")["Dermoplasm"]
    wording = offer_wording({"_context": _Context(dermoplasm.oracle_text)})
    assert wording["card_text"] == (
        "When this creature is turned face up, you may put a creature card with a "
        "morph ability from your hand onto the battlefield face up. If you do, "
        "return this creature to its owner's hand."
    )
    # "…unless…": the halves of the offer are still the offer's own sentence.
    sink = offer_wording({"_context": _Context(
        "Counter target spell unless its controller pays {X}. If that player "
        "doesn't, they tap all lands with mana abilities they control and lose "
        "all unspent mana."
    )})
    assert sink["card_text"].endswith("lose all unspent mana.")
    assert sink["decline_text"] == "Counter target spell"
    assert sink["accept_text"] == "its controller pays {X}"
    # A sentence that is not about the answer is not swept in.
    plain = offer_wording({"_context": _Context(
        "Create a 2/2 Weird. Then you may return an instant or sorcery card "
        "from your graveyard to your hand. Exile this spell."
    )})
    assert plain == {
        "card_text": "Then you may return an instant or sorcery card from your graveyard to your hand.",
    }


def _hvh(seed: int = 5115):
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": seed,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    session.pregame_phase = None
    game = session.game
    game.interactive_seats = {0, 1}
    game.enforce_mana_costs = False
    for player in game.players:
        player.battlefield.clear()
        player.hand.clear()
        player.graveyard.clear()
    game.stack.clear()
    game.pending_choices.clear()
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, session, game


def _post(sid, body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def _state(sid, seat):
    response = client.get(f"/api/sessions/{sid}/state", params={"seat": seat})
    assert response.status_code == 200, response.text
    return response.json()


def test_dermoplasms_offer_reaches_its_seat_with_the_bounce_in_it(set_pool):
    sid, _session, game = _hvh()
    lgn = set_pool("LGN")
    dermoplasm = Permanent(card=face_down_card(lgn["Dermoplasm"]))
    dermoplasm.metadata["summoning_sickness_turn"] = -99
    game.players[0].battlefield.append(dermoplasm)
    game._sync_control()
    game.players[0].hand.append(lgn["Willbender"])
    game.players[0].mana_pool["U"] += 4  # Morph {2}{U}{U}
    turned = _post(sid, {
        "seat": 0, "action": "special_action",
        "permanent_id": dermoplasm.permanent_id, "special_action_kind": "turn_face_up",
    })
    assert turned.status_code == 200, turned.text
    for passer in (0, 1, 0, 1):
        if game.pending_choice_of("optional_pay", 0) is not None:
            break
        _post(sid, {"seat": passer, "action": "pass_priority"})
    (offer,) = _state(sid, 0)["optional_pay"]["pending"]
    assert offer["card_name"] == "Dermoplasm"
    assert offer["card_text"].endswith("If you do, return this creature to its owner's hand.")


# --- 2. the stack-target hint -------------------------------------------------

_PANEL_PRELUDE = r"""
var seat = 0;
let currentState = INPUT.state;
function makeEl(id) {
  return {
    id, textContent: "", disabled: false, _html: "", onclick: null,
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    set innerHTML(v) { this._html = v; }, get innerHTML() { return this._html; },
    querySelectorAll() { return []; },
  };
}
const ELS = {};
function q(id) { if (!ELS[id]) ELS[id] = makeEl(id); return ELS[id]; }
function escapeHtml(s) { return String(s); }
function submitPromptAction() {}
"""

_PANEL_BODY = r"""
applyTriggerTargetPrompt(INPUT.info);
return q("promptSteps").innerHTML.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
"""

_PANEL_FUNCTIONS = [
    "applyTriggerTargetPrompt", "stackObjectNoun", "stackObjectsNoun",
    "triggerNamesSeveralTargets", "triggerNamesSeveralGraveyardCards",
    "triggerTargetForAnotherText", "graveyardOwnerLabel",
]


def _stack_state(*items):
    return {
        "players": [{"name": "Player 2"}, {"name": "AI"}],
        "stack": [dict(item) for item in items],
    }


@needs_node
def test_the_stack_hint_names_an_ability_as_an_ability():
    # Willbender's trigger over a Goblin Dynamo ability (top) and a Shock.
    state = _stack_state(
        {"type": "ability", "is_triggered": False, "label": "Goblin Dynamo ability"},
        {"type": "spell", "is_triggered": False, "label": "Shock"},
    )
    info = {"card_name": "Willbender", "candidates": [
        {"kind": "stack", "stack_index": 0, "seat": 0, "name": "Goblin Dynamo"},
        {"kind": "stack", "stack_index": 1, "seat": 0, "name": "Shock"},
    ]}
    text = run_app_js(_PANEL_FUNCTIONS, _PANEL_BODY, {"state": state, "info": info}, prelude=_PANEL_PRELUDE)
    assert "click a glowing spell or ability on the stack" in text
    assert "On the stack it can target: Goblin Dynamo (Player 2's activated ability), " \
           "Shock (Player 2's spell)." in text
    assert "Spells it can target" not in text


@needs_node
def test_a_spell_only_offer_reads_as_it_did():
    state = _stack_state(
        {"type": "ability", "is_triggered": True, "label": "Willbender ability"},
        {"type": "spell", "is_triggered": False, "label": "Shock"},
    )
    info = {"card_name": "Mystic Snake", "candidates": [
        {"kind": "stack", "stack_index": 1, "seat": 1, "name": "Shock"},
    ]}
    text = run_app_js(_PANEL_FUNCTIONS, _PANEL_BODY, {"state": state, "info": info}, prelude=_PANEL_PRELUDE)
    assert "click a glowing spell on the stack" in text
    assert "Spells it can target: Shock (AI)." in text


@needs_node
def test_a_triggered_ability_is_named_triggered():
    state = _stack_state({"type": "ability", "is_triggered": True, "label": "Brood Sliver ability"})
    info = {"card_name": "Willbender", "candidates": [
        {"kind": "stack", "stack_index": 0, "seat": 1, "name": "Brood Sliver"},
    ]}
    text = run_app_js(_PANEL_FUNCTIONS, _PANEL_BODY, {"state": state, "info": info}, prelude=_PANEL_PRELUDE)
    assert "click a glowing ability on the stack" in text
    assert "Brood Sliver (AI's triggered ability)" in text


# --- 3. rail offers and counter badges ---------------------------------------

def _css_rule(css: str, selector: str) -> str:
    rule = re.search(re.escape(selector) + r" \{([^}]*)\}", css)
    assert rule, f"no rule for {selector}"
    return rule.group(1)


def test_rail_offers_stack_in_the_rails_column():
    """The three offer lists sit in one column inside the rail; it scrolls and
    gives way, and the phase chips keep their own height, so an offer neither
    runs out of the rail's 112px nor squeezes a step out of sight (at 1280x720
    four turn-up offers had hidden AT through CL)."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    controls = html[html.index('<div class="phase-controls">'):html.index('id="undoBtn"')]
    offers = controls[controls.index('<div class="rail-offers">'):]
    for list_id in ("specialActions", "handAbilities", "graveyardAbilities"):
        assert f'id="{list_id}"' in offers, list_id

    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    column = _css_rule(css, ".rail-offers")
    assert "flex-direction: column" in column
    assert "overflow-y: auto" in column
    assert "min-height: 0" in column
    each = _css_rule(css, ".rail-offers .special-actions")
    assert "flex-direction: column" in each
    assert "display: none" in _css_rule(css, ".rail-offers .special-actions.hidden")
    assert "min-height: min-content" in _css_rule(css, ".phase-rail")
    controls_rule = _css_rule(css, ".phase-controls")
    assert "flex-shrink: 1" in controls_rule and "min-height: 0" in controls_rule


@needs_node
def test_the_keyword_band_sits_above_every_counter_badge():
    """The band's reserve is read off the same count the badge loop draws, and
    counters stack 15px apart (13px badges, 2px gaps) above the P/T badge."""
    counts = run_app_js(
        ["_counterBadgeCount"],
        "return INPUT.cards.map((card) => _counterBadgeCount(card));",
        {"cards": [
            {"counters": {"+1/+1": 4}},
            {"counters": {"+1/+1": 2, "-1/-1": 0, "corpse": 1}},
            {"counters": {}, "corpse_counters": 2},
            {},
        ]},
        scripts=("battlefield-canvas.js",),
    )
    assert counts == [1, 2, 1, 0]
    canvas = (STATIC / "battlefield-canvas.js").read_text(encoding="utf-8")
    assert "const reserveBottom = (isCreatureCard ? 16 : 3) + counterSlots * 15;" in canvas
    assert ": y + h - bh - 2 - (i + counterBaseSlot) * (bh + 2);" in canvas
    assert "const bh = 13;" in canvas


# --- 4. a hint's moment ------------------------------------------------------

def _default_hint() -> str:
    source = (STATIC / "app.js").read_text(encoding="utf-8")
    found = re.search(r'^const DEFAULT_ACTION_HINT = "([^"]+)";', source, re.MULTILINE)
    assert found, "app.js no longer names its default tip"
    return found.group(1)


_HINT_PRELUDE = r"""
let currentState = null;
let actionHintMoment = null;
const DEFAULT_ACTION_HINT = INPUT.defaultHint;
const EL = { textContent: "", style: {} };
function q(id) { return EL; }
const document = { querySelector() { return null; } };
"""

_HINT_BODY = r"""
const seen = [];
function at(turn, step, active = 0) {
  return { turn_number: turn, current_turn: active, current_turn_phase: step, current_step: step };
}
function show(state) { currentState = state; expireStaleActionHint(state); seen.push(EL.textContent); }
show(at(3, "declare_attackers"));
updateActionHint("Declare attackers by clicking creatures, or use Alpha Strike to toggle all valid attackers, then press OK.");
show(at(3, "declare_attackers"));          // the same step: still true
show(at(3, "postcombat_main"));            // the step has passed
updateActionHint("Auto-passing priority until your turn ends.", false, { until: "turn" });
show(at(3, "end"));                        // the same turn
show(at(4, "upkeep", 1));                  // the opponent's turn
updateActionHint("Passed priority.");
show(at(4, "upkeep", 1));
show(at(4, "draw", 1));
// A rematch opens on the turn, seat and step a game can end on, so the
// pregame is a moment of its own: a hint from the last game goes as it opens,
// and one written during it lasts until the next game's first turn.
show(at(1, "precombat_main"));
updateActionHint("Debug: added Fireball to your hand.");
const pregame = (phase) => ({ ...at(1, "precombat_main"), pregame: { phase } });
show(pregame("coin_flip"));
updateActionHint("Choose cards to put on the bottom.");
show(pregame("mulligan"));
show(at(1, "precombat_main"));
show(at(5, "untap"));                      // the default tip never expires
return seen;
"""


@needs_node
def test_a_hint_gives_way_to_the_default_tip_once_its_moment_has_passed():
    default = _default_hint()
    seen = run_app_js(
        ["updateActionHint", "actionHintMomentKey", "expireStaleActionHint"],
        _HINT_BODY, {"defaultHint": default}, prelude=_HINT_PRELUDE,
    )
    declare = "Declare attackers by clicking creatures, or use Alpha Strike to toggle all valid attackers, then press OK."
    assert seen == [
        "",
        declare,
        default,
        "Auto-passing priority until your turn ends.",
        default,
        "Passed priority.",
        default,
        default,
        default,                                  # the last game's hint, at the coin flip
        "Choose cards to put on the bottom.",     # the pregame's own hint, in the pregame
        default,                                  # the next game's first turn
        default,
    ]


# --- 5. the next game of a match ---------------------------------------------

def _finished_vs_ai(seed: int, loser: int | None):
    created = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "Solo", "host_colors": 2, "guest_colors": 2,
        "seed": seed, "enable_pregame": True,
    }).json()
    sid = created["session_id"]
    session = store.get(sid)
    flipped = session.coin_flip_winner
    if loser is None:
        session.game.players[0].life = 0
        session.game.players[1].life = 0
    else:
        session.game.players[loser].life = 0
    finished = _state(sid, 0)
    assert finished["status"] == "finished"
    return sid, session, flipped


def test_the_human_who_lost_to_the_ai_is_asked_who_plays_first():
    sid, _session, _flipped = _finished_vs_ai(7310, loser=0)
    again = client.post(f"/api/sessions/{sid}/rematch", json={"seat": 0})
    assert again.status_code == 200, again.text
    pregame = again.json()["pregame"]
    assert pregame["phase"] == "coin_flip"
    assert pregame["winner_seat"] == 0 and pregame["is_my_turn"] is True
    assert pregame["choice_reason"] == "loser" and pregame["is_loser_choice"] is True
    chosen = _post(sid, {"seat": 0, "action": "coin_flip_choose", "hand_index": 1})
    assert chosen.status_code == 200, chosen.text
    assert store.get(sid).pregame_starting_player == 1


def test_the_ai_that_lost_chooses_at_once_and_plays_first():
    sid, session, _flipped = _finished_vs_ai(7311, loser=1)
    again = client.post(f"/api/sessions/{sid}/rematch", json={"seat": 0})
    assert again.status_code == 200, again.text
    assert again.json()["pregame"]["phase"] != "coin_flip"
    assert session.pregame_starting_player == 1
    log = session.game.log
    assert "AI lost the last game and chooses who plays first" in log
    assert "AI chooses to go first" in log
    assert not any(line.startswith("Coin flip:") for line in log)


def test_after_a_draw_the_seat_that_chose_last_time_chooses_again():
    for seed in range(7312, 7340):
        sid, session, flipped = _finished_vs_ai(seed, loser=None)
        if flipped == 0:
            break
    else:
        pytest.fail("no seed gave the human the first flip")
    assert _state(sid, 0)["winner"] == -1
    again = client.post(f"/api/sessions/{sid}/rematch", json={"seat": 0})
    assert again.status_code == 200, again.text
    pregame = again.json()["pregame"]
    assert pregame["winner_seat"] == 0 and pregame["is_my_turn"] is True
    assert pregame["choice_reason"] == "draw" and pregame["is_loser_choice"] is False
    assert "The last game was a draw: Solo chose who played first then and chooses again" in session.game.log


_SENDER_KEYS = (
    "aiAutoStepRequestedStateKey", "autoPassTurnEndRequestedStateKey",
    "autoPassPriorityRequestedStateKey", "autoPassDisabledPhaseRequestedStateKey",
    "autoCombatDeclareRequestedStateKey",
)


@needs_node
def test_a_finished_game_forgets_the_states_its_senders_acted_on(monkeypatch):
    """Two rematches in a row that the AI opens reach the same first state —
    turn 1, the AI's main phase, an empty stack, a log of the same length — so
    the client took the second game's first AI step for one it had already
    sent, and the game sat at "Waiting for AI…" (driven on port 8075). Every
    sender's remembered key is forgotten as a game ends."""
    import web.session_store as session_store

    # The same deal each time, so the openings differ only where the AI's
    # keep-or-mulligan does — what a person met by chance on the second try.
    monkeypatch.setattr(session_store.secrets, "randbits", lambda bits: 4242)
    sid, session, _flipped = _finished_vs_ai(7350, loser=1)
    keys, logs = [], []
    for _ in range(6):
        again = client.post(f"/api/sessions/{sid}/rematch", json={"seat": 0})
        assert again.status_code == 200, again.text
        kept = _post(sid, {"seat": 0, "action": "mulligan_keep"})
        assert kept.status_code == 200, kept.text
        opened = _state(sid, 0)
        assert opened["current_turn"] == 1 and not opened["pregame"]
        keys.append(run_app_js(
            ["getAiStepStateKey"], "return getAiStepStateKey(INPUT.state);", {"state": opened},
        ))
        logs.append(opened["log"])
        session.game.players[1].life = 0
        assert _state(sid, 0)["status"] == "finished"
        if len(keys) > 1 and keys[-1] == keys[-2]:
            break
    else:
        pytest.fail(f"no two openings in a row collided; the test lost its subject: {logs}")

    prelude = "".join(f"let {name} = INPUT.stale;\n" for name in _SENDER_KEYS)
    prelude += "let autoPassTurnEndEnabled = true;\nlet autoPassMode = 'self';\n"
    after = run_app_js(
        ["forgetLastGamesRequests"],
        "forgetLastGamesRequests(); return [" + ", ".join(_SENDER_KEYS)
        + ", autoPassTurnEndEnabled, autoPassMode];",
        {"stale": keys[-1]}, prelude=prelude,
    )
    assert after == [""] * len(_SENDER_KEYS) + [False, None]

    source = (STATIC / "app.js").read_text(encoding="utf-8")
    render = source[source.index("\nfunction renderState("):]
    boundary = render.index("if (gameIsOver(prevStateForDiscard) && state && !gameIsOver(state)) forgetLastGamesRequests();")
    assert boundary < render.index("\n  currentState = state;")


_FLIP_PRELUDE = r"""
var seat = INPUT.seat;
function makeEl(id) {
  return {
    id, textContent: "", disabled: false, _html: "",
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    set innerHTML(v) { this._html = v; }, get innerHTML() { return this._html; },
    addEventListener() {},
  };
}
const ELS = {};
function q(id) { if (!ELS[id]) ELS[id] = makeEl(id); return ELS[id]; }
const document = { getElementById: (id) => q(id) };
function escapeHtml(s) { return String(s); }
async function sendAction() {}
"""


@needs_node
@pytest.mark.parametrize("reason, mine, title, body", [
    ("loser", True, "You lost — your call", "You lost the last game, so you choose who plays first."),
    ("draw", True, "A draw — your call again", "The last game was a draw, and you chose who played first in it"),
    ("draw", False, "Choosing who plays first", "The last game was a draw: AI chose who played first in it"),
    ("coin_flip", True, "You won the coin flip!", "Solo won the coin flip."),
])
def test_the_coin_flip_prompt_says_why_this_seat_chooses(reason, mine, title, body):
    info = {
        "phase": "coin_flip", "winner_seat": 0 if mine else 1,
        "winner_name": "Solo" if mine else "AI", "is_my_turn": mine,
        "is_loser_choice": reason == "loser", "choice_reason": reason,
        "waiting_for": None if mine else "AI",
    }
    out = run_app_js(
        ["applyCoinFlipPrompt"],
        'applyCoinFlipPrompt(INPUT.info); return [q("promptTitle").textContent, q("promptBody").textContent];',
        {"info": info, "seat": 0}, prelude=_FLIP_PRELUDE,
    )
    assert out[0] == title
    assert out[1].startswith(body), out
