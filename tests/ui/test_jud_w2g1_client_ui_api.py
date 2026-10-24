"""What Judgment's client round made a person able to answer, held without a
browser.

Wave 1 built the server half of every Judgment prompt and was kept out of
``web/static/``; W2G1 is the round with a browser, and every branch here was
**clicked** in the running app with the state API read before and after (the
round's report says what it showed). These tests are the half that can be held
without one: the real client functions, lifted out of ``app.js`` by name and
run in node (``tests.helpers.run_app_js``) against the payload the server
really sent — and the body they build posted back to the server, as built, so
the request shape the browser sends is the one the engine is asked.

The cards are put into the session by hand: Judgment is a measured set on this
branch, so its cards are not in the catalog a session deals from.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.helpers import run_app_js
from web.app import app, store

client = TestClient(app)

STATIC = Path(__file__).resolve().parents[2] / "web" / "static"

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)


def _session(seed: int):
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
            "host_colors": 2, "guest_colors": 2, "seed": seed,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    session.pregame_phase = None
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    for player in game.players:
        player.hand.clear()
        player.graveyard.clear()
    game.remove_all_from_battlefield(list(game.all_permanents()))
    game.stack.clear()
    return sid, session, game


def _state(sid: str, seat: int = 0) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _act(sid: str, **payload):
    return client.post(f"/api/sessions/{sid}/action", json=payload)


def _post(sid: str, body: dict):
    return client.post(f"/api/sessions/{sid}/action", json=body)


# ---------------------------------------------------------------------------
# 1. ``outside_game_pick`` — the Wishes (CR 400.11b)
# ---------------------------------------------------------------------------

_PICK_PRELUDE = r'''
let seat = INPUT.seat;
let currentState = INPUT.state;
const sent = [];
let shown = null;
function sendAction(body) { sent.push(body); return Promise.resolve(); }
function renderCardPickModal(spec) { shown = spec; }
'''

_PICK_BODY = r'''
const info = getOutsideGamePickInfo(currentState);
if (!info) return { info: null };
renderOutsideGamePickModal(info);
const out = {
  title: shown.title,
  subtitle: shown.subtitle,
  names: shown.entries.map((entry) => entry.name),
  decline: shown.decline ? shown.decline.label : null,
};
if (INPUT.pick !== null) await shown.onPick(INPUT.pick);
if (INPUT.decline) await shown.decline.onClick();
out.sent = sent;
return out;
'''


def _run_pick(state: dict, seat: int, *, pick=None, decline=False) -> dict:
    return run_app_js(
        ["getOutsideGamePickInfo", "renderOutsideGamePickModal"],
        _PICK_BODY,
        {"state": state, "seat": seat, "pick": pick, "decline": decline},
        prelude=_PICK_PRELUDE,
    )


def _wish_resolving(set_pool, wish: str, sideboard: list[str]):
    sid, _session_, game = _session(6067)
    jud = set_pool("JUD")
    lea = set_pool("LEA")
    game.enforce_mana_costs = False
    game.players[0].hand = [jud[wish]]
    game.players[0].sideboard = [lea[name] for name in sideboard]
    assert _act(sid, seat=0, action="cast", card_name=wish).status_code == 200
    for seat in (0, 1):
        assert _act(sid, seat=seat, action="pass_priority").status_code == 200
    accepted = _act(sid, seat=0, action="resolve_optional_pay", card_name=wish, accept=True)
    assert accepted.status_code == 200, accepted.json()
    return sid, game


@needs_node
def test_burning_wish_shows_its_owner_the_sorceries_and_the_pick_it_sends_brings_one_in(set_pool):
    sid, game = _wish_resolving(
        set_pool, "Burning Wish", ["Lightning Bolt", "Stone Rain", "Grizzly Bears"],
    )
    # The other seat is shown nothing: the pick is the owner's (CR 400.11a).
    assert _run_pick(_state(sid, 1), 1) == {"info": None}

    shown = _run_pick(_state(sid, 0), 0, pick=0)
    assert shown["title"] == "Burning Wish", "titled by the card that asks, not by the Ring"
    assert shown["names"] == ["Stone Rain"]
    assert "revealed to every player" in shown["subtitle"]
    assert shown["decline"] is None, "a pick the accepted 'may' made mandatory has no way out"
    (body,) = shown["sent"]
    assert body == {"seat": 0, "action": "outside_game_pick_confirm", "sideboard_index": 1}

    answered = _post(sid, body)
    assert answered.status_code == 200, answered.json()
    assert [card.name for card in game.players[0].hand] == ["Stone Rain"]
    assert [card.name for card in game.players[0].sideboard] == ["Lightning Bolt", "Grizzly Bears"]
    assert _state(sid)["outside_game_pick"] is None


@needs_node
def test_death_wish_offers_any_card_unrevealed(set_pool):
    sid, game = _wish_resolving(set_pool, "Death Wish", ["Lightning Bolt", "Grizzly Bears"])
    shown = _run_pick(_state(sid, 0), 0, pick=1)
    assert shown["names"] == ["Lightning Bolt", "Grizzly Bears"]
    assert "revealed" not in shown["subtitle"]
    answered = _post(sid, shown["sent"][0])
    assert answered.status_code == 200, answered.json()
    assert [card.name for card in game.players[0].hand] == ["Grizzly Bears"]


@needs_node
def test_the_decline_button_is_drawn_exactly_where_the_engine_takes_a_decline():
    """``optional`` is the printed "may"; an empty candidate list is the one
    other case the engine accepts ``accept: false`` for (``Game.
    _resolve_outside_game_pick``) — and the seat must still be able to give it,
    or the game waits on a prompt with no button."""
    def payload(optional, names):
        return {"outside_game_pick": {
            "player_seat": 0, "card_name": "A Wish", "optional": optional, "reveal": False,
            "choices": [
                {"sideboard_index": i, "name": name, "card": {"name": name}}
                for i, name in enumerate(names)
            ],
        }}

    optional = _run_pick(payload(True, ["Shock"]), 0, decline=True)
    assert optional["decline"] == "Decline"
    assert optional["sent"] == [
        {"seat": 0, "action": "outside_game_pick_confirm", "accept": False},
    ]
    assert _run_pick(payload(False, ["Shock"]), 0)["decline"] is None
    assert _run_pick(payload(False, []), 0)["decline"] == "Continue"


# ---------------------------------------------------------------------------
# 2. ``entry_exile`` in "any number" mode — Sutured Ghoul
# ---------------------------------------------------------------------------

def _ghoul_entering(set_pool, graveyard: list[str]):
    sid, _session_, game = _session(6068)
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game.enforce_mana_costs = False
    game.players[0].hand = [jud["Sutured Ghoul"]]
    game.players[0].graveyard = [lea[name] for name in graveyard]
    assert _act(sid, seat=0, action="cast", card_name="Sutured Ghoul").status_code == 200
    for seat in (0, 1):
        assert _act(sid, seat=seat, action="pass_priority").status_code == 200
    return sid, game


@needs_node
def test_sutured_ghoul_s_confirm_is_ready_at_every_size_and_its_picks_are_taken(set_pool):
    sid, game = _ghoul_entering(set_pool, ["Grizzly Bears", "Lightning Bolt", "Hill Giant"])
    info = _state(sid)["entry_exile"]
    assert info["any_number"] is True and info["legal_indices"] == [0, 2]

    picks = [{"index": 0, "counter": None}, {"index": 2, "counter": None}]
    states = run_app_js(
        ["entryExileConfirmState"],
        "return [0, 1, 2].map((n) => entryExileConfirmState(INPUT.info, INPUT.picks.slice(0, n)));",
        {"info": info, "picks": picks},
    )
    assert states == [
        {"ready": True, "label": "Exile nothing"},
        {"ready": True, "label": "Exile 1 card"},
        {"ready": True, "label": "Exile 2 cards"},
    ]
    # What the Confirm sends (`applyEntryExilePrompt`): every pick, in order.
    answered = _act(sid, seat=0, action="entry_exile_confirm", entry_exile_picks=picks)
    assert answered.status_code == 200, answered.json()
    ghoul = next(p for p in game.controlled_by(0) if p.card.name == "Sutured Ghoul")
    assert (ghoul.effective_power, ghoul.effective_toughness) == (5, 5)
    assert [card.name for card in game.players[0].graveyard] == ["Lightning Bolt"]


@needs_node
def test_a_printed_count_still_owes_exactly_that_many():
    info = {"count": 2, "any_number": False, "counters": [], "legal_indices": [0, 1, 2]}
    states = run_app_js(
        ["entryExileConfirmState"],
        "return [0, 1, 2, 3].map((n) => entryExileConfirmState(INPUT, "
        "[0, 1, 2, 5].slice(0, n).map((index) => ({ index, counter: null }))));",
        info,
    )
    assert [state["ready"] for state in states] == [False, False, True, False]
    assert states[1]["label"] == "Confirm (1/2)"


# ---------------------------------------------------------------------------
# 3. CR 116.2d's special action — Lost in Thought and Volrath's Curse
# ---------------------------------------------------------------------------

_SPECIAL_PRELUDE = r'''
let seat = INPUT.seat;
let currentState = INPUT.state;
let pendingPermanentCost = null;
const sent = [];
const hints = [];
const SFX = { onError() {} };
function sendAction(body) { sent.push(body); return Promise.resolve(); }
function renderActivationPrompt() {}
function updateActionHint(message) { hints.push(message); }
'''

_SPECIAL_BODY = r'''
const entry = currentState.special_actions.find((e) => e.name === INPUT.name);
const opened = startSpecialActionCostPrompt(entry);
const offered = (pendingPermanentCost?.options || []).map((option) => option.name);
const purpose = pendingPermanentCost?.purposeText || null;
for (const id of INPUT.clicks) togglePermanentCost(id);
await confirmPermanentCost();
return { label: SPECIAL_ACTION_LABELS[entry.kind](entry.name), opened, offered, purpose, sent, hints };
'''


def _app_js_const(name: str) -> str:
    """One top-level ``const`` of app.js as written there, for a lifted
    function that reads it — the real table, not a copy that could drift."""
    import re

    source = (STATIC / "app.js").read_text(encoding="utf-8")
    match = re.search(r"^const " + re.escape(name) + r" = .*?;$", source, re.S | re.M)
    assert match is not None, f"app.js no longer declares {name}"
    return match.group(0)


def _special(state: dict, name: str, clicks: list) -> dict:
    return run_app_js(
        ["startSpecialActionCostPrompt", "sendSpecialAction", "togglePermanentCost",
         "confirmPermanentCost"],
        _SPECIAL_BODY,
        {"state": state, "seat": 0, "name": name, "clicks": clicks},
        prelude=_SPECIAL_PRELUDE + _app_js_const("SPECIAL_ACTION_LABELS"),
    )


def _aura_on_my_creature(set_pool, aura_name: str, creature: str, *, graveyard=(), board=()):
    from engine.aura_attachment import attach_aura
    from engine.models import Permanent

    sid, _session_, game = _session(6069)
    pool = {**set_pool("LEA"), **set_pool("TMP"), **set_pool("JUD")}
    victim = Permanent(card=pool[creature])
    game._put_permanent_onto_battlefield(0, victim, None)
    victim.metadata.pop("summoning_sickness_turn", None)  # it could attack but for the Aura
    for name in board:
        game._put_permanent_onto_battlefield(0, Permanent(card=pool[name]), None)
    aura = Permanent(card=pool[aura_name])
    game._put_permanent_onto_battlefield(1, aura, None)
    attach_aura(aura, victim)
    game._recompute_continuous_effects()
    game.players[0].graveyard = [pool[name] for name in graveyard]
    game.start_priority_window(0)
    return sid, game, victim


@needs_node
def test_lost_in_thought_s_three_cards_are_the_three_the_player_picked(set_pool):
    sid, game, bears = _aura_on_my_creature(
        set_pool, "Lost in Thought", "Grizzly Bears",
        graveyard=["Lightning Bolt", "Hill Giant", "Dark Ritual", "Giant Growth"],
    )
    assert not game.can_attack(bears, 1)
    out = _special(_state(sid), "Lost in Thought", [0, 2, 3])
    assert out["label"] == "Ignore Lost in Thought until end of turn"
    assert out["opened"] is True
    assert out["offered"] == ["Lightning Bolt", "Hill Giant", "Dark Ritual", "Giant Growth"]
    assert out["purpose"] == "ignore Lost in Thought until end of turn"
    (body,) = out["sent"]
    assert body["action"] == "special_action" and body["seat"] == 0
    assert body["special_action_kind"] == "ignore_attached_static_until_eot"
    assert body["cost_graveyard_indices"] == [0, 2, 3]

    taken = _post(sid, body)
    assert taken.status_code == 200, taken.json()
    assert [card.name for card in game.players[0].graveyard] == ["Hill Giant"]
    assert [card.name for card in game.players[0].exile] == ["Lightning Bolt", "Dark Ritual", "Giant Growth"]
    assert game.can_attack(bears, 1)


@needs_node
def test_lost_in_thought_s_confirm_waits_for_exactly_three(set_pool):
    sid, _game, _bears = _aura_on_my_creature(
        set_pool, "Lost in Thought", "Grizzly Bears",
        graveyard=["Lightning Bolt", "Hill Giant", "Dark Ritual"],
    )
    out = _special(_state(sid), "Lost in Thought", [0, 1])
    assert out["sent"] == [], "two of three is not a payment"


@needs_node
def test_volrath_s_curse_sacrifices_the_permanent_the_player_picked(set_pool):
    sid, game, giant = _aura_on_my_creature(
        set_pool, "Volrath's Curse", "Hill Giant", board=["Grizzly Bears", "Forest"],
    )
    assert not game.can_attack(giant, 1)
    state = _state(sid)
    entry = next(e for e in state["special_actions"] if e["name"] == "Volrath's Curse")
    choices = {choice["name"]: choice["permanent_id"] for choice in entry["sacrifice_choices"]}
    assert set(choices) == {"Hill Giant", "Grizzly Bears", "Forest"}

    out = _special(state, "Volrath's Curse", [choices["Grizzly Bears"], choices["Forest"]])
    assert out["offered"] == [choice["name"] for choice in entry["sacrifice_choices"]]
    (body,) = out["sent"]
    assert body["cost_permanent_id"] == choices["Forest"], "a second click swaps a count of one"

    taken = _post(sid, body)
    assert taken.status_code == 200, taken.json()
    assert [card.name for card in game.players[0].graveyard] == ["Forest"]
    assert sorted(p.card.name for p in game.controlled_by(0)) == ["Grizzly Bears", "Hill Giant"]
    assert game.can_attack(giant, 1)


# ---------------------------------------------------------------------------
# 4. Role kind ``any`` — Shieldmage Advocate
# ---------------------------------------------------------------------------

_ROLES_FUNCTIONS = [
    "indexValidTargets", "pendingTargetFields", "targetSpecOf", "permanentIdAt",
    "withPermanentId", "normalizeCardName", "roleTargetNoun", "roleChoosesAPlayer",
    "roleAcceptsAPlayer", "roleReadsAGraveyard", "roleChoosesASpell", "currentRole",
    "roleTargetsHint", "startCastRolesTargetPrompt", "chooseRolePlayer",
    "chooseRoleTarget", "advanceRoleWalk", "confirmRoleTargets",
    "handlePlayerTargetClick", "rolePermanentPicks", "restartRoleWalkForRequirement",
    "targetRequirementOf", "targetRequirementMet", "startCastChosenSourceStage",
    "sendCastWithChosenSource",
]

_ROLES_PRELUDE = r'''
let seat = INPUT.seat;
let currentState = INPUT.state;
let pendingCastTarget = null;
let _currentStack = [];
const EMPTY_TARGET_SPEC = { kind: "none", requires_target: false, valid_targets: [] };
const sent = [];
const hints = [];
function sendAction(body) { sent.push(body); return Promise.resolve(); }
function renderActivationPrompt() {}
function renderBoard() {}
function renderStack() {}
function revealRoleGraveyards() {}
function clearPendingHandCast() {}
function clearPendingCastTargeting() { pendingCastTarget = null; }
function updateActionHint(message) { hints.push(message); }
'''

_WALK_BODY = r'''
const card = currentState.players[0].battlefield.find((c) => c.name === "Shieldmage Advocate");
startCastRolesTargetPrompt(card, "activate", { sourcePermanentIndex: 0, abilityIndex: null });
const first = roleTargetsHint();
chooseRoleTarget(1, 1, "graveyard");
const second = roleTargetsHint();
if (INPUT.answer === "pill") handlePlayerTargetClick(0);
else chooseRoleTarget(0, 1);
const sourceStage = !!pendingCastTarget?.__sourceStage;
const sources = [...(pendingCastTarget?.validKeys || [])];
await sendCastWithChosenSource(
  pendingCastTarget,
  withPermanentId({ source_seat: 1, source_permanent_index: 0 }, "source_permanent_id", 1, 0),
);
return { first, second, sourceStage, sources, sent, hints };
'''


def _shieldmage(set_pool):
    from engine.models import Permanent

    sid, _session_, game = _session(6070)
    jud, lea = set_pool("JUD"), set_pool("LEA")
    advocate = Permanent(card=jud["Shieldmage Advocate"])
    game._put_permanent_onto_battlefield(0, advocate, None)
    advocate.metadata.pop("summoning_sickness_turn", None)
    game._put_permanent_onto_battlefield(0, Permanent(card=lea["Grizzly Bears"]), None)
    game._put_permanent_onto_battlefield(1, Permanent(card=lea["Hill Giant"]), None)
    game.players[1].graveyard = [lea["Lightning Bolt"], lea["Grizzly Bears"]]
    game.start_priority_window(0)
    return sid, game


def _walk(state: dict, answer: str) -> dict:
    return run_app_js(
        _ROLES_FUNCTIONS, _WALK_BODY, {"state": state, "seat": 0, "answer": answer},
        prelude=_ROLES_PRELUDE + _app_js_const("SEAT_ROLE_KINDS"),
    )


def _resolve(sid: str):
    for seat in (0, 1):
        assert _act(sid, seat=seat, action="pass_priority").status_code == 200


@needs_node
def test_shieldmage_s_any_target_role_takes_a_life_pill_and_then_asks_the_source(set_pool):
    sid, game = _shieldmage(set_pool)
    out = _walk(_state(sid), "pill")
    assert out["first"] == "Choose the card for Shieldmage Advocate (1 of 2)."
    assert out["second"] == "Choose any target for Shieldmage Advocate (2 of 2)."
    assert out["sourceStage"] is True, "the pill answered the role; the walk went on to the source"
    assert set(out["sources"]) == {"0-0", "0-1", "1-0"}
    (body,) = out["sent"]
    assert body["action"] == "activate"
    assert body["target_role_refs"] == [{"graveyard_seat": 1, "graveyard_index": 1}, {"seat": 0}]
    assert "Activated Shieldmage Advocate." in out["hints"]

    sent = _post(sid, body)
    assert sent.status_code == 200, sent.json()
    _resolve(sid)
    assert [card.name for card in game.players[1].hand][-1:] == ["Grizzly Bears"]
    giant = next(p for p in game.controlled_by(1) if p.card.name == "Hill Giant")
    game._deal_damage_to_player(game.players[0], 3, source=giant)
    assert game.players[0].life == 20


@needs_node
def test_shieldmage_s_any_target_role_takes_a_creature_too(set_pool):
    sid, game = _shieldmage(set_pool)
    out = _walk(_state(sid), "card")
    (body,) = out["sent"]
    bears = next(p for p in game.controlled_by(0) if p.card.name == "Grizzly Bears")
    assert body["target_role_refs"] == [
        {"graveyard_seat": 1, "graveyard_index": 1}, {"permanent_id": bears.permanent_id},
    ]
    sent = _post(sid, body)
    assert sent.status_code == 200, sent.json()
    _resolve(sid)
    from engine.handlers._common import apply_damage_to_creature

    giant = next(p for p in game.controlled_by(1) if p.card.name == "Hill Giant")
    apply_damage_to_creature(game, bears, 3, giant)
    assert bears.damage_marked == 0, "the shield is around the creature named"
    game._deal_damage_to_player(game.players[0], 3, source=giant)
    assert game.players[0].life == 17, "and not around its controller"
