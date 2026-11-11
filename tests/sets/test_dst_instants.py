"""Darksteel instants.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("DST")` / `set_cards("DST")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.
#
# Stand Together, from the drive list: supported on arrival and placing all
# four counters on the first creature named.

from engine import Game as _W1G1Game, PlayerState as _W1G1PlayerState
from engine.models import Permanent as _W1G1Permanent
from engine.named_counters import counters_on as _w1g1_counters_on
from engine.oracle import compile_card_oracle as _w1g1_compile
from engine.targeting import derive_cast_spec as _w1g1_cast_spec
from tests.helpers import settle as _w1g1_settle


def test_w1g1_stand_together_puts_two_counters_on_each_of_two_creatures(set_pool):
    """"Put two +1/+1 counters on target creature and two +1/+1 counters on
    another target creature." Two announcements (the printed "another", CR
    601.2c), so the picker asks for two distinct creatures, one creature named
    twice is refused, and each takes two counters — the conjunction used to
    lower as two one-target steps, one picker, and four counters on the first
    creature."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    card = dst["Stand Together"]
    spec = _w1g1_cast_spec(card, _w1g1_compile(card))
    assert spec["kind"] == "roles"
    assert [role["role"] for role in spec["roles"]] == ["creature", "another creature"]

    game = _W1G1Game(players=[
        _W1G1PlayerState(name="P0", hand=[card, card], library=[lea["Island"]] * 5),
        _W1G1PlayerState(name="P1", library=[lea["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    _w1g1_settle(game)
    bears, ogre = (_W1G1Permanent(card=lea["Grizzly Bears"]), _W1G1Permanent(card=lea["Gray Ogre"]))
    game._put_permanent_onto_battlefield(0, bears, None)
    game._put_permanent_onto_battlefield(1, ogre, None)
    _w1g1_settle(game)

    twice = game.cast_from_hand(
        0, "Stand Together", target_permanent_ids=[bears.permanent_id, bears.permanent_id]
    )
    assert not twice.supported

    cast = game.cast_from_hand(
        0, "Stand Together", target_permanent_ids=[bears.permanent_id, ogre.permanent_id]
    )
    assert cast.supported, cast
    _w1g1_settle(game)

    assert _w1g1_counters_on(bears, "+1/+1") == 2 and bears.effective_power == 4
    assert _w1g1_counters_on(ogre, "+1/+1") == 2 and ogre.effective_power == 4

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
