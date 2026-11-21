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

from engine import Game as _w1g8_Game, PlayerState as _w1g8_PlayerState
from tests.helpers import stock_libraries as _w1g8_stock_libraries


def test_w1g8_tendo_ice_bridge_spends_its_one_charge_counter_on_a_colour(set_pool):
    """"This land enters with a charge counter on it. / {T}: Add {C}. / {T},
    Remove a charge counter from this land: Add one mana of any color." Played
    from hand it enters with the counter; the second ability makes {U} and
    takes it; with none left the coloured ability is refused and {C} still
    comes."""
    from engine.named_counters import counters_on

    bok = set_pool("BOK")
    game = _w1g8_Game(players=[_w1g8_PlayerState(name="P0"), _w1g8_PlayerState(name="P1")])
    _w1g8_stock_libraries(game)
    game.enforce_mana_costs = True
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    game.players[0].hand.append(bok["Tendo Ice Bridge"])
    assert game.cast_from_hand(0, "Tendo Ice Bridge").supported
    (bridge,) = game.controlled_by(0)
    assert counters_on(bridge, "charge") == 1
    coloured = game.activate_permanent_ability(
        0, "Tendo Ice Bridge", ability_index=1, mana_color="U",
    )
    assert coloured.supported, coloured.details
    assert game.players[0].mana_pool["U"] == 1 and counters_on(bridge, "charge") == 0
    bridge.tapped = False
    assert not game.activate_permanent_ability(
        0, "Tendo Ice Bridge", ability_index=1, mana_color="R",
    ).supported
    assert game.players[0].mana_pool["R"] == 0
    assert game.tap_land_for_mana(0, "Tendo Ice Bridge", "C", permanent_id=bridge.permanent_id)
    assert game.players[0].mana_pool["C"] == 1

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

# ==== end w1g9 ======================================================


# ==== w1g10 ==========================================================
# w1g10's tests go between this line and the "end w1g10" line.

# ==== end w1g10 ======================================================
