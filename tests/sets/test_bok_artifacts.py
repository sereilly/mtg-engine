"""Betrayers of Kamigawa artifacts.

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

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

from engine import Game as _W1G7Game
from engine import PlayerState as _W1G7PlayerState
from engine.models import Permanent as _W1G7Permanent
from tests.helpers import settle as _w1g7_settle


def _w1g7_table(set_pool, *, hand=(), opponent_hand=(), interactive=(), library=20):
    """Two seats on seat 0's first main phase, costs not enforced."""
    lea = set_pool("LEA")
    game = _W1G7Game(players=[
        _W1G7PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * library,
            hand=list(hand) if seat == 0 else list(opponent_hand),
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    _w1g7_settle(game)
    return game


def _w1g7_put(game, card, seat=0):
    permanent = _W1G7Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g7_named(game, name):
    return [perm for perm in game.all_permanents() if perm.card.name == name]


def test_w1g7_orb_of_dreams_taps_every_entering_permanent_but_itself(set_pool):
    """Permanents enter tapped. CR 614.12: the replacement comes from the Orb
    only for what is already on the battlefield — its example is Orb of
    Dreams entering untapped. Then a played land, a creature spell, the
    tokens a spell creates and an opponent's creature all enter tapped, and so
    does a second Orb (the first one's effect reaches it)."""
    bok, lea, chk = set_pool("BOK"), set_pool("LEA"), set_pool("CHK")
    game = _w1g7_table(
        set_pool,
        hand=[bok["Orb of Dreams"], lea["Forest"], lea["Grizzly Bears"], bok["Orb of Dreams"]],
    )
    assert game.cast_from_hand(0, "Orb of Dreams").supported
    _w1g7_settle(game)
    (orb,) = _w1g7_named(game, "Orb of Dreams")
    assert not orb.tapped
    assert game.cast_from_hand(0, "Forest").supported
    assert game.cast_from_hand(0, "Grizzly Bears").supported
    _w1g7_settle(game)
    assert _w1g7_named(game, "Forest")[0].tapped
    assert _w1g7_named(game, "Grizzly Bears")[0].tapped
    # A token is a permanent too, and so is the opponent's creature.
    _w1g7_put(game, chk["Kami of the Hunt"], seat=1)
    assert _w1g7_named(game, "Kami of the Hunt")[0].tapped
    assert game.cast_from_hand(0, "Orb of Dreams").supported
    _w1g7_settle(game)
    assert sorted(perm.tapped for perm in _w1g7_named(game, "Orb of Dreams")) == [False, True]


def test_w1g7_orb_of_dreams_taps_tokens(set_pool):
    """A token a spell creates enters tapped under the Orb (every road onto
    the battlefield passes the one entry seam)."""
    bok, mrd = set_pool("BOK"), set_pool("MRD")
    game = _w1g7_table(set_pool, hand=[mrd["Raise the Alarm"]])
    _w1g7_put(game, bok["Orb of Dreams"])
    assert game.cast_from_hand(0, "Raise the Alarm").supported
    _w1g7_settle(game)
    soldiers = _w1g7_named(game, "Soldier Token")
    assert len(soldiers) == 2 and all(perm.tapped for perm in soldiers)

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
