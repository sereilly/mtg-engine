"""What a seat the engine plays names in secret (W2G1, Goblin Game).

"Each player hides at least one item … Each player loses life equal to the
number of items they revealed. The player who revealed the fewest items then
loses half their life, rounded up." Every point named is a point of life, and
the least pays half of what it has left — so ``ai_policy.choose_secret_number``
has two lines to pick between, and picks from the life totals alone.

It is a default like any other: deterministic, a function of public state, and
never the answer that loses the game where another is legal.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_policy import choose_secret_number


def _table(lives, lost=()):
    game = Game(players=[
        PlayerState(name=f"P{seat}") for seat in range(len(lives))
    ])
    for seat, (player, life) in enumerate(zip(game.players, lives)):
        player.life = life
        player.lost = seat in lost
    return game


def _left_after(life, mine, theirs):
    """What a duel seat has left after naming *mine* against *theirs*."""
    left = life - mine
    if mine <= theirs:
        left -= -(-max(0, left) // 2)
    return left


def test_w2g1_level_life_totals_name_the_floor():
    """Nothing to gain by outbidding a seat with as much life as you: naming
    the rival's whole life total would cost everything."""
    game = _table([20, 20])
    assert choose_secret_number(game, 0, 1) == 1
    assert choose_secret_number(game, 1, 1) == 1


@pytest.mark.parametrize("lives, expected", [
    ([30, 5], 5),    # 25 left unhalved, against 14 on the quiet line
    ([20, 9], 9),    # 11 against 9
    ([20, 10], 10),  # 10 against 9
    ([20, 11], 1),   # 9 is not better than 9
    ([20, 19], 1),
])
def test_w2g1_a_seat_far_enough_ahead_outbids_the_weakest_rival(lives, expected):
    """It names the rival's whole life total — a number that rival can only
    match by naming all the life it has — exactly when that leaves it more
    than the quiet line would."""
    game = _table(lives)
    assert choose_secret_number(game, 0, 1) == expected
    assert choose_secret_number(game, 1, 1) == 1, "the seat behind names the floor"


def test_w2g1_the_weakest_rival_is_the_one_outbid_and_a_seat_that_left_is_nobody():
    """At three seats the bid is the lowest life total among the *other*
    seats still in the game (CR 800.4a)."""
    assert choose_secret_number(_table([40, 30, 6]), 0, 1) == 6
    assert choose_secret_number(_table([40, 30, 6], lost={2}), 0, 1) == 1
    assert choose_secret_number(_table([40, 12, 6], lost={2}), 0, 1) == 12
    assert choose_secret_number(_table([20]), 0, 1) == 1, "nobody to outbid"


def test_w2g1_the_printed_floor_is_the_floor():
    """"At least **two**" on another card is a different least answer, and a
    rival below the floor is outbid by the floor itself."""
    assert choose_secret_number(_table([20, 20]), 0, 2) == 2
    assert choose_secret_number(_table([20, 1]), 0, 3) == 3
    assert choose_secret_number(_table([20, 20]), 0, 0) == 0


def test_w2g1_the_default_never_names_its_own_death_where_it_need_not():
    """Over every pair of life totals from 1 to 40: the answer is at least the
    floor, and it leaves the seat above 0 whenever the floor itself would —
    whatever the rival then names. (A seat at 1 life has no such answer: every
    legal number is lethal, and it names the floor.)"""
    examined = 0
    for mine in range(1, 41):
        for theirs in range(1, 41):
            named = choose_secret_number(_table([mine, theirs]), 0, 1)
            examined += 1
            assert named >= 1
            if mine > 1:
                assert named < mine, (mine, theirs, named)
            if named > 1:
                # Outbidding is taken only when it beats the quiet line even
                # if the rival matches it.
                assert named == theirs
                assert mine - named > _left_after(mine, 1, 1)
    assert examined == 1600


def test_w2g1_the_policy_reads_life_totals_and_nothing_else(set_pool):
    """Deterministic, and blind to everything but the public life totals: a
    table with a full board and a table with none answer alike, and asking
    twice answers the same."""
    from engine.models import Permanent

    bare = _table([24, 9])
    busy = _table([24, 9])
    lea = set_pool("LEA")
    for seat, name in ((0, "Forest"), (1, "Shivan Dragon"), (1, "Mountain")):
        busy._put_permanent_onto_battlefield(seat, Permanent(card=lea[name]), None)
    busy.players[1].hand.append(lea["Lightning Bolt"])
    for seat in (0, 1):
        assert (
            choose_secret_number(bare, seat, 1)
            == choose_secret_number(busy, seat, 1)
            == choose_secret_number(busy, seat, 1)
        )
