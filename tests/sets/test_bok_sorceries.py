"""Betrayers of Kamigawa sorceries.

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
#
# Stir the Grave: a graveyard target bounded by the announced X.
from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState
from tests.helpers import settle as _w1g6_settle


def _w1g6_table(set_pool, *, hand=(), graveyard=()):
    lea = set_pool("LEA")
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="Alice", hand=list(hand), graveyard=list(graveyard),
                         library=[lea["Island"]] * 10),
        _W1G6PlayerState(name="Bob", library=[lea["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    _w1g6_settle(game)
    return game


def test_w1g6_stir_the_grave_returns_a_creature_card_up_to_x(set_pool):
    """"Return target creature card with mana value X or less from your
    graveyard to the battlefield." X is announced before the target
    (CR 601.2b): X=2 cannot name Hill Giant (mana value 4) and the cast is
    refused before anything is paid; it returns Grizzly Bears. Cast again at
    X=4, it returns the Giant."""
    lea = set_pool("LEA")
    stir = set_pool("BOK")["Stir the Grave"]
    game = _w1g6_table(
        set_pool, hand=[stir, stir], graveyard=[lea["Grizzly Bears"], lea["Hill Giant"]],
    )
    assert not game.cast_from_hand(
        0, "Stir the Grave", x_value=2, target_graveyard_indices=[1],
    ).supported
    assert len(game.players[0].hand) == 2
    assert game.cast_from_hand(
        0, "Stir the Grave", x_value=2, target_graveyard_indices=[0],
    ).supported
    _w1g6_settle(game)
    assert [p.card.name for p in game.controlled_by(0)] == ["Grizzly Bears"]
    assert game.cast_from_hand(
        0, "Stir the Grave", x_value=4,
        target_graveyard_indices=[
            [card.name for card in game.players[0].graveyard].index("Hill Giant")
        ],
    ).supported
    _w1g6_settle(game)
    assert sorted(p.card.name for p in game.controlled_by(0)) == [
        "Grizzly Bears", "Hill Giant",
    ]


def test_w1g6_stir_the_grave_at_x_zero_has_no_target(set_pool):
    """No creature card in the graveyard has mana value 0, so X=0 has no legal
    target (CR 601.2c) and the cast is refused."""
    lea = set_pool("LEA")
    game = _w1g6_table(
        set_pool, hand=[set_pool("BOK")["Stir the Grave"]],
        graveyard=[lea["Grizzly Bears"]],
    )
    assert not game.cast_from_hand(
        0, "Stir the Grave", x_value=0, target_graveyard_indices=[0],
    ).supported
    assert not game.players[0].battlefield

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


# ==== w1g10 ==========================================================
# w1g10's tests go between this line and the "end w1g10" line.

# ==== end w1g10 ======================================================
