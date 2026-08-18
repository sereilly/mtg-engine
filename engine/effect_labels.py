"""The reporting label an ability's compiled instruction carries.

``effect_kind`` is a *label*, never dispatch. It reaches three places and no
others: ``SimulationResult.effect_kind`` (the string the duel scripts and the
per-card tests report a cast by), ``scripts/support_report.py``'s buckets, and
``StackItem.ability_effect_kind`` — whose ``triggered_`` prefix is what
``web/serialization.py`` serializes as a stack item's ``is_triggered``.

Its vocabulary was ``engine/parsing/``'s. Each string was named after the rule
that produced it (``activated_deny_regeneration`` because there was a rule
called that), and the compiler preferred the legacy label whenever a legacy rule
matched the same line the grammar had already read. Deleting the registry
without carrying the vocabulary would therefore have silently re-bucketed 57
cards — an activated regeneration reported ``activated_regeneration`` where it
had always said ``activated_regenerate``, and every trigger the grammar reads
losing the ``triggered_`` prefix that flag depends on.

So the vocabulary moves here, which is the move
``card_hooks.CardLine.effect_kind`` already made for the lines that became
name-keyed hooks: *"carried here so deleting the rule that produced it does not
silently re-bucket the card."* A hook supplies its own label and never consults
these tables; what they cover is the grammar's output.

**Both tables are held to the pool**, by ``tests/engine/test_effect_labels.py``:
every entry must still be reached by a card that compiles through the grammar,
and every such ability must take its label from an entry rather than the
fallback. A frozen list of strings nothing checks would rot into a description
of a pool that has moved on; this one fails when it stops describing the pool,
so it can be pruned and extended for cause rather than by guesswork.

The fallbacks below the tables are what a *new* card gets: an activated ability
is labelled by the grammar category its instruction lowered to, and a trigger
keeps the ``spell_pattern`` marker the compiler has always used when nothing
claimed the clause. A new entry is only needed when a card must keep a label the
category cannot produce.
"""

from __future__ import annotations

# Instruction kind -> label, for an ability the grammar reads in the **activated**
# position (the clause right of an ability's colon).
ACTIVATED_LABELS: dict[str, str] = {
    "add_counter_to_self": "activated_counter",
    # Jandor's Saddlebags. Declared here rather than taken from the "tapping"
    # category default, so the card keeps the bucket it reported before the
    # grammar learned to lower its line — the whole reason this table exists.
    "untap_target_permanent": "activated_untap",
    # Historically "triggered_counter" — the label Dwarven Weaponsmith's hook
    # declared for this kind before the grammar learned the lowering. Kept so
    # the card is not silently re-bucketed; the misnomer is the legacy
    # vocabulary, and this module exists to carry it.
    "add_counter_to_target": "triggered_counter",
    "add_mana_from_text": "activated_mana",
    "counter_top_stack_spell": "spell_pattern",
    "create_token": "activated_token",
    "deal_damage": "activated_damage",
    "deal_damage_and_opponent_choice": "activated_damage",
    "deal_damage_each_creature_and_player": "activated_damage",
    "deny_regeneration_to_target": "activated_deny_regeneration",
    "destroy_all_artifacts_creatures_enchantments": "activated_destruction",
    "destroy_target_permanent": "activated_destruction",
    "discard_target_cards": "spell_pattern",
    "draw_controller_cards": "activated_draw",
    "draw_then_discard_self": "activated_draw",
    "grant_banding_to_target": "activated_pump",
    "grant_extra_turn": "spell_pattern",
    "grant_prevention_shield": "activated_prevent",
    "grant_regeneration_to_enchanted_creature": "activated_regenerate",
    "grant_regeneration_to_self": "activated_regenerate",
    "grant_regeneration_to_target_creature": "activated_regenerate",
    "grant_self_flying_until_eot": "activated_pump",
    "grant_target_flying_until_eot": "activated_pump",
    "grant_unblockable_to_low_power_target": "activated_evasion",
    "hurricane_damage": "activated_damage",
    "look_at_target_hand": "activated_look",
    "mill_target_player": "activated_mill",
    "pump_enchanted_creature": "activated_pump",
    "pump_self": "activated_pump",
    "pump_target_creature_until_eot": "activated_pump",
    "remove_counter_from_self": "activated_counters",
    # A composed effect (Orcish Artillery's "deals damage to X and damage to
    # you"). The label names what the ability is *for*, which is why it cannot
    # be read off the wrapper kind.
    "sequence": "activated_damage",
    "set_base_pt_target_until_eot": "activated_pump",
    "steal_target_permanent_linked_to_self": "activated_steal",
    "tap_target_permanent": "activated_tapping",
    "untap_enchanted_creature": "activated_untap",
    "untap_self": "activated_untap",
    "untap_target_land": "spell_pattern",
}

# Instruction kind -> label, for an ability the grammar reads in the **triggered**
# position (the clause after a trigger condition).
TRIGGERED_LABELS: dict[str, str] = {
    "add_corpse_counters_for_each_creature_died": "triggered_counter",
    "add_counter_to_self": "triggered_counter",
    "add_mana_for_tapped_land": "spell_pattern",
    "add_plus1_counters_for_each_creature_died": "triggered_counter",
    "deal_damage": "spell_pattern",
    "deal_damage_equal_to_swamps": "upkeep_effect",
    "delayed_destroy_blocked_or_blocker": "triggered_delayed_destroy",
    "opponent_discards_random_card_on_damage": "triggered_discard",
    "sacrifice_self": "triggered_sacrifice",
    "self_damage_unless_pay": "triggered_damage",
    "target_gains_life": "spell_pattern",
    "upkeep_chosen_player_hand_overflow_damage": "upkeep_effect",
    "upkeep_pay_or_deal_damage_to_controller": "upkeep_effect",
    "upkeep_pay_or_sacrifice_enchantment": "upkeep_effect",
    "upkeep_pay_or_sacrifice_self": "upkeep_effect",
    "upkeep_pay_to_untap_self": "upkeep_effect",
}

# The one instruction kind whose label depends on what triggered it: `may` wraps
# whatever the optional clause offers, so the wrapper says nothing about the
# effect. Verduran Enchantress's optional draw was labelled a draw; the
# pay-{1}-gain-1-life cycle (Crystal Rod and its four siblings, Soul Net) was
# never claimed by a rule at all and kept the `spell_pattern` marker.
TRIGGERED_LABELS_BY_CONDITION: dict[tuple[str, str], str] = {
    ("creature_dies", "may"): "spell_pattern",
    ("enchantment_cast", "may"): "triggered_draw",
    ("spell_cast", "may"): "spell_pattern",
}


def activated_label(instruction_kind: str, category: str) -> str:
    """The label for *instruction_kind* read as an activated ability."""
    return ACTIVATED_LABELS.get(instruction_kind, f"activated_{category}")


def triggered_label(instruction_kind: str, condition_kind: str | None) -> str:
    """The label for *instruction_kind* read as a trigger's effect."""
    if condition_kind is not None:
        by_condition = TRIGGERED_LABELS_BY_CONDITION.get((condition_kind, instruction_kind))
        if by_condition is not None:
            return by_condition
    return TRIGGERED_LABELS.get(instruction_kind, "spell_pattern")


__all__ = [
    "ACTIVATED_LABELS",
    "TRIGGERED_LABELS",
    "TRIGGERED_LABELS_BY_CONDITION",
    "activated_label",
    "triggered_label",
]
