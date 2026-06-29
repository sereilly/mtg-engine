"""Regression tests for the fifth batch of cards reported FAILED in-game.

Each test documents a bug reported through the in-game Debug Menu verification
flow (recorded in CARD_VERIFICATION.md) and guards the rules-correct behavior
after the fix. Tests load the real Alpha (LEA) card definitions so they exercise
the actual oracle text, parse rules, handlers, and continuous-effect logic.

Cards covered: Blessing, Firebreathing, Kormus Bell, Living Lands, Conversion,
Disintegrate, Feedback, Sengir Vampire, Warp Artifact, Kudzu, Volcanic Eruption,
Power Leak, Iron Star, Northern Paladin, Righteousness, Jade Monolith,
Animate Wall, Magical Hack, Thoughtlace, Animate Dead.
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
# Blessing / Firebreathing — "should only buff when I use the ability, not when
# I attach the aura."  An activated "{cost}: Enchanted creature gets +X/+Y until
# end of turn" must NOT be applied on attachment.
# ---------------------------------------------------------------------------

class TestBlessing:
    def test_attaching_does_not_buff(self, cards):
        bear = Permanent(card=cards["Grizzly Bears"])  # 2/2
        p1 = PlayerState(name="P1", hand=[cards["Blessing"]], battlefield=[bear])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.cast_from_hand(0, "Blessing", target_player_index=0, target_permanent_index=0)
        assert (bear.effective_power, bear.effective_toughness) == (2, 2)

    def test_activating_grants_the_buff(self, cards):
        bear = Permanent(card=cards["Grizzly Bears"])
        p1 = PlayerState(name="P1", hand=[cards["Blessing"]], battlefield=[bear])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.cast_from_hand(0, "Blessing", target_player_index=0, target_permanent_index=0)
        result = game.activate_permanent_ability(0, "Blessing", permanent_index=1)
        assert result.supported
        assert (bear.effective_power, bear.effective_toughness) == (3, 3)


class TestFirebreathing:
    def test_attaching_does_not_buff(self, cards):
        bear = Permanent(card=cards["Grizzly Bears"])
        p1 = PlayerState(name="P1", hand=[cards["Firebreathing"]], battlefield=[bear])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.cast_from_hand(0, "Firebreathing", target_player_index=0, target_permanent_index=0)
        assert (bear.effective_power, bear.effective_toughness) == (2, 2)

    def test_activating_grants_plus_one_power(self, cards):
        bear = Permanent(card=cards["Grizzly Bears"])
        p1 = PlayerState(name="P1", hand=[cards["Firebreathing"]], battlefield=[bear])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.cast_from_hand(0, "Firebreathing", target_player_index=0, target_permanent_index=0)
        game.activate_permanent_ability(0, "Firebreathing", permanent_index=1)
        assert (bear.effective_power, bear.effective_toughness) == (3, 2)

    def test_static_buff_aura_still_applies_on_attach(self, cards):
        # Holy Strength ("Enchanted creature gets +1/+2.") is a *static* buff and
        # must still apply when attached — the fix only excludes the "until end of
        # turn" activated form.
        bear = Permanent(card=cards["Grizzly Bears"])
        p1 = PlayerState(name="P1", hand=[cards["Holy Strength"]], battlefield=[bear])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.cast_from_hand(0, "Holy Strength", target_player_index=0, target_permanent_index=0)
        assert (bear.effective_power, bear.effective_toughness) == (3, 4)


# ---------------------------------------------------------------------------
# Kormus Bell / Living Lands — "I'm not able to attack with my lands."
# Animated basic lands are 1/1 creatures and may attack.
# ---------------------------------------------------------------------------

class TestKormusBell:
    def test_animated_swamp_can_attack(self, cards):
        swamp = _nosick(Permanent(card=cards["Swamp"]))
        bell = Permanent(card=cards["Kormus Bell"])
        p1 = PlayerState(name="P1", battlefield=[bell, swamp])
        p2 = PlayerState(name="P2", life=20)
        game = _game(p1, p2)
        game._refresh_dynamic_creatures()
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        game.combat_defending_player_index = 1

        ok, _ = game.declare_attackers(0, [1], 1)
        assert ok
        assert swamp.metadata.get("land_animated") is True
        assert (swamp.effective_power, swamp.effective_toughness) == (1, 1)

    def test_lands_revert_when_source_leaves(self, cards):
        swamp = _nosick(Permanent(card=cards["Swamp"]))
        bell = Permanent(card=cards["Kormus Bell"])
        p1 = PlayerState(name="P1", battlefield=[bell, swamp])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game._refresh_dynamic_creatures()
        assert swamp.metadata.get("land_animated") is True

        p1.battlefield.remove(bell)
        game._refresh_dynamic_creatures()
        assert swamp.metadata.get("land_animated") is not True


class TestLivingLands:
    def test_animated_forest_can_attack(self, cards):
        forest = _nosick(Permanent(card=cards["Forest"]))
        lands = Permanent(card=cards["Living Lands"])
        p1 = PlayerState(name="P1", battlefield=[lands, forest])
        p2 = PlayerState(name="P2", life=20)
        game = _game(p1, p2)
        game._refresh_dynamic_creatures()
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        game.combat_defending_player_index = 1

        ok, _ = game.declare_attackers(0, [1], 1)
        assert ok
        assert (forest.effective_power, forest.effective_toughness) == (1, 1)


# ---------------------------------------------------------------------------
# Conversion — "Card doesn't work." All Mountains are Plains while it is in play.
# ---------------------------------------------------------------------------

class TestConversion:
    def test_mountains_become_plains_and_revert(self, cards):
        mountain = Permanent(card=cards["Mountain"])
        p1 = PlayerState(name="P1", hand=[cards["Conversion"]], battlefield=[mountain])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        game.cast_from_hand(0, "Conversion", target_player_index=0)
        assert mountain.metadata.get("land_type_override") == "plains"

        # It now taps for white.
        game.tap_land_for_mana(0, "Mountain", chosen_color="W", permanent_index=0)
        assert p1.mana_pool.get("W", 0) == 1

        conversion = next(p for p in p1.battlefield if p.card.name == "Conversion")
        p1.battlefield.remove(conversion)
        game._refresh_dynamic_creatures()
        assert mountain.metadata.get("land_type_override") is None


# ---------------------------------------------------------------------------
# Disintegrate — "should put the target in exile if it dies this turn, not the
# graveyard." It also can't be regenerated.
# ---------------------------------------------------------------------------

class TestDisintegrate:
    def test_lethal_target_is_exiled_not_buried(self, cards):
        bear = Permanent(card=cards["Grizzly Bears"])  # 2/2
        p1 = PlayerState(name="P1", hand=[cards["Disintegrate"]])
        p2 = PlayerState(name="P2", battlefield=[bear])
        game = _game(p1, p2)

        result = game.cast_from_hand(
            0, "Disintegrate", target_player_index=1, target_permanent_index=0, x_value=2
        )
        game.resolve_stack()

        assert result.supported
        assert bear not in p2.battlefield
        assert any(c.name == "Grizzly Bears" for c in p2.exile)
        assert not any(c.name == "Grizzly Bears" for c in p2.graveyard)

    def test_cannot_be_regenerated(self, cards):
        bear = Permanent(card=cards["Grizzly Bears"])
        bear.regeneration_shield = 1
        p1 = PlayerState(name="P1", hand=[cards["Disintegrate"]])
        p2 = PlayerState(name="P2", battlefield=[bear])
        game = _game(p1, p2)

        game.cast_from_hand(
            0, "Disintegrate", target_player_index=1, target_permanent_index=0, x_value=2
        )
        game.resolve_stack()

        # The regeneration shield did not save it; it was exiled.
        assert any(c.name == "Grizzly Bears" for c in p2.exile)
        assert bear not in p2.battlefield

    def test_can_deal_damage_to_a_player(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Disintegrate"]])
        p2 = PlayerState(name="P2", life=20)
        game = _game(p1, p2)
        game.cast_from_hand(0, "Disintegrate", target_player_index=1, x_value=3)
        game.resolve_stack()
        assert p2.life == 17


# ---------------------------------------------------------------------------
# Feedback — "I had multiple Feedbacks in play but only 1 of them triggered."
# Each Aura is a separate permanent and triggers independently.
# ---------------------------------------------------------------------------

class TestFeedback:
    def test_each_copy_deals_its_own_damage(self, cards):
        e1 = Permanent(card=cards["Castle"])
        e2 = Permanent(card=cards["Crusade"])
        p1 = PlayerState(name="P1", hand=[cards["Feedback"], cards["Feedback"]], life=20)
        p2 = PlayerState(name="P2", battlefield=[e1, e2], life=20)
        game = _game(p1, p2)

        game.cast_from_hand(0, "Feedback", target_player_index=1, target_permanent_index=0)
        game.cast_from_hand(0, "Feedback", target_player_index=1, target_permanent_index=1)

        game.active_player_index = 1
        game.resolve_upkeep(1)
        assert p2.life == 18  # two Feedbacks each deal 1

    def test_two_copies_on_the_same_enchantment_both_trigger(self, cards):
        target = Permanent(card=cards["Castle"])
        p1 = PlayerState(name="P1", hand=[cards["Feedback"], cards["Feedback"]], life=20)
        p2 = PlayerState(name="P2", battlefield=[target], life=20)
        game = _game(p1, p2)

        game.cast_from_hand(0, "Feedback", target_player_index=1, target_permanent_index=0)
        game.cast_from_hand(0, "Feedback", target_player_index=1, target_permanent_index=0)

        game.active_player_index = 1
        game.resolve_upkeep(1)
        assert p2.life == 18


# ---------------------------------------------------------------------------
# Sengir Vampire — "I didn't get a +1/+1 counter for blocking and killing a
# creature."  The death-of-a-damaged-creature trigger adds a +1/+1 counter.
# ---------------------------------------------------------------------------

class TestSengirVampire:
    def _combat(self, game, attacker_seat, blocker_seat, blocker_map):
        game.active_player_index = attacker_seat
        game._set_phase_and_step("combat", "declare_attackers")
        game.combat_defending_player_index = blocker_seat

    def test_counter_added_when_blocked_attacker_it_killed_dies(self, cards):
        sengir = _nosick(Permanent(card=cards["Sengir Vampire"]))  # 4/4 flier
        giant = _nosick(Permanent(card=cards["Hill Giant"]))  # 3/3
        p1 = PlayerState(name="P1", battlefield=[sengir])
        p2 = PlayerState(name="P2", battlefield=[giant])
        game = _game(p1, p2)

        # P2 attacks with the Hill Giant; Sengir blocks it.
        game.active_player_index = 1
        game._set_phase_and_step("combat", "declare_attackers")
        game.combat_defending_player_index = 0
        game.declare_attackers(1, [0], 0)
        game._set_phase_and_step("combat", "declare_blockers")
        game.declare_blockers(0, {0: 0})
        game._set_phase_and_step("combat", "combat_damage")
        game.resolve_combat_damage(1)
        # The dies-trigger (Sengir's +1/+1 counter) goes on the stack after combat
        # damage and resolves when priority passes (CR 603.3).
        game.resolve_stack()

        assert giant not in p2.battlefield  # Sengir killed it
        assert (sengir.effective_power, sengir.effective_toughness) == (5, 5)

    def test_no_counter_when_no_creature_it_damaged_dies(self, cards):
        sengir = _nosick(Permanent(card=cards["Sengir Vampire"]))
        p1 = PlayerState(name="P1", battlefield=[sengir])
        p2 = PlayerState(name="P2", life=20)
        game = _game(p1, p2)
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        game.combat_defending_player_index = 1
        game.declare_attackers(0, [0], 1)
        game._set_phase_and_step("combat", "combat_damage")
        game.resolve_combat_damage(0)
        assert (sengir.effective_power, sengir.effective_toughness) == (4, 4)


# ---------------------------------------------------------------------------
# Warp Artifact — "doesn't get attached to the artifact and is instead put in the
# graveyard."  The Aura attaches to the chosen artifact and deals upkeep damage.
# ---------------------------------------------------------------------------

class TestWarpArtifact:
    def test_attaches_to_chosen_artifact_and_deals_upkeep_damage(self, cards):
        artifact = Permanent(card=cards["Black Lotus"])
        p1 = PlayerState(name="P1", hand=[cards["Warp Artifact"]], life=20)
        p2 = PlayerState(name="P2", battlefield=[artifact], life=20)
        game = _game(p1, p2)

        result = game.cast_from_hand(
            0, "Warp Artifact", target_player_index=1, target_permanent_index=0
        )

        assert result.supported
        warp = next(
            (p for pl in game.players for p in pl.battlefield if p.card.name == "Warp Artifact"),
            None,
        )
        assert warp is not None
        assert warp.metadata.get("attached_to") is artifact
        assert not any(c.name == "Warp Artifact" for c in p1.graveyard)

        game.active_player_index = 1
        game.resolve_upkeep(1)
        assert p2.life == 19

    def test_requires_an_artifact_target(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Warp Artifact"]])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=cards["Grizzly Bears"])])
        game = _game(p1, p2)
        result = game.cast_from_hand(
            0, "Warp Artifact", target_player_index=1, target_permanent_index=0
        )
        assert not result.supported


# ---------------------------------------------------------------------------
# Kudzu — "Doesn't let me choose a new target when I tap the enchanted land."
# ---------------------------------------------------------------------------

class TestKudzu:
    def test_reattaches_to_the_chosen_land_when_tapped(self, cards):
        forest = Permanent(card=cards["Forest"])
        island = Permanent(card=cards["Island"])
        plains = Permanent(card=cards["Plains"])
        p1 = PlayerState(name="P1", hand=[cards["Kudzu"]], battlefield=[forest, island, plains])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        game.cast_from_hand(0, "Kudzu", target_player_index=0, target_permanent_index=0)
        kudzu = next(p for p in p1.battlefield if p.card.name == "Kudzu")
        assert kudzu.metadata.get("attached_to") is forest

        # Tap the Forest; choose to re-attach to the Plains (index 1 after the
        # Forest is removed: battlefield becomes [Island, Plains, Kudzu]).
        game.tap_land_for_mana(0, "Forest", chosen_color="G", permanent_index=0, kudzu_reattach_index=1)
        assert not any(p.card.name == "Forest" for p in p1.battlefield)
        assert kudzu.metadata.get("attached_to") is plains


# ---------------------------------------------------------------------------
# Volcanic Eruption — "Card doesn't deal damage or let me choose mountains to
# destroy."
# ---------------------------------------------------------------------------

class TestVolcanicEruption:
    def test_destroys_chosen_mountains_and_deals_damage(self, cards):
        m1 = Permanent(card=cards["Mountain"])
        m2 = Permanent(card=cards["Mountain"])
        m3 = Permanent(card=cards["Mountain"])
        bear = Permanent(card=cards["Grizzly Bears"])  # 2/2
        p1 = PlayerState(name="P1", hand=[cards["Volcanic Eruption"]], life=20, battlefield=[bear])
        p2 = PlayerState(name="P2", life=20, battlefield=[m1, m2, m3])
        game = _game(p1, p2)

        result = game.cast_from_hand(
            0, "Volcanic Eruption", target_player_index=1, target_permanent_index=[0, 1], x_value=2
        )
        game.resolve_stack()

        assert result.supported
        assert sum(1 for p in p2.battlefield if p.card.name == "Mountain") == 1
        # 2 Mountains destroyed -> 2 damage to each player and creature.
        assert p1.life == 18 and p2.life == 18
        assert bear not in p1.battlefield


# ---------------------------------------------------------------------------
# Power Leak — "I didn't get a prompt to pay any amount of mana to negate the
# damage from Power Leak."
# ---------------------------------------------------------------------------

class TestPowerLeak:
    def test_prevention_trigger_is_surfaced(self, cards):
        target = Permanent(card=cards["Bad Moon"])
        p1 = PlayerState(name="P1", hand=[cards["Power Leak"]])
        p2 = PlayerState(name="P2", battlefield=[target], life=20)
        game = _game(p1, p2)
        game.cast_from_hand(0, "Power Leak", target_player_index=1, target_permanent_index=0)

        triggers = game.get_upkeep_mana_prevention_triggers(1)
        assert any(t["card_name"] == "Power Leak" and t["damage"] == 2 for t in triggers)

    def test_paying_mana_prevents_that_much_damage(self, cards):
        target = Permanent(card=cards["Bad Moon"])
        p1 = PlayerState(name="P1", hand=[cards["Power Leak"]])
        p2 = PlayerState(name="P2", battlefield=[target], life=20, mana_pool={"B": 3})
        game = _game(p1, p2)
        game.cast_from_hand(0, "Power Leak", target_player_index=1, target_permanent_index=0)
        game.active_player_index = 1

        game.resolve_upkeep(1, mana_prevention={"Power Leak": 2})
        assert p2.life == 20  # all 2 damage prevented

    def test_no_payment_takes_full_damage(self, cards):
        target = Permanent(card=cards["Bad Moon"])
        p1 = PlayerState(name="P1", hand=[cards["Power Leak"]])
        p2 = PlayerState(name="P2", battlefield=[target], life=20)
        game = _game(p1, p2)
        game.cast_from_hand(0, "Power Leak", target_player_index=1, target_permanent_index=0)
        game.active_player_index = 1
        game.resolve_upkeep(1)
        assert p2.life == 18

    def test_partial_payment_prevents_partial_damage(self, cards):
        target = Permanent(card=cards["Bad Moon"])
        p1 = PlayerState(name="P1", hand=[cards["Power Leak"]])
        p2 = PlayerState(name="P2", battlefield=[target], life=20, mana_pool={"R": 1})
        game = _game(p1, p2)
        game.cast_from_hand(0, "Power Leak", target_player_index=1, target_permanent_index=0)
        game.active_player_index = 1
        game.resolve_upkeep(1, mana_prevention={"Power Leak": 2})
        assert p2.life == 19  # only 1 mana available -> 1 prevented


# ---------------------------------------------------------------------------
# Iron Star — "I can't use Iron Star's triggered ability. It should prompt me to
# use it when a player casts a red spell."  Rules text: "Whenever a player casts a
# red spell, you may pay {1}. If you do, you gain 1 life." The {1} payment is
# required (paid automatically from the pool when able); with no mana, no life.
# ---------------------------------------------------------------------------

class TestIronStar:
    def test_gains_life_when_either_player_casts_a_red_spell(self, cards):
        star = Permanent(card=cards["Iron Star"])
        p1 = PlayerState(name="P1", battlefield=[star], hand=[cards["Lightning Bolt"]], life=20)
        p1.mana_pool["C"] = 1  # available to pay the {1}
        p2 = PlayerState(name="P2", life=20)
        game = _game(p1, p2)
        game.cast_from_hand(0, "Lightning Bolt", target_player_index=1)
        game.resolve_stack()
        game.auto_resolve_pending_optional_pays()  # the controller chooses to pay {1}
        assert p1.life == 21
        assert p1.mana_pool["C"] == 0  # the {1} was paid

        # Opponent casting a red spell also triggers Iron Star for its controller.
        star2 = Permanent(card=cards["Iron Star"])
        p1 = PlayerState(name="P1", battlefield=[star2], life=20)
        p1.mana_pool["C"] = 1
        p2 = PlayerState(name="P2", hand=[cards["Lightning Bolt"]], life=20)
        game = _game(p1, p2)
        game.cast_from_hand(1, "Lightning Bolt", target_player_index=0)
        game.resolve_stack()
        game.auto_resolve_pending_optional_pays()  # the controller chooses to pay {1}
        # P1 took 3 from the bolt but gained 1 from Iron Star (paid {1}).
        assert p1.life == 18

    def test_no_life_when_unable_to_pay(self, cards):
        # Empty mana pool: the optional {1} can't be paid, so no life is gained.
        star = Permanent(card=cards["Iron Star"])
        p1 = PlayerState(name="P1", battlefield=[star], hand=[cards["Lightning Bolt"]], life=20)
        p2 = PlayerState(name="P2", life=20)
        game = _game(p1, p2)
        game.cast_from_hand(0, "Lightning Bolt", target_player_index=1)
        game.resolve_stack()
        assert p1.life == 20

    def test_no_life_on_a_nonred_spell(self, cards):
        star = Permanent(card=cards["Iron Star"])
        p1 = PlayerState(name="P1", battlefield=[star], hand=[cards["Ancestral Recall"]], life=20)
        p1.mana_pool["C"] = 1
        p2 = PlayerState(name="P2", life=20)
        game = _game(p1, p2)
        game.cast_from_hand(0, "Ancestral Recall", target_player_index=0)
        game.resolve_stack()
        assert p1.life == 20


# ---------------------------------------------------------------------------
# Northern Paladin — "Didn't let me choose a target." Its activated ability
# destroys target *black* permanent; a non-black choice is illegal.
# ---------------------------------------------------------------------------

class TestNorthernPaladin:
    def test_destroys_chosen_black_permanent(self, cards):
        paladin = _nosick(Permanent(card=cards["Northern Paladin"]))
        white = Permanent(card=cards["Crusade"])
        black = Permanent(card=cards["Bad Moon"])
        p1 = PlayerState(name="P1", battlefield=[paladin])
        p2 = PlayerState(name="P2", battlefield=[white, black])
        game = _game(p1, p2)

        result = game.activate_permanent_ability(
            0, "Northern Paladin", target_player_index=1, target_permanent_index=1, permanent_index=0
        )
        game.resolve_stack()

        assert result.supported
        assert black not in p2.battlefield
        assert white in p2.battlefield  # only the black permanent is destroyed

    def test_illegal_nonblack_target_is_rejected(self, cards):
        paladin = _nosick(Permanent(card=cards["Northern Paladin"]))
        white = Permanent(card=cards["Crusade"])
        p1 = PlayerState(name="P1", battlefield=[paladin])
        p2 = PlayerState(name="P2", battlefield=[white])
        game = _game(p1, p2)

        result = game.activate_permanent_ability(
            0, "Northern Paladin", target_player_index=1, target_permanent_index=0, permanent_index=0
        )

        assert not result.supported
        assert white in p2.battlefield
        assert paladin.tapped is False  # the ability never paid its tap cost


# ---------------------------------------------------------------------------
# Righteousness — "It doesn't let me choose a target. Also it should only let me
# target blocking creatures."
# ---------------------------------------------------------------------------

class TestRighteousness:
    def _attack_and_block(self, game, p1, p2):
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        game.combat_defending_player_index = 1
        game.declare_attackers(0, [0], 1)
        game._set_phase_and_step("combat", "declare_blockers")
        game.declare_blockers(1, {0: 0})

    def test_pumps_a_blocking_creature(self, cards):
        attacker = _nosick(Permanent(card=cards["Grizzly Bears"]))
        blocker = _nosick(Permanent(card=cards["Hill Giant"]))  # 3/3
        p1 = PlayerState(name="P1", battlefield=[attacker])
        p2 = PlayerState(name="P2", battlefield=[blocker], hand=[cards["Righteousness"]])
        game = _game(p1, p2)
        self._attack_and_block(game, p1, p2)

        result = game.cast_from_hand(
            1, "Righteousness", target_player_index=1, target_permanent_index=0
        )
        game.resolve_stack()

        assert result.supported
        assert (blocker.effective_power, blocker.effective_toughness) == (10, 10)

    def test_cannot_target_a_nonblocking_creature(self, cards):
        bear = _nosick(Permanent(card=cards["Grizzly Bears"]))
        p1 = PlayerState(name="P1", hand=[cards["Righteousness"]], battlefield=[bear])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        result = game.cast_from_hand(
            0, "Righteousness", target_player_index=0, target_permanent_index=0
        )
        assert not result.supported


# ---------------------------------------------------------------------------
# Jade Monolith — "Doesn't let me choose a source (target spell or permanent)."
# The activation chooses which creature's next damage is redirected.
# ---------------------------------------------------------------------------

class TestJadeMonolith:
    def test_redirects_damage_from_the_chosen_creature(self, cards):
        jade = Permanent(card=cards["Jade Monolith"])
        bear_a = Permanent(card=cards["Grizzly Bears"])
        bear_b = Permanent(card=cards["Hill Giant"])
        p1 = PlayerState(
            name="P1", battlefield=[jade, bear_a, bear_b], hand=[cards["Lightning Bolt"]], life=20
        )
        p2 = PlayerState(name="P2", life=20)
        game = _game(p1, p2)

        result = game.activate_permanent_ability(
            0, "Jade Monolith", target_player_index=0, target_permanent_index=2, permanent_index=0
        )
        assert result.supported
        assert bear_b.metadata.get("redirect_damage_to_player") == 0
        assert bear_a.metadata.get("redirect_damage_to_player") is None

        # Damage that would hit the chosen creature is redirected to its controller.
        game.cast_from_hand(0, "Lightning Bolt", target_player_index=0, target_permanent_index=2)
        game.resolve_stack()
        assert p1.life == 17
        assert bear_b.damage_marked == 0


# ---------------------------------------------------------------------------
# Animate Wall — "The targeting prompt should only highlight valid targets
# (i.e. walls)."  The Aura is a legal cast only against a Wall.
# ---------------------------------------------------------------------------

class TestAnimateWall:
    def test_enchants_a_wall_and_lets_it_attack(self, cards):
        wall = next(c for c in cards.values() if c.name.startswith("Wall of"))
        wall_perm = Permanent(card=wall)
        p1 = PlayerState(name="P1", hand=[cards["Animate Wall"]])
        p2 = PlayerState(name="P2", battlefield=[wall_perm])
        game = _game(p1, p2)

        result = game.cast_from_hand(
            0, "Animate Wall", target_player_index=1, target_permanent_index=0
        )
        assert result.supported
        assert wall_perm.metadata.get("can_attack_as_though_no_defender") is True

    def test_cannot_enchant_a_nonwall_creature(self, cards):
        bear = Permanent(card=cards["Grizzly Bears"])
        p1 = PlayerState(name="P1", hand=[cards["Animate Wall"]])
        p2 = PlayerState(name="P2", battlefield=[bear])
        game = _game(p1, p2)
        result = game.cast_from_hand(
            0, "Animate Wall", target_player_index=1, target_permanent_index=0
        )
        assert not result.supported


# ---------------------------------------------------------------------------
# Magical Hack — "Doesn't prompt me to change the [land type]. ... then replace
# the text for those types and reevaluate the card."
# ---------------------------------------------------------------------------

class TestMagicalHack:
    def test_changes_a_lands_basic_type(self, cards):
        forest = Permanent(card=cards["Forest"])
        p1 = PlayerState(name="P1", hand=[cards["Magical Hack"]])
        p2 = PlayerState(name="P2", battlefield=[forest])
        game = _game(p1, p2)

        result = game.cast_from_hand(
            0, "Magical Hack", target_player_index=1, target_permanent_index=0, new_color="U"
        )
        game.resolve_stack()

        assert result.supported
        assert forest.metadata.get("land_type_override") == "island"
        game.tap_land_for_mana(1, "Forest", chosen_color="U", permanent_index=0)
        assert p2.mana_pool.get("U", 0) == 1


# ---------------------------------------------------------------------------
# Thoughtlace — "The color label, e.g. Color: {U} should use the mana symbol."
# The recolor is recorded so the UI can render the mana symbol.
# ---------------------------------------------------------------------------

class TestThoughtlace:
    def test_records_color_override_for_serialization(self, cards):
        from web.app import _serialize_permanent

        bear = Permanent(card=cards["Grizzly Bears"])
        p1 = PlayerState(name="P1", hand=[cards["Thoughtlace"]])
        p2 = PlayerState(name="P2", battlefield=[bear])
        game = _game(p1, p2)

        game.cast_from_hand(0, "Thoughtlace", target_player_index=1, target_permanent_index=0)
        game.resolve_stack()

        assert bear.metadata.get("color_override") == "U"
        data = _serialize_permanent(bear, game)
        assert data["color_override"] == "U"


# ---------------------------------------------------------------------------
# Animate Dead — "The targeting works but the prompt is wrong." Guard the
# engine reanimation so the targeting it depends on stays correct.
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

        result = game.cast_from_hand(
            0, "Animate Dead", target_player_index=0, target_permanent_index=1
        )

        assert result.supported
        names = [p.card.name for p in p1.battlefield]
        assert "Hill Giant" in names
        assert [c.name for c in p1.graveyard] == ["Grizzly Bears"]
