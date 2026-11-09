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

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

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
