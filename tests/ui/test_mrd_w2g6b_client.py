"""The gestures wave 2 added after the first client round, driven through the
real ``app.js`` functions over the payload the server sent, and what they
build posted back.

* **Liar's Pendulum's guess** (``guess_named_card``): the guesser alone is
  asked "Is a card named X in Y's hand?", answered on
  ``guess_named_card_confirm`` with ``accept``.
* **Shared Fate's choice** (``opponent_library_draw``, three seats): a button
  per opponent with the library size, answered with ``option_index``.
* **"Don't copy"** (Clone; W2G4's ``decline_copy``): the copy picker offers
  declining, and the cast goes out naming no copy target.
* **Viridian Joiner's amount**: ``ability_mana`` carries ``amount`` where a
  board count multiplies a pip, and the hint names the mana made.
* **What a choice is for**: Fatespinner's ``mode_choice`` carries a
  ``question`` and whose ability asks it; a trigger's target prompt carries
  the trigger's printed line.
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
_POOL = {**_LEA, **_MRD}

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)


def _session(*, seats=None, seed=909):
    if seats:
        created = client.post("/api/sessions", json={
            "mode": "free_for_all", "seed": seed,
            "seats": [{"name": name, "is_ai": False, "colors": 2} for name in seats],
        }).json()
    else:
        created = client.post("/api/sessions", json={
            "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
            "host_colors": 2, "guest_colors": 2, "seed": seed,
        }).json()
    sid = created["session_id"]
    if not seats:
        client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    session.pregame_phase = None
    game = session.game
    for player in game.players:
        player.battlefield = []
        player.hand = []
        player.graveyard = []
        player.exile = []
    game.interactive_seats = set(range(len(game.players)))
    game.enforce_mana_costs = False
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
function updateActionHint() {}
"""


@needs_node
def test_the_pendulum_guess_is_asked_of_the_guesser_and_answered_with_accept():
    sid, _session_, game = _session()
    pendulum = _put(game, 0, "Liar's Pendulum")
    game.players[0].hand = [_LEA["Grizzly Bears"]]
    game.start_priority_window(0)
    assert game.activate_permanent_ability(
        0, "Liar's Pendulum", permanent_index=game.battlefield_index_of(pendulum),
        ability_index=0, target_player_index=1,
    ).supported
    assert game.confirm_choose_card_name(0, "Grizzly Bears")
    out = run_app_js(
        ["getGuessNamedCardInfo", "applyGuessNamedCardPrompt"],
        """
        currentState = INPUT.state0;
        const host = getGuessNamedCardInfo();
        seat = 1;
        currentState = INPUT.state1;
        const info = getGuessNamedCardInfo();
        applyGuessNamedCardPrompt(info);
        return { host, info, body: q("promptBody").textContent, steps: q("promptSteps").innerHTML };
        """,
        {"state0": _state(sid, 0), "state1": _state(sid, 1)},
        prelude=_DOM_PRELUDE,
    )
    assert out["host"] is None, "only the guesser is asked"
    assert out["info"]["named"] == "Grizzly Bears" and "cards" not in out["info"]
    assert out["body"] == "Is a card named Grizzly Bears in Host's hand?"
    assert 'data-guess-named="yes"' in out["steps"] and 'data-guess-named="no"' in out["steps"]
    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 1, "action": "guess_named_card_confirm", "accept": True,
    })
    assert response.status_code == 200, response.text
    assert _state(sid, 1)["guess_named_card"] is None
    assert [c.kind for c in game.pending_choices] == ["optional_pay"], "the reveal is asked next"


@needs_node
def test_shared_fate_asks_whose_library_with_the_sizes_and_takes_the_index():
    sid, _session_, game = _session(seats=["Alice", "Bob", "Carol"])
    _put(game, 0, "Shared Fate")
    game.players[1].library = [_LEA["Plains"]] * 3
    game.players[2].library = [_LEA["Mountain"]] * 2
    game._draw_with_replacements(game.players[0], 1)
    out = run_app_js(
        ["getOpponentLibraryDrawInfo", "applyOpponentLibraryDrawPrompt"],
        """
        currentState = INPUT.state;
        const info = getOpponentLibraryDrawInfo();
        applyOpponentLibraryDrawPrompt(info);
        return { info, steps: q("promptSteps").innerHTML, title: q("promptTitle").textContent };
        """,
        {"state": _state(sid, 0)},
        prelude=_DOM_PRELUDE,
    )
    assert out["info"]["options"] == ["Bob", "Carol"]
    assert out["info"]["library_sizes"] == [3, 2]
    assert "Bob (3 cards in library)" in out["steps"] and "Carol (2 cards in library)" in out["steps"]
    assert out["title"] == "Shared Fate — exile instead of drawing"
    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "opponent_library_draw_confirm", "option_index": 1,
    })
    assert response.status_code == 200, response.text
    assert [c.name for c in game.players[2].exile] == ["Mountain"]
    entries = [e for e in _state(sid, 0)["castable_from_zones"] if e["zone"] == "exile"]
    assert [(e["owner_seat"], e["name"]) for e in entries] == [(2, "Mountain")]
    assert _state(sid, 2)["players"][2]["exile"] == ["<hidden>"], "its owner sees a card back"


_COPY_FUNCTIONS = [
    "cardOffersCopyCreatureChoice", "cardOffersCopyArtifactChoice", "castOffersCopyDecline",
    "declineCopyCast", "targetSpecOf",
]
_COPY_PRELUDE = """
let seat = 0, pendingCastTarget = null, pendingAutoTap = null;
const EMPTY_TARGET_SPEC = { kind: "none", requires_target: false, valid_targets: [] };
const _CAST_ACTIONS = new Set(["cast", "debug_cast_free", "debug_cast_free_opponent"]);
const sent = [];
function sendAction(body) { sent.push(JSON.parse(JSON.stringify(body))); return Promise.resolve(); }
function clearPendingCastTargeting() { pendingCastTarget = null; }
function clearPendingHandCast() {}
function updateActionHint() {}
function renderActivationPrompt() {}
function isManaRefusal() { return false; }
"""


@needs_node
@pytest.mark.parametrize("decline", [True, False])
def test_clone_may_decline_to_copy_and_still_copies_when_told(decline):
    sid, _session_, game = _session()
    giant = _put(game, 1, "Hill Giant")
    game.players[0].hand = [_LEA["Clone"]]
    game.start_priority_window(0)
    state = _state(sid)
    clone = next(c for c in state["players"][0]["hand"] if c["name"] == "Clone")
    out = run_app_js(
        _COPY_FUNCTIONS,
        """
        pendingCastTarget = { card: INPUT.clone, cardName: "Clone", castAction: "cast", targetKind: "creature" };
        const offered = castOffersCopyDecline(pendingCastTarget);
        const activation = castOffersCopyDecline({ ...pendingCastTarget, castAction: "activate" });
        declineCopyCast();
        await Promise.resolve();
        return { offered, activation, sent, left: pendingCastTarget };
        """,
        {"clone": clone},
        prelude=_COPY_PRELUDE,
    )
    assert clone["target_spec"]["optional"] is True and clone["target_spec"]["requires_target"] is True
    assert out["offered"] is True and out["activation"] is False and out["left"] is None
    (body,) = out["sent"]
    assert body == {"seat": 0, "action": "cast", "card_name": "Clone", "decline_copy": True}
    if not decline:
        body = {"seat": 0, "action": "cast", "card_name": "Clone",
                "target_seat": 1, "target_permanent_id": giant.permanent_id}
    response = client.post(f"/api/sessions/{sid}/action", json=body)
    assert response.status_code == 200, response.text
    game._settle()
    resolve_stack(game)
    game._settle()
    names = [p.card.name for p in game.players[0].battlefield]
    if decline:
        assert names == [] and "Clone" in [c.name for c in game.players[0].graveyard], game.log
    else:
        (copy,) = game.players[0].battlefield
        assert copy.effective_card.name == "Hill Giant", game.log


@needs_node
def test_viridian_joiners_mana_is_sent_with_its_amount_and_named_in_the_hint():
    from engine.equipment import attach_equipment

    sid, _session_, game = _session()
    joiner = _put(game, 0, "Viridian Joiner")
    scimitar = _put(game, 0, "Leonin Scimitar")
    assert attach_equipment(game, scimitar, joiner)
    game._recompute_continuous_effects()
    state = _state(sid)
    entry = next(c for c in state["players"][0]["battlefield"] if c["name"] == "Viridian Joiner")
    assert entry["ability_mana"] == [{"symbols": ["G"], "choice": False, "amount": 2}]
    out = run_app_js(
        ["activatedHint"],
        """
        return [activatedHint("Viridian Joiner", INPUT.mana),
                activatedHint("Llanowar Elves", { symbols: ["G"], choice: false }),
                activatedHint("Birds of Paradise", { symbols: ["W", "U"], choice: true }),
                activatedHint("Rod of Ruin", null)];
        """,
        {"mana": entry["ability_mana"][0]},
    )
    assert out == [
        "Tapped Viridian Joiner for {G}{G}.", "Tapped Llanowar Elves for {G}.",
        "Activated Birds of Paradise.", "Activated Rod of Ruin.",
    ]
    llanowar = _put(game, 0, "Llanowar Elves")
    plain = next(c for c in _state(sid)["players"][0]["battlefield"] if c["id"] == llanowar.permanent_id)
    assert plain["ability_mana"] == [{"symbols": ["G"], "choice": False}], "a fixed pip carries no amount"


def test_fatespinners_choice_says_it_is_a_skip_and_whose():
    sid, _session_, game = _session()
    _put(game, 1, "Fatespinner")
    game.current_phase = "beginning"
    game.current_turn_phase, game.current_step = "beginning", "upkeep"
    game.resolve_upkeep(0)
    info = _state(sid, 0)["mode_choice"]
    assert info["question"] == "Choose the step or phase you skip this turn."
    assert info["controller_name"] == "Joiner"


def test_a_trigger_target_prompt_carries_the_triggers_line():
    sid, session, game = _session()
    _put(game, 0, "Confusion in the Ranks")
    _put(game, 1, "Hill Giant")
    game.players[0].hand = [_LEA["Grizzly Bears"]]
    game.start_priority_window(0)
    assert game.cast_from_hand(0, "Grizzly Bears").supported
    for _ in range(4):
        if game.pending_choices:
            break
        game.resolve_top_of_stack()
    info = _state(sid, 0)["trigger_target"]
    assert info is not None, [c.kind for c in game.pending_choices]
    assert "shares a card type with it" in info["ability_text"]
    assert "controller_seat" not in info, "its own controller chooses"
