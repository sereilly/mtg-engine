"""Champions of Kamigawa sorceries.

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


# Drive list: Champions of Kamigawa sorceries supported on arrival, given a game.

from engine import Game as _W1G1Game
from engine import PlayerState as _W1G1PlayerState
from tests.helpers import settle as _w1g1_settle


def test_w1g1_time_of_need_finds_a_legendary_creature_card(set_pool):
    """Time of Need: Search your library for a legendary creature card, reveal
    it, put it into your hand, then shuffle. It finds Isamaru, Hound of Konda;
    it does not find Akki Lavarunner, whose bottom half is legendary and whose
    card is not (CR 710.2), nor a Grizzly Bears."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _W1G1Game(players=[
        _W1G1PlayerState(
            name="P0", hand=[chk["Time of Need"], chk["Time of Need"]],
            library=[lea["Grizzly Bears"], chk["Akki Lavarunner"],
                     chk["Isamaru, Hound of Konda"]],
        ),
        _W1G1PlayerState(name="P1", library=[lea["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    _w1g1_settle(game)
    assert game.cast_from_hand(0, "Time of Need").supported
    _w1g1_settle(game)
    assert "Isamaru, Hound of Konda" in [card.name for card in game.players[0].hand]
    assert sorted(card.name for card in game.players[0].library) == [
        "Akki Lavarunner", "Grizzly Bears",
    ]
    assert game.cast_from_hand(0, "Time of Need").supported
    _w1g1_settle(game)
    assert sorted(card.name for card in game.players[0].library) == [
        "Akki Lavarunner", "Grizzly Bears",
    ]

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

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

# ==== end w1g9 ======================================================
