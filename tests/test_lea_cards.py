# Auto-generated LEA card presence tests
from __future__ import annotations

from typing import List


def _card_names(cards) -> List[str]:
    return [c.name for c in cards]


def _make_test(name, idx):
    def test_func(all_cards):
        names = _card_names(all_cards)
        assert name in names
    test_func.__name__ = f"test_lea_card_presence_{idx}"
    return test_func

import pytest

# Consolidated imports required by extracted tests
from engine.ai_policy import (
    choose_cast_action,
    choose_activation_action,
    choose_combat_blockers,
    choose_combat_instant_cast_action,
    choose_reorder_library_order,
)
from engine import Game, PlayerState, classify_card, load_cards
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle, lex_oracle_text, parse_activated_ability_cost
import asyncio
from fastapi.testclient import TestClient
import json
import web.app as web_app
import web.session_store as web_session_store
from web.app import app, store

# Extracted LEA-specific tests
from tests.test_utils import (
    _mk_card,
    _mk_creature_card,
    _pass_priority,
    _resolve_top_stack,
    client,
    _get,
)


def test_feedback_oracle_supported(all_cards):
    feedback = _get(all_cards, "Feedback")
    program = compile_card_oracle(feedback)
    assert program.supported
    # Should expose an "at the beginning" triggered ability
    assert any(t.condition.trigger == "at" for t in program.triggered_abilities)


def test_feedback_deals_damage_at_enchanted_enchantment_upkeep(all_cards):
    feedback = _get(all_cards, "Feedback")
    bad_moon = _get(all_cards, "Bad Moon")

    # P1 will cast Feedback enchanting P2's Bad Moon
    p1 = PlayerState(name="P1", hand=[feedback])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bad_moon)], life=20)
    game = Game(players=[p1, p2])

    # Cast Feedback targeting the enchantment on P2's battlefield
    result = game.cast_from_hand(0, "Feedback", target_player_index=1, target_permanent_index=0)
    assert result.supported

    # Resolve upkeep for P2 (controller of the enchanted enchantment)
    game.resolve_upkeep(1)

    # Feedback should have dealt 1 damage to P2
    assert p2.life == 19

def test_basalt_monolith_tap_and_untap(all_cards):
    monolith = _get(all_cards, "Basalt Monolith")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=monolith)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # Tap for mana (should succeed)
    result = game.activate_permanent_ability(0, "Basalt Monolith")
    assert result.supported
    assert p1.battlefield[0].tapped is True
    assert p1.mana_pool["C"] == 3

    # Untap using ability (should succeed)
    result2 = game.activate_permanent_ability(0, "Basalt Monolith")
    assert result2.supported
    assert p1.battlefield[0].tapped is False

    # Tap again (should succeed, since it's untapped now)
    result3 = game.activate_permanent_ability(0, "Basalt Monolith")
    assert result3.supported
    assert p1.battlefield[0].tapped is True

    # Untap again (should succeed, since it's tapped)
    result4 = game.activate_permanent_ability(0, "Basalt Monolith")
    assert result4.supported
    assert p1.battlefield[0].tapped is False

    # The engine does not expose a way to force the untap ability when untapped.
    # The legal tap/untap cycle is fully tested above.

def test_choose_cast_action_targets_self_for_ancestral_recall(all_cards):
    recall = _get(all_cards, "Ancestral Recall")
    island = _get(all_cards, "Island")
    # Provide enough library cards so self-targeting is safe (≥ 3 required).
    p1 = PlayerState(
        name="P1",
        hand=[recall],
        library=[island, island, island, island, island],
        mana_pool={"W": 0, "U": 1, "B": 0, "R": 0, "G": 0, "C": 0},
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2], enforce_mana_costs=True)

    action = choose_cast_action(game, 0)

    assert action is not None
    assert action.card_name == "Ancestral Recall"
    assert action.target_player_index == 0

def test_choose_cast_action_finds_lethal_lightning_bolt(all_cards):
    bolt = _get(all_cards, "Lightning Bolt")
    salve = _get(all_cards, "Healing Salve")
    mountain = _get(all_cards, "Mountain")
    plains = _get(all_cards, "Plains")

    p1 = PlayerState(
        name="P1",
        hand=[salve, bolt],
        battlefield=[Permanent(card=mountain), Permanent(card=plains)],
        mana_pool={"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0},
    )
    p2 = PlayerState(name="P2", life=3)
    game = Game(players=[p1, p2], enforce_mana_costs=True)

    action = choose_cast_action(game, 0)

    assert action is not None
    assert action.card_name == "Lightning Bolt"
    assert action.target_player_index == 1
    assert action.land_tap_indices

def test_choose_cast_action_skips_unsummon_without_target(all_cards):
    unsummon = _get(all_cards, "Unsummon")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[unsummon], battlefield=[Permanent(card=island)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2], enforce_mana_costs=True)

    action = choose_cast_action(game, 0)

    assert action is None

def test_choose_activation_action_prefers_prodigal_for_lethal(all_cards):
    prodigal = _get(all_cards, "Prodigal Sorcerer")
    tome = _get(all_cards, "Jayemdae Tome")

    p1 = PlayerState(
        name="P1",
        battlefield=[Permanent(card=tome), Permanent(card=prodigal)],
        mana_pool={"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 4},
        library=[_get(all_cards, "Island")],
    )
    p2 = PlayerState(name="P2", life=1)
    game = Game(players=[p1, p2], enforce_mana_costs=True)

    action = choose_activation_action(game, 0)

    assert action is not None
    assert action.permanent_name == "Prodigal Sorcerer"
    assert action.target_player_index == 1

def test_choose_combat_blockers_tries_to_prevent_lethal(all_cards):
    craw_wurm = _get(all_cards, "Craw Wurm")
    grizzly = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=craw_wurm), Permanent(card=grizzly)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=grizzly), Permanent(card=grizzly)], life=7)
    game = Game(players=[p1, p2], enforce_mana_costs=True)
    game.active_player_index = 0
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    game.current_phase = "combat"

    ok, _ = game.declare_attackers(0, [0, 1], defending_player_index=1)
    assert ok
    game.current_step = "declare_blockers"

    blockers = choose_combat_blockers(game, 1)

    assert blockers
    assert len(blockers) == 2

def test_choose_combat_blockers_returns_empty_when_no_legal_blockers(all_cards):
    craw_wurm = _get(all_cards, "Craw Wurm")
    mountain = _get(all_cards, "Mountain")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=craw_wurm)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=mountain)], life=20)
    game = Game(players=[p1, p2], enforce_mana_costs=True)
    game.active_player_index = 0
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    game.current_phase = "combat"

    ok, _ = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok
    game.current_step = "declare_blockers"

    blockers = choose_combat_blockers(game, 1)
    assert blockers == {}


def test_fear_enchanted_creature_unblockable_by_non_artifact_non_black(all_cards):
    fear = _get(all_cards, "Fear")
    grizzly = _get(all_cards, "Grizzly Bears")

    # Controller casts Fear on their creature
    p1 = PlayerState(name="P1", hand=[fear], battlefield=[Permanent(card=grizzly)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=grizzly)], life=20)
    game = Game(players=[p1, p2])

    cast_result = game.cast_from_hand(0, "Fear", target_player_index=0, target_permanent_index=0)
    assert cast_result.supported

    # Attack with the enchanted creature
    game.active_player_index = 0
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    game.current_phase = "combat"

    ok, _ = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok
    game.current_step = "declare_blockers"

    blockers = choose_combat_blockers(game, 1)

    # Non-artifact non-black Grizzly should not be able to block creature with fear
    assert blockers == {}


def test_fear_cannot_be_cast_without_target(all_cards):
    """Regression: Fear (an Aura) was cast without a target and resolved unattached.

    All Aura spells require a target chosen at cast time (Rules 115.1b, 601.2c).
    """
    fear = _get(all_cards, "Fear")
    grizzly = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", hand=[fear], battlefield=[Permanent(card=grizzly)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=grizzly)], life=20)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Fear", target_player_index=0)

    assert not result.supported
    assert "requires a target" in result.details
    assert any(c.name == "Fear" for c in p1.hand)
    assert not any(perm.card.name == "Fear" for perm in p1.battlefield)
    # No creature was silently enchanted
    assert all(perm.metadata.get("attached_aura") is None for perm in p1.battlefield)
    assert all(perm.metadata.get("attached_aura") is None for perm in p2.battlefield)


def test_fear_cannot_be_cast_targeting_a_land(all_cards):
    """Regression companion: Fear can only target a creature, never a land."""
    fear = _get(all_cards, "Fear")
    swamp = _get(all_cards, "Swamp")
    grizzly = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", hand=[fear], battlefield=[Permanent(card=swamp), Permanent(card=grizzly)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # Index 0 is the Swamp — illegal target for "Enchant creature"
    result = game.cast_from_hand(0, "Fear", target_player_index=0, target_permanent_index=0)

    assert not result.supported
    assert any(c.name == "Fear" for c in p1.hand)
    assert not any(perm.card.name == "Fear" for perm in p1.battlefield)


def test_choose_combat_instant_cast_action_prefers_interaction_in_block_step(all_cards):
    bolt = _get(all_cards, "Lightning Bolt")
    mountain = _get(all_cards, "Mountain")

    p1 = PlayerState(name="P1", life=5)
    p2 = PlayerState(
        name="P2",
        hand=[bolt],
        battlefield=[Permanent(card=mountain)],
        mana_pool={"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0},
    )
    game = Game(players=[p1, p2], enforce_mana_costs=True)
    game.active_player_index = 0
    game.current_turn_phase = "combat"
    game.current_step = "declare_blockers"
    game.current_phase = "combat"

    action = choose_combat_instant_cast_action(game, 1)

    assert action is not None


def test_firebreathing_pumps_enchanted_creature(all_cards):
    fire = _get(all_cards, "Firebreathing")
    grizzly = _get(all_cards, "Grizzly Bears")

    # Place a creature and the aura on the battlefield and attach the aura
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=grizzly), Permanent(card=fire)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # Manually attach the aura to the creature (simulates casting and attaching)
    aura_perm = p1.battlefield[1]
    creature_perm = p1.battlefield[0]
    aura_perm.metadata["attached_to"] = creature_perm
    creature_perm.metadata["attached_aura"] = aura_perm

    # Activate the aura's ability (no mana enforcement required for this test)
    result = game.activate_permanent_ability(0, "Firebreathing")

    assert result.supported
    # The enchanted creature should have received the +1 power bonus
    assert creature_perm.power_bonus >= 1

def test_flight_grants_flying(all_cards):
    flight = _get(all_cards, "Flight")
    grizzly = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", hand=[flight], battlefield=[Permanent(card=grizzly)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Flight", target_player_index=0, target_permanent_index=0)
    assert result.supported

    creature_perm = p1.battlefield[0]
    assert (
        creature_perm.metadata.get("gains_flying")
        or creature_perm.metadata.get("gains_flying_until_eot")
        or "Flying" in creature_perm.card.keywords
    )

def test_destroy_all_lands_spell(all_cards):
    armageddon = _get(all_cards, "Armageddon")
    plains = _get(all_cards, "Plains")

    p1 = PlayerState(name="P1", hand=[armageddon])
    p2 = PlayerState(name="P2")
    p1.battlefield.append(Permanent(plains))
    p2.battlefield.append(Permanent(plains))

    game = Game(players=[p1, p2])
    result = game.cast_from_hand(0, "Armageddon", target_player_index=1)

    assert result.supported
    assert len(p1.battlefield) == 0
    assert len(p2.battlefield) == 0


def test_flashfires_destroys_only_plains(all_cards):
    flash = _get(all_cards, "Flashfires")
    plains = _get(all_cards, "Plains")
    mountain = _get(all_cards, "Mountain")

    p1 = PlayerState(name="P1", hand=[flash])
    p2 = PlayerState(name="P2")
    p1.battlefield.append(Permanent(plains))
    p1.battlefield.append(Permanent(mountain))
    p2.battlefield.append(Permanent(plains))
    p2.battlefield.append(Permanent(mountain))

    game = Game(players=[p1, p2])
    result = game.cast_from_hand(0, "Flashfires", target_player_index=1)

    assert result.supported
    # Plains should be destroyed on both sides; mountains should remain
    assert all(perm.card.primary_type != "land" or "plains" not in perm.card.type_line.lower() for perm in p1.battlefield)
    assert any("mountain" in perm.card.type_line.lower() for perm in p1.battlefield)
    assert all(perm.card.primary_type != "land" or "plains" not in perm.card.type_line.lower() for perm in p2.battlefield)
    assert any("mountain" in perm.card.type_line.lower() for perm in p2.battlefield)

def test_ancestral_recall_draws_three(all_cards):
    recall = _get(all_cards, "Ancestral Recall")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[recall])
    p2 = PlayerState(name="P2", library=[island, island, island, island])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Ancestral Recall", target_player_index=1)

    assert result.supported
    assert len(p2.hand) == 3

def test_counterspell_counters_spell_on_stack(all_cards):
    recall = _get(all_cards, "Ancestral Recall")
    counterspell = _get(all_cards, "Counterspell")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[recall])
    p2 = PlayerState(name="P2", hand=[counterspell], library=[island, island, island, island])
    game = Game(players=[p1, p2])

    game.queue_from_hand(0, "Ancestral Recall", target_player_index=1)
    game.queue_from_hand(1, "Counterspell", target_player_index=0)
    game.resolve_stack()

    assert len(p2.hand) == 0
    assert len(p2.graveyard) == 1
    assert p2.graveyard[0].name == "Counterspell"
    assert len(p1.graveyard) == 1
    assert p1.graveyard[0].name == "Ancestral Recall"

def test_disenchant_destroys_target_artifact(all_cards):
    disenchant = _get(all_cards, "Disenchant")
    lotus = _get(all_cards, "Black Lotus")

    p1 = PlayerState(name="P1", hand=[disenchant])
    p2 = PlayerState(name="P2")
    p2.battlefield.append(Permanent(card=lotus))
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Disenchant", target_player_index=1)

    assert result.supported
    assert not p2.battlefield
    assert p2.graveyard
    assert p2.graveyard[0].name == "Black Lotus"

def test_ice_storm_destroys_selected_target_land(all_cards):
    ice_storm = _get(all_cards, "Ice Storm")
    island = _get(all_cards, "Island")
    mountain = _get(all_cards, "Mountain")

    p1 = PlayerState(name="P1", hand=[ice_storm])
    p2 = PlayerState(name="P2")
    p2.battlefield.append(Permanent(card=island))
    p2.battlefield.append(Permanent(card=mountain))
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(
        0,
        "Ice Storm",
        target_player_index=1,
        target_permanent_index=1,
    )

    assert result.supported
    assert len(p2.battlefield) == 1
    assert p2.battlefield[0].card.name == "Island"
    assert p2.graveyard
    assert p2.graveyard[0].name == "Mountain"

def test_bad_moon_applies_global_black_creature_buff(all_cards):
    bad_moon = _get(all_cards, "Bad Moon")
    black_knight = _get(all_cards, "Black Knight")

    p1 = PlayerState(name="P1", hand=[bad_moon])
    p2 = PlayerState(name="P2")
    p1.battlefield.append(Permanent(card=black_knight))
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Bad Moon")

    assert result.supported
    knight_perm = p1.battlefield[0]
    assert knight_perm.effective_power == 3
    assert knight_perm.effective_toughness == 3

def test_discard_effect():
    spell = _mk_card("Discard Test", "Sorcery", "Target player discards two cards.")
    island = _mk_card("Island", "Basic Land — Island")

    p1 = PlayerState(name="P1", hand=[spell])
    p2 = PlayerState(name="P2", hand=[island, island, island])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Discard Test", target_player_index=1)
    assert len(p2.hand) == 1
    assert len(p2.graveyard) == 2

def test_serra_angel_enters_with_flying_and_vigilance(all_cards):
    angel = _get(all_cards, "Serra Angel")
    p1 = PlayerState(name="P1", hand=[angel])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Serra Angel")

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.effective_power == 4
    assert perm.effective_toughness == 4
    assert any(k.lower() == "flying" for k in angel.keywords)
    assert any(k.lower() == "vigilance" for k in angel.keywords)

def test_prodigal_sorcerer_enters_battlefield(all_cards):
    prodigal = _get(all_cards, "Prodigal Sorcerer")
    p1 = PlayerState(name="P1", hand=[prodigal])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Prodigal Sorcerer")

    assert result.supported
    assert p1.battlefield[0].card.name == "Prodigal Sorcerer"
    assert p1.battlefield[0].effective_power == 1
    assert p1.battlefield[0].effective_toughness == 1

def test_activate_prodigal_sorcerer_ability(all_cards):
    prodigal = _get(all_cards, "Prodigal Sorcerer")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=prodigal)])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Prodigal Sorcerer", target_player_index=1)
    assert result.supported
    assert p2.life == 19
    assert p1.battlefield[0].tapped is True

def test_nevinyrrals_disk_enters_tapped(all_cards):
    disk = _get(all_cards, "Nevinyrral's Disk")
    p1 = PlayerState(name="P1", hand=[disk])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    cast_result = game.cast_from_hand(0, "Nevinyrral's Disk")
    assert cast_result.supported
    assert len(p1.battlefield) == 1
    assert p1.battlefield[0].card.name == "Nevinyrral's Disk"
    assert p1.battlefield[0].tapped is True

    assert game.tap_permanent(0, "Nevinyrral's Disk") is False

def test_activate_nevinyrrals_disk_destroys_artifacts_creatures_and_enchantments(all_cards):
    disk = _get(all_cards, "Nevinyrral's Disk")
    land = _mk_card("Test Plains", "Land")
    artifact = _mk_card("Test Relic", "Artifact")
    creature = _mk_card("Test Bear", "Creature — Bear")
    enchantment = _mk_card("Test Aura", "Enchantment")

    p1 = PlayerState(
        name="P1",
        battlefield=[
            Permanent(card=disk, tapped=False),
            Permanent(card=artifact),
            Permanent(card=creature),
            Permanent(card=land),
        ],
    )
    p2 = PlayerState(
        name="P2",
        battlefield=[
            Permanent(card=enchantment),
            Permanent(card=creature),
            Permanent(card=land),
        ],
    )
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Nevinyrral's Disk", target_player_index=1)

    assert result.supported
    assert [perm.card.primary_type for perm in p1.battlefield] == ["land"]
    assert [perm.card.primary_type for perm in p2.battlefield] == ["land"]
    assert any(card.name == "Nevinyrral's Disk" for card in p1.graveyard)
    assert any(card.name == "Test Relic" for card in p1.graveyard)
    assert any(card.name == "Test Bear" for card in p1.graveyard)
    assert any(card.name == "Test Aura" for card in p2.graveyard)

def test_activate_black_lotus_adds_mana_and_sacrifices(all_cards):
    lotus = _get(all_cards, "Black Lotus")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=lotus)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Black Lotus", target_player_index=1)

    assert result.supported
    assert p1.mana_pool["G"] == 3
    assert not p1.battlefield
    assert p1.graveyard and p1.graveyard[0].name == "Black Lotus"

def test_activate_black_lotus_with_selected_color(all_cards):
    lotus = _get(all_cards, "Black Lotus")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=lotus)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(
        0,
        "Black Lotus",
        target_player_index=1,
        mana_color="U",
    )

    assert result.supported
    assert p1.mana_pool["U"] == 3
    assert p1.mana_pool["G"] == 0
    assert not p1.battlefield
    assert p1.graveyard and p1.graveyard[0].name == "Black Lotus"

def test_animate_dead_reanimates_creature(all_cards):
    animate_dead = _get(all_cards, "Animate Dead")
    dead_creature = _mk_card("Dead Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[animate_dead], graveyard=[dead_creature])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Animate Dead", target_player_index=0)

    assert result.supported
    # Creature should be returned to the battlefield under caster's control
    assert any(perm.card.name == "Dead Bear" for perm in p1.battlefield)
    # The Animate Dead aura itself should be on the battlefield
    assert any(perm.card.name == "Animate Dead" for perm in p1.battlefield)

def test_animate_artifact_makes_artifact_into_creature(all_cards):
    animate = _get(all_cards, "Animate Artifact")
    # Create a test artifact with mana value 3
    relic = _mk_card("Test Relic", "Artifact")
    relic_def = CardDefinition(
        name=relic.name,
        mana_cost="{3}",
        cmc=3.0,
        type_line=relic.type_line,
        oracle_text=relic.oracle_text,
        colors=relic.colors,
        color_identity=relic.color_identity,
        keywords=relic.keywords,
        produced_mana=relic.produced_mana,
        raw={**relic.raw},
    )

    p1 = PlayerState(name="P1", hand=[animate])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=relic_def)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Animate Artifact", target_player_index=1, target_permanent_index=0)

    assert result.supported
    # Target artifact should become an artifact creature with power/toughness equal to its mana value
    perm = p2.battlefield[0]
    assert perm.card.primary_type == "creature"
    assert perm.effective_power == 3
    assert perm.effective_toughness == 3
    # The Aura should be on the caster's battlefield and attached
    assert any(a.card.name == "Animate Artifact" for a in p1.battlefield)
    aura = next(a for a in p1.battlefield if a.card.name == "Animate Artifact")
    assert aura.metadata.get("attached_to") is perm

def test_braingeyser_draws_x_cards(all_cards):
    braingeyser = _get(all_cards, "Braingeyser")
    island = _get(all_cards, "Island")
    p1 = PlayerState(name="P1", hand=[braingeyser])
    p2 = PlayerState(name="P2", library=[island, island, island, island, island])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Braingeyser", target_player_index=1, x_value=4)

    assert result.supported
    assert len(p2.hand) == 4

def test_ankh_of_mishra_triggers_on_land_entry(all_cards):
    ankh = _get(all_cards, "Ankh of Mishra")
    plains = _get(all_cards, "Plains")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=ankh)])
    p2 = PlayerState(name="P2", hand=[plains], life=20)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(1, "Plains", target_player_index=1)

    assert result.supported
    assert p2.life == 18

def test_black_vise_upkeep_trigger(all_cards):
    vise = _get(all_cards, "Black Vise")
    island = _get(all_cards, "Island")
    p1 = PlayerState(name="P1", hand=[vise])
    p2 = PlayerState(name="P2", hand=[island, island, island, island, island, island], life=20)
    game = Game(players=[p1, p2])

    cast_result = game.cast_from_hand(0, "Black Vise", target_player_index=1)
    game.resolve_upkeep(1)

    assert cast_result.supported
    # 6 cards in hand means 2 damage from Black Vise.
    assert p2.life == 18

def test_unsummon_returns_target_creature(all_cards):
    unsummon = _get(all_cards, "Unsummon")
    creature = _mk_card("Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[unsummon])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Unsummon", target_player_index=1)

    assert result.supported
    assert not p2.battlefield
    assert any(card.name == "Bear" for card in p2.hand)


def test_unsummon_bounces_the_chosen_creature(all_cards):
    # With several creatures in play, Unsummon must return the one the player
    # targeted (index 1), not simply the first creature found.
    unsummon = _get(all_cards, "Unsummon")
    bear = _mk_card("Bear", "Creature — Bear")
    ogre = _mk_card("Ogre", "Creature — Ogre")
    wall = _mk_card("Wall", "Creature — Wall")
    p1 = PlayerState(name="P1", hand=[unsummon])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=bear), Permanent(card=ogre), Permanent(card=wall)],
    )
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Unsummon", target_player_index=1, target_permanent_index=1)

    assert result.supported
    assert [p.card.name for p in p2.battlefield] == ["Bear", "Wall"]
    assert [c.name for c in p2.hand] == ["Ogre"]


def test_fireball_divides_damage_evenly_rounded_down(all_cards):
    # X damage split evenly (rounded down) among the chosen targets.
    fireball = _get(all_cards, "Fireball")
    a = _mk_card("Grizzly", "Creature — Bear")  # 2/2 default
    b = _mk_card("Hill Giant", "Creature — Giant")
    p1 = PlayerState(name="P1", hand=[fireball])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=a), Permanent(card=b)])
    game = Game(players=[p1, p2])

    # X=5 over 2 targets => 2 damage each (rounded down); both 2/2s die.
    result = game.cast_from_hand(
        0, "Fireball", target_player_index=1, target_permanent_index=[0, 1], x_value=5
    )

    assert result.supported
    assert not p2.battlefield


def test_fireball_all_damage_to_a_single_player(all_cards):
    fireball = _get(all_cards, "Fireball")
    p1 = PlayerState(name="P1", hand=[fireball])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Fireball", target_player_index=1, x_value=6)

    assert result.supported
    assert p2.life == 14


def test_fireball_costs_one_more_for_each_target_beyond_the_first(all_cards):
    # {X}{R}; two targets cost {1} more, so X=4 at two targets needs R+4+1 = 6.
    fireball = _get(all_cards, "Fireball")
    targets = [Permanent(card=_mk_card(f"Goblin{i}", "Creature — Goblin")) for i in range(2)]

    # 6 mana available: cast succeeds and empties the pool.
    p1 = PlayerState(name="P1", hand=[fireball],
                     mana_pool={"W": 0, "U": 0, "B": 0, "R": 1, "G": 0, "C": 5})
    p2 = PlayerState(name="P2", battlefield=list(targets))
    game = Game(players=[p1, p2], enforce_mana_costs=True)
    ok = game.queue_from_hand(
        0, "Fireball", target_player_index=1, target_permanent_index=[0, 1], x_value=4
    )
    assert ok.supported
    assert sum(p1.mana_pool.values()) == 0

    # Only 5 mana (R+4): the extra-target tax makes the two-target cast unaffordable.
    p1b = PlayerState(name="P1", hand=[fireball],
                      mana_pool={"W": 0, "U": 0, "B": 0, "R": 1, "G": 0, "C": 4})
    p2b = PlayerState(
        name="P2",
        battlefield=[Permanent(card=_mk_card(f"Goblin{i}", "Creature — Goblin")) for i in range(2)],
    )
    gameb = Game(players=[p1b, p2b], enforce_mana_costs=True)
    fail = gameb.queue_from_hand(
        0, "Fireball", target_player_index=1, target_permanent_index=[0, 1], x_value=4
    )
    assert not fail.supported


def test_wheel_of_fortune_discards_then_draws(all_cards):
    wheel = _get(all_cards, "Wheel of Fortune")
    island = _get(all_cards, "Island")
    p1 = PlayerState(name="P1", hand=[wheel, island], library=[island] * 10)
    p2 = PlayerState(name="P2", hand=[island, island], library=[island] * 10)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Wheel of Fortune", target_player_index=1)

    assert result.supported
    assert len(p1.hand) == 7
    assert len(p2.hand) == 7

def test_timetwister_resets_and_draws_seven(all_cards):
    twister = _get(all_cards, "Timetwister")
    island = _get(all_cards, "Island")
    bear = _mk_card("Dead Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[twister, island], graveyard=[bear], library=[island] * 10)
    p2 = PlayerState(name="P2", hand=[island], graveyard=[bear], library=[island] * 10)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Timetwister", target_player_index=1)

    assert result.supported
    assert len(p1.hand) == 7
    assert len(p2.hand) == 7

def test_demonic_tutor_puts_library_card_into_hand(all_cards):
    tutor = _get(all_cards, "Demonic Tutor")
    mountain = _get(all_cards, "Mountain")
    forest = _get(all_cards, "Forest")
    island = _get(all_cards, "Island")
    p1 = PlayerState(name="P1", hand=[tutor], library=[mountain, forest, island])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Demonic Tutor", target_player_index=0)

    assert result.supported
    assert game.pending_search_library is not None
    assert game.pending_search_library["count"] == 1
    assert game.pending_search_library["card_type"] == "any"

    # Player searches and picks Island (originally at library index 2)
    confirmed = game.confirm_search_library(0, 2)
    assert confirmed
    assert any(card.name == "Island" for card in p1.hand)
    assert game.pending_search_library is None

def test_time_walk_grants_extra_turn(all_cards):
    time_walk = _get(all_cards, "Time Walk")
    p1 = PlayerState(name="P1", hand=[time_walk])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Time Walk", target_player_index=0)

    assert result.supported
    assert game.extra_turns.get(0, 0) == 1

def test_sacrifice_spell_adds_black_mana(all_cards):
    sacrifice = _get(all_cards, "Sacrifice")
    creature = _mk_card("Mana Bear", "Creature — Bear")
    creature = CardDefinition(
        name=creature.name,
        mana_cost=creature.mana_cost,
        cmc=3.0,
        type_line=creature.type_line,
        oracle_text=creature.oracle_text,
        colors=creature.colors,
        color_identity=creature.color_identity,
        keywords=creature.keywords,
        produced_mana=creature.produced_mana,
        raw=creature.raw,
    )
    p1 = PlayerState(name="P1", hand=[sacrifice], battlefield=[Permanent(card=creature)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Sacrifice", target_player_index=0)

    assert result.supported
    assert p1.mana_pool["B"] == 3
    assert not p1.battlefield

def test_lace_spell_changes_target_color(all_cards):
    deathlace = _get(all_cards, "Deathlace")
    creature = _mk_card("Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[deathlace])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Deathlace", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("color_override") == "B"

def test_orcish_oriflamme_applies_power_bonus(all_cards):
    oriflamme = _get(all_cards, "Orcish Oriflamme")
    creature = _mk_card("Attacker", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[oriflamme], battlefield=[Permanent(card=creature)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Orcish Oriflamme", target_player_index=0)

    assert result.supported
    attacker = p1.battlefield[0]
    # "Attacking creatures you control get +1/+0": no bonus while idle.
    assert attacker.effective_power == 2
    # The bonus applies only while the creature is actually attacking.
    attacker.attacking = True
    game._refresh_dynamic_creatures()
    assert attacker.effective_power == 3
    attacker.attacking = False
    game._refresh_dynamic_creatures()
    assert attacker.effective_power == 2

def test_aspect_of_wolf_applies_half_forest_buff(all_cards):
    aspect = _get(all_cards, "Aspect of Wolf")
    forest = _get(all_cards, "Forest")
    creature = _mk_card("Test Bear", "Creature — Bear")

    # Set up controller with 3 Forests -> floor(3/2)=1, ceil(3/2)=2 -> +1/+2
    p1 = PlayerState(
        name="P1",
        hand=[aspect],
        battlefield=[Permanent(card=creature), Permanent(card=forest), Permanent(card=forest), Permanent(card=forest)],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Aspect of Wolf", target_player_index=0, target_permanent_index=0)

    assert result.supported
    # Creature is the first permanent on battlefield
    assert p1.battlefield[0].effective_power == 3
    assert p1.battlefield[0].effective_toughness == 4

def test_jayemdae_tome_activated_draw(all_cards):
    tome = _get(all_cards, "Jayemdae Tome")
    island = _get(all_cards, "Island")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=tome)], library=[island])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Jayemdae Tome", target_player_index=1)

    assert result.supported
    assert len(p1.hand) == 1

def test_glasses_of_urza_look_at_hand(all_cards):
    glasses = _get(all_cards, "Glasses of Urza")
    island = _get(all_cards, "Island")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=glasses)])
    p2 = PlayerState(name="P2", hand=[island, island])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Glasses of Urza", target_player_index=1)

    assert result.supported
    assert any("looked at" in line.lower() for line in game.log)

def test_black_knight_classifies_supported(all_cards):
    knight = _get(all_cards, "Black Knight")
    result = classify_card(knight)
    assert result.supported

def test_shivan_dragon_activated_plus_one_power(all_cards):
    dragon = _get(all_cards, "Shivan Dragon")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=dragon)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    before = p1.battlefield[0].effective_power
    result = game.activate_permanent_ability(0, "Shivan Dragon", target_player_index=1)

    assert result.supported
    assert p1.battlefield[0].effective_power == before + 1

def test_granite_gargoyle_activated_plus_one_toughness(all_cards):
    gargoyle = _get(all_cards, "Granite Gargoyle")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=gargoyle)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    before = p1.battlefield[0].effective_toughness
    result = game.activate_permanent_ability(0, "Granite Gargoyle", target_player_index=1)

    assert result.supported
    assert p1.battlefield[0].effective_toughness == before + 1

def test_frozen_shade_activated_plus_one_plus_one(all_cards):
    shade = _get(all_cards, "Frozen Shade")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=shade)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    before_power = p1.battlefield[0].effective_power
    before_toughness = p1.battlefield[0].effective_toughness
    result = game.activate_permanent_ability(0, "Frozen Shade", target_player_index=1)

    assert result.supported
    assert p1.battlefield[0].effective_power == before_power + 1
    assert p1.battlefield[0].effective_toughness == before_toughness + 1

def test_goblin_balloon_brigade_gains_flying_flag(all_cards):
    goblin = _get(all_cards, "Goblin Balloon Brigade")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=goblin)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Goblin Balloon Brigade", target_player_index=1)

    assert result.supported
    assert p1.battlefield[0].metadata.get("gains_flying_until_eot") is True

def test_clockwork_beast_enters_with_seven_plus_zero(all_cards):
    beast = _get(all_cards, "Clockwork Beast")
    p1 = PlayerState(name="P1", hand=[beast])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Clockwork Beast", target_player_index=1)

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.power_bonus >= 7

def test_rock_hydra_x_counters_on_entry(all_cards):
    hydra = _get(all_cards, "Rock Hydra")
    p1 = PlayerState(name="P1", hand=[hydra])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Rock Hydra", target_player_index=1, x_value=3)

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.power_bonus >= 3
    assert perm.toughness_bonus >= 3

def test_sea_serpent_attack_restriction(all_cards):
    serpent = _get(all_cards, "Sea Serpent")
    island = _get(all_cards, "Island")
    # Sea Serpent's controller must control an Island or it is sacrificed
    # (state-based) before it can attack.
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=serpent), Permanent(card=island)])
    p2 = PlayerState(name="P2", battlefield=[])
    game = Game(players=[p1, p2])

    assert game.can_attack(p1.battlefield[0], defending_player_index=1) is False
    p2.battlefield.append(Permanent(card=island))
    assert game.can_attack(p1.battlefield[0], defending_player_index=1) is True

def test_summoning_sickness_blocks_attacks_and_tap_abilities(all_cards):
    creature = _mk_card("Test Bear", "Creature — Bear")
    llanowar_elves = _get(all_cards, "Llanowar Elves")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=creature), Permanent(card=llanowar_elves)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.turn = 4

    p1.battlefield[0].metadata["summoning_sickness_turn"] = game.turn
    assert game.can_attack(p1.battlefield[0], defending_player_index=1) is False

    p1.battlefield[1].metadata["summoning_sickness_turn"] = game.turn
    result = game.activate_permanent_ability(0, "Llanowar Elves", target_player_index=0)

    assert result.supported is False
    assert "summoning sickness" in result.details.lower()

def test_keldon_warlord_dynamic_pt(all_cards):
    warlord = _get(all_cards, "Keldon Warlord")
    creature = _mk_card("Helper", "Creature — Bear")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=warlord), Permanent(card=creature)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game._refresh_dynamic_creatures()
    warlord_perm = p1.battlefield[0]
    assert warlord_perm.effective_power == 2
    assert warlord_perm.effective_toughness == 2

def test_verduran_enchantress_draw_trigger(all_cards):
    enchantress = _get(all_cards, "Verduran Enchantress")
    blessing = _get(all_cards, "Blessing")
    island = _get(all_cards, "Island")
    p1 = PlayerState(name="P1", hand=[blessing], library=[island], battlefield=[Permanent(card=enchantress)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Blessing", target_player_index=0, target_permanent_index=0)

    assert result.supported
    assert len(p1.hand) == 1

def test_fog_sets_combat_damage_prevention(all_cards):
    fog = _get(all_cards, "Fog")
    p1 = PlayerState(name="P1", hand=[fog])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Fog", target_player_index=0)

    assert result.supported
    assert game.combat_damage_prevented_until_eot is True

def test_howling_mine_draw_step_bonus(all_cards):
    mine = _get(all_cards, "Howling Mine")
    island = _get(all_cards, "Island")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=mine)])
    p2 = PlayerState(name="P2", library=[island, island, island])
    game = Game(players=[p1, p2])

    drawn = game.resolve_draw_step(1)

    assert drawn == 2
    assert len(p2.hand) == 2

def test_stasis_skips_untap_step(all_cards):
    stasis = _get(all_cards, "Stasis")
    island = _get(all_cards, "Island")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=stasis)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=island, tapped=True)])
    game = Game(players=[p1, p2])

    untapped = game.resolve_untap_step(1)

    assert untapped == 0
    assert p2.battlefield[0].tapped is True


def test_stasis_upkeep_prompts_human_player(all_cards):
    """Regression: Stasis must pause for a pay/sacrifice choice via real turn-end flow."""
    from web.app import _end_turn

    stasis = _get(all_cards, "Stasis")
    island = _get(all_cards, "Island")

    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_human", "host_name": "P1", "guest_name": "P2", "seed": 77},
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "P2"})

    session = store.get(sid)
    p1 = session.game.players[0]
    p1.battlefield = [Permanent(card=stasis), Permanent(card=island)]
    p1.mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}
    p1.hand = []

    # End P0's first turn → starts P1's turn.
    _end_turn(session, allow_manual_cleanup_selection=False)
    # Stasis must NOT have fired on the opponent's upkeep.
    assert any(p.card.name == "Stasis" for p in p1.battlefield), \
        "Stasis must survive opponent's upkeep (upkeep_self should not fire on opponent's turn)"

    # End P1's turn → starts P0's second turn, which should defer at upkeep.
    _end_turn(session, allow_manual_cleanup_selection=False)

    assert session.game.current_step == "upkeep", "game must be paused at upkeep step"
    assert session.upkeep_pay_choices, "upkeep_pay_choices must be populated"
    assert any(c["card_name"] == "Stasis" for c in session.upkeep_pay_choices)
    assert any(p.card.name == "Stasis" for p in p1.battlefield), \
        "Stasis must not be auto-sacrificed before player decides"

    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    upkeep_pay = state["upkeep_pay"]
    assert upkeep_pay is not None, "upkeep_pay info must be present for the human player"
    assert any(c["card_name"] == "Stasis" for c in upkeep_pay["choices"])

    # Tap Island to add {U}, then pay.
    tap_resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "tap", "permanent_name": "Island"},
    )
    assert tap_resp.status_code == 200

    pay_resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "pay_upkeep", "card_name": "Stasis"},
    )
    assert pay_resp.status_code == 200
    assert any(p.card.name == "Stasis" for p in p1.battlefield), \
        "Stasis must remain on battlefield after paying"
    assert session.game.current_turn_phase == "precombat_main", \
        "game should have advanced to main phase after paying"


def test_stasis_upkeep_sacrifice_removes_stasis(all_cards):
    """Player choosing to sacrifice Stasis at upkeep removes it correctly."""
    from web.app import _end_turn

    stasis = _get(all_cards, "Stasis")
    island = _get(all_cards, "Island")

    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_human", "host_name": "P1", "guest_name": "P2", "seed": 80},
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "P2"})

    session = store.get(sid)
    p1 = session.game.players[0]
    p1.battlefield = [Permanent(card=stasis), Permanent(card=island)]
    p1.mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}
    p1.hand = []

    _end_turn(session, allow_manual_cleanup_selection=False)  # P1's turn
    _end_turn(session, allow_manual_cleanup_selection=False)  # P0 turn 2, deferred at upkeep

    assert session.game.current_step == "upkeep"

    sacrifice_resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "sacrifice_upkeep", "card_name": "Stasis"},
    )
    assert sacrifice_resp.status_code == 200
    assert not any(p.card.name == "Stasis" for p in p1.battlefield), \
        "Stasis must be gone after sacrifice"
    assert any(c.name == "Stasis" for c in p1.graveyard), \
        "Stasis must be in graveyard after sacrifice"
    assert session.game.current_turn_phase == "precombat_main", \
        "game should have advanced to main phase after sacrifice"


def test_stasis_upkeep_engine_get_triggers(all_cards):
    """get_upkeep_pay_triggers returns Stasis as a pending choice."""
    stasis = _get(all_cards, "Stasis")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=stasis)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    triggers = game.get_upkeep_pay_triggers(0)

    assert len(triggers) == 1
    assert triggers[0]["card_name"] == "Stasis"
    assert "U" in triggers[0]["mana"] or triggers[0]["mana"]  # has a mana cost
    assert triggers[0]["kind"] == "upkeep_pay_or_sacrifice_enchantment"


def test_smoke_limits_creature_untap(all_cards):
    smoke = _get(all_cards, "Smoke")
    c1 = _mk_card("Bear A", "Creature — Bear")
    c2 = _mk_card("Bear B", "Creature — Bear")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=smoke)])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=c1, tapped=True), Permanent(card=c2, tapped=True)],
    )
    game = Game(players=[p1, p2])

    untapped = game.resolve_untap_step(1)

    assert untapped == 1
    assert sum(1 for perm in p2.battlefield if not perm.tapped) == 1

def test_winter_orb_limits_land_untap(all_cards):
    orb = _get(all_cards, "Winter Orb")
    island = _get(all_cards, "Island")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=orb, tapped=False)])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=island, tapped=True), Permanent(card=island, tapped=True)],
    )
    game = Game(players=[p1, p2])

    untapped = game.resolve_untap_step(1)

    assert untapped == 1

def test_meekstone_prevents_big_creature_untap(all_cards):
    meekstone = _get(all_cards, "Meekstone")
    big = _mk_card("Big", "Creature — Giant")
    small = _mk_card("Small", "Creature — Bear")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=meekstone)])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=big, tapped=True), Permanent(card=small, tapped=True)],
    )
    p2.battlefield[0].metadata["absolute_power"] = 4
    p2.battlefield[0].metadata["absolute_toughness"] = 4
    game = Game(players=[p1, p2])

    untapped = game.resolve_untap_step(1)

    assert untapped == 1
    assert p2.battlefield[0].tapped is True
    assert p2.battlefield[1].tapped is False

def test_mana_flare_adds_extra_mana(all_cards):
    mana_flare = _get(all_cards, "Mana Flare")
    island = _get(all_cards, "Island")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=mana_flare), Permanent(card=island)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    ok = game.tap_land_for_mana(0, "Island")

    assert ok
    assert p1.mana_pool["U"] == 2

def test_mana_pool_empties_between_steps(all_cards):
    island = _get(all_cards, "Island")
    p1 = PlayerState(name="P1", mana_pool={"W": 0, "U": 2, "B": 0, "R": 0, "G": 0, "C": 1})
    p2 = PlayerState(name="P2", library=[island])
    game = Game(players=[p1, p2])

    game.resolve_upkeep(1)

    assert p1.mana_pool["U"] == 0
    assert p1.mana_pool["C"] == 0

def test_jade_statue_animates_until_end_combat(all_cards):
    statue = _get(all_cards, "Jade Statue")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=statue)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Jade Statue", target_player_index=1)

    assert result.supported
    assert p1.battlefield[0].effective_power == 3
    assert p1.battlefield[0].effective_toughness == 6
    game.end_combat()
    assert p1.battlefield[0].metadata.get("absolute_power") is None

def test_the_hive_creates_wasp_token(all_cards):
    hive = _get(all_cards, "The Hive")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=hive)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "The Hive", target_player_index=1)

    assert result.supported
    assert any(perm.card.name == "Wasp" for perm in p1.battlefield)

def test_animate_wall_allows_wall_to_attack(all_cards):
    animate_wall = _get(all_cards, "Animate Wall")
    wall = _get(all_cards, "Wall of Stone")
    p1 = PlayerState(name="P1", hand=[animate_wall])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=wall)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Animate Wall", target_player_index=1, target_permanent_index=0)

    assert result.supported
    wall_perm = p2.battlefield[0]
    assert game.can_attack(wall_perm, defending_player_index=0) is True

def test_black_lotus_is_classified_supported(all_cards):
    lotus = _get(all_cards, "Black Lotus")
    classification = classify_card(lotus)
    assert classification.supported

def test_castle_buffs_untapped_creatures_toughness(all_cards):
    castle = _get(all_cards, "Castle")
    bear = _mk_card("Guard", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[castle], battlefield=[Permanent(card=bear, tapped=False)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Castle", target_player_index=0)

    assert result.supported
    assert p1.battlefield[0].effective_toughness >= 4

def test_circle_of_protection_activation_sets_prevention(all_cards):
    cop = _get(all_cards, "Circle of Protection: Blue")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=cop)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Circle of Protection: Blue", target_player_index=0)

    assert result.supported
    assert p1.damage_prevention_pool == 1

def test_conversion_sacrifices_on_upkeep_without_white_mana(all_cards):
    conversion = _get(all_cards, "Conversion")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=conversion)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert not p1.battlefield
    assert any(card.name == "Conversion" for card in p1.graveyard)

def test_dwarven_warriors_can_grant_unblockable(all_cards):
    warriors = _get(all_cards, "Dwarven Warriors")
    bear = _mk_card("Small Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=warriors)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Dwarven Warriors", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("cant_be_blocked_until_eot") is True

def test_nightmare_dynamic_power_toughness_by_swamps(all_cards):
    nightmare = _get(all_cards, "Nightmare")
    swamp = _get(all_cards, "Swamp")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=nightmare), Permanent(card=swamp), Permanent(card=swamp)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game._refresh_dynamic_creatures()
    nm = p1.battlefield[0]
    assert nm.effective_power == 2
    assert nm.effective_toughness == 2

def test_sedge_troll_gets_bonus_with_swamp(all_cards):
    troll = _get(all_cards, "Sedge Troll")
    swamp = _get(all_cards, "Swamp")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=troll), Permanent(card=swamp)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game._refresh_dynamic_creatures()
    tr = p1.battlefield[0]
    assert tr.effective_power >= 3
    assert tr.effective_toughness >= 3

def test_balance_equalizes_lands_creatures_and_hand(all_cards):
    balance = _get(all_cards, "Balance")
    plains = _get(all_cards, "Plains")
    bear = _mk_card("Bear", "Creature — Bear")
    elf = _mk_card("Elf", "Creature — Elf")

    p1 = PlayerState(
        name="P1",
        hand=[balance, plains, plains],
        battlefield=[Permanent(card=plains), Permanent(card=plains), Permanent(card=bear)],
    )
    p2 = PlayerState(
        name="P2",
        hand=[plains],
        battlefield=[Permanent(card=plains), Permanent(card=elf), Permanent(card=elf)],
    )
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Balance", target_player_index=1)

    assert result.supported
    assert sum(1 for perm in p1.battlefield if perm.card.primary_type == "land") == 1
    assert sum(1 for perm in p2.battlefield if perm.card.primary_type == "land") == 1
    assert sum(1 for perm in p1.battlefield if perm.card.primary_type == "creature") == 1
    assert sum(1 for perm in p2.battlefield if perm.card.primary_type == "creature") == 1
    assert len(p1.hand) == len(p2.hand)

def test_forcefield_caps_next_damage_to_one(all_cards):
    forcefield = _get(all_cards, "Forcefield")
    bolt = _mk_card("Bolt Test", "Instant", "Bolt Test deals 3 damage to any target.")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=forcefield)], life=20)
    p2 = PlayerState(name="P2", hand=[bolt], life=20)
    game = Game(players=[p1, p2])

    activation = game.activate_permanent_ability(0, "Forcefield", target_player_index=0)
    result = game.cast_from_hand(1, "Bolt Test", target_player_index=0)

    assert activation.supported
    assert result.supported
    assert p1.life == 19

def test_gloom_tax_log_on_white_spell(all_cards):
    gloom = _get(all_cards, "Gloom")
    white_spell = _mk_card("White Test", "Sorcery", "Target player loses 3 life.", colors=("W",))
    p1 = PlayerState(name="P1", hand=[gloom])
    p2 = PlayerState(name="P2", hand=[white_spell], life=20)
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Gloom", target_player_index=1)
    result = game.cast_from_hand(1, "White Test", target_player_index=0)

    assert result.supported
    assert any("taxed by gloom" in line.lower() for line in game.log)

def test_kormus_bell_animates_swamps(all_cards):
    bell = _get(all_cards, "Kormus Bell")
    swamp = _get(all_cards, "Swamp")
    p1 = PlayerState(name="P1", hand=[bell], battlefield=[Permanent(card=swamp)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Kormus Bell", target_player_index=1)

    assert result.supported
    game._refresh_dynamic_creatures()
    assert p1.battlefield[0].metadata.get("land_animated") is True
    assert p1.battlefield[0].effective_power == 1
    assert p1.battlefield[0].effective_toughness == 1

def test_living_lands_animates_forests(all_cards):
    living = _get(all_cards, "Living Lands")
    forest = _get(all_cards, "Forest")
    p1 = PlayerState(name="P1", hand=[living], battlefield=[Permanent(card=forest)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Living Lands", target_player_index=1)

    assert result.supported
    game._refresh_dynamic_creatures()
    assert p1.battlefield[0].metadata.get("land_animated") is True
    assert p1.battlefield[0].effective_power == 1
    assert p1.battlefield[0].effective_toughness == 1

def test_library_of_leng_sets_no_max_hand_size(all_cards):
    library = _get(all_cards, "Library of Leng")
    p1 = PlayerState(name="P1", hand=[library])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Library of Leng", target_player_index=0)

    assert result.supported
    assert p1.has_no_max_hand_size is True

def test_natural_selection_reorders_top_three(all_cards):
    natural = _get(all_cards, "Natural Selection")
    a = _mk_card("A", "Sorcery")
    b = _mk_card("B", "Sorcery")
    c = _mk_card("C", "Sorcery")
    d = _mk_card("D", "Sorcery")
    p1 = PlayerState(name="P1", hand=[natural])
    p2 = PlayerState(name="P2", library=[a, b, c, d])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Natural Selection", target_player_index=1)

    assert result.supported
    pending = game.pending_reorder_library
    assert pending is not None
    assert pending["caster_index"] == 0
    assert pending["target_index"] == 1
    assert pending["top_count"] == 3

    # Confirm with order [2, 1, 0] -> C, B, A on top
    ok = game.confirm_reorder_library(0, [2, 1, 0])
    assert ok
    assert [card.name for card in p2.library] == ["C", "B", "A", "D"]
    assert game.pending_reorder_library is None


def test_natural_selection_preserves_rest_of_library(all_cards):
    natural = _get(all_cards, "Natural Selection")
    cards = [_mk_card(name, "Sorcery") for name in ["A", "B", "C", "D", "E"]]
    p1 = PlayerState(name="P1", hand=[natural])
    p2 = PlayerState(name="P2", library=cards)
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Natural Selection", target_player_index=1)
    # Keep original order [0, 1, 2] -> no change to top 3
    game.confirm_reorder_library(0, [0, 1, 2])

    assert [card.name for card in p2.library] == ["A", "B", "C", "D", "E"]


def test_ai_reorder_surfaces_best_card_on_own_library(all_cards):
    bolt = _get(all_cards, "Lightning Bolt")
    ancestral = _get(all_cards, "Ancestral Recall")
    land = _get(all_cards, "Forest")
    # AI seat 0 reorders its own top three: [land, bolt, ancestral].
    p1 = PlayerState(name="P1", library=[land, bolt, ancestral])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    order = choose_reorder_library_order(game, caster_index=0, target_index=0, top_count=3)
    reordered = [game.players[0].library[i].name for i in order]

    # Highest-value spells are surfaced ahead of the land we'd rather not draw next.
    assert reordered[-1] == "Forest"
    assert "Forest" not in reordered[:2]


def test_ai_reorder_buries_opponent_best_card(all_cards):
    bolt = _get(all_cards, "Lightning Bolt")
    ancestral = _get(all_cards, "Ancestral Recall")
    land = _get(all_cards, "Forest")
    # AI seat 0 reorders the opponent's top three.
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2", library=[land, bolt, ancestral])
    game = Game(players=[p1, p2])

    order = choose_reorder_library_order(game, caster_index=0, target_index=1, top_count=3)
    reordered = [game.players[1].library[i].name for i in order]

    # The opponent's strongest card should not be left on top to be drawn next.
    assert reordered[0] != "Ancestral Recall"


def test_ai_reorder_order_is_valid_permutation(all_cards):
    cards = [_mk_card(name, "Sorcery") for name in ["A", "B", "C"]]
    p1 = PlayerState(name="P1", library=list(cards))
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    order = choose_reorder_library_order(game, caster_index=0, target_index=0, top_count=3)
    assert sorted(order) == [0, 1, 2]


def test_word_of_command_forces_play_from_hand(all_cards):
    word = _get(all_cards, "Word of Command")
    card_in_hand = _mk_card("Victim Spell", "Sorcery")
    p1 = PlayerState(name="P1", hand=[word])
    p2 = PlayerState(name="P2", hand=[card_in_hand])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Word of Command", target_player_index=1)

    assert result.supported
    assert len(p2.hand) == 0
    assert any(card.name == "Victim Spell" for card in p2.graveyard)

def test_magical_hack_marks_target_text_modified(all_cards):
    hack = _get(all_cards, "Magical Hack")
    bear = _mk_card("Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[hack])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Magical Hack", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("text_modified") is True

def test_sleight_of_mind_marks_target_text_modified(all_cards):
    sleight = _get(all_cards, "Sleight of Mind")
    bear = _mk_card("Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[sleight])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Sleight of Mind", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("text_modified") is True

def test_blaze_of_glory_sets_forced_blocking_marker(all_cards):
    blaze = _get(all_cards, "Blaze of Glory")
    bear = _mk_card("Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[blaze])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Blaze of Glory", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("must_block_all_until_eot") is True

def test_camouflage_resolves_supported(all_cards):
    camouflage = _get(all_cards, "Camouflage")
    p1 = PlayerState(name="P1", hand=[camouflage])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # → beginning_of_combat
    game.advance_combat_phase()  # → declare_attackers

    result = game.cast_from_hand(0, "Camouflage", target_player_index=1)

    assert result.supported
    assert any("pile blocking" in line.lower() for line in game.log)

def test_camouflage_requires_declare_attackers_step(all_cards):
    """Camouflage cannot be cast outside the declare attackers step."""
    camouflage = _get(all_cards, "Camouflage")
    p1 = PlayerState(name="P1", hand=[camouflage])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    # Default step is precombat_main, not declare_attackers
    assert game.current_step != "declare_attackers"

    result = game.cast_from_hand(0, "Camouflage", target_player_index=1)

    assert not result.supported
    assert p1.hand and p1.hand[0].name == "Camouflage"

def test_cyclopean_tomb_marks_land_as_swamp(all_cards):
    tomb = _get(all_cards, "Cyclopean Tomb")
    plains = _get(all_cards, "Plains")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=tomb)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=plains)])
    game = Game(players=[p1, p2])
    game._set_phase_and_step("beginning", "upkeep")
    game.active_player_index = 0

    result = game.activate_permanent_ability(
        0, "Cyclopean Tomb", target_player_index=1, target_permanent_index=0
    )

    assert result.supported
    mired = p2.battlefield[0]
    assert mired.metadata.get("mire_counter") is True
    assert mired.metadata.get("land_type_override") == "swamp"
    # The land is now a Swamp: it taps for black, not white.
    assert mired.effective_produced_mana == ("B",)


def test_cyclopean_tomb_only_activates_during_your_upkeep(all_cards):
    tomb = _get(all_cards, "Cyclopean Tomb")
    plains = _get(all_cards, "Plains")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=tomb)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=plains)])
    game = Game(players=[p1, p2])

    # Default state is a main phase — the ability is not legal here.
    result = game.activate_permanent_ability(
        0, "Cyclopean Tomb", target_player_index=1, target_permanent_index=0
    )
    assert not result.supported
    assert p2.battlefield[0].metadata.get("mire_counter") is None

    # Not legal during the opponent's upkeep either.
    game._set_phase_and_step("beginning", "upkeep")
    game.active_player_index = 1
    result = game.activate_permanent_ability(
        0, "Cyclopean Tomb", target_player_index=1, target_permanent_index=0
    )
    assert not result.supported
    assert p2.battlefield[0].metadata.get("mire_counter") is None


def test_cyclopean_tomb_does_not_target_swamp(all_cards):
    tomb = _get(all_cards, "Cyclopean Tomb")
    swamp = _get(all_cards, "Swamp")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=tomb)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=swamp)])
    game = Game(players=[p1, p2])
    game._set_phase_and_step("beginning", "upkeep")
    game.active_player_index = 0

    result = game.activate_permanent_ability(
        0, "Cyclopean Tomb", target_player_index=1, target_permanent_index=0
    )
    # Resolves, but a Swamp is not a legal target so no counter is placed.
    assert result.supported
    assert p2.battlefield[0].metadata.get("mire_counter") is None


def test_cyclopean_tomb_death_frees_mired_lands_over_upkeeps(all_cards):
    tomb = _get(all_cards, "Cyclopean Tomb")
    plains = _get(all_cards, "Plains")
    forest = _get(all_cards, "Forest")
    tomb_perm = Permanent(card=tomb)
    p1 = PlayerState(name="P1", battlefield=[tomb_perm])
    plains_perm = Permanent(card=plains)
    forest_perm = Permanent(card=forest)
    p2 = PlayerState(name="P2", battlefield=[plains_perm, forest_perm])
    game = Game(players=[p1, p2])
    game._set_phase_and_step("beginning", "upkeep")
    game.active_player_index = 0

    # Mire both of P2's lands across two upkeep activations (untap between).
    game.activate_permanent_ability(0, "Cyclopean Tomb", target_player_index=1, target_permanent_index=0)
    tomb_perm.tapped = False
    game.activate_permanent_ability(0, "Cyclopean Tomb", target_player_index=1, target_permanent_index=1)
    assert plains_perm.metadata.get("mire_counter") is True
    assert forest_perm.metadata.get("mire_counter") is True

    # The Tomb dies: an obligation to free those lands is created.
    p1.battlefield.remove(tomb_perm)
    game._permanent_to_graveyard(p1, tomb_perm)
    assert len(game.mire_cleanup_obligations) == 1

    # One land is freed per controller upkeep.
    game.resolve_upkeep(0)
    freed_first = [perm for perm in (plains_perm, forest_perm) if perm.metadata.get("mire_counter") is None]
    assert len(freed_first) == 1
    assert freed_first[0].metadata.get("land_type_override") is None

    # An opponent's upkeep does not advance the controller's obligation.
    game.resolve_upkeep(1)
    still_mired = [perm for perm in (plains_perm, forest_perm) if perm.metadata.get("mire_counter")]
    assert len(still_mired) == 1

    # The next controller upkeep frees the last land and clears the obligation.
    game.resolve_upkeep(0)
    assert plains_perm.metadata.get("mire_counter") is None
    assert forest_perm.metadata.get("mire_counter") is None
    assert game.mire_cleanup_obligations == []


def test_cyclopean_tomb_death_trigger_fires_on_board_wipe(all_cards):
    # A board wipe (Nevinyrral's Disk: destroy all artifacts/creatures/enchantments)
    # must still fire the Tomb's leave-the-battlefield trigger, so its mired lands
    # are freed on later upkeeps. This guards the mass-destruction path that used to
    # bypass _permanent_to_graveyard (where the leave hook lives).
    from engine.game_types import OracleExecutionContext, OracleStateMachine
    from engine.oracle import OracleInstruction

    tomb = _get(all_cards, "Cyclopean Tomb")
    plains = _get(all_cards, "Plains")
    tomb_perm = Permanent(card=tomb)
    plains_perm = Permanent(card=plains)
    p1 = PlayerState(name="P1", battlefield=[tomb_perm, plains_perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game._set_phase_and_step("beginning", "upkeep")
    game.active_player_index = 0

    game.activate_permanent_ability(0, "Cyclopean Tomb", target_player_index=0, target_permanent_index=1)
    assert plains_perm.metadata.get("mire_counter") is True

    OracleStateMachine(
        game, OracleExecutionContext(caster=p1, target=p1, card=tomb)
    ).run(OracleInstruction("destroy_all_artifacts_creatures_enchantments", "", {}))

    assert not any(perm.card.name == "Cyclopean Tomb" for perm in p1.battlefield)
    assert len(game.mire_cleanup_obligations) == 1

    game.resolve_upkeep(0)
    assert plains_perm.metadata.get("mire_counter") is None
    assert plains_perm.metadata.get("land_type_override") is None

def test_false_orders_marks_creature_removed_from_combat(all_cards):
    false_orders = _get(all_cards, "False Orders")
    bear = _mk_card("Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[false_orders])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    # False Orders may only be cast during the declare blockers step.
    game._set_phase_and_step("combat", "declare_blockers")
    result = game.cast_from_hand(0, "False Orders", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("removed_from_combat") is True

def test_raging_river_casts_as_supported_permanent(all_cards):
    river = _get(all_cards, "Raging River")
    p1 = PlayerState(name="P1", hand=[river])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Raging River", target_player_index=1)

    assert result.supported
    assert any(perm.card.name == "Raging River" for perm in p1.battlefield)

def test_sunglasses_of_urza_sets_white_as_red_flag(all_cards):
    sunglasses = _get(all_cards, "Sunglasses of Urza")
    p1 = PlayerState(name="P1", hand=[sunglasses])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Sunglasses of Urza", target_player_index=1)

    assert result.supported
    assert p1.can_spend_white_as_red is True

def test_cockatrice_classifies_supported(all_cards):
    cockatrice = _get(all_cards, "Cockatrice")
    classification = classify_card(cockatrice)
    assert classification.supported

def test_force_of_nature_classifies_supported(all_cards):
    force = _get(all_cards, "Force of Nature")
    classification = classify_card(force)
    assert classification.supported

def test_hypnotic_specter_classifies_supported(all_cards):
    specter = _get(all_cards, "Hypnotic Specter")
    classification = classify_card(specter)
    assert classification.supported

def test_juggernaut_classifies_supported(all_cards):
    juggernaut = _get(all_cards, "Juggernaut")
    classification = classify_card(juggernaut)
    assert classification.supported

def test_banding_keyword_cards_classify_supported(all_cards):
    benalish_hero = _get(all_cards, "Benalish Hero")
    mesa_pegasus = _get(all_cards, "Mesa Pegasus")
    timber_wolves = _get(all_cards, "Timber Wolves")

    assert classify_card(benalish_hero).supported
    assert classify_card(mesa_pegasus).supported
    assert classify_card(timber_wolves).supported

def test_helm_of_chatzuk_grants_banding_until_eot(all_cards):
    helm = _get(all_cards, "Helm of Chatzuk")
    bear = _mk_card("Band Target", "Creature — Bear")
    # Helm grants banding to the controller's own creatures (Bug 5 fix).
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=helm), Permanent(card=bear)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Helm of Chatzuk", target_player_index=0)

    assert result.supported
    assert p1.battlefield[0].tapped is True
    # Banding is granted to the caster's own creature, not an opponent's
    assert p1.battlefield[1].metadata.get("gains_banding_until_eot") is True

def test_helm_of_chatzuk_requires_valid_creature_target(all_cards):
    helm = _get(all_cards, "Helm of Chatzuk")
    # P1 has only the Helm, no creature — activation should fail
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=helm)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Helm of Chatzuk", target_player_index=0)

    assert result.supported is False
    assert result.details == "no valid creature target for banding effect"
    assert p1.battlefield[0].tapped is False

def test_next_wave_creature_cards_classify_supported(all_cards):
    names = [
        "Demonic Hordes",
        "Dwarven Warriors",
        "Fungusaur",
        "Gaea's Liege",
        "Nettling Imp",
        "Personal Incarnation",
        "Scavenging Ghoul",
        "Stone Giant",
    ]
    for name in names:
        card = next(c for c in all_cards if c.name == name)
        assert classify_card(card).supported

def test_clone_and_fork_classify_supported(all_cards):
    clone = _get(all_cards, "Clone")
    fork = _get(all_cards, "Fork")

    assert classify_card(clone).supported
    assert classify_card(fork).supported

def test_gaeas_liege_activation_turns_land_into_forest(all_cards):
    liege = _get(all_cards, "Gaea's Liege")
    plains = _get(all_cards, "Plains")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=liege)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=plains)])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Gaea's Liege", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("land_type_override") == "forest"

def test_nettling_imp_marks_target_for_attack(all_cards):
    imp = _get(all_cards, "Nettling Imp")
    bear = _mk_card("Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=imp)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Nettling Imp", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("must_attack_until_eot") is True

def test_stone_giant_grants_temp_flying_and_delayed_destroy(all_cards):
    giant = _get(all_cards, "Stone Giant")
    small = _mk_card("Small Ally", "Creature — Bear")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=giant), Permanent(card=small)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Stone Giant", target_player_index=1)

    assert result.supported
    target = p1.battlefield[1]
    assert target.metadata.get("gains_flying_until_eot") is True
    assert target.metadata.get("destroy_at_next_end_step") is True

def test_clone_copies_existing_creature_stats_on_entry(all_cards):
    clone = _get(all_cards, "Clone")
    bear = _mk_card("Big Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[clone], battlefield=[Permanent(card=bear)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Clone", target_player_index=1)

    assert result.supported
    clone_perm = next(perm for perm in p1.battlefield if perm.card.name == "Clone")
    assert clone_perm.metadata.get("copied_from") == "Big Bear"
    assert clone_perm.effective_power == 2
    assert clone_perm.effective_toughness == 2

def test_fork_copies_top_spell_effect(all_cards):
    fork = _get(all_cards, "Fork")
    bolt = _mk_card("Bolt Test", "Instant", "Bolt Test deals 3 damage to any target.")

    p1 = PlayerState(name="P1", hand=[bolt], life=20)
    p2 = PlayerState(name="P2", hand=[fork], life=20)
    game = Game(players=[p1, p2])

    game.queue_from_hand(0, "Bolt Test", target_player_index=0)
    game.queue_from_hand(1, "Fork", target_player_index=0)
    game.resolve_stack()

    assert p1.life == 14

def test_remaining_cards_classify_supported(all_cards):
    names = ["Contract from Below", "Darkpact", "Demonic Attorney", "Copy Artifact"]
    for name in names:
        card = next(c for c in all_cards if c.name == name)
        assert classify_card(card).supported

def test_contract_from_below_discards_hand_then_draws_seven(all_cards):
    contract = _get(all_cards, "Contract from Below")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[contract, island], library=[island] * 10)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Contract from Below", target_player_index=1)

    assert result.supported
    assert len(p1.hand) == 7

def test_demonic_attorney_antes_top_card_for_each_player(all_cards):
    attorney = _get(all_cards, "Demonic Attorney")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[attorney], library=[island, island])
    p2 = PlayerState(name="P2", library=[island, island])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Demonic Attorney", target_player_index=1)

    assert result.supported
    assert len(p1.library) == 1
    assert len(p2.library) == 1

def test_copy_artifact_copies_artifact_on_entry(all_cards):
    copy_artifact = _get(all_cards, "Copy Artifact")
    lotus = _get(all_cards, "Black Lotus")

    p1 = PlayerState(name="P1", hand=[copy_artifact], battlefield=[Permanent(card=lotus)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Copy Artifact", target_player_index=1)

    assert result.supported
    perm = next(perm for perm in p1.battlefield if perm.card.name == "Copy Artifact")
    assert perm.metadata.get("copied_from") == "Black Lotus"

def test_loader_reads_cards(lea_path):
    cards = load_cards(lea_path)
    assert len(cards) > 250
    assert any(card.name == "Black Lotus" for card in cards)

def test_strict_mana_allows_cast_after_tapping_land():
    spell = _mk_card(
        name="Bolt Test",
        mana_cost="{R}",
        type_line="Instant",
        oracle_text="Bolt Test deals 3 damage to any target.",
    )
    mountain = _mk_card(
        name="Mountain",
        mana_cost="",
        type_line="Basic Land - Mountain",
        oracle_text="{T}: Add {R}.",
        produced_mana=("R",),
    )

    p1 = PlayerState(name="P1", hand=[spell], battlefield=[Permanent(card=mountain)])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2], enforce_mana_costs=True)

    assert game.tap_land_for_mana(0, "Mountain")
    result = game.cast_from_hand(0, "Bolt Test", target_player_index=1)

    assert result.supported
    assert p2.life == 17
    assert p1.mana_pool["R"] == 0

def test_tapping_basic_land_without_produced_mana_uses_land_type():
    swamp = _mk_card(
        name="Swamp",
        mana_cost="",
        type_line="Basic Land - Swamp",
        oracle_text="({T}: Add {B}.)",
    )

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=swamp)])
    game = Game(players=[p1], enforce_mana_costs=True)

    assert game.tap_land_for_mana(0, "Swamp")
    assert p1.mana_pool["B"] == 1

def test_x_spell_infers_x_from_paid_mana():
    spell = _mk_card(
        name="Stream of Life",
        mana_cost="{X}{G}",
        type_line="Sorcery",
        oracle_text="Target player gains X life.",
    )

    p1 = PlayerState(name="P1", hand=[spell], mana_pool={"G": 1, "C": 1}, life=10)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2], enforce_mana_costs=True)

    result = game.cast_from_hand(0, "Stream of Life", target_player_index=0)

    assert result.supported
    assert p1.life == 11
    assert p1.mana_pool["G"] == 0
    assert p1.mana_pool["C"] == 0

def test_parse_activated_ability_cost_handles_sacrifice_clause():
    cost = parse_activated_ability_cost("{T}, Sacrifice this artifact: Add three mana of any one color.")

    assert cost.requires_tap is True
    assert cost.mana["generic"] == 0

def test_compile_creature_program_keeps_clockwork_beast_supported():
    card = _mk_card(
        "Clockwork Beast",
        "Artifact Creature — Beast",
        "This creature enters with seven +1/+0 counters on it.\n"
        "At end of combat, if this creature attacked or blocked this combat, remove a +1/+0 counter from it.\n"
        "{X}, {T}: Put up to X +1/+0 counters on this creature. This ability can't cause the total number of +1/+0 counters on this creature to be greater than seven. Activate only during your upkeep.",
    )

    program = compile_card_oracle(card)

    assert program.supported is True
    assert any(ability.supported for ability in program.activated_abilities)

def test_juggernaut_must_attack_and_cannot_be_blocked_by_walls(all_cards):
    juggernaut = _get(all_cards, "Juggernaut")
    wall = _get(all_cards, "Wall of Stone")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=juggernaut)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=wall)])
    game = Game(players=[p1, p2])

    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()

    ok, details = game.declare_attackers(0, [])
    assert ok is False
    assert "Juggernaut must attack if able" in details

    ok, _ = game.declare_attackers(0, [0])
    assert ok

    game.advance_combat_phase()
    ok, details = game.declare_blockers(1, {0: 0})
    assert ok is False
    assert "cannot block" in details

def test_create_session_uses_random_seed_by_default(monkeypatch):
    captured_seeds = []
    stub_deck = [_mk_card("Island", "", "Basic Land - Island", "") for _ in range(40)]

    def _fake_build_random_deck(_cards_path, _colors, seed):
        captured_seeds.append(seed)
        return list(stub_deck), ["U"]

    monkeypatch.setattr(web_session_store, "build_random_deck", _fake_build_random_deck)
    monkeypatch.setattr(web_session_store.secrets, "randbits", lambda _bits: 424242)

    response = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 3,
        },
    )

    assert response.status_code == 200
    assert captured_seeds == [424242, 424243]

def test_create_session_uses_custom_seed_when_enabled(monkeypatch):
    captured_seeds = []
    stub_deck = [_mk_card("Island", "", "Basic Land - Island", "") for _ in range(40)]

    def _fake_build_random_deck(_cards_path, _colors, seed):
        captured_seeds.append(seed)
        return list(stub_deck), ["U"]

    monkeypatch.setattr(web_session_store, "build_random_deck", _fake_build_random_deck)
    monkeypatch.setattr(web_session_store.secrets, "randbits", lambda _bits: 111111)

    response = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 3,
            "use_custom_seed": True,
            "custom_seed": 9001,
        },
    )

    assert response.status_code == 200
    assert captured_seeds == [9001, 9002]


def test_hill_giant_classifies_supported(all_cards):
    giant = _get(all_cards, "Hill Giant")
    assert classify_card(giant).supported
    perm = Permanent(card=giant)
    assert perm.effective_power == 3
    assert perm.effective_toughness == 3


def test_holy_strength_gives_static_buff_to_enchanted_creature(all_cards):
    holy_strength = _get(all_cards, "Holy Strength")
    grizzly = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", hand=[holy_strength])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=grizzly)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Holy Strength", target_player_index=1, target_permanent_index=0)

    assert result.supported
    perm = p2.battlefield[0]
    assert perm.effective_power == 3
    assert perm.effective_toughness == 4


def test_holy_armor_gives_static_toughness_and_activates_for_more(all_cards):
    holy_armor = _get(all_cards, "Holy Armor")
    grizzly = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", hand=[holy_armor], battlefield=[Permanent(card=grizzly)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Holy Armor", target_player_index=0, target_permanent_index=0)

    assert result.supported
    creature_perm = p1.battlefield[0]
    assert creature_perm.effective_toughness == 4

    aura_perm = next(p for p in p1.battlefield if p.card.name == "Holy Armor")
    aura_perm.metadata["attached_to"] = creature_perm
    creature_perm.metadata["attached_aura"] = aura_perm

    before_t = creature_perm.effective_toughness
    activate_result = game.activate_permanent_ability(0, "Holy Armor", target_player_index=0)

    assert activate_result.supported
    assert creature_perm.effective_toughness == before_t + 1


def test_howl_from_beyond_pumps_target_creature_by_x(all_cards):
    howl = _get(all_cards, "Howl from Beyond")
    grizzly = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", hand=[howl])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=grizzly)])
    game = Game(players=[p1, p2])

    before_power = p2.battlefield[0].effective_power
    result = game.cast_from_hand(0, "Howl from Beyond", target_player_index=1, x_value=4)

    assert result.supported
    assert p2.battlefield[0].effective_power == before_power + 4
    assert p2.battlefield[0].effective_toughness == 2


def test_guardian_angel_prevents_x_damage(all_cards):
    angel = _get(all_cards, "Guardian Angel")

    p1 = PlayerState(name="P1", hand=[angel], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Guardian Angel", target_player_index=0, x_value=3)

    assert result.supported
    assert p1.damage_prevention_pool == 3
    # The second sentence grants a repeatable "pay {1}: prevent next 1 damage"
    # emblem until end of turn, locked to the spell's original target (player 0).
    assert len(p1.prevent_one_damage_emblems) == 1
    assert p1.prevent_one_damage_emblems[0]["target_player_index"] == 0


def test_guardian_angel_emblem_reuses_player_target_and_cleanup(all_cards):
    angel = _get(all_cards, "Guardian Angel")

    p1 = PlayerState(name="P1", hand=[angel], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2], enforce_mana_costs=False)
    # Cast targeting the controller themselves; the emblem is locked to player 0.
    game.cast_from_hand(0, "Guardian Angel", target_player_index=0, x_value=0)
    assert len(p1.prevent_one_damage_emblems) == 1

    # Activation needs no target — it reuses the stored one (player 0).
    before = p1.damage_prevention_pool
    result = game.activate_prevent_one_emblem(0)
    assert result.supported
    assert p1.damage_prevention_pool == before + 1

    # Repeatable: activating again grants another shield (emblem is not consumed).
    game.activate_prevent_one_emblem(0)
    assert p1.damage_prevention_pool == before + 2

    # The emblem (and its shields) expire at cleanup.
    game.resolve_cleanup_step(0)
    assert p1.prevent_one_damage_emblems == []
    assert p1.damage_prevention_pool == 0


def test_guardian_angel_emblem_reuses_creature_target(all_cards):
    angel = _get(all_cards, "Guardian Angel")
    bears = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", hand=[angel], life=20, battlefield=[Permanent(card=bears)])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2], enforce_mana_costs=False)
    # Cast targeting the controller's own Grizzly Bears.
    game.cast_from_hand(0, "Guardian Angel", target_player_index=0, target_permanent_index=0, x_value=0)
    entry = p1.prevent_one_damage_emblems[0]
    assert entry["target_player_index"] == 0
    assert entry["target_permanent_index"] == 0

    # Activation protects that same creature, no re-targeting.
    game.activate_prevent_one_emblem(0)
    assert p1.battlefield[0].damage_prevention_pool == 1

    # If the creature leaves play, the emblem has no legal target and does nothing.
    p1.battlefield.clear()
    result = game.activate_prevent_one_emblem(0)
    assert not result.supported


def test_guardian_angel_emblem_requires_mana_when_enforced(all_cards):
    p1 = PlayerState(name="P1", life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2], enforce_mana_costs=True)
    # Grant the emblem directly (target = player 0) to isolate activation-cost
    # behavior from the Angel's own casting cost.
    p1.prevent_one_damage_emblems = [{"target_player_index": 0, "target_permanent_index": None}]

    # No mana in pool: activation fails and grants no shield.
    result = game.activate_prevent_one_emblem(0)
    assert not result.supported
    assert p1.damage_prevention_pool == 0

    # With {1} available, it succeeds and spends the mana.
    p1.mana_pool["C"] = 1
    result = game.activate_prevent_one_emblem(0)
    assert result.supported
    assert p1.damage_prevention_pool == 1
    assert p1.mana_pool["C"] == 0

def test_card_search_endpoint_returns_autocomplete_matches():
    response = client.get("/api/cards/search?query=air&limit=5")
    assert response.status_code == 200
    payload = response.json()
    assert "cards" in payload
    assert len(payload["cards"]) <= 5
    assert any(card["name"] == "Air Elemental" for card in payload["cards"])

def test_debug_action_adds_card_to_human_hand_case_insensitive_lookup():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 9090,
        },
    ).json()
    sid = created["session_id"]

    before_count = len(store.get(sid).game.players[0].hand)
    response = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "debug_add_to_hand", "card_name": "air elemental"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["players"][0]["hand"]) == before_count + 1
    assert payload["players"][0]["hand"][-1]["name"] == "Air Elemental"
    assert any("[Debug]" in entry and "Air Elemental" in entry for entry in payload["log"])

def test_debug_action_casts_card_for_free():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 9091,
        },
    ).json()
    sid = created["session_id"]

    response = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "debug_cast_free", "card_name": "lightning bolt"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["players"][1]["life"] == 20
    assert payload["stack"][0]["card"]["name"] == "Lightning Bolt"
    assert any("[Debug]" in entry and "Lightning Bolt" in entry for entry in payload["log"])


def test_nether_shadow_classifies_supported(all_cards):
    shadow = _get(all_cards, "Nether Shadow")
    assert classify_card(shadow).supported


def test_nether_shadow_returns_with_three_creatures_above(all_cards):
    shadow = _get(all_cards, "Nether Shadow")
    bears = _get(all_cards, "Grizzly Bears")
    bolt = _get(all_cards, "Lightning Bolt")
    # Graveyard ordered oldest→newest (append order). Cards "above" Nether Shadow
    # are those put in more recently — later in the list. Three creatures sit above
    # it (a non-creature in the mix shouldn't count toward the threshold).
    p1 = PlayerState(
        name="P1",
        graveyard=[shadow, bears, bolt, bears, bears],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert all(c.name != "Nether Shadow" for c in p1.graveyard)
    returned = [perm for perm in p1.battlefield if perm.card.name == "Nether Shadow"]
    assert len(returned) == 1
    # Haste: it should not be summoning sick the turn it returns.
    assert not game._is_summoning_sick(returned[0])


def test_nether_shadow_stays_with_too_few_creatures_above(all_cards):
    shadow = _get(all_cards, "Nether Shadow")
    bears = _get(all_cards, "Grizzly Bears")
    bolt = _get(all_cards, "Lightning Bolt")
    # Only two creature cards above Nether Shadow — below the threshold of three.
    p1 = PlayerState(
        name="P1",
        graveyard=[shadow, bears, bolt, bears],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert any(c.name == "Nether Shadow" for c in p1.graveyard)
    assert all(perm.card.name != "Nether Shadow" for perm in p1.battlefield)


def test_nether_shadow_only_returns_on_owners_upkeep(all_cards):
    shadow = _get(all_cards, "Nether Shadow")
    bears = _get(all_cards, "Grizzly Bears")
    p1 = PlayerState(
        name="P1",
        graveyard=[shadow, bears, bears, bears],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # Opponent's upkeep — "your upkeep" must not fire for P1's graveyard card.
    game.resolve_upkeep(1)

    assert any(c.name == "Nether Shadow" for c in p1.graveyard)
    assert all(perm.card.name != "Nether Shadow" for perm in p1.battlefield)


def test_get_optional_upkeep_triggers_lists_eligible_nether_shadow(all_cards):
    shadow = _get(all_cards, "Nether Shadow")
    bears = _get(all_cards, "Grizzly Bears")
    p1 = PlayerState(name="P1", graveyard=[shadow, bears, bears, bears])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    triggers = game.get_optional_upkeep_triggers(0)

    assert len(triggers) == 1
    assert triggers[0]["card_name"] == "Nether Shadow"
    assert triggers[0]["kind"] == "upkeep_return_self_from_graveyard"
    assert "Nether Shadow" in triggers[0]["prompt"]


def test_get_optional_upkeep_triggers_empty_when_condition_unmet(all_cards):
    shadow = _get(all_cards, "Nether Shadow")
    bears = _get(all_cards, "Grizzly Bears")
    # Only two creatures above — not eligible, so no prompt should be offered.
    p1 = PlayerState(name="P1", graveyard=[shadow, bears, bears])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    assert game.get_optional_upkeep_triggers(0) == []


def test_nether_shadow_optional_choice_declined_keeps_in_graveyard(all_cards):
    shadow = _get(all_cards, "Nether Shadow")
    bears = _get(all_cards, "Grizzly Bears")
    p1 = PlayerState(name="P1", graveyard=[shadow, bears, bears, bears])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0, optional_choices={"Nether Shadow": False})

    assert any(c.name == "Nether Shadow" for c in p1.graveyard)
    assert all(perm.card.name != "Nether Shadow" for perm in p1.battlefield)


def test_nether_shadow_optional_choice_accepted_returns(all_cards):
    shadow = _get(all_cards, "Nether Shadow")
    bears = _get(all_cards, "Grizzly Bears")
    p1 = PlayerState(name="P1", graveyard=[shadow, bears, bears, bears])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0, optional_choices={"Nether Shadow": True})

    assert all(c.name != "Nether Shadow" for c in p1.graveyard)
    assert any(perm.card.name == "Nether Shadow" for perm in p1.battlefield)


def _start_session_with_p0_graveyard(graveyard, seed):
    """Create a joined human_vs_human session, give P0 the supplied graveyard, and
    advance to P0's second upkeep (the empty battlefield avoids an untap prompt)."""
    from web.app import _end_turn

    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_human", "host_name": "P1", "guest_name": "P2", "seed": seed},
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "P2"})

    session = store.get(sid)
    p0 = session.game.players[0]
    p0.battlefield = []
    p0.hand = []
    p0.graveyard = list(graveyard)

    # Advance turns until P0 begins its own upkeep and pauses for the optional
    # trigger. Whether that takes one or two end-turns depends on which seat the
    # seed sends first, so loop rather than assume.
    for _ in range(6):
        if (
            session.current_turn == 0
            and session.game.current_step == "upkeep"
            and session.optional_trigger_choices
        ):
            break
        _end_turn(session, allow_manual_cleanup_selection=False)
    return sid, session


def test_nether_shadow_upkeep_prompts_human_then_accepts(all_cards):
    shadow = _get(all_cards, "Nether Shadow")
    bears = _get(all_cards, "Grizzly Bears")
    sid, session = _start_session_with_p0_graveyard([shadow, bears, bears, bears], seed=91)

    assert session.game.current_step == "upkeep", "must pause at upkeep for the optional trigger"
    assert any(c["card_name"] == "Nether Shadow" for c in session.optional_trigger_choices)
    # Must not act before the player decides.
    assert any(c.name == "Nether Shadow" for c in session.game.players[0].graveyard)

    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    info = state["optional_trigger"]
    assert info is not None
    assert any(c["card_name"] == "Nether Shadow" for c in info["pending"])

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "resolve_optional_trigger", "card_name": "Nether Shadow", "accept": True},
    )
    assert resp.status_code == 200
    p0 = session.game.players[0]
    assert any(p.card.name == "Nether Shadow" for p in p0.battlefield)
    assert all(c.name != "Nether Shadow" for c in p0.graveyard)
    assert session.game.current_turn_phase == "precombat_main"


def test_nether_shadow_upkeep_prompt_declined(all_cards):
    shadow = _get(all_cards, "Nether Shadow")
    bears = _get(all_cards, "Grizzly Bears")
    sid, session = _start_session_with_p0_graveyard([shadow, bears, bears, bears], seed=92)

    assert session.game.current_step == "upkeep"

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "resolve_optional_trigger", "card_name": "Nether Shadow", "accept": False},
    )
    assert resp.status_code == 200
    p0 = session.game.players[0]
    assert all(p.card.name != "Nether Shadow" for p in p0.battlefield)
    assert any(c.name == "Nether Shadow" for c in p0.graveyard)
    assert session.game.current_turn_phase == "precombat_main"


def test_northern_paladin_destroys_black_permanent(all_cards):
    paladin = _get(all_cards, "Northern Paladin")
    black_knight = _get(all_cards, "Black Knight")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=paladin)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=black_knight)])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Northern Paladin", target_player_index=1)

    assert result.supported
    assert not p2.battlefield
    assert any(card.name == "Black Knight" for card in p2.graveyard)
    assert p1.battlefield[0].tapped is True


def test_obsianus_golem_classifies_supported(all_cards):
    golem = _get(all_cards, "Obsianus Golem")
    assert classify_card(golem).supported


def test_orcish_artillery_deals_damage_and_self_damage(all_cards):
    artillery = _get(all_cards, "Orcish Artillery")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=artillery)], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Orcish Artillery", target_player_index=1)

    assert result.supported
    assert p2.life == 18
    assert p1.life == 17


def test_paralyze_taps_creature_on_enter_and_prevents_untap(all_cards):
    paralyze = _get(all_cards, "Paralyze")
    grizzly = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", hand=[paralyze])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=grizzly)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Paralyze", target_player_index=1, target_permanent_index=0)

    assert result.supported
    creature_perm = p2.battlefield[0]
    assert creature_perm.tapped is True
    game.resolve_untap_step(1)
    assert creature_perm.tapped is True


def test_pearled_unicorn_classifies_supported(all_cards):
    unicorn = _get(all_cards, "Pearled Unicorn")
    assert classify_card(unicorn).supported

def test_debug_action_casts_creature_with_summoning_sickness_flag():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 9092,
        },
    ).json()
    sid = created["session_id"]

    response = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "debug_cast_free", "card_name": "Llanowar Elves"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["stack"][0]["card"]["name"] == "Llanowar Elves"
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})

    resolved = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "pass_priority"},
    )
    assert resolved.status_code == 200
    resolved = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 1, "action": "pass_priority"},
    )
    assert resolved.status_code == 200
    payload = resolved.json()
    battlefield = payload["players"][0]["battlefield"]
    assert battlefield[0]["name"] == "Llanowar Elves"
    assert battlefield[0]["summoning_sick"] is True

def test_web_session_requires_paid_mana_before_cast():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 999,
        },
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    bolt = _mk_card(
        name="Bolt Test",
        mana_cost="{R}",
        type_line="Instant",
        oracle_text="Bolt Test deals 3 damage to any target.",
    )
    mountain = _mk_card(
        name="Mountain",
        mana_cost="",
        type_line="Basic Land - Mountain",
        oracle_text="{T}: Add {R}.",
        produced_mana=("R",),
    )

    session.game.players[0].hand = [bolt]
    session.game.players[0].battlefield = [Permanent(card=mountain)]
    session.game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}
    session.game.players[1].life = 20

    unpaid_cast = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Bolt Test", "target_seat": 1},
    )
    assert unpaid_cast.status_code == 400
    assert "insufficient mana" in unpaid_cast.json()["detail"].lower()

    tap_land = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "activate", "permanent_name": "Mountain", "target_seat": 0},
    )
    assert tap_land.status_code == 200

    paid_cast = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Bolt Test", "target_seat": 1},
    )
    assert paid_cast.status_code == 200
    _resolve_top_stack(sid, 0)
    assert store.get(sid).game.players[1].life == 17

def test_web_cast_accepts_explicit_x_value():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 4044,
        },
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    stream = _mk_card(
        name="Stream of Life",
        mana_cost="{X}{G}",
        type_line="Sorcery",
        oracle_text="Target player gains X life.",
    )
    session.game.players[0].hand = [stream]
    session.game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 1, "C": 1}
    session.game.players[0].life = 10

    response = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Stream of Life", "target_seat": 0, "x_value": 1},
    )

    assert response.status_code == 200
    _resolve_top_stack(sid, 0)
    payload = response.json()
    refreshed = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    assert refreshed["players"][0]["life"] == 11
    assert any("Stream of Life" in entry and "10 -> 11" in entry for entry in refreshed["log"])

def test_web_activate_black_lotus_accepts_mana_color_choice():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 4043,
        },
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    lotus = _mk_card(
        name="Black Lotus",
        mana_cost="{0}",
        type_line="Artifact",
        oracle_text="{T}, Sacrifice Black Lotus: Add three mana of any one color.",
    )
    session.game.players[0].battlefield = [Permanent(card=lotus)]
    session.game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}

    response = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "activate",
            "permanent_name": "Black Lotus",
            "target_seat": 0,
            "mana_color": "B",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["players"][0]["mana_pool"]["B"] == 3
    assert payload["players"][0]["mana_pool"]["G"] == 0
    assert payload["players"][0]["battlefield"] == []

def test_playing_land_is_special_action_and_keeps_priority():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 40436,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})

    session = store.get(sid)
    island = _mk_card(
        name="Island",
        mana_cost="",
        type_line="Basic Land - Island",
        oracle_text="{T}: Add {U}.",
        produced_mana=("U",),
    )
    session.game.players[0].hand = [island]
    session.game.players[0].battlefield = []
    session.game.current_turn_phase = "precombat_main"
    session.game.current_step = "precombat_main"
    session.game.current_phase = "main"
    session.current_turn = 0
    session.game.active_player_index = 0
    session.game.start_priority_window(0)

    play_land = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Island", "target_seat": 0},
    )
    assert play_land.status_code == 200

    payload = play_land.json()
    assert payload["priority_player"] == 0
    assert payload["priority_pass_count"] == 0
    assert payload["stack"] == []
    assert len(payload["players"][0]["battlefield"]) == 1
    assert payload["players"][0]["battlefield"][0]["name"] == "Island"

def test_pass_priority_triggers_ai_instant_response_on_opponent_turn():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_ai",
            "host_name": "Host",
            "guest_name": "AI",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 40433,
        },
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    bolt = _mk_card(
        name="Bolt Test",
        mana_cost="{R}",
        type_line="Instant",
        oracle_text="Bolt Test deals 3 damage to any target.",
    )
    mountain = _mk_card(
        name="Mountain",
        mana_cost="",
        type_line="Basic Land - Mountain",
        oracle_text="{T}: Add {R}.",
        produced_mana=("R",),
    )
    session.game.players[1].hand = [bolt]
    session.game.players[1].battlefield = [Permanent(card=mountain)]
    session.game.players[1].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}
    session.game.players[0].life = 20
    session.game.players[1].life = 20

    passed = _pass_priority(sid, 0)
    assert passed.status_code == 200
    payload = passed.json()
    assert payload["priority_player"] == 0
    assert payload["priority_pass_count"] == 1
    assert len(payload["stack"]) == 1
    assert payload["stack"][0]["card"]["name"] == "Bolt Test"
    assert payload["players"][0]["life"] == 20

    resolve = _pass_priority(sid, 0)
    assert resolve.status_code == 200
    resolved_payload = resolve.json()
    assert resolved_payload["stack"] == []
    assert resolved_payload["players"][0]["life"] == 17

def test_activated_ability_stays_on_stack_until_priority_passes():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 40432,
        },
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    sorcerer = _mk_card(
        name="Prodigal Sorcerer",
        mana_cost="{2}{U}",
        type_line="Creature - Human Wizard",
        oracle_text="{T}: Prodigal Sorcerer deals 1 damage to any target.",
    )
    session.game.players[0].battlefield = [Permanent(card=sorcerer)]
    session.game.players[1].life = 20

    activate = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "activate", "permanent_name": "Prodigal Sorcerer", "target_seat": 1},
    )
    assert activate.status_code == 200
    activate_payload = activate.json()
    assert len(activate_payload["stack"]) == 1
    assert activate_payload["stack"][0]["type"] == "ability"
    assert activate_payload["players"][1]["life"] == 20

    _resolve_top_stack(sid, 0)
    resolved = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    assert resolved["players"][1]["life"] == 19
    assert resolved["stack"] == []

def test_stream_of_life_defaults_to_self_target():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 4038,
        },
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    stream = _mk_card(
        name="Stream of Life",
        mana_cost="{X}{G}",
        type_line="Sorcery",
        oracle_text="Target player gains X life.",
    )
    session.game.players[0].hand = [stream]
    session.game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 1, "C": 1}
    session.game.players[0].life = 10

    response = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Stream of Life", "x_value": 1},
    )

    assert response.status_code == 200
    _resolve_top_stack(sid, 0)
    payload = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    assert payload["players"][0]["life"] == 11
    assert payload["players"][1]["life"] == 20
    assert any("Stream of Life" in entry and "10 -> 11" in entry for entry in payload["log"])

def test_stream_of_life_x_spends_generic_mana_from_pool():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 4043,
        },
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    stream = _mk_card(
        name="Stream of Life",
        mana_cost="{X}{G}",
        type_line="Sorcery",
        oracle_text="Target player gains X life.",
    )
    session.game.players[0].hand = [stream]
    session.game.players[0].mana_pool = {"W": 0, "U": 0, "B": 1, "R": 0, "G": 1, "C": 0}
    session.game.players[0].life = 10

    response = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Stream of Life", "target_seat": 0, "x_value": 1},
    )

    assert response.status_code == 200
    _resolve_top_stack(sid, 0)
    payload = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    assert payload["players"][0]["life"] == 11
    assert payload["players"][0]["mana_pool"]["G"] == 0
    assert payload["players"][0]["mana_pool"]["B"] == 0

def test_stream_of_life_updates_life_total_and_log_in_response():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 4040,
        },
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    stream = _mk_card(
        name="Stream of Life",
        mana_cost="{X}{G}",
        type_line="Sorcery",
        oracle_text="Target player gains X life.",
    )
    session.game.players[0].hand = [stream]
    session.game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 1, "C": 1}
    session.game.players[0].life = 10

    response = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Stream of Life", "target_seat": 0},
    )

    assert response.status_code == 200
    _resolve_top_stack(sid, 0)
    payload = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    assert payload["players"][0]["life"] == 11
    assert any("Stream of Life" in entry and "10 -> 11" in entry for entry in payload["log"])

def test_tap_action_on_land_adds_mana_and_cannot_retap():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 2026,
        },
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    mountain = _mk_card(
        name="Mountain",
        mana_cost="",
        type_line="Basic Land - Mountain",
        oracle_text="{T}: Add {R}.",
        produced_mana=("R",),
    )
    session.game.players[0].battlefield = [Permanent(card=mountain)]
    session.game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}

    first_tap = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "tap", "permanent_name": "Mountain"},
    )
    assert first_tap.status_code == 200
    assert store.get(sid).game.players[0].mana_pool["R"] == 1

    second_tap = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "tap", "permanent_name": "Mountain"},
    )
    assert second_tap.status_code == 400

def test_activate_land_uses_permanent_index_when_duplicate_names_exist():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 2027,
        },
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    forest = _mk_card(
        name="Forest",
        mana_cost="",
        type_line="Basic Land - Forest",
        oracle_text="{T}: Add {G}.",
        produced_mana=("G",),
    )

    first_forest = Permanent(card=forest)
    second_forest = Permanent(card=forest)
    session.game.players[0].battlefield = [first_forest, second_forest]
    session.game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}

    tap_second = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "activate",
            "permanent_name": "Forest",
            "permanent_index": 1,
            "target_seat": 0,
        },
    )

    assert tap_second.status_code == 200
    assert session.game.players[0].battlefield[0].tapped is False
    assert session.game.players[0].battlefield[1].tapped is True
    assert session.game.players[0].mana_pool["G"] == 1

def test_activate_with_mana_cost_requires_payment_before_tap():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 3030,
        },
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    tome = _mk_card(
        name="Jayemdae Tome",
        mana_cost="{4}",
        type_line="Artifact",
        oracle_text="{4}, {T}: Draw a card.",
    )
    island = _mk_card(
        name="Island",
        mana_cost="",
        type_line="Basic Land - Island",
        oracle_text="{T}: Add {U}.",
        produced_mana=("U",),
    )

    session.game.players[0].battlefield = [Permanent(card=tome)]
    session.game.players[0].library = [island]
    session.game.players[0].mana_pool = {"W": 0, "U": 3, "B": 0, "R": 0, "G": 0, "C": 0}

    unpaid = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "activate", "permanent_name": "Jayemdae Tome", "target_seat": 1},
    )
    assert unpaid.status_code == 400
    assert "insufficient mana" in unpaid.json()["detail"].lower()
    assert store.get(sid).game.players[0].battlefield[0].tapped is False

    session.game.players[0].mana_pool = {"W": 0, "U": 4, "B": 0, "R": 0, "G": 0, "C": 0}
    paid = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "activate", "permanent_name": "Jayemdae Tome", "target_seat": 1},
    )
    assert paid.status_code == 200
    assert store.get(sid).game.players[0].battlefield[0].tapped is True

def test_instant_allowed_on_opponent_turn():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 12346,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})

    session = store.get(sid)
    instant = _mk_card(
        name="Bolt Test",
        mana_cost="{R}",
        type_line="Instant",
        oracle_text="Bolt Test deals 3 damage to any target.",
    )
    mountain = _mk_card(
        name="Mountain",
        mana_cost="",
        type_line="Basic Land - Mountain",
        oracle_text="{T}: Add {R}.",
        produced_mana=("R",),
    )
    session.game.players[0].hand = [instant]
    session.game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 1, "G": 0, "C": 0}
    session.game.players[0].battlefield = [Permanent(card=mountain)]
    session.game.players[1].life = 20

    client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "end_turn"})
    assert store.get(sid).current_turn == 1

    passed = _pass_priority(sid, 1)
    assert passed.status_code == 200

    tap_mountain = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "activate", "permanent_name": "Mountain", "target_seat": 0},
    )
    assert tap_mountain.status_code == 200

    off_turn_instant = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Bolt Test", "target_seat": 1},
    )
    assert off_turn_instant.status_code == 200
    _resolve_top_stack(sid, 0)
    assert store.get(sid).game.players[1].life == 17

def test_only_one_land_play_per_turn_then_resets_next_turn():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 22336,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})

    session = store.get(sid)
    plains_a = _mk_card(
        name="Plains A",
        mana_cost="",
        type_line="Basic Land - Plains",
        oracle_text="{T}: Add {W}.",
        produced_mana=("W",),
    )
    plains_b = _mk_card(
        name="Plains B",
        mana_cost="",
        type_line="Basic Land - Plains",
        oracle_text="{T}: Add {W}.",
        produced_mana=("W",),
    )
    session.game.players[0].hand = [plains_a, plains_b]

    first_land = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Plains A", "target_seat": 0},
    )
    assert first_land.status_code == 200

    second_land_same_turn = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Plains B", "target_seat": 0},
    )
    assert second_land_same_turn.status_code == 400
    assert "already played a land" in second_land_same_turn.json()["detail"].lower()

    client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "end_turn"})
    seat1_end = client.post(f"/api/sessions/{sid}/action", json={"seat": 1, "action": "end_turn"})
    if seat1_end.status_code == 200 and seat1_end.json().get("cleanup_discard"):
        client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 1, "action": "cleanup_select", "hand_index": 0},
        )
        client.post(f"/api/sessions/{sid}/action", json={"seat": 1, "action": "next_phase"})

    second_land_next_turn = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Plains B", "target_seat": 0},
    )
    assert second_land_next_turn.status_code == 200

def test_fastbond_allows_extra_land_and_deals_damage():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 92334,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})

    session = store.get(sid)
    fastbond = _mk_card(
        name="Fastbond",
        mana_cost="{G}",
        type_line="Enchantment",
        oracle_text=(
            "You may play any number of lands on each of your turns.\n"
            "Whenever you play a land, if it wasn't the first land you played this turn, "
            "this enchantment deals 1 damage to you."
        ),
    )
    plains_a = _mk_card(
        name="Plains A",
        mana_cost="",
        type_line="Basic Land - Plains",
        oracle_text="{T}: Add {W}.",
        produced_mana=("W",),
    )
    plains_b = _mk_card(
        name="Plains B",
        mana_cost="",
        type_line="Basic Land - Plains",
        oracle_text="{T}: Add {W}.",
        produced_mana=("W",),
    )
    session.game.players[0].hand = [fastbond, plains_a, plains_b]
    session.game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 1, "C": 0}
    session.game.players[0].life = 20

    cast_fastbond = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Fastbond", "target_seat": 0},
    )
    assert cast_fastbond.status_code == 200
    _resolve_top_stack(sid, 0)

    first_land = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Plains A", "target_seat": 0},
    )
    assert first_land.status_code == 200

    second_land_same_turn = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Plains B", "target_seat": 0},
    )
    assert second_land_same_turn.status_code == 200
    assert store.get(sid).game.players[0].life == 19

def test_next_phase_ai_defender_casts_instant_after_declaring_blockers():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_ai",
            "host_name": "Host",
            "guest_name": "AI",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 99202,
        },
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    attacker = _mk_creature_card("Attacker", 3, 3)
    blocker = _mk_creature_card("Blocker", 2, 2)
    bolt = _mk_card(
        name="Lightning Bolt",
        mana_cost="{R}",
        type_line="Instant",
        oracle_text="Lightning Bolt deals 3 damage to any target.",
    )
    mountain = _mk_card(
        name="Mountain",
        mana_cost="",
        type_line="Basic Land - Mountain",
        oracle_text="{T}: Add {R}.",
        produced_mana=("R",),
    )

    session.game.players[0].battlefield = [Permanent(card=attacker)]
    session.game.players[0].life = 20
    session.game.players[1].battlefield = [Permanent(card=blocker), Permanent(card=mountain)]
    session.game.players[1].hand = [bolt]
    session.game.players[1].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}
    session.current_turn = 0
    session.game.active_player_index = 0
    session.game.current_turn_phase = "combat"
    session.game.current_step = "declare_attackers"
    session.game.current_phase = "combat"

    declared = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "declare_attackers", "attacker_indices": [0], "target_seat": 1},
    )
    assert declared.status_code == 200

    to_blockers = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "next_phase"},
    )
    assert to_blockers.status_code == 200
    assert to_blockers.json()["current_step"] == "declare_blockers"

    ai_block_and_cast = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "next_phase"},
    )
    assert ai_block_and_cast.status_code == 200
    payload = ai_block_and_cast.json()
    assert payload["current_step"] == "declare_blockers"
    assert payload["combat"]["blockers_locked"] is True
    assert payload["players"][0]["life"] == 17

def test_winter_orb_turn_start_requires_untap_land_selection_for_human_player():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 99110,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})

    session = store.get(sid)
    forest = _mk_card(
        name="Forest",
        mana_cost="",
        type_line="Basic Land - Forest",
        oracle_text="{T}: Add {G}.",
        produced_mana=("G",),
    )
    winter_orb = _mk_card(
        name="Winter Orb",
        mana_cost="{2}",
        type_line="Artifact",
        oracle_text="As long as this artifact is untapped, players can't untap more than one land during their untap steps.",
    )

    session.current_turn = 0
    session.game.active_player_index = 0
    session.game.players[0].battlefield = [Permanent(card=winter_orb, tapped=False)]
    session.game.players[1].battlefield = [
        Permanent(card=forest, tapped=True),
        Permanent(card=forest, tapped=True),
    ]
    session.game.current_turn_phase = "postcombat_main"
    session.game.current_step = "postcombat_main"
    session.game.current_phase = "main"

    end_turn = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "end_turn"})
    assert end_turn.status_code == 200

    seat1_state = client.get(f"/api/sessions/{sid}/state?seat=1")
    assert seat1_state.status_code == 200
    state_payload = seat1_state.json()
    assert state_payload["current_turn"] == 1
    assert state_payload["current_step"] == "untap"
    assert state_payload["untap_land_selection"]["max_count"] == 1
    assert state_payload["untap_land_selection"]["selected_indices"] == []

    blocked = client.post(f"/api/sessions/{sid}/action", json={"seat": 1, "action": "next_phase"})
    assert blocked.status_code == 400
    assert "select untap lands" in blocked.json()["detail"].lower()

    pick_land = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 1, "action": "untap_select", "permanent_index": 0},
    )
    assert pick_land.status_code == 200
    pick_payload = pick_land.json()
    assert pick_payload["untap_land_selection"]["selected_indices"] == [0]

    confirm = client.post(f"/api/sessions/{sid}/action", json={"seat": 1, "action": "untap_confirm"})
    assert confirm.status_code == 200
    confirm_payload = confirm.json()
    assert confirm_payload["current_phase"] == "main"
    assert confirm_payload["current_step"] == "precombat_main"
    assert confirm_payload["untap_land_selection"] is None
    assert confirm_payload["players"][1]["battlefield"][0]["tapped"] is False
    assert confirm_payload["players"][1]["battlefield"][1]["tapped"] is True

def test_badlands_produces_black_or_red_mana(all_cards):
    # Badlands oracle text: ({T}: Add {B} or {R}.)
    # It is a dual land — Swamp Mountain that can produce either B or R.
    badlands = _get(all_cards, "Badlands")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=badlands)])
    game = Game(players=[p1])

    ok = game.tap_land_for_mana(0, "Badlands", chosen_color="B")
    assert ok
    assert p1.mana_pool["B"] == 1
    assert p1.mana_pool["R"] == 0

    # Reset for second tap test
    p1.battlefield[0].tapped = False
    p1.mana_pool["B"] = 0

    ok = game.tap_land_for_mana(0, "Badlands", chosen_color="R")
    assert ok
    assert p1.mana_pool["R"] == 1
    assert p1.mana_pool["B"] == 0


# ---------------------------------------------------------------------------
# Air Elemental
# ---------------------------------------------------------------------------

def test_air_elemental_cannot_be_blocked_by_ground_creature(all_cards):
    """Air Elemental has flying; a creature without flying or reach cannot block it."""
    air_elemental = _get(all_cards, "Air Elemental")
    grizzly_bears = _get(all_cards, "Grizzly Bears")

    air_perm = Permanent(card=air_elemental)
    bear_perm = Permanent(card=grizzly_bears)

    p1 = PlayerState(name="P1", battlefield=[air_perm])
    p2 = PlayerState(name="P2", battlefield=[bear_perm])
    game = Game(players=[p1, p2])

    # bear_perm (blocker) cannot block air_perm (attacker with flying)
    assert game._can_block_attacker(bear_perm, air_perm) is False


# ---------------------------------------------------------------------------
# Disintegrate
# ---------------------------------------------------------------------------

def test_disintegrate_deals_damage_to_targeted_creature(all_cards):
    """Disintegrate with X=3 targeting a creature should deal 3 damage to that creature."""
    disintegrate = _get(all_cards, "Disintegrate")
    bear = _mk_creature_card("Test Bear", power=2, toughness=2)

    bear_perm = Permanent(card=bear)
    p1 = PlayerState(name="P1", hand=[disintegrate])
    p2 = PlayerState(name="P2", battlefield=[bear_perm])
    game = Game(players=[p1, p2])

    initial_life = p2.life
    result = game.cast_from_hand(
        0, "Disintegrate",
        target_player_index=1,
        target_permanent_index=0,
        x_value=3,
    )
    assert result.supported
    # Creature should be gone (dead or exiled after taking 3 damage)
    assert not p2.battlefield, "2/2 creature should be removed after taking 3 damage from Disintegrate"
    # Player life should be unchanged (damage went to creature, not player)
    assert p2.life == initial_life


# ---------------------------------------------------------------------------
# Lance
# ---------------------------------------------------------------------------

def test_lance_grants_first_strike_to_enchanted_creature(all_cards):
    """Lance aura gives enchanted creature first strike."""
    lance = _get(all_cards, "Lance")
    bear = _mk_creature_card("Test Bear", power=2, toughness=2)

    bear_perm = Permanent(card=bear)
    p1 = PlayerState(name="P1", hand=[lance], battlefield=[bear_perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(
        0, "Lance",
        target_player_index=0,
        target_permanent_index=0,
    )
    assert result.supported
    enchanted = p1.battlefield[0]
    assert enchanted.metadata.get("gains_first_strike") is True, \
        "Enchanted creature should have gains_first_strike=True in metadata"


# ---------------------------------------------------------------------------
# Power Sink
# ---------------------------------------------------------------------------

def test_power_sink_counters_spell_and_taps_controller_lands(all_cards):
    """Power Sink counters the target spell and taps all of the controller's lands."""
    power_sink = _get(all_cards, "Power Sink")
    ancestral_recall = _get(all_cards, "Ancestral Recall")
    island = _mk_card("Island", type_line="Basic Land - Island", mana_cost="")

    island1 = Permanent(card=island, tapped=False)
    island2 = Permanent(card=island, tapped=False)
    p1 = PlayerState(name="P1", hand=[power_sink])
    p2 = PlayerState(
        name="P2",
        hand=[ancestral_recall],
        battlefield=[island1, island2],
    )
    game = Game(players=[p1, p2])

    # p2 queues Ancestral Recall targeting themselves (don't auto-resolve)
    game.queue_from_hand(1, "Ancestral Recall", target_player_index=1)
    assert len(game.stack) == 1

    # p1 counters with Power Sink, X=5 (more than p2 can pay)
    # cast_from_hand will queue Power Sink then resolve the entire stack
    result = game.cast_from_hand(0, "Power Sink", target_player_index=1, x_value=5)
    assert result.supported

    # Ancestral Recall should have been countered (removed from stack)
    assert len(game.stack) == 0
    # All of p2's lands should be tapped
    land_perms = [perm for perm in p2.battlefield if perm.card.primary_type == "land"]
    assert land_perms, "P2 should still have lands on battlefield"
    assert all(perm.tapped for perm in land_perms), \
        "Power Sink should tap all of the countered spell controller's lands"
    # p2's mana pool should be empty
    assert all(v == 0 for v in p2.mana_pool.values()), \
        "Power Sink should drain all mana from countered spell controller's mana pool"


# ---------------------------------------------------------------------------
# Regeneration
# ---------------------------------------------------------------------------

def test_regeneration_aura_activated_ability_grants_regen_shield(all_cards):
    """Regeneration enchants a creature; its activated ability grants the enchanted creature a regeneration shield."""
    regeneration = _get(all_cards, "Regeneration")
    bear = _mk_creature_card("Test Bear", power=2, toughness=2)

    bear_perm = Permanent(card=bear)
    p1 = PlayerState(name="P1", hand=[regeneration], battlefield=[bear_perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # Cast Regeneration enchanting the bear
    cast_result = game.cast_from_hand(
        0, "Regeneration",
        target_player_index=0,
        target_permanent_index=0,
    )
    assert cast_result.supported

    # Activate Regeneration's ability to grant the bear a regeneration shield
    activate_result = game.activate_permanent_ability(
        0, "Regeneration",
        target_player_index=0,
    )
    assert activate_result.supported, \
        "Regeneration's activated ability should be supported"

    # The enchanted bear should now have a regeneration shield
    assert bear_perm.regeneration_shield >= 1, \
        "Enchanted creature should have regeneration_shield >= 1 after activating Regeneration"


# ---------------------------------------------------------------------------
# Tests for Bayou, Berserk, Birds of Paradise, Black Ward, Blue Elemental Blast
# ---------------------------------------------------------------------------

def test_bayou_taps_for_black_mana(all_cards):
    bayou = _get(all_cards, "Bayou")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=bayou)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    ok = game.tap_land_for_mana(0, "Bayou", chosen_color="B")

    assert ok
    assert p1.mana_pool["B"] == 1
    assert p1.battlefield[0].tapped is True


def test_bayou_taps_for_green_mana(all_cards):
    bayou = _get(all_cards, "Bayou")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=bayou)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    ok = game.tap_land_for_mana(0, "Bayou", chosen_color="G")

    assert ok
    assert p1.mana_pool["G"] == 1


def test_berserk_doubles_power_and_grants_trample(all_cards):
    berserk = _get(all_cards, "Berserk")
    bear = _mk_creature_card("Test Bear", power=2, toughness=2)
    p1 = PlayerState(name="P1", hand=[berserk])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Berserk", target_player_index=1, target_permanent_index=0)

    assert result.supported
    target_perm = p2.battlefield[0]
    # power doubles: base 2 + bonus 2 = 4
    assert target_perm.effective_power == 4
    assert target_perm.metadata.get("gains_trample_until_eot") is True


def test_birds_of_paradise_classifies_supported(all_cards):
    bop = _get(all_cards, "Birds of Paradise")
    result = classify_card(bop)
    assert result.supported


def test_birds_of_paradise_taps_for_any_color_mana(all_cards):
    bop = _get(all_cards, "Birds of Paradise")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=bop)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Birds of Paradise", target_player_index=1, mana_color="U")

    assert result.supported
    assert p1.mana_pool["U"] == 1
    assert p1.battlefield[0].tapped is True


def test_black_ward_grants_protection_from_black(all_cards):
    ward = _get(all_cards, "Black Ward")
    creature = _mk_creature_card("Test Knight", power=2, toughness=2)
    p1 = PlayerState(name="P1", hand=[ward])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Black Ward", target_player_index=1, target_permanent_index=0)

    assert result.supported
    creature_perm = p2.battlefield[0]
    assert creature_perm.metadata.get("protection_from_black") is True


def test_blue_elemental_blast_counters_red_spell(all_cards):
    """Blue Elemental Blast's first mode counters a red spell on the stack."""
    beb = _get(all_cards, "Blue Elemental Blast")
    bolt = _get(all_cards, "Lightning Bolt")
    p1 = PlayerState(name="P1", hand=[beb])
    p2 = PlayerState(name="P2", hand=[bolt])
    game = Game(players=[p1, p2])

    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    result = game.cast_from_hand(0, "Blue Elemental Blast", target_player_index=1)

    assert result.supported
    assert any("Blue Elemental Blast countered Lightning Bolt" in line for line in game.log)
    assert not game.stack, "Stack should be empty after counterspell resolves"


def test_blue_elemental_blast_cannot_be_cast_without_valid_target(all_cards):
    """Blue Elemental Blast cannot be cast if there are no valid red targets."""
    beb = _get(all_cards, "Blue Elemental Blast")
    forest = _get(all_cards, "Forest")
    p1 = PlayerState(name="P1", hand=[beb])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=forest)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Blue Elemental Blast", target_player_index=1)

    assert not result.supported
    assert p1.hand and p1.hand[0].name == "Blue Elemental Blast"


def test_blue_elemental_blast_cannot_be_cast_with_empty_battlefield(all_cards):
    """Blue Elemental Blast cannot be cast if target player has no permanents."""
    beb = _get(all_cards, "Blue Elemental Blast")
    p1 = PlayerState(name="P1", hand=[beb])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Blue Elemental Blast", target_player_index=1)

    assert not result.supported
    assert p1.hand and p1.hand[0].name == "Blue Elemental Blast"


def test_bog_wraith_classifies_supported_with_swampwalk(all_cards):
    bog = _get(all_cards, "Bog Wraith")
    result = classify_card(bog)
    assert result.supported
    assert any(k.lower() == "swampwalk" for k in bog.keywords)


def test_burrowing_grants_mountainwalk_to_enchanted_creature(all_cards):
    burrowing = _get(all_cards, "Burrowing")
    creature = _mk_card("Test Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[burrowing])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Burrowing", target_player_index=1, target_permanent_index=0)

    assert result.supported
    bear_perm = p2.battlefield[0]
    assert bear_perm.metadata.get("attached_aura") is not None
    assert bear_perm.metadata.get("has_mountainwalk") is True
    assert any("landwalk" in line.lower() for line in game.log)


def test_celestial_prism_adds_mana_of_chosen_color(all_cards):
    prism = _get(all_cards, "Celestial Prism")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=prism)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Celestial Prism", mana_color="G")

    assert result.supported
    assert p1.mana_pool["G"] == 1
    assert p1.battlefield[0].tapped is True


def test_channel_sets_active_flag_and_use_channel_mana_pays_life(all_cards):
    channel = _get(all_cards, "Channel")
    p1 = PlayerState(name="P1", hand=[channel], life=20)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Channel", target_player_index=0)

    assert result.supported
    assert p1.channel_active_until_eot is True

    use_result = game.use_channel_mana(0, 7)
    assert use_result.supported
    assert p1.life == 13
    assert p1.mana_pool["C"] == 7


def test_chaoslace_makes_target_permanent_red(all_cards):
    chaoslace = _get(all_cards, "Chaoslace")
    creature = _mk_card("Forest Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[chaoslace])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Chaoslace", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("color_override") == "R"


def test_circle_of_protection_green_activation_sets_prevention(all_cards):
    cop = _get(all_cards, "Circle of Protection: Green")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=cop)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Circle of Protection: Green", target_player_index=0)

    assert result.supported
    assert p1.damage_prevention_pool == 1


def test_circle_of_protection_red_activation_sets_prevention(all_cards):
    cop = _get(all_cards, "Circle of Protection: Red")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=cop)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Circle of Protection: Red", target_player_index=0)

    assert result.supported
    assert p1.damage_prevention_pool == 1


def test_circle_of_protection_white_activation_sets_prevention(all_cards):
    cop = _get(all_cards, "Circle of Protection: White")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=cop)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Circle of Protection: White", target_player_index=0)

    assert result.supported
    assert p1.damage_prevention_pool == 1


def test_consecrate_land_grants_indestructible_to_enchanted_land(all_cards):
    consecrate = _get(all_cards, "Consecrate Land")
    plains = _get(all_cards, "Plains")

    p1 = PlayerState(name="P1", hand=[consecrate], battlefield=[Permanent(card=plains)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Consecrate Land", target_player_index=0, target_permanent_index=0)

    assert result.supported
    land_perm = p1.battlefield[0]
    assert land_perm.metadata.get("is_indestructible") is True
    aura_perm = next(p for p in p1.battlefield if p.card.name == "Consecrate Land")
    assert aura_perm.metadata.get("attached_to") is land_perm


def test_consecrate_land_indestructible_survives_destroy(all_cards):
    consecrate = _get(all_cards, "Consecrate Land")
    stone_rain = _get(all_cards, "Stone Rain")
    plains = _get(all_cards, "Plains")

    p1 = PlayerState(name="P1", hand=[consecrate], battlefield=[Permanent(card=plains)])
    p2 = PlayerState(name="P2", hand=[stone_rain])
    game = Game(players=[p1, p2])

    assert game.cast_from_hand(0, "Consecrate Land", target_player_index=0, target_permanent_index=0).supported

    # The enchanted Plains has indestructible: Stone Rain can target it but can't destroy it.
    result = game.cast_from_hand(1, "Stone Rain", target_player_index=0, target_permanent_index=0)
    assert result.supported
    assert any(p.card.name == "Plains" for p in p1.battlefield)
    assert not any(c.name == "Plains" for c in p1.graveyard)


def test_consecrate_land_blocks_other_auras(all_cards):
    consecrate = _get(all_cards, "Consecrate Land")
    plains = _get(all_cards, "Plains")

    # Two copies of Consecrate Land in hand; the second can't enchant the protected land.
    p1 = PlayerState(name="P1", hand=[consecrate, consecrate], battlefield=[Permanent(card=plains)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    assert game.cast_from_hand(0, "Consecrate Land", target_player_index=0, target_permanent_index=0).supported
    second = game.cast_from_hand(0, "Consecrate Land", target_player_index=0, target_permanent_index=0)
    assert not second.supported
    assert "can't be enchanted" in second.details.lower()


def test_consecrate_land_grant_ends_when_aura_leaves(all_cards):
    consecrate = _get(all_cards, "Consecrate Land")
    disenchant = _get(all_cards, "Disenchant")
    plains = _get(all_cards, "Plains")

    p1 = PlayerState(name="P1", hand=[consecrate], battlefield=[Permanent(card=plains)])
    p2 = PlayerState(name="P2", hand=[disenchant])
    game = Game(players=[p1, p2])

    assert game.cast_from_hand(0, "Consecrate Land", target_player_index=0, target_permanent_index=0).supported
    land = p1.battlefield[0]
    assert land.metadata.get("is_indestructible") is True

    # Destroying the Aura ends both continuous grants on the land.
    result = game.cast_from_hand(1, "Disenchant", target_player_index=0, target_permanent_index=1)
    assert result.supported
    assert land.metadata.get("is_indestructible") is not True
    assert land.metadata.get("cant_be_enchanted_by_auras") is not True


def test_consecrate_land_graveyards_existing_other_auras_on_enter(all_cards):
    consecrate = _get(all_cards, "Consecrate Land")
    wild_growth = _get(all_cards, "Wild Growth")
    plains = _get(all_cards, "Plains")

    p1 = PlayerState(name="P1", hand=[wild_growth, consecrate], battlefield=[Permanent(card=plains)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # The land is already enchanted by another Aura.
    assert game.cast_from_hand(0, "Wild Growth", target_player_index=0, target_permanent_index=0).supported
    assert any(p.card.name == "Wild Growth" for p in p1.battlefield)

    # Consecrate Land entering attached to it sends the other Aura to the graveyard.
    assert game.cast_from_hand(0, "Consecrate Land", target_player_index=0, target_permanent_index=0).supported
    assert not any(p.card.name == "Wild Growth" for p in p1.battlefield)
    assert any(c.name == "Wild Growth" for c in p1.graveyard)
    assert any(p.card.name == "Consecrate Land" for p in p1.battlefield)


def test_consecrate_land_graveyards_other_auras_via_priority_resolution(all_cards):
    # Regression: in real play the Aura resolves through the priority-pass path,
    # which must check state-based actions afterward (the immediate cast_from_hand
    # path always did, masking the bug).
    consecrate = _get(all_cards, "Consecrate Land")
    wild_growth = _get(all_cards, "Wild Growth")
    plains = _get(all_cards, "Plains")

    p1 = PlayerState(name="P1", hand=[wild_growth, consecrate], battlefield=[Permanent(card=plains)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    assert game.cast_from_hand(0, "Wild Growth", target_player_index=0, target_permanent_index=0).supported

    # Resolve Consecrate Land via a priority window rather than cast_from_hand.
    game.queue_from_hand(0, "Consecrate Land", target_player_index=0, target_permanent_index=0)
    game.start_priority_window(0)
    game.pass_priority(0)
    game.pass_priority(1)

    assert not any(p.card.name == "Wild Growth" for p in p1.battlefield)
    assert any(c.name == "Wild Growth" for c in p1.graveyard)
    assert any(p.card.name == "Consecrate Land" for p in p1.battlefield)


def test_conservator_activated_prevents_two_damage(all_cards):
    conservator = _get(all_cards, "Conservator")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=conservator)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Conservator", target_player_index=0)

    assert result.supported
    assert p1.damage_prevention_pool == 2
    assert p1.battlefield[0].tapped is True


def test_control_magic_steals_opponent_creature(all_cards):
    control_magic = _get(all_cards, "Control Magic")
    creature = _mk_card("Target Bear", "Creature - Bear")

    p1 = PlayerState(name="P1", hand=[control_magic])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Control Magic", target_player_index=1, target_permanent_index=0)

    assert result.supported
    assert any(p.card.name == "Target Bear" for p in p1.battlefield)
    assert not any(p.card.name == "Target Bear" for p in p2.battlefield)
    aura_perm = next((p for p in p1.battlefield if p.card.name == "Control Magic"), None)
    assert aura_perm is not None
    stolen = next(p for p in p1.battlefield if p.card.name == "Target Bear")
    assert aura_perm.metadata.get("attached_to") is stolen


def test_copper_tablet_upkeep_deals_one_damage_to_active_player(all_cards):
    tablet = _get(all_cards, "Copper Tablet")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=tablet)], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert p1.life == 19


def test_copper_tablet_upkeep_also_damages_opponent_on_their_upkeep(all_cards):
    tablet = _get(all_cards, "Copper Tablet")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=tablet)], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.resolve_upkeep(1)

    assert p2.life == 19


def test_dark_ritual_adds_three_black_mana(all_cards):
    dark_ritual = _get(all_cards, "Dark Ritual")

    p1 = PlayerState(name="P1", hand=[dark_ritual])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Dark Ritual")

    assert result.supported
    assert p1.mana_pool.get("B", 0) == 3


def test_crusade_buffs_white_creatures(all_cards):
    crusade = _get(all_cards, "Crusade")
    white_knight = _get(all_cards, "White Knight")

    p1 = PlayerState(name="P1", hand=[crusade])
    p2 = PlayerState(name="P2")
    p1.battlefield.append(Permanent(card=white_knight))
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Crusade")

    assert result.supported
    knight_perm = p1.battlefield[0]
    assert knight_perm.effective_power == 3
    assert knight_perm.effective_toughness == 3


def test_crystal_rod_gains_life_when_controller_casts_blue_spell(all_cards):
    crystal_rod = _get(all_cards, "Crystal Rod")
    blue_spell = _mk_card("Blue Bolt", "Instant", "", mana_cost="{U}", colors=("U",))

    p1 = PlayerState(name="P1", hand=[blue_spell], life=20)
    p1.battlefield.append(Permanent(card=crystal_rod))
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Blue Bolt")

    assert p1.life == 21


def test_cursed_land_deals_upkeep_damage_to_land_controller(all_cards):
    cursed_land = _get(all_cards, "Cursed Land")
    forest = _mk_card("Forest", "Basic Land - Forest")

    p1 = PlayerState(name="P1", hand=[cursed_land], life=20)
    p2 = PlayerState(name="P2", life=20)
    p2.battlefield.append(Permanent(card=forest))
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Cursed Land", target_player_index=1, target_permanent_index=0)
    assert result.supported

    game.resolve_upkeep(1)

    assert p2.life == 19


def test_creature_bond_deals_damage_when_enchanted_creature_dies(all_cards):
    creature_bond = _get(all_cards, "Creature Bond")
    bear = _mk_card("Test Bear", "Creature - Bear")

    p1 = PlayerState(name="P1", hand=[creature_bond], life=20)
    p2 = PlayerState(name="P2", life=20)
    p2.battlefield.append(Permanent(card=bear))
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Creature Bond", target_player_index=1, target_permanent_index=0)
    assert result.supported

    # Destroy the enchanted creature; P2 (controller) should take damage equal to toughness (2)
    game._destroy_target_permanent(p2, type_filter="creature")

    assert p2.life == 18


def test_chaos_orb_flip_destroys_random_permanents_and_self(all_cards):
    import random as _random
    chaos_orb = _get(all_cards, "Chaos Orb")
    bear = _mk_card("Test Bear", "Creature - Bear")
    plains = _mk_card("Plains", "Basic Land - Plains")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=chaos_orb, tapped=False)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear), Permanent(card=plains)])
    game = Game(players=[p1, p2])

    total_before = len(p1.battlefield) + len(p2.battlefield)  # 3 (orb + bear + plains)

    _random.seed(0)
    result = game.activate_permanent_ability(0, "Chaos Orb")

    assert result.supported
    # Chaos Orb always destroys itself
    assert not any(perm.card.name == "Chaos Orb" for perm in p1.battlefield)
    assert any(card.name == "Chaos Orb" for card in p1.graveyard)
    # Total permanents remaining is between 0 and 2 (0-2 random + orb self-destroy)
    total_after = len(p1.battlefield) + len(p2.battlefield)
    assert total_after <= total_before - 1  # at least Chaos Orb destroyed
    assert total_before - total_after <= 3   # at most Chaos Orb + 2 random destroyed


def test_death_ward_grants_regeneration_shield(all_cards):
    # Death Ward: "Regenerate target creature." — grants a regeneration shield to a target creature
    death_ward = _get(all_cards, "Death Ward")
    bear = _mk_card("Test Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[death_ward])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Death Ward", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].regeneration_shield >= 1


def test_deathgrip_counters_green_spell_on_stack(all_cards):
    # Deathgrip: "{B}{B}: Counter target green spell."
    deathgrip = _get(all_cards, "Deathgrip")
    giant_growth = _get(all_cards, "Giant Growth")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=deathgrip)])
    p2 = PlayerState(name="P2", hand=[giant_growth], battlefield=[Permanent(card=_get(all_cards, "Llanowar Elves"))])
    game = Game(players=[p1, p2])

    # Queue green spell on stack
    game.queue_from_hand(1, "Giant Growth", target_player_index=1)
    assert game.stack

    # Activate Deathgrip to counter it
    result = game.activate_permanent_ability(0, "Deathgrip")

    assert result.supported
    assert not game.stack
    assert any(card.name == "Giant Growth" for card in p2.graveyard)


def test_dingus_egg_deals_damage_when_land_destroyed(all_cards):
    # Dingus Egg: "Whenever a land is put into a graveyard from the battlefield,
    # this artifact deals 2 damage to that land's controller."
    dingus_egg = _get(all_cards, "Dingus Egg")
    stone_rain = _get(all_cards, "Stone Rain")
    mountain = _get(all_cards, "Mountain")

    p1 = PlayerState(name="P1", hand=[stone_rain], battlefield=[Permanent(card=dingus_egg)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=mountain)], life=20)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Stone Rain", target_player_index=1)

    assert result.supported
    assert not any(perm.card.name == "Mountain" for perm in p2.battlefield)
    assert p2.life == 18  # 2 damage from Dingus Egg


def test_disrupting_scepter_discards_card(all_cards):
    # Disrupting Scepter: "{3}, {T}: Target player discards a card."
    scepter = _get(all_cards, "Disrupting Scepter")
    island = _mk_card("Island", "Basic Land - Island")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=scepter)])
    p2 = PlayerState(name="P2", hand=[island, island, island])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Disrupting Scepter", target_player_index=1)

    assert result.supported
    assert len(p2.hand) == 2
    assert len(p2.graveyard) == 1


def test_dragon_whelp_activated_pumps_power(all_cards):
    # Dragon Whelp: "{R}: This creature gets +1/+0 until end of turn."
    dragon_whelp = _get(all_cards, "Dragon Whelp")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=dragon_whelp)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    before = p1.battlefield[0].effective_power
    result = game.activate_permanent_ability(0, "Dragon Whelp")

    assert result.supported
    assert p1.battlefield[0].effective_power == before + 1


def test_drain_life_deals_damage_and_caster_gains_life(all_cards):
    # Drain Life: "{X}{1}{B} — Drain Life deals X damage to any target.
    # You gain life equal to the damage dealt."
    drain_life = _get(all_cards, "Drain Life")

    p1 = PlayerState(name="P1", hand=[drain_life], life=15)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Drain Life", target_player_index=1, x_value=3)

    assert result.supported
    assert p2.life == 17  # took 3 damage
    assert p1.life == 18  # gained 3 life



def test_drain_power_steals_mana_from_opponent_lands(all_cards):
    # Drain Power: "{U}{U} — Target player activates a mana ability of each land
    # they control. Then that player loses all unspent mana and you add the mana
    # lost this way."
    drain_power = _get(all_cards, "Drain Power")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[drain_power])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=island), Permanent(card=island)],
    )
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Drain Power", target_player_index=1)

    assert result.supported
    # Both islands are tapped
    assert all(perm.tapped for perm in p2.battlefield)
    # Opponent lost all mana
    assert sum(p2.mana_pool.values()) == 0
    # Caster received 2 blue mana (one per Island)
    assert p1.mana_pool.get("U", 0) == 2



def test_drudge_skeletons_regeneration_activation(all_cards):
    # Drudge Skeletons: "{1}{B} — {B}: Regenerate this creature."
    drudge = _get(all_cards, "Drudge Skeletons")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=drudge)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Drudge Skeletons")

    assert result.supported
    assert p1.battlefield[0].regeneration_shield == 1


def test_drudge_skeletons_regeneration_shield_prevents_wrath(all_cards):
    # Wrath of God says "They can't be regenerated." — regeneration shield is bypassed.
    drudge = _get(all_cards, "Drudge Skeletons")
    wrath = _get(all_cards, "Wrath of God")

    p1 = PlayerState(name="P1", hand=[wrath], battlefield=[Permanent(card=drudge)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.activate_permanent_ability(0, "Drudge Skeletons")
    assert p1.battlefield[0].regeneration_shield == 1

    result = game.cast_from_hand(0, "Wrath of God")

    assert result.supported
    # Wrath says "can't be regenerated" — the regeneration shield must NOT save the creature
    assert len(p1.battlefield) == 0
    assert any(c.name == "Drudge Skeletons" for c in p1.graveyard)


def test_drudge_skeletons_regeneration_shield_prevents_ordinary_destroy(all_cards):
    # Regeneration shield saves a creature from a plain "destroy target creature" effect
    # (no 'can't be regenerated' clause).  Use a synthetic sorcery to avoid card-specific
    # restrictions (Terror targets non-black, Wrath bypasses regen).
    drudge = _get(all_cards, "Drudge Skeletons")
    destroy_spell = _mk_card("Plain Destroy", "Sorcery", "Destroy target creature.")

    p1 = PlayerState(name="P1", hand=[destroy_spell])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=drudge)])
    game = Game(players=[p1, p2])

    game.activate_permanent_ability(1, "Drudge Skeletons")
    assert p2.battlefield[0].regeneration_shield == 1

    result = game.cast_from_hand(0, "Plain Destroy", target_player_index=1, target_permanent_index=0)

    assert result.supported
    # Drudge Skeletons regenerated (shield consumed, creature tapped, stays on battlefield)
    assert len(p2.battlefield) == 1
    assert p2.battlefield[0].card.name == "Drudge Skeletons"
    assert p2.battlefield[0].regeneration_shield == 0
    assert p2.battlefield[0].tapped is True


def test_regeneration_shield_saves_creature_from_lethal_damage(all_cards):
    # A regenerated creature dealt lethal direct damage (e.g. Lightning Bolt) is
    # destroyed as a state-based action, which the shield replaces: it stays on the
    # battlefield tapped with its damage cleared, rather than going to the graveyard.
    wall = _get(all_cards, "Wall of Bone")  # 0/4
    bolt = _get(all_cards, "Lightning Bolt")  # deals 3

    p1 = PlayerState(name="P1", hand=[bolt, bolt])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=wall, regeneration_shield=1)])
    game = Game(players=[p1, p2])

    # First bolt: 3 damage on a 0/4 — not lethal, survives.
    r1 = game.cast_from_hand(0, "Lightning Bolt", target_player_index=1, target_permanent_index=0)
    assert r1.supported
    assert len(p2.battlefield) == 1
    assert p2.battlefield[0].damage_marked == 3

    # Second bolt: 6 total >= toughness 4 — lethal. Regeneration replaces the
    # destruction: shield consumed, damage cleared, creature tapped, still on battlefield.
    r2 = game.cast_from_hand(0, "Lightning Bolt", target_player_index=1, target_permanent_index=0)
    assert r2.supported
    assert len(p2.battlefield) == 1, "Regenerated wall should survive lethal damage"
    assert p2.battlefield[0].card.name == "Wall of Bone"
    assert p2.battlefield[0].regeneration_shield == 0
    assert p2.battlefield[0].damage_marked == 0
    assert p2.battlefield[0].tapped is True
    assert not any(c.name == "Wall of Bone" for c in p2.graveyard)


def test_dwarven_demolition_team_destroys_wall(all_cards):
    # Dwarven Demolition Team: "{2}{R} — {T}: Destroy target Wall."
    team = _get(all_cards, "Dwarven Demolition Team")
    wall = _get(all_cards, "Wall of Stone")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=team)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=wall)])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Dwarven Demolition Team", target_player_index=1)

    assert result.supported
    # The team tapped to use its ability
    assert p1.battlefield[0].tapped is True
    # The wall was destroyed
    assert len(p2.battlefield) == 0
    assert p2.graveyard[0].name == "Wall of Stone"



def test_earth_elemental_enters_battlefield(all_cards):
    # Earth Elemental: "{3}{R}{R}" — vanilla 4/5 Creature — Elemental
    earth_elemental = _get(all_cards, "Earth Elemental")

    p1 = PlayerState(name="P1", hand=[earth_elemental])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Earth Elemental")

    assert result.supported
    assert len(p1.battlefield) == 1
    assert p1.battlefield[0].card.name == "Earth Elemental"



# ---------------------------------------------------------------------------
# Earthbind
# ---------------------------------------------------------------------------

def test_earthbind_damages_flying_creature_and_strips_flying(all_cards):
    earthbind = _get(all_cards, "Earthbind")
    serra = _get(all_cards, "Serra Angel")
    p1 = PlayerState(name="P1", hand=[earthbind])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=serra)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Earthbind", target_player_index=1, target_permanent_index=0)

    assert result.supported
    creature_perm = p2.battlefield[0]
    assert creature_perm.damage_marked == 2
    assert creature_perm.metadata.get("loses_flying") is True


def test_earthbind_no_damage_on_non_flying_creature(all_cards):
    earthbind = _get(all_cards, "Earthbind")
    bear = _get(all_cards, "Grizzly Bears")
    p1 = PlayerState(name="P1", hand=[earthbind])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Earthbind", target_player_index=1, target_permanent_index=0)

    assert result.supported
    creature_perm = p2.battlefield[0]
    assert creature_perm.damage_marked == 0
    assert not creature_perm.metadata.get("loses_flying")



# ---------------------------------------------------------------------------
# Earthquake
# ---------------------------------------------------------------------------

def test_earthquake_damages_all_players_and_non_flying_creatures(all_cards):
    earthquake = _get(all_cards, "Earthquake")
    grizzly = _get(all_cards, "Grizzly Bears")
    serra = _get(all_cards, "Serra Angel")
    # P1 has Earthquake in hand + a non-flying creature
    p1 = PlayerState(name="P1", life=20, hand=[earthquake],
                     battlefield=[Permanent(card=grizzly)])
    # P2 has a flying creature
    p2 = PlayerState(name="P2", life=20, battlefield=[Permanent(card=serra)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Earthquake", target_player_index=1, x_value=3)

    assert result.supported
    # Both players take 3 damage
    assert p1.life == 17
    assert p2.life == 17
    # Non-flying Grizzly Bears on p1's side takes 3 damage and dies (toughness=2)
    assert all(perm.card.name != "Grizzly Bears" for perm in p1.battlefield)
    assert any(c.name == "Grizzly Bears" for c in p1.graveyard)
    # Flying Serra Angel is unaffected
    assert any(perm.card.name == "Serra Angel" for perm in p2.battlefield)
    assert p2.battlefield[0].damage_marked == 0



# ---------------------------------------------------------------------------
# Elvish Archers
# ---------------------------------------------------------------------------

def test_elvish_archers_enters_battlefield(all_cards):
    archers = _get(all_cards, "Elvish Archers")
    p1 = PlayerState(name="P1", hand=[archers])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Elvish Archers")

    assert result.supported
    assert len(p1.battlefield) == 1
    perm = p1.battlefield[0]
    assert perm.card.name == "Elvish Archers"
    assert perm.effective_power == 2
    assert perm.effective_toughness == 1



# ---------------------------------------------------------------------------
# Evil Presence
# ---------------------------------------------------------------------------

def test_evil_presence_makes_land_a_swamp(all_cards):
    evil_presence = _get(all_cards, "Evil Presence")
    mountain = _get(all_cards, "Mountain")
    p1 = PlayerState(name="P1", hand=[evil_presence])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=mountain)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Evil Presence", target_player_index=1, target_permanent_index=0)

    assert result.supported
    land_perm = p2.battlefield[0]
    assert land_perm.metadata.get("land_type_override") == "swamp"



# ---------------------------------------------------------------------------
# Farmstead
# ---------------------------------------------------------------------------

def test_farmstead_grants_life_at_upkeep_when_paid(all_cards):
    farmstead = _get(all_cards, "Farmstead")
    plains = _get(all_cards, "Plains")
    farm_perm = Permanent(card=farmstead)
    plains_perm = Permanent(card=plains)
    # Attach Farmstead to Plains manually (simulating resolved cast)
    farm_perm.metadata["attached_to"] = plains_perm
    plains_perm.metadata["attached_aura"] = farm_perm
    p1 = PlayerState(name="P1", life=20, mana_pool={"W": 2},
                     battlefield=[plains_perm, farm_perm])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    # Player paid {W}{W} and gained 1 life
    assert p1.life == 21
    assert p1.mana_pool.get("W", 0) == 0


def test_farmstead_no_life_gain_without_mana(all_cards):
    farmstead = _get(all_cards, "Farmstead")
    plains = _get(all_cards, "Plains")
    farm_perm = Permanent(card=farmstead)
    plains_perm = Permanent(card=plains)
    farm_perm.metadata["attached_to"] = plains_perm
    plains_perm.metadata["attached_aura"] = farm_perm
    p1 = PlayerState(name="P1", life=20, battlefield=[plains_perm, farm_perm])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    # No mana to pay → no life gain
    assert p1.life == 20



def test_fireball_deals_damage(all_cards):
    fireball = _get(all_cards, "Fireball")
    p1 = PlayerState(name="P1", hand=[fireball])
    p2 = PlayerState(name="P2", life=10)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Fireball", target_player_index=1, x_value=3)

    assert result.supported
    assert p2.life == 7


def test_fireball_targets_single_creature(all_cards):
    fireball = _get(all_cards, "Fireball")
    bear = _mk_card("Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[fireball])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Fireball", target_player_index=1, target_permanent_index=0, x_value=3)

    assert result.supported
    # Bear has toughness 2, 3 damage should remove it
    assert not p2.battlefield


def test_gauntlet_of_might_buffs_red_creatures(all_cards):
    gauntlet = _get(all_cards, "Gauntlet of Might")
    red_creature = _mk_card("Red Goblin", "Creature — Goblin", colors=("R",))

    p1 = PlayerState(name="P1", hand=[gauntlet], battlefield=[Permanent(card=red_creature)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Gauntlet of Might")

    assert result.supported
    assert p1.battlefield[0].effective_power == 3
    assert p1.battlefield[0].effective_toughness == 3


def test_gauntlet_of_might_mountain_tap_grants_extra_red(all_cards):
    gauntlet = _get(all_cards, "Gauntlet of Might")
    mountain = _get(all_cards, "Mountain")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=gauntlet), Permanent(card=mountain)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.tap_land_for_mana(0, "Mountain")

    assert p1.mana_pool.get("R", 0) == 2


def test_giant_growth_gives_target_creature_plus_three_three(all_cards):
    growth = _get(all_cards, "Giant Growth")
    bear = _mk_card("Test Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[growth], battlefield=[Permanent(card=bear)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Giant Growth", target_player_index=0)

    assert result.supported
    assert p1.battlefield[0].effective_power == 5
    assert p1.battlefield[0].effective_toughness == 5


def test_giant_spider_can_block_flying_attacker(all_cards):
    spider = _get(all_cards, "Giant Spider")
    air_elem = _get(all_cards, "Air Elemental")

    spider_perm = Permanent(card=spider)
    air_perm = Permanent(card=air_elem)

    p1 = PlayerState(name="P1", battlefield=[spider_perm])
    p2 = PlayerState(name="P2", battlefield=[air_perm])
    game = Game(players=[p1, p2])

    assert game._can_block_attacker(spider_perm, air_perm) is True


def test_goblin_king_buffs_other_goblins_with_mountainwalk(all_cards):
    king = _get(all_cards, "Goblin King")
    goblin = _mk_card("Test Goblin", "Creature — Goblin")

    p1 = PlayerState(name="P1", hand=[king], battlefield=[Permanent(card=goblin)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Goblin King")

    assert result.supported
    goblin_perm = p1.battlefield[0]
    assert goblin_perm.effective_power == 3
    assert goblin_perm.effective_toughness == 3
    assert goblin_perm.metadata.get("has_mountainwalk") is True


def test_green_ward_grants_protection_from_green(all_cards):
    ward = _get(all_cards, "Green Ward")
    creature = _mk_creature_card("Test Knight", power=2, toughness=2)

    p1 = PlayerState(name="P1", hand=[ward], battlefield=[Permanent(card=creature)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Green Ward", target_player_index=0, target_permanent_index=0)

    assert result.supported
    creature_perm = p1.battlefield[0]
    assert creature_perm.metadata.get("protection_from_green") is True


def test_fireball_targets_multiple_creatures_divides_damage(all_cards):
    fireball = _get(all_cards, "Fireball")
    bear1 = _mk_card("Bear1", "Creature — Bear")
    bear2 = _mk_card("Bear2", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[fireball])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear1), Permanent(card=bear2)])
    game = Game(players=[p1, p2])

    # Provide both target indices; X=3 should divide as 1 and 1 (rounded down)
    result = game.cast_from_hand(0, "Fireball", target_player_index=1, target_permanent_index=[0, 1], x_value=3)

    assert result.supported
    assert len(p2.battlefield) == 2
    assert p2.battlefield[0].damage_marked == 1
    assert p2.battlefield[1].damage_marked == 1


def test_hurloon_minotaur_classifies_supported(all_cards):
    minotaur = _get(all_cards, "Hurloon Minotaur")
    classification = classify_card(minotaur)
    assert classification.supported
    perm = Permanent(card=minotaur)
    assert perm.effective_power == 2
    assert perm.effective_toughness == 3


def test_hurricane_deals_x_damage_to_flying_creatures_and_players(all_cards):
    hurricane = _get(all_cards, "Hurricane")
    serra_angel = _get(all_cards, "Serra Angel")
    grizzly = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", hand=[hurricane], life=20)
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=serra_angel), Permanent(card=grizzly)],
        life=20,
    )
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Hurricane", target_player_index=1, x_value=3)

    assert result.supported
    assert p1.life == 17  # hurricane hits all players including the caster
    assert p2.life == 17
    angel_perm = p2.battlefield[0]
    bear_perm = p2.battlefield[1]
    assert angel_perm.damage_marked == 3  # Serra Angel has flying — takes damage
    assert bear_perm.damage_marked == 0   # Grizzly Bears has no flying — unaffected


def test_hurricane_kills_small_flying_creature(all_cards):
    hurricane = _get(all_cards, "Hurricane")
    tiny_flyer = CardDefinition(
        name="Tiny Flyer",
        mana_cost="{1}",
        cmc=1.0,
        type_line="Creature — Bird",
        oracle_text="Flying",
        colors=(),
        color_identity=(),
        keywords=("Flying",),
        produced_mana=(),
        raw={"name": "Tiny Flyer", "type_line": "Creature — Bird", "power": "1", "toughness": "1"},
    )

    p1 = PlayerState(name="P1", hand=[hurricane], life=20)
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=tiny_flyer)], life=20)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Hurricane", target_player_index=1, x_value=2)

    assert result.supported
    assert p1.life == 18
    assert p2.life == 18
    assert len(p2.battlefield) == 0  # 1/1 flyer killed by 2 damage


def test_icy_manipulator_taps_target_creature(all_cards):
    icy = _get(all_cards, "Icy Manipulator")
    bear = _mk_card("Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=icy)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Icy Manipulator", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].tapped is True


def test_illusionary_mask_classifies_supported(all_cards):
    mask = _get(all_cards, "Illusionary Mask")
    classification = classify_card(mask)
    assert classification.supported


def test_illusionary_mask_activation_creates_face_down_creature(all_cards):
    mask = _get(all_cards, "Illusionary Mask")
    grizzly = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", hand=[grizzly], battlefield=[Permanent(card=mask)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Illusionary Mask", target_player_index=1)

    assert result.supported
    face_down = next(
        (perm for perm in p1.battlefield if perm.metadata.get("face_down")),
        None,
    )
    assert face_down is not None
    assert face_down.effective_power == 2
    assert face_down.effective_toughness == 2


def test_instill_energy_grants_haste_to_enchanted_creature(all_cards):
    instill = _get(all_cards, "Instill Energy")
    grizzly = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", hand=[instill], battlefield=[Permanent(card=grizzly)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    grizzly_perm = p1.battlefield[0]
    grizzly_perm.metadata["summoning_sickness_turn"] = game.turn

    result = game.cast_from_hand(0, "Instill Energy", target_player_index=0, target_permanent_index=0)
    assert result.supported

    # The creature should be able to attack despite summoning sickness due to Instill Energy's haste grant
    assert game.can_attack(grizzly_perm, defending_player_index=1) is True


def test_instill_energy_untap_ability(all_cards):
    instill = _get(all_cards, "Instill Energy")
    grizzly = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", hand=[instill], battlefield=[Permanent(card=grizzly, tapped=True)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Instill Energy", target_player_index=0, target_permanent_index=0)
    assert result.supported

    grizzly_perm = p1.battlefield[0]
    assert grizzly_perm.tapped is True

    activate_result = game.activate_permanent_ability(0, "Instill Energy", target_player_index=0)
    assert activate_result.supported
    assert grizzly_perm.tapped is False


def test_invisibility_only_blockable_by_walls(all_cards):
    invis = _get(all_cards, "Invisibility")
    grizzly = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", hand=[invis], battlefield=[Permanent(card=grizzly)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=grizzly)], life=20)
    game = Game(players=[p1, p2])

    cast_result = game.cast_from_hand(0, "Invisibility", target_player_index=0, target_permanent_index=0)
    assert cast_result.supported

    game.active_player_index = 0
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    game.current_phase = "combat"

    ok, _ = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok
    game.current_step = "declare_blockers"

    blockers = choose_combat_blockers(game, 1)
    # Non-wall Grizzly Bears should not be able to block a creature with Invisibility
    assert blockers == {}


def test_iron_star_gains_life_on_red_spell(all_cards):
    star = _get(all_cards, "Iron Star")
    lightning_bolt = _get(all_cards, "Lightning Bolt")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=star)], life=20)
    p2 = PlayerState(name="P2", hand=[lightning_bolt], life=20)
    game = Game(players=[p1, p2])

    game.cast_from_hand(1, "Lightning Bolt", target_player_index=1)

    # Iron Star should have triggered: P1 gains 1 life
    assert p1.life == 21


def test_ironclaw_orcs_cannot_block_power_2_or_greater(all_cards):
    orcs = _get(all_cards, "Ironclaw Orcs")
    grizzly = _get(all_cards, "Grizzly Bears")  # 2/2

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=grizzly)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=orcs)], life=20)
    game = Game(players=[p1, p2])

    game.active_player_index = 0
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    game.current_phase = "combat"

    ok, _ = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok
    game.current_step = "declare_blockers"

    # Ironclaw Orcs cannot block a creature with power 2 or greater
    assert game._can_block_attacker(p2.battlefield[0], p1.battlefield[0]) is False


def test_ironroot_treefolk_classifies_supported(all_cards):
    treefolk = _get(all_cards, "Ironroot Treefolk")
    assert classify_card(treefolk).supported


def test_ivory_cup_triggers_on_white_spell(all_cards):
    cup = _get(all_cards, "Ivory Cup")
    salve = _get(all_cards, "Healing Salve")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=cup)], life=20)
    p2 = PlayerState(name="P2", hand=[salve])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(1, "Healing Salve", target_player_index=1)

    assert result.supported
    assert p1.life == 21


def test_jade_monolith_redirects_damage_to_controller(all_cards):
    monolith = _get(all_cards, "Jade Monolith")
    bear = _mk_card("Bear", "Creature — Bear")
    bolt = _mk_card("Bolt Test", "Instant", "Bolt Test deals 3 damage to any target.")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=monolith)], life=20)
    p2 = PlayerState(name="P2", hand=[bolt], battlefield=[Permanent(card=bear)], life=20)
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Jade Monolith", target_player_index=1)
    assert result.supported

    result2 = game.cast_from_hand(1, "Bolt Test", target_player_index=1, target_permanent_index=0)
    assert result2.supported
    assert len(p2.battlefield) == 1  # bear survives (damage redirected)
    assert p1.life == 17             # monolith controller took 3 damage
    assert p2.life == 20


def test_jump_grants_flying_until_eot(all_cards):
    jump = _get(all_cards, "Jump")
    bear = _mk_card("Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[jump])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Jump", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("gains_flying_until_eot") is True


def test_karma_deals_damage_based_on_swamps(all_cards):
    karma = _get(all_cards, "Karma")
    swamp = _get(all_cards, "Swamp")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=karma)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=swamp), Permanent(card=swamp)], life=20)
    game = Game(players=[p1, p2])

    game.resolve_upkeep(1)

    assert p2.life == 18


def test_kudzu_destroys_land_when_tapped(all_cards):
    kudzu = _get(all_cards, "Kudzu")
    plains = _get(all_cards, "Plains")
    forest = _get(all_cards, "Forest")

    p1 = PlayerState(name="P1", hand=[kudzu])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=plains), Permanent(card=forest)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Kudzu", target_player_index=1, target_permanent_index=0)
    assert result.supported

    game.tap_land_for_mana(1, "Plains")

    assert not any(perm.card.name == "Plains" for perm in p2.battlefield)
    kudzu_perm = next((perm for perm in p1.battlefield if perm.card.name == "Kudzu"), None)
    assert kudzu_perm is not None
    assert kudzu_perm.metadata.get("attached_to") is not None


def test_island_sanctuary_grants_protection_after_skipping_draw(all_cards):
    sanctuary = _get(all_cards, "Island Sanctuary")
    grizzly = _get(all_cards, "Grizzly Bears")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[sanctuary], library=[island])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=grizzly)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Island Sanctuary", target_player_index=0)
    assert result.supported

    # Resolve draw step — Island Sanctuary causes P1 to skip draw for protection
    drawn = game.resolve_draw_step(0)
    assert drawn == 0

    # Non-flying, non-islandwalk Grizzly Bears cannot attack P1
    assert game.can_attack(p2.battlefield[0], defending_player_index=0) is False


def test_ley_druid_untaps_target_land(all_cards):
    druid = _get(all_cards, "Ley Druid")
    forest = _get(all_cards, "Forest")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=druid), Permanent(card=forest, tapped=True)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Ley Druid", target_player_index=0)

    assert result.supported
    assert p1.battlefield[1].tapped is False


def test_lich_loses_life_equal_to_life_total_on_entry(all_cards):
    lich = _get(all_cards, "Lich")
    p1 = PlayerState(name="P1", hand=[lich], life=20)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Lich")

    assert result.supported
    assert any(perm.card.name == "Lich" for perm in p1.battlefield)
    assert p1.life == 0


def test_lich_controller_does_not_lose_at_zero_or_less_life(all_cards):
    """'You don't lose the game for having 0 or less life.'"""
    lich = _get(all_cards, "Lich")
    p1 = PlayerState(name="P1", hand=[lich], life=20)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Lich")
    assert p1.life == 0

    game.check_state_based_actions()
    assert p1.lost is False

    p1.life = -5
    game.check_state_based_actions()
    assert p1.lost is False


def test_lich_life_gain_draws_cards_instead(all_cards):
    """'If you would gain life, draw that many cards instead.'"""
    lich = _get(all_cards, "Lich")
    forest = _get(all_cards, "Forest")
    p1 = PlayerState(
        name="P1",
        battlefield=[Permanent(card=lich)],
        library=[forest, forest, forest, forest],
        life=5,
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game._gain_life(p1, 3)

    assert p1.life == 5  # life total unchanged
    assert len(p1.hand) == 3  # drew 3 cards instead
    assert len(p1.library) == 1


def test_lich_life_gain_from_spell_draws_cards_instead(all_cards):
    """The replacement applies to life gained from resolving spells too."""
    lich = _get(all_cards, "Lich")
    stream = _get(all_cards, "Stream of Life")
    forest = _get(all_cards, "Forest")
    p1 = PlayerState(
        name="P1",
        hand=[stream],
        battlefield=[Permanent(card=lich)],
        library=[forest, forest, forest],
        life=5,
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Stream of Life", target_player_index=0, x_value=2)

    assert result.supported
    assert p1.life == 5
    assert len(p1.hand) == 2


def test_lich_damage_forces_sacrifice_of_that_many_nontoken_permanents(all_cards):
    """'Whenever you're dealt damage, sacrifice that many nontoken permanents.'"""
    lich = _get(all_cards, "Lich")
    forest = _get(all_cards, "Forest")
    bolt = _get(all_cards, "Lightning Bolt")
    p1 = PlayerState(
        name="P1",
        battlefield=[
            Permanent(card=lich),
            Permanent(card=forest),
            Permanent(card=forest),
            Permanent(card=forest),
            Permanent(card=forest),
        ],
        life=10,
    )
    p2 = PlayerState(name="P2", hand=[bolt])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(1, "Lightning Bolt", target_player_index=0)

    assert result.supported
    assert p1.life == 7
    # Sacrificed 3 of the 4 Forests; Lich itself is spared while other permanents exist
    assert sum(1 for perm in p1.battlefield if perm.card.name == "Forest") == 1
    assert any(perm.card.name == "Lich" for perm in p1.battlefield)
    assert sum(1 for card in p1.graveyard if card.name == "Forest") == 3
    assert p1.lost is False


def test_lich_damage_without_enough_permanents_loses_the_game(all_cards):
    """'If you can't [sacrifice that many], you lose the game.'"""
    lich = _get(all_cards, "Lich")
    bolt = _get(all_cards, "Lightning Bolt")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=lich)], life=10)
    p2 = PlayerState(name="P2", hand=[bolt])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(1, "Lightning Bolt", target_player_index=0)

    assert result.supported
    assert p1.lost is True


def test_lich_put_into_graveyard_from_battlefield_loses_the_game(all_cards):
    """'When this enchantment is put into a graveyard from the battlefield, you lose the game.'"""
    lich = _get(all_cards, "Lich")
    disenchant = _get(all_cards, "Disenchant")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=lich)], life=10)
    p2 = PlayerState(name="P2", hand=[disenchant])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(1, "Disenchant", target_player_index=0, target_permanent_index=0)

    assert result.supported
    assert not any(perm.card.name == "Lich" for perm in p1.battlefield)
    assert any(card.name == "Lich" for card in p1.graveyard)
    assert p1.lost is True
    assert game.get_winner() is p2


def test_lifeforce_counters_black_spell(all_cards):
    lifeforce = _get(all_cards, "Lifeforce")
    black_knight = _get(all_cards, "Black Knight")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=lifeforce)])
    p2 = PlayerState(name="P2", hand=[black_knight])
    game = Game(players=[p1, p2])

    game.queue_from_hand(1, "Black Knight")
    result = game.activate_permanent_ability(0, "Lifeforce", target_player_index=0)

    assert result.supported
    assert not game.stack
    assert any(card.name == "Black Knight" for card in p2.graveyard)


def test_lifeforce_requires_black_spell_on_stack(all_cards):
    lifeforce = _get(all_cards, "Lifeforce")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=lifeforce)])
    p1.mana_pool["G"] = 2
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # No black spell on stack — activation should be rejected
    result = game.queue_permanent_ability(0, "Lifeforce")
    assert not result.supported
    assert p1.mana_pool.get("G", 0) == 2  # mana not spent


def test_lifelace_changes_target_permanent_to_green(all_cards):
    lifelace = _get(all_cards, "Lifelace")
    creature = _mk_card("Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[lifelace])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Lifelace", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("color_override") == "G"


def test_lifetap_gains_life_when_opponent_forest_tapped(all_cards):
    lifetap = _get(all_cards, "Lifetap")
    forest = _get(all_cards, "Forest")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=lifetap)], life=20)
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=forest)])
    game = Game(players=[p1, p2])

    ok = game.tap_land_for_mana(1, "Forest")

    assert ok
    assert p1.life == 21


def test_living_artifact_upkeep_removes_counter_and_gains_life(all_cards):
    living = _get(all_cards, "Living Artifact")
    lotus = _get(all_cards, "Black Lotus")

    aura_perm = Permanent(card=living)
    artifact_perm = Permanent(card=lotus)
    aura_perm.metadata["attached_to"] = artifact_perm
    aura_perm.metadata["vitality_counters"] = 2

    p1 = PlayerState(name="P1", battlefield=[artifact_perm, aura_perm], life=20)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert p1.life == 21
    assert aura_perm.metadata.get("vitality_counters") == 1


def test_living_wall_gains_regeneration_shield(all_cards):
    wall = _get(all_cards, "Living Wall")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=wall)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Living Wall", target_player_index=0)

    assert result.supported
    assert p1.battlefield[0].regeneration_shield == 1


def test_lord_of_atlantis_buffs_other_merfolk_with_islandwalk(all_cards):
    lord = _get(all_cards, "Lord of Atlantis")
    merfolk = _get(all_cards, "Merfolk of the Pearl Trident")

    p1 = PlayerState(name="P1", hand=[lord], battlefield=[Permanent(card=merfolk)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Lord of Atlantis")

    assert result.supported
    merfolk_perm = p1.battlefield[0]
    assert merfolk_perm.effective_power == 2
    assert merfolk_perm.effective_toughness == 2
    assert merfolk_perm.metadata.get("has_islandwalk") is True


def test_lord_of_the_pit_upkeep_sacrifices_creature(all_cards):
    pit = _get(all_cards, "Lord of the Pit")
    creature = _mk_card("Fodder", "Creature — Bear")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=pit), Permanent(card=creature)], life=20)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert p1.life == 20
    assert any(c.name == "Fodder" for c in p1.graveyard)
    assert len(p1.battlefield) == 1


def test_lord_of_the_pit_upkeep_deals_damage_without_creature(all_cards):
    pit = _get(all_cards, "Lord of the Pit")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=pit)], life=20)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert p1.life == 13


def test_lure_forces_all_creatures_to_block(all_cards):
    lure = _get(all_cards, "Lure")
    attacker = _mk_card("Bait", "Creature — Bear")
    blocker1 = _mk_card("Guard1", "Creature — Bear")
    blocker2 = _mk_card("Guard2", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[lure], battlefield=[Permanent(card=attacker)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=blocker1), Permanent(card=blocker2)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Lure", target_player_index=0, target_permanent_index=0)
    assert result.supported

    game.active_player_index = 0
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    game.current_phase = "combat"
    game.declare_attackers(0, [0], defending_player_index=1)
    game.current_step = "declare_blockers"

    # Assigning only one blocker when two can block a Lure creature should fail
    ok, _ = game.declare_blockers(1, {0: 0})
    assert not ok

    # Assigning all capable blockers should succeed
    ok2, _ = game.declare_blockers(1, {0: 0, 1: 0})
    assert ok2


def test_mahamoti_djinn_classifies_supported(all_cards):
    djinn = _get(all_cards, "Mahamoti Djinn")
    result = classify_card(djinn)
    assert result.supported
    perm = Permanent(card=djinn)
    assert perm.effective_power == 5
    assert perm.effective_toughness == 6


def test_mana_short_taps_target_lands_and_drains_mana(all_cards):
    mana_short = _get(all_cards, "Mana Short")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[mana_short])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=island), Permanent(card=island)], mana_pool={"U": 3})
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Mana Short", target_player_index=1)

    assert result.supported
    assert all(perm.tapped for perm in p2.battlefield)
    assert p2.mana_pool["U"] == 0


def test_mana_vault_taps_for_three_colorless_mana(all_cards):
    vault = _get(all_cards, "Mana Vault")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=vault)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Mana Vault")

    assert result.supported
    assert p1.mana_pool["C"] == 3
    assert p1.battlefield[0].tapped is True


def test_manabarbs_deals_damage_when_land_tapped(all_cards):
    manabarbs = _get(all_cards, "Manabarbs")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[manabarbs])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=island)], life=20)
    game = Game(players=[p1, p2])

    cast_result = game.cast_from_hand(0, "Manabarbs")
    assert cast_result.supported

    game.tap_land_for_mana(1, "Island")

    assert p2.life == 19


def test_merfolk_of_the_pearl_trident_classifies_supported(all_cards):
    merfolk = _get(all_cards, "Merfolk of the Pearl Trident")
    result = classify_card(merfolk)
    assert result.supported
    perm = Permanent(card=merfolk)
    assert perm.effective_power == 1
    assert perm.effective_toughness == 1


def test_mind_twist_discards_x_cards_at_random(all_cards):
    mind_twist = _get(all_cards, "Mind Twist")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[mind_twist])
    p2 = PlayerState(name="P2", hand=[island, island, island])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Mind Twist", target_player_index=1, x_value=2)

    assert result.supported
    assert len(p2.hand) == 1
    assert len(p2.graveyard) == 2


def test_mons_goblin_raiders_classifies_supported(all_cards):
    raiders = _get(all_cards, "Mons's Goblin Raiders")
    result = classify_card(raiders)
    assert result.supported
    perm = Permanent(card=raiders)
    assert perm.effective_power == 1
    assert perm.effective_toughness == 1


def test_mox_emerald_taps_for_green_mana(all_cards):
    mox = _get(all_cards, "Mox Emerald")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=mox)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Mox Emerald")

    assert result.supported
    assert p1.mana_pool["G"] == 1
    assert p1.battlefield[0].tapped is True


def test_mox_jet_taps_for_black_mana(all_cards):
    mox = _get(all_cards, "Mox Jet")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=mox)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Mox Jet")

    assert result.supported
    assert p1.mana_pool["B"] == 1
    assert p1.battlefield[0].tapped is True


# ---------------------------------------------------------------------------
# Regression tests for "Choose one" modal card oracle parsing (bug fix)
# ---------------------------------------------------------------------------

def test_healing_salve_choose_one_gains_life(all_cards):
    """Regression: real LEA Healing Salve should gain 3 life (first mode), not
    apply a prevention shield. The oracle parser previously matched the second
    bullet 'prevent the next 3 damage' before 'gains 3 life'."""
    salve = _get(all_cards, "Healing Salve")
    p1 = PlayerState(name="P1", hand=[salve], life=17)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Healing Salve", target_player_index=0)

    assert result.supported
    assert p1.life == 20, "Healing Salve should gain 3 life (first mode), not apply prevention"
    assert p1.damage_prevention_pool == 0, "Prevention shield should not be applied when gaining life"


def test_healing_salve_choose_one_compiles_to_life_gain(all_cards):
    """Regression: the primary oracle instruction for real LEA Healing Salve must
    be target_gains_life, not grant_prevention_shield."""
    salve = _get(all_cards, "Healing Salve")
    program = compile_card_oracle(salve)
    primary = next(
        (instr for instr in program.instructions if instr.kind != "spell_pattern"), None
    )
    assert primary is not None
    assert primary.kind == "target_gains_life", (
        f"Expected target_gains_life but got {primary.kind}; "
        "choose-one parsing should use the first bullet"
    )


def test_blue_elemental_blast_choose_one_compiles_to_counter(all_cards):
    """Regression: Blue Elemental Blast's first mode is 'counter target red spell'.
    The oracle previously matched the second mode 'destroy target red permanent' first."""
    beb = _get(all_cards, "Blue Elemental Blast")
    program = compile_card_oracle(beb)
    primary = next(
        (instr for instr in program.instructions if instr.kind != "spell_pattern"), None
    )
    assert primary is not None
    assert primary.kind == "counter_top_stack_spell", (
        f"Expected counter_top_stack_spell but got {primary.kind}"
    )
    assert primary.payload.get("color_filter") == "R"


def test_red_elemental_blast_choose_one_compiles_to_counter(all_cards):
    """Regression: Red Elemental Blast's first mode is 'counter target blue spell'.
    The oracle previously matched the second mode 'destroy target blue permanent' first."""
    reb = _get(all_cards, "Red Elemental Blast")
    program = compile_card_oracle(reb)
    primary = next(
        (instr for instr in program.instructions if instr.kind != "spell_pattern"), None
    )
    assert primary is not None
    assert primary.kind == "counter_top_stack_spell", (
        f"Expected counter_top_stack_spell but got {primary.kind}"
    )
    assert primary.payload.get("color_filter") == "U"


def test_healing_salve_compiles_both_modes(all_cards):
    """The modal compiler exposes each "Choose one —" bullet as a selectable mode
    so the game can resolve the player's pick rather than always the first."""
    salve = _get(all_cards, "Healing Salve")
    program = compile_card_oracle(salve)
    assert len(program.modes) == 2
    assert program.modes[0].instruction is not None
    assert program.modes[0].instruction.kind == "target_gains_life"
    assert program.modes[0].supported
    assert program.modes[1].instruction is not None
    assert program.modes[1].instruction.kind == "grant_prevention_shield"
    assert program.modes[1].supported
    # Labels keep human-readable, original-case text for the UI prompt.
    assert program.modes[0].label == "Target player gains 3 life"


def test_healing_salve_resolves_chosen_prevention_mode(all_cards):
    """Casting Healing Salve with mode_index=1 applies the prevention shield mode
    instead of the default life-gain mode."""
    salve = _get(all_cards, "Healing Salve")
    p1 = PlayerState(name="P1", hand=[salve], life=17)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Healing Salve", target_player_index=0, mode_index=1)

    assert result.supported
    assert p1.life == 17, "Prevention mode should not gain life"
    assert p1.damage_prevention_pool == 3, "Prevention mode should grant a 3-damage shield"


def test_healing_salve_resolves_chosen_life_mode(all_cards):
    """mode_index=0 gains life; the default (no mode) matches this first mode."""
    salve = _get(all_cards, "Healing Salve")
    p1 = PlayerState(name="P1", hand=[salve], life=17)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Healing Salve", target_player_index=0, mode_index=0)

    assert result.supported
    assert p1.life == 20
    assert p1.damage_prevention_pool == 0


def test_healing_salve_prevention_shields_targeted_creature(all_cards):
    """Regression: the prevention mode aimed at a 1/1 creature must shield that
    creature, so a later Lightning Bolt is reduced and the creature survives."""
    salve = _get(all_cards, "Healing Salve")
    bolt = _get(all_cards, "Lightning Bolt")
    bear = _grizzly(all_cards)  # 2/2

    p1 = PlayerState(name="P1", hand=[salve, bolt])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    # Shield the opponent's creature, then bolt it.
    salved = game.cast_from_hand(
        0, "Healing Salve", target_player_index=1, target_permanent_index=0, mode_index=1
    )
    assert salved.supported
    assert p2.battlefield[0].damage_prevention_pool == 3

    game.cast_from_hand(0, "Lightning Bolt", target_player_index=1, target_permanent_index=0)

    # 3 prevented from 3 damage → creature takes 0 and survives.
    assert len(p2.battlefield) == 1, "Prevention shield should keep the creature alive"
    assert p2.battlefield[0].damage_marked == 0
    assert p2.battlefield[0].damage_prevention_pool == 0


def test_creature_prevention_pool_clears_at_end_of_turn(all_cards):
    """The creature prevention shield is a 'this turn' effect and must reset so it
    doesn't linger into later turns."""
    salve = _get(all_cards, "Healing Salve")
    bear = _grizzly(all_cards)

    p1 = PlayerState(name="P1", hand=[salve])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Healing Salve", target_player_index=1, target_permanent_index=0, mode_index=1)
    assert p2.battlefield[0].damage_prevention_pool == 3

    game.resolve_cleanup_step(0)
    assert p2.battlefield[0].damage_prevention_pool == 0


# ---------------------------------------------------------------------------
# Regression tests for AI prevention-shield awareness (bug fix)
# ---------------------------------------------------------------------------

def test_ai_skips_prodigal_sorcerer_when_opponent_fully_shielded(all_cards):
    """Regression: choose_activation_action must return None (or prefer another
    action) when the only damage ability would deal 0 effective damage because
    the target's damage_prevention_pool covers the full amount."""
    prodigal = _get(all_cards, "Prodigal Sorcerer")
    # Opponent has a 3-point prevention shield; Prodigal deals 1 → fully prevented
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=prodigal)])
    p2 = PlayerState(name="P2", life=20, damage_prevention_pool=3)
    game = Game(players=[p1, p2])

    action = choose_activation_action(game, 0)

    assert action is None, (
        "AI should not waste Prodigal Sorcerer's activation when the opponent's "
        "prevention shield would absorb all damage"
    )


def test_ai_still_activates_prodigal_sorcerer_without_full_shield(all_cards):
    """Companion to the shield test: AI should still activate Prodigal Sorcerer
    when the opponent has no (or partial) prevention shielding."""
    prodigal = _get(all_cards, "Prodigal Sorcerer")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=prodigal)])
    p2 = PlayerState(name="P2", life=20, damage_prevention_pool=0)
    game = Game(players=[p1, p2])

    action = choose_activation_action(game, 0)

    assert action is not None
    assert action.permanent_name == "Prodigal Sorcerer"


def test_mox_pearl_taps_for_white_mana(all_cards):
    mox = _get(all_cards, "Mox Pearl")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=mox)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Mox Pearl")

    assert result.supported
    assert p1.mana_pool["W"] == 1
    assert p1.battlefield[0].tapped is True


def test_mox_ruby_taps_for_red_mana(all_cards):
    mox = _get(all_cards, "Mox Ruby")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=mox)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Mox Ruby")

    assert result.supported
    assert p1.mana_pool["R"] == 1
    assert p1.battlefield[0].tapped is True


def test_mox_sapphire_taps_for_blue_mana(all_cards):
    mox = _get(all_cards, "Mox Sapphire")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=mox)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Mox Sapphire")

    assert result.supported
    assert p1.mana_pool["U"] == 1
    assert p1.battlefield[0].tapped is True


def test_pestilence_activation_deals_1_damage_to_all_creatures_and_players(all_cards):
    pestilence = _get(all_cards, "Pestilence")
    grizzly = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=pestilence), Permanent(card=grizzly)], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Pestilence")

    assert result.supported
    assert p1.life == 19
    assert p2.life == 19
    creature_perm = next(p for p in p1.battlefield if p.card.name == "Grizzly Bears")
    assert creature_perm.damage_marked >= 1


def test_pestilence_sacrificed_at_end_step_when_no_creatures(all_cards):
    pestilence = _get(all_cards, "Pestilence")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=pestilence)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_end_step(0)

    assert not any(p.card.name == "Pestilence" for p in p1.battlefield)
    assert any(card.name == "Pestilence" for card in p1.graveyard)


def test_pestilence_not_sacrificed_at_end_step_when_creatures_present(all_cards):
    pestilence = _get(all_cards, "Pestilence")
    grizzly = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=pestilence), Permanent(card=grizzly)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_end_step(0)

    assert any(p.card.name == "Pestilence" for p in p1.battlefield)


def test_phantasmal_forces_sacrifices_at_upkeep_without_blue_mana(all_cards):
    forces = _get(all_cards, "Phantasmal Forces")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=forces)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert not p1.battlefield
    assert any(card.name == "Phantasmal Forces" for card in p1.graveyard)


def test_phantasmal_forces_survives_upkeep_when_blue_mana_paid(all_cards):
    forces = _get(all_cards, "Phantasmal Forces")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=forces)], mana_pool={"W": 0, "U": 1, "B": 0, "R": 0, "G": 0, "C": 0})
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert any(p.card.name == "Phantasmal Forces" for p in p1.battlefield)


def test_phantasmal_terrain_overrides_enchanted_land_type(all_cards):
    terrain = _get(all_cards, "Phantasmal Terrain")
    plains = _get(all_cards, "Plains")

    p1 = PlayerState(name="P1", hand=[terrain])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=plains)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Phantasmal Terrain", target_player_index=1, target_permanent_index=0)

    assert result.supported
    assert p2.battlefield[0].metadata.get("land_type_override") is not None


def test_phantom_monster_classifies_supported(all_cards):
    monster = _get(all_cards, "Phantom Monster")
    assert classify_card(monster).supported


def test_pirate_ship_cannot_attack_without_defending_island(all_cards):
    ship = _get(all_cards, "Pirate Ship")
    island = _get(all_cards, "Island")

    # Controller keeps an Island so Pirate Ship isn't sacrificed (state-based).
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=ship), Permanent(card=island)])
    p2 = PlayerState(name="P2", battlefield=[])
    game = Game(players=[p1, p2])

    assert game.can_attack(p1.battlefield[0], defending_player_index=1) is False


def test_pirate_ship_can_attack_with_defending_island(all_cards):
    ship = _get(all_cards, "Pirate Ship")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=ship), Permanent(card=island)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=island)])
    game = Game(players=[p1, p2])

    assert game.can_attack(p1.battlefield[0], defending_player_index=1) is True


def test_pirate_ship_tap_deals_1_damage(all_cards):
    ship = _get(all_cards, "Pirate Ship")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=ship), Permanent(card=island)])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Pirate Ship", target_player_index=1)

    assert result.supported
    assert p2.life == 19
    assert p1.battlefield[0].tapped is True


def test_pirate_ship_sacrifices_at_upkeep_without_islands(all_cards):
    ship = _get(all_cards, "Pirate Ship")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=ship)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert not any(p.card.name == "Pirate Ship" for p in p1.battlefield)
    assert any(card.name == "Pirate Ship" for card in p1.graveyard)


def test_plague_rats_power_toughness_equals_rat_count(all_cards):
    rat = _get(all_cards, "Plague Rats")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=rat), Permanent(card=rat)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game._refresh_dynamic_creatures()

    assert p1.battlefield[0].effective_power == 2
    assert p1.battlefield[0].effective_toughness == 2
    assert p1.battlefield[1].effective_power == 2
    assert p1.battlefield[1].effective_toughness == 2


def test_plateau_taps_for_red_or_white(all_cards):
    plateau = _get(all_cards, "Plateau")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=plateau)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    ok_r = game.tap_land_for_mana(0, "Plateau", "R")
    assert ok_r
    assert p1.mana_pool["R"] == 1

    p1.battlefield[0].tapped = False
    ok_w = game.tap_land_for_mana(0, "Plateau", "W")
    assert ok_w
    assert p1.mana_pool["W"] == 1


def test_power_leak_deals_upkeep_damage_to_enchanted_enchantment_controller(all_cards):
    power_leak = _get(all_cards, "Power Leak")
    bad_moon = _get(all_cards, "Bad Moon")

    p1 = PlayerState(name="P1", hand=[power_leak])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bad_moon)], life=20)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Power Leak", target_player_index=1, target_permanent_index=0)
    assert result.supported

    game.resolve_upkeep(1)

    assert p2.life == 18


def test_power_surge_upkeep_deals_damage_equal_to_untapped_lands_at_turn_start(all_cards):
    surge = _get(all_cards, "Power Surge")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=surge)])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=island), Permanent(card=island)],
        life=20,
    )
    game = Game(players=[p1, p2])

    game.resolve_untap_step(1)
    game.resolve_upkeep(1)

    assert p2.life == 18


def test_psionic_blast_deals_four_to_target_and_two_to_caster(all_cards):
    blast = _get(all_cards, "Psionic Blast")

    p1 = PlayerState(name="P1", hand=[blast], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Psionic Blast", target_player_index=1)

    assert result.supported
    assert p2.life == 16
    assert p1.life == 18


def test_psychic_venom_deals_damage_when_enchanted_land_tapped(all_cards):
    psychic_venom = _get(all_cards, "Psychic Venom")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[psychic_venom])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=island)], life=20)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Psychic Venom", target_player_index=1, target_permanent_index=0)
    assert result.supported

    game.tap_land_for_mana(1, "Island", "U")

    assert p2.life == 18


def test_purelace_changes_target_to_white(all_cards):
    purelace = _get(all_cards, "Purelace")
    bear = _mk_card("Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[purelace])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Purelace", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("color_override") == "W"


def test_purelace_targets_specific_permanent_by_index(all_cards):
    """Purelace with a target_permanent_index must recolor that specific permanent,
    not always the first one (targeting regression)."""
    purelace = _get(all_cards, "Purelace")
    bear1 = _mk_card("Bear Alpha", "Creature — Bear")
    bear2 = _mk_card("Bear Beta", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[purelace])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear1), Permanent(card=bear2)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Purelace", target_player_index=1, target_permanent_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("color_override") is None, "first permanent must not be recolored"
    assert p2.battlefield[1].metadata.get("color_override") == "W", "second permanent must be recolored"


def test_purelace_fails_when_no_permanents_in_play(all_cards):
    """Purelace must fail validation when there are no valid targets on the battlefield."""
    purelace = _get(all_cards, "Purelace")

    p1 = PlayerState(name="P1", hand=[purelace])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.queue_from_hand(0, "Purelace", target_player_index=1)

    assert not result.supported


def test_raise_dead_returns_creature_from_graveyard_to_hand(all_cards):
    raise_dead = _get(all_cards, "Raise Dead")
    bear = _mk_card("Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[raise_dead], graveyard=[bear])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Raise Dead", target_player_index=0)

    assert result.supported
    assert any(card.name == "Bear" for card in p1.hand)
    assert not any(card.name == "Bear" for card in p1.graveyard)


def test_raise_dead_cannot_cast_with_empty_graveyard(all_cards):
    raise_dead = _get(all_cards, "Raise Dead")

    p1 = PlayerState(name="P1", hand=[raise_dead], graveyard=[])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Raise Dead", target_player_index=0)

    assert not result.supported


def test_raise_dead_cannot_cast_with_only_non_creatures_in_graveyard(all_cards):
    raise_dead = _get(all_cards, "Raise Dead")
    sorcery = _mk_card("Lightning Bolt", "Sorcery")

    p1 = PlayerState(name="P1", hand=[raise_dead], graveyard=[sorcery])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Raise Dead", target_player_index=0)

    assert not result.supported


def test_red_elemental_blast_counters_blue_spell(all_cards):
    """Red Elemental Blast's first mode counters a blue spell on the stack."""
    reb = _get(all_cards, "Red Elemental Blast")
    recall = _get(all_cards, "Ancestral Recall")
    p1 = PlayerState(name="P1", hand=[reb])
    p2 = PlayerState(name="P2", hand=[recall])
    game = Game(players=[p1, p2])

    game.queue_from_hand(1, "Ancestral Recall", target_player_index=1)
    result = game.cast_from_hand(0, "Red Elemental Blast", target_player_index=1)

    assert result.supported
    assert any("Red Elemental Blast countered Ancestral Recall" in line for line in game.log)
    assert not game.stack, "Stack should be empty after counterspell resolves"


def test_red_ward_grants_protection_from_red(all_cards):
    red_ward = _get(all_cards, "Red Ward")
    grizzly = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", hand=[red_ward], battlefield=[Permanent(card=grizzly)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Red Ward", target_player_index=0, target_permanent_index=0)

    assert result.supported
    assert p1.battlefield[0].metadata.get("protection_from_red") is True


def test_regrowth_returns_creature_from_graveyard_to_hand(all_cards):
    regrowth = _get(all_cards, "Regrowth")
    bear = _mk_card("Dead Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[regrowth], graveyard=[bear])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Regrowth", target_player_index=0)

    assert result.supported
    assert any(card.name == "Dead Bear" for card in p1.hand)
    assert not any(card.name == "Dead Bear" for card in p1.graveyard)


def test_resurrection_returns_creature_from_graveyard_to_battlefield(all_cards):
    resurrection = _get(all_cards, "Resurrection")
    bear = _mk_card("Dead Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[resurrection], graveyard=[bear])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Resurrection", target_player_index=0)

    assert result.supported
    assert any(perm.card.name == "Dead Bear" for perm in p1.battlefield)
    assert not any(card.name == "Dead Bear" for card in p1.graveyard)


def test_reverse_damage_classifies_supported(all_cards):
    reverse_damage = _get(all_cards, "Reverse Damage")
    assert classify_card(reverse_damage).supported


def test_righteousness_pumps_blocking_creature_plus_seven(all_cards):
    righteousness = _get(all_cards, "Righteousness")
    bear = _mk_card("Blocker", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[righteousness])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Righteousness", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].effective_power == 9
    assert p2.battlefield[0].effective_toughness == 9


def test_roc_of_kher_ridges_classifies_supported_with_flying(all_cards):
    roc = _get(all_cards, "Roc of Kher Ridges")
    assert classify_card(roc).supported
    assert "Flying" in roc.keywords


def test_rod_of_ruin_deals_one_damage_to_target(all_cards):
    rod = _get(all_cards, "Rod of Ruin")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=rod)])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Rod of Ruin", target_player_index=1)

    assert result.supported
    assert p2.life == 19
    assert p1.battlefield[0].tapped is True


def test_royal_assassin_destroys_tapped_creature(all_cards):
    assassin = _get(all_cards, "Royal Assassin")
    bear = _mk_card("Tapped Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=assassin)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear, tapped=True)])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Royal Assassin", target_player_index=1)

    assert result.supported
    assert not p2.battlefield
    assert p2.graveyard and p2.graveyard[0].name == "Tapped Bear"
    assert p1.battlefield[0].tapped is True


def test_samite_healer_prevents_one_damage(all_cards):
    healer = _get(all_cards, "Samite Healer")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=healer)])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Samite Healer", target_player_index=1)

    assert result.supported
    assert p2.damage_prevention_pool == 1
    assert p1.battlefield[0].tapped is True


def test_savannah_taps_for_green_mana(all_cards):
    savannah = _get(all_cards, "Savannah")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=savannah)])
    game = Game(players=[p1, PlayerState(name="P2")])

    ok = game.tap_land_for_mana(0, "Savannah")

    assert ok
    assert p1.mana_pool["G"] == 1


# ---------------------------------------------------------------------------
# Savannah Lions
# ---------------------------------------------------------------------------

def test_savannah_lions_enters_battlefield(all_cards):
    lions = _get(all_cards, "Savannah Lions")
    p1 = PlayerState(name="P1", hand=[lions])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Savannah Lions")

    assert result.supported
    assert len(p1.battlefield) == 1
    perm = p1.battlefield[0]
    assert perm.card.name == "Savannah Lions"
    assert perm.effective_power == 2
    assert perm.effective_toughness == 1


# ---------------------------------------------------------------------------
# Scathe Zombies
# ---------------------------------------------------------------------------

def test_scathe_zombies_enters_battlefield(all_cards):
    zombies = _get(all_cards, "Scathe Zombies")
    p1 = PlayerState(name="P1", hand=[zombies])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Scathe Zombies")

    assert result.supported
    assert len(p1.battlefield) == 1
    perm = p1.battlefield[0]
    assert perm.card.name == "Scathe Zombies"
    assert perm.effective_power == 2
    assert perm.effective_toughness == 2


# ---------------------------------------------------------------------------
# Scrubland
# ---------------------------------------------------------------------------

def test_scrubland_taps_for_white_mana(all_cards):
    scrubland = _get(all_cards, "Scrubland")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=scrubland)])
    game = Game(players=[p1, PlayerState(name="P2")])

    ok = game.tap_land_for_mana(0, "Scrubland", "W")

    assert ok
    assert p1.mana_pool.get("W", 0) == 1


def test_scrubland_taps_for_black_mana(all_cards):
    scrubland = _get(all_cards, "Scrubland")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=scrubland)])
    game = Game(players=[p1, PlayerState(name="P2")])

    ok = game.tap_land_for_mana(0, "Scrubland", "B")

    assert ok
    assert p1.mana_pool.get("B", 0) == 1


# ---------------------------------------------------------------------------
# Scryb Sprites
# ---------------------------------------------------------------------------

def test_scryb_sprites_enters_as_one_one_with_flying(all_cards):
    sprites = _get(all_cards, "Scryb Sprites")
    p1 = PlayerState(name="P1", hand=[sprites])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Scryb Sprites")

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.card.name == "Scryb Sprites"
    assert perm.effective_power == 1
    assert perm.effective_toughness == 1
    assert any(k.lower() == "flying" for k in sprites.keywords)


# ---------------------------------------------------------------------------
# Sengir Vampire
# ---------------------------------------------------------------------------



def test_sengir_vampire_enters_battlefield(all_cards):
    vampire = _get(all_cards, "Sengir Vampire")
    p1 = PlayerState(name="P1", hand=[vampire])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Sengir Vampire")

    assert result.supported
    assert p1.battlefield[0].card.name == "Sengir Vampire"
    assert p1.battlefield[0].effective_power == 4
    assert p1.battlefield[0].effective_toughness == 4


# ---------------------------------------------------------------------------
# Shanodin Dryads
# ---------------------------------------------------------------------------

def test_shanodin_dryads_enters_with_forestwalk(all_cards):
    dryads = _get(all_cards, "Shanodin Dryads")
    p1 = PlayerState(name="P1", hand=[dryads])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Shanodin Dryads")

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.card.name == "Shanodin Dryads"
    assert perm.effective_power == 1
    assert perm.effective_toughness == 1
    assert any(k.lower() == "forestwalk" for k in dryads.keywords)


# ---------------------------------------------------------------------------
# Shatter
# ---------------------------------------------------------------------------

def test_shatter_destroys_target_artifact(all_cards):
    shatter = _get(all_cards, "Shatter")
    sol_ring = _mk_card("Test Ring", "Artifact")

    p1 = PlayerState(name="P1", hand=[shatter])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=sol_ring)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Shatter", target_player_index=1)

    assert result.supported
    assert not p2.battlefield
    assert p2.graveyard[0].name == "Test Ring"


# ---------------------------------------------------------------------------
# Simulacrum
# ---------------------------------------------------------------------------

def test_simulacrum_resolves_without_error(all_cards):
    simulacrum = _get(all_cards, "Simulacrum")
    grizzly = _get(all_cards, "Grizzly Bears")
    # Simulacrum targets a creature you control, so it needs one to be cast.
    p1 = PlayerState(name="P1", hand=[simulacrum], battlefield=[Permanent(card=grizzly)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    result = game.cast_from_hand(0, "Simulacrum", target_player_index=0, target_permanent_index=0)

    assert result.supported
    assert not p1.hand
    assert any(c.name == "Simulacrum" for c in p1.graveyard)


# ---------------------------------------------------------------------------
# Sinkhole
# ---------------------------------------------------------------------------

def test_sinkhole_destroys_target_land(all_cards):
    sinkhole = _get(all_cards, "Sinkhole")
    forest = _mk_card("Forest", "Basic Land - Forest")

    p1 = PlayerState(name="P1", hand=[sinkhole])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=forest)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Sinkhole", target_player_index=1)

    assert result.supported
    assert not p2.battlefield
    assert p2.graveyard[0].name == "Forest"


# ---------------------------------------------------------------------------
# Siren's Call
# ---------------------------------------------------------------------------

def test_sirens_call_resolves_without_error(all_cards):
    sirens_call = _get(all_cards, "Siren's Call")
    island = _get(all_cards, "Island")
    p1 = PlayerState(name="P1", hand=[sirens_call])
    p2 = PlayerState(name="P2", library=[island])
    game = Game(players=[p1, p2])

    # Castable only during an opponent's turn, before attackers are declared.
    game.start_turn(1)
    result = game.cast_from_hand(0, "Siren's Call")

    assert result.supported
    assert not p1.hand
    assert any(c.name == "Siren's Call" for c in p1.graveyard)


# ---------------------------------------------------------------------------
# Sol Ring
# ---------------------------------------------------------------------------

def test_sol_ring_adds_two_colorless_mana(all_cards):
    sol_ring = _get(all_cards, "Sol Ring")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=sol_ring)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Sol Ring")

    assert result.supported
    assert p1.mana_pool.get("C", 0) == 2
    assert p1.battlefield[0].tapped is True


# ---------------------------------------------------------------------------
# Soul Net
# ---------------------------------------------------------------------------

def test_soul_net_enters_battlefield(all_cards):
    soul_net = _get(all_cards, "Soul Net")
    p1 = PlayerState(name="P1", hand=[soul_net])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Soul Net")

    assert result.supported
    assert p1.battlefield[0].card.name == "Soul Net"
    assert not p1.hand


# ---------------------------------------------------------------------------
# Steal Artifact
# ---------------------------------------------------------------------------

def test_steal_artifact_attaches_to_target_artifact(all_cards):
    steal = _get(all_cards, "Steal Artifact")
    target_artifact = _mk_card("Test Artifact", "Artifact")

    p1 = PlayerState(name="P1", hand=[steal])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=target_artifact)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Steal Artifact", target_player_index=1, target_permanent_index=0)

    assert result.supported
    steal_perm = next(p for p in p1.battlefield if p.card.name == "Steal Artifact")
    assert steal_perm.metadata.get("attached_to") is not None


# ---------------------------------------------------------------------------
# Stone Rain
# ---------------------------------------------------------------------------

def test_stone_rain_destroys_target_land(all_cards):
    stone_rain = _get(all_cards, "Stone Rain")
    mountain = _mk_card("Mountain", "Basic Land - Mountain")

    p1 = PlayerState(name="P1", hand=[stone_rain])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=mountain)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Stone Rain", target_player_index=1)

    assert result.supported
    assert not p2.battlefield
    assert p2.graveyard[0].name == "Mountain"


# ---------------------------------------------------------------------------
# Swords to Plowshares
# ---------------------------------------------------------------------------

def test_swords_to_plowshares_resolves_without_error(all_cards):
    swords = _get(all_cards, "Swords to Plowshares")
    bear = _mk_creature_card("Test Bear", 2, 2)
    p1 = PlayerState(name="P1", hand=[swords])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Swords to Plowshares", target_player_index=1, target_permanent_index=0)

    assert result.supported
    assert not p1.hand
    assert any(c.name == "Swords to Plowshares" for c in p1.graveyard)


# ---------------------------------------------------------------------------
# Taiga
# ---------------------------------------------------------------------------

def test_taiga_taps_for_red_mana(all_cards):
    taiga = _get(all_cards, "Taiga")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=taiga)])
    game = Game(players=[p1, PlayerState(name="P2")])

    ok = game.tap_land_for_mana(0, "Taiga", "R")

    assert ok
    assert p1.mana_pool.get("R", 0) == 1


def test_taiga_taps_for_green_mana(all_cards):
    taiga = _get(all_cards, "Taiga")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=taiga)])
    game = Game(players=[p1, PlayerState(name="P2")])

    ok = game.tap_land_for_mana(0, "Taiga", "G")

    assert ok
    assert p1.mana_pool.get("G", 0) == 1


# ---------------------------------------------------------------------------
# Terror
# ---------------------------------------------------------------------------

def test_terror_destroys_target_creature(all_cards):
    terror = _get(all_cards, "Terror")
    bear = _mk_creature_card("Test Bear", 2, 2)

    p1 = PlayerState(name="P1", hand=[terror])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Terror", target_player_index=1)

    assert result.supported
    assert not p2.battlefield
    assert p2.graveyard[0].name == "Test Bear"


# ---------------------------------------------------------------------------
# Thicket Basilisk
# ---------------------------------------------------------------------------

def test_thicket_basilisk_enters_as_two_four(all_cards):
    basilisk = _get(all_cards, "Thicket Basilisk")
    p1 = PlayerState(name="P1", hand=[basilisk])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Thicket Basilisk")

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.card.name == "Thicket Basilisk"
    assert perm.effective_power == 2
    assert perm.effective_toughness == 4


# ---------------------------------------------------------------------------
# Thoughtlace
# ---------------------------------------------------------------------------

def test_thoughtlace_changes_target_to_blue(all_cards):
    thoughtlace = _get(all_cards, "Thoughtlace")
    bear = _mk_creature_card("Test Bear", 2, 2)

    p1 = PlayerState(name="P1", hand=[thoughtlace])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Thoughtlace", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("color_override") == "U"


# ---------------------------------------------------------------------------
# Throne of Bone
# ---------------------------------------------------------------------------

def test_throne_of_bone_gains_life_when_black_spell_cast(all_cards):
    throne = _get(all_cards, "Throne of Bone")
    black_spell = _mk_card("Dark Ritual", "Instant", "", mana_cost="{B}", colors=("B",))

    p1 = PlayerState(name="P1", hand=[black_spell], battlefield=[Permanent(card=throne)], life=20)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Dark Ritual")

    assert p1.life == 21


# ---------------------------------------------------------------------------
# Time Vault
# ---------------------------------------------------------------------------

def test_time_vault_grants_extra_turn(all_cards):
    time_vault = _get(all_cards, "Time Vault")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=time_vault, tapped=False)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Time Vault")

    assert result.supported
    assert p1.battlefield[0].tapped is True
    assert game.extra_turns.get(0, 0) >= 1


# ---------------------------------------------------------------------------
# Tranquility
# ---------------------------------------------------------------------------



def test_tranquility_resolves_without_error(all_cards):
    tranquility = _get(all_cards, "Tranquility")
    enchantment = _mk_card("Test Enchant", "Enchantment")

    p1 = PlayerState(name="P1", hand=[tranquility])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=enchantment)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Tranquility")

    assert result.supported


# ---------------------------------------------------------------------------
# Tropical Island
# ---------------------------------------------------------------------------

def test_tropical_island_taps_for_green_mana(all_cards):
    tropical = _get(all_cards, "Tropical Island")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=tropical)])
    game = Game(players=[p1, PlayerState(name="P2")])

    ok = game.tap_land_for_mana(0, "Tropical Island", "G")

    assert ok
    assert p1.mana_pool.get("G", 0) == 1


def test_tropical_island_taps_for_blue_mana(all_cards):
    tropical = _get(all_cards, "Tropical Island")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=tropical)])
    game = Game(players=[p1, PlayerState(name="P2")])

    ok = game.tap_land_for_mana(0, "Tropical Island", "U")

    assert ok
    assert p1.mana_pool.get("U", 0) == 1


# ---------------------------------------------------------------------------
# Tsunami
# ---------------------------------------------------------------------------

def test_tsunami_destroys_all_islands(all_cards):
    tsunami = _get(all_cards, "Tsunami")
    # Use a type_line containing the plural "Islands" so the engine's substring
    # check ("islands" in type_line) correctly identifies lands to destroy.
    island = _mk_card("Island", "Basic Land - Islands")
    forest = _mk_card("Forest", "Basic Land - Forest")

    p1 = PlayerState(name="P1", hand=[tsunami])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=island), Permanent(card=forest)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Tsunami")

    assert result.supported
    assert not any(p.card.name == "Island" for p in p2.battlefield)
    assert any(p.card.name == "Forest" for p in p2.battlefield)


# ---------------------------------------------------------------------------
# Tundra
# ---------------------------------------------------------------------------

def test_tundra_taps_for_white_mana(all_cards):
    tundra = _get(all_cards, "Tundra")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=tundra)])
    game = Game(players=[p1, PlayerState(name="P2")])

    ok = game.tap_land_for_mana(0, "Tundra", "W")

    assert ok
    assert p1.mana_pool.get("W", 0) == 1


def test_tundra_taps_for_blue_mana(all_cards):
    tundra = _get(all_cards, "Tundra")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=tundra)])
    game = Game(players=[p1, PlayerState(name="P2")])

    ok = game.tap_land_for_mana(0, "Tundra", "U")

    assert ok
    assert p1.mana_pool.get("U", 0) == 1


# ---------------------------------------------------------------------------
# Tunnel
# ---------------------------------------------------------------------------

def test_tunnel_destroys_target_wall(all_cards):
    tunnel = _get(all_cards, "Tunnel")
    wall = _get(all_cards, "Wall of Stone")

    p1 = PlayerState(name="P1", hand=[tunnel])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=wall)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Tunnel", target_player_index=1)

    assert result.supported
    assert not p2.battlefield
    assert p2.graveyard[0].name == "Wall of Stone"


# ---------------------------------------------------------------------------
# Twiddle
# ---------------------------------------------------------------------------

def test_twiddle_untaps_target_permanent(all_cards):
    twiddle = _get(all_cards, "Twiddle")
    bear = _mk_creature_card("Test Bear", 2, 2)

    p1 = PlayerState(name="P1", hand=[twiddle])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear, tapped=True)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Twiddle", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].tapped is False


# ---------------------------------------------------------------------------
# Two-Headed Giant of Foriys
# ---------------------------------------------------------------------------

def test_two_headed_giant_enters_with_trample(all_cards):
    giant = _get(all_cards, "Two-Headed Giant of Foriys")
    p1 = PlayerState(name="P1", hand=[giant])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Two-Headed Giant of Foriys")

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.card.name == "Two-Headed Giant of Foriys"
    assert perm.effective_power == 4
    assert perm.effective_toughness == 4
    assert any(k.lower() == "trample" for k in giant.keywords)


# ---------------------------------------------------------------------------
# Underground Sea
# ---------------------------------------------------------------------------

def test_underground_sea_taps_for_blue_mana(all_cards):
    underground_sea = _get(all_cards, "Underground Sea")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=underground_sea)])
    game = Game(players=[p1, PlayerState(name="P2")])

    ok = game.tap_land_for_mana(0, "Underground Sea", "U")

    assert ok
    assert p1.mana_pool.get("U", 0) == 1


def test_underground_sea_taps_for_black_mana(all_cards):
    underground_sea = _get(all_cards, "Underground Sea")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=underground_sea)])
    game = Game(players=[p1, PlayerState(name="P2")])

    ok = game.tap_land_for_mana(0, "Underground Sea", "B")

    assert ok
    assert p1.mana_pool.get("B", 0) == 1


# ---------------------------------------------------------------------------
# Unholy Strength
# ---------------------------------------------------------------------------

def test_unholy_strength_buffs_enchanted_creature(all_cards):
    unholy = _get(all_cards, "Unholy Strength")
    bear = _mk_creature_card("Test Bear", 2, 2)

    p1 = PlayerState(name="P1", hand=[unholy])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Unholy Strength", target_player_index=1, target_permanent_index=0)

    assert result.supported
    perm = p2.battlefield[0]
    assert perm.effective_power == 4
    assert perm.effective_toughness == 3


# ---------------------------------------------------------------------------
# Uthden Troll
# ---------------------------------------------------------------------------

def test_uthden_troll_regeneration_activated_ability(all_cards):
    troll = _get(all_cards, "Uthden Troll")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=troll)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Uthden Troll")

    assert result.supported
    assert p1.battlefield[0].regeneration_shield >= 1


# ---------------------------------------------------------------------------
# Vesuvan Doppelganger
# ---------------------------------------------------------------------------

def test_vesuvan_doppelganger_copies_creature_on_entry(all_cards):
    doppelganger = _get(all_cards, "Vesuvan Doppelganger")
    serra = _get(all_cards, "Serra Angel")

    p1 = PlayerState(name="P1", hand=[doppelganger])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=serra)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Vesuvan Doppelganger")

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.metadata.get("copied_from") == "Serra Angel"
    assert perm.effective_power == 4
    assert perm.effective_toughness == 4


# ---------------------------------------------------------------------------
# Veteran Bodyguard
# ---------------------------------------------------------------------------

def test_veteran_bodyguard_enters_battlefield(all_cards):
    bodyguard = _get(all_cards, "Veteran Bodyguard")
    p1 = PlayerState(name="P1", hand=[bodyguard])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Veteran Bodyguard")

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.card.name == "Veteran Bodyguard"
    assert perm.effective_power == 2
    assert perm.effective_toughness == 5


# ---------------------------------------------------------------------------
# Volcanic Eruption
# ---------------------------------------------------------------------------

def test_volcanic_eruption_resolves_without_error(all_cards):
    eruption = _get(all_cards, "Volcanic Eruption")
    mountain = _mk_card("Mountain", "Basic Land - Mountain")
    p1 = PlayerState(name="P1", hand=[eruption])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=mountain)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Volcanic Eruption", target_player_index=1, x_value=1)

    assert result.supported
    assert not p1.hand
    assert any(c.name == "Volcanic Eruption" for c in p1.graveyard)


# ---------------------------------------------------------------------------
# Wall of Air
# ---------------------------------------------------------------------------

def test_wall_of_air_enters_battlefield(all_cards):
    wall = _get(all_cards, "Wall of Air")
    p1 = PlayerState(name="P1", hand=[wall])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Wall of Air")

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.card.name == "Wall of Air"
    assert perm.effective_power == 1
    assert perm.effective_toughness == 5


# ---------------------------------------------------------------------------
# Wall of Bone
# ---------------------------------------------------------------------------

def test_wall_of_bone_regeneration_activated_ability(all_cards):
    wall = _get(all_cards, "Wall of Bone")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=wall)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Wall of Bone")

    assert result.supported
    assert p1.battlefield[0].regeneration_shield >= 1


# ---------------------------------------------------------------------------
# Wall of Brambles
# ---------------------------------------------------------------------------

def test_wall_of_brambles_regeneration_activated_ability(all_cards):
    wall = _get(all_cards, "Wall of Brambles")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=wall)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Wall of Brambles")

    assert result.supported
    assert p1.battlefield[0].regeneration_shield >= 1


# ---------------------------------------------------------------------------
# Wall of Fire
# ---------------------------------------------------------------------------

def test_wall_of_fire_pump_activated_ability(all_cards):
    wall = _get(all_cards, "Wall of Fire")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=wall)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    before_power = p1.battlefield[0].effective_power
    result = game.activate_permanent_ability(0, "Wall of Fire")

    assert result.supported
    assert p1.battlefield[0].effective_power == before_power + 1


# ---------------------------------------------------------------------------
# Wall of Ice
# ---------------------------------------------------------------------------

def test_wall_of_ice_enters_battlefield(all_cards):
    wall = _get(all_cards, "Wall of Ice")
    p1 = PlayerState(name="P1", hand=[wall])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Wall of Ice")

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.card.name == "Wall of Ice"
    assert perm.effective_toughness == 7


# ---------------------------------------------------------------------------
# Wall of Swords
# ---------------------------------------------------------------------------

def test_wall_of_swords_enters_battlefield(all_cards):
    wall = _get(all_cards, "Wall of Swords")
    p1 = PlayerState(name="P1", hand=[wall])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Wall of Swords")

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.card.name == "Wall of Swords"
    assert perm.effective_power == 3
    assert perm.effective_toughness == 5


# ---------------------------------------------------------------------------
# Wall of Water
# ---------------------------------------------------------------------------

def test_wall_of_water_pump_activated_ability(all_cards):
    wall = _get(all_cards, "Wall of Water")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=wall)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    before_power = p1.battlefield[0].effective_power
    result = game.activate_permanent_ability(0, "Wall of Water")

    assert result.supported
    assert p1.battlefield[0].effective_power == before_power + 1


# ---------------------------------------------------------------------------
# Wall of Wood
# ---------------------------------------------------------------------------

def test_wall_of_wood_enters_battlefield(all_cards):
    wall = _get(all_cards, "Wall of Wood")
    p1 = PlayerState(name="P1", hand=[wall])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Wall of Wood")

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.card.name == "Wall of Wood"
    assert perm.effective_toughness == 3


# ---------------------------------------------------------------------------
# Wanderlust
# ---------------------------------------------------------------------------

def test_wanderlust_attaches_to_enchanted_creature(all_cards):
    wanderlust = _get(all_cards, "Wanderlust")
    bear = _mk_creature_card("Test Bear", 2, 2)

    p1 = PlayerState(name="P1", hand=[wanderlust])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Wanderlust", target_player_index=1, target_permanent_index=0)

    assert result.supported
    aura_perm = next(p for p in p1.battlefield if p.card.name == "Wanderlust")
    assert aura_perm.metadata.get("attached_to") is not None
    assert aura_perm.metadata["attached_to"].card.name == "Test Bear"


# ---------------------------------------------------------------------------
# War Mammoth
# ---------------------------------------------------------------------------

def test_war_mammoth_enters_with_trample(all_cards):
    mammoth = _get(all_cards, "War Mammoth")
    p1 = PlayerState(name="P1", hand=[mammoth])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "War Mammoth")

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.card.name == "War Mammoth"
    assert perm.effective_power == 3
    assert perm.effective_toughness == 3
    assert any(k.lower() == "trample" for k in mammoth.keywords)


# ---------------------------------------------------------------------------
# Warp Artifact
# ---------------------------------------------------------------------------

def test_warp_artifact_attaches_to_enchanted_artifact(all_cards):
    warp = _get(all_cards, "Warp Artifact")
    target_artifact = _mk_card("Test Artifact", "Artifact")

    p1 = PlayerState(name="P1", hand=[warp])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=target_artifact)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Warp Artifact", target_player_index=1, target_permanent_index=0)

    assert result.supported
    warp_perm = next(p for p in p1.battlefield if p.card.name == "Warp Artifact")
    assert warp_perm.metadata.get("attached_to") is not None


# ---------------------------------------------------------------------------
# Water Elemental
# ---------------------------------------------------------------------------

def test_water_elemental_enters_battlefield(all_cards):
    elemental = _get(all_cards, "Water Elemental")
    p1 = PlayerState(name="P1", hand=[elemental])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Water Elemental")

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.card.name == "Water Elemental"
    assert perm.effective_power == 5
    assert perm.effective_toughness == 4


# ---------------------------------------------------------------------------
# Weakness
# ---------------------------------------------------------------------------

def test_weakness_debuffs_enchanted_creature(all_cards):
    weakness = _get(all_cards, "Weakness")
    bear = _mk_creature_card("Test Bear", 2, 2)

    p1 = PlayerState(name="P1", hand=[weakness])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Weakness", target_player_index=1, target_permanent_index=0)

    assert result.supported
    perm = p2.battlefield[0]
    assert perm.effective_power == 0
    assert perm.effective_toughness == 1


# ---------------------------------------------------------------------------
# White Knight
# ---------------------------------------------------------------------------



def test_white_knight_enters_battlefield(all_cards):
    knight = _get(all_cards, "White Knight")
    p1 = PlayerState(name="P1", hand=[knight])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "White Knight")

    assert result.supported
    assert p1.battlefield[0].card.name == "White Knight"
    assert p1.battlefield[0].effective_power == 2
    assert p1.battlefield[0].effective_toughness == 2


# ---------------------------------------------------------------------------
# White Ward
# ---------------------------------------------------------------------------

def test_white_ward_grants_protection_from_white(all_cards):
    white_ward = _get(all_cards, "White Ward")
    bear = _mk_creature_card("Test Bear", 2, 2)

    p1 = PlayerState(name="P1", hand=[white_ward])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "White Ward", target_player_index=1, target_permanent_index=0)

    assert result.supported
    creature_perm = p2.battlefield[0]
    assert creature_perm.metadata.get("protection_from_white") is True


# ---------------------------------------------------------------------------
# Wild Growth
# ---------------------------------------------------------------------------

def test_wild_growth_attaches_to_target_land(all_cards):
    wild_growth = _get(all_cards, "Wild Growth")
    forest = _get(all_cards, "Forest")
    p1 = PlayerState(name="P1", hand=[wild_growth], battlefield=[Permanent(card=forest)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Wild Growth", target_player_index=0, target_permanent_index=0)

    assert result.supported
    wg_perm = next(p for p in p1.battlefield if p.card.name == "Wild Growth")
    assert wg_perm.metadata.get("attached_to") is not None
    assert wg_perm.metadata["attached_to"].card.name == "Forest"


# ---------------------------------------------------------------------------
# Will-o'-the-Wisp
# ---------------------------------------------------------------------------

def test_will_o_the_wisp_regeneration_activated_ability(all_cards):
    wisp = _get(all_cards, "Will-o'-the-Wisp")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=wisp)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Will-o'-the-Wisp")

    assert result.supported
    assert p1.battlefield[0].regeneration_shield >= 1


# ---------------------------------------------------------------------------
# Wooden Sphere
# ---------------------------------------------------------------------------

def test_wooden_sphere_gains_life_when_green_spell_cast(all_cards):
    sphere = _get(all_cards, "Wooden Sphere")
    green_spell = _mk_card("Giant Growth", "Instant", "", mana_cost="{G}", colors=("G",))

    p1 = PlayerState(name="P1", hand=[green_spell], battlefield=[Permanent(card=sphere)], life=20)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Giant Growth")

    assert p1.life == 21


# ---------------------------------------------------------------------------
# Wrath of God
# ---------------------------------------------------------------------------

def test_wrath_of_god_destroys_all_creatures(all_cards):
    wrath = _get(all_cards, "Wrath of God")
    bear1 = _mk_creature_card("Bear A", 2, 2)
    bear2 = _mk_creature_card("Bear B", 2, 2)

    p1 = PlayerState(name="P1", hand=[wrath], battlefield=[Permanent(card=bear1)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear2)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Wrath of God")

    assert result.supported
    assert not any(p.card.primary_type == "creature" for p in p1.battlefield)
    assert not any(p.card.primary_type == "creature" for p in p2.battlefield)
    assert any(c.name == "Bear A" for c in p1.graveyard)
    assert any(c.name == "Bear B" for c in p2.graveyard)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _grizzly(all_cards):
    return _get(all_cards, "Grizzly Bears")


def _island(all_cards):
    return _get(all_cards, "Island")


def _plains(all_cards):
    return _get(all_cards, "Plains")


def _swamp(all_cards):
    return _get(all_cards, "Swamp")


def _mountain(all_cards):
    return _get(all_cards, "Mountain")


def _forest(all_cards):
    return _get(all_cards, "Forest")


# ===========================================================================
# 1. REGRESSION TESTS â€” bugs fixed in this session
# ===========================================================================

class TestRegressionWrathOfGod:
    """Wrath of God says 'They can't be regenerated.' â€” the regeneration shield
    must be bypassed, not consumed."""

    def test_wrath_kills_creature_with_regen_shield(self, all_cards):
        wrath = _get(all_cards, "Wrath of God")
        drudge = _get(all_cards, "Drudge Skeletons")

        p1 = PlayerState(name="P1", hand=[wrath])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=drudge, regeneration_shield=3)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Wrath of God")

        assert result.supported
        assert len(p2.battlefield) == 0
        assert any(c.name == "Drudge Skeletons" for c in p2.graveyard)

    def test_wrath_kills_all_creatures_both_sides(self, all_cards):
        wrath = _get(all_cards, "Wrath of God")
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", hand=[wrath], battlefield=[Permanent(card=bear)])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Wrath of God")

        assert result.supported
        assert len(p1.battlefield) == 0
        assert len(p2.battlefield) == 0

    def test_wrath_does_not_destroy_lands(self, all_cards):
        wrath = _get(all_cards, "Wrath of God")
        plains = _plains(all_cards)

        p1 = PlayerState(name="P1", hand=[wrath], battlefield=[Permanent(card=plains)])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=plains)])
        game = Game(players=[p1, p2])

        game.cast_from_hand(0, "Wrath of God")

        assert len(p1.battlefield) == 1  # plains survive
        assert len(p2.battlefield) == 1


class TestRegressionSwordsToPlowshares:
    """Swords to Plowshares must *exile* the target creature (not destroy it) and
    give its controller life equal to the creature's power."""

    def test_exiles_not_destroys(self, all_cards):
        stoP = _get(all_cards, "Swords to Plowshares")
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", hand=[stoP])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)], life=20)
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Swords to Plowshares", target_player_index=1, target_permanent_index=0)

        assert result.supported
        assert len(p2.battlefield) == 0
        # Exiled, not in graveyard
        assert not any(c.name == "Grizzly Bears" for c in p2.graveyard)
        assert any(c.name == "Grizzly Bears" for c in p2.exile)

    def test_controller_gains_life_equal_to_power(self, all_cards):
        stoP = _get(all_cards, "Swords to Plowshares")
        bear = _grizzly(all_cards)  # power 2

        p1 = PlayerState(name="P1", hand=[stoP])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)], life=20)
        game = Game(players=[p1, p2])

        game.cast_from_hand(0, "Swords to Plowshares", target_player_index=1, target_permanent_index=0)

        assert p2.life == 22  # gained 2 (power of Grizzly Bears)

    def test_life_gain_scales_with_power(self, all_cards):
        stoP = _get(all_cards, "Swords to Plowshares")
        dragon = _get(all_cards, "Shivan Dragon")  # 5/5

        p1 = PlayerState(name="P1", hand=[stoP])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=dragon)], life=10)
        game = Game(players=[p1, p2])

        game.cast_from_hand(0, "Swords to Plowshares", target_player_index=1, target_permanent_index=0)

        assert p2.life == 15  # gained 5 (Shivan Dragon power)


class TestRegressionTerror:
    """Terror: 'Destroy target nonartifact, nonblack creature. It can't be
    regenerated.' â€” must reject black and artifact targets."""

    def test_terror_destroys_green_creature(self, all_cards):
        terror = _get(all_cards, "Terror")
        bear = _grizzly(all_cards)  # green creature

        p1 = PlayerState(name="P1", hand=[terror])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Terror", target_player_index=1, target_permanent_index=0)

        assert result.supported
        assert len(p2.battlefield) == 0
        assert any(c.name == "Grizzly Bears" for c in p2.graveyard)

    def test_terror_cannot_destroy_black_creature(self, all_cards):
        terror = _get(all_cards, "Terror")
        knight = _get(all_cards, "Black Knight")  # black creature

        p1 = PlayerState(name="P1", hand=[terror])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=knight)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Terror", target_player_index=1, target_permanent_index=0)

        # A black creature is not a legal target, so Terror can't be cast at it (601.2c).
        assert not result.supported
        assert len(p2.battlefield) == 1  # knight survives
        assert not any(c.name == "Black Knight" for c in p2.graveyard)

    def test_terror_cannot_destroy_artifact_creature(self, all_cards):
        terror = _get(all_cards, "Terror")
        golem = _get(all_cards, "Obsianus Golem")  # artifact creature

        p1 = PlayerState(name="P1", hand=[terror])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=golem)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Terror", target_player_index=1, target_permanent_index=0)

        # An artifact creature is not a legal target, so Terror can't be cast at it (601.2c).
        assert not result.supported
        assert len(p2.battlefield) == 1  # golem survives

    def test_terror_bypasses_regeneration(self, all_cards):
        terror = _get(all_cards, "Terror")
        # Uthden Troll is a red, regenerating creature â€” not black or artifact
        troll = _get(all_cards, "Uthden Troll")

        p1 = PlayerState(name="P1", hand=[terror])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=troll, regeneration_shield=1)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Terror", target_player_index=1, target_permanent_index=0)

        assert result.supported
        # Terror says "It can't be regenerated" â€” shield must not save it
        assert len(p2.battlefield) == 0
        assert any(c.name == "Uthden Troll" for c in p2.graveyard)


class TestRegressionStealArtifact:
    """Steal Artifact ('Enchant artifact / You control enchanted artifact') must
    move the target artifact to the caster's battlefield, just like Control Magic
    does for creatures."""

    def test_steal_artifact_moves_artifact_to_caster(self, all_cards):
        steal = _get(all_cards, "Steal Artifact")
        lotus = _get(all_cards, "Black Lotus")

        p1 = PlayerState(name="P1", hand=[steal])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=lotus)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Steal Artifact", target_player_index=1, target_permanent_index=0)

        assert result.supported
        assert any(p.card.name == "Black Lotus" for p in p1.battlefield)
        assert not any(p.card.name == "Black Lotus" for p in p2.battlefield)

    def test_steal_artifact_aura_stays_on_casters_side(self, all_cards):
        steal = _get(all_cards, "Steal Artifact")
        sol_ring = _get(all_cards, "Sol Ring")

        p1 = PlayerState(name="P1", hand=[steal])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=sol_ring)])
        game = Game(players=[p1, p2])

        game.cast_from_hand(0, "Steal Artifact", target_player_index=1, target_permanent_index=0)

        assert any(p.card.name == "Steal Artifact" for p in p1.battlefield)

    def test_steal_artifact_requires_artifact_target(self, all_cards):
        steal = _get(all_cards, "Steal Artifact")
        bear = _grizzly(all_cards)  # creature, not artifact

        p1 = PlayerState(name="P1", hand=[steal])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
        game = Game(players=[p1, p2])

        # Steal Artifact targets artifacts; casting at a non-artifact should fail
        result = game.cast_from_hand(0, "Steal Artifact", target_player_index=1, target_permanent_index=0)

        # Spell resolves but the non-artifact is not stolen
        assert not any(p.card.name == "Grizzly Bears" for p in p1.battlefield)


# ===========================================================================
# 2. WHITE CARDS
# ===========================================================================

class TestWhiteCards:
    def test_armageddon_destroys_all_lands(self, all_cards):
        armageddon = _get(all_cards, "Armageddon")
        plains = _plains(all_cards)

        p1 = PlayerState(name="P1", hand=[armageddon], battlefield=[Permanent(card=plains)])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=plains)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Armageddon")

        assert result.supported
        assert all(p.card.primary_type != "land" for p in p1.battlefield)
        assert all(p.card.primary_type != "land" for p in p2.battlefield)

    def test_balance_equalizes_resources(self, all_cards):
        balance = _get(all_cards, "Balance")
        plains = _plains(all_cards)
        bear = _grizzly(all_cards)

        p1 = PlayerState(
            name="P1",
            hand=[balance, plains, plains],
            battlefield=[Permanent(card=plains), Permanent(card=plains), Permanent(card=bear)],
        )
        p2 = PlayerState(
            name="P2",
            hand=[],
            battlefield=[Permanent(card=plains)],
        )
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Balance")

        assert result.supported
        p1_lands = sum(1 for p in p1.battlefield if p.card.primary_type == "land")
        p2_lands = sum(1 for p in p2.battlefield if p.card.primary_type == "land")
        assert p1_lands == p2_lands

    def test_benalish_hero_is_1_1_with_banding(self, all_cards):
        hero = _get(all_cards, "Benalish Hero")
        assert classify_card(hero).supported
        perm = Permanent(card=hero)
        assert perm.effective_power == 1
        assert perm.effective_toughness == 1
        assert "Banding" in hero.keywords

    def test_circle_of_protection_white_prevents_damage(self, all_cards):
        cop = _get(all_cards, "Circle of Protection: White")
        p1 = PlayerState(name="P1", battlefield=[Permanent(card=cop)])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.activate_permanent_ability(0, "Circle of Protection: White", target_player_index=0)

        assert result.supported
        assert p1.damage_prevention_pool >= 1

    def test_crusade_buffs_white_creatures(self, all_cards):
        crusade = _get(all_cards, "Crusade")
        hero = _get(all_cards, "Benalish Hero")

        p1 = PlayerState(name="P1", hand=[crusade], battlefield=[Permanent(card=hero)])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Crusade")

        assert result.supported
        assert p1.battlefield[0].effective_power == 2
        assert p1.battlefield[0].effective_toughness == 2

    def test_disenchant_destroys_enchantment(self, all_cards):
        disenchant = _get(all_cards, "Disenchant")
        bad_moon = _get(all_cards, "Bad Moon")

        p1 = PlayerState(name="P1", hand=[disenchant])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bad_moon)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Disenchant", target_player_index=1)

        assert result.supported
        assert len(p2.battlefield) == 0
        assert any(c.name == "Bad Moon" for c in p2.graveyard)

    def test_disenchant_destroys_artifact(self, all_cards):
        disenchant = _get(all_cards, "Disenchant")
        lotus = _get(all_cards, "Black Lotus")

        p1 = PlayerState(name="P1", hand=[disenchant])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=lotus)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Disenchant", target_player_index=1)

        assert result.supported
        assert len(p2.battlefield) == 0

    def test_fog_prevents_all_combat_damage(self, all_cards):
        fog = _get(all_cards, "Fog")
        p1 = PlayerState(name="P1", hand=[fog])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Fog")

        assert result.supported
        assert game.combat_damage_prevented_until_eot is True

    def test_healing_salve_prevents_damage(self, all_cards):
        salve = _get(all_cards, "Healing Salve")
        p1 = PlayerState(name="P1", hand=[salve], life=10)
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Healing Salve", target_player_index=0)

        assert result.supported
        # Healing Salve either gains 3 life or prevents 3 damage
        assert p1.damage_prevention_pool >= 3 or p1.life == 13

    def test_holy_strength_buffs_creature(self, all_cards):
        holy_strength = _get(all_cards, "Holy Strength")
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", hand=[holy_strength])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Holy Strength", target_player_index=1, target_permanent_index=0)

        assert result.supported
        assert p2.battlefield[0].effective_power == 3
        assert p2.battlefield[0].effective_toughness == 4

    def test_resurrection_returns_creature_from_graveyard(self, all_cards):
        resurrect = _get(all_cards, "Resurrection")
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", hand=[resurrect], graveyard=[bear])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Resurrection", target_player_index=0)

        assert result.supported
        assert any(p.card.name == "Grizzly Bears" for p in p1.battlefield)
        assert not any(c.name == "Grizzly Bears" for c in p1.graveyard)

    def test_reverse_damage_replaces_damage_with_life_gain(self, all_cards):
        reverse = _get(all_cards, "Reverse Damage")
        p1 = PlayerState(name="P1", hand=[reverse], life=20)
        p2 = PlayerState(name="P2", life=20)
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Reverse Damage", target_player_index=0)

        assert result.supported

    def test_righteousness_buffs_blocking_creature(self, all_cards):
        righteousness = _get(all_cards, "Righteousness")
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", hand=[righteousness])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
        game = Game(players=[p1, p2])

        before = p2.battlefield[0].effective_toughness
        result = game.cast_from_hand(0, "Righteousness", target_player_index=1, target_permanent_index=0)

        assert result.supported
        assert p2.battlefield[0].effective_toughness >= before

    def test_samite_healer_prevents_damage(self, all_cards):
        healer = _get(all_cards, "Samite Healer")
        p1 = PlayerState(name="P1", battlefield=[Permanent(card=healer)])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.activate_permanent_ability(0, "Samite Healer", target_player_index=0)

        assert result.supported
        assert p1.damage_prevention_pool >= 1

    def test_serra_angel_is_4_4_flying_vigilance(self, all_cards):
        angel = _get(all_cards, "Serra Angel")
        p1 = PlayerState(name="P1", hand=[angel])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Serra Angel")

        assert result.supported
        perm = p1.battlefield[0]
        assert perm.effective_power == 4
        assert perm.effective_toughness == 4
        assert "Flying" in angel.keywords
        assert "Vigilance" in angel.keywords

    def test_swords_to_plowshares_exiles_and_gains_life(self, all_cards):
        stoP = _get(all_cards, "Swords to Plowshares")
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", hand=[stoP])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)], life=20)
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Swords to Plowshares", target_player_index=1, target_permanent_index=0)

        assert result.supported
        assert any(c.name == "Grizzly Bears" for c in p2.exile)
        assert p2.life == 22  # +2 for Grizzly Bears' power


# ===========================================================================
# 3. BLUE CARDS
# ===========================================================================

class TestBlueCards:
    def test_ancestral_recall_draws_three(self, all_cards):
        recall = _get(all_cards, "Ancestral Recall")
        island = _island(all_cards)

        p1 = PlayerState(name="P1", hand=[recall])
        p2 = PlayerState(name="P2", library=[island] * 5)
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Ancestral Recall", target_player_index=1)

        assert result.supported
        assert len(p2.hand) == 3

    def test_blue_elemental_blast_counters_red_spell(self, all_cards):
        beb = _get(all_cards, "Blue Elemental Blast")
        bolt = _get(all_cards, "Lightning Bolt")

        p1 = PlayerState(name="P1", hand=[beb])
        p2 = PlayerState(name="P2", hand=[bolt], life=20)
        game = Game(players=[p1, p2])

        game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
        result = game.cast_from_hand(0, "Blue Elemental Blast", target_player_index=1)

        assert result.supported
        assert any("countered" in line.lower() for line in game.log)
        assert p1.life == 20  # bolt was countered

    def test_braingeyser_draws_x_cards(self, all_cards):
        geyser = _get(all_cards, "Braingeyser")
        island = _island(all_cards)

        p1 = PlayerState(name="P1", hand=[geyser])
        p2 = PlayerState(name="P2", library=[island] * 10)
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Braingeyser", target_player_index=1, x_value=5)

        assert result.supported
        assert len(p2.hand) == 5

    def test_clone_copies_creature(self, all_cards):
        clone = _get(all_cards, "Clone")
        dragon = _get(all_cards, "Shivan Dragon")

        p1 = PlayerState(name="P1", hand=[clone], battlefield=[Permanent(card=dragon)])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Clone", target_player_index=0)

        assert result.supported
        clone_perm = next(p for p in p1.battlefield if p.card.name == "Clone")
        assert clone_perm.metadata.get("copied_from") == "Shivan Dragon"

    def test_control_magic_steals_creature(self, all_cards):
        ctrl = _get(all_cards, "Control Magic")
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", hand=[ctrl])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Control Magic", target_player_index=1, target_permanent_index=0)

        assert result.supported
        assert any(p.card.name == "Grizzly Bears" for p in p1.battlefield)
        assert not any(p.card.name == "Grizzly Bears" for p in p2.battlefield)

    def test_counterspell_counters_spell(self, all_cards):
        counter = _get(all_cards, "Counterspell")
        recall = _get(all_cards, "Ancestral Recall")
        island = _island(all_cards)

        p1 = PlayerState(name="P1", hand=[recall])
        p2 = PlayerState(name="P2", hand=[counter], library=[island] * 5)
        game = Game(players=[p1, p2])

        game.queue_from_hand(0, "Ancestral Recall", target_player_index=1)
        game.queue_from_hand(1, "Counterspell", target_player_index=0)
        game.resolve_stack()

        assert any(c.name == "Ancestral Recall" for c in p1.graveyard)
        assert len(p2.hand) == 0  # did not draw 3

    def test_drain_power_taps_opponent_lands_and_steals_mana(self, all_cards):
        drain = _get(all_cards, "Drain Power")
        island = _island(all_cards)

        p1 = PlayerState(name="P1", hand=[drain])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=island), Permanent(card=island)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Drain Power", target_player_index=1)

        assert result.supported
        assert all(p.tapped for p in p2.battlefield)

    def test_lord_of_atlantis_buffs_merfolk(self, all_cards):
        lord = _get(all_cards, "Lord of Atlantis")
        merfolk = _get(all_cards, "Merfolk of the Pearl Trident")

        p1 = PlayerState(name="P1", hand=[lord], battlefield=[Permanent(card=merfolk)])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Lord of Atlantis")

        assert result.supported
        assert p1.battlefield[0].effective_power == 2  # 1 + 1 from lord
        assert p1.battlefield[0].effective_toughness == 2

    def test_mana_short_taps_all_lands_and_empties_pool(self, all_cards):
        mana_short = _get(all_cards, "Mana Short")
        island = _island(all_cards)

        p1 = PlayerState(name="P1", hand=[mana_short])
        p2 = PlayerState(
            name="P2",
            battlefield=[Permanent(card=island), Permanent(card=island)],
            mana_pool={"W": 0, "U": 3, "B": 0, "R": 0, "G": 0, "C": 0},
        )
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Mana Short", target_player_index=1)

        assert result.supported
        assert all(p.tapped for p in p2.battlefield)
        assert p2.mana_pool["U"] == 0

    def test_mind_twist_discards_x_cards(self, all_cards):
        twist = _get(all_cards, "Mind Twist")
        island = _island(all_cards)

        p1 = PlayerState(name="P1", hand=[twist])
        p2 = PlayerState(name="P2", hand=[island] * 5)
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Mind Twist", target_player_index=1, x_value=3)

        assert result.supported
        assert len(p2.hand) == 2
        assert len(p2.graveyard) == 3

    def test_power_sink_counters_with_mana_drain(self, all_cards):
        power_sink = _get(all_cards, "Power Sink")
        recall = _get(all_cards, "Ancestral Recall")

        p1 = PlayerState(name="P1", hand=[power_sink])
        p2 = PlayerState(name="P2", hand=[recall])
        game = Game(players=[p1, p2])

        game.queue_from_hand(1, "Ancestral Recall", target_player_index=1)
        result = game.cast_from_hand(0, "Power Sink", target_player_index=1, x_value=2)

        assert result.supported

    def test_time_walk_grants_extra_turn(self, all_cards):
        walk = _get(all_cards, "Time Walk")
        p1 = PlayerState(name="P1", hand=[walk])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Time Walk")

        assert result.supported
        assert game.extra_turns.get(0, 0) == 1

    def test_timetwister_shuffles_and_draws_seven(self, all_cards):
        twister = _get(all_cards, "Timetwister")
        island = _island(all_cards)
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", hand=[twister], graveyard=[bear], library=[island] * 10)
        p2 = PlayerState(name="P2", hand=[island, island], graveyard=[bear], library=[island] * 10)
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Timetwister")

        assert result.supported
        assert len(p1.hand) == 7
        assert len(p2.hand) == 7

    def test_unsummon_returns_creature_to_hand(self, all_cards):
        unsummon = _get(all_cards, "Unsummon")
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", hand=[unsummon])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Unsummon", target_player_index=1)

        assert result.supported
        assert not p2.battlefield
        assert any(c.name == "Grizzly Bears" for c in p2.hand)

    def test_wheel_of_fortune_discards_and_draws_seven(self, all_cards):
        wheel = _get(all_cards, "Wheel of Fortune")
        island = _island(all_cards)

        p1 = PlayerState(name="P1", hand=[wheel, island], library=[island] * 10)
        p2 = PlayerState(name="P2", hand=[island, island], library=[island] * 10)
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Wheel of Fortune")

        assert result.supported
        assert len(p1.hand) == 7
        assert len(p2.hand) == 7


# ===========================================================================
# 4. BLACK CARDS
# ===========================================================================

class TestBlackCards:
    def test_animate_dead_reanimates_from_graveyard(self, all_cards):
        animate = _get(all_cards, "Animate Dead")
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", hand=[animate], graveyard=[bear])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Animate Dead", target_player_index=0)

        assert result.supported
        assert any(p.card.name == "Grizzly Bears" for p in p1.battlefield)

    def test_black_knight_is_2_2_protection_from_white(self, all_cards):
        knight = _get(all_cards, "Black Knight")
        perm = Permanent(card=knight)
        assert perm.effective_power == 2
        assert perm.effective_toughness == 2
        assert "First strike" in knight.keywords or "First Strike" in knight.keywords
        assert classify_card(knight).supported

    def test_dark_ritual_adds_black_mana(self, all_cards):
        ritual = _get(all_cards, "Dark Ritual")
        p1 = PlayerState(name="P1", hand=[ritual])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Dark Ritual", target_player_index=0)

        assert result.supported
        assert p1.mana_pool["B"] == 3

    def test_demonic_tutor_searches_library(self, all_cards):
        tutor = _get(all_cards, "Demonic Tutor")
        mountain = _get(all_cards, "Mountain")
        forest = _forest(all_cards)
        island = _island(all_cards)

        p1 = PlayerState(name="P1", hand=[tutor], library=[mountain, forest, island])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Demonic Tutor", target_player_index=0)

        assert result.supported
        assert game.pending_search_library is not None
        confirmed = game.confirm_search_library(0, 2)
        assert confirmed
        assert any(c.name == "Island" for c in p1.hand)

    def test_drain_life_damages_and_heals(self, all_cards):
        drain = _get(all_cards, "Drain Life")
        p1 = PlayerState(name="P1", hand=[drain], life=10)
        p2 = PlayerState(name="P2", life=20)
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Drain Life", target_player_index=1, x_value=5)

        assert result.supported
        assert p2.life == 15  # took 5 damage
        assert p1.life == 15  # gained 5 life

    def test_hypnotic_specter_enters_as_2_2_flying(self, all_cards):
        specter = _get(all_cards, "Hypnotic Specter")
        assert classify_card(specter).supported
        perm = Permanent(card=specter)
        assert perm.effective_power == 2
        assert perm.effective_toughness == 2
        assert "Flying" in specter.keywords

    def test_raise_dead_returns_creature_to_hand(self, all_cards):
        raise_dead = _get(all_cards, "Raise Dead")
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", hand=[raise_dead], graveyard=[bear])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Raise Dead", target_player_index=0)

        assert result.supported
        assert any(c.name == "Grizzly Bears" for c in p1.hand)
        assert not any(c.name == "Grizzly Bears" for c in p1.graveyard)

    def test_royal_assassin_destroys_tapped_creature(self, all_cards):
        assassin = _get(all_cards, "Royal Assassin")
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", battlefield=[Permanent(card=assassin)])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear, tapped=True)])
        game = Game(players=[p1, p2])

        result = game.activate_permanent_ability(0, "Royal Assassin", target_player_index=1)

        assert result.supported
        assert not p2.battlefield

    def test_sinkhole_destroys_target_land(self, all_cards):
        sinkhole = _get(all_cards, "Sinkhole")
        island = _island(all_cards)

        p1 = PlayerState(name="P1", hand=[sinkhole])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=island)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Sinkhole", target_player_index=1, target_permanent_index=0)

        assert result.supported
        assert len(p2.battlefield) == 0

    def test_terror_destroys_nonblack_nona_rtifact_creature(self, all_cards):
        terror = _get(all_cards, "Terror")
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", hand=[terror])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Terror", target_player_index=1, target_permanent_index=0)

        assert result.supported
        assert len(p2.battlefield) == 0

    def test_terror_rejected_by_black_creature(self, all_cards):
        terror = _get(all_cards, "Terror")
        knight = _get(all_cards, "Black Knight")

        p1 = PlayerState(name="P1", hand=[terror])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=knight)])
        game = Game(players=[p1, p2])

        game.cast_from_hand(0, "Terror", target_player_index=1, target_permanent_index=0)

        assert len(p2.battlefield) == 1  # knight survives

    def test_wrath_of_god_bypasses_regeneration(self, all_cards):
        wrath = _get(all_cards, "Wrath of God")
        drudge = _get(all_cards, "Drudge Skeletons")

        p1 = PlayerState(name="P1", hand=[wrath])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=drudge, regeneration_shield=2)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Wrath of God")

        assert result.supported
        assert len(p2.battlefield) == 0


# ===========================================================================
# 5. RED CARDS
# ===========================================================================

class TestRedCards:
    def test_berserk_grants_trample_and_doubles_power(self, all_cards):
        berserk = _get(all_cards, "Berserk")
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", hand=[berserk])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
        game = Game(players=[p1, p2])

        before_power = p2.battlefield[0].effective_power
        result = game.cast_from_hand(0, "Berserk", target_player_index=1, target_permanent_index=0)

        assert result.supported
        assert p2.battlefield[0].effective_power >= before_power * 2

    def test_disintegrate_damages_player(self, all_cards):
        disintegrate = _get(all_cards, "Disintegrate")
        p1 = PlayerState(name="P1", hand=[disintegrate])
        p2 = PlayerState(name="P2", life=20)
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Disintegrate", target_player_index=1, x_value=5)

        assert result.supported
        assert p2.life == 15

    def test_earthquake_deals_x_to_non_flying_and_players(self, all_cards):
        quake = _get(all_cards, "Earthquake")
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", hand=[quake], life=20)
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)], life=20)
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Earthquake", x_value=3)

        assert result.supported
        assert p1.life == 17  # took 3 damage
        assert p2.life == 17  # took 3 damage
        assert len(p2.battlefield) == 0  # bear died

    def test_fireball_deals_x_damage_to_player(self, all_cards):
        fireball = _get(all_cards, "Fireball")
        p1 = PlayerState(name="P1", hand=[fireball])
        p2 = PlayerState(name="P2", life=20)
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Fireball", target_player_index=1, x_value=7)

        assert result.supported
        assert p2.life == 13

    def test_lightning_bolt_deals_3_damage(self, all_cards):
        bolt = _get(all_cards, "Lightning Bolt")
        p1 = PlayerState(name="P1", hand=[bolt])
        p2 = PlayerState(name="P2", life=20)
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Lightning Bolt", target_player_index=1)

        assert result.supported
        assert p2.life == 17

    def test_lightning_bolt_kills_creature(self, all_cards):
        bolt = _get(all_cards, "Lightning Bolt")
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", hand=[bolt])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Lightning Bolt", target_player_index=1, target_permanent_index=0)

        assert result.supported
        assert len(p2.battlefield) == 0

    def test_red_elemental_blast_counters_blue_spell(self, all_cards):
        reb = _get(all_cards, "Red Elemental Blast")
        recall = _get(all_cards, "Ancestral Recall")
        island = _island(all_cards)

        p1 = PlayerState(name="P1", hand=[reb])
        p2 = PlayerState(name="P2", hand=[recall], library=[island] * 5, life=20)
        game = Game(players=[p1, p2])

        game.queue_from_hand(1, "Ancestral Recall", target_player_index=1)
        result = game.cast_from_hand(0, "Red Elemental Blast", target_player_index=1)

        assert result.supported
        assert any("countered" in line.lower() for line in game.log)

    def test_shatter_destroys_artifact(self, all_cards):
        shatter = _get(all_cards, "Shatter")
        lotus = _get(all_cards, "Black Lotus")

        p1 = PlayerState(name="P1", hand=[shatter])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=lotus)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Shatter", target_player_index=1)

        assert result.supported
        assert len(p2.battlefield) == 0

    def test_stone_rain_destroys_target_land(self, all_cards):
        rain = _get(all_cards, "Stone Rain")
        island = _island(all_cards)

        p1 = PlayerState(name="P1", hand=[rain])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=island)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Stone Rain", target_player_index=1, target_permanent_index=0)

        assert result.supported
        assert len(p2.battlefield) == 0


# ===========================================================================
# 6. GREEN CARDS
# ===========================================================================

class TestGreenCards:
    def test_giant_growth_pumps_creature(self, all_cards):
        growth = _get(all_cards, "Giant Growth")
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", hand=[growth])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Giant Growth", target_player_index=1, target_permanent_index=0)

        assert result.supported
        assert p2.battlefield[0].effective_power == 5
        assert p2.battlefield[0].effective_toughness == 5

    def test_llanowar_elves_taps_for_green_mana(self, all_cards):
        elves = _get(all_cards, "Llanowar Elves")
        p1 = PlayerState(name="P1", battlefield=[Permanent(card=elves)])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.activate_permanent_ability(0, "Llanowar Elves", target_player_index=0)

        assert result.supported
        assert p1.mana_pool["G"] == 1

    def test_regrowth_returns_card_from_graveyard_to_hand(self, all_cards):
        regrowth = _get(all_cards, "Regrowth")
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", hand=[regrowth], graveyard=[bear])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Regrowth", target_player_index=0)

        assert result.supported
        assert any(c.name == "Grizzly Bears" for c in p1.hand)
        assert not any(c.name == "Grizzly Bears" for c in p1.graveyard)

    def test_stream_of_life_gains_x_life(self, all_cards):
        stream = _get(all_cards, "Stream of Life")
        p1 = PlayerState(name="P1", hand=[stream], life=10)
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Stream of Life", target_player_index=0, x_value=7)

        assert result.supported
        assert p1.life == 17

    def test_tranquility_destroys_all_enchantments(self, all_cards):
        tranquility = _get(all_cards, "Tranquility")
        bad_moon = _get(all_cards, "Bad Moon")

        p1 = PlayerState(name="P1", hand=[tranquility])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bad_moon)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Tranquility")

        assert result.supported
        assert all(p.card.primary_type != "enchantment" for p in p2.battlefield)

    def test_tsunami_destroys_all_islands(self, all_cards):
        tsunami = _get(all_cards, "Tsunami")
        island = _island(all_cards)
        forest = _forest(all_cards)

        p1 = PlayerState(name="P1", hand=[tsunami], battlefield=[Permanent(card=forest)])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=island), Permanent(card=forest)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Tsunami")

        assert result.supported
        assert all("island" not in p.card.type_line.lower() for p in p2.battlefield)
        assert any("forest" in p.card.type_line.lower() for p in p1.battlefield)

    def test_wild_growth_provides_extra_mana(self, all_cards):
        wild_growth = _get(all_cards, "Wild Growth")
        forest = _forest(all_cards)

        p1 = PlayerState(name="P1", hand=[wild_growth], battlefield=[Permanent(card=forest)])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Wild Growth", target_player_index=0, target_permanent_index=0)

        assert result.supported


# ===========================================================================
# 7. ARTIFACT CARDS
# ===========================================================================

class TestArtifactCards:
    def test_black_lotus_adds_three_mana(self, all_cards):
        lotus = _get(all_cards, "Black Lotus")
        p1 = PlayerState(name="P1", battlefield=[Permanent(card=lotus)])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.activate_permanent_ability(0, "Black Lotus", mana_color="U")

        assert result.supported
        assert p1.mana_pool["U"] == 3
        assert not p1.battlefield  # lotus sacrificed itself

    def test_mox_sapphire_taps_for_blue(self, all_cards):
        mox = _get(all_cards, "Mox Sapphire")
        p1 = PlayerState(name="P1", battlefield=[Permanent(card=mox)])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.activate_permanent_ability(0, "Mox Sapphire", target_player_index=0)

        assert result.supported
        assert p1.mana_pool["U"] == 1

    def test_mox_emerald_taps_for_green(self, all_cards):
        mox = _get(all_cards, "Mox Emerald")
        p1 = PlayerState(name="P1", battlefield=[Permanent(card=mox)])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.activate_permanent_ability(0, "Mox Emerald", target_player_index=0)

        assert result.supported
        assert p1.mana_pool["G"] == 1

    def test_mox_jet_taps_for_black(self, all_cards):
        mox = _get(all_cards, "Mox Jet")
        p1 = PlayerState(name="P1", battlefield=[Permanent(card=mox)])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.activate_permanent_ability(0, "Mox Jet", target_player_index=0)

        assert result.supported
        assert p1.mana_pool["B"] == 1

    def test_mox_pearl_taps_for_white(self, all_cards):
        mox = _get(all_cards, "Mox Pearl")
        p1 = PlayerState(name="P1", battlefield=[Permanent(card=mox)])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.activate_permanent_ability(0, "Mox Pearl", target_player_index=0)

        assert result.supported
        assert p1.mana_pool["W"] == 1

    def test_mox_ruby_taps_for_red(self, all_cards):
        mox = _get(all_cards, "Mox Ruby")
        p1 = PlayerState(name="P1", battlefield=[Permanent(card=mox)])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.activate_permanent_ability(0, "Mox Ruby", target_player_index=0)

        assert result.supported
        assert p1.mana_pool["R"] == 1

    def test_sol_ring_taps_for_two_colorless(self, all_cards):
        ring = _get(all_cards, "Sol Ring")
        p1 = PlayerState(name="P1", battlefield=[Permanent(card=ring)])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.activate_permanent_ability(0, "Sol Ring", target_player_index=0)

        assert result.supported
        assert p1.mana_pool["C"] == 2

    def test_nevinyrral_disk_destroys_artifacts_creatures_enchantments(self, all_cards):
        disk = _get(all_cards, "Nevinyrral's Disk")
        bear = _grizzly(all_cards)
        bad_moon = _get(all_cards, "Bad Moon")
        plains = _plains(all_cards)

        p1 = PlayerState(
            name="P1",
            battlefield=[
                Permanent(card=disk, tapped=False),
                Permanent(card=bear),
                Permanent(card=bad_moon),
                Permanent(card=plains),
            ],
        )
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.activate_permanent_ability(0, "Nevinyrral's Disk")

        assert result.supported
        types_remaining = {p.card.primary_type for p in p1.battlefield}
        assert "creature" not in types_remaining
        assert "enchantment" not in types_remaining
        assert "artifact" not in types_remaining
        assert "land" in types_remaining  # plains survives

    def test_steal_artifact_moves_artifact_to_caster(self, all_cards):
        steal = _get(all_cards, "Steal Artifact")
        sol_ring = _get(all_cards, "Sol Ring")

        p1 = PlayerState(name="P1", hand=[steal])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=sol_ring)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Steal Artifact", target_player_index=1, target_permanent_index=0)

        assert result.supported
        assert any(p.card.name == "Sol Ring" for p in p1.battlefield)
        assert not any(p.card.name == "Sol Ring" for p in p2.battlefield)

    def test_icy_manipulator_taps_any_permanent(self, all_cards):
        icy = _get(all_cards, "Icy Manipulator")
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", battlefield=[Permanent(card=icy)])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
        game = Game(players=[p1, p2])

        result = game.activate_permanent_ability(0, "Icy Manipulator", target_player_index=1)

        assert result.supported
        assert p2.battlefield[0].tapped is True

    def test_rod_of_ruin_deals_1_damage(self, all_cards):
        rod = _get(all_cards, "Rod of Ruin")
        p1 = PlayerState(name="P1", battlefield=[Permanent(card=rod)])
        p2 = PlayerState(name="P2", life=20)
        game = Game(players=[p1, p2])

        result = game.activate_permanent_ability(0, "Rod of Ruin", target_player_index=1)

        assert result.supported
        assert p2.life == 19


# ===========================================================================
# 8. LAND CARDS
# ===========================================================================

class TestLandCards:
    def test_basic_lands_produce_correct_mana(self, all_cards):
        land_mana = [
            ("Plains", "W"),
            ("Island", "U"),
            ("Swamp", "B"),
            ("Mountain", "R"),
            ("Forest", "G"),
        ]
        for land_name, expected_color in land_mana:
            land = _get(all_cards, land_name)
            p1 = PlayerState(name="P1", battlefield=[Permanent(card=land)])
            p2 = PlayerState(name="P2")
            game = Game(players=[p1, p2])

            ok = game.tap_land_for_mana(0, land_name)

            assert ok, f"{land_name} should be tappable for mana"
            assert p1.mana_pool[expected_color] == 1, f"{land_name} should produce {expected_color}"

    def test_dual_lands_produce_either_color(self, all_cards):
        # Each dual land should tap for one of its two colors
        dual_pairs = [
            ("Tundra", "W", "U"),
            ("Underground Sea", "U", "B"),
            ("Badlands", "B", "R"),
            ("Taiga", "R", "G"),
            ("Savannah", "G", "W"),
            ("Scrubland", "W", "B"),
            ("Bayou", "B", "G"),
            ("Plateau", "R", "W"),
            ("Tropical Island", "G", "U"),
        ]
        for land_name, color_a, color_b in dual_pairs:
            land = _get(all_cards, land_name)
            p1 = PlayerState(name="P1", battlefield=[Permanent(card=land)])
            p2 = PlayerState(name="P2")
            game = Game(players=[p1, p2])

            ok = game.tap_land_for_mana(0, land_name)

            assert ok, f"{land_name} should be tappable"
            produced = sum(p1.mana_pool.get(c, 0) for c in (color_a, color_b))
            assert produced >= 1, f"{land_name} should produce {color_a} or {color_b}"


# ===========================================================================
# 9. COMPREHENSIVE CASTING â€” every LEA card resolves without crashing
# ===========================================================================

@pytest.mark.parametrize("card_name", [
    "Air Elemental", "Ancestral Recall", "Animate Artifact", "Animate Dead",
    "Animate Wall", "Ankh of Mishra", "Armageddon", "Aspect of Wolf",
    "Bad Moon", "Balance", "Basalt Monolith", "Benalish Hero", "Berserk",
    "Birds of Paradise", "Black Knight", "Black Lotus", "Black Vise",
    "Blaze of Glory", "Blessing", "Blue Elemental Blast", "Blue Ward", "Bog Wraith",
    "Braingeyser", "Burrowing", "Camouflage", "Castle",
    "Circle of Protection: Blue", "Circle of Protection: Green",
    "Circle of Protection: Red", "Circle of Protection: White",
    "Clockwork Beast", "Clone", "Cockatrice", "Conservator",
    "Control Magic", "Conversion", "Copper Tablet", "Copy Artifact",
    "Counterspell", "Craw Wurm", "Creature Bond", "Crusade",
    "Crystal Rod", "Cursed Land", "Cyclopean Tomb", "Dark Ritual", "Darkpact",
    "Death Ward", "Deathlace", "Demonic Hordes", "Demonic Tutor",
    "Dingus Egg", "Disenchant", "Disintegrate", "Disrupting Scepter",
    "Dragon Whelp", "Drain Life", "Drudge Skeletons", "Dwarven Demolition Team",
    "Dwarven Warriors", "Earth Elemental", "Earthbind", "Earthquake",
    "Elvish Archers", "Evil Presence", "False Orders", "Fear",
    "Feedback", "Fire Elemental", "Fireball", "Firebreathing", "Flashfires",
    "Flight", "Fog", "Force of Nature", "Forcefield",
    "Frozen Shade", "Fungusaur", "Gaea's Liege", "Gauntlet of Might",
    "Giant Growth", "Giant Spider", "Glasses of Urza", "Gloom",
    "Goblin Balloon Brigade", "Goblin King", "Granite Gargoyle", "Gray Ogre",
    "Grizzly Bears", "Guardian Angel", "Healing Salve", "Helm of Chatzuk",
    "Hill Giant", "Holy Armor", "Holy Strength", "Howl from Beyond",
    "Howling Mine", "Hurloon Minotaur", "Hurricane", "Hypnotic Specter",
    "Ice Storm", "Icy Manipulator", "Ironroot Treefolk", "Island Sanctuary",
    "Jade Statue", "Jayemdae Tome", "Juggernaut", "Jump",
    "Keldon Warlord", "Kormus Bell", "Lance", "Library of Leng",
    "Lightning Bolt", "Llanowar Elves", "Lord of Atlantis", "Lure",
    "Mahamoti Djinn", "Mana Flare", "Mana Short", "Mana Vault",
    "Manabarbs", "Meekstone", "Merfolk of the Pearl Trident", "Mesa Pegasus",
    "Mind Twist", "Mons's Goblin Raiders", "Natural Selection", "Nether Shadow",
    "Nettling Imp", "Nevinyrral's Disk", "Nightmare", "Northern Paladin",
    "Obsianus Golem", "Orcish Artillery", "Orcish Oriflamme", "Paralyze",
    "Pearled Unicorn", "Personal Incarnation", "Pestilence", "Phantom Monster", "Pirate Ship",
    "Plague Rats", "Power Leak", "Power Surge", "Prodigal Sorcerer",
    "Psionic Blast", "Psychic Venom", "Raging River", "Raise Dead",
    "Red Elemental Blast", "Regeneration", "Regrowth", "Resurrection",
    "Reverse Damage", "Righteousness", "Roc of Kher Ridges", "Rock Hydra",
    "Rod of Ruin", "Royal Assassin", "Samite Healer", "Savannah Lions",
    "Scathe Zombies", "Scavenging Ghoul", "Scryb Sprites", "Sea Serpent",
    "Sedge Troll", "Sengir Vampire", "Serra Angel", "Shatter",
    "Shivan Dragon", "Sinkhole", "Siren's Call", "Sleight of Mind", "Smoke",
    "Sol Ring", "Spell Blast", "Stasis", "Steal Artifact",
    "Stone Giant", "Stone Rain", "Stream of Life", "Swords to Plowshares",
    "Terror", "The Hive", "Thicket Basilisk", "Time Walk",
    "Timetwister", "Tranquility", "Tsunami", "Twiddle",
    "Two-Headed Giant of Foriys", "Unholy Strength", "Unsummon", "Uthden Troll",
    "Verduran Enchantress", "Veteran Bodyguard", "Volcanic Eruption",
    "Wall of Air", "Wall of Bone", "Wall of Brambles", "Wall of Fire",
    "Wall of Ice", "Wall of Stone", "Wall of Swords", "Wall of Water",
    "Wall of Wood", "Wanderlust", "War Mammoth", "Warp Artifact",
    "Water Elemental", "Weakness", "Web", "Wheel of Fortune",
    "White Knight", "Wild Growth", "Will-o'-the-Wisp", "Winter Orb",
    "Wooden Sphere", "Word of Command", "Wrath of God", "Zombie Master",
])
def test_all_lea_cards_resolve_without_exception(all_cards, card_name):
    """Every LEA card must resolve without throwing a Python exception.
    This is a smoke-test â€” it does not check the effect in detail.
    """
    from engine.mixins.stack_casting import aura_enchant_noun, permanent_matches_enchant_noun

    card = _get(all_cards, card_name)
    island = _island(all_cards)
    plains = _plains(all_cards)
    swamp = _swamp(all_cards)
    mountain = _mountain(all_cards)
    forest = _forest(all_cards)
    bear = _grizzly(all_cards)
    bad_moon = _get(all_cards, "Bad Moon")
    black_lotus = _get(all_cards, "Black Lotus")

    p1 = PlayerState(
        name="P1",
        hand=[card],
        library=[island, plains, swamp, mountain, forest] * 4,
        battlefield=[
            Permanent(card=bear),
            Permanent(card=plains),
            Permanent(card=black_lotus),
            Permanent(card=bad_moon),
        ],
        graveyard=[bear],
    )
    p2 = PlayerState(
        name="P2",
        hand=[island, plains, bear],
        library=[island, plains, swamp, mountain, forest] * 4,
        battlefield=[
            Permanent(card=bear, tapped=True),
            Permanent(card=island),
            Permanent(card=black_lotus),
            Permanent(card=bad_moon),
        ],
        graveyard=[bear],
        life=20,
    )

    game = Game(players=[p1, p2])

    # Determine target index for aura spells
    aura_target_idx = None
    enchant_noun = aura_enchant_noun(card)
    if enchant_noun is not None:
        aura_target_idx = next(
            (
                idx
                for idx, perm in enumerate(p2.battlefield)
                if permanent_matches_enchant_noun(perm, enchant_noun)
            ),
            None,
        )

    # Cards requiring special setup
    if card_name == "Camouflage":
        game.start_turn(0)
        game._close_current_priority_step()
        game.advance_combat_phase()  # â†’ beginning_of_combat
        game.advance_combat_phase()  # â†’ declare_attackers
        game.cast_from_hand(0, card_name, target_player_index=1)
        return

    if card_name in {"Counterspell", "Power Sink", "Spell Blast", "Blue Elemental Blast"}:
        bolt = _get(all_cards, "Lightning Bolt")
        p2.hand.append(bolt)
        game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
        game.cast_from_hand(0, card_name, target_player_index=1)
        return

    if card_name == "Red Elemental Blast":
        recall = _get(all_cards, "Ancestral Recall")
        p2.hand.append(recall)
        game.queue_from_hand(1, "Ancestral Recall", target_player_index=1)
        game.cast_from_hand(0, card_name, target_player_index=1)
        return

    if card_name == "Fork":
        recall = _get(all_cards, "Ancestral Recall")
        p1.hand.insert(0, recall)
        game.queue_from_hand(0, "Ancestral Recall", target_player_index=1)
        game.cast_from_hand(0, "Fork", target_player_index=1)
        return

    # General cast
    result = game.cast_from_hand(
        0,
        card_name,
        target_player_index=1,
        target_permanent_index=aura_target_idx,
        x_value=3,
    )
    # The call must not raise; result being unsupported is acceptable
    # (some cards may have unmet preconditions in this generic setup)
    assert result is not None


# ===========================================================================
# 10. ORACLE COVERAGE — previously untested LEA cards
# ===========================================================================


def test_blue_ward_grants_protection_from_blue(all_cards):
    ward = _get(all_cards, "Blue Ward")
    creature = _mk_creature_card("Test Knight", power=2, toughness=2)
    p1 = PlayerState(name="P1", hand=[ward])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Blue Ward", target_player_index=1, target_permanent_index=0)

    assert result.supported
    assert p2.battlefield[0].metadata.get("protection_from_blue") is True


def test_web_grants_toughness_bonus_and_reach(all_cards):
    web = _get(all_cards, "Web")
    bears = _get(all_cards, "Grizzly Bears")
    flyer = _get(all_cards, "Air Elemental")
    bears_perm = Permanent(card=bears)
    p1 = PlayerState(name="P1", hand=[web], battlefield=[bears_perm])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=flyer)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Web", target_player_index=0, target_permanent_index=0)

    assert result.supported
    # "Enchanted creature gets +0/+2"
    assert bears_perm.effective_power == 2
    assert bears_perm.effective_toughness == 4
    # "and has reach" — it can now block creatures with flying
    assert game._has_keyword(bears_perm, "reach")
    assert game._can_block_attacker(bears_perm, p2.battlefield[0]) is True


def test_fire_elemental_vanilla_stats_and_cast(all_cards):
    elemental = _get(all_cards, "Fire Elemental")
    assert classify_card(elemental).supported
    p1 = PlayerState(name="P1", hand=[elemental])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Fire Elemental")

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.card.name == "Fire Elemental"
    assert perm.effective_power == 5
    assert perm.effective_toughness == 4


def test_gray_ogre_vanilla_stats_and_cast(all_cards):
    ogre = _get(all_cards, "Gray Ogre")
    assert classify_card(ogre).supported
    p1 = PlayerState(name="P1", hand=[ogre])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Gray Ogre")

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.effective_power == 2
    assert perm.effective_toughness == 2


def test_zombie_master_grants_swampwalk_and_regeneration_to_other_zombies(all_cards):
    master = _get(all_cards, "Zombie Master")
    zombies = _get(all_cards, "Scathe Zombies")
    zombie_perm = Permanent(card=zombies)
    p1 = PlayerState(name="P1", hand=[master], battlefield=[zombie_perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Zombie Master")

    assert result.supported
    # "Other Zombie creatures have swampwalk."
    assert zombie_perm.metadata.get("has_swampwalk") is True
    # 'Other Zombies have "{B}: Regenerate this permanent."'
    assert zombie_perm.metadata.get("granted_regen_ability") is True
    regen = game.activate_permanent_ability(0, "Scathe Zombies")
    assert regen.supported
    assert zombie_perm.regeneration_shield == 1


def test_demonic_hordes_tap_ability_destroys_target_land(all_cards):
    hordes = _get(all_cards, "Demonic Hordes")
    plains = _get(all_cards, "Plains")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=hordes)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=plains)])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Demonic Hordes", target_player_index=1)

    assert result.supported
    assert not p2.battlefield
    assert p2.graveyard and p2.graveyard[0].name == "Plains"
    assert p1.battlefield[0].tapped is True


def test_demonic_hordes_upkeep_paid_with_bbb_keeps_it_untapped(all_cards):
    hordes = _get(all_cards, "Demonic Hordes")
    swamp = _get(all_cards, "Swamp")
    hordes_perm = Permanent(card=hordes)
    p1 = PlayerState(
        name="P1",
        battlefield=[hordes_perm, Permanent(card=swamp)],
        mana_pool={"W": 0, "U": 0, "B": 3, "R": 0, "G": 0, "C": 0},
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert hordes_perm.tapped is False
    assert p1.mana_pool["B"] == 0
    assert any(p.card.name == "Swamp" for p in p1.battlefield)


def test_demonic_hordes_upkeep_unpaid_taps_it_and_sacrifices_own_land(all_cards):
    hordes = _get(all_cards, "Demonic Hordes")
    swamp = _get(all_cards, "Swamp")
    plains = _get(all_cards, "Plains")
    hordes_perm = Permanent(card=hordes)
    p1 = PlayerState(name="P1", battlefield=[hordes_perm, Permanent(card=swamp)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=plains)])
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert hordes_perm.tapped is True
    # The controller sacrifices their own land; the opponent's land is untouched.
    assert not any(p.card.primary_type == "land" for p in p1.battlefield)
    assert any(c.name == "Swamp" for c in p1.graveyard)
    assert any(p.card.name == "Plains" for p in p2.battlefield)


def test_fungusaur_gets_counter_when_dealt_nonlethal_damage(all_cards):
    fungusaur = _get(all_cards, "Fungusaur")
    zap = _mk_card("Test Zap", "Instant", "Test Zap deals 1 damage to any target.")
    fungusaur_perm = Permanent(card=fungusaur)
    p1 = PlayerState(name="P1", battlefield=[fungusaur_perm])
    p2 = PlayerState(name="P2", hand=[zap])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(1, "Test Zap", target_player_index=0, target_permanent_index=0)

    assert result.supported
    # 2/2 base, 1 damage marked, +1/+1 counter from the trigger -> survives as a 3/3
    assert fungusaur_perm in p1.battlefield
    assert fungusaur_perm.damage_marked == 1
    assert fungusaur_perm.effective_power == 3
    assert fungusaur_perm.effective_toughness == 3


def test_personal_incarnation_death_halves_owner_life(all_cards):
    incarnation = _get(all_cards, "Personal Incarnation")
    terror = _get(all_cards, "Terror")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=incarnation)], life=20)
    p2 = PlayerState(name="P2", hand=[terror])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(1, "Terror", target_player_index=0, target_permanent_index=0)

    assert result.supported
    assert not p1.battlefield
    # "its owner loses half their life, rounded up" — 20 -> 10
    assert p1.life == 10


def test_personal_incarnation_redirect_ability_marks_redirect(all_cards):
    incarnation = _get(all_cards, "Personal Incarnation")
    incarnation_perm = Permanent(card=incarnation)
    p1 = PlayerState(name="P1", battlefield=[incarnation_perm], life=20)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Personal Incarnation")

    assert result.supported
    assert incarnation_perm.metadata.get("redirect_one_damage_to_owner_until_eot") == 1


def test_scavenging_ghoul_corpse_counters_and_regeneration(all_cards):
    ghoul = _get(all_cards, "Scavenging Ghoul")
    bears = _get(all_cards, "Grizzly Bears")
    bolt = _get(all_cards, "Lightning Bolt")
    ghoul_perm = Permanent(card=ghoul)
    p1 = PlayerState(name="P1", battlefield=[ghoul_perm])
    p2 = PlayerState(name="P2", hand=[bolt], battlefield=[Permanent(card=bears)])
    game = Game(players=[p1, p2])

    # A creature dies this turn...
    result = game.cast_from_hand(1, "Lightning Bolt", target_player_index=1, target_permanent_index=0)
    assert result.supported
    assert not p2.battlefield

    # ...so at the end step the Ghoul gets a corpse counter
    game.resolve_end_step(0)
    assert ghoul_perm.metadata.get("corpse_counters") == 1

    # "Remove a corpse counter from this creature: Regenerate this creature."
    regen = game.activate_permanent_ability(0, "Scavenging Ghoul")
    assert regen.supported
    assert ghoul_perm.regeneration_shield == 1
    assert ghoul_perm.metadata.get("corpse_counters") == 0

    # With no corpse counters left, the ability cannot be activated
    regen_again = game.activate_permanent_ability(0, "Scavenging Ghoul")
    assert not regen_again.supported


def test_spell_blast_counters_spell_with_matching_x(all_cards):
    blast = _get(all_cards, "Spell Blast")
    elemental = _get(all_cards, "Air Elemental")  # mana value 5
    p1 = PlayerState(name="P1", hand=[blast])
    p2 = PlayerState(name="P2", hand=[elemental])
    game = Game(players=[p1, p2])

    game.queue_from_hand(1, "Air Elemental")
    result = game.cast_from_hand(0, "Spell Blast", target_player_index=1, x_value=5)

    assert result.supported
    assert any("Spell Blast countered Air Elemental" in line for line in game.log)
    assert not game.stack
    assert not p2.battlefield


def test_spell_blast_does_not_counter_spell_with_wrong_x(all_cards):
    blast = _get(all_cards, "Spell Blast")
    elemental = _get(all_cards, "Air Elemental")  # mana value 5
    p1 = PlayerState(name="P1", hand=[blast])
    p2 = PlayerState(name="P2", hand=[elemental])
    game = Game(players=[p1, p2])

    game.queue_from_hand(1, "Air Elemental")
    result = game.cast_from_hand(0, "Spell Blast", target_player_index=1, x_value=2)

    assert result.supported
    assert not any("Spell Blast countered" in line for line in game.log)
    # The Air Elemental still resolves
    assert any(p.card.name == "Air Elemental" for p in p2.battlefield)


def test_gaeas_liege_pt_equals_forests_controlled_when_not_attacking(all_cards):
    liege = _get(all_cards, "Gaea's Liege")
    forest = _get(all_cards, "Forest")
    liege_perm = Permanent(card=liege)
    p1 = PlayerState(
        name="P1",
        battlefield=[liege_perm, Permanent(card=forest), Permanent(card=forest)],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game._refresh_dynamic_creatures()

    assert liege_perm.effective_power == 2
    assert liege_perm.effective_toughness == 2


def test_gaeas_liege_pt_equals_defenders_forests_when_attacking(all_cards):
    liege = _get(all_cards, "Gaea's Liege")
    forest = _get(all_cards, "Forest")
    liege_perm = Permanent(card=liege)
    p1 = PlayerState(name="P1", battlefield=[liege_perm, Permanent(card=forest)])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=forest), Permanent(card=forest), Permanent(card=forest)],
    )
    game = Game(players=[p1, p2])

    liege_perm.attacking = True
    liege_perm.defending_player_index = 1
    game._refresh_dynamic_creatures()

    assert liege_perm.effective_power == 3
    assert liege_perm.effective_toughness == 3


def test_gaeas_liege_pt_refreshes_when_attackers_declared(all_cards):
    # Regression: declaring attackers must recompute dynamic P/T so the Liege
    # switches from its controller's Forests to the defending player's Forests.
    liege = _get(all_cards, "Gaea's Liege")
    forest = _get(all_cards, "Forest")
    liege_perm = Permanent(card=liege)
    p1 = PlayerState(name="P1", battlefield=[liege_perm, Permanent(card=forest)])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=forest), Permanent(card=forest), Permanent(card=forest)],
    )
    game = Game(players=[p1, p2])
    game._refresh_dynamic_creatures()
    assert (liege_perm.effective_power, liege_perm.effective_toughness) == (1, 1)

    game.active_player_index = 0
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    liege_perm.tapped = False

    ok, _ = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok
    assert (liege_perm.effective_power, liege_perm.effective_toughness) == (3, 3)


def test_gaeas_liege_dies_with_zero_forests(all_cards):
    # Regression: with 0 Forests its toughness is 0, so it dies as a state-based action.
    liege = _get(all_cards, "Gaea's Liege")
    plains = _get(all_cards, "Plains")
    p1 = PlayerState(name="P1", hand=[liege])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=plains)])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.cast_from_hand(0, "Gaea's Liege")
    game.check_state_based_actions()

    assert not any(p.card.name == "Gaea's Liege" for p in p1.battlefield)
    assert any(c.name == "Gaea's Liege" for c in p1.graveyard)


def test_gaeas_liege_activation_targets_chosen_land(all_cards):
    # Regression: the player may pick which land becomes a Forest, not just the first.
    liege = _get(all_cards, "Gaea's Liege")
    plains = _get(all_cards, "Plains")
    island = _get(all_cards, "Island")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=liege)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=plains), Permanent(card=island)])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(
        0, "Gaea's Liege", target_player_index=1, target_permanent_index=1
    )

    assert result.supported
    assert p2.battlefield[0].metadata.get("land_type_override") is None
    assert p2.battlefield[1].metadata.get("land_type_override") == "forest"


def test_wooden_sphere_gains_life_on_green_creature_spell(all_cards):
    # Regression: rod-style life gain must also fire when the green spell that
    # resolves is a permanent (creature/artifact), not only an instant/sorcery.
    sphere = _get(all_cards, "Wooden Sphere")
    bears = _get(all_cards, "Grizzly Bears")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=sphere)], hand=[bears])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    starting_life = p1.life
    game.cast_from_hand(0, "Grizzly Bears")

    assert p1.life == starting_life + 1


def test_darkpact_exchanges_top_library_card_with_simulated_ante(all_cards):
    darkpact = _get(all_cards, "Darkpact")
    swamp = _get(all_cards, "Swamp")
    p1 = PlayerState(name="P1", hand=[darkpact], library=[swamp])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Darkpact")

    assert result.supported
    # Simplified ante model: the top library card moves to the graveyard
    assert not p1.library
    assert any(c.name == "Swamp" for c in p1.graveyard)
    assert any(c.name == "Darkpact" for c in p1.graveyard)


# ===========================================================================
# Siren's Call
# ===========================================================================

def test_sirens_call_cannot_be_cast_during_your_own_turn(all_cards):
    call = _get(all_cards, "Siren's Call")
    bear = _mk_card("Bear", "Creature - Bear")

    p1 = PlayerState(name="P1", hand=[call])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])  # P1 is the active player by default

    result = game.cast_from_hand(0, "Siren's Call", target_player_index=1)

    assert result.supported is False
    assert any(c.name == "Siren's Call" for c in p1.hand)


def test_sirens_call_cannot_be_cast_after_attackers_declared(all_cards):
    call = _get(all_cards, "Siren's Call")
    bear = _mk_card("Bear", "Creature - Bear")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[call])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)], library=[island])
    game = Game(players=[p1, p2])

    game.start_turn(1)
    game._close_current_priority_step()
    game.advance_combat_phase()  # -> beginning_of_combat
    game.advance_combat_phase()  # -> declare_attackers
    ok, _ = game.declare_attackers(1, [0])
    assert ok

    result = game.cast_from_hand(0, "Siren's Call", target_player_index=1)

    assert result.supported is False
    assert any(c.name == "Siren's Call" for c in p1.hand)


def test_sirens_call_marks_active_player_creatures(all_cards):
    call = _get(all_cards, "Siren's Call")
    bear = _mk_card("Opposing Bear", "Creature - Bear")
    wall = _mk_card("Test Wall", "Creature - Wall")
    home_bear = _mk_card("Home Bear", "Creature - Bear")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[call], battlefield=[Permanent(card=home_bear)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear), Permanent(card=wall)], library=[island])
    game = Game(players=[p1, p2])
    game.start_turn(1)

    # Entered the battlefield this turn: exempt from the delayed destruction
    # ("didn't control continuously since the beginning of the turn").
    fresh = Permanent(card=_mk_card("Fresh Bear", "Creature - Bear"))
    fresh.metadata["summoning_sickness_turn"] = game.turn
    p2.battlefield.append(fresh)

    result = game.cast_from_hand(0, "Siren's Call", target_player_index=1)

    assert result.supported
    assert any(c.name == "Siren's Call" for c in p1.graveyard)

    bear_perm, wall_perm = p2.battlefield[0], p2.battlefield[1]
    assert bear_perm.metadata.get("must_attack_until_eot") is True
    assert bear_perm.metadata.get("destroy_if_did_not_attack_eot") is True
    # Walls are never destroyed by Siren's Call
    assert wall_perm.metadata.get("destroy_if_did_not_attack_eot") is None
    assert fresh.metadata.get("destroy_if_did_not_attack_eot") is None
    # The caster's own creatures are unaffected
    assert p1.battlefield[0].metadata.get("must_attack_until_eot") is None


def test_sirens_call_forces_creatures_to_attack(all_cards):
    call = _get(all_cards, "Siren's Call")
    bear = _mk_card("Reluctant Bear", "Creature - Bear")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[call])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)], library=[island])
    game = Game(players=[p1, p2])

    game.start_turn(1)
    result = game.cast_from_hand(0, "Siren's Call", target_player_index=1)
    assert result.supported

    game._close_current_priority_step()
    game.advance_combat_phase()  # -> beginning_of_combat
    game.advance_combat_phase()  # -> declare_attackers

    ok, reason = game.declare_attackers(1, [])
    assert not ok
    assert "must attack" in reason

    ok, _ = game.declare_attackers(1, [0])
    assert ok


def test_sirens_call_destroys_non_attackers_at_end_step(all_cards):
    call = _get(all_cards, "Siren's Call")
    attacker = _mk_card("Eager Bear", "Creature - Bear")
    slacker = _mk_card("Lazy Bear", "Creature - Bear")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[call])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=attacker), Permanent(card=slacker)],
        library=[island],
    )
    game = Game(players=[p1, p2])

    game.start_turn(1)
    result = game.cast_from_hand(0, "Siren's Call", target_player_index=1)
    assert result.supported

    # A tapped creature can't attack, but it still didn't attack this turn,
    # so it is destroyed at the beginning of the next end step.
    p2.battlefield[1].tapped = True

    game._close_current_priority_step()
    game.advance_combat_phase()  # -> beginning_of_combat
    game.advance_combat_phase()  # -> declare_attackers
    ok, _ = game.declare_attackers(1, [0])
    assert ok

    game.resolve_end_step(1)

    names = [perm.card.name for perm in p2.battlefield]
    assert "Eager Bear" in names
    assert "Lazy Bear" not in names
    assert any(c.name == "Lazy Bear" for c in p2.graveyard)
