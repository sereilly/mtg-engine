"""Mirrodin's gestures the browser could not make, each driven through the real
``app.js`` functions over the payload the server sent, and what they build
posted back.

* **Copy cast** (CR 707.12, Isochron Scepter): the ``copy_cast`` offer, its
  cast chain's body turned into ``copy_cast_confirm`` (``carryCopyCastAnswer``),
  and the decline.
* **The Shards' cost choice** (CR 602.2b through 601.2b): the prices the server
  lists (``ability_cost_alternatives``), the card's own halves on the buttons,
  and ``alternative_cost_index`` carried onto the activation it was chosen for
  (``carryAbilityCostAlternative``) — and on no other.
* **A charged ability price** (``ability_prices``): Auriok Steelshaper's {0}
  equip is shown and gated as {0}.
* **Power Conduit's counter kind**: a permanent holding two kinds asks which,
  and the answer rides ``cost_counter_kind``.
* **Fiery Gambit's run** (``flip_again`` with ``flips_won``) and **Grim
  Reminder's reveal** (``search_library`` destination ``revealed``) in words.
* **A blocker ceiling** (CR 509.1b: Vorrac Battlehorns, Stalking Tiger): the
  state view sends ``combat.blocker_ceilings`` and the second blocker is
  refused at the click.
"""
from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from engine import load_cards
from engine.card_loader import manifest_set_path
from engine.equipment import attach_equipment
from engine.models import Permanent
from tests.helpers import resolve_stack, run_app_js
from web.app import app, store

client = TestClient(app)

_MRD = {c.name: c for c in load_cards(manifest_set_path("MRD", include_measured=True))}
_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}
_MIR = {c.name: c for c in load_cards(manifest_set_path("MIR"))}
_POOL = {**_LEA, **_MIR, **_MRD}

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)


def _session(*, seed=707):
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": seed,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    session.pregame_phase = None
    game = session.game
    for player in game.players:
        player.battlefield = []
        player.hand = []
        player.graveyard = []
        player.exile = []
    game.interactive_seats = {0, 1}
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return sid, session, game


def _put(game, seat, name):
    permanent = Permanent(card=_POOL[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _state(sid, seat=0):
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _entry(state, permanent, seat=0):
    return next(c for c in state["players"][seat]["battlefield"] if c["id"] == permanent.permanent_id)


# ---------------------------------------------------------------------------
# Copy cast (Isochron Scepter)
# ---------------------------------------------------------------------------

_COPY_FUNCTIONS = ["getCopyCastInfo", "copyCastExiledCard", "copyCastWay", "carryCopyCastAnswer",
                   "zoneCastCard", "xLivesInManaCost"]
_COPY_PRELUDE = "let seat = 0; let currentState = null; let pendingCopyCast = null;"


def _scepter_offer():
    """Isochron Scepter imprinted with Lightning Bolt and activated: its
    ability resolving offers seat 0 the copy's cast."""
    sid, session, game = _session()
    game.enforce_mana_costs = False
    game.players[0].hand = [_MRD["Isochron Scepter"], _LEA["Lightning Bolt"]]
    game.start_priority_window(0)
    assert game.cast_from_hand(0, "Isochron Scepter").supported
    assert game.resolve_top_of_stack() is False, "the imprint offer holds the trigger"
    assert game.confirm_optional_pay(0, accept=True)
    (pick,) = game.pending_choices
    assert game.confirm_exile_from_hand_choice(0, 0), pick
    resolve_stack(game)
    scepter = next(p for p in game.players[0].battlefield if p.card.name == "Isochron Scepter")
    scepter.metadata["summoning_sickness_turn"] = -99
    assert game.activate_permanent_ability(
        0, "Isochron Scepter", permanent_index=game.battlefield_index_of(scepter),
        ability_index=0,
    ).supported
    assert game.resolve_top_of_stack() is False
    assert [c.kind for c in game.pending_choices] == ["copy_cast"]
    return sid, game


@needs_node
def test_the_copy_casts_chain_body_goes_out_as_the_offers_answer():
    sid, game = _scepter_offer()
    state = _state(sid)
    out = run_app_js(
        _COPY_FUNCTIONS,
        """
        currentState = INPUT.state;
        const info = getCopyCastInfo();
        const card = copyCastExiledCard(info);
        const way = copyCastWay(info);
        const priced = zoneCastCard(card, way);
        // The body the "any target" prompt builds, after carryCastZoneAndCost.
        const castBody = { seat: 0, action: "cast", card_name: card.name, target_seat: 1,
          from_zone: "exile", auto_tap: true };
        const untouched = carryCopyCastAnswer({ ...castBody });
        pendingCopyCast = { slot: info.exile_index };
        const answer = carryCopyCastAnswer({ ...castBody });
        const tap = carryCopyCastAnswer({ seat: 0, action: "activate", permanent_index: 0 });
        return { info, cardName: card.name, spec: card.target_spec.kind, price: priced.mana_cost,
          untouched, answer, tap };
        """,
        {"state": state},
        prelude=_COPY_PRELUDE,
    )
    assert out["info"]["source_name"] == "Isochron Scepter"
    assert (out["info"]["exile_seat"], out["info"]["exile_index"]) == (0, 0)
    assert (out["cardName"], out["spec"], out["price"]) == ("Lightning Bolt", "any", "{0}")
    assert out["untouched"]["action"] == "cast"
    assert out["tap"]["action"] == "activate"
    answer = out["answer"]
    assert answer["action"] == "copy_cast_confirm" and answer["accept"] is True
    assert "auto_tap" not in answer, "made mid-resolution: no priority-window payment"

    response = client.post(f"/api/sessions/{sid}/action", json=answer)
    assert response.status_code == 200, response.text
    assert _state(sid)["copy_cast"] is None
    copies = [item for item in game.stack if item.card.name == "Lightning Bolt"]
    assert len(copies) == 1 and copies[0].is_copy
    resolve_stack(game)
    assert game.players[1].life == 17
    assert [c.name for c in game.players[0].exile] == ["Lightning Bolt"], "the imprint stays"


@needs_node
def test_the_copy_cast_offer_is_read_by_its_seat_alone_and_can_be_declined():
    sid, game = _scepter_offer()
    out = run_app_js(
        _COPY_FUNCTIONS,
        """
        currentState = INPUT.state0;
        const mine = getCopyCastInfo();
        seat = 1;
        currentState = INPUT.state1;
        return { mine: !!mine, theirs: getCopyCastInfo() };
        """,
        {"state0": _state(sid, 0), "state1": _state(sid, 1)},
        prelude=_COPY_PRELUDE,
    )
    assert out == {"mine": True, "theirs": None}
    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "copy_cast_confirm", "accept": False,
    })
    assert response.status_code == 200, response.text
    assert _state(sid)["copy_cast"] is None
    assert not any(item.card.name == "Lightning Bolt" for item in game.stack)
    assert any("did not cast a copy of Lightning Bolt" in line for line in game.log)


# ---------------------------------------------------------------------------
# The Shards' cost choice
# ---------------------------------------------------------------------------

_SHARD_FUNCTIONS = [
    "abilityCostAlternativesOf", "abilityCostAlternativeAnswered", "abilityOptionAt",
    "abilityCostAlternativeLabels", "chooseAbilityCostAlternative",
    "carryAbilityCostAlternative", "getActivatedAbilityOptions", "activatedAbilityText",
    "activationColonIndex", "expandEquipLine", "expandCyclingLine",
    "abilityFunctionsOnBattlefield", "isPlaneswalkerCard", "loyaltyCostOf",
]


def _shard_prelude():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "web" / "static" / "app.js").read_text(encoding="utf-8")
    regexes = (
        src[src.index("const EQUIP_LINE_RE"):src.index("function expandEquipLine")]
        + src[src.index("const CYCLING_LINE_RE"):src.index("function expandCyclingLine")]
        + src[src.index("const LOYALTY_COST_RE"):src.index("function isPlaneswalkerCard")]
    )
    return regexes + """
let seat = 0;
let pendingAbilityCostChoice = null, pendingAbilityCostAlternative = null;
const restarted = [];
function renderActivationPrompt() {}
function startActivationPrompt(card, targetSeat, permanentIndex) { restarted.push(permanentIndex); }
"""


@needs_node
def test_a_shards_activation_offers_both_prices_and_carries_the_one_chosen():
    sid, _session_, game = _session()
    shard = _put(game, 0, "Granite Shard")
    _put(game, 0, "Mountain")
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update({"R": 1, "C": 3})
    game.start_priority_window(0)
    state = _state(sid)
    slot = next(i for i, c in enumerate(state["players"][0]["battlefield"]) if c["id"] == shard.permanent_id)
    out = run_app_js(
        _SHARD_FUNCTIONS,
        """
        const card = INPUT.card;
        const prices = abilityCostAlternativesOf(card, null);
        const labels = abilityCostAlternativeLabels(card, null, prices);
        pendingAbilityCostChoice = { card, cardName: card.name, targetSeat: 1,
          permanentIndex: INPUT.slot, abilityIndex: null, prices };
        chooseAbilityCostAlternative(1);
        // A land tapped for mana in between is another activation.
        const land = carryAbilityCostAlternative(
          { seat: 0, action: "activate", permanent_index: INPUT.slot + 1 }, {});
        const caller = {};
        const shard = carryAbilityCostAlternative(
          { seat: 0, action: "activate", permanent_index: INPUT.slot, target_seat: 1 }, caller);
        return { prices, labels, restarted, land, shard, caller, left: pendingAbilityCostAlternative };
        """,
        {"card": _entry(state, shard), "slot": slot},
        prelude=_shard_prelude(),
    )
    assert out["prices"] == ["{3}", "{R}"]
    assert out["labels"] == ["{3}, {T}", "{R}, {T}"]
    assert out["restarted"] == [slot], "the activation goes on with the cost chosen"
    assert "alternative_cost_index" not in out["land"]
    assert out["shard"]["alternative_cost_index"] == 1
    assert out["caller"]["alternative_cost_index"] == 1, "an auto-tap retry resends it"
    assert out["left"] is None

    body = {**out["shard"], "permanent_name": "Granite Shard", "permanent_id": shard.permanent_id}
    response = client.post(f"/api/sessions/{sid}/action", json=body)
    assert response.status_code == 200, response.text
    resolve_stack(game)
    assert game.players[1].life == 19
    pool = game.players[0].mana_pool
    assert (pool["R"], pool["C"]) == (0, 3), "the {R} price was paid, not the {3}"


# ---------------------------------------------------------------------------
# A charged ability price (Auriok Steelshaper)
# ---------------------------------------------------------------------------

@needs_node
def test_a_moved_equip_price_is_shown_and_gated_as_charged():
    sid, _session_, game = _session()
    game.current_turn_phase, game.current_step = "precombat_main", None
    scimitar = _put(game, 0, "Leonin Scimitar")
    battlegear = _put(game, 0, "Vulshok Battlegear")
    _put(game, 0, "Auriok Steelshaper")
    state = _state(sid)
    out = run_app_js(
        ["abilityPriceNow", "chargedActivationCost", "abilityCostShownHtml", "getActivatedAbilityCost",
         "getActivatedAbilityOptions", "activatedAbilityText", "activationColonIndex", "expandEquipLine",
         "expandCyclingLine", "abilityFunctionsOnBattlefield", "isPlaneswalkerCard", "loyaltyCostOf",
         "shouldPromptForActivationCost", "parseManaCostSymbols"],
        """
        const out = {};
        for (const card of [INPUT.scimitar, INPUT.battlegear]) {
          out[card.name] = {
            printed: getActivatedAbilityCost(card, null),
            charged: chargedActivationCost(card, null),
            prompts: shouldPromptForActivationCost(chargedActivationCost(card, null)),
            shown: abilityCostShownHtml(card, getActivatedAbilityCost(card, null), null),
          };
        }
        out.unmoved = abilityPriceNow({ name: "x" }, null);
        return out;
        """,
        {"scimitar": _entry(state, scimitar), "battlegear": _entry(state, battlegear)},
        prelude=_shard_prelude() + "function renderSymbolsInline(text) { return String(text); }",
    )
    assert out["Leonin Scimitar"] == {
        "printed": "{1}", "charged": "{0}", "prompts": False, "shown": "<s>{1}</s> {0}",
    }
    assert out["Vulshok Battlegear"]["charged"] == "{2}"
    assert out["Vulshok Battlegear"]["prompts"] is True
    assert out["unmoved"] is None


# ---------------------------------------------------------------------------
# Power Conduit's counter kind
# ---------------------------------------------------------------------------

@needs_node
def test_power_conduit_asks_which_counter_and_the_answer_rides_the_activation():
    sid, _session_, game = _session()
    conduit = _put(game, 0, "Power Conduit")
    holder = _put(game, 0, "Grizzly Bears")
    holder.metadata["plus_counters"] = 1
    holder.metadata["charge_counters"] = 2
    game._recompute_continuous_effects()
    game.start_priority_window(0)
    state = _state(sid)
    out = run_app_js(
        ["counterKindsOnPermanentId", "findPermanentInState", "confirmPermanentCost",
         "chooseCounterKind"],
        """
        currentState = INPUT.state;
        const kinds = counterKindsOnPermanentId(INPUT.holder);
        pendingPermanentCost = { card: { name: "Power Conduit" }, cardName: "Power Conduit",
          verb: "remove_counter", counter: "any", anyCounterKind: true, count: 1,
          announcesX: false, picked: [INPUT.holder], remaining: [], chosen: [],
          activation: { targetSeat: 0, permanentIndex: 0, abilityIndex: 1 } };
        confirmPermanentCost();
        const asked = pendingCounterKindChoice && pendingCounterKindChoice.kinds;
        chooseCounterKind("charge");
        return { kinds, asked, resumed, left: pendingCounterKindChoice };
        """,
        {"state": state, "holder": holder.permanent_id},
        prelude="""
let seat = 0, currentState = null, pendingPermanentCost = null, pendingCounterKindChoice = null;
const resumed = [];
function renderActivationPrompt() {}
function updateActionHint() {}
function resumeActivationAfterCost(card, activation, fields) { resumed.push(fields); }
""",
    )
    assert sorted(out["kinds"]) == ["+1/+1", "charge"]
    assert sorted(out["asked"]) == ["+1/+1", "charge"]
    (fields,) = out["resumed"]
    assert fields == {"cost_permanent_ids": [holder.permanent_id], "cost_counter_kind": "charge"}
    assert out["left"] is None

    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "activate", "permanent_name": "Power Conduit",
        "permanent_id": conduit.permanent_id, "ability_index": 1,
        "target_seat": 0, "target_permanent_id": holder.permanent_id, **fields,
    })
    assert response.status_code == 200, response.text
    resolve_stack(game)
    assert holder.metadata.get("charge_counters") == 1, holder.metadata
    assert holder.metadata.get("plus_counters") == 2, holder.metadata


@needs_node
def test_one_counter_kind_is_not_asked():
    out = run_app_js(
        ["counterKindsOnPermanentId", "findPermanentInState", "confirmPermanentCost"],
        """
        currentState = { players: [{ battlefield: [{ id: 7, name: "Myr", counters: { charge: 3 } }] }] };
        pendingPermanentCost = { card: {}, cardName: "Power Conduit", verb: "remove_counter",
          counter: "any", anyCounterKind: true, count: 1, picked: [7], remaining: [], chosen: [],
          activation: { permanentIndex: 0, abilityIndex: 0 } };
        confirmPermanentCost();
        return { asked: pendingCounterKindChoice, resumed };
        """,
        {},
        prelude="""
let seat = 0, currentState = null, pendingPermanentCost = null, pendingCounterKindChoice = null;
const resumed = [];
function renderActivationPrompt() {}
function updateActionHint() {}
function resumeActivationAfterCost(card, activation, fields) { resumed.push(fields); }
""",
    )
    assert out == {"asked": None, "resumed": [{"cost_permanent_ids": [7]}]}


# ---------------------------------------------------------------------------
# Fiery Gambit's run, Grim Reminder's reveal
# ---------------------------------------------------------------------------

_DOM_PRELUDE = """
let seat = 0, currentState = { stack: [] };
const els = {};
function q(id) {
  if (!els[id]) {
    els[id] = { id, textContent: "", innerHTML: "", disabled: false,
      classList: { add() {}, remove() {}, toggle() {} },
      querySelector() { return null; } };
  }
  return els[id];
}
function escapeHtml(value) { return String(value); }
async function sendAction() {}
"""


@needs_node
def test_the_flip_again_prompt_counts_fiery_gambits_wins_and_keeps_game_of_chaoss_stake():
    out = run_app_js(
        ["applyFlipAgainPrompt"],
        """
        applyFlipAgainPrompt({ player_seat: 0, card_name: "Fiery Gambit", stake: 0, flips_won: 2 });
        const gambit = { body: q("promptBody").textContent, steps: q("promptSteps").innerHTML };
        applyFlipAgainPrompt({ player_seat: 0, card_name: "Game of Chaos", stake: 4 });
        return { gambit, chaos: q("promptBody").textContent };
        """,
        {},
        prelude=_DOM_PRELUDE,
    )
    assert "won 2 flips in a row" in out["gambit"]["body"]
    assert "0 life" not in out["gambit"]["body"]
    assert "Stop at 2 wins" in out["gambit"]["steps"]
    assert out["chaos"] == "The next flip is for 4 life."


@needs_node
def test_a_revealing_search_says_reveal_not_confirm():
    out = run_app_js(
        ["searchDestinationWords", "searchSubtitle", "libraryDepthWords"],
        """
        const words = searchDestinationWords("revealed", false);
        return { button: words.button, sub: searchSubtitle("Choose a card", words),
          hand: searchSubtitle("Choose a card", searchDestinationWords("hand", false)) };
        """,
        {},
        prelude=_DOM_PRELUDE + """
const SEARCH_DESTINATION_WORDS = (() => {
  const src = require("fs").readFileSync(process.argv[2], "utf8");
  const start = src.indexOf("const SEARCH_DESTINATION_WORDS = {");
  const end = src.indexOf("const SEARCH_DESTINATION_FALLBACK");
  return eval("(" + src.slice(start + "const SEARCH_DESTINATION_WORDS = ".length, end).trim().replace(/;$/, "") + ")");
})();
const SEARCH_DESTINATION_FALLBACK = { into: "", button: "Confirm" };
const LIBRARY_DEPTH_ORDINALS = [""];
""",
    )
    assert out["button"] == "Reveal It"
    assert out["sub"] == "Choose a card to reveal (it stays in your library)."
    assert out["hand"] == "Choose a card to put into your hand."


# ---------------------------------------------------------------------------
# A blocker ceiling (Vorrac Battlehorns, Stalking Tiger)
# ---------------------------------------------------------------------------

def _combat(attackers, blockers, *, equip=None):
    sid, session, game = _session(seed=509)
    mine = [_put(game, 0, name) for name in attackers]
    theirs = [_put(game, 1, name) for name in blockers]
    if equip:
        horns = _put(game, 0, equip)
        assert attach_equipment(game, horns, mine[0])
        game._recompute_continuous_effects()
    game._set_phase_and_step("combat", "declare_attackers")
    game.combat_defending_player_index = 1
    game.declare_attackers(0, [game.battlefield_index_of(p) for p in mine])
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"
    return sid, game, mine, theirs


_BLOCK_PRELUDE = """
let seat = 1, currentState = null, combatBlockerDraft = {};
function getCombatState(state) { return state && state.combat; }
function iDeclareBlocks() { return true; }
function getValidBlockerAssignments(state) {
  return state.combat.legal_blocker_assignments.map((p) => ({
    blocker_index: Number(p.blocker_index), attacker_index: Number(p.attacker_index) }));
}
"""


@needs_node
@pytest.mark.parametrize("attacker, equip", [
    ("Grizzly Bears", "Vorrac Battlehorns"),
    ("Stalking Tiger", None),
])
def test_a_second_blocker_on_a_one_blocker_attacker_is_refused_at_the_click(attacker, equip):
    sid, game, mine, theirs = _combat([attacker], ["Hill Giant", "Craw Wurm"], equip=equip)
    state = _state(sid, 1)
    assert state["combat"]["blocker_ceilings"] == [{"attacker_index": 0, "max_blockers": 1}]
    out = run_app_js(
        ["blockAssignmentRejectionReason"],
        """
        currentState = INPUT.state;
        const first = blockAssignmentRejectionReason(INPUT.state, 0, 0);
        combatBlockerDraft = { 0: [0] };
        const second = blockAssignmentRejectionReason(INPUT.state, 1, 0);
        const moved = blockAssignmentRejectionReason(INPUT.state, 0, 0);
        return { first, second, moved };
        """,
        {"state": state},
        prelude=_BLOCK_PRELUDE,
    )
    assert out["first"] == "" and out["moved"] == ""
    assert "can't be blocked by more than one creature" in out["second"]
    # The server refuses the same double block the client now stops.
    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 1, "action": "declare_blockers",
        "blocker_pairs_by_id": {
            str(theirs[0].permanent_id): mine[0].permanent_id,
            str(theirs[1].permanent_id): mine[0].permanent_id,
        },
    })
    assert response.status_code == 400, response.text


def test_an_attacker_without_a_ceiling_sends_none():
    sid, _game, _mine, _theirs = _combat(["Grizzly Bears"], ["Hill Giant"])
    assert _state(sid, 1)["combat"]["blocker_ceilings"] == []
