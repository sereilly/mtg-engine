"""Apocalypse artifacts (artifact creatures included).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("APC")` / `set_cards("APC")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ============================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ========================================================


# ==== W1G2 ============================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ========================================================


# ==== W1G3 ============================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ========================================================


# ==== W1G4 ============================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ========================================================


# ==== W1G5 ============================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ========================================================


# ==== W1G6 ============================================================
# W1G6's tests go between this line and the "end W1G6" line.

import pytest as _w1g6_pytest

from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from engine.oracle import compile_card_oracle as _w1g6_compile
from tests.helpers import resolve_stack as _w1g6_resolve_stack

_W1G6_FOUR_TYPES = ("Plains", "Island", "Swamp", "Mountain")


def _w1g6_mask_table(set_pool, mine=(), theirs=()):
    """Mask of Intolerance under seat 0, with *mine* / *theirs* (Alpha's lands)
    beside it and across from it. Returns the game and seat 0's permanents,
    the Mask first."""
    w1g6_game = _W1G6Game(players=[
        _W1G6PlayerState(name="W1G6-A"), _W1G6PlayerState(name="W1G6-B"),
    ])
    w1g6_game.enforce_mana_costs = False
    w1g6_rows = []
    for w1g6_seat, w1g6_names in enumerate((("Mask of Intolerance",) + tuple(mine), theirs)):
        w1g6_row = []
        for w1g6_name in w1g6_names:
            w1g6_card = set_pool("APC").get(w1g6_name) or set_pool("LEA")[w1g6_name]
            w1g6_perm = _W1G6Permanent(card=w1g6_card)
            w1g6_game._put_permanent_onto_battlefield(w1g6_seat, w1g6_perm, None)
            w1g6_row.append(w1g6_perm)
        w1g6_rows.append(w1g6_row)
    return w1g6_game, w1g6_rows[0]  # _w1g6_mask_table


def _w1g6_mask_upkeep(game, seat):
    """Run *seat*'s upkeep; returns what triggered, left on the stack."""
    game.active_player_index = seat
    game.resolve_upkeep(seat, defer_priority=True)
    return [w1g6_item.card.name for w1g6_item in game.stack]  # _w1g6_mask_upkeep


def test_w1g6_mask_of_intolerance_reads_that_players_lands(set_pool):
    """"At the beginning of **each player's** upkeep, if there are four or more
    basic land types among lands **that player** controls, this artifact deals
    3 damage to that player." Domain counted for the player whose upkeep it
    is — the Mask's controller on theirs, the opponent on the opponent's — and
    the damage goes to that same player."""
    program = _w1g6_compile(set_pool("APC")["Mask of Intolerance"])
    assert program.supported, program.reason

    # Four types on the controller's side, one on the other.
    game, _mine = _w1g6_mask_table(
        set_pool, mine=_W1G6_FOUR_TYPES, theirs=("Forest",) * 4,
    )
    assert _w1g6_mask_upkeep(game, 0) == ["Mask of Intolerance"]
    _w1g6_resolve_stack(game)
    assert [player.life for player in game.players] == [17, 20]
    assert "Mask of Intolerance dealt 3 damage to W1G6-A" in game.log
    assert _w1g6_mask_upkeep(game, 1) == []
    assert [player.life for player in game.players] == [17, 20]

    # Three on the controller's side, five on the other: the controller's own
    # upkeep is quiet and the opponent's is not.
    game, _mine = _w1g6_mask_table(
        set_pool, mine=_W1G6_FOUR_TYPES[:3], theirs=_W1G6_FOUR_TYPES + ("Forest",),
    )
    assert _w1g6_mask_upkeep(game, 0) == []
    assert _w1g6_mask_upkeep(game, 1) == ["Mask of Intolerance"]
    _w1g6_resolve_stack(game)
    assert [player.life for player in game.players] == [20, 17]
    assert "Mask of Intolerance dealt 3 damage to W1G6-B" in game.log


@_w1g6_pytest.mark.parametrize("lands, burned", [
    # Types, not lands: four Forests are one type.
    (("Forest",) * 4, False),
    (("Plains", "Island", "Swamp"), False),
    # A dual land is two (CR 305.6: each basic land type it has).
    (("Tropical Island", "Badlands"), True),
    (("Tropical Island", "Swamp"), False),
    (("Plains", "Island", "Swamp", "Mountain", "Forest"), True),
])
def test_w1g6_mask_of_intolerance_counts_types_not_lands(set_pool, lands, burned):
    game, _mine = _w1g6_mask_table(set_pool, mine=lands)

    triggered = _w1g6_mask_upkeep(game, 0)
    _w1g6_resolve_stack(game)

    assert triggered == (["Mask of Intolerance"] if burned else [])
    assert game.players[0].life == (17 if burned else 20)


def test_w1g6_mask_of_intolerance_checks_again_as_it_resolves(set_pool):
    """CR 603.4's second check. The trigger is on the stack over four types; a
    land leaves in response; three types deal nothing. (An upkeep damage
    trigger with an intervening "if" used to be queued as a bare damage event
    with no condition on it, so the answer came too late to matter.)"""
    game, mine = _w1g6_mask_table(set_pool, mine=_W1G6_FOUR_TYPES)

    assert _w1g6_mask_upkeep(game, 0) == ["Mask of Intolerance"]
    game.remove_from_battlefield(mine[-1])
    _w1g6_resolve_stack(game)

    assert game.players[0].life == 20
    assert (
        "Mask of Intolerance ability did nothing: its condition is no longer true"
    ) in game.log

# ==== end W1G6 ========================================================


# ==== W1G7 ============================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ========================================================


# ==== W1G8 ============================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ========================================================


# ==== W1G9 ============================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ========================================================
