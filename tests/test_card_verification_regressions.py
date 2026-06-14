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
