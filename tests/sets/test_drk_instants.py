"""Per-card tests for The Dark's instants.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent


# --- G3: upkeep and land denial (The Dark) ---


def _festival_board(set_pool):
    """Festival in seat 1's hand, with a creature of seat 0's ready to attack."""
    bears = Permanent(card=set_pool("LEA")["Grizzly Bears"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[bears]),
        PlayerState(name="P2", hand=[set_pool("DRK")["Festival"]]),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game, bears


def test_festival_can_only_be_cast_during_an_opponents_upkeep(set_pool):
    """"Cast this spell only during an opponent's upkeep." Both halves of the
    window are asked — the seat *and* the step — because either alone is a
    window the card does not print."""
    game, _bears = _festival_board(set_pool)

    game.current_turn_phase = "precombat_main"
    game.current_step = None
    assert not game.cast_from_hand(1, "Festival").supported

    game.current_turn_phase = "beginning"
    game.current_step = "upkeep"
    assert game.cast_from_hand(1, "Festival").supported


def test_festival_grounds_every_creature_for_the_turn(set_pool):
    """"Creatures can't attack this turn."

    A blanket restriction the attack gate tests for the rest of the turn, not a
    flag stamped on the creatures that happened to be there — so a creature
    that entered afterwards cannot attack either.
    """
    game, _bears = _festival_board(set_pool)
    game.current_turn_phase = "beginning"
    game.current_step = "upkeep"

    assert game.cast_from_hand(1, "Festival").supported
    while game.stack:
        game.resolve_top_of_stack()

    latecomer = Permanent(card=set_pool("LEA")["Hill Giant"])
    game.players[0].battlefield.append(latecomer)

    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    ok, _message = game.declare_attackers(0, [0])
    assert not ok
    ok, _message = game.declare_attackers(0, [1])
    assert not ok


def test_festival_stops_at_the_end_of_the_turn(set_pool):
    """"…this turn" (CR 514.2): the cleanup step ends it, beside its blocking
    twin so the two cannot disagree about when the turn is over."""
    game, _bears = _festival_board(set_pool)
    game.current_turn_phase = "beginning"
    game.current_step = "upkeep"
    assert game.cast_from_hand(1, "Festival").supported
    while game.stack:
        game.resolve_top_of_stack()

    game.resolve_cleanup_step(0)

    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    ok, _message = game.declare_attackers(0, [0])
    assert ok
