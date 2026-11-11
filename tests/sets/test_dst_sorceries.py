"""Darksteel sorceries.

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
#
# Scrounge: the opponent's pick out of their own graveyard, read by the
# sentence behind it.
from engine import Game as _W1G9Game
from engine.models import PlayerState as _W1G9PlayerState
from engine.oracle import compile_card_oracle as _w1g9_compile
from engine.targeting import derive_cast_spec as _w1g9_derive_cast_spec

from tests.helpers import settle as _w1g9_settle


def _w1g9_table(set_pool, *, hand=(), opponent_graveyard=()):
    lea = set_pool("LEA")
    alice = _W1G9PlayerState(name="Alice", hand=list(hand), library=[lea["Swamp"]] * 8)
    bob = _W1G9PlayerState(
        name="Bob", library=[lea["Plains"]] * 8, graveyard=list(opponent_graveyard),
    )
    game = _W1G9Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game, alice, bob


def test_w1g9_scrounge_puts_the_opponents_pick_onto_your_battlefield(set_pool):
    """"Target opponent chooses an artifact card in their graveyard. Put that
    card onto the battlefield under your control." The picker offers an
    opponent; a headless opponent gives up the cheaper artifact (its own pile,
    least valuable first), never the Bears; the card enters under Alice's
    control and stays Bob's (CR 108.3), so when it dies it goes to Bob's
    graveyard."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    scrounge = dst["Scrounge"]
    assert _w1g9_derive_cast_spec(scrounge, _w1g9_compile(scrounge)) == {
        "kind": "player", "opponents_only": True,
    }
    game, alice, bob = _w1g9_table(
        set_pool, hand=[scrounge],
        opponent_graveyard=[lea["Juggernaut"], lea["Grizzly Bears"], lea["Sol Ring"]],
    )
    assert not game.cast_from_hand(0, "Scrounge", target_player_index=0).supported
    result = game.cast_from_hand(0, "Scrounge", target_player_index=1)
    assert result.supported, result.details
    _w1g9_settle(game)
    assert [p.card.name for p in alice.battlefield] == ["Sol Ring"]
    assert [card.name for card in bob.graveyard] == ["Juggernaut", "Grizzly Bears"]
    ring = alice.battlefield[0]
    assert game.owner_index_of(ring) == 1
    assert any("Bob chose Sol Ring in Bob's graveyard" in line for line in game.log)


def test_w1g9_scrounge_asks_an_interactive_opponent_and_waits(set_pool):
    """The pick is the opponent's prompt: the spell stays on the stack until it
    is answered, only the artifact cards are offered, and the card named is
    the one that moves; the owner gets it back when it dies."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game, alice, bob = _w1g9_table(
        set_pool, hand=[dst["Scrounge"], dst["Purge"]],
        opponent_graveyard=[lea["Juggernaut"], lea["Grizzly Bears"], lea["Sol Ring"]],
    )
    game.interactive_seats = {1}
    assert game.cast_from_hand(0, "Scrounge", target_player_index=1).supported
    owed = _w1g9_settle(game, defaults=False)
    assert owed is not None and owed.kind == "graveyard_exile_pick", owed
    assert owed.player_index == 1 and owed.data["destination"] == "chosen"
    assert game.live_graveyard_exile_candidates(owed) == [0, 2]
    assert game.stack, "Scrounge waits on the pick (CR 608.2)"
    assert not game.confirm_graveyard_exile_pick(1, [1]), "the Bears are no artifact"
    assert game.confirm_graveyard_exile_pick(1, [0])
    _w1g9_settle(game)
    assert [p.card.name for p in alice.battlefield] == ["Juggernaut"]
    juggernaut = alice.battlefield[0]
    assert game.cast_from_hand(
        0, "Purge", target_permanent_ids=[juggernaut.permanent_id],
    ).supported
    _w1g9_settle(game)
    assert lea["Juggernaut"] in bob.graveyard and lea["Juggernaut"] not in alice.graveyard


def test_w1g9_scrounge_finds_no_artifact_and_does_nothing(set_pool):
    """A pile with no artifact card asks nobody and moves nothing."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game, alice, bob = _w1g9_table(
        set_pool, hand=[dst["Scrounge"]], opponent_graveyard=[lea["Grizzly Bears"]],
    )
    game.interactive_seats = {1}
    assert game.cast_from_hand(0, "Scrounge", target_player_index=1).supported
    assert _w1g9_settle(game, defaults=False) is None
    assert alice.battlefield == [] and [c.name for c in bob.graveyard] == ["Grizzly Bears"]

# ==== end W1G9 ======================================================
