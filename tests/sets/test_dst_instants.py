"""Darksteel instants.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("DST")` / `set_cards("DST")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

from engine import Game as _W1G5Game
from engine import PlayerState as _W1G5PlayerState
from engine.models import Permanent as _W1G5Permanent
from engine.oracle import compile_card_oracle as _w1g5_compile
from engine.targeting import derive_cast_spec as _w1g5_derive_cast_spec
from tests.helpers import settle as _w1g5_settle


def _w1g5_burden_table(set_pool, mine=(), theirs=()):
    lea = set_pool("LEA")
    game = _W1G5Game(players=[
        _W1G5PlayerState(name="Alice", hand=[set_pool("DST")["Burden of Greed"]],
                         library=[lea["Plains"]] * 10),
        _W1G5PlayerState(name="Bob", library=[lea["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    placed = {0: [], 1: []}
    for seat, cards in ((0, mine), (1, theirs)):
        for card in cards:
            permanent = _W1G5Permanent(card=card)
            game._put_permanent_onto_battlefield(seat, permanent, None)
            placed[seat].append(permanent)
    game._sync_control()
    game.start_turn(0)
    _w1g5_settle(game)
    return game, placed[0], placed[1]


def test_w1g5_burden_of_greed_counts_the_targets_tapped_artifacts(set_pool):
    """"Target player loses 1 life for each tapped artifact they control."
    "They" is the target, and "tapped" is a narrowing the count enforces: of
    Bob's three artifacts two are tapped, so he loses 2; Alice's own tapped
    artifact and Bob's untapped one count for nothing. The picker offers a
    player."""
    lea = set_pool("LEA")
    card = set_pool("DST")["Burden of Greed"]
    assert _w1g5_derive_cast_spec(card, _w1g5_compile(card)) == {"kind": "player"}
    game, mine, theirs = _w1g5_burden_table(
        set_pool,
        mine=[lea["Sol Ring"]],
        theirs=[lea["Sol Ring"], lea["Mox Pearl"], lea["Mox Jet"], lea["Grizzly Bears"]],
    )
    mine[0].tapped = True
    theirs[0].tapped = theirs[1].tapped = theirs[3].tapped = True
    game.cast_from_hand(0, "Burden of Greed", target_player_index=1)
    _w1g5_settle(game)
    assert (game.players[0].life, game.players[1].life) == (20, 18)
    assert "Burden of Greed: Bob lost 2 life (20 -> 18)" in game.log


def test_w1g5_burden_of_greed_aimed_at_its_caster_counts_the_casters_board(set_pool):
    """Aimed at its own caster the count follows the target: Alice's two
    tapped artifacts, not Bob's three."""
    lea = set_pool("LEA")
    game, mine, theirs = _w1g5_burden_table(
        set_pool,
        mine=[lea["Sol Ring"], lea["Mox Pearl"]],
        theirs=[lea["Sol Ring"], lea["Mox Pearl"], lea["Mox Jet"]],
    )
    for permanent in mine + theirs:
        permanent.tapped = True
    game.cast_from_hand(0, "Burden of Greed", target_player_index=0)
    _w1g5_settle(game)
    assert (game.players[0].life, game.players[1].life) == (18, 20)

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
