"""Darksteel sorceries.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("DST")` / `set_cards("DST")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

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
#
# Flamebreak: Earthquake's sweep with CR 701.19c's rider on the creatures it
# actually dealt damage to.
from engine import Game as _W1G6Game
from engine.models import Permanent as _W1G6Permanent
from engine.models import PlayerState as _W1G6PlayerState
from engine.regeneration import cant_be_regenerated as _w1g6_cant_be_regenerated

from tests.helpers import settle as _w1g6_settle


def _w1g6_table(set_pool, *, hand=()):
    lea = set_pool("LEA")
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="Alice", hand=list(hand), library=[lea["Plains"]] * 8),
        _W1G6PlayerState(name="Bob", library=[lea["Island"]] * 8),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._settle()
    return game


def _w1g6_put(game, seat, card):
    permanent = _W1G6Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def test_w1g6_flamebreak_burns_the_ground_and_denies_regeneration(set_pool):
    """"Flamebreak deals 3 damage to each creature without flying and each
    player. Creatures dealt damage this way can't be regenerated this turn."
    Both players go to 17; a flier is untouched; Drudge Skeletons dies
    through its regeneration shield; a Wall of Stone survives the 3 and is
    left unable to regenerate for the turn."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g6_table(set_pool, hand=[dst["Flamebreak"]])
    angel = _w1g6_put(game, 0, lea["Serra Angel"])
    skeletons = _w1g6_put(game, 1, lea["Drudge Skeletons"])
    skeletons.regeneration_shield = 1
    wall = _w1g6_put(game, 1, lea["Wall of Stone"])
    result = game.cast_from_hand(0, "Flamebreak")
    assert result.supported, result.details
    _w1g6_settle(game)
    assert [player.life for player in game.players] == [17, 17]
    assert game.is_on_battlefield(angel) and angel.damage_marked == 0
    assert not game.is_on_battlefield(skeletons)
    assert [card.name for card in game.players[1].graveyard] == ["Drudge Skeletons"]
    assert game.is_on_battlefield(wall) and wall.damage_marked == 3
    assert _w1g6_cant_be_regenerated(wall)
    assert not _w1g6_cant_be_regenerated(angel)


def test_w1g6_flamebreak_leaves_a_creature_it_did_not_damage_regenerable(set_pool):
    """A creature whose damage was prevented (protection from red, CR
    702.16e) was not dealt damage this way: it keeps its ability to
    regenerate."""
    dst, arn = set_pool("DST"), set_pool("ARN")
    game = _w1g6_table(set_pool, hand=[dst["Flamebreak"]])
    blacksmith = _w1g6_put(game, 1, arn["Repentant Blacksmith"])
    assert game.cast_from_hand(0, "Flamebreak").supported
    _w1g6_settle(game)
    assert game.is_on_battlefield(blacksmith) and blacksmith.damage_marked == 0
    assert not _w1g6_cant_be_regenerated(blacksmith)

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
