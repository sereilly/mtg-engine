"""Static abilities that function from a graveyard (CR 113.6b, CR 611.3b), and
the timestamp their effect carries (CR 613.7a, CR 613.7d).

Judgment's Incarnations print "As long as this card is in your graveyard and
you control a <basic>, creatures you control have <keyword>." Every rule the
sentence leans on is asked here of Anger, the one whose ruling says it out
loud (2004-10-04): "The timestamp for the 'in your graveyard' ability is set at
the time that this card goes to your graveyard, regardless of whether you
control a Mountain at that time."

* the ability works from the graveyard **and only there** — not on the
  battlefield, in a hand or in exile (CR 113.6b);
* "you" is the graveyard's owner, the controller CR 108.4a gives a card nobody
  controls — so a stolen Anger that dies grants its haste to its owner's side;
* the grant's layer-6 timestamp is the moment the card entered the graveyard
  (CR 613.7d, through CR 613.7a), which is what orders it against a "loses all
  abilities" — Humble's (a resolved spell, CR 613.7b) and Humility's (a
  static, the timestamp of the permanent it is on) — in either order.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.control import change_control
from engine.models import Permanent
from tests.helpers import resolve_stack


def _seat_table(set_pool):
    island = set_pool("LEA")["Island"]
    game = Game(players=[
        PlayerState(name=f"P{seat}", life=20, library=[island] * 10)
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    return game


def _put(game, card, seat):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return permanent


def _cast(game, seat, card, **targets):
    game.players[seat].hand.append(card)
    cast = game.queue_from_hand(seat, card.name, **targets)
    assert cast.supported, game.log[-3:]
    resolve_stack(game)
    game._settle()


def _anger_board(set_pool):
    """Seat 0 with a Mountain and a Grizzly Bears, and Anger on the
    battlefield beside them."""
    lea = set_pool("LEA")
    game = _seat_table(set_pool)
    _put(game, lea["Mountain"], 0)
    bears = _put(game, lea["Grizzly Bears"], 0)
    anger = _put(game, set_pool("JUD")["Anger"], 0)
    game._settle()
    return game, bears, anger


@pytest.mark.cr("113.6b", "611.3b")
def test_113_6b_anger_grants_haste_from_the_graveyard_and_from_nowhere_else(set_pool):
    game, bears, anger = _anger_board(set_pool)
    anger_card = anger.card
    assert not bears.has_keyword("haste"), "on the battlefield"

    game.sacrifice_permanent(anger)
    game._settle()
    assert bears.has_keyword("haste"), "in the graveyard"

    for zone in ("hand", "exile"):
        game.players[0].graveyard.remove(anger_card)
        getattr(game.players[0], zone).append(anger_card)
        game._settle()
        assert not bears.has_keyword("haste"), f"in the {zone}"
        getattr(game.players[0], zone).remove(anger_card)
        assert game.put_card_into_graveyard(0, anger_card)
        game._settle()
        assert bears.has_keyword("haste"), "back in the graveyard"


@pytest.mark.cr("108.4a", "113.6b")
def test_108_4a_a_stolen_anger_that_dies_grants_its_owners_creatures(set_pool):
    """Anger stolen by seat 1 dies under seat 1's control and goes to seat 0's
    graveyard (CR 404.1, its owner's). Seat 0 owns the card and is the one
    "you" can mean (CR 108.4a); seat 1's Mountain and creature have nothing to
    do with it."""
    lea = set_pool("LEA")
    game = _seat_table(set_pool)
    _put(game, lea["Mountain"], 0)
    _put(game, lea["Mountain"], 1)
    mine = _put(game, lea["Grizzly Bears"], 0)
    theirs = _put(game, lea["Grizzly Bears"], 1)
    anger = _put(game, set_pool("JUD")["Anger"], 0)
    thief = _put(game, lea["Grizzly Bears"], 1)
    change_control(anger, 1, source=thief)
    game._settle()
    assert game.controller_index_of(anger) == 1

    game.sacrifice_permanent(anger)
    game._settle()

    assert "Anger" in [card.name for card in game.players[0].graveyard]
    assert mine.has_keyword("haste")
    assert not theirs.has_keyword("haste")


@pytest.mark.cr("613.7d", "613.7a", "613.1f")
def test_613_7d_anger_dying_after_humble_keeps_the_haste_humble_could_not_take(set_pool):
    """Humble resolves on the Grizzly Bears first (CR 613.7b: stamped as it
    resolves); Anger dies afterwards, so its grant is stamped later and is
    applied after the removal in layer 6 — the Bears has haste."""
    game, bears, anger = _anger_board(set_pool)
    _cast(game, 0, set_pool("USG")["Humble"], target_permanent_ids=[bears.permanent_id])
    assert not bears.has_keyword("haste")

    game.sacrifice_permanent(anger)
    game._settle()

    assert bears.has_keyword("haste")


@pytest.mark.cr("613.7d", "613.7a", "613.1f")
def test_613_7d_humble_after_anger_died_takes_the_haste_away(set_pool):
    """The other order: Anger is already in the graveyard (its grant stamped
    when it got there), and Humble resolves later — newer, so it takes the
    haste with every other ability until end of turn."""
    game, bears, anger = _anger_board(set_pool)
    game.sacrifice_permanent(anger)
    game._settle()
    assert bears.has_keyword("haste")

    _cast(game, 0, set_pool("USG")["Humble"], target_permanent_ids=[bears.permanent_id])

    assert not bears.has_keyword("haste")


@pytest.mark.cr("613.7d", "613.7a")
def test_613_7d_the_stamp_is_when_the_card_arrived_not_when_the_mountain_did(set_pool):
    """Anger's ruling, word for word: the timestamp is set as the card goes to
    the graveyard "regardless of whether you control a Mountain at that time".
    Anger dies with no Mountain on the board; Humility enters; *then* the
    Mountain arrives. The grant switches on with the Mountain, but its stamp
    is still the older one, so Humility's (CR 613.7a: the stamp of the
    permanent it is on) is newer and wins."""
    lea = set_pool("LEA")
    game = _seat_table(set_pool)
    bears = _put(game, lea["Grizzly Bears"], 0)
    anger = _put(game, set_pool("JUD")["Anger"], 0)
    game._settle()
    game.sacrifice_permanent(anger)
    game._settle()
    _put(game, set_pool("TMP")["Humility"], 1)
    _put(game, lea["Mountain"], 0)
    game._settle()

    assert not bears.has_keyword("haste")


@pytest.mark.cr("613.7d", "613.7a")
def test_613_7d_anger_arriving_after_humility_grants_through_it(set_pool):
    """And the reverse of the one above: Humility is on the battlefield first,
    Anger goes to the graveyard later — its stamp is the newer, so the haste
    it grants is applied after Humility's removal."""
    lea = set_pool("LEA")
    game = _seat_table(set_pool)
    _put(game, lea["Mountain"], 0)
    bears = _put(game, lea["Grizzly Bears"], 0)
    _put(game, set_pool("TMP")["Humility"], 1)
    game._settle()
    assert game.put_card_into_graveyard(0, set_pool("JUD")["Anger"])
    game._settle()

    assert bears.has_keyword("haste")
