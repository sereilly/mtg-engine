"""The madness offer in the browser (CR 702.35a, CR 608.2g) — the client half
of ``test_madness_cast_prompt_ui_api.py``.

The offer is answered while the madness trigger resolves, so the cast it
makes is not the ``cast`` route: it is ``madness_cast_confirm`` with
``accept: true`` and the ordinary cast fields. The client builds those fields
with the cast chain it already has — the exiled card's own target, X,
division and Aura prompts, priced by the madness way the server lists for
the exile slot — and ``carryMadnessAnswer`` turns the body that chain sends
into the answer. These run the real ``app.js`` functions over the payload the
server sent and post what they build.
"""
from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from tests.helpers import app_js_function_body, run_app_js
from web.app import app, store

client = TestClient(app)

_POOL: dict = {}
for _card in load_cards(manifest_set_paths(include_measured=True)):
    _POOL.setdefault(_card.name, _card)

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)

_FUNCTIONS = [
    "getMadnessCastInfo", "madnessExiledCard", "madnessZoneEntry", "madnessWayOf",
    "carryMadnessAnswer",
]
_PRELUDE = "let seat = 0; let currentState = null; let pendingMadnessCast = null;"


def _offer(discarded: str = "Fiery Temper"):
    """Seat 0 discards *discarded* to Aquamoeba: the madness trigger resolves
    and offers the cast. Two interactive seats, mana costs enforced."""
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 702,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    game = store.get(sid).game
    game.enforce_mana_costs = True
    game.interactive_seats = {0, 1}
    game.players[0].battlefield = [
        Permanent(card=_POOL["Aquamoeba"]), Permanent(card=_POOL["Mountain"]),
    ]
    game.players[1].battlefield = [Permanent(card=_POOL["Grizzly Bears"])]
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    game._recompute_continuous_effects()
    game.players[0].hand = [_POOL[discarded]]
    game.players[0].graveyard = []
    game.players[0].exile = []
    store.get(sid).current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    assert game.activate_permanent_ability(0, "Aquamoeba", cost_hand_index=0).supported
    return sid, game


def _state(sid, seat=0):
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


@needs_node
def test_the_cast_chains_body_goes_out_as_the_offers_answer():
    """What the browser reads off the offer (the card in its exile slot, the
    madness price), and the cast body its target prompt sends, turned into
    ``madness_cast_confirm`` — posted as built, after the Mountain is tapped
    the way a click on it taps it."""
    sid, game = _offer()
    bears = game.players[1].battlefield[0]

    out = run_app_js(
        _FUNCTIONS,
        """
        currentState = INPUT.state;
        const info = getMadnessCastInfo();
        const card = madnessExiledCard(info);
        const way = madnessWayOf(madnessZoneEntry(info), info);
        // The body resolvePendingCastTarget builds, after carryCastZoneAndCost.
        const castBody = {
          seat: 0, action: "cast", card_name: card.name, target_seat: 1,
          target_permanent_id: INPUT.bears, from_zone: "exile", alternative_cost: true,
          auto_tap: true,
        };
        const untouched = carryMadnessAnswer({ ...castBody });
        pendingMadnessCast = { slot: info.exile_index };
        const answer = carryMadnessAnswer({ ...castBody });
        // Anything that is not a cast — a land tapped for the cost — passes.
        const tap = carryMadnessAnswer({ seat: 0, action: "activate", permanent_index: 1 });
        return { cardName: card.name, price: way.price, keyword: way.keyword,
          spec: card.target_spec.kind, untouched, answer, tap };
        """,
        {"state": _state(sid), "bears": bears.permanent_id},
        prelude=_PRELUDE,
    )

    assert out["cardName"] == "Fiery Temper"
    assert (out["price"], out["keyword"], out["spec"]) == ("{R}", "madness", "any")
    # Outside a madness cast the body is left alone.
    assert out["untouched"]["action"] == "cast"
    assert out["tap"]["action"] == "activate"
    answer = out["answer"]
    assert answer["action"] == "madness_cast_confirm" and answer["accept"] is True
    # Auto-Tap is a priority-window payment; a madness cast is tapped by hand.
    assert "auto_tap" not in answer

    mountain = game.players[0].battlefield[1]
    tapped = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "tap", "permanent_id": mountain.permanent_id,
    })
    assert tapped.status_code == 200, tapped.text
    answered = client.post(f"/api/sessions/{sid}/action", json=answer)
    assert answered.status_code == 200, answered.text
    assert _state(sid)["madness_cast"] is None
    spell = game.stack[-1]
    assert spell.card.name == "Fiery Temper" and not spell.ability_effect_kind
    assert spell.target_permanent_id == bears.permanent_id


@needs_node
def test_the_offer_is_only_read_by_its_owner():
    sid, _game = _offer("Obsessive Search")
    out = run_app_js(
        _FUNCTIONS,
        """
        currentState = INPUT.state0;
        const mine = getMadnessCastInfo();
        seat = 1;
        currentState = INPUT.state1;
        const theirs = getMadnessCastInfo();
        return { mine, theirs };
        """,
        {"state0": _state(sid, 0), "state1": _state(sid, 1)},
        prelude=_PRELUDE,
    )
    assert out["mine"]["card_name"] == "Obsessive Search"
    assert out["theirs"] is None


def test_every_cast_body_passes_through_the_madness_rewrite():
    """``sendAction`` is the one place every cast prompt ends; the rewrite is
    made there, after the zone and the alternative cost are carried, so a
    target, X, division or Aura prompt cannot send a madness cast as a ``cast``
    the server would refuse mid-resolution."""
    sender = app_js_function_body("sendAction")
    assert "carryMadnessAnswer(body)" in sender
    assert sender.index("carryCastZoneAndCost(body)") < sender.index("carryMadnessAnswer(body)")
    # The panel yields to the cast's own prompts once the cast has begun, and
    # a cancelled cast clears the flag so the offer comes back.
    panel = app_js_function_body("renderActivationPrompt")
    assert "applyMadnessCastPrompt(madnessInfo)" in panel
    assert "pendingMadnessCast = null" in app_js_function_body("clearPendingHandCast")
    # The exile pile's click on the offered card answers the offer.
    assert "beginMadnessCast(madness)" in app_js_function_body("renderZoneCards")
