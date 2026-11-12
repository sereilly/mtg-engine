"""Fifth Dawn instants.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("5DN")` / `set_cards("5DN")` — never a new
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

from engine import Game as _W1G3Game, PlayerState as _W1G3PlayerState
from engine.models import Permanent as _W1G3Permanent
from tests.helpers import settle as _w1g3_settle


def _w1g3_table(set_pool, *, hand=(), opponent_hand=(), graveyard=()):
    """Two seats on seat 0's first main phase with ten-card libraries."""
    lea = set_pool("LEA")
    game = _W1G3Game(players=[
        _W1G3PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * 10,
            hand=list(hand if seat == 0 else opponent_hand),
            graveyard=list(graveyard) if seat == 0 else [],
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    _w1g3_settle(game)
    return game


def _w1g3_put(game, seat, card):
    permanent = _W1G3Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    _w1g3_settle(game)
    return permanent


def _w1g3_where(game, name):
    return [
        f"{seat}.{zone}"
        for seat, player in enumerate(game.players)
        for zone in ("hand", "library", "graveyard", "exile")
        for card in getattr(player, zone)
        if card.name == name
    ]


def test_w1g3_beacon_of_destruction_kills_and_shuffles_itself_away(set_pool):
    """"Beacon of Destruction deals 5 damage to any target. Shuffle Beacon of
    Destruction into its owner's library." The creature dies; the Beacon ends
    in its owner's library — one card longer — and never in the graveyard
    (CR 608.2n's last step is the library's, not the graveyard's)."""
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g3_table(set_pool, hand=[fdn["Beacon of Destruction"]])
    giant = _w1g3_put(game, 1, lea["Hill Giant"])
    assert game.cast_from_hand(
        0, "Beacon of Destruction", target_permanent_ids=[giant.permanent_id],
    ).supported
    _w1g3_settle(game)

    assert not game.is_on_battlefield(giant)
    assert _w1g3_where(game, "Beacon of Destruction") == ["0.library"]
    assert len(game.players[0].library) == 11
    assert (
        "Beacon of Destruction resolved and was shuffled into its owner's library"
        in game.log
    )


def test_w1g3_beacon_of_destruction_leaves_a_copy_in_the_graveyard_alone(set_pool):
    """Two Beacons are one ``CardDefinition``: with one already in its owner's
    graveyard, the resolving one is shuffled in and the graveyard's stays
    where it is. At a player, five damage."""
    fdn = set_pool("5DN")
    game = _w1g3_table(
        set_pool, hand=[fdn["Beacon of Destruction"]],
        graveyard=[fdn["Beacon of Destruction"]],
    )
    assert game.cast_from_hand(0, "Beacon of Destruction", target_player_index=1).supported
    _w1g3_settle(game)
    assert game.players[1].life == 15
    assert sorted(_w1g3_where(game, "Beacon of Destruction")) == ["0.graveyard", "0.library"]


def test_w1g3_beacon_of_destruction_countered_goes_to_the_graveyard(set_pool):
    """Ruling (2007-07-15): "If a Beacon is countered or doesn't resolve, it's
    put into its owner's graveyard, not shuffled into the library." """
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g3_table(
        set_pool, hand=[fdn["Beacon of Destruction"]], opponent_hand=[lea["Counterspell"]],
    )
    assert game.queue_from_hand(0, "Beacon of Destruction", target_player_index=1).supported
    assert game.queue_from_hand(1, "Counterspell", target_stack_index=0).supported
    _w1g3_settle(game)
    assert game.players[1].life == 20
    assert _w1g3_where(game, "Beacon of Destruction") == ["0.graveyard"]
    assert len(game.players[0].library) == 10


def test_w1g3_beacon_of_destruction_whose_target_left_is_not_shuffled(set_pool):
    """The same ruling's "doesn't resolve": its one target Bolted in response,
    the Beacon is removed from the stack (CR 608.2b) into its owner's
    graveyard — the shuffle sentence never runs."""
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g3_table(
        set_pool, hand=[fdn["Beacon of Destruction"]], opponent_hand=[lea["Lightning Bolt"]],
    )
    bears = _w1g3_put(game, 1, lea["Grizzly Bears"])
    assert game.queue_from_hand(
        0, "Beacon of Destruction", target_permanent_ids=[bears.permanent_id],
    ).supported
    assert game.queue_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g3_settle(game)
    assert _w1g3_where(game, "Beacon of Destruction") == ["0.graveyard"]
    assert len(game.players[0].library) == 10


def test_w1g3_beacon_of_destruction_shuffle_is_announced(set_pool):
    """The shuffle is an effect's shuffle (CR 701.24a), heard by "Whenever a
    spell or ability causes a player to shuffle their library, this artifact
    deals 2 damage to that player." (Psychogenic Probe): the Beacon's owner
    takes 2 — and the opponent, whose library nothing shuffled, does not."""
    fdn = set_pool("5DN")
    game = _w1g3_table(set_pool, hand=[fdn["Beacon of Destruction"]])
    _w1g3_put(game, 1, set_pool("MRD")["Psychogenic Probe"])
    assert game.cast_from_hand(0, "Beacon of Destruction", target_player_index=1).supported
    _w1g3_settle(game)
    assert game.players[0].life == 18, game.log[-6:]
    assert game.players[1].life == 15

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
