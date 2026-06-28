"""Regression tests for the sixth batch of cards reported FAILED in-game.

Each test documents a bug reported through the in-game Debug Menu verification
flow (recorded in CARD_VERIFICATION.md) and guards the rules-correct behavior
after the fix. Tests load the real Alpha (LEA) card definitions so they exercise
the actual oracle text, parse rules, handlers, and continuous-effect logic.

Cards covered: Animate Artifact, Animate Dead, Blaze of Glory, Channel,
Circle of Protection: Red, Dwarven Demolition Team, Lifetap, Power Sink,
Resurrection, Throne of Bone, Timber Wolves, Verduran Enchantress,
Volcanic Eruption.
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
# Animate Artifact — "The power and toughness labels are not removed when the
# creature turns back into a normal artifact."
# ---------------------------------------------------------------------------

class TestAnimateArtifact:
    def test_animates_artifact_into_a_creature(self, cards):
        tome = Permanent(card=cards["Jayemdae Tome"])  # mana value 4
        p1 = PlayerState(name="P1", hand=[cards["Animate Artifact"]], battlefield=[tome])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        result = game.cast_from_hand(
            0, "Animate Artifact", target_player_index=0, target_permanent_index=0
        )
        game.resolve_stack()

        assert result.supported
        assert "creature" in tome.card.type_line.lower()
        assert tome.effective_power == 4 and tome.effective_toughness == 4

    def test_reverts_to_noncreature_when_aura_leaves(self, cards):
        # The reported bug: after the Aura is destroyed, the artifact kept its
        # creature type and P/T, so the UI still showed power/toughness labels.
        tome = Permanent(card=cards["Jayemdae Tome"])
        p1 = PlayerState(name="P1", hand=[cards["Animate Artifact"]], battlefield=[tome])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.cast_from_hand(0, "Animate Artifact", target_player_index=0, target_permanent_index=0)
        game.resolve_stack()
        aura = next(p for p in p1.battlefield if p.card.name == "Animate Artifact")

        game._permanent_to_graveyard(p1, aura)
        game.check_state_based_actions()

        assert "creature" not in tome.card.type_line.lower()
        assert tome.card.name == "Jayemdae Tome"
        assert tome.metadata.get("attached_aura") is None


# ---------------------------------------------------------------------------
# Animate Dead — "choose a creature card in a graveyard" (not a player).
# ---------------------------------------------------------------------------

class TestAnimateDead:
    def test_reanimates_the_specific_chosen_graveyard_creature(self, cards):
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
        game.resolve_stack()

        assert result.supported
        names = [p.card.name for p in p1.battlefield]
        assert "Hill Giant" in names  # the chosen creature, not the first one
        assert [c.name for c in p1.graveyard] == ["Grizzly Bears"]


# ---------------------------------------------------------------------------
# Blaze of Glory — "only castable during combat before blockers are declared".
# ---------------------------------------------------------------------------

class TestBlazeOfGlory:
    def test_cannot_be_cast_in_a_main_phase(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Blaze of Glory"]])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=cards["Grizzly Bears"])])
        game = _game(p1, p2)
        game._set_phase_and_step("precombat_main", "main")

        result = game.cast_from_hand(0, "Blaze of Glory", target_player_index=1)

        assert not result.supported
        assert "before blockers" in result.details
        assert any(c.name == "Blaze of Glory" for c in p1.hand)  # not consumed

    def test_cannot_be_cast_after_blockers(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Blaze of Glory"]])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=cards["Grizzly Bears"])])
        game = _game(p1, p2)
        game._set_phase_and_step("combat", "declare_blockers")

        result = game.cast_from_hand(0, "Blaze of Glory", target_player_index=1)

        assert not result.supported

    def test_can_be_cast_during_declare_attackers(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Blaze of Glory"]])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=cards["Grizzly Bears"])])
        game = _game(p1, p2)
        game._set_phase_and_step("combat", "declare_attackers")

        result = game.cast_from_hand(0, "Blaze of Glory", target_player_index=1)

        assert result.supported
        assert p2.battlefield[0].metadata.get("must_block_all_until_eot") is True


# ---------------------------------------------------------------------------
# Channel — "Create an emblem of this card that lasts until end of turn that
# lets me activate its ability." ({G}{G}: until end of turn, pay 1 life: add {C}.)
# ---------------------------------------------------------------------------

class TestChannel:
    def test_grants_a_repeatable_pay_life_for_mana_ability(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Channel"]], life=20)
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        game.cast_from_hand(0, "Channel")
        assert p1.channel_active_until_eot is True

        result = game.use_channel_mana(0, 3)  # pay 3 life for {C}{C}{C}
        assert result.supported
        assert p1.life == 17
        assert p1.mana_pool["C"] == 3

    def test_ability_is_serialized_so_the_ui_can_offer_it(self, cards):
        from web.app import _serialize_player

        p1 = PlayerState(name="P1", hand=[cards["Channel"]])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.cast_from_hand(0, "Channel")

        data = _serialize_player(game.players[0], 0, 0, game)
        assert data["channel_active"] is True


# ---------------------------------------------------------------------------
# Circle of Protection: Red — "I don't get a prompt to choose a red source."
# ---------------------------------------------------------------------------

class TestCircleOfProtectionRed:
    def test_activation_records_the_chosen_source_color(self, cards):
        cop = _nosick(Permanent(card=cards["Circle of Protection: Red"]))
        p1 = PlayerState(name="P1", battlefield=[cop], life=20)
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        result = game.activate_permanent_ability(0, "Circle of Protection: Red", permanent_index=0)

        assert result.supported
        # CoP arms a color-scoped shield, not the generic numeric prevention pool.
        assert p1.color_prevention_shields == ["R"]
        # The color of the chosen source is recorded so the UI can show/prompt it.
        assert p1.damage_prevention_color == "R"

    def test_color_is_surfaced_in_serialized_state(self, cards):
        from web.app import _serialize_player

        cop = _nosick(Permanent(card=cards["Circle of Protection: Red"]))
        p1 = PlayerState(name="P1", battlefield=[cop], life=20)
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.activate_permanent_ability(0, "Circle of Protection: Red", permanent_index=0)

        data = _serialize_player(game.players[0], 0, 0, game)
        assert data["shield_color"] == "R"


# ---------------------------------------------------------------------------
# Dwarven Demolition Team — "{T}: Destroy target Wall." Must target only Walls.
# ---------------------------------------------------------------------------

class TestDwarvenDemolitionTeam:
    def test_destroys_a_chosen_wall(self, cards):
        wall = next(c for c in cards.values() if c.name.startswith("Wall of"))
        team = _nosick(Permanent(card=cards["Dwarven Demolition Team"]))
        p1 = PlayerState(name="P1", battlefield=[team])
        p2 = PlayerState(
            name="P2",
            battlefield=[Permanent(card=cards["Grizzly Bears"]), Permanent(card=wall)],
        )
        game = _game(p1, p2)

        result = game.activate_permanent_ability(
            0, "Dwarven Demolition Team", target_player_index=1, target_permanent_index=1, permanent_index=0
        )
        game.resolve_stack()
        game.check_state_based_actions()

        assert result.supported
        names = [p.card.name for p in p2.battlefield]
        assert wall.name not in names
        assert "Grizzly Bears" in names

    def test_cannot_target_a_nonwall_creature(self, cards):
        # The reported bug: the ability was offered against any creature.
        team = _nosick(Permanent(card=cards["Dwarven Demolition Team"]))
        p1 = PlayerState(name="P1", battlefield=[team])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=cards["Grizzly Bears"])])
        game = _game(p1, p2)

        result = game.activate_permanent_ability(
            0, "Dwarven Demolition Team", target_player_index=1, target_permanent_index=0, permanent_index=0
        )

        assert not result.supported
        assert any(p.card.name == "Grizzly Bears" for p in p2.battlefield)


# ---------------------------------------------------------------------------
# Lifetap — "Whenever a Forest an opponent controls becomes tapped, you gain 1
# life."  Reported "Card doesn't work".
# ---------------------------------------------------------------------------

class TestLifetap:
    def test_gains_life_when_opponent_taps_a_forest(self, cards):
        lifetap = Permanent(card=cards["Lifetap"])
        p1 = PlayerState(name="P1", battlefield=[lifetap], life=20)
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=cards["Forest"])])
        game = _game(p1, p2)

        game.tap_land_for_mana(1, "Forest")  # opponent taps their Forest

        assert p1.life == 21

    def test_no_life_when_controller_taps_their_own_forest(self, cards):
        lifetap = Permanent(card=cards["Lifetap"])
        forest = Permanent(card=cards["Forest"])
        p1 = PlayerState(name="P1", battlefield=[lifetap, forest], life=20)
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        game.tap_land_for_mana(0, "Forest")  # the controller's own Forest

        assert p1.life == 20  # only an opponent's Forest triggers it


# ---------------------------------------------------------------------------
# Power Sink — "Counter target spell unless its controller pays {X}."
# ---------------------------------------------------------------------------

class TestPowerSink:
    def test_counters_when_controller_cannot_pay_x(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Power Sink"]])
        p2 = PlayerState(name="P2", hand=[cards["Lightning Bolt"]])  # no mana to pay
        game = _game(p1, p2)
        game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
        bolt_index = len(game.stack) - 1

        game.queue_from_hand(0, "Power Sink", target_stack_index=bolt_index, x_value=3)
        game.resolve_stack()

        assert any(c.name == "Lightning Bolt" for c in p2.graveyard)  # countered
        # Rider: its controller taps all their lands and loses unspent mana.
        assert all(p.tapped for p in p2.battlefield if p.card.primary_type == "land")

    def test_not_countered_when_controller_pays_x(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Power Sink"]])
        p2 = PlayerState(name="P2", hand=[cards["Lightning Bolt"]], life=20)
        p2.mana_pool["R"] = 3  # enough to pay {3}
        game = _game(p1, p2)
        game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
        bolt_index = len(game.stack) - 1

        game.queue_from_hand(0, "Power Sink", target_stack_index=bolt_index, x_value=3)
        game.resolve_stack()

        # P2 paid {3}; the bolt was not countered and resolved (P1 took 3).
        assert p1.life == 17
        assert p2.mana_pool["R"] == 0  # the {3} was paid


# ---------------------------------------------------------------------------
# Resurrection — "Return target creature card from your graveyard." Doesn't let
# me choose the target.
# ---------------------------------------------------------------------------

class TestResurrection:
    def test_returns_the_specific_chosen_creature(self, cards):
        p1 = PlayerState(
            name="P1",
            hand=[cards["Resurrection"]],
            graveyard=[cards["Grizzly Bears"], cards["Hill Giant"]],
        )
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        result = game.cast_from_hand(
            0, "Resurrection", target_player_index=0, target_permanent_index=1
        )
        game.resolve_stack()

        assert result.supported
        names = [p.card.name for p in p1.battlefield]
        assert "Hill Giant" in names  # the chosen creature, not the first one
        assert "Grizzly Bears" not in names
        grave = [c.name for c in p1.graveyard]
        assert "Grizzly Bears" in grave  # the unchosen creature stays behind
        assert "Hill Giant" not in grave


# ---------------------------------------------------------------------------
# Throne of Bone — "Whenever a player casts a black spell, you may pay {1}. If
# you do, you gain 1 life."
# ---------------------------------------------------------------------------

class TestThroneOfBone:
    def test_gains_life_only_when_the_one_is_paid(self, cards):
        throne = Permanent(card=cards["Throne of Bone"])
        p1 = PlayerState(name="P1", battlefield=[throne], life=20)
        p1.mana_pool["C"] = 1
        p2 = PlayerState(name="P2", hand=[cards["Dark Ritual"]])  # a black spell
        game = _game(p1, p2)

        game.cast_from_hand(1, "Dark Ritual")
        game.auto_resolve_pending_optional_pays()  # the controller chooses to pay {1}

        assert p1.life == 21
        assert p1.mana_pool["C"] == 0  # the {1} was paid

    def test_no_life_when_unable_to_pay_the_one(self, cards):
        throne = Permanent(card=cards["Throne of Bone"])
        p1 = PlayerState(name="P1", battlefield=[throne], life=20)  # empty pool
        p2 = PlayerState(name="P2", hand=[cards["Dark Ritual"]])
        game = _game(p1, p2)

        game.cast_from_hand(1, "Dark Ritual")

        assert p1.life == 20

    def test_no_trigger_on_a_nonblack_spell(self, cards):
        throne = Permanent(card=cards["Throne of Bone"])
        p1 = PlayerState(name="P1", battlefield=[throne], life=20)
        p1.mana_pool["C"] = 1
        p2 = PlayerState(name="P2", hand=[cards["Lightning Bolt"]], life=20)  # red, not black
        game = _game(p1, p2)

        game.cast_from_hand(1, "Lightning Bolt", target_player_index=1)  # at themselves

        assert p1.life == 20  # Throne did not trigger on a red spell
        assert p1.mana_pool["C"] == 1  # nothing paid


# ---------------------------------------------------------------------------
# Timber Wolves — "Banding". The keyword must be recognized and surfaced so the
# combat (banding) UI can act on it.
# ---------------------------------------------------------------------------

class TestTimberWolves:
    def test_banding_keyword_is_recognized(self, cards):
        wolves = Permanent(card=cards["Timber Wolves"])
        p1 = PlayerState(name="P1", battlefield=[wolves])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        assert game._has_keyword(wolves, "Banding")

    def test_banding_is_surfaced_in_the_serialized_keyword_strip(self, cards):
        from web.app import _effective_keywords

        wolves = Permanent(card=cards["Timber Wolves"])
        p1 = PlayerState(name="P1", battlefield=[wolves])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        assert "Banding" in _effective_keywords(wolves, game)


# ---------------------------------------------------------------------------
# Verduran Enchantress — "Whenever you cast an enchantment spell, you may draw a
# card."  Reported "The trigger doesn't work".
# ---------------------------------------------------------------------------

class TestVerduranEnchantress:
    def test_draws_when_controller_casts_an_enchantment(self, cards):
        enchantress = Permanent(card=cards["Verduran Enchantress"])
        p1 = PlayerState(
            name="P1",
            battlefield=[enchantress],
            hand=[cards["Bad Moon"]],
            library=[cards["Forest"], cards["Island"]],
        )
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        game.cast_from_hand(0, "Bad Moon")  # an enchantment spell

        # "you may draw a card" is an optional yes/no prompt now: queued, not auto.
        assert any(e["card_name"] == "Verduran Enchantress" for e in game.pending_optional_pays)
        assert len(p1.hand) == 0
        game.confirm_optional_pay(0, "Verduran Enchantress", accept=True)
        assert len(p1.hand) == 1  # drew one card off accepting

    def test_does_not_draw_on_a_noncreature_nonenchantment_spell(self, cards):
        enchantress = Permanent(card=cards["Verduran Enchantress"])
        p1 = PlayerState(
            name="P1",
            battlefield=[enchantress],
            hand=[cards["Lightning Bolt"]],
            library=[cards["Forest"], cards["Island"]],
        )
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        game.cast_from_hand(0, "Lightning Bolt", target_player_index=1)

        assert len(p1.hand) == 0  # Lightning Bolt is not an enchantment → no draw


# ---------------------------------------------------------------------------
# Volcanic Eruption — "Destroy X target Mountains. ... deals damage to each
# creature and each player equal to the number of Mountains put into a graveyard
# this way."  Reported "I didn't get to choose the targets myself".
# ---------------------------------------------------------------------------

class TestVolcanicEruption:
    def test_destroys_the_chosen_mountains_and_deals_that_much_damage(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Volcanic Eruption"]], life=20)
        mountains = [Permanent(card=cards["Mountain"]) for _ in range(3)]
        bear = Permanent(card=cards["Grizzly Bears"])  # 2/2 → dies to 2 damage
        p2 = PlayerState(name="P2", battlefield=mountains + [bear], life=20)
        game = _game(p1, p2)

        # Choose the first and third Mountains (X = 2).
        result = game.cast_from_hand(
            0, "Volcanic Eruption", target_player_index=1, target_permanent_index=[0, 2], x_value=2
        )
        game.resolve_stack()
        game.check_state_based_actions()

        assert result.supported
        # Exactly the two chosen Mountains were destroyed (one Mountain remains).
        assert sum(1 for p in p2.battlefield if "mountain" in p.card.type_line.lower()) == 1
        # 2 Mountains destroyed → 2 damage to each player and each creature.
        assert p1.life == 18 and p2.life == 18
        assert not any(p.card.name == "Grizzly Bears" for p in p2.battlefield)
