"""Scourge instants.

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
# Decree of Savagery's cycle trigger (a printed number of +1/+1 counters on one
# target, refused until this round), and the cycling instants on W1G2's drive
# list (Spark Spray, Wipe Clean).
from engine import Game as _W1G2Game
from engine.models import Permanent as _W1G2Permanent
from engine.models import PlayerState as _W1G2PlayerState

from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_table(set_pool, hand, *, interactive=False):
    lea = set_pool("LEA")
    alice = _W1G2PlayerState(name="Alice", hand=list(hand), library=[lea["Plains"]] * 6)
    bob = _W1G2PlayerState(name="Bob", library=[lea["Island"]] * 6)
    game = _W1G2Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game, alice, bob


def _w1g2_put(game, seat, card):
    permanent = _W1G2Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g2_drain(game):
    _w1g2_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g2_resolve_stack(game)


def _w1g2_pt(permanent):
    return permanent.effective_power, permanent.effective_toughness


def test_w1g2_decree_of_savagery_counters_each_creature_you_control(set_pool):
    lea = set_pool("LEA")
    game, _alice, _bob = _w1g2_table(set_pool, [set_pool("SCG")["Decree of Savagery"]])
    mine = _w1g2_put(game, 0, lea["Grizzly Bears"])
    theirs = _w1g2_put(game, 1, lea["Grizzly Bears"])
    assert game.cast_from_hand(0, "Decree of Savagery").supported
    _w1g2_drain(game)
    assert _w1g2_pt(mine) == (6, 6) and _w1g2_pt(theirs) == (2, 2)


def test_w1g2_decree_of_savagery_cycled_puts_four_counters_on_the_target(set_pool):
    """"When you cycle this card, you may put four +1/+1 counters on target
    creature." Compiled to nothing until this round (the count was refused as
    "variable"); the target is chosen as the trigger goes on the stack, by a
    person here, and it may be any creature."""
    lea = set_pool("LEA")
    game, alice, _bob = _w1g2_table(
        set_pool, [set_pool("SCG")["Decree of Savagery"]], interactive=True,
    )
    mine = _w1g2_put(game, 0, lea["Grizzly Bears"])
    theirs = _w1g2_put(game, 1, lea["Llanowar Elves"])

    assert game.activate_from_hand(0, "Decree of Savagery").supported
    prompt = game.pending_choice_of("trigger_target", 0)
    assert prompt is not None
    offered = {t.get("permanent_id") for t in prompt.data["targets"]}
    assert {mine.permanent_id, theirs.permanent_id} <= offered
    assert game.resolve_pending_choice(
        "trigger_target", 0, permanent_id=theirs.permanent_id,
    )
    game.resolve_top_of_stack()
    offer = game.pending_choice_of("optional_pay", 0)
    assert offer is not None, [c.kind for c in game.pending_choices]
    assert game.resolve_pending_choice("optional_pay", 0, accept=True)
    _w1g2_drain(game)
    assert _w1g2_pt(theirs) == (5, 5)
    assert _w1g2_pt(mine) == (2, 2)
    assert [c.name for c in alice.hand] == ["Plains"]


def test_w1g2_decree_of_savagery_cycles_with_no_creature_to_target(set_pool):
    """2022-12-08: "You can cycle this card even if there are no legal targets
    for the triggered ability." The trigger is removed (CR 603.3d); the draw
    still happens."""
    game, alice, _bob = _w1g2_table(set_pool, [set_pool("SCG")["Decree of Savagery"]])
    assert game.activate_from_hand(0, "Decree of Savagery").supported
    assert len(game.stack) == 1
    _w1g2_drain(game)
    assert [c.name for c in alice.hand] == ["Plains"]
    assert any("no legal target" in line for line in game.log)


def test_w1g2_spark_spray_deals_one_to_any_target(set_pool):
    lea = set_pool("LEA")
    game, _alice, bob = _w1g2_table(set_pool, [set_pool("SCG")["Spark Spray"]] * 2)
    elves = _w1g2_put(game, 1, lea["Llanowar Elves"])
    assert game.cast_from_hand(0, "Spark Spray", target_permanent_ids=[elves.permanent_id]).supported
    _w1g2_drain(game)
    game.check_state_based_actions()
    assert not game.is_on_battlefield(elves)
    assert game.cast_from_hand(0, "Spark Spray", target_player_index=1).supported
    _w1g2_drain(game)
    assert bob.life == 19


def test_w1g2_wipe_clean_exiles_target_enchantment(set_pool):
    lea = set_pool("LEA")
    game, _alice, bob = _w1g2_table(set_pool, [set_pool("SCG")["Wipe Clean"]])
    moon = _w1g2_put(game, 1, lea["Bad Moon"])
    assert game.cast_from_hand(0, "Wipe Clean", target_permanent_ids=[moon.permanent_id]).supported
    _w1g2_drain(game)
    assert not game.is_on_battlefield(moon)
    assert [c.name for c in bob.exile] == ["Bad Moon"] and bob.graveyard == []


def test_w1g2_the_cycling_instants_cycle(set_pool):
    for name in ("Spark Spray", "Wipe Clean"):
        game, alice, _bob = _w1g2_table(set_pool, [set_pool("SCG")[name]])
        assert game.activate_from_hand(0, name).supported, name
        _w1g2_drain(game)
        assert [c.name for c in alice.hand] == ["Plains"], name

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

# ==== end W1G9 ======================================================
