"""Effect productions: one per thing a card can *do*.

The bulk of the grammar, and the package a new template usually lands in. Split
into seven families that share no code with each other — the two fragments they
all wanted (`_parse_zone`, `_parse_mana_payment`) are in `grammar/phrases.py`
precisely so this stays true. Independence is the point: it is what makes
"where does prowess go?" a question with an answer.

    damage           dealing it, and preventing it
    characteristics  P/T, keywords, colour, printed text, counters
    board            destruction, sacrificing
    returns          an object put back into a zone it came from
    tapping          tapping, and not untapping
    cards            drawing, discarding, milling, searching, revealing
    mana             producing it, and changing what a permanent produces
    stack            countering, choosing modes, and declining a cost
    combat           can't-attack / can't-be-blocked restrictions
    game             tokens, winning, extra turns, enchant

Every production here owes the same invariant: match and account for **every
token** of what it consumes, or raise `GrammarError`. A production that reads
most of its clause and shrugs at the rest is the dropped-rider bug the
parse-coverage probe exists to catch.

This module re-exports the families flat, so callers say
`from .effects import _parse_damage` and do not have to know which family a
production is in — moving one between families is not a caller-visible change.
"""

from .damage import (
    _parse_fight,
    _parse_damage,
    _parse_damage_unless_pay,
    _parse_have_source_deal_damage,
    _parse_damage_rider_sentence,
    _parse_damage_dealt_riders,
)
from .prevention import (
    _parse_prevent,
    _parse_prevent_all,
    _parse_source_of_choice_effect,
    _parse_damage_redirect,
    _parse_optional_damage_redirect,
    _parse_damage_cant_be_prevented,
    parse_source_damage_lock,
    _parse_bound_targeting_prevention,
)
from .tapping import (
    _parse_doesnt_untap_next_step,
    _parse_linked_untap_restriction,
    _parse_tap_untap,
    _parse_untap_chosen_by_paying,
)
from .counters import (
    _expect_counter_kind,
    _parse_distribute_counters,
    _parse_put_counter,
    _parse_remove_counter,
)
from .characteristics import (
    _parse_double,
    _parse_switch_pt,
    _parse_gets,
    _parse_gains,
    _parse_loses,
    _parse_has,
    _parse_has_base_pt,
    _parse_for_each,
    _TEXT_CHANGE_MODES,
    _parse_change_base_pt,
    _parse_becomes_base_pt,
    _parse_change_text,
)
from .types import (
    _parse_becomes,
    _parse_no_longer_supertype,
)
from .board import (
    _accept_life_alternative,
    _parse_for_each_destroy_unless_paid,
    _parse_sacrifice,
    _parse_counted_sacrifice,
    _parse_sacrifice_expansion_permanents,
    _parse_delayed_self_action,
    _parse_destroy,
    _parse_further_subjects,
    _parse_that_object,
)
from .returns import (
    _parse_return,
    _parse_put_source_into_zone,
)
from .attachments import (
    _parse_attach,
    parse_player_chooses_permanent,
)
from .control_changes import (
    _parse_exchange_control,
    _parse_gain_control,
)
from .mana import (
    _parse_add_mana,
    _parse_note_mana_spent,
    _parse_player_adds_mana,
    _parse_produces_instead,
    _parse_tapper_produces_instead,
    _parse_spend_mana_as_though,
)
from .exile import (
    _parse_exile_bound_card,
    _parse_put_exiled_card_into_hand,
    _parse_exile_cost_sacrifices,
    _parse_exile_graveyard,
    _parse_put_exiled_with_source,
)
from .cards import (
    _parse_draw,
    _parse_choose_cards_in_hand,
    _parse_discard,
    _parse_discard_revealed_unless_pay_life,
    _parse_mill,
    _parse_scry,
    _parse_cast_permission,
    _parse_play_with_hand_revealed,
    _parse_reveal_hand,
    _parse_reveal_hand_and_choose,
    parse_put_milled_card_onto_battlefield,
    _parse_put_hand_cards_on_library,
    _parse_player_puts_whole_hand_on_library,
    _parse_repeated_graveyard_pick,
    _parse_player_puts_hand_cards_on_library,
)
from .library import (
    _parse_shuffle_graveyard_into_library,
    _parse_shuffle_hand_into_library,
    _parse_shuffle_library,
    _parse_exile_top_of_library,
    _parse_exile_entire_library,
    _parse_look_at_hand,
    _parse_put_iterated_card_on_library,
    _parse_reveal_top,
    parse_player_looks_at_own_library_top,
    parse_player_separates_your_library_top,
)
from .search import _parse_search_library
from .stack import (
    _parse_can_be_targeted_as_though,
    _parse_change_target,
    _parse_copy_that_spell,
    _parse_copy_this_spell,
    _parse_counter,
    _parse_modal_head,
    _UNPAID_PENALTIES,
    _parse_unpaid_penalty_sentence,
    _parse_activation_restriction,
    _parse_x_spend_restriction,
    _parse_cost_x_definition,
)
from .combat import (
    parse_block_count_grant,
    _parse_assigns_no_combat_damage,
    _parse_force_chosen_creature_to_attack,
    _parse_attacking_doesnt_tap,
    _parse_cant_attack_or_block,
    _CANT_BE_ACTIONS,
    _parse_cant_be,
    _parse_remove_from_combat,
    _parse_choose_blocks_for_defenders,
)
from .game import (
    _parse_ante,
    _parse_exchange_life_totals,
    _parse_life_total_becomes,
    _parse_wins,
    _parse_choose_color,
    _parse_choose_number,
    _parse_count_objects,
    _parse_choose_player_who_cast,
    _parse_coin_flip_stakes_loop,
    _parse_flip_coin,
    _parse_game_is_a_draw,
    _parse_token_keywords,
    _parse_create_token,
    _parse_create_token_for_recipient,
    _parse_enchant,
    _parse_end_the_turn,
    _parse_extra_turn,
    _parse_skip_step,
)

__all__ = [
    "_parse_damage",
    "_parse_damage_unless_pay",
    "_parse_have_source_deal_damage",
    "_accept_life_alternative",
    "_parse_for_each_destroy_unless_paid",
    "_parse_damage_rider_sentence",
    "_parse_prevent",
    "_parse_prevent_all",
    "_parse_source_of_choice_effect",
    "_parse_damage_redirect",
    "_parse_optional_damage_redirect",
    "_parse_damage_cant_be_prevented",
    "parse_source_damage_lock",
    "_parse_bound_targeting_prevention",
    "_parse_damage_dealt_riders",
    "_parse_gets",
    "_parse_gains",
    "_parse_loses",
    "_parse_has",
    "_parse_has_base_pt",
    "_expect_counter_kind",
    "_parse_for_each",
    "_parse_distribute_counters",
    "_parse_put_counter",
    "_parse_remove_counter",
    "_TEXT_CHANGE_MODES",
    "_parse_change_base_pt",
    "_parse_becomes_base_pt",
    "_parse_change_text",
    "_parse_becomes",
    "_parse_no_longer_supertype",
    "_parse_gain_control",
    "parse_player_chooses_permanent",
    "_parse_return",
    "_parse_put_source_into_zone",
    "_parse_destroy",
    "_parse_further_subjects",
    "_parse_that_object",
    "_parse_doesnt_untap_next_step",
    "_parse_linked_untap_restriction",
    "_parse_tap_untap",
    "_parse_untap_chosen_by_paying",
    "_parse_attach",
    "_parse_exchange_control",
    "_parse_draw",
    "_parse_choose_cards_in_hand",
    "_parse_put_iterated_card_on_library",
    "_parse_sacrifice",
    "_parse_counted_sacrifice",
    "_parse_sacrifice_expansion_permanents",
    "_parse_delayed_self_action",
    "_parse_shuffle_graveyard_into_library",
    "_parse_shuffle_hand_into_library",
    "_parse_shuffle_library",
    "_parse_discard",
    "_parse_discard_revealed_unless_pay_life",
    "_parse_mill",
    "_parse_scry",
    "_parse_skip_step",
    "_parse_add_mana",
    "_parse_note_mana_spent",
    "_parse_cast_permission",
    "_parse_exile_bound_card",
    "_parse_put_exiled_card_into_hand",
    "_parse_exile_cost_sacrifices",
    "_parse_exile_graveyard",
    "_parse_play_with_hand_revealed",
    "_parse_reveal_hand",
    "_parse_reveal_hand_and_choose",
    "_parse_exile_top_of_library",
    "_parse_exile_entire_library",
    "_parse_put_exiled_with_source",
    "parse_put_milled_card_onto_battlefield",
    "_parse_put_hand_cards_on_library",
    "_parse_player_puts_whole_hand_on_library",
    "_parse_repeated_graveyard_pick",
    "_parse_player_puts_hand_cards_on_library",
    "_parse_player_adds_mana",
    "_parse_produces_instead",
    "_parse_tapper_produces_instead",
    "_parse_spend_mana_as_though",
    "_parse_double",
    "_parse_switch_pt",
    "_parse_fight",
    "_parse_look_at_hand",
    "_parse_reveal_top",
    "_parse_search_library",
    "parse_player_looks_at_own_library_top",
    "parse_player_separates_your_library_top",
    "_parse_can_be_targeted_as_though",
    "_parse_change_target",
    "_parse_copy_that_spell",
    "_parse_copy_this_spell",
    "_parse_counter",
    "_parse_modal_head",
    "_UNPAID_PENALTIES",
    "_parse_unpaid_penalty_sentence",
    "_parse_activation_restriction",
    "_parse_x_spend_restriction",
    "_parse_cost_x_definition",
    "_parse_cant_attack_or_block",
    "parse_block_count_grant",
    "_parse_assigns_no_combat_damage",
    "_parse_force_chosen_creature_to_attack",
    "_parse_attacking_doesnt_tap",
    "_parse_remove_from_combat",
    "_parse_choose_blocks_for_defenders",
    "_CANT_BE_ACTIONS",
    "_parse_cant_be",
    "_parse_ante",
    "_parse_exchange_life_totals",
    "_parse_life_total_becomes",
    "_parse_wins",
    "_parse_choose_color",
    "_parse_choose_number",
    "_parse_count_objects",
    "_parse_choose_player_who_cast",
    "_parse_coin_flip_stakes_loop",
    "_parse_flip_coin",
    "_parse_game_is_a_draw",
    "_parse_token_keywords",
    "_parse_create_token",
    "_parse_create_token_for_recipient",
    "_parse_enchant",
    "_parse_end_the_turn",
    "_parse_extra_turn",
]
