"""Per-card tests for The Dark's creatures.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle


# --- G1: damage family (The Dark) ---


def _board(set_pool, name: str, *, seats: int = 2) -> tuple[Game, list[PlayerState], Permanent]:
    """*name* on seat 0's battlefield, summoning sickness already worked off."""
    perm = Permanent(card=set_pool("DRK")[name])
    perm.summoning_sick = False
    players = [PlayerState(name=f"P{i + 1}", life=20) for i in range(seats)]
    players[0].battlefield = [perm]
    game = Game(players=players)
    game.enforce_mana_costs = False
    return game, players, perm


def test_banshee_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("DRK")["Banshee"])
    assert program.supported, program.unsupported_reason


def test_banshee_rounds_the_two_halves_in_opposite_directions(set_pool):
    """"half X damage, rounded down, to any target, and half X damage, rounded
    up, to you" — one sentence, two roundings. With X = 5 that is 2 and 3, and
    a reader that honoured one rounding for both would deal 2/2 or 3/3."""
    game, players, banshee = _board(set_pool, "Banshee")

    result = game.activate_permanent_ability(
        0, "Banshee", target_player_index=1, x_value=5
    )

    assert result.supported, result.details
    assert players[1].life == 18, game.log
    assert players[0].life == 17, game.log


def test_banshee_with_an_odd_x_of_one_hits_only_its_controller(set_pool):
    """X = 1: half rounded down is 0, and CR 120.8 makes a source that would
    deal 0 damage deal none at all. Half rounded up is still 1."""
    game, players, banshee = _board(set_pool, "Banshee")

    game.activate_permanent_ability(0, "Banshee", target_player_index=1, x_value=1)

    assert players[1].life == 20, game.log
    assert players[0].life == 19, game.log


def test_electric_eel_pumps_and_bites_its_controller_in_one_ability(set_pool):
    """"gets +2/+0 until end of turn **and deals 1 damage to you**" is one
    printed ability. Read as a pump alone the card is strictly better than it
    prints, and the whole line refused to parse before the conjunct existed."""
    game, players, eel = _board(set_pool, "Electric Eel")

    result = game.activate_permanent_ability(0, "Electric Eel")

    assert result.supported, result.details
    assert eel.effective_power == 3, game.log
    assert players[0].life == 19, game.log


def test_electric_eel_bites_its_controller_when_it_enters(set_pool):
    """The other half of the card, and the one that already worked — kept here
    so a change to the activated line cannot quietly take the trigger with it."""
    players = [PlayerState(name="P1", life=20), PlayerState(name="P2", life=20)]
    players[0].hand = [set_pool("DRK")["Electric Eel"]]
    game = Game(players=players)
    game.enforce_mana_costs = False

    game.cast_from_hand(0, "Electric Eel")
    game._settle()

    assert players[0].life == 19, game.log


def test_the_fallen_damages_nobody_before_it_has_damaged_anybody(set_pool):
    """"each opponent … **it has dealt damage to this game**" is a history, not
    a board. With an empty record the upkeep trigger hits nothing; a reading
    that dropped the clause would be a Pestilence."""
    game, players, fallen = _board(set_pool, "The Fallen")
    game.start_turn(0)
    game._settle()

    assert players[1].life == 20, game.log


def test_the_fallen_remembers_the_opponent_it_damaged(set_pool):
    """One point of damage from this creature puts that seat in its record, and
    every later upkeep collects on it."""
    game, players, fallen = _board(set_pool, "The Fallen")
    game._deal_damage_to_player(players[1], 3, source=fallen)
    assert players[1].life == 17

    game.start_turn(0)
    game._settle()

    assert players[1].life == 16, game.log


def test_the_fallen_forgets_what_a_previous_object_damaged(set_pool):
    """CR 400.7: a creature that leaves and returns is a new object. The record
    lives on the permanent, so the new one remembers nothing — which is what
    keeps "this game" from meaning "this game, plus a previous incarnation"."""
    game, players, fallen = _board(set_pool, "The Fallen")
    game._deal_damage_to_player(players[1], 1, source=fallen)
    game.remove_from_battlefield(fallen)

    returned = Permanent(card=set_pool("DRK")["The Fallen"])
    returned.summoning_sick = False
    players[0].battlefield = [returned]
    game._sync_control()
    life_before = players[1].life

    game.start_turn(0)
    game._settle()

    assert players[1].life == life_before, game.log


def test_the_fallen_never_damages_its_own_controller(set_pool):
    """"each **opponent**": a seat recorded because this creature damaged its
    own controller is not one, and the record holds seats rather than
    opponents so the question is asked when the trigger resolves."""
    game, players, fallen = _board(set_pool, "The Fallen")
    game._deal_damage_to_player(players[0], 1, source=fallen)
    life_before = players[0].life

    game.start_turn(0)
    game._settle()

    assert players[0].life == life_before, game.log
