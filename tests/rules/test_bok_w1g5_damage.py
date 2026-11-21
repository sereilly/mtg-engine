"""Betrayers of Kamigawa's damage family (W1G5): redirection, prevention and
replacement boards that reach past one card's own test (CR 614, 615).

Cards come from ``set_pool`` (the set is measured while it is implemented);
each board is driven through the engine's entry points and read after
``settle``.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import settle

_SEATS = [pytest.param(set(), id="nobody-asked"), pytest.param({0, 1}, id="interactive")]


def _table(set_pool, interactive=(), *, hand=(), opponent_hand=()):
    lea = set_pool("LEA")
    game = Game(players=[
        PlayerState(
            name=name, library=[lea["Island"]] * 20,
            hand=list(hand) if seat == 0 else list(opponent_hand),
        )
        for seat, name in enumerate(("Alice", "Bob"))
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    settle(game)
    return game


def _put(game, card, seat=0):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _activate(game, permanent, seat=0, **announce):
    result = game.activate_permanent_ability(
        seat, permanent.card.name,
        permanent_index=game.battlefield_index_of(permanent), **announce,
    )
    assert result.supported, (result, game.log[-6:])
    settle(game)
    return result


@pytest.mark.cr("615.8", "614.9")
@pytest.mark.parametrize("interactive", _SEATS)
def test_opal_eye_takes_a_whole_sweep_from_the_chosen_source(set_pool, interactive):
    """"{T}: The next time a source of your choice would deal damage this
    turn, that damage is dealt to Opal-Eye instead." Named against Bob's
    Pestilence: one instance is everything that source deals in one dealing
    (CR 615.8; the owner's ruling, 2026-11-07), so every chunk of "1 damage
    to each creature and each player" — Alice, her Bears, Bob, his Hill
    Giant — moves onto Opal-Eye, whose own chunk was already its own. Five
    damage on Opal-Eye (1/4), which dies; nobody else is dealt any. The next
    activation of Pestilence is dealt normally."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    pestilence_set = set_pool("2ED")
    game = _table(set_pool, interactive)
    opal = _put(game, bok["Opal-Eye, Konda's Yojimbo"])
    bears = _put(game, lea["Grizzly Bears"])
    pestilence = _put(game, pestilence_set["Pestilence"], seat=1)
    giant = _put(game, lea["Hill Giant"], seat=1)
    _activate(game, opal, ability_index=0,
              target_permanent_ids=[pestilence.permanent_id])
    _activate(game, pestilence, seat=1)
    assert [p.life for p in game.players] == [20, 20], game.log
    assert (bears.damage_marked, giant.damage_marked) == (0, 0), game.log
    assert not game.is_on_battlefield(opal), game.log
    moved = [line for line in game.log
             if line.startswith("1 damage to") and "is dealt to Opal-Eye" in line]
    assert len(moved) == 4, game.log
    _activate(game, pestilence, seat=1)
    assert [p.life for p in game.players] == [19, 19], game.log
    assert (bears.damage_marked, giant.damage_marked) == (1, 1), game.log
