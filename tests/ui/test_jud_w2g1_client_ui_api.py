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
    "sendCastWithChosenSource", "roleGraveyardOrderNote",
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


# ---------------------------------------------------------------------------
# 5. Cost flag ``library_bottom_cost`` — Battlefield Scrounger
# ---------------------------------------------------------------------------

_PICKER_PRELUDE = r'''
let seat = INPUT.seat;
let currentState = INPUT.state;
let pendingPermanentCost = null;
let pendingCastCost = INPUT.pendingCastCost || null;
let pendingAutoTap = null;
const sent = [];
const hints = [];
const resumed = [];
const continued = [];
const SFX = { onError() {} };
const EMPTY_TARGET_SPEC = { kind: "none", requires_target: false, valid_targets: [] };
function sendAction(body) { sent.push(body); return Promise.resolve(); }
function renderActivationPrompt() {}
function updateActionHint(message) { hints.push(message); }
function resumeActivationAfterCost(card, activation, fields) { resumed.push({ activation, fields }); }
function startCastCostPrompt() { return false; }
function continueCastAfterCost(card) { continued.push({ card: card.name, cost: pendingCastCost }); }
'''

_PICKER_FUNCTIONS = [
    "targetSpecOf", "castCostSpec", "specIsACost", "graveyardCardNoun",
    "activationGraveyardCostSpec", "startActivationGraveyardCostPrompt",
    "startZoneWayCostPrompt", "normalizeCardName", "togglePermanentCost",
    "confirmPermanentCost", "sendSpecialAction",
]


def _run_picker(body: str, payload: dict) -> dict:
    return run_app_js(
        _PICKER_FUNCTIONS, body, payload,
        prelude=_PICKER_PRELUDE + _app_js_const("ACTIVATION_COST_FLAGS"),
    )


_SCROUNGER_BODY = r'''
const card = currentState.players[0].battlefield.find((c) => c.name === "Battlefield Scrounger");
const opened = startActivationGraveyardCostPrompt(card, card.name, 0, 0, null);
const verb = pendingPermanentCost?.verb;
const offered = (pendingPermanentCost?.options || []).map((option) => option.name);
for (const slot of INPUT.clicks) togglePermanentCost(slot);
await confirmPermanentCost();
return { opened, verb, offered, resumed, hints };
'''


@needs_node
def test_battlefield_scrounger_puts_the_three_picked_cards_on_the_bottom_in_order(set_pool):
    from engine.models import Permanent

    sid, _session_, game = _session(6071)
    jud, lea = set_pool("JUD"), set_pool("LEA")
    scrounger = Permanent(card=jud["Battlefield Scrounger"])
    game._put_permanent_onto_battlefield(0, scrounger, None)
    scrounger.metadata.pop("summoning_sickness_turn", None)
    pile = ["Lightning Bolt", "Hill Giant", "Dark Ritual", "Giant Growth",
            "Forest", "Island", "Swamp", "Plains"]
    game.players[0].graveyard = [lea[name] for name in pile]
    game.start_priority_window(0)

    # Swamp, then Lightning Bolt and Island — with a change of mind on the way.
    out = _run_picker(_SCROUNGER_BODY, {"state": _state(sid), "seat": 0,
                                        "clicks": [6, 0, 4, 4, 5]})
    assert out["opened"] is True and out["verb"] == "bottom"
    assert out["offered"] == pile
    assert "in order" in out["hints"][0]
    (resume,) = out["resumed"]
    assert resume["fields"] == {"cost_graveyard_indices": [6, 0, 5]}

    activated = _act(sid, seat=0, action="activate", permanent_id=scrounger.permanent_id,
                     **resume["fields"])
    assert activated.status_code == 200, activated.json()
    assert [card.name for card in game.players[0].library[-3:]] == ["Swamp", "Lightning Bolt", "Island"]
    assert [card.name for card in game.players[0].graveyard] == [
        "Hill Giant", "Dark Ritual", "Giant Growth", "Forest", "Plains",
    ]


# ---------------------------------------------------------------------------
# 6. Flashback costs that take permanents or graveyard cards
# ---------------------------------------------------------------------------

_ZONE_COST_BODY = r'''
const entry = currentState.castable_from_zones.find((e) => e.name === INPUT.name);
const way = entry.ways.find((w) => w.keyword === "flashback");
const card = currentState.players[0].graveyard[entry.index];
const opened = startZoneWayCostPrompt(card, way);
const offered = (pendingPermanentCost?.options || []).map((option) => option.name);
const announcesX = !!pendingPermanentCost?.announcesX;
for (const id of INPUT.clicks) togglePermanentCost(id);
await confirmPermanentCost();
return { opened, offered, announcesX, continued, choice: way.cost_choice };
'''


def _flashback_board(set_pool, *, graveyard: list[str], board: list[str]):
    from engine.models import Permanent

    sid, _session_, game = _session(6072)
    pool = {**set_pool("LEA"), **set_pool("ODY"), **set_pool("TOR"), **set_pool("JUD")}
    game.players[0].graveyard = [pool[name] for name in graveyard]
    for name in board:
        permanent = Permanent(card=pool[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata.pop("summoning_sickness_turn", None)
    game.start_priority_window(0)
    return sid, game


def _zone_cast(sid: str, name: str, clicks: list) -> dict:
    return _run_picker(_ZONE_COST_BODY, {"state": _state(sid), "seat": 0, "name": name,
                                         "clicks": clicks})


@needs_node
def test_flash_of_insight_exiles_the_blue_cards_picked_and_x_is_their_number(set_pool):
    sid, game = _flashback_board(
        set_pool, graveyard=["Flash of Insight", "Lightning Bolt", "Counterspell",
                             "Ancestral Recall", "Lord of Atlantis"],
        board=["Island", "Island"],
    )
    game.enforce_mana_costs = False
    choice_slots = {c["name"]: c["index"] for c in _zone_cast(sid, "Flash of Insight", [])["choice"]["choices"]}
    assert set(choice_slots) == {"Counterspell", "Ancestral Recall", "Lord of Atlantis"}, (
        "the blue cards, the spell itself withheld (CR 601.2a)"
    )
    out = _zone_cast(sid, "Flash of Insight", [choice_slots["Counterspell"], choice_slots["Lord of Atlantis"]])
    assert out["opened"] is True and out["announcesX"] is True
    (cont,) = out["continued"]
    assert cont["cost"] == {"cost_graveyard_indices": [2, 4], "x_value": 2}

    cast = _act(sid, seat=0, action="cast", card_name="Flash of Insight", from_zone="graveyard",
                alternative_cost=True, **cont["cost"])
    assert cast.status_code == 200, cast.json()
    assert [card.name for card in game.players[0].exile] == ["Counterspell", "Lord of Atlantis"]
    assert "Ancestral Recall" in [card.name for card in game.players[0].graveyard]


@needs_node
def test_firecat_blitz_sacrifices_the_mountains_picked(set_pool):
    sid, game = _flashback_board(
        set_pool, graveyard=["Firecat Blitz"], board=["Mountain", "Mountain", "Mountain"],
    )
    game.enforce_mana_costs = False
    mountains = [p.permanent_id for p in game.controlled_by(0)]
    out = _zone_cast(sid, "Firecat Blitz", [mountains[0], mountains[2]])
    assert out["offered"] == ["Mountain"] * 3
    (cont,) = out["continued"]
    assert cont["cost"] == {"alternative_cost_permanent_ids": [mountains[0], mountains[2]], "x_value": 2}

    cast = _act(sid, seat=0, action="cast", card_name="Firecat Blitz", from_zone="graveyard",
                alternative_cost=True, **cont["cost"])
    assert cast.status_code == 200, cast.json()
    assert [p.permanent_id for p in game.controlled_by(0) if p.card.name == "Mountain"] == [mountains[1]]
    for seat in (0, 1):
        _act(sid, seat=seat, action="pass_priority")
    assert len([p for p in game.controlled_by(0) if p.card.name != "Mountain"]) == 2, "X = 2 Cats"


@needs_node
def test_battle_screech_taps_the_three_white_creatures_picked(set_pool):
    sid, game = _flashback_board(
        set_pool, graveyard=["Battle Screech"],
        board=["Savannah Lions", "Savannah Lions", "Savannah Lions", "Savannah Lions"],
    )
    lions = [p.permanent_id for p in game.controlled_by(0)]
    out = _zone_cast(sid, "Battle Screech", [lions[3], lions[1], lions[0]])
    assert out["announcesX"] is False
    (cont,) = out["continued"]
    assert cont["cost"] == {"alternative_cost_permanent_ids": [lions[3], lions[1], lions[0]]}
    cast = _act(sid, seat=0, action="cast", card_name="Battle Screech", from_zone="graveyard",
                alternative_cost=True, **cont["cost"])
    assert cast.status_code == 200, cast.json()
    tapped = {p.permanent_id for p in game.controlled_by(0) if p.tapped}
    assert tapped == {lions[0], lions[1], lions[3]}


@needs_node
def test_a_short_pick_of_a_fixed_count_is_not_sent(set_pool):
    sid, _game = _flashback_board(
        set_pool, graveyard=["Battle Screech"],
        board=["Savannah Lions", "Savannah Lions", "Savannah Lions"],
    )
    out = _zone_cast(sid, "Battle Screech", [1])
    assert out["continued"] == [], "two short of 'tap three' is not a payment (CR 601.2h)"


_CONTINUE_PRELUDE = r'''
let seat = 0;
let pendingAutoTap = null;
let cleared = 0;
const hints = [];
function startCastTargetCascade() { return false; }
function normalizeCardName(card) { return card.name; }
function getDefaultTargetSeat() { return 1; }
function sendAction() { return Promise.reject(new Error(INPUT.error)); }
function updateActionHint(message) { hints.push(message); }
function renderActivationPrompt() {}
function clearPendingHandCast() { cleared += 1; }
'''


@needs_node
def test_a_cast_refused_for_mana_after_its_cost_was_picked_opens_the_auto_tap():
    """``continueCastAfterCost`` ended the cast on any refusal — so a flashback
    whose Mountains had just been chosen, refused only because the lands were
    untapped, threw the choice away with the error. A mana refusal now opens
    the auto-tap the plain cast opens, keeping the cast for its retry."""
    body = r'''
continueCastAfterCost({ name: "Firecat Blitz" });
await new Promise((resolve) => setTimeout(resolve, 0));
return { autoTap: pendingAutoTap && pendingAutoTap.actionBody, cleared, hints };
'''
    funcs = ["continueCastAfterCost", "isManaRefusal"]
    mana = run_app_js(funcs, body, {"error": "insufficient mana for Firecat Blitz's flashback cost ({R}{R})"},
                      prelude=_CONTINUE_PRELUDE)
    assert mana["autoTap"] == {"seat": 0, "action": "cast", "card_name": "Firecat Blitz", "target_seat": 1}
    assert mana["cleared"] == 0
    other = run_app_js(funcs, body, {"error": "no legal target"}, prelude=_CONTINUE_PRELUDE)
    assert other["autoTap"] is None and other["cleared"] == 1


# ---------------------------------------------------------------------------
# 7. Casting from an opponent's graveyard — Shaman's Trance
# ---------------------------------------------------------------------------

def test_an_opened_card_in_an_opponent_s_graveyard_carries_its_cast_spec(set_pool):
    """The opponent's pile is serialized for its owner, so its cards carry no
    target spec, and a click on Lightning Bolt sent a bare cast — no target
    prompt at all. The entry now carries the card as this seat would cast it,
    and the client's click hands that card to the cast chain."""
    from engine.models import Permanent
    from tests.helpers import app_js_function_body

    sid, _session_, game = _session(6073)
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game.enforce_mana_costs = False
    game.players[0].hand = [jud["Shaman's Trance"]]
    game.players[1].graveyard = [lea["Lightning Bolt"], lea["Forest"]]
    giant = Permanent(card=lea["Hill Giant"])
    game._put_permanent_onto_battlefield(1, giant, None)
    game.start_priority_window(0)
    assert _act(sid, seat=0, action="cast", card_name="Shaman's Trance").status_code == 200
    for seat in (0, 1):
        assert _act(sid, seat=seat, action="pass_priority").status_code == 200

    state = _state(sid)
    entries = {e["name"]: e for e in state["castable_from_zones"]}
    bolt = entries["Lightning Bolt"]
    assert bolt["owner_seat"] == 1
    assert "target_spec" not in state["players"][1]["graveyard"][0], "the pile is the owner's"
    assert bolt["card"]["target_spec"]["kind"] == "any"
    assert entries["Forest"]["card"]["name"] == "Forest"
    assert "zoneEntry?.card || card" in app_js_function_body("renderZoneCards")

    cast = _act(sid, seat=0, action="cast", card_name="Lightning Bolt", from_zone="graveyard",
                target_permanent_id=giant.permanent_id)
    assert cast.status_code == 200, cast.json()
    for seat in (0, 1):
        _act(sid, seat=seat, action="pass_priority")
    assert "Hill Giant" in [card.name for card in game.players[1].graveyard]
    assert [card.name for card in game.players[1].graveyard].count("Lightning Bolt") == 1


# ---------------------------------------------------------------------------
# 8. ``choose_card_name``'s bound — Cabal Therapy
# ---------------------------------------------------------------------------

_NAME_PRELUDE = r'''
const answers = INPUT.search;
async function fetch(url) {
  const query = decodeURIComponent(url.split("query=")[1].split("&")[0]);
  return { ok: true, json: async () => answers[query.toLowerCase()] || { cards: [] } };
}
'''


@needs_node
def test_cabal_therapy_s_bound_is_shown_and_a_land_name_is_not_sent(set_pool):
    sid, _session_, game = _session(6074)
    jud = set_pool("JUD")
    game.enforce_mana_costs = False
    game.players[0].hand = [jud["Cabal Therapy"]]
    game.start_priority_window(0)
    assert _act(sid, seat=0, action="cast", card_name="Cabal Therapy", target_seat=1).status_code == 200
    for seat in (0, 1):
        assert _act(sid, seat=seat, action="pass_priority").status_code == 200
    info = _state(sid)["choose_card_name"]
    assert info["excluded_card_type"] == "land"

    # What the catalog search the client asks answers, keyed as the client's
    # stub looks it up (the route itself matches case-insensitively).
    search = {
        name.lower(): client.get("/api/cards/search", params={"query": name, "limit": 20}).json()
        for name in ("forest", "Lightning Bolt")
    }
    out = run_app_js(
        ["chooseCardNameBound", "chooseCardNameBarred"],
        "return { bound: chooseCardNameBound(INPUT.info), "
        "forest: await chooseCardNameBarred(INPUT.info, 'forest'), "
        "bolt: await chooseCardNameBarred(INPUT.info, 'Lightning Bolt'), "
        "unknown: await chooseCardNameBarred(INPUT.info, 'Not A Card') };",
        {"info": info, "search": search},
        prelude=_NAME_PRELUDE,
    )
    assert out["bound"] == "a nonland card name"
    assert out["forest"] == "Forest is a land card: Cabal Therapy names a nonland card name."
    assert out["bolt"] is None and out["unknown"] is None
    # The engine agrees with both answers.
    assert _act(sid, seat=0, action="choose_card_name_confirm", card_name="Forest").status_code == 400
    named = _act(sid, seat=0, action="choose_card_name_confirm", card_name="Lightning Bolt")
    assert named.status_code == 200, named.json()


@needs_node
def test_the_other_printed_bounds_read_as_the_card_prints_them():
    out = run_app_js(
        ["chooseCardNameBound"],
        "return INPUT.map((info) => chooseCardNameBound(info));",
        [{}, {"card_type": "creature"}, {"exclude_basic_land_names": True},
         {"card_type": "artifact"}],
    )
    assert out == [
        "a card name", "a creature card name",
        "a card name other than a basic land card name", "an artifact card name",
    ]


# ---------------------------------------------------------------------------
# The click list: what clicking the wave-1 branches turned up
# ---------------------------------------------------------------------------

def _board(set_pool, seed: int, mine=(), theirs=(), *, my_graveyard=(), their_graveyard=()):
    from engine.models import Permanent

    sid, _session_, game = _session(seed)
    pool = {**set_pool("LEA"), **set_pool("JUD")}
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = Permanent(card=pool[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata.pop("summoning_sickness_turn", None)
            placed[seat].append(permanent)
    game.players[0].graveyard = [pool[name] for name in my_graveyard]
    game.players[1].graveyard = [pool[name] for name in their_graveyard]
    game._recompute_continuous_effects()
    game.start_priority_window(0)
    return sid, game, placed


@needs_node
def test_a_granted_ability_is_offered_once_not_twice(set_pool):
    """``oracle_text`` is the effective text, which already carries every
    granted line, and ``activatedAbilityText`` appended ``granted_abilities``
    as well: Scathe Zombies under Zombie Master offered "{B}: Regenerate" twice,
    and a Swamp under Riftstone Portal opened a menu of two "{T}: Add {G} or
    {W}" buttons — with no way to tap it for {B} — in place of its W/G/B fan."""
    sid, _game, _placed = _board(
        set_pool, 6075, mine=["Zombie Master", "Scathe Zombies", "Swamp"],
        my_graveyard=["Riftstone Portal"],
    )
    battlefield = {c["name"]: c for c in _state(sid)["players"][0]["battlefield"]}
    zombies, swamp = battlefield["Scathe Zombies"], battlefield["Swamp"]
    assert zombies["granted_abilities"], "the grant is listed apart from the text"
    assert swamp["produced_mana"] == ["W", "G", "B"]

    texts = run_app_js(
        ["activatedAbilityText"],
        "return INPUT.map((card) => activatedAbilityText(card).split('\\n'));",
        [zombies, swamp],
    )
    assert [line.lower() for line in texts[0]] == ["{b}: regenerate this permanent."]
    assert len([line for line in texts[1] if "{G} or {W}" in line]) == 1
    assert texts[1][0].startswith("("), "the basic land's own {B} line stays reminder text"


_WALK_ONLY_BODY = r'''
const card = currentState.players[0].battlefield.find((c) => c.name === INPUT.name);
startCastRolesTargetPrompt(card, "activate", { sourcePermanentIndex: 0, abilityIndex: null });
const hints = [roleTargetsHint()];
for (const [s, i] of INPUT.clicks) {
  chooseRoleTarget(s, i, "graveyard");
  hints.push(roleTargetsHint());
}
return hints;
'''


@needs_node
def test_an_advocate_s_pile_walk_says_it_is_in_pile_order(set_pool):
    """Nullmage Advocate's two cards are a walk over one pile in its order
    (``later_in_same_graveyard_role``): the newest card does not glow for the
    first pick, and nothing said why. The hint now does — and its third slot
    is named "artifact or enchantment", not "permanent"."""
    sid, _game, _placed = _board(
        set_pool, 6076, mine=["Nullmage Advocate"], theirs=["Sol Ring"],
        their_graveyard=["Lightning Bolt", "Grizzly Bears", "Dark Ritual"],
    )
    hints = run_app_js(
        _ROLES_FUNCTIONS, _WALK_ONLY_BODY,
        {"state": _state(sid), "seat": 0, "name": "Nullmage Advocate", "clicks": [[1, 0], [1, 2]]},
        prelude=_ROLES_PRELUDE + _app_js_const("SEAT_ROLE_KINDS"),
    )
    assert hints[0] == (
        "Choose the first card for Nullmage Advocate (1 of 3). "
        "Cards from one graveyard are chosen oldest first (the rightmost card is the oldest)."
    )
    assert hints[1].startswith("Choose the second card for Nullmage Advocate (2 of 3). It must")
    assert hints[2] == "Choose the artifact or enchantment for Nullmage Advocate (3 of 3)."


@needs_node
def test_mist_of_stagnation_s_confirm_waits_for_one_per_graveyard_card(set_pool):
    """The permanent-set modal ignored ``at_least``: Confirm sent a short
    answer, the engine kept the prompt, and the modal — hidden on the click —
    never came back. It now says how many, marks which are tapped, and is
    ready only at the count the engine takes."""
    sid, game, placed = _board(
        set_pool, 6077, mine=["Mist of Stagnation", "Island", "Grizzly Bears"],
        theirs=["Hill Giant"], my_graveyard=["Lightning Bolt", "Dark Ritual"],
    )
    for permanent in placed[0][1:] + placed[1]:
        permanent.tapped = True
    # Both seats are people; a turn started outside an action has not been
    # told so yet (the action dispatch is what marks them).
    game.interactive_seats = {0, 1}
    game.active_player_index = 1
    game.start_turn(0)  # the upkeep trigger resolves into the prompt
    info = _state(sid)["permanent_set_choice"]
    assert (info["up_to"], info["at_least"]) == (2, 2)

    out = run_app_js(
        ["permanentSetChoiceCountText", "permanentSetChoiceConfirmState"],
        "return { text: permanentSetChoiceCountText(INPUT), "
        "states: [0, 1, 2].map((n) => permanentSetChoiceConfirmState(INPUT, n)) };",
        info,
    )
    assert out["text"] == "Choose exactly 2."
    assert out["states"] == [
        {"ready": False, "label": "Confirm (0/2)"},
        {"ready": False, "label": "Confirm (1/2)"},
        {"ready": True, "label": "Confirm (2/2)"},
    ]
    island, giant = placed[0][1], placed[1][0]
    short = _act(sid, seat=0, action="permanent_set_choice_confirm",
                 target_permanent_ids=[island.permanent_id])
    assert short.status_code == 400, "the engine refuses what Confirm no longer sends"
    done = _act(sid, seat=0, action="permanent_set_choice_confirm",
                target_permanent_ids=[island.permanent_id, giant.permanent_id])
    assert done.status_code == 200, done.json()
    assert not island.tapped and not giant.tapped and placed[0][2].tapped


def test_grave_consequences_asks_the_second_seat_only_after_the_first(set_pool):
    """"Each player may exile …" queues one pick per seat, answered in turn
    order (CR 101.4) — the answer action takes the oldest. Seat 1 was shown
    its picker at once, and its Confirm was a bare "not your choice"; now it
    sees nothing until seat 0 has answered, and then its own pick."""
    sid, session, game = _session(6078)
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game.enforce_mana_costs = False
    game.players[0].hand = [jud["Grave Consequences"]]
    game.players[0].graveyard = [lea["Lightning Bolt"], lea["Hill Giant"]]
    game.players[1].graveyard = [lea["Counterspell"]]
    game.start_priority_window(0)
    assert _act(sid, seat=0, action="cast", card_name="Grave Consequences").status_code == 200
    for seat in (0, 1):
        assert _act(sid, seat=seat, action="pass_priority").status_code == 200

    first, second = _state(sid, 0), _state(sid, 1)
    assert first["graveyard_exile_pick"]["player_seat"] == 0
    assert second["graveyard_exile_pick"] is None
    assert second["waiting_on_prompt"] is True, "seat 1 waits rather than acts"

    assert _act(sid, seat=0, action="graveyard_exile_confirm", graveyard_indices=[0]).status_code == 200
    then = _state(sid, 1)["graveyard_exile_pick"]
    assert then["player_seat"] == 1 and then["legal_indices"] == [0]
    assert _act(sid, seat=1, action="graveyard_exile_confirm", graveyard_indices=[]).status_code == 200
    assert [card.name for card in game.players[0].exile] == ["Lightning Bolt"]
    assert game.players[0].life == 19 and game.players[1].life == 19
