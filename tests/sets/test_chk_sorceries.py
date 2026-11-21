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
#
# Devouring Greed's variable sacrifice, and sorcery hosts for splice onto
# Arcane (CR 702.47, ``engine/splice.py``): an X spell and an "up to three"
# spell carry gained text as well as an instant does.

from engine import Game as _w1g5_Game, PlayerState as _w1g5_PlayerState
from engine.models import Permanent as _w1g5_Permanent
from tests.helpers import settle as _w1g5_settle

_W1G5_SETS = ("CHK", "LEA")


def _w1g5_card(set_pool, name):
    for code in _W1G5_SETS:
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g5_table(set_pool, *, hand=(), mine=(), theirs=()):
    """A two-seat game on seat 0's first main phase, costs off, settled."""
    island = _w1g5_card(set_pool, "Island")
    game = _w1g5_Game(players=[
        _w1g5_PlayerState("A", hand=[_w1g5_card(set_pool, n) for n in hand],
                          library=[island] * 10),
        _w1g5_PlayerState("B", library=[island] * 10),
    ])
    game.enforce_mana_costs = False
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _w1g5_Permanent(card=_w1g5_card(set_pool, name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    game._sync_control()
    game.start_turn(0)
    _w1g5_settle(game)
    return game, placed[0], placed[1]


def test_w1g5_devouring_greed_drains_two_plus_two_per_spirit_sacrificed(set_pool):
    """'Target player loses 2 life plus 2 life for each Spirit sacrificed
    this way. You gain that much life.'"""
    for sacrificed, drained in ((2, 6), (0, 2)):
        game, spirits, _theirs = _w1g5_table(
            set_pool, hand=["Devouring Greed"], mine=["Kami of Ancient Law", "Lantern Kami"],
        )
        result = game.cast_from_hand(
            0, "Devouring Greed", target_player_index=1,
            cost_permanent_ids=[s.permanent_id for s in spirits[:sacrificed]],
            optional_cost_payments={"sacrifice any number of spirits": 1},
        )
        assert result.supported, result.details
        _w1g5_settle(game)
        assert game.players[1].life == 20 - drained, sacrificed
        assert game.players[0].life == 20 + drained, sacrificed
        assert len(game.players[0].battlefield) == 2 - sacrificed


def test_w1g5_splice_onto_an_x_sorcery_keeps_the_hosts_x(set_pool):
    """Swallowing Plague at X=2 with Glacial Ray spliced: the host's own X
    for its own text, the gained text's 2 for the gained target."""
    game, _mine, (giant, bears) = _w1g5_table(
        set_pool, hand=["Swallowing Plague", "Glacial Ray"], theirs=["Hill Giant", "Grizzly Bears"],
    )
    result = game.cast_from_hand(
        0, "Swallowing Plague", target_permanent_ids=[giant.permanent_id], x_value=2,
        splice_cards=[{"hand_index": 1, "target_permanent_ids": [bears.permanent_id]}],
    )
    assert result.supported, result.details
    _w1g5_settle(game)
    assert giant.damage_marked == 2 and game.players[0].life == 22
    assert not game.is_on_battlefield(bears)


def test_w1g5_splice_onto_an_up_to_three_sorcery(set_pool):
    """Terashi's Cry taps up to three creatures; Kodama's Might spliced onto it
    pumps a creature of its own, its own target."""
    game, (bears,), theirs = _w1g5_table(
        set_pool, hand=["Terashi's Cry", "Kodama's Might"], mine=["Grizzly Bears"],
        theirs=["Hill Giant", "Llanowar Elves"],
    )
    result = game.cast_from_hand(
        0, "Terashi's Cry", target_permanent_ids=[p.permanent_id for p in theirs],
        splice_cards=[{"hand_index": 1, "target_permanent_ids": [bears.permanent_id]}],
    )
    assert result.supported, result.details
    _w1g5_settle(game)
    assert all(p.tapped for p in theirs)
    assert bears.effective_power == 4 and not bears.tapped

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
