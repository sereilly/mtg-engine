"""Betrayers of Kamigawa enchantments, Auras included.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("BOK")` / `set_cards("BOK")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== w1g1 ==========================================================
# w1g1's tests go between this line and the "end w1g1" line.

# ==== end w1g1 ======================================================


# ==== w1g2 ==========================================================
# w1g2's tests go between this line and the "end w1g2" line.

# ==== end w1g2 ======================================================


# ==== w1g3 ==========================================================
# w1g3's tests go between this line and the "end w1g3" line.

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.

# ==== end w1g4 ======================================================


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

# Damage redirection from an Aura's host (CR 614.9, 303.4e).

import pytest as _w1g5_pytest

from engine import Game as _W1G5Game
from engine import PlayerState as _W1G5PlayerState
from engine.models import Permanent as _W1G5Permanent
from tests.helpers import settle as _w1g5_settle

_W1G5_SEATS = [
    _w1g5_pytest.param(set(), id="nobody-asked"),
    _w1g5_pytest.param({0, 1}, id="interactive"),
]


def _w1g5_table(set_pool, interactive=(), *, hand=(), opponent_hand=()):
    """Two seats on seat 0's first main phase, costs not enforced."""
    lea = set_pool("LEA")
    game = _W1G5Game(players=[
        _W1G5PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * 20,
            hand=list(hand) if seat == 0 else list(opponent_hand),
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    _w1g5_settle(game)
    return game


def _w1g5_put(game, card, seat=0):
    permanent = _W1G5Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


@_w1g5_pytest.mark.parametrize("interactive", _W1G5_SEATS)
@_w1g5_pytest.mark.parametrize("aim", ["creature", "player"])
def test_w1g5_ward_of_piety_moves_the_next_point_off_its_host(
    set_pool, interactive, aim,
):
    """"Enchant creature / {1}{W}: The next 1 damage that would be dealt to
    enchanted creature this turn is dealt to any target instead." Ward of
    Piety's controller activates it (CR 303.4e) at the opposing Craw Wurm
    or at the opponent; a Lightning Bolt at the enchanted Grizzly Bears
    deals 1 there and 2 to the Bears, which die (CR 615.7's pool read with
    CR 614.9's verb). A Bolt at the Wurm itself is not the Ward's
    business."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g5_table(
        set_pool, interactive, hand=[bok["Ward of Piety"]],
        opponent_hand=[lea["Lightning Bolt"], lea["Lightning Bolt"]],
    )
    bears = _w1g5_put(game, lea["Grizzly Bears"])
    giant = _w1g5_put(game, lea["Craw Wurm"], seat=1)
    assert game.cast_from_hand(
        0, "Ward of Piety", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g5_settle(game)
    ward = next(p for p in game.players[0].battlefield if p.card.name == "Ward of Piety")
    announce = (
        {"target_permanent_ids": [giant.permanent_id]} if aim == "creature"
        else {"target_player_index": 1}
    )
    result = game.activate_permanent_ability(
        0, ward.card.name, permanent_index=game.battlefield_index_of(ward),
        **announce,
    )
    assert result.supported, (result.details, game.log[-4:])
    _w1g5_settle(game)
    assert game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[giant.permanent_id],
    ).supported
    _w1g5_settle(game)
    assert giant.damage_marked == 3 and bears.damage_marked == 0, game.log
    giant.damage_marked = 0
    assert game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g5_settle(game)
    if aim == "creature":
        assert giant.damage_marked == 1 and game.players[1].life == 20, game.log
    else:
        assert giant.damage_marked == 0 and game.players[1].life == 19, game.log
    assert not game.is_on_battlefield(bears), game.log
    assert any("is dealt to" in line and "(Ward of Piety)" in line
               for line in game.log), game.log


# ==== end w1g5 ======================================================


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

# ==== end w1g7 ======================================================


# ==== w1g8 ==========================================================
# w1g8's tests go between this line and the "end w1g8" line.

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

# ==== end w1g9 ======================================================


# ==== w1g10 ==========================================================
# w1g10's tests go between this line and the "end w1g10" line.

# ==== end w1g10 ======================================================
