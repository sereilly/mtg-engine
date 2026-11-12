"""Fifth Dawn sorceries.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("5DN")` / `set_cards("5DN")` — never a new
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
from engine import Game as _W1G2Game, PlayerState as _W1G2PlayerState
from engine.models import Permanent as _W1G2Permanent
from tests.helpers import settle as _w1g2_settle


def test_w1g2_channel_the_suns_pays_a_bringers_wubrg(set_pool):
    """"Add {W}{U}{B}{R}{G}." Four Forests cast Channel the Suns, and the five
    mana it makes is exactly the alternative cost a Bringer prints — one cast
    payment for each, the Bringer's through the ordinary pool."""
    lea, fdn = set_pool("LEA"), set_pool("5DN")
    game = _W1G2Game(players=[
        _W1G2PlayerState(
            name="Alice", library=[lea["Island"]] * 8,
            hand=[fdn["Channel the Suns"], fdn["Bringer of the Green Dawn"]],
        ),
        _W1G2PlayerState(name="Bob", library=[lea["Island"]] * 8),
    ])
    game.enforce_mana_costs = True
    for _ in range(4):
        forest = _W1G2Permanent(card=lea["Forest"])
        game._put_permanent_onto_battlefield(0, forest, None)
    game.start_turn(0)
    _w1g2_settle(game)
    for permanent in list(game.controlled_by(0)):
        assert game.tap_land_for_mana_or_refusal(
            0, "Forest", permanent_id=permanent.permanent_id,
        ) is None

    assert game.cast_from_hand(0, "Channel the Suns").supported
    assert {k: v for k, v in game.players[0].mana_pool.items() if v} == {
        "W": 1, "U": 1, "B": 1, "R": 1, "G": 1,
    }
    result = game.cast_from_hand(0, "Bringer of the Green Dawn", alternative_cost=True)

    assert result.supported, result.details
    _w1g2_settle(game)
    assert "Bringer of the Green Dawn" in [p.card.name for p in game.controlled_by(0)]
    assert not any(game.players[0].mana_pool.values())

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
