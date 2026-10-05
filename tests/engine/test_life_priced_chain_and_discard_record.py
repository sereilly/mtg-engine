"""Two productions Aether Rift bought, on sentences no card prints.

* **A life price on the chained toll.** "…unless any player pays 5 life" is
  ``unless_player_pays`` — Prophecy's "unless any player pays {2}" — with
  CR 119.4's currency: every named seat is asked in turn, one payment ends the
  chain, and a seat below the amount cannot say yes.
* **Which cards a random discard took.** ``discard_x_target_cards`` records
  them (``DISCARDED_THIS_WAY`` / ``DISCARDED_INTO_GRAVEYARD``) and counts them
  (``discarded_count``), so "if you discard a <type> card this way", "if you
  do" and "return it from your graveyard" have a producer to name.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card, resolve_stack


def _spell(text: str):
    return _mk_card(name="Probe", mana_cost="{1}", type_line="Sorcery", oracle_text=text)


def _duel(set_pool, text: str, *, interactive=(), seats: int = 2, hand=()):
    island = set_pool("LEA")["Island"]
    game = Game(players=[
        PlayerState(name=f"P{seat}", life=20, library=[island] * 10)
        for seat in range(seats)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    game.players[0].hand = [_spell(text), *[set_pool("LEA")[name] for name in hand]]
    return game


def _answer_all(game, paying: frozenset[int] = frozenset()) -> list[int]:
    """Answer every owed link in order, the seats in *paying* accepting."""
    asked = []
    while game.pending_choices:
        seat = game.pending_choices[0].player_index
        asked.append(seat)
        assert game.confirm_optional_pay(seat, accept=seat in paying)
    game._settle()
    return asked


# --- the life-priced chain ---------------------------------------------------


@pytest.mark.parametrize("text, payer", [
    ("Draw a card unless any player pays 5 life.", "any_player"),
    ("Unless any player pays 5 life, draw a card.", "any_player"),
    ("Draw a card unless an opponent pays 5 life.", "opponent"),
])
def test_a_life_price_over_a_set_of_seats_is_the_chain(text, payer):
    (toll,) = compile_card_oracle(_spell(text)).instructions
    assert toll.kind == "unless_player_pays"
    assert toll.payload["payer"] == payer
    assert toll.payload["life"] == 5
    assert toll.payload["cost"] == {}
    assert [step.kind for step in toll.payload["unpaid"]] == ["draw_controller_cards"]


def test_any_player_is_asked_in_turn_order_and_one_payment_ends_it(set_pool):
    game = _duel(
        set_pool, "Draw a card unless any player pays 5 life.",
        interactive=(0, 1, 2), seats=3,
    )
    game.cast_from_hand(0, "Probe")

    assert _answer_all(game, paying=frozenset({1})) == [0, 1]
    assert [player.life for player in game.players] == [20, 15, 20]
    assert game.players[0].hand == []          # nothing drawn


def test_nobody_paying_lets_the_effect_happen(set_pool):
    game = _duel(
        set_pool, "Draw a card unless any player pays 5 life.", interactive=(0, 1),
    )
    game.cast_from_hand(0, "Probe")

    assert _answer_all(game) == [0, 1]
    assert [player.life for player in game.players] == [20, 20]
    assert [card.name for card in game.players[0].hand] == ["Island"]


def test_an_opponent_priced_chain_never_asks_the_controller(set_pool):
    game = _duel(
        set_pool, "Draw a card unless an opponent pays 5 life.",
        interactive=(0, 1, 2), seats=3,
    )
    game.cast_from_hand(0, "Probe")

    assert _answer_all(game) == [1, 2]


def test_a_seat_below_the_price_cannot_pay_it(set_pool):
    """CR 119.4. The accept is not a payment: no life moves and the chain goes
    on to its unpaid branch."""
    game = _duel(
        set_pool, "Draw a card unless any player pays 5 life.", interactive=(0, 1),
    )
    game.players[1].life = 4
    game.cast_from_hand(0, "Probe")

    assert game.confirm_optional_pay(0, accept=False)
    assert game.confirm_optional_pay(1, accept=True)
    game._settle()

    assert game.players[1].life == 4
    assert [card.name for card in game.players[0].hand] == ["Island"]


def test_paying_down_to_exactly_zero_is_a_payment(set_pool):
    """CR 119.4 again: "greater than or equal to". The payer loses the game to
    the next state-based check, and the toll was paid."""
    game = _duel(
        set_pool, "Draw a card unless any player pays 5 life.", interactive=(0, 1),
    )
    game.players[1].life = 5
    game.cast_from_hand(0, "Probe")

    assert game.confirm_optional_pay(0, accept=False)
    assert game.confirm_optional_pay(1, accept=True)

    assert game.players[1].life == 0
    assert game.players[0].hand == []


@pytest.mark.parametrize("text", [
    # A variable life price would have to be re-read for every seat asked.
    "Draw a card unless any player pays X life.",
    # Two currencies on one chain: the link is one offer with one price.
    "Draw a card unless any player pays 5 life or discards a card.",
])
def test_a_chain_price_the_handler_cannot_charge_is_refused(text: str):
    assert not compile_card_oracle(_spell(text)).supported


# --- what a random discard took ----------------------------------------------


def test_a_typed_discard_test_reads_the_cards_the_random_discard_took(set_pool):
    text = "Discard a card at random. If you discard a land card this way, draw two cards."
    game = _duel(set_pool, text, hand=["Forest"])
    game.cast_from_hand(0, "Probe")
    resolve_stack(game)
    assert [card.name for card in game.players[0].hand] == ["Island", "Island"]

    game = _duel(set_pool, text, hand=["Grizzly Bears"])
    game.cast_from_hand(0, "Probe")
    resolve_stack(game)
    assert game.players[0].hand == []


def test_if_you_do_behind_a_random_discard_asks_whether_a_card_went(set_pool):
    text = "Discard a card at random. If you do, draw two cards."
    game = _duel(set_pool, text, hand=["Forest"])
    game.cast_from_hand(0, "Probe")
    resolve_stack(game)
    assert [card.name for card in game.players[0].hand] == ["Island", "Island"]

    game = _duel(set_pool, text)          # an empty hand discards nothing
    game.cast_from_hand(0, "Probe")
    resolve_stack(game)
    assert game.players[0].hand == []


def test_the_pronoun_returns_the_discarded_card_and_only_to_the_battlefield(set_pool):
    text = "Discard a card at random. Return it from your graveyard to the battlefield."
    game = _duel(set_pool, text, hand=["Grizzly Bears"])
    game.cast_from_hand(0, "Probe")
    resolve_stack(game)
    assert [
        permanent.card.name for permanent in game.controlled_by(game.players[0])
    ] == ["Grizzly Bears"]


@pytest.mark.parametrize("text", [
    # A chosen discard counts its cards and does not list them: against that
    # producer the typed test would never be true.
    "Discard a card. If you discard a creature card this way, draw a card.",
    # No step put a card there for "it" to name.
    "Return it from your graveyard to the battlefield.",
    # The record's reader moves a card onto the battlefield and nowhere else.
    "Discard a card at random. Return it from your graveyard to your hand.",
    "Discard a card at random. Return it from your graveyard to the battlefield tapped.",
])
def test_a_discard_back_reference_with_no_reader_is_refused(text: str):
    assert not compile_card_oracle(_spell(text)).supported
