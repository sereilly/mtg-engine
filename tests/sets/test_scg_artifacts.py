"""Scourge artifacts.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("SCG")` / `set_cards("SCG")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.
#
# Stabilizer ("Players can't cycle cards.", CR 702.29f / 602.5) and Ark of
# Blight, driven through the engine's activation doors, the AI's hand chooser
# and the wire's hand-ability offer.
from fastapi.testclient import TestClient as _W1G2TestClient

from engine import Game as _W1G2Game
from engine.ai_hand_activations import (
    choose_hand_activation_action as _w1g2_choose_hand_activation,
)
from engine.models import Permanent as _W1G2Permanent
from engine.models import PlayerState as _W1G2PlayerState
from engine.oracle import compile_card_oracle as _w1g2_compile
from engine.targeting import derive_activation_spec as _w1g2_activation_spec

from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_table(set_pool, hand, *, bob_hand=(), mana=None):
    lea = set_pool("LEA")
    alice = _W1G2PlayerState(name="Alice", hand=list(hand), library=[lea["Plains"]] * 6)
    bob = _W1G2PlayerState(name="Bob", hand=list(bob_hand), library=[lea["Island"]] * 6)
    game = _W1G2Game(players=[alice, bob])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    alice.mana_pool.update(mana or {"W": 6, "R": 2})
    bob.mana_pool.update({"U": 6})
    return game, alice, bob


def _w1g2_put(game, seat, card):
    permanent = _W1G2Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def test_w1g2_stabilizer_stops_cycling_and_typecycling_for_every_player(set_pool):
    """"Players can't cycle cards." Stabilizer rulings (2004-10-04): "This
    affects both Cycling and Landcycling." It names every player, its
    controller included, and the activation cannot be begun (CR 602.5):
    nothing is paid and nothing is discarded."""
    scg = set_pool("SCG")
    game, alice, bob = _w1g2_table(
        set_pool, [scg["Noble Templar"], scg["Spark Spray"]],
        bob_hand=[scg["Shoreline Ranger"]],
    )
    _w1g2_put(game, 0, scg["Stabilizer"])

    for seat, name in ((0, "Noble Templar"), (0, "Spark Spray"), (1, "Shoreline Ranger")):
        player = game.players[seat]
        before = (list(player.hand), dict(player.mana_pool))
        refused = game.activate_from_hand(seat, name)
        assert not refused.supported, name
        assert refused.details == f"{name} can't be cycled (Stabilizer)"
        assert (list(player.hand), dict(player.mana_pool)) == before
    assert game.stack == [] and alice.graveyard == [] and bob.graveyard == []
    assert not any("cycled" in line for line in game.log)


def test_w1g2_cycling_returns_when_the_stabilizer_leaves(set_pool):
    scg = set_pool("SCG")
    game, alice, _bob = _w1g2_table(set_pool, [scg["Spark Spray"]])
    stabilizer = _w1g2_put(game, 1, scg["Stabilizer"])
    assert not game.activate_from_hand(0, "Spark Spray").supported

    game.remove_from_battlefield(stabilizer)
    assert game.activate_from_hand(0, "Spark Spray").supported
    _w1g2_resolve_stack(game)
    assert [c.name for c in alice.hand] == ["Plains"]


def test_w1g2_stabilizer_does_not_stop_casting_the_card(set_pool):
    """It stops the cycling ability, not the spell: Spark Spray is cast."""
    scg = set_pool("SCG")
    game, _alice, bob = _w1g2_table(set_pool, [scg["Spark Spray"]])
    _w1g2_put(game, 0, scg["Stabilizer"])
    assert game.cast_from_hand(0, "Spark Spray", target_player_index=1).supported
    _w1g2_resolve_stack(game)
    assert bob.life == 19


def test_w1g2_the_ai_does_not_propose_a_cycle_stabilizer_forbids(set_pool):
    scg = set_pool("SCG")
    game, _alice, _bob = _w1g2_table(set_pool, [scg["Spark Spray"]])
    proposed = _w1g2_choose_hand_activation(game, 0)
    assert proposed is not None and proposed.card_name == "Spark Spray"

    _w1g2_put(game, 1, scg["Stabilizer"])
    assert _w1g2_choose_hand_activation(game, 0) is None


def test_w1g2_the_wire_marks_a_forbidden_cycle_prohibited(set_pool):
    """The hand-ability offer reads the same table: the button is shown,
    unpayable, with the engine's own words."""
    from web.app import app as _w1g2_app
    from web.app import store as _w1g2_store

    client = _W1G2TestClient(_w1g2_app)
    created = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "H",
        "host_colors": 2, "guest_colors": 2, "seed": 11,
    }).json()
    sid = created["session_id"]
    game = _w1g2_store.get(sid).game
    game.active_player_index = 0
    game.priority_player_index = 0
    game.players[0].hand.append(set_pool("SCG")["Wirewood Guardian"])
    game.players[0].mana_pool["G"] = 2
    _w1g2_put(game, 1, set_pool("SCG")["Stabilizer"])

    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    (entry,) = [e for e in state["hand_abilities"] if e["name"] == "Wirewood Guardian"]
    assert entry["payable"] is False
    assert entry["prohibited"] == "Wirewood Guardian can't be cycled (Stabilizer)"


def test_w1g2_ark_of_blight_sacrifices_itself_to_destroy_target_land(set_pool):
    scg, lea = set_pool("SCG"), set_pool("LEA")
    (ability,) = _w1g2_compile(scg["Ark of Blight"]).activated_abilities
    spec = _w1g2_activation_spec(ability)
    assert spec is not None and spec.get("kind") in ("permanent", "land")

    game, alice, bob = _w1g2_table(set_pool, [], mana={"C": 3})
    ark = _w1g2_put(game, 0, scg["Ark of Blight"])
    island = _w1g2_put(game, 1, lea["Island"])
    result = game.activate_permanent_ability(
        0, "Ark of Blight", permanent_index=game.battlefield_index_of(ark),
        ability_index=0, target_permanent_ids=[island.permanent_id],
    )
    assert result.supported, result.details
    assert not game.is_on_battlefield(ark), "sacrificed as a cost"
    _w1g2_resolve_stack(game)
    assert not game.is_on_battlefield(island)
    assert [c.name for c in alice.graveyard] == ["Ark of Blight"]
    assert [c.name for c in bob.graveyard] == ["Island"]

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.
#
# Proteus Machine: cast face down for {3}, turned face up for its {0} morph
# cost through the CR 116.2b special action, and its trigger's creature type
# chosen by a person and by a seat nobody asks — an indefinite change
# (CR 611.2a) that outlives the turn.

import pytest as _w1g9_pytest

from engine import Game as _W1G9Game, PlayerState as _W1G9PlayerState
from engine.card_loader import load_catalog as _w1g9_load_catalog
from engine.face_down import is_face_down as _w1g9_is_face_down
from engine.models import Permanent as _W1G9Permanent
from engine.special_actions import (
    take_permanent_special_action as _w1g9_take_special_action)
from tests.helpers import resolve_stack as _w1g9_resolve_stack

_W1G9_CATALOG = {card.name: card for card in _w1g9_load_catalog()}


def _w1g9_proteus_up(set_pool, *, interactive, board=()):
    """A game with *board* on seat 0, Proteus Machine cast face down and then
    turned face up; returns the game and the Machine with its trigger on the
    stack."""
    machine_card = set_pool("SCG")["Proteus Machine"]
    battlefield = []
    for card in board:
        permanent = _W1G9Permanent(card=card)
        permanent.metadata["summoning_sickness_turn"] = -99
        battlefield.append(permanent)
    p1 = _W1G9PlayerState(name="A", hand=[machine_card], battlefield=battlefield,
                          library=[_W1G9_CATALOG["Island"]] * 10)
    p2 = _W1G9PlayerState(name="B", library=[_W1G9_CATALOG["Island"]] * 10)
    game = _W1G9Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    game._recompute_continuous_effects()
    p1.mana_pool.update({"C": 3})
    result = game.queue_from_hand(0, "Proteus Machine", alternative_cost=True)
    assert result.supported, result.details
    _w1g9_resolve_stack(game)
    (machine,) = [p for p in game.controlled_by(0) if _w1g9_is_face_down(p)]
    machine.metadata["summoning_sickness_turn"] = -99
    assert not machine.has_type("shapeshifter"), "a face-down 2/2 has no type (CR 708.2)"
    game.priority_player_index = 0
    assert _w1g9_take_special_action(game, 0, machine, "turn_face_up") is None
    assert machine.card is machine_card and machine.has_type("shapeshifter")
    assert [item.card.name for item in game.stack] == ["Proteus Machine"]
    return game, machine


def test_w1g9_proteus_machine_becomes_the_type_a_person_names_for_good(set_pool):
    """"When this creature is turned face up, it becomes the creature type of
    your choice. (This effect lasts indefinitely.)" Named Goblin, it is a
    Goblin and no longer a Shapeshifter (CR 205.1a) — still an artifact — and
    stays one through the cleanup step and the next turn (CR 611.2a)."""
    game, machine = _w1g9_proteus_up(set_pool, interactive=True)
    game.resolve_top_of_stack(pause_for_choices=True)
    (choice,) = game.pending_choices_of("creature_type_choice", 0)
    assert game.resolve_pending_choice("creature_type_choice", 0, creature_type="goblin")
    _w1g9_resolve_stack(game)
    assert machine.has_type("goblin") and not machine.has_type("shapeshifter")
    assert machine.has_type("artifact") and machine.is_creature
    game.resolve_cleanup_step(0)
    game.turn += 1
    game.start_turn(1)
    assert machine.has_type("goblin") and not machine.has_type("shapeshifter")
    assert any("Proteus Machine became a Goblin (Proteus Machine)" in line for line in game.log)


def test_w1g9_proteus_machine_left_to_itself_joins_its_controllers_tribe(set_pool):
    """A seat nobody asks names the commonest creature type among its other
    creatures (``ai_prompt_readers``' "join"): beside two Bears, Bear."""
    bears = _W1G9_CATALOG["Grizzly Bears"]
    game, machine = _w1g9_proteus_up(set_pool, interactive=False, board=(bears, bears))
    _w1g9_resolve_stack(game)
    assert machine.has_type("bear") and not machine.has_type("shapeshifter")

# ==== end W1G9 ======================================================


# ==== W2G1 ==========================================================
# W2G1's tests go between this line and the "end W2G1" line.

# ==== end W2G1 ======================================================


# ==== W2G2 ==========================================================
# W2G2's tests go between this line and the "end W2G2" line.

# ==== end W2G2 ======================================================


# ==== W2G3 ==========================================================
# W2G3's tests go between this line and the "end W2G3" line.

# ==== end W2G3 ======================================================


# ==== W2G4 ==========================================================
# W2G4's tests go between this line and the "end W2G4" line.

# ==== end W2G4 ======================================================


# ==== W2G5 ==========================================================
# W2G5's tests go between this line and the "end W2G5" line.

# ==== end W2G5 ======================================================
