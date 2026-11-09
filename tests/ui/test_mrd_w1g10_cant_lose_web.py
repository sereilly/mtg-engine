"""The web layer's early read of CR 704.5a asks the printed "can't lose the
game" ban too (Platinum Angel, Mirrodin W1G10).

``web/seats._player_has_lost`` falls back to "0 or less life" before the
engine's state-based check has run, and ``_winner`` decides the game from it.
It knew Lich's narrower ban and not the Angel's, so a player at 0 life behind
an Angel was shown the game as lost while the engine played on.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from web.seats import _player_has_lost


def _game(set_pool) -> Game:
    forest = set_pool("LEA")["Forest"]
    game = Game(players=[
        PlayerState("P1", library=[forest] * 5),
        PlayerState("P2", library=[forest] * 5),
    ])
    game.enforce_mana_costs = False
    return game


def test_a_player_at_zero_life_behind_the_angel_has_not_lost(set_pool):
    game = _game(set_pool)
    angel = Permanent(card=set_pool("MRD")["Platinum Angel"])
    game._put_permanent_onto_battlefield(0, angel, None)
    game.players[0].life = 0
    assert not _player_has_lost(game, 0)
    game.remove_from_battlefield(angel)
    assert _player_has_lost(game, 0)


def test_a_player_at_zero_life_without_a_ban_has_lost(set_pool):
    game = _game(set_pool)
    game.players[1].life = -2
    assert _player_has_lost(game, 1)
