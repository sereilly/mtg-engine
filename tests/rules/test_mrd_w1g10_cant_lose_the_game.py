"""CR 104.3 and CR 104.2b under "You can't lose the game and your opponents
can't win the game." (Platinum Angel, Mirrodin W1G10.)

The Angel's 2009-10-01 ruling: "No game effect can cause you to lose the game
or cause any opponent to win the game while you control Platinum Angel. It
doesn't matter whether you have 0 or less life, you're forced to draw a card
while your library is empty, you have ten or more poison counters, … You keep
playing." Its 2004-12-01 rulings: a concession still loses, and "effects that
say the game is a draw … will still work". Every way to lose goes through
``Game.lose_the_game``; the ban is read off the board on every ask
(``engine/game_result_bans.py``), so it lifts the moment the Angel leaves.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.control import change_control
from engine.models import Permanent
from tests.helpers import resolve_stack


def _table(set_pool) -> Game:
    forest = set_pool("LEA")["Forest"]
    game = Game(players=[
        PlayerState("P1", library=[forest] * 20),
        PlayerState("P2", library=[forest] * 20),
    ])
    game.enforce_mana_costs = False
    return game


def _put(game: Game, seat: int, card) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _angel(set_pool, game: Game, seat: int = 0) -> Permanent:
    return _put(game, seat, set_pool("MRD")["Platinum Angel"])


def _kill(game: Game, permanent: Permanent) -> None:
    seat = game.controller_index_of(permanent)
    game.remove_from_battlefield(permanent)
    game._permanent_to_graveyard(game.players[seat], permanent)


@pytest.mark.cr("104.3b", "704.5a", "611.3b")
def test_zero_life_does_not_lose_and_loses_once_the_angel_leaves(set_pool):
    game = _table(set_pool)
    angel = _angel(set_pool, game)
    game.players[0].life = -3
    game.check_state_based_actions()
    assert not game.players[0].lost
    assert not game.is_game_over()
    # The ban is a static ability: it ends the moment its source leaves
    # (CR 611.3b), and the next check sees a player at -3 with nothing saying
    # they can't lose.
    _kill(game, angel)
    game.check_state_based_actions()
    assert game.players[0].lost
    assert game.get_winner() is game.players[1]
    assert "P1 lost the game (704.5a: 0 or less life)" in game.log


@pytest.mark.cr("104.3d", "704.5c")
def test_ten_poison_counters_do_not_lose(set_pool):
    game = _table(set_pool)
    angel = _angel(set_pool, game)
    game.players[0].poison_counters = 12
    game.check_state_based_actions()
    assert not game.players[0].lost
    _kill(game, angel)
    game.check_state_based_actions()
    assert game.players[0].lost


@pytest.mark.cr("104.3c", "704.5b")
def test_a_draw_from_an_empty_library_does_not_lose(set_pool):
    game = _table(set_pool)
    angel = _angel(set_pool, game)
    game.players[0].library = []
    game.players[0].draw(1)
    game.check_state_based_actions()
    assert not game.players[0].lost
    # CR 704.5b asks about a draw "since the last time state-based actions
    # were checked": the draw the Angel answered is not owed again.
    _kill(game, angel)
    game.check_state_based_actions()
    assert not game.players[0].lost


@pytest.mark.cr("104.3e")
def test_an_effect_saying_you_lose_does_nothing(set_pool):
    """Phage the Untouchable put onto the battlefield, not cast from a hand:
    "When Phage enters, if you didn't cast it from your hand, you lose the
    game." """
    game = _table(set_pool)
    _angel(set_pool, game)
    _put(game, 0, set_pool("LGN")["Phage the Untouchable"])
    resolve_stack(game)
    game.check_state_based_actions()
    assert not game.players[0].lost
    assert "P1 can't lose the game (Platinum Angel)" in game.log


@pytest.mark.cr("104.2b")
def test_an_opponents_win_effect_does_nothing(set_pool):
    """Test of Endurance: "At the beginning of your upkeep, if you have 50 or
    more life, you win the game." Controlled by the Angel's opponent."""
    game = _table(set_pool)
    _angel(set_pool, game)
    _put(game, 1, set_pool("JUD")["Test of Endurance"])
    game.players[1].life = 60
    game.active_player_index = 1
    game.resolve_upkeep(1)
    resolve_stack(game)
    assert not any(player.lost for player in game.players)
    assert not game.is_game_over()
    assert "Test of Endurance: P2 can't win the game (Platinum Angel)" in game.log


@pytest.mark.cr("104.2b")
def test_the_angels_controller_may_still_win(set_pool):
    """Only *opponents* can't win: the Angel's controller's own win effect
    works, and their opponent loses to it."""
    game = _table(set_pool)
    _angel(set_pool, game)
    _put(game, 0, set_pool("JUD")["Test of Endurance"])
    game.players[0].life = 60
    game.resolve_upkeep(0)
    resolve_stack(game)
    assert game.players[1].lost
    assert game.get_winner() is game.players[0]


@pytest.mark.cr("104.3a")
def test_a_concession_still_loses(set_pool):
    game = _table(set_pool)
    _angel(set_pool, game)
    game.concede(0)
    assert game.players[0].lost
    assert game.get_winner() is game.players[1]


@pytest.mark.cr("104.3b", "109.5")
def test_a_stolen_angel_protects_the_player_who_controls_it(set_pool):
    """"You" is the controller (CR 109.5): the thief keeps playing at 0 life
    and the owner, at 0 too, loses."""
    game = _table(set_pool)
    angel = _angel(set_pool, game, seat=1)
    change_control(angel, 0, source="a control-changing effect")
    game._sync_control()
    game.players[0].life = 0
    game.players[1].life = 0
    game.check_state_based_actions()
    assert not game.players[0].lost
    assert game.players[1].lost
