"""Champions of Kamigawa lands.

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


# Drive list: Champions of Kamigawa lands supported on arrival, given a game.

from engine import Game as _W1G1Game
from engine import PlayerState as _W1G1PlayerState
from engine.models import Permanent as _W1G1Permanent
from tests.helpers import settle as _w1g1_settle


def _w1g1_table(set_pool):
    lea = set_pool("LEA")
    game = _W1G1Game(players=[
        _W1G1PlayerState(name=f"P{seat}", library=[lea["Island"]] * 20)
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    _w1g1_settle(game)
    return game


def _w1g1_put(game, card, seat=0):
    permanent = _W1G1Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def test_w1g1_minamo_untaps_a_legendary_permanent_only(set_pool):
    """Minamo, School at Water's Edge: {U}, {T}: Untap target legendary
    permanent. A tapped Isamaru untaps; a tapped Grizzly Bears is no legal
    target; and Minamo still taps for {U}."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    minamo = _w1g1_put(game, chk["Minamo, School at Water's Edge"])
    isamaru = _w1g1_put(game, chk["Isamaru, Hound of Konda"])
    bears = _w1g1_put(game, lea["Grizzly Bears"])
    isamaru.tapped = bears.tapped = True
    refused = game.activate_permanent_ability(
        0, minamo.card.name, ability_index=1,
        target_permanent_ids=[bears.permanent_id],
    )
    assert not refused.supported and bears.tapped and not minamo.tapped
    assert game.activate_permanent_ability(
        0, minamo.card.name, ability_index=1,
        target_permanent_ids=[isamaru.permanent_id],
    ).supported
    _w1g1_settle(game)
    assert not isamaru.tapped and minamo.tapped
    minamo.tapped = False
    assert game.activate_permanent_ability(0, minamo.card.name, ability_index=0).supported
    _w1g1_settle(game)
    assert minamo.tapped and game.players[0].mana_pool.get("U", 0) == 1

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
