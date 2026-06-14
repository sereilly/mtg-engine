"""Regression tests for the third batch of cards reported FAILED in-game.

Each test documents a bug reported through the in-game Debug Menu verification
flow and guards the rules-correct behavior after the fix. Tests load the real
Alpha (LEA) card definitions so they exercise the actual oracle text, parse
rules, and handlers.

Cards covered: Glasses of Urza, Goblin King, Lich, Magical Hack, Orcish
Artillery, Orcish Oriflamme, Power Surge, Simulacrum, Unsummon.
"""
from __future__ import annotations

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


def _nosick(perm: Permanent) -> Permanent:
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


# ---------------------------------------------------------------------------
# Glasses of Urza — "doesn't do anything; should show the opponent's hand"
# ---------------------------------------------------------------------------

class TestGlassesOfUrza:
    def test_tapping_records_a_reveal_of_target_players_hand(self, cards):
        glasses = _nosick(Permanent(card=cards["Glasses of Urza"]))
        p1 = PlayerState(name="P1", battlefield=[glasses])
        p2 = PlayerState(name="P2", hand=[cards["Hill Giant"], cards["Lightning Bolt"]])
        game = _game(p1, p2)

        result = game.activate_permanent_ability(
            0, "Glasses of Urza", target_player_index=1, permanent_index=0
        )

        assert result.supported
        reveal = game.pending_hand_reveal
        assert reveal is not None
        assert reveal["viewer_index"] == 0
        assert reveal["target_index"] == 1
        assert reveal["card_names"] == ["Hill Giant", "Lightning Bolt"]
        # Looking is not destructive: the hand is unchanged.
        assert [c.name for c in p2.hand] == ["Hill Giant", "Lightning Bolt"]


# ---------------------------------------------------------------------------
# Goblin King — "didn't give mountainwalk to my other goblins"
# ---------------------------------------------------------------------------

class TestGoblinKing:
    def _setup(self, cards):
        king = _nosick(Permanent(card=cards["Goblin King"]))
        raider = _nosick(Permanent(card=cards["Mons's Goblin Raiders"]))
        blocker = _nosick(Permanent(card=cards["Grizzly Bears"]))
        p1 = PlayerState(name="P1", battlefield=[king, raider])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=cards["Mountain"]), blocker])
        game = _game(p1, p2)
        game._apply_global_buff(p1, cards["Goblin King"])
        return game, p1, p2, raider, blocker

    def test_other_goblins_gain_mountainwalk_metadata(self, cards):
        game, p1, p2, raider, blocker = self._setup(cards)
        assert raider.metadata.get("has_mountainwalk") is True

    def test_mountainwalker_is_unblockable_when_defender_controls_a_mountain(self, cards):
        game, p1, p2, raider, blocker = self._setup(cards)
        # P2 controls a Mountain, so the Goblin can't be blocked (CR 702.14).
        assert game._can_block_attacker(blocker, raider) is False

    def test_mountainwalk_irrelevant_without_a_mountain(self, cards):
        king = _nosick(Permanent(card=cards["Goblin King"]))
        raider = _nosick(Permanent(card=cards["Mons's Goblin Raiders"]))
        blocker = _nosick(Permanent(card=cards["Grizzly Bears"]))
        p1 = PlayerState(name="P1", battlefield=[king, raider])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=cards["Forest"]), blocker])
        game = _game(p1, p2)
        game._apply_global_buff(p1, cards["Goblin King"])
        # No Mountain on defender's side: the Goblin is blockable normally.
        assert game._can_block_attacker(blocker, raider) is True

    def test_declare_blockers_rejects_blocking_the_mountainwalker(self, cards):
        game, p1, p2, raider, blocker = self._setup(cards)
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        ok, _ = game.declare_attackers(0, [0, 1], defending_player_index=1)
        assert ok
        game._set_phase_and_step("combat", "declare_blockers")
        # Blocker (index 1) tries to block the raider (attacker index 1) — illegal.
        ok, _ = game.declare_blockers(1, {1: 1})
        assert ok is False


# ---------------------------------------------------------------------------
# Lich — "killed me when I played it even though I don't lose for 0 life"
# ---------------------------------------------------------------------------

class TestLich:
    def test_playing_lich_does_not_lose_the_game_at_zero_life(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Lich"]], life=20)
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        result = game.cast_from_hand(0, "Lich")

        assert result.supported
        # Loses life equal to life total (20 -> 0) but stays in the game.
        assert p1.life == 0
        assert p1.lost is False
        assert any(perm.card.name == "Lich" for perm in p1.battlefield)

    def test_zero_life_with_lich_survives_repeated_sba_checks(self, cards):
        lich = Permanent(card=cards["Lich"])
        p1 = PlayerState(name="P1", battlefield=[lich], life=0)
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        game.check_state_based_actions()
        game.check_state_based_actions()

        assert p1.lost is False

    def test_player_loses_once_lich_leaves_with_zero_life(self, cards):
        lich = Permanent(card=cards["Lich"])
        p1 = PlayerState(name="P1", battlefield=[lich], life=0)
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.check_state_based_actions()
        assert p1.lost is False

        # Lich is gone — the "don't lose for 0 life" replacement no longer applies.
        p1.battlefield = []
        game.check_state_based_actions()
        assert p1.lost is True


# ---------------------------------------------------------------------------
# Magical Hack — "didn't change my land's type / mana"
# ---------------------------------------------------------------------------

class TestMagicalHack:
    def test_changes_a_forest_into_an_island_producing_blue(self, cards):
        forest = Permanent(card=cards["Forest"])
        p1 = PlayerState(name="P1", hand=[cards["Magical Hack"]])
        p2 = PlayerState(name="P2", battlefield=[forest])
        game = _game(p1, p2)

        result = game.cast_from_hand(
            0, "Magical Hack", target_player_index=1, target_permanent_index=0, new_color="U"
        )

        assert result.supported
        assert forest.metadata.get("land_type_override") == "island"
        # The land now taps for blue, not green (CR 305.7).
        assert forest.effective_produced_mana == ("U",)
        game.tap_land_for_mana(1, "Forest", chosen_color="G", permanent_index=0)
        assert p2.mana_pool["U"] == 1
        assert p2.mana_pool["G"] == 0


# ---------------------------------------------------------------------------
# Orcish Artillery — "the activated ability didn't let me choose any target"
# ---------------------------------------------------------------------------

class TestOrcishArtillery:
    def test_ability_deals_two_to_target_creature_and_three_to_controller(self, cards):
        artillery = _nosick(Permanent(card=cards["Orcish Artillery"]))
        target = Permanent(card=cards["Grizzly Bears"])  # 2/2
        p1 = PlayerState(name="P1", battlefield=[artillery], life=20)
        p2 = PlayerState(name="P2", battlefield=[target], life=20)
        game = _game(p1, p2)

        result = game.activate_permanent_ability(
            0, "Orcish Artillery", target_player_index=1, permanent_index=0,
            target_permanent_index=0,
        )

        assert result.supported
        # 2 damage kills the 2/2; 3 self-damage to the controller.
        assert target not in p2.battlefield
        assert p1.life == 17

    def test_ability_can_target_a_player(self, cards):
        artillery = _nosick(Permanent(card=cards["Orcish Artillery"]))
        p1 = PlayerState(name="P1", battlefield=[artillery], life=20)
        p2 = PlayerState(name="P2", life=20)
        game = _game(p1, p2)

        result = game.activate_permanent_ability(
            0, "Orcish Artillery", target_player_index=1, permanent_index=0
        )

        assert result.supported
        assert p2.life == 18  # 2 to the opponent's face
        assert p1.life == 17  # 3 to self


# ---------------------------------------------------------------------------
# Orcish Oriflamme — "should only buff creatures declared as attackers"
# ---------------------------------------------------------------------------

class TestOrcishOriflamme:
    def test_only_attacking_creatures_get_the_bonus(self, cards):
        oriflamme = Permanent(card=cards["Orcish Oriflamme"])
        attacker = _nosick(Permanent(card=cards["Grizzly Bears"]))  # 2/2
        idle = _nosick(Permanent(card=cards["Hill Giant"]))  # 3/3, stays back
        p1 = PlayerState(name="P1", battlefield=[oriflamme, attacker, idle])
        p2 = PlayerState(name="P2", life=20)
        game = _game(p1, p2)
        game._apply_global_buff(p1, cards["Orcish Oriflamme"])

        # Before combat: nobody is buffed.
        assert attacker.effective_power == 2
        assert idle.effective_power == 3

        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        ok, _ = game.declare_attackers(0, [1], defending_player_index=1)
        assert ok

        # Only the declared attacker gets +1/+0; the idle creature is unchanged.
        assert attacker.effective_power == 3
        assert idle.effective_power == 3


# ---------------------------------------------------------------------------
# Power Surge — X = "untapped lands they controlled at the beginning of this
# turn", measured *before* the untap step. Lands tapped going into the turn are
# not counted (the reported "no damage from tapped lands" is correct behavior);
# lands left untapped going into the turn are.
# ---------------------------------------------------------------------------

class TestPowerSurge:
    def test_only_lands_untapped_at_the_beginning_of_the_turn_deal_damage(self, cards):
        surge = Permanent(card=cards["Power Surge"])
        untapped_land = Permanent(card=cards["Island"])  # open going into the turn
        tapped_land = Permanent(card=cards["Island"]); tapped_land.tapped = True  # tapped out
        p1 = PlayerState(name="P1", battlefield=[surge])
        p2 = PlayerState(name="P2", battlefield=[untapped_land, tapped_land], life=20)
        game = _game(p1, p2)

        game.resolve_untap_step(1)
        # Counted before the untap step: only the land that was untapped counts,
        # even though the tapped land untaps during the step.
        assert game.untapped_lands_at_turn_start[1] == 1
        game.resolve_upkeep(1)

        assert p2.life == 19

    def test_tapping_out_before_your_turn_avoids_the_damage(self, cards):
        surge = Permanent(card=cards["Power Surge"])
        land_a = Permanent(card=cards["Island"]); land_a.tapped = True
        land_b = Permanent(card=cards["Island"]); land_b.tapped = True
        p1 = PlayerState(name="P1", battlefield=[surge])
        p2 = PlayerState(name="P2", battlefield=[land_a, land_b], life=20)
        game = _game(p1, p2)

        game.resolve_untap_step(1)
        assert game.untapped_lands_at_turn_start[1] == 0
        game.resolve_upkeep(1)

        assert p2.life == 20


# ---------------------------------------------------------------------------
# Simulacrum — "killed my own creature when I targeted the opponent's"
# ---------------------------------------------------------------------------

class TestSimulacrum:
    def test_cannot_target_an_opponents_creature(self, cards):
        mine = Permanent(card=cards["Hill Giant"])
        theirs = Permanent(card=cards["Grizzly Bears"])
        p1 = PlayerState(name="P1", hand=[cards["Simulacrum"]], battlefield=[mine], life=16)
        p2 = PlayerState(name="P2", battlefield=[theirs])
        game = _game(p1, p2)
        game._deal_damage_to_player(p1, 4)

        # Targeting the opponent's creature is illegal ("target creature you control").
        result = game.cast_from_hand(
            0, "Simulacrum", target_player_index=1, target_permanent_index=0
        )

        assert not result.supported
        # The illegal cast did not kill the caster's own creature.
        assert mine in p1.battlefield
        assert theirs in p2.battlefield


# ---------------------------------------------------------------------------
# Unsummon — "couldn't cast it / didn't let me choose / defaulted to opponent"
# ---------------------------------------------------------------------------

class TestUnsummon:
    def test_can_target_a_creature_you_control(self, cards):
        mine = Permanent(card=cards["Hill Giant"])
        p1 = PlayerState(name="P1", hand=[cards["Unsummon"]], battlefield=[mine])
        p2 = PlayerState(name="P2")  # opponent controls no creatures
        game = _game(p1, p2)

        result = game.cast_from_hand(
            0, "Unsummon", target_player_index=0, target_permanent_index=0
        )

        assert result.supported
        assert mine not in p1.battlefield
        assert any(c.name == "Hill Giant" for c in p1.hand)

    def test_returns_the_chosen_opponent_creature_to_its_owners_hand(self, cards):
        theirs = Permanent(card=cards["Grizzly Bears"])
        p1 = PlayerState(name="P1", hand=[cards["Unsummon"]])
        p2 = PlayerState(name="P2", battlefield=[theirs])
        game = _game(p1, p2)

        result = game.cast_from_hand(
            0, "Unsummon", target_player_index=1, target_permanent_index=0
        )

        assert result.supported
        assert theirs not in p2.battlefield
        assert any(c.name == "Grizzly Bears" for c in p2.hand)

    def test_illegal_when_no_creatures_exist(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Unsummon"]])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        result = game.cast_from_hand(0, "Unsummon", target_player_index=1)

        assert not result.supported
