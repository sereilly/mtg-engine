"""A blocker whose attacker has left combat is still drawn as in combat
(CR 509.1g).

CR 509.1g: a blocking creature stays blocking "until it's removed from combat
or the combat phase ends", whether or not the creature it blocked is still
there. The engine has held that since kg5's ``combat`` group
(``Permanent.is_blocking``), and the wire says it the way the engine does:
``blocking_attacker_controller`` is the attacking seat for every creature that
is blocking, and ``blocking_attacker_index`` an attacker it is blocking *now* —
null for an orphan.

The canvas's one in-combat test (``_isCombatActive``, what pulls a card out of
a pile of identical permanents so it stays visible on its own) asked the index
only, so a Wall of Stone whose Grizzly Bears was bolted after blocks folded
back into its twin's pile for the rest of combat. It asks the controller field
too now.

Backwards: on the base the orphan reads ``false`` and the first test fails;
the second is the direction that must not move (the Wall's twin, blocking
nothing, stays in its pile).

Driven in a browser (port 8045): Grizzly Bears attacking, one of two Walls of
Stone blocking, the Bears bolted in the declare blockers step — the blocking
Wall stands in its own slot beside its twin through the damage step.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine.models import Permanent
from tests.helpers import declare_attack, drive_combat, run_app_js, settle
from web.app import app, store

client = TestClient(app)

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)

_CANVAS = Path(__file__).resolve().parents[2] / "web" / "static" / "battlefield-canvas.js"


def _canvas_method(name: str) -> str:
    """One method of the canvas class, as an object-literal member."""
    source = _CANVAS.read_text(encoding="utf-8").replace("\r\n", "\n")
    match = re.search(r"\n  " + re.escape(name) + r"\([^)]*\) \{\n.*?\n  \}\n", source, re.S)
    assert match is not None, f"battlefield-canvas.js no longer defines {name}"
    return match.group(0)


def _session():
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 5045,
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
    game.enforce_mana_costs = False
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return sid, game


def _put(game, seat, card):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _bolted_attacker_board(set_pool):
    """Grizzly Bears attacks, the first of two Walls of Stone blocks it, and
    the Bears is bolted before damage: the board the Known-gaps item names."""
    lea = set_pool("LEA")
    sid, game = _session()
    bears = _put(game, 0, lea["Grizzly Bears"])
    blocking_wall = _put(game, 1, lea["Wall of Stone"])
    idle_wall = _put(game, 1, lea["Wall of Stone"])
    game.players[0].hand = [lea["Lightning Bolt"]]
    declare_attack(game, 0, blocks={game.battlefield_index_of(blocking_wall): 0})
    result = game.cast_from_hand(
        0, "Lightning Bolt", target_player_index=0,
        target_permanent_index=game.battlefield_index_of(bears),
    )
    assert result.supported, result.details
    settle(game)
    assert bears not in game.players[0].battlefield, game.log[-6:]
    # On into the damage step, which deals nothing — the Wall's attacker is
    # gone — and stops with the creatures still in combat (CR 511.3 has not
    # come yet).
    drive_combat(game, through="combat_damage")
    # The engine's half, which this test only reads: still blocking, and
    # blocking nothing.
    assert blocking_wall.is_blocking and blocking_wall.blocking_attacker_index is None
    assert not idle_wall.is_blocking
    state = client.get(f"/api/sessions/{sid}/state?seat=1").json()
    by_id = {entry["id"]: entry for entry in state["players"][1]["battlefield"]}
    return by_id[blocking_wall.permanent_id], by_id[idle_wall.permanent_id]


def _in_combat(cards):
    return run_app_js(
        [],
        "return INPUT.map((card) => canvasMethods._isCombatActive(card));",
        cards,
        prelude="const canvasMethods = {" + _canvas_method("_isCombatActive") + "};\n",
    )


@needs_node
def test_a_blocker_whose_attacker_left_combat_is_drawn_in_combat(set_pool):
    orphan, _idle = _bolted_attacker_board(set_pool)
    # What the wire sends for it: the seat it blocks from, no attacker.
    assert orphan["blocking_attacker_index"] is None
    assert orphan["blocking_attacker_controller"] == 0
    assert orphan["damage_marked"] == 0 and not orphan["attacking"]
    assert _in_combat([orphan]) == [True]


@needs_node
def test_its_twin_blocking_nothing_stays_in_the_pile(set_pool):
    _orphan, idle = _bolted_attacker_board(set_pool)
    assert idle["blocking_attacker_index"] is None
    assert idle["blocking_attacker_controller"] is None
    assert _in_combat([idle]) == [False]
