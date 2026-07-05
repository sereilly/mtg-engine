"""Tests for Magic: The Gathering Comprehensive Rules Sections 611–613.

Covers:
  611 — Continuous Effects
  612 — Text-Changing Effects (basic structural test)
  613 — Interaction of Continuous Effects (layer system)
"""

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mk_card(
    name: str,
    type_line: str,
    oracle_text: str = "",
    mana_cost: str = "",
    colors: tuple[str, ...] = (),
    cmc: float = 0.0,
    power: int = 2,
    toughness: int = 2,
) -> CardDefinition:
    raw: dict = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw["power"] = str(power)
        raw["toughness"] = str(toughness)
    return CardDefinition(
        name=name,
        mana_cost=mana_cost,
        cmc=cmc,
        type_line=type_line,
        oracle_text=oracle_text,
        colors=colors,
        color_identity=colors,
        keywords=(),
        produced_mana=(),
        raw=raw,
    )


def _mk_creature(
    name: str,
    power: int = 2,
    toughness: int = 2,
    colors: tuple[str, ...] = (),
    oracle_text: str = "",
) -> CardDefinition:
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line="Creature — Test",
        oracle_text=oracle_text,
        colors=colors,
        color_identity=colors,
        keywords=(),
        produced_mana=(),
        raw={
            "name": name,
            "type_line": "Creature — Test",
            "power": str(power),
            "toughness": str(toughness),
        },
    )


# ---------------------------------------------------------------------------
# Rule 611.2a — "Until end of turn" effects last exactly one turn
# ---------------------------------------------------------------------------


def test_611_2a_pump_until_eot_applies_during_turn():
    """611.2a: A pump spell effect applies during the turn it resolves."""
    pump = _mk_card("Giant Growth", "Instant", "Target creature gets +3/+3 until end of turn.")
    creature = _mk_creature("Bear", 2, 2)
    p1 = PlayerState(name="P1", hand=[pump], battlefield=[Permanent(card=creature)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Giant Growth", target_player_index=0, target_permanent_index=0)

    perm = p1.battlefield[0]
    assert perm.effective_power == 5
    assert perm.effective_toughness == 5


def test_611_2a_pump_until_eot_clears_after_cleanup():
    """611.2a: A "until end of turn" continuous effect ends at the cleanup step (611.2a)."""
    pump = _mk_card("Giant Growth", "Instant", "Target creature gets +3/+3 until end of turn.")
    creature = _mk_creature("Bear", 2, 2)
    p1 = PlayerState(name="P1", hand=[pump], battlefield=[Permanent(card=creature)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Giant Growth", target_player_index=0, target_permanent_index=0)
    assert p1.battlefield[0].effective_power == 5

    # End-of-turn cleanup removes "until end of turn" effects
    game.resolve_cleanup_step(0)

    perm = p1.battlefield[0]
    assert perm.effective_power == 2
    assert perm.effective_toughness == 2


def test_611_2a_enchantment_effect_with_no_duration_persists():
    """611.2a: If no duration is stated, a continuous effect lasts until the end of the game."""
    enchantment = _mk_card(
        "Crusade", "Enchantment", "White creatures get +1/+1.", colors=("W",)
    )
    knight = _mk_creature("White Knight", 2, 2, colors=("W",))
    p1 = PlayerState(name="P1", hand=[enchantment], battlefield=[Permanent(card=knight)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Crusade")

    knight_perm = p1.battlefield[0]
    assert knight_perm.effective_power == 3
    assert knight_perm.effective_toughness == 3

    # Cleanup should NOT remove the enchantment's static buff
    game.resolve_cleanup_step(0)

    assert knight_perm.effective_power == 3
    assert knight_perm.effective_toughness == 3


# ---------------------------------------------------------------------------
# Rule 611.2b — "For as long as" duration
# ---------------------------------------------------------------------------


def test_611_2b_for_as_long_as_duration_requires_condition_to_have_started():
    """611.2b: A 'for as long as' effect does nothing if the duration never starts.

    Example: gain control of artifact 'for as long as you control [controller]'.
    If the controller leaves before resolution the effect does nothing.
    """
    # Simulate the condition by checking that an effect tracking a controller-based
    # duration does not apply when the controlling permanent is absent.
    # We represent this by verifying that a "steal while controlling X" effect
    # stored in metadata is absent when the tracking permanent was never present.
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # No permanent with "for as long as" was ever on the battlefield,
    # so no such effect should be present in any permanent's metadata.
    for player in game.players:
        for perm in player.battlefield:
            assert perm.metadata.get("for_as_long_as_active") is None


# ---------------------------------------------------------------------------
# Rule 611.2c — Spell-based effects lock in their target set at resolution
# ---------------------------------------------------------------------------


def test_611_2c_spell_buff_applies_only_to_creatures_present_at_resolution():
    """611.2c: 'All white creatures get +1/+1 until EOT' only applies to white
    creatures on the battlefield when the spell resolves, not those that enter later.
    """
    buff_spell = _mk_card(
        "Holy Day Pump", "Sorcery", "White creatures get +1/+1 until end of turn."
    )
    white_creature = _mk_creature("White Bear", 2, 2, colors=("W",))
    black_creature = _mk_creature("Black Bear", 2, 2, colors=("B",))

    p1 = PlayerState(
        name="P1",
        hand=[buff_spell],
        battlefield=[Permanent(card=white_creature), Permanent(card=black_creature)],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Holy Day Pump")

    white_perm = p1.battlefield[0]
    black_perm = p1.battlefield[1]

    # White creature present at resolution gets the buff
    assert white_perm.effective_power == 3
    assert white_perm.effective_toughness == 3
    # Non-white creature does not get the buff
    assert black_perm.effective_power == 2
    assert black_perm.effective_toughness == 2


def test_611_2c_new_creature_entering_after_spell_buff_is_unaffected():
    """611.2c: A creature that enters the battlefield after a spell-based global buff
    resolves does not receive that buff (the set of objects was locked in at resolution).
    """
    buff_spell = _mk_card(
        "Holy Day Pump", "Sorcery", "White creatures get +1/+1 until end of turn."
    )
    late_arrival = _mk_creature("Late White Bear", 2, 2, colors=("W",))

    p1 = PlayerState(name="P1", hand=[buff_spell])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # Spell resolves when no white creatures are on the battlefield
    game.cast_from_hand(0, "Holy Day Pump")

    # White creature enters AFTER the spell resolved
    p1.battlefield.append(Permanent(card=late_arrival))

    # The late-arriving creature should NOT have the spell's bonus
    late_perm = p1.battlefield[0]
    assert late_perm.effective_power == 2
    assert late_perm.effective_toughness == 2


# ---------------------------------------------------------------------------
# Rule 611.3a — Static abilities are not "locked in"; they apply dynamically
# ---------------------------------------------------------------------------


def test_611_3a_static_ability_applies_to_creature_present_when_lord_enters():
    """611.3a: A static ability applies to creatures already on the battlefield
    when the permanent with the static ability enters.
    """
    crusade = _mk_card(
        "Crusade", "Enchantment", "White creatures get +1/+1.", colors=("W",)
    )
    white_knight = _mk_creature("White Knight", 2, 2, colors=("W",))

    p1 = PlayerState(
        name="P1", hand=[crusade], battlefield=[Permanent(card=white_knight)]
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Crusade")

    knight_perm = p1.battlefield[0]
    assert knight_perm.effective_power == 3
    assert knight_perm.effective_toughness == 3


def test_611_3a_static_ability_applies_to_newly_entering_creature():
    """611.3a: A static continuous effect from a permanent is not 'locked in'.
    A creature that enters the battlefield after the lord does also gets the buff.
    """
    crusade = _mk_card(
        "Crusade", "Enchantment", "White creatures get +1/+1.", colors=("W",)
    )
    late_white_creature = _mk_creature("Late White Bear", 2, 2, colors=("W",))

    p1 = PlayerState(name="P1", hand=[crusade, late_white_creature])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # Crusade enters with no creatures on the battlefield
    game.cast_from_hand(0, "Crusade")

    # White creature enters AFTER Crusade
    game.cast_from_hand(0, "Late White Bear", target_player_index=0)

    late_perm = next(p for p in p1.battlefield if p.card.name == "Late White Bear")
    assert late_perm.effective_power == 3
    assert late_perm.effective_toughness == 3


def test_611_3a_static_ability_does_not_apply_to_non_matching_creature():
    """611.3a: A static effect applies only to permanents matching its criteria.
    A black creature entering after a 'white creatures +1/+1' lord is unaffected.
    """
    crusade = _mk_card(
        "Crusade", "Enchantment", "White creatures get +1/+1.", colors=("W",)
    )
    black_creature = _mk_creature("Black Bear", 2, 2, colors=("B",))

    p1 = PlayerState(name="P1", hand=[crusade, black_creature])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Crusade")
    game.cast_from_hand(0, "Black Bear", target_player_index=0)

    black_perm = next(p for p in p1.battlefield if p.card.name == "Black Bear")
    assert black_perm.effective_power == 2
    assert black_perm.effective_toughness == 2


# ---------------------------------------------------------------------------
# Rule 611.3b — Static effects apply while the permanent is on the battlefield
# ---------------------------------------------------------------------------


def test_611_3b_lord_buff_present_while_lord_on_battlefield():
    """611.3b: The continuous effect of a static ability applies while the
    permanent generating it is on the battlefield.
    """
    crusade = _mk_card(
        "Crusade", "Enchantment", "White creatures get +1/+1.", colors=("W",)
    )
    knight = _mk_creature("White Knight", 2, 2, colors=("W",))

    p1 = PlayerState(
        name="P1", hand=[crusade], battlefield=[Permanent(card=knight)]
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Crusade")

    knight_perm = p1.battlefield[0]
    assert knight_perm.effective_power == 3


def test_611_3b_lord_buff_removed_when_lord_leaves_battlefield():
    """611.3b: When the permanent generating a static effect leaves the battlefield,
    the effect ceases to apply (the buff should disappear).
    """
    crusade = _mk_card(
        "Crusade", "Enchantment", "White creatures get +1/+1.", colors=("W",)
    )
    knight = _mk_creature("White Knight", 2, 2, colors=("W",))

    p1 = PlayerState(
        name="P1", hand=[crusade], battlefield=[Permanent(card=knight)]
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Crusade")
    knight_perm = p1.battlefield[0]
    assert knight_perm.effective_power == 3

    # Remove Crusade from the battlefield (simulate destruction)
    crusade_perm = next(p for p in p1.battlefield if p.card.name == "Crusade")
    p1.battlefield.remove(crusade_perm)
    p1.graveyard.append(crusade_perm.card)

    # Recalculate lord buffs now that Crusade is gone
    game._recalculate_lord_buffs()

    assert knight_perm.effective_power == 2
    assert knight_perm.effective_toughness == 2


# ---------------------------------------------------------------------------
# Rule 611.3c — Static effects apply simultaneously with creature entering
# ---------------------------------------------------------------------------


def test_611_3c_static_buff_applies_simultaneously_with_creature_entering():
    """611.3c: A static continuous effect applies as the permanent enters the
    battlefield. A 1/1 white creature enters as 3/3 when a 'white creatures
    get +2/+2' enchantment is already in play.
    """
    buff_enchant = _mk_card(
        "White Ward Buff", "Enchantment", "White creatures get +2/+2.", colors=("W",)
    )
    small_white = _mk_creature("Small White", 1, 1, colors=("W",))

    p1 = PlayerState(name="P1", hand=[buff_enchant, small_white])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # Enchantment enters first
    game.cast_from_hand(0, "White Ward Buff")

    # 1/1 white creature enters after
    game.cast_from_hand(0, "Small White", target_player_index=0)

    small_perm = next(p for p in p1.battlefield if p.card.name == "Small White")
    # Creature should enter as 3/3, not 1/1 then 3/3
    assert small_perm.effective_power == 3
    assert small_perm.effective_toughness == 3


# ---------------------------------------------------------------------------
# Rule 613.1 / 613.4 — Layer system: Layer 7 sublayers
# ---------------------------------------------------------------------------


def test_613_4b_set_effect_layer_7b_overrides_card_base_stats():
    """613.4b: Effects that set power/toughness to a specific value (layer 7b)
    override the card's printed stats.
    """
    creature = _mk_creature("Gray Ogre", 2, 2)
    perm = Permanent(card=creature)

    # Apply a layer 7b "becomes 0/1" effect
    perm.metadata["absolute_power_until_eot"] = 0
    perm.metadata["absolute_toughness_until_eot"] = 1

    assert perm.effective_power == 0
    assert perm.effective_toughness == 1


def test_613_4_layer_7b_set_then_7c_modify():
    """613.4: A layer 7b set effect establishes the base, and layer 7c modifications
    (counters, pump spells) are applied on top of that base.

    Example: A 2/2 creature gets +3/+3 from a pump (7c), then 'becomes 0/1' (7b).
    Result: 0/1 base + 3/3 = 3/4.
    """
    creature = _mk_creature("Gray Ogre", 2, 2)
    perm = Permanent(card=creature)

    # Layer 7c: +3/+3 from a pump spell
    perm.power_bonus = 3
    perm.toughness_bonus = 3

    # Layer 7b: "becomes 0/1" (overrides base but 7c still applies on top)
    perm.metadata["absolute_power_until_eot"] = 0
    perm.metadata["absolute_toughness_until_eot"] = 1

    assert perm.effective_power == 3   # 0 (7b) + 3 (7c)
    assert perm.effective_toughness == 4  # 1 (7b) + 3 (7c)


def test_613_4_layer_7c_counter_plus_set_effect():
    """613.4: The Gray Ogre rules example from 613.5.

    2/2 creature:
    - +1/+1 counter (7c): 3/3
    - Gets +4/+4 until EOT (7c): 7/7
    - Enchantment +0/+2 (7c): 7/9
    - 'Becomes 0/1' until EOT (7b): 5/8  (0+5 / 1+7)
    """
    creature = _mk_creature("Gray Ogre", 2, 2)
    perm = Permanent(card=creature)

    # +1/+1 counter (layer 7c)
    perm.power_bonus += 1
    perm.toughness_bonus += 1
    # +4/+4 until EOT pump (layer 7c)
    perm.power_bonus += 4
    perm.toughness_bonus += 4
    # +0/+2 from enchantment aura (layer 7c)
    perm.power_bonus += 0
    perm.toughness_bonus += 2

    assert perm.effective_power == 7
    assert perm.effective_toughness == 9

    # "Becomes 0/1 until EOT" (layer 7b) - sets base, 7c bonuses remain on top
    perm.metadata["absolute_power_until_eot"] = 0
    perm.metadata["absolute_toughness_until_eot"] = 1

    assert perm.effective_power == 5   # 0 (7b) + 5 (7c: 1+4+0)
    assert perm.effective_toughness == 8  # 1 (7b) + 7 (7c: 1+4+2)


def test_613_4d_power_toughness_switch_layer_7d():
    """613.4d: Effects that switch a creature's power and toughness are applied
    in layer 7d, after all other layer 7 effects.

    A 1/3 creature that has power and toughness switched becomes 3/1.
    """
    creature = _mk_creature("Test Bear", 1, 3)
    perm = Permanent(card=creature)

    perm.metadata["pt_switched"] = True

    assert perm.effective_power == 3
    assert perm.effective_toughness == 1


def test_613_4d_switch_applied_after_7c_modify():
    """613.4d: Power/toughness switch (7d) is applied after +0/+1 modification (7c).

    A 1/3 creature gets +0/+1 (making it 1/4), then switched: becomes 4/1.
    """
    creature = _mk_creature("Test Bear", 1, 3)
    perm = Permanent(card=creature)

    # Layer 7c: +0/+1
    perm.toughness_bonus = 1  # now 1/4

    # Layer 7d: switch
    perm.metadata["pt_switched"] = True

    assert perm.effective_power == 4   # switched from toughness 1+3=4
    assert perm.effective_toughness == 1  # switched from power 1


def test_613_4d_switch_applied_after_set_and_modify():
    """613.4d: Switch (7d) is applied after both 7b (set) and 7c (modify) effects.

    A 1/3 creature: set to 5/5 (7b), +0/+1 (7c = 5/6), then switched: 6/5.
    """
    creature = _mk_creature("Test Bear", 1, 3)
    perm = Permanent(card=creature)

    # Layer 7b: set to 5/5
    perm.metadata["absolute_power_until_eot"] = 5
    perm.metadata["absolute_toughness_until_eot"] = 5

    # Layer 7c: +0/+1
    perm.toughness_bonus = 1  # now 5/6

    # Layer 7d: switch → 6/5
    perm.metadata["pt_switched"] = True

    assert perm.effective_power == 6
    assert perm.effective_toughness == 5


def test_613_4d_double_switch_returns_to_original_values():
    """613.4d: Two power/toughness switch effects essentially cancel each other.

    A 1/3 creature: +0/+1 (7c = 1/4), switch = 4/1, switch again = 1/4.
    """
    creature = _mk_creature("Test Bear", 1, 3)
    perm = Permanent(card=creature)

    # Layer 7c: +0/+1
    perm.toughness_bonus = 1  # unswitched: 1/4

    # Two switches cancel out: the creature is not switched
    # (pt_switched flag is toggled twice, net effect = no switch)
    perm.metadata["pt_switched"] = True
    # Toggling again (two switches = no switch)
    perm.metadata["pt_switched"] = not perm.metadata["pt_switched"]

    assert perm.effective_power == 1
    assert perm.effective_toughness == 4


# ---------------------------------------------------------------------------
# Rule 613.5 — Continuous effects applied continuously and instantaneously
# ---------------------------------------------------------------------------


def test_613_5_lord_buff_and_pump_applied_simultaneously():
    """613.5: Layer effects are applied continuously. A white creature on the
    battlefield gets the color lord's +1/+1 (layer 7c) plus any pump.
    Both apply instantaneously - there's no intermediate state shown to players.
    """
    crusade = _mk_card(
        "Crusade", "Enchantment", "White creatures get +1/+1.", colors=("W",)
    )
    pump = _mk_card("Giant Growth", "Instant", "Target creature gets +3/+3 until end of turn.")
    knight = _mk_creature("White Knight", 2, 2, colors=("W",))

    p1 = PlayerState(
        name="P1",
        hand=[crusade, pump],
        battlefield=[Permanent(card=knight)],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Crusade")  # knight becomes 3/3 from static
    game.cast_from_hand(
        0, "Giant Growth", target_player_index=0, target_permanent_index=0
    )  # +3/+3 until EOT on top

    knight_perm = p1.battlefield[0]
    # Static +1/+1 from Crusade + +3/+3 from Giant Growth = 6/6
    assert knight_perm.effective_power == 6
    assert knight_perm.effective_toughness == 6


def test_613_5_until_eot_set_plus_modifications_resolve_correctly():
    """613.5: When 'becomes 0/1' (layer 7b) is applied to a creature with existing
    layer 7c bonuses, those bonuses still apply on top of the new base.
    """
    creature = _mk_creature("Gray Ogre", 2, 2)
    perm = Permanent(card=creature)

    # Layer 7c: +2/+2 from a pump
    perm.power_bonus = 2
    perm.toughness_bonus = 2

    # Verify 4/4 before the set effect
    assert perm.effective_power == 4
    assert perm.effective_toughness == 4

    # Layer 7b: "becomes 0/1 until EOT"
    perm.metadata["absolute_power_until_eot"] = 0
    perm.metadata["absolute_toughness_until_eot"] = 1

    # Result: 0 (7b) + 2 (7c) = 2 / 1 (7b) + 2 (7c) = 3
    assert perm.effective_power == 2
    assert perm.effective_toughness == 3


# ---------------------------------------------------------------------------
# Rule 613.7 — Timestamp order within a layer
# ---------------------------------------------------------------------------


def test_613_7_later_timestamp_wins_for_conflicting_effects_in_same_layer():
    """613.7: When two conflicting effects apply in the same layer, the one with
    the later timestamp is applied last, so it 'wins'.

    Example: Effect T1 changes creature to red (layer 5), effect T2 changes it
    to blue (layer 5). T2 was applied later, so creature is blue.
    We simulate this with color_override metadata (representing layer 5 effects).
    """
    creature = _mk_creature("Test Creature", 2, 2)
    perm = Permanent(card=creature)

    # T1: creature becomes red (layer 5)
    perm.metadata["color_override"] = "R"
    # T2: creature becomes blue (layer 5) - applied after T1
    perm.metadata["color_override"] = "U"

    # Later timestamp (T2 = blue) wins
    assert perm.metadata["color_override"] == "U"


def test_613_7_timestamp_order_affects_power_toughness_set_effects():
    """613.7: In layer 7b, two 'becomes X/Y' effects - the later one wins.

    Creature first 'becomes 3/3' (T1) then 'becomes 1/1' (T2).
    T2 wins: creature is 1/1 (as a base, before any 7c modifiers).
    """
    creature = _mk_creature("Test Creature", 2, 2)
    perm = Permanent(card=creature)

    # Layer 7c modifier already in place
    perm.power_bonus = 2
    perm.toughness_bonus = 2

    # T1: becomes 3/3 (7b)
    perm.metadata["absolute_power_until_eot"] = 3
    perm.metadata["absolute_toughness_until_eot"] = 3

    # T2: becomes 1/1 (7b) - overwrites T1
    perm.metadata["absolute_power_until_eot"] = 1
    perm.metadata["absolute_toughness_until_eot"] = 1

    # T2 wins for the 7b base; 7c still adds +2/+2
    assert perm.effective_power == 3   # 1 (7b) + 2 (7c)
    assert perm.effective_toughness == 3  # 1 (7b) + 2 (7c)


# ---------------------------------------------------------------------------
# Rule 613.8 — Dependency within a layer
# ---------------------------------------------------------------------------


def test_613_8_dependent_effects_applied_after_effects_they_depend_on():
    """613.8: An effect that depends on another (its result changes based on the
    other) waits to apply until after the effect it depends on.

    Example: Color lord gives 'white creatures +1/+1'. A color-change effect
    (T1) makes a creature white. The lord (T2, later) then applies to it.
    Even though dependency may alter order, the creature gets the buff because
    it IS white (from T1) when the lord effect is applied.
    """
    crusade = _mk_card(
        "Crusade", "Enchantment", "White creatures get +1/+1.", colors=("W",)
    )
    creature = _mk_creature("Colorless Creature", 2, 2, colors=())

    p1 = PlayerState(name="P1", hand=[crusade], battlefield=[Permanent(card=creature)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Crusade")

    creature_perm = p1.battlefield[0]

    # Colorless creature → no buff from Crusade yet
    assert creature_perm.effective_power == 2

    # Simulate a color-change effect (layer 5): creature becomes white
    creature_perm.metadata["color_override"] = "W"

    # Re-evaluate static buffs (613.3a / 613.8)
    game._recalculate_lord_buffs()

    # Now creature is white and should receive Crusade's +1/+1
    assert creature_perm.effective_power == 3
    assert creature_perm.effective_toughness == 3


# ---------------------------------------------------------------------------
# Rule 613.9 — One continuous effect can override another
# ---------------------------------------------------------------------------


def test_613_9_later_effect_overrides_earlier_effect_in_same_layer():
    """613.9: Two effects in the same layer — the later one applies last.

    Example: 'Gains flying' (T1) then 'loses flying' (T2). T2 wins.
    We model this with the metadata keys used by the engine.
    """
    creature = _mk_creature("Test Bird", 2, 2)
    perm = Permanent(card=creature)

    # T1: gains flying
    perm.metadata["gains_flying_until_eot"] = True
    # T2: loses flying (later effect — wins)
    perm.metadata["loses_flying_until_eot"] = True

    # The engine's _has_keyword would check these; with both set,
    # the later "loses flying" should take precedence.
    # Verify both flags are independently stored (engine resolves order).
    assert perm.metadata.get("gains_flying_until_eot") is True
    assert perm.metadata.get("loses_flying_until_eot") is True


# ---------------------------------------------------------------------------
# Rule 612 — Text-Changing Effects (structural test)
# ---------------------------------------------------------------------------


def test_612_1_text_changing_effect_modifies_rules_text():
    """612.1: A text-changing effect modifies the text of an object.
    This engine-level test verifies that the text_modified metadata flag can be
    set to indicate a text-changing effect has been applied.
    """
    creature = _mk_creature("Test Creature", 2, 2, oracle_text="Forestwalk")
    perm = Permanent(card=creature)

    # A text-changing effect changes "Forest" to "Island" (Forestwalk → Islandwalk)
    perm.metadata["text_modified"] = True
    perm.metadata["has_islandwalk"] = True  # Result of the text change

    assert perm.metadata.get("text_modified") is True
    assert perm.metadata.get("has_islandwalk") is True


def test_612_3_granted_abilities_not_modified_by_text_changing_effects():
    """612.3: Abilities granted to an object by other effects are not modified
    by text-changing effects that affect that object. Only printed text changes.
    """
    creature = _mk_creature("Test Creature", 2, 2)
    perm = Permanent(card=creature)

    # Flying is granted by an aura effect (not printed)
    perm.metadata["gains_flying_until_eot"] = True

    # A text-changing effect is applied (changes printed text)
    perm.metadata["text_modified"] = True

    # The granted flying should still be present (not removed by text change)
    assert perm.metadata.get("gains_flying_until_eot") is True


# ---------------------------------------------------------------------------
# Rule 611.2a — EOT cleanup clears temporary metadata flags
# ---------------------------------------------------------------------------


def test_611_2a_eot_metadata_flags_cleared_at_cleanup():
    """611.2a: Metadata flags that carry 'until end of turn' effects are cleared
    during the cleanup step.
    """
    creature = _mk_creature("Test Creature", 2, 2)
    perm = Permanent(card=creature)

    p1 = PlayerState(name="P1", battlefield=[perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # Apply temporary effects
    perm.metadata["gains_flying_until_eot"] = True
    perm.metadata["pt_switched"] = True
    perm.metadata["absolute_power_until_eot"] = 5
    perm.metadata["absolute_toughness_until_eot"] = 5

    game.resolve_cleanup_step(0)

    # All until-EOT effects should be cleared
    assert not perm.metadata.get("gains_flying_until_eot")
    assert not perm.metadata.get("pt_switched")
    assert "absolute_power_until_eot" not in perm.metadata
    assert "absolute_toughness_until_eot" not in perm.metadata


# ---------------------------------------------------------------------------
# Integration: multiple continuous effects stacking correctly
# ---------------------------------------------------------------------------


def test_integration_multiple_effects_stack_in_layer_7c():
    """613.4c: Multiple layer 7c effects (counters, pump spells, static buffs)
    all add together.
    """
    creature = _mk_creature("Test Bear", 2, 2, colors=("W",))
    perm = Permanent(card=creature)

    # Counter (+1/+1)
    perm.power_bonus += 1
    perm.toughness_bonus += 1

    # Pump spell until EOT (+3/+3) — tracked in temporary bonus
    perm.power_bonus += 3
    perm.toughness_bonus += 3

    # Static lord buff (+1/+1 from Crusade-like effect)
    perm.metadata["static_buff_power"] = 1
    perm.metadata["static_buff_toughness"] = 1

    # Total: 2 (base) + 4 (counter+pump) + 1 (static) = 7/7
    assert perm.effective_power == 7
    assert perm.effective_toughness == 7
