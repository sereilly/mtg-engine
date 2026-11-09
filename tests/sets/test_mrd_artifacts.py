"""Mirrodin artifacts.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("MRD")` / `set_cards("MRD")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.
#
# Equipment's own lines: counted pumps, Vorrac Battlehorns' blocker ceiling,
# "Equip—Pay 3 life", and the "Whenever equipped creature …" triggers. Every
# test equips through the real equip ability (CR 702.6a) and fights through
# the real combat steps.

import pytest as _w1g1_pytest

from engine import Game as _W1G1Game, PlayerState as _W1G1PlayerState
from engine.equipment import (attach_equipment as _w1g1_attach,
                              equipped_creature as _w1g1_equipped)
from engine.models import Permanent as _W1G1Permanent
from engine.named_counters import counters_on as _w1g1_counters_on
from engine.targeting import derive_activation_spec as _w1g1_activation_spec
from tests.helpers import declare_attack as _w1g1_declare_attack
from tests.helpers import resolve_stack as _w1g1_resolve_stack


def _w1g1_table(set_pool, *, interactive=(), enforce=False, life=20):
    """Two seats on seat 0's first main phase, libraries to draw from."""
    island = set_pool("LEA")["Island"]
    game = _W1G1Game(players=[
        _W1G1PlayerState(name=f"P{seat}", life=life, library=[island] * 20)
        for seat in range(2)
    ])
    game.enforce_mana_costs = enforce
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    return game


def _w1g1_put(game, card, seat, *, sick=False):
    """*card* onto *seat*'s battlefield through the entry seam."""
    permanent = _W1G1Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    if not sick:
        permanent.metadata["summoning_sickness_turn"] = -99
    game._settle()
    return permanent


def _w1g1_equip(game, seat, equipment, creature):
    """Activate *equipment*'s equip ability at *creature* and resolve it."""
    result = game.activate_permanent_ability(
        seat,
        equipment.card.name,
        permanent_index=game.battlefield_index_of(equipment),
        target_permanent_ids=[creature.permanent_id],
    )
    assert result.supported, (result, game.log[-4:])
    _w1g1_resolve_stack(game)
    game._settle()
    return result


def _w1g1_pt(permanent):
    return permanent.effective_power, permanent.effective_toughness


def _w1g1_fight(game, steps=1):
    """From the declare-blockers step through *steps* combat-damage steps."""
    for _ in range(steps):
        game.advance_combat_phase()
        _w1g1_resolve_stack(game)
        game._settle()


def test_w1g1_empyrial_plate_counts_its_controllers_hand(set_pool):
    """"Equipped creature gets +1/+1 for each card in your hand." The count is
    the Equipment controller's hand (CR 109.5), read on every recompute, and
    the bonus follows the Plate to a second creature."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    plate = _w1g1_put(game, mrd["Empyrial Plate"], 0)
    bears = _w1g1_put(game, lea["Grizzly Bears"], 0)
    ogre = _w1g1_put(game, lea["Gray Ogre"], 0)
    game.players[0].hand = [lea["Island"]] * 3
    game.players[1].hand = [lea["Island"]] * 6

    _w1g1_equip(game, 0, plate, bears)
    assert _w1g1_equipped(plate) is bears
    assert _w1g1_pt(bears) == (5, 5)

    game.players[0].hand.pop()
    game._settle()
    assert _w1g1_pt(bears) == (4, 4)

    _w1g1_equip(game, 0, plate, ogre)
    assert _w1g1_pt(bears) == (2, 2)
    assert _w1g1_pt(ogre) == (4, 4)


def test_w1g1_golem_skin_gauntlets_counts_equipment_on_its_host(set_pool):
    """"…+1/+0 for each Equipment attached to **it**" — the equipped creature,
    not the Gauntlets. Its 2020-08-07 ruling: it counts itself, so it gives at
    least +1/+0, and another Equipment adds to it beside that Equipment's own
    bonus."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    gauntlets = _w1g1_put(game, mrd["Golem-Skin Gauntlets"], 0)
    scimitar = _w1g1_put(game, mrd["Leonin Scimitar"], 0)
    bears = _w1g1_put(game, lea["Grizzly Bears"], 0)
    ogre = _w1g1_put(game, lea["Gray Ogre"], 0)

    _w1g1_equip(game, 0, gauntlets, bears)
    assert _w1g1_pt(bears) == (3, 2)

    _w1g1_equip(game, 0, scimitar, bears)
    assert _w1g1_pt(bears) == (5, 3)

    # The Scimitar moves away: the Gauntlets count one Equipment again.
    _w1g1_equip(game, 0, scimitar, ogre)
    assert _w1g1_pt(bears) == (3, 2)
    assert _w1g1_pt(ogre) == (3, 3)


def test_w1g1_nightmare_lash_equips_for_three_life_and_counts_swamps(set_pool):
    """"Equip—Pay 3 life." is CR 702.6a's ability with a life cost (CR 119.4),
    no mana spent, and the Lash's bonus counts its controller's Swamps."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = _w1g1_table(set_pool, enforce=True)
    lash = _w1g1_put(game, mrd["Nightmare Lash"], 0)
    bears = _w1g1_put(game, lea["Grizzly Bears"], 0)
    _w1g1_put(game, lea["Swamp"], 0)
    _w1g1_put(game, lea["Swamp"], 0)
    _w1g1_put(game, lea["Swamp"], 1)

    # The picker offers what the printed line says: a creature you control.
    from engine.oracle import compile_card_oracle as _compile

    equip = _compile(lash.card).activated_abilities[0]
    assert equip.cost.pay_life == 3
    assert equip.cost.mana.get("generic", 0) == 0
    assert _w1g1_activation_spec(equip) == {"kind": "creature", "own_only": True}

    _w1g1_equip(game, 0, lash, bears)
    assert game.players[0].life == 17
    assert all(not land.tapped for land in game.controlled_by(0) if land.has_type("land"))
    assert _w1g1_pt(bears) == (4, 4)

    _w1g1_put(game, lea["Swamp"], 0)
    assert _w1g1_pt(bears) == (5, 5)


def test_w1g1_nightmare_lash_cannot_equip_on_less_than_three_life(set_pool):
    """CR 119.4: a player may pay life only if their life total is at least
    the payment — at 2 life the equip ability cannot be activated."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = _w1g1_table(set_pool, enforce=True, life=2)
    lash = _w1g1_put(game, mrd["Nightmare Lash"], 0)
    bears = _w1g1_put(game, lea["Grizzly Bears"], 0)

    result = game.activate_permanent_ability(
        0, lash.card.name,
        permanent_index=game.battlefield_index_of(lash),
        target_permanent_ids=[bears.permanent_id],
    )
    _w1g1_resolve_stack(game)

    assert not result.supported
    assert game.players[0].life == 2
    assert _w1g1_equipped(lash) is None


def test_w1g1_vorrac_battlehorns_grants_trample_and_caps_blockers_at_one(set_pool):
    """"Equipped creature has trample and can't be blocked by more than one
    creature." Two blockers is an illegal declaration (CR 509.1b); one is
    legal, and trample carries the excess to the player."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    horns = _w1g1_put(game, mrd["Vorrac Battlehorns"], 0)
    wurm = _w1g1_put(game, lea["Craw Wurm"], 0)
    _w1g1_put(game, lea["Grizzly Bears"], 1)
    _w1g1_put(game, lea["Grizzly Bears"], 1)
    _w1g1_equip(game, 0, horns, wurm)
    assert wurm.has_keyword("trample")
    assert game._maximum_blockers(wurm) == 1

    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(0, [game.battlefield_index_of(wurm)],
                                     defending_player_index=1)
    assert ok, why
    game.advance_combat_phase()
    slot = game.battlefield_index_of(wurm)
    ok, _why = game.declare_blockers(1, {0: slot, 1: slot})
    assert not ok
    ok, why = game.declare_blockers(1, {0: slot})
    assert ok, why
    _w1g1_fight(game)

    assert game.players[1].life == 16, game.log[-6:]


def test_w1g1_vorrac_battlehorns_moved_away_lifts_the_ceiling(set_pool):
    """The restriction is the Equipment's while attached: once it equips
    another creature the first may be blocked by any number again."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    horns = _w1g1_put(game, mrd["Vorrac Battlehorns"], 0)
    wurm = _w1g1_put(game, lea["Craw Wurm"], 0)
    bears = _w1g1_put(game, lea["Grizzly Bears"], 0)
    _w1g1_equip(game, 0, horns, wurm)
    _w1g1_equip(game, 0, horns, bears)

    assert game._maximum_blockers(wurm) is None
    assert not wurm.has_keyword("trample")
    assert game._maximum_blockers(bears) == 1
    assert bears.has_keyword("trample")

# ==== end W1G1 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================
