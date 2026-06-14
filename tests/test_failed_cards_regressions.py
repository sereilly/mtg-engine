"""Regression tests for the second batch of cards reported FAILED in-game.

Each test documents the bug that was reported via the Debug Menu verification
flow, then guards the rules-correct behavior after the fix. Tests load the real
Alpha (LEA) card definitions so they exercise the actual oracle text and parse
rules.
"""
from __future__ import annotations

import random
from pathlib import Path

import pytest

from engine import Game, PlayerState, load_cards
from engine.models import Permanent


@pytest.fixture(scope="module")
def cards():
    root = Path(__file__).resolve().parent.parent
    return {c.name: c for c in load_cards(root / "lea_cards.json")}


def _game(p1: PlayerState, p2: PlayerState) -> Game:
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game


def _no_summoning_sickness(perm: Permanent) -> Permanent:
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


# ---------------------------------------------------------------------------
# Berserk — "didn't let me choose a target creature"
# ---------------------------------------------------------------------------

class TestBerserk:
    def test_pumps_chosen_creature_and_grants_trample(self, cards):
        bears = Permanent(card=cards["Grizzly Bears"])  # 2/2
        giant = Permanent(card=cards["Hill Giant"])     # 3/3
        p1 = PlayerState(name="P1", hand=[cards["Berserk"]], battlefield=[bears, giant])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        result = game.cast_from_hand(
            0, "Berserk", target_player_index=0, target_permanent_index=1
        )

        assert result.supported
        # +X/+0 where X is its power: Hill Giant 3 -> 6 power, and gains trample.
        assert giant.effective_power == 6
        assert giant.metadata.get("gains_trample_until_eot") is True
        assert bears.effective_power == 2  # untouched

    def test_requires_a_creature_target(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Berserk"]])
        p2 = PlayerState(name="P2")  # no creatures anywhere
        game = _game(p1, p2)

        result = game.cast_from_hand(0, "Berserk", target_player_index=0)

        assert not result.supported


# ---------------------------------------------------------------------------
# Clockwork Beast — "end of combat trigger didn't occur"
# ---------------------------------------------------------------------------

class TestClockworkBeast:
    def test_enters_with_seven_counters(self, cards):
        beast = Permanent(card=cards["Clockwork Beast"])
        game = _game(PlayerState(name="P1"), PlayerState(name="P2"))

        game._put_permanent_onto_battlefield(0, beast, None)

        assert beast.metadata.get("plus_1_0_counters") == 7
        assert beast.effective_power == 7

    def test_removes_a_counter_at_end_of_combat_if_it_attacked(self, cards):
        beast = Permanent(card=cards["Clockwork Beast"])
        game = _game(PlayerState(name="P1"), PlayerState(name="P2"))
        game._put_permanent_onto_battlefield(0, beast, None)

        beast.metadata["attacked_this_turn"] = True
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        game.combat_defending_player_index = 1
        game.end_combat()

        assert beast.metadata.get("plus_1_0_counters") == 6
        assert beast.effective_power == 6

    def test_no_counter_removed_if_it_did_not_fight(self, cards):
        beast = Permanent(card=cards["Clockwork Beast"])
        game = _game(PlayerState(name="P1"), PlayerState(name="P2"))
        game._put_permanent_onto_battlefield(0, beast, None)

        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        game.combat_defending_player_index = 1
        game.end_combat()

        assert beast.metadata.get("plus_1_0_counters") == 7
        assert beast.effective_power == 7


# ---------------------------------------------------------------------------
# Clone — "didn't let me choose a target"
# ---------------------------------------------------------------------------

class TestClone:
    def test_copies_the_chosen_creature(self, cards):
        bears = Permanent(card=cards["Grizzly Bears"])  # 2/2
        giant = Permanent(card=cards["Hill Giant"])     # 3/3
        p1 = PlayerState(name="P1", hand=[cards["Clone"]])
        p2 = PlayerState(name="P2", battlefield=[bears, giant])
        game = _game(p1, p2)

        result = game.cast_from_hand(
            0, "Clone", target_player_index=1, target_permanent_index=1
        )

        assert result.supported
        clone = next(p for p in p1.battlefield if p.card.name == "Clone")
        assert clone.metadata.get("copied_from") == "Hill Giant"
        assert (clone.effective_power, clone.effective_toughness) == (3, 3)


# ---------------------------------------------------------------------------
# Conservator — "should have prevented 2 of the 3 damage to me"
# ---------------------------------------------------------------------------

class TestConservator:
    def test_prevention_shield_protects_the_controller(self, cards):
        conservator = _no_summoning_sickness(Permanent(card=cards["Conservator"]))
        p1 = PlayerState(
            name="P1", battlefield=[conservator], hand=[cards["Lightning Bolt"]]
        )
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        game.activate_permanent_ability(0, "Conservator", permanent_index=0)

        # The shield goes to the activating player, not the opponent.
        assert p1.damage_prevention_pool == 2
        assert p2.damage_prevention_pool == 0

        before = p1.life
        game.cast_from_hand(0, "Lightning Bolt", target_player_index=0)
        # 3 damage, 2 prevented -> only 1 dealt.
        assert p1.life == before - 1


# ---------------------------------------------------------------------------
# Earthbind — "didn't make the flying creature lose flying"
# ---------------------------------------------------------------------------

class TestEarthbind:
    def test_strips_flying_and_deals_two_damage(self, cards):
        assert "Flying" in cards["Air Elemental"].keywords
        flyer = Permanent(card=cards["Air Elemental"])
        p1 = PlayerState(name="P1", hand=[cards["Earthbind"]])
        p2 = PlayerState(name="P2", battlefield=[flyer])
        game = _game(p1, p2)

        result = game.cast_from_hand(
            0, "Earthbind", target_player_index=1, target_permanent_index=0
        )

        assert result.supported
        assert flyer.damage_marked == 2
        assert game._has_keyword(flyer, "flying") is False


# ---------------------------------------------------------------------------
# Evil Presence — "should turn the enchanted land into a basic Swamp"
# ---------------------------------------------------------------------------

class TestEvilPresence:
    def test_enchanted_land_taps_for_black(self, cards):
        forest = Permanent(card=cards["Forest"])
        p1 = PlayerState(name="P1", hand=[cards["Evil Presence"]])
        p2 = PlayerState(name="P2", battlefield=[forest])
        game = _game(p1, p2)

        result = game.cast_from_hand(
            0, "Evil Presence", target_player_index=1, target_permanent_index=0
        )

        assert result.supported
        assert forest.metadata.get("land_type_override") == "swamp"
        # The land is now a Swamp: it produces black, not green.
        assert forest.effective_produced_mana == ("B",)
        game.tap_land_for_mana(1, "Forest", chosen_color="G", permanent_index=0)
        assert p2.mana_pool["B"] == 1
        assert p2.mana_pool["G"] == 0


# ---------------------------------------------------------------------------
# Fork — "didn't let me select a spell target"
# ---------------------------------------------------------------------------

class TestFork:
    def test_cannot_be_cast_with_no_spell_on_the_stack(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Fork"]])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        result = game.cast_from_hand(0, "Fork", target_player_index=1)

        assert not result.supported

    def test_copies_an_instant_on_the_stack(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Fork"]])
        p2 = PlayerState(name="P2", hand=[cards["Lightning Bolt"]], life=20)
        game = _game(p1, p2)

        # Opponent's Lightning Bolt sits on the stack, aimed at themselves.
        game.queue_from_hand(1, "Lightning Bolt", target_player_index=1)
        result = game.cast_from_hand(0, "Fork", target_player_index=1)
        assert result.supported
        game.resolve_stack()

        # Copy (3) plus the original bolt (3) = 6 damage.
        assert p2.life == 20 - 6


# ---------------------------------------------------------------------------
# Natural Selection — "should prompt to shuffle the chosen player's library"
# ---------------------------------------------------------------------------

class TestNaturalSelection:
    NAMES = ["Grizzly Bears", "Hill Giant", "Mountain", "Forest"]

    def _library(self, cards):
        return [cards[n] for n in self.NAMES]

    def test_offers_a_shuffle_option(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Natural Selection"]])
        p2 = PlayerState(name="P2", library=self._library(cards))
        game = _game(p1, p2)

        result = game.cast_from_hand(0, "Natural Selection", target_player_index=1)

        assert result.supported
        pending = game.pending_reorder_library
        assert pending is not None
        assert pending["may_shuffle"] is True

    def test_reorders_then_shuffles_when_requested(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Natural Selection"]])
        p2 = PlayerState(name="P2", library=self._library(cards))
        game = _game(p1, p2)
        game.cast_from_hand(0, "Natural Selection", target_player_index=1)

        random.seed(1234)
        ok = game.confirm_reorder_library(0, [2, 1, 0], shuffle=True)

        assert ok
        assert game.pending_reorder_library is None
        # Shuffle does not lose cards.
        assert sorted(c.name for c in p2.library) == sorted(self.NAMES)

    def test_reorder_without_shuffle_keeps_the_chosen_order(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Natural Selection"]])
        p2 = PlayerState(name="P2", library=self._library(cards))
        game = _game(p1, p2)
        game.cast_from_hand(0, "Natural Selection", target_player_index=1)

        ok = game.confirm_reorder_library(0, [2, 1, 0], shuffle=False)

        assert ok
        # Top 3 reversed, 4th card untouched.
        assert [c.name for c in p2.library] == [
            "Mountain",
            "Hill Giant",
            "Grizzly Bears",
            "Forest",
        ]


# ---------------------------------------------------------------------------
# Sedge Troll — regenerate vs Terror.
# The reported "bug" is actually correct rules: Terror reads "It can't be
# regenerated", so the shield does not save it. A normal destroy IS prevented.
# ---------------------------------------------------------------------------

class TestSedgeTroll:
    def test_terror_destroys_it_despite_a_regeneration_shield(self, cards):
        troll = Permanent(card=cards["Sedge Troll"])
        troll.regeneration_shield = 1
        p1 = PlayerState(name="P1", battlefield=[troll])
        p2 = PlayerState(name="P2", hand=[cards["Terror"]])
        game = _game(p1, p2)

        # Sedge Troll is red, so it is a legal Terror target.
        result = game.cast_from_hand(
            1, "Terror", target_player_index=0, target_permanent_index=0
        )

        assert result.supported
        assert not p1.battlefield  # "can't be regenerated" beats the shield
        assert any(c.name == "Sedge Troll" for c in p1.graveyard)

    def test_regeneration_shield_saves_it_from_ordinary_destruction(self, cards):
        troll = Permanent(card=cards["Sedge Troll"])
        troll.regeneration_shield = 1
        p1 = PlayerState(name="P1", battlefield=[troll])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        destroyed = game._destroy_target_permanent(p1, type_filter="creature")

        assert destroyed is None
        assert troll in p1.battlefield
        assert troll.tapped is True
        assert troll.regeneration_shield == 0


# ---------------------------------------------------------------------------
# Simulacrum — "should require a creature target to cast it"
# ---------------------------------------------------------------------------

class TestSimulacrum:
    def test_requires_a_creature_you_control(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Simulacrum"]])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        result = game.cast_from_hand(0, "Simulacrum", target_player_index=0)

        assert not result.supported

    def test_gains_life_and_redirects_damage_taken_this_turn(self, cards):
        giant = Permanent(card=cards["Hill Giant"])  # 3/3
        p1 = PlayerState(
            name="P1", hand=[cards["Simulacrum"]], battlefield=[giant], life=16
        )
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        game._deal_damage_to_player(p1, 4)
        assert p1.damage_taken_this_turn == 4
        assert p1.life == 12

        result = game.cast_from_hand(
            0, "Simulacrum", target_player_index=0, target_permanent_index=0
        )

        assert result.supported
        # Gains 4 life (back to 16) and deals 4 to the 3/3, which dies.
        assert p1.life == 16
        assert giant not in p1.battlefield


# ---------------------------------------------------------------------------
# Choosing a specific spell on the stack (Counterspell, Fork) — not just the top.
# ---------------------------------------------------------------------------

class TestChooseStackTarget:
    def _two_spell_stack(self, cards):
        """Stack (bottom -> top): Lightning Bolt at P1, then Giant Growth on P1's
        Grizzly Bears. Returns (game, p1, p2, bears)."""
        bears = Permanent(card=cards["Grizzly Bears"])
        p1 = PlayerState(name="P1", battlefield=[bears], life=20)
        p2 = PlayerState(
            name="P2", hand=[cards["Lightning Bolt"], cards["Giant Growth"]], life=20
        )
        game = _game(p1, p2)
        game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)            # engine idx 0
        game.queue_from_hand(1, "Giant Growth", target_player_index=0, target_permanent_index=0)  # engine idx 1
        return game, p1, p2, bears

    def test_counterspell_counters_the_chosen_bottom_spell(self, cards):
        game, p1, p2, bears = self._two_spell_stack(cards)
        p1.hand.append(cards["Counterspell"])

        # Counter the BOTTOM spell (Lightning Bolt, engine index 0).
        result = game.cast_from_hand(0, "Counterspell", target_stack_index=0)
        assert result.supported
        game.resolve_stack()

        # The bolt was countered (P1 still at 20), Giant Growth resolved (bears 2 -> 5).
        assert p1.life == 20
        assert any(c.name == "Lightning Bolt" for c in p2.graveyard)
        assert bears.effective_power == 5

    def test_counterspell_counters_the_chosen_top_spell(self, cards):
        game, p1, p2, bears = self._two_spell_stack(cards)
        p1.hand.append(cards["Counterspell"])

        # Counter the TOP spell (Giant Growth, engine index 1).
        result = game.cast_from_hand(0, "Counterspell", target_stack_index=1)
        assert result.supported
        game.resolve_stack()

        # Giant Growth was countered (bears unbuffed), the bolt resolved (P1 -3).
        assert any(c.name == "Giant Growth" for c in p2.graveyard)
        assert bears.effective_power == 2
        assert p1.life == 17

    def test_fork_copies_the_chosen_spell(self, cards):
        # Stack (bottom -> top): Lightning Bolt at P1 (idx 0), Giant Growth on
        # P1's bears (idx 1).
        bears = Permanent(card=cards["Grizzly Bears"])
        p1 = PlayerState(
            name="P1",
            hand=[cards["Fork"], cards["Giant Growth"]],
            battlefield=[bears],
            life=20,
        )
        p2 = PlayerState(name="P2", hand=[cards["Lightning Bolt"]], life=20)
        game = _game(p1, p2)
        game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)  # idx 0
        game.queue_from_hand(0, "Giant Growth", target_player_index=0, target_permanent_index=0)  # idx 1

        # Fork copies the BOTTOM spell (Lightning Bolt) even though Giant Growth is on top.
        result = game.cast_from_hand(0, "Fork", target_stack_index=0)
        assert result.supported
        game.resolve_stack()

        # Fork's copy dealt 3 to P1 and the original bolt dealt 3 more = 6.
        assert p1.life == 20 - 6
        # Giant Growth still resolved on the bears (2 -> 5).
        assert bears.effective_power == 5
