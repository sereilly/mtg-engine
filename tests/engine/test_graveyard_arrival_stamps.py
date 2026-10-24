"""CR 613.7d: a card in a graveyard has the timestamp of its arrival there —
recorded for the cards whose static ability functions there, and for no other.

``engine/graveyard_order.py`` keeps ``PlayerState.graveyard_arrivals`` in step
with the pile — which every removal edits by index, at seventy-odd sites — by
holding the record to the pile as a subsequence: arrivals only ever go on top
(CR 404.1) and removal never reorders (CR 404.2). These pin the properties the
static that reads the stamp (``graveyard_statics.graveyard_static_sources``,
Anger's ruling of 2004-10-04) relies on:

* each arrival of such a card through ``Game.put_card_into_graveyard`` is
  stamped, newer arrivals with newer stamps;
* a card removed from the middle of the pile leaves everyone else's stamp
  alone;
* a card that left and came back is a new object (CR 400.7) with a new stamp,
  not its old record matched again;
* a card written into the list directly (a test, the Debug Menu) is stamped the
  first time anything asks, and keeps that stamp on every later read;
* **a card no graveyard static reads is never recorded**, so the field is
  untouched by a game without one. Every reader that compares a seat's fields
  across a cast (the AI's rehearsal, the mode census) read a stamp written for
  the spell's own trip to the graveyard as a change the spell made — the W1G1
  merge's six reds.
"""

from __future__ import annotations

import functools

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.graveyard_order import graveyard_arrival_stamps


@functools.lru_cache(maxsize=1)
def _cards() -> dict:
    cards: dict = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            cards.setdefault(card.name, card)
    return cards


def _game():
    game = Game(players=[PlayerState(name="P0"), PlayerState(name="P1")])
    game.enforce_mana_costs = False
    return game


def test_each_arrival_of_a_graveyard_static_card_is_stamped_in_order():
    game = _game()
    for name in ("Anger", "Wonder", "Brawn"):
        assert game.put_card_into_graveyard(0, _cards()[name])
    stamps = graveyard_arrival_stamps(game.players[0])
    assert len(stamps) == 3 and None not in stamps
    assert stamps == sorted(stamps) and len(set(stamps)) == 3


def test_a_card_no_graveyard_static_reads_is_never_recorded():
    """Lightning Bolt resolving into a graveyard writes nothing: the field a
    rehearsal and the census compare across a cast is the same before and
    after."""
    game = _game()
    assert game.put_card_into_graveyard(0, _cards()["Lightning Bolt"])
    assert game.put_card_into_graveyard(0, _cards()["Grizzly Bears"])
    assert game.players[0].graveyard_arrivals == []
    assert graveyard_arrival_stamps(game.players[0]) == [None, None]
    assert game.players[0].graveyard_arrivals == []

    assert game.put_card_into_graveyard(0, _cards()["Anger"])
    recorded = list(game.players[0].graveyard_arrivals)
    assert game.put_card_into_graveyard(0, _cards()["Lightning Bolt"])
    assert game.players[0].graveyard_arrivals == recorded
    bolt, bears, anger, bolt_again = graveyard_arrival_stamps(game.players[0])
    assert (bolt, bears, bolt_again) == (None, None, None) and anger is not None


def test_removing_a_middle_card_leaves_the_others_stamps():
    game = _game()
    for name in ("Anger", "Wonder", "Brawn"):
        game.put_card_into_graveyard(0, _cards()[name])
    bottom, _middle, top = graveyard_arrival_stamps(game.players[0])
    game.players[0].graveyard.pop(1)
    assert graveyard_arrival_stamps(game.players[0]) == [bottom, top]


def test_a_card_that_left_and_came_back_is_stamped_anew():
    """CR 400.7. Two copies of a card are one ``CardDefinition`` object, and the
    same object is what comes back: the old record must not answer for it."""
    game = _game()
    anger = _cards()["Anger"]
    game.put_card_into_graveyard(0, anger)
    (first,) = graveyard_arrival_stamps(game.players[0])
    game.players[0].graveyard.pop()
    game.put_card_into_graveyard(0, _cards()["Wonder"])
    game.put_card_into_graveyard(0, anger)
    wonder_stamp, again = graveyard_arrival_stamps(game.players[0])
    assert again > wonder_stamp > first


def test_two_copies_are_two_stamps():
    game = _game()
    anger = _cards()["Anger"]
    game.put_card_into_graveyard(0, anger)
    game.put_card_into_graveyard(0, anger)
    older, newer = graveyard_arrival_stamps(game.players[0])
    assert newer > older


def test_a_card_written_directly_is_stamped_once_at_first_sight():
    game = _game()
    game.players[0].graveyard.append(_cards()["Anger"])
    (seen,) = graveyard_arrival_stamps(game.players[0])
    assert graveyard_arrival_stamps(game.players[0]) == [seen]
    game.put_card_into_graveyard(0, _cards()["Wonder"])
    kept, arrived = graveyard_arrival_stamps(game.players[0])
    assert kept == seen and arrived > seen
