"""Mirrodin creatures, the later groups' sections (legendary ones too).

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


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

from engine import Game as _W1G5Game
from engine import PlayerState as _W1G5PlayerState
from engine.models import Permanent as _W1G5Permanent
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def test_w1g5_arc_slogger_exiles_ten_to_deal_two(set_pool):
    """Drive list. "{R}, Exile the top ten cards of your library: This
    creature deals 2 damage to any target." With twelve cards the cost is
    paid and Bob takes 2; with nine it cannot be (CR 601.2h): nothing is paid,
    nothing exiled."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    for library, life, left in ((12, 18, 2), (9, 20, 9)):
        alice = _W1G5PlayerState(name="Alice", library=[lea["Plains"]] * library)
        bob = _W1G5PlayerState(name="Bob", library=[lea["Island"]] * 6)
        game = _W1G5Game(players=[alice, bob])
        game.enforce_mana_costs = True
        game.interactive_seats = {0}
        game.active_player_index = game.priority_player_index = 0
        game.current_phase = "main"
        game.current_turn_phase, game.current_step = "precombat_main", None
        slogger = _W1G5Permanent(card=mrd["Arc-Slogger"])
        game._put_permanent_onto_battlefield(0, slogger, None)
        slogger.metadata["summoning_sickness_turn"] = -99
        game._sync_control()
        alice.mana_pool["R"] = 1
        result = game.activate_permanent_ability(
            0, "Arc-Slogger", permanent_index=game.battlefield_index_of(slogger),
            ability_index=0, target_player_index=1,
        )
        assert result.supported is (library >= 10), result.details
        _w1g5_resolve_stack(game)
        assert (bob.life, len(alice.library)) == (life, left)
        assert len(alice.exile) == library - left

# ==== end W1G5 ======================================================


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

# ==== end W1G12 ======================================================
