""""If you have **a** card in hand" is one or more (Mirrodin W1G10).

Imaginary Pet (Urza's Saga): "At the beginning of your upkeep, if you have a
card in hand, return this creature to its owner's hand." The count reader read
the article as the number one and compared for *equality*, so the Pet went
home holding one card and stayed on the battlefield holding two. Found while
building Mindstorm Crown, whose second sentence prints the same article in the
past tense ("If you had a card in hand, …") as the complement of "no cards".
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _pet_upkeep(set_pool, cards_in_hand: int) -> Game:
    forest = set_pool("LEA")["Forest"]
    game = Game(players=[
        PlayerState("P1", library=[forest] * 10, hand=[forest] * cards_in_hand),
        PlayerState("P2", library=[forest] * 10),
    ])
    game.enforce_mana_costs = False
    pet = Permanent(card=set_pool("USG")["Imaginary Pet"])
    game._put_permanent_onto_battlefield(0, pet, None)
    game.resolve_upkeep(0)
    resolve_stack(game)
    return game


def _pet_on_battlefield(game: Game) -> bool:
    return any(
        permanent.card.name == "Imaginary Pet" for permanent in game.controlled_by(0)
    )


def test_the_pet_goes_home_holding_two_cards(set_pool):
    game = _pet_upkeep(set_pool, 2)
    assert not _pet_on_battlefield(game)
    assert any(card.name == "Imaginary Pet" for card in game.players[0].hand)


def test_the_pet_goes_home_holding_one_card(set_pool):
    game = _pet_upkeep(set_pool, 1)
    assert not _pet_on_battlefield(game)


def test_the_pet_stays_with_an_empty_hand(set_pool):
    game = _pet_upkeep(set_pool, 0)
    assert _pet_on_battlefield(game)
