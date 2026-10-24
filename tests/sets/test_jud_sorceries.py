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

import pytest as _w1g2_pytest

from engine import Game as _W1G2Game, PlayerState as _W1G2PlayerState
from engine.models import Permanent as _W1G2Permanent
from tests.helpers import resolve_stack as _w1g2_resolve_stack


@_w1g2_pytest.mark.parametrize(
    ("graveyard", "survives", "damage", "counters"),
    [(0, True, 0, 2), (7, False, 6, 2)],
    ids=["four-damage-prevented", "threshold-six-unpreventable"],
)
def test_w1g2_lightning_surge_against_a_phantom(
    set_pool, catalog_by_name, graveyard, survives, damage, counters,
):
    """Lightning Surge, from the drive list, against Phantom Centaur (3
    counters, 2/0). Without threshold its 4 damage is prevented for a counter.
    With seven cards in its caster's graveyard it deals 6 "and the damage can't
    be prevented": the 6 is marked, and the Phantom still pays its counter
    (2022-12-08: "the damage is dealt and a +1/+1 counter is removed",
    CR 615.12) — so a 4/1 takes 6 and dies."""
    jud = set_pool("JUD")
    island = catalog_by_name["Island"]
    game = _W1G2Game(players=[
        _W1G2PlayerState(name="Alice", library=[island] * 5),
        _W1G2PlayerState(name="Bob", library=[island] * 5,
                         graveyard=[island] * graveyard),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 1
    game.current_turn_phase = "main1"
    centaur = _W1G2Permanent(card=jud["Phantom Centaur"])
    game._put_permanent_onto_battlefield(0, centaur, None)
    _w1g2_resolve_stack(game)
    game.players[1].hand.append(jud["Lightning Surge"])
    result = game.cast_from_hand(
        1, "Lightning Surge", target_player_index=0,
        target_permanent_ids=[centaur.permanent_id],
    )
    assert result.supported, result.details
    _w1g2_resolve_stack(game)
    damage_marked = centaur.damage_marked
    game._settle()

    assert game.is_on_battlefield(centaur) is survives
    assert damage_marked == damage
    assert int(centaur.metadata.get("plus_counters", 0)) == counters

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
