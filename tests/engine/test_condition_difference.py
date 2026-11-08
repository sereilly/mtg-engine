"""A hand measured against the caster's, and "the difference" it leads by.

Balance of Power (8ED) is the card: "If target opponent has more cards in hand
than you, draw cards equal to the difference." Its own tests are in
`tests/sets/test_8ed_cards.py`; these are the grammar's half — the shapes beside
it that must refuse rather than guess, and the condition read alone, by
invented cards, because it is a template and not one card.

"The difference" is read as a back-reference (``oracle_types.CONDITION_DIFFERENCE``)
and bound only by a conditional whose condition compared one *named* seat's
hand with the caster's (``rebinding.rebind_difference_to_condition``).
Everywhere else nothing binds it, and the lowering refuses a back-reference
with no producer.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.grammar.errors import GrammarError, LoweringError
from engine.grammar.lower import lower_ability
from engine.grammar.parser import parse_line
from engine.oracle import compile_card_oracle

from tests.helpers import _mk_card, resolve_stack


def _lower(line: str):
    return lower_ability(parse_line(line))


@pytest.mark.parametrize(
    "line",
    [
        # Nothing measured anything: the words name no quantity.
        "Draw cards equal to the difference.",
        # "An opponent" is asked of every opponent, so there is one difference
        # per opponent and nothing to say which.
        "If an opponent has more cards in hand than you, draw cards equal to the difference.",
        # A bound against a printed number compares no two counts.
        "If target opponent has five or more cards in hand, draw cards equal to the difference.",
    ],
    ids=["no condition", "an existential seat", "a printed bound"],
)
def test_the_difference_refuses_where_no_condition_compared_two_named_counts(line):
    with pytest.raises(LoweringError, match="condition_difference"):
        _lower(line)


@pytest.mark.parametrize(
    "line",
    [
        # A pile compared with itself.
        "If you have more cards in hand than you, draw a card.",
        # "A player" is the life superlative's existential, which the zone
        # evaluator does not answer.
        "If a player has more cards in hand than you, draw a card.",
    ],
)
def test_the_hand_comparison_refuses_a_seat_it_cannot_answer(line):
    with pytest.raises(GrammarError):
        parse_line(line)


def test_the_hand_comparison_carries_its_seat_and_margin():
    """The same op and margin reader the "controls more … than you" clause
    uses: the bare "more" rides as 0 (a lead of one), "at least two more" as 2,
    and "an opponent" stays the existential the evaluator asks of each."""
    (bare,) = _lower("If target opponent has more cards in hand than you, draw a card.")
    assert bare.payload["condition"] == {
        "kind": "zone_card_count", "player": "target_opponent", "zone": "hand",
        "op": "more_than_you", "value": 0,
    }
    (margin,) = _lower(
        "If target opponent has at least two more cards in hand than you, draw a card."
    )
    assert margin.payload["condition"]["value"] == 2
    (anyone,) = _lower("If an opponent has more cards in hand than you, draw a card.")
    assert anyone.payload["condition"]["player"] == "opponent"


def _table(*hand_sizes: int, spell) -> Game:
    """Seat 0 holds *spell* plus ``hand_sizes[0]`` Islands; every other seat its
    own number of Islands."""
    island = _mk_card("Island", "Basic Land — Island")
    forest = _mk_card("Forest", "Basic Land — Forest")
    players = [
        PlayerState(
            name=f"P{seat}",
            hand=([spell] if seat == 0 else []) + [island] * size,
            library=[forest] * 12,
        )
        for seat, size in enumerate(hand_sizes)
    ]
    game = Game(players=players)
    game.interactive_seats = set()
    return game


@pytest.mark.parametrize(
    ("hands", "drawn"),
    [((1, 2), 0), ((1, 3), 1)],
    ids=["a lead of one is short", "a lead of two holds"],
)
def test_a_printed_margin_is_the_lead_the_target_must_reach(hands, drawn):
    """"At least two more" holds on a lead of two and not of one — an invented
    card, since no printing carries the margin on a hand yet."""
    spell = _mk_card(
        "Measured Study", "{U}", "Sorcery",
        "If target opponent has at least two more cards in hand than you, draw a card.",
    )
    assert compile_card_oracle(spell).supported
    game = _table(*hands, spell=spell)

    assert game.cast_from_hand(0, "Measured Study", target_player_index=1).supported
    resolve_stack(game)

    assert len(game.players[0].hand) == hands[0] + drawn


@pytest.mark.parametrize(
    ("hands", "drawn"),
    [((1, 1, 1), 0), ((1, 0, 3), 1)],
    ids=["nobody ahead", "one opponent of two ahead"],
)
def test_an_opponent_ahead_is_any_one_opponent(hands, drawn):
    """"If an opponent has more cards in hand than you" is an existential over
    the opponents (CR 102.2): one of two being ahead is enough."""
    spell = _mk_card(
        "Envious Glance", "{U}", "Sorcery",
        "If an opponent has more cards in hand than you, draw a card.",
    )
    assert compile_card_oracle(spell).supported
    game = _table(*hands, spell=spell)

    assert game.cast_from_hand(0, "Envious Glance").supported
    resolve_stack(game)

    assert len(game.players[0].hand) == hands[0] + drawn
