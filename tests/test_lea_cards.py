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


# List of LEA cards that lacked tests when this file was generated
_UNTESTED = [
"Badlands",
"Basalt Monolith",
"Bayou",
"Berserk",
"Birds of Paradise",
"Black Ward",
"Blue Elemental Blast",
"Blue Ward",
"Bog Wraith",
"Burrowing",
"Celestial Prism",
"Channel",
"Chaos Orb",
"Chaoslace",
"Circle of Protection: Green",
"Circle of Protection: Red",
"Circle of Protection: White",
"Consecrate Land",
"Conservator",
"Control Magic",
"Copper Tablet",
"Creature Bond",
"Crusade",
"Crystal Rod",
"Cursed Land",
"Dark Ritual",
"Death Ward",
"Deathgrip",
"Dingus Egg",
"Disrupting Scepter",
"Dragon Whelp",
"Drain Life",
"Drain Power",
"Drudge Skeletons",
"Dwarven Demolition Team",
"Earth Elemental",
"Earthbind",
"Earthquake",
"Elvish Archers",
"Evil Presence",
"Farmstead",
"Fear",
"Feedback",
"Fire Elemental",
"Fireball",
"Firebreathing",
"Flashfires",
"Flight",
"Gauntlet of Might",
"Giant Growth",
"Giant Spider",
"Goblin King",
"Gray Ogre",
"Green Ward",
"Guardian Angel",
"Hill Giant",
"Holy Armor",
"Holy Strength",
"Howl from Beyond",
"Hurloon Minotaur",
"Hurricane",
"Icy Manipulator",
"Illusionary Mask",
"Instill Energy",
"Invisibility",
"Iron Star",
"Ironclaw Orcs",
"Ironroot Treefolk",
"Island Sanctuary",
"Ivory Cup",
"Jade Monolith",
"Jump",
"Karma",
"Kudzu",
"Ley Druid",
"Lich",
"Lifeforce",
"Lifelace",
"Lifetap",
"Living Artifact",
"Living Wall",
"Lord of Atlantis",
"Lord of the Pit",
"Lure",
"Mahamoti Djinn",
"Mana Short",
"Mana Vault",
"Manabarbs",
"Merfolk of the Pearl Trident",
"Mind Twist",
"Mons's Goblin Raiders",
"Mox Emerald",
"Mox Jet",
"Mox Pearl",
"Mox Ruby",
"Mox Sapphire",
"Nether Shadow",
"Northern Paladin",
"Obsianus Golem",
"Orcish Artillery",
"Paralyze",
"Pearled Unicorn",
"Pestilence",
"Phantasmal Forces",
"Phantasmal Terrain",
"Phantom Monster",
"Pirate Ship",
"Plague Rats",
"Plateau",
"Power Leak",
"Power Surge",
"Psionic Blast",
"Psychic Venom",
"Purelace",
"Raise Dead",
"Red Elemental Blast",
"Red Ward",
"Regrowth",
"Resurrection",
"Reverse Damage",
"Righteousness",
"Roc of Kher Ridges",
"Rod of Ruin",
"Royal Assassin",
"Samite Healer",
"Savannah",
"Savannah Lions",
"Scathe Zombies",
"Scrubland",
"Scryb Sprites",
"Sengir Vampire",
"Shanodin Dryads",
"Shatter",
"Simulacrum",
"Sinkhole",
"Siren's Call",
"Sol Ring",
"Soul Net",
"Steal Artifact",
"Stone Rain",
"Swords to Plowshares",
"Taiga",
"Terror",
"Thicket Basilisk",
"Thoughtlace",
"Throne of Bone",
"Time Vault",
"Tranquility",
"Tropical Island",
"Tsunami",
"Tundra",
"Tunnel",
"Twiddle",
"Two-Headed Giant of Foriys",
"Underground Sea",
"Unholy Strength",
"Uthden Troll",
"Vesuvan Doppelganger",
"Veteran Bodyguard",
"Volcanic Eruption",
"Wall of Air",
"Wall of Bone",
"Wall of Brambles",
"Wall of Fire",
"Wall of Ice",
"Wall of Swords",
"Wall of Water",
"Wall of Wood",
"Wanderlust",
"War Mammoth",
"Warp Artifact",
"Water Elemental",
"Weakness",
"White Knight",
"White Ward",
"Wild Growth",
"Will-o'-the-Wisp",
"Wooden Sphere",
"Wrath of God",
"Zombie Master",
]


# Dynamically attach tests to module
for i, card in enumerate(_UNTESTED, start=1):
    globals()[f"test_lea_card_presence_{i:03d}"] = _make_test(card, i)

# Consolidated imports required by extracted tests
from engine.ai_policy import (
    choose_cast_action,
    choose_activation_action,
    choose_combat_blockers,
    choose_combat_instant_cast_action,
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

def test_choose_cast_action_targets_self_for_ancestral_recall(all_cards):
    recall = _get(all_cards, "Ancestral Recall")
    p1 = PlayerState(name="P1", hand=[recall], mana_pool={"W": 0, "U": 1, "B": 0, "R": 0, "G": 0, "C": 0})
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
    assert action.card_name == "Lightning Bolt"
    assert action.target_player_index == 0

def test_destroy_all_lands_spell(all_cards):
    armageddon = next(card for card in all_cards if card.name == "Armageddon")
    plains = next(card for card in all_cards if card.name == "Plains")

    p1 = PlayerState(name="P1", hand=[armageddon])
    p2 = PlayerState(name="P2")
    p1.battlefield.append(Permanent(plains))
    p2.battlefield.append(Permanent(plains))

    game = Game(players=[p1, p2])
    result = game.cast_from_hand(0, "Armageddon", target_player_index=1)

    assert result.supported
    assert len(p1.battlefield) == 0
    assert len(p2.battlefield) == 0

def test_ancestral_recall_draws_three(all_cards):
    recall = next(card for card in all_cards if card.name == "Ancestral Recall")
    island = next(card for card in all_cards if card.name == "Island")

    p1 = PlayerState(name="P1", hand=[recall])
    p2 = PlayerState(name="P2", library=[island, island, island, island])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Ancestral Recall", target_player_index=1)

    assert result.supported
    assert len(p2.hand) == 3

def test_counterspell_counters_spell_on_stack(all_cards):
    recall = next(card for card in all_cards if card.name == "Ancestral Recall")
    counterspell = next(card for card in all_cards if card.name == "Counterspell")
    island = next(card for card in all_cards if card.name == "Island")

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
    disenchant = next(card for card in all_cards if card.name == "Disenchant")
    lotus = next(card for card in all_cards if card.name == "Black Lotus")

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
    ice_storm = next(card for card in all_cards if card.name == "Ice Storm")
    island = next(card for card in all_cards if card.name == "Island")
    mountain = next(card for card in all_cards if card.name == "Mountain")

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
    bad_moon = next(card for card in all_cards if card.name == "Bad Moon")
    black_knight = next(card for card in all_cards if card.name == "Black Knight")

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

def test_creature_with_keyword_reminder_is_supported(all_cards):
    serra_angel = next(card for card in all_cards if card.name == "Serra Angel")
    classification = classify_card(serra_angel)
    assert classification.supported

def test_creature_with_activated_damage_is_supported(all_cards):
    prodigal = next(card for card in all_cards if card.name == "Prodigal Sorcerer")
    classification = classify_card(prodigal)
    assert classification.supported

def test_activate_prodigal_sorcerer_ability(all_cards):
    prodigal = next(card for card in all_cards if card.name == "Prodigal Sorcerer")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=prodigal)])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Prodigal Sorcerer", target_player_index=1)
    assert result.supported
    assert p2.life == 19
    assert p1.battlefield[0].tapped is True

def test_nevinyrrals_disk_enters_tapped(all_cards):
    disk = next(card for card in all_cards if card.name == "Nevinyrral's Disk")
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
    disk = next(card for card in all_cards if card.name == "Nevinyrral's Disk")
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
    lotus = next(card for card in all_cards if card.name == "Black Lotus")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=lotus)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Black Lotus", target_player_index=1)

    assert result.supported
    assert p1.mana_pool["G"] == 3
    assert not p1.battlefield
    assert p1.graveyard and p1.graveyard[0].name == "Black Lotus"

def test_activate_black_lotus_with_selected_color(all_cards):
    lotus = next(card for card in all_cards if card.name == "Black Lotus")
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
    animate_dead = next(card for card in all_cards if card.name == "Animate Dead")
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
    animate = next(card for card in all_cards if card.name == "Animate Artifact")
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
    braingeyser = next(card for card in all_cards if card.name == "Braingeyser")
    island = next(card for card in all_cards if card.name == "Island")
    p1 = PlayerState(name="P1", hand=[braingeyser])
    p2 = PlayerState(name="P2", library=[island, island, island, island, island])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Braingeyser", target_player_index=1, x_value=4)

    assert result.supported
    assert len(p2.hand) == 4

def test_ankh_of_mishra_triggers_on_land_entry(all_cards):
    ankh = next(card for card in all_cards if card.name == "Ankh of Mishra")
    plains = next(card for card in all_cards if card.name == "Plains")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=ankh)])
    p2 = PlayerState(name="P2", hand=[plains], life=20)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(1, "Plains", target_player_index=1)

    assert result.supported
    assert p2.life == 18

def test_black_vise_upkeep_trigger(all_cards):
    vise = next(card for card in all_cards if card.name == "Black Vise")
    island = next(card for card in all_cards if card.name == "Island")
    p1 = PlayerState(name="P1", hand=[vise])
    p2 = PlayerState(name="P2", hand=[island, island, island, island, island, island], life=20)
    game = Game(players=[p1, p2])

    cast_result = game.cast_from_hand(0, "Black Vise", target_player_index=1)
    game.resolve_upkeep(1)

    assert cast_result.supported
    # 6 cards in hand means 2 damage from Black Vise.
    assert p2.life == 18

def test_unsummon_returns_target_creature(all_cards):
    unsummon = next(card for card in all_cards if card.name == "Unsummon")
    creature = _mk_card("Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[unsummon])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Unsummon", target_player_index=1)

    assert result.supported
    assert not p2.battlefield
    assert any(card.name == "Bear" for card in p2.hand)

def test_wheel_of_fortune_discards_then_draws(all_cards):
    wheel = next(card for card in all_cards if card.name == "Wheel of Fortune")
    island = next(card for card in all_cards if card.name == "Island")
    p1 = PlayerState(name="P1", hand=[wheel, island], library=[island] * 10)
    p2 = PlayerState(name="P2", hand=[island, island], library=[island] * 10)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Wheel of Fortune", target_player_index=1)

    assert result.supported
    assert len(p1.hand) == 7
    assert len(p2.hand) == 7

def test_timetwister_resets_and_draws_seven(all_cards):
    twister = next(card for card in all_cards if card.name == "Timetwister")
    island = next(card for card in all_cards if card.name == "Island")
    bear = _mk_card("Dead Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[twister, island], graveyard=[bear], library=[island] * 10)
    p2 = PlayerState(name="P2", hand=[island], graveyard=[bear], library=[island] * 10)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Timetwister", target_player_index=1)

    assert result.supported
    assert len(p1.hand) == 7
    assert len(p2.hand) == 7

def test_demonic_tutor_puts_library_card_into_hand(all_cards):
    tutor = next(card for card in all_cards if card.name == "Demonic Tutor")
    island = next(card for card in all_cards if card.name == "Island")
    p1 = PlayerState(name="P1", hand=[tutor], library=[island])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Demonic Tutor", target_player_index=0)

    assert result.supported
    assert any(card.name == "Island" for card in p1.hand)

def test_time_walk_grants_extra_turn(all_cards):
    time_walk = next(card for card in all_cards if card.name == "Time Walk")
    p1 = PlayerState(name="P1", hand=[time_walk])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Time Walk", target_player_index=0)

    assert result.supported
    assert game.extra_turns.get(0, 0) == 1

def test_sacrifice_spell_adds_black_mana(all_cards):
    sacrifice = next(card for card in all_cards if card.name == "Sacrifice")
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
    deathlace = next(card for card in all_cards if card.name == "Deathlace")
    creature = _mk_card("Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[deathlace])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Deathlace", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("color_override") == "B"

def test_orcish_oriflamme_applies_power_bonus(all_cards):
    oriflamme = next(card for card in all_cards if card.name == "Orcish Oriflamme")
    creature = _mk_card("Attacker", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[oriflamme], battlefield=[Permanent(card=creature)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Orcish Oriflamme", target_player_index=0)

    assert result.supported
    assert p1.battlefield[0].effective_power == 3

def test_aspect_of_wolf_applies_half_forest_buff(all_cards):
    aspect = next(card for card in all_cards if card.name == "Aspect of Wolf")
    forest = next(card for card in all_cards if card.name == "Forest")
    creature = _mk_card("Test Bear", "Creature — Bear")

    # Set up controller with 3 Forests -> floor(3/2)=1, ceil(3/2)=2 -> +1/+2
    p1 = PlayerState(
        name="P1",
        hand=[aspect],
        battlefield=[Permanent(card=creature), Permanent(card=forest), Permanent(card=forest), Permanent(card=forest)],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Aspect of Wolf", target_player_index=0)

    assert result.supported
    # Creature is the first permanent on battlefield
    assert p1.battlefield[0].effective_power == 3
    assert p1.battlefield[0].effective_toughness == 4

def test_jayemdae_tome_activated_draw(all_cards):
    tome = next(card for card in all_cards if card.name == "Jayemdae Tome")
    island = next(card for card in all_cards if card.name == "Island")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=tome)], library=[island])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Jayemdae Tome", target_player_index=1)

    assert result.supported
    assert len(p1.hand) == 1

def test_glasses_of_urza_look_at_hand(all_cards):
    glasses = next(card for card in all_cards if card.name == "Glasses of Urza")
    island = next(card for card in all_cards if card.name == "Island")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=glasses)])
    p2 = PlayerState(name="P2", hand=[island, island])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Glasses of Urza", target_player_index=1)

    assert result.supported
    assert any("looked at" in line.lower() for line in game.log)

def test_black_knight_classifies_supported(all_cards):
    knight = next(card for card in all_cards if card.name == "Black Knight")
    result = classify_card(knight)
    assert result.supported

def test_shivan_dragon_activated_plus_one_power(all_cards):
    dragon = next(card for card in all_cards if card.name == "Shivan Dragon")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=dragon)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    before = p1.battlefield[0].effective_power
    result = game.activate_permanent_ability(0, "Shivan Dragon", target_player_index=1)

    assert result.supported
    assert p1.battlefield[0].effective_power == before + 1

def test_granite_gargoyle_activated_plus_one_toughness(all_cards):
    gargoyle = next(card for card in all_cards if card.name == "Granite Gargoyle")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=gargoyle)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    before = p1.battlefield[0].effective_toughness
    result = game.activate_permanent_ability(0, "Granite Gargoyle", target_player_index=1)

    assert result.supported
    assert p1.battlefield[0].effective_toughness == before + 1

def test_frozen_shade_activated_plus_one_plus_one(all_cards):
    shade = next(card for card in all_cards if card.name == "Frozen Shade")
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
    goblin = next(card for card in all_cards if card.name == "Goblin Balloon Brigade")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=goblin)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Goblin Balloon Brigade", target_player_index=1)

    assert result.supported
    assert p1.battlefield[0].metadata.get("gains_flying_until_eot") is True

def test_clockwork_beast_enters_with_seven_plus_zero(all_cards):
    beast = next(card for card in all_cards if card.name == "Clockwork Beast")
    p1 = PlayerState(name="P1", hand=[beast])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Clockwork Beast", target_player_index=1)

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.power_bonus >= 7

def test_rock_hydra_x_counters_on_entry(all_cards):
    hydra = next(card for card in all_cards if card.name == "Rock Hydra")
    p1 = PlayerState(name="P1", hand=[hydra])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Rock Hydra", target_player_index=1, x_value=3)

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.power_bonus >= 3
    assert perm.toughness_bonus >= 3

def test_sea_serpent_attack_restriction(all_cards):
    serpent = next(card for card in all_cards if card.name == "Sea Serpent")
    island = next(card for card in all_cards if card.name == "Island")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=serpent)])
    p2 = PlayerState(name="P2", battlefield=[])
    game = Game(players=[p1, p2])

    assert game.can_attack(p1.battlefield[0], defending_player_index=1) is False
    p2.battlefield.append(Permanent(card=island))
    assert game.can_attack(p1.battlefield[0], defending_player_index=1) is True

def test_summoning_sickness_blocks_attacks_and_tap_abilities(all_cards):
    creature = _mk_card("Test Bear", "Creature — Bear")
    llanowar_elves = next(card for card in all_cards if card.name == "Llanowar Elves")

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
    warlord = next(card for card in all_cards if card.name == "Keldon Warlord")
    creature = _mk_card("Helper", "Creature — Bear")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=warlord), Permanent(card=creature)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game._refresh_dynamic_creatures()
    warlord_perm = p1.battlefield[0]
    assert warlord_perm.effective_power == 2
    assert warlord_perm.effective_toughness == 2

def test_verduran_enchantress_draw_trigger(all_cards):
    enchantress = next(card for card in all_cards if card.name == "Verduran Enchantress")
    blessing = next(card for card in all_cards if card.name == "Blessing")
    island = next(card for card in all_cards if card.name == "Island")
    p1 = PlayerState(name="P1", hand=[blessing], library=[island], battlefield=[Permanent(card=enchantress)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Blessing", target_player_index=0)

    assert result.supported
    assert len(p1.hand) == 1

def test_fog_sets_combat_damage_prevention(all_cards):
    fog = next(card for card in all_cards if card.name == "Fog")
    p1 = PlayerState(name="P1", hand=[fog])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Fog", target_player_index=0)

    assert result.supported
    assert game.combat_damage_prevented_until_eot is True

def test_howling_mine_draw_step_bonus(all_cards):
    mine = next(card for card in all_cards if card.name == "Howling Mine")
    island = next(card for card in all_cards if card.name == "Island")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=mine)])
    p2 = PlayerState(name="P2", library=[island, island, island])
    game = Game(players=[p1, p2])

    drawn = game.resolve_draw_step(1)

    assert drawn == 2
    assert len(p2.hand) == 2

def test_stasis_skips_untap_step(all_cards):
    stasis = next(card for card in all_cards if card.name == "Stasis")
    island = next(card for card in all_cards if card.name == "Island")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=stasis)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=island, tapped=True)])
    game = Game(players=[p1, p2])

    untapped = game.resolve_untap_step(1)

    assert untapped == 0
    assert p2.battlefield[0].tapped is True

def test_smoke_limits_creature_untap(all_cards):
    smoke = next(card for card in all_cards if card.name == "Smoke")
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
    orb = next(card for card in all_cards if card.name == "Winter Orb")
    island = next(card for card in all_cards if card.name == "Island")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=orb, tapped=False)])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=island, tapped=True), Permanent(card=island, tapped=True)],
    )
    game = Game(players=[p1, p2])

    untapped = game.resolve_untap_step(1)

    assert untapped == 1

def test_meekstone_prevents_big_creature_untap(all_cards):
    meekstone = next(card for card in all_cards if card.name == "Meekstone")
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
    mana_flare = next(card for card in all_cards if card.name == "Mana Flare")
    island = next(card for card in all_cards if card.name == "Island")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=mana_flare), Permanent(card=island)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    ok = game.tap_land_for_mana(0, "Island")

    assert ok
    assert p1.mana_pool["U"] == 2

def test_mana_pool_empties_between_steps(all_cards):
    island = next(card for card in all_cards if card.name == "Island")
    p1 = PlayerState(name="P1", mana_pool={"W": 0, "U": 2, "B": 0, "R": 0, "G": 0, "C": 1})
    p2 = PlayerState(name="P2", library=[island])
    game = Game(players=[p1, p2])

    game.resolve_upkeep(1)

    assert p1.mana_pool["U"] == 0
    assert p1.mana_pool["C"] == 0

def test_jade_statue_animates_until_end_combat(all_cards):
    statue = next(card for card in all_cards if card.name == "Jade Statue")
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
    hive = next(card for card in all_cards if card.name == "The Hive")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=hive)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "The Hive", target_player_index=1)

    assert result.supported
    assert any(perm.card.name == "Wasp" for perm in p1.battlefield)

def test_animate_wall_allows_wall_to_attack(all_cards):
    animate_wall = next(card for card in all_cards if card.name == "Animate Wall")
    wall = next(card for card in all_cards if card.name == "Wall of Stone")
    p1 = PlayerState(name="P1", hand=[animate_wall])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=wall)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Animate Wall", target_player_index=1)

    assert result.supported
    wall_perm = p2.battlefield[0]
    assert game.can_attack(wall_perm, defending_player_index=0) is True

def test_black_lotus_is_classified_supported(all_cards):
    lotus = next(card for card in all_cards if card.name == "Black Lotus")
    classification = classify_card(lotus)
    assert classification.supported

def test_castle_buffs_untapped_creatures_toughness(all_cards):
    castle = next(card for card in all_cards if card.name == "Castle")
    bear = _mk_card("Guard", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[castle], battlefield=[Permanent(card=bear, tapped=False)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Castle", target_player_index=0)

    assert result.supported
    assert p1.battlefield[0].effective_toughness >= 4

def test_circle_of_protection_activation_sets_prevention(all_cards):
    cop = next(card for card in all_cards if card.name == "Circle of Protection: Blue")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=cop)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Circle of Protection: Blue", target_player_index=0)

    assert result.supported
    assert p1.damage_prevention_pool == 1

def test_conversion_sacrifices_on_upkeep_without_white_mana(all_cards):
    conversion = next(card for card in all_cards if card.name == "Conversion")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=conversion)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert not p1.battlefield
    assert any(card.name == "Conversion" for card in p1.graveyard)

def test_dwarven_warriors_can_grant_unblockable(all_cards):
    warriors = next(card for card in all_cards if card.name == "Dwarven Warriors")
    bear = _mk_card("Small Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=warriors)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Dwarven Warriors", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("cant_be_blocked_until_eot") is True

def test_nightmare_dynamic_power_toughness_by_swamps(all_cards):
    nightmare = next(card for card in all_cards if card.name == "Nightmare")
    swamp = next(card for card in all_cards if card.name == "Swamp")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=nightmare), Permanent(card=swamp), Permanent(card=swamp)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game._refresh_dynamic_creatures()
    nm = p1.battlefield[0]
    assert nm.effective_power == 2
    assert nm.effective_toughness == 2

def test_sedge_troll_gets_bonus_with_swamp(all_cards):
    troll = next(card for card in all_cards if card.name == "Sedge Troll")
    swamp = next(card for card in all_cards if card.name == "Swamp")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=troll), Permanent(card=swamp)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game._refresh_dynamic_creatures()
    tr = p1.battlefield[0]
    assert tr.effective_power >= 3
    assert tr.effective_toughness >= 3

def test_balance_equalizes_lands_creatures_and_hand(all_cards):
    balance = next(card for card in all_cards if card.name == "Balance")
    plains = next(card for card in all_cards if card.name == "Plains")
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
    forcefield = next(card for card in all_cards if card.name == "Forcefield")
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
    gloom = next(card for card in all_cards if card.name == "Gloom")
    white_spell = _mk_card("White Test", "Sorcery", "Target player loses 3 life.", colors=("W",))
    p1 = PlayerState(name="P1", hand=[gloom])
    p2 = PlayerState(name="P2", hand=[white_spell], life=20)
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Gloom", target_player_index=1)
    result = game.cast_from_hand(1, "White Test", target_player_index=0)

    assert result.supported
    assert any("taxed by gloom" in line.lower() for line in game.log)

def test_kormus_bell_animates_swamps(all_cards):
    bell = next(card for card in all_cards if card.name == "Kormus Bell")
    swamp = next(card for card in all_cards if card.name == "Swamp")
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
    living = next(card for card in all_cards if card.name == "Living Lands")
    forest = next(card for card in all_cards if card.name == "Forest")
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
    library = next(card for card in all_cards if card.name == "Library of Leng")
    p1 = PlayerState(name="P1", hand=[library])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Library of Leng", target_player_index=0)

    assert result.supported
    assert p1.has_no_max_hand_size is True

def test_natural_selection_reorders_top_three(all_cards):
    natural = next(card for card in all_cards if card.name == "Natural Selection")
    a = _mk_card("A", "Sorcery")
    b = _mk_card("B", "Sorcery")
    c = _mk_card("C", "Sorcery")
    d = _mk_card("D", "Sorcery")
    p1 = PlayerState(name="P1", hand=[natural])
    p2 = PlayerState(name="P2", library=[a, b, c, d])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Natural Selection", target_player_index=1)

    assert result.supported
    assert [card.name for card in p2.library[:3]] == ["C", "B", "A"]

def test_word_of_command_forces_play_from_hand(all_cards):
    word = next(card for card in all_cards if card.name == "Word of Command")
    card_in_hand = _mk_card("Victim Spell", "Sorcery")
    p1 = PlayerState(name="P1", hand=[word])
    p2 = PlayerState(name="P2", hand=[card_in_hand])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Word of Command", target_player_index=1)

    assert result.supported
    assert len(p2.hand) == 0
    assert any(card.name == "Victim Spell" for card in p2.graveyard)

def test_magical_hack_marks_target_text_modified(all_cards):
    hack = next(card for card in all_cards if card.name == "Magical Hack")
    bear = _mk_card("Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[hack])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Magical Hack", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("text_modified") is True

def test_sleight_of_mind_marks_target_text_modified(all_cards):
    sleight = next(card for card in all_cards if card.name == "Sleight of Mind")
    bear = _mk_card("Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[sleight])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Sleight of Mind", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("text_modified") is True

def test_blaze_of_glory_sets_forced_blocking_marker(all_cards):
    blaze = next(card for card in all_cards if card.name == "Blaze of Glory")
    bear = _mk_card("Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[blaze])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Blaze of Glory", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("must_block_all_until_eot") is True

def test_camouflage_resolves_supported(all_cards):
    camouflage = next(card for card in all_cards if card.name == "Camouflage")
    p1 = PlayerState(name="P1", hand=[camouflage])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Camouflage", target_player_index=1)

    assert result.supported
    assert any("pile blocking" in line.lower() for line in game.log)

def test_cyclopean_tomb_marks_land_as_swamp(all_cards):
    tomb = next(card for card in all_cards if card.name == "Cyclopean Tomb")
    plains = next(card for card in all_cards if card.name == "Plains")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=tomb)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=plains)])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Cyclopean Tomb", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("land_type_override") == "swamp"

def test_false_orders_marks_creature_removed_from_combat(all_cards):
    false_orders = next(card for card in all_cards if card.name == "False Orders")
    bear = _mk_card("Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[false_orders])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "False Orders", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("removed_from_combat") is True

def test_raging_river_casts_as_supported_permanent(all_cards):
    river = next(card for card in all_cards if card.name == "Raging River")
    p1 = PlayerState(name="P1", hand=[river])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Raging River", target_player_index=1)

    assert result.supported
    assert any(perm.card.name == "Raging River" for perm in p1.battlefield)

def test_sunglasses_of_urza_sets_white_as_red_flag(all_cards):
    sunglasses = next(card for card in all_cards if card.name == "Sunglasses of Urza")
    p1 = PlayerState(name="P1", hand=[sunglasses])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Sunglasses of Urza", target_player_index=1)

    assert result.supported
    assert p1.can_spend_white_as_red is True

def test_cockatrice_classifies_supported(all_cards):
    cockatrice = next(card for card in all_cards if card.name == "Cockatrice")
    classification = classify_card(cockatrice)
    assert classification.supported

def test_force_of_nature_classifies_supported(all_cards):
    force = next(card for card in all_cards if card.name == "Force of Nature")
    classification = classify_card(force)
    assert classification.supported

def test_hypnotic_specter_classifies_supported(all_cards):
    specter = next(card for card in all_cards if card.name == "Hypnotic Specter")
    classification = classify_card(specter)
    assert classification.supported

def test_juggernaut_classifies_supported(all_cards):
    juggernaut = next(card for card in all_cards if card.name == "Juggernaut")
    classification = classify_card(juggernaut)
    assert classification.supported

def test_banding_keyword_cards_classify_supported(all_cards):
    benalish_hero = next(card for card in all_cards if card.name == "Benalish Hero")
    mesa_pegasus = next(card for card in all_cards if card.name == "Mesa Pegasus")
    timber_wolves = next(card for card in all_cards if card.name == "Timber Wolves")

    assert classify_card(benalish_hero).supported
    assert classify_card(mesa_pegasus).supported
    assert classify_card(timber_wolves).supported

def test_helm_of_chatzuk_grants_banding_until_eot(all_cards):
    helm = next(card for card in all_cards if card.name == "Helm of Chatzuk")
    bear = _mk_card("Band Target", "Creature — Bear")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=helm)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Helm of Chatzuk", target_player_index=1)

    assert result.supported
    assert p1.battlefield[0].tapped is True
    assert p2.battlefield[0].metadata.get("gains_banding_until_eot") is True

def test_helm_of_chatzuk_requires_valid_creature_target(all_cards):
    helm = next(card for card in all_cards if card.name == "Helm of Chatzuk")
    island = next(card for card in all_cards if card.name == "Island")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=helm)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=island)])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Helm of Chatzuk", target_player_index=1)

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
    clone = next(card for card in all_cards if card.name == "Clone")
    fork = next(card for card in all_cards if card.name == "Fork")

    assert classify_card(clone).supported
    assert classify_card(fork).supported

def test_gaeas_liege_activation_turns_land_into_forest(all_cards):
    liege = next(card for card in all_cards if card.name == "Gaea's Liege")
    plains = next(card for card in all_cards if card.name == "Plains")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=liege)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=plains)])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Gaea's Liege", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("land_type_override") == "forest"

def test_nettling_imp_marks_target_for_attack(all_cards):
    imp = next(card for card in all_cards if card.name == "Nettling Imp")
    bear = _mk_card("Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=imp)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Nettling Imp", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("must_attack_until_eot") is True

def test_stone_giant_grants_temp_flying_and_delayed_destroy(all_cards):
    giant = next(card for card in all_cards if card.name == "Stone Giant")
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
    clone = next(card for card in all_cards if card.name == "Clone")
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
    fork = next(card for card in all_cards if card.name == "Fork")
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
    contract = next(card for card in all_cards if card.name == "Contract from Below")
    island = next(card for card in all_cards if card.name == "Island")

    p1 = PlayerState(name="P1", hand=[contract, island], library=[island] * 10)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Contract from Below", target_player_index=1)

    assert result.supported
    assert len(p1.hand) == 7

def test_demonic_attorney_antes_top_card_for_each_player(all_cards):
    attorney = next(card for card in all_cards if card.name == "Demonic Attorney")
    island = next(card for card in all_cards if card.name == "Island")

    p1 = PlayerState(name="P1", hand=[attorney], library=[island, island])
    p2 = PlayerState(name="P2", library=[island, island])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Demonic Attorney", target_player_index=1)

    assert result.supported
    assert len(p1.library) == 1
    assert len(p2.library) == 1

def test_copy_artifact_copies_artifact_on_entry(all_cards):
    copy_artifact = next(card for card in all_cards if card.name == "Copy Artifact")
    lotus = next(card for card in all_cards if card.name == "Black Lotus")

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
    juggernaut = next(card for card in all_cards if card.name == "Juggernaut")
    wall = next(card for card in all_cards if card.name == "Wall of Stone")

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
            "seed": 4041,
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
            "seed": 4042,
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
            "seed": 12345,
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
            "seed": 22334,
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
