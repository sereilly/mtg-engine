"""SCG Phase 5's client closer, run for real in bare node.

The verification agent played Scourge in the browser and reported what the
client did wrong. Each item here is a class, and each test runs the client's own
functions, lifted out of ``web/static/app.js``, over payloads the server really
sent. The census tests ask their question of every member of the class:

* **A decision belongs to the seat the payload names.** The cleanup prompt
  used to count the viewer's own hand against a literal seven whenever the
  server's ``cleanup_discard`` was empty. So it drew "Cleanup discard
  required" on the other seat's turn (and would on a turn with no maximum hand
  size). The census runs every ``get*Info`` getter over states that owe this
  viewer nothing, the viewer holding ten cards in every step of either seat's
  turn, and asks each for null.
* **Nothing opens on the engine's provisional default.** ``default_*`` keys
  are what an AI seat takes. A select, an input or a division that opened on
  one made a single click a choice the person never made.
* **The CR 118.9d note says only what the label does not.** A morph's offer
  read "for {3} — {3} in mana in all".
* **A long list scrolls inside the prompt panel.**
* **A permanent's tile shows its art.**
* **A modal dialog's prompt hides the panel behind it.** The panel used to
  fall through to the step's "Main Phase … press OK to pass priority".
* **A cast the pool cannot pay is previewed, never sent.** Every auto-tap cast
  logged a 400 in the console, from the refused cast the dialog was opened on.

What cannot run here is the click and the layout; those were driven in a
browser before and after.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import run_app_js
from tests.ui.js_requests import mask
from web.app import app, store
from web.payment_plan import PAYING_ACTIONS

client = TestClient(app)
_CARDS = {card.name: card for card in load_catalog()}
_STATIC = Path(__file__).resolve().parents[2] / "web" / "static"
_APP_JS = _STATIC / "app.js"

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)


def _source() -> str:
    return _APP_JS.read_text(encoding="utf-8").replace("\r", "")


def _session(board=(), hand=(), opponent_board=()):
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 5150,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    session.pregame_phase = None
    game.enforce_mana_costs = True
    game.players[0].battlefield = []
    game.players[1].battlefield = []
    for seat, names in ((0, board), (1, opponent_board)):
        for name in names:
            permanent = Permanent(card=_CARDS[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
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


def _state(sid, seat=0):
    return client.get(f"/api/sessions/{sid}/state?seat={seat}").json()


# A driver that lifts the named functions *and whatever they reach for*: a
# name the code throws "is not defined" on is grabbed from app.js (a function
# or a top-level binding) and the run starts again, so a census over a hundred
# getters does not have to spell out each one's helpers.
_DEPS_DRIVER = r'''
const fs = require("fs");
const CR = String.fromCharCode(13);
const src = fs.readFileSync(process.argv[2], "utf8").split(CR).join("");
function grabFunction(name) {
  for (const head of ["\nfunction " + name + "(", "\nasync function " + name + "("]) {
    const at = src.indexOf(head);
    if (at >= 0) return src.slice(at, src.indexOf("\n}\n", at) + 2);
  }
  return null;
}
function grabBinding(name) {
  const found = new RegExp("\\n(?:const|let) " + name + "\\b").exec(src);
  if (!found) return null;
  let depth = 0;
  for (let j = found.index + 1; j < src.length; j += 1) {
    const c = src[j];
    if ("([{".includes(c)) depth += 1;
    else if (")]}".includes(c)) depth -= 1;
    else if (c === ";" && depth === 0) return src.slice(found.index + 1, j + 1);
  }
  return null;
}
const INPUT = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const PRELUDE = __PRELUDE__;
const BODY = __BODY__;
const names = __NAMES__;
(async () => {
  for (let attempt = 0; attempt < 400; attempt += 1) {
    const parts = names.map((name) => grabFunction(name) || grabBinding(name));
    const missing = names.filter((_, i) => !parts[i]);
    if (missing.length) throw new Error("app.js defines none of " + missing.join(", "));
    const code = PRELUDE + "\n" + parts.join("\n") + "\nreturn (async () => {" + BODY + "})();";
    try {
      const out = await new Function("INPUT", code)(INPUT);
      process.stdout.write(JSON.stringify({ out, lifted: names.length }));
      return;
    } catch (err) {
      const unknown = /^(\w+) is not defined$/.exec(err && err.message);
      if (unknown && !names.includes(unknown[1])
          && (grabFunction(unknown[1]) || grabBinding(unknown[1]))) {
        names.push(unknown[1]);
        continue;
      }
      throw err;
    }
  }
  throw new Error("dependencies did not settle");
})().catch((err) => { process.stderr.write(String(err && err.stack || err)); process.exit(1); });
'''


def _run_with_deps(names, body, payload=None, *, prelude="", source=None):
    driver = (
        _DEPS_DRIVER
        .replace("__PRELUDE__", json.dumps(prelude))
        .replace("__BODY__", json.dumps(body))
        .replace("__NAMES__", json.dumps(list(names)))
    )
    with tempfile.TemporaryDirectory(prefix="app-js-") as folder:
        driver_path = Path(folder) / "driver.js"
        payload_path = Path(folder) / "input.json"
        source_path = Path(folder) / "source.js"
        driver_path.write_text(driver, encoding="utf-8")
        payload_path.write_text(json.dumps(payload), encoding="utf-8")
        source_path.write_text(source if source is not None else _source(), encoding="utf-8")
        done = subprocess.run(
            ["node", str(driver_path), str(source_path), str(payload_path)],
            capture_output=True, text=True, encoding="utf-8",
        )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# --- 1. A decision belongs to the seat the payload names ---------------------

_STEPS = [
    ("beginning", "untap", "untap"), ("beginning", "upkeep", "upkeep"),
    ("beginning", "draw", "draw"), ("precombat_main", "precombat_main", "main"),
    ("combat", "beginning_of_combat", "combat"), ("combat", "declare_attackers", "combat"),
    ("combat", "declare_blockers", "combat"), ("combat", "combat_damage", "combat"),
    ("combat", "end_of_combat", "combat"), ("postcombat_main", "postcombat_main", "main"),
    ("ending", "end", "end"), ("ending", "cleanup", "cleanup"),
]


def _owes_nothing_states():
    """A real payload for seat 0 that owes it nothing, re-dated to every step
    of either seat's turn, with the viewer holding ten cards and a board, a
    graveyard and an exile to infer something from."""
    sid, _game = _session(
        board=["Forest", "Mountain", "Grizzly Bears"],
        hand=["Grizzly Bears"] * 6 + ["Lightning Bolt"] * 4,
        opponent_board=["Hill Giant"],
    )
    base = _state(sid)
    assert base["players"][0]["hand_count"] == 10
    base["players"][0]["graveyard"] = base["players"][0]["hand"][:3]
    states = []
    for turn in (0, 1):
        for turn_phase, step, phase in _STEPS:
            state = json.loads(json.dumps(base))
            state.update(
                current_turn=turn, current_turn_phase=turn_phase, current_step=step,
                current_phase=phase, priority_player=turn,
            )
            states.append(state)
    return states


_GETTERS_BODY = r'''
const names = INPUT.getters;
const owed = [];
for (const state of INPUT.states) {
  for (const name of names) {
    const info = eval(name)(state);
    if (info) owed.push(`${name} @ turn ${state.current_turn} ${state.current_step}`);
  }
}
return { owed, examined: names.length * INPUT.states.length };
'''


def _getter_names(source: str) -> list[str]:
    return re.findall(r"^function (get\w+Info)\(state = currentState\)", source, re.M)


@needs_node
def test_c1_every_getter_reads_what_is_owed_never_the_viewers_zones():
    """Every ``get*Info(state)`` getter, over states that owe seat 0 nothing:
    each step of its own turn and of the other seat's, with ten cards in hand.
    A getter that infers a decision from the viewer's zones answers here. On
    the base the cleanup getter did, on its own turn: a hand of ten counted
    against a literal seven while the server's ``cleanup_discard`` was empty
    (CR 402.2: seven is the normal maximum, not the only one). Before
    ``e2831271`` it did on the other seat's turn too, which the SCG Phase 5
    smoke game drew."""
    source = _source()
    getters = _getter_names(source)
    assert len(getters) >= 100, getters
    result = _run_with_deps(
        getters, _GETTERS_BODY,
        {"states": _owes_nothing_states(), "getters": getters},
        prelude="let seat = 0; let currentState = null;",
    )
    assert result["out"]["owed"] == []
    assert result["out"]["examined"] >= 100 * 24


@needs_node
def test_c1_the_cleanup_prompt_is_the_active_seats_and_the_servers():
    """The cleanup getter itself, three ways: holding ten at the other seat's
    cleanup asks nothing (CR 514.1); holding ten at its own cleanup with the
    server's ``cleanup_discard`` empty asks nothing (the server counts against
    the real maximum hand size); and its own cleanup with the server's record
    returns that record."""
    owed = {"required_count": 3, "selected_indices": [], "selected_count": 0}
    hand = [{"name": "Grizzly Bears"}] * 10
    def state(turn, info):
        return {
            "current_turn": turn, "current_phase": "cleanup", "current_step": "cleanup",
            "cleanup_discard": info, "players": [{"hand": hand}, {"hand": []}],
        }
    out = run_app_js(
        ["getCleanupDiscardInfo"],
        "return INPUT.states.map((s) => getCleanupDiscardInfo(s));",
        {"states": [state(1, None), state(0, None), state(0, owed)]},
        prelude="let seat = 0; let currentState = null;",
    )
    assert out == [None, None, owed]


# --- 2. Nothing opens on the engine's provisional default --------------------

# The renderers write markup; this reads it back as a person would see it.
_PROMPT_DOM = r'''
let seat = 0;
let currentState = (INPUT && INPUT.state) || null;
const sent = [];
const hints = [];
async function sendAction(body) { sent.push(body); }
function updateActionHint(message) { hints.push(message); }
const escapeHtml = (text) => String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
// A control read back out of the markup a renderer wrote: its opening tag
// says whether it is disabled and what it holds; a select holds the option
// marked selected (the first, if none is).
function controlAt(markup, at) {
  const start = markup.lastIndexOf("<", at);
  const end = markup.indexOf(">", at);
  const tag = markup.slice(start, end + 1);
  const node = {
    tag, value: "", disabled: /\sdisabled(?=[\s>\/=])/.test(tag), listeners: {}, dataset: {},
    classList: { toggle() {}, add() {}, remove() {} },
    addEventListener(type, fn) { this.listeners[type] = fn; },
  };
  for (const [, name, value] of tag.matchAll(/\sdata-([a-z-]+)="([^"]*)"/g)) {
    node.dataset[name.replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = value;
  }
  if (tag.startsWith("<select")) {
    const inner = markup.slice(end + 1, markup.indexOf("</select>", end));
    const options = [...inner.matchAll(/<option value="([^"]*)"([^>]*)>/g)];
    node.options = options.map((m) => m[1]);
    const chosen = options.find((m) => /\sselected\b/.test(m[2])) || options[0];
    node.value = chosen ? chosen[1] : "";
  } else {
    const value = /\svalue="([^"]*)"/.exec(tag);
    if (value) node.value = value[1];
  }
  return node;
}
function needleOf(selector) {
  if (selector.startsWith("#")) return `id="${selector.slice(1)}"`;
  if (selector.startsWith("[")) return selector.slice(1, -1).split("=")[0] + "=";
  return null;
}
function element(id) {
  return {
    id, textContent: "", markup: "", disabled: false, found: {},
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    set innerHTML(html) { this.markup = html; this.found = {}; },
    get innerHTML() { return this.markup; },
    querySelector(selector) {
      return this.querySelectorAll(selector)[0] || null;
    },
    querySelectorAll(selector) {
      if (!this.found[selector]) {
        const needle = needleOf(selector);
        const hits = [];
        if (needle) {
          for (let at = this.markup.indexOf(needle); at >= 0; at = this.markup.indexOf(needle, at + 1)) {
            hits.push(controlAt(this.markup, at));
          }
        }
        this.found[selector] = hits;
      }
      return this.found[selector];
    },
  };
}
const nodes = {};
const q = (id) => (nodes[id] = nodes[id] || element(id));
const document = { getElementById: q };
'''


def _creature_type_payload():
    """The prompt the server sends as Harsh Mercy resolves — the same
    ``creature_type_choice`` Proteus Machine's turn-up arms, with its
    ``default_creature_type``, the engine's pick for an AI seat."""
    sid, game = _session(board=["Elvish Warrior"], hand=["Harsh Mercy"],
                         opponent_board=["Goblin Sledder"])
    game.players[0].mana_pool["W"] = 3
    cast = client.post(f"/api/sessions/{sid}/action",
                       json={"seat": 0, "action": "cast", "card_name": "Harsh Mercy"})
    assert cast.status_code == 200, cast.text
    for passing in (0, 1):
        client.post(f"/api/sessions/{sid}/action", json={"seat": passing, "action": "pass_priority"})
    state = _state(sid)
    payload = state.get("creature_type_choice")
    assert payload and payload.get("creature_types"), state.get("prompt_owed_by")
    return payload


@needs_node
def test_c2_the_creature_type_select_opens_on_no_choice_and_holds_choose():
    payload = _creature_type_payload()
    assert payload.get("default_creature_type")  # the field is still on the wire
    out = run_app_js(
        ["applyCreatureTypeChoicePrompt", "creatureTypeChoiceWording", "creatureTypeChoiceKey",
         "typeChoiceOptionsHtml"],
        """
        applyCreatureTypeChoicePrompt(INPUT.info);
        const steps = nodes.promptSteps;
        const picker = steps.querySelector("#creatureTypeChoiceSelect");
        const button = steps.querySelector("#creatureTypeChoiceOk");
        const opened = { value: picker.value, disabled: button.disabled, first: picker.options[0] };
        await button.listeners.click();
        const sentBeforeChoosing = sent.length;
        picker.value = "dragon";
        picker.listeners.change();
        const afterPick = button.disabled;
        // A poll redraws the panel; the pick is kept.
        applyCreatureTypeChoicePrompt(INPUT.info);
        const redrawn = nodes.promptSteps.querySelector("#creatureTypeChoiceSelect").value;
        const redrawnDisabled = nodes.promptSteps.querySelector("#creatureTypeChoiceOk").disabled;
        await nodes.promptSteps.querySelector("#creatureTypeChoiceOk").listeners.click();
        return { opened, sentBeforeChoosing, afterPick, redrawn, redrawnDisabled, sent };
        """,
        {"info": payload},
        prelude=_PROMPT_DOM + "\nlet creatureTypeChoiceDraft = { key: null, value: \"\" };",
    )
    assert out["opened"] == {"value": "", "disabled": True, "first": ""}
    assert out["sentBeforeChoosing"] == 0
    assert out["afterPick"] is False
    assert (out["redrawn"], out["redrawnDisabled"]) == ("dragon", False)
    assert out["sent"] == [
        {"seat": 0, "action": "creature_type_choice_confirm", "creature_type": "dragon"},
    ]


@needs_node
def test_c2_the_name_prompt_opens_empty_and_a_chip_fills_it():
    """Necromentia's name prompt over the server's payload: the input opens
    empty with Name It held, though the payload names a ``default_name``."""
    info = {
        "card_name": "Necromentia", "target_seat": 1, "suggestions": ["Grizzly Bears"],
        "default_name": "Grizzly Bears",
    }
    out = run_app_js(
        ["applyNameAndStripPrompt"],
        """
        applyNameAndStripPrompt(INPUT.info);
        const steps = nodes.promptSteps;
        const input = steps.querySelector("#nameAndStripInput");
        const confirm = steps.querySelector("[data-name-confirm]");
        const opened = { value: input.value, disabled: confirm.disabled };
        await confirm.listeners.click();
        const sentBlank = sent.length;
        steps.querySelectorAll("[data-name-chip]")[0].listeners.click();
        const chipped = { value: input.value, disabled: confirm.disabled };
        await confirm.listeners.click();
        return { opened, sentBlank, chipped, sent };
        """,
        {"info": info, "state": {"players": [{"name": "Me"}, {"name": "AI"}]}},
        prelude=_PROMPT_DOM + "\nlet nameAndStripDraft = null;",
    )
    assert out["opened"] == {"value": "", "disabled": True}
    assert out["sentBlank"] == 0
    assert out["chipped"] == {"value": "Grizzly Bears", "disabled": False}
    assert out["sent"] == [{"seat": 0, "action": "name_and_strip_confirm", "card_name": "Grizzly Bears"}]


@needs_node
def test_c2_a_cast_announced_type_starts_unpicked():
    """Aphetto Dredging's cast announcement: nothing is selected, and the
    select's markup opens on the disabled placeholder."""
    out = run_app_js(
        ["startCastCreatureTypePrompt", "typeChoiceOptionsHtml"],
        """
        startCastCreatureTypePrompt({ name: "Aphetto Dredging" });
        return { selected: pendingCastCreatureType.selected,
                 markup: typeChoiceOptionsHtml(pendingCastCreatureType.types, "") };
        """,
        prelude=_PROMPT_DOM + """
        let pendingCastCreatureType = null;
        function castAnnouncesCreatureType() {
          return { creature_types: ["elf", "goblin", "zombie"], default_creature_type: "goblin" };
        }
        function normalizeCardName(card) { return card.name; }
        function renderActivationPrompt() {}
        """,
    )
    assert out["selected"] is None
    assert out["markup"].startswith('<option value="" disabled selected>Choose…</option>')
    assert " selected>Goblin" not in out["markup"]


@needs_node
def test_c2_a_division_starts_from_the_rules_minimum():
    """CR 601.2d: each target must receive at least one — and nothing more
    is placed for the caster. A lone target takes the whole total; that, too,
    is the rule's. The base split evenly (``evenStartingDivision``: {3}
    between two opened as 2 and 1, so one click on Confirm divided it)."""
    out = run_app_js(
        ["ruleStartingDivision"],
        "return [ruleStartingDivision(3, 2), ruleStartingDivision(3, 3), ruleStartingDivision(3, 1), ruleStartingDivision(5, 2)];",
    )
    assert out == [[1, 1], [1, 1, 1], [3], [1, 1]]


# A ``document.createElement`` page: enough of one for the combat-damage
# dialog's sections, which build nodes rather than markup.
_CREATE_ELEMENT_DOM = r"""
let seat = 0;
let currentState = INPUT.state;
let combatDividedDraft = { key: null, byAttacker: {} };
let combatDamageDraft = {};
let redraws = 0;
function getCombatDamagePassKey() { return "combat-damage-1"; }
function renderCombatDamageDialogBody() { redraws += 1; }
const escapeHtml = (t) => String(t);
function made(tag) {
  return {
    tag, className: "", dataset: {}, textContent: "", innerHTML: "", children: [], listeners: {},
    appendChild(child) { this.children.push(child); return child; },
    addEventListener(type, fn) { this.listeners[type] = fn; },
    setAttribute() {},
  };
}
const document = { createElement: made };
function everyNode(node, out = []) { out.push(node); for (const c of node.children) everyNode(c, out); return out; }
"""


@needs_node
def test_c2_butcher_orggs_division_opens_with_nothing_placed():
    """Butcher Orgg's question (CR 510.1, its own "divided as you choose"):
    choosing to divide opens with no share placed. The base wrote its whole
    power onto the defending player on that click, so Confirm divided it."""
    group = {
        "attackerIdx": 0, "power": 4, "attackerCard": {"name": "Butcher Orgg"}, "blockers": [],
        "divide": {"defendingSeat": 1, "creatures": []},
    }
    out = run_app_js(
        ["renderDividedAssignmentSection", "dividedDraftFor", "dividedRecipients"],
        """
        const section = renderDividedAssignmentSection(
          INPUT.group, [INPUT.group], "assign", { valid: false, total: 0 }, () => made("thumb"));
        const divide = everyNode(section).find((n) => n.dataset && n.dataset.divide === "divide");
        divide.listeners.click();
        return { draft: dividedDraftFor(INPUT.group), redraws };
        """,
        {"group": group, "state": {"players": [{"name": "Me", "battlefield": []},
                                               {"name": "AI", "life": 20, "battlefield": []}]}},
        prelude=_CREATE_ELEMENT_DOM,
    )
    assert out["draft"] == {"answer": "divide", "shares": {}}
    assert out["redraws"] == 1


@needs_node
def test_c2_the_colour_buttons_do_not_mark_the_ai_default():
    out = run_app_js(
        ["applyColorChoicePrompt"],
        """
        applyColorChoicePrompt(INPUT.info);
        return nodes.promptSteps.markup;
        """,
        {"info": {"card_name": "Ward Sliver", "colors": ["W", "U", "B", "R", "G"], "default_color": "R"}},
        prelude=_PROMPT_DOM + "\nconst COLOR_CHOICE_WORDS = { W: 'White', U: 'Blue', B: 'Black', R: 'Red', G: 'Green' };",
    )
    assert "(default)" not in out and ">Red<" in out


def test_c2_census_no_client_code_reads_a_provisional_default():
    """The census: no code in app.js reads a ``default_*`` field. Comments and
    strings are blanked first, so the explanations that name the fields do not
    count. On the base there were four: the creature-type prompt's select
    (``default_creature_type``), the cast announcement's (the spec's), the
    name prompt's input (``default_name``) and the colour buttons'
    "(default)" (``default_color``). An engine default is what an AI seat
    takes; a person's prompt opens on no choice. The divisions read no
    ``default_*`` but placed shares the same way — an even split, and Butcher
    Orgg's whole power on the player — so they are asked by name above."""
    code = mask(_source())
    reads = re.findall(r"\.default_\w+", code)
    assert reads == []


# --- 3. The CR 118.9d note says only what the label does not ----------------

def _offer(sid, card_name):
    state = _state(sid)
    card = next(c for c in state["players"][0]["hand"] if c["name"] == card_name)
    offers = card["target_spec"]["cost_offers"]
    return next(offer for offer in offers if offer.get("keyword") == "morph")


@needs_node
def test_3_the_morph_offer_names_its_mana_once_and_the_tax_beside_it():
    """Skirk Volcanist's face-down offer, as the server sent it: on a bare
    board it owes the {3} its label already names, so no note; under Sphere of
    Resistance it owes {4}, and the CR 118.9d note says so."""
    sid, _game = _session(board=["Mountain"] * 4, hand=["Skirk Volcanist"])
    bare = _offer(sid, "Skirk Volcanist")
    sid, _game = _session(board=["Mountain"] * 4 + ["Sphere of Resistance"], hand=["Skirk Volcanist"])
    taxed = _offer(sid, "Skirk Volcanist")
    assert (bare["mana_owed"], taxed["mana_owed"]) == ("{3}", "{4}")
    out = run_app_js(
        ["alternativeOfferOwedNote", "manaSymbolTallyKey"],
        "return INPUT.offers.map((offer) => alternativeOfferOwedNote(offer));",
        {"offers": [bare, taxed, {"label": "pay 1 life", "mana_owed": "{1}"}, {"label": "x", "mana_owed": None}]},
        prelude="function renderSymbolsInline(text) { return text; }",
    )
    assert out[0] == ""
    assert out[1] == " — {4} in mana in all (cost increases apply to it, CR 118.9d)"
    assert out[2] == " — {1} in mana in all (cost increases apply to it, CR 118.9d)"
    assert out[3] == ""


# --- 4. A long list scrolls inside the prompt panel --------------------------

def _css_block(selector: str) -> str:
    css = (_STATIC / "styles.css").read_text(encoding="utf-8")
    found = re.search(r"(^|\n)" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert found, selector
    return found.group(2)


def test_4_the_prompt_steps_scroll_inside_the_panel():
    """Every renderer writes its list into ``#promptSteps``; that box scrolls,
    capped below the dock's height, so the title and buttons above it stay.
    The modal dialogs' grids already scroll (``.library-card-grid``)."""
    steps = _css_block(".prompt-steps")
    assert "overflow-y: auto" in steps
    assert re.search(r"max-height:\s*max\(160px,\s*calc\(70vh - 240px\)\)", steps)
    grid = _css_block(".library-card-grid")
    assert "overflow-y: auto" in grid and "max-height: 52vh" in grid


@needs_node
def test_4_the_breach_return_list_is_written_into_the_scrolling_box():
    """A 28-card Dimensional Breach return, rendered: every choice lands in
    ``#promptSteps`` (the box that scrolls) and none in the title or body."""
    info = {
        "card_name": "Dimensional Breach", "zone": "battlefield",
        "choices": [{"entry_index": i, "name": f"Card {i}", "card": {"name": f"Card {i}", "type": "Creature"}}
                    for i in range(28)],
    }
    out = run_app_js(
        ["applyExiledCardReturnPrompt"],
        """
        applyExiledCardReturnPrompt(INPUT.info);
        return { steps: (nodes.promptSteps.markup.match(/data-ecr-entry=/g) || []).length,
                 title: nodes.promptTitle.textContent };
        """,
        {"info": info},
        prelude=_PROMPT_DOM + "\nfunction showCardPreview() {}",
    )
    assert out["steps"] == 28
    assert "return an exiled card" in out["title"]


# --- 5. A permanent's tile shows its art -------------------------------------

@needs_node
def test_5_a_candidate_tile_shows_the_permanents_art_off_the_board():
    """The tile face reads the board the candidate names by id: art where the
    permanent has it, the name for a face-down permanent (CR 708.2) and for
    one the board does not show, and a seatless candidate (the keep modal's)
    found on any seat."""
    sid, game = _session(board=["Grizzly Bears"], opponent_board=["Hill Giant"])
    state = _state(sid)
    bears = state["players"][0]["battlefield"][0]
    giant = state["players"][1]["battlefield"][0]
    assert bears["image_uri"] and giant["image_uri"]
    hidden = dict(giant, id=999, face_down=True, image_uri=None)
    state["players"][1]["battlefield"].append(hidden)
    out = run_app_js(
        ["candidatePermanentTileFace", "candidatePermanentImage"],
        """
        return [
          candidatePermanentTileFace({ seat: 1, id: INPUT.giant, name: "Hill Giant" }, "Hill Giant", INPUT.state),
          candidatePermanentTileFace({ id: INPUT.bears, name: "Grizzly Bears" }, "Grizzly Bears", INPUT.state),
          candidatePermanentTileFace({ seat: 1, id: 999, name: "Face-down creature" }, "Face-down creature", INPUT.state),
          candidatePermanentTileFace({ seat: 0, id: 12345, name: "Gone" }, "Gone", INPUT.state),
        ];
        """,
        {"state": state, "giant": giant["id"], "bears": bears["id"]},
        prelude="const escapeHtml = (t) => String(t); let currentState = null;",
    )
    assert out[0].startswith(f'<img src="{giant["image_uri"]}" alt="Hill Giant"')
    assert out[1].startswith(f'<img src="{bears["image_uri"]}" alt="Grizzly Bears"')
    assert out[2] == '<div class="library-card-text-placeholder">Face-down creature</div>'
    assert out[3] == '<div class="library-card-text-placeholder">Gone</div>'


def test_5_census_every_tile_falls_back_to_a_name_only_without_art():
    """Every ``library-card-text-placeholder`` the client writes is the else
    branch of an image test (``: `<div class=…``). On the base five tile
    renderers wrote it unconditionally — the several-target dialog, the roles
    dialog, untap-up-to, the permanent-set choice and the keep modal — so
    their tiles were names in blank boxes."""
    lines = [line.strip() for line in _source().splitlines() if "library-card-text-placeholder" in line]
    assert len(lines) >= 10
    bare = [line for line in lines if not line.startswith(": `<div class=\"library-card-text-placeholder\"")]
    assert bare == []


# --- 6. A modal's prompt hides the panel behind it ---------------------------

def _modal_render_getters(source: str) -> set[str]:
    """The getter behind each modal ``renderState`` draws: every
    ``render…Modal(…)`` call between the panel's render and the draw-choice
    modals, its argument a getter called on the state or a local
    ``renderState`` assigned from one."""
    body = source[source.index("\nfunction renderState(state"):]
    body = body[:body.index("\n}\n")]
    locals_ = dict(re.findall(r"const (\w+) = (\w+)\(state\);", body))
    block = body[body.index("  renderActivationPrompt();"):body.index("  renderDrawChoiceModals(state);")]
    getters = set()
    for argument in re.findall(r"^\s*render\w+Modal\(([^;]*)\);$", block, re.M):
        called = re.fullmatch(r"(\w+)\(state\)", argument)
        getter = called.group(1) if called else locals_.get(argument)
        assert getter, f"a modal drawn from {argument!r}, which this census cannot read"
        getters.add(getter)
    return getters


def _modal_owned_getters(source: str) -> list[str]:
    block = source[source.index("const MODAL_OWNED_PROMPTS = ["):]
    block = block[:block.index("];")]
    return re.findall(r'\["[a-z_]+", (get\w+Info)\]', block)


# A modal that owes nothing — a notification, so the panel behind it is
# current — and the several-target dialog, whose panel line says where the
# answer is ("choose them in the dialog").
_PANEL_STAYS = {"getHandRevealInfo", "getFaceDownLookInfo", "severalTargetsPrompt"}


def test_6_census_every_decision_modal_hides_the_panel():
    """Every modal ``renderState`` draws is in ``MODAL_OWNED_PROMPTS``, the
    three above aside, and so are the draw-choice modals
    (``renderDrawChoiceModals``). On the base two were (the revealed hand
    pick and the graveyard exile pick); the panel behind the other nine and
    the four draw choices fell through to the step's own prompt."""
    source = _source()
    owned = set(_modal_owned_getters(source))
    rendered = _modal_render_getters(source)
    assert len(rendered) == 14, sorted(rendered)
    assert rendered - _PANEL_STAYS - owned == set()
    draws = source[source.index("function renderDrawChoiceModals(state) {"):]
    draws = draws[:draws.index("\n}\n")]
    drawn = set(re.findall(r"(get\w+Info)\(state\)", draws))
    assert len(drawn) == 4 and drawn - owned == set()


@needs_node
def test_6_a_modal_prompt_is_owned_for_its_seat_only():
    """Run over the server's own payloads: a library search owed by seat 0
    hides seat 0's panel; the same payload read by seat 1 hides nothing (the
    server already leaves the search off seat 1's poll, which shows "Waiting
    for …"; the client's getter holds the line too); and a state owing
    nothing hides nothing."""
    sid, game = _session(hand=["Long-Term Plans"], board=["Island"] * 3)
    game.interactive_seats = {0, 1}
    assert client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "cast", "card_name": "Long-Term Plans", "auto_tap": True,
    }).status_code == 200
    client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "pass_priority"})
    client.post(f"/api/sessions/{sid}/action", json={"seat": 1, "action": "pass_priority"})
    mine, theirs = _state(sid, 0), _state(sid, 1)
    assert mine.get("search_library"), mine.get("prompt_owed_by")
    assert not theirs.get("search_library")
    nothing = _state(_session()[0], 0)
    def owned(state, viewer):
        return _run_with_deps(
            ["modalOwnedPrompt"], "return modalOwnedPrompt(INPUT.state);", {"state": state},
            prelude=f"let seat = {viewer}; let currentState = null;",
        )["out"]
    assert owned(mine, 0) == "search_library"
    assert owned(mine, 1) is None
    assert owned(theirs, 1) is None
    assert owned(nothing, 0) is None


# --- 7. A cast the pool cannot pay is previewed, never sent ------------------

def _previewed_paying_actions() -> str:
    """The client's own ``PREVIEWED_PAYING_ACTIONS`` declaration, as written."""
    block = _source()
    block = block[block.index("const PREVIEWED_PAYING_ACTIONS = new Set(["):]
    return block[:block.index("]);") + 3]


def test_7_the_previewed_kinds_are_the_servers_paying_actions():
    assert set(re.findall(r'"([a-z_]+)"', _previewed_paying_actions())) == set(PAYING_ACTIONS)


_SEND_PRELUDE = r'''
let seat = 0;
let sessionId = "S";
let currentState = null;
const posted = [];
const rendered = [];
const replies = INPUT.replies || {};
async function postJson(url, body) {
  posted.push({ url: url.split("/").pop(), body: JSON.parse(JSON.stringify(body)) });
  const reply = replies[url.split("/").pop()];
  if (reply && reply.error) throw new Error(reply.error);
  return reply || {};
}
function snapStateRefetchBackoff() {}
function opponentStopSteps() { return []; }
function selfStopSteps() { return []; }
function carryCastMode(body) { return body; }
function carryAnnouncedSeat() {}
function carryCastZoneAndCost(body) { return body; }
function castManaSplitFor() { return null; }
function carryMadnessAnswer(body) { return body; }
function carryCopyCastAnswer(body) { return body; }
function carryAbilityCostAlternative(body) { return body; }
function captureModeCollectionTarget() { return false; }
function renderState(payload) { rendered.push(payload); }
let pendingChosenAbilityWord = null;
let pendingActivationCost = null;
let pendingModeCollection = null;
const _CAST_ACTIONS = new Set(["cast", "debug_cast_free", "debug_cast_free_opponent"]);
'''

_SEND_BODY = r'''
let refusal = null;
try { await sendAction(INPUT.body); } catch (e) { refusal = { message: e.message, plan: !!e.paymentPlan }; }
return { posted: posted.map((p) => p.url), refusal, rendered: rendered.length };
'''


@needs_node
@pytest.mark.parametrize("board, pool, expected", [
    # The pool short, the lands untapped: the preview taps, so the cast is
    # not sent and "insufficient mana" is raised for the dialog.
    (["Mountain", "Mountain"], {}, (["payment_plan"], "insufficient mana")),
    # The pool pays: preview, then the cast.
    ([], {"R": 2}, (["payment_plan", "action"], None)),
    # Nothing pays: the preview's own mana refusal is raised.
    (["Mountain"], {}, (["payment_plan"], "insufficient mana for Goblin Brigand")),
], ids=["board-pays", "pool-pays", "nothing-pays"])
def test_7_a_paying_cast_is_previewed_and_sent_only_when_the_pool_pays(board, pool, expected):
    sid, game = _session(board=board, hand=["Goblin Brigand"])
    for color, amount in pool.items():
        game.players[0].mana_pool[color] = amount
    body = {"seat": 0, "action": "cast", "card_name": "Goblin Brigand"}
    plan = client.post(f"/api/sessions/{sid}/payment_plan", json=body).json()
    out = run_app_js(
        ["sendAction", "previewPayingAction", "paymentPreviewVerdict", "isManaRefusal"],
        _SEND_BODY,
        {"body": body, "replies": {"payment_plan": plan, "action": {"ok": True}}},
        prelude=_SEND_PRELUDE + _previewed_paying_actions(),
    )
    posted, message = expected
    assert out["posted"] == posted
    assert (out["refusal"] or {}).get("message") == message
    if message is None:
        # And the cast the client then sends goes through on the server.
        response = client.post(f"/api/sessions/{sid}/action", json=body)
        assert response.status_code == 200, response.text
    else:
        assert out["refusal"]["plan"] is True
        refused = client.post(f"/api/sessions/{sid}/action", json=body)
        assert refused.status_code == 400 and refused.json()["detail"].startswith("insufficient mana")


@needs_node
def test_7_a_preview_refused_for_anything_else_sends_the_action():
    """A preview that could not be made, or that was refused for something
    other than mana, decides nothing: the action is sent and the server's own
    answer is read, as before. An auto-tap payment is never previewed."""
    def run(replies, body):
        return run_app_js(
            ["sendAction", "previewPayingAction", "paymentPreviewVerdict", "isManaRefusal"],
            _SEND_BODY,
            {"body": body, "replies": replies},
            prelude=_SEND_PRELUDE + _previewed_paying_actions(),
        )
    cast = {"seat": 0, "action": "cast", "card_name": "Shock"}
    assert run({"payment_plan": {"error": "seat has not joined"}}, cast)["posted"] == ["payment_plan", "action"]
    assert run({"payment_plan": {"payable": False, "taps": [], "reason": "a resolution is in progress"}},
               cast)["posted"] == ["payment_plan", "action"]
    assert run({}, {**cast, "auto_tap": True})["posted"] == ["action"]
    assert run({}, {"seat": 0, "action": "pass_priority"})["posted"] == ["action"]
