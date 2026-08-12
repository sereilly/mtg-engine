"""Which migration category each lowered instruction kind belongs to.

One table, in its own module because it is a *registry* rather than logic: the
gate in `engine/grammar/__init__.py` turns categories on one at a time, and an
instruction whose kind is missing here can be lowered but never gated on.

`GRAMMAR_CATEGORIES` is held equal to the set of values here by
`tests/engine/test_grammar_categories.py`. With no fallback underneath the
grammar, a category left off does not route its lines elsewhere — it costs
those cards their support, which is why the equality is a test and not a
convention.
"""

from ...lord_buffs import (LORD_BUFF_KIND)
from ...land_animation import LAND_ANIMATION_KIND
from ...land_types import STATIC_LAND_TYPE_KIND
INSTRUCTION_CATEGORIES: dict[str, str] = {
    "deal_damage": "damage",
    "earthquake_damage": "damage",
    "hurricane_damage": "damage",
    "deal_damage_each_creature_and_player": "damage",
    "deal_damage_each_attacking_creature": "damage",
    "deal_damage_and_opponent_choice": "damage",
    "self_damage_unless_pay": "damage",
    # Dispatched by the (trigger condition, instruction kind) registry in
    # engine/phases/upkeep_effects.py rather than by EFFECT_HANDLERS, so they
    # share the category of the other upkeep pay-or-else shapes.
    "upkeep_pay_or_deal_damage_to_controller": "upkeep",
    "upkeep_chosen_player_hand_overflow_damage": "upkeep",
    "deal_damage_equal_to_swamps": "upkeep",
    "pump_target_creature_until_eot": "pump",
    "pump_self": "pump",
    "pump_enchanted_creature": "pump",
    "buff_creatures_global": "pump",
    # A permanent's continuous anthem/lord buff. Its own category rather than
    # "pump": that one is a one-shot boost with a duration, and these two
    # readings of the same printed sentence answer to different rules
    # (CR 611.2c vs 611.3a). Sharing a switch would tie them together.
    LORD_BUFF_KIND: "static_buffs",
    # A permanent's board-wide static effect on *lands* (CR 613 layer 4):
    # Kormus Bell animating every Swamp, Conversion turning every Mountain into
    # a Plains. Their own category rather than "static_buffs" because the two
    # answer to different layers and to different consumers —
    # `_refresh_dynamic_creatures` and `_recalculate_derived_land_types` — so
    # one switch would tie two migrations together.
    LAND_ANIMATION_KIND: "land_statics",
    STATIC_LAND_TYPE_KIND: "land_statics",
    "set_base_pt_target_until_eot": "pump",
    "grant_target_flying_until_eot": "pump",
    "grant_self_flying_until_eot": "pump",
    "grant_target_keyword_until_eot": "pump",
    # The negative twin ("It loses indestructible until end of turn", Soul Sear).
    "remove_target_keyword_until_eot": "pump",
    "grant_self_keyword_until_eot": "pump",
    "grant_banding_to_target": "pump",
    "add_counter_to_self": "pump",
    "add_counter_to_target": "pump",
    "add_counter_to_each_you_control": "pump",
    # Counter placements sized by a board count. Their own category rather than
    # "pump": a corpse counter never touches power or toughness (it is
    # regeneration fuel), so gating it behind the pump switch would tie two
    # unrelated migrations together. Keeping it out of the differential's
    # MIGRATED_CATEGORIES also means these two lines stay compared against the
    # legacy rules for as long as those rules exist.
    "add_corpse_counters_for_each_creature_died": "counters",
    "add_plus1_counters_for_each_creature_died": "counters",
    "remove_counter_from_self": "counters",
    # Pestilent Haze's second mode: loyalty stripped from every walker at once.
    "remove_loyalty_from_each_planeswalker": "counters",
    "draw_then_discard_self": "zones",
    "target_gains_life": "life",
    "target_loses_life": "life",
    "destroy_target_permanent": "destruction",
    "destroy_all_artifacts": "destruction",
    "destroy_all_creatures": "destruction",
    "destroy_all_enchantments": "destruction",
    "destroy_all_lands": "destruction",
    "destroy_all_lands_of_type": "destruction",
    "destroy_all_artifacts_creatures_enchantments": "destruction",
    "delayed_destroy_blocked_or_blocker": "destruction",
    "tap_target_permanent": "tapping",
    "tap_self": "tapping",
    "untap_target_permanent": "tapping",
    "untap_target_land": "tapping",
    # "Untap up to four lands." (Rewind) — the controller picks the lands on
    # resolution through the pending-choice queue; no "target" is printed.
    "untap_up_to_matching": "tapping",
    "untap_self": "tapping",
    "untap_enchanted_creature": "tapping",
    "grant_prevention_shield": "prevention",
    "prevent_all_combat_damage": "prevention",
    "recolor_target_from_text": "recolor",
    # A printed text change (CR 612). Its own category rather than "recolor":
    # the Lace cycle makes an object a colour, while this replaces a *word*
    # wherever the object's text uses it, and one of the two modes does not
    # touch colour at all.
    "mark_text_modified": "text_change",
    # A control change whose duration is linked to its source (CR 611.3).
    "steal_target_permanent_linked_to_self": "control",
    "sacrifice_self": "zones",
    "upkeep_pay_or_sacrifice_enchantment": "upkeep",
    "upkeep_pay_or_sacrifice_self": "upkeep",
    "upkeep_pay_to_untap_self": "upkeep",
    "discard_target_cards": "zones",
    "discard_x_target_cards": "zones",
    "opponent_discards_random_card_on_damage": "zones",
    "grant_regeneration_to_target_creature": "regeneration",
    "grant_regeneration_to_self": "regeneration",
    "grant_regeneration_to_enchanted_creature": "regeneration",
    # "Target creature can't be regenerated this turn" is the negative half of
    # the same subject, so it shares the category rather than minting one that
    # would always be switched on and off alongside it.
    "deny_regeneration_to_target": "regeneration",
    # Looking at a hand reads a hidden zone; the legacy rule and the handler
    # both live in the engine's zones modules.
    "look_at_target_hand": "zones",
    # A library search moves a card between hidden zones — same module, same
    # category as the other zone-change handlers.
    "search_library": "zones",
    # The cast-from-exile/graveyard subsystem (both Chandras, M21): two exiles
    # that record what they moved, and the permission their later sentences
    # grant over it. All zone work — the permission is about which zone a card
    # may be cast from — so no new category and GRAMMAR_CATEGORIES is unchanged.
    "exile_top_of_library": "zones",
    "look_top_pick_to_hand": "zones",
    "search_and_exile_matching": "zones",
    "grant_cast_permission": "zones",
    "grant_extra_turn": "turns",
    # The planeswalker block's one-shot zone movers (M21 loyalty abilities).
    "each_player_discards_a_card": "zones",
    "opponents_who_could_not_discard_lose_life": "life",
    "discard_hand": "zones",
    "put_target_on_library_top": "zones",
    "put_cards_from_hand_onto_battlefield": "zones",
    "reveal_top_to_hand_or_bottom": "zones",
    "exile_all_matching": "zones",
    "grant_team_keyword_until_eot": "pump",
    "add_loyalty_counters": "counters",
    "target_bites_target": "damage",
    "phase_out_target": "zones",
    "grant_team_assign_unblocked_until_eot": "pump",
    "phase_out_opponent_creatures": "zones",
    # Ending the game (CR 104). Their own category rather than "life": nothing
    # about a life total is involved, and the three outcomes share one set of
    # handlers in engine/handlers/life_and_game.py.
    "player_wins_game": "game_end",
    "player_loses_game": "game_end",
    "target_player_loses_game": "game_end",
    "game_is_draw": "game_end",
    "grant_unblockable_to_low_power_target": "evasion",
    # Restrictions on declaring attackers/blockers (CR 506, 509).
    "cant_attack_without_land_type": "combat_restrictions",
    "cant_block_power_n_or_greater": "combat_restrictions",
    # The one-shot, turn-scoped blanket ("Creatures without flying can't block
    # this turn", Destructive Tampering's second mode).
    "cant_block_until_eot": "combat_restrictions",
    "counter_top_stack_spell": "counterspells",
    "tap_or_untap_target": "tapping",
    "draw_target_cards": "zones",
    "draw_controller_cards": "zones",
    "mill_target_player": "zones",
    # Scry moves cards within one library (CR 701.22a) — the same family as
    # mill and draw, so no new category and GRAMMAR_CATEGORIES is unchanged.
    "scry": "zones",
    "exile_creature_gain_life_equal_to_power": "zones",
    "exile_target_creature_until_eot": "zones",
    # The permanent exiles. Same category as the temporary one, so
    # GRAMMAR_CATEGORIES is unchanged — exile is a zone change either way, and
    # a second switch would let one of the two be gated off without the other.
    "exile_target_permanent": "zones",
    "exile_target_graveyard_card": "zones",
    "return_creature_from_graveyard_to_hand": "zones",
    "reanimate_creature": "zones",
    "bounce_target_creature": "zones",
    "add_mana_from_text": "mana",
    # A triggered *mana* ability on a land being tapped (CR 605.1b): resolved
    # inline by Game.tap_land_for_mana, not through EFFECT_HANDLERS on the
    # stack, because CR 605.4a says a triggered mana ability never uses it.
    "add_mana_for_tapped_land": "mana",
    "create_token": "tokens",
    "create_emblem": "tokens",
    # Optional actions. Parsed and lowered, not switched on — see _WRAPPER_KINDS.
    "may": "optional",
}
