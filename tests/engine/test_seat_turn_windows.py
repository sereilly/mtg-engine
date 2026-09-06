"""The seat-turn window — a mark that takes hold on a turn nobody is taking yet.

``engine/turn_state.py``'s third record, beside "what state did this permanent
start the turn in" and "which of a seat's turns did it last attack on". Pool-wide
rather than a set's, which is why it is here: Wall of Dust (LEG) wrote the shape
inline for one restriction, and Oracle en-Vec (TMP) prints three more clauses
over it — a requirement, a blanket restriction and an end-step destruction, all
scoped to "that player's next turn".

The card-level behaviour is tested where the cards are. What is tested here is
the comparison itself, which no two-player game can exercise honestly: a stamp
compared on its seat alone holds on every one of that player's turns forever,
and one compared on its ordinal alone holds on whichever player's turn happens
to share the number. In a duel those two mistakes are invisible half the time.
"""

from engine import Game, PlayerState
from engine.turn_state import (seats_next_turn_window, stamped_turn_has_passed,
                               stamped_turn_is_now)


def _seats(count: int) -> Game:
    return Game(players=[PlayerState(name=f"P{i}") for i in range(count)])


def test_the_window_names_the_seats_own_next_turn():
    """``+1`` against that seat's counter, not against ``game.turn``.

    A seat's counter does not move while its opponents take their turns, so
    "your next turn" is one ordinal up however many turns away it is — which is
    the whole difference between this and a countdown of turn ends.
    """
    game = _seats(4)
    game.seat_turn_counts = {0: 5, 1: 4, 2: 4, 3: 4}
    assert seats_next_turn_window(game, 2) == {"seat": 2, "seat_turn": 5}
    assert seats_next_turn_window(game, 0) == {"seat": 0, "seat_turn": 6}


def test_both_halves_of_the_comparison_are_required():
    """Four seats, because that is where either half alone stops working."""
    game = _seats(4)
    game.seat_turn_counts = {0: 1, 1: 1, 2: 1, 3: 1}
    stamp = seats_next_turn_window(game, 2)      # seat 2's turn number 2

    # Seat 3 reaches turn 2 first. Same ordinal, wrong seat.
    game.active_player_index = 3
    game.seat_turn_counts = {0: 2, 1: 2, 2: 1, 3: 2}
    assert not stamped_turn_is_now(game, stamp)
    assert not stamped_turn_has_passed(game, stamp)

    game.active_player_index = 2
    game.seat_turn_counts = {0: 2, 1: 2, 2: 2, 3: 2}
    assert stamped_turn_is_now(game, stamp)
    assert not stamped_turn_has_passed(game, stamp)

    # A later turn of the same seat: right seat, wrong ordinal.
    game.seat_turn_counts = {0: 3, 1: 3, 2: 3, 3: 3}
    assert not stamped_turn_is_now(game, stamp)
    assert stamped_turn_has_passed(game, stamp)


def test_a_missing_or_malformed_stamp_answers_no():
    """A permanent that carries no stamp is not restricted and not compelled.

    ``None`` is what ``metadata.get`` returns for every permanent in the game
    that this effect never touched, so it is the common case rather than a
    defensive branch.
    """
    game = _seats(2)
    game.seat_turn_counts = {0: 1, 1: 1}
    for value in (None, {}, "next turn", {"seat": 1}, {"seat_turn": 1}):
        assert not stamped_turn_is_now(game, value)
        assert not stamped_turn_has_passed(game, value)
