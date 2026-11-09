"""Mirrodin lands.

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
#
# Blinkmoth Well, supported on arrival and driven: its {C}, and "Tap target
# noncreature artifact" refusing an artifact creature at announcement.
from engine import Game as _W1G8Game
from engine.models import Permanent as _W1G8Permanent
from engine.models import PlayerState as _W1G8PlayerState
from engine.oracle import compile_card_oracle as _w1g8_compile

from tests.helpers import resolve_stack as _w1g8_resolve_stack


def test_w1g8_blinkmoth_well_taps_only_a_noncreature_artifact(set_pool):
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = _W1G8Game(players=[
        _W1G8PlayerState(name="A", library=[lea["Plains"]] * 5),
        _W1G8PlayerState(name="B", library=[lea["Plains"]] * 5),
    ])
    game.enforce_mana_costs = False
    well = _W1G8Permanent(card=mrd["Blinkmoth Well"])
    ring = _W1G8Permanent(card=lea["Sol Ring"])
    myr = _W1G8Permanent(card=mrd["Iron Myr"])
    game._put_permanent_onto_battlefield(0, well, None)
    game._put_permanent_onto_battlefield(1, ring, None)
    game._put_permanent_onto_battlefield(1, myr, None)
    _w1g8_resolve_stack(game)
    game.start_turn(0)
    game._close_current_priority_step()
    ability = _w1g8_compile(well.card).activated_abilities[1]
    offered = [e.get("name") for e in game.activation_offer(0, well, ability)["valid_targets"]]
    assert offered == ["Sol Ring"]
    refused = game.activate_permanent_ability(
        0, "Blinkmoth Well", ability_index=1, target_permanent_ids=[myr.permanent_id]
    )
    assert not refused.supported and not well.tapped
    assert game.activate_permanent_ability(
        0, "Blinkmoth Well", ability_index=1, target_permanent_ids=[ring.permanent_id]
    ).supported
    _w1g8_resolve_stack(game)
    assert ring.tapped and well.tapped
    well.tapped = False
    assert game.tap_land_for_mana(0, "Blinkmoth Well")
    assert game.players[0].mana_pool["C"] == 1


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
