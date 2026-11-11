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

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.
#
# Second Sight, on W1G3's drive list (supported on arrival): a look and a
# reorder on a real library, which the mode-chooser census cannot build (its
# library is ten Forests).

from engine import Game as _W1G3Game
from engine import PlayerState as _W1G3PlayerState
from tests.helpers import settle as _w1g3_settle


def test_w1g3_second_sight_reorders_the_library_its_mode_names(set_pool):
    """"Choose one — • Look at the top five cards of target opponent's
    library, then put them back in any order. • Look at the top five cards of
    your library, then put them back in any order." Each mode rearranges the
    library it names, in the order the caster chooses, and leaves the other
    alone."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    names = ["Forest", "Island", "Swamp", "Mountain", "Plains", "Grizzly Bears"]
    for mode, seat in ((0, 1), (1, 0)):
        alice = _W1G3PlayerState(
            name="Alice", hand=[dst["Second Sight"]], library=[lea[n] for n in names],
        )
        bob = _W1G3PlayerState(name="Bob", library=[lea[n] for n in names])
        game = _W1G3Game(players=[alice, bob])
        game.enforce_mana_costs = False
        game.interactive_seats = {0}
        game.active_player_index = game.priority_player_index = 0
        game._set_phase_and_step("precombat_main", None)
        extra = {"target_player_index": 1} if mode == 0 else {}
        assert game.cast_from_hand(0, "Second Sight", mode_index=mode, **extra).supported
        pick = _w1g3_settle(game, defaults=False)
        assert pick is not None and pick.kind == "reorder_library"
        assert game.confirm_reorder_library(0, [4, 3, 2, 1, 0])
        _w1g3_settle(game)
        looked = game.players[seat].library
        other = game.players[1 - seat].library
        assert [c.name for c in looked] == [
            "Plains", "Mountain", "Swamp", "Island", "Forest", "Grizzly Bears",
        ]
        assert [c.name for c in other] == names

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
