from __future__ import annotations

_MANA_SYMBOLS = ("W", "U", "B", "R", "G", "C")
_EOT_METADATA_KEYS = (
    "gains_flying_until_eot",
    "gains_banding_until_eot",
    "gains_trample_until_eot",
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
    # Layer 6 "loses flying" effect
    "loses_flying_until_eot",
    # Disintegrate-style riders that last only "this turn"
    "cant_be_regenerated_this_turn",
    "exile_if_dies_this_turn",
    # Sengir Vampire damage-source tracking (cleared each turn)
    "damaged_by_sources_this_turn",
    # Dragon Whelp firebreathing activation counter ("four or more times this turn")
    "pump_activation_count",
)

# Map: artifact name → (color that triggers it, life gained).
# Kept as an alias for backwards compatibility; the data now lives in
# engine.card_hooks alongside the other per-card behavior registries.
from ..card_hooks import COLOR_ROD_TRIGGERS as _COLOR_ROD_TRIGGERS  # noqa: E402

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
    "upkeep_pay_or_sacrifice_self",
    "upkeep_pay_or_deal_damage_to_controller",
    "upkeep_pay_or_tap_and_sacrifice_opponent_land",
    # Optional pays with no decline consequence — pay to untap (Mana Vault /
    # Basalt Monolith untap themselves; Paralyze untaps the enchanted creature)
    # or pay for life (Farmstead's granted enchant-land upkeep ability).
    "upkeep_pay_to_untap_self",
    "upkeep_pay_to_untap_enchanted",
    "upkeep_pay_to_gain_life",
}
