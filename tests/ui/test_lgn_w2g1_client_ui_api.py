"""Legions' prompts in the browser: the client halves wave 1 left owing.

Wave 1 built each of these on the wire and could not touch ``web/static/``;
each is driven here from the payload the server really sends, through the
client function that renders it (lifted out of ``app.js`` by name and run in
node over a stubbed page), to the request body it sends — and that body is
posted back to the server, which must take it. The same paths were clicked in
a browser (``scratch/lgn/w2g1``).

* ``entry_reveal`` (amplify, CR 702.38a): the hand cards to reveal, toggled,
  and "Reveal nothing" as an answer;
* turning a morph face up with an X in its morph cost (CR 107.3d, 702.37f):
  a row of X values, each priced in full;
* ``trigger_target`` with ``roles`` (Chromeshell Crab): one pick per role,
  sent in role order whatever order they were clicked in;
* a search with a hand zone (Dark Supplicant): a Hand grid, answered with
  ``search_zone: "hand"``;
* Hollow Specter's "you may pay {X}" panel (``pays_x``), provoke's badge and
  the offer it makes, who the game is waiting on (``prompt_owed_by``), the
  card a face-down permanent hides in a prompt's permanent list, and a
  cleanup discard another viewer's poll used to wipe.
"""
from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.face_down import FACE_DOWN_NAME, face_down_card
from engine.models import Permanent
from engine.named_counters import counters_on
from engine.provoke import PROVOKE_REMINDER
from tests.helpers import _resolve_top_stack, resolve_stack, run_app_js
from web.app import app, store
from web.prompt_registry import PromptContext
from web.prompts import prompt_owed_by, render_prompts
from web.serialization import _effective_keywords, _serialize_card_summary
from web.state_view import _prompt_permanent_summary

client = TestClient(app)
_CATALOG = {card.name: card for card in load_catalog()}

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)


# --- the page, stubbed ----------------------------------------------------

#: Just enough of a page for the panels and dialogs under test: every element
#: is a stub whose ``innerHTML`` is parsed back into child stubs (tag,
#: classes, ``data-*``), so a test clicks the very markup the renderer wrote.
_DOM = r'''
var seat = INPUT.seat === undefined ? 0 : INPUT.seat;
let currentState = INPUT.state || null;
const SENT = [];
const HINTS = [];
async function sendAction(body) { SENT.push(body); return {}; }
function updateActionHint(message) { HINTS.push(String(message)); }
function escapeHtml(text) { return String(text); }
function renderSymbolsInline(text) { return String(text); }
function setSymbolsHtml(el, text) { el.innerHTML = String(text); }
function renderActivationPrompt() {}
function updateSearchLibraryPreview() {}
const SFX = { onError() {} };

function camel(name) { return name.replace(/-([a-z])/g, (_, c) => c.toUpperCase()); }
function parseChildren(html) {
  const out = [];
  const tags = /<([a-zA-Z0-9]+)((?:\s+[^\s=>]+(?:="[^"]*")?)*)\s*\/?>/g;
  let m;
  while ((m = tags.exec(html))) {
    const el = makeEl(null, m[1].toLowerCase());
    const attrs = /([^\s=>\/]+)(?:="([^"]*)")?/g;
    let a;
    while ((a = attrs.exec(m[2]))) el.attrs[a[1]] = a[2] === undefined ? "" : a[2];
    el.id = el.attrs.id || null;
    el.className = el.attrs.class || "";
    for (const [k, v] of Object.entries(el.attrs)) {
      if (k.startsWith("data-")) el.dataset[camel(k.slice(5))] = v;
    }
    el.disabled = "disabled" in el.attrs;
    el.textContent = html.slice(tags.lastIndex).split("<")[0];
    out.push(el);
  }
  return out;
}
function matches(el, sel) {
  const id = sel.match(/#([\w-]+)/);
  if (id && el.id !== id[1]) return false;
  const have = (el.className || "").split(/\s+/);
  for (const c of sel.matchAll(/\.([\w-]+)/g)) if (!have.includes(c[1])) return false;
  for (const [, name, value] of sel.matchAll(/\[([\w-]+)(?:=['"]?([^'"\]]*)['"]?)?\]/g)) {
    const key = camel(name.replace(/^data-/, ""));
    if (!(key in el.dataset)) return false;
    if (value !== undefined && String(el.dataset[key]) !== value) return false;
  }
  return true;
}
function descendants(el) {
  const out = [];
  for (const child of el.children) out.push(child, ...descendants(child));
  return out;
}
function makeEl(id, tag = "div") {
  const el = {
    id, tag, textContent: "", value: "", title: "", disabled: false, checked: false,
    dataset: {}, attrs: {}, className: "", children: [], listeners: {}, onclick: null,
    _html: "",
    classList: {
      add(c) { if (!this.contains(c)) el.className = `${el.className} ${c}`.trim(); },
      remove(c) { el.className = el.className.split(/\s+/).filter((x) => x && x !== c).join(" "); },
      toggle(c, on) { (on === undefined ? !this.contains(c) : on) ? this.add(c) : this.remove(c); },
      contains(c) { return el.className.split(/\s+/).includes(c); },
    },
    set innerHTML(v) { this._html = String(v); this.children = parseChildren(this._html); },
    get innerHTML() { return this._html; },
    appendChild(child) { this.children.push(child); return child; },
    querySelectorAll(sel) { return descendants(this).filter((c) => matches(c, sel)); },
    querySelector(sel) { return this.querySelectorAll(sel)[0] || null; },
    addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
    async click() {
      if (this.disabled) return;
      for (const fn of this.listeners.click || []) await fn({});
      if (this.onclick) await this.onclick({});
    },
  };
  return el;
}
const ELS = {};
function q(id) { if (!ELS[id]) ELS[id] = makeEl(id); return ELS[id]; }
const document = { getElementById: (id) => q(id), createElement: (tag) => makeEl(null, tag) };
'''


def _hvh(seed: int = 3802):
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


def _state(sid: str, seat: int) -> dict:
    response = client.get(f"/api/sessions/{sid}/state", params={"seat": seat})
    assert response.status_code == 200, response.text
    return response.json()


def _post(sid: str, body: dict):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def _put(game, seat: int, card) -> Permanent:
    permanent = Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(permanent)
    game._sync_control()
    return permanent


# --- 1. amplify's reveal ---------------------------------------------------

def _rogon_entering(set_pool):
    sid, _session, game = _hvh()
    lgn = set_pool("LGN")
    game.enforce_mana_costs = False
    game.players[1].battlefield.append(Permanent(card=_CATALOG["Mountain"]))
    game.players[0].hand = [
        lgn["Glowering Rogon"], lgn["Canopy Crawler"], _CATALOG["Island"], lgn["Feral Throwback"],
    ]
    assert game.cast_from_hand(0, "Glowering Rogon").supported
    game.resolve_top_of_stack()
    assert game.pending_choice_of("entry_reveal", 0) is not None
    return sid, game


_REVEAL_BODY = r'''
applyEntryRevealPrompt(INPUT.info);
const steps = q("promptSteps");
const opened = {
  title: q("promptTitle").textContent,
  body: q("promptBody").textContent,
  offered: steps.querySelectorAll("[data-entry-reveal-hand]").map((b) => [Number(b.dataset.entryRevealHand), b.textContent]),
  confirm: steps.querySelector("[data-entry-reveal-confirm]").textContent,
};
for (const index of INPUT.pick) {
  await q("promptSteps").querySelector(`[data-entry-reveal-hand='${index}']`).click();
}
const label = q("promptSteps").querySelector("[data-entry-reveal-confirm]").textContent;
await q("promptSteps").querySelector("[data-entry-reveal-confirm]").click();
return { opened, label, sent: SENT };
'''


@needs_node
@pytest.mark.parametrize("pick, counters", [([0, 2], 2), ([], 0)], ids=["two", "none"])
def test_the_reveal_panel_sends_the_slots_clicked_and_the_server_takes_them(set_pool, pick, counters):
    sid, game = _rogon_entering(set_pool)
    info = _state(sid, 0)["entry_reveal"]

    out = run_app_js(
        ["applyEntryRevealPrompt"], _REVEAL_BODY,
        {"info": info, "pick": pick},
        prelude=_DOM + "let entryRevealSelected = []; let entryRevealFor = null;",
    )

    assert out["opened"]["title"] == "Glowering Rogon — amplify 1"
    assert "share a creature type with it (Beast)" in out["opened"]["body"]
    assert out["opened"]["offered"] == [[0, "Canopy Crawler"], [2, "Feral Throwback"]]
    assert out["opened"]["confirm"] == "Reveal nothing", "revealing none is an answer from the start"
    assert out["label"] == ("Reveal nothing" if not pick else "Reveal 2 cards (2 +1/+1 counters)")
    (body,) = out["sent"]
    assert body == {"seat": 0, "action": "entry_reveal_confirm", "hand_indices": pick}

    response = _post(sid, body)
    assert response.status_code == 200, response.text
    rogon = next(p for p in game.controlled_by(0) if p.card.name == "Glowering Rogon")
    assert counters_on(rogon, "+1/+1") == counters
    assert game.pending_choice_of("entry_reveal", 0) is None


# --- 2. an X in a morph cost ---------------------------------------------

_X_ROW_BODY = r'''
renderSpecialActions(currentState, true);
const host = q("specialActions");
const offer = host.children.map((b) => b.innerHTML);
await host.children[0].click();
const row = host.querySelector(".special-action-x-row");
const values = row.children.filter((b) => b.dataset.specialActionXValue !== undefined)
  .map((b) => b.innerHTML);
const sentBeforeX = SENT.length;
await host.querySelector(`[data-special-action-x-value='${INPUT.x}']`).click();
return { offer, values, sentBeforeX, sent: SENT };
'''


@needs_node
def test_the_morph_x_row_offers_each_payable_x_and_sends_the_one_clicked(set_pool):
    sid, _session, game = _hvh(seed=3)
    trumpeter = _put(game, 0, face_down_card(set_pool("LGN")["Warbreak Trumpeter"]))
    for _ in range(5):
        _put(game, 0, _CATALOG["Mountain"])
    state = _state(sid, 0)

    out = run_app_js(
        ["renderSpecialActions", "renderSpecialActionXRow", "morphCostWithX",
         "turnFaceUpActionLabel", "turnFaceUpHiddenName", "startSpecialActionCostPrompt",
         "sendSpecialAction"],
        _X_ROW_BODY, {"state": state, "x": 2},
        prelude=_DOM + (
            "let specialActionXFor = null; let pendingPermanentCost = null;"
            # The real table's turn-face-up row; the other kinds never arise here.
            "const SPECIAL_ACTION_LABELS = { turn_face_up: (name, entry) => turnFaceUpActionLabel(entry) };"
        ),
    )

    assert out["offer"] == ["Turn Warbreak Trumpeter face up — Morph {X}{X}{R}"]
    assert out["sentBeforeX"] == 0, "the offer opens the X row; it does not send X = 0"
    # Each printed {X} is X generic mana: {X}{X}{R} at X = 2 is {4}{R}.
    assert out["values"] == ["X = 0 · {R}", "X = 1 · {2}{R}", "X = 2 · {4}{R}"]
    (body,) = out["sent"]
    assert body["special_action_kind"] == "turn_face_up" and body["x_value"] == 2
    assert body["permanent_id"] == trumpeter.permanent_id

    response = _post(sid, body)
    assert response.status_code == 200, response.text
    assert trumpeter.card.name == "Warbreak Trumpeter"
    _resolve_top_stack(sid, 0)
    assert sum(p.card.name == "Goblin Token" for p in game.controlled_by(0)) == 2


@needs_node
def test_morph_cost_with_x_prices_each_x_symbol():
    out = run_app_js(
        ["morphCostWithX"],
        "return [morphCostWithX('{X}{X}{R}', 0), morphCostWithX('{X}{X}{R}', 3), "
        "morphCostWithX('{X}{B}{B}', 2), morphCostWithX('{2}{X}', 1), morphCostWithX('{X}', 0)];",
    )
    assert out == ["{R}", "{6}{R}", "{2}{B}{B}", "{3}", "{0}"]


# --- 3. a trigger that names its targets by role --------------------------

_ROLES_BODY = r'''
renderSeveralTargetsModal(severalTargetsPrompt(currentState));
const list = q("modalModeTargetsList");
const confirm = q("modalModeTargetsConfirmBtn");
const opened = {
  hidden: q("modalModeTargetsModal").classList.contains("hidden"),
  subtitle: q("modalModeTargetsSubtitle").textContent,
  headings: list.querySelectorAll(".role-target-heading").map((h) => h.textContent),
  tiles: list.querySelectorAll(".library-card-choice").map((t) => [Number(t.dataset.rolePosition), Number(t.dataset.id), t.textContent]),
  disabled: confirm.disabled,
};
// The second role first: the answer is in role order, not click order.
await q("modalModeTargetsList").querySelector(`[data-role-position='1'][data-id='${INPUT.theirs}']`).click();
const afterOne = confirm.disabled;
await q("modalModeTargetsList").querySelector(`[data-role-position='0'][data-id='${INPUT.mine}']`).click();
const afterBoth = confirm.disabled;
await confirm.onclick();
return { opened, afterOne, afterBoth, sent: SENT };
'''


@needs_node
def test_the_roles_dialog_answers_each_role_in_role_order(set_pool):
    """Chromeshell Crab: "When this creature is turned face up, you may
    exchange control of target creature you control and target creature an
    opponent controls." The several-targets dialog sent a set of ids in the
    order they were clicked — the opponent's creature first named the roles
    backwards and the server refused it."""
    sid, _session, game = _hvh(seed=5)
    crab = _put(game, 0, face_down_card(set_pool("LGN")["Chromeshell Crab"]))
    bears = _put(game, 0, _CATALOG["Grizzly Bears"])
    giant = _put(game, 1, _CATALOG["Hill Giant"])
    for _ in range(5):
        _put(game, 0, _CATALOG["Island"])
    response = _post(sid, {
        "seat": 0, "action": "special_action", "permanent_id": crab.permanent_id,
        "special_action_kind": "turn_face_up",
    })
    assert response.status_code == 200, response.text
    state = _state(sid, 0)
    assert state["trigger_target"]["roles"], "a roles announcement"

    out = run_app_js(
        ["getTriggerTargetInfo", "getModalModeTargetsInfo", "triggerNamesSeveralTargets",
         "severalTargetsPrompt", "candidateOwnerLabel", "renderSeveralTargetsModal",
         "renderRoleTargetsModal", "candidatePermanentName"],
        _ROLES_BODY,
        {"state": state, "mine": bears.permanent_id, "theirs": giant.permanent_id},
        prelude=_DOM + (
            "let modalModeTargetsSelected = new Set(); let severalTargetsShares = new Map();"
            "let severalTargetsOpenFor = null; let severalTargetsRolePicks = [];"
        ),
    )

    opened = out["opened"]
    assert opened["hidden"] is False and opened["disabled"] is True
    assert "target creature you control and target creature an opponent controls" in opened["subtitle"]
    assert opened["headings"] == ["Target 1: creature — not chosen", "Target 2: creature — not chosen"]
    assert {(role, pid) for role, pid, _name in opened["tiles"]} == {
        (0, bears.permanent_id), (0, crab.permanent_id), (1, giant.permanent_id),
    }
    assert out["afterOne"] is True and out["afterBoth"] is False
    (body,) = out["sent"]
    assert body == {"seat": 0, "action": "trigger_target_confirm",
                    "target_permanent_ids": [bears.permanent_id, giant.permanent_id]}

    response = _post(sid, body)
    assert response.status_code == 200, response.text
    game.resolve_top_of_stack()
    assert game.resolve_pending_choice("optional_pay", 0, accept=True)
    resolve_stack(game)
    assert game.controller_index_of(bears) == 1 and game.controller_index_of(giant) == 0


@needs_node
def test_a_face_down_candidate_is_named_by_its_card_to_its_controller_alone(set_pool):
    """Two face-down permanents in one list were "Face-down creature" twice to
    the player who knows which is which. Their controller is sent the card each
    hides (``hidden_card``, CR 708.5) and the tile says it; the opponent is not
    and sees the blank's name."""
    sid, _session, game = _hvh(seed=7)
    onslaught = {c.name: c for c in load_catalog() if c.name in ("Exalted Angel",)}
    angel = _put(game, 0, face_down_card(onslaught["Exalted Angel"]))
    entry = {"seat": 0, "id": angel.permanent_id, "name": FACE_DOWN_NAME}
    body = "return candidatePermanentName(INPUT.entry);"

    mine = run_app_js(["candidatePermanentName"], body,
                      {"state": _state(sid, 0), "entry": entry, "seat": 0}, prelude=_DOM)
    theirs = run_app_js(["candidatePermanentName"], body,
                        {"state": _state(sid, 1), "entry": entry, "seat": 1}, prelude=_DOM)

    assert mine == f"{FACE_DOWN_NAME} (Exalted Angel)"
    assert theirs == FACE_DOWN_NAME


# --- 4. a search that reads the hand --------------------------------------

_SEARCH_BODY = r'''
renderSearchLibraryModal(INPUT.info);
const opened = {
  title: q("searchLibraryTitle").textContent,
  handHeadingShown: !q("searchLibraryHandHeading").classList.contains("hidden"),
  hand: q("searchLibraryHandGrid").querySelectorAll(".library-card-choice").map((t) => t.dataset.key),
};
await q("searchLibraryHandGrid").querySelector(".library-card-choice").click();
await q("searchLibraryConfirmBtn").click();
return { opened, sent: SENT };
'''


@needs_node
def test_the_search_dialog_offers_the_hand_and_answers_from_it(set_pool):
    """Dark Supplicant: "Search your graveyard, hand, and/or library for a card
    named Scion of Darkness and put it onto the battlefield." The dialog drew
    the graveyard and the library and never the hand the prompt sent."""
    sid, _session, game = _hvh(seed=9)
    lgn = set_pool("LGN")
    game.players[0].library = [_CATALOG["Forest"], _CATALOG["Island"]]
    game.players[0].hand = [_CATALOG["Plains"], lgn["Scion of Darkness"]]
    _put(game, 0, lgn["Dark Supplicant"])
    clerics = [_put(game, 0, lgn[name]) for name in ("Blood Celebrant", "Earthblighter", "Deathmark Prelate")]
    result = game.activate_permanent_ability(
        0, "Dark Supplicant", cost_permanent_ids=[p.permanent_id for p in clerics],
    )
    assert result.supported, result.details
    if game.stack:
        game.resolve_top_of_stack()
    info = _state(sid, 0)["search_library"]
    assert info["legal_hand_indices"] == [1]

    out = run_app_js(
        ["renderSearchLibraryModal", "searchSlotAssignment", "searchSlotAnswers",
         "searchPicksAreOrdered"],
        _SEARCH_BODY, {"info": info},
        prelude=_DOM + (
            "let searchLibrarySelectedKey = null; let searchLibrarySelectedMulti = new Set();"
            "let searchLibrarySlotNote = ''; let searchLibraryFilter = ''; let searchLibraryShowAll = false;"
            "let searchLibraryRenderSig = null; let searchLibraryRebuild = null;"
            "function getSearchLibraryInfo() { return INPUT.info; }"
            # The destination wording reads a table (not a function) and is
            # not what this test is about.
            "function searchDestinationWords() { return { button: 'Put onto Battlefield' }; }"
            "function searchSubtitle(lead) { return lead; }"
        ),
    )

    assert out["opened"]["title"] == "Search Library, Hand, and Graveyard"
    assert out["opened"]["handHeadingShown"] is True
    assert out["opened"]["hand"] == ["hand:1"]
    (body,) = out["sent"]
    assert body == {"seat": 0, "action": "search_library_confirm", "hand_index": 1, "search_zone": "hand"}

    response = _post(sid, body)
    assert response.status_code == 200, response.text
    resolve_stack(game)
    assert any(p.card.name == "Scion of Darkness" for p in game.controlled_by(0))
    assert [c.name for c in game.players[0].hand] == ["Plains"]


# --- 5. Hollow Specter's "pay {X}" ----------------------------------------

def _two_seats():
    game = Game([PlayerState(name="Alice", library=[_CATALOG["Forest"]] * 5),
                 PlayerState(name="Bob", library=[_CATALOG["Forest"]] * 5)])
    game.enforce_mana_costs = False
    return game


def _attack_with(game, attackers, defenders, *, interactive=frozenset({0})):
    """*attackers* for seat 0 and *defenders* for seat 1, every attacker
    declared at seat 0's declare-attackers step; returns the permanents."""
    game.interactive_seats = set(interactive)
    mine = []
    for card in attackers:
        permanent = Permanent(card=card)
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        mine.append(permanent)
    for card in defenders:
        game._put_permanent_onto_battlefield(1, Permanent(card=card), None)
    resolve_stack(game)
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    return mine


def _prompts(game, seat):
    return render_prompts(PromptContext(
        game=game, viewer_seat=seat, serialize_card=_serialize_card_summary,
        seat_type=lambda s: "human",
    ))


def test_hollow_specters_offer_is_paying_x_on_the_prompt_and_in_the_log(set_pool):
    game = _two_seats()
    (specter,) = _attack_with(game, [set_pool("LGN")["Hollow Specter"]], [])
    for _ in range(3):
        swamp = Permanent(card=_CATALOG["Swamp"])
        game._put_permanent_onto_battlefield(0, swamp, None)
    assert game.declare_attackers(0, [game.battlefield_index_of(specter)], 1)[0]
    for _ in range(6):
        if game.stack:
            break
        game.advance_combat_phase()
    game.resolve_top_of_stack()

    offer = _prompts(game, 0)["pay_any_amount"]
    assert offer["pays_x"] is True and offer["options"] == [0, 1, 2, 3]
    assert "Alice may pay {X}" in game.log
    assert "Alice may pay any amount of mana" not in game.log


def test_liege_of_the_hollows_offer_is_still_any_amount():
    game = _two_seats()
    game.interactive_seats = {0, 1}
    game.arm_pending_choice("pay_any_amount", 0, card_name="Liege of the Hollows", _results={})
    assert "pays_x" not in _prompts(game, 0)["pay_any_amount"]


_PAY_X_BODY = r'''
applyPayAnyAmountPrompt(INPUT.info);
const buttons = q("promptSteps").querySelectorAll("[data-pay-mana]").map((b) => b.textContent);
await q("promptSteps").querySelector("[data-pay-mana='1']").click();
return { title: q("promptTitle").textContent, body: q("promptBody").innerHTML, buttons, sent: SENT };
'''


@needs_node
@pytest.mark.parametrize("pays_x", [True, False])
def test_the_pay_panel_says_x_when_the_card_prints_x(pays_x):
    info = {"player_seat": 0, "card_name": "Hollow Specter" if pays_x else "Liege of the Hollows",
            "minimum": 0, "maximum": 2, "options": [0, 1, 2], "default": 0}
    if pays_x:
        info["pays_x"] = True
    out = run_app_js(["applyPayAnyAmountPrompt"], _PAY_X_BODY, {"info": info}, prelude=_DOM)
    if pays_x:
        assert out["title"] == "Choose X"
        assert "you may pay {X}" in out["body"]
        assert out["buttons"] == ["X = 0", "X = 1", "X = 2"]
    else:
        assert out["title"] == "Pay how much mana?"
        assert "any amount of mana" in out["body"]
        assert out["buttons"] == ["0", "1", "2"]
    assert out["sent"] == [{"seat": 0, "action": "pay_any_amount_confirm", "number": 1}]


# --- 6. provoke: the badge and the offer -------------------------------------

def test_provoke_is_badged_printed_and_granted(set_pool):
    lgn = set_pool("LGN")
    game = _two_seats()
    elite = Permanent(card=lgn["Deftblade Elite"])
    sliver = Permanent(card=lgn["Plated Sliver"])
    bears = Permanent(card=_CATALOG["Grizzly Bears"])
    for permanent in (elite, sliver, bears):
        game._put_permanent_onto_battlefield(0, permanent, None)
    assert "Provoke" in _effective_keywords(elite, game)
    assert "Provoke" not in _effective_keywords(sliver, game)
    game._put_permanent_onto_battlefield(0, Permanent(card=lgn["Hunter Sliver"]), None)
    assert "Provoke" in _effective_keywords(sliver, game), "Hunter Sliver grants it"
    assert "Provoke" not in _effective_keywords(bears, game)


@pytest.mark.parametrize("attackers", [("Deftblade Elite",), ("Hunter Sliver",)],
                         ids=["printed", "granted"])
def test_the_provoke_offer_says_what_provoke_does(set_pool, attackers):
    """A provoke Hunter Sliver grants is the bare word on the Sliver, and the
    "may" it offers read "Provoke" and nothing more; a printed one read the
    card's whole text. Either way the offer is the ability CR 702.39a
    defines."""
    lgn = set_pool("LGN")
    game = _two_seats()
    mine = _attack_with(game, [lgn[name] for name in attackers], [_CATALOG["Grizzly Bears"]])
    assert game.declare_attackers(0, [game.battlefield_index_of(mine[-1])], 1)[0]
    (target,) = _prompts(game, 0)["trigger_target"]["candidates"]
    assert game.resolve_pending_choice("trigger_target", 0, permanent_id=target["id"])
    game.resolve_top_of_stack()

    (offer,) = _prompts(game, 0)["optional_pay"]["pending"]
    assert offer["card_text"] == f"Provoke — {PROVOKE_REMINDER}"


# --- 7. who the game is waiting on ----------------------------------------

def test_prompt_owed_by_names_the_seat_and_speaks_of_it_to_everyone_else():
    game = _two_seats()
    game.interactive_seats = {0, 1}
    assert prompt_owed_by(game, 0) is None
    game.arm_pending_choice("pay_any_amount", 0, card_name="Hollow Specter", pays_x=True, _results={})

    assert prompt_owed_by(game, 0) == {
        "seat": 0, "name": "Alice", "kind": "pay_any_amount",
        "doing": "say how much mana you pay",
    }
    assert prompt_owed_by(game, 1)["doing"] == "say how much mana they pay"


def test_the_state_says_who_owes_the_open_decision_to_both_seats(set_pool):
    sid, _session, game = _hvh(seed=11)
    game.players[1].hand = [_CATALOG["Plains"], _CATALOG["Island"], _CATALOG["Forest"]]
    game.players[0].hand = [_CATALOG["Mind Rot"]]
    game.enforce_mana_costs = False
    assert game.cast_from_hand(0, "Mind Rot", target_player_index=1).supported
    game.resolve_top_of_stack()

    for viewer in (0, 1):
        owed = _state(sid, viewer)["prompt_owed_by"]
        assert owed["seat"] == 1 and owed["kind"] == "discard", owed
    assert _state(sid, 0)["waiting_on_prompt"] is True


# --- 8. a face-down permanent in a prompt's list ----------------------------

def test_a_prompt_permanent_summary_carries_the_hidden_card_for_its_controller_alone():
    angel = {c.name: c for c in load_catalog()}["Exalted Angel"]
    game = _two_seats()
    face_down = Permanent(card=face_down_card(angel))
    face_up = Permanent(card=_CATALOG["Grizzly Bears"])
    for permanent in (face_down, face_up):
        game._put_permanent_onto_battlefield(0, permanent, None)

    mine = _prompt_permanent_summary(0, face_down, game)
    assert mine["name"] == FACE_DOWN_NAME
    assert mine["hidden_card"]["name"] == "Exalted Angel"
    assert "hidden_card" not in _prompt_permanent_summary(1, face_down, game)
    assert "hidden_card" not in _prompt_permanent_summary(None, face_down, game)
    assert "hidden_card" not in _prompt_permanent_summary(0, face_up, game)


def test_a_sacrifice_list_tells_two_face_down_creatures_apart_to_their_controller():
    catalog = {c.name: c for c in load_catalog()}
    sid, _session, game = _hvh(seed=13)
    _put(game, 0, face_down_card(catalog["Exalted Angel"]))
    _put(game, 0, face_down_card(catalog["Daru Lancer"]))
    game.players[1].hand = [catalog["Diabolic Edict"]]
    game.enforce_mana_costs = False
    assert game.cast_from_hand(1, "Diabolic Edict", target_player_index=0).supported
    game.resolve_top_of_stack()

    listed = _state(sid, 0)["sacrifice_select"]["permanents"]
    assert sorted((p["name"], p["hidden_card"]["name"]) for p in listed) == [
        (FACE_DOWN_NAME, "Daru Lancer"), (FACE_DOWN_NAME, "Exalted Angel"),
    ]


# --- 9. a cleanup discard with a second person at the table -----------------

def test_another_viewers_poll_does_not_wipe_a_cleanup_selection():
    """CR 514.1: the active player discards down to their hand size. The
    selection is the session's, one click at a time — and every state the
    *other* browser fetched between two clicks cleared it, so a seat owing two
    discards in a game with a second person could never finish choosing."""
    sid, session, game = _hvh(seed=17)
    session.current_turn = 1
    game.active_player_index = 1
    game.players[1].hand = [_CATALOG["Plains"]] * 5 + [_CATALOG["Island"]] * 4
    game.current_phase = "cleanup"
    game.current_turn_phase = "ending"
    game.current_step = "cleanup"

    first = _post(sid, {"seat": 1, "action": "cleanup_select", "hand_index": 0})
    assert first.status_code == 200, first.text
    _state(sid, 0)
    assert _state(sid, 1)["cleanup_discard"]["selected_indices"] == [0]

    second = _post(sid, {"seat": 1, "action": "cleanup_select", "hand_index": 8})
    assert second.status_code == 200, second.text
    assert len(game.players[1].hand) == 7
    assert sorted(c.name for c in game.players[1].graveyard) == ["Island", "Plains"]


# --- 10. a mana split the activating seat chooses ---------------------------

_SPLIT_BODY = r'''
const card = { name: "Goblin Clearcutter", ability_mana: [INPUT.entry], __abilityIndex: 0 };
const combination = chosenAbilityCombination(card);
const splits = manaSplits(combination.symbols, combination.count).map(manaSplitKey);
const texts = manaSplits(combination.symbols, combination.count).map(manaSplitText);
pendingManaColor = { cardName: "Goblin Clearcutter", permanentIndex: 2, targetSeat: 0,
                     abilityIndex: 0, combination };
resolvePendingManaSplit("R:2,G:1");
return { combination, splits, texts, cleared: pendingManaColor === null, sent: SENT,
         fan: chosenAbilityCombination({ ability_mana: [{ symbols: ["R", "G"], choice: true }] }) };
'''


@needs_node
def test_a_mana_split_is_offered_whole_and_sent_as_mana_combination():
    """"{T}, Sacrifice a Forest: Add three mana in any combination of {R}
    and/or {G}." (Goblin Clearcutter.) The ability's ``ability_mana`` entry
    carries ``combination: {symbols, count}`` (W2G3's wire) and the activation
    takes ``mana_combination`` ({symbol: count}); a colour fan could only ever
    send one colour for all three. Every split is a button, and the one clicked
    goes out with the activation."""
    entry = {"symbols": ["R", "G"], "choice": True,
             "combination": {"symbols": ["R", "G"], "count": 3}}
    out = run_app_js(
        ["chosenAbilityCombination", "manaSplits", "manaSplitText", "manaSplitKey",
         "resolvePendingManaSplit"],
        _SPLIT_BODY, {"entry": entry},
        prelude=_DOM + (
            "let pendingManaColor = null;"
            "function withPermanentId(body, field, seatIndex, index) {"
            " return { ...body, [field]: 100 + index }; }"
        ),
    )
    assert out["combination"] == {"symbols": ["R", "G"], "count": 3}
    assert out["splits"] == ["R:3", "R:2,G:1", "R:1,G:2", "G:3"]
    assert out["texts"] == ["{R}{R}{R}", "{R}{R}{G}", "{R}{G}{G}", "{G}{G}{G}"]
    assert out["cleared"] is True
    (body,) = out["sent"]
    assert body["action"] == "activate" and body["ability_index"] == 0
    assert body["permanent_id"] == 102
    assert body["mana_combination"] == {"R": 2, "G": 1}
    assert out["fan"] is None, "a plain colour choice is not a split"
