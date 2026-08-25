from __future__ import annotations

from ..combat_permissions import ATTACK_AS_THOUGH_NO_DEFENDER

_MANA_SYMBOLS = ("W", "U", "B", "R", "G", "C")
_EOT_METADATA_KEYS = (
    # Riddleform's self-animation: the record *is* the effect, so sweeping it
    # here is what ends it — nothing was stashed and nothing is restored.
    "animate_until_end_of_turn",
    "assign_combat_damage_as_unblocked_until_eot",
    "cant_be_blocked_until_eot",
    "must_attack_until_eot",
    "destroy_if_did_not_attack_eot",
    "destroy_if_attacked_eot",
    "attacked_this_turn",
    "redirect_one_damage_to_owner_until_eot",
    # Layer 7b temporary set effects (613.4b)
    "absolute_power_until_eot",
    "absolute_toughness_until_eot",
    # Layer 7d power/toughness switch (613.4d)
    "pt_switched",
    # CR 609.4 combat permission: "…can attack this turn as though it didn't
    # have defender" (Wall of Wonder). Named through
    # `engine/combat_permissions.py` so the write, the read and this sweep
    # cannot spell the channel three ways.
    ATTACK_AS_THOUGH_NO_DEFENDER,
    # Disintegrate-style riders that last only "this turn"
    "cant_be_regenerated_this_turn",
    "exile_if_dies_this_turn",
    # Sengir Vampire damage-source tracking (cleared each turn)
    "damaged_by_sources_this_turn",
    # Dragon Whelp firebreathing activation counter ("four or more times this turn")
    "pump_activation_count",
    # Pyramids: unused land-destruction shield expires with the turn
    "land_destruction_shield_this_turn",
    # Ebony Horse: combat-damage shield on the untapped attacker
    "prevent_combat_damage_to_and_by_until_eot",
    # "One or more target creatures become red until end of turn" (Dwarven Song
    # and its four Legends siblings). The indefinite `color_override` beside it
    # is a lace and must survive the turn, which is why this is a second key
    # rather than a flag on the first.
    "color_override_until_eot",
    # "Prevent all combat damage that would be dealt by target creature this
    # turn" (Horn of Deafening, Lady Evangela). The direction is the value, so
    # the key is one rather than one per direction.
    "prevent_combat_damage_direction_until_eot",
)

_TURN_PHASES: tuple[str, ...] = (
    "beginning",
    "precombat_main",
    "combat",
    "postcombat_main",
    "ending",
)

_PHASE_STEPS: dict[str, tuple[str, ...]] = {
    "beginning": ("untap", "upkeep", "draw"),
    "precombat_main": ("precombat_main",),
    "combat": (
        "beginning_of_combat",
        "declare_attackers",
        "declare_blockers",
        "combat_damage",
        "end_of_combat",
    ),
    "postcombat_main": ("postcombat_main",),
    "ending": ("end", "cleanup"),
}

# Untap and cleanup are the regular no-priority steps in this simplified engine.
_NO_PRIORITY_STEPS = {"untap", "cleanup"}

# Instruction kinds where the controller must pay mana or face a consequence.
# These require an interactive choice from a human player.
_UPKEEP_PAY_KINDS = {
    "upkeep_pay_or_sacrifice_enchantment",
    # Cyclone: escalating {G} per wind counter, or sacrifice; paying deals
    # counter-many damage to each creature and each player.
    "upkeep_wind_counter_pay_or_sacrifice",
    "upkeep_pay_or_sacrifice_self",
    "upkeep_pay_or_deal_damage_to_controller",
    "upkeep_pay_or_tap_and_sacrifice_opponent_land",
    # Rohgahh of Kher Keep: pay {R}{R}{R} or tap Rohgahh and every creature
    # named Kobolds of Kher Keep, then an opponent gains control of them all.
    "upkeep_pay_or_cede_named_creatures",
    # Optional pays with no decline consequence — pay to untap (Mana Vault /
    # Basalt Monolith untap themselves; Paralyze untaps the enchanted creature)
    # or pay for life (Farmstead's granted enchant-land upkeep ability).
    "upkeep_pay_to_untap_self",
    "upkeep_pay_to_untap_enchanted",
    "upkeep_pay_to_gain_life",
}
