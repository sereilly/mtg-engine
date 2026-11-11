"""Darksteel artifacts — the later groups' sections.

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
# The one-offs that are artifacts: Auriok Siege Sled's requirement on an
# "artifact creature", and the rest below as they land.
from engine import Game as _W1G9Game
from engine import ai_declarations as _w1g9_ai_declarations
from engine.models import Permanent as _W1G9Permanent
from engine.models import PlayerState as _W1G9PlayerState
from engine.oracle import compile_card_oracle as _w1g9_compile

from tests.helpers import drive_combat as _w1g9_drive_combat
from tests.helpers import settle as _w1g9_settle


def _w1g9_table(set_pool, *, hand=(), library=None, opponent_library=None):
    lea = set_pool("LEA")
    alice = _W1G9PlayerState(
        name="Alice", hand=list(hand),
        library=list(library) if library is not None else [lea["Plains"]] * 8,
    )
    bob = _W1G9PlayerState(
        name="Bob",
        library=list(opponent_library) if opponent_library is not None else [lea["Swamp"]] * 8,
    )
    game = _W1G9Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game, alice, bob


def _w1g9_put(game, seat, card, *, sick=False):
    permanent = _W1G9Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    if not sick:
        permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g9_slot(game, seat, permanent):
    return game.players[seat].battlefield.index(permanent)


def _w1g9_attack_with(game, seat, attackers):
    game.active_player_index = seat
    game._set_phase_and_step("combat", "declare_attackers")
    slots = [_w1g9_slot(game, seat, each) for each in attackers]
    ok, why = game.declare_attackers(seat, slots, defending_player_index=1 - seat)
    assert ok, why


def test_w1g9_auriok_siege_sled_compels_the_artifact_creature_it_names(set_pool):
    """"{1}: Target artifact creature blocks this creature this turn if able."
    CR 509.1c: with the requirement on Obsianus Golem, a declaration in which
    the Golem does not block the Sled obeys fewer requirements than it could,
    and is illegal — no block, and the Bears blocking alone, both refused."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    sled = dst["Auriok Siege Sled"]
    assert _w1g9_compile(sled).supported
    game, alice, bob = _w1g9_table(set_pool)
    attacker = _w1g9_put(game, 0, sled)
    golem = _w1g9_put(game, 1, lea["Obsianus Golem"])
    bears = _w1g9_put(game, 1, lea["Grizzly Bears"])
    _w1g9_attack_with(game, 0, [attacker])

    refused = game.activate_permanent_ability(
        0, "Auriok Siege Sled", ability_index=0, target_permanent_ids=[bears.permanent_id],
    )
    assert not refused.supported, "Grizzly Bears is not an artifact creature"
    result = game.activate_permanent_ability(
        0, "Auriok Siege Sled", ability_index=0, target_permanent_ids=[golem.permanent_id],
    )
    assert result.supported, result.details
    _w1g9_settle(game)
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"
    sled_slot = _w1g9_slot(game, 0, attacker)
    ai_blocks = _w1g9_ai_declarations.choose_combat_blockers(game, 1)
    assert ai_blocks.get(_w1g9_slot(game, 1, golem)) == sled_slot, ai_blocks
    assert game.declare_blockers(1, {})[0] is False
    assert game.declare_blockers(1, {_w1g9_slot(game, 1, bears): sled_slot})[0] is False
    ok, why = game.declare_blockers(1, {_w1g9_slot(game, 1, golem): sled_slot})
    assert ok, why
    _w1g9_drive_combat(game)
    assert bob.life == 20
    assert game.is_on_battlefield(golem) and game.is_on_battlefield(attacker)


def test_w1g9_auriok_siege_sled_denies_the_artifact_creature_a_block(set_pool):
    """"{1}: Target artifact creature can't block this creature this turn."
    The Golem may not block the Sled; the Sled's damage reaches Bob."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game, alice, bob = _w1g9_table(set_pool)
    attacker = _w1g9_put(game, 0, dst["Auriok Siege Sled"])
    golem = _w1g9_put(game, 1, lea["Obsianus Golem"])
    _w1g9_attack_with(game, 0, [attacker])
    result = game.activate_permanent_ability(
        0, "Auriok Siege Sled", ability_index=1, target_permanent_ids=[golem.permanent_id],
    )
    assert result.supported, result.details
    _w1g9_settle(game)
    game.advance_combat_phase()
    sled_slot = _w1g9_slot(game, 0, attacker)
    assert game.declare_blockers(1, {_w1g9_slot(game, 1, golem): sled_slot})[0] is False
    assert game.declare_blockers(1, {})[0]
    _w1g9_drive_combat(game)
    assert bob.life == 17

# ==== end W1G9 ======================================================
