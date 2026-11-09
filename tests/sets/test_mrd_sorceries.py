"""Mirrodin sorceries.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("MRD")` / `set_cards("MRD")` — never a new
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


# ==== W1G11 ==========================================================
# W1G11's tests go between this line and the "end W1G11" line.

# ==== end W1G11 ======================================================


# ==== W1G12 ==========================================================
# W1G12's tests go between this line and the "end W1G12" line.
#
# The drive list: Mirrodin sorceries that compiled supported on arrival.

from engine import Game as _w1g12_Game
from engine import PlayerState as _w1g12_PlayerState
from engine.models import Permanent as _w1g12_Permanent
from tests.helpers import resolve_stack as _w1g12_resolve_stack


def _w1g12_table(set_pool, *, hand=(), theirs=()):
    mrd = set_pool("MRD")
    card = lambda name: mrd[name] if name in mrd else set_pool("LEA")[name]  # noqa: E731
    game = _w1g12_Game(players=[
        _w1g12_PlayerState("A", hand=[card(n) for n in hand], library=[card("Forest")] * 12),
        _w1g12_PlayerState("B", library=[card("Island")] * 12),
    ])
    game.enforce_mana_costs = False
    placed = []
    for name in theirs:
        permanent = _w1g12_Permanent(card=card(name))
        game._put_permanent_onto_battlefield(1, permanent, None)
        placed.append(permanent)
    game.start_turn(0)
    game._settle()
    return game, placed


def test_w1g12_deconstruct_destroys_an_artifact_and_adds_ggg(set_pool):
    game, (myr,) = _w1g12_table(set_pool, hand=["Deconstruct"], theirs=["Alpha Myr"])
    assert game.queue_from_hand(0, "Deconstruct", target_permanent_ids=[myr.permanent_id]).supported
    _w1g12_resolve_stack(game)
    assert not game.is_on_battlefield(myr)
    assert game.players[0].mana_pool["G"] == 3


def test_w1g12_molten_rain_burns_only_for_a_nonbasic_land(set_pool):
    game, (seat, mountain) = _w1g12_table(
        set_pool, hand=["Molten Rain", "Molten Rain"],
        theirs=["Seat of the Synod", "Mountain"],
    )
    assert game.queue_from_hand(0, "Molten Rain", target_permanent_ids=[seat.permanent_id]).supported
    _w1g12_resolve_stack(game)
    assert not game.is_on_battlefield(seat) and game.players[1].life == 18
    assert game.queue_from_hand(
        0, "Molten Rain", target_permanent_ids=[mountain.permanent_id],
    ).supported
    _w1g12_resolve_stack(game)
    assert not game.is_on_battlefield(mountain) and game.players[1].life == 18

# ==== end W1G12 ======================================================
