"""Champions of Kamigawa instants.

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
# The drive list's instants: Call to Glory and Hold the Line.

from engine import Game as _W1G2Game, PlayerState as _W1G2PlayerState
from engine.models import Permanent as _W1G2Permanent
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


def test_w1g2_call_to_glory_untaps_its_side_and_pumps_its_samurai(set_pool):
    """"Untap all creatures you control. Samurai creatures you control get
    +1/+1 until end of turn." The opponent's tapped Samurai stays tapped and
    unpumped; the Bears untaps and stays a 2/2."""
    chk = set_pool("CHK")
    game = _w1g2_table(set_pool, hands=([chk["Call to Glory"]], ()))
    retainer = _w1g2_put(game, chk["Devoted Retainer"], 0)
    bears = _w1g2_put(game, set_pool("LEA")["Grizzly Bears"], 0)
    theirs = _w1g2_put(game, chk["Nezumi Ronin"], 1)
    for permanent in (retainer, bears, theirs):
        permanent.tapped = True
    assert game.cast_from_hand(0, "Call to Glory").supported
    _w1g2_settle(game)
    assert not retainer.tapped and not bears.tapped and theirs.tapped
    assert (retainer.effective_power, retainer.effective_toughness) == (2, 2)
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)
    assert (theirs.effective_power, theirs.effective_toughness) == (3, 1)


def test_w1g2_hold_the_line_pumps_only_the_blockers(set_pool):
    """"Blocking creatures get +7/+7 until end of turn." Cast in the declare
    blockers step: the blocking Devoted Retainer (already +1/+1 from bushido)
    is a 9/9, the attackers are untouched."""
    chk = set_pool("CHK")
    game = _w1g2_table(set_pool, hands=((), [chk["Hold the Line"]]))
    giant = _w1g2_put(game, set_pool("LEA")["Hill Giant"], 0)
    bears = _w1g2_put(game, set_pool("LEA")["Grizzly Bears"], 0)
    retainer = _w1g2_put(game, chk["Devoted Retainer"], 1)
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(
        0, [game.battlefield_index_of(giant), game.battlefield_index_of(bears)],
        defending_player_index=1,
    )[0]
    _w1g2_settle(game)
    game.advance_combat_phase()
    assert game.declare_blockers(
        1, {game.battlefield_index_of(retainer): game.battlefield_index_of(giant)}
    )[0]
    _w1g2_settle(game)
    game.priority_player_index = 1
    assert game.cast_from_hand(1, "Hold the Line").supported
    _w1g2_settle(game)
    assert (retainer.effective_power, retainer.effective_toughness) == (9, 9)
    assert (giant.effective_power, giant.effective_toughness) == (3, 3)
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)

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
