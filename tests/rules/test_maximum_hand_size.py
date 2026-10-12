"""CR 402.2 / CR 613.11: a maximum hand size, and the order its effects apply in.

An effect that modifies a player's maximum hand size changes a game rule, not
an object, and CR 613.11 says such effects "are applied in timestamp order".
The reader in ``engine/hand_size.py`` took the lowest printed limit and let
"no maximum" win outright, which no card could tell from the rule while every
shipped sentence either *set* the number or *removed* it and stood alone — and
which was wrong for 7 of the 20 ordered pairs of the five shipped permanents.
Odyssey's three Thought beasts *change* the number, and a change means nothing
without an order.
"""

import itertools

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.faces import compilation_units
from engine.hand_size import (DEFAULT_MAXIMUM_HAND_SIZE, hand_size_effect,
                              hand_size_line, maximum_hand_size)
from engine.models import Permanent
from tests.helpers import _mk_card


def _static(name: str, text: str):
    return _mk_card(name, "{1}", "Enchantment", text)


NO_MAXIMUM = _static("No Maximum", "You have no maximum hand size.")
EVERYBODY = _static("Nobody's Maximum", "Players have no maximum hand size.")
LIMIT_TWO = _static("Limit Two", "Your maximum hand size is two.")
RACK = _static("Rack", "The chosen player's maximum hand size is four.")
LESS_THREE = _static("Less Three", "Your maximum hand size is reduced by three.")
LESS_FIVE = _static("Less Five", "Your maximum hand size is reduced by five.")
PLUS_TWO = _static("Plus Two", "Your maximum hand size is increased by two.")


def _board(*cards, opponent_chooses=()):
    """Seat 0 controls *cards*, entered in that order. A card in
    *opponent_chooses* is controlled by seat 1 and has chosen seat 0."""
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = False
    for card in cards:
        seat = 1 if card in opponent_chooses else 0
        permanent = Permanent(card=card)
        game._put_permanent_onto_battlefield(seat, permanent, None)
        if card in opponent_chooses:
            permanent.metadata["chosen_player_index"] = 0
    return game


@pytest.mark.cr("613.11", "402.2")
def test_613_11_a_limit_and_a_removal_apply_in_timestamp_order():
    """Spellbook and Recycle print it as their own ruling: the later of the
    two is the one that stands."""
    assert maximum_hand_size(_board(NO_MAXIMUM, LIMIT_TWO), 0) == 2
    assert maximum_hand_size(_board(LIMIT_TWO, NO_MAXIMUM), 0) is None
    assert maximum_hand_size(_board(EVERYBODY, LIMIT_TWO), 0) == 2
    assert maximum_hand_size(_board(LIMIT_TWO, EVERYBODY), 0) is None


@pytest.mark.cr("613.11")
def test_613_11_two_limits_are_the_later_one_not_the_lower_one():
    """Cursed Rack's ruling: after a "two", the Rack makes it four."""
    rack_last = _board(LIMIT_TWO, RACK, opponent_chooses=(RACK,))
    rack_first = _board(RACK, LIMIT_TWO, opponent_chooses=(RACK,))

    assert maximum_hand_size(rack_last, 0) == 4
    assert maximum_hand_size(rack_first, 0) == 2
    assert maximum_hand_size(rack_last, 1) == DEFAULT_MAXIMUM_HAND_SIZE, (
        "the Rack names the player it chose and not its controller"
    )


@pytest.mark.cr("613.11", "402.2")
def test_613_11_a_change_moves_the_limit_that_is_there_when_it_applies():
    """The Thought beasts' ruling: a Rack and then "reduced by three" is one,
    and the opposite order is four."""
    assert maximum_hand_size(_board(LESS_THREE), 0) == 4
    assert maximum_hand_size(
        _board(RACK, LESS_THREE, opponent_chooses=(RACK,)), 0
    ) == 1
    assert maximum_hand_size(
        _board(LESS_THREE, RACK, opponent_chooses=(RACK,)), 0
    ) == 4
    assert maximum_hand_size(_board(LESS_THREE), 1) == DEFAULT_MAXIMUM_HAND_SIZE, (
        "'your' is the controller alone"
    )


@pytest.mark.cr("613.11")
def test_613_11_a_change_to_no_maximum_leaves_no_maximum():
    """There is no number for the change to move; a later limit starts from
    its own value."""
    assert maximum_hand_size(_board(NO_MAXIMUM, LESS_THREE), 0) is None
    assert maximum_hand_size(_board(LESS_THREE, NO_MAXIMUM), 0) is None
    assert maximum_hand_size(_board(NO_MAXIMUM, LESS_THREE, LIMIT_TWO), 0) == 2


@pytest.mark.cr("107.1b", "402.2")
def test_107_1b_a_maximum_below_zero_is_used_in_arithmetic_and_answered_as_zero():
    """"If a calculation or comparison needs to use a negative value, it does
    so": seven less five less five is minus three, so a later "increased by
    two" is minus one — still nothing — where flooring at each step would have
    answered two."""
    assert maximum_hand_size(_board(LESS_FIVE, LESS_FIVE), 0) == 0
    assert maximum_hand_size(_board(LESS_FIVE, LESS_FIVE, PLUS_TWO), 0) == 0
    assert maximum_hand_size(_board(LESS_FIVE, PLUS_TWO), 0) == 4
    assert maximum_hand_size(_board(PLUS_TWO), 0) == 9


@pytest.mark.cr("611.3a", "613.11")
def test_611_3a_a_change_ends_with_its_source():
    game = _board(LESS_THREE, LESS_THREE)
    assert maximum_hand_size(game, 0) == 1
    game.remove_from_battlefield(next(iter(game.controlled_by(0))))
    assert maximum_hand_size(game, 0) == 4


@pytest.mark.cr("514.1", "613.11")
def test_514_1_cleanup_discards_down_to_the_ordered_maximum():
    game = _board(LESS_THREE)
    filler = _mk_card("Filler", "", "Sorcery", "")
    game.players[0].hand = [filler] * 7
    game.resolve_cleanup_step(0)
    assert len(game.players[0].hand) == 4
    assert len(game.players[0].graveyard) == 3


@pytest.mark.cr("613.11")
def test_613_11_every_ordered_pair_of_the_pools_hand_size_permanents():
    """The census the fix was measured with, kept: every ordered pair of the
    shipped permanents that print a hand-size sentence, against the order the
    rule gives. Read backwards against the old reader it names seven pairs."""
    # Through ``compilation_units``: the question is about printed text, and a
    # multi-face card read whole has none.
    catalog = {
        unit.name: unit for unit in compilation_units(load_catalog())
        if any(hand_size_line(line) for line in (unit.oracle_text or "").splitlines())
    }
    printers = sorted(catalog)
    assert len(printers) >= 5, printers

    def effect_of(card):
        (effect,) = [
            found for line in (card.oracle_text or "").splitlines()
            if (found := hand_size_effect(line)) is not None
        ]
        return effect

    examined = 0
    for first, second in itertools.permutations(printers, 2):
        cards = (catalog[first], catalog[second])
        chosen = tuple(card for card in cards if effect_of(card)[2] == "chosen_player")
        expected: int | None = DEFAULT_MAXIMUM_HAND_SIZE
        for card in cards:
            kind, amount, _seat = effect_of(card)
            if kind == "no_maximum":
                expected = None
            elif kind == "set":
                expected = amount
            elif expected is not None:
                expected += amount
        if expected is not None:
            expected = max(0, expected)
        game = _board(*cards, opponent_chooses=chosen)
        assert maximum_hand_size(game, 0) == expected, (first, second)
        examined += 1
    assert examined >= 20


@pytest.mark.cr("402.2")
def test_402_2_a_hand_size_sentence_saying_more_is_not_claimed():
    """The table is anchored on the whole sentence: a count it does not take
    must stay unclaimed rather than be read as its first few words."""
    assert hand_size_line("Your maximum hand size is reduced by two.")
    assert hand_size_line("Your maximum hand size is increased by 1.")
    assert not hand_size_line(
        "Your maximum hand size is reduced by one for each creature you control."
    )
    assert not hand_size_line("Your maximum hand size is reduced.")
    assert not hand_size_line("Each opponent's maximum hand size is reduced by seven.")
