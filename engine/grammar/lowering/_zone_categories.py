"""The `zones` half of `lowering/categories.INSTRUCTION_CATEGORIES`.

Split out of `lowering/zones.py` at Tempest's Phase 0, when that module sat
eleven lines from the thousand-line guard with three of the wave's five groups
reaching it and none of them owning it. The line is the one the table's own
header had already drawn, read one clause further than it was written:

    "The `zones` half of `lowering/categories.INSTRUCTION_CATEGORIES`, here
    rather than there for the reason that table's two earlier splits both
    record: what a wrapper carries belongs beside what builds one, and the
    family name is reused so the mirror re-forms instead of forking.

    The line is this module's own docstring, read as a question about a *kind*
    rather than about a sentence: a zone change names **two** zones, the one an
    object leaves and the one it goes to, and that pair is what picks the
    handler — where every kind left in `categories` acts on an object where it
    stands. It is 121 of the table's 380 rows and the largest category by a
    factor of three, which is why this is the seam that pays."

"Here rather than *there*" was an argument against `categories.py` and not an
argument for one file: composing 121 rows into the module that composes them
would put a wrapper's rows away from the family that builds them. They are
still not in `categories.py`, the family's name is in this module's own, and
what the split gives up is adjacency inside one file — which is what a cap
split always gives up.

The half that moved is the **registry**, which is the seam `by_node.py` and
`_records.py` each recorded when they left a module for exactly this reason:
"the table is a registry either way, and `lower.py` is dispatch". `zones.py` is
dispatch — one function per node — and this is 121 rows of data with no call
graph at all, which is why the cut moved nothing: no name in here is read by
anything in there, or the other way about. It is also the half that grows with
the pool, since a kind gets a row the day it is invented and a lowering only
when a card prints its sentence.

**Not one row changed, and that is the whole claim.** A category names the
migration family a *kind* belongs to, never the module its lowering lives in.
Giving a moved table a new category name would leave that name out of
`GRAMMAR_CATEGORIES`, which has no fallback underneath it, and every card whose
kind moved would go unsupported — two cards and eleven guards, at Weatherlight's
wave-2 integration. Every value below still reads "zones".

A floor rather than a family, and it reads nothing at all. `categories` composes
it into one `INSTRUCTION_CATEGORIES`, so there is still exactly one table and
exactly one row per kind, and the address every reader uses is unchanged — and
that composition is now a shared module reading a shared module, where it used
to be `categories` reaching up into a family for its rows.
"""

ZONE_INSTRUCTION_CATEGORIES: dict[str, str] = {
    "bin_revealed_card": "zones",
    "put_revealed_card_onto_battlefield": "zones",
    "reveal_top_opponent_chooses": "zones",
    # Wood Sage's sorted reveal, beside the pick above: what it touches is a
    # library and two zones the pile is split between.
    "reveal_top_sorting_by_chosen_name": "zones",
    "choose_card_name": "zones",
    "graveyard_top_to_library": "zones",
    "shuffle_graveyard_into_library": "zones",
    "shuffle_hand_into_library": "zones",
    "shuffle_hand_cards_into_library": "zones",
    # CR 701.24 with nothing moving into the library (Prophecy's third
    # sentence). The same category as the two above: what it touches is a zone.
    "shuffle_library": "zones",
    "exile_any_number_of_own_tokens": "zones",
    "put_graveyard_cards_on_library_top": "zones",
    "draw_then_discard_self": "zones",
    "discard_then_draw_that_many": "zones",
    "sacrifice_self": "zones",
    # The controller-chosen sacrifice (Dire Fleet Warmonger's optional cost).
    "sacrifice_matching_permanent": "zones",
    # "…sacrifice any number of creatures with total power 12 or greater"
    # (Phyrexian Dreadnought). The same category as every other sacrifice, so
    # GRAMMAR_CATEGORIES is unchanged: what differs is how the price is counted,
    # not what happens to the permanents.
    "sacrifice_permanents_totalling": "zones",
    "sacrifice_attached_permanent": "zones",
    "discard_target_cards": "zones",
    # The controller's own chosen discard (Jeskai Elder's if-you-do branch).
    "discard_controller_cards": "zones",
    # "Each player may discard up to three cards." (Mind Bomb.) One prompt
    # per seat, and a discard like every other one in this category.
    "each_player_discards_up_to_cards": "zones",
    # "Each player may draw up to two cards." (Truce.) The discard's twin one
    # zone over, and the same category: a card moving between a library and a
    # hand.
    "each_player_draws_up_to_cards": "zones",
    "draw_up_to_cards": "zones",
    # "Each opponent discards two cards." (Bad Deal) — one pending discard
    # choice per opponent, same flow as the targeted form.
    "each_opponent_discards_cards": "zones",
    "discard_x_target_cards": "zones",
    "opponent_discards_random_card_on_damage": "zones",
    # Looking at a hand reads a hidden zone; the legacy rule and the handler
    # both live in the engine's zones modules.
    "exile_target_graveyard": "zones",
    # Sword of the Ages: what the ability's own cost sacrificed, exiled out of
    # the graveyard the cost put it in.
    "exile_cost_sacrifices": "zones",
    # "Target player reveals their hand." (Inquisition.) The reveal on its own
    # (CR 701.20) — a zone becoming public, the same family as the paragraph
    # below it, so GRAMMAR_CATEGORIES is unchanged.
    "reveal_hand": "zones",
    # "…play with their hand revealed for as long as this creature remains on
    # the battlefield." (Stromgald Spy.) CR 701.20a's reveal made continuous —
    # the same zone becoming public, so the same category.
    "reveal_hand_while_source_present": "zones",
    "reveal_hand_and_choose": "zones",
    # CR 701.20, the reveal on its own (Amnesia, Rag Man). The same category as
    # the template above, so GRAMMAR_CATEGORIES is unchanged: what moves is
    # information about a hand either way.
    "reveal_hand": "zones",
    # "Target player reveals a card at random from their hand." (Wand of Ith.)
    # The same zone made public one card at a time, and the same category for
    # that reason.
    "reveal_random_card_from_hand": "zones",
    # "…discards it unless they pay 1 life." The offer and its declined branch
    # are one instruction because the branch acts on a card only the offer knows
    # — the same reason `unless_player_pays` carries its own unpaid steps.
    "discard_revealed_unless_pay_life": "zones",
    # Sirocco: the plural of the row above, one offer per revealed card the
    # printed phrase names. Same category, so GRAMMAR_CATEGORIES is unchanged.
    "discard_revealed_matching_unless_pay_life": "zones",
    "discard_bound_revealed_card": "zones",
    # "…discards **all nonland cards**" (Amnesia). A discard like the counted
    # ones beside it; only who picks differs, and here nobody does.
    "discard_all_matching_cards": "zones",
    "look_at_target_hand": "zones",
    "look_at_target_library_top": "zones",
    # "…You may put that card on the bottom of that player's library"
    # (Coral Fighters): the same look with the one offer that moves a card.
    "look_at_library_top_then_bottom": "zones",
    # "…, then put them back in any order" (Natural Selection, Portent). The
    # look above with the rearrangement switched on — same prompt, same zone,
    # so the same family.
    "reorder_target_library_top": "zones",
    "reorder_own_library_top": "zones",
    "shuffle_source_card_into_library": "zones",
    # A library search moves a card between hidden zones — same module, same
    # category as the other zone-change handlers.
    "search_library": "zones",
    # The cast-from-exile/graveyard subsystem (both Chandras, M21): two exiles
    # that record what they moved, and the permission their later sentences
    # grant over it. All zone work — the permission is about which zone a card
    # may be cast from — so no new category and GRAMMAR_CATEGORIES is unchanged.
    "exile_top_of_library": "zones",
    # "Exile the bottom card of target player's graveyard" (Phyrexian
    # Furnace). A zone change like the exile above it — a card leaves a
    # graveyard and arrives in exile — so the same category and
    # GRAMMAR_CATEGORIES is unchanged.
    "exile_graveyard_position": "zones",
    "exile_entire_library": "zones",
    "exile_random_card_from_hand": "zones",
    "exile_chosen_card_from_hand": "zones",
    # The pile spelling of the row above (Duplicity, Scroll Rack): the same
    # hidden zone, a quantifier up.
    "exile_hand_pile": "zones",
    # Scroll Rack's other two sentences: cards off a library into a hand
    # (not a draw — CR 121.3) and the linked pile back on top of it.
    "put_library_top_into_hand": "zones",
    "put_exiled_pile_on_library": "zones",
    # Living Death's per-seat pile going back to the battlefield: two zones
    # named, exile and the battlefield, which is this table's own line.
    "put_exiled_this_way": "zones",
    "put_exiled_with_source": "zones",
    "exile_graveyard_until_leaves": "zones",
    "exile_until_leaves_or_untaps": "zones",
    "take_ownership_of_exiled": "zones",
    "return_exiled_source_to_graveyard": "zones",
    "transmute_by_sacrifice": "zones",
    "rebalance_lands": "zones",
    "place_held_card": "zones",
    "look_top_pick_to_hand": "zones",
    "look_top_exile_random": "zones",
    "search_and_exile_matching": "zones",
    "grant_cast_permission": "zones",
    "grant_look_at_exiled_cards": "zones",
    # The planeswalker block's one-shot zone movers (M21 loyalty abilities).
    "each_player_discards_a_card": "zones",
    "discard_hand": "zones",
    "put_target_on_library_top": "zones",
    # The self twin of the row above (Thalakos Mistfolk, Avenging Angel). Same
    # zone change, and the only thing that differs is that the object is named
    # rather than chosen.
    "put_source_card_on_library_top": "zones",
    # "Choose two cards in your hand drawn this turn." (Sylvan Library.) A
    # pick out of a hidden zone that moves nothing; the sentence after it is
    # what moves anything.
    "choose_cards_in_hand": "zones",
    "put_iterated_card_on_library": "zones",
    "put_graveyard_card_on_library_bottom": "zones",
    "put_top_of_graveyard_on_library_bottom": "zones",
    # Unsubstantiate: a spell unstacked to its owner's hand, or a creature bounced.
    "return_spell_or_creature_to_hand": "zones",
    "put_cards_from_hand_onto_battlefield": "zones",
    # "…put **a** permanent card from their hand onto the battlefield."
    # (Eureka.) The chosen-card twin of the sweep above: same zone change, one
    # card, and the seat picks which.
    "put_chosen_card_from_hand_onto_battlefield": "zones",
    "reveal_top_to_hand_or_bottom": "zones",
    # The bare reveal (Track Down). Same category as the template above: both
    # look at the top of a library, and what differs is what the card's other
    # sentences then do about it.
    "reveal_top_of_library": "zones",
    "reveal_until_match": "zones",
    "name_and_strip": "zones",
    # Its decomposed half (Lobotomy): the same strip across the same three
    # zones, reading a name an earlier step of the spell recorded rather than
    # one this step asked for.
    "strip_cards_with_chosen_name": "zones",
    # "Choose a card name. Target opponent reveals X cards at random from their
    # hand. Then that player discards all cards with that name revealed this
    # way." (Nebuchadnezzar.) The same category as the naming paragraph above:
    # what it does is move cards out of a hidden zone.
    "name_and_random_reveal": "zones",
    # Petra Sphinx's guess. "zones" like the reveals above it: what the card
    # does is look at the top of a library and move that card somewhere, and
    # the name is only what decides which somewhere.
    "name_then_reveal_top": "zones",
    # Demonic Consultation, beside it: the same guess, taken against your own
    # library and paid for with its top cards.
    "name_then_consult": "zones",
    # Necropotence, exiling what its controller just discarded.
    "exile_bound_card_from_graveyard": "zones",
    # Necropotence again, the other half: what its own exile put aside comes
    # back at its controller\'s next end step.
    "put_exiled_cards_into_zone": "zones",
    # "Put the top card of the exiled pile into its owner's hand."
    # (Mangara's Tome.) CR 610.3's linked pile, so the same category as
    # the search that made it.
    "put_exiled_pile_top_into_hand": "zones",
    # "The next time you would draw a card this turn, instead ..."
    # (Mangara's Tome.) A wrapper like `create_delayed_trigger`, and the
    # gate walks into it for the same reason: what the line touches is
    # what the armed effect touches.
    "arm_draw_replacement": "zones",
    # Forgotten Lore: an opponent picks out of your graveyard, again for
    # each payment, and the pick the loop stopped on is the one you keep.
    "repeated_graveyard_pick": "zones",
    # The sentence that ends that loop. Its own kind because it is reached
    # from two places — the decline branch and an exhausted graveyard — and
    # a handler cannot be half a handler.
    "finish_repeated_graveyard_pick": "zones",
    "exile_all_matching": "zones",
    # "…then **the chosen permanents** phase out." (Equipoise.) The same zone
    # question as every other phase-out beside it — CR 702.26 is not a zone
    # change, and this table is where the family says so — with the set read
    # off a record rather than off a target.
    "phase_out_recorded_permanents": "zones",
    "phase_out_target": "zones",
    # "Until your next upkeep, target permanent **can't phase out**." (Spatial
    # Binding.) Beside the phasing actions rather than with the combat
    # restrictions: what it forbids is a CR 702.26 event, not a declaration.
    "forbid_phase_out": "zones",
    "phase_out_opponent_creatures": "zones",
    # CR 702.26's other two printed subjects (Mirage): the ability's own source
    # ("This creature phases out") and a sweep over a printed noun phrase ("All
    # lands you control phase out").
    "phase_out_self": "zones",
    "phase_out_matching": "zones",
    # "Enchanted creature phases out" (Vanishing): the Aura's attachment, known
    # from the source rather than chosen, so the same category and its own kind.
    "phase_out_enchanted": "zones",
    # "Simultaneously, all phased-out creatures phase in and all creatures
    # with phasing phase out." (Time and Tide.) The same family: what the
    # sentence does is move permanents in and out of play, and doing both at
    # once is a property of the moment rather than of the effect.
    "phase_in_and_out_matching": "zones",

    # "…and **that creature** phase out" (Dream Fighter): the creature the
    # block trigger bound, beside the sweep and the source above it.
    "phase_out_block_pair": "zones",
    # Teferi's Veil's delayed half and Ertai's Familiar's lock: the same
    # CR 702.26 family as every row above, on the object a delayed ability
    # bound and on the ability's own source.
    "reanimate_graveyard_position": "zones",
    "phase_out_bound_permanent": "zones",
    "forbid_source_phase_out": "zones",
    "draw_target_cards": "zones",
    "draw_controller_cards": "zones",
    "mill_target_player": "zones",
    "look_top_cycle_and_stack": "zones",
    "separate_library_top_into_piles": "zones",
    "mill_until_matching": "zones",
    "put_milled_card_onto_battlefield": "zones",
    "put_hand_cards_on_library": "zones",
    # Scry moves cards within one library (CR 701.22a) — the same family as
    # mill and draw, so no new category and GRAMMAR_CATEGORIES is unchanged.
    "scry": "zones",
    "exile_creature_gain_life_equal_to_power": "zones",
    "exile_target_creature_until_eot": "zones",
    # The permanent exiles. Same category as the temporary one, so
    # GRAMMAR_CATEGORIES is unchanged — exile is a zone change either way, and
    # a second switch would let one of the two be gated off without the other.
    "exile_target_permanent": "zones",
    "exile_self": "zones",
    # "Target spell's controller exiles it with X delay counters on it."
    # (Ertai's Meddling.) A zone change by this module's own line — the object
    # leaves the **stack** and arrives in exile — rather than a counterspell:
    # CR 701.6a counters a spell, and this one is never countered, it is moved.
    "exile_target_spell": "zones",
    # "Exile that token" (Stangg) — the token this same effect created, by the
    # id the token maker recorded. A zone change like the two beside it.
    "exile_created_token": "zones",
    "exile_target_graveyard_card": "zones",
    # "…exile up to two target creature cards from defending player's
    # graveyard" (Rysorian Badger) — the counted twin of the row above, whose
    # picks are made through a prompt.
    "exile_cards_from_graveyard": "zones",
    "exile_graveyard_cards": "zones",
    # "When that creature dies this turn, exile **it**" (Whippoorwill) — the
    # card the delayed ability was bound to, out of the graveyard the death put
    # it in.
    "exile_bound_card": "zones",
    # "Put it into your graveyard." (All Hallow's Eve, from exile.) The
    # ability's own source moving zones — the same category as the self-exile
    # above, because it is the same kind of move made by the same kind of
    # sentence; the destination is payload.
    "put_self_into_zone": "zones",
    # "Each player returns all creature cards from their graveyard to the
    # battlefield." (All Hallow's Eve.) A sweep reanimation, filed with the
    # targeted graveyard returns beside it for the reason the two exiles share
    # a category: what varies is which cards, not what happens to them.
    "return_all_cards_from_graveyard": "zones",
    "return_creature_from_graveyard_to_hand": "zones",
    # "…return a card from your graveyard to your hand **for each card
    # discarded this way**." (Recall.) The same zone change, counted by an
    # earlier step's answer and chosen while the spell resolves rather than at
    # cast time. Same category, so GRAMMAR_CATEGORIES is unchanged.
    "return_chosen_cards_from_graveyard_to_hand": "zones",
    "reanimate_creature": "zones",
    # "Return target Aura card from your graveyard to the battlefield
    # attached to Hakim." The same zone change with CR 303.4f's attachment
    # folded into the entry, so the category is unchanged and
    # GRAMMAR_CATEGORIES gains nothing.
    "reanimate_aura_onto_source": "zones",
    "reanimate_bound_card": "zones",
    # A card returning *itself* from the graveyard (Silversmote Ghoul). Same
    # category as every other zone change: what differs is which object moves,
    # not what kind of effect it is — so GRAMMAR_CATEGORIES is unchanged and one
    # switch cannot gate half of "zones" off.
    "return_self_from_graveyard": "zones",
    "return_bound_card_to_owners_hand": "zones",
    "return_source_card_to_owners_hand": "zones",
    "return_source_card_to_battlefield": "zones",
    "bounce_target_creature": "zones",
    # "Return to your hand all enchantments you both own and control" (Remove
    # Enchantments) — the sweep twin of the bounce above.
    "return_all_matching": "zones",
    # "Return a creature you control to its owner's hand" (Shrieking Drake) —
    # the same move again, over the permanents a `choose_permanents` step in
    # front of it recorded rather than over a target or a sweep.
    "return_recorded_permanents_to_hand": "zones",
    # "{W}: Return **enchanted creature** to its owner's hand." (Sun Clasp.)
    "return_attached_permanent_to_hand": "zones",
    # "During your next untap step, as you untap your permanents, return this
    # land to its owner's hand." (Undiscovered Paradise.)
    "return_self_instead_of_untapping": "zones",
    # "Whenever a land is tapped for mana, return it to its owner's hand."
    # (Storm Cauldron.) The "zones" family rather than "mana": the trigger
    # fires on a mana event and the effect is a zone change. Resolved inline at
    # the same seam as its neighbour above and for the same reason — a land is
    # tapped for mana part-way through paying a cost, before the spell it pays
    # for is on the stack, so there is no stack to enqueue onto.
    "return_tapped_land_to_hand": "zones",
}
