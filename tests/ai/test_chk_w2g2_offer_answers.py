"""Petals of Insight against a library too thin for its "otherwise" (CHK W2G2).

"Look at the top three cards of your library. You may put those cards on the
bottom of your library in any order. If you do, return Petals of Insight to its
owner's hand. Otherwise, draw three cards." A seat nobody asks declines into the
three draws (``ai_offer_answers.offer_declines_into_more_cards``, W1G7) — which
over a library of two is a loss at the next state-based check (CR 704.5b): it
takes the offer instead. Over an empty library the look found nothing and
putting nothing on the bottom is no option at all (CR 608.2d), so the offer is
not made (``handlers/offers._action_is_takeable``) and the draws stand.
"""

from __future__ import annotations

from engine import Game, PlayerState
from tests.helpers import settle


def _w2g2_petals(set_pool, library_size: int) -> Game:
    chk = set_pool("CHK")
    game = Game(players=[
        PlayerState("A", hand=[chk["Petals of Insight"]],
                    library=[chk["Island"]] * library_size),
        PlayerState("B", library=[chk["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._sync_control()
    game.turn = 3
    game.begin_turn_bookkeeping(0)
    game._enter_main_phase(precombat=True)
    result = game.cast_from_hand(0, "Petals of Insight")
    assert result.supported, result.details
    settle(game)
    return game


def test_a_library_of_two_takes_the_card_back_rather_than_drawing_three(set_pool):
    game = _w2g2_petals(set_pool, 2)
    assert [card.name for card in game.players[0].hand] == ["Petals of Insight"]
    assert len(game.players[0].library) == 2
    assert not game.players[0].lost


def test_an_empty_library_offers_nothing_to_put_back(set_pool):
    game = _w2g2_petals(set_pool, 0)
    assert [card.name for card in game.players[0].graveyard] == ["Petals of Insight"]
    assert game.players[0].hand == []
    assert game.players[0].lost


def test_a_full_library_still_draws_three(set_pool):
    """W1G7's policy where the library covers the draws: declined, three
    cards in hand."""
    game = _w2g2_petals(set_pool, 10)
    assert len(game.players[0].hand) == 3
    assert [card.name for card in game.players[0].graveyard] == ["Petals of Insight"]
