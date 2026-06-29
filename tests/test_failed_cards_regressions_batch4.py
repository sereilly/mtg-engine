"""Regression tests for the fourth batch of cards reported FAILED in-game.

Each test documents a bug reported through the in-game Debug Menu verification
flow and guards the rules-correct behavior after the fix. Tests load the real
Alpha (LEA) card definitions so they exercise the actual oracle text, parse
rules, handlers, and continuous-effect recalculation.

Cards covered: Castle, Gauntlet of Might, Lord of Atlantis, Nightmare, Fear,
Wild Growth, Sea Serpent, Rock Hydra, Clockwork Beast, Island Sanctuary,
Nettling Imp, Shatter, Rod of Ruin, Soul Net, Wooden Sphere,
Circle of Protection: Red, Feedback, Force of Nature.
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


def _destroy(game: Game, owner: PlayerState, perm: Permanent) -> None:
    game._destroy_target_permanent(owner, target_permanent_index=owner.battlefield.index(perm))


# ---------------------------------------------------------------------------
# Continuous effects must end when their source leaves the battlefield (611.3b).
# ---------------------------------------------------------------------------

class TestCastle:
    """"Destroying Castle doesn't remove the toughness bonus." Castle's
    "Untapped creatures you control get +0/+2" is a static ability, so it must be
    recalculated dynamically and vanish when Castle leaves."""

    def test_buffs_untapped_creatures_and_reverts_when_destroyed(self, cards):
        bear = Permanent(card=cards["Grizzly Bears"])  # 2/2
        p1 = PlayerState(name="P1", hand=[cards["Castle"]], battlefield=[bear])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        game.cast_from_hand(0, "Castle")
        assert bear.effective_toughness == 4

        castle = next(p for p in p1.battlefield if p.card.name == "Castle")
        _destroy(game, p1, castle)
        assert bear.effective_toughness == 2

    def test_tapped_creature_does_not_get_the_bonus(self, cards):
        bear = Permanent(card=cards["Grizzly Bears"], tapped=True)
        p1 = PlayerState(name="P1", hand=[cards["Castle"]], battlefield=[bear])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        game.cast_from_hand(0, "Castle")
        # Only *untapped* creatures get +0/+2.
        assert bear.effective_toughness == 2


class TestGauntletOfMight:
    """"When I destroy Gauntlet of Might its effects still persist." The
    "Red creatures get +1/+1" static buff must end when Gauntlet leaves."""

    def test_red_buff_reverts_when_destroyed(self, cards):
        goblin = Permanent(card=cards["Mons's Goblin Raiders"])  # red 0/1
        base_power = goblin.effective_power
        p1 = PlayerState(name="P1", hand=[cards["Gauntlet of Might"]], battlefield=[goblin])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        game.cast_from_hand(0, "Gauntlet of Might")
        assert goblin.effective_power == base_power + 1

        gauntlet = next(p for p in p1.battlefield if p.card.name == "Gauntlet of Might")
        _destroy(game, p1, gauntlet)
        assert goblin.effective_power == base_power


class TestLordOfAtlantis:
    """"It grants +1/+1 but not islandwalk." Lord of Atlantis must grant both
    +1/+1 and islandwalk to other Merfolk, including ones entering later, and
    those bonuses must end when the lord leaves."""

    def test_grants_buff_and_islandwalk_to_other_merfolk(self, cards):
        merfolk = _nosick(Permanent(card=cards["Merfolk of the Pearl Trident"]))  # 1/1
        p1 = PlayerState(name="P1", hand=[cards["Lord of Atlantis"]], battlefield=[merfolk])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=cards["Island"])])
        game = _game(p1, p2)

        game.cast_from_hand(0, "Lord of Atlantis")
        assert merfolk.effective_power == 2
        assert merfolk.metadata.get("has_islandwalk") is True

    def test_merfolk_entering_after_the_lord_also_benefits(self, cards):
        p1 = PlayerState(
            name="P1",
            hand=[cards["Lord of Atlantis"], cards["Merfolk of the Pearl Trident"]],
        )
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        game.cast_from_hand(0, "Lord of Atlantis")
        game.cast_from_hand(0, "Merfolk of the Pearl Trident", target_player_index=0)
        late = next(
            p for p in p1.battlefield
            if p.card.name == "Merfolk of the Pearl Trident"
        )
        assert late.effective_power == 2
        assert late.metadata.get("has_islandwalk") is True

    def test_buff_and_islandwalk_revert_when_lord_leaves(self, cards):
        merfolk = _nosick(Permanent(card=cards["Merfolk of the Pearl Trident"]))
        p1 = PlayerState(name="P1", hand=[cards["Lord of Atlantis"]], battlefield=[merfolk])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.cast_from_hand(0, "Lord of Atlantis")
        lord = next(p for p in p1.battlefield if p.card.name == "Lord of Atlantis")

        _destroy(game, p1, lord)

        assert merfolk.effective_power == 1
        assert merfolk.metadata.get("has_islandwalk") is not True


class TestNightmare:
    """"Nightmare's power and toughness aren't changed when a swamp is removed."
    Its CDA P/T = number of Swamps you control must recompute when a Swamp leaves."""

    def test_pt_tracks_swamp_count_when_one_is_destroyed(self, cards):
        nightmare = Permanent(card=cards["Nightmare"])
        swamp_a = Permanent(card=cards["Swamp"])
        swamp_b = Permanent(card=cards["Swamp"])
        p1 = PlayerState(name="P1", battlefield=[nightmare, swamp_a, swamp_b])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game._refresh_dynamic_creatures()
        assert (nightmare.effective_power, nightmare.effective_toughness) == (2, 2)

        _destroy(game, p1, swamp_a)
        assert (nightmare.effective_power, nightmare.effective_toughness) == (1, 1)


class TestFear:
    """"The Fear keyword does not get removed from the enchanted creature when the
    card is destroyed. In general, continuous effects granted by auras should stop
    when the aura is removed."""

    def test_fear_is_removed_when_the_aura_is_destroyed(self, cards):
        bear = Permanent(card=cards["Grizzly Bears"])
        p1 = PlayerState(name="P1", hand=[cards["Fear"]], battlefield=[bear])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        game.cast_from_hand(0, "Fear", target_player_index=0, target_permanent_index=0)
        assert game._has_keyword(bear, "fear") is True

        fear = next(p for p in p1.battlefield if p.card.name == "Fear")
        _destroy(game, p1, fear)
        assert game._has_keyword(bear, "fear") is False

    def test_numeric_aura_buff_reverts_when_aura_destroyed(self, cards):
        # Generalized: Holy Strength's +1/+2 also ends when the Aura leaves.
        bear = Permanent(card=cards["Grizzly Bears"])  # 2/2
        p1 = PlayerState(name="P1", hand=[cards["Holy Strength"]], battlefield=[bear])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.cast_from_hand(0, "Holy Strength", target_player_index=0, target_permanent_index=0)
        assert (bear.effective_power, bear.effective_toughness) == (3, 4)

        aura = next(p for p in p1.battlefield if p.card.name == "Holy Strength")
        _destroy(game, p1, aura)
        assert (bear.effective_power, bear.effective_toughness) == (2, 2)


# ---------------------------------------------------------------------------
# Wild Growth — "Trigger doesn't work"
# ---------------------------------------------------------------------------

class TestWildGrowth:
    def test_tapping_enchanted_land_adds_an_extra_green(self, cards):
        forest = Permanent(card=cards["Forest"])
        p1 = PlayerState(name="P1", hand=[cards["Wild Growth"]], battlefield=[forest])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        game.cast_from_hand(0, "Wild Growth", target_player_index=0, target_permanent_index=0)
        game.tap_land_for_mana(0, "Forest", chosen_color="G", permanent_index=0)

        # One {G} from the Forest plus one extra {G} from Wild Growth.
        assert p1.mana_pool.get("G", 0) == 2


# ---------------------------------------------------------------------------
# Sea Serpent — "should be destroyed immediately as a state based action if there
# are no islands in play"
# ---------------------------------------------------------------------------

class TestSeaSerpent:
    def test_sacrificed_as_sba_when_controller_has_no_islands(self, cards):
        serpent = Permanent(card=cards["Sea Serpent"])
        island = Permanent(card=cards["Island"])
        p1 = PlayerState(name="P1", battlefield=[serpent, island])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.check_state_based_actions()
        assert serpent in p1.battlefield  # safe while an Island is controlled

        p1.battlefield.remove(island)
        game.check_state_based_actions()
        assert serpent not in p1.battlefield
        assert any(c.name == "Sea Serpent" for c in p1.graveyard)


# ---------------------------------------------------------------------------
# Rock Hydra — "has 2 activated abilities. I should be able to choose which one"
# ---------------------------------------------------------------------------

class TestRockHydra:
    def _hydra_on_upkeep(self, cards):
        hydra = _nosick(Permanent(card=cards["Rock Hydra"]))
        # Entered with X=3 counters; without them it is a 0/0 and dies (704.5f).
        hydra.power_bonus = 3
        hydra.toughness_bonus = 3
        p1 = PlayerState(name="P1", battlefield=[hydra])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.active_player_index = 0
        game._set_phase_and_step("beginning", "upkeep")
        return game, p1, hydra

    def test_ability_index_one_puts_a_plus_one_counter(self, cards):
        game, p1, hydra = self._hydra_on_upkeep(cards)
        before = hydra.effective_power
        result = game.activate_permanent_ability(0, "Rock Hydra", permanent_index=0, ability_index=1)
        assert result.supported
        assert hydra.effective_power == before + 1

    def test_ability_index_zero_is_the_prevention_ability(self, cards):
        game, p1, hydra = self._hydra_on_upkeep(cards)
        before = hydra.effective_power
        result = game.activate_permanent_ability(0, "Rock Hydra", permanent_index=0, ability_index=0)
        assert result.supported
        # The {R} prevention ability does not add a counter.
        assert hydra.effective_power == before


# ---------------------------------------------------------------------------
# Clockwork Beast — "Using the activated ability doesn't add more counters even
# though I had less than 7."
# ---------------------------------------------------------------------------

class TestClockworkBeast:
    def _beast_on_upkeep(self, cards, enforce=False, mana=None):
        beast = Permanent(card=cards["Clockwork Beast"])
        p1 = PlayerState(name="P1", mana_pool=dict(mana or {}))
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])
        game.enforce_mana_costs = enforce
        game._put_permanent_onto_battlefield(0, beast, None)
        _nosick(beast)
        game.active_player_index = 0
        game._set_phase_and_step("beginning", "upkeep")
        return game, p1, beast

    def test_x_counters_are_added(self, cards):
        game, p1, beast = self._beast_on_upkeep(cards)
        beast.metadata["plus_1_0_counters"] = 2
        beast.power_bonus = 2
        result = game.activate_permanent_ability(0, "Clockwork Beast", permanent_index=0, x_value=3)
        assert result.supported
        assert beast.metadata["plus_1_0_counters"] == 5
        assert beast.effective_power == 5

    def test_cannot_exceed_seven_counters(self, cards):
        game, p1, beast = self._beast_on_upkeep(cards)
        beast.metadata["plus_1_0_counters"] = 6
        beast.power_bonus = 6
        game.activate_permanent_ability(0, "Clockwork Beast", permanent_index=0, x_value=5)
        assert beast.metadata["plus_1_0_counters"] == 7

    def test_x_generic_mana_is_paid(self, cards):
        game, p1, beast = self._beast_on_upkeep(cards, enforce=True, mana={"C": 3})
        beast.metadata["plus_1_0_counters"] = 2
        beast.power_bonus = 2
        result = game.activate_permanent_ability(0, "Clockwork Beast", permanent_index=0, x_value=3)
        assert result.supported
        assert sum(p1.mana_pool.values()) == 0  # paid {3}
        assert beast.metadata["plus_1_0_counters"] == 5


# ---------------------------------------------------------------------------
# Island Sanctuary — "I didn't get a prompt during my draw phase"
# ---------------------------------------------------------------------------

class TestIslandSanctuary:
    def _setup(self, cards):
        sanctuary = Permanent(card=cards["Island Sanctuary"])
        p1 = PlayerState(
            name="P1",
            battlefield=[sanctuary],
            library=[cards["Forest"], cards["Forest"]],
        )
        p2 = PlayerState(name="P2")
        return _game(p1, p2), p1

    def test_skipping_the_draw_grants_protection(self, cards):
        game, p1 = self._setup(cards)
        before = len(p1.hand)
        game.resolve_draw_step(0, sanctuary_choice=True)
        assert len(p1.hand) == before  # the draw was skipped
        assert p1.island_sanctuary_protected is True

    def test_choosing_to_draw_normally_takes_no_protection(self, cards):
        game, p1 = self._setup(cards)
        before = len(p1.hand)
        game.resolve_draw_step(0, sanctuary_choice=False)
        assert len(p1.hand) == before + 1
        assert p1.island_sanctuary_protected is False


# ---------------------------------------------------------------------------
# Nettling Imp — "Activated ability didn't let me choose a target"
# ---------------------------------------------------------------------------

class TestNettlingImp:
    def test_marks_the_chosen_creature_to_attack(self, cards):
        imp = _nosick(Permanent(card=cards["Nettling Imp"]))
        victim = _nosick(Permanent(card=cards["Grizzly Bears"]))
        p1 = PlayerState(name="P1", battlefield=[imp])
        p2 = PlayerState(name="P2", battlefield=[victim])
        game = _game(p1, p2)
        # Activate only during an opponent's turn (here P2 is the active player).
        game.active_player_index = 1
        game._set_phase_and_step("beginning", "upkeep")

        result = game.activate_permanent_ability(
            0, "Nettling Imp", target_player_index=1, permanent_index=0, target_permanent_index=0
        )

        assert result.supported
        assert victim.metadata.get("must_attack_until_eot") is True
        assert victim.metadata.get("destroy_if_did_not_attack_eot") is True


# ---------------------------------------------------------------------------
# Shatter — "Shatter didn't let me choose a target"
# ---------------------------------------------------------------------------

class TestShatter:
    def test_destroys_the_chosen_artifact(self, cards):
        keeper = Permanent(card=cards["Black Lotus"])
        victim = Permanent(card=cards["Mox Ruby"])
        p1 = PlayerState(name="P1", hand=[cards["Shatter"]])
        p2 = PlayerState(name="P2", battlefield=[keeper, victim])
        game = _game(p1, p2)

        result = game.cast_from_hand(0, "Shatter", target_player_index=1, target_permanent_index=1)

        assert result.supported
        assert victim not in p2.battlefield
        assert keeper in p2.battlefield  # only the chosen artifact is destroyed

    def test_requires_an_artifact_target(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Shatter"]])
        p2 = PlayerState(name="P2")  # no artifacts anywhere
        game = _game(p1, p2)

        result = game.cast_from_hand(0, "Shatter", target_player_index=1)

        assert not result.supported


# ---------------------------------------------------------------------------
# Rod of Ruin — "has a mana cost as part of its activation"
# ---------------------------------------------------------------------------

class TestRodOfRuin:
    def test_pays_three_and_deals_one_damage(self, cards):
        rod = _nosick(Permanent(card=cards["Rod of Ruin"]))
        p1 = PlayerState(name="P1", battlefield=[rod], mana_pool={"C": 3})
        p2 = PlayerState(name="P2", life=20)
        game = Game(players=[p1, p2], enforce_mana_costs=True)

        result = game.activate_permanent_ability(0, "Rod of Ruin", target_player_index=1, permanent_index=0)

        assert result.supported
        assert p2.life == 19
        assert sum(p1.mana_pool.values()) == 0  # the {3} was paid

    def test_illegal_without_enough_mana(self, cards):
        rod = _nosick(Permanent(card=cards["Rod of Ruin"]))
        p1 = PlayerState(name="P1", battlefield=[rod], mana_pool={"C": 1})
        p2 = PlayerState(name="P2", life=20)
        game = Game(players=[p1, p2], enforce_mana_costs=True)

        result = game.activate_permanent_ability(0, "Rod of Ruin", target_player_index=1, permanent_index=0)

        assert not result.supported
        assert p2.life == 20


# ---------------------------------------------------------------------------
# Soul Net — "When a creature dies I should get a trigger prompt"
# The death trigger fires; the optional {1} is paid when the controller can.
# ---------------------------------------------------------------------------

class TestSoulNet:
    def test_gains_life_when_the_payment_is_made(self, cards):
        net = Permanent(card=cards["Soul Net"])
        bear = _nosick(Permanent(card=cards["Grizzly Bears"]))
        p1 = PlayerState(name="P1", battlefield=[net, bear], mana_pool={"C": 1}, life=20)
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        game._permanent_to_graveyard(p1, bear)
        p1.battlefield.remove(bear)
        # The dies-trigger resolves off the stack; its pay-prompt is raised then.
        game.resolve_stack()

        # Soul Net's "you may pay {1}" is now an optional choice — accept it.
        assert game.pending_optional_pays
        game.confirm_optional_pay(0, "Soul Net", accept=True)
        assert p1.life == 21

    def test_no_life_gain_when_the_cost_cannot_be_paid(self, cards):
        net = Permanent(card=cards["Soul Net"])
        bear = _nosick(Permanent(card=cards["Grizzly Bears"]))
        p1 = PlayerState(name="P1", battlefield=[net, bear], mana_pool={}, life=20)
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        game._permanent_to_graveyard(p1, bear)
        p1.battlefield.remove(bear)
        game.resolve_stack()

        assert p1.life == 20


# ---------------------------------------------------------------------------
# Wooden Sphere — "When I cast a green spell, it should ... activate wooden sphere"
# ---------------------------------------------------------------------------

class TestWoodenSphere:
    def test_gains_life_when_a_green_spell_is_cast(self, cards):
        sphere = Permanent(card=cards["Wooden Sphere"])
        bear = Permanent(card=cards["Grizzly Bears"])
        p1 = PlayerState(
            name="P1", battlefield=[sphere, bear], hand=[cards["Giant Growth"]], life=20
        )
        p1.mana_pool["C"] = 1  # to pay Wooden Sphere's optional {1}
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        game.cast_from_hand(0, "Giant Growth", target_player_index=0, target_permanent_index=1)
        game.auto_resolve_pending_optional_pays()  # the controller chooses to pay {1}

        assert p1.life == 21


# ---------------------------------------------------------------------------
# Circle of Protection: Red — "doesn't let me choose a red source"
# ---------------------------------------------------------------------------

class TestCircleOfProtectionRed:
    def test_activation_grants_the_controller_a_prevention_shield(self, cards):
        cop = _nosick(Permanent(card=cards["Circle of Protection: Red"]))
        p1 = PlayerState(name="P1", battlefield=[cop], life=20)
        p2 = PlayerState(name="P2", hand=[cards["Lightning Bolt"]])
        game = _game(p1, p2)

        result = game.activate_permanent_ability(0, "Circle of Protection: Red", permanent_index=0)

        assert result.supported
        # CoP arms a color-scoped shield (not the generic numeric prevention pool).
        assert p1.color_prevention_shields == ["R"]

        before = p1.life
        game.cast_from_hand(1, "Lightning Bolt", target_player_index=0)
        # The shield prevents the entire next damage event from a red source.
        assert p1.life == before


# ---------------------------------------------------------------------------
# Feedback — enchant enchantment; deals 1 damage to that enchantment's controller
# ---------------------------------------------------------------------------

class TestFeedback:
    def test_deals_damage_to_enchanted_enchantments_controller(self, cards):
        enchantment = Permanent(card=cards["Castle"])
        p1 = PlayerState(name="P1", hand=[cards["Feedback"]], life=20)
        p2 = PlayerState(name="P2", battlefield=[enchantment], life=20)
        game = _game(p1, p2)

        result = game.cast_from_hand(0, "Feedback", target_player_index=1, target_permanent_index=0)
        assert result.supported

        game.active_player_index = 1
        game.resolve_upkeep(1)
        assert p2.life == 19


# ---------------------------------------------------------------------------
# Force of Nature — "The sacrifice button in the force of nature prompt didn't do
# anything." Declining the upkeep payment deals 8 damage to the controller.
# ---------------------------------------------------------------------------

class TestForceOfNature:
    def test_declining_payment_deals_eight_damage(self, cards):
        fon = Permanent(card=cards["Force of Nature"])
        p1 = PlayerState(name="P1", battlefield=[fon], life=20)
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.active_player_index = 0

        game.resolve_upkeep(0, human_choices={"Force of Nature": False})

        assert p1.life == 12
        assert fon in p1.battlefield  # it is not sacrificed — only damage

    def test_paying_avoids_the_damage(self, cards):
        fon = Permanent(card=cards["Force of Nature"])
        p1 = PlayerState(name="P1", battlefield=[fon], life=20, mana_pool={"G": 4})
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.active_player_index = 0

        game.resolve_upkeep(0, human_choices={"Force of Nature": True})

        assert p1.life == 20
        assert p1.mana_pool.get("G", 0) == 0

    def test_upkeep_trigger_reports_the_damage_consequence(self, cards):
        # The pay-trigger data exposes the damage so the UI can label the decline
        # button "Take 8 damage" rather than "Sacrifice".
        fon = Permanent(card=cards["Force of Nature"])
        p1 = PlayerState(name="P1", battlefield=[fon], life=20)
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.active_player_index = 0

        triggers = game.get_upkeep_pay_triggers(0)
        force = next(t for t in triggers if t["card_name"] == "Force of Nature")
        assert force["kind"] == "upkeep_pay_or_deal_damage_to_controller"
        assert force["damage"] == 8
