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
#
# The drive list: Arcane sorceries supported on arrival, each given a game.

from engine import Game as _w1g3_Game
from engine import PlayerState as _w1g3_PlayerState
from engine.models import Permanent as _w1g3_Permanent
from tests.helpers import settle as _w1g3_settle

#: Where each card the section names is looked up, in order.
_W1G3_SETS = ("BOK", "CHK", "LEA")


def _w1g3_card(set_pool, name):
    for code in _W1G3_SETS:
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g3_table(set_pool, *, hand=(), mine=(), theirs=(), opponent_hand=()):
    cards = lambda names: [_w1g3_card(set_pool, n) for n in names]  # noqa: E731
    island = _w1g3_card(set_pool, "Island")
    game = _w1g3_Game(players=[
        _w1g3_PlayerState("A", hand=cards(hand), library=[island] * 10),
        _w1g3_PlayerState("B", hand=cards(opponent_hand), library=[island] * 10),
    ])
    game.enforce_mana_costs = False
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _w1g3_Permanent(card=_w1g3_card(set_pool, name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    game._sync_control()
    game.start_turn(0)
    _w1g3_settle(game)
    return game, placed[0], placed[1]


def test_w1g3_terashis_grasp_destroys_and_gains_the_mana_value(set_pool):
    game, _mine, (icy,) = _w1g3_table(
        set_pool, hand=["Terashi's Grasp"], theirs=["Icy Manipulator"],
    )
    assert game.cast_from_hand(
        0, "Terashi's Grasp", target_permanent_ids=[icy.permanent_id],
    ).supported
    _w1g3_settle(game)
    assert not game.is_on_battlefield(icy) and game.players[0].life == 24


def test_w1g3_three_tragedies_makes_its_target_discard_three(set_pool):
    game, _mine, _theirs = _w1g3_table(
        set_pool, hand=["Three Tragedies"],
        opponent_hand=["Island", "Mountain", "Forest", "Swamp"],
    )
    assert game.cast_from_hand(0, "Three Tragedies", target_player_index=1).supported
    _w1g3_settle(game)
    assert len(game.players[1].hand) == 1 and len(game.players[1].graveyard) == 3


def test_w1g3_uproot_puts_the_land_on_top_of_its_owners_library(set_pool):
    game, _mine, (mountain,) = _w1g3_table(set_pool, hand=["Uproot"], theirs=["Mountain"])
    assert game.cast_from_hand(
        0, "Uproot", target_permanent_ids=[mountain.permanent_id],
    ).supported
    _w1g3_settle(game)
    assert not game.is_on_battlefield(mountain)
    assert game.players[1].library[0].name == "Mountain"


def test_w1g3_crack_the_earth_has_each_player_sacrifice_a_permanent(set_pool):
    game, (_bears, mountain), (_giant, forest) = _w1g3_table(
        set_pool, hand=["Crack the Earth"],
        mine=["Grizzly Bears", "Mountain"], theirs=["Hill Giant", "Forest"],
    )
    assert game.cast_from_hand(0, "Crack the Earth").supported
    _w1g3_settle(game)
    assert len(list(game.controlled_by(0))) == 1 and len(list(game.controlled_by(1))) == 1
    assert not game.is_on_battlefield(mountain) and not game.is_on_battlefield(forest)


def test_w1g3_ribbons_of_the_reikai_draws_a_card_for_each_spirit(set_pool):
    game, _mine, _theirs = _w1g3_table(
        set_pool, hand=["Ribbons of the Reikai"],
        mine=["Kami of Ancient Law", "Kami of Ancient Law", "Grizzly Bears"],
    )
    assert game.cast_from_hand(0, "Ribbons of the Reikai").supported
    _w1g3_settle(game)
    assert len(game.players[0].hand) == 2

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


# ==== w1g10 ==========================================================
# w1g10's tests go between this line and the "end w1g10" line.

# ==== end w1g10 ======================================================
