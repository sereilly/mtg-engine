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

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.

# ==== end w1g4 ======================================================


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

# ==== end w1g5 ======================================================


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

from engine import Game as _W1G6Game
from engine import PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from tests.helpers import drive_combat as _w1g6_drive_combat
from tests.helpers import settle as _w1g6_settle


def _w1g6_put(game, seat, card):
    permanent = _W1G6Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    _w1g6_settle(game)
    return permanent


def test_w1g6_retaliate_destroys_the_creatures_that_damaged_its_caster(set_pool):
    """'Destroy all creatures that dealt damage to you this turn.' The turn's
    damage ledger, asked about the caster: the unblocked Grizzly Bears (combat
    damage) and the Prodigal Sorcerer (a ping) go; the Hill Giant, blocked by
    a Wall, dealt its damage to the Wall and stays; the Llanowar Elves dealt
    none. A creature that dealt damage, left and came back is a new object
    (CR 400.7) that dealt nothing — the Bears' twin bounced and replayed —
    and stays too."""
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    plains = lea["Plains"]
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="P0", library=[plains] * 20),
        _W1G6PlayerState(name="P1", hand=[fdn["Retaliate"]], library=[plains] * 20),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    _w1g6_settle(game)
    bears = _w1g6_put(game, 0, lea["Grizzly Bears"])
    twin = _w1g6_put(game, 0, lea["Grizzly Bears"])
    giant = _w1g6_put(game, 0, lea["Hill Giant"])
    sorcerer = _w1g6_put(game, 0, lea["Prodigal Sorcerer"])
    elves = _w1g6_put(game, 0, lea["Llanowar Elves"])
    wall = _w1g6_put(game, 1, lea["Wall of Stone"])

    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    attackers = [game.battlefield_index_of(p) for p in (bears, twin, giant)]
    ok, why = game.declare_attackers(0, attackers, defending_player_index=1)
    assert ok, why
    game.advance_combat_phase()
    ok, why = game.declare_blockers(1, {game.battlefield_index_of(wall): game.battlefield_index_of(giant)})
    assert ok, why
    _w1g6_drive_combat(game)
    assert game.players[1].life == 16
    game._set_phase_and_step("postcombat_main", "postcombat_main")
    result = game.activate_permanent_ability(
        0, "Prodigal Sorcerer", permanent_index=game.battlefield_index_of(sorcerer),
        target_player_index=1,
    )
    assert result.supported, result
    _w1g6_settle(game)
    assert game.players[1].life == 15

    # The twin leaves and comes back: a new object, with no damage behind it.
    game.remove_from_battlefield(twin)
    returned = _w1g6_put(game, 0, lea["Grizzly Bears"])

    result = game.cast_from_hand(1, "Retaliate")
    assert result.supported, result
    _w1g6_settle(game)
    assert not game.is_on_battlefield(bears)
    assert not game.is_on_battlefield(sorcerer)
    for survivor in (giant, elves, returned, wall):
        assert game.is_on_battlefield(survivor), survivor.card.name

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

# ==== end w1g7 ======================================================
