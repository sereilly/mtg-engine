"""Torment sorceries.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and eight branches editing eight disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("TOR")` / `set_cards("TOR")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
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
from engine import Game as _w1g7_Game, PlayerState as _w1g7_PlayerState
from engine.models import Permanent as _w1g7_Permanent
from tests.helpers import _nosick as _w1g7_nosick, resolve_stack as _w1g7_resolve_stack


def _w1g7_flash_board(set_pool, *, from_graveyard=False):
    tor, lea = set_pool("TOR"), set_pool("LEA")
    flash = tor["Flash of Defiance"]
    ogre = _w1g7_nosick(_w1g7_Permanent(card=lea["Gray Ogre"]))
    seat0 = _w1g7_PlayerState(
        name="P0", battlefield=[ogre],
        hand=[] if from_graveyard else [flash],
        graveyard=[flash] if from_graveyard else [],
    )
    seat1 = _w1g7_PlayerState(name="P1", battlefield=[
        _w1g7_Permanent(card=lea[name])
        for name in ("Grizzly Bears", "Savannah Lions", "Scathe Zombies")
    ])
    game = _w1g7_Game(players=[seat0, seat1])
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "main")
    return game, flash, ogre


def _w1g7_attack_with(game, ogre):
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok, why
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"


def test_w1g7_flash_of_defiance_stops_green_and_white_blockers_only(set_pool):
    """"Green creatures and white creatures can't block this turn." The noun
    phrase is a union of two colours (CR 105.2): the Bears and the Lions may not
    block, the black Zombies still may."""
    game, _, ogre = _w1g7_flash_board(set_pool)
    game.enforce_mana_costs = False
    assert game.cast_from_hand(0, "Flash of Defiance").supported
    _w1g7_resolve_stack(game)
    _w1g7_attack_with(game, ogre)

    bears, lions, zombies = game.players[1].battlefield
    ok, why = game.declare_blockers(1, {0: 0})
    assert not ok and "Grizzly Bears" in why
    ok, why = game.declare_blockers(1, {1: 0})
    assert not ok and "Savannah Lions" in why
    ok, why = game.declare_blockers(1, {2: 0})
    assert ok, why
    assert game._can_block_attacker(zombies, ogre)


def test_w1g7_flash_of_defiance_flashback_pays_mana_and_three_life(set_pool):
    """"Flashback—{1}{R}, Pay 3 life." Cast from the graveyard for exactly
    that, it restricts the same blockers and is exiled."""
    game, flash, ogre = _w1g7_flash_board(set_pool, from_graveyard=True)
    game.enforce_mana_costs = True
    game.players[0].mana_pool["R"] = 2
    assert game.cast_from_hand(0, "Flash of Defiance", from_zone="graveyard").supported
    _w1g7_resolve_stack(game)

    assert game.players[0].life == 17
    assert not any(game.players[0].mana_pool.values())
    assert game.players[0].exile == [flash] and flash not in game.players[0].graveyard
    _w1g7_attack_with(game, ogre)
    ok, _ = game.declare_blockers(1, {0: 0})
    assert not ok
    ok, why = game.declare_blockers(1, {2: 0})
    assert ok, why


def test_w1g7_flash_of_defiance_ends_with_the_turn(set_pool):
    """"This turn": the cleanup sweep drops the entry, and the next turn the
    Bears block again."""
    game, _, ogre = _w1g7_flash_board(set_pool)
    game.enforce_mana_costs = False
    game.cast_from_hand(0, "Flash of Defiance")
    _w1g7_resolve_stack(game)
    bears = game.players[1].battlefield[0]
    assert not game._can_block_attacker(bears, ogre)
    game.resolve_cleanup_step(0)
    assert game.blocking_restrictions_until_eot == []
    assert game._can_block_attacker(bears, ogre)

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================
