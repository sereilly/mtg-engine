"""Regression tests for the ninth batch of cards reported FAILED in-game.

Each test documents a bug reported through the in-game Debug Menu verification
flow (recorded in CARD_VERIFICATION.md) and guards the rules-correct behavior
after the fix. Tests load the real Alpha (LEA) card definitions so they exercise
the actual oracle text, parse rules, handlers, continuous-effect logic, and the
backend legality/targeting queries the web UI relies on.

Clusters covered in this batch:
- Helm of Chatzuk grants banding to the *chosen* target creature (not the
  controller's first creature).
- Stone Giant's activated ability enumerates only legal targets (a creature you
  control with toughness less than Stone Giant's power).
- Rock Hydra's {R} prevention ability is usable any time; only its {R}{R}{R}
  pump is restricted to the controller's upkeep.
- A Lured attacker is treated as forced by the AI so the defender still gets a
  declare-blockers step.
- Verduran Enchantress's "you may draw a card" is an optional yes/no prompt.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import random

from engine import Game, PlayerState, load_cards
from engine.models import Permanent
from engine.ai_policy import choose_attackers
from engine.oracle import compile_card_oracle


_ROOT = Path(__file__).resolve().parent.parent
_C = {c.name: c for c in load_cards(_ROOT / "lea_cards.json")}


@pytest.fixture(scope="module")
def cards():
    return _C


def _game(p1: PlayerState, p2: PlayerState) -> Game:
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game


# ---------------------------------------------------------------------------
# Helm of Chatzuk — "Doesn't give banding to the target creature." The handler
# granted banding to the controller's first creature instead of the chosen one.
# ---------------------------------------------------------------------------

class TestHelmOfChatzuk:
    def test_grants_banding_to_chosen_opponent_creature(self, cards):
        helm = Permanent(card=cards["Helm of Chatzuk"])
        my_creature = Permanent(card=cards["Grizzly Bears"])
        their_creature = Permanent(card=cards["Hill Giant"])
        p1 = PlayerState(name="P1", battlefield=[helm, my_creature])
        p2 = PlayerState(name="P2", battlefield=[their_creature])
        game = _game(p1, p2)
        result = game.activate_permanent_ability(
            0, "Helm of Chatzuk", permanent_index=0,
            target_player_index=1, target_permanent_index=0,
        )
        assert result.supported
        assert their_creature.metadata.get("gains_banding_until_eot") is True
        # The controller's own creature was NOT the one that gained banding.
        assert not my_creature.metadata.get("gains_banding_until_eot")
        assert game._creature_has_banding(their_creature)

    def test_grants_banding_to_chosen_own_creature(self, cards):
        helm = Permanent(card=cards["Helm of Chatzuk"])
        bear = Permanent(card=cards["Grizzly Bears"])
        ogre = Permanent(card=cards["Gray Ogre"])
        p1 = PlayerState(name="P1", battlefield=[helm, bear, ogre])
        game = _game(p1, PlayerState(name="P2"))
        game.activate_permanent_ability(
            0, "Helm of Chatzuk", permanent_index=0,
            target_player_index=0, target_permanent_index=2,
        )
        assert ogre.metadata.get("gains_banding_until_eot") is True
        assert not bear.metadata.get("gains_banding_until_eot")


# ---------------------------------------------------------------------------
# Stone Giant — "I should not be able to select invalid targets." Its ability
# targets a creature you control with toughness less than its power.
# ---------------------------------------------------------------------------

class TestStoneGiantTargeting:
    def test_enumerates_only_legal_low_toughness_own_creatures(self, cards):
        giant = Permanent(card=cards["Stone Giant"])          # 3/4, source
        giant.metadata["summoning_sickness_turn"] = -99
        my_bear = Permanent(card=cards["Grizzly Bears"])       # 2/2  -> legal (T2 < P3)
        my_hill = Permanent(card=cards["Hill Giant"])          # 3/3  -> illegal (T3 !< P3)
        their_bear = Permanent(card=cards["Grizzly Bears"])    # not "you control" -> illegal
        p1 = PlayerState(name="P1", battlefield=[giant, my_bear, my_hill])
        p2 = PlayerState(name="P2", battlefield=[their_bear])
        game = _game(p1, p2)
        spec = game.activation_target_spec(0, 0)
        assert spec["kind"] == "creature" and spec["requires_target"]
        keys = {(t["seat"], t["index"]) for t in spec["valid_targets"]}
        assert keys == {(0, 1)}  # only the controller's Grizzly Bears


# ---------------------------------------------------------------------------
# Rock Hydra — "I should be able to activate the first ability at any time. Only
# the second ability has an upkeep restriction."
# ---------------------------------------------------------------------------

class TestRockHydraTiming:
    def _hydra_game(self, cards):
        hydra = Permanent(card=cards["Rock Hydra"])
        # Entered with X=3 counters; without them it is a 0/0 and dies (704.5f).
        hydra.power_bonus = 3
        hydra.toughness_bonus = 3
        p1 = PlayerState(name="P1", battlefield=[hydra])
        game = _game(p1, PlayerState(name="P2"))
        game.active_player_index = 0
        return game, hydra

    def test_prevent_ability_usable_outside_upkeep(self, cards):
        game, _ = self._hydra_game(cards)
        game.current_turn_phase = "combat"
        game.current_step = "declare_blockers"
        result = game.activate_permanent_ability(0, "Rock Hydra", permanent_index=0, ability_index=0)
        assert result.supported  # {R}: prevent — no upkeep restriction

    def test_pump_ability_blocked_outside_upkeep(self, cards):
        game, _ = self._hydra_game(cards)
        game.current_turn_phase = "precombat_main"
        game.current_step = "precombat_main"
        result = game.activate_permanent_ability(0, "Rock Hydra", permanent_index=0, ability_index=1)
        assert not result.supported  # {R}{R}{R}: pump — upkeep only

    def test_pump_ability_usable_during_upkeep(self, cards):
        game, hydra = self._hydra_game(cards)
        game.current_turn_phase = "beginning"
        game.current_step = "upkeep"
        result = game.activate_permanent_ability(0, "Rock Hydra", permanent_index=0, ability_index=1)
        assert result.supported


# ---------------------------------------------------------------------------
# Lure — "When Lure is attached to an opponent (AI) creature it skips my block
# step entirely." The AI declined to attack with the Lured creature.
# ---------------------------------------------------------------------------

class TestLureAttackPolicy:
    def test_ai_attacks_with_lured_creature(self, cards):
        attacker = Permanent(card=cards["Grizzly Bears"])
        attacker.metadata["summoning_sickness_turn"] = -99
        attacker.metadata["lure_active"] = True
        p1 = PlayerState(name="P1", battlefield=[attacker])
        # A big blocker that would normally make the AI decline the attack.
        blocker = Permanent(card=cards["Force of Nature"])
        p2 = PlayerState(name="P2", battlefield=[blocker], life=20)
        game = _game(p1, p2)
        game.active_player_index = 0
        chosen = choose_attackers(game, 0)
        assert 0 in chosen


# ---------------------------------------------------------------------------
# Verduran Enchantress — "it says may draw a card so I should get a prompt." The
# draw is now an optional yes/no rather than automatic.
# ---------------------------------------------------------------------------

class TestVerduranOptionalDraw:
    def test_draw_is_optional_and_can_be_declined(self, cards):
        ench = Permanent(card=cards["Verduran Enchantress"])
        bear = Permanent(card=cards["Grizzly Bears"])
        p1 = PlayerState(
            name="P1",
            hand=[cards["Blessing"]],
            library=[cards["Island"], cards["Forest"]],
            battlefield=[ench, bear],
        )
        game = _game(p1, PlayerState(name="P2"))
        game.cast_from_hand(0, "Blessing", target_player_index=0, target_permanent_index=1)
        assert any(e["card_name"] == "Verduran Enchantress" for e in game.pending_optional_pays)
        assert len(p1.hand) == 0
        game.confirm_optional_pay(0, "Verduran Enchantress", accept=False)
        assert len(p1.hand) == 0  # declined: no draw

    def test_draw_is_taken_on_accept(self, cards):
        ench = Permanent(card=cards["Verduran Enchantress"])
        p1 = PlayerState(
            name="P1",
            hand=[cards["Blessing"]],
            library=[cards["Island"]],
            battlefield=[ench, Permanent(card=cards["Grizzly Bears"])],
        )
        game = _game(p1, PlayerState(name="P2"))
        game.cast_from_hand(0, "Blessing", target_player_index=0, target_permanent_index=1)
        game.confirm_optional_pay(0, "Verduran Enchantress", accept=True)
        assert len(p1.hand) == 1


# ---------------------------------------------------------------------------
# Reverse Damage — "of your choice" was classified `none` (no-op). It now arms a
# one-shot shield that prevents the next damage event to the caster and gains
# them that much life.
# ---------------------------------------------------------------------------

class TestReverseDamage:
    def test_supported(self, cards):
        assert compile_card_oracle(cards["Reverse Damage"]).supported

    def test_prevents_next_damage_and_gains_life(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Reverse Damage"]], life=20)
        game = _game(p1, PlayerState(name="P2"))
        game.cast_from_hand(0, "Reverse Damage")
        assert p1.reverse_damage_charges == 1
        # The next damage event is fully prevented and converted to life gain.
        game._deal_damage_to_player(p1, 5)
        assert p1.life == 25
        assert p1.reverse_damage_charges == 0
        # Only one event is shielded; subsequent damage applies normally.
        game._deal_damage_to_player(p1, 3)
        assert p1.life == 22


# ---------------------------------------------------------------------------
# Phantasmal Terrain — "of your choice"/"chosen type" hardcoded island. The
# controller now picks the basic land type via a pending choice.
# ---------------------------------------------------------------------------

class TestPhantasmalTerrain:
    def _setup(self, cards):
        land = Permanent(card=cards["Forest"])
        p1 = PlayerState(name="P1", hand=[cards["Phantasmal Terrain"]])
        p2 = PlayerState(name="P2", battlefield=[land])
        game = _game(p1, p2)
        game.cast_from_hand(0, "Phantasmal Terrain", target_player_index=1, target_permanent_index=0)
        return game, land

    def test_arms_pending_choice_with_provisional_default(self, cards):
        game, land = self._setup(cards)
        assert land.metadata.get("land_type_override") == "island"
        assert game.pending_land_type_choice is not None
        assert game.pending_land_type_choice["player_index"] == 0

    def test_confirm_overrides_land_type(self, cards):
        game, land = self._setup(cards)
        assert game.confirm_land_type(0, "mountain") is True
        assert land.metadata.get("land_type_override") == "mountain"
        assert game.pending_land_type_choice is None

    def test_invalid_type_and_wrong_player_rejected(self, cards):
        game, _ = self._setup(cards)
        assert game.confirm_land_type(0, "wastes") is False  # not a basic type
        assert game.confirm_land_type(1, "swamp") is False   # not the controller
        assert game.pending_land_type_choice is not None     # still pending


# ---------------------------------------------------------------------------
# Kudzu — "Doesn't let me choose a new target when I tap the enchanted land."
# With defer_kudzu_choice the reattach becomes a pending controller choice; the
# headless/AI path keeps the deterministic first-land default.
# ---------------------------------------------------------------------------

class TestKudzuReattach:
    def _setup(self, cards):
        forest = Permanent(card=cards["Forest"])
        island = Permanent(card=cards["Island"])
        plains = Permanent(card=cards["Plains"])
        p1 = PlayerState(name="P1", hand=[cards["Kudzu"]], battlefield=[forest, island, plains])
        game = _game(p1, PlayerState(name="P2"))
        game.cast_from_hand(0, "Kudzu", target_player_index=0, target_permanent_index=0)
        kudzu = next(p for p in p1.battlefield if p.card.name == "Kudzu")
        return game, p1, kudzu, forest, island, plains

    def test_deferred_tap_arms_pending_choice(self, cards):
        game, _, kudzu, forest, _, _ = self._setup(cards)
        assert kudzu.metadata.get("attached_to") is forest
        game.tap_land_for_mana(0, "Forest", chosen_color="G", permanent_index=0, defer_kudzu_choice=True)
        # Land destroyed; Aura detached and awaiting the controller's choice.
        assert game.pending_kudzu_reattach is not None
        assert kudzu.metadata.get("attached_to") is None

    def test_confirm_attaches_to_chosen_land(self, cards):
        game, p1, kudzu, _, _, plains = self._setup(cards)
        game.tap_land_for_mana(0, "Forest", chosen_color="G", permanent_index=0, defer_kudzu_choice=True)
        # Battlefield is now [Island, Plains, Kudzu]; pick Plains (index 1).
        assert game.confirm_kudzu_reattach(0, 1) is True
        assert kudzu.metadata.get("attached_to") is plains
        assert game.pending_kudzu_reattach is None

    def test_headless_path_auto_attaches_first_land(self, cards):
        game, _, kudzu, _, island, _ = self._setup(cards)
        game.tap_land_for_mana(0, "Forest", chosen_color="G", permanent_index=0)
        assert game.pending_kudzu_reattach is None
        assert kudzu.metadata.get("attached_to") is island


# ---------------------------------------------------------------------------
# Smoke — "Players can't untap more than one creature during their untap steps."
# The controller now chooses which creature untaps (was the first tapped one).
# ---------------------------------------------------------------------------

class TestSmokeUntapSelection:
    def _setup(self, cards):
        def tapped(name):
            p = Permanent(card=cards[name])
            p.tapped = True
            return p
        smoke = Permanent(card=cards["Smoke"])
        c1, c2, c3 = tapped("Grizzly Bears"), tapped("Hill Giant"), tapped("Gray Ogre")
        land = tapped("Forest")
        p1 = PlayerState(name="P1", battlefield=[smoke, c1, c2, c3, land])
        game = _game(p1, PlayerState(name="P2"))
        game.active_player_index = 0
        return game, (c1, c2, c3), land

    def test_options_enumerate_only_tapped_creatures(self, cards):
        game, _, _ = self._setup(cards)
        opts = game.get_untap_land_selection_options(0)
        assert opts is not None
        assert opts["max_count"] == 1
        assert opts["creature_max"] == 1
        assert opts["land_max"] is None  # lands untap freely (no Winter Orb)
        assert opts["candidate_indices"] == [1, 2, 3]  # the three creatures

    def test_untaps_only_chosen_creature_and_all_lands(self, cards):
        game, (c1, c2, c3), land = self._setup(cards)
        game.resolve_untap_step(0, selected_creature_indices=[2])  # choose Hill Giant
        assert c2.tapped is False
        assert c1.tapped is True and c3.tapped is True
        assert land.tapped is False  # lands are unconstrained

    def test_single_tapped_creature_needs_no_selection(self, cards):
        smoke = Permanent(card=cards["Smoke"])
        only = Permanent(card=cards["Grizzly Bears"])
        only.tapped = True
        p1 = PlayerState(name="P1", battlefield=[smoke, only])
        game = _game(p1, PlayerState(name="P2"))
        game.active_player_index = 0
        assert game.get_untap_land_selection_options(0) is None


# ---------------------------------------------------------------------------
# Mana Vault / Paralyze — "you may pay {N}. If you do, untap ..." upkeep pays.
# These had no parsed instruction, so the prompt never surfaced and the untap
# never happened. Now they are optional upkeep pays with no decline consequence.
# ---------------------------------------------------------------------------

class TestManaVaultUpkeepUntap:
    def _game(self, cards):
        mv = Permanent(card=cards["Mana Vault"])
        mv.tapped = True
        p1 = PlayerState(name="P1", battlefield=[mv])
        game = _game(p1, PlayerState(name="P2"))
        return game, mv

    def test_trigger_is_surfaced(self, cards):
        game, _ = self._game(cards)
        names = [t["card_name"] for t in game.get_upkeep_pay_triggers(0)]
        assert "Mana Vault" in names

    def test_decline_leaves_it_tapped(self, cards):
        game, mv = self._game(cards)
        game.resolve_upkeep(0, human_choices={"Mana Vault": False})
        assert mv.tapped is True

    def test_accept_untaps_it(self, cards):
        game, mv = self._game(cards)
        game.resolve_upkeep(0, human_choices={"Mana Vault": True})
        assert mv.tapped is False


class TestParalyzeUpkeepUntap:
    def _game(self, cards):
        bear = Permanent(card=cards["Grizzly Bears"])
        bear.tapped = True
        paralyze = Permanent(card=cards["Paralyze"])
        paralyze.metadata["attached_to"] = bear
        # Aura controlled by P2; it enchants P1's creature.
        p1 = PlayerState(name="P1", battlefield=[bear])
        p2 = PlayerState(name="P2", battlefield=[paralyze])
        game = _game(p1, p2)
        return game, bear

    def test_trigger_surfaced_to_enchanted_controller(self, cards):
        game, _ = self._game(cards)
        names = [t["card_name"] for t in game.get_upkeep_pay_triggers(0)]
        assert "Paralyze" in names

    def test_decline_leaves_creature_tapped(self, cards):
        game, bear = self._game(cards)
        game.resolve_upkeep(0, human_choices={"Paralyze": False})
        assert bear.tapped is True

    def test_accept_untaps_creature(self, cards):
        game, bear = self._game(cards)
        game.resolve_upkeep(0, human_choices={"Paralyze": True})
        assert bear.tapped is False


# ---------------------------------------------------------------------------
# Farmstead — "you may pay {W}{W}. If you do, you gain 1 life." Was auto-paid
# silently; now surfaced as an optional upkeep pay the controller decides.
# ---------------------------------------------------------------------------

class TestFarmsteadUpkeepPay:
    def _game(self, cards, white=2):
        land = Permanent(card=cards["Plains"])
        farm = Permanent(card=cards["Farmstead"])
        farm.metadata["attached_to"] = land
        p1 = PlayerState(name="P1", battlefield=[land, farm], life=20)
        p1.mana_pool["W"] = white
        game = _game(p1, PlayerState(name="P2"))
        return game, p1

    def test_trigger_surfaced(self, cards):
        game, _ = self._game(cards)
        names = [t["card_name"] for t in game.get_upkeep_pay_triggers(0)]
        assert "Farmstead" in names

    def test_accept_pays_and_gains_life(self, cards):
        # (Mana empties at the upkeep step boundary, so life is the payment signal.)
        game, p1 = self._game(cards)
        game.resolve_upkeep(0, human_choices={"Farmstead": True})
        assert p1.life == 21

    def test_decline_gains_no_life(self, cards):
        game, p1 = self._game(cards)
        game.resolve_upkeep(0, human_choices={"Farmstead": False})
        assert p1.life == 20

    def test_decline_with_mana_still_gains_no_life(self, cards):
        # Even able to pay, an explicit decline forgoes the life (regression guard
        # against the old always-auto-pay behavior).
        game, p1 = self._game(cards, white=2)
        game.resolve_upkeep(0, human_choices={"Farmstead": False})
        assert p1.life == 20

    def test_auto_path_pays_when_able(self, cards):
        game, p1 = self._game(cards)
        game.resolve_upkeep(0)  # no human_choices -> beneficial default
        assert p1.life == 21


# ---------------------------------------------------------------------------
# Library of Leng — "If an effect causes you to discard a card, put it on top of
# your library instead of into your graveyard." Previously only Disrupting Scepter
# honored this; now random and cleanup discards route through the same helper.
# ---------------------------------------------------------------------------

class TestLibraryOfLengDiscards:
    def test_helper_routes_to_top_of_library_with_leng(self, cards):
        leng = Permanent(card=cards["Library of Leng"])
        p1 = PlayerState(name="P1", battlefield=[leng], library=[cards["Plains"]])
        game = _game(p1, PlayerState(name="P2"))
        game._discard_card(p1, cards["Forest"])
        assert p1.library[0].name == "Forest"   # kept on top
        assert p1.graveyard == []

    def test_helper_routes_to_graveyard_without_leng(self, cards):
        p1 = PlayerState(name="P1", library=[])
        game = _game(p1, PlayerState(name="P2"))
        game._discard_card(p1, cards["Forest"])
        assert [c.name for c in p1.graveyard] == ["Forest"]
        assert p1.library == []

    def test_cleanup_discard_goes_to_top_with_leng(self, cards):
        leng = Permanent(card=cards["Library of Leng"])
        hand = [cards["Forest"]] * 8  # one over the max hand size of 7
        p1 = PlayerState(name="P1", battlefield=[leng], hand=list(hand), library=[])
        game = _game(p1, PlayerState(name="P2"))
        game.resolve_cleanup_step(0)  # auto-discards the excess
        assert len(p1.hand) == 7
        assert len(p1.library) == 1   # the discarded card went on top, not to the yard
        assert p1.graveyard == []


# ---------------------------------------------------------------------------
# Fork — "Copy target instant or sorcery spell, except that the copy is red. You
# may choose new targets for the copy." The copy resolves with the original's
# targets (keeping targets is legal; the optional retarget is unmodeled).
# ---------------------------------------------------------------------------

class TestForkCopiesSpell:
    def test_fork_copies_a_targeted_burn_spell(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Lightning Bolt"], cards["Fork"]])
        p2 = PlayerState(name="P2", life=20)
        game = _game(p1, p2)
        game.queue_from_hand(0, "Lightning Bolt", target_player_index=1)
        game.queue_from_hand(0, "Fork", target_player_index=1, target_stack_index=0)
        assert len(game.stack) == 2
        while game.stack:
            game.resolve_top_of_stack()
        # 3 from the Bolt + 3 from the Fork copy (same target).
        assert p2.life == 14


# ---------------------------------------------------------------------------
# Power Sink — "Counter target spell unless its controller pays {X}." The core
# works: the spell is countered when its controller can't pay {X}. (The pay-or-be-
# countered prompt to a human is an unmodeled enhancement; AI auto-pays when able.)
# ---------------------------------------------------------------------------

class TestPowerSinkCounters:
    def test_counters_when_controller_cannot_pay(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Power Sink"]])
        p2 = PlayerState(name="P2", hand=[cards["Lightning Bolt"]])  # empty mana pool
        game = _game(p1, p2)
        game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
        game.queue_from_hand(0, "Power Sink", target_player_index=1, target_stack_index=0, x_value=3)
        while game.stack:
            game.resolve_top_of_stack()
        assert any(c.name == "Lightning Bolt" for c in p2.graveyard)  # countered


# ---------------------------------------------------------------------------
# Lich — "Whenever you're dealt damage, sacrifice that many nontoken permanents."
# The core works: N damage sacrifices N nontoken permanents (game-losing ones
# last). The interactive choice of which permanents is an unmodeled enhancement.
# ---------------------------------------------------------------------------

class TestLichSacrifice:
    def test_damage_sacrifices_that_many_nontoken_permanents(self, cards):
        lich = Permanent(card=cards["Lich"])
        a = Permanent(card=cards["Grizzly Bears"])
        b = Permanent(card=cards["Hill Giant"])
        p1 = PlayerState(name="P1", battlefield=[a, b, lich], life=20)
        game = _game(p1, PlayerState(name="P2"))
        before = len(p1.battlefield)
        game._deal_damage_to_player(p1, 2)
        assert before - len(p1.battlefield) == 2  # two nontoken permanents sacrificed
        assert lich in p1.battlefield              # Lich (game-losing) sacrificed last


# ---------------------------------------------------------------------------
# Fireball — "deals X damage divided evenly, rounded down, among any number of
# targets." The core works for targets on one battlefield (the common case);
# splitting across both seats' battlefields/faces is the remaining enhancement.
# ---------------------------------------------------------------------------

class TestFireballDividedDamage:
    def test_divides_evenly_among_creatures_on_one_side(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Fireball"]])
        b1 = Permanent(card=cards["Grizzly Bears"])
        b2 = Permanent(card=cards["Hill Giant"])
        p2 = PlayerState(name="P2", battlefield=[b1, b2], life=20)
        game = _game(p1, p2)
        game.queue_from_hand(0, "Fireball", target_player_index=1, target_permanent_index=[0, 1], x_value=4)
        while game.stack:
            game.resolve_top_of_stack()
        assert b1.damage_marked == 2 and b2.damage_marked == 2  # 4 split evenly


# ---------------------------------------------------------------------------
# Magical Hack — "replace all instances of one basic land type with another."
# The core works on lands: the enchanted/changed land's type override updates and
# it produces the new color of mana. (Landwalk remap on creatures + not recoloring
# non-lands are the remaining enhancements.)
# ---------------------------------------------------------------------------

class TestMagicalHackLand:
    def test_changes_land_type_and_mana(self, cards):
        forest = Permanent(card=cards["Forest"])
        p1 = PlayerState(name="P1", hand=[cards["Magical Hack"]])
        p2 = PlayerState(name="P2", battlefield=[forest])
        game = _game(p1, p2)
        game.queue_from_hand(0, "Magical Hack", target_player_index=1, target_permanent_index=0, new_color="U")
        while game.stack:
            game.resolve_top_of_stack()
        assert forest.metadata.get("land_type_override") == "island"
        # And it now taps for blue rather than green.
        game.tap_land_for_mana(1, "Forest", chosen_color="U", permanent_index=0)
        assert p2.mana_pool.get("U") == 1

    def test_remaps_creature_landwalk(self, cards):
        # Bog Wraith has Swampwalk; Magical Hack swamp (B) -> island (U) makes it
        # islandwalk instead, and it no longer has swampwalk.
        wraith = Permanent(card=cards["Bog Wraith"])
        wraith.metadata["summoning_sickness_turn"] = -99
        blocker = Permanent(card=cards["Grizzly Bears"])
        island = Permanent(card=cards["Island"])
        swamp = Permanent(card=cards["Swamp"])
        p1 = PlayerState(name="P1", hand=[cards["Magical Hack"]], battlefield=[wraith])
        p2 = PlayerState(name="P2", battlefield=[blocker, island, swamp])
        game = _game(p1, p2)
        assert game._attacker_has_active_landwalk(wraith, blocker) is True  # swampwalk vs Swamp
        game.cast_from_hand(0, "Magical Hack", target_player_index=0, target_permanent_index=0, old_color="B", new_color="U")
        assert wraith.metadata.get("lost_swampwalk") is True
        assert wraith.metadata.get("has_islandwalk") is True
        # Still unblockable via the Island (islandwalk now), but...
        assert game._attacker_has_active_landwalk(wraith, blocker) is True
        # ...with the Island gone, swampwalk no longer applies (it was remapped).
        p2.battlefield.remove(island)
        assert game._attacker_has_active_landwalk(wraith, blocker) is False


# ---------------------------------------------------------------------------
# Sleight of Mind — "replace all instances of one color word with another." It
# stores a per-permanent color-word remap (consumed where the engine reads that
# text's colors, e.g. protection) rather than recoloring the permanent.
# ---------------------------------------------------------------------------

class TestSleightOfMind:
    def test_remaps_protection_color(self, cards):
        # Black Knight has "protection from white"; change white (W) -> red (R).
        bk = Permanent(card=cards["Black Knight"])
        p1 = PlayerState(name="P1", hand=[cards["Sleight of Mind"]])
        p2 = PlayerState(name="P2", battlefield=[bk])
        game = _game(p1, p2)
        assert game._protection_colors(bk) == {"W"}
        game.cast_from_hand(0, "Sleight of Mind", target_player_index=1, target_permanent_index=0, old_color="W", new_color="R")
        assert bk.metadata.get("color_word_remap") == {"W": "R"}
        assert game._protection_colors(bk) == {"R"}     # protection from red now
        assert bk.metadata.get("color_override") is None  # not recolored


# ---------------------------------------------------------------------------
# Two-Headed Giant of Foriys — "This creature can block an additional creature
# each combat." The blocker model now maps a blocker to a list of attackers so
# one creature can block two, taking damage from both and dealing to one.
# ---------------------------------------------------------------------------

class TestTwoHeadedGiantDoubleBlock:
    def _combat(self, cards):
        b1 = Permanent(card=cards["Grizzly Bears"])
        b2 = Permanent(card=cards["Grizzly Bears"])
        for b in (b1, b2):
            b.metadata["summoning_sickness_turn"] = -99
        thg = Permanent(card=cards["Two-Headed Giant of Foriys"])
        p1 = PlayerState(name="P1", battlefield=[b1, b2], life=20)
        p2 = PlayerState(name="P2", battlefield=[thg], life=20)
        game = _game(p1, p2)
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        game.combat_defending_player_index = 1
        game.declare_attackers(0, [0, 1])
        game.advance_combat_phase()  # -> declare_blockers
        return game, p1, p2, b1, b2, thg

    def test_blocks_two_attackers_and_resolves_damage(self, cards):
        game, p1, p2, b1, b2, thg = self._combat(cards)
        ok, _ = game.declare_blockers(1, {0: [0, 1]})
        assert ok
        assert game.combat_blockers == {0: [0, 1]}
        game._set_phase_and_step("combat", "combat_damage")
        game.resolve_combat_damage(0)
        # Both bears are blocked, so no damage reaches the player.
        assert p2.life == 20
        # The Giant takes 2 + 2 = 4 and dies; it deals its 4 to one bear (kills it).
        assert thg not in p2.battlefield
        survivors = [b for b in (b1, b2) if b in p1.battlefield]
        assert len(survivors) == 1

    def test_ordinary_creature_cannot_block_two(self, cards):
        game, p1, p2, b1, b2, thg = self._combat(cards)
        # A vanilla Grizzly Bears on defense may only block one attacker.
        ordinary = Permanent(card=cards["Grizzly Bears"])
        p2.battlefield.append(ordinary)
        game._prune_combat_state()
        ok, msg = game.declare_blockers(1, {1: [0, 1]})  # index 1 = the ordinary bear
        assert not ok
        assert "cannot block that many" in msg

    def test_giant_cannot_block_three(self, cards):
        b1 = Permanent(card=cards["Grizzly Bears"])
        b2 = Permanent(card=cards["Grizzly Bears"])
        b3 = Permanent(card=cards["Grizzly Bears"])
        for b in (b1, b2, b3):
            b.metadata["summoning_sickness_turn"] = -99
        thg = Permanent(card=cards["Two-Headed Giant of Foriys"])
        p1 = PlayerState(name="P1", battlefield=[b1, b2, b3], life=20)
        p2 = PlayerState(name="P2", battlefield=[thg], life=20)
        game = _game(p1, p2)
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        game.combat_defending_player_index = 1
        game.declare_attackers(0, [0, 1, 2])
        game.advance_combat_phase()
        ok, msg = game.declare_blockers(1, {0: [0, 1, 2]})
        assert not ok
        assert "cannot block that many" in msg


# ---------------------------------------------------------------------------
# Camouflage — replaces the declare-blockers step with random pile assignment.
# The defender's creatures are divided into piles (one per attacker), randomly
# assigned, and block their assigned attacker if able (seeded RNG = reproducible).
# ---------------------------------------------------------------------------

class TestCamouflage:
    def _combat(self, cards):
        a1 = Permanent(card=cards["Grizzly Bears"])
        a2 = Permanent(card=cards["Hill Giant"])
        for a in (a1, a2):
            a.metadata["summoning_sickness_turn"] = -99
        d1 = Permanent(card=cards["Grizzly Bears"])
        d2 = Permanent(card=cards["Gray Ogre"])
        p1 = PlayerState(name="P1", battlefield=[a1, a2], life=20)
        p2 = PlayerState(name="P2", battlefield=[d1, d2], life=20)
        game = _game(p1, p2)
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        game.combat_defending_player_index = 1
        game.declare_attackers(0, [0, 1])
        game.advance_combat_phase()  # -> declare_blockers
        game.camouflage_active_turn = game.turn
        return game

    def test_assigns_random_blocks_and_is_deterministic(self, cards):
        game = self._combat(cards)
        random.seed(42)
        ok, _ = game.resolve_camouflage_blocking(1)
        assert ok
        first = dict(game.combat_blockers)
        assert first  # some creature was assigned to block
        # Each blocker blocks exactly one attacker (single pile membership).
        assert all(len(atks) == 1 for atks in first.values())

        game2 = self._combat(cards)
        random.seed(42)
        game2.resolve_camouflage_blocking(1)
        assert game2.combat_blockers == first  # reproducible under the same seed

    def test_auto_resolves_when_active_on_advance(self, cards):
        game = self._combat(cards)
        random.seed(5)
        assert game.is_camouflage_active()
        game.advance_combat_phase()  # at declare_blockers -> camouflage resolves
        assert game.combat_blockers_locked is True
        assert game.combat_blockers  # blocks were auto-assigned


# ---------------------------------------------------------------------------
# Illusionary Mask — "{X}: cast a creature card whose cost X could pay, face down
# as a 2/2." The controller now chooses which eligible creature (mana value <= X),
# instead of the handler auto-picking the first creature.
# ---------------------------------------------------------------------------

class TestIllusionaryMask:
    def _game(self, cards, hand):
        mask = Permanent(card=cards["Illusionary Mask"])
        p1 = PlayerState(name="P1", hand=list(hand), battlefield=[mask])
        game = _game(p1, PlayerState(name="P2"))
        return game, p1

    def test_activation_arms_choice_filtered_by_x(self, cards):
        game, p1 = self._game(cards, [cards["Grizzly Bears"], cards["Force of Nature"]])
        game.activate_permanent_ability(0, "Illusionary Mask", permanent_index=0, x_value=3)
        assert game.pending_face_down_cast is not None
        assert game.pending_face_down_cast["max_cmc"] == 3

    def test_confirm_casts_chosen_creature_face_down(self, cards):
        game, p1 = self._game(cards, [cards["Grizzly Bears"], cards["Force of Nature"]])
        game.activate_permanent_ability(0, "Illusionary Mask", permanent_index=0, x_value=3)
        assert game.confirm_face_down_cast(0, 0) is True  # Grizzly Bears (cmc 2)
        fd = [p for p in p1.battlefield if p.metadata.get("face_down")]
        assert len(fd) == 1
        assert fd[0].effective_power == 2 and fd[0].effective_toughness == 2
        assert fd[0].metadata["face_down_real_card"].name == "Grizzly Bears"
        assert [c.name for c in p1.hand] == ["Force of Nature"]
        assert game.pending_face_down_cast is None

    def test_ineligible_creature_rejected(self, cards):
        game, p1 = self._game(cards, [cards["Force of Nature"]])  # cmc 8 > X
        game.activate_permanent_ability(0, "Illusionary Mask", permanent_index=0, x_value=3)
        assert game.pending_face_down_cast is None  # nothing eligible -> no prompt

    def test_decline_casts_nothing(self, cards):
        game, p1 = self._game(cards, [cards["Grizzly Bears"]])
        game.activate_permanent_ability(0, "Illusionary Mask", permanent_index=0, x_value=3)
        assert game.confirm_face_down_cast(0, -1) is True  # decline
        assert not any(p.metadata.get("face_down") for p in p1.battlefield)
        assert len(p1.hand) == 1
        assert game.pending_face_down_cast is None


# ---------------------------------------------------------------------------
# Time Vault — "If you would begin your turn while this is tapped, you may skip
# that turn to untap it." untap_for_skip untaps WITHOUT scheduling a future skip
# (the web turn flow skips the current turn), unlike skip_turn_to_untap.
# ---------------------------------------------------------------------------

class TestTimeVaultUntapForSkip:
    def test_untaps_without_scheduling_a_future_skip(self, cards):
        vault = Permanent(card=cards["Time Vault"])
        vault.tapped = True
        p1 = PlayerState(name="P1", battlefield=[vault])
        game = _game(p1, PlayerState(name="P2"))
        assert game.get_begin_turn_untap_options(0) == ["Time Vault"]
        assert game.untap_for_skip(0, "Time Vault") is True
        assert vault.tapped is False
        assert game.skip_turn_counts.get(0, 0) == 0  # no future-turn skip queued

    def test_rejected_when_untapped(self, cards):
        vault = Permanent(card=cards["Time Vault"])  # already untapped
        p1 = PlayerState(name="P1", battlefield=[vault])
        game = _game(p1, PlayerState(name="P2"))
        assert game.untap_for_skip(0, "Time Vault") is False


# ---------------------------------------------------------------------------
# Word of Command — "Look at target opponent's hand and choose a card; that
# player plays it." The caster now chooses which card (and the target plays it)
# instead of the old stub that discarded the first card. MVP: the forced spell
# defaults to targeting the forced player.
# ---------------------------------------------------------------------------

class TestWordOfCommand:
    def test_arms_choice_and_forces_chosen_card(self, cards):
        p0 = PlayerState(name="P0", hand=[cards["Word of Command"]], life=20)
        p1 = PlayerState(name="P1", hand=[cards["Lightning Bolt"], cards["Grizzly Bears"]], life=20)
        game = _game(p0, p1)
        game.cast_from_hand(0, "Word of Command", target_player_index=1)
        pending = game.pending_word_of_command
        assert pending is not None
        assert pending["hand"] == ["Lightning Bolt", "Grizzly Bears"]
        # Force the opponent's Lightning Bolt — it defaults to hitting themselves.
        assert game.confirm_word_of_command(0, 0) is True
        assert p1.life == 17
        assert [c.name for c in p1.hand] == ["Grizzly Bears"]
        assert game.pending_word_of_command is None

    def test_forced_creature_enters_under_target_control(self, cards):
        p0 = PlayerState(name="P0", hand=[cards["Word of Command"]], life=20)
        p1 = PlayerState(name="P1", hand=[cards["Grizzly Bears"]], life=20)
        game = _game(p0, p1)
        game.cast_from_hand(0, "Word of Command", target_player_index=1)
        game.confirm_word_of_command(0, 0)
        # The forced creature is played onto the target's own battlefield.
        assert any(p.card.name == "Grizzly Bears" for p in p1.battlefield)
        assert not any(p.card.name == "Grizzly Bears" for p in p0.battlefield)

    def test_decline_plays_nothing(self, cards):
        p0 = PlayerState(name="P0", hand=[cards["Word of Command"]], life=20)
        p1 = PlayerState(name="P1", hand=[cards["Lightning Bolt"]], life=20)
        game = _game(p0, p1)
        game.cast_from_hand(0, "Word of Command", target_player_index=1)
        assert game.confirm_word_of_command(0, -1) is True
        assert p1.life == 20
        assert len(p1.hand) == 1
        assert game.pending_word_of_command is None


# ---------------------------------------------------------------------------
# Forcefield — "{1}: The next time an unblocked creature of your choice would deal
# combat damage to you this turn, prevent all but 1 of that damage." The
# activation now targets the chosen unblocked attacker (was a generic cap).
# ---------------------------------------------------------------------------

class TestForcefield:
    def _combat(self, cards):
        ff = Permanent(card=cards["Forcefield"])
        attacker = Permanent(card=cards["Hill Giant"])  # 3/3
        attacker.metadata["summoning_sickness_turn"] = -99
        # Seat 0 = attacker (active), seat 1 = Forcefield controller (defender).
        p_att = PlayerState(name="Attacker", battlefield=[attacker], life=20)
        p_def = PlayerState(name="Defender", battlefield=[ff], life=20)
        game = _game(p_att, p_def)
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        game.combat_defending_player_index = 1
        game.declare_attackers(0, [0])
        game.advance_combat_phase()       # -> declare_blockers
        game.declare_blockers(1, {})      # Hill Giant unblocked
        return game, p_def, attacker

    def test_activation_enumerates_only_unblocked_attackers(self, cards):
        game, _, _ = self._combat(cards)
        spec = game.activation_target_spec(1, 0)  # Forcefield is p_def's index 0
        assert spec["kind"] == "creature" and spec["requires_target"]
        keys = {(t["seat"], t["index"]) for t in spec["valid_targets"]}
        assert keys == {(0, 0)}  # the unblocked Hill Giant

    def test_caps_chosen_attacker_combat_damage_to_one(self, cards):
        game, p_def, attacker = self._combat(cards)
        game.activate_permanent_ability(
            1, "Forcefield", permanent_index=0, target_player_index=0, target_permanent_index=0
        )
        assert attacker in p_def.forcefield_capped_sources
        game._set_phase_and_step("combat", "combat_damage")
        game.resolve_combat_damage(0)
        assert p_def.life == 19  # Hill Giant's 3 prevented down to 1


# ---------------------------------------------------------------------------
# Volcanic Eruption — "Destroy X target Mountains." The caster now chooses which
# Mountains (cast spec is a Mountain multi-select where X = the number chosen).
# ---------------------------------------------------------------------------

class TestVolcanicEruption:
    def test_cast_spec_enumerates_mountains(self, cards):
        ve = cards["Volcanic Eruption"]
        m1, m2 = Permanent(card=cards["Mountain"]), Permanent(card=cards["Mountain"])
        forest = Permanent(card=cards["Forest"])
        p0 = PlayerState(name="P0", hand=[ve], battlefield=[m1, m2, forest], life=20)
        game = _game(p0, PlayerState(name="P1"))
        spec = game.cast_target_spec(0, ve)
        assert spec["kind"] == "divided"
        assert spec["land_filter"] == "mountain"
        assert spec["x_equals_targets"] is True
        keys = {(t["seat"], t["index"]) for t in spec["valid_targets"]}
        assert keys == {(0, 0), (0, 1)}  # only the two Mountains (not the Forest)

    def test_destroys_only_chosen_mountains(self, cards):
        m1, m2, m3 = (Permanent(card=cards["Mountain"]) for _ in range(3))
        p0 = PlayerState(name="P0", hand=[cards["Volcanic Eruption"]], battlefield=[m1, m2, m3], life=20)
        p1 = PlayerState(name="P1", life=20)
        game = _game(p0, p1)
        # Choose two of the three Mountains; X = 2.
        game.cast_from_hand(0, "Volcanic Eruption", target_player_index=0, target_permanent_index=[0, 1], x_value=2)
        assert len(p0.battlefield) == 1  # one Mountain survives
        assert p0.life == 18 and p1.life == 18  # 2 damage to each player
