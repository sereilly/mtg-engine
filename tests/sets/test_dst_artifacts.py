"""Darksteel artifacts.

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
#
# Equipment: the granted "{T}, Unattach ~:" abilities, Whispersilk Cloak's
# reversed compound, Shield of Kaldra's named indestructible, and the drive
# list (the Swords, Skullclamp, Specter's Shroud, Nemesis Mask). Every test
# equips through the real equip ability (CR 702.6a) and reads the board after
# `settle`.

from engine import Game as _W1G2Game, PlayerState as _W1G2PlayerState
from engine.equipment import equipped_creature as _w1g2_equipped
from engine.models import Permanent as _W1G2Permanent
from tests.helpers import declare_attack as _w1g2_declare_attack
from tests.helpers import drive_combat as _w1g2_drive_combat
from tests.helpers import settle as _w1g2_settle


def _w1g2_table(set_pool, *, interactive=(), enforce=False, life=20):
    """Two seats on seat 0's first main phase, libraries to draw from."""
    island = set_pool("LEA")["Island"]
    game = _W1G2Game(players=[
        _W1G2PlayerState(name=f"P{seat}", life=life, library=[island] * 20)
        for seat in range(2)
    ])
    game.enforce_mana_costs = enforce
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    return game


def _w1g2_put(game, card, seat, *, sick=False):
    """*card* onto *seat*'s battlefield through the entry seam."""
    permanent = _W1G2Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    if not sick:
        permanent.metadata["summoning_sickness_turn"] = -99
    _w1g2_settle(game)
    return permanent


def _w1g2_equip(game, seat, equipment, creature):
    """Activate *equipment*'s equip ability at *creature* and resolve it."""
    result = game.activate_permanent_ability(
        seat,
        equipment.card.name,
        permanent_index=game.battlefield_index_of(equipment),
        target_permanent_ids=[creature.permanent_id],
    )
    assert result.supported, (result, game.log[-4:])
    _w1g2_settle(game)
    assert _w1g2_equipped(equipment) is creature, game.log[-4:]
    return result


def test_w1g2_whispersilk_cloak_unblockable_and_shroud(set_pool):
    """"Equipped creature can't be blocked and has shroud." Both halves of the
    one line: no blocker may be declared (CR 509.1b), and no spell may target
    the creature — its controller's included (CR 702.18a). Moved off, the
    creature is blockable and targetable again."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g2_table(set_pool)
    cloak = _w1g2_put(game, dst["Whispersilk Cloak"], 0)
    bears = _w1g2_put(game, lea["Grizzly Bears"], 0)
    wall = _w1g2_put(game, lea["Wall of Stone"], 1)
    _w1g2_equip(game, 0, cloak, bears)
    assert bears.has_keyword("shroud")

    game.players[0].hand = [lea["Lightning Bolt"]]
    refused = game.cast_from_hand(0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id])
    assert not refused.supported
    assert bears in game.controlled_by(0)

    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(0, [game.battlefield_index_of(bears)], defending_player_index=1)
    assert ok, why
    game.advance_combat_phase()
    ok, _why = game.declare_blockers(1, {game.battlefield_index_of(wall): 0})
    assert not ok
    ok, why = game.declare_blockers(1, {})
    assert ok, why
    _w1g2_drive_combat(game)
    assert game.players[1].life == 18

    # Off the creature, both halves end (CR 611.3b).
    game._set_phase_and_step("postcombat_main", "main")
    ogre = _w1g2_put(game, lea["Gray Ogre"], 0)
    _w1g2_equip(game, 0, cloak, ogre)
    assert not bears.has_keyword("shroud")
    result = game.cast_from_hand(0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id])
    assert result.supported, result
    _w1g2_settle(game)
    assert bears not in game.controlled_by(0)


def test_w1g2_shield_of_kaldra_makes_the_named_equipment_indestructible(set_pool):
    """"Equipment named Sword of Kaldra, Shield of Kaldra, and Helm of Kaldra
    have indestructible." Every name on the list, whoever controls it (the
    sentence names no controller), and nothing off it; and "Equipped creature
    has indestructible" on the creature it equips."""
    dst, mrd, lea = set_pool("DST"), set_pool("MRD"), set_pool("LEA")
    game = _w1g2_table(set_pool)
    shield = _w1g2_put(game, dst["Shield of Kaldra"], 0)
    sword = _w1g2_put(game, mrd["Sword of Kaldra"], 1)
    scimitar = _w1g2_put(game, mrd["Leonin Scimitar"], 1)
    bears = _w1g2_put(game, lea["Grizzly Bears"], 0)
    assert shield.has_keyword("indestructible")
    assert sword.has_keyword("indestructible")
    assert not scimitar.has_keyword("indestructible")
    assert not bears.has_keyword("indestructible")

    game.players[0].hand = [lea["Shatter"], lea["Shatter"], lea["Shatter"]]
    for victim in (sword, shield, scimitar):
        result = game.cast_from_hand(0, "Shatter", target_permanent_ids=[victim.permanent_id])
        assert result.supported, result
        _w1g2_settle(game)
    assert sword in game.controlled_by(1)
    assert shield in game.controlled_by(0)
    assert scimitar not in game.controlled_by(1)

    _w1g2_equip(game, 0, shield, bears)
    assert bears.has_keyword("indestructible")
    game.players[0].hand = [lea["Terror"]]
    result = game.cast_from_hand(0, "Terror", target_permanent_ids=[bears.permanent_id])
    assert result.supported, result
    _w1g2_settle(game)
    assert bears in game.controlled_by(0)

    # The Shield leaving takes the Sword's indestructible with it (CR 611.3b).
    game.remove_from_battlefield(shield)
    _w1g2_settle(game)
    assert not sword.has_keyword("indestructible")

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
