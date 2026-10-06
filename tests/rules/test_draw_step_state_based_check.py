"""CR 704.3 in the draw step — the state-based check between the step's draw
(CR 504.1) and its priority window (CR 504.2).

"Whenever a player would get priority, the game checks for any of the listed
conditions for state-based actions" (CR 704.3), and CR 121.4 names the one this
step can create by itself: "A player who attempts to draw a card from a library
with no cards in it loses the game the next time a player would receive
priority." The draw step went from its draw straight to the priority window,
which runs no check while the stack is empty — so a seat that decked itself
there stayed in the game through its own main phase.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from tests.helpers import _mk_card

_W2G6_LAND = _mk_card(name="W2G6 Acre", type_line="Land")


def _w2g6_at_the_draw_step(*libraries, turn: int = 2) -> Game:
    """One seat per library, seat 0's upkeep just finished."""
    game = Game(players=[
        PlayerState(name=f"P{seat + 1}", library=list(library))
        for seat, library in enumerate(libraries)
    ])
    game.turn = turn
    game.begin_turn_bookkeeping(0)
    game.resolve_untap_step(0)
    game.resolve_upkeep(0)
    return game


@pytest.mark.cr("704.5b", "121.4", "704.3", "504.2")
def test_w2g6_704_5b_decking_in_the_draw_step_loses_before_anyone_has_priority():
    """The draw finds nothing; the check that precedes the step's priority
    window finds the attempt, and the seat has lost while it is still the draw
    step — not a main phase later."""
    game = _w2g6_at_the_draw_step([], [_W2G6_LAND] * 3)

    drawn = game.resolve_draw_step(0, defer_priority=True)

    assert drawn == 0
    assert game.current_step == "draw"
    assert game.players[0].lost
    assert not game.players[0].drew_from_empty, "the attempt has been answered"
    assert any("704.5b" in line for line in game.log)
    assert not game.players[1].lost


@pytest.mark.cr("704.5b", "504.1")
def test_w2g6_704_5b_a_library_that_covers_the_draw_loses_nobody():
    """The check runs on every draw step; it is the empty library that loses."""
    game = _w2g6_at_the_draw_step([_W2G6_LAND], [_W2G6_LAND] * 3)

    assert game.resolve_draw_step(0, defer_priority=True) == 1

    assert not game.players[0].lost and not game.players[1].lost
    assert [card.name for card in game.players[0].hand] == ["W2G6 Acre"]


@pytest.mark.cr("704.5b", "103.8c")
def test_w2g6_103_8c_a_three_seat_table_draws_on_its_first_turn_and_can_deck_there():
    """Only a two-player game skips the first draw step (CR 103.8a), so at a
    table of three the first seat draws on turn one — and an empty library is
    a loss there. This is the fixture shape that was passing on the missing
    check: three seats, no libraries, a first turn started."""
    game = _w2g6_at_the_draw_step([], [_W2G6_LAND] * 3, [_W2G6_LAND] * 3, turn=1)

    game.resolve_draw_step(0, defer_priority=True)
    assert game.players[0].lost

    duel = _w2g6_at_the_draw_step([], [_W2G6_LAND] * 3, turn=1)
    duel.resolve_draw_step(0, defer_priority=True)
    assert not duel.players[0].lost, "CR 103.8a: no draw, so no attempt"
