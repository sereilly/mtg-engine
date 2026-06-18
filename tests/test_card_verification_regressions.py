"""Regression tests for cards reported FAILED in CARD_VERIFICATION.md.

Each test documents the in-game bug that was reported, then guards the
rules-correct behavior after the fix. Tests load the real Alpha (LEA) card
definitions so they exercise the actual oracle text and parse rules.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from engine import Game, PlayerState, load_cards
from engine.models import CardDefinition, Permanent


@pytest.fixture(scope="module")
def cards():
    root = Path(__file__).resolve().parent.parent
    return {c.name: c for c in load_cards(root / "lea_cards.json")}


def _game(p1: PlayerState, p2: PlayerState) -> Game:
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game


def _untapped_assassin(card: CardDefinition) -> Permanent:
    perm = Permanent(card=card)
    perm.metadata["summoning_sickness_turn"] = -99  # not summoning sick → may tap
    return perm


# ---------------------------------------------------------------------------
# Animate Dead — "should let me target a creature in the graveyard when cast"
# ---------------------------------------------------------------------------

class TestAnimateDead:
    def test_reanimates_the_chosen_graveyard_creature(self, cards):
        p1 = PlayerState(
            name="P1",
            hand=[cards["Animate Dead"]],
            graveyard=[cards["Grizzly Bears"], cards["Hill Giant"]],
        )
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        # Target the second creature in P1's graveyard (Hill Giant).
        result = game.cast_from_hand(
            0, "Animate Dead", target_player_index=0, target_permanent_index=1
        )

        assert result.supported
        names = [p.card.name for p in p1.battlefield]
        assert "Hill Giant" in names  # the chosen creature was reanimated
        assert "Animate Dead" in names
        assert [c.name for c in p1.graveyard] == ["Grizzly Bears"]  # other left behind

    def test_can_reanimate_from_opponents_graveyard(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Animate Dead"]])
        p2 = PlayerState(name="P2", graveyard=[cards["Hill Giant"]])
        game = _game(p1, p2)

        result = game.cast_from_hand(
            0, "Animate Dead", target_player_index=1, target_permanent_index=0
        )

        assert result.supported
        # Reanimated under the caster's control.
        assert any(p.card.name == "Hill Giant" for p in p1.battlefield)

    def test_rejects_noncreature_graveyard_target(self, cards):
        p1 = PlayerState(
            name="P1",
            hand=[cards["Animate Dead"]],
            graveyard=[cards["Lightning Bolt"]],  # not a creature card
        )
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        result = game.cast_from_hand(
            0, "Animate Dead", target_player_index=0, target_permanent_index=0
        )

        assert not result.supported


# ---------------------------------------------------------------------------
# Disenchant — "I'm not able to cast it even when there are valid targets"
# ---------------------------------------------------------------------------

class TestDisenchant:
    def test_destroys_opponent_enchantment(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Disenchant"]])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=cards["Bad Moon"])])
        game = _game(p1, p2)

        result = game.cast_from_hand(
            0, "Disenchant", target_player_index=1, target_permanent_index=0
        )

        assert result.supported
        assert not p2.battlefield
        assert any(c.name == "Bad Moon" for c in p2.graveyard)

    def test_can_target_own_artifact(self, cards):
        # Regression: validation only checked the opponent's battlefield, so a
        # Disenchant whose only legal target was on the caster's own side was
        # wrongly rejected as having "no valid target".
        p1 = PlayerState(
            name="P1",
            hand=[cards["Disenchant"]],
            battlefield=[Permanent(card=cards["Black Lotus"])],
        )
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        result = game.cast_from_hand(
            0, "Disenchant", target_player_index=0, target_permanent_index=0
        )

        assert result.supported
        assert not p1.battlefield

    def test_rejected_when_no_artifact_or_enchantment(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Disenchant"]])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=cards["Grizzly Bears"])])
        game = _game(p1, p2)

        result = game.cast_from_hand(
            0, "Disenchant", target_player_index=1, target_permanent_index=0
        )

        assert not result.supported


# ---------------------------------------------------------------------------
# False Orders — "Card was cast at an illegal time"
# ---------------------------------------------------------------------------

class TestFalseOrders:
    def test_cannot_be_cast_outside_declare_blockers(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["False Orders"]])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=cards["Grizzly Bears"])])
        game = _game(p1, p2)
        game._set_phase_and_step("precombat_main", "main")

        result = game.cast_from_hand(0, "False Orders", target_player_index=1)

        assert not result.supported
        assert "declare blockers" in result.details
        assert any(c.name == "False Orders" for c in p1.hand)  # not consumed

    def test_can_be_cast_during_declare_blockers(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["False Orders"]])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=cards["Grizzly Bears"])])
        game = _game(p1, p2)
        game._set_phase_and_step("combat", "declare_blockers")

        result = game.cast_from_hand(0, "False Orders", target_player_index=1)

        assert result.supported
        assert p2.battlefield[0].metadata.get("removed_from_combat") is True


# ---------------------------------------------------------------------------
# Power Leak — "no valid target even though I had an enchantment in play"
# ---------------------------------------------------------------------------

class TestPowerLeak:
    def test_attaches_to_chosen_enchantment_and_deals_upkeep_damage(self, cards):
        target = Permanent(card=cards["Bad Moon"])
        p1 = PlayerState(name="P1", hand=[cards["Power Leak"]])
        p2 = PlayerState(name="P2", battlefield=[target])
        game = _game(p1, p2)

        result = game.cast_from_hand(
            0, "Power Leak", target_player_index=1, target_permanent_index=0
        )

        assert result.supported
        aura = next(
            (p for pl in game.players for p in pl.battlefield if p.card.name == "Power Leak"),
            None,
        )
        assert aura is not None
        assert aura.metadata.get("attached_to") is target

        # At the enchanted enchantment's controller's upkeep it deals 2 damage.
        before = p2.life
        game.resolve_upkeep(1)
        assert p2.life == before - 2

    def test_can_enchant_own_enchantment(self, cards):
        target = Permanent(card=cards["Bad Moon"])
        p1 = PlayerState(name="P1", hand=[cards["Power Leak"]], battlefield=[target])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        result = game.cast_from_hand(
            0, "Power Leak", target_player_index=0, target_permanent_index=0
        )

        assert result.supported


# ---------------------------------------------------------------------------
# Raging River — "When I attacked Raging River's trigger did not activate"
# ---------------------------------------------------------------------------

class TestRagingRiver:
    def test_attack_trigger_fires_on_declare_attackers(self, cards):
        river = Permanent(card=cards["Raging River"])
        attacker = _untapped_assassin(cards["Grizzly Bears"])
        p1 = PlayerState(name="P1", battlefield=[river, attacker])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=cards["Hill Giant"])])
        game = _game(p1, p2)
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        game.combat_defending_player_index = 1

        ok, _ = game.declare_attackers(0, [1], 1)

        assert ok
        # The "whenever one or more creatures you control attack" trigger fired.
        assert river.metadata.get("left_right_division_turn") == game.turn

    def test_no_trigger_without_attackers(self, cards):
        river = Permanent(card=cards["Raging River"])
        p1 = PlayerState(name="P1", battlefield=[river])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        game.combat_defending_player_index = 1

        game.declare_attackers(0, [], 1)

        assert river.metadata.get("left_right_division_turn") is None


# ---------------------------------------------------------------------------
# Royal Assassin — ability must target a tapped creature, not a Mountain
# ---------------------------------------------------------------------------

class TestRoyalAssassin:
    def test_destroys_targeted_tapped_creature(self, cards):
        tapped = Permanent(card=cards["Grizzly Bears"], tapped=True)
        p1 = PlayerState(name="P1", battlefield=[_untapped_assassin(cards["Royal Assassin"])])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=cards["Mountain"]), tapped])
        game = _game(p1, p2)

        game.activate_permanent_ability(
            0, "Royal Assassin", target_player_index=1, target_permanent_index=1, permanent_index=0
        )
        game.resolve_stack()
        game.check_state_based_actions()

        names = [p.card.name for p in p2.battlefield]
        assert "Grizzly Bears" not in names
        assert "Mountain" in names  # untouched

    def test_cannot_destroy_untapped_creature(self, cards):
        untapped = Permanent(card=cards["Grizzly Bears"])  # not tapped
        p1 = PlayerState(name="P1", battlefield=[_untapped_assassin(cards["Royal Assassin"])])
        p2 = PlayerState(name="P2", battlefield=[untapped])
        game = _game(p1, p2)

        game.activate_permanent_ability(
            0, "Royal Assassin", target_player_index=1, target_permanent_index=0, permanent_index=0
        )
        game.resolve_stack()
        game.check_state_based_actions()

        assert any(p.card.name == "Grizzly Bears" for p in p2.battlefield)

    def test_does_not_destroy_a_noncreature(self, cards):
        # The reported bug: the ability destroyed a Mountain (an illegal target).
        mountain = Permanent(card=cards["Mountain"], tapped=True)
        p1 = PlayerState(name="P1", battlefield=[_untapped_assassin(cards["Royal Assassin"])])
        p2 = PlayerState(name="P2", battlefield=[mountain])
        game = _game(p1, p2)

        game.activate_permanent_ability(
            0, "Royal Assassin", target_player_index=1, target_permanent_index=0, permanent_index=0
        )
        game.resolve_stack()
        game.check_state_based_actions()

        assert any(p.card.name == "Mountain" for p in p2.battlefield)


# ---------------------------------------------------------------------------
# Soul Net — triggered ability should fire when a creature dies
# ---------------------------------------------------------------------------

class TestSoulNet:
    def test_gains_life_when_a_creature_dies_and_mana_is_paid(self, cards):
        net = Permanent(card=cards["Soul Net"])
        p1 = PlayerState(name="P1", battlefield=[net])
        p1.mana_pool["C"] = 1
        dying = Permanent(card=cards["Grizzly Bears"])
        p2 = PlayerState(name="P2", battlefield=[dying])
        game = _game(p1, p2)

        before = p1.life
        game._permanent_to_graveyard(p2, dying)

        assert p1.life == before + 1
        assert p1.mana_pool["C"] == 0  # the {1} was paid

    def test_no_life_gain_when_unable_to_pay(self, cards):
        net = Permanent(card=cards["Soul Net"])
        p1 = PlayerState(name="P1", battlefield=[net])  # empty mana pool
        dying = Permanent(card=cards["Grizzly Bears"])
        p2 = PlayerState(name="P2", battlefield=[dying])
        game = _game(p1, p2)

        before = p1.life
        game._permanent_to_graveyard(p2, dying)

        assert p1.life == before


# ---------------------------------------------------------------------------
# Terror — "Terror didn't let me choose a target"
# ---------------------------------------------------------------------------

class TestTerror:
    def test_destroys_chosen_creature(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Terror"]])
        p2 = PlayerState(
            name="P2",
            battlefield=[Permanent(card=cards["Mountain"]), Permanent(card=cards["Grizzly Bears"])],
        )
        game = _game(p1, p2)

        result = game.cast_from_hand(
            0, "Terror", target_player_index=1, target_permanent_index=1
        )

        assert result.supported
        names = [p.card.name for p in p2.battlefield]
        assert "Grizzly Bears" not in names
        assert "Mountain" in names  # only the chosen creature was destroyed

    def test_cannot_target_a_land(self, cards):
        # Regression: with no type filter Terror could be aimed at non-creatures.
        p1 = PlayerState(name="P1", hand=[cards["Terror"]])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=cards["Mountain"])])
        game = _game(p1, p2)

        result = game.cast_from_hand(
            0, "Terror", target_player_index=1, target_permanent_index=0
        )

        assert not result.supported


# ---------------------------------------------------------------------------
# Time Vault — must not auto-untap; may be untapped by skipping a turn
# ---------------------------------------------------------------------------

class TestTimeVault:
    def test_does_not_untap_during_untap_step(self, cards):
        vault = Permanent(card=cards["Time Vault"], tapped=True)
        p1 = PlayerState(name="P1", battlefield=[vault])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        game.resolve_untap_step(0)

        assert vault.tapped is True

    def test_skip_turn_to_untap(self, cards):
        vault = Permanent(card=cards["Time Vault"], tapped=True)
        p1 = PlayerState(name="P1", battlefield=[vault])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        assert game.get_begin_turn_untap_options(0) == ["Time Vault"]
        assert game.skip_turn_to_untap(0, "Time Vault") is True
        assert vault.tapped is False
        assert game.skip_turn_counts.get(0, 0) == 1

    def test_no_skip_option_when_untapped(self, cards):
        vault = Permanent(card=cards["Time Vault"])  # already untapped
        p1 = PlayerState(name="P1", battlefield=[vault])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        assert game.get_begin_turn_untap_options(0) == []
        assert game.skip_turn_to_untap(0, "Time Vault") is False


# ---------------------------------------------------------------------------
# Tunnel — "didn't prompt me to select a target; target needs to be a wall"
# ---------------------------------------------------------------------------

class TestTunnel:
    def test_destroys_a_wall(self, cards):
        wall = next(c for c in cards.values() if c.name.startswith("Wall of"))
        p1 = PlayerState(name="P1", hand=[cards["Tunnel"]])
        p2 = PlayerState(
            name="P2",
            battlefield=[Permanent(card=cards["Grizzly Bears"]), Permanent(card=wall)],
        )
        game = _game(p1, p2)

        result = game.cast_from_hand(
            0, "Tunnel", target_player_index=1, target_permanent_index=1
        )

        assert result.supported
        names = [p.card.name for p in p2.battlefield]
        assert wall.name not in names
        assert "Grizzly Bears" in names  # non-Wall creature untouched

    def test_cannot_target_a_nonwall_creature(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Tunnel"]])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=cards["Grizzly Bears"])])
        game = _game(p1, p2)

        result = game.cast_from_hand(
            0, "Tunnel", target_player_index=1, target_permanent_index=0
        )

        assert not result.supported


def _untapped(card: CardDefinition) -> Permanent:
    perm = Permanent(card=card)
    perm.metadata["summoning_sickness_turn"] = -99  # may tap this turn
    return perm


# ---------------------------------------------------------------------------
# Death Ward — "Says no valid target. I should be able to target any creature"
# ---------------------------------------------------------------------------

class TestDeathWard:
    def test_regenerates_the_chosen_own_creature(self, cards):
        # Reported bug: validation only looked at the opponent's battlefield, so
        # regenerating your own creature was wrongly rejected as "no valid target".
        bears = Permanent(card=cards["Grizzly Bears"])
        p1 = PlayerState(name="P1", hand=[cards["Death Ward"]], battlefield=[bears])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        result = game.cast_from_hand(
            0, "Death Ward", target_player_index=0, target_permanent_index=0
        )
        game.resolve_stack()

        assert result.supported
        assert bears.regeneration_shield == 1

    def test_regenerates_the_specific_chosen_creature(self, cards):
        first = Permanent(card=cards["Grizzly Bears"])
        second = Permanent(card=cards["Hill Giant"])
        p1 = PlayerState(name="P1", hand=[cards["Death Ward"]], battlefield=[first, second])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        game.cast_from_hand(0, "Death Ward", target_player_index=0, target_permanent_index=1)
        game.resolve_stack()

        assert first.regeneration_shield == 0
        assert second.regeneration_shield == 1  # only the chosen creature

    def test_rejected_when_no_creature_anywhere(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Death Ward"]])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        result = game.cast_from_hand(0, "Death Ward", target_player_index=0)

        assert not result.supported


# ---------------------------------------------------------------------------
# Swords to Plowshares — "Doesn't let me choose a target"
# ---------------------------------------------------------------------------

class TestSwordsToPlowshares:
    def test_exiles_chosen_creature_and_controller_gains_life(self, cards):
        bears = Permanent(card=cards["Grizzly Bears"])  # power 2
        mountain = Permanent(card=cards["Mountain"])
        p1 = PlayerState(name="P1", hand=[cards["Swords to Plowshares"]])
        p2 = PlayerState(name="P2", battlefield=[mountain, bears])
        game = _game(p1, p2)
        before = p2.life

        result = game.cast_from_hand(
            0, "Swords to Plowshares", target_player_index=1, target_permanent_index=1
        )
        game.resolve_stack()

        assert result.supported
        names = [p.card.name for p in p2.battlefield]
        assert "Grizzly Bears" not in names
        assert "Mountain" in names  # only the chosen creature was exiled
        assert any(c.name == "Grizzly Bears" for c in p2.exile)
        assert p2.life == before + 2  # its controller gains life equal to its power

    def test_can_target_own_creature(self, cards):
        bears = Permanent(card=cards["Grizzly Bears"])
        p1 = PlayerState(name="P1", hand=[cards["Swords to Plowshares"]], battlefield=[bears])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        before = p1.life

        result = game.cast_from_hand(
            0, "Swords to Plowshares", target_player_index=0, target_permanent_index=0
        )
        game.resolve_stack()

        assert result.supported
        assert not p1.battlefield
        assert p1.life == before + 2

    def test_cannot_target_a_land(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Swords to Plowshares"]])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=cards["Mountain"])])
        game = _game(p1, p2)

        result = game.cast_from_hand(
            0, "Swords to Plowshares", target_player_index=1, target_permanent_index=0
        )

        assert not result.supported


# ---------------------------------------------------------------------------
# Ley Druid — "ability doesn't prompt me to choose a land"
# ---------------------------------------------------------------------------

class TestLeyDruid:
    def test_untaps_the_chosen_land(self, cards):
        forest = Permanent(card=cards["Forest"], tapped=True)
        island = Permanent(card=cards["Island"], tapped=True)
        druid = _untapped(cards["Ley Druid"])
        p1 = PlayerState(name="P1", battlefield=[druid, forest, island])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        result = game.activate_permanent_ability(
            0, "Ley Druid", target_player_index=0, target_permanent_index=2, permanent_index=0
        )

        assert result.supported
        assert island.tapped is False  # the chosen land
        assert forest.tapped is True   # untouched

    def test_can_untap_opponents_land(self, cards):
        opp_land = Permanent(card=cards["Forest"], tapped=True)
        druid = _untapped(cards["Ley Druid"])
        p1 = PlayerState(name="P1", battlefield=[druid])
        p2 = PlayerState(name="P2", battlefield=[opp_land])
        game = _game(p1, p2)

        game.activate_permanent_ability(
            0, "Ley Druid", target_player_index=1, target_permanent_index=0, permanent_index=0
        )

        assert opp_land.tapped is False


# ---------------------------------------------------------------------------
# Stone Giant — "activated ability doesn't let me choose a target"
# ---------------------------------------------------------------------------

class TestStoneGiant:
    def test_grants_flying_and_delayed_destruction_to_chosen_creature(self, cards):
        giant = _untapped(cards["Stone Giant"])  # power 3
        bears = Permanent(card=cards["Grizzly Bears"])  # toughness 2 < 3
        sprites = Permanent(card=cards["Scryb Sprites"])  # toughness 1 < 3
        p1 = PlayerState(name="P1", battlefield=[giant, bears, sprites])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        result = game.activate_permanent_ability(
            0, "Stone Giant", target_player_index=0, target_permanent_index=2, permanent_index=0
        )

        assert result.supported
        assert sprites.metadata.get("gains_flying_until_eot") is True
        assert sprites.metadata.get("destroy_at_next_end_step") is True
        assert bears.metadata.get("gains_flying_until_eot") is not True  # not the chosen one

    def test_cannot_target_creature_with_toughness_at_least_power(self, cards):
        giant = _untapped(cards["Stone Giant"])  # power 3
        big = Permanent(card=cards["Hill Giant"])  # toughness 3, not < 3
        p1 = PlayerState(name="P1", battlefield=[giant, big])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        game.activate_permanent_ability(
            0, "Stone Giant", target_player_index=0, target_permanent_index=1, permanent_index=0
        )

        assert big.metadata.get("gains_flying_until_eot") is not True


# ---------------------------------------------------------------------------
# Deathgrip — "should let me choose a target green spell rather than auto targeting"
# ---------------------------------------------------------------------------

class TestDeathgrip:
    def test_counters_the_chosen_green_spell(self, cards):
        grip = Permanent(card=cards["Deathgrip"])
        p1 = PlayerState(name="P1", battlefield=[grip])
        p1.mana_pool["B"] = 2
        p2 = PlayerState(
            name="P2",
            hand=[cards["Lightning Bolt"], cards["Giant Growth"]],
            battlefield=[Permanent(card=cards["Grizzly Bears"])],
        )
        game = _game(p1, p2)

        game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
        game.queue_from_hand(1, "Giant Growth", target_player_index=1, target_permanent_index=0)
        green_index = next(i for i, s in enumerate(game.stack) if s.card.name == "Giant Growth")

        result = game.queue_permanent_ability(
            0, "Deathgrip", permanent_index=0, target_stack_index=green_index
        )
        assert result.supported
        game.resolve_stack()

        # The chosen green spell was countered (put into its owner's graveyard).
        assert any(c.name == "Giant Growth" for c in p2.graveyard)

    def test_cannot_counter_a_nongreen_spell(self, cards):
        grip = Permanent(card=cards["Deathgrip"])
        p1 = PlayerState(name="P1", battlefield=[grip])
        p1.mana_pool["B"] = 2
        p2 = PlayerState(name="P2", hand=[cards["Lightning Bolt"]])
        game = _game(p1, p2)

        game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
        bolt_index = next(i for i, s in enumerate(game.stack) if s.card.name == "Lightning Bolt")

        result = game.queue_permanent_ability(
            0, "Deathgrip", permanent_index=0, target_stack_index=bolt_index
        )

        assert not result.supported  # red spell is not a legal target


# ---------------------------------------------------------------------------
# Copy Artifact — "Didn't let me choose an artifact when it entered"
# ---------------------------------------------------------------------------

class TestCopyArtifact:
    def test_enters_as_copy_of_chosen_artifact(self, cards):
        lotus = Permanent(card=cards["Black Lotus"])
        sol_ring = Permanent(card=cards["Sol Ring"])
        p1 = PlayerState(name="P1", hand=[cards["Copy Artifact"]], battlefield=[lotus])
        p2 = PlayerState(name="P2", battlefield=[sol_ring])
        game = _game(p1, p2)

        # Choose the opponent's Sol Ring rather than the nearest artifact.
        result = game.cast_from_hand(
            0, "Copy Artifact", target_player_index=1, target_permanent_index=0
        )
        game.resolve_stack()

        assert result.supported
        copy = next(p for p in p1.battlefield if p.card.name == "Copy Artifact")
        assert copy.metadata.get("copied_from") == "Sol Ring"


# ---------------------------------------------------------------------------
# Lich — "I lose the game when I play this even though I shouldn't"
# ---------------------------------------------------------------------------

class TestLich:
    def test_does_not_lose_the_game_at_zero_life(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Lich"]])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        result = game.cast_from_hand(0, "Lich")
        game.resolve_stack()
        game.check_state_based_actions()

        assert result.supported
        assert p1.life <= 0          # paid all life on entry
        assert p1.lost is False      # but the replacement keeps P1 in the game

    def test_web_winner_honors_lich_replacement(self, cards):
        # The reported in-game loss came from the web winner check using raw life
        # totals; it must honor Lich's "you don't lose the game" replacement.
        from web.app import _player_has_lost

        p1 = PlayerState(name="P1", hand=[cards["Lich"]])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.cast_from_hand(0, "Lich")
        game.resolve_stack()
        game.check_state_based_actions()

        assert _player_has_lost(game, 0) is False

    def test_player_at_zero_without_lich_still_loses(self, cards):
        from web.app import _player_has_lost

        p1 = PlayerState(name="P1", life=0)
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.check_state_based_actions()

        assert _player_has_lost(game, 0) is True


# ---------------------------------------------------------------------------
# Lifelace — "When a card changes color it should display it as a label"
# ---------------------------------------------------------------------------

class TestLifelace:
    def test_recolors_chosen_permanent_to_green(self, cards):
        target = Permanent(card=cards["Grizzly Bears"])
        p1 = PlayerState(name="P1", hand=[cards["Lifelace"]])
        p2 = PlayerState(name="P2", battlefield=[target])
        game = _game(p1, p2)

        result = game.cast_from_hand(
            0, "Lifelace", target_player_index=1, target_permanent_index=0
        )
        game.resolve_stack()

        assert result.supported
        # The new color is recorded so the UI can render a "Color: {G}" label.
        assert target.metadata.get("color_override") == "G"

    def test_recolored_permanent_is_serialized_with_color_override(self, cards):
        from web.app import _serialize_permanent

        target = Permanent(card=cards["Grizzly Bears"])
        target.metadata["color_override"] = "G"
        p1 = PlayerState(name="P1", battlefield=[target])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        data = _serialize_permanent(target, game)
        assert data["color_override"] == "G"


# ---------------------------------------------------------------------------
# Wanderlust — "upkeep trigger isn't working"
# ---------------------------------------------------------------------------

class TestWanderlust:
    def test_deals_one_damage_to_enchanted_creatures_controller_on_upkeep(self, cards):
        creature = Permanent(card=cards["Grizzly Bears"])
        aura = Permanent(card=cards["Wanderlust"])
        aura.metadata["attached_to"] = creature
        creature.metadata["attached_aura"] = aura
        p1 = PlayerState(name="P1")
        p2 = PlayerState(name="P2", battlefield=[creature, aura])
        game = _game(p1, p2)

        before = p2.life
        game.resolve_upkeep(1)  # P2's upkeep (the enchanted creature's controller)

        assert p2.life == before - 1

    def test_no_damage_on_other_players_upkeep(self, cards):
        creature = Permanent(card=cards["Grizzly Bears"])
        aura = Permanent(card=cards["Wanderlust"])
        aura.metadata["attached_to"] = creature
        creature.metadata["attached_aura"] = aura
        p1 = PlayerState(name="P1")
        p2 = PlayerState(name="P2", battlefield=[creature, aura])
        game = _game(p1, p2)

        before = p2.life
        game.resolve_upkeep(0)  # P1's upkeep — Wanderlust should not fire

        assert p2.life == before
