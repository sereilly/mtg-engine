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


def test_w1g1_banshees_blade_does_not_charge_when_its_creature_deals_no_damage(set_pool):
    """A blocked creature whose blocker is removed deals no combat damage
    (CR 510.1c) — no counter. Here: the equipped creature does not attack at
    all, and an unequipped attacker's damage is not the Blade's event."""
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
    # Ownership never moved (CR 400.3): it is still the opponent's card.
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
    """The trigger exists apart from its source (CR 113.7a): the Scythe is
    destroyed while its trigger waits, the dead creature still comes back
    under the Scythe controller's control, and there is nothing to attach."""
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
