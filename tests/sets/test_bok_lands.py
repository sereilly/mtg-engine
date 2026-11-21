"""Betrayers of Kamigawa lands.

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

from engine import Game as _w1g4_Game
from engine import PlayerState as _w1g4_PlayerState
from engine.models import Permanent as _w1g4_Permanent
from tests.helpers import settle as _w1g4_settle


def test_w1g4_gods_eye_leaves_a_spirit_behind(set_pool):
    """"When Gods' Eye is put into a graveyard from the battlefield, create a
    1/1 colorless Spirit creature token": Stone Rain on it leaves the token."""
    lea = set_pool("LEA")
    game = _w1g4_Game(players=[
        _w1g4_PlayerState("A", hand=[lea["Stone Rain"]], library=[lea["Forest"]] * 12),
        _w1g4_PlayerState("B", library=[lea["Forest"]] * 12),
    ])
    game.enforce_mana_costs = False
    eye = _w1g4_Permanent(card=set_pool("BOK")["Gods' Eye, Gate to the Reikai"])
    game._put_permanent_onto_battlefield(0, eye, None)
    game.start_turn(0)
    game._settle()
    result = game.cast_from_hand(
        0, "Stone Rain", target_player_index=0, target_permanent_ids=[eye.permanent_id],
    )
    assert result.supported, result.details
    _w1g4_settle(game)
    (token,) = game.controlled_by(0)
    assert token.has_type("spirit") and token.is_creature, game.log
    assert (token.effective_power, token.effective_toughness) == (1, 1)
    from engine.handlers._filters import permanent_effective_colors

    assert permanent_effective_colors(token) == set()

# ==== end w1g4 ======================================================


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

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
