""""As an additional cost to cast this spell, discard X cards" in the browser
(CR 601.2b, CR 107.3a) — the Dreams of Torment — and Insidious Dreams' search
that puts the X cards it finds on top "in any order".

The cost spec's ``count`` is the printed 1, and the discard picker was sized
by it: a person named one card, an X prompt followed, and the engine
discarded the rest by its own default. The spec carries ``announces_x`` (the
flag "Sacrifice X lands" carries): the picker takes any number, the number
taken is the X announced, and no X prompt follows. These run the real
``app.js`` functions over the spec the server sent and post what they build.

The search half: the engine puts the found cards on top in the order the
answer lists them, the first on top, and the confirm used to sort its picks
into library order — so the order the searcher chose was never sent.
"""
from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from tests.helpers import app_js_function_body, resolve_stack, run_app_js
from web.app import app, store

client = TestClient(app)

_POOL: dict = {}
for _card in load_cards(manifest_set_paths(include_measured=True)):
    _POOL.setdefault(_card.name, _card)

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)

_PICKER = [
    "targetSpecOf", "castCostSpec", "specIsACost", "castCostIsSeparate",
    "discardCostOptions", "discardXPickerFields", "castXAnnouncedByCost",
    "normalizeCardName", "startCastDiscardCostPrompt", "payDiscardCost",
    "confirmDiscardCost", "finishDiscardCost",
]
# What those functions reach for that touches the page, recorded.
_PICKER_PRELUDE = """
const EMPTY_TARGET_SPEC = { kind: "none", requires_target: false, valid_targets: [] };
const ACTIVATION_COST_FLAGS = ["sacrifice_cost", "discard_cost", "exile_cost", "tap_cost", "return_cost"];
let seat = 0;
let pendingDiscardCost = null;
let pendingCastCost = null;
let pendingAutoTap = null;
const hints = [];
const sent = [];
let continued = null;
const renderActivationPrompt = () => {};
const updateActionHint = (text) => hints.push(text);
const clearPendingHandCast = () => {};
const isManaRefusal = () => false;
const resumeActivationAfterCost = () => { throw new Error("not an activation"); };
const continueCastAfterCost = (card, castAction) => { continued = { card: card.name, castAction }; };
const sendAction = async (body) => { sent.push(body); };
"""


def _session(hand, *, graveyard=(), lands=("Swamp", "Swamp", "Swamp", "Swamp")):
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 107,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    session.pregame_phase = None
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    game.players[0].battlefield = [Permanent(card=_POOL[name]) for name in lands]
    game.players[1].battlefield = [Permanent(card=_POOL["Grizzly Bears"])]
    game.players[0].hand = [_POOL[name] for name in hand]
    game.players[0].graveyard = [_POOL[name] for name in graveyard]
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, game


def _state(sid, seat=0):
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


@needs_node
@pytest.mark.parametrize("picks", [(1, 2), ()], ids=["x-two", "x-zero"])
def test_restless_dreams_discards_the_cards_picked_and_x_is_how_many(picks):
    """Two creature cards in the graveyard bound the picker at two (X target
    cards is exactly X, CR 601.2c); picking two announces X = 2 on the cost
    fields the target prompt then sends, and picking none is X = 0."""
    sid, game = _session(
        ["Restless Dreams", "Island", "Forest", "Mountain"],
        graveyard=["Grizzly Bears", "Hill Giant", "Shock"],
    )
    out = run_app_js(
        _PICKER,
        """
        const card = INPUT.state.players[0].hand[0];
        startCastDiscardCostPrompt(card);
        const opened = { announcesX: pendingDiscardCost.announcesX, maxX: pendingDiscardCost.maxX };
        for (const index of INPUT.picks) payDiscardCost(index);
        // A third card is past the bound and changes nothing.
        if (INPUT.picks.length === 2) payDiscardCost(3);
        const picked = [...pendingDiscardCost.picked];
        confirmDiscardCost();
        return { opened, picked, cost: pendingCastCost, continued, sent };
        """,
        {"state": _state(sid), "picks": list(picks)},
        prelude=_PICKER_PRELUDE,
    )
    assert out["opened"] == {"announcesX": True, "maxX": 2}
    assert out["picked"] == list(picks)
    # The discard is half the announcement: the targets are still owed.
    assert out["continued"] == {"card": "Restless Dreams", "castAction": "cast"}
    expected = {"x_value": len(picks)}
    if picks:
        expected.update(cost_hand_index=picks[0], cost_other_hand_indices=list(picks[1:]))
    assert out["cost"] == expected

    # The body the graveyard prompt sends carries those fields; posted as built.
    yard = [card.name for card in game.players[0].graveyard]
    targets = [yard.index("Grizzly Bears"), yard.index("Hill Giant")][: len(picks)]
    body = {"seat": 0, "action": "cast", "card_name": "Restless Dreams", **out["cost"]}
    if targets:
        body.update(target_seat=0, target_permanent_indices=targets)
    answered = client.post(f"/api/sessions/{sid}/action", json=body)
    assert answered.status_code == 200, answered.text
    resolve_stack(game)
    hand = sorted(card.name for card in game.players[0].hand)
    if picks:
        assert hand == ["Grizzly Bears", "Hill Giant", "Mountain"]
    else:
        assert hand == ["Forest", "Island", "Mountain"]


@needs_node
def test_sickening_dreams_sends_its_cast_with_the_discard_and_the_x():
    """A Dreams that targets nothing is cast from the picker's confirm, with the
    X the picked cards announced."""
    sid, game = _session(["Sickening Dreams", "Island", "Forest"])
    out = run_app_js(
        _PICKER,
        """
        startCastDiscardCostPrompt(INPUT.state.players[0].hand[0]);
        payDiscardCost(2);
        confirmDiscardCost();
        return { sent, continued };
        """,
        {"state": _state(sid)},
        prelude=_PICKER_PRELUDE,
    )
    assert out["continued"] is None
    [body] = out["sent"]
    assert body == {
        "seat": 0, "action": "cast", "card_name": "Sickening Dreams",
        "cost_hand_index": 2, "x_value": 1,
    }
    answered = client.post(f"/api/sessions/{sid}/action", json=body)
    assert answered.status_code == 200, answered.text
    resolve_stack(game)
    assert [card.name for card in game.players[0].hand] == ["Island"]
    assert game.players[1].life == game.players[0].life


def test_no_x_prompt_follows_an_x_the_discard_announced():
    """Every place the cast chain would ask for X asks first whether the cost
    already announced one."""
    assert "castXAnnouncedByCost() === null" in app_js_function_body("startCastTargetCascade")
    assert "castXAnnouncedByCost()" in app_js_function_body("startCastSeveralTargetsPrompt")
    assert "castXAnnouncedByCost()" in app_js_function_body("startCastGraveyardCreatureTargetPrompt")


@needs_node
def test_an_ordered_search_sends_its_picks_in_the_order_they_were_made():
    """Insidious Dreams' "put those cards on top in any order": the payload the
    server sends reads as ordered, a search with another destination does
    not, and the engine puts the first pick on top."""
    sid, game = _session(["Insidious Dreams", "Island", "Forest"])
    game.players[0].library = [_POOL[name] for name in ("Plains", "Shock", "Hill Giant", "Island")]
    cast = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "cast", "card_name": "Insidious Dreams",
        "cost_hand_index": 1, "cost_other_hand_indices": [2], "x_value": 2,
    })
    assert cast.status_code == 200, cast.text
    game.resolve_top_of_stack()
    prompt = _state(sid)["search_library"]
    assert (prompt["min_picks"], prompt["destination"]) == (2, "library_top")

    out = run_app_js(
        ["searchPicksAreOrdered"],
        """
        return {
          ordered: searchPicksAreOrdered(INPUT.prompt),
          hand: searchPicksAreOrdered({ ...INPUT.prompt, destination: "hand", destinations: ["hand", "hand"] }),
          single: searchPicksAreOrdered({ ...INPUT.prompt, multi: false }),
        };
        """,
        {"prompt": prompt},
    )
    assert out == {"ordered": True, "hand": False, "single": False}
    confirm = app_js_function_body("renderSearchLibraryModal")
    assert "searchPicksAreOrdered(liveInfo) ? chosenKeys : chosenKeys.sort()" in confirm

    # Hill Giant picked first, then Plains: Hill Giant is the top card.
    names = [card.name for card in game.players[0].library]
    picks = [
        {"zone": "library", "index": names.index("Hill Giant")},
        {"zone": "library", "index": names.index("Plains")},
    ]
    answered = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "search_library_confirm", "search_picks": picks,
    })
    assert answered.status_code == 200, answered.text
    assert [card.name for card in game.players[0].library[:2]] == ["Hill Giant", "Plains"]
