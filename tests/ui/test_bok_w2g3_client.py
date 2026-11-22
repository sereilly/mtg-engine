"""Betrayers of Kamigawa's hand, combat and resolution gestures, client half.

Three things wave 1 built a wire for and no browser could answer:

* **Ninjutsu** (CR 702.49a; W1G1): the hand button names the attacker to
  return (CR 601.2b) on the set picker every return cost uses, over the
  candidates the server now enumerates on the entry's ``cost_spec``; and the
  viewer's own turn asks the server to hold its declare blockers step while a
  ninjutsu waits in hand — CR 509.2's priority, which the server hands a
  person only at a step they flagged (``web/seats._self_should_hold``) — so the
  window ninjutsu lives in is reachable at all. The battlefield menu no longer
  lists the keyword line (CR 113.6j), which renumbered every later ability.
* **The graveyard cast offer** (CR 608.2g; W1G10): Toshiro Umezawa's and
  Chandra, Flame's Catalyst's "you may cast target … card from your
  graveyard", a ``copy_cast`` offer whose card is in a graveyard and whose mana
  cost is paid. The client looked for it in exile.
* **Kept mana** (CR 500.5's exception; W1G8): drawn as pool mana that pays for
  anything, counted in the total, never as "restricted".

The client functions run in bare node over payloads the server really sent
(``tests.helpers.run_app_js``), and every body they build is posted back to
the server. Betrayers of Kamigawa is ``measured``: its cards come from
``set_pool("BOK")`` and are handed to the session's game.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine.models import Permanent
from engine.restricted_mana import mana_bucket
from tests.helpers import (_mk_creature_card, _nosick, app_js_function_body, run_app_js,
                           seat_plays_first, settle)
from web.app import app, store
from web.seats import _self_should_hold

client = TestClient(app)

_APP_JS = Path(__file__).resolve().parents[2] / "web" / "static" / "app.js"

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is not on PATH; the client half cannot run",
)


def _w2g3_const(name: str) -> str:
    """The ``const NAME = …;`` statement of app.js, as written (brackets
    balanced to its closing semicolon), for a prelude: the lifted functions
    read these tables, and a paraphrase would test the paraphrase."""
    source = _APP_JS.read_text(encoding="utf-8").replace("\r\n", "\n")
    start = source.index(f"\nconst {name} = ") + 1
    depth = 0
    for offset, char in enumerate(source[start:], start):
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == ";" and depth == 0:
            return source[start:offset + 1]
    raise AssertionError(f"no end to const {name}")


def _w2g3_session():
    created = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "H", "host_colors": 2, "guest_colors": 2, "seed": 11,
    }).json()
    sid = created["session_id"]
    # Seat 0's turn 1, before the board is built (``seat_plays_first``).
    seat_plays_first(sid, 0)
    game = store.get(sid).game
    for permanent in list(game.all_permanents()):
        game.remove_from_battlefield(permanent)
    for player in game.players:
        player.hand.clear()
        player.graveyard.clear()
    return sid, game


def _w2g3_put(game, seat, card):
    permanent = _nosick(Permanent(card=card))
    game._put_permanent_onto_battlefield(seat, permanent, None)
    _nosick(permanent)
    game._sync_control()
    return permanent


def _w2g3_state(sid, seat=0):
    response = client.get(f"/api/sessions/{sid}/state?seat={seat}")
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Ninjutsu
# ---------------------------------------------------------------------------


def _w2g3_ninja_combat(set_pool, *, block_second=False, declared=True, islands=2):
    """Seat 0 attacking with two 2/2 Runners, Ninja of the Deep Hours in hand
    and *islands* Islands, holding priority in the declare blockers step;
    seat 1 has a Wall that blocks the second Runner when asked."""
    sid, game = _w2g3_session()
    lea = set_pool("LEA")
    runners = [_w2g3_put(game, 0, _mk_creature_card(f"Runner {i}", 2, 2)) for i in range(2)]
    for _ in range(islands):
        _w2g3_put(game, 0, lea["Island"])
    wall = _w2g3_put(game, 1, lea["Wall of Stone"])
    game.players[0].hand.append(set_pool("BOK")["Ninja of the Deep Hours"])
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0, 1], defending_player_index=1)[0]
    game._set_phase_and_step("combat", "declare_blockers")
    if declared:
        # Battlefield slots, blocker to attacker (``declare_blockers``).
        blocks = (
            {game.battlefield_index_of(wall): game.battlefield_index_of(runners[1])}
            if block_second else {}
        )
        assert game.declare_blockers(1, blocks)[0]
    game.priority_player_index = 0
    return sid, game, runners


def _w2g3_ninja_entry(state):
    return next(e for e in state["hand_abilities"] if e["name"] == "Ninja of the Deep Hours")


def test_w2g3_the_ninjutsu_cost_lists_the_attackers_it_may_return(set_pool):
    """The picker's candidates are the charger's (``_return_cost_candidates``):
    none before blockers are declared (CR 509.1h), the unblocked attackers
    after — a blocked one is not offered."""
    sid, _game, runners = _w2g3_ninja_combat(set_pool, declared=False)
    assert _w2g3_ninja_entry(_w2g3_state(sid))["cost_spec"]["valid_targets"] == []

    sid, game, runners = _w2g3_ninja_combat(set_pool, block_second=True)
    offered = _w2g3_ninja_entry(_w2g3_state(sid))["cost_spec"]["valid_targets"]
    assert [(o["seat"], o["index"]) for o in offered] == [
        (0, game.battlefield_index_of(runners[0]))
    ]


_W2G3_DOM = r'''
function element() {
  return {
    children: [], className: "", dataset: {}, disabled: false, title: "", textContent: "",
    classList: {
      list: new Set(),
      add(name) { this.list.add(name); },
      toggle(name, on) { if (on) this.list.add(name); else this.list.delete(name); },
    },
    listeners: {},
    addEventListener(type, fn) { this.listeners[type] = fn; },
    appendChild(child) { this.children.push(child); },
    set innerHTML(_value) { this.children = []; },
  };
}
const host = element();
const document = { createElement: () => element() };
function q(id) { return id === "handAbilities" ? host : null; }
let seat = 0;
let currentState = null;
let pendingAutoTap = null;
let pendingPermanentCost = null;
const sent = [];
const hints = [];
function sendAction(body) { sent.push(body); return Promise.resolve(); }
function renderActivationPrompt() {}
function updateActionHint(text) { hints.push(text); }
const SFX = { onError() {} };
'''

_W2G3_HAND_FUNCTIONS = [
    "handAbilityProhibition", "renderHandAbilities", "isManaRefusal", "startHandAbilityCostPrompt",
    "specIsACost", "permanentCostStep", "permanentCostVerb", "permanentCostVerbLabel",
    "handAbilityReturnsUnblockedAttacker", "permanentIdAt", "togglePermanentCost",
    "confirmPermanentCost",
]


@needs_node
def test_w2g3_the_ninjutsu_button_asks_which_attacker_returns_and_the_body_does_it(set_pool):
    """Click the lit button: the return picker opens over the unblocked
    attacker alone, says "unblocked attacker", and its confirm sends the
    button's body with ``cost_permanent_ids`` — which the server takes: the
    named Runner goes home and the Ninja's ability is on the stack."""
    sid, game, runners = _w2g3_ninja_combat(set_pool, block_second=True)
    game.enforce_mana_costs = False
    state = _w2g3_state(sid)
    out = run_app_js(
        _W2G3_HAND_FUNCTIONS,
        """
        currentState = INPUT;
        renderHandAbilities(INPUT, true);
        const button = host.children[0];
        const label = button.textContent;
        button.listeners.click();
        const picker = { ...pendingPermanentCost };
        delete picker.handAbility; delete picker.card;
        togglePermanentCost(picker.options[0].id);
        confirmPermanentCost();
        await Promise.resolve();
        return { label, disabled: button.disabled, picker, sent, after: pendingPermanentCost };
        """,
        state, prelude=_W2G3_DOM + _w2g3_const("ACTIVATION_COST_FLAGS")
        + "\n" + _w2g3_const("PERMANENT_SET_COST_VERBS"),
    )
    assert out["label"] == "Ninjutsu {1}{U}: Ninja of the Deep Hours"
    assert out["disabled"] is False
    picker = out["picker"]
    assert picker["verb"] == "return" and picker["noun"] == "unblocked attacker"
    assert picker["count"] == 1
    assert [o["id"] for o in picker["options"]] == [runners[0].permanent_id]
    assert out["after"] is None
    (body,) = out["sent"]
    assert body["action"] == "activate_hand" and body["cost_permanent_ids"] == [runners[0].permanent_id]

    response = client.post(f"/api/sessions/{sid}/action", json=body)
    assert response.status_code == 200, response.text
    assert "Runner 0" in [card.name for card in game.players[0].hand]
    assert game.stack and game.stack[-1].card.name == "Ninja of the Deep Hours"
    settle(game)
    ninja = next(p for p in game.controlled_by(0) if p.card.name == "Ninja of the Deep Hours")
    assert ninja.tapped and ninja.attacking and not ninja.blocked


@needs_node
def test_w2g3_before_blocks_the_button_says_why_on_hover(set_pool):
    """Before blockers are declared the button is dead and its tooltip is the
    server's sentence (``unpayable``) — not the line, which sent players
    looking for mana."""
    sid, _game, _runners = _w2g3_ninja_combat(set_pool, declared=False)
    state = _w2g3_state(sid)
    entry = _w2g3_ninja_entry(state)
    out = run_app_js(
        _W2G3_HAND_FUNCTIONS,
        """
        renderHandAbilities(INPUT, true);
        const button = host.children[0];
        return { title: button.title, disabled: button.disabled, said: button.dataset.unpayable };
        """,
        state, prelude=_W2G3_DOM,
    )
    assert entry["unpayable"] and out["said"] == entry["unpayable"]
    assert out["disabled"] is True
    assert out["title"].startswith(f"Not now: {entry['unpayable']}.")


_W2G3_STOP_FUNCTIONS = [
    "ninjutsuStopSteps", "ninjutsuWindowHeld", "handAbilityReturnsUnblockedAttacker",
    "handAbilityProhibition", "isCombatStep", "getCombatState",
]


@needs_node
def test_w2g3_a_ninja_in_hand_asks_for_the_declare_blockers_stop_on_its_own_turn(set_pool):
    """The stop is asked only on the viewer's own turn and only while the
    Settings toggle is on; the window it opens is held (the unflagged-step
    auto-pass stands down) only once blocks are declared and the ninjutsu is
    payable."""
    before_sid, _g, _r = _w2g3_ninja_combat(set_pool, declared=False)
    after_sid, _g, _r = _w2g3_ninja_combat(set_pool)
    broke_sid, _g, _r = _w2g3_ninja_combat(set_pool, islands=0)
    out = run_app_js(
        _W2G3_STOP_FUNCTIONS,
        """
        const ask = (state, on = true) => { ninjutsuStopOn = on; return ninjutsuStopSteps(state); };
        const held = (state, on = true) => { ninjutsuStopOn = on; return ninjutsuWindowHeld(state); };
        const theirs = { ...INPUT.before, current_turn: 1 };
        return {
          mine: ask(INPUT.before), theirs: ask(theirs), off: ask(INPUT.before, false),
          heldBefore: held(INPUT.before), heldAfter: held(INPUT.after),
          heldOff: held(INPUT.after, false), heldBroke: held(INPUT.broke),
        };
        """,
        {"before": _w2g3_state(before_sid), "after": _w2g3_state(after_sid),
         "broke": _w2g3_state(broke_sid)},
        prelude="let seat = 0; let currentState = null; let ninjutsuStopOn = true;",
    )
    assert out["mine"] == ["declare_blockers"]
    assert out["theirs"] == [] and out["off"] == []
    assert out["heldBefore"] is False
    assert out["heldAfter"] is True
    assert out["heldOff"] is False
    # No Island: the entry is unpayable, so the window is passed as before.
    assert out["heldBroke"] is False


def test_w2g3_every_action_carries_the_stop_and_the_auto_pass_respects_it():
    """Where the two readers are asked: ``selfStopSteps`` (every action body
    carries it) and ``maybeAutoPassDisabledPhase`` (the auto-pass that would
    otherwise pass the held window at once)."""
    assert "ninjutsuStopSteps()" in app_js_function_body("selfStopSteps")
    gate = app_js_function_body("maybeAutoPassDisabledPhase")
    assert "if (ninjutsuWindowHeld(state)) return;" in gate
    assert gate.index("if (ninjutsuWindowHeld(state)) return;") < gate.index("const latest = currentState;")


def _w2g3_walk_to_declare_blockers(sid, game, runner, self_stop_steps):
    """Through the routes the browser uses: the attack declared, its priority
    passed, then the ``next_phase`` the client sends in the declare blockers
    step, which makes the AI declare (`game_flow._advance_phase`)."""
    for _ in range(6):
        if game.current_step == "declare_attackers":
            break
        client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "next_phase"})
    assert game.current_step == "declare_attackers"
    body = {"seat": 0, "self_stop_steps": self_stop_steps}
    assert client.post(f"/api/sessions/{sid}/action", json={
        **body, "action": "declare_attackers", "attacker_ids": [runner.permanent_id],
    }).status_code == 200
    for _ in range(4):
        if game.current_step != "declare_attackers":
            break
        client.post(f"/api/sessions/{sid}/action", json={**body, "action": "pass_priority"})
    if game.current_step == "declare_blockers" and game.priority_player_index is None:
        assert client.post(f"/api/sessions/{sid}/action", json={
            **body, "action": "next_phase",
        }).status_code == 200


@pytest.mark.parametrize("asked", [True, False])
def test_w2g3_the_server_holds_the_step_the_client_asks_for(set_pool, asked):
    """The server half the client relies on: with "declare_blockers" in the
    body's ``self_stop_steps`` (what ``ninjutsuStopSteps`` adds), the person
    keeps CR 509.2's priority after the AI's empty declaration, the ninjutsu
    payable; without it, combat damage is dealt and the Ninja could only be
    offered afterwards."""
    sid, game = _w2g3_session()
    lea = set_pool("LEA")
    runner = _w2g3_put(game, 0, _mk_creature_card("Runner", 2, 2))
    for _ in range(2):
        _w2g3_put(game, 0, lea["Island"])
    game.players[0].hand.append(set_pool("BOK")["Ninja of the Deep Hours"])
    _w2g3_walk_to_declare_blockers(sid, game, runner, ["declare_blockers"] if asked else [])
    if asked:
        assert (game.current_step, game.priority_player_index) == ("declare_blockers", 0)
        assert game.blockers_have_been_declared()
        assert _w2g3_ninja_entry(_w2g3_state(sid))["payable"] is True
        assert game.players[1].life == 20
    else:
        assert game.players[1].life == 18


def test_w2g3_the_stop_never_holds_an_ai_seat(set_pool):
    """``_self_should_hold`` answers for a human active seat only: the stop a
    person's client asks for cannot stop the AI's own declare blockers step."""
    sid, game = _w2g3_session()
    session = store.get(sid)
    session.self_stop_steps = {"declare_blockers"}
    game.active_player_index = 0
    assert _self_should_hold(session, "declare_blockers") is True
    game.active_player_index = 1
    assert _self_should_hold(session, "declare_blockers") is False


# ---------------------------------------------------------------------------
# The graveyard cast offer (Toshiro Umezawa)
# ---------------------------------------------------------------------------


def _w2g3_toshiro_offer(set_pool):
    """Toshiro's trigger targeting the Lightning Bolt in seat 0's graveyard,
    resolving and offering the cast — with a second Lightning Bolt already in
    seat 0's exile, and a Mountain untapped."""
    sid, game = _w2g3_session()
    bok, lea = set_pool("BOK"), set_pool("LEA")
    _w2g3_put(game, 0, bok["Toshiro Umezawa"])
    _w2g3_put(game, 0, lea["Mountain"])
    bears = _w2g3_put(game, 1, lea["Grizzly Bears"])
    giant = _w2g3_put(game, 1, lea["Hill Giant"])
    game.players[0].graveyard.append(lea["Lightning Bolt"])
    game.players[0].exile.append(lea["Lightning Bolt"])
    game.players[0].hand.append(lea["Terror"])
    game.active_player_index = 0
    game.start_priority_window(0)
    game.interactive_seats = {0}
    game.enforce_mana_costs = False
    assert game.cast_from_hand(0, "Terror", target_permanent_ids=[bears.permanent_id]).supported
    owed = settle(game, defaults=False)
    assert owed.kind == "trigger_target"
    bolt_slot = next(
        t["graveyard_index"] for t in owed.data["targets"]
        if game.players[0].graveyard[t["graveyard_index"]].name == "Lightning Bolt"
    )
    assert game.confirm_trigger_target(0, seat=0, graveyard_index=bolt_slot)
    owed = settle(game, defaults=False)
    assert owed.kind == "copy_cast"
    game.enforce_mana_costs = True
    return sid, game, giant


def test_w2g3_the_graveyard_offer_names_its_graveyard_and_no_exile(set_pool):
    """The renderer found the card's place by identity, and a card definition
    is one object for every copy: the exiled twin Bolt's slot was named too."""
    sid, game, _giant = _w2g3_toshiro_offer(set_pool)
    info = _w2g3_state(sid)["copy_cast"]
    assert (info["exile_seat"], info["exile_index"]) == (None, None)
    assert (info["graveyard_seat"], info["graveyard_index"]) == (0, 0)
    assert info["free"] is False and info["exile_instead"] is True


_W2G3_COPY_PRELUDE = """
let seat = 0, sessionId = "s", currentState = null, pendingCopyCast = null;
const fetched = [];
const zoneCasts = [];
async function fetch(url) {
  fetched.push(url);
  return { ok: true, async json() { return { target_spec: { kind: "any", valid_targets: [] }, modes: [] }; } };
}
function beginZoneCast(card, zone, entry, way, opts) { zoneCasts.push({ card, zone, entry, way, opts }); }
function updateActionHint() {}
"""


@needs_node
def test_w2g3_the_offer_opens_a_paid_cast_on_the_graveyard_card_and_its_body_casts_it(set_pool):
    """"Cast it" opens the zone cast chain on the graveyard card — its spec
    asked as cast from that graveyard, its price the mana cost, not free — and
    the body that chain sends is the offer's answer. The server refuses it for
    mana with the offer kept; the Mountain tapped while the offer is open pays
    for it on the resend, and the Bolt is exiled after it resolves."""
    sid, game, giant = _w2g3_toshiro_offer(set_pool)
    state = _w2g3_state(sid)
    out = run_app_js(
        ["beginCopyCast", "beginGraveyardCopyCast", "copyCastExiledCard", "copyCastFromHand",
         "graveyardCopyCastWay", "copyCastWay", "normalizeCardName", "xLivesInManaCost",
         "carryCopyCastAnswer"],
        """
        currentState = INPUT;
        await beginCopyCast(INPUT.copy_cast);
        const cast = zoneCasts[0];
        pendingCopyCast = { slot: cast.opts.copyCastSlot };
        const body = carryCopyCastAnswer({ seat: 0, action: "cast", card_name: cast.card.name,
          target_permanent_ids: [INPUT.giant], from_zone: cast.zone, auto_tap: true });
        return { fetched, zoneCasts, body };
        """,
        {**state, "giant": giant.permanent_id},
        prelude=_W2G3_COPY_PRELUDE,
    )
    (url,) = out["fetched"]
    assert "from_zone=graveyard" in url and "card_name=Lightning+Bolt" in url
    (cast,) = out["zoneCasts"]
    assert cast["zone"] == "graveyard" and cast["opts"] == {"copyCastSlot": 0}
    assert cast["card"]["name"] == "Lightning Bolt"
    assert cast["way"]["free"] is False and cast["way"]["price"] == "{R}"
    body = out["body"]
    assert body["action"] == "copy_cast_confirm" and body["accept"] is True
    assert "auto_tap" not in body

    refused = client.post(f"/api/sessions/{sid}/action", json=body)
    assert refused.status_code == 400 and "mana" in refused.json()["detail"].lower()
    assert _w2g3_state(sid)["copy_cast"] is not None, "a refusal for mana keeps the offer"
    mountain = next(p for p in game.controlled_by(0) if p.card.name == "Mountain")
    assert client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "tap", "permanent_index": game.battlefield_index_of(mountain),
    }).status_code == 200
    response = client.post(f"/api/sessions/{sid}/action", json=body)
    assert response.status_code == 200, response.text
    settle(game)
    assert not game.is_on_battlefield(giant)
    assert [card.name for card in game.players[0].exile] == ["Lightning Bolt", "Lightning Bolt"]
    assert game.players[0].graveyard == [] or all(
        card.name != "Lightning Bolt" for card in game.players[0].graveyard
    )


@needs_node
def test_w2g3_the_offer_card_is_read_from_the_graveyard_first():
    """``copyCastExiledCard`` reads the graveyard slot the offer names before
    any exile slot, which the client used to answer "no longer in exile"."""
    out = run_app_js(
        ["copyCastExiledCard", "copyCastFromHand"],
        """
        const state = { players: [{ exile: [{ name: "Shock" }], graveyard: [{ name: "Terror" }, { name: "Lightning Bolt" }] }] };
        return [
          copyCastExiledCard({ graveyard_seat: 0, graveyard_index: 1, exile_seat: 0, exile_index: 0 }, state).name,
          copyCastExiledCard({ graveyard_seat: 0, graveyard_index: 5 }, state),
          copyCastExiledCard({ exile_seat: 0, exile_index: 0 }, state).name,
        ];
        """,
    )
    assert out == ["Lightning Bolt", None, "Shock"]


def test_w2g3_the_payment_dialog_says_mana_cost_for_a_graveyard_cast():
    body = app_js_function_body("applyMadnessPaymentPrompt")
    assert 'pendingCastFromZone === "graveyard"' in body
    assert '"mana cost"' in body


# ---------------------------------------------------------------------------
# Kept mana
# ---------------------------------------------------------------------------


_W2G3_MANA_DOM = r'''
function element() {
  return {
    children: [], className: "", title: "", _html: "",
    classList: { list: new Set(), add(n) { this.list.add(n); }, toggle(n, on) { if (on) this.list.add(n); else this.list.delete(n); } },
    addEventListener() {},
    appendChild(child) { this.children.push(child); },
    set innerHTML(value) { this._html = value; if (value === "") this.children = []; },
    get innerHTML() { return this._html; },
  };
}
const container = element();
const document = { createElement: () => element() };
function q() { return container; }
function symbolSrc() { return null; }
let debugAddManaMode = false;
const lastManaCounts = {};
'''


@needs_node
def test_w2g3_kept_mana_is_pool_mana_with_a_kept_badge_and_counts_in_the_total(set_pool):
    """Kept {G}{G} beside a creature-only {G}: the kept chips say "kept", pay
    for anything and are in the total; the creature mana stays a restricted
    chip outside it."""
    sid, game = _w2g3_session()
    player = game.players[0]
    mana_bucket(player, "kept_until_end_of_turn")["G"] = 2
    mana_bucket(player, "creature")["G"] = 1
    player.mana_pool["R"] = 1
    me = _w2g3_state(sid)["players"][0]
    assert me["restricted_mana"]["kept_until_end_of_turn"] == {"G": 2}
    out = run_app_js(
        ["renderMana", "keptManaCount", "escapeHtml"],
        """
        renderMana("selfMana", INPUT.mana_pool, 0, INPUT.restricted_mana, INPUT.restricted_mana_words);
        return container.children.map((c) => ({ cls: c.className, title: c.title, html: c.innerHTML }));
        """,
        me,
        prelude=_W2G3_MANA_DOM + _w2g3_const("MANA_ORDER") + "\n" + _w2g3_const("RESTRICTED_MANA_LABELS")
        + "\n" + _w2g3_const("KEPT_MANA_KEYS") + "\n" + _w2g3_const("KEPT_MANA_LABEL"),
    )
    total = next(c for c in out if "mana-total" in c["cls"])
    # {R} and the kept {G}{G}; the creature-only {G} is not "available".
    assert ">3<" in total["html"], total
    assert "2 kept until end of turn" in total["title"]
    kept = [c for c in out if "mana-symbol-kept" in c["cls"]]
    assert len(kept) == 1 and "mana-G" in kept[0]["cls"]
    assert ">kept<" in kept[0]["html"] and "restricted" not in kept[0]["cls"]
    assert kept[0]["title"].startswith("Pays for anything.")
    restricted = [c for c in out if "mana-symbol-restricted" in c["cls"]]
    assert len(restricted) == 1 and ">creatures only<" in restricted[0]["html"]


def test_w2g3_a_cast_paid_by_kept_mana_taps_nothing(set_pool):
    """What the click does with kept mana in the pool: the card is castable,
    the preview taps nothing, and the cast spends the kept {G}."""
    sid, game = _w2g3_session()
    lea = set_pool("LEA")
    forest = _w2g3_put(game, 0, lea["Forest"])
    game.players[0].hand.append(lea["Llanowar Elves"])
    mana_bucket(game.players[0], "kept_until_end_of_turn")["G"] = 1
    game.enforce_mana_costs = True
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    game.start_priority_window(0)
    state = _w2g3_state(sid)
    hand = state["players"][0]["hand"]
    elves = next(i for i, c in enumerate(hand) if c["name"] == "Llanowar Elves")
    assert elves in state["players"][0]["playable_hand_indices"]
    body = {"seat": 0, "action": "cast", "card_name": "Llanowar Elves"}
    plan = client.post(f"/api/sessions/{sid}/payment_plan", json=body).json()
    assert not plan.get("taps"), plan
    assert client.post(f"/api/sessions/{sid}/action", json=body).status_code == 200
    settle(game)
    assert any(p.card.name == "Llanowar Elves" for p in game.controlled_by(0))
    assert not forest.tapped
    assert not any(game.players[0].restricted_mana.get("kept_until_end_of_turn", {}).values())


def test_w2g3_the_ninjutsu_keyword_is_no_ability_of_the_permanent():
    """The battlefield menu's zone reader (CR 113.6j) reads the keyword line's
    split cost half and the expansion's reveal as hand-only; the parity census
    (`test_ability_cost_js_parity.py`) holds the whole pool to it."""
    body = app_js_function_body("abilityFunctionsOnBattlefield")
    assert re.search(r"ninjutsu", body, re.IGNORECASE)
    assert "reveal this card from your hand" in body
