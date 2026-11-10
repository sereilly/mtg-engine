"""An entwined cast in the browser (CR 702.42a) — the client half of
``test_mrd_w1g4_entwine_wire.py``.

The server puts the entwine offer on the hand card's own "modal" spec
(``target_spec.entwine`` beside a ``cost_offers`` entry labelled "entwine"),
because taking it is the choice of modes and is made before any mode. The
client asks "Entwine?" first (``startModalChoicePrompt`` / ``takeEntwine``);
taken, the price is announced on ``pendingCastCost`` and every mode's targets
are walked by the choose-one-or-more collection, whose captures
(``captureModeCollectionTarget``) and final send (``finishModeCollection``)
make one cast naming them all. "Entwine—Sacrifice three lands" asks which
lands first, from the picker the modal spec carries (``entwine_cost_spec``).

These run the real ``app.js`` functions over the payload the server sent and
post what they build.
"""
from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from engine import load_cards
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from tests.helpers import resolve_stack, run_app_js
from web.app import app, store

client = TestClient(app)

_MRD = {c.name: c for c in load_cards(manifest_set_path("MRD", include_measured=True))}
_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)

_FUNCTIONS = [
    "startModalChoicePrompt", "cardModeOptions", "normalizeCardName", "targetSpecOf",
    "castEntwineOffer", "entwineRefusal", "takeEntwine", "declineEntwine",
    "captureModeCollectionTarget", "finishModeCollection", "findPermanentInState",
    "permanentIdAt", "startCastPermanentSetCostPrompt", "permanentCostVerb",
    "castCostIsSeparate", "confirmPermanentCost", "counterKindsOnPermanentId",
]

_PRELUDE = r'''
let seat = 0;
let currentState = null;
let pendingModalChoice = null, pendingModeCollection = null, pendingCastCost = null,
    pendingCastModeIndex = null, pendingCastFromZone = null, pendingPermanentCost = null,
    pendingAutoTap = null, pendingCounterKindChoice = null, pendingActivationCost = null;
const EMPTY_TARGET_SPEC = { kind: "none", requires_target: false, valid_targets: [] };
const _CAST_ACTIONS = new Set(["cast", "debug_cast_free", "debug_cast_free_opponent"]);
const PERMANENT_SET_COST_VERBS = [["tap_cost", "tap"], ["return_cost", "return"]];
const sent = [];
const hints = [];
const prompted = [];
function sendAction(body) { sent.push(JSON.parse(JSON.stringify(body))); return Promise.resolve(); }
function renderActivationPrompt() {}
function updateActionHint(text, error) { hints.push([text, !!error]); }
function clearPendingHandCast() {}
function isManaRefusal() { return false; }
// The collection's own walk: each mode's prompt is the test's to answer, so
// opening one only records which; past the last mode the cast is finished.
function promptNextModeTarget() {
  const run = pendingModeCollection;
  if (!run) return;
  if (run.cursor >= run.order.length) { finishModeCollection(); return; }
  prompted.push(run.order[run.cursor]);
}
'''


def _session(hand, mine, theirs, graveyard=()):
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 4242,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    session.pregame_phase = None
    game = session.game
    game.enforce_mana_costs = False
    pool = {**_LEA, **_MRD}
    game.players[0].hand = [pool[name] for name in hand]
    game.players[0].battlefield = [Permanent(card=pool[name]) for name in mine]
    game.players[1].battlefield = [Permanent(card=pool[name]) for name in theirs]
    game.players[0].graveyard = [pool[name] for name in graveyard]
    game.players[1].hand = []
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game._sync_control()
    game.start_priority_window(0)
    return sid, game


def _state(sid, seat=0):
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _hand_card(state, name):
    return next(c for c in state["players"][0]["hand"] if c["name"] == name)


@needs_node
def test_entwine_is_asked_before_the_modes_and_walks_every_one():
    """Blinding Beam entwined: "Entwine?" before any mode; taken, the {1}
    is announced, mode 0's "Tap two target creatures" is answered by the
    several-target picker's ids — one creature on each battlefield — and
    mode 1's by a seat, and one cast posts both: it taps both creatures and
    locks the named player's untap."""
    # Four Plains: the {1} entwine is offered only where the pool and the
    # board can pay it on top of the spell ({2}{W}).
    sid, game = _session(
        ["Blinding Beam"], ["Grizzly Bears"] + ["Plains"] * 4, ["Hill Giant", "Craw Wurm"],
    )
    giant, wurm = game.players[1].battlefield
    state = _state(sid)
    out = run_app_js(
        _FUNCTIONS,
        """
        currentState = INPUT.state;
        const card = INPUT.state.players[0].hand.find((c) => c.name === "Blinding Beam");
        startModalChoicePrompt(card, "cast");
        const asked = { entwine: pendingModalChoice.entwine.offer.symbols,
          refusal: entwineRefusal(pendingModalChoice) };
        takeEntwine();
        const announced = JSON.parse(JSON.stringify(pendingCastCost));
        const firstPrompt = prompted.slice();
        // Mode 0 picked across two battlefields: the AI's Giant and my Bears
        // (W2G6b — a mode's several targets travel by id).
        const mine = INPUT.state.players[0].battlefield[0].id;
        captureModeCollectionTarget({ seat: 0, action: "cast",
          card_name: "Blinding Beam", target_seat: 1, target_permanent_ids: [INPUT.giant, mine] });
        captureModeCollectionTarget({ seat: 0, action: "cast", card_name: "Blinding Beam",
          target_seat: 1 });
        return { asked, announced, firstPrompt, prompted, mine,
          hints, sent, collecting: pendingModeCollection };
        """,
        {"state": state, "giant": giant.permanent_id, "wurm": wurm.permanent_id},
        prelude=_PRELUDE,
    )
    assert out["asked"] == {"entwine": "{1}", "refusal": ""}
    assert out["announced"] == {"optional_cost_payments": {"{1}": 1}}
    assert out["firstPrompt"] == [0]
    assert out["prompted"] == [0, 1]
    assert out["collecting"] is None
    (body,) = out["sent"]
    assert body["optional_cost_payments"] == {"{1}": 1}
    assert body["mode_choices"] == [
        {"index": 0, "target_seat": 1, "permanent_ids": [giant.permanent_id, out["mine"]]},
        {"index": 1, "target_seat": 1},
    ]

    response = client.post(f"/api/sessions/{sid}/action", json=body)
    assert response.status_code == 200, response.text
    game._settle()
    resolve_stack(game)
    bears = game.players[0].battlefield[0]
    assert giant.tapped and bears.tapped and not wurm.tapped, game.log
    assert [lock.seat for lock in game.untap_step_locks] == [1]


@needs_node
def test_a_sacrifice_entwine_asks_which_lands_and_a_graveyard_mode_sends_its_slot():
    """Betrayal of Flesh: "Entwine—Sacrifice three lands." The modal spec
    carries the lands that may pay (``entwine_cost_spec``); the three chosen
    ride ``cost_permanent_ids``, then mode 0 names the creature by id and
    mode 1's graveyard card goes by its slot alone — never by the id of the
    permanent in the same numbered battlefield slot."""
    sid, game = _session(
        ["Betrayal of Flesh"], ["Swamp", "Swamp", "Swamp", "Swamp"], ["Hill Giant"],
        graveyard=["Grizzly Bears"],
    )
    swamps = game.players[0].battlefield[:3]
    (giant,) = game.players[1].battlefield
    state = _state(sid)
    spec = _hand_card(state, "Betrayal of Flesh")["target_spec"]
    assert spec["entwine"] == "sacrifice three lands"
    assert spec["entwine_cost_spec"]["count"] == 3
    assert len(spec["entwine_cost_spec"]["valid_targets"]) == 4
    out = run_app_js(
        _FUNCTIONS,
        """
        currentState = INPUT.state;
        const card = INPUT.state.players[0].hand.find((c) => c.name === "Betrayal of Flesh");
        startModalChoicePrompt(card, "cast");
        takeEntwine();
        const picker = { verb: pendingPermanentCost.verb, count: pendingPermanentCost.count,
          options: pendingPermanentCost.options.length };
        const beforeLands = prompted.slice();
        pendingPermanentCost.picked = INPUT.swamps;
        confirmPermanentCost();
        captureModeCollectionTarget({ seat: 0, action: "cast", card_name: card.name,
          target_seat: 1, permanent_index: 0 });
        captureModeCollectionTarget({ seat: 0, action: "cast", card_name: card.name,
          target_seat: 0, permanent_index: 0 });
        return { picker, beforeLands, prompted, sent };
        """,
        {"state": state, "swamps": [p.permanent_id for p in swamps]},
        prelude=_PRELUDE,
    )
    assert out["picker"] == {"verb": "sacrifice", "count": 3, "options": 4}
    assert out["beforeLands"] == [], "the lands are asked before any mode"
    assert out["prompted"] == [0, 1]
    (body,) = out["sent"]
    assert body["optional_cost_payments"] == {"sacrifice three lands": 1}
    assert body["cost_permanent_ids"] == [p.permanent_id for p in swamps]
    assert body["mode_choices"] == [
        {"index": 0, "target_seat": 1, "permanent_index": 0, "permanent_id": giant.permanent_id},
        {"index": 1, "target_seat": 0, "permanent_index": 0},
    ]

    response = client.post(f"/api/sessions/{sid}/action", json=body)
    assert response.status_code == 200, response.text
    game._settle()
    resolve_stack(game)
    assert not game.is_on_battlefield(giant)
    names = sorted(p.card.name for p in game.players[0].battlefield)
    assert names == ["Grizzly Bears", "Swamp"], (names, game.log)


@needs_node
def test_entwine_is_refused_where_a_mode_has_no_target_and_declining_shows_the_modes():
    """CR 700.2a: with no creature card in the graveyard Betrayal of Flesh can
    destroy a creature but not entwine — the button says why and the take is
    refused; "Choose one mode" opens the ordinary mode buttons."""
    sid, _game = _session(["Betrayal of Flesh"], ["Swamp"] * 3, ["Hill Giant"])
    out = run_app_js(
        _FUNCTIONS,
        """
        currentState = INPUT.state;
        const card = INPUT.state.players[0].hand.find((c) => c.name === "Betrayal of Flesh");
        startModalChoicePrompt(card, "cast");
        const refusal = entwineRefusal(pendingModalChoice);
        takeEntwine();
        const stillAsking = !!pendingModalChoice && !pendingModalChoice.entwine.declined;
        declineEntwine();
        return { refusal, stillAsking, declined: pendingModalChoice.entwine.declined,
          collecting: !!pendingModeCollection, cost: pendingCastCost, hints };
        """,
        {"state": _state(sid)},
        prelude=_PRELUDE,
    )
    assert "no legal target" in out["refusal"]
    assert out["stillAsking"] is True and out["declined"] is True
    assert out["collecting"] is False and out["cost"] is None
    assert any("can't be entwined" in text for text, _error in out["hints"])


@needs_node
def test_a_card_without_entwine_is_asked_for_its_mode_alone():
    sid, _game = _session(["Healing Salve"], [], [])
    out = run_app_js(
        _FUNCTIONS,
        """
        currentState = INPUT.state;
        const card = INPUT.state.players[0].hand.find((c) => c.name === "Healing Salve");
        startModalChoicePrompt(card, "cast");
        return { entwine: pendingModalChoice.entwine || null, modes: pendingModalChoice.modes.length };
        """,
        {"state": _state(sid)},
        prelude=_PRELUDE,
    )
    assert out == {"entwine": None, "modes": 2}
