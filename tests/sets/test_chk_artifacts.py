"""Champions of Kamigawa artifacts.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("CHK")` / `set_cards("CHK")` — never a new
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

from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState
from engine.named_counters import counters_on as _w1g6_counters_on
from tests.helpers import settle as _w1g6_settle


def _w1g6_table(set_pool, *, hand=()):
    lea = set_pool("LEA")
    game = _W1G6Game(players=[
        _W1G6PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * 20,
            hand=list(hand) if seat == 0 else [],
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    _w1g6_settle(game)
    return game


def test_w1g6_orochi_hatchery_makes_a_snake_for_each_charge_counter(set_pool):
    """Cast for X=3, it enters with three charge counters; "{5}, {T}: Create a
    1/1 green Snake creature token for each charge counter on this artifact"
    makes three green 1/1 Snakes and taps it. The count is read as it
    resolves: a Hatchery with no counters makes nothing."""
    chk = set_pool("CHK")
    game = _w1g6_table(set_pool, hand=[chk["Orochi Hatchery"]])
    assert game.cast_from_hand(0, "Orochi Hatchery", x_value=3).supported
    _w1g6_settle(game)
    hatchery = next(p for p in game.controlled_by(0) if p.card.name == "Orochi Hatchery")
    assert _w1g6_counters_on(hatchery, "charge") == 3

    assert game.activate_permanent_ability(0, "Orochi Hatchery").supported
    _w1g6_settle(game)
    snakes = [p for p in game.controlled_by(0) if p.card.name != "Orochi Hatchery"]
    assert len(snakes) == 3 and hatchery.tapped
    for snake in snakes:
        assert snake.has_type("Snake") and snake.is_creature
        assert (snake.effective_power, snake.effective_toughness) == (1, 1)
        assert sorted(game._effective_colors(snake)) == ["G"]

    game = _w1g6_table(set_pool, hand=[chk["Orochi Hatchery"]])
    assert game.cast_from_hand(0, "Orochi Hatchery", x_value=0).supported
    _w1g6_settle(game)
    assert game.activate_permanent_ability(0, "Orochi Hatchery").supported
    _w1g6_settle(game)
    assert [p.card.name for p in game.controlled_by(0)] == ["Orochi Hatchery"]

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
