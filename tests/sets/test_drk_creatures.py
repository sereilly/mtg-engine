"""Per-card tests for The Dark's creatures.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent


# --- G2: auras and land statics (The Dark) ---


def _attack_with(game: Game, seat: int, index: int) -> None:
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    ok, msg = game.declare_attackers(seat, [index])
    assert ok, msg


def test_goblin_rock_sled_rests_for_exactly_one_of_its_controllers_untap_steps(set_pool):
    """"…doesn't untap during your untap step if it attacked during your last
    turn." The condition is re-asked every untap step off the permanent's own
    attack record — the loose substring reading of the phrase would have frozen
    the Sled for the rest of the game."""
    sled = Permanent(card=set_pool("DRK")["Goblin Rock Sled"])
    # "…can't attack unless defending player controls a Mountain" is the Sled's
    # other printed restriction, so the defender needs one for this test to be
    # about the untap step at all.
    game = Game(players=[
        PlayerState(name="P1", battlefield=[sled]),
        PlayerState(name="P2", battlefield=[Permanent(card=set_pool("LEA")["Mountain"])]),
    ])
    game.start_turn(0)
    _attack_with(game, 0, 0)
    assert sled.tapped, "attacking taps it (CR 508.1f)"

    game.start_next_turn()   # P2
    game.start_next_turn()   # P1: it attacked during P1's last turn
    assert sled.tapped, game.log

    game.start_next_turn()   # P2
    game.start_next_turn()   # P1: last turn it sat out, so it untaps
    assert not sled.tapped, game.log


def test_a_goblin_rock_sled_that_never_attacked_untaps_normally(set_pool):
    """The other direction of the same condition. Without it the phrase alone
    would keep any tapped Sled tapped forever."""
    sled = Permanent(card=set_pool("DRK")["Goblin Rock Sled"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[sled]), PlayerState(name="P2"),
    ])
    game.become_tapped(sled)
    game.start_turn(0)

    assert not sled.tapped, game.log


def test_goblin_rock_sled_cannot_attack_without_a_defending_mountain(set_pool):
    """The card's other printed restriction, on the same compiled program."""
    sled = Permanent(card=set_pool("DRK")["Goblin Rock Sled"])
    mountain = Permanent(card=set_pool("LEA")["Mountain"])
    p1 = PlayerState(name="P1", battlefield=[sled])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.start_turn(0)

    assert not game.can_attack(sled, 1)
    p2.battlefield.append(mountain)
    game._sync_control()
    assert game.can_attack(sled, 1)


def test_goblins_of_the_flarg_is_sacrificed_the_moment_a_dwarf_arrives(set_pool):
    """"When you control a Dwarf, sacrifice this creature." A state trigger
    (CR 603.8), so it fires alongside the state-based actions rather than
    waiting for the next upkeep — the Goblin never gets to attack beside the
    Dwarf it is printed to lose to."""
    pool = set_pool("DRK")
    goblin = Permanent(card=pool["Goblins of the Flarg"])
    p1 = PlayerState(name="P1", battlefield=[goblin])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.check_state_based_actions()
    assert goblin in p1.battlefield, "no Dwarf, no sacrifice"

    dwarf = Permanent(card=set_pool("LEA")["Dwarven Warriors"])
    p1.battlefield.append(dwarf)
    game._sync_control()
    game.check_state_based_actions()

    assert goblin not in p1.battlefield, game.log
    assert [c.name for c in p1.graveyard] == ["Goblins of the Flarg"]


def test_an_opponents_dwarf_does_not_sacrifice_goblins_of_the_flarg(set_pool):
    """"**You** control a Dwarf" is a seat, and the seat is the Goblin's
    controller — an ignored controller narrowing would sacrifice the card off
    somebody else's board."""
    pool = set_pool("DRK")
    goblin = Permanent(card=pool["Goblins of the Flarg"])
    dwarf = Permanent(card=set_pool("LEA")["Dwarven Warriors"])
    p1 = PlayerState(name="P1", battlefield=[goblin])
    p2 = PlayerState(name="P2", battlefield=[dwarf])
    game = Game(players=[p1, p2])

    game.check_state_based_actions()

    assert goblin in p1.battlefield, game.log
