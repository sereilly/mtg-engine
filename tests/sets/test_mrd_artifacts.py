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


def test_w1g1_banshees_blade_charges_on_combat_damage_and_keeps_its_counters(set_pool):
    """"Whenever equipped creature deals combat damage, put a charge counter on
    this Equipment." and "+1/+1 for each charge counter on this Equipment."
    Its 2004-12-01 ruling: the counters stay when the Blade moves."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    blade = _w1g1_put(game, mrd["Banshee's Blade"], 0)
    bears = _w1g1_put(game, lea["Grizzly Bears"], 0)
    _w1g1_equip(game, 0, blade, bears)
    assert _w1g1_pt(bears) == (2, 2)

    _w1g1_declare_attack(game, 0)
    _w1g1_fight(game)

    assert game.players[1].life == 18, game.log[-6:]
    assert _w1g1_counters_on(blade, "charge") == 1
    assert _w1g1_pt(bears) == (3, 3)

    # Unattached, it keeps the counter; the next creature gets the bonus.
    ogre = _w1g1_put(game, lea["Gray Ogre"], 0)
    _w1g1_attach(game, blade, ogre)
    game._settle()
    assert _w1g1_counters_on(blade, "charge") == 1
    assert _w1g1_pt(bears) == (2, 2)
    assert _w1g1_pt(ogre) == (3, 3)


def test_w1g1_banshees_blade_unattached_does_not_charge(set_pool):
    """The trigger watches the creature the Blade is attached to: with the
    Blade equipping nothing, an attacker's combat damage is not its event."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    blade = _w1g1_put(game, mrd["Banshee's Blade"], 0)
    _w1g1_put(game, lea["Grizzly Bears"], 0)

    _w1g1_declare_attack(game, 0)
    _w1g1_fight(game)

    assert game.players[1].life == 18
    assert _w1g1_counters_on(blade, "charge") == 0


@_w1g1_pytest.mark.parametrize("interactive", [False, True])
def test_w1g1_mask_of_memory_draws_two_then_discards_one(set_pool, interactive):
    """"Whenever equipped creature deals combat damage to a player, you may draw
    two cards. If you do, discard a card." Driven as a headless seat and as an
    interactive one answering the offer and the discard."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = _w1g1_table(set_pool, interactive=(0,) if interactive else ())
    mask = _w1g1_put(game, mrd["Mask of Memory"], 0)
    bears = _w1g1_put(game, lea["Grizzly Bears"], 0)
    _w1g1_equip(game, 0, mask, bears)
    hand_before = len(game.players[0].hand)
    library_before = len(game.players[0].library)

    _w1g1_declare_attack(game, 0)
    game.advance_combat_phase()
    # The trigger resolves in the damage step and offers the draw (an
    # ``optional_pay`` prompt, CR 608.2d).
    offer = game.pending_choices[0]
    assert offer.kind == "optional_pay", offer
    if interactive:
        assert game.resolve_pending_choice("optional_pay", 0, accept=True)
        # "If you do, discard a card": the discard is the seat's to pick.
        discard = game.pending_choices[0]
        assert discard.kind == "discard", discard
        drawn = game.players[0].hand[-1]
        assert game.resolve_pending_choice(
            "discard", 0, hand_indices=[len(game.players[0].hand) - 1],
            to_library=False,
        )
        assert game.players[0].graveyard[-1] is drawn
    else:
        # A seat nobody sits in takes the default: a free draw-two-discard-one
        # is a gift, and it is taken.
        game.auto_resolve_pending_choices()
    _w1g1_resolve_stack(game)
    game._settle()

    assert game.players[1].life == 18, game.log[-6:]
    assert len(game.players[0].library) == library_before - 2, game.log[-8:]
    assert len(game.players[0].hand) == hand_before + 1, game.log[-8:]
    assert len(game.players[0].graveyard) == 1


def test_w1g1_mask_of_memory_does_not_trigger_on_damage_to_a_creature(set_pool):
    """The trigger names a *player* recipient: a blocked attacker's damage to
    the blocker draws nothing."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    mask = _w1g1_put(game, mrd["Mask of Memory"], 0)
    bears = _w1g1_put(game, lea["Grizzly Bears"], 0)
    _w1g1_put(game, lea["Grizzly Bears"], 1)
    _w1g1_equip(game, 0, mask, bears)
    library_before = len(game.players[0].library)

    _w1g1_declare_attack(game, 0, blocks={0: game.battlefield_index_of(bears)})
    _w1g1_fight(game)

    assert game.players[1].life == 20
    assert len(game.players[0].library) == library_before


def test_w1g1_sword_of_kaldra_does_not_chase_a_creature_that_already_died(set_pool):
    """"Equipped creature gets +5/+5." / "Whenever equipped creature deals
    damage to a creature, exile that creature. (Exile it only if it's still on
    the battlefield.)" The Wurm takes 7, the state-based check puts it in the
    graveyard before the trigger resolves (CR 704.3, 603.3), and the exile
    then finds nothing — the card stays in the graveyard."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    sword = _w1g1_put(game, mrd["Sword of Kaldra"], 0)
    bears = _w1g1_put(game, lea["Grizzly Bears"], 0)
    wurm = _w1g1_put(game, lea["Craw Wurm"], 1)
    _w1g1_equip(game, 0, sword, bears)
    assert _w1g1_pt(bears) == (7, 7)

    _w1g1_declare_attack(game, 0, blocks={
        game.battlefield_index_of(wurm): game.battlefield_index_of(bears),
    })
    _w1g1_fight(game)

    assert [card.name for card in game.players[1].graveyard] == ["Craw Wurm"]
    assert game.players[1].exile == []
    assert game.is_on_battlefield(bears)


def test_w1g1_sword_of_kaldra_exiles_a_survivor(set_pool):
    """A creature the damage does not kill is exiled all the same — the
    trigger, not lethal damage, removes it: a 7/7 into an 0/8 Wall."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    sword = _w1g1_put(game, mrd["Sword of Kaldra"], 0)
    bears = _w1g1_put(game, lea["Grizzly Bears"], 0)
    wall = _w1g1_put(game, lea["Wall of Stone"], 1)
    _w1g1_equip(game, 0, sword, bears)

    _w1g1_declare_attack(game, 0, blocks={
        game.battlefield_index_of(wall): game.battlefield_index_of(bears),
    })
    _w1g1_fight(game)

    assert "Wall of Stone" in [card.name for card in game.players[1].exile], game.log[-8:]
    assert not game.is_on_battlefield(wall)


def test_w1g1_worldslayer_destroys_every_other_permanent(set_pool):
    """"Whenever equipped creature deals combat damage to a player, destroy all
    permanents other than this Equipment." Its 2011-09-22 ruling: "The
    equipped creature is also destroyed." Lands go too."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    slayer = _w1g1_put(game, mrd["Worldslayer"], 0)
    bears = _w1g1_put(game, lea["Grizzly Bears"], 0)
    _w1g1_put(game, lea["Forest"], 0)
    _w1g1_put(game, lea["Island"], 1)
    _w1g1_put(game, lea["Wall of Stone"], 1)
    _w1g1_equip(game, 0, slayer, bears)

    _w1g1_declare_attack(game, 0)
    _w1g1_fight(game)

    assert game.players[1].life == 18
    assert [p.card.name for p in game.controlled_by(0)] == ["Worldslayer"], game.log[-8:]
    assert list(game.controlled_by(1)) == []
    assert _w1g1_equipped(slayer) is None


def _w1g1_sledge_board(set_pool):
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    sledge = _w1g1_put(game, mrd["Dead-Iron Sledge"], 0)
    giant = _w1g1_put(game, lea["Hill Giant"], 0)
    wurm = _w1g1_put(game, lea["Craw Wurm"], 1)
    _w1g1_equip(game, 0, sledge, giant)
    return game, sledge, giant, wurm


def test_w1g1_dead_iron_sledge_destroys_both_when_its_creature_is_blocked(set_pool):
    """"Whenever equipped creature blocks or becomes blocked by a creature,
    destroy both creatures." The becomes-blocked half: the trigger resolves
    in the declare-blockers step, before any damage."""
    game, sledge, giant, wurm = _w1g1_sledge_board(set_pool)

    _w1g1_declare_attack(game, 0, blocks={
        game.battlefield_index_of(wurm): game.battlefield_index_of(giant),
    })
    _w1g1_resolve_stack(game)
    game._settle()

    assert game.current_step == "declare_blockers"
    assert not game.is_on_battlefield(giant), game.log[-6:]
    assert not game.is_on_battlefield(wurm)
    assert game.is_on_battlefield(sledge)
    assert game.players[0].life == 20 and game.players[1].life == 20


def test_w1g1_dead_iron_sledge_destroys_both_when_its_creature_blocks(set_pool):
    """The blocks half: the Sledge on a blocker destroys it and the attacker."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    sledge = _w1g1_put(game, mrd["Dead-Iron Sledge"], 1)
    wall = _w1g1_put(game, lea["Wall of Stone"], 1)
    wurm = _w1g1_put(game, lea["Craw Wurm"], 0)
    # Seat 1's own equip happened on its turn; attach directly here.
    assert _w1g1_attach(game, sledge, wall)
    game._settle()

    _w1g1_declare_attack(game, 0, blocks={
        game.battlefield_index_of(wall): game.battlefield_index_of(wurm),
    })
    _w1g1_resolve_stack(game)
    game._settle()

    assert not game.is_on_battlefield(wurm), game.log[-6:]
    assert not game.is_on_battlefield(wall)


def test_w1g1_dead_iron_sledge_moved_after_triggering_destroys_the_same_pair(set_pool):
    """Its 2006-10-15 ruling: "Moving Dead-Iron Sledge after the ability
    triggers will not affect which creatures are destroyed." The Sledge is
    moved onto a third creature while the trigger waits; the original pair
    dies and the new host lives."""
    game, sledge, giant, wurm = _w1g1_sledge_board(set_pool)
    bears = _w1g1_put(game, set_pool("LEA")["Grizzly Bears"], 0)
    game.interactive_seats = {0, 1}

    _w1g1_declare_attack(game, 0, blocks={
        game.battlefield_index_of(wurm): game.battlefield_index_of(giant),
    })
    assert [item.card.name for item in game.stack] == ["Dead-Iron Sledge"]
    _w1g1_attach(game, sledge, bears)
    assert _w1g1_equipped(sledge) is bears
    _w1g1_resolve_stack(game)
    game._settle()

    assert not game.is_on_battlefield(giant), game.log[-6:]
    assert not game.is_on_battlefield(wurm)
    assert game.is_on_battlefield(bears)


def test_w1g1_dead_iron_sledge_unblocked_does_nothing(set_pool):
    """No block, no trigger: the giant hits the player and everything stays."""
    game, sledge, giant, wurm = _w1g1_sledge_board(set_pool)

    _w1g1_declare_attack(game, 0)
    _w1g1_fight(game)

    assert game.players[1].life == 17
    assert game.is_on_battlefield(giant) and game.is_on_battlefield(wurm)


def test_w1g1_scythe_of_the_wretched_steals_the_creature_its_host_killed(set_pool):
    """"Whenever a creature dealt damage by equipped creature this turn dies,
    return that card to the battlefield under your control. Attach this
    Equipment to that creature." The Wurm-sized host kills a blocker; the
    blocker comes back under the Scythe's controller, wearing the Scythe."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    scythe = _w1g1_put(game, mrd["Scythe of the Wretched"], 0)
    giant = _w1g1_put(game, lea["Hill Giant"], 0)
    bears = _w1g1_put(game, lea["Grizzly Bears"], 1)
    _w1g1_equip(game, 0, scythe, giant)
    assert _w1g1_pt(giant) == (5, 5)

    _w1g1_declare_attack(game, 0, blocks={
        game.battlefield_index_of(bears): game.battlefield_index_of(giant),
    })
    _w1g1_fight(game)

    stolen = [p for p in game.controlled_by(0) if p.card.name == "Grizzly Bears"]
    assert len(stolen) == 1, game.log[-8:]
    assert _w1g1_equipped(scythe) is stolen[0]
    assert _w1g1_pt(stolen[0]) == (4, 4)
    assert _w1g1_pt(giant) == (3, 3)
    assert game.players[1].graveyard == []
    # Control moved, ownership did not (CR 108.3): it is still the
    # opponent's card.
    assert game.owner_index_of(stolen[0]) == 1


def test_w1g1_scythe_of_the_wretched_ignores_a_death_its_host_did_not_damage(set_pool):
    """A creature that dies without having been dealt damage by the equipped
    creature this turn does not trigger the Scythe."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    scythe = _w1g1_put(game, mrd["Scythe of the Wretched"], 0)
    giant = _w1g1_put(game, lea["Hill Giant"], 0)
    bears = _w1g1_put(game, lea["Grizzly Bears"], 1)
    _w1g1_equip(game, 0, scythe, giant)

    game._destroy_swept_permanents(game.players[1], lambda p: p is bears)
    _w1g1_resolve_stack(game)
    game._settle()

    assert [card.name for card in game.players[1].graveyard] == ["Grizzly Bears"]
    assert not game.is_on_battlefield(bears)
    assert _w1g1_equipped(scythe) is giant

def test_w1g1_scythe_destroyed_in_response_still_returns_the_card(set_pool):
    """Once triggered, the ability exists on the stack independently of its
    source (CR 113.7a). The Scythe is destroyed while its trigger waits.

    The dead creature still comes back, onto its seat 0's battlefield, and
    there is nothing left to attach."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = _w1g1_table(set_pool, interactive=(0, 1))
    scythe = _w1g1_put(game, mrd["Scythe of the Wretched"], 0)
    giant = _w1g1_put(game, lea["Hill Giant"], 0)
    bears = _w1g1_put(game, lea["Grizzly Bears"], 1)
    _w1g1_equip(game, 0, scythe, giant)

    # The record combat damage writes (``damaged_by_sources_this_turn``),
    # written here so the death can be caused with the trigger left waiting
    # on the stack rather than resolved inside the damage step.
    bears.metadata["damaged_by_sources_this_turn"] = [giant]
    game._destroy_swept_permanents(game.players[1], lambda p: p is bears)
    assert [item.card.name for item in game.stack] == ["Scythe of the Wretched"], game.log[-6:]
    game._destroy_swept_permanents(game.players[0], lambda p: p is scythe)
    game._settle()
    _w1g1_resolve_stack(game)
    game._settle()

    assert [p.card.name for p in game.controlled_by(0)] == ["Hill Giant", "Grizzly Bears"], game.log[-12:]
    assert [card.name for card in game.players[0].graveyard] == ["Scythe of the Wretched"]


# --- The supported-on-arrival Equipment, driven (W1G1's drive list) -------
#
# (name, P/T delta, keywords granted). Each is equipped through its own equip
# ability, read through the layers, moved to a second creature (the bonus
# follows it, CR 301.5a / 613.7e), and sent into combat.
_W1G1_DRIVEN = (
    ("Bonesplitter", (2, 0), ()),
    ("Fireshrieker", (0, 0), ("double strike",)),
    ("Leonin Scimitar", (1, 1), ()),
    ("Lightning Greaves", (0, 0), ("haste", "shroud")),
    ("Loxodon Warhammer", (3, 0), ("trample", "lifelink")),
    ("Neurok Hoversail", (0, 0), ("flying",)),
    ("Slagwurm Armor", (0, 6), ()),
    ("Vulshok Battlegear", (3, 3), ()),
    ("Vulshok Gauntlets", (4, 2), ()),
)


@_w1g1_pytest.mark.parametrize("name, delta, keywords", _W1G1_DRIVEN)
def test_w1g1_driven_equipment_grants_and_follows(set_pool, name, delta, keywords):
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    gear = _w1g1_put(game, mrd[name], 0)
    bears = _w1g1_put(game, lea["Grizzly Bears"], 0)
    ogre = _w1g1_put(game, lea["Gray Ogre"], 0)

    _w1g1_equip(game, 0, gear, bears)
    assert _w1g1_pt(bears) == (2 + delta[0], 2 + delta[1])
    for keyword in keywords:
        assert bears.has_keyword(keyword), keyword

    _w1g1_equip(game, 0, gear, ogre)
    assert _w1g1_pt(bears) == (2, 2)
    assert _w1g1_pt(ogre) == (2 + delta[0], 2 + delta[1])
    for keyword in keywords:
        assert ogre.has_keyword(keyword) and not bears.has_keyword(keyword)

    # The ogre alone attacks; what reaches the player is its new power,
    # twice for double strike.
    game._destroy_swept_permanents(game.players[0], lambda p: p is bears)
    _w1g1_declare_attack(game, 0)
    hits = 2 if "double strike" in keywords else 1
    _w1g1_fight(game, steps=hits)
    assert game.players[1].life == 20 - hits * (2 + delta[0]), game.log[-6:]
    if "lifelink" in keywords:
        assert game.players[0].life == 20 + 2 + delta[0]


def test_w1g1_vulshok_gauntlets_keeps_its_creature_tapped(set_pool):
    """"...and doesn't untap during its controller's untap step." An attacker
    wearing the Gauntlets stays tapped through its controller's next untap
    step."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    gauntlets = _w1g1_put(game, mrd["Vulshok Gauntlets"], 0)
    bears = _w1g1_put(game, lea["Grizzly Bears"], 0)
    _w1g1_equip(game, 0, gauntlets, bears)
    _w1g1_declare_attack(game, 0)
    _w1g1_fight(game)
    assert bears.tapped

    game.start_turn(1)
    game.start_turn(0)
    assert bears.tapped, game.log[-6:]


def test_w1g1_lightning_greaves_shroud_refuses_a_bolt(set_pool):
    """Shroud on the equipped creature: an opponent's Lightning Bolt cannot
    name it (CR 702.18a)."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    greaves = _w1g1_put(game, mrd["Lightning Greaves"], 0)
    bears = _w1g1_put(game, lea["Grizzly Bears"], 0, sick=True)
    _w1g1_equip(game, 0, greaves, bears)
    assert bears.has_keyword("haste")
    game.players[1].hand.append(lea["Lightning Bolt"])
    cast = game.queue_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id]
    )
    _w1g1_resolve_stack(game)
    assert not cast.supported
    assert game.is_on_battlefield(bears)


def test_w1g1_viridian_longbow_grants_a_ping_activated_from_the_creature(set_pool):
    """'Equipped creature has "{T}: This creature deals 1 damage to any
    target."' The ability is the creature's (CR 301.5d): activated from the
    bears, tapping the bears, and gone once the Longbow moves."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    bow = _w1g1_put(game, mrd["Viridian Longbow"], 0)
    bears = _w1g1_put(game, lea["Grizzly Bears"], 0)
    ogre = _w1g1_put(game, lea["Gray Ogre"], 0)
    _w1g1_equip(game, 0, bow, bears)

    result = game.activate_permanent_ability(
        0, "Grizzly Bears",
        permanent_index=game.battlefield_index_of(bears),
        target_player_index=1,
    )
    assert result.supported, (result, game.log[-4:])
    _w1g1_resolve_stack(game)
    assert bears.tapped
    assert game.players[1].life == 19

    _w1g1_equip(game, 0, bow, ogre)
    bears.tapped = False
    again = game.activate_permanent_ability(
        0, "Grizzly Bears",
        permanent_index=game.battlefield_index_of(bears),
        target_player_index=1,
    )
    _w1g1_resolve_stack(game)
    assert not again.supported
    assert game.players[1].life == 19


def test_w1g1_myr_adapter_counts_the_equipment_on_it(set_pool):
    """'This creature gets +1/+1 for each Equipment attached to it.'"""
    mrd = set_pool("MRD")
    game = _w1g1_table(set_pool)
    adapter = _w1g1_put(game, mrd["Myr Adapter"], 0)
    scimitar = _w1g1_put(game, mrd["Leonin Scimitar"], 0)
    gauntlets = _w1g1_put(game, mrd["Golem-Skin Gauntlets"], 0)
    assert _w1g1_pt(adapter) == (1, 1)
    _w1g1_equip(game, 0, scimitar, adapter)
    assert _w1g1_pt(adapter) == (3, 3)
    # Gauntlets: +1/+0 per Equipment on it (2), the Adapter's own +1/+1 per
    # Equipment (2) and the Scimitar's +1/+1.
    _w1g1_equip(game, 0, gauntlets, adapter)
    assert _w1g1_pt(adapter) == (6, 4)


# ==== end W1G1 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.
from engine import Game as _W1G3Game
from engine import PlayerState as _W1G3PlayerState
from engine.cost_modifiers import cast_mana_charge as _w1g3_charge
from engine.models import Permanent as _W1G3Permanent
from engine.oracle import compile_card_oracle as _w1g3_compile
from tests.helpers import resolve_stack as _w1g3_resolve


def _w1g3_find(set_pool, name):
    """*name* out of Mirrodin, else Alpha (a body or a basic) — pools kept
    separate and asked in that order."""
    for w1g3_code in ("MRD", "LEA"):
        w1g3_pool = set_pool(w1g3_code)
        if name in w1g3_pool:
            return w1g3_pool[name]
    raise KeyError(name)  # _w1g3_find


def _w1g3_table(set_pool, hand=(), mine=(), theirs=(), active=0):
    """A two-seat table with mana costs enforced — affinity changes a price,
    so nothing here is free — and every permanent past summoning sickness."""
    w1g3_game = _W1G3Game(players=[
        _W1G3PlayerState(
            name="W1G3-A", hand=[_w1g3_find(set_pool, n) for n in hand],
            library=[_w1g3_find(set_pool, "Island")] * 8,
        ),
        _W1G3PlayerState(
            name="W1G3-B", library=[_w1g3_find(set_pool, "Island")] * 8,
        ),
    ])
    w1g3_game.enforce_mana_costs = True
    w1g3_game.interactive_seats = set()
    w1g3_game.active_player_index = active
    w1g3_rows = []
    for w1g3_seat, w1g3_names in enumerate((mine, theirs)):
        w1g3_row = []
        for w1g3_name in w1g3_names:
            w1g3_perm = _W1G3Permanent(card=_w1g3_find(set_pool, w1g3_name))
            w1g3_game._put_permanent_onto_battlefield(w1g3_seat, w1g3_perm, None)
            w1g3_perm.metadata["summoning_sickness_turn"] = -99
            w1g3_row.append(w1g3_perm)
        w1g3_rows.append(w1g3_row)
    return w1g3_game, w1g3_rows[0], w1g3_rows[1]  # _w1g3_table


def _w1g3_tap(game, count, seat=0):
    """Tap *count* untapped lands *seat* controls for their first colour,
    through the real mana-ability entry point."""
    w1g3_tapped = 0
    for w1g3_land in list(game.controlled_by(seat)):
        if w1g3_tapped == count:
            break
        if w1g3_land.has_type("land") and not w1g3_land.tapped:
            w1g3_color = (w1g3_land.effective_produced_mana or ("C",))[0]
            assert game.tap_land_for_mana(
                seat, w1g3_land.card.name, w1g3_color,
                permanent_id=w1g3_land.permanent_id,
            ), game.log[-3:]
            w1g3_tapped += 1
    assert w1g3_tapped == count, f"only {w1g3_tapped} lands to tap"  # _w1g3_tap


def _w1g3_pool(game, seat=0):
    return sum(game.players[seat].mana_pool.values())  # _w1g3_pool


def _w1g3_on_board(game, name, seat=0):
    return [p for p in game.controlled_by(seat) if p.card.name == name]  # _w1g3_on_board


def test_w1g3_frogmite_reprices_as_artifacts_enter_and_leave(set_pool):
    """"Affinity for artifacts" (CR 702.41a: "This spell costs {1} less to cast
    for each artifact you control."). Printed {4}. Three artifact lands make it
    {1}, and one of them pays it — a tapped artifact is still an artifact. The
    first Frogmite is an artifact too, so the second costs {0} and is cast from
    an empty pool. Then an artifact land leaves, and the third Frogmite is back
    to {1}: refused with an empty pool, nothing spent, still in hand."""
    assert _w1g3_compile(set_pool("MRD")["Frogmite"]).supported
    frogmite = set_pool("MRD")["Frogmite"]
    game, mine, _theirs = _w1g3_table(
        set_pool, hand=["Frogmite", "Frogmite", "Frogmite"],
        mine=["Seat of the Synod"] * 3,
    )
    assert _w1g3_charge(game, 0, frogmite).get("generic") == 1
    _w1g3_tap(game, 1)
    cast = game.cast_from_hand(0, "Frogmite")
    assert cast.supported, cast.details
    _w1g3_resolve(game)
    assert _w1g3_pool(game) == 0 and len(_w1g3_on_board(game, "Frogmite")) == 1

    assert _w1g3_charge(game, 0, frogmite).get("generic") == 0
    cast = game.cast_from_hand(0, "Frogmite")
    assert cast.supported, cast.details
    _w1g3_resolve(game)
    assert len(_w1g3_on_board(game, "Frogmite")) == 2
    assert "Frogmite costs less to cast (Frogmite)" in game.log

    # Five artifacts; one leaving (CR 701.21a's sacrifice, through the seam)
    # would leave four and Frogmite still free — so two leave.
    game.sacrifice_permanents(mine[:2])
    assert len(_w1g3_on_board(game, "Seat of the Synod")) == 1
    assert _w1g3_charge(game, 0, frogmite).get("generic") == 1
    refused = game.cast_from_hand(0, "Frogmite")
    assert not refused.supported and "insufficient mana" in refused.details
    assert [c.name for c in game.players[0].hand] == ["Frogmite"]
    assert len(_w1g3_on_board(game, "Frogmite")) == 2


def test_w1g3_myr_enforcer_is_cast_for_what_its_artifacts_leave(set_pool):
    """Printed {7}: five artifact lands and a Frogmite are six artifacts, so
    it costs {1}; five lands' worth of artifacts alone would be {2}. An
    opponent's artifacts discount nothing — "you control" is the caster."""
    enforcer = set_pool("MRD")["Myr Enforcer"]
    game, _mine, _theirs = _w1g3_table(
        set_pool, hand=["Myr Enforcer"],
        mine=["Seat of the Synod"] * 5 + ["Frogmite"],
        theirs=["Seat of the Synod"] * 7,
    )
    assert _w1g3_charge(game, 0, enforcer).get("generic") == 1
    assert _w1g3_charge(game, 1, enforcer).get("generic") == 0
    _w1g3_tap(game, 1)
    cast = game.cast_from_hand(0, "Myr Enforcer")
    assert cast.supported, cast.details
    _w1g3_resolve(game)
    enforcer_perm = _w1g3_on_board(game, "Myr Enforcer")[0]
    assert (enforcer_perm.effective_power, enforcer_perm.effective_toughness) == (4, 4)
    assert _w1g3_pool(game) == 0


def test_w1g3_scale_and_tooth_flash_in_cheap_and_pump(set_pool):
    """Flash and affinity on one artifact: on the opponent's turn, with two
    artifact lands, Scale of Chiss-Goria costs {1} and Tooth of Chiss-Goria
    then costs {0} (Scale is the third artifact). Each taps at once — an
    artifact's {T} ability has no summoning sickness (CR 302.6 is about
    creatures) — for +0/+1 and +1/+0 on a creature."""
    game, _mine, theirs = _w1g3_table(
        set_pool, hand=["Scale of Chiss-Goria", "Tooth of Chiss-Goria"],
        mine=["Seat of the Synod"] * 2, theirs=["Grizzly Bears"], active=1,
    )
    bears = theirs[0]
    _w1g3_tap(game, 1)
    cast = game.cast_from_hand(0, "Scale of Chiss-Goria")
    assert cast.supported, cast.details
    _w1g3_resolve(game)
    cast = game.cast_from_hand(0, "Tooth of Chiss-Goria")
    assert cast.supported, cast.details
    _w1g3_resolve(game)
    assert _w1g3_pool(game) == 0
    for w1g3_name in ("Scale of Chiss-Goria", "Tooth of Chiss-Goria"):
        activated = game.activate_permanent_ability(
            0, w1g3_name, target_permanent_ids=[bears.permanent_id],
        )
        assert activated.supported, activated.details
        _w1g3_resolve(game)
    assert (bears.effective_power, bears.effective_toughness) == (3, 3)


def test_w1g3_every_reader_agrees_on_an_affinity_price(set_pool):
    """The price must agree everywhere it is read: the client's castable
    highlight and hand badge (``cast_mana_charge``), the AI's affordability
    read (``ai_payment._cost_for``) and the cast itself. With four artifact
    lands a {4} Frogmite is offered and is free; with none it is not offered
    off three Islands."""
    from fastapi.testclient import TestClient

    from engine.ai_payment import _cost_for
    from web.app import app, store

    client = TestClient(app)
    frogmite = set_pool("MRD")["Frogmite"]

    def offered(lands):
        response = client.post("/api/sessions", json={
            "mode": "human_vs_ai", "host_name": "W1G3", "host_colors": 2,
            "guest_colors": 2, "seed": 4103,
            "host_deck_cards": [{"name": "Island", "count": 40}],
            "guest_deck_cards": [{"name": "Island", "count": 40}],
        })
        assert response.status_code == 200, response.text
        session_id = response.json()["session_id"]
        session = store.get(session_id)
        game = session.game
        session.pregame_phase = None
        session.current_turn = 0
        game.active_player_index = 0
        game.players[0].hand[:] = [frogmite]
        for name in lands:
            game._put_permanent_onto_battlefield(
                0, _W1G3Permanent(card=_w1g3_find(set_pool, name)), None
            )
        game.start_priority_window(0)
        state = client.get(
            f"/api/sessions/{session_id}/state", params={"seat": 0}
        ).json()
        return game, state["players"][0]["playable_hand_indices"]

    game, playable = offered(["Seat of the Synod"] * 4)
    assert playable == [0]
    assert _cost_for(game, game.players[0], frogmite, None)["generic"] == 0
    assert sum(_w1g3_charge(game, 0, frogmite).values()) == 0
    game, playable = offered(["Island"] * 3)
    assert playable == []
    assert _cost_for(game, game.players[0], frogmite, None)["generic"] == 4


def test_w1g3_bosh_flings_the_mana_value_it_sacrificed(set_pool):
    """"Trample" / "{3}{R}, Sacrifice an artifact: Bosh deals damage equal to
    the sacrificed artifact's mana value to any target." A Myr Enforcer is
    7: the Craw Wurm dies. Bosh may sacrifice itself (its ruling, 2020-08-07:
    "Bosh can be sacrificed to pay the cost of its last ability") and deals 8
    from beyond the battlefield."""
    game, mine, theirs = _w1g3_table(
        set_pool, mine=["Bosh, Iron Golem", "Myr Enforcer"] + ["Great Furnace"] * 8,
        theirs=["Craw Wurm"],
    )
    game.enforce_mana_costs = False
    bosh, enforcer = mine[:2]
    wurm = theirs[0]
    assert game._has_keyword(bosh, "trample")
    activated = game.activate_permanent_ability(
        0, "Bosh, Iron Golem", target_permanent_ids=[wurm.permanent_id],
        cost_permanent_ids=[enforcer.permanent_id],
    )
    assert activated.supported, activated.details
    _w1g3_resolve(game)
    game.check_state_based_actions()
    assert not game.is_on_battlefield(wurm) and not game.is_on_battlefield(enforcer)
    assert "Bosh, Iron Golem dealt 7 damage to Craw Wurm" in game.log

    activated = game.activate_permanent_ability(
        0, "Bosh, Iron Golem", target_player_index=1,
        cost_permanent_ids=[bosh.permanent_id],
    )
    assert activated.supported, activated.details
    _w1g3_resolve(game)
    assert game.players[1].life == 12
    assert "Bosh, Iron Golem" in [c.name for c in game.players[0].graveyard]

# ==== end W1G3 ======================================================

# ==== end W1G3 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.
#
# Imprint (an ability word, CR 207.2c) over CR 607.2a's linked abilities:
# "the exiled card" is the card this permanent's own entry trigger exiled and
# still in exile (``linked_exile.cards_still_exiled_with``). Each card is
# driven through the real entry points — cast, the entry trigger on the stack,
# the "may" answered by an interactive seat and by a seat nobody asks, then the
# linked ability.

from engine import Game as _W1G5Game
from engine import PlayerState as _W1G5PlayerState
from engine.models import Permanent as _W1G5Permanent
from engine.mana_could_produce import (
    ability_colors_on_offer as _w1g5_colors_on_offer,
)
from engine.oracle import compile_card_oracle as _w1g5_compile
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_table(set_pool, hand=(), *, interactive=False, bob_hand=()):
    lea = set_pool("LEA")
    alice = _W1G5PlayerState(
        name="Alice", hand=list(hand), library=[lea["Plains"]] * 8,
    )
    bob = _W1G5PlayerState(
        name="Bob", hand=list(bob_hand), library=[lea["Island"]] * 8,
    )
    game = _W1G5Game(players=[alice, bob])
    game.enforce_mana_costs = True
    game.interactive_seats = {0} if interactive else set()
    game.active_player_index = 0
    game.priority_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game, alice, bob


def _w1g5_put(game, seat, card):
    permanent = _W1G5Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g5_named(game, name):
    return next(p for p in game.all_permanents() if p.card.name == name)


def _w1g5_imprint_from_hand(game, alice, source_name, card_name):
    """Cast *source_name* for an interactive seat 0, take its imprint offer
    and pick *card_name* out of the hand."""
    assert game.cast_from_hand(0, source_name).supported
    assert game.resolve_top_of_stack() is False, "the imprint offer holds the trigger"
    assert [c.kind for c in game.pending_choices] == ["optional_pay"]
    assert game.confirm_optional_pay(0, accept=True)
    (pick,) = game.pending_choices
    assert pick.kind == "exile_from_hand_choice"
    slot = next(i for i, c in enumerate(alice.hand) if c.name == card_name)
    assert slot in game.live_exile_from_hand_choices(pick)
    assert game.confirm_exile_from_hand_choice(0, slot)
    _w1g5_resolve_stack(game)
    return _w1g5_named(game, source_name)


def _w1g5_tap_for(game, permanent, color):
    for symbol in list(game.players[0].mana_pool):
        game.players[0].mana_pool[symbol] = 0
    permanent.tapped = False
    result = game.activate_permanent_ability(
        0, permanent.card.name,
        permanent_index=game.battlefield_index_of(permanent),
        ability_index=0, mana_color=color,
    )
    assert result.supported, result.details
    return {k: v for k, v in game.players[0].mana_pool.items() if v}


def test_w1g5_chrome_mox_taps_only_for_the_imprinted_cards_colors(set_pool):
    """"{T}: Add one mana of any of the exiled card's colors." A red card
    imprinted makes {R}, and a colour named outside the set is re-checked to
    one inside it (the colour fan offers only {R})."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, _bob = _w1g5_table(
        set_pool, [mrd["Chrome Mox"], lea["Lightning Bolt"], lea["Wheel of Fortune"]],
        interactive=True,
    )
    mox = _w1g5_imprint_from_hand(game, alice, "Chrome Mox", "Lightning Bolt")
    assert [c.name for c in alice.exile] == ["Lightning Bolt"]
    (ability,) = _w1g5_compile(mox.card).activated_abilities
    assert ability.supported
    assert _w1g5_colors_on_offer(game, mox, ability.instruction) == ("R",)
    assert _w1g5_tap_for(game, mox, "R") == {"R": 1}
    assert _w1g5_tap_for(game, mox, "G") == {"R": 1}


def test_w1g5_chrome_mox_offers_each_color_of_a_multicolored_card(set_pool):
    """Ruling 2025-02-07: "If the exiled card is multicolored, you choose one
    of that card's colors each time you tap this artifact for mana.\""""
    mrd, inv = set_pool("MRD"), set_pool("INV")
    gold = next(
        c for c in sorted(inv.values(), key=lambda c: c.name)
        if set(c.colors) == {"W", "U"} and "Land" not in c.type_line
        and "Artifact" not in c.type_line
    )
    game, alice, _bob = _w1g5_table(
        set_pool, [mrd["Chrome Mox"], gold], interactive=True,
    )
    mox = _w1g5_imprint_from_hand(game, alice, "Chrome Mox", gold.name)
    (ability,) = _w1g5_compile(mox.card).activated_abilities
    assert _w1g5_colors_on_offer(game, mox, ability.instruction) == ("W", "U")
    assert _w1g5_tap_for(game, mox, "U") == {"U": 1}
    assert _w1g5_tap_for(game, mox, "W") == {"W": 1}


def test_w1g5_chrome_mox_adds_nothing_with_no_card_or_once_the_card_leaves(set_pool):
    """Ruling 2025-02-07: "If no card is exiled with this artifact, it can't
    add mana." A declined imprint links nothing; a card that leaves exile is no
    longer "the exiled card"; and the Mox returning is a new object with no
    exiled card at all (CR 400.7)."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, _bob = _w1g5_table(
        set_pool, [mrd["Chrome Mox"], lea["Lightning Bolt"]], interactive=True,
    )
    assert game.cast_from_hand(0, "Chrome Mox").supported
    assert game.resolve_top_of_stack() is False
    assert game.confirm_optional_pay(0, accept=False)
    _w1g5_resolve_stack(game)
    mox = _w1g5_named(game, "Chrome Mox")
    assert alice.exile == [] and [c.name for c in alice.hand] == ["Lightning Bolt"]
    assert _w1g5_tap_for(game, mox, "R") == {}
    assert "it adds no mana" in game.log[-1]

    game, alice, _bob = _w1g5_table(
        set_pool, [mrd["Chrome Mox"], lea["Lightning Bolt"]], interactive=True,
    )
    mox = _w1g5_imprint_from_hand(game, alice, "Chrome Mox", "Lightning Bolt")
    assert _w1g5_tap_for(game, mox, "R") == {"R": 1}
    game.remove_from_battlefield(mox)
    returned = _w1g5_put(game, 0, mrd["Chrome Mox"])
    assert [c.name for c in alice.exile] == ["Lightning Bolt"]
    assert _w1g5_tap_for(game, returned, "R") == {}

    game, alice, _bob = _w1g5_table(
        set_pool, [mrd["Chrome Mox"], lea["Lightning Bolt"]], interactive=True,
    )
    mox = _w1g5_imprint_from_hand(game, alice, "Chrome Mox", "Lightning Bolt")
    (bolt,) = alice.exile
    assert game.take_card_from_exile(0, bolt)
    assert _w1g5_tap_for(game, mox, "R") == {}


def _w1g5_golem_imprints(set_pool, graveyard_index, *, interactive=True):
    """Mirror Golem cast with Terror and Grizzly Bears in Bob's graveyard; the
    imprint's target is the card at *graveyard_index* (an interactive seat
    names it on the trigger's target prompt, CR 603.3d)."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, bob = _w1g5_table(
        set_pool, [mrd["Mirror Golem"]], interactive=interactive,
        bob_hand=[lea["Lightning Bolt"], lea["Terror"]],
    )
    game.enforce_mana_costs = False
    bob.graveyard.extend([lea["Terror"], lea["Grizzly Bears"]])
    assert game.cast_from_hand(0, "Mirror Golem").supported
    if interactive:
        assert game.resolve_top_of_stack() is False
        assert [c.kind for c in game.pending_choices] == ["trigger_target"]
        assert game.confirm_trigger_target(0, seat=1, graveyard_index=graveyard_index)
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()
    return game, alice, bob, _w1g5_named(game, "Mirror Golem")


def test_w1g5_mirror_golem_is_protected_from_the_exiled_instants_type(set_pool):
    """"This creature has protection from each of the exiled card's card
    types." Terror imprinted: an instant cannot target the Golem (CR 702.16b)
    — Bob's Terror and Lightning Bolt are both refused — and its damage would
    be prevented (CR 702.16e)."""
    game, _alice, bob, golem = _w1g5_golem_imprints(set_pool, 0)
    assert [c.name for c in bob.exile] == ["Terror"]
    assert game._protection_qualities(golem) == {("card_type", "instant")}
    bolt = set_pool("LEA")["Lightning Bolt"]
    assert not game._can_be_targeted(golem, bolt, caster_index=1)
    assert game._is_protected_from(golem, bolt, as_damage_source=True, seat=1)
    refused = game.cast_from_hand(1, "Lightning Bolt", target_permanent_ids=[golem.permanent_id])
    assert not refused.supported
    assert game.is_on_battlefield(golem)


def test_w1g5_mirror_golem_with_a_creature_imprinted_answers_creatures_only(set_pool):
    """Grizzly Bears imprinted: protection from creatures (a creature cannot
    block it or damage it, CR 702.16e/f) and nothing else — an instant
    targets it as usual."""
    game, _alice, bob, golem = _w1g5_golem_imprints(set_pool, 1)
    assert [c.name for c in bob.exile] == ["Grizzly Bears"]
    assert game._protection_qualities(golem) == {("card_type", "creature")}
    bears = _w1g5_put(game, 1, set_pool("LEA")["Grizzly Bears"])
    assert game._is_protected_from(golem, bears)
    bolt = set_pool("LEA")["Lightning Bolt"]
    assert game._can_be_targeted(golem, bolt, caster_index=1)


def test_w1g5_mirror_golem_loses_the_protection_with_the_card(set_pool):
    """The exiled card leaving exile takes the protection with it, and a
    Golem that never imprinted (the seat nobody asks takes the first legal
    target) has the one quality its card gives."""
    game, _alice, bob, golem = _w1g5_golem_imprints(set_pool, 0, interactive=False)
    assert game._protection_qualities(golem) == {("card_type", "instant")}
    (terror,) = bob.exile
    assert game.take_card_from_exile(1, terror)
    assert game._protection_qualities(golem) == set()


def _w1g5_duplicant_exiles(set_pool, victim_name, *, interactive=True, bob_lands=()):
    """Duplicant cast at Bob's *victim_name* — named on the trigger's target
    prompt and the imprint taken, for an interactive seat 0."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, _alice, bob = _w1g5_table(set_pool, [mrd["Duplicant"]], interactive=interactive)
    game.enforce_mana_costs = False
    for land in bob_lands:
        _w1g5_put(game, 1, lea[land])
    victim = _w1g5_put(game, 1, lea[victim_name])
    assert game.cast_from_hand(0, "Duplicant").supported
    if interactive:
        assert game.resolve_top_of_stack() is False
        assert [c.kind for c in game.pending_choices] == ["trigger_target"]
        assert game.confirm_trigger_target(0, permanent_id=victim.permanent_id)
        game.resolve_top_of_stack()
        assert [c.kind for c in game.pending_choices] == ["optional_pay"]
        assert game.confirm_optional_pay(0, accept=True)
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()
    return game, bob, _w1g5_named(game, "Duplicant")


def test_w1g5_duplicant_takes_the_exiled_creatures_body_and_types(set_pool):
    """"…this creature has the power, toughness, and creature types of the
    last creature card exiled with it. It's still a Shapeshifter." Hill Giant
    exiled: a 3/3 Giant Shapeshifter, and a +1/+1 modification still applies on
    top of the new base (the 2020-08-07 ruling)."""
    from engine.pt import add_pt_modifier as _w1g5_add_pt

    game, bob, duplicant = _w1g5_duplicant_exiles(set_pool, "Hill Giant")
    assert [c.name for c in bob.exile] == ["Hill Giant"]
    assert list(game.controlled_by(1)) == []
    assert (duplicant.effective_power, duplicant.effective_toughness) == (3, 3)
    assert duplicant.has_type("giant") and duplicant.has_type("shapeshifter")
    _w1g5_add_pt(duplicant, 1, 1)
    game._recompute_continuous_effects()
    assert (duplicant.effective_power, duplicant.effective_toughness) == (4, 4)


def test_w1g5_duplicant_is_its_printed_self_once_the_card_leaves_exile(set_pool):
    """CR 607.2a: only a card still in exile is "a card exiled with this
    creature". The seat nobody asks takes the opposing creature too."""
    game, bob, duplicant = _w1g5_duplicant_exiles(set_pool, "Hill Giant", interactive=False)
    assert (duplicant.effective_power, duplicant.effective_toughness) == (3, 3)
    (giant,) = bob.exile
    assert game.take_card_from_exile(1, giant)
    game._recompute_continuous_effects()
    assert (duplicant.effective_power, duplicant.effective_toughness) == (2, 4)
    assert not duplicant.has_type("giant") and duplicant.has_type("shapeshifter")


def test_w1g5_duplicant_follows_an_exiled_cards_characteristic_defining_pt(set_pool):
    """Ruling 2020-08-07: a */* defined by the card's own ability applies in
    exile, and Duplicant's P/T "are constantly updated". Nightmare counts the
    Swamps its owner controls: two, then three."""
    game, _bob, duplicant = _w1g5_duplicant_exiles(
        set_pool, "Nightmare", bob_lands=("Swamp", "Swamp"),
    )
    assert (duplicant.effective_power, duplicant.effective_toughness) == (2, 2)
    assert duplicant.has_type("nightmare")
    _w1g5_put(game, 1, set_pool("LEA")["Swamp"])
    game._recompute_continuous_effects()
    assert (duplicant.effective_power, duplicant.effective_toughness) == (3, 3)


def test_w1g5_soul_foundry_makes_a_copy_of_the_imprinted_creature_for_its_mana_value(set_pool):
    """"{X}, {T}: Create a token that's a copy of the exiled card. X is the mana
    value of that card." Hill Giant imprinted: X is 4 — two mana is refused —
    and the token is a Hill Giant with the card's mana cost and mana value
    (the 2004-12-01 rulings)."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, _bob = _w1g5_table(
        set_pool, [mrd["Soul Foundry"], lea["Hill Giant"], lea["Grizzly Bears"]],
        interactive=True,
    )
    alice.mana_pool["C"] = 4
    foundry = _w1g5_imprint_from_hand(game, alice, "Soul Foundry", "Hill Giant")
    foundry.metadata["summoning_sickness_turn"] = -99
    assert [c.name for c in alice.exile] == ["Hill Giant"]

    alice.mana_pool.update({"C": 0, "R": 2})
    refused = game.activate_permanent_ability(
        0, "Soul Foundry", permanent_index=game.battlefield_index_of(foundry),
        ability_index=0,
    )
    assert not refused.supported and foundry.tapped is False
    alice.mana_pool["R"] = 4
    assert game.activate_permanent_ability(
        0, "Soul Foundry", permanent_index=game.battlefield_index_of(foundry),
        ability_index=0,
    ).supported
    assert alice.mana_pool["R"] == 0
    _w1g5_resolve_stack(game)
    (token,) = [p for p in game.controlled_by(0) if p.metadata.get("is_token")]
    assert token.effective_card.name == "Hill Giant"
    assert (token.effective_power, token.effective_toughness) == (3, 3)
    assert token.effective_card.mana_cost == "{3}{R}" and token.effective_card.cmc == 4
    assert [c.name for c in alice.exile] == ["Hill Giant"], "the card stays imprinted"


def test_w1g5_soul_foundry_with_nothing_imprinted_makes_nothing(set_pool):
    """A declined imprint: X is 0 (CR 107.2) and the token copies nothing."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, _bob = _w1g5_table(
        set_pool, [mrd["Soul Foundry"], lea["Hill Giant"]], interactive=True,
    )
    alice.mana_pool["C"] = 4
    assert game.cast_from_hand(0, "Soul Foundry").supported
    assert game.resolve_top_of_stack() is False
    assert game.confirm_optional_pay(0, accept=False)
    _w1g5_resolve_stack(game)
    foundry = _w1g5_named(game, "Soul Foundry")
    foundry.metadata["summoning_sickness_turn"] = -99
    assert game.activate_permanent_ability(
        0, "Soul Foundry", permanent_index=game.battlefield_index_of(foundry),
        ability_index=0,
    ).supported
    _w1g5_resolve_stack(game)
    assert [p for p in game.controlled_by(0) if p.metadata.get("is_token")] == []
    assert any("no card is exiled with it" in line for line in game.log)


def _w1g5_shield_imprints(set_pool, graveyard_index):
    """Mourner's Shield cast for an interactive seat 0, its imprint aimed at
    Bob's graveyard card at *graveyard_index* (Shatter, then Grizzly Bears)
    and taken; Bob controls Mons's Goblin Raiders and Grizzly Bears."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, _alice, bob = _w1g5_table(set_pool, [mrd["Mourner's Shield"]], interactive=True)
    game.enforce_mana_costs = False
    bob.graveyard.extend([lea["Shatter"], lea["Grizzly Bears"]])
    goblin = _w1g5_put(game, 1, lea["Mons's Goblin Raiders"])
    bears = _w1g5_put(game, 1, lea["Grizzly Bears"])
    assert game.cast_from_hand(0, "Mourner's Shield").supported
    assert game.resolve_top_of_stack() is False
    assert game.confirm_trigger_target(0, seat=1, graveyard_index=graveyard_index)
    game.resolve_top_of_stack()
    assert [c.kind for c in game.pending_choices] == ["optional_pay"]
    assert game.confirm_optional_pay(0, accept=True)
    _w1g5_resolve_stack(game)
    shield = _w1g5_named(game, "Mourner's Shield")
    shield.metadata["summoning_sickness_turn"] = -99
    return game, bob, shield, goblin, bears


def _w1g5_shield_against(game, shield, source):
    result = game.activate_permanent_ability(
        0, "Mourner's Shield", permanent_index=game.battlefield_index_of(shield),
        ability_index=0, source_seat=game.controller_index_of(source),
        source_permanent_index=game.battlefield_index_of(source),
    )
    assert result.supported, result.details
    _w1g5_resolve_stack(game)


def test_w1g5_mourners_shield_stops_a_source_sharing_the_imprinted_cards_color(set_pool):
    """"{2}, {T}: Prevent all damage that would be dealt this turn by a source
    of your choice that shares a color with the exiled card." Shatter (red)
    imprinted, a red Goblin chosen: none of its damage this turn is dealt, to
    a player or to a creature; a green source's damage still is."""
    from tests.helpers import _damage_dealt as _w1g5_damage_dealt

    game, bob, shield, goblin, bears = _w1g5_shield_imprints(set_pool, 0)
    assert [c.name for c in bob.exile] == ["Shatter"]
    _w1g5_shield_against(game, shield, goblin)
    alice = game.players[0]
    assert _w1g5_damage_dealt(game, alice, 2, source=goblin, combat=True) == 0
    assert _w1g5_damage_dealt(game, bears, 1, source=goblin) == 0
    assert _w1g5_damage_dealt(game, alice, 2, source=bears, combat=True) == 2


def test_w1g5_mourners_shield_chosen_source_must_share_the_color(set_pool):
    """A green source chosen against a red imprint shares nothing: the shield
    is rechecked as the damage would be dealt (CR 609.7b) and prevents none."""
    from tests.helpers import _damage_dealt as _w1g5_damage_dealt

    game, _bob, shield, _goblin, bears = _w1g5_shield_imprints(set_pool, 0)
    _w1g5_shield_against(game, shield, bears)
    assert _w1g5_damage_dealt(game, game.players[0], 2, source=bears) == 2


def test_w1g5_mourners_shield_arms_nothing_once_the_imprinted_card_leaves(set_pool):
    """Grizzly Bears imprinted, then taken out of exile: no card is "the exiled
    card" any more (CR 607.2a), no colour is left to share, and the shield is
    not armed at all — the green Bears' damage is dealt."""
    from tests.helpers import _damage_dealt as _w1g5_damage_dealt

    game, bob, shield, goblin, bears = _w1g5_shield_imprints(set_pool, 1)
    assert [c.name for c in bob.exile] == ["Grizzly Bears"]
    (exiled,) = bob.exile
    assert game.take_card_from_exile(1, exiled)
    _w1g5_shield_against(game, shield, bears)
    assert "no colored card is exiled with it" in " ".join(game.log[-3:])
    assert _w1g5_damage_dealt(game, game.players[0], 2, source=bears) == 2

def _w1g5_tapped_for(game, seat, land):
    pool = game.players[seat].mana_pool
    before = dict(pool)
    assert game.tap_land_for_mana_or_refusal(
        seat, land.card.name, permanent_id=land.permanent_id,
    ) is None
    return {k: pool[k] - before.get(k, 0) for k in pool if pool[k] != before.get(k, 0)}


def test_w1g5_extraplanar_lens_doubles_every_land_sharing_the_imprinted_name(set_pool):
    """"Whenever a land with the same name as the exiled card is tapped for
    mana, its controller adds one mana of any type that land produced." A
    Forest imprinted: each Forest — Alice's and Bob's, each to its own
    controller — makes {G}{G}; a Mountain makes its one {R}."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, bob = _w1g5_table(set_pool, [mrd["Extraplanar Lens"]], interactive=True)
    game.enforce_mana_costs = False
    imprinted = _w1g5_put(game, 0, lea["Forest"])
    forest = _w1g5_put(game, 0, lea["Forest"])
    mountain = _w1g5_put(game, 0, lea["Mountain"])
    theirs = _w1g5_put(game, 1, lea["Forest"])
    assert game.cast_from_hand(0, "Extraplanar Lens").supported
    assert game.resolve_top_of_stack() is False
    assert game.confirm_trigger_target(0, permanent_id=imprinted.permanent_id)
    game.resolve_top_of_stack()
    assert game.confirm_optional_pay(0, accept=True)
    _w1g5_resolve_stack(game)
    assert [c.name for c in alice.exile] == ["Forest"]
    assert not game.is_on_battlefield(imprinted)
    assert _w1g5_tapped_for(game, 0, forest) == {"G": 2}
    assert _w1g5_tapped_for(game, 0, mountain) == {"R": 1}
    assert _w1g5_tapped_for(game, 1, theirs) == {"G": 2}
    assert bob.mana_pool["G"] == 2 and alice.mana_pool["G"] == 2


def test_w1g5_extraplanar_lens_without_its_card_adds_nothing(set_pool):
    """A declined imprint is a Lens with no exiled card: a Forest is one {G}."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, _alice, _bob = _w1g5_table(set_pool, [mrd["Extraplanar Lens"]], interactive=True)
    game.enforce_mana_costs = False
    target = _w1g5_put(game, 0, lea["Forest"])
    forest = _w1g5_put(game, 0, lea["Forest"])
    assert game.cast_from_hand(0, "Extraplanar Lens").supported
    assert game.resolve_top_of_stack() is False
    assert game.confirm_trigger_target(0, permanent_id=target.permanent_id)
    game.resolve_top_of_stack()
    assert game.confirm_optional_pay(0, accept=False)
    _w1g5_resolve_stack(game)
    assert game.is_on_battlefield(target)
    assert _w1g5_tapped_for(game, 0, forest) == {"G": 1}


def _w1g5_prison_imprints(set_pool, pick_name, *, interactive=True):
    """Thought Prison cast at Bob for an interactive seat 0: the offer taken
    and *pick_name* chosen out of Bob's revealed hand."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, bob = _w1g5_table(
        set_pool, [mrd["Thought Prison"], lea["Lightning Bolt"]],
        interactive=interactive,
        bob_hand=[
            lea["Lightning Bolt"], lea["Mountain"], lea["Grizzly Bears"],
            lea["Shatter"], lea["Giant Growth"],
        ],
    )
    game.enforce_mana_costs = False
    assert game.cast_from_hand(0, "Thought Prison", target_player_index=1).supported
    if interactive:
        assert game.resolve_top_of_stack() is False
        assert [c.kind for c in game.pending_choices] == ["optional_pay"]
        assert game.confirm_optional_pay(0, accept=True)
        (pick,) = game.pending_choices
        assert pick.kind == "revealed_hand_pick" and pick.player_index == 0
        legal = pick.data["legal_indices"]
        assert all(bob.hand[i].name != "Mountain" for i in legal), "a nonland card"
        slot = next(i for i in legal if bob.hand[i].name == pick_name)
        assert game.confirm_revealed_hand_pick(0, slot)
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()
    return game, alice, bob, _w1g5_named(game, "Thought Prison")


def test_w1g5_thought_prison_burns_a_caster_sharing_a_color_or_mana_value(set_pool):
    """"Whenever a player casts a spell that shares a color or mana value with
    the exiled card, this artifact deals 2 damage to that player." Lightning
    Bolt (red, 1) imprinted out of Bob's hand: Giant Growth (green, 1) and
    Shatter (red, 2) each cost their caster 2; Grizzly Bears (green, 2) does
    not; and Alice's own red spell burns Alice ("that player")."""
    game, alice, bob, prison = _w1g5_prison_imprints(set_pool, "Lightning Bolt")
    assert [c.name for c in bob.exile] == ["Lightning Bolt"]
    assert "Lightning Bolt" not in [c.name for c in bob.hand]
    game.active_player_index = game.priority_player_index = 1

    assert game.cast_from_hand(1, "Grizzly Bears").supported
    _w1g5_resolve_stack(game)
    assert bob.life == 20
    bears = _w1g5_named(game, "Grizzly Bears")
    assert game.cast_from_hand(
        1, "Giant Growth", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    assert bob.life == 18
    assert game.cast_from_hand(
        1, "Shatter", target_permanent_ids=[prison.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    assert bob.life == 16
    assert not game.is_on_battlefield(prison)

    game, alice, bob, _prison = _w1g5_prison_imprints(set_pool, "Lightning Bolt")
    game.active_player_index = game.priority_player_index = 0
    assert game.cast_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    _w1g5_resolve_stack(game)
    assert (alice.life, bob.life) == (18, 17)


def test_w1g5_thought_prison_declined_or_emptied_burns_nobody(set_pool):
    """A declined offer exiles nothing, and a card that leaves exile shares
    nothing: no spell burns anyone."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, _alice, bob = _w1g5_table(
        set_pool, [mrd["Thought Prison"]], interactive=True,
        bob_hand=[lea["Lightning Bolt"], lea["Shatter"]],
    )
    game.enforce_mana_costs = False
    assert game.cast_from_hand(0, "Thought Prison", target_player_index=1).supported
    assert game.resolve_top_of_stack() is False
    assert game.confirm_optional_pay(0, accept=False)
    _w1g5_resolve_stack(game)
    assert bob.exile == [] and len(bob.hand) == 2
    game.active_player_index = game.priority_player_index = 1
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g5_resolve_stack(game)
    assert bob.life == 20

    game, _alice, bob, _prison = _w1g5_prison_imprints(set_pool, "Shatter")
    (shatter,) = bob.exile
    assert game.take_card_from_exile(1, shatter)
    game.active_player_index = game.priority_player_index = 1
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g5_resolve_stack(game)
    assert bob.life == 20

def _w1g5_scepter_with(set_pool, imprint="Lightning Bolt", *, interactive=True):
    """Isochron Scepter on the battlefield with *imprint* exiled with it — by
    the imprint's own offer and pick — and ready to activate."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, bob = _w1g5_table(
        set_pool, [mrd["Isochron Scepter"], lea[imprint]], interactive=True,
    )
    alice.mana_pool["C"] = 2
    scepter = _w1g5_imprint_from_hand(game, alice, "Isochron Scepter", imprint)
    scepter.metadata["summoning_sickness_turn"] = -99
    game.interactive_seats = {0} if interactive else set()
    alice.mana_pool["C"] = 2
    return game, alice, bob, scepter


def _w1g5_activate_scepter(game, scepter):
    result = game.activate_permanent_ability(
        0, "Isochron Scepter", permanent_index=game.battlefield_index_of(scepter),
        ability_index=0,
    )
    assert result.supported, result.details


def test_w1g5_isochron_scepter_casts_a_copy_of_the_imprinted_instant(set_pool):
    """"{2}, {T}: You may copy the exiled card. If you do, you may cast the
    copy without paying its mana cost." Lightning Bolt imprinted: the ability
    resolving offers the cast (CR 707.12, made during the resolution — the
    2020-08-07 ruling); the copy is cast free, aimed at Bob, resolves for 3
    and ceases to exist (CR 707.10a) while the imprinted Bolt stays in exile.
    Twice, on two turns' worth of activations."""
    game, alice, bob, scepter = _w1g5_scepter_with(set_pool)
    for expected in (17, 14):
        _w1g5_activate_scepter(game, scepter)
        assert game.resolve_top_of_stack() is False
        (offer,) = game.pending_choices
        assert offer.kind == "copy_cast" and offer.data["card_name"] == "Lightning Bolt"
        outcome = []
        assert game.confirm_copy_cast(0, True, outcome=outcome, target_player_index=1)
        (copy,) = [item for item in game.stack if item.card.name == "Lightning Bolt"]
        assert copy.is_copy, "the spell is the copy, not the card"
        _w1g5_resolve_stack(game)
        assert bob.life == expected
        assert [c.name for c in alice.exile] == ["Lightning Bolt"]
        assert alice.graveyard == [] and bob.graveyard == []
        assert alice.mana_pool["C"] == 0, "{2} paid; the copy's own cost waived"
        scepter.tapped = False
        alice.mana_pool["C"] = 2


def test_w1g5_isochron_scepter_declined_or_emptied_casts_nothing(set_pool):
    """A declined offer makes no copy; and once the imprinted card has left
    exile the ability resolves with nothing to copy (the ruling's "the copy
    can't be made")."""
    game, alice, bob, scepter = _w1g5_scepter_with(set_pool)
    _w1g5_activate_scepter(game, scepter)
    assert game.resolve_top_of_stack() is False
    assert game.confirm_copy_cast(0, False)
    _w1g5_resolve_stack(game)
    assert bob.life == 20 and [c.name for c in alice.exile] == ["Lightning Bolt"]
    assert game.pending_choices == []

    game, alice, bob, scepter = _w1g5_scepter_with(set_pool)
    # Queued, not settled: the ability waits on the stack for a response.
    assert game.queue_permanent_ability(
        0, "Isochron Scepter", permanent_index=game.battlefield_index_of(scepter),
        ability_index=0,
    ).supported
    assert [item.card.name for item in game.stack] == ["Isochron Scepter"]
    assert game.pending_choices == [], "not yet resolving"
    (bolt,) = alice.exile
    assert game.take_card_from_exile(0, bolt), "removed in response"
    _w1g5_resolve_stack(game)
    assert game.pending_choices == [] and bob.life == 20
    assert "no card is exiled with it to copy" in " ".join(game.log[-3:])


def test_w1g5_isochron_scepter_still_copies_after_it_leaves(set_pool):
    """Ruling 2020-08-07: "If Isochron Scepter leaves the battlefield while
    the activated ability is on the stack, the ability can still make a
    copy." A seat nobody asks takes the offer with its rehearsed chooser."""
    game, alice, bob, scepter = _w1g5_scepter_with(set_pool, interactive=False)
    assert game.queue_permanent_ability(
        0, "Isochron Scepter", permanent_index=game.battlefield_index_of(scepter),
        ability_index=0,
    ).supported
    assert bob.life == 20 and len(game.stack) == 1
    game.remove_from_battlefield(scepter)
    assert not game.is_on_battlefield(scepter)
    _w1g5_resolve_stack(game)
    assert bob.life == 17
    assert [c.name for c in alice.exile] == ["Lightning Bolt"]


def test_w1g5_isochron_scepter_offer_is_answered_on_the_wire(set_pool):
    """The ``copy_cast`` prompt renders with the exiled card's place (the
    client's cast dialog opens on it), and the ``copy_cast_confirm`` action
    casts the copy with the ordinary cast fields."""
    from types import SimpleNamespace as _W1G5Namespace

    from web.action_prompt_board import _action_copy_cast_confirm
    from web.prompts import PromptContext, render_prompts
    from web.schemas import GameActionRequest

    game, alice, bob, scepter = _w1g5_scepter_with(set_pool)
    _w1g5_activate_scepter(game, scepter)
    assert game.resolve_top_of_stack() is False
    offered = render_prompts(PromptContext(
        game=game, viewer_seat=0,
        serialize_card=lambda card: {"name": getattr(card, "name", str(card))},
        seat_type=lambda index: "human" if index in game.interactive_seats else "ai",
    ))["copy_cast"]
    assert offered["card_name"] == "Lightning Bolt"
    assert (offered["exile_seat"], offered["exile_index"]) == (0, 0)
    assert alice.exile[offered["exile_index"]].name == "Lightning Bolt"

    _action_copy_cast_confirm(
        _W1G5Namespace(game=game),
        GameActionRequest(
            seat=0, action="copy_cast_confirm", accept=True, target_player_index=1,
        ),
        None,
    )
    _w1g5_resolve_stack(game)
    assert bob.life == 17 and game.pending_choices == []


def _w1g5_helix_imprints(set_pool, buried, *, interactive=True):
    """Spellweaver Helix with the two sorceries *buried* in Bob's graveyard
    exiled by its imprint (named on the trigger's target prompt), Bad Moon and
    a Swamp on Bob's side, and a Stone Rain in Alice's hand."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, bob = _w1g5_table(
        set_pool, [mrd["Spellweaver Helix"], lea["Stone Rain"]], interactive=interactive,
    )
    game.enforce_mana_costs = False
    bob.graveyard.extend(lea[name] for name in buried)
    moon = _w1g5_put(game, 1, lea["Bad Moon"])
    swamp = _w1g5_put(game, 1, lea["Swamp"])
    assert game.cast_from_hand(0, "Spellweaver Helix").supported
    if interactive:
        assert game.resolve_top_of_stack() is False
        assert game.confirm_trigger_target(0, seat=1, graveyard_indices=[0, 1])
        game.resolve_top_of_stack()
        assert game.confirm_optional_pay(0, accept=True)
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()
    return game, alice, bob, moon, swamp


def _w1g5_cast_stone_rain(game, swamp, *, accept=True):
    assert game.cast_from_hand(0, "Stone Rain", target_permanent_ids=[swamp.permanent_id]).supported
    while game.stack and not game.pending_choices:
        if game.resolve_top_of_stack():
            continue
        break
    offers = [c for c in game.pending_choices if c.kind == "copy_cast"]
    for offer in offers:
        assert game.confirm_copy_cast(0, accept)
    _w1g5_resolve_stack(game)
    return [offer.data["card_name"] for offer in offers]


def test_w1g5_spellweaver_helix_casts_a_copy_of_the_other_imprinted_sorcery(set_pool):
    """"Whenever a player casts a card, if it has the same name as one of the
    cards exiled with this artifact, you may copy the other. If you do, you
    may cast the copy without paying its mana cost." Stone Rain and
    Tranquility imprinted: Alice's Stone Rain offers a copy of Tranquility,
    cast above it, which destroys Bad Moon before the Stone Rain resolves; the
    copy is not a card, so it does not trigger the Helix again (CR 707.10)."""
    game, alice, bob, moon, swamp = _w1g5_helix_imprints(set_pool, ("Stone Rain", "Tranquility"))
    assert [c.name for c in bob.exile] == ["Stone Rain", "Tranquility"]
    assert _w1g5_cast_stone_rain(game, swamp) == ["Tranquility"]
    assert not game.is_on_battlefield(moon) and not game.is_on_battlefield(swamp)
    assert [c.name for c in bob.exile] == ["Stone Rain", "Tranquility"]
    assert [c.name for c in alice.graveyard] == ["Stone Rain"], "the copy ceased to exist"
    assert sum("cast a copy of" in line for line in game.log) == 1


def test_w1g5_spellweaver_helix_two_of_one_name_make_one_copy(set_pool):
    """Ruling 2004-12-01: "If the two imprinted sorcery cards have the same
    name and a card with that name is cast, only one copy is created." And a
    seat nobody asks takes the offer."""
    game, _alice, _bob, _moon, swamp = _w1g5_helix_imprints(
        set_pool, ("Stone Rain", "Stone Rain"), interactive=False,
    )
    _w1g5_put(game, 1, set_pool("LEA")["Swamp"])
    assert game.cast_from_hand(0, "Stone Rain", target_permanent_ids=[swamp.permanent_id]).supported
    _w1g5_resolve_stack(game)
    assert sum("cast a copy of Stone Rain" in line for line in game.log) == 1
    assert not game.is_on_battlefield(swamp)


def test_w1g5_spellweaver_helix_with_one_card_left_does_nothing(set_pool):
    """Ruling 2004-12-01: "If there's only one imprinted sorcery card, nothing
    happens." With Tranquility gone from exile, Stone Rain names one card and
    there is no other; with Stone Rain gone, the cast names none and the Helix
    does not trigger (CR 603.4)."""
    game, _alice, bob, moon, swamp = _w1g5_helix_imprints(set_pool, ("Stone Rain", "Tranquility"))
    tranquility = next(c for c in bob.exile if c.name == "Tranquility")
    assert game.take_card_from_exile(1, tranquility)
    assert _w1g5_cast_stone_rain(game, swamp) == []
    assert game.is_on_battlefield(moon) and not game.is_on_battlefield(swamp)

    game, _alice, bob, moon, swamp = _w1g5_helix_imprints(set_pool, ("Stone Rain", "Tranquility"))
    rain = next(c for c in bob.exile if c.name == "Stone Rain")
    assert game.take_card_from_exile(1, rain)
    before = len(game.log)
    assert _w1g5_cast_stone_rain(game, swamp) == []
    assert game.is_on_battlefield(moon)
    assert not any("Spellweaver Helix" in line for line in game.log[before:])

def test_w1g5_synod_sanctum_exiles_your_own_permanent_and_returns_the_pile(set_pool):
    """Drive list. "{2}, {T}: Exile target permanent you control." — an
    opponent's creature is no target — and "{2}, Sacrifice this artifact:
    Return all cards exiled with this artifact to the battlefield under your
    control." The Bears comes back a new object (CR 400.7)."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, _bob = _w1g5_table(set_pool, interactive=True)
    sanctum = _w1g5_put(game, 0, mrd["Synod Sanctum"])
    bears = _w1g5_put(game, 0, lea["Grizzly Bears"])
    giant = _w1g5_put(game, 1, lea["Hill Giant"])
    alice.mana_pool["C"] = 2
    refused = game.activate_permanent_ability(
        0, "Synod Sanctum", permanent_index=game.battlefield_index_of(sanctum),
        ability_index=0, target_permanent_ids=[giant.permanent_id],
    )
    assert not refused.supported and game.is_on_battlefield(giant)
    assert game.activate_permanent_ability(
        0, "Synod Sanctum", permanent_index=game.battlefield_index_of(sanctum),
        ability_index=0, target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    assert [c.name for c in alice.exile] == ["Grizzly Bears"]
    alice.mana_pool["C"] = 2
    assert game.activate_permanent_ability(
        0, "Synod Sanctum", permanent_index=game.battlefield_index_of(sanctum),
        ability_index=1,
    ).supported
    _w1g5_resolve_stack(game)
    returned = _w1g5_named(game, "Grizzly Bears")
    assert returned is not bears and alice.exile == []
    assert [c.name for c in alice.graveyard] == ["Synod Sanctum"]

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.
#
# Counters on artifacts: fate counters as a sweep's exemption, charge counters
# as a cast's mana-value gate, remove-all-and-count, a counter removed as a cost
# from any permanent.

import pytest as _w1g6_pytest

from engine import Game as _w1g6_Game, PlayerState as _w1g6_PlayerState
from engine.models import (
    CardDefinition as _w1g6_CardDefinition, Permanent as _w1g6_Permanent,
)
from engine.named_counters import counters_on as _w1g6_counters_on
from engine.oracle import compile_card_oracle as _w1g6_compile
from tests.helpers import resolve_stack as _w1g6_resolve_stack


def _w1g6_creature(name: str, power: int = 2, toughness: int = 2,
                   type_line: str = "Creature — Test", mana_cost: str = "{1}{G}",
                   cmc: float = 2.0):
    return _w1g6_CardDefinition(
        name=name, mana_cost=mana_cost, cmc=cmc, type_line=type_line,
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": type_line,
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g6_nosick(perm):
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _w1g6_game(mine=(), theirs=(), hand=(), their_hand=()):
    game = _w1g6_Game(players=[
        _w1g6_PlayerState(name="P1", battlefield=list(mine), hand=list(hand)),
        _w1g6_PlayerState(name="P2", battlefield=list(theirs),
                          hand=list(their_hand)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    return game


def test_w1g6_oblivion_stone_spares_only_what_carries_a_fate_counter(set_pool):
    """"{4}, {T}: Put a fate counter on target permanent." / "{5}, {T},
    Sacrifice this artifact: Destroy each nonland permanent without a fate
    counter on it, then remove all fate counters from all permanents."

    "Target permanent" offers every permanent — its own controller's, the
    opponent's, a land — and the sweep spares exactly the marked ones, lands
    untouched, the Stone itself sacrificed as the cost; afterwards no fate
    counter is left anywhere.
    """
    card = set_pool("MRD")["Oblivion Stone"]
    program = _w1g6_compile(card)
    assert program.supported, program.reason
    from engine.targeting import derive_activation_spec

    assert derive_activation_spec(program.activated_abilities[0]) == {
        "kind": "permanent"
    }

    stone = _w1g6_nosick(_w1g6_Permanent(card=card))
    keeper = _w1g6_nosick(_w1g6_Permanent(card=_w1g6_creature("Keeper")))
    mine = _w1g6_nosick(_w1g6_Permanent(card=_w1g6_creature("Mine")))
    theirs = _w1g6_nosick(_w1g6_Permanent(card=_w1g6_creature("Theirs")))
    marked_land = _w1g6_Permanent(card=set_pool("MRD")["Island"])
    their_land = _w1g6_Permanent(card=set_pool("MRD")["Mountain"])
    game = _w1g6_game([stone, keeper, mine, marked_land], [theirs, their_land])

    placed = game.activate_permanent_ability(
        0, "Oblivion Stone", ability_index=0,
        target_permanent_ids=[keeper.permanent_id],
    )
    assert placed.supported, placed
    _w1g6_resolve_stack(game)
    assert _w1g6_counters_on(keeper, "fate") == 1

    # A land is a permanent too: the picker's "permanent" reaches it.
    stone.tapped = False
    placed = game.activate_permanent_ability(
        0, "Oblivion Stone", ability_index=0,
        target_permanent_ids=[marked_land.permanent_id],
    )
    assert placed.supported, placed
    _w1g6_resolve_stack(game)
    assert _w1g6_counters_on(marked_land, "fate") == 1

    stone.tapped = False
    swept = game.activate_permanent_ability(0, "Oblivion Stone", ability_index=1)
    assert swept.supported, swept
    _w1g6_resolve_stack(game)

    board = [p.card.name for p in game.all_permanents()]
    assert "Keeper" in board
    assert "Mine" not in board and "Theirs" not in board
    assert "Island" in board and "Mountain" in board
    assert "Oblivion Stone" not in board
    assert "Oblivion Stone" in [c.name for c in game.players[0].graveyard]
    assert _w1g6_counters_on(keeper, "fate") == 0
    assert _w1g6_counters_on(marked_land, "fate") == 0


def _w1g6_slot(game, seat, permanent):
    return next(
        index for index, candidate in enumerate(game.players[seat].battlefield)
        if candidate is permanent
    )


def test_w1g6_myr_prototype_grows_each_upkeep_and_prices_both_combat_steps(
    set_pool,
):
    """"At the beginning of your upkeep, put a +1/+1 counter on this creature."
    / "This creature can't attack or block unless you pay {1} for each +1/+1
    counter on it."

    Two upkeeps make a 4/4 whose attack costs {2}: refused with one land
    (nothing tapped), paid with two. The same pile prices its block — and a
    Prototype whose counters are gone owes nothing ("for each" at zero).
    """
    pool = set_pool("MRD")
    prototype = _w1g6_nosick(_w1g6_Permanent(card=pool["Myr Prototype"]))
    game = _w1g6_Game(players=[
        _w1g6_PlayerState(name="P1", battlefield=[prototype],
                          library=[pool["Island"]] * 10),
        _w1g6_PlayerState(name="P2", library=[pool["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for _ in range(2):
        game.start_turn(0)
        _w1g6_resolve_stack(game)
    assert prototype.metadata.get("plus_counters") == 2, game.log
    assert (prototype.effective_power, prototype.effective_toughness) == (4, 4)
    assert game._attack_mana_costs_of(prototype, 1) == [{"generic": 2}]

    land = _w1g6_Permanent(card=pool["Plains"])
    game.players[0].battlefield.append(land)
    game._sync_control()
    game.enforce_mana_costs = True
    game._set_phase_and_step("combat", "declare_attackers")
    ok, _why = game.declare_attackers(
        0, [_w1g6_slot(game, 0, prototype)], defending_player_index=1,
    )
    assert not ok and not prototype.tapped and not land.tapped, "{2} owed, one land"

    second = _w1g6_Permanent(card=pool["Plains"])
    game.players[0].battlefield.append(second)
    game._sync_control()
    ok, why = game.declare_attackers(
        0, [_w1g6_slot(game, 0, prototype)], defending_player_index=1,
    )
    assert ok, why
    assert land.tapped and second.tapped
    assert any("paid {2} to declare attackers" in line for line in game.log)

    # The block half reads the same pile, per attacker blocked.
    attacker = _w1g6_nosick(_w1g6_Permanent(card=_w1g6_creature("Raider")))
    assert game._block_mana_costs_of(prototype, attacker) == [{"generic": 2}]
    from engine.named_counters import remove_counters

    remove_counters(prototype, "+1/+1", 2)
    assert game._block_mana_costs_of(prototype, attacker) == []
    assert game._attack_mana_costs_of(prototype, 1) == []


def _w1g6_chalice_table(set_pool, x_value, *, their_hand=(), interactive=()):
    """Chalice of the Void cast by P1 for *x_value*, paid for in full ({X}{X}
    is twice X, the 2021-03-19 ruling), resolved; P2 holds *their_hand*."""
    lea = set_pool("LEA")
    chalice = set_pool("MRD")["Chalice of the Void"]
    game = _w1g6_Game(players=[
        _w1g6_PlayerState(name="P1", hand=[chalice],
                          library=[lea["Island"]] * 10),
        _w1g6_PlayerState(name="P2", hand=list(their_hand),
                          library=[lea["Island"]] * 10),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    game._close_current_priority_step()
    if x_value:
        game.players[0].mana_pool.update({"R": 2 * x_value - 1})
        short = game.queue_from_hand(0, "Chalice of the Void", x_value=x_value)
        assert not short.supported, "X is paid twice"
    game.players[0].mana_pool.update({"R": 2 * x_value})
    assert game.queue_from_hand(0, "Chalice of the Void", x_value=x_value).supported
    assert all(amount == 0 for amount in game.players[0].mana_pool.values())
    _w1g6_resolve_stack(game)
    (permanent,) = [
        p for p in game.all_permanents() if p.card.name == "Chalice of the Void"
    ]
    game.enforce_mana_costs = False
    return game, permanent



@_w1g6_pytest.mark.parametrize("interactive", [(), (0, 1)])
def test_w1g6_chalice_of_the_void_counters_each_spell_of_its_count(
    set_pool, interactive,
):
    """"This artifact enters with X charge counters on it." / "Whenever a
    player casts a spell with mana value equal to the number of charge counters
    on this artifact, counter that spell."

    Cast for X=1 it pays {2} and holds one counter: the opponent's Lightning
    Bolt (mana value 1) is countered, their Grizzly Bears (2) resolves, and
    its own controller's one-drop is countered too — "a player". Nothing to
    answer: an interactive table arms no prompt.
    """
    lea = set_pool("LEA")
    game, chalice = _w1g6_chalice_table(
        set_pool, 1, their_hand=[lea["Lightning Bolt"], lea["Grizzly Bears"]],
        interactive=interactive,
    )
    assert _w1g6_counters_on(chalice, "charge") == 1

    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert [item.card.name for item in game.stack] == [
        "Lightning Bolt", "Chalice of the Void",
    ]
    _w1g6_resolve_stack(game)
    assert game.players[0].life == 20
    assert "Lightning Bolt was countered by Chalice of the Void" in " ".join(game.log)
    assert not game.pending_choices

    assert game.queue_from_hand(1, "Grizzly Bears").supported
    assert [item.card.name for item in game.stack] == ["Grizzly Bears"]
    _w1g6_resolve_stack(game)
    assert any(p.card.name == "Grizzly Bears" for p in game.all_permanents())

    game.players[0].hand.append(lea["Lightning Bolt"])
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    _w1g6_resolve_stack(game)
    assert game.players[1].life == 20, "its own controller's spell too"


def test_w1g6_chalice_reads_its_counters_only_as_the_spell_is_cast(set_pool):
    """The 2021-03-19 rulings: the count matters only when the spell is cast,
    and once the ability has triggered it counters the spell even if Chalice
    leaves the battlefield. So a Bolt cast into one counter is countered after
    the counter is removed and the Chalice destroyed in response; a Bolt cast
    after that, into no Chalice at all, resolves."""
    lea = set_pool("LEA")
    game, chalice = _w1g6_chalice_table(
        set_pool, 1,
        their_hand=[lea["Lightning Bolt"], lea["Shatter"], lea["Lightning Bolt"]],
    )
    from engine.named_counters import remove_counters

    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    remove_counters(chalice, "charge", 1)
    # Shatter (mana value 2) in response, above the trigger: Chalice is gone
    # before its ability resolves.
    assert game.queue_from_hand(
        1, "Shatter", target_permanent_ids=[chalice.permanent_id],
    ).supported
    assert [item.card.name for item in game.stack] == [
        "Lightning Bolt", "Chalice of the Void", "Shatter",
    ]
    _w1g6_resolve_stack(game)
    assert not game.is_on_battlefield(chalice)
    assert game.players[0].life == 20

    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g6_resolve_stack(game)
    assert game.players[0].life == 17


def test_w1g6_chalice_for_zero_counters_the_mana_value_zero_spells(set_pool):
    """"If there are zero charge counters on Chalice of the Void, it counters
    each spell with a mana value of 0" (2021-03-19). A second Chalice cast for
    X=0 has mana value 0 on the stack (CR 202.3e) and is countered; one cast
    for X=1 has mana value 2 and is not."""
    chalice_card = set_pool("MRD")["Chalice of the Void"]
    game, chalice = _w1g6_chalice_table(
        set_pool, 0, their_hand=[chalice_card, chalice_card],
    )
    assert _w1g6_counters_on(chalice, "charge") == 0

    assert game.queue_from_hand(1, "Chalice of the Void", x_value=0).supported
    _w1g6_resolve_stack(game)
    assert [p.card.name for p in game.all_permanents()] == ["Chalice of the Void"]
    assert [c.name for c in game.players[1].graveyard] == ["Chalice of the Void"]

    assert game.queue_from_hand(1, "Chalice of the Void", x_value=1).supported
    _w1g6_resolve_stack(game)
    assert len(game.players[1].battlefield) == 1


def _w1g6_coils_table(set_pool, charge: int, *, mine=()):
    lea = set_pool("LEA")
    coils = _w1g6_Permanent(card=set_pool("MRD")["Lightning Coils"])
    game = _w1g6_Game(players=[
        _w1g6_PlayerState(name="P1", battlefield=[coils, *mine],
                          library=[lea["Island"]] * 10),
        _w1g6_PlayerState(name="P2", library=[lea["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._sync_control()
    from engine.named_counters import add_counters

    add_counters(coils, "charge", charge)
    return game, coils


def _w1g6_elementals(game):
    return [p for p in game.all_permanents() if p.card.name == "Elemental Token"]


def test_w1g6_lightning_coils_spends_every_counter_on_hasty_elementals(set_pool):
    """"At the beginning of your upkeep, if this artifact has five or more charge
    counters on it, remove all of them from it and create that many 3/1 red
    Elemental creature tokens with haste. Exile them at the beginning of the
    next end step."

    "All of them" is every charge counter, and "that many" is how many came
    off: six counters are six 3/1 hasty Elementals and an empty Coils. They
    are exiled at the next end step and the Coils starts again from zero.
    """
    game, coils = _w1g6_coils_table(set_pool, 6)
    game.start_turn(0)
    _w1g6_resolve_stack(game)

    tokens = _w1g6_elementals(game)
    assert len(tokens) == 6, game.log
    assert _w1g6_counters_on(coils, "charge") == 0
    assert all(
        (t.effective_power, t.effective_toughness) == (3, 1) for t in tokens
    )
    assert all(game._has_keyword(t, "haste") for t in tokens)
    assert all(t in game.players[0].battlefield for t in tokens)

    game.resolve_end_step(0)
    _w1g6_resolve_stack(game)
    assert _w1g6_elementals(game) == [], game.log[-6:]
    assert game.is_on_battlefield(coils)


def test_w1g6_lightning_coils_below_five_does_nothing_and_counts_deaths(set_pool):
    """Four counters: the intervening-if is false and nothing happens (CR
    603.4). A nontoken creature its controller controls dying is the fifth
    ("Whenever a nontoken creature you control dies"), and the next upkeep
    makes five."""
    lea = set_pool("LEA")
    bears = _w1g6_nosick(_w1g6_Permanent(card=lea["Grizzly Bears"]))
    game, coils = _w1g6_coils_table(set_pool, 4, mine=[bears])
    game.start_turn(0)
    _w1g6_resolve_stack(game)
    assert _w1g6_elementals(game) == []
    assert _w1g6_counters_on(coils, "charge") == 4

    game._close_current_priority_step()
    game.players[1].hand.append(lea["Lightning Bolt"])
    assert game.queue_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g6_resolve_stack(game)
    game.check_state_based_actions()
    _w1g6_resolve_stack(game)
    assert not game.is_on_battlefield(bears)
    assert _w1g6_counters_on(coils, "charge") == 5

    game.start_turn(0)
    _w1g6_resolve_stack(game)
    assert len(_w1g6_elementals(game)) == 5
    assert _w1g6_counters_on(coils, "charge") == 0


def _w1g6_conduit_table(set_pool):
    """Power Conduit beside a Clockwork Beetle (a 0/0) holding two +1/+1
    counters and a charge counter, a counterless Leaden Myr, and the
    opponent's creature carrying a +1/+1 counter it cannot be asked to pay."""
    from engine.named_counters import add_counters

    pool = set_pool("MRD")
    conduit = _w1g6_nosick(_w1g6_Permanent(card=pool["Power Conduit"]))
    beetle = _w1g6_nosick(_w1g6_Permanent(card=pool["Clockwork Beetle"]))
    myr = _w1g6_nosick(_w1g6_Permanent(card=pool["Leaden Myr"]))
    theirs = _w1g6_nosick(_w1g6_Permanent(card=_w1g6_creature("Theirs")))
    add_counters(beetle, "+1/+1", 2)
    add_counters(beetle, "charge", 1)
    add_counters(theirs, "+1/+1", 1)
    game = _w1g6_game([conduit, beetle, myr], [theirs])
    return game, conduit, beetle, myr, theirs


def test_w1g6_power_conduit_pays_with_a_counter_of_the_kind_named(set_pool):
    """"{T}, Remove a counter from a permanent you control: Choose one — • Put a
    charge counter on target artifact. • Put a +1/+1 counter on target
    creature."

    A counter of any kind pays (CR 122.1), off any permanent its controller
    controls that holds one — the picker offers exactly those — and the kind
    named is the kind removed: a +1/+1 counter off the Beetle shrinks it
    (CR 122.1a), and the charge mode puts its counter on the target artifact;
    then the Beetle's charge counter pays for the +1/+1 mode on the Myr.
    """
    from engine.targeting import derive_activation_spec

    game, conduit, beetle, myr, theirs = _w1g6_conduit_table(set_pool)
    program = _w1g6_compile(conduit.card)
    assert program.supported, program.reason
    charge_mode, plus_mode = program.activated_abilities
    cost_spec = derive_activation_spec(charge_mode)["cost_spec"]
    assert cost_spec["remove_counter_cost"] and cost_spec["any_counter_kind"]
    from engine.subject_filters import subject_matches

    offered = [
        p.card.name for p in game.players[0].battlefield
        if subject_matches(game, p, cost_spec["filter"], observer=0, source=conduit)
    ]
    assert offered == ["Clockwork Beetle"], "only what holds a counter can pay"

    paid = game.activate_permanent_ability(
        0, "Power Conduit", ability_index=0,
        target_permanent_ids=[myr.permanent_id],
        cost_permanent_ids=[beetle.permanent_id], cost_counter_kind="+1/+1",
    )
    assert paid.supported, paid.details
    assert beetle.metadata.get("plus_counters") == 1
    assert _w1g6_counters_on(beetle, "charge") == 1
    assert (beetle.effective_power, beetle.effective_toughness) == (1, 1)
    _w1g6_resolve_stack(game)
    assert _w1g6_counters_on(myr, "charge") == 1

    conduit.tapped = False
    paid = game.activate_permanent_ability(
        0, "Power Conduit", ability_index=1,
        target_permanent_ids=[myr.permanent_id],
        cost_permanent_ids=[beetle.permanent_id], cost_counter_kind="charge",
    )
    assert paid.supported, paid.details
    assert _w1g6_counters_on(beetle, "charge") == 0
    _w1g6_resolve_stack(game)
    assert myr.metadata.get("plus_counters") == 1
    assert (myr.effective_power, myr.effective_toughness) == (2, 2)


def test_w1g6_power_conduit_refuses_a_payment_it_cannot_take(set_pool):
    """A kind the chosen permanent does not hold, a permanent the opponent
    controls, and a board holding no counter at all are each refused with
    nothing paid — the Conduit stays untapped (CR 601.2h, 733.1)."""
    game, conduit, beetle, myr, theirs = _w1g6_conduit_table(set_pool)

    for named in (
        {"cost_permanent_ids": [beetle.permanent_id], "cost_counter_kind": "fate"},
        {"cost_permanent_ids": [theirs.permanent_id]},
        {"cost_permanent_ids": [myr.permanent_id]},
    ):
        refused = game.activate_permanent_ability(
            0, "Power Conduit", ability_index=1,
            target_permanent_ids=[myr.permanent_id], **named,
        )
        assert not refused.supported, named
        assert not conduit.tapped, named
        assert beetle.metadata.get("plus_counters") == 2, named
        assert _w1g6_counters_on(beetle, "charge") == 1, named

    from engine.named_counters import remove_counters

    remove_counters(beetle, "+1/+1", 2)
    remove_counters(beetle, "charge", 1)
    assert game.unpayable_activation_cost(
        0, conduit, _w1g6_compile(conduit.card).activated_abilities[1],
    )
    refused = game.activate_permanent_ability(
        0, "Power Conduit", ability_index=1, target_permanent_ids=[myr.permanent_id],
    )
    assert not refused.supported and not conduit.tapped


def test_w1g6_power_conduit_unnamed_gives_up_the_inert_counter_first(set_pool):
    """A seat that names no kind (a headless one, or the AI): the Beetle
    holds +1/+1 counters and a charge counter, and the charge counter — which
    sizes nothing — is the one given up."""
    game, conduit, beetle, myr, theirs = _w1g6_conduit_table(set_pool)

    paid = game.activate_permanent_ability(
        0, "Power Conduit", ability_index=1, target_permanent_ids=[myr.permanent_id],
    )
    assert paid.supported, paid.details
    assert _w1g6_counters_on(beetle, "charge") == 0
    assert beetle.metadata.get("plus_counters") == 2
    assert any(
        "Clockwork Beetle gave up 1 charge counter(s)" in line for line in game.log
    ), game.log


# --- The supported-on-arrival family, driven ---------------------------------


def _w1g6_table_of(set_pool, mine=(), theirs=(), *, interactive=()):
    """Permanents by card name (MRD first, then LEA) on each side, past their
    summoning sickness, with libraries to draw from."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = _w1g6_Game(players=[
        _w1g6_PlayerState(name="P1", library=[lea["Island"]] * 20),
        _w1g6_PlayerState(name="P2", library=[lea["Island"]] * 20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    placed = []
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _w1g6_nosick(
                _w1g6_Permanent(card=mrd[name] if name in mrd else lea[name])
            )
            game.players[seat].battlefield.append(permanent)
            placed.append(permanent)
    game._sync_control()
    return game, placed


def _w1g6_fight_to_the_end_of_combat(game, attacker_seat, attackers, blocks=None):
    """Declare *attackers* for *attacker_seat* and *blocks* (``{blocker slot:
    attacker slot}``), then step out of combat — the end-of-combat step's
    delayed triggers fire as it is left."""
    game.active_player_index = attacker_seat
    game._set_phase_and_step("combat", "declare_attackers")
    slots = [_w1g6_slot(game, attacker_seat, p) for p in attackers]
    ok, why = game.declare_attackers(
        attacker_seat, slots, defending_player_index=1 - attacker_seat,
    )
    assert ok, why
    _w1g6_resolve_stack(game)
    game.advance_combat_phase()
    ok, why = game.declare_blockers(1 - attacker_seat, dict(blocks or {}))
    assert ok, why
    for _ in range(6):
        _w1g6_resolve_stack(game)
        if game.current_phase != "combat":
            break
        game.advance_combat_phase()
    _w1g6_resolve_stack(game)
    assert game.current_phase != "combat", game.current_step


def test_w1g6_altar_of_shadows_destroys_then_banks_black_mana(set_pool):
    """"{7}, {T}: Destroy target creature. Then put a charge counter on this
    artifact." / "At the beginning of your first main phase, add {B} for each
    charge counter on this artifact." The Giant dies and the Altar takes its
    counter; the next turn's first main phase holds {B}."""
    game, (altar, giant) = _w1g6_table_of(set_pool, ["Altar of Shadows"], ["Hill Giant"])
    game.start_turn(0)
    game._close_current_priority_step()

    used = game.activate_permanent_ability(
        0, "Altar of Shadows", target_permanent_ids=[giant.permanent_id],
    )
    assert used.supported, used.details
    _w1g6_resolve_stack(game)
    assert not game.is_on_battlefield(giant)
    assert _w1g6_counters_on(altar, "charge") == 1

    game.start_turn(0)
    _w1g6_resolve_stack(game)
    assert game.current_step == "precombat_main", game.current_step
    assert game.players[0].mana_pool["B"] == 1
    assert "Altar of Shadows produced {B}" in game.log


@_w1g6_pytest.mark.parametrize("interactive", [(), (0,)])
def test_w1g6_sun_droplet_banks_damage_and_pays_it_back_a_life_a_turn(
    set_pool, interactive,
):
    """"Whenever you're dealt damage, put that many charge counters on this
    artifact." / "At the beginning of each upkeep, you may remove a charge
    counter from this artifact. If you do, you gain 1 life." A Bolt is three
    counters; each upkeep — its controller's and the opponent's — trades one
    for a life, the "may" asked of an interactive seat and taken by default."""
    game, (droplet,) = _w1g6_table_of(set_pool, ["Sun Droplet"], interactive=interactive)
    game.players[1].hand.append(set_pool("LEA")["Lightning Bolt"])
    game.start_turn(1)
    game._close_current_priority_step()
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g6_resolve_stack(game)
    assert game.players[0].life == 17
    assert _w1g6_counters_on(droplet, "charge") == 3

    for seat in (0, 1):
        game.start_turn(seat)
        _w1g6_resolve_stack(game)
        if game.pending_choices:
            (asked,) = game.pending_choices
            assert asked.kind == "optional_pay"
            assert game.confirm_optional_pay(0, accept=True)
            _w1g6_resolve_stack(game)
        game._close_current_priority_step()
    assert game.players[0].life == 19
    assert _w1g6_counters_on(droplet, "charge") == 1


def test_w1g6_pentavus_trades_counters_for_pentavites_and_back(set_pool):
    """"This creature enters with five +1/+1 counters on it." / "{1}, Remove a
    +1/+1 counter from this creature: Create a 1/1 colorless Pentavite artifact
    creature token with flying." / "{1}, Sacrifice a Pentavite: Put a +1/+1
    counter on this creature." """
    pentavus_card = set_pool("MRD")["Pentavus"]
    game = _w1g6_game(hand=[pentavus_card])
    assert game.queue_from_hand(0, "Pentavus").supported
    _w1g6_resolve_stack(game)
    (pentavus,) = [p for p in game.all_permanents() if p.card.name == "Pentavus"]
    assert pentavus.metadata.get("plus_counters") == 5
    assert (pentavus.effective_power, pentavus.effective_toughness) == (5, 5)

    assert game.activate_permanent_ability(0, "Pentavus", ability_index=0).supported
    _w1g6_resolve_stack(game)
    (token,) = [p for p in game.all_permanents() if "Pentavite" in p.card.type_line]
    assert (token.effective_power, token.effective_toughness) == (1, 1)
    assert game._has_keyword(token, "flying")
    assert token.has_type("artifact")
    assert pentavus.metadata.get("plus_counters") == 4

    assert game.activate_permanent_ability(0, "Pentavus", ability_index=1).supported
    _w1g6_resolve_stack(game)
    assert not game.is_on_battlefield(token)
    assert pentavus.metadata.get("plus_counters") == 5


@_w1g6_pytest.mark.parametrize("name,counters", [
    ("Clockwork Beetle", 2), ("Clockwork Condor", 3),
    ("Clockwork Vorrac", 4), ("Clockwork Dragon", 6),
])
def test_w1g6_a_clockwork_creature_winds_down_by_one_each_combat(
    set_pool, name, counters,
):
    """"This creature enters with N +1/+1 counters on it." / "Whenever this
    creature attacks or blocks, remove a +1/+1 counter from it at end of
    combat." Cast, it enters with its N; an attack costs one counter at end of
    combat, and so does a block (against a 0/1 it survives)."""
    card = set_pool("MRD")[name]
    game = _w1g6_game(hand=[card])
    assert game.queue_from_hand(0, name).supported
    _w1g6_resolve_stack(game)
    (clockwork,) = [p for p in game.all_permanents() if p.card.name == name]
    _w1g6_nosick(clockwork)
    assert clockwork.metadata.get("plus_counters") == counters

    _w1g6_fight_to_the_end_of_combat(game, 0, [clockwork])
    assert clockwork.metadata.get("plus_counters") == counters - 1
    assert game.players[1].life == 20 - counters

    raider = _w1g6_nosick(_w1g6_Permanent(card=_w1g6_creature("Raider", 0, 1)))
    game.players[1].battlefield.append(raider)
    game._sync_control()
    clockwork.tapped = False
    _w1g6_fight_to_the_end_of_combat(
        game, 1, [raider],
        blocks={_w1g6_slot(game, 0, clockwork): _w1g6_slot(game, 1, raider)},
    )
    assert not game.is_on_battlefield(raider)
    assert clockwork.metadata.get("plus_counters") == counters - 2

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.
from engine import Game as _w1g7_Game, PlayerState as _w1g7_PlayerState
from engine.models import Permanent as _w1g7_Permanent
from tests.helpers import _nosick as _w1g7_nosick, resolve_stack as _w1g7_resolve


def _w1g7_game(set_pool, mine=(), hand=(), theirs=(), their_hand=(), interactive=(),
               library=None):
    pool = set_pool("MRD")
    other = set_pool("LEA")

    def card(name):
        return pool[name] if name in pool else other[name]

    p1 = _w1g7_PlayerState(
        name="P1",
        battlefield=[_w1g7_nosick(_w1g7_Permanent(card=card(n))) for n in mine],
        hand=[card(n) for n in hand],
        library=[card(n) for n in library] if library is not None else [other["Island"]] * 10,
    )
    p2 = _w1g7_PlayerState(
        name="P2",
        battlefield=[_w1g7_nosick(_w1g7_Permanent(card=card(n))) for n in theirs],
        hand=[card(n) for n in their_hand], library=[other["Island"]] * 10,
    )
    game = _w1g7_Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game, p1, p2


def _w1g7_settle(game):
    _w1g7_resolve(game)
    game.auto_resolve_pending_choices()
    _w1g7_resolve(game)


def _w1g7_named(player, name):
    return next(p for p in player.battlefield if p.card.name == name)


def test_w1g7_serum_tank_counts_its_own_entry_and_every_other_artifact(set_pool):
    """"Whenever this artifact **or another artifact** enters, put a charge
    counter on this artifact." The union row read "this creature or" alone, so
    the line matched nothing and the Tank shipped "supported" on its draw line
    with no way to get a counter. Its own entry counts, another artifact counts,
    an opponent's artifact counts, a nonartifact creature does not — and the
    counter pays the draw."""
    game, p1, _p2 = _w1g7_game(
        set_pool, hand=["Serum Tank", "Ornithopter", "Grizzly Bears"],
        their_hand=["Ornithopter"],
    )
    game.cast_from_hand(0, "Serum Tank")
    _w1g7_settle(game)
    tank = _w1g7_named(p1, "Serum Tank")
    assert tank.metadata.get("charge_counters") == 1
    game.cast_from_hand(0, "Ornithopter")
    _w1g7_settle(game)
    assert tank.metadata.get("charge_counters") == 2
    game.cast_from_hand(1, "Ornithopter")
    _w1g7_settle(game)
    assert tank.metadata.get("charge_counters") == 3
    game.cast_from_hand(0, "Grizzly Bears")
    _w1g7_settle(game)
    assert tank.metadata.get("charge_counters") == 3

    _w1g7_nosick(tank)
    hand_before = len(p1.hand)
    result = game.activate_permanent_ability(
        0, "Serum Tank", permanent_index=game.battlefield_index_of(tank),
    )
    assert result.supported, result.details
    _w1g7_settle(game)
    assert tank.metadata.get("charge_counters") == 2
    assert len(p1.hand) == hand_before + 1


def _w1g7_open_main(game, seat, *, before_main=None):
    """Step *seat*'s turn to its first main phase and return each pool, emptied
    first. *before_main* runs after the untap step (a tap in upkeep)."""
    for player in game.players:
        for symbol in list(player.mana_pool):
            player.mana_pool[symbol] = 0
    game.start_turn(seat)
    if before_main is not None:
        before_main()
    while game.current_turn_phase != "precombat_main":
        game.advance_phase()
    _w1g7_settle(game)
    return [
        {sym: n for sym, n in player.mana_pool.items() if n}
        for player in game.players
    ]


def test_w1g7_blinkmoth_urn_pays_each_player_for_their_own_artifacts(set_pool):
    """"At the beginning of **each player's** first main phase, if this
    artifact is untapped, **that player** adds {C} for each artifact **they**
    control." The trigger, the frozen seat and the intervening-if all shipped
    (Eladamri's Vineyard, Farsight-style "if this artifact is untapped"); the
    count behind the mana did not. The Urn counts itself for its controller,
    and the opponent's turn counts the opponent's board."""
    game, _p1, p2 = _w1g7_game(
        set_pool, mine=["Blinkmoth Urn", "Ornithopter", "Ornithopter"],
        theirs=["Ornithopter"],
    )
    assert _w1g7_open_main(game, 0) == [{"C": 3}, {}], game.log
    assert _w1g7_open_main(game, 1) == [{}, {"C": 1}], game.log
    p2.battlefield.append(_w1g7_Permanent(card=set_pool("MRD")["Ornithopter"]))
    game._settle()
    assert _w1g7_open_main(game, 1) == [{}, {"C": 2}], "counted at resolution"


def test_w1g7_blinkmoth_urn_tapped_pays_nobody(set_pool):
    """The intervening "if" (CR 603.4): tapped as the main phase begins, the
    Urn does not trigger — on the opponent's turn its controller's untap step
    has not come round."""
    game, p1, _p2 = _w1g7_game(
        set_pool, mine=["Blinkmoth Urn", "Ornithopter"], theirs=["Ornithopter"],
    )
    urn = _w1g7_named(p1, "Blinkmoth Urn")
    urn.tapped = True
    assert _w1g7_open_main(game, 1) == [{}, {}], game.log
    assert _w1g7_open_main(game, 0) == [{"C": 2}, {}], "untapped in its untap step"


def test_w1g7_blinkmoth_urn_tapped_in_response_pays_nothing(set_pool):
    """CR 603.4 asks the intervening "if" again on resolution: an Urn tapped
    while its trigger waits on the stack adds nothing."""
    game, p1, _p2 = _w1g7_game(set_pool, mine=["Blinkmoth Urn", "Ornithopter"])
    urn = _w1g7_named(p1, "Blinkmoth Urn")
    game.start_turn(0)
    while game.current_turn_phase != "precombat_main":
        game.advance_phase()
    assert any(item.card.name == "Blinkmoth Urn" for item in game.stack), game.log
    urn.tapped = True
    _w1g7_settle(game)
    assert not any(p1.mana_pool.values()), game.log

def test_w1g7_sculpting_steel_enters_as_a_copy_of_the_chosen_artifact(set_pool):
    """"You may have this artifact enter as a copy of any artifact on the
    battlefield." Clone's and Copy Artifact's sentences were two literals, and
    "this artifact … any artifact" was neither. Aimed at the opponent's Serum
    Tank over my Ornithopter, it is a Serum Tank — under my control, with the
    Tank's own entry trigger counting its arrival (CR 707.5) and the original
    Tank counting it too. The picker offers artifacts, optionally."""
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_cast_spec

    pool = set_pool("MRD")
    steel_card = pool["Sculpting Steel"]
    assert derive_cast_spec(steel_card, compile_card_oracle(steel_card)) == {
        "kind": "artifact", "optional": True,
    }

    game, p1, p2 = _w1g7_game(
        set_pool, mine=["Ornithopter"], hand=["Sculpting Steel"], theirs=["Serum Tank"],
    )
    their_tank = p2.battlefield[0]
    assert game.cast_from_hand(
        0, "Sculpting Steel", target_permanent_ids=[their_tank.permanent_id]
    ).supported
    _w1g7_settle(game)
    steel = next(p for p in p1.battlefield if p.card.name == "Sculpting Steel")
    assert steel.effective_card.name == "Serum Tank"
    assert steel.has_type("artifact") and not steel.is_creature
    assert steel.metadata.get("charge_counters") == 1, game.log
    assert their_tank.metadata.get("charge_counters") == 1, "another artifact entered"


def test_w1g7_sculpting_steel_with_nothing_to_copy_is_itself(set_pool):
    game, p1, _p2 = _w1g7_game(set_pool, hand=["Sculpting Steel", "Grizzly Bears"])
    game.cast_from_hand(0, "Grizzly Bears")
    _w1g7_settle(game)
    assert game.cast_from_hand(0, "Sculpting Steel").supported
    _w1g7_settle(game)
    steel = next(p for p in p1.battlefield if p.card.name == "Sculpting Steel")
    assert steel.effective_card.name == "Sculpting Steel", "a creature is not an artifact"

# ==== end W1G7 ======================================================
