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
#
# Mana Geyser's count of the opponents' tapped lands; Vicious Betrayal's
# sacrifice as a cast cost; Rude Awakening's lands become creatures.

from engine import Game as _W1G7Game, PlayerState as _W1G7PlayerState
from engine.models import Permanent as _W1G7Permanent
from tests.helpers import settle as _w1g7_settle


def _w1g7_table(set_pool, *, hand=(), mine=(), theirs=(), interactive=()):
    lea = set_pool("LEA")
    game = _W1G7Game(players=[
        _W1G7PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * 20,
            hand=list(hand) if seat == 0 else [],
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    _w1g7_settle(game)
    placed = {0: [], 1: []}
    for seat, cards in ((0, mine), (1, theirs)):
        for card in cards:
            permanent = _W1G7Permanent(card=card)
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    _w1g7_settle(game)
    return game, placed[0], placed[1]


def _w1g7_pool(player):
    return {symbol: n for symbol, n in player.mana_pool.items() if n}


def test_w1g7_mana_geyser_counts_only_the_opponents_tapped_lands(set_pool):
    """"Add {R} for each tapped land your opponents control." Three of the
    opponent's four lands are tapped and so is one of the caster's own: three
    {R}, the caster's tapped Mountain and the opponent's untapped Plains
    counted for nothing."""
    lea = set_pool("LEA")
    game, mine, theirs = _w1g7_table(
        set_pool, hand=[set_pool("5DN")["Mana Geyser"]],
        mine=[lea["Mountain"], lea["Mountain"]],
        theirs=[lea["Forest"], lea["Forest"], lea["Island"], lea["Plains"]],
    )
    mine[0].tapped = True
    for land in theirs[:3]:
        land.tapped = True

    result = game.cast_from_hand(0, "Mana Geyser")
    assert result.supported, result
    _w1g7_settle(game)

    assert _w1g7_pool(game.players[0]) == {"R": 3}
    assert _w1g7_pool(game.players[1]) == {}
    assert "Mana Geyser produced {R}{R}{R}" in game.log


def test_w1g7_mana_geyser_with_no_tapped_opposing_land_adds_nothing(set_pool):
    lea = set_pool("LEA")
    game, mine, _ = _w1g7_table(
        set_pool, hand=[set_pool("5DN")["Mana Geyser"]],
        mine=[lea["Mountain"]], theirs=[lea["Forest"]],
    )
    mine[0].tapped = True

    game.cast_from_hand(0, "Mana Geyser")
    _w1g7_settle(game)

    assert _w1g7_pool(game.players[0]) == {}

# ==== end w1g7 ======================================================
