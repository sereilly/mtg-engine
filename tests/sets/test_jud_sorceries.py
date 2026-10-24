"""Judgment sorceries.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("JUD")` / `set_cards("JUD")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.
#
# "Any player may have <this> deal N damage to them. If no one does, <effect>."
# CR 118.12a's toll over a set of seats, printed the long way round: the
# ``unless_player_pays`` chain with a *deed* for its price
# (``ast.UnlessPlayerPays.action``). Each seat is asked in turn from the active
# player (CR 101.4); the first that takes the damage ends the chain; the effect
# happens only when nobody does.

import pytest as _w1g5_pytest  # noqa: E402

from tests.sets import jud_w1g5_helpers as _w1g5  # noqa: E402


def _w1g5_cast(game, name, **targets):
    result = game.cast_from_hand(0, name, **targets)
    assert result.supported, result.details
    game.resolve_top_of_stack(pause_for_choices=True)
    return result


def test_w1g5_browbeat_asks_each_seat_from_the_active_player_and_the_taker_ends_it(set_pool):
    """The caster is asked first and declines; the opponent takes the five.
    Nobody draws: CR 118.12a's "if no one does" is false."""
    game = _w1g5.table(set_pool, hands=(["Browbeat"], []), interactive=(0, 1))
    game.start_turn(0)
    _w1g5_cast(game, "Browbeat", target_player_index=0)

    assert _w1g5.answer_offers(game, {1: True}) == [0, 1]
    _w1g5.settle(game)

    assert [player.life for player in game.players] == [20, 15]
    assert game.players[0].hand == []
    assert "Browbeat dealt 5 damage to P2" in game.log


def test_w1g5_browbeat_nobody_taking_it_draws_the_target_not_the_last_seat_asked(set_pool):
    """The unpaid branch reads the target the spell chose — the opponent here —
    and not the seat the last link of the chain was aimed at."""
    game = _w1g5.table(set_pool, hands=(["Browbeat"], []), interactive=(0, 1))
    game.start_turn(0)
    _w1g5_cast(game, "Browbeat", target_player_index=1)

    assert _w1g5.answer_offers(game, {}) == [0, 1]
    _w1g5.settle(game)

    assert [player.life for player in game.players] == [20, 20]
    assert [len(player.hand) for player in game.players] == [0, 3]


def test_w1g5_the_caster_may_take_browbeats_damage_and_nobody_else_is_asked(set_pool):
    game = _w1g5.table(set_pool, hands=(["Browbeat"], []), interactive=(0, 1))
    game.start_turn(0)
    _w1g5_cast(game, "Browbeat", target_player_index=1)

    assert _w1g5.answer_offers(game, {0: True}) == [0]
    _w1g5.settle(game)

    assert [player.life for player in game.players] == [15, 20]
    assert [len(player.hand) for player in game.players] == [0, 0]


def test_w1g5_browbeat_at_a_three_seat_table_asks_in_turn_order_from_the_active_player(set_pool):
    """Seat 1 is active: it is asked first, then seat 2, then the caster."""
    game = _w1g5.table(
        set_pool, hands=([], ["Browbeat"], []), interactive=(0, 1, 2),
    )
    game.start_turn(1)
    result = game.cast_from_hand(1, "Browbeat", target_player_index=1)
    assert result.supported, result.details
    held = len(game.players[1].hand)
    game.resolve_top_of_stack(pause_for_choices=True)

    assert _w1g5.answer_offers(game, {0: True}) == [1, 2, 0]
    _w1g5.settle(game)

    assert [player.life for player in game.players] == [15, 20, 20]
    assert len(game.players[1].hand) == held


def test_w1g5_book_burning_mills_its_target_when_nobody_takes_six(set_pool):
    game = _w1g5.table(set_pool, hands=(["Book Burning"], []), interactive=(0, 1))
    game.start_turn(0)
    _w1g5_cast(game, "Book Burning", target_player_index=1)

    _w1g5.answer_offers(game, {})
    _w1g5.settle(game)

    assert [len(player.library) for player in game.players] == [20, 14]
    assert len(game.players[1].graveyard) == 6


def test_w1g5_book_burning_taken_burns_the_taker_and_mills_nobody(set_pool):
    game = _w1g5.table(set_pool, hands=(["Book Burning"], []), interactive=(0, 1))
    game.start_turn(0)
    _w1g5_cast(game, "Book Burning", target_player_index=1)

    _w1g5.answer_offers(game, {1: True})
    _w1g5.settle(game)

    assert [player.life for player in game.players] == [20, 14]
    assert [len(player.library) for player in game.players] == [20, 20]


def test_w1g5_breaking_point_destroys_every_creature_past_a_regeneration_shield(set_pool):
    """"Creatures destroyed this way can't be regenerated" rides the unpaid
    branch: a Drudge Skeletons with a shield up still goes."""
    game = _w1g5.table(set_pool, hands=(["Breaking Point"], []), interactive=(0, 1))
    game.start_turn(0)
    _w1g5.put(game, set_pool, 0, "Grizzly Bears")
    skeletons = _w1g5.put(game, set_pool, 1, "Drudge Skeletons")
    shield = game.activate_permanent_ability(1, "Drudge Skeletons")
    assert shield.supported, shield.details
    _w1g5.settle(game)
    assert skeletons.regeneration_shield == 1

    _w1g5_cast(game, "Breaking Point")
    _w1g5.answer_offers(game, {})
    _w1g5.settle(game)

    assert _w1g5.names(game, 0) == [] and _w1g5.names(game, 1) == []
    assert "Drudge Skeletons regenerated" not in game.log


def test_w1g5_breaking_point_taken_spares_the_board(set_pool):
    game = _w1g5.table(set_pool, hands=(["Breaking Point"], []), interactive=(0, 1))
    game.start_turn(0)
    _w1g5.put(game, set_pool, 1, "Grizzly Bears")
    _w1g5_cast(game, "Breaking Point")

    _w1g5.answer_offers(game, {1: True})
    _w1g5.settle(game)

    assert [player.life for player in game.players] == [20, 14]
    assert _w1g5.names(game, 1) == ["Grizzly Bears"]


@_w1g5_pytest.mark.parametrize("name", ["Browbeat", "Book Burning", "Breaking Point"])
def test_w1g5_the_offer_holds_the_spell_on_the_stack_until_it_is_answered(set_pool, name):
    """CR 608.2: the spell is still resolving while a seat is being asked, so
    it is on the stack and the caster does not have priority to do anything
    else in between."""
    game = _w1g5.table(set_pool, hands=([name], []), interactive=(0, 1))
    game.start_turn(0)
    targets = {} if name == "Breaking Point" else {"target_player_index": 1}
    _w1g5_cast(game, name, **targets)

    assert _w1g5.owed(game) == [0]
    assert [item.card.name for item in game.stack] == [name]

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

# ==== end W1G10 ======================================================
