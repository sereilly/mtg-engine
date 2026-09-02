"""The node-type registry ``lower.py`` dispatches through.

One row per AST node whose lowering needs nothing but the node — no event,
no ``produced`` set, no recursion back into the dispatcher. Everything that
does need one of those stays in ``lower.py``'s chain, which is why this is a
table and that is a function.

It left ``lower.py`` when Fallen Empires took that module past the 1,000-line
cap, for the reason ``lowering/_records.py`` already records about the two
tables that left it before: **the table is a registry either way, and
``lower.py`` is dispatch.** A registry sitting inside the dispatcher is the
thing that grows every time a card lands, so it is the half that moves.

Beside ``lower.py`` rather than under ``lowering/`` because it is part of the
dispatch layer, not one of the effect families: no family imports it, and a
module inside that package that no family reads would be neither a family nor
a floor.
"""

from __future__ import annotations

from ..oracle_types import OracleInstruction
from . import ast
from .derived import derived_instruction_for_line
from .errors import LoweringError
from .lowering._events import CHOSEN_PLAYER
from .lowering.where_x import lower_where_x
from .statics import _lower_static_ability
from .lowering.control_flow import (
    _lower_for_each_life_lost,
    _lower_for_each_matching,
    _lower_for_each_player,
    _lower_may, _lower_one_of, _lower_steps, _lower_unless_player_pays,
)
from .lowering import (
    # Re-exported, not used here: callers outside the package import these two
    # from `engine.grammar.lower` (`grammar/__init__.py`,
    # `tests/engine/test_grammar_categories.py`, `test_grammar_lowering.py`).
    # Moving the definitions into `lowering/` did not move their address, which
    # is what kept this a pure move rather than a rename with a diff attached.
    GRAMMAR_ONLY_PAYLOAD_KEYS,
    INSTRUCTION_CATEGORIES,
    categories_of,
    _lower_produces_mana_instead,
    _lower_spend_mana_as_though,
    _lower_change_land_type,
    _lower_change_supertype,
    _lower_gain_type,
    _lower_attack_as_though,
    _lower_assigns_no_combat_damage,
    _lower_attacking_doesnt_tap,
    _lower_change_text,
    _lower_counter_ability,
    _lower_choose_target,
    _lower_waive_shroud,
    _lower_change_target,
    _lower_counter_spell,
    _lower_create_emblem,
    _lower_create_copy_token,
    _lower_damage_dealt_riders,
    _lower_coin_flip_damage_loop,
    _lower_coin_flip_stakes_loop,
    _lower_damage_this_game_history,
    _lower_draw,
    _lower_put_source_into_zone,
    _lower_extra_turn,
    _lower_choose_cards_in_hand,
    _lower_put_iterated_card_on_library,
    _lower_pay_life,
    _lower_ante,
    _lower_exchange_life_totals,
    _lower_set_life_total,
    _lower_double_power,
    _lower_switch_pt,
    _lower_exile_cost_sacrifices,
    _lower_exile_graveyard,
    _lower_reveal_hand,
    _lower_reveal_random_from_hand,
    _lower_look_at_hand,
    _lower_look_at_library_top,
    _lower_lose_game,
    _lower_put_hand_cards_on_library,
    _lower_scry,
    _lower_prevent_damage,
    _lower_redirect_damage,
    _lower_damage_cant_be_prevented,
    _lower_become_creature,
    _lower_pump,
    _lower_phase_out,
    _lower_put_on_library_bottom,
    _lower_put_on_library_top,
    _lower_regenerate,
    _lower_reveal_top,
    _lower_reveal_top_of_library,
    _lower_reanimate_enchanted_card,
    _lower_sacrifice_expansion_permanents,
    _lower_shuffle_graveyard_into_library,
    _lower_shuffle_hand_into_library,
    _lower_shuffle_library,
    _lower_destroy_each_unless_paid,
    _lower_sacrifice_unless_pay,
    _lower_cast_from_exiled_with,
    _lower_exile_graveyard_until_leaves,
    _lower_choose_blocks_for_defenders,
    _lower_force_chosen_creature_to_attack,
    _lower_reassign_blockers_between_attackers,
    _lower_transmute_by_sacrifice,
    _lower_exile_until_leaves_or_untaps,
    _lower_ownership_exchange_unless_paid,
    _lower_ante_offer_ownership_exchange,
    _lower_random_reveal_ownership_exchange,
    _lower_exile_top_of_library,
    _lower_put_exiled_with_source,
    _lower_look_top_exile_random,
    _lower_search_and_exile,
    _lower_search_library,
    _lower_change_base_pt,
    _lower_set_base_pt,
    _lower_delayed_self_action,
    _lower_damage_reduced_by_paid_mana,
    _lower_upkeep_damage_unless_cost,
    _lower_doesnt_untap_while_source_tapped,
    _lower_tap_or_untap,
    _lower_attach,
    _lower_count_objects,
    _lower_exchange_control,
    _lower_exchange_greatest_mana_value,
    _lower_win_game,
)


#: The node types whose lowering is *only* a name — one AST class, one
#: function, nothing to decide. These were 78 two-line branches of the chain
#: below: 156 lines saying what a dict says in 78, growing by three every time
#: a round adds a node. Dispatching them by type is what every other seam in
#: this engine already does (`EFFECT_HANDLERS` is the one the architecture
#: notes name), and it is what the module-size guard was pointing at — the
#: families were absorbing the work; the chain grew anyway, by construction.
#:
#: The chain below keeps every branch that *decides* something: a node whose
#: lowering depends on its own fields, on the firing event, or on which of
#: several kinds it should become.
#:
#: Read before the chain, which is safe by construction rather than by
#: inspection: no class in this table appears anywhere else in the chain and
#: none of them inherits from another, so at most one branch could ever have
#: matched a given node.
_BY_NODE_TYPE: dict[type, object] = {
    ast.DamageRidersUntilEndOfTurn: _lower_damage_dealt_riders,
    ast.DamageThoseDamagedThisGame: _lower_damage_this_game_history,
    ast.CoinFlipDamageLoop: _lower_coin_flip_damage_loop,
    ast.CoinFlipStakesLoop: _lower_coin_flip_stakes_loop,
    ast.Pump: _lower_pump,
    ast.SetBasePT: _lower_set_base_pt,
    ast.ChangeBasePT: _lower_change_base_pt,
    ast.ReanimateEnchantedCard: _lower_reanimate_enchanted_card,
    ast.DoublePower: _lower_double_power,
    ast.SwitchPT: _lower_switch_pt,
    ast.Ante: _lower_ante,
    ast.ExchangeLifeTotals: _lower_exchange_life_totals,
    ast.SetLifeTotal: _lower_set_life_total,
    ast.PayLife: _lower_pay_life,
    ast.DelayedSelfAction: _lower_delayed_self_action,
    ast.DamageReducedByPaidMana: _lower_damage_reduced_by_paid_mana,
    ast.UpkeepDamageUnlessCost: _lower_upkeep_damage_unless_cost,
    ast.DoesntUntapWhileSourceTapped: _lower_doesnt_untap_while_source_tapped,
    ast.TapOrUntap: _lower_tap_or_untap,
    ast.Attach: _lower_attach,
    ast.CountObjects: _lower_count_objects,
    ast.ExchangeControl: _lower_exchange_control,
    ast.ExchangeGreatestManaValue: _lower_exchange_greatest_mana_value,
    ast.Draw: _lower_draw,
    ast.PutHandCardsOnLibrary: _lower_put_hand_cards_on_library,
    ast.Scry: _lower_scry,
    ast.ProducesManaInstead: _lower_produces_mana_instead,
    ast.SpendManaAsThough: _lower_spend_mana_as_though,
    ast.CreateCopyToken: _lower_create_copy_token,
    ast.CreateEmblem: _lower_create_emblem,
    ast.SacrificeUnlessPay: _lower_sacrifice_unless_pay,
    ast.DestroyEachUnlessPaid: _lower_destroy_each_unless_paid,
    ast.BecomeCreature: _lower_become_creature,
    ast.ChangeText: _lower_change_text,
    ast.PreventDamage: _lower_prevent_damage,
    ast.RedirectDamage: _lower_redirect_damage,
    ast.DamageCantBePreventedOrRedirected: _lower_damage_cant_be_prevented,
    ast.Regenerate: _lower_regenerate,
    ast.CounterAbility: _lower_counter_ability,
    ast.CounterSpell: _lower_counter_spell,
    ast.ChangeTarget: _lower_change_target,
    ast.PhaseOut: _lower_phase_out,
    ast.PutOnLibraryTop: _lower_put_on_library_top,
    ast.ChooseCardsInHand: _lower_choose_cards_in_hand,
    ast.PutIteratedCardOnLibrary: _lower_put_iterated_card_on_library,
    ast.PutOnLibraryBottom: _lower_put_on_library_bottom,
    ast.RevealTopToHandOrBottom: _lower_reveal_top,
    ast.SacrificeExpansionPermanents: _lower_sacrifice_expansion_permanents,
    ast.GainType: _lower_gain_type,
    ast.ChangeSupertype: _lower_change_supertype,
    ast.ChangeLandType: _lower_change_land_type,
    ast.ShuffleGraveyardIntoLibrary: _lower_shuffle_graveyard_into_library,
    ast.ShuffleHandIntoLibrary: _lower_shuffle_hand_into_library,
    ast.ShuffleLibrary: _lower_shuffle_library,
    # CR 701.20a's bare reveal. It moved out of `lower.py`'s if-chain when
    # it grew a field: the chain's branch built the instruction inline
    # because the node had nothing to read, and a lowering that reads its
    # node is exactly what this table is for.
    ast.RevealTop: _lower_reveal_top_of_library,
    ast.RevealHand: _lower_reveal_hand,
    ast.RevealRandomFromHand: _lower_reveal_random_from_hand,
    ast.ExileCostSacrifices: _lower_exile_cost_sacrifices,
    ast.ExileGraveyard: _lower_exile_graveyard,
    ast.LookAtHand: _lower_look_at_hand,
    ast.LookAtLibraryTop: _lower_look_at_library_top,
    ast.SearchLibrary: _lower_search_library,
    ast.ExileTopOfLibrary: _lower_exile_top_of_library,
    ast.PutExiledWithSource: _lower_put_exiled_with_source,
    ast.LookTopExileRandom: _lower_look_top_exile_random,
    ast.SearchAndExile: _lower_search_and_exile,
    ast.ForceChosenCreatureToAttack: _lower_force_chosen_creature_to_attack,
    ast.ExileGraveyardUntilLeaves: _lower_exile_graveyard_until_leaves,
    ast.TransmuteBySacrifice: _lower_transmute_by_sacrifice,
    ast.OwnershipExchangeUnlessPaid: _lower_ownership_exchange_unless_paid,
    ast.AnteOfferOwnershipExchange: _lower_ante_offer_ownership_exchange,
    ast.RandomRevealOwnershipExchange: _lower_random_reveal_ownership_exchange,
    ast.ExileUntilLeavesOrUntaps: _lower_exile_until_leaves_or_untaps,
    ast.CastFromExiledWith: _lower_cast_from_exiled_with,
    ast.ExtraTurn: _lower_extra_turn,
    ast.LoseGame: _lower_lose_game,
    ast.WinGame: _lower_win_game,
    ast.AttackAsThough: _lower_attack_as_though,
    ast.AssignsNoCombatDamage: _lower_assigns_no_combat_damage,
    ast.AttackingDoesntTap: _lower_attacking_doesnt_tap,
    ast.ChooseTarget: _lower_choose_target,
    ast.WaiveShroud: _lower_waive_shroud,
    ast.ChooseBlocksForDefenders: _lower_choose_blocks_for_defenders,
    ast.ReassignBlockersBetweenAttackers: _lower_reassign_blockers_between_attackers,
    ast.PutSourceIntoZone: _lower_put_source_into_zone,
}
