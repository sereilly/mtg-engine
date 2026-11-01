"""CR 103.5's mulligan rounds as the AI takes them
(``ai_mulligan.take_opening_mulligans``), and the London bottom
(``Game.keep_opening_hand`` / ``put_mulligan_cards_on_bottom``).

The simulator and the web table's no-pregame deal ask the same driver, so its
order is the rule's order: the starting player declares first, then each other
player in turn order; every mulligan declared in a round is taken after the
last declaration; a seat that keeps is not asked again. What a seat decides is
``tests/ai/test_kg2_mulligan_decision.py``'s subject; here a script decides,
so the rounds are what is tested.
"""
from __future__ import annotations

from unittest import mock

import pytest

from engine import Game, PlayerState
from engine import ai_mulligan
from engine.ai_mulligan import take_opening_mulligans


def _deck(lea) -> list:
    return [lea["Forest"]] * 17 + [lea["Grizzly Bears"]] * 23


def _table(lea, seats: int) -> Game:
    return Game(players=[PlayerState(name=f"P{i}", library=_deck(lea)) for i in range(seats)])


def _scripted(answers: dict[int, list[bool]], events: list):
    """A keep decision that answers from *answers* (per seat, in order) and
    records each declaration."""
    def decide(game, seat):
        events.append(("declare", seat))
        return answers[seat].pop(0)
    return decide


def _recording_draws(game: Game, events: list):
    original = game.pregame_mulligan_draw

    def draw(seat):
        events.append(("mulligan", seat))
        return original(seat)
    return draw


@pytest.mark.cr("103.5")
def test_the_starting_player_declares_first_and_mulligans_follow_every_declaration(set_pool):
    lea = set_pool("LEA")
    game = _table(lea, 3)
    game.deal_opening_hands(1)
    events: list = []
    game.pregame_mulligan_draw = _recording_draws(game, events)
    answers = {1: [False, True], 2: [True], 0: [False, True]}
    with mock.patch.object(ai_mulligan, "keeps_opening_hand", _scripted(answers, events)):
        taken = take_opening_mulligans(game, 1)

    assert taken == 2
    assert events == [
        ("declare", 1), ("declare", 2), ("declare", 0),
        ("mulligan", 1), ("mulligan", 0),
        # Seat 2 kept in the first round and "may not take any further
        # mulligans"; the second round asks the two that mulliganed, in order.
        ("declare", 1), ("declare", 0),
    ]
    assert [len(p.hand) for p in game.players] == [7, 7, 7]  # CR 103.5c: free


@pytest.mark.cr("103.5c")
def test_a_multiplayer_seat_s_first_mulligan_puts_nothing_on_the_bottom(set_pool):
    lea = set_pool("LEA")
    game = _table(lea, 3)
    game.deal_opening_hands(0)
    answers = {0: [False, True], 1: [True], 2: [True]}
    with mock.patch.object(ai_mulligan, "keeps_opening_hand", _scripted(answers, [])):
        take_opening_mulligans(game, 0)
    seat = game.players[0]
    assert seat.mulligans_taken == 1
    assert len(seat.hand) == 7
    assert len(seat.hand) + len(seat.library) == 40
    assert any("P0 keeps opening hand of 7 card(s) (1 mulligan(s) taken)" in line for line in game.log)


@pytest.mark.cr("103.5")
def test_a_two_player_seat_s_mulligan_bottoms_the_card_its_decision_names(set_pool):
    lea = set_pool("LEA")
    game = _table(lea, 2)
    game.deal_opening_hands(0)
    answers = {0: [False, True], 1: [True]}
    chosen: list = []
    real_bottom = ai_mulligan.opening_hand_bottom

    def bottom(game_, seat, count=None):
        picked = real_bottom(game_, seat, count)
        if seat == 0:
            chosen.extend(game_.players[seat].hand[i] for i in picked)
        return picked

    with mock.patch.object(ai_mulligan, "keeps_opening_hand", _scripted(answers, [])), \
            mock.patch.object(ai_mulligan, "opening_hand_bottom", bottom):
        take_opening_mulligans(game, 0)
    seat = game.players[0]
    assert len(chosen) == 1
    assert len(seat.hand) == 6
    assert len(seat.hand) + len(seat.library) == 40
    assert seat.library[-1] is chosen[0]
    assert len(game.players[1].hand) == 7


@pytest.mark.cr("103.5")
def test_mulligans_end_at_a_hand_of_zero_cards(set_pool):
    """"A player can take mulligans until their opening hand would be zero
    cards, after which they may not take further mulligans." A decision that
    never keeps still ends: the engine refuses the eighth, and the seat keeps
    the nothing it owes seven cards out of."""
    lea = set_pool("LEA")
    game = _table(lea, 2)
    game.deal_opening_hands(0)
    with mock.patch.object(ai_mulligan, "keeps_opening_hand", lambda game_, seat: seat != 0):
        taken = take_opening_mulligans(game, 0)
    assert taken == 7
    assert game.players[0].mulligans_taken == 7
    assert game.players[0].hand == []
    assert len(game.players[0].library) == 40


@pytest.mark.cr("103.5")
def test_a_seat_nobody_asks_keeps_what_it_was_dealt(set_pool):
    """The web table's no-pregame deal: a person's seat keeps its seven, and
    only the AI seats named as deciding are asked."""
    lea = set_pool("LEA")
    game = _table(lea, 2)
    game.deal_opening_hands(0)
    dealt = list(game.players[0].hand)
    events: list = []
    answers = {1: [True]}
    with mock.patch.object(ai_mulligan, "keeps_opening_hand", _scripted(answers, events)):
        take_opening_mulligans(game, 0, deciding=[1])
    assert events == [("declare", 1)]
    assert game.players[0].hand == dealt


@pytest.mark.cr("103.5")
def test_keeping_puts_the_named_cards_on_the_bottom_in_the_order_given(set_pool):
    lea = set_pool("LEA")
    bears, forest, bolt = lea["Grizzly Bears"], lea["Forest"], lea["Lightning Bolt"]
    seat = PlayerState(name="P0", hand=[forest, bears, bolt, forest], library=[bears] * 3)
    seat.mulligans_taken = 2
    game = Game(players=[seat, PlayerState(name="P1")])
    game.keep_opening_hand(0, [2, 1])
    assert seat.library[-2:] == [bolt, bears]
    assert seat.hand == [forest, forest]
    assert any("P0 keeps opening hand of 2 card(s) (2 mulligan(s) taken)" in line for line in game.log)


@pytest.mark.cr("103.5")
def test_a_hand_holding_copies_of_one_card_loses_exactly_one(set_pool):
    """Every copy of a card in a deck is the same object; the bottom goes
    through ``take_card_from_hand``, so naming one Forest moves one."""
    lea = set_pool("LEA")
    forest = lea["Forest"]
    seat = PlayerState(name="P0", hand=[forest] * 4, library=[])
    game = Game(players=[seat, PlayerState(name="P1")])
    moved = game.put_mulligan_cards_on_bottom(0, [3])
    assert moved == [forest]
    assert len(seat.hand) == 3 and seat.library == [forest]
