"""Champions of Kamigawa instants — the later groups' sections.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("CHK")` / `set_cards("CHK")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

# ==== end w1g7 ======================================================


# ==== w1g8 ==========================================================
# w1g8's tests go between this line and the "end w1g8" line.

from engine import PlayerState as _w1g8_PlayerState
from engine.models import Permanent as _w1g8_Permanent
from tests.helpers import (
    _game as _w1g8_game,
    _nosick as _w1g8_nosick,
    settle as _w1g8_settle,
    stock_libraries as _w1g8_stock_libraries,
)


def _w1g8_table(mine=(), theirs=(), *, hand=(), opponent_hand=()):
    """Two seats on seat 0's precombat main phase of turn 2, the permanents
    placed through the entry funnel, libraries stocked."""
    game = _w1g8_game(
        _w1g8_PlayerState(name="P1", hand=list(hand), life=20),
        _w1g8_PlayerState(name="P2", hand=list(opponent_hand), life=20),
    )
    _w1g8_stock_libraries(game)
    game.turn = 2
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    placed = []
    for seat, cards in ((0, mine), (1, theirs)):
        row = []
        for card in cards:
            permanent = _w1g8_Permanent(card=card)
            game._put_permanent_onto_battlefield(seat, permanent, None)
            row.append(_w1g8_nosick(permanent))
        placed.append(row)
    game._sync_control()
    _w1g8_settle(game)
    return game, placed[0], placed[1]


def _w1g8_zone_names(game, seat, zone):
    return [card.name for card in getattr(game.players[seat], zone)]


# --- Yamabushi's Flame --------------------------------------------------------
# "Yamabushi's Flame deals 3 damage to any target. If a creature dealt damage
# this way would die this turn, exile it instead." A replacement on what the
# damage was *dealt* to (CR 615.1a), for the rest of the turn and by any
# means of dying (CR 700.4).


def test_w1g8_yamabushis_flame_exiles_the_creature_it_kills(set_pool):
    flame = set_pool("CHK")["Yamabushi's Flame"]
    giant = set_pool("LEA")["Hill Giant"]
    game, _, (hill,) = _w1g8_table([], [giant], hand=[flame])
    cast = game.cast_from_hand(
        0, "Yamabushi's Flame", target_permanent_ids=[hill.permanent_id]
    )
    assert cast.supported, cast.details
    _w1g8_settle(game)
    assert _w1g8_zone_names(game, 1, "exile") == ["Hill Giant"]
    assert _w1g8_zone_names(game, 1, "graveyard") == []


def test_w1g8_yamabushis_flame_exiles_a_survivor_that_dies_later_this_turn(set_pool):
    flame = set_pool("CHK")["Yamabushi's Flame"]
    terror = set_pool("LEA")["Terror"]
    craw = set_pool("LEA")["Craw Wurm"]
    game, _, (wurm,) = _w1g8_table([], [craw], hand=[flame, terror])
    assert game.cast_from_hand(
        0, "Yamabushi's Flame", target_permanent_ids=[wurm.permanent_id]
    ).supported
    _w1g8_settle(game)
    assert game.is_on_battlefield(wurm)
    assert game.cast_from_hand(0, "Terror", target_permanent_ids=[wurm.permanent_id]).supported
    _w1g8_settle(game)
    assert _w1g8_zone_names(game, 1, "exile") == ["Craw Wurm"]


def test_w1g8_yamabushis_flame_at_a_player_is_plain_damage(set_pool):
    flame = set_pool("CHK")["Yamabushi's Flame"]
    game, _, _ = _w1g8_table([], [], hand=[flame])
    assert game.cast_from_hand(0, "Yamabushi's Flame", target_player_index=1).supported
    _w1g8_settle(game)
    assert game.players[1].life == 17

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

# ==== end w1g9 ======================================================
