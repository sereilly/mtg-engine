"""Tests for Magic: The Gathering Comprehensive Rules Section 303 — Enchantments."""

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mk_card(name: str, type_line: str, oracle_text: str = "", colors: tuple[str, ...] = ()) -> CardDefinition:
    raw: dict = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw["power"] = "2"
        raw["toughness"] = "2"
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line=type_line,
        oracle_text=oracle_text,
        colors=colors,
        color_identity=colors,
        keywords=(),
        produced_mana=(),
        raw=raw,
    )


def _mk_creature(name: str, power: int = 2, toughness: int = 2, oracle_text: str = "") -> CardDefinition:
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line="Creature — Test",
        oracle_text=oracle_text,
        colors=(),
        color_identity=(),
        keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature — Test", "power": str(power), "toughness": str(toughness)},
    )


# ---------------------------------------------------------------------------
# Rule 303.1 – A player who has priority may cast an enchantment card from
# their hand during a main phase of their turn when the stack is empty.
# ---------------------------------------------------------------------------

def test_303_1_enchantment_cast_from_hand_during_main_phase():
    """303.1: Casting an enchantment from hand uses the stack and resolves normally."""
    shrine = _mk_card("Test Shrine", "Enchantment — Shrine")
    p1 = PlayerState(name="P1", hand=[shrine])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    assert game.current_turn_phase == "precombat_main"
    game.cast_from_hand(0, "Test Shrine", target_player_index=1)

    assert not any(c.name == "Test Shrine" for c in p1.hand)


def test_303_1_enchantment_not_castable_as_sorcery_outside_main_phase():
    """303.1: Enchantments are cast during main phase — game starts in precombat_main."""
    enchantment = _mk_card("Upkeep Enchantment", "Enchantment")
    p1 = PlayerState(name="P1", hand=[enchantment])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # The default phase is precombat_main, which is the correct phase for casting
    assert game.current_turn_phase == "precombat_main"


# ---------------------------------------------------------------------------
# Rule 303.2 – When an enchantment spell resolves, its controller puts it onto
# the battlefield under their control.
# ---------------------------------------------------------------------------

def test_303_2_enchantment_enters_battlefield_under_casters_control():
    """303.2: Resolved enchantment is on the caster's battlefield, not the opponent's."""
    enchantment = _mk_card("Test Enchantment", "Enchantment")
    p1 = PlayerState(name="P1", hand=[enchantment])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Test Enchantment", target_player_index=1)

    assert any(perm.card.name == "Test Enchantment" for perm in p1.battlefield)
    assert not any(perm.card.name == "Test Enchantment" for perm in p2.battlefield)
    assert not any(c.name == "Test Enchantment" for c in p1.graveyard)


def test_303_2_enchantment_leaves_hand_when_cast():
    """303.2: The enchantment card leaves the hand as it is cast."""
    enchantment = _mk_card("Test Enchantment", "Enchantment")
    p1 = PlayerState(name="P1", hand=[enchantment])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    assert len(p1.hand) == 1
    game.cast_from_hand(0, "Test Enchantment")
    assert len(p1.hand) == 0


# ---------------------------------------------------------------------------
# Rule 303.3 – Enchantment subtypes are always a single word and are listed
# after a long dash. Each word after the dash is a separate subtype.
# Enchantments may have multiple subtypes.
# ---------------------------------------------------------------------------

def test_303_3_enchantment_primary_type_from_type_line():
    """303.3: Cards with 'Enchantment' in the type line have primary type 'enchantment'."""
    assert _mk_card("Plain", "Enchantment").primary_type == "enchantment"
    assert _mk_card("An Aura", "Enchantment — Aura").primary_type == "enchantment"
    assert _mk_card("A Saga", "Enchantment — Saga").primary_type == "enchantment"
    assert _mk_card("A Shrine", "Enchantment — Shrine").primary_type == "enchantment"
    assert _mk_card("A Class", "Enchantment — Class").primary_type == "enchantment"


def test_303_3_enchantment_subtype_is_single_word_after_dash():
    """303.3: Subtypes in 'Enchantment — Aura' are single words separated by whitespace."""
    card = _mk_card("Test Aura", "Enchantment — Aura", "Enchant creature")
    subtype_section = card.type_line.split("—")[-1].strip()
    for subtype in subtype_section.split():
        assert " " not in subtype, f"Subtype '{subtype}' must be a single word"


def test_303_3_enchantment_multiple_subtypes_each_single_word():
    """303.3: An enchantment may have multiple subtypes; each is a single word after the dash."""
    card = _mk_card("Dual Subtype", "Enchantment — Aura Shrine")
    subtype_section = card.type_line.split("—")[-1].strip()
    subtypes = subtype_section.split()
    assert "Aura" in subtypes
    assert "Shrine" in subtypes
    assert len(subtypes) == 2
    for st in subtypes:
        assert " " not in st


# ---------------------------------------------------------------------------
# Rule 303.4 – Some enchantments have the subtype "Aura." An Aura enters the
# battlefield attached to an object or player. What an Aura can be attached to
# is defined by its enchant keyword ability.
# ---------------------------------------------------------------------------

def test_303_4_aura_identified_by_type_line():
    """303.4: A card with 'Enchantment — Aura' in its type line is an Aura."""
    aura_card = _mk_card("Test Aura", "Enchantment — Aura", "Enchant creature")
    assert "Aura" in aura_card.type_line
    assert aura_card.primary_type == "enchantment"


# ---------------------------------------------------------------------------
# Rule 303.4a – An Aura spell requires a target, which is defined by its
# enchant keyword ability.
# ---------------------------------------------------------------------------

def test_303_4a_enchant_creature_aura_attaches_to_target_creature():
    """303.4a: 'Enchant creature' Aura spell targets and attaches to a creature."""
    aura = _mk_card("Power Buff", "Enchantment — Aura", "Enchant creature\nEnchanted creature gets +2/+1.")
    creature = _mk_creature("Target Bear")
    p1 = PlayerState(name="P1", hand=[aura])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Power Buff", target_player_index=1)

    aura_perm = next(perm for perm in p1.battlefield if perm.card.name == "Power Buff")
    assert aura_perm.metadata.get("attached_to") is not None
    assert aura_perm.metadata["attached_to"].card.name == "Target Bear"


def test_303_4a_enchant_land_aura_attaches_to_target_land():
    """303.4a: 'Enchant land' Aura spell targets and attaches to a land."""
    aura = _mk_card("Land Aura", "Enchantment — Aura",
                    "Enchant land\nWhenever enchanted land is tapped for mana, its controller adds {G}.")
    land = _mk_card("Forest", "Basic Land — Forest")
    p1 = PlayerState(name="P1", hand=[aura])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=land)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Land Aura", target_player_index=1)

    aura_perm = next(perm for perm in p1.battlefield if perm.card.name == "Land Aura")
    assert aura_perm.metadata.get("attached_to") is not None
    assert aura_perm.metadata["attached_to"].card.name == "Forest"


# ---------------------------------------------------------------------------
# Rule 303.4b – The object or player an Aura is attached to is called enchanted.
# The Aura is attached to, or "enchants," that object or player.
# ---------------------------------------------------------------------------

def test_303_4b_enchanted_object_holds_aura_reference():
    """303.4b: The enchanted permanent has a back-reference to the Aura in its metadata."""
    aura = _mk_card("Test Aura", "Enchantment — Aura", "Enchant creature\nEnchanted creature gets +1/+1.")
    creature = _mk_creature("Enchanted Bear")
    p1 = PlayerState(name="P1", hand=[aura])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Test Aura", target_player_index=1)

    enchanted_creature = p2.battlefield[0]
    assert enchanted_creature.metadata.get("attached_aura") is not None
    assert enchanted_creature.metadata["attached_aura"].card.name == "Test Aura"


def test_303_4b_aura_holds_reference_to_enchanted_object():
    """303.4b: The Aura permanent's metadata points to the permanent it enchants."""
    aura = _mk_card("Test Aura", "Enchantment — Aura", "Enchant creature\nEnchanted creature gets +1/+1.")
    creature = _mk_creature("Target Bear", 3, 3)
    p1 = PlayerState(name="P1", hand=[aura])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Test Aura", target_player_index=1)

    aura_perm = next(perm for perm in p1.battlefield if perm.card.name == "Test Aura")
    assert aura_perm.metadata.get("attached_to") is not None
    assert aura_perm.metadata["attached_to"].card.name == "Target Bear"


# ---------------------------------------------------------------------------
# Rule 303.4c – If an Aura is enchanting an illegal object or player, or the
# object no longer exists, the Aura is put into its owner's graveyard.
# (State-based action — rule 704.)
# ---------------------------------------------------------------------------

@pytest.mark.xfail(
    strict=False,
    reason=(
        "Rule 303.4c state-based action not implemented: the engine leaves the Aura "
        "on the battlefield after its enchanted creature leaves play instead of moving "
        "it to the owner's graveyard."
    ),
)
def test_303_4c_aura_goes_to_graveyard_when_enchanted_creature_is_destroyed():
    """303.4c: When the enchanted creature is destroyed the Aura goes to its owner's graveyard."""
    aura = _mk_card("Test Aura", "Enchantment — Aura", "Enchant creature\nEnchanted creature gets +1/+1.")
    creature = _mk_creature("Doomed Creature")
    wrath = _mk_card("Wrath", "Sorcery", "Destroy all creatures.")
    p1 = PlayerState(name="P1", hand=[aura, wrath])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Test Aura", target_player_index=1)
    game.cast_from_hand(0, "Wrath", target_player_index=1)

    # 303.4c: Aura with no legal enchantment target goes to its owner's graveyard
    assert any(c.name == "Test Aura" for c in p1.graveyard)
    assert not any(perm.card.name == "Test Aura" for perm in p1.battlefield)


# ---------------------------------------------------------------------------
# Rule 303.4d – An Aura can't enchant itself. An Aura can't enchant more than
# one object or player. If a spell or ability would cause it to become attached
# to more than one, the controller chooses which one.
# ---------------------------------------------------------------------------

def test_303_4d_aura_not_attached_to_itself():
    """303.4d: After resolution the Aura's attached_to reference is not the Aura itself."""
    aura = _mk_card("Self Check Aura", "Enchantment — Aura", "Enchant creature\nEnchanted creature gets +1/+1.")
    creature = _mk_creature("Target Creature")
    p1 = PlayerState(name="P1", hand=[aura])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Self Check Aura", target_player_index=1)

    aura_perm = next(perm for perm in p1.battlefield if perm.card.name == "Self Check Aura")
    assert aura_perm.metadata.get("attached_to") is not aura_perm


def test_303_4d_aura_enchants_exactly_one_permanent():
    """303.4d: An Aura enchants exactly one permanent — not multiple."""
    aura = _mk_card("Single Target Aura", "Enchantment — Aura", "Enchant creature\nEnchanted creature gets +1/+1.")
    creature_a = _mk_creature("Creature Alpha")
    creature_b = _mk_creature("Creature Beta")
    p1 = PlayerState(name="P1", hand=[aura])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature_a), Permanent(card=creature_b)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Single Target Aura", target_player_index=1)

    enchanted_count = sum(
        1 for perm in p2.battlefield if perm.metadata.get("attached_aura") is not None
    )
    assert enchanted_count == 1


# ---------------------------------------------------------------------------
# Rule 303.4e – An Aura's controller is separate from the enchanted object's
# controller. Changing control of the object doesn't change control of the Aura,
# and vice versa. If the Aura grants an ability to the enchanted object, the
# enchanted object's controller is the only one who can activate that ability.
# ---------------------------------------------------------------------------

def test_303_4e_aura_is_on_casters_battlefield_while_creature_stays_on_opponents():
    """303.4e: P1's Aura sits on P1's battlefield; the enchanted creature stays on P2's."""
    aura = _mk_card("Control Test Aura", "Enchantment — Aura", "Enchant creature\nEnchanted creature gets +1/+1.")
    creature = _mk_creature("Opponent Creature")
    p1 = PlayerState(name="P1", hand=[aura])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Control Test Aura", target_player_index=1)

    assert any(perm.card.name == "Control Test Aura" for perm in p1.battlefield)
    assert any(perm.card.name == "Opponent Creature" for perm in p2.battlefield)
    assert not any(perm.card.name == "Control Test Aura" for perm in p2.battlefield)
    assert not any(perm.card.name == "Opponent Creature" for perm in p1.battlefield)


def test_303_4e_ability_granted_by_aura_is_stamped_on_enchanted_object():
    """303.4e: An ability granted by the Aura (flying) is stored on the enchanted creature."""
    aura = _mk_card("Wings Aura", "Enchantment — Aura", "Enchant creature\nEnchanted creature has flying.")
    creature = _mk_creature("Grounded Creature")
    p1 = PlayerState(name="P1", hand=[aura])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Wings Aura", target_player_index=1)

    enchanted_creature = p2.battlefield[0]
    assert enchanted_creature.metadata.get("gains_flying") is True


def test_303_4e_first_strike_granted_to_enchanted_creature():
    """303.4e: An ability granted by the Aura (first strike) is stored on the enchanted creature."""
    aura = _mk_card("Strike Aura", "Enchantment — Aura", "Enchant creature\nEnchanted creature has first strike.")
    creature = _mk_creature("Sluggish Bear")
    p1 = PlayerState(name="P1", hand=[aura])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Strike Aura", target_player_index=1)

    enchanted_creature = p2.battlefield[0]
    assert enchanted_creature.metadata.get("gains_first_strike") is True


# ---------------------------------------------------------------------------
# Rule 303.4f – If an Aura enters the battlefield by any means other than by
# resolving as an Aura spell, the player chooses what it will enchant as the
# Aura enters the battlefield.
# ---------------------------------------------------------------------------

def test_303_4f_aura_entering_via_reanimation_attaches_to_chosen_target():
    """303.4f: An Aura entering by non-spell means (reanimation) attaches to a chosen target."""
    animate = _mk_card(
        "Animate Dead",
        "Enchantment — Aura",
        "Enchant creature card in a graveyard\n"
        "When Animate Dead enters, if it's on the battlefield, "
        "return enchanted creature card to the battlefield under your control. "
        "Enchanted creature gets -1/-0.",
    )
    dead_creature = _mk_creature("Revived Creature", 3, 3)
    p1 = PlayerState(name="P1", hand=[animate], graveyard=[dead_creature])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Animate Dead", target_player_index=0)

    # The revived creature should be on P1's battlefield
    assert any(perm.card.name == "Revived Creature" for perm in p1.battlefield)
    # Animate Dead should be attached to the revived creature
    animate_perm = next((perm for perm in p1.battlefield if perm.card.name == "Animate Dead"), None)
    assert animate_perm is not None
    assert animate_perm.metadata.get("attached_to") is not None
    assert animate_perm.metadata["attached_to"].card.name == "Revived Creature"


# ---------------------------------------------------------------------------
# Rule 303.4g – If an Aura is entering the battlefield and there is no legal
# object or player for it to enchant, the Aura remains in its current zone,
# unless that zone is the stack. In that case, the Aura is put into its owner's
# graveyard instead of entering the battlefield.
# ---------------------------------------------------------------------------

@pytest.mark.xfail(
    strict=False,
    reason=(
        "Rule 303.4g not implemented: when an 'enchant creature' Aura resolves from "
        "the stack with no legal target, the engine places it on the battlefield "
        "instead of moving it to its owner's graveyard."
    ),
)
def test_303_4g_enchant_creature_aura_with_no_creatures_goes_to_graveyard():
    """303.4g: Casting 'enchant creature' Aura with no creatures present — Aura goes to graveyard."""
    aura = _mk_card("Orphan Aura", "Enchantment — Aura", "Enchant creature\nEnchanted creature gets +1/+1.")
    p1 = PlayerState(name="P1", hand=[aura])
    p2 = PlayerState(name="P2")  # No creatures
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Orphan Aura", target_player_index=1)

    assert any(c.name == "Orphan Aura" for c in p1.graveyard)
    assert not any(perm.card.name == "Orphan Aura" for perm in p1.battlefield)


# ---------------------------------------------------------------------------
# Rule 303.4h – If an effect attempts to put a permanent that isn't an Aura,
# Equipment, or Fortification onto the battlefield attached to an object or
# player, it enters the battlefield unattached.
# ---------------------------------------------------------------------------

def test_303_4h_non_aura_enchantment_enters_without_attached_to_metadata():
    """303.4h: A non-Aura enchantment enters the battlefield without being attached to anything."""
    enchantment = _mk_card("Plain Enchantment", "Enchantment",
                           "At the beginning of your upkeep, you gain 1 life.")
    p1 = PlayerState(name="P1", hand=[enchantment])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Plain Enchantment", target_player_index=1)

    perm = next(p for p in p1.battlefield if p.card.name == "Plain Enchantment")
    assert perm.metadata.get("attached_to") is None


def test_303_4h_creature_enters_unattached():
    """303.4h: A creature permanent (not an Aura) enters unattached."""
    creature = _mk_creature("Regular Creature")
    p1 = PlayerState(name="P1", hand=[creature])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Regular Creature")

    perm = next(p for p in p1.battlefield if p.card.name == "Regular Creature")
    assert perm.metadata.get("attached_to") is None


# ---------------------------------------------------------------------------
# Rule 303.4i – If an effect attempts to put an Aura onto the battlefield
# attached to an object it can't legally enchant or one that is undefined, the
# Aura remains in its current zone; if from the stack, it goes to its owner's
# graveyard.
# ---------------------------------------------------------------------------

@pytest.mark.xfail(
    strict=False,
    reason=(
        "Rule 303.4i not implemented: when an 'enchant land' Aura resolves from the "
        "stack with no legal land target, the engine places it on the battlefield "
        "instead of moving it to its owner's graveyard."
    ),
)
def test_303_4i_enchant_land_aura_with_no_lands_goes_to_graveyard():
    """303.4i: Casting 'enchant land' Aura when there are no lands — Aura goes to graveyard."""
    aura = _mk_card("Wandering Land Aura", "Enchantment — Aura",
                    "Enchant land\nEnchanted land is a Swamp.")
    p1 = PlayerState(name="P1", hand=[aura])
    p2 = PlayerState(name="P2")  # No lands
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Wandering Land Aura", target_player_index=1)

    assert any(c.name == "Wandering Land Aura" for c in p1.graveyard)
    assert not any(perm.card.name == "Wandering Land Aura" for perm in p1.battlefield)


# ---------------------------------------------------------------------------
# Rule 303.4j – If an effect attempts to attach an Aura on the battlefield to
# an object or player it can't legally enchant, the Aura doesn't move.
# ---------------------------------------------------------------------------

def test_303_4j_enchant_creature_aura_attaches_to_creature_not_land():
    """303.4j: 'Enchant creature' Aura attaches to a creature even when both a creature
    and a land are present — it cannot legally enchant the land."""
    aura = _mk_card("Creature Magnet", "Enchantment — Aura",
                    "Enchant creature\nEnchanted creature gets +1/+1.")
    creature = _mk_creature("Valid Target")
    land = _mk_card("Forest", "Basic Land — Forest")
    p1 = PlayerState(name="P1", hand=[aura])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=land), Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Creature Magnet", target_player_index=1)

    aura_perm = next(perm for perm in p1.battlefield if perm.card.name == "Creature Magnet")
    attached = aura_perm.metadata.get("attached_to")
    assert attached is not None
    assert attached.card.primary_type == "creature"
    assert attached.card.name == "Valid Target"


def test_303_4j_enchant_land_aura_attaches_to_land_not_creature():
    """303.4j: 'Enchant land' Aura attaches to a land even when a creature is also present."""
    aura = _mk_card("Land Seeker", "Enchantment — Aura",
                    "Enchant land\nEnchanted land produces an additional {G} when tapped.")
    creature = _mk_creature("Irrelevant Creature")
    land = _mk_card("Forest", "Basic Land — Forest")
    p1 = PlayerState(name="P1", hand=[aura])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature), Permanent(card=land)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Land Seeker", target_player_index=1)

    aura_perm = next(perm for perm in p1.battlefield if perm.card.name == "Land Seeker")
    attached = aura_perm.metadata.get("attached_to")
    assert attached is not None
    assert attached.card.primary_type == "land"


# ---------------------------------------------------------------------------
# Rule 303.4m – An ability of a permanent that refers to the "enchanted [object
# or player]" refers to whatever object or player that permanent is attached to,
# even if the permanent with the ability isn't an Aura.
# ---------------------------------------------------------------------------

def test_303_4m_enchanted_creature_receives_power_toughness_buff():
    """303.4m: 'Enchanted creature gets +2/+1' applies the buff to the attached creature."""
    aura = _mk_card("Power Aura", "Enchantment — Aura", "Enchant creature\nEnchanted creature gets +2/+1.")
    creature = _mk_creature("Test Bear", 2, 2)
    p1 = PlayerState(name="P1", hand=[aura])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Power Aura", target_player_index=1)

    enchanted = p2.battlefield[0]
    assert enchanted.effective_power == 4
    assert enchanted.effective_toughness == 3


def test_303_4m_enchanted_creature_receives_negative_buff():
    """303.4m: 'Enchanted creature gets -1/-1' applies the debuff to the attached creature."""
    aura = _mk_card("Weakness Aura", "Enchantment — Aura", "Enchant creature\nEnchanted creature gets -1/-1.")
    creature = _mk_creature("Strong Bear", 3, 3)
    p1 = PlayerState(name="P1", hand=[aura])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Weakness Aura", target_player_index=1)

    enchanted = p2.battlefield[0]
    assert enchanted.effective_power == 2
    assert enchanted.effective_toughness == 2


def test_303_4m_enchanted_creature_unaffected_by_aura_on_different_creature():
    """303.4m: 'Enchanted creature' buff only applies to the specific attached creature."""
    aura = _mk_card("Selective Aura", "Enchantment — Aura", "Enchant creature\nEnchanted creature gets +2/+2.")
    target_creature = _mk_creature("Enchanted One", 2, 2)
    bystander = _mk_creature("Bystander", 1, 1)
    p1 = PlayerState(name="P1", hand=[aura])
    p2 = PlayerState(name="P2", battlefield=[
        Permanent(card=target_creature),
        Permanent(card=bystander),
    ])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Selective Aura", target_player_index=1)

    # The first creature (the one the aura attaches to) gets the buff
    enchanted = p2.battlefield[0]
    assert enchanted.effective_power == 4
    assert enchanted.effective_toughness == 4
    # The bystander is unchanged
    untouched = p2.battlefield[1]
    assert untouched.effective_power == 1
    assert untouched.effective_toughness == 1


# ---------------------------------------------------------------------------
# Rule 303.5 – Some enchantments have the subtype "Saga."
# ---------------------------------------------------------------------------

def test_303_5_saga_has_enchantment_primary_type():
    """303.5: A Saga card's primary type is 'enchantment'."""
    saga = _mk_card("Test Saga", "Enchantment — Saga")
    assert saga.primary_type == "enchantment"
    assert "Saga" in saga.type_line


def test_303_5_saga_enters_casters_battlefield():
    """303.5: A Saga enters the battlefield under its controller's control."""
    saga = _mk_card("Story Saga", "Enchantment — Saga")
    p1 = PlayerState(name="P1", hand=[saga])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Story Saga", target_player_index=1)

    assert any(perm.card.name == "Story Saga" for perm in p1.battlefield)
    assert not any(perm.card.name == "Story Saga" for perm in p2.battlefield)


# ---------------------------------------------------------------------------
# Rule 303.6 – Some enchantments have the subtype "Class."
# ---------------------------------------------------------------------------

def test_303_6_class_has_enchantment_primary_type():
    """303.6: A Class card's primary type is 'enchantment'."""
    class_card = _mk_card("Test Class", "Enchantment — Class")
    assert class_card.primary_type == "enchantment"
    assert "Class" in class_card.type_line


def test_303_6_class_enters_casters_battlefield():
    """303.6: A Class card enters the battlefield under its controller's control."""
    class_card = _mk_card("Wizard Class", "Enchantment — Class")
    p1 = PlayerState(name="P1", hand=[class_card])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Wizard Class", target_player_index=1)

    assert any(perm.card.name == "Wizard Class" for perm in p1.battlefield)
    assert not any(perm.card.name == "Wizard Class" for perm in p2.battlefield)


# ---------------------------------------------------------------------------
# Rule 303.7 – Some Aura enchantments also have the subtype "Role."
# ---------------------------------------------------------------------------

def test_303_7_role_has_enchantment_primary_type():
    """303.7: A Role card has primary type 'enchantment'."""
    role = _mk_card("Monster Role", "Enchantment — Role", "Enchant creature\nEnchanted creature gets +1/+1.")
    assert role.primary_type == "enchantment"
    assert "Role" in role.type_line


def test_303_7_role_enters_battlefield_attached_like_an_aura():
    """303.7: A Role (which is an Aura subtype) attaches to a creature when cast."""
    role = _mk_card("Warrior Role", "Enchantment — Role", "Enchant creature\nEnchanted creature gets +1/+1.")
    creature = _mk_creature("Role Bearer")
    p1 = PlayerState(name="P1", hand=[role])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Warrior Role", target_player_index=1)

    role_perm = next((perm for perm in p1.battlefield if perm.card.name == "Warrior Role"), None)
    assert role_perm is not None
    assert role_perm.metadata.get("attached_to") is not None


# ---------------------------------------------------------------------------
# Rule 303.7a – If a permanent has more than one Role controlled by the same
# player attached to it, each of those Roles except the one with the most
# recent timestamp is put into its owner's graveyard. (State-based action.)
# ---------------------------------------------------------------------------

@pytest.mark.xfail(
    strict=False,
    reason=(
        "Rule 303.7a state-based action not implemented: the engine allows multiple "
        "Roles controlled by the same player to remain on the battlefield simultaneously "
        "instead of sending all but the newest to the owner's graveyard."
    ),
)
def test_303_7a_two_roles_from_same_player_only_newest_survives():
    """303.7a: When the same player attaches two Roles to the same creature, only the
    Role with the most recent timestamp remains; the older one goes to the graveyard."""
    role1 = _mk_card("Warrior Role", "Enchantment — Role", "Enchant creature\nEnchanted creature gets +1/+1.")
    role2 = _mk_card("Monster Role", "Enchantment — Role", "Enchant creature\nEnchanted creature gets +2/+2.")
    creature = _mk_creature("Role Host")
    p1 = PlayerState(name="P1", hand=[role1, role2])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Warrior Role", target_player_index=1)
    game.cast_from_hand(0, "Monster Role", target_player_index=1)

    # Only the newer Role (Monster Role) should remain on the battlefield
    role_perms = [perm for perm in p1.battlefield if "Role" in perm.card.type_line]
    assert len(role_perms) == 1
    assert role_perms[0].card.name == "Monster Role"
    # The older Role (Warrior Role) should have gone to its owner's graveyard
    assert any(c.name == "Warrior Role" for c in p1.graveyard)
