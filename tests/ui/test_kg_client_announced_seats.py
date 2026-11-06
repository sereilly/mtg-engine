"""The target player a cast names beside its other targets, asked of a person.

kg/seats made the engine announce every printed "target player/opponent" and
the cast spec carry ``announced_seats`` (and Reap's ``defined_x_by_seat``),
the seats the gate admits for a seat the spec's own slots cannot carry
(``target_descriptions.ANNOUNCED_SEAT``), riding the cast's ``target_seat``.
The browser read none of it: Reap's picker sent the caster's own seat (the
pile's), Gaea's Blessing with no cards picked sent the caster's own seat, and
Fiery Justice's division sent none — so at three seats the engine's default,
the first opponent, was every answer.

Now the cascade asks for the seat first when the spec admits more than one
(``startAnnouncedSeatPrompt``), takes the one it admits otherwise, narrows the
graveyard picker to that player's pile or caps it at the X that player fixes,
and ``sendAction`` writes the seat onto the cast body
(``carryAnnouncedSeat``). Each flow below runs the client's own functions in
node over the state a free-for-all session serves, and posts the body they
send.
"""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import run_app_js
from web.app import app, store

client = TestClient(app)

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is not on PATH; the client half cannot run",
)


@pytest.fixture(scope="module")
def by_name():
    return {card.name: card for card in load_catalog()}


def _ffa(by_name, hand):
    """Three seats. Seat 0 (human, active): *hand*, and three Grizzly Bears
    and a Mountain in the graveyard. Seat 1 (AI): one Scathe Zombies (one
    black permanent), an empty graveyard. Seat 2 (AI): two Scathe Zombies."""
    created = client.post("/api/sessions", json={
        "mode": "free_for_all", "seed": 77,
        "seats": [{"name": "Me", "is_ai": False}, {"name": "Left", "is_ai": True},
                  {"name": "Right", "is_ai": True}],
    }).json()
    sid = created["session_id"]
    session = store.get(sid)
    session.pregame_phase = None
    game = session.game
    game.enforce_mana_costs = False
    for player in game.players:
        player.hand.clear()
        player.graveyard.clear()
    game.remove_all_from_battlefield(list(game.all_permanents()))
    game.stack.clear()
    for seat, count in ((1, 1), (2, 2)):
        for _ in range(count):
            zombie = Permanent(card=by_name["Scathe Zombies"])
            game._put_permanent_onto_battlefield(seat, zombie, None)
    game.players[0].hand = [by_name[name] for name in hand]
    game.players[0].graveyard = [by_name["Grizzly Bears"]] * 3 + [by_name["Mountain"]]
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, session, game


_PRELUDE = r'''
let seat = 0;
let sessionId = "s";
let currentState = INPUT.state;
let pendingCastTarget = null;
let pendingAnnouncedSeat = null;
let pendingCastModeIndex = null;
let pendingModeCollection = null;
let pendingChosenAbilityWord = null;
let pendingActivationCost = null;
let pendingAutoTap = null;
const _CAST_ACTIONS = new Set(["cast", "debug_cast_free", "debug_cast_free_opponent"]);
const sent = [];
const hints = [];
const shown = [];
const battlefieldCanvas = null;
function q() { return null; }
function renderActivationPrompt() {
  if (pendingCastTarget) {
    shown.push({
      kind: pendingCastTarget.targetKind, seatStage: !!pendingCastTarget.__announcedSeatStage,
      seats: [...(pendingCastTarget.validPlayerSeats || [])],
      graveyard: (pendingCastTarget.validGraveyard || []).map((t) => [t.seat, t.index]),
      max: pendingCastTarget.maxTargets ?? null,
    });
  }
}
function renderBoard() {}
function updateActionHint(text) { hints.push(text); }
function clearPendingHandCast() { pendingAnnouncedSeat = null; }
function clearPendingCastTargeting() { pendingCastTarget = null; }
function closeZoneRevealIfAutoOpened() {}
function clearFfaTargetingHighlights() {}
function zoneRevealSectionFor() { return null; }
function openZoneReveal() {}
function castXAnnouncedByCost() { return null; }
function specIsACost() { return false; }
function getDefaultTargetSeat() { return 1; }
function opponentStopSteps() { return []; }
function selfStopSteps() { return []; }
function activationCostAnswered() { return false; }
function carryCastMode(body) { return body; }
function carryCastZoneAndCost(body) { return body; }
function carryMadnessAnswer(body) { return body; }
function snapStateRefetchBackoff() {}
function castManaSplitFor() { return null; }
function startCastDividedPrompt(card) { shown.push({ kind: "divided", seat: pendingAnnouncedSeat }); }
async function postJson(_url, body) { sent.push(body); return {}; }
// The payment preview every paying action asks first (SCG P5; its own test is
// test_scg_p5c_client_js): here the pool pays, so the cast is sent.
async function previewPayingAction() { return null; }
function renderState() {}
'''

_FUNCTIONS = [
    "startCastTargetCascade", "announcedSeatsOf", "startAnnouncedSeatPrompt",
    "announcedSeatRole", "announcedSeatX", "carryAnnouncedSeat", "sendAction",
    "resolvePendingCastTarget", "continueCastAfterCost", "targetSpecOf", "specKind",
    "indexValidTargets", "pendingTargetFields", "normalizeCardName",
    "cardRequiresTargetRoles", "cardRequiresTargetGraveyardCreature",
    "cardRequiresSeveralTargets", "cardRequiresDividedDamage", "cardRequiresTargetLand",
    "cardRequiresTargetArtifact", "cardOffersCopyCreatureChoice", "cardOffersCopyArtifactChoice",
    "cardRequiresTargetCreature", "cardRequiresTargetPermanent", "cardRequiresTargetStackSpell",
    "startCastGraveyardCreatureTargetPrompt", "graveyardCardNoun", "cardNamesXTargets",
    "severalTargetMaximum", "toggleSeveralGraveyardTarget", "severalGraveyardHint",
    "confirmSeveralGraveyardTargets",
]


def _run(state, body, **extra):
    return run_app_js(_FUNCTIONS, body, {"state": state, **extra}, prelude=_PRELUDE)


def _hand_card(state, name):
    return next(card for card in state["players"][0]["hand"] if card["name"] == name)


def _cast(sid, body):
    response = client.post(f"/api/sessions/{sid}/action", json=body)
    assert response.status_code == 200, response.text
    client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "pass_priority"})


def test_reap_asks_the_opponent_first_and_caps_the_cards_at_their_x(by_name):
    sid, _session, game = _ffa(by_name, ["Reap"])
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    card = _hand_card(state, "Reap")
    assert card["target_spec"]["announced_seats"] == [1, 2]
    out = _run(state, r'''
        const card = INPUT.card;
        startCastTargetCascade(card);
        const seatX = [1, 2].map((s) => announcedSeatX(targetSpecOf(card), s));
        resolvePendingCastTarget(2);
        toggleSeveralGraveyardTarget(0, 0);
        toggleSeveralGraveyardTarget(0, 1);
        confirmSeveralGraveyardTargets();
        await new Promise((r) => setTimeout(r, 0));
        return { shown, seatX, sent };
    ''', card=card)
    first, picker = out["shown"][0], out["shown"][-1]
    assert first["seatStage"] and first["seats"] == [1, 2], "the opponent is asked first"
    assert out["seatX"] == [1, 2]
    assert picker["kind"] == "graveyard_creature" and picker["max"] == 2, (
        "capped at the X the chosen opponent fixes, not the default seat's 1"
    )
    (body,) = out["sent"]
    assert body["target_seat"] == 2 and body["target_permanent_indices"] == [0, 1]
    _cast(sid, body)
    assert sorted(c.name for c in game.players[0].hand) == ["Grizzly Bears", "Grizzly Bears"]


def test_gaeas_blessing_with_no_cards_names_the_player_chosen(by_name):
    sid, _session, game = _ffa(by_name, ["Gaea's Blessing"])
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    card = _hand_card(state, "Gaea's Blessing")
    assert card["target_spec"]["announced_seats"] == [0, 1, 2]
    out = _run(state, r'''
        startCastTargetCascade(INPUT.card);
        resolvePendingCastTarget(1);
        await new Promise((r) => setTimeout(r, 0));
        return { shown, sent };
    ''', card=card)
    assert out["shown"][0]["seatStage"] and out["shown"][0]["seats"] == [0, 1, 2]
    # Seat 1's graveyard is empty: nothing to pick, and the cast is sent naming
    # that player rather than the caster.
    (body,) = out["sent"]
    assert body["target_seat"] == 1 and "target_permanent_indices" not in body
    _cast(sid, body)
    assert any("Left shuffled 0" in line for line in game.log), game.log[-6:]


def test_gaeas_blessing_picks_only_from_the_chosen_players_pile(by_name):
    sid, _session, game = _ffa(by_name, ["Gaea's Blessing"])
    game.players[2].graveyard = [by_name["Grizzly Bears"], by_name["Hill Giant"]]
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    out = _run(state, r'''
        startCastTargetCascade(INPUT.card);
        resolvePendingCastTarget(2);
        return { shown };
    ''', card=_hand_card(state, "Gaea's Blessing"))
    picker = out["shown"][-1]
    assert picker["kind"] == "graveyard_creature"
    assert picker["graveyard"] == [[2, 0], [2, 1]], "seat 0's own pile is not offered"


def test_fiery_justice_names_the_opponent_chosen_for_the_life(by_name):
    sid, _session, game = _ffa(by_name, ["Fiery Justice"])
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    card = _hand_card(state, "Fiery Justice")
    assert card["target_spec"]["announced_seats"] == [1, 2]
    zombie = game.permanent_at(1, 0)
    out = _run(state, r'''
        startCastTargetCascade(INPUT.card);
        resolvePendingCastTarget(2);
        // The division prompt's own send, as confirmDividedTargets builds it.
        await sendAction({ seat, action: "cast", card_name: "Fiery Justice",
                           divided_targets: [{ seat: 1, id: INPUT.zombie, amount: 5 }] });
        return { shown, sent };
    ''', card=card, zombie=zombie.permanent_id)
    assert out["shown"][0]["seatStage"]
    assert out["shown"][-1] == {"kind": "divided", "seat": 2}
    (body,) = out["sent"]
    assert body["target_seat"] == 2
    before = game.players[2].life
    _cast(sid, body)
    assert game.players[2].life == before + 5
    assert game.players[1].life == 20


def test_one_admissible_seat_is_taken_without_asking(by_name):
    """Two seats: Reap's only opponent is the answer, and the cast says so."""
    created = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_colors": 2, "guest_colors": 2, "seed": 77,
    }).json()
    sid = created["session_id"]
    game = store.get(sid).game
    game.players[0].hand = [by_name["Reap"]]
    game.players[0].graveyard = [by_name["Grizzly Bears"]]
    game._put_permanent_onto_battlefield(1, Permanent(card=by_name["Scathe Zombies"]), None)
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    assert _hand_card(state, "Reap")["target_spec"]["announced_seats"] == [1]
    out = _run(state, r'''
        startCastTargetCascade(INPUT.card);
        return { shown, seat: pendingAnnouncedSeat };
    ''', card=_hand_card(state, "Reap"))
    assert not any(entry.get("seatStage") for entry in out["shown"])
    assert out["shown"][-1]["kind"] == "graveyard_creature" and out["shown"][-1]["max"] == 1
    assert out["seat"] == 1
