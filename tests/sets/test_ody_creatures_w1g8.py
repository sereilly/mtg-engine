"""Odyssey creatures, W1G8's section: the ones it drove, then the ones it
implemented.

**Driven.** Every card in the first half compiled "supported" on the day of
the ingest, which is not the same as working (SET_PLAYBOOK.md Phase 3: a card
is supported when *any* of its lines is). Each was given a headless game
through its whole text — activated with a legal target, an illegal one and
none; its cost paid and refused; its trigger fired and, where something can
respond, answered — and what the game showed is pinned here. One of them did
not work: **Shifty Doppelganger** never came back. It is first.

**Implemented.** Junk Golem, Mad Dog, Savage Firecat and Whipkeeper, in the
second half, under the `_w1g8_` names they were written with.

In a file of the group's own rather than in `test_ody_creatures.py`'s W1G8
section: together the two halves are some 900 lines, and that file stood at
2,185 of 2,600 with four sections still empty. The split is along a section
boundary, which is the axis `tests/sets/README.md` names once the printed type
has run out, so every section stays whole.
"""

from __future__ import annotations

import pytest

from engine.named_counters import counters_on
from engine.oracle import compile_card_oracle
from tests.sets import ody_w1g8_helpers as w1g8


def _crack(game, name, **announcement):
    """Activate *name* (seat 0's) and settle the stack; returns the result."""
    used = game.activate_permanent_ability(0, name, **announcement)
    w1g8.settle(game)
    return used


def _table(set_pool, mana=None, **kwargs):
    """Seat 0's turn, costs enforced, *mana* floating."""
    game = w1g8.table(set_pool, enforce=True, **kwargs)
    game.start_turn(0)
    game.players[0].mana_pool.update(mana or {})
    return game


def _dies(game, permanent):
    w1g8.leave(game, permanent)
    w1g8.settle(game)


def _to_blocks(game, attacker):
    """Seat 0 attacks with *attacker*; returns at the declare-blockers step."""
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    declared, why = game.declare_attackers(
        0, [list(game.controlled_by(0)).index(attacker)]
    )
    assert declared, why
    game.advance_combat_phase()


# --- Shifty Doppelganger ----------------------------------------------------
# "{3}{U}, Exile this creature: You may put a creature card from your hand
# onto the battlefield. If you do, that creature gains haste until end of
# turn. At the beginning of the next end step, sacrifice that creature. If you
# do, return this card to the battlefield."

def test_shifty_doppelganger_comes_back_from_exile_when_its_guest_is_sacrificed(
    set_pool,
):
    """It compiled, swapped in the creature, sacrificed it at the end step —
    and stayed in exile, logging that it "was no longer in the graveyard".
    "Return this card" names no zone and the lowering read a graveyard; the
    ability's own cost says exile, and that is where it is looked for now."""
    game = _table(set_pool, {"U": 1, "C": 3}, hand=["Shivan Dragon"])
    w1g8.put(game, set_pool, 0, "Shifty Doppelganger")

    assert _crack(game, "Shifty Doppelganger").supported
    assert w1g8.names(game, 0) == ["Shivan Dragon"]
    assert w1g8.pile(game, 0, "exile") == ["Shifty Doppelganger"]
    dragon = next(iter(game.controlled_by(0)))
    assert game._has_keyword(dragon, "Haste") and not game._is_summoning_sick(dragon)

    game.resolve_end_step(0)
    w1g8.settle(game)

    assert w1g8.names(game, 0) == ["Shifty Doppelganger"]
    assert w1g8.pile(game, 0) == ["Shivan Dragon"]
    assert w1g8.pile(game, 0, "exile") == []


@pytest.mark.parametrize("guest_dies_first", [False, True])
def test_shifty_doppelganger_stays_exiled_when_nothing_is_sacrificed(
    set_pool, guest_dies_first
):
    """"If you do": with no creature card to put in, or the creature gone
    before the end step, there is no sacrifice and so no return."""
    hand = ["Shivan Dragon"] if guest_dies_first else []
    game = _table(set_pool, {"U": 1, "C": 3}, hand=hand)
    w1g8.put(game, set_pool, 0, "Shifty Doppelganger")

    assert _crack(game, "Shifty Doppelganger").supported
    if guest_dies_first:
        _dies(game, next(iter(game.controlled_by(0))))
    game.resolve_end_step(0)
    w1g8.settle(game)

    assert w1g8.names(game, 0) == []
    assert w1g8.pile(game, 0, "exile") == ["Shifty Doppelganger"]


def test_a_self_return_reads_exile_only_behind_an_exile_this_cost(set_pool):
    """The zone is the cost's to say. Nether Spirit prints the same sentence
    from a graveyard and must not start looking in exile."""
    def returns(card):
        found = []

        def walk(value):
            if hasattr(value, "kind") and hasattr(value, "payload"):
                if value.kind == "return_self_from_graveyard":
                    found.append(value.payload.get("from"))
                for inner in value.payload.values():
                    walk(inner)
            elif isinstance(value, (list, tuple)):
                for inner in value:
                    walk(inner)

        program = compile_card_oracle(card)
        for ability in (*program.activated_abilities, *program.triggered_abilities):
            walk(ability.instruction)
        return found

    assert returns(set_pool("ODY")["Shifty Doppelganger"]) == ["exile"]
    assert returns(w1g8.card(set_pool, "Nether Spirit")) == [None]


# --- sacrifice outlets and activated damage ---------------------------------

def test_ashen_firebeast_burns_every_ground_creature_itself_included(set_pool):
    game = _table(set_pool, {"R": 2, "C": 2})
    beast = w1g8.put(game, set_pool, 0, "Ashen Firebeast")
    w1g8.put(game, set_pool, 1, "Grizzly Bears")
    w1g8.put(game, set_pool, 1, "Birds of Paradise")

    assert _crack(game, "Ashen Firebeast").supported
    assert _crack(game, "Ashen Firebeast").supported

    assert w1g8.names(game, 1) == ["Birds of Paradise"], "fliers are spared"
    assert beast.damage_marked == 2
    refused = _crack(game, "Ashen Firebeast")
    assert not refused.supported and "insufficient mana" in refused.details


def test_atogatog_eats_only_atogs_and_grows_by_their_power(set_pool):
    game = _table(set_pool)
    big = w1g8.put(game, set_pool, 0, "Atogatog")
    lithatog = w1g8.put(game, set_pool, 0, "Lithatog")
    bears = w1g8.put(game, set_pool, 0, "Grizzly Bears")

    refused = _crack(game, "Atogatog", cost_permanent_ids=[bears.permanent_id])
    assert not refused.supported and game.is_on_battlefield(bears)

    assert _crack(game, "Atogatog", cost_permanent_ids=[lithatog.permanent_id]).supported
    assert w1g8.pt(big) == (6, 6), "+X/+X where X is Lithatog's power, 1"
    assert w1g8.pile(game, 0) == ["Lithatog"]


@pytest.mark.parametrize(
    "atog, fodder",
    [("Lithatog", ("Sol Ring", "Forest")), ("Thaumatog", ("Forest", "Castle"))],
)
def test_the_two_colour_atogs_take_each_food_for_its_own_ability(set_pool, atog, fodder):
    game = _table(set_pool)
    eater = w1g8.put(game, set_pool, 0, atog)
    first, second = (w1g8.put(game, set_pool, 0, name) for name in fodder)

    crossed = _crack(game, atog, ability_index=0, cost_permanent_ids=[second.permanent_id])
    assert not crossed.supported, "the first ability's food is not the second's"

    assert _crack(game, atog, ability_index=0, cost_permanent_ids=[first.permanent_id]).supported
    assert _crack(game, atog, ability_index=1, cost_permanent_ids=[second.permanent_id]).supported
    assert w1g8.pt(eater) == (3, 4)
    assert w1g8.names(game, 0) == [atog]
    empty = _crack(game, atog, ability_index=1)
    assert not empty.supported and "available to sacrifice" in empty.details


def test_barbarian_lunatic_dies_to_deal_two_to_a_creature(set_pool):
    game = _table(set_pool, {"R": 1, "C": 2})
    lunatic = w1g8.put(game, set_pool, 0, "Barbarian Lunatic")
    bears = w1g8.put(game, set_pool, 1, "Grizzly Bears")
    forest = w1g8.put(game, set_pool, 1, "Forest")

    at_a_land = _crack(game, "Barbarian Lunatic", target_permanent_ids=[forest.permanent_id])
    assert not at_a_land.supported and game.is_on_battlefield(lunatic)
    assert sum(game.players[0].mana_pool.values()) == 3, "a refusal spends nothing"

    assert _crack(game, "Barbarian Lunatic", target_permanent_ids=[bears.permanent_id]).supported
    assert w1g8.pile(game, 0) == ["Barbarian Lunatic"]
    assert w1g8.pile(game, 1) == ["Grizzly Bears"]


def test_dedicated_martyr_and_limestone_golem_trade_themselves_in(set_pool):
    game = _table(set_pool, {"W": 1})
    w1g8.put(game, set_pool, 0, "Dedicated Martyr")
    assert _crack(game, "Dedicated Martyr").supported
    assert game.players[0].life == 23 and w1g8.pile(game, 0) == ["Dedicated Martyr"]

    for seat in (0, 1):
        game = _table(set_pool, {"C": 2})
        w1g8.put(game, set_pool, 0, "Limestone Golem")
        before = len(game.players[seat].hand)
        assert _crack(game, "Limestone Golem", target_player_index=seat).supported
        assert len(game.players[seat].hand) == before + 1, "the *targeted* player draws"


def test_druid_lyrist_needs_an_enchantment_and_an_untapped_self(set_pool):
    game = _table(set_pool, {"G": 1})
    lyrist = w1g8.put(game, set_pool, 0, "Druid Lyrist")
    castle = w1g8.put(game, set_pool, 1, "Castle")
    bears = w1g8.put(game, set_pool, 1, "Grizzly Bears")

    assert not _crack(game, "Druid Lyrist", target_permanent_ids=[bears.permanent_id]).supported
    lyrist.metadata["summoning_sickness_turn"] = game.turn
    sick = _crack(game, "Druid Lyrist", target_permanent_ids=[castle.permanent_id])
    assert not sick.supported and "summoning sickness" in sick.details

    lyrist.metadata["summoning_sickness_turn"] = -99
    assert _crack(game, "Druid Lyrist", target_permanent_ids=[castle.permanent_id]).supported
    assert w1g8.names(game, 1) == ["Grizzly Bears"]
    assert w1g8.pile(game, 0) == ["Druid Lyrist"]


def test_cephalid_scout_turns_a_land_into_a_card(set_pool):
    game = _table(set_pool, {"U": 2, "C": 4})
    w1g8.put(game, set_pool, 0, "Cephalid Scout")
    island = w1g8.put(game, set_pool, 0, "Island")
    before = len(game.players[0].hand)

    assert _crack(game, "Cephalid Scout", cost_permanent_ids=[island.permanent_id]).supported
    assert len(game.players[0].hand) == before + 1
    assert w1g8.names(game, 0) == ["Cephalid Scout"]

    without = _crack(game, "Cephalid Scout")
    assert not without.supported and "no land available" in without.details
    assert sum(game.players[0].mana_pool.values()) == 3


def test_kamahl_pit_fighter_shoots_the_turn_he_arrives(set_pool):
    game = _table(set_pool, hand=["Kamahl, Pit Fighter"])
    game.enforce_mana_costs = False
    bears = w1g8.put(game, set_pool, 1, "Grizzly Bears")
    assert game.cast_from_hand(0, "Kamahl, Pit Fighter").supported
    w1g8.settle(game)
    kamahl = next(iter(game.controlled_by(0)))

    assert _crack(game, "Kamahl, Pit Fighter", target_player_index=1).supported, "haste"
    assert game.players[1].life == 17 and kamahl.tapped
    again = _crack(game, "Kamahl, Pit Fighter", target_permanent_ids=[bears.permanent_id])
    assert not again.supported and "already tapped" in again.details


def test_vampiric_dragon_feeds_on_what_it_damaged_this_turn(set_pool):
    game = _table(set_pool, {"R": 2, "C": 2})
    dragon = w1g8.put(game, set_pool, 0, "Vampiric Dragon")
    elves = w1g8.put(game, set_pool, 1, "Llanowar Elves")
    bears = w1g8.put(game, set_pool, 1, "Grizzly Bears")
    bystander = w1g8.put(game, set_pool, 1, "Hill Giant")

    assert _crack(game, "Vampiric Dragon", target_permanent_ids=[elves.permanent_id]).supported
    assert w1g8.pt(dragon) == (6, 6), "the Elves it pinged died"

    assert _crack(game, "Vampiric Dragon", target_permanent_ids=[bears.permanent_id]).supported
    assert w1g8.pt(dragon) == (6, 6) and bears.damage_marked == 1
    _dies(game, bears)
    assert w1g8.pt(dragon) == (7, 7), "damaged by it this turn, died another way"

    _dies(game, bystander)
    assert w1g8.pt(dragon) == (7, 7), "a creature it never touched"


def test_twigwalker_needs_two_different_creatures(set_pool):
    game = _table(set_pool, {"G": 1, "C": 1})
    walker = w1g8.put(game, set_pool, 0, "Twigwalker")
    bears = w1g8.put(game, set_pool, 0, "Grizzly Bears")
    giant = w1g8.put(game, set_pool, 1, "Hill Giant")

    one = _crack(game, "Twigwalker", target_permanent_ids=[bears.permanent_id])
    twice = _crack(
        game, "Twigwalker",
        target_permanent_ids=[bears.permanent_id, bears.permanent_id],
    )
    assert not one.supported and not twice.supported
    assert game.is_on_battlefield(walker)
    assert sum(game.players[0].mana_pool.values()) == 2

    assert _crack(
        game, "Twigwalker",
        target_permanent_ids=[bears.permanent_id, giant.permanent_id],
    ).supported
    assert w1g8.pt(bears) == (4, 4) and w1g8.pt(giant) == (5, 5)


def test_ivy_elemental_is_as_big_as_its_x_and_halberdier_strikes_first(set_pool):
    game = _table(set_pool, {"R": 1, "C": 3, "G": 4}, hand=["Halberdier", "Ivy Elemental"])
    assert game.cast_from_hand(0, "Halberdier").supported
    assert game.cast_from_hand(0, "Ivy Elemental", x_value=3).supported
    w1g8.settle(game)
    by_name = {permanent.card.name: permanent for permanent in game.controlled_by(0)}

    assert game._has_keyword(by_name["Halberdier"], "First strike")
    assert w1g8.pt(by_name["Ivy Elemental"]) == (3, 3)
    assert not any(game.players[0].mana_pool.values()), "{3}{R} and {3}{G}"

    game = _table(set_pool, {"G": 1}, hand=["Ivy Elemental"])
    assert game.cast_from_hand(0, "Ivy Elemental", x_value=0).supported
    w1g8.settle(game)
    assert w1g8.pile(game, 0) == ["Ivy Elemental"], "a 0/0"


# --- triggers ---------------------------------------------------------------

def test_aven_cloudchaser_must_destroy_an_enchantment_even_its_own(set_pool):
    game = _table(set_pool, hand=["Aven Cloudchaser"])
    game.enforce_mana_costs = False
    w1g8.put(game, set_pool, 0, "Crusade")

    assert game.cast_from_hand(0, "Aven Cloudchaser").supported
    w1g8.settle(game)

    assert w1g8.names(game, 0) == ["Aven Cloudchaser"], "no \"may\" on the trigger"


def test_braids_makes_each_player_feed_her_on_their_own_upkeep(set_pool):
    game = w1g8.table(set_pool, interactive=(1,))
    w1g8.put(game, set_pool, 0, "Braids, Cabal Minion")
    w1g8.put(game, set_pool, 0, "Forest")
    forest = w1g8.put(game, set_pool, 1, "Forest")
    w1g8.put(game, set_pool, 1, "Castle")
    bears = w1g8.put(game, set_pool, 1, "Grizzly Bears")

    game.active_player_index = 1
    game.resolve_upkeep(1)
    game.resolve_top_of_stack(pause_for_choices=True)
    assert w1g8.owed(game) == [("sacrifice", 1)], "that player chooses, not Braids' controller"
    offered = game.pending_choices[0].data["filter"]["type_filter"]
    assert offered == ["artifact", "creature", "land"], "an enchantment will not do"
    w1g8.settle(game)
    assert len(list(game.controlled_by(1))) == 2 and "Castle" in w1g8.names(game, 1)

    w1g8.upkeep(game, 0)
    assert w1g8.names(game, 0) == ["Braids, Cabal Minion"], "her own controller feeds her too"


def test_filthy_cur_passes_its_damage_on_as_life_loss(set_pool):
    game = w1g8.table(set_pool, hand=["Lightning Bolt"])
    cur = w1g8.put(game, set_pool, 1, "Filthy Cur")
    game.start_turn(0)

    assert game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[cur.permanent_id]
    ).supported
    w1g8.settle(game)

    assert game.players[1].life == 17, "its controller lost that much life"
    assert w1g8.pile(game, 1) == ["Filthy Cur"]


def test_soulcatcher_grows_when_a_flier_dies_and_only_then(set_pool):
    game = _table(set_pool)
    catcher = w1g8.put(game, set_pool, 0, "Soulcatcher")
    bears = w1g8.put(game, set_pool, 1, "Grizzly Bears")
    bird = w1g8.put(game, set_pool, 1, "Birds of Paradise")

    _dies(game, bears)
    assert w1g8.pt(catcher) == (1, 1)
    _dies(game, bird)
    assert w1g8.pt(catcher) == (2, 2)


def test_shadowmage_infiltrator_is_feared_and_draws_on_a_hit(set_pool):
    game = w1g8.table(set_pool, interactive=(0,))
    mage = w1g8.put(game, set_pool, 0, "Shadowmage Infiltrator")
    bears = w1g8.put(game, set_pool, 1, "Grizzly Bears")
    game.start_turn(0)
    _to_blocks(game, mage)

    blocked, why = game.declare_blockers(1, {list(game.controlled_by(1)).index(bears): 0})
    assert not blocked and "cannot block" in why, "fear: not black, not an artifact"
    assert game.declare_blockers(1, {})[0]
    hand = len(game.players[0].hand)
    game.advance_combat_phase()
    assert game.players[1].life == 19
    game.resolve_top_of_stack(pause_for_choices=True)
    assert w1g8.owed(game) == [("optional_pay", 0)], "\"you may draw\""
    assert game.confirm_optional_pay(0, accept=True)
    w1g8.settle(game)
    assert len(game.players[0].hand) == hand + 1


def test_spark_mage_may_ping_a_creature_of_the_player_it_hit(set_pool):
    game = w1g8.table(set_pool, interactive=(0,))
    mage = w1g8.put(game, set_pool, 0, "Spark Mage")
    w1g8.put(game, set_pool, 0, "Birds of Paradise")
    elves = w1g8.put(game, set_pool, 1, "Llanowar Elves")
    game.start_turn(0)
    _to_blocks(game, mage)
    assert game.declare_blockers(1, {})[0]
    game.advance_combat_phase()

    assert w1g8.owed(game) == [("trigger_target", 0)]
    offered = [target["name"] for target in game.pending_choices[0].data["targets"]]
    assert offered == ["Llanowar Elves"], "that player's creatures, not the Mage's own side"
    assert game.resolve_pending_choice("trigger_target", 0, permanent_id=elves.permanent_id)
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_optional_pay(0, accept=True)
    w1g8.settle(game)
    assert w1g8.pile(game, 1) == ["Llanowar Elves"]


def test_spark_mage_with_nothing_to_ping_has_no_trigger_on_the_stack(set_pool):
    game = w1g8.table(set_pool)
    mage = w1g8.put(game, set_pool, 0, "Spark Mage")
    game.start_turn(0)
    _to_blocks(game, mage)
    assert game.declare_blockers(1, {})[0]
    game.advance_combat_phase()

    assert game.players[1].life == 19 and not game.stack
    assert any("no legal target (603.3d)" in line for line in game.log)


# --- Mine Layer and Patron Wizard -------------------------------------------

def _mined(set_pool):
    game = _table(set_pool, {"R": 1, "C": 1})
    layer = w1g8.put(game, set_pool, 0, "Mine Layer")
    forest = w1g8.put(game, set_pool, 1, "Forest")
    assert _crack(game, "Mine Layer", target_permanent_ids=[forest.permanent_id]).supported
    assert counters_on(forest, "mine") == 1 and layer.tapped
    return game, layer, forest


@pytest.mark.parametrize("for_mana", [True, False])
def test_mine_layer_destroys_a_mined_land_however_it_becomes_tapped(set_pool, for_mana):
    game, layer, forest = _mined(set_pool)

    if for_mana:
        assert game.tap_land_for_mana(1, "Forest", permanent_id=forest.permanent_id)
        assert game.players[1].mana_pool["G"] == 1, "the mana is made first"
    else:
        game.become_tapped(forest)
    assert [item.card.name for item in game.stack] == ["Mine Layer"]
    w1g8.settle(game)

    assert w1g8.pile(game, 1) == ["Forest"]


def test_mine_layer_leaving_takes_every_mine_with_it(set_pool):
    game, layer, forest = _mined(set_pool)

    _dies(game, layer)
    assert counters_on(forest, "mine") == 0
    assert game.tap_land_for_mana(1, "Forest", permanent_id=forest.permanent_id)
    w1g8.settle(game)
    assert game.is_on_battlefield(forest)


def test_mine_layer_mines_lands_only(set_pool):
    game = _table(set_pool, {"R": 1, "C": 1})
    w1g8.put(game, set_pool, 0, "Mine Layer")
    bears = w1g8.put(game, set_pool, 1, "Grizzly Bears")

    assert not _crack(game, "Mine Layer", target_permanent_ids=[bears.permanent_id]).supported


def _patron(set_pool, opposing_land):
    """Seat 1's Bolt on the stack, aimed at seat 0, who holds Patron Wizard."""
    game = w1g8.table(set_pool, their_hand=["Lightning Bolt"], enforce=True)
    patron = w1g8.put(game, set_pool, 0, "Patron Wizard")
    if opposing_land:
        w1g8.put(game, set_pool, 1, "Island")
    game.start_turn(1)
    game.players[1].mana_pool["R"] = 1
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    return game, patron


def test_patron_wizard_taps_wizards_and_nothing_else_to_tax_a_spell(set_pool):
    game, patron = _patron(set_pool, opposing_land=True)
    sorcerer = w1g8.put(game, set_pool, 0, "Prodigal Sorcerer")
    bears = w1g8.put(game, set_pool, 0, "Grizzly Bears")

    not_a_wizard = game.activate_permanent_ability(
        0, "Patron Wizard", target_stack_index=0, cost_permanent_ids=[bears.permanent_id]
    )
    assert not not_a_wizard.supported and not bears.tapped

    assert _crack(
        game, "Patron Wizard", target_stack_index=0,
        cost_permanent_ids=[sorcerer.permanent_id],
    ).supported
    assert sorcerer.tapped and not patron.tapped, "any Wizard pays, not only the Patron"
    assert game.players[0].life == 17, "the Bolt's controller had {1} and paid it"


def test_patron_wizard_may_tap_itself_the_turn_it_arrives(set_pool):
    """The cost is "tap an untapped Wizard", not {T}: CR 302.6 restricts only
    the tap symbol, so a summoning-sick Patron can pay with itself."""
    game, patron = _patron(set_pool, opposing_land=False)
    patron.metadata["summoning_sickness_turn"] = game.turn

    assert _crack(
        game, "Patron Wizard", target_stack_index=0,
        cost_permanent_ids=[patron.permanent_id],
    ).supported
    assert patron.tapped
    assert game.players[0].life == 20, "nothing to pay with: the Bolt is countered"
    assert w1g8.pile(game, 1) == ["Lightning Bolt"]
    assert not _crack(game, "Patron Wizard").supported, "an empty stack"


# ============================================================================
# The creatures the group implemented.
# ============================================================================
import pytest as _w1g8_pytest

from engine.oracle import compile_card_oracle as _w1g8_compile
from tests.sets import ody_w1g8_helpers as _w1g8


# --- Junk Golem -------------------------------------------------------------
# "At the beginning of your upkeep, sacrifice this creature unless you remove a
# +1/+1 counter from it." The toll's seventh currency: the removal is the
# offer's action, so the `may` every "unless" already is asks for it and the
# takeability gate decides whether there is anything to ask about.

def test_w1g8_junk_golem_pays_a_counter_each_upkeep_until_it_has_none(set_pool):
    game = _w1g8.table(set_pool)
    golem = _w1g8.put(game, set_pool, 0, "Junk Golem")
    assert _w1g8.pt(golem) == (3, 3), "enters with three +1/+1 counters"

    sizes = []
    for _ in range(3):
        _w1g8.upkeep(game)
        sizes.append(_w1g8.pt(golem) if game.is_on_battlefield(golem) else None)

    # The third counter leaves a 0/0, which state-based actions take.
    assert sizes == [(2, 2), (1, 1), None]
    assert _w1g8.pile(game, 0) == ["Junk Golem"]


@_w1g8_pytest.mark.parametrize("accept, left", [(True, (2, 2)), (False, None)])
def test_w1g8_junk_golem_asks_its_controller_and_obeys_the_answer(
    set_pool, accept, left
):
    game = _w1g8.table(set_pool, interactive=(0,))
    golem = _w1g8.put(game, set_pool, 0, "Junk Golem")
    game.active_player_index = 0
    game.resolve_upkeep(0)

    assert _w1g8.owed(game) == [("optional_pay", 0)]
    assert game.stack, "the ability waits on the stack for its answer (CR 608.2)"
    assert game.confirm_optional_pay(0, accept=accept)
    _w1g8.settle(game)

    if left is None:
        assert _w1g8.pile(game, 0) == ["Junk Golem"]
        assert "Junk Golem was sacrificed" in game.log
    else:
        assert _w1g8.pt(golem) == left


def test_w1g8_junk_golem_with_no_counter_is_not_offered_the_price(set_pool):
    """Kept alive at no counters by an anthem, the Golem has nothing to pay
    with: no prompt, and the sacrifice stands (CR 118.12a — the "unless" is an
    offer, and an action nobody can take is not offered)."""
    game = _w1g8.table(set_pool, interactive=(0,))
    golem = _w1g8.put(game, set_pool, 0, "Junk Golem")
    _w1g8.put(game, set_pool, 0, "Glorious Anthem")
    for _ in range(3):
        game.active_player_index = 0
        game.resolve_upkeep(0)
        assert game.confirm_optional_pay(0, accept=True)
        _w1g8.settle(game)
    assert _w1g8.pt(golem) == (1, 1), "the anthem alone"

    game.resolve_upkeep(0)
    assert _w1g8.owed(game) == []
    _w1g8.settle(game)

    assert _w1g8.names(game, 0) == ["Glorious Anthem"]
    assert _w1g8.pile(game, 0) == ["Junk Golem"]


def test_w1g8_junk_golem_gone_in_response_is_asked_nothing(set_pool):
    """Counters are not retained across a zone change (CR 122.2), so a Golem
    destroyed with its trigger on the stack has none to remove: nobody is
    asked, and there is nothing left to sacrifice."""
    game = _w1g8.table(set_pool, interactive=(0,))
    golem = _w1g8.put(game, set_pool, 0, "Junk Golem")
    game.active_player_index = 0
    game.resolve_upkeep(0, defer_priority=True)
    assert [item.card.name for item in game.stack] == ["Junk Golem"]

    _w1g8.leave(game, golem)
    _w1g8.settle(game)

    assert _w1g8.owed(game) == []
    assert not any("Removed a +1/+1 counter" in line for line in game.log)


def test_w1g8_junk_golem_grows_for_one_mana_and_a_card_and_is_refused_without(
    set_pool,
):
    game = _w1g8.table(set_pool, hand=["Forest"], enforce=True)
    golem = _w1g8.put(game, set_pool, 0, "Junk Golem")
    game.players[0].mana_pool["C"] = 2

    used = game.activate_permanent_ability(0, "Junk Golem")
    _w1g8.settle(game)
    assert used.supported, used.details
    assert _w1g8.pt(golem) == (4, 4)
    assert _w1g8.pile(game, 0) == ["Forest"] and not game.players[0].hand

    refused = game.activate_permanent_ability(0, "Junk Golem")
    assert not refused.supported and "discard" in refused.details
    assert game.players[0].mana_pool["C"] == 1, "a refused activation spends nothing"
    assert _w1g8.pt(golem) == (4, 4)


@_w1g8_pytest.mark.parametrize(
    "price",
    [
        "remove all +1/+1 counters from it",        # a quantity nobody asks "can you?" of
        "remove a +1/+1 counter from target creature",  # a target is not a price
        "remove two +1/+1 counters from it",        # one handler, one counter
    ],
)
def test_w1g8_a_counter_removal_price_is_one_counter_off_the_source(price):
    """The refusing gate's refusal test: a price the offer cannot ask about is
    refused whole, never read as "remove one from this"."""
    from tests.helpers import _mk_card

    probe = _mk_card(
        "Probe Golem", "Artifact Creature — Golem",
        f"At the beginning of your upkeep, sacrifice this creature unless you {price}.",
    )
    assert not _w1g8_compile(probe).supported


# --- Mad Dog ----------------------------------------------------------------
# "At the beginning of your end step, if this creature didn't attack or come
# under your control this turn, sacrifice it." One negation over two records
# of the turn: an intervening-if (CR 603.4), so on a turn it attacked or
# arrived the ability does not trigger at all.

def _w1g8_end_step(game, seat):
    """*seat*'s end step, settled; returns the lines it logged."""
    before = len(game.log)
    game.resolve_end_step(seat)
    _w1g8.settle(game)
    return game.log[before:]


def _w1g8_next_turn(game, seat):
    game.turn += 1
    game.start_turn(seat)


def test_w1g8_mad_dog_stays_the_turn_it_arrives_and_dies_the_turn_it_idles(set_pool):
    game = _w1g8.table(set_pool, hand=["Mad Dog"])
    _w1g8_next_turn(game, 0)
    assert game.cast_from_hand(0, "Mad Dog").supported

    assert not any("Mad Dog" in line for line in _w1g8_end_step(game, 0)), (
        "it came under your control this turn, so nothing triggered"
    )
    _w1g8_next_turn(game, 1)
    _w1g8_end_step(game, 1)
    assert _w1g8.names(game, 0) == ["Mad Dog"], "an opponent's end step is not yours"

    _w1g8_next_turn(game, 0)
    assert "Mad Dog was sacrificed" in _w1g8_end_step(game, 0)
    assert _w1g8.pile(game, 0) == ["Mad Dog"]


def test_w1g8_mad_dog_that_attacked_is_kept(set_pool):
    game = _w1g8.table(set_pool)
    dog = _w1g8.put(game, set_pool, 0, "Mad Dog")
    _w1g8_next_turn(game, 0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    declared, why = game.declare_attackers(0, [0])
    assert declared, why

    assert not any("Mad Dog" in line for line in _w1g8_end_step(game, 0))
    assert game.is_on_battlefield(dog)


def test_w1g8_mad_dog_changing_hands_is_coming_under_control(set_pool):
    """Erg Raiders' 2018-03-16 ruling: a creature "comes under your control"
    if it enters under your control *or* you gain control of it while it is
    already on the battlefield. The thief keeps the Dog that turn and loses it
    the next one it sits out."""
    from engine.control import change_control

    game = _w1g8.table(set_pool)
    dog = _w1g8.put(game, set_pool, 0, "Mad Dog")
    _w1g8_next_turn(game, 0)
    _w1g8_next_turn(game, 1)
    change_control(dog, 1, source="a test's theft")
    game._sync_control()

    assert not any("Mad Dog" in line for line in _w1g8_end_step(game, 1))
    _w1g8_next_turn(game, 0)
    _w1g8_end_step(game, 0)
    assert _w1g8.names(game, 1) == ["Mad Dog"], "its old controller's end step is not 'yours'"

    _w1g8_next_turn(game, 1)
    assert "Mad Dog was sacrificed" in _w1g8_end_step(game, 1)
    assert _w1g8.pile(game, 0) == ["Mad Dog"], "to its owner's graveyard"


def test_w1g8_came_under_control_this_turn_is_only_read_on_your_own_turn():
    """The refusing gate's refusal test. The record is CR 302.6's, carried
    across other players' turns, so under "each end step" it could not tell
    this turn from the last one — the clause refuses there instead."""
    from tests.helpers import _mk_card

    def dog(step):
        return _mk_card(
            "Probe Dog", "Creature — Dog",
            f"At the beginning of {step}, if this creature didn't attack or "
            "come under your control this turn, sacrifice it.",
        )

    assert _w1g8_compile(dog("your end step")).supported
    assert not _w1g8_compile(dog("each end step")).supported


# --- Savage Firecat ---------------------------------------------------------
# "Whenever you tap a land for mana, remove a +1/+1 counter from this
# creature." The third seat the tap-for-mana event prints ("a player", "an
# opponent", "you"), narrowed at the tap seam against the Firecat's controller.
#
# Like every non-mana trigger under this event the removal is resolved at the
# tap seam rather than put on the stack (Manabarbs' convention; CR 603.3 and
# Manabarbs' own 2009-10-01 ruling say stack — measured and reported, not
# changed here: it is seven shipped cards' behaviour, not this one's).

def _w1g8_tap(game, seat, land):
    return game.tap_land_for_mana(seat, land.card.name, permanent_id=land.permanent_id)


def test_w1g8_savage_firecat_loses_a_counter_for_each_land_its_controller_taps(set_pool):
    game = _w1g8.table(set_pool)
    cat = _w1g8.put(game, set_pool, 0, "Savage Firecat")
    mine = [_w1g8.put(game, set_pool, 0, "Mountain") for _ in range(3)]
    theirs = _w1g8.put(game, set_pool, 1, "Forest")
    game.start_turn(0)
    assert _w1g8.pt(cat) == (7, 7), "a 0/0 with seven +1/+1 counters"

    assert _w1g8_tap(game, 0, mine[0]) and _w1g8_tap(game, 0, mine[1])
    assert _w1g8.pt(cat) == (5, 5)
    assert game.players[0].mana_pool["R"] == 2, "the mana is still made"

    assert _w1g8_tap(game, 1, theirs)
    assert _w1g8.pt(cat) == (5, 5), "\"you\" is the Firecat's controller, not any player"

    game.become_tapped(mine[2])
    assert _w1g8.pt(cat) == (5, 5), "tapped, but not for mana"


def test_w1g8_savage_firecat_follows_its_controller(set_pool):
    """CR 109.5: "you" is whoever controls the Firecat now. Stolen, it counts
    the thief's taps and stops counting its owner's."""
    from engine.control import change_control

    game = _w1g8.table(set_pool)
    cat = _w1g8.put(game, set_pool, 0, "Savage Firecat")
    mine = _w1g8.put(game, set_pool, 0, "Mountain")
    theirs = _w1g8.put(game, set_pool, 1, "Forest")
    game.start_turn(0)
    change_control(cat, 1, source="a test's theft")
    game._sync_control()

    assert _w1g8_tap(game, 0, mine)
    assert _w1g8.pt(cat) == (7, 7)
    assert _w1g8_tap(game, 1, theirs)
    assert _w1g8.pt(cat) == (6, 6)


def test_w1g8_savage_firecat_tapped_down_to_nothing_dies(set_pool):
    game = _w1g8.table(set_pool)
    cat = _w1g8.put(game, set_pool, 0, "Savage Firecat")
    lands = [_w1g8.put(game, set_pool, 0, "Mountain") for _ in range(8)]
    game.start_turn(0)

    for land in lands[:7]:
        assert _w1g8_tap(game, 0, land)
    game.check_state_based_actions()
    assert _w1g8.pile(game, 0) == ["Savage Firecat"]
    assert _w1g8_tap(game, 0, lands[7]), "with the Firecat gone a land is just a land"


# --- Whipkeeper -------------------------------------------------------------
# "{T}: This creature deals damage to target creature equal to the damage
# already dealt to it this turn." A history of the *target*, read off the
# turn's damage ledger. The card's two 2004-10-04 rulings are the reading:
# damage a regeneration wiped still counts, and prevented damage never does —
# so it is not the damage marked on the creature.

def _w1g8_whip(set_pool, victim="Shivan Dragon", hand=("Lightning Bolt",)):
    game = _w1g8.table(set_pool, hand=list(hand))
    whip = _w1g8.put(game, set_pool, 0, "Whipkeeper")
    creature = _w1g8.put(game, set_pool, 1, victim)
    game.start_turn(0)
    return game, whip, creature


def _w1g8_crack(game, creature):
    used = game.activate_permanent_ability(
        0, "Whipkeeper", target_permanent_ids=[creature.permanent_id]
    )
    assert used.supported, used.details
    _w1g8.settle(game)


def test_w1g8_whipkeeper_doubles_the_damage_a_creature_has_taken_this_turn(set_pool):
    game, whip, dragon = _w1g8_whip(set_pool)
    assert game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[dragon.permanent_id]
    ).supported
    assert dragon.damage_marked == 3

    _w1g8_crack(game, dragon)

    assert whip.tapped
    assert _w1g8.pile(game, 1) == ["Shivan Dragon"], "3 + 3 on a 5/5"


def test_w1g8_whipkeeper_deals_nothing_to_an_unhurt_creature(set_pool):
    game, whip, dragon = _w1g8_whip(set_pool)

    _w1g8_crack(game, dragon)

    assert dragon.damage_marked == 0 and game.is_on_battlefield(dragon)


def test_w1g8_whipkeeper_counts_damage_a_regeneration_wiped_and_not_prevented_damage(
    set_pool,
):
    """Both rulings at once. The Bolt's 3 is cut to 2 by a prevention shield
    (so 2 was *dealt*), then the marked damage is wiped as a regeneration
    would wipe it (CR 120.6): the history is still 2."""
    game, whip, dragon = _w1g8_whip(set_pool)
    _w1g8.put(game, set_pool, 1, "Samite Healer")
    shield = game.activate_permanent_ability(
        1, "Samite Healer", target_permanent_ids=[dragon.permanent_id]
    )
    assert shield.supported, shield.details
    _w1g8.settle(game)
    assert game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[dragon.permanent_id]
    ).supported
    assert dragon.damage_marked == 2, "one of the three was prevented"
    dragon.damage_marked = 0

    _w1g8_crack(game, dragon)

    assert dragon.damage_marked == 2


def test_w1g8_whipkeeper_reads_this_turn_only_and_needs_a_creature(set_pool):
    game, whip, dragon = _w1g8_whip(set_pool)
    forest = _w1g8.put(game, set_pool, 1, "Forest")
    assert game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[dragon.permanent_id]
    ).supported

    at_a_land = game.activate_permanent_ability(
        0, "Whipkeeper", target_permanent_ids=[forest.permanent_id]
    )
    assert not at_a_land.supported and not whip.tapped

    game.turn += 1
    game.start_turn(1)
    game.turn += 1
    game.start_turn(0)
    dragon.damage_marked = 0
    _w1g8_crack(game, dragon)
    assert dragon.damage_marked == 0, "last turn's damage is not this turn's"


def test_w1g8_a_damage_history_amount_needs_the_one_creature_it_is_about():
    """The refusing gate's refusal test: "it" is the sentence's own target,
    so a sweep or a player has no history for the clause to read."""
    from tests.helpers import _mk_card

    def keeper(recipient):
        return _mk_card(
            "Probe Keeper", "Creature — Dwarf",
            f"{{T}}: This creature deals damage to {recipient} equal to the "
            "damage already dealt to it this turn.",
        )

    assert _w1g8_compile(keeper("target creature")).supported
    assert not _w1g8_compile(keeper("each creature")).supported
    assert not _w1g8_compile(keeper("target player")).supported
