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


# Drive list: Champions of Kamigawa artifacts supported on arrival, given a game.

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


def test_w1g1_honor_worn_shaku_untaps_by_tapping_a_legend(set_pool):
    """Honor-Worn Shaku: {T}: Add {C}. Tap an untapped legendary permanent you
    control: Untap this artifact. Tapping Isamaru untaps it; a Grizzly Bears
    cannot pay; and a flipped Tomoya the Revealer — legendary only once
    flipped (CR 710.2) — can, where the unflipped Jushi Apprentice could not."""
    from engine.flip_cards import flip_permanent

    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    shaku = _w1g1_put(game, chk["Honor-Worn Shaku"])
    bears = _w1g1_put(game, lea["Grizzly Bears"])
    jushi = _w1g1_put(game, chk["Jushi Apprentice"])

    def untap(by):
        return game.activate_permanent_ability(
            0, "Honor-Worn Shaku", permanent_index=game.battlefield_index_of(shaku),
            ability_index=1, cost_permanent_ids=[by.permanent_id],
        )

    shaku.tapped = True
    assert not untap(bears).supported
    assert not untap(jushi).supported
    assert shaku.tapped and not bears.tapped and not jushi.tapped
    flip_permanent(game, jushi)
    assert untap(jushi).supported
    _w1g1_settle(game)
    assert jushi.tapped and not shaku.tapped
    isamaru = _w1g1_put(game, chk["Isamaru, Hound of Konda"])
    shaku.tapped = True
    assert untap(isamaru).supported
    _w1g1_settle(game)
    assert isamaru.tapped and not shaku.tapped

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
