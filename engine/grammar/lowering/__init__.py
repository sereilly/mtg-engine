"""Lowering: AST node -> ``OracleInstruction``, one family per subject.

The mirror of `grammar/effects/`, with the *same family names*, so a new
template has one home on each side — prowess parses in
`effects/characteristics.py` and lowers in `lowering/characteristics.py`.

    _common          payload shapes and the fragments several families need
    categories       the kind -> category registry the gate in `lower.py` reads
    damage           dealing it, and preventing it
    redirection      CR 614.9, changing who dealt damage reaches
    fighting         CR 701.14, two creatures damaging each other
    characteristics  P/T, colour, printed text
    types            CR 205 / layer 4: animation, a gained card type, a
                     supertype, a basic land type
    counters         putting and removing them, and the per-death repetition
    tapping          CR 701.20/701.21, the keyword action itself
    untap_restrictions
                     CR 502.3, what keeps a permanent from untapping
    board            destruction, bouncing, tapping, control, exile
    cards            draw, discard, mill, scry
    library          search, reveal, look-at, exile linkage — the hidden zones
    mana             "Add {G}", the tapped-land mana trigger, and a standing
                     change to what a land produces
    stack            countering
    combat           can't-attack / can't-be-blocked
    game             tokens, life, winning, extra turns

The families share no code with each other; everything common is in `_common`.
Re-exported flat, so callers name a production and not its family, and moving
one between families is not a caller-visible change.

An effect that should *not* execute belongs here as a `LoweringError` naming
what is missing — never as a lowering that quietly drops the part the engine
cannot do.
"""

from .categories import INSTRUCTION_CATEGORIES
from .control_flow import categories_of
from ._records import _COST_PRODUCES, _PRODUCES
from .where_x import lower_where_x
from .conditions import _lower_condition, pronoun_target_referent
from ._events import (CREATED_TOKEN, 
    _BLOCK_PAIR_EVENTS,
    binds_block_pair,
    _DAMAGED_PLAYER_EVENTS,
    _EVENT_SUBJECT_CONTROLLERS,
    _EVENT_SUBJECT_PLAYERS,
    EVENT_SUBJECT_CONTROLLER,
    EVENT_SUBJECT_PLAYER,
)
from ._common import (
    _filter_payload,
    _restrictions_beyond,
    GRAMMAR_ONLY_PAYLOAD_KEYS,
    _describe_targets,
    _describe_several_targets,
    _describe_several_card_targets,
    _targets_only,
    _targets_payload,
    _amount_payload,
    _is_source,
    _is_created_token,
    _is_enchanted,
    _is_target,
    _is_you,
    _signed,
    _durationless_reason,
    _MANA_KEYS,
    _full_mana_payload,
    _REST_OF_TURN,
    _refuse_unfused_distinctness,
)
from ._amounts import (
    _mentions_x,
    _stamp_x_from_count,
    _READABLE_COST_SACRIFICE_CHARACTERISTICS,
    _lower_cost_tap_damage,
    _SWAMPS_THEY_CONTROL,
    _BOARD_COUNT_DAMAGE,
    _damaged_player_is,
    _lower_cost_sacrifice_damage,
    _lower_counted_damage,
    _lower_board_count_damage,
    count_spec,
    halved_count_spec,
)
from .damage import (
    _lower_damage,
    _lower_damage_dealt_riders,
    _lower_damage_conjunction,
)
from .upkeep import (
    _lower_damage_reduced_by_paid_mana,
    _lower_upkeep_counter_toll,
    _lower_upkeep_damage_unless_cost,
    _lower_damage_unless_pay,
)
from .fighting import (
    _fused_prepare_then_interact,
    _lower_fight,
)
from .redirection import (
    _lower_damage_becomes_counter_removal,
    _lower_double_combat_damage,
    _lower_redirect_damage,
)
from ._blankets import _lower_prevent_all
from .prevention import (
    _lower_prevent_damage,
    _lower_prevent_half,
    _lower_damage_cant_be_prevented,
)
from .base_pt import _lower_change_base_pt, _lower_set_base_pt
from .characteristics import (
    _fused_tap_any_number_then_pump,
    _fused_two_target_pump,
    _lower_double_power,
    _lower_switch_pt,
    _lower_pump,
    _lower_change_text,
)
from .types import (
    _lower_land_type_swap,
    _lower_become_color,
    _lower_become_creature,
    _lower_change_land_type,
    _lower_change_supertype,
    _lower_gain_type,
)
from .keywords import (
    _KEYWORD_GRANTS,
    _lower_gain_ability_text,
    _lower_gain_keyword,
    _lower_lose_keyword,
)
from .counter_removal import _lower_move_counter, _lower_remove_counter
from ._counter_stores import _lower_player_gets_counters
from .counters import _lower_put_counter
from .sequences import (_fused_cost_repeated_destroys,
                        _fused_tap_enchanted_then_counters)
from .loops import (
    _PER_DEATH_COUNTERS,
    _PER_DEATH_SUBJECT,
    _ANY_CREATURE_DIED,
    _lower_for_each,
)
from .zones import (
    _lower_ownership_exchange_unless_paid,
    _lower_ante_offer_ownership_exchange,
    _lower_random_reveal_ownership_exchange,
    _lower_shuffle_graveyard_into_library,
    _lower_shuffle_hand_into_library,
    _lower_shuffle_library,
    _lower_reveal_top_of_library,

    _lower_put_onto_battlefield,

    _lower_put_on_library_top,
)
from .returns import (
    _reads_no_return_restriction,
    _lower_reanimate_enchanted_card,
    _lower_return_to_zone,
    _lower_put_source_into_zone,
    _lower_return_self_instead_of_untapping,
)
from .exile import (
    _EXILED_CREATURE,
    _lower_exile,
    _lower_exile_cost_sacrifices,
    _lower_for_each_exiled,
    _lower_exile_until_leaves_or_untaps,
    _fused_exile_then_controller_life,
    _lower_exile_graveyard_until_leaves,
    _lower_put_exiled_pile_top_into_hand,
    _lower_exile_top_of_library,
    _lower_exile_entire_library,
    _lower_put_exiled_card_into_zone,
    _lower_put_exiled_with_source,
    _lower_search_and_exile,
    _lower_transmute_by_sacrifice,
)
# The linked-exile half came here whole out of `.library` when that module
# crossed the thousand-line guard, and its *permission* half left again for
# `.permissions` when `.exile` crossed the same guard at Alliances. The names
# never changed on either move, so this package's flat re-export is unchanged
# and no caller learns where a split fell — a move that renamed anything would
# be a rename wearing a move's clothes.
from ._piles import _SEARCH_EXILE_HONOURED
from .permissions import (
    _lower_cast_from_exiled_with,
    _lower_cast_permission,
)
from .attachments import (
    _lower_attach,
    _lower_choose_permanent,
    _lower_choose_permanents,
)
from .board import (
    _lower_cant_phase_out,
    _lower_phase_out,
    _lower_simultaneous_phasing,
    _lower_put_on_library_bottom,
    _lower_put_graveyard_top_on_library_bottom,
    _lower_delayed_self_action,
    _lower_exchange_greatest_mana_value,
    _lower_regenerate,
    _lower_rebalance_lands,
    _lower_sacrifice_unless_pay,
    _lower_destroy_unless_pay,
    _lower_destroy_each_unless_paid,
    _lower_sacrifice,
    _lower_sacrifice_expansion_permanents,
)
from .destruction import (
    _DESTROY_ALL_KINDS,
    _BASIC_LAND_TYPES,
    _lower_destroy,
    _lower_for_each_destroyed,
    _lower_delayed_destroy,
)
from .control_changes import (
    _lower_bid_life_for_control,
    _lower_exchange_control,
    _lower_gain_control,
)
from .tapping import (
    _lower_for_each_tapped,
    _lower_tap,
    _lower_untap_chosen_by_paying,
    _lower_simultaneous_untap_and_tap,
    _lower_tap_or_untap,
    _fused_upkeep_pay_to_untap,
)
from .untap_restrictions import (
    _lower_doesnt_untap_next_step,
    _lower_untap_restriction,
    _lower_doesnt_untap_while_source_tapped,
)
from .cards import (
    _lower_discard,
    _fused_discard_then_draw,
    _fused_draw_then_discard,
    _lower_draw,
    _lower_next_draw_replacement,
    _lower_mill,
    _lower_mill_until,
    _lower_put_milled_card_onto_battlefield,
    _lower_scry,
)
# The hand family, split off `.cards` at the size guard in the same round its
# parse mirror was. Every name keeps its address: this package re-exports flat,
# so no caller learns where the split fell.
from .hand import (
    CHOSEN_HAND_CARDS_RESULT,
    HAND_CARDS_TO_LIBRARY_RESULT,
    _lower_choose_cards_in_hand,
    _lower_for_each_chosen,
    _lower_for_each_short_of_this_way,
    _lower_put_iterated_card_on_library,
    _lower_put_hand_cards_on_library,
)
from .mana import (
    _lower_add_mana,
    _lower_note_mana_spent,
    _TAPPED_LAND_MANA_RECIPIENTS,
    _lower_activate_each_lands_mana_ability,
    _lower_add_mana_for_tapped_land,
    _lower_lose_unspent_mana,
    _lower_produces_mana_instead,
    _lower_spend_mana_as_though,
)
from .library import (
    _lower_reveal_top,
    _lower_reveal_until,
    _lower_look_top_exile_random,
    _lower_look_top_pick,
    _lower_exile_graveyard,
    _lower_discard_revealed_matching_unless_pay_life,
    _lower_discard_revealed_unless_pay_life,
    _lower_play_with_hand_revealed,
    _lower_reveal_hand,
    _lower_reveal_random_from_hand,
    _lower_reveal_hand_and_choose,
    _lower_look_at_hand,
    _lower_bin_revealed_card,
    _lower_graveyard_top_to_library,
    _lower_look_at_library_top,
    _lower_look_top_cycle_for_life,
    _lower_separate_library_top_into_piles,
    _lower_graveyard_pick_onto_battlefield,
)
from .search import (
    _SEARCH_HONOURED_FILTER_FIELDS,
    _lower_search_library,
    _lower_search_player_library,
)
from .stack import (
    _COUNTER_HONOURED_FILTER_FIELDS,
    _COUNTER_UNLESS_PAYS_X,
    _COUNTER_PERFORMED_PENALTIES,
    _fused_conditional_counter,
    _lower_change_target,
    _lower_counter_ability,
    _lower_counter_spell,
    _lower_modal_head,
)
from .delayed import (
    _lower_choose_target,
    _lower_create_delayed_trigger,
    _lower_waive_shroud,
)
from .prohibitions import _lower_cant_be
from .combat import (
    _lower_combat_restriction,
    lower_block_count_grant,
    _lower_attack_as_though,
    _lower_assigns_no_combat_damage,
    _lower_attacks_this_turn_if_able,
    _lower_attacking_doesnt_tap,
    _lower_force_chosen_creature_to_attack,
    _lower_choose_blocks_for_defenders,
    _lower_reassign_blockers_between_attackers,
    _lower_become_blocked,
    _lower_remove_from_combat,
)
from .tokens import (_lower_create_copy_token, _lower_create_emblem, _title,
                     _lower_create_token)
from .game import (
    _lower_count_objects,
    _lower_ante,
    _lower_repeat_process,
    _lower_extra_turn,
    _LOSE_GAME_KINDS,
    _lower_lose_game,
    _lower_win_game,
    _lower_coin_flip_damage_loop,
    _lower_coin_flip_stakes_loop,
    _lower_damage_this_game_history,
    _lower_skip_step,
    _lower_skip_turn,
    _lower_targeting_ban,
    _lower_extra_land_plays,
    _lower_cant_play_lands,
)
from .life import (
    _lower_exchange_life_totals,
    _lower_gain_life,
    _lower_lose_life,
    _lower_pay_life,
    _lower_set_life_total,
)

__all__ = [
    "lower_where_x",
    "_lower_condition",
    "pronoun_target_referent",
    "INSTRUCTION_CATEGORIES",
    "categories_of",
    "_COST_PRODUCES",
    "_PRODUCES",
    "_mentions_x",
    "_refuse_unfused_distinctness",
    "_stamp_x_from_count",
    "_fused_upkeep_pay_to_untap",
    "_filter_payload",
    "_restrictions_beyond",
    "GRAMMAR_ONLY_PAYLOAD_KEYS",
    "_describe_targets",
    "_describe_several_targets",
    "_describe_several_card_targets",
    "_targets_only",
    "_targets_payload",
    "_amount_payload",
    "CREATED_TOKEN",
    "_is_source",
    "_is_created_token",
    "_EVENT_SUBJECT_CONTROLLERS",
    "_EVENT_SUBJECT_PLAYERS",
    "EVENT_SUBJECT_CONTROLLER",
    "EVENT_SUBJECT_PLAYER",
    "_is_enchanted",
    "_is_target",
    "_is_you",
    "_signed",
    "_durationless_reason",
    "_MANA_KEYS",
    "_full_mana_payload",
    "_REST_OF_TURN",
    "_SWAMPS_THEY_CONTROL",
    "_BOARD_COUNT_DAMAGE",
    "_damaged_player_is",
    "_READABLE_COST_SACRIFICE_CHARACTERISTICS",
    "_lower_cost_tap_damage",
    "_lower_cost_sacrifice_damage",
    "_lower_counted_damage",
    "_lower_board_count_damage",
    "_lower_damage_unless_pay",
    "_lower_damage",
    "_lower_damage_reduced_by_paid_mana",
    "_lower_skip_step",
    "_lower_skip_turn",
    "_lower_targeting_ban",
    "_lower_extra_land_plays",
    "_lower_cant_play_lands",
    "_lower_upkeep_counter_toll",
    "_lower_upkeep_damage_unless_cost",
    "_lower_damage_dealt_riders",
    "_lower_damage_conjunction",
    "_lower_coin_flip_damage_loop",
    "_lower_coin_flip_stakes_loop",
    "_lower_damage_this_game_history",
    "_lower_damage_cant_be_prevented",
    "_lower_damage_becomes_counter_removal",
    "_lower_prevent_damage",
    "_lower_prevent_half",
    "_lower_double_combat_damage",
    "_lower_redirect_damage",
    "_lower_prevent_all",
    "_fused_tap_any_number_then_pump",
    "_fused_two_target_pump",
    "_lower_become_creature",
    "_lower_pump",
    "_lower_change_base_pt",
    "_lower_set_base_pt",
    "_KEYWORD_GRANTS",
    "_lower_gain_ability_text",
    "_lower_gain_keyword",
    "_lower_lose_keyword",
    "_lower_player_gets_counters",
    "_fused_tap_enchanted_then_counters",
    "_lower_put_counter",
    "_PER_DEATH_COUNTERS",
    "_PER_DEATH_SUBJECT",
    "_ANY_CREATURE_DIED",
    "_lower_move_counter",
    "_lower_remove_counter",
    "_lower_for_each",
    "_lower_become_color",
    "_lower_change_land_type",
    "_lower_change_supertype",
    "_lower_gain_type",
    "_lower_change_text",
    "_DESTROY_ALL_KINDS",
    "_BASIC_LAND_TYPES",
    "_BLOCK_PAIR_EVENTS",
    "binds_block_pair",
    "_lower_destroy",
    "_fused_cost_repeated_destroys",
    "_lower_for_each_destroyed",
    "_lower_delayed_destroy",
    "_lower_doesnt_untap_next_step",
    "_lower_untap_restriction",
    "_lower_untap_chosen_by_paying",
    "_lower_delayed_self_action",
    "_lower_doesnt_untap_while_source_tapped",
    "_lower_tap",
    "_reads_no_return_restriction",
    "_lower_cant_phase_out",
    "_lower_phase_out",
    "_lower_land_type_swap",
    "_lower_simultaneous_phasing",
    "_lower_put_on_library_bottom",
    "_lower_put_graveyard_top_on_library_bottom",
    "_lower_put_on_library_top",
    "_lower_put_onto_battlefield",
    "_lower_reanimate_enchanted_card",
    "_lower_return_to_zone",
    "_lower_put_source_into_zone",
    "_lower_return_self_instead_of_untapping",
    "_lower_reveal_top",
    "_lower_reveal_until",
    "_lower_simultaneous_untap_and_tap",
    "_lower_tap_or_untap",
    "_lower_attach",
    "_lower_choose_permanent",
    "_lower_choose_permanents",
    "_lower_exchange_control",
    "_lower_exchange_greatest_mana_value",
    "_lower_regenerate",
    "_lower_destroy_unless_pay",
    "_lower_rebalance_lands",
    "_lower_sacrifice_unless_pay",
    "_lower_bid_life_for_control",
    "_lower_gain_control",
    "_lower_sacrifice",
    "_lower_sacrifice_expansion_permanents",
    "_lower_destroy_each_unless_paid",
    "_lower_shuffle_graveyard_into_library",
    "_lower_shuffle_hand_into_library",
    "_lower_shuffle_library",
    "_lower_reveal_top_of_library",
    "_EXILED_CREATURE",
    "_lower_exile",
    "_lower_exile_cost_sacrifices",
    "_lower_for_each_exiled",
    "_lower_for_each_tapped",
    "_fused_exile_then_controller_life",
    "_DAMAGED_PLAYER_EVENTS",
    "CHOSEN_HAND_CARDS_RESULT",
    "HAND_CARDS_TO_LIBRARY_RESULT",
    "_lower_choose_cards_in_hand",
    "_lower_for_each_chosen",
    "_lower_for_each_short_of_this_way",
    "_lower_put_iterated_card_on_library",
    "_lower_discard",
    "_fused_discard_then_draw",
    "_fused_draw_then_discard",
    "_lower_draw",
    "_lower_next_draw_replacement",
    "_lower_mill",
    "_lower_mill_until",
    "_lower_put_milled_card_onto_battlefield",
    "_lower_put_hand_cards_on_library",
    "_lower_scry",
    "_lower_add_mana",
    "_lower_note_mana_spent",
    "_TAPPED_LAND_MANA_RECIPIENTS",
    "_lower_activate_each_lands_mana_ability",
    "_lower_add_mana_for_tapped_land",
    "_lower_lose_unspent_mana",
    "_lower_produces_mana_instead",
    "_lower_spend_mana_as_though",
    "_lower_double_power",
    "_lower_switch_pt",
    "_fused_prepare_then_interact",
    "_lower_fight",
    "_lower_exile_graveyard",
    "_lower_put_exiled_card_into_zone",
    "_lower_discard_revealed_matching_unless_pay_life",
    "_lower_discard_revealed_unless_pay_life",
    "_lower_play_with_hand_revealed",
    "_lower_reveal_hand",
    "_lower_reveal_random_from_hand",
    "_lower_reveal_hand_and_choose",
    "_lower_look_at_hand",
    "_lower_bin_revealed_card",
    "_lower_graveyard_top_to_library",
    "_lower_look_at_library_top",
    "_lower_look_top_cycle_for_life",
    "_lower_separate_library_top_into_piles",
    "_SEARCH_HONOURED_FILTER_FIELDS",
    "_lower_graveyard_pick_onto_battlefield",
    "_lower_search_library",
    "_SEARCH_EXILE_HONOURED",
    "_lower_cast_from_exiled_with",
    "_lower_cast_permission",
    "_lower_exile_graveyard_until_leaves",
    "_lower_put_exiled_pile_top_into_hand",
    "_lower_force_chosen_creature_to_attack",
    "_lower_transmute_by_sacrifice",
    "_lower_exile_until_leaves_or_untaps",
    "_lower_ownership_exchange_unless_paid",
    "_lower_ante_offer_ownership_exchange",
    "_lower_random_reveal_ownership_exchange",
    "_lower_exile_top_of_library",
    "_lower_exile_entire_library",
    "_lower_put_exiled_with_source",
    "_lower_look_top_exile_random",
    "_lower_look_top_pick",
    "_lower_search_and_exile",
    "_lower_search_player_library",
    "_COUNTER_HONOURED_FILTER_FIELDS",
    "_COUNTER_UNLESS_PAYS_X",
    "_COUNTER_PERFORMED_PENALTIES",
    "_fused_conditional_counter",
    "_lower_change_target",
    "_lower_counter_ability",
    "_lower_choose_target",
    "_lower_waive_shroud",
    "_lower_counter_spell",
    "_lower_create_delayed_trigger",
    "_lower_modal_head",
    "_lower_combat_restriction",
    "lower_block_count_grant",
    "_lower_cant_be",
    "_lower_attack_as_though",
    "_lower_assigns_no_combat_damage",
    "_lower_attacks_this_turn_if_able",
    "_lower_attacking_doesnt_tap",
    "_lower_choose_blocks_for_defenders",
    "_lower_reassign_blockers_between_attackers",
    "_lower_become_blocked",
    "_lower_remove_from_combat",
    "_lower_ante",
    "_lower_repeat_process",
    "_lower_exchange_life_totals",
    "_lower_set_life_total",
    "_lower_gain_life",
    "_title",
    "_lower_count_objects",
    "_lower_create_emblem",
    "_lower_create_copy_token",
    "_lower_create_token",
    "_lower_extra_turn",
    "_LOSE_GAME_KINDS",
    "_lower_lose_game",
    "_lower_win_game",
    "_lower_lose_life",
    "_lower_pay_life",
    "count_spec",
    "halved_count_spec",
]
