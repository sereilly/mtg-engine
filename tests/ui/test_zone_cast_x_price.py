"""An X cast from a zone is priced by the way it is cast (CR 118.9, CR 107.3).

Flaming Gambit costs {X}{R} from a hand and {X}{R}{R} by flashback. The X
box's ceiling is what the pool can pay *after* the cost's coloured symbols,
so it has to read the price of the way being cast — the server's
``castable_from_zones[].ways[].price`` — and not the card's mana cost, or it
offers an X one too high and the server refuses it. The zone cast hands the
X prompt ``zoneCastCard(card, way)``, the card with that price in its cost
fields; the madness cast goes through the same ``beginZoneCast``. Driven in a
browser at five Mountains: the flashback X box offered 0-3 and X = 3 was
cast; these pin what the box offers and what the server takes.

Since kg4 the X box's numbers are the server's (``x_payable`` on the hand
card and on each way, ``web/offers``): what the pool pays and what the board
could still tap for, priced as the cast charges it — the client's own
arithmetic (``getMaxAffordableX``) is gone.
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


def _session():
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 1189,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    session.pregame_phase = None
    game = session.game
    game.enforce_mana_costs = True
    game.interactive_seats = {0, 1}
    game.players[0].battlefield = [Permanent(card=_POOL["Mountain"]) for _ in range(5)]
    game.players[1].battlefield = []
    game.players[0].hand = [_POOL["Flaming Gambit"]]
    game.players[0].graveyard = [_POOL["Flaming Gambit"]]
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    game.players[0].mana_pool["R"] = 5
    return sid, game


def _state(sid, seat=0):
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


@needs_node
def test_the_x_box_is_priced_by_the_way_the_card_is_cast():
    sid, _game = _session()
    state = _state(sid)
    out = run_app_js(
        [
            "targetSpecOf", "xLivesInManaCost", "castXCeiling", "castXPayable", "zoneCastCard",
        ],
        """
        const me = INPUT.state.players[0];
        const entry = INPUT.state.castable_from_zones.find((e) => e.zone === "graveyard");
        const way = entry.ways[0];
        const fromYard = zoneCastCard(me.graveyard[entry.index], way);
        const fromHand = me.hand[0];
        const ceiling = (card) => castXCeiling(card, castXPayable(card).board);
        return {
          price: way.price, keyword: way.keyword,
          yard: castXPayable(fromYard), hand: castXPayable(fromHand),
          yardBox: ceiling(fromYard), handBox: ceiling(fromHand),
        };
        """,
        {"state": state},
        prelude=(
            'const EMPTY_TARGET_SPEC = { kind: "none", requires_target: false, valid_targets: [] };'
        ),
    )
    assert (out["price"], out["keyword"]) == ("{X}{R}{R}", "flashback")
    # Five red floating: {R}{R} leaves three for X by flashback, {R} leaves
    # four by hand — and the five untapped Mountains five more of each.
    assert (out["yard"]["pool"], out["hand"]["pool"]) == (3, 4)
    assert (out["yard"]["board"], out["hand"]["board"]) == (8, 9)
    assert (out["yardBox"], out["handBox"]) == (8, 9)
    # And the zone cast — the madness cast included — hands that card on.
    assert "card = zoneCastCard(card, chosenWay);" in app_js_function_body("beginZoneCast")


def test_the_server_takes_the_x_the_box_offers_and_refuses_one_more():
    sid, game = _session()
    too_high = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "cast", "card_name": "Flaming Gambit", "from_zone": "graveyard",
        "alternative_cost": True, "x_value": 4, "target_seat": 1,
    })
    assert too_high.status_code == 400
    assert "insufficient mana" in too_high.json()["detail"]
    cast = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "cast", "card_name": "Flaming Gambit", "from_zone": "graveyard",
        "alternative_cost": True, "x_value": 3, "target_seat": 1,
    })
    assert cast.status_code == 200, cast.text
    assert game.stack[-1].card.name == "Flaming Gambit" and game.stack[-1].flashback
    assert game.players[0].mana_pool["R"] == 0


def test_the_largest_x_the_board_pays_is_one_the_auto_tap_casts():
    """The box's top is the board's, and the payment step pays it: X = 8 by
    flashback with five red floating and five Mountains to tap."""
    sid, game = _session()
    way = next(
        e for e in _state(sid)["castable_from_zones"] if e["zone"] == "graveyard"
    )["ways"][0]
    assert way["x_payable"]["board"] == 8
    cast = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "cast", "card_name": "Flaming Gambit", "from_zone": "graveyard",
        "alternative_cost": True, "x_value": 8, "target_seat": 1, "auto_tap": True,
    })
    assert cast.status_code == 200, cast.text
    assert all(p.tapped for p in game.players[0].battlefield)
    over = _session()
    refused = client.post(f"/api/sessions/{over[0]}/action", json={
        "seat": 0, "action": "cast", "card_name": "Flaming Gambit", "from_zone": "graveyard",
        "alternative_cost": True, "x_value": 9, "target_seat": 1, "auto_tap": True,
    })
    assert refused.status_code == 400
