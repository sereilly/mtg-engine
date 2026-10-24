"""CR 613.7d: a card in a graveyard has the timestamp of its arrival there.

``engine/graveyard_order.py`` keeps ``PlayerState.graveyard_arrivals`` in step
with the pile — which every removal edits by index, at seventy-odd sites — by
holding the record to the pile as a subsequence: arrivals only ever go on top
(CR 404.1) and removal never reorders (CR 404.2). These pin the properties the
static that reads the stamp (``graveyard_statics.graveyard_static_sources``,
Anger's ruling of 2004-10-04) relies on:

* each arrival through ``Game.put_card_into_graveyard`` is stamped, newer
  arrivals with newer stamps;
* a card removed from the middle of the pile leaves everyone else's stamp
  alone;
* a card that left and came back is a new object (CR 400.7) with a new stamp,
  not its old record matched again;
* a card written into the list directly (a test, the Debug Menu) is stamped the
  first time anything asks, and keeps that stamp on every later read.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.graveyard_order import graveyard_arrival_stamps
from tests.helpers import CARDS_BY_NAME


def _game():
    game = Game(players=[PlayerState(name="P0"), PlayerState(name="P1")])
    game.enforce_mana_costs = False
    return game


def test_each_arrival_is_stamped_in_order():
    game = _game()
    for name in ("Grizzly Bears", "Forest", "Lightning Bolt"):
        assert game.put_card_into_graveyard(0, CARDS_BY_NAME[name])
    stamps = graveyard_arrival_stamps(game.players[0])
    assert len(stamps) == 3
    assert stamps == sorted(stamps) and len(set(stamps)) == 3


def test_removing_a_middle_card_leaves_the_others_stamps():
    game = _game()
    for name in ("Grizzly Bears", "Forest", "Lightning Bolt"):
        game.put_card_into_graveyard(0, CARDS_BY_NAME[name])
    bottom, _middle, top = graveyard_arrival_stamps(game.players[0])
    game.players[0].graveyard.pop(1)
    assert graveyard_arrival_stamps(game.players[0]) == [bottom, top]


def test_a_card_that_left_and_came_back_is_stamped_anew():
    """CR 400.7. Two copies of a card are one ``CardDefinition`` object, and the
    same object is what comes back: the old record must not answer for it."""
    game = _game()
    bears = CARDS_BY_NAME["Grizzly Bears"]
    game.put_card_into_graveyard(0, bears)
    (first,) = graveyard_arrival_stamps(game.players[0])
    game.players[0].graveyard.pop()
    game.put_card_into_graveyard(0, CARDS_BY_NAME["Forest"])
    game.put_card_into_graveyard(0, bears)
    forest_stamp, again = graveyard_arrival_stamps(game.players[0])
    assert again > forest_stamp > first


def test_two_copies_are_two_stamps():
    game = _game()
    bears = CARDS_BY_NAME["Grizzly Bears"]
    game.put_card_into_graveyard(0, bears)
    game.put_card_into_graveyard(0, bears)
    older, newer = graveyard_arrival_stamps(game.players[0])
    assert newer > older


def test_a_card_written_directly_is_stamped_once_at_first_sight():
    game = _game()
    game.players[0].graveyard.append(CARDS_BY_NAME["Grizzly Bears"])
    (seen,) = graveyard_arrival_stamps(game.players[0])
    assert graveyard_arrival_stamps(game.players[0]) == [seen]
    game.put_card_into_graveyard(0, CARDS_BY_NAME["Forest"])
    kept, arrived = graveyard_arrival_stamps(game.players[0])
    assert kept == seen and arrived > seen
