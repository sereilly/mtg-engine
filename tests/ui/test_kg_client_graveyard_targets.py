"""A graveyard ability that targets, activated by a person (Carrionette).

"{2}{B}{B}: Exile this card and target creature unless that creature's
controller pays {2}. Activate only if this card is in your graveyard."

Judgment gave the graveyard a gesture (``state.graveyard_abilities``,
``activate_graveyard``) and left this one disabled: the engine's graveyard door
has taken targets and judged them since Tempest (``activation_target_refusal``
over ``activation_offer``), but nothing between the button and the engine
carried one. The payload sent a ``targets`` flag and no list to pick from, and
the route forwarded no target field — so the only activation a browser could
have sent was a bare one, which ``engine/bare_announcements.py`` answers with
the first legal creature, a choice the player never made. The census
(every activated ability of a card in a hand or a graveyard, both manifest
roles: 49 hand abilities, 8 graveyard ones) finds Carrionette the only one that
targets.

Now: the entry carries ``target_spec`` (``Game.graveyard_activation_target_spec``
— the gate's own list, narrowed by an opposing Flagbearer as the permanent
picker is), the button opens the ordinary target picker over it, and the click
sends the target with ``activate_graveyard``, which forwards it. Pinned here
from both ends: the body the client builds (lifted out of ``app.js`` and run in
node) is the body posted, and the board after it is the one CR 608.2 makes —
with the creature's controller answering "pays {2}" both ways, as an
interactive seat and as the default one.
"""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from engine import faces
from engine.activation_zones import GRAVEYARD, HAND, ability_functions_from
from engine.card_loader import load_cards, manifest_set_paths
from engine.cost_pickers import spec_is_a_cost
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec, usable_activated_abilities
from tests.helpers import _mk_card, run_app_js
from web.app import app, store

client = TestClient(app)

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)

_BEARER_SENTENCE = (
    "While an opponent is choosing targets as part of casting a spell they "
    "control or activating an ability they control, that player must choose at "
    "least one Flagbearer on the battlefield if able."
)


def _session(mode: str, seed: int = 6031):
    created = client.post("/api/sessions", json={
        "mode": mode, "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": seed,
    }).json()
    sid = created["session_id"]
    if mode == "human_vs_human":
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
    return sid, game


def _put(game, seat: int, card) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata.pop("summoning_sickness_turn", None)
    return permanent


def _board(set_pool, mode: str, *, their_lands: int = 2, theirs_extra=()):
    """Seat 0: four Swamps, a Grizzly Bears, Carrionette in the graveyard.
    Seat 1: a Grizzly Bears, a Hill Giant and *their_lands* Plains."""
    lea, tmp = set_pool("LEA"), set_pool("TMP")
    sid, game = _session(mode)
    swamps = [_put(game, 0, lea["Swamp"]) for _ in range(4)]
    mine = _put(game, 0, lea["Grizzly Bears"])
    bears = _put(game, 1, lea["Grizzly Bears"])
    giant = _put(game, 1, lea["Hill Giant"])
    extra = [_put(game, 1, card) for card in theirs_extra]
    plains = [_put(game, 1, lea["Plains"]) for _ in range(their_lands)]
    game.players[0].graveyard = [tmp["Carrionette"]]
    game.start_priority_window(0)
    return sid, game, {
        "swamps": swamps, "mine": mine, "bears": bears, "giant": giant,
        "plains": plains, "extra": extra,
    }


def _state(sid: str, seat: int = 0) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _act(sid: str, body: dict):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def _entry(sid: str) -> dict:
    return next(e for e in _state(sid)["graveyard_abilities"] if e["name"] == "Carrionette")


def _body(entry: dict, target: Permanent, game) -> dict:
    seat, _ = game.find_permanent_by_id(target.permanent_id)
    return {
        "seat": 0, "action": "activate_graveyard", "card_name": entry["name"],
        "graveyard_index": entry["graveyard_index"], "ability_index": entry["ability_index"],
        "target_seat": seat, "target_permanent_index": game.battlefield_index_of(target),
        "target_permanent_id": target.permanent_id, "auto_tap": True,
    }


def _resolve(sid: str):
    for seat in (0, 1):
        assert _act(sid, {"seat": seat, "action": "pass_priority"}).status_code == 200


# ---------------------------------------------------------------------------
# The census
# ---------------------------------------------------------------------------


def test_carrionette_is_the_only_zone_ability_that_targets():
    """Every activated ability that works from a hand or a graveyard, over both
    manifest roles. Carrionette is the one that names a target; a second
    arriving — in a hand especially, whose route takes no target at all —
    is a client and engine half to build, and this says so."""
    examined = {HAND: 0, GRAVEYARD: 0}
    targeting = []
    pool = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            pool.setdefault(card.name, card)
    # Text compiles per face: a split card's halves, each in its own right.
    for card in faces.compilation_units(list(pool.values())):
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        zone_abilities = [(HAND, a) for a in usable_activated_abilities(program, zone=HAND)]
        zone_abilities += [
            (GRAVEYARD, a) for a in program.activated_abilities
            if a.supported and a.instruction is not None
            and ability_functions_from(a) == GRAVEYARD
        ]
        for zone, ability in zone_abilities:
            examined[zone] += 1
            spec = derive_activation_spec(ability) or {}
            if spec.get("kind") not in (None, "none") and not spec_is_a_cost(spec):
                targeting.append((zone, card.name))
    assert examined[HAND] >= 40 and examined[GRAVEYARD] >= 6, examined
    assert targeting == [(GRAVEYARD, "Carrionette")], targeting


# ---------------------------------------------------------------------------
# The payload and the route
# ---------------------------------------------------------------------------


def test_the_entry_carries_the_gates_own_list(set_pool):
    sid, game, board = _board(set_pool, "human_vs_human")
    entry = _entry(sid)
    assert entry["targets"] is True and entry["payable"] is True
    spec = entry["target_spec"]
    assert spec["kind"] == "creature" and spec["requires_target"] is True
    offered = {(t["seat"], t["index"]) for t in spec["valid_targets"]}
    assert offered == {
        (0, game.battlefield_index_of(board["mine"])),
        (1, game.battlefield_index_of(board["bears"])),
        (1, game.battlefield_index_of(board["giant"])),
    }, "every creature, either side; no land"


def test_the_named_creature_is_the_one_exiled_when_its_controller_declines(set_pool):
    """The Hill Giant, not the creature a bare activation defaults to — and
    its controller, an interactive seat, is asked and declines."""
    sid, game, board = _board(set_pool, "human_vs_human")
    sent = _act(sid, _body(_entry(sid), board["giant"], game))
    assert sent.status_code == 200, sent.json()
    assert all(s.tapped for s in board["swamps"]), "{2}{B}{B} paid"
    _resolve(sid)
    offer = _state(sid, 1)["optional_pay"]["pending"]
    assert [(o["card_name"], o["player_index"], o["cost"]) for o in offer] == [
        ("Carrionette", 1, {"generic": 2})
    ]
    assert _act(sid, {"seat": 1, "action": "resolve_optional_pay", "accept": False}).status_code == 200
    assert not game.is_on_battlefield(board["giant"])
    assert [c.name for c in game.players[1].exile] == ["Hill Giant"]
    assert game.is_on_battlefield(board["bears"]), "the default creature is untouched"
    assert [c.name for c in game.players[0].exile] == ["Carrionette"]
    assert game.players[0].graveyard == []
    assert not any(p.tapped for p in board["plains"])


def test_paying_two_keeps_both_where_they_are(set_pool):
    """"…unless that creature's controller pays {2}": paid, neither is exiled
    — Carrionette stays in the graveyard and can be activated again (ruling,
    2004-10-04: "it is exiled as part of the effect and not part of the
    cost")."""
    sid, game, board = _board(set_pool, "human_vs_human")
    assert _act(sid, _body(_entry(sid), board["giant"], game)).status_code == 200
    _resolve(sid)
    assert _act(sid, {"seat": 1, "action": "resolve_optional_pay", "accept": True}).status_code == 200
    assert game.is_on_battlefield(board["giant"])
    assert [c.name for c in game.players[0].graveyard] == ["Carrionette"]
    assert game.players[0].exile == [] and game.players[1].exile == []
    assert all(p.tapped for p in board["plains"]), "the {2} was paid from their lands"
    assert any("Carrionette" == e["name"] for e in _state(sid)["graveyard_abilities"])


def test_a_default_seat_that_cannot_pay_loses_the_named_creature(set_pool):
    """The same offer to a seat nobody asks (the AI), on a board where it
    cannot pay: the default answer, and the named creature is the one gone."""
    sid, game, board = _board(set_pool, "human_vs_ai", their_lands=0)
    assert _act(sid, _body(_entry(sid), board["giant"], game)).status_code == 200
    assert _act(sid, {"seat": 0, "action": "pass_priority"}).status_code == 200
    assert not game.stack
    assert [c.name for c in game.players[1].exile] == ["Hill Giant"]
    assert game.is_on_battlefield(board["bears"])
    assert [c.name for c in game.players[0].exile] == ["Carrionette"]


def test_a_target_the_list_does_not_offer_is_refused_with_nothing_paid(set_pool):
    sid, game, board = _board(set_pool, "human_vs_human")
    body = _body(_entry(sid), board["plains"][0], game)
    refused = _act(sid, body)
    assert refused.status_code == 400
    assert not any(s.tapped for s in board["swamps"])
    assert [c.name for c in game.players[0].graveyard] == ["Carrionette"]
    assert not game.stack
    # …and a shape the graveyard door cannot carry is refused, not dropped.
    body = _body(_entry(sid), board["giant"], game)
    body["target_stack_index"] = 0
    assert _act(sid, body).status_code == 400
    assert not game.stack


def test_an_opposing_flagbearer_narrows_the_list_and_binds_the_announcement(set_pool):
    """CR 602.2b under Standard Bearer's requirement — the gate the permanent
    path asks (``activation_checks``) and this door did not: the offer is the
    bearer alone, a Hill Giant named past it is refused before {2}{B}{B} is
    paid, and the bearer named is accepted. The bearer is an invented card
    carrying the sentence, so no name table can answer."""
    bearer = _mk_card(
        name="Test Banner Herald", type_line="Creature - Human Flagbearer",
        oracle_text=_BEARER_SENTENCE, power=1, toughness=3,
    )
    sid, game, board = _board(set_pool, "human_vs_human", theirs_extra=[bearer])
    (herald,) = board["extra"]
    spec = _entry(sid)["target_spec"]
    assert [t["name"] for t in spec["valid_targets"]] == ["Test Banner Herald"]
    assert [t["id"] for t in spec["required_targets"]] == [herald.permanent_id]

    refused = _act(sid, _body(_entry(sid), board["giant"], game))
    assert refused.status_code == 400, refused.json()
    assert "Flagbearer" in refused.json()["detail"] or "must be chosen" in refused.json()["detail"]
    assert not any(s.tapped for s in board["swamps"]) and not game.stack

    assert _act(sid, _body(_entry(sid), herald, game)).status_code == 200
    _resolve(sid)
    assert _act(sid, {"seat": 1, "action": "resolve_optional_pay", "accept": False}).status_code == 200
    assert [c.name for c in game.players[1].exile] == ["Test Banner Herald"]


# ---------------------------------------------------------------------------
# The client half: the body the click builds is the body that works
# ---------------------------------------------------------------------------

_CLICK_PRELUDE = r'''
let seat = 0;
let currentState = INPUT.state;
let pendingCastTarget = null;
let pendingAutoTap = null;
const sent = [];
const hints = [];
function sendAction(body) { sent.push(body); return Promise.resolve(); }
function updateActionHint(text) { hints.push(text); }
function renderActivationPrompt() {}
function renderBoard() {}
function closeZoneRevealIfAutoOpened() {}
function clearFfaTargetingHighlights() {}
function isManaRefusal() { return false; }
function q() { return null; }
const battlefieldCanvas = null;
const SFX = { onError() {} };
'''

_CLICK_FUNCTIONS = [
    "graveyardAbilityRefusal", "graveyardAbilityTargetKind",
    "startGraveyardAbilityTargetPrompt", "graveyardAbilityTargetFields",
    "graveyardAbilityBody", "sendGraveyardAbility", "resolvePendingCastTarget",
    "pendingTargetFields", "indexValidTargets", "targetSpecOf",
    "withPermanentId", "permanentIdAt",
]


def _click(state: dict, entry: dict, target_seat: int, target_index: int) -> dict:
    return run_app_js(
        _CLICK_FUNCTIONS,
        r'''
        const entry = INPUT.entry;
        const refusal = graveyardAbilityRefusal(entry);
        startGraveyardAbilityTargetPrompt(entry);
        const prompt = pendingCastTarget && {
          kind: pendingCastTarget.targetKind, action: pendingCastTarget.castAction,
          keys: [...pendingCastTarget.validKeys].sort(),
        };
        resolvePendingCastTarget(INPUT.seat, INPUT.index);
        await Promise.resolve();
        return { refusal, prompt, sent, open: pendingCastTarget !== null };
        ''',
        {"state": state, "entry": entry, "seat": target_seat, "index": target_index},
        prelude=_CLICK_PRELUDE,
    )


@needs_node
def test_the_button_picks_the_target_and_sends_it(set_pool):
    sid, game, board = _board(set_pool, "human_vs_human")
    state = _state(sid)
    entry = _entry(sid)
    giant_index = game.battlefield_index_of(board["giant"])
    out = _click(state, entry, 1, giant_index)
    assert out["refusal"] is None, "enabled: the button can pick this target"
    assert out["prompt"]["kind"] == "creature" and out["prompt"]["action"] == "activate_graveyard"
    assert f"1-{giant_index}" in out["prompt"]["keys"]
    assert not out["open"], "the click answered the picker"
    (body,) = out["sent"]
    assert body["action"] == "activate_graveyard"
    assert body["target_permanent_id"] == board["giant"].permanent_id
    assert (body["target_seat"], body["target_permanent_index"]) == (1, giant_index)

    # …and exactly that body, sent, is the activation the board then shows.
    posted = _act(sid, {**body, "auto_tap": True})
    assert posted.status_code == 200, posted.json()
    _resolve(sid)
    assert _act(sid, {"seat": 1, "action": "resolve_optional_pay", "accept": False}).status_code == 200
    assert [c.name for c in game.players[1].exile] == ["Hill Giant"]
