"""Champions of Kamigawa enchantments, Auras included.

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
#
# The drive list's Auras: Indomitable Will (flash), Vigilance,
# Uncontrollable Anger.

from engine import Game as _W1G2Game, PlayerState as _W1G2PlayerState
from engine.models import Permanent as _W1G2Permanent
from tests.helpers import drive_combat as _w1g2_drive_combat
from tests.helpers import settle as _w1g2_settle


def _w1g2_table(set_pool, *, hands=((), ())):
    forest = set_pool("LEA")["Forest"]
    game = _W1G2Game(players=[
        _W1G2PlayerState(name=f"P{seat}", library=[forest] * 20, hand=list(hands[seat]))
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game


def _w1g2_put(game, card, seat):
    permanent = _W1G2Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    _w1g2_settle(game)
    return permanent


def test_w1g2_indomitable_will_flashes_in_to_save_a_blocker(set_pool):
    """Flash: cast in the declare blockers step on the Bears blocking a Hill
    Giant, it is a 3/4 that survives the 3 damage."""
    game = _w1g2_table(set_pool, hands=((), [set_pool("CHK")["Indomitable Will"]]))
    giant = _w1g2_put(game, set_pool("LEA")["Hill Giant"], 0)
    bears = _w1g2_put(game, set_pool("LEA")["Grizzly Bears"], 1)
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [game.battlefield_index_of(giant)], defending_player_index=1)[0]
    _w1g2_settle(game)
    game.advance_combat_phase()
    assert game.declare_blockers(
        1, {game.battlefield_index_of(bears): game.battlefield_index_of(giant)}
    )[0]
    game.priority_player_index = 1
    assert game.cast_from_hand(
        1, "Indomitable Will", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g2_settle(game)
    assert (bears.effective_power, bears.effective_toughness) == (3, 4)
    _w1g2_drive_combat(game)
    assert game.is_on_battlefield(bears)


def test_w1g2_vigilance_and_uncontrollable_anger_on_a_bear(set_pool):
    """Vigilance gives the enchanted creature vigilance; Uncontrollable Anger
    makes it a +2/+2 that must attack — a declaration without it is refused."""
    chk = set_pool("CHK")
    game = _w1g2_table(set_pool, hands=([chk["Vigilance"], chk["Uncontrollable Anger"]], ()))
    bears = _w1g2_put(game, set_pool("LEA")["Grizzly Bears"], 0)
    for aura in ("Vigilance", "Uncontrollable Anger"):
        assert game.cast_from_hand(0, aura, target_permanent_ids=[bears.permanent_id]).supported
        _w1g2_settle(game)
    assert bears.has_keyword("vigilance")
    assert (bears.effective_power, bears.effective_toughness) == (4, 4)
    game._set_phase_and_step("combat", "declare_attackers")
    assert not game.declare_attackers(0, [], defending_player_index=1)[0]
    assert game.declare_attackers(0, [game.battlefield_index_of(bears)], defending_player_index=1)[0]
    assert not bears.tapped

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
