"""Darksteel creatures (legendary ones too).

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
from tests.helpers import declare_attack as _w1g5_declare_attack
from tests.helpers import drive_combat as _w1g5_drive_combat
from tests.helpers import settle as _w1g5_settle


def _w1g5_table(set_pool, mine=(), theirs=()):
    """A two-seat game on seat 0's first main phase, *mine* and *theirs* on
    the battlefield (none summoning sick), settled."""
    lea = set_pool("LEA")
    game = _W1G5Game(players=[
        _W1G5PlayerState(name="Alice", library=[lea["Plains"]] * 10),
        _W1G5PlayerState(name="Bob", library=[lea["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    placed = {0: [], 1: []}
    for seat, cards in ((0, mine), (1, theirs)):
        for card in cards:
            permanent = _W1G5Permanent(card=card)
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    game._sync_control()
    game.start_turn(0)
    _w1g5_settle(game)
    return game, placed[0], placed[1]


def test_w1g5_emissary_of_hope_gains_a_life_per_artifact_the_damaged_player_controls(set_pool):
    """"Whenever this creature deals combat damage to a player, you gain 1
    life for each artifact that player controls." "That player" is the seat
    the damage hit (CR 603.10, frozen by the damage seam), so the count is the
    defender's board: three artifacts there — an artifact creature among them
    — and the attacker's own Sol Ring and the defender's Grizzly Bears count
    for nothing."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game, _mine, _theirs = _w1g5_table(
        set_pool,
        mine=[dst["Emissary of Hope"], lea["Sol Ring"]],
        theirs=[lea["Sol Ring"], lea["Mox Pearl"], set_pool("ATQ")["Ornithopter"],
                lea["Grizzly Bears"]],
    )
    _w1g5_declare_attack(game, 0)
    _w1g5_drive_combat(game)
    assert game.players[1].life == 18
    assert game.players[0].life == 23
    assert "Alice gained 3 life from Emissary of Hope (20 -> 23)" in game.log


def test_w1g5_emissary_of_hope_counts_as_its_trigger_resolves(set_pool):
    """The count is taken as the ability resolves (CR 608.2), not as it
    triggers: an artifact sacrificed with the trigger waiting on the stack is
    not counted. And a blocked Emissary deals no damage to a player, so
    nothing triggers at all."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game, _mine, theirs = _w1g5_table(
        set_pool,
        mine=[dst["Emissary of Hope"]],
        theirs=[lea["Sol Ring"], lea["Mox Pearl"]],
    )
    _w1g5_declare_attack(game, 0)
    game.advance_combat_phase(allow_damage_skip=False)
    assert game.players[1].life == 18
    assert any(item.card.name == "Emissary of Hope" for item in game.stack)
    game.sacrifice_permanent(theirs[1])
    _w1g5_settle(game)
    assert game.players[0].life == 21

    game, _mine, _theirs = _w1g5_table(
        set_pool,
        mine=[dst["Emissary of Hope"]],
        theirs=[lea["Sol Ring"], set_pool("ATQ")["Ornithopter"]],
    )
    _w1g5_declare_attack(game, 0, blocks={1: 0})
    _w1g5_drive_combat(game)
    assert game.players[0].life == 20
    assert not any("from Emissary of Hope" in line for line in game.log)


def test_w1g5_emissary_of_despair_drains_a_life_per_artifact_the_damaged_player_controls(set_pool):
    """"…that player loses 1 life for each artifact they control." "They" is
    the clause's own subject — the damaged player — so the loss is counted on
    the loser's board: two artifacts, 2 combat damage and 2 more life lost.
    The attacker's own artifact does not count."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game, _mine, _theirs = _w1g5_table(
        set_pool,
        mine=[dst["Emissary of Despair"], lea["Sol Ring"], lea["Mox Pearl"]],
        theirs=[lea["Sol Ring"], set_pool("ATQ")["Ornithopter"], lea["Grizzly Bears"]],
    )
    _w1g5_declare_attack(game, 0)
    _w1g5_drive_combat(game)
    assert game.players[1].life == 16
    assert game.players[0].life == 20
    assert "Emissary of Despair: Bob lost 2 life (18 -> 16)" in game.log

    # Nothing to count is nothing lost beyond the damage.
    game, _mine, _theirs = _w1g5_table(
        set_pool, mine=[dst["Emissary of Despair"], lea["Sol Ring"]],
    )
    _w1g5_declare_attack(game, 0)
    _w1g5_drive_combat(game)
    assert game.players[1].life == 18

# ==== end W1G5 ======================================================
