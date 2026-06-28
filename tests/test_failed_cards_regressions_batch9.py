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
