"""Per-card tests for The Dark's lands.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent


# --- G1: damage family (The Dark) ---


def test_sorrows_path_burns_its_controller_and_their_creatures_when_tapped(set_pool):
    """"it deals 2 damage to **you and each creature you control**" — one
    printed clause, two kinds of recipient, and no sweep handler that batches
    exactly that set. Lowered as one instruction per recipient; refused
    outright before that, so the whole trigger did nothing."""
    lea = set_pool("LEA")
    path = Permanent(card=set_pool("DRK")["Sorrow's Path"])
    mine = Permanent(card=lea["Grizzly Bears"])
    theirs = Permanent(card=lea["Grizzly Bears"])
    players = [PlayerState(name="P1", life=20), PlayerState(name="P2", life=20)]
    players[0].battlefield = [path, mine]
    players[1].battlefield = [theirs]
    game = Game(players=players)
    game._sync_control()

    game.become_tapped(path)
    game._settle()

    assert players[0].life == 18, game.log
    assert mine.damage_marked == 2, game.log
    assert theirs.damage_marked == 0, game.log


def test_sorrows_paths_sweep_reaches_creatures_that_arrived_since(set_pool):
    """The recipients are the printed noun phrase asked at resolution, not a
    list built when the land entered — so a creature that arrived in between is
    damaged and one that left is not."""
    lea = set_pool("LEA")
    path = Permanent(card=set_pool("DRK")["Sorrow's Path"])
    players = [PlayerState(name="P1", life=20), PlayerState(name="P2", life=20)]
    players[0].battlefield = [path]
    game = Game(players=players)
    game._sync_control()

    latecomer = Permanent(card=lea["Hill Giant"])
    players[0].battlefield.append(latecomer)
    game._sync_control()
    game.become_tapped(path)
    game._settle()

    assert latecomer.damage_marked == 2, game.log
