"""The node-type registries ``lower_statement`` dispatches through.

One row per AST node whose lowering **decides nothing the dispatcher has to
know about**: one node class, one function, called the same way as every other
row of its table. That is the line, and it is drawn on what the dispatcher does
rather than on what the lowering reads — which is why there are four tables
rather than one, a row's table being only *which arguments its function takes*:

* :data:`_BY_NODE_TYPE` — the node alone;
* :data:`_BY_NODE_TYPE_WITH_EVENT` — and the firing ``event``, raw;
* :data:`_BY_NODE_TYPE_WITH_PRODUCED` — and the records earlier steps wrote;
* :data:`_BY_NODE_TYPE_WITH_EVENT_AND_PRODUCED` — and both.

What stays in ``statement_dispatch.py``'s chain is an arm that chooses between
families or lowerings, passes something no table carries (the trigger's
narrowing, ``whole_effect``, the filtered event) or recurses into the
dispatcher — which is why these are tables and that is a function. This
paragraph said "needs nothing but the node — no event, no ``produced`` set"
from Fallen Empires until Invasion's Phase 0, though the second table arrived at
Visions' first wave and the third at its fourth — and the chain's arms quoted it
back as their reason for being arms. Thirteen of them were rows of the third
table and came across at that Phase 0.

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
from .lowering import (_lower_play_with_hand_revealed, _lower_add_mana_for_tapped_land, _lower_activate_each_lands_mana_ability, _lower_lose_unspent_mana,
                       _lower_discard, _lower_exile_entire_library,
                       _lower_exile_random_from_hand, _lower_mill,
                       _lower_exile_cards_from_hand,
                       _lower_move_counter, _lower_note_mana_spent,
                       _lower_bid_life_for_control, _lower_become_blocked,
                       _lower_produces_mana_instead, _lower_spend_mana_as_though,
                       _lower_change_land_type, _lower_change_supertype,
                       _lower_become_aura, _lower_untap_chosen_by_paying,
                       _lower_reveal_hand_and_choose, _lower_look_top_pick,
                       _lower_player_gets_counters,
                       _lower_gain_type, _lower_attack_as_though,
                       _lower_assigns_combat_damage_as_unblocked,
                       _lower_assigns_no_combat_damage, _lower_attacking_doesnt_tap,
                       _lower_attacks_this_turn_if_able,
    _lower_blocks_this_turn_if_able,
                       _lower_change_text, _lower_counter_ability, _lower_choose_target,
                       _lower_destroy_countered_ability_source,
                       _lower_put_graveyard_position_onto_battlefield,
                       _lower_waive_shroud, _lower_change_target, _lower_counter_spell,
                       _lower_put_exiled_card_on_stack_as_copy,
                       _lower_create_emblem, _lower_create_copy_token,
                       _lower_damage_dealt_riders, _lower_coin_flip_damage_loop,
                       _lower_coin_flip_stakes_loop, _lower_damage_this_game_history,
                       _lower_repeat_process_request,
                       _lower_put_source_into_zone,
                       _lower_return_self_instead_of_untapping, _lower_extra_turn,
                       _lower_become_copy,
                       _lower_extra_phases,
                       _lower_choose_cards_in_hand, _lower_put_iterated_card_on_library,
                       _lower_pay_life, _lower_ante, _lower_exchange_life_totals,
                       _lower_set_life_total, _lower_double_power, _lower_switch_pt,
                       _lower_lose_ability_text,
                       _lower_exile_cost_sacrifices, _lower_exile_graveyard,
                       _lower_exile_graveyard_arrivals_this_turn,
                       _lower_reveal_hand, _lower_reveal_random_from_hand,
                       _lower_reveal_cards_from_hand,
                       _lower_graveyard_top_to_library,
                       _lower_reveal_top_sorting_by_filter,
                       _lower_look_at_hand, _lower_look_at_library_top,
                       _lower_look_top_cycle_for_life,
                       _lower_separate_library_top_into_piles,
                       _lower_lose_game, _lower_mill_until,
                       _lower_put_hand_cards_on_library, _lower_scry,
                       _lower_damage_becomes_counter_removal,
                       _lower_redirect_damage, _lower_double_combat_damage,
                       _lower_choose_damage_source,
                       _lower_damage_cant_be_prevented, _lower_become_creature,
                       _lower_destroy_chosen_that_didnt_attack,
                       _lower_cant_phase_out,
                       _lower_land_type_swap,
                       _lower_simultaneous_phasing,
                       _lower_simultaneous_untap_and_tap,
                       _lower_put_on_library_bottom,
                       _lower_put_graveyard_top_on_library_bottom,
                       _lower_regenerate, _lower_reveal_top,
                       _lower_reveal_top_of_library, _lower_reanimate_enchanted_card,
                       _lower_sacrifice_expansion_permanents,
                       _lower_shuffle_graveyard_into_library,
                       _lower_shuffle_source_into_library,
                       _lower_shuffle_target_into_library,
                       _lower_shuffle_hand_into_library, _lower_shuffle_library,
                       _lower_destroy_each_unless_paid,
                       _lower_cast_from_exiled_with,
                       _lower_exile_graveyard_until_leaves,
                       _lower_put_exiled_pile_top_into_hand,
                       _lower_choose_blocks_for_defenders,
                       _lower_force_chosen_creature_to_attack,
                       _lower_reassign_blockers_between_attackers,
                       _lower_transmute_by_sacrifice,
                       _lower_rebalance_lands,
                       _lower_keep_chosen_sacrifice_rest,
                       _lower_exile_until_leaves_or_untaps,
                       _lower_ownership_exchange_unless_paid,
                       _lower_ante_offer_ownership_exchange,
                       _lower_random_reveal_ownership_exchange,
                       _lower_exile_top_of_library,
                       _lower_exile_graveyard_position,
                       _lower_sacrifice_and_return_targets,
                       _lower_random_graveyard_card_fate,
                       _lower_look_top_exile_random, _lower_search_and_exile,
                       _lower_put_exiled_pile_on_library,
                       _lower_graveyard_top_opponent_chooses,
                       _lower_reveal_top_opponent_chooses,
                       _lower_search_reveal_opponent_chooses,
                       _lower_strip_cards_with_chosen_name,
                       _lower_search_library, _lower_change_base_pt, _lower_set_base_pt,
                       _lower_delayed_self_action, _lower_damage_reduced_by_paid_mana,
                       _lower_skip_phase,
                       _lower_skip_step,
                       _lower_skip_turn,
                       _lower_bound_permanent_activation_ban,
                       _lower_targeting_ban,
                       _lower_extra_land_plays,
                       _lower_cant_activate_nonmana_abilities,
                       _lower_cant_cast_spell_types,
                       _lower_cant_play_lands,
                       _lower_upkeep_counter_toll,
                       _lower_upkeep_damage_unless_cost,
                       _lower_doesnt_untap_while_source_tapped, _lower_tap_or_untap,
                       _lower_attach, _lower_count_objects, _lower_exchange_control,
                       _lower_exchange_greatest_mana_value,
                       _lower_mutual_control_of_sets,
                       _lower_pay_or_sacrifice_greatest_mana_value,
                       _lower_win_game,
                       # The rows that left `statement_dispatch`'s chain at
                       # Invasion's Phase 0 — see each table's own note.
                       lower_block_count_grant,
                       _lower_sacrifice, _lower_tap,
                       _lower_sacrifice_unless_pay,
                       _lower_chosen_source_next_damage, _lower_add_mana,
                       _lower_bin_revealed_card,
                       _lower_put_milled_card_onto_battlefield,
                       _lower_discard_revealed_unless_pay_life,
                       _lower_discard_revealed_matching_unless_pay_life,
                       _lower_play_with_top_revealed,
                       _lower_search_player_library,
                       _lower_remove_from_combat,
                       _lower_put_library_top_into_hand,
                       _lower_put_exiled_with_source,
                       _lower_each_player_claims_exiled_card)


#: The node types whose lowering is *only* a name — one AST class, one
#: function, nothing to decide. These were 78 two-line branches of
#: ``lower_statement``'s chain: 156 lines saying what a dict says in 78, growing
#: by three every time a round adds a node. Dispatching them by type is what
#: every other seam in this engine already does (`EFFECT_HANDLERS` is the one
#: the architecture notes name), and it is what the module-size guard was
#: pointing at — the families were absorbing the work; the chain grew anyway,
#: by construction.
#:
#: That chain — in ``statement_dispatch.py`` since Alliances — keeps every
#: branch that *decides* something: which family or which lowering a node goes
#: to, or what to hand it beyond the arguments these four tables carry. That a
#: lowering reads the firing event or the records is not such a decision; the
#: wider tables below are for exactly those.
#:
#: Read before the chain, which is safe by construction rather than by
#: inspection: no class in this table appears anywhere else in the chain and
#: none of them inherits from another, so at most one branch could ever have
#: matched a given node.
_BY_NODE_TYPE: dict[type, object] = {
    # Five arms that had stayed in `statement_dispatch`'s chain while asking
    # nothing of it — no `produced`, no `event`, no recursion — which is the
    # definition of an entry in this table. They moved at Visions' first wave,
    # when that module crossed the thousand-line guard and the seam it needed
    # was the one this file already is: a registry inside a dispatcher is the
    # half that grows, so it is the half that leaves.
    ast.MoveCounter: _lower_move_counter,
    ast.NoteManaSpent: _lower_note_mana_spent,
    # Illicit Auction. Beside the control change above rather than inside
    # it: what the two share is where the permanent ends up, and what
    # differs is that this one has to run an auction first to find out
    # whose it becomes.
    ast.BidLifeForControl: _lower_bid_life_for_control,
    ast.BecomeBlocked: _lower_become_blocked,
    # "Choose a card name." (Foreshadow.) The name is chosen as the spell
    # resolves (CR 608.2) and CR 202.1 lets a player name any card at all, so
    # nothing about it can be decided at lowering — the whole of the lowering
    # is the instruction.
    #
    # "Choose a **creature** card name." (Wood Sage.) The one thing a printing
    # can add, carried as payload and **only when it is printed**, so
    # Foreshadow's instruction stays byte-identical and no behaviour signature
    # moves — the same rule `NameThenRevealTop`'s `miss_damage` follows.
    ast.ChooseCardName: lambda node: (
        OracleInstruction(
            "choose_card_name", "",
            {"card_type": node.card_type} if node.card_type else {},
        ),
    ),
    ast.DamageRidersUntilEndOfTurn: _lower_damage_dealt_riders,
    ast.DamageThoseDamagedThisGame: _lower_damage_this_game_history,
    ast.CoinFlipDamageLoop: _lower_coin_flip_damage_loop,
    ast.CoinFlipStakesLoop: _lower_coin_flip_stakes_loop,
    ast.RepeatProcessRequest: _lower_repeat_process_request,
    ast.SetBasePT: _lower_set_base_pt,
    ast.ChangeBasePT: _lower_change_base_pt,
    ast.ReanimateEnchantedCard: _lower_reanimate_enchanted_card,
    ast.DoublePower: _lower_double_power,
    ast.SwitchPT: _lower_switch_pt,
    ast.Ante: _lower_ante,
    ast.ExchangeLifeTotals: _lower_exchange_life_totals,
    ast.SetLifeTotal: _lower_set_life_total,
    ast.LoseAbilityText: _lower_lose_ability_text,
    ast.PayLife: _lower_pay_life,
    ast.DelayedSelfAction: _lower_delayed_self_action,
    ast.DamageReducedByPaidMana: _lower_damage_reduced_by_paid_mana,
    ast.SkipStep: _lower_skip_step,
    ast.SkipTurn: _lower_skip_turn,
    ast.TargetingBan: _lower_targeting_ban,
    ast.ExtraLandPlays: _lower_extra_land_plays,
    ast.CantPlayLands: _lower_cant_play_lands,
    ast.CantCastSpellTypes: _lower_cant_cast_spell_types,
    ast.CantActivateNonManaAbilities: _lower_cant_activate_nonmana_abilities,
    ast.UpkeepCounterToll: _lower_upkeep_counter_toll,
    ast.UpkeepDamageUnlessCost: _lower_upkeep_damage_unless_cost,
    ast.TapOrUntap: _lower_tap_or_untap,
    ast.SimultaneousUntapAndTap: _lower_simultaneous_untap_and_tap,
    ast.CountObjects: _lower_count_objects,
    ast.ExchangeControl: _lower_exchange_control,
    ast.ExchangeGreatestManaValue: _lower_exchange_greatest_mana_value,
    ast.MutualControlOfSets: _lower_mutual_control_of_sets,
    ast.PayOrSacrificeGreatestManaValue: _lower_pay_or_sacrifice_greatest_mana_value,
    ast.MillUntil: _lower_mill_until,
    ast.Scry: _lower_scry,
    ast.ProducesManaInstead: _lower_produces_mana_instead,
    ast.SpendManaAsThough: _lower_spend_mana_as_though,
    ast.CreateEmblem: _lower_create_emblem,
    ast.DestroyEachUnlessPaid: _lower_destroy_each_unless_paid,
    ast.BecomeCreature: _lower_become_creature,
    ast.ChangeText: _lower_change_text,
    ast.DamageBecomesCounterRemoval: _lower_damage_becomes_counter_removal,
    ast.DoubleCombatDamage: _lower_double_combat_damage,
    ast.ChooseDamageSource: _lower_choose_damage_source,
    ast.RedirectDamage: _lower_redirect_damage,
    ast.DamageCantBePreventedOrRedirected: _lower_damage_cant_be_prevented,
    ast.Regenerate: _lower_regenerate,
    ast.CounterAbility: _lower_counter_ability,
    ast.ChangeTarget: _lower_change_target,
    ast.CantPhaseOut: _lower_cant_phase_out,
    ast.LandTypeSwap: _lower_land_type_swap,
    ast.SimultaneousPhasing: _lower_simultaneous_phasing,
    ast.ChooseCardsInHand: _lower_choose_cards_in_hand,
    ast.PutIteratedCardOnLibrary: _lower_put_iterated_card_on_library,
    ast.PutOnLibraryBottom: _lower_put_on_library_bottom,
    ast.PutGraveyardTopOnLibraryBottom: _lower_put_graveyard_top_on_library_bottom,
    ast.RevealTopToHandOrBottom: _lower_reveal_top,
    ast.SacrificeExpansionPermanents: _lower_sacrifice_expansion_permanents,
    ast.BecomeAura: _lower_become_aura,
    ast.GainType: _lower_gain_type,
    ast.ChangeSupertype: _lower_change_supertype,
    ast.ChangeLandType: _lower_change_land_type,
    ast.ShuffleGraveyardIntoLibrary: _lower_shuffle_graveyard_into_library,
    ast.ShuffleSourceIntoLibrary: _lower_shuffle_source_into_library,
    ast.ShuffleTargetIntoLibrary: _lower_shuffle_target_into_library,
    ast.ShuffleHandIntoLibrary: _lower_shuffle_hand_into_library,
    ast.ShuffleLibrary: _lower_shuffle_library,
    # CR 701.20a's bare reveal. It moved out of `lower.py`'s if-chain when
    # it grew a field: the chain's branch built the instruction inline
    # because the node had nothing to read, and a lowering that reads its
    # node is exactly what this table is for.
    ast.RevealTop: _lower_reveal_top_of_library,
    ast.RevealHand: _lower_reveal_hand,
    # "Reveal any number of blue cards in your hand." (Brine Seer.) The
    # chosen-subset reveal beside the whole-hand one, and a different node
    # for a different effect - see `ast.RevealCardsFromHand`.
    ast.RevealCardsFromHand: _lower_reveal_cards_from_hand,
    ast.RevealRandomFromHand: _lower_reveal_random_from_hand,
    ast.ExileCostSacrifices: _lower_exile_cost_sacrifices,
    ast.ExileGraveyard: _lower_exile_graveyard,
    ast.ExileGraveyardArrivalsThisTurn: _lower_exile_graveyard_arrivals_this_turn,
    ast.GraveyardTopToLibrary: _lower_graveyard_top_to_library,
    ast.LookAtLibraryTop: _lower_look_at_library_top,
    ast.LookTopCycleForLife: _lower_look_top_cycle_for_life,
    ast.SeparateLibraryTopIntoPiles: _lower_separate_library_top_into_piles,
    ast.ExileTopOfLibrary: _lower_exile_top_of_library,
    ast.ExileGraveyardPosition: _lower_exile_graveyard_position,
    ast.SacrificeAndReturnTargets: _lower_sacrifice_and_return_targets,
    ast.RandomGraveyardCardFate: _lower_random_graveyard_card_fate,
    ast.LookTopExileRandom: _lower_look_top_exile_random,
    ast.RevealTopOpponentChooses: _lower_reveal_top_opponent_chooses,
    ast.RevealTopSortingByFilter: _lower_reveal_top_sorting_by_filter,
    # The same pick over a pile a **search** found (Intuition), which is
    # why it is a row of its own rather than a field on that node: a search
    # finds what a player picks out of a hidden zone (CR 701.23a), where a
    # reveal off the top finds whatever is there.
    ast.SearchRevealOpponentChooses: _lower_search_reveal_opponent_chooses,
    # The same pick over a *public* pile (Phyrexian Grimoire): no reveal,
    # because CR 400.2 makes a graveyard public — see the node.
    ast.GraveyardTopOpponentChooses: _lower_graveyard_top_opponent_chooses,
    # Scroll Rack's linked pile going back on the library: the record
    # answers which cards, so the node carries the position and nothing
    # else — a row here rather than an arm in the chain.
    ast.PutExiledPileOnLibrary: _lower_put_exiled_pile_on_library,
    ast.SearchAndExile: _lower_search_and_exile,
    ast.ForceChosenCreatureToAttack: _lower_force_chosen_creature_to_attack,
    ast.ExileGraveyardUntilLeaves: _lower_exile_graveyard_until_leaves,
    ast.PutExiledPileTopIntoHand: _lower_put_exiled_pile_top_into_hand,
    ast.TransmuteBySacrifice: _lower_transmute_by_sacrifice,
    ast.RebalanceLands: _lower_rebalance_lands,
    ast.KeepChosenSacrificeRest: _lower_keep_chosen_sacrifice_rest,
    ast.OwnershipExchangeUnlessPaid: _lower_ownership_exchange_unless_paid,
    ast.AnteOfferOwnershipExchange: _lower_ante_offer_ownership_exchange,
    ast.RandomRevealOwnershipExchange: _lower_random_reveal_ownership_exchange,
    ast.ExileUntilLeavesOrUntaps: _lower_exile_until_leaves_or_untaps,
    ast.CastFromExiledWith: _lower_cast_from_exiled_with,
    ast.ExtraTurn: _lower_extra_turn,
    ast.ExtraPhases: _lower_extra_phases,
    ast.LoseGame: _lower_lose_game,
    ast.WinGame: _lower_win_game,
    ast.AttackAsThough: _lower_attack_as_though,
    ast.AssignsCombatDamageAsUnblocked: _lower_assigns_combat_damage_as_unblocked,
    ast.AssignsNoCombatDamage: _lower_assigns_no_combat_damage,
    ast.AttackingDoesntTap: _lower_attacking_doesnt_tap,
    ast.ChooseTarget: _lower_choose_target,
    ast.WaiveShroud: _lower_waive_shroud,
    # "…the player puts it onto the stack as a copy of the original spell."
    # (Ertai's Meddling.) A row rather than an arm in the chain: everything the
    # copy inherits was frozen into the exile register when the spell left the
    # stack, so the lowering reads the node and nothing else.
    ast.PutExiledCardOnStackAsCopy: _lower_put_exiled_card_on_stack_as_copy,
    ast.ChooseBlocksForDefenders: _lower_choose_blocks_for_defenders,
    ast.ReassignBlockersBetweenAttackers: _lower_reassign_blockers_between_attackers,
    ast.ReturnSelfInsteadOfUntapping: _lower_return_self_instead_of_untapping,
    # The permission twin of ``ast.CombatRestriction``, and its own node for
    # the node's own reason: the two say opposite things and share only the
    # rule they read (CR 509.1b). The restriction is an arm of the chain — it
    # is handed the ``whole_effect``-filtered event, which no table carries —
    # and the grant sat beside it there until Invasion's Phase 0 taking the
    # node and nothing else, which is this table's definition.
    ast.BlockCountGrant: lower_block_count_grant,
}


#: The same registry one argument wider: a node whose lowering needs the
#: **firing event** and nothing else. "That player puts the cards in their hand
#: on the bottom of their library" (Teferi's Puzzle Box) names the seat the fire
#: site froze, so the node cannot answer on its own — but the lowering still
#: *decides* nothing, which is the line :data:`_BY_NODE_TYPE` above is drawn on.
#: A row here rather than a branch in ``lower_statement``'s chain for that
#: table's reason: a registry that grows every time a card lands is the half
#: that moves out of the dispatcher.
#:
#: Nine branches of that chain were already exactly ``return _lower_x(statement,
#: event)`` when this table arrived — Discard, Mill, ExileEntireLibrary,
#: PlayWithHandRevealed, AddManaForTappedLand, PlayerGetsCounters,
#: UntapChosenByPaying, RevealHandAndChoose, LookTopPick — and were left where
#: they were, because moving a branch nobody is changing is churn. All nine are
#: rows below now, brought across by the rounds that next touched the
#: dispatcher; no arm of the chain is left that passes the raw event alone.
#:
#: Read after :data:`_BY_NODE_TYPE` and before the chain, and disjoint from both
#: for that table's reason: a class in two tables would be dispatched by
#: whichever was consulted first, which is not a fact anyone should have to look
#: up.
_BY_NODE_TYPE_WITH_EVENT: dict[type, object] = {
    # "…**that player** exiles all cards from their library" (Thought Lash),
    # "…**that player** mills a card" (Reef Pirates), "…**that player**
    # discards a card" (Anvil of Bogardan): each names the seat the fire site
    # froze. All three were branches of the chain saying exactly this.
    # "…this creature becomes a copy of **that creature**" (Unstable
    # Shapeshifter). The object copied is the one the firing event froze, so
    # the lowering has to know which event fired — and refuses under one that
    # freezes none rather than copying whatever the resolution is holding.
    ast.BecomeCopy: _lower_become_copy,
    ast.Discard: _lower_discard,
    ast.ExileEntireLibrary: _lower_exile_entire_library,
    # "…**that player** exiles a card at random from their hand" (Elkin Lair):
    # the same seat question one zone over, and the same answer.
    ast.ExileRandomFromHand: _lower_exile_random_from_hand,
    ast.ExileCardsFromHand: _lower_exile_cards_from_hand,
    ast.Mill: _lower_mill,
    # "…**that player** skips their next combat phase" (Blinding Angel): the
    # seat the damage event froze, so the lowering has to know which event
    # fired. It left the name-only table above the moment it started deciding
    # that.
    ast.SkipPhase: _lower_skip_phase,
    # "…a card **with the same name as that creature**" (Remembrance). The
    # name is the firing event's object's, so the lowering has to know which
    # event fired — and refuses under one that records none rather than
    # searching for a name nobody wrote down. It left the name-only table above
    # the moment its lowering started deciding something.
    # "…**that player** puts the cards in their hand on the bottom of their
    # library in any order, then draws that many cards" (Teferi's Puzzle Box).
    ast.PutHandCardsOnLibrary: _lower_put_hand_cards_on_library,
    # "Look at **that player's** hand" (Leshrac's Sigil) and "**that player**
    # may choose … and pay" (Mudslide): each acts on a seat the firing event
    # may have frozen. Four more of the branches the note above names, brought
    # across by the round that next touched the dispatcher — which is what that
    # note asks for.
    ast.UntapChosenByPaying: _lower_untap_chosen_by_paying,
    # "…you may look at **defending player's** hand" (Port Inspector).
    # CR 506.2's seat is one a *combat* event froze, so the same words on a
    # line with no such event in front of them name nobody — which the
    # lowering can only decide once it knows which event fired. It left the
    # name-only table above the moment it started deciding that.
    ast.LookAtHand: _lower_look_at_hand,
    ast.RevealHandAndChoose: _lower_reveal_hand_and_choose,
    ast.PlayerGetsCounters: _lower_player_gets_counters,
    ast.LookTopPickToHand: _lower_look_top_pick,
    # Four more of the chain's `return _lower_x(statement, event)` arms, moved
    # at Weatherlight's Phase 0 with `statement_dispatch.py` thirteen lines
    # from the guard — the move this table's own comment asks the next round
    # to make. Each arm's reasoning about the *raw* event travels with it.
    # The raw `event`, not `dispatch_event`: "defending player" is a fact
    # about the *trigger* — which seat the fire site froze — rather than
    # about where in the sentence the clause sits, and Stromgald Spy prints
    # it inside a "you may have …" offer, where `dispatch_event` is already
    # None. The same reading the delayed block-pair destroy takes above.
    ast.PlayWithHandRevealed: _lower_play_with_hand_revealed,
    # The **unfiltered** event, for `_lower_destroy`'s reason: which land
    # "that land" names and which seat "that player" names are facts about
    # the trigger, true of every clause under it. It read `dispatch_event`
    # while the tap-for-mana seam dispatched on `trig.instruction.kind`
    # alone, which made a nested occurrence genuinely unreachable — so
    # Winter's Night, whose trigger's effect is *two* sentences and
    # therefore lowers under a `Sequence`, refused with "None binds
    # neither". That seam now walks a sequence's steps, so the nesting is
    # reachable and the filtered event was the wrong question.
    ast.AddManaForTappedLand: _lower_add_mana_for_tapped_land,
    # The **unfiltered** event, for `_lower_play_with_hand_revealed`'s
    # reason above: "defending player" is a fact about the trigger — which
    # seat the fire site froze — rather than about where in the sentence
    # the clause sits, and Pygmy Hippo prints it inside a "you may have …"
    # offer, where `dispatch_event` is already None.
    ast.ActivateEachLandsManaAbility: _lower_activate_each_lands_mana_ability,
    ast.LoseUnspentMana: _lower_lose_unspent_mana,
    # "Put the top creature card of **defending player's** graveyard onto
    # the battlefield under your control." (Bone Dancer.) The raw `event`
    # for the two rows above's reason, and the same seat: which pile the
    # words name is a fact about the trigger, and this one is printed inside
    # a "you may …" offer where `dispatch_event` is already None.
    ast.PutGraveyardPositionOntoBattlefield:
        _lower_put_graveyard_position_onto_battlefield,
}


#: The fourth registry: a node that needs **both** — what the firing event
#: froze *and* what earlier steps of this same effect recorded.
#:
#: "…all creatures with magnet counters on them block **that creature** this
#: turn if able" (Magnetic Web) reads the event — the attacker the requirement
#: names is the object the trigger fired on. "**That creature** blocks this turn
#: if able" (Provoke) reads the records — the creature compelled is the one the
#: sentence in front of it untapped. One printed sentence, two pronouns, two
#: different questions, and dropping either argument answers one of them with
#: whatever the resolution happened to be holding.
#:
#: A fourth table rather than a chain branch, for the third table's stated
#: reason: ``lower_statement`` is dispatch and this is a registry. Disjoint from
#: the three above like every other pair of them.
_BY_NODE_TYPE_WITH_EVENT_AND_PRODUCED: dict[type, object] = {
    ast.BlocksThisTurnIfAble: _lower_blocks_this_turn_if_able,
    # "…a card **with the same name as that creature**" (Remembrance) reads the
    # firing event's object; "…a card **with the same name as that card**"
    # (Assembly Hall) reads a card an earlier step of this same effect turned
    # face up. One node, two pronouns, two different places to look — which is
    # exactly this table's shape, and why the search left the event-only table
    # above the moment the second referent arrived. Under neither record the
    # words name nothing and the lowering refuses, rather than searching the
    # whole library.
    ast.SearchLibrary: _lower_search_library,
    # "Create a token that's a copy of **that creature**." Echo Chamber's
    # "that creature" is the one an earlier step of the same effect chose (the
    # records); Dual Nature's is the one its trigger's event entered with (the
    # event), and its "**its controller** creates" is a seat that event froze.
    # It left the records-only table for the search's reason one row up: one
    # node, two referents, two places to look.
    ast.CreateCopyToken: _lower_create_copy_token,
    # Three arms of `statement_dispatch`'s chain that were exactly ``return
    # _lower_x(statement, event, produced)``, brought across at Invasion's
    # Phase 0. Each arm's reasoning about the *raw* event travels with it, and
    # the raw event is what this table passes.
    #
    # The **unfiltered** event, for the same reason ``_lower_destroy`` takes
    # one: whether a repeated "that <noun>" names the permanent the source is
    # attached to is a fact about the trigger, true of every clause under it,
    # and Mind Whip's tap sits inside a ``may``'s otherwise branch. Two rows
    # and one lowering: the chain's arm matched either class.
    ast.Tap: _lower_tap,
    ast.Untap: _lower_tap,
    # ``event``, not ``dispatch_event``: what "that artifact" names is a fact
    # about the *trigger* — its condition already named the enchanted permanent
    # — rather than about where in the sentence the clause sits, and the kind
    # it produces reaches its handler through the ordinary dict dispatch
    # however deeply it is nested. The same reading ``_lower_destroy`` takes,
    # and for the same reason: Curse Artifact's sacrifice lowers under a
    # ``May``.
    # ``produced`` for the same reason ``_lower_destroy`` takes it: "one of
    # those creatures" names a set an earlier step of this effect chose.
    # The **unfiltered** event, for ``_lower_destroy``'s reason: "that
    # creature's controller sacrifices **it** at end of combat" (Basalt Golem)
    # reaches the bound branch through the *delay's* event, which is a fact
    # about the sentence rather than about where in it the clause sits.
    ast.Sacrifice: _lower_sacrifice,
}


#: The same registry one argument wider again: a node whose lowering needs the
#: **records earlier steps of this same effect wrote** and nothing else. "…and
#: attach this enchantment to **it**" (Necromancy) is a back-reference, and only
#: ``produced`` can say whether a step in front of it recorded the permanent the
#: pronoun names — so the node cannot answer on its own, and the lowering still
#: decides nothing else, which is the line :data:`_BY_NODE_TYPE` is drawn on.
#:
#: ``ast.Attach`` left the name-only table above for exactly the reason
#: ``ast.Draw`` left it for the chain: a pronoun is only a pronoun relative to
#: what came before it, and with no record the same words mean something else.
#: A table rather than a chain branch because ``lower_statement`` is dispatch
#: and this is a registry — the move ``by_node`` was created by.
#:
#: Read after the two tables above and before the chain, and disjoint from both
#: for their reason: a class in two tables would be dispatched by whichever was
#: consulted first.
_BY_NODE_TYPE_WITH_PRODUCED: dict[type, object] = {
    ast.Attach: _lower_attach,
    # "Counter target spell unless its controller pays {1} **for each card
    # revealed this way**." (Brine Seer, Scent of Brine.) It left the name-only
    # table above for ``ast.Attach``'s reason: the price is a rate over a record
    # an earlier step of this same effect wrote, and with no such step the words
    # name nothing — an offer of {0} every board covers, which is a counterspell
    # that never counters.
    ast.CounterSpell: _lower_counter_spell,
    # "Put **it** into your graveyard" is All Hallow's Eve's own card or Call of
    # the Wild's revealed one, and only a reveal earlier in the same effect
    # tells them apart. It left the name-only table above for ``ast.Attach``'s
    # reason, word for word: a pronoun is only a pronoun relative to what came
    # before it, and with no record the same words mean something else.
    ast.PutSourceIntoZone: _lower_put_source_into_zone,
    # "**That permanent's** activated abilities can't be activated this turn."
    # (Interdict.) Here rather than in the name-only table for the two rows
    # above's reason: the pronoun names the source of an ability an earlier step
    # of this same effect countered, and with no such record the words name
    # nothing.
    ast.BoundPermanentActivationBan: _lower_bound_permanent_activation_ban,
    # "If a permanent's ability is countered this way, destroy **that
    # permanent**." (Teferi's Response.) The row above's pronoun and the row
    # above's reason: the source of an ability an earlier step countered, which
    # with no such record names nothing.
    ast.DestroyCounteredAbilitySource: _lower_destroy_countered_ability_source,
    # "Search that player's graveyard, hand, and library for all cards with the
    # same name as **the chosen card**…" (Lobotomy.) Here for the two rows
    # above's reason: the description is a record an earlier step of the same
    # spell wrote, and with none the words name nothing.
    ast.StripCardsWithChosenName: _lower_strip_cards_with_chosen_name,
    # "During that player's next turn, **the chosen creatures** attack if able"
    # and "destroy each of **the chosen creatures** that didn't attack this
    # turn" (Oracle en-Vec). Both name a set *and* a seat an earlier step of
    # the same effect recorded, so both moved out of the name-only table for
    # ``ast.Attach``'s reason: the words are a back-reference, and with no
    # record they name nobody.
    ast.AttacksThisTurnIfAble: _lower_attacks_this_turn_if_able,
    ast.DestroyChosenThatDidntAttack: _lower_destroy_chosen_that_didnt_attack,
    # "Tap all other artifacts. **They** don't untap … for as long as this
    # artifact remains tapped." (Kill Switch.) It left the name-only table
    # above for ``ast.Attach``'s reason: the plural pronoun names the set a
    # sweep in front of it recorded, and with no record it names nothing. The
    # singular spellings (Phyrexian Gremlins' "it", Giant Oyster's target) read
    # no record and lower exactly as they did.
    ast.DoesntUntapWhileSourceTapped: _lower_doesnt_untap_while_source_tapped,
    # Thirteen arms of `statement_dispatch`'s chain that were exactly ``return
    # _lower_x(statement, produced)`` — this table's definition — brought across
    # at Invasion's Phase 0, with that module 44 lines from the size guard and
    # eight groups about to reach it. Eight predate this table and were never
    # moved; five were written after it, three of them under a comment saying
    # a row of ``by_node`` is a lowering that needs "nothing but its node".
    # That was this module's own docstring, which had stopped being true the
    # day the event table was added. Each arm's reasoning travels with it.
    #
    # "Sacrifice **it** unless you pay its mana cost reduced by {2}" (Flash).
    # The pronoun is only a pronoun *relative to what came before it*: with no
    # record from an earlier step of the same sentence, "it" has no referent but
    # the source, and the two readings lower to different machinery.
    ast.SacrificeUnlessPay: _lower_sacrifice_unless_pay,
    # Beside ``ast.PreventDamage``'s shield, which is an arm of the chain: the
    # source this names is one a step in front of it chose (idiom 7).
    ast.ChosenSourceNextDamage: _lower_chosen_source_next_damage,
    ast.AddMana: _lower_add_mana,
    # "it" names the card an earlier step of *this* effect turned up, so the
    # lowering needs ``produced`` where the event-bearing table passes
    # ``event``.
    ast.BinRevealedCard: _lower_bin_revealed_card,
    # "one of **them**" names a set an earlier step of this same effect
    # recorded, so the node cannot answer on its own.
    ast.PutMilledCardOntoBattlefield: _lower_put_milled_card_onto_battlefield,
    ast.DiscardRevealedUnlessPayLife: _lower_discard_revealed_unless_pay_life,
    # The plural, beside the singular for its reason: the record an earlier
    # step wrote is the whole of the gate.
    ast.DiscardRevealedMatchingUnlessPayLife:
        _lower_discard_revealed_matching_unless_pay_life,
    # The reveal half of the printed sentence ``ast.CastPermission`` reads the
    # other half of (Temporal Aperture): the condition its duration holds under
    # is about "that card", so the lowering has to see what the step in front
    # of it recorded.
    ast.PlayWithTopRevealed: _lower_play_with_top_revealed,
    # "Search that player's library for **that many** cards" (Jester's Mask):
    # the count is a back-reference, so this lowering needs the record of what
    # the steps before it produced.
    ast.SearchPlayerLibrary: _lower_search_player_library,
    ast.RemoveFromCombat: _lower_remove_from_combat,
    # Scroll Rack prints "put **that many** cards", which is a back-reference
    # to the exile a step earlier.
    ast.PutLibraryTopIntoHand: _lower_put_library_top_into_hand,
    # It left the name-only table when Duplicity's "put **all other** cards you
    # own exiled with this enchantment into your hand" gave it a
    # back-reference: "other" names the cards a step of this same effect
    # exiled. It went to the chain then, and should have come here.
    ast.PutExiledWithSource: _lower_put_exiled_with_source,
    # "one of the exiled cards" names what a step of this same effect exiled,
    # which is a reading only the producer set can admit.
    ast.EachPlayerClaimsExiledCard: _lower_each_player_claims_exiled_card,
}
