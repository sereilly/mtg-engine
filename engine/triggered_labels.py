"""The triggered family of the ``effect_kind`` vocabulary: the
condition-blind rows, ``TRIGGERED_LABELS`` (instruction kind -> label, for the
clause after a trigger condition), and its by-condition rows,
``TRIGGERED_LABELS_BY_CONDITION`` ((condition kind, instruction kind) -> label,
for a wrapper whose word the trigger's moment names).

``engine/effect_labels.py`` is the reader (``triggered_label``): a by-condition
row first, then the kind's row, then the ``spell_pattern`` marker. It holds the
vocabulary's story — what reads a label, what never may, and why the rows are
kept rather than derived.

``tests/engine/test_effect_labels.py`` holds both tables to the pool (every row
reached, no grammar-read trigger falling back, a by-condition row only where the
kind alone is ambiguous), and ``tests/engine/test_kg3_chores_moment_labels.py``
holds a by-condition row to its moment. Both tables are keyed, so their order is
not behaviour; their headings name the set or round that settled the rows under
them.
"""

from __future__ import annotations

# Instruction kind -> label, for an ability the grammar reads in the **triggered**
# position (the clause after a trigger condition).
TRIGGERED_LABELS: dict[str, str] = {
    # --- Mirage, at its promotion ----------------------------------------
    # Eleven triggered kinds that fall back to the `spell_pattern` marker until
    # they are named, each settled against the spelling its family already uses
    # on the activated side rather than against its grammar category. The one
    # wrapper among them (Bazaar of Wonders' `if_then`) is in
    # TRIGGERED_LABELS_BY_CONDITION below, because a wrapper says nothing about
    # its contents and the condition is the only half of the pair that does.
    # Nine kinds that reached a *triggered* ability for the first time at
    # Visions' promotion. Eight are that set's; Viashino Sandstalker is Mirage's
    # and shipped, which is the promotion gate doing its job — the kind existed,
    # and no shipped trigger had produced it until this set widened the
    # productions that emit it.
    #
    # Each takes the family of what the ability *does*, which is the whole
    # contract of this table: the label feeds `SimulationResult` and the
    # stack item's own copy of it.
    #
    # `if_then` is the exception in this block: a **wrapper**, condition-blind
    # here, so it names its shape — `triggered_conditional`, the twin of
    # `activated_conditional` — for every condition that has no row of its own
    # in TRIGGERED_LABELS_BY_CONDITION (an entry trigger, a death, an end step).
    # It read `triggered_label` until kg3, a word naming neither the shape nor
    # the moment; Insubordination's end step and Erg Raiders' are the same
    # wrapper and take the same word.
    "if_then": "triggered_conditional",
    # Lim-Dûl's Hex and Oath of Lim-Dûl: "…for each player, …" / "for each 1
    # life you lost, …". A **wrapper** (its payload carries the step it
    # repeats), so condition-blind it names the shape, as `activated_repeated`
    # does for Heroism; the upkeep's row below still lets that moment name
    # itself. Oath's "whenever you lose life" had a row reading
    # `spell_pattern` — the fallback marker, which is a leaf's bucket too —
    # until kg3.
    "for_each": "triggered_repeated",
    "remove_all_counters_from_matching": "triggered_counter",
    "search_library": "triggered_library",
    # Skyship Weatherlight's entry: "search your library for any number of
    # artifact and/or creature cards, exile them, then shuffle." A search
    # whose finds go to exile instead of a hand is still what the trigger is
    # *for* - the library - and the bucket names that, not the destination.
    "search_and_exile_matching": "triggered_library",
    "pump_enchanted_creature": "triggered_pump",
    "untap_and_tap_matching": "triggered_tap",
    "phase_out_target": "triggered_phasing",
    # Oubliette's entry, read by the grammar since kg5 (its card hook went):
    # the same phasing, its phase-in bound to the source's departure.
    "phase_out_target_creature_until_source_leaves": "triggered_phasing",
    "destroy_event_subject": "triggered_destruction",
    "exile_event_subject": "triggered_destruction",
    # No Quarter's two lines: the other half of the block pair, destroyed the
    # moment the pair is declared. Beside the block-pair pump and keyword rows
    # in this table and filed with the *destructions*, because the label is what
    # the ability does and not which referent it does it to.
    "destroy_block_pair_partner": "triggered_destruction",
    # --- Invasion, at its promotion ---------------------------------------
    # Fight or Flight ("At the beginning of combat on each opponent's turn,
    # separate all creatures that player controls into two piles. Only
    # creatures in the pile of their choice can attack this turn.") and Stand
    # or Fall, its mirror for blockers. The kind is CR 700.3's and is not
    # about combat in itself - Fact or Fiction separates cards - but every
    # *triggered* printing of it is one of these two, and what the ability
    # does is decide who may attack or block: the bucket the block-pair rows
    # beside it take. A triggered pile of cards, when one is printed, wants a
    # row in TRIGGERED_LABELS_BY_CONDITION rather than a change to this one.
    "separate_into_piles": "triggered_combat",
    "remove_keyword_from_block_pair": "triggered_combat",
    "return_source_card_to_owners_hand": "triggered_return",
    "exile_target_graveyard": "triggered_exile",
    "exile_graveyard_cards": "triggered_exile",
    "exile_bound_card": "triggered_exile",
    "look_at_library_top_then_bottom": "triggered_library",
    # Mortuary's "whenever a creature is put into your graveyard from the
    # battlefield, put that card on top of your library". `triggered_library`
    # rather than `triggered_recursion`, for the reason the three
    # `put_*_on_library_top` rows take `activated_library` on the other side:
    # the library is the object the ability acts on, and which zone the card
    # came from is payload.
    "put_iterated_card_on_library": "triggered_library",
    # Phasing is a permanent leaving and coming back, which is the word the
    # activated side settled on for the same pair of kinds.
    "phase_out_self": "triggered_recursion",
    "phase_out_matching": "triggered_recursion",
    "add_counter_to_each_matching": "triggered_counter",
    "tap_target_permanent": "triggered_tap",
    "discard_controller_cards": "triggered_discard",
    # --- Stronghold, at its promotion ------------------------------------
    # Bottomless Pit's "at the beginning of each player's upkeep, that player
    # discards a card at random". Beside the row above, whose sentence is the
    # same act with a different seat asked — who discards is payload, and the
    # label is what the ability does.
    "discard_x_target_cards": "triggered_discard",
    "gain_control_until_eot": "triggered_control",
    # --- Urza's Destiny, at its promotion ---------------------------------
    # Aura Thief's death trigger. `triggered_control` beside
    # `gain_control_until_eot` above and matching `gain_control_of_target`'s
    # `activated_steal` family on the other side: the label is what the
    # ability does, and taking every enchantment on the battlefield is the
    # same thing as taking one, done to more of them.
    "gain_control_of_all_matching": "triggered_control",
    # Telepathic Spies' entry trigger, the same kind Orcish Spy activates —
    # so it takes `activated_look`'s family with the prefix its side of the
    # table uses, rather than a bucket of its own.
    "look_at_target_hand": "triggered_look",
    # --- Urza's Saga ------------------------------------------------------
    # Wild Dogs' and Ghazban Ogre's "at the beginning of your upkeep, ... the
    # player with the most life gains control of this creature". The kind
    # reached a triggered ability for the first time when the production took
    # the Ogre's hook over; the activated side already spells this family
    # `activated_give_control`, so the trigger takes the same word its
    # neighbours above do.
    "give_control_of_source_to_player": "triggered_control",
    # "Whenever enchanted creature becomes the target of a spell or ability,
    # that spell or ability's controller gains control of that creature."
    # (Fractured Loyalty.) The host handed over rather than the source — the
    # same family's word.
    "give_control_of_attached_to_player": "triggered_control",
    # --- Homelands ------------------------------------------------------
    # Two untap denials whose trigger is a combat moment rather than an
    # upkeep (Labyrinth Minotaur blocks, Spectral Bears attacks), the
    # block-pair counter Greater Werewolf places at end of combat, and the
    # first strike Mammoth Harness hands the *other* creature in a block.
    # `skip_next_untap` is a tap-family effect and the keyword grant a pump
    # one, matching the spellings the two families already use above.
    "skip_next_untap": "triggered_tap",
    "add_named_counter_to_creatures_in_combat_with_source": "triggered_counter",
    "grant_keyword_to_block_pair": "triggered_pump",
    # Flailing Drake's "+1/+1 to that creature" — the P/T twin of the grant
    # above, and the same bucket: one printed sentence, one label, whichever of
    # the two the card spells.
    "pump_block_pair": "triggered_pump",
    # Mishra's War Machine / Minion of Leshrac. The bucket the card hook
    # carried before the grammar read the template, kept across the retirement
    # so the support report does not silently re-bucket a shipped card — which
    # is the reason this table exists.
    "upkeep_damage_unless_cost": "upkeep_effect",
    # Mudslide and Magnetic Mountain: "that player may choose any number of
    # tapped <creatures> they control and pay <cost> for each creature chosen
    # this way." A toll whose number of payments the payer picks, and the same
    # bucket Magnetic Mountain's retired card hook reported — kept across the
    # retirement for this table's own reason. Rewind's untap of the same kind
    # is a *spell*, so no triggered label reads it and there is no ambiguity to
    # resolve by condition.
    "untap_up_to_matching": "upkeep_effect",
    # --- The Dark ---
    # Each names what the ability is *for*, which is the question the support
    # report and `SimulationResult` ask. The `may` wrappers among this set's new
    # triggers are in TRIGGERED_LABELS_BY_CONDITION instead, because a wrapper
    # says nothing about its contents and the condition is the only half of the
    # pair that does.
    "create_copy_token": "triggered_token",
    "exile_created_token": "triggered_exile",
    "destroy_self": "triggered_destruction",
    "destroy_all_matching": "triggered_destruction",
    # "When you cycle this card, destroy all lands." (Decree of Annihilation.)
    # The land sweep's first trigger; it fell back to the marker label.
    "destroy_all_lands": "triggered_destruction",
    # Abu Ja'far and Kjeldoran Frostbeast. Declared rather than
    # defaulted so the shipped card keeps the bucket its card hook
    # reported before the grammar took the template over — the reason
    # this table exists.
    # --- Mercadian Masques, at its promotion -----------------------------
    # Four leaf kinds, each beside the nearest name its own family already
    # carries. The five `may` wrappers this set also brought are in
    # TRIGGERED_LABELS_BY_CONDITION below, for the reason the Dark's block
    # states: a wrapper says nothing about its contents, so the condition is
    # the only half of the pair that does.
    #
    # Charisma gains control of the creature its host damaged, beside
    # `steal_blockers_of_source`.
    "steal_target_linked_to_source": "triggered_steal",
    # Ignoble Soldier shields the damage its own becoming-blocked trigger
    # names, beside `prevent_damage_to_target_until_eot` — the same phrase with
    # the other preposition, which is where the damage starts rather than a
    # different kind of ability.
    "prevent_damage_by_target_until_eot": "triggered_prevention",
    # Indentured Djinn fills every hand to a number, beside `draw_target_cards`.
    "each_player_draws_up_to_cards": "triggered_draw",
    # Saprazzan Bailiff hands every graveyard's artifacts and enchantments back
    # when it leaves. Beside `return_creature_from_graveyard_to_hand` and not
    # `return_all_matching`: the sweep is over *graveyards*, and it is the pile
    # a card comes out of that this family is named for.
    "return_all_cards_from_graveyard": "triggered_recursion",
    "destroy_creatures_in_combat_with_source": "spell_pattern",
    # Animate Dead and Dance of the Dead, whose whole entry line the grammar
    # now reads as one template. Declared for the same reason the row above is:
    # Animate Dead reported `spell_pattern` from its card hook, and retiring
    # that hook must not re-bucket a shipped card.
    "reanimate_creature": "spell_pattern",
    "deal_damage_each_matching": "triggered_damage",
    "deal_damage_to_those_damaged_this_game": "triggered_damage",
    "add_corpse_counters_for_each_creature_died": "triggered_counter",
    "add_counter_to_self": "triggered_counter",
    # A CR 122.1 counter (Malefic Scythe, Armageddon Clock). The same
    # bucket as a +1/+1 one: the report asks what the ability is for.
    "add_named_counter_to_self": "triggered_counter",
    "add_mana_for_tapped_land": "spell_pattern",
    # Eladamri's Vineyard: the mana a *triggered* ability adds to the seat the
    # firing named. `triggered_mana` rather than the `spell_pattern` above it,
    # because this one really does go on the stack and resolve through
    # EFFECT_HANDLERS — which is the whole difference between the two kinds.
    "frozen_seat_adds_mana": "triggered_mana",
    # Storm Cauldron, beside its neighbour: both are resolved inline by the tap
    # seam rather than through EFFECT_HANDLERS, so neither has an
    # ``activated_``/``triggered_`` bucket a dispatcher would give it.
    "return_tapped_land_to_hand": "spell_pattern",
    "add_plus1_counters_for_each_creature_died": "triggered_counter",
    # The upkeep decay an Aura puts on what it enchants (Unstable Mutation).
    # `upkeep_effect` rather than `triggered_counter`, which is the label the
    # kind it replaced (`add_minus1_counter_to_enchanted`) reported: the pair's
    # instruction changed when the card-name hook became a production, and the
    # bucket the support report puts the card in must not move with it.
    "add_pt_counters_to_attached": "upkeep_effect",
    "deal_damage": "spell_pattern",
    "deal_damage_equal_to_swamps": "upkeep_effect",
    "delayed_destroy_blocked_or_blocker": "triggered_delayed_destroy",
    # "…create a 4/4 red Bird creature token with flying **at the beginning of
    # the next end step**." (Rukh Egg.) A shipped card whose instruction kind
    # changed: the delay used to be a `Game`-level queue behind an
    # `arm_end_step_token` hook, and the grammar reads the trailing delay now.
    # The label was what the report and the web payload had always shown for it
    # — a triggered ability that creates something — so the card was not
    # re-bucketed by the change underneath it.
    #
    # The kind is a **wrapper** (its payload carries what the delay does), and
    # by the kg round it had generalised to some forty triggers under a dozen
    # conditions — Fog Elemental's sacrifice, Lowland Basilisk's destruction,
    # Carrier Pigeons' draw — three of which make a token. So it takes the
    # label naming its shape, the activated side's `activated_delayed_trigger`
    # with this side's prefix, never the leaf bucket one card shared:
    # `test_a_triggered_wrapper_row_never_borrows_a_leaf_effects_bucket`.
    "create_delayed_trigger": "triggered_delayed_trigger",
    "opponent_discards_random_card_on_damage": "triggered_discard",
    "sacrifice_self": "triggered_sacrifice",
    # "When this Aura enters, tap enchanted creature." (Paralyze, Venarian
    # Gold, Cocoon) — the enter-tap that used to be a substring branch in
    # `_apply_aura_effect` and is a compiled trigger now.
    "tap_enchanted_creature": "triggered_tap",
    "self_damage_unless_pay": "triggered_damage",
    "target_gains_life": "spell_pattern",
    "upkeep_chosen_player_hand_overflow_damage": "upkeep_effect",
    "upkeep_pay_or_deal_damage_to_controller": "upkeep_effect",
    "upkeep_pay_or_sacrifice_enchantment": "upkeep_effect",
    # --- Alliances, at its promotion ----------------------------------------
    # Both are upkeep obligations whose payment is the whole ability: Phantasmal
    # Sphere's cumulative upkeep (CR 702.24) and Rogue Skycaptain's counter toll
    # whose refusal cedes the creature. They take `upkeep_effect` beside every
    # other pay-or-consequence above rather than the `spell_pattern` marker the
    # fallback gives them, which is not a bucket at all.
    "cumulative_upkeep": "upkeep_effect",
    "upkeep_counter_toll_or_cede_control": "upkeep_effect",
    "upkeep_pay_or_sacrifice_self": "upkeep_effect",
    "upkeep_pay_to_untap_self": "upkeep_effect",
    # Paralyze's Aura twin. The label the card-name hook used to supply: the
    # kind is unchanged and so is the bucket — what moved is which half of the
    # engine produces the instruction, and this table is why that move did not
    # re-bucket a shipped card.
    "upkeep_pay_to_untap_enchanted": "upkeep_effect",
    # --- M21's triggered abilities, added at its promotion -------------------
    # M21 is the first set whose triggers the grammar reads wholesale, so this
    # is the block where the vocabulary the shipped pool built gets applied to a
    # set it did not come from. Each label is the bucket the *ability* belongs
    # to, not a rendering of its instruction kind.
    "add_counter_to_target": "triggered_counter",
    "add_mana_from_text": "triggered_mana",
    "bounce_target_creature": "triggered_bounce",
    # "…return that creature to its owner's hand" (Cowardice) — the same
    # reported effect as the targeted bounce beside it; what differs is where
    # the object came from, which is not what a label is about.
    "bounce_event_subject": "triggered_bounce",
    "buff_creatures_global": "triggered_pump",
    "copy_triggering_spell": "triggered_copy",
    "create_token": "triggered_token",
    "destroy_target_permanent": "triggered_destruction",
    "discard_then_draw_that_many": "triggered_draw",
    "draw_controller_cards": "triggered_draw",
    # Horn of Greed's "whenever a player plays a land, **that player** draws a
    # card" — the row above with the drawing seat named rather than assumed,
    # which is the same distinction `draw_target_cards` takes from it on the
    # activated side. A draw is a draw whoever does it.
    "draw_target_cards": "triggered_draw",
    "draw_then_discard_self": "triggered_draw",
    "exile_graveyard_until_leaves": "triggered_exile",
    "exile_self": "triggered_exile",
    # Thought Lash's unpaid cumulative upkeep, beside `exile_self`: the
    # ability's point is that cards go to exile, whichever pile they leave.
    "exile_entire_library": "triggered_exile",
    # "…the game is a draw." (Divine Intervention, at Legends' promotion.) Its
    # own bucket rather than a life one: the ability ends the game, and the
    # report reading it as `spell_pattern` would have said the card does
    # nothing recognisable — which is what it did until the trigger had a
    # dispatcher at all.
    "game_is_draw": "triggered_game_end",
    # Battering Ram's banding, added at Antiquities' promotion. A keyword
    # granted until end of combat is the same bucket the activated table gives
    # one granted until end of turn.
    "grant_self_keyword_until_eot": "triggered_pump",
    # A keyword granted until end of turn is what `activated_pump` holds on the
    # other side; same ability, other position.
    "grant_self_flying_until_eot": "triggered_pump",
    "grant_target_flying_until_eot": "triggered_pump",
    # Erhnam Djinn, once the "until your next upkeep" duration became a channel
    # with a sweep and its card-keyed hook retired: the trigger now lowers
    # through the ordinary keyword grant, so it needs the bucket its siblings
    # above already have.
    "grant_target_keyword_until_eot": "triggered_pump",
    "remove_event_subject_keyword": "triggered_pump",
    # The P/T twin of the row above (Spined Sliver). Only a trigger can produce
    # it — the object it acts on is the one the firing event froze — so it has
    # no `activated_` sibling in the table above.
    "pump_event_subject": "triggered_pump",
    "pump_self": "triggered_pump",
    "pump_target_creature_until_eot": "triggered_pump",
    "tap_any_number_then_pump_self": "triggered_pump",
    # Looking at cards and choosing among them.
    "look_top_pick_to_hand": "triggered_look",
    # Goblin Ringleader and Apocalypse's six other recruiters: "reveal the top
    # four cards of your library. Put all Goblin cards revealed this way into
    # your hand and the rest on the bottom of your library in any order." The
    # kind is Mulch's, which no trigger had produced; its bucket is Raven
    # Familiar's one row up — a pile off the top, part of it kept, the rest
    # bottomed — with the pick made by a printed filter instead of the player.
    "reveal_top_sorting_by_filter": "triggered_look",
    "reveal_hand_and_choose": "triggered_look",
    "scry": "triggered_look",
    # "At the beginning of your upkeep, surveil 1." (Think Tank.) Scry's
    # bucket: the same look, with the graveyard for the bottom.
    "surveil": "triggered_look",
    "mill_target_player": "triggered_mill",
    # Life loss is not damage by the rules (CR 120.3), but for a report about
    # what an ability does to a player it is the same bucket.
    "target_loses_life": "triggered_damage",
    "prevent_all_combat_damage_to_matching": "triggered_prevent",
    "player_loses_game": "triggered_game_end",
    # Moving a card out of a graveyard, whichever way and whoever's.
    "return_creature_from_graveyard_to_hand": "triggered_recursion",
    "return_self_from_graveyard": "triggered_recursion",
    "sacrifice_matching_permanent": "triggered_sacrifice",
    # A composed effect, exactly as `sequence` is on the activated side: the
    # wrapper cannot say what the ability is for, so the label names the shape
    # rather than guessing at a bucket. Ten cards share it and they do ten
    # different things.
    "sequence": "triggered_sequence",
    # --- Legends' triggered abilities, added at its promotion ----------------
    # Same rule again: the bucket the ability belongs to, in the vocabulary the
    # pool already uses. Every entry here also has to *keep a prefix*: a label
    # without `triggered_` is what `web/serialization.py` reads as "not a
    # triggered ability", so the fallback marker `spell_pattern` is never the
    # answer for a trigger that uses the stack.
    #
    # A combat restriction laid on a creature (Wall of Dust), beside the
    # `triggered_combat` the optional combat triggers already take.
    "cant_attack_during_controllers_next_turn": "triggered_combat",
    # Gabriel Angelfire's upkeep grant ("choose flying, first strike, trample,
    # or rampage 3" — a CR 608.2d choice, not a modal one) and Illusionary
    # Presence's landwalk, and every printed modal trigger ("Whenever … ,
    # choose one —", Elder Gargaroth, Trufflesnout), which
    # ``ability_lines`` labels through this same row. `choose_one` is a
    # **wrapper** and says nothing by itself, so it takes the shape label the
    # activated side's `activated_modal` already is. It read `triggered_pump`
    # because the two grammar-read cards both grant keywords — the borrowing
    # `if_then` was argued into for the Urza's cycle and argued out of, and
    # which put every modal trigger in the pool in the pump bucket.
    "choose_one": "triggered_modal",
    # In the Eye of Chaos, Invoke Prejudice, Nether Void, Presence of the
    # Master. `activated_counter` / `triggered_counter` mean a +1/+1 counter, so
    # countering takes the grammar category's word, matching
    # `counter_stack_ability` on the activated side. Note this is *not* the
    # `spell_pattern` that `counter_top_stack_spell` carries in the activated
    # table: that label is the legacy marker, and here it would cost four real
    # triggers their `triggered_` prefix.
    "counter_top_stack_spell": "triggered_counterspells",
    # Blight, beside `destroy_target_permanent`.
    "destroy_attached_permanent": "triggered_destruction",
    # Nicol Bolas, beside `opponent_discards_random_card_on_damage`.
    "discard_hand": "triggered_discard",
    # Hazezon Tamar's departing Sand Warriors, beside `exile_self`.
    "exile_all_matching": "triggered_exile",
    # Pit Scorpion's poison counters. A counter is a counter whether it sits on
    # a permanent or on a player (CR 122.1).
    "player_gets_poison_counters": "triggered_counter",
    # Knowledge Vault's leave-trigger empties the pile its activated ability
    # filled; `triggered_exile` is where that pile lives.
    "put_exiled_with_source": "triggered_exile",
    # --- Urza's Saga's four, added at its promotion -------------------------
    # The Hidden / Opal / Veiled cycle is fifteen cards printing one sentence
    # with the nouns changed — "if this permanent is an enchantment, it becomes
    # a 2/2 Gargoyle creature". Both of its kinds already sit in
    # `ACTIVATED_LABELS` under `activated_pump` (the animation is a P/T and a
    # type arriving together, and `engine/pt.py` is where it lands), so the
    # triggered spellings take the mirror bucket. Hidden Stag prints both, one
    # in each direction.
    "animate_self_indefinitely": "triggered_pump",
    "set_card_types_self": "triggered_pump",
    # Cackling Fiend, beside `discard_hand` above: the seat set is payload, and
    # a discard is a discard whoever the sentence names (CR 701.9a).
    "each_opponent_discards_cards": "triggered_discard",
    # Marsh Crocodile's "When this creature enters, each player discards a
    # card." - the row above with every seat in the set, its controller's
    # included.
    "each_player_discards_a_card": "triggered_discard",
    # Noetic Scales returns every creature whose power outruns its controller's
    # hand. `triggered_return` for `return_source_card_to_owners_hand`'s reason
    # — the destination is a hand and the act is a bounce; that it names a
    # described set rather than one object is the payload's business.
    "return_all_matching": "triggered_return",
    # Aisling Leprechaun turns a blocker green — the colour change whose bucket
    # `recolor_enchanted_chosen_color` settles on the activated side.
    "recolor_target_from_text": "triggered_pump",
    # Divine Intervention's countdown and Venarian Gold's sleep counter. Not
    # `upkeep_effect`: that label belongs to the pay-or-consequence upkeep
    # registry, and these are ordinary triggers that go on the stack, where the
    # prefix is read.
    "move_counter_from_self": "triggered_counter",
    "move_all_counters_to_self": "triggered_counter",
    "remove_counter_from_self": "triggered_counter",
    "remove_all_counters_from_self": "triggered_counter",
    "remove_counter_from_attached": "triggered_counter",
    # Elder Land Wurm shedding defender: `grant_self_keyword_until_eot` with a
    # minus sign, and the same bucket.
    "remove_self_keyword": "triggered_pump",
    # Three P/T rewrites (Brine Hag, Halfdane, Wall of Tombstones), beside
    # `pump_self` and `pump_target_creature_until_eot`.
    "set_base_pt_of_creatures_that_damaged_source": "triggered_pump",
    "set_source_base_pt_from_target_until_next_upkeep": "triggered_pump",
    "set_source_base_toughness_from_count": "triggered_pump",
    # The Wretched keeps what blocked it. `activated_steal` is the pool's word
    # for an ability whose point is who controls what; this is its trigger.
    "steal_blockers_of_source": "triggered_steal",
    # Arena of the Ancients, beside `tap_enchanted_creature`.
    "tap_all_matching": "triggered_tap",
    # Cosmic Horror, beside the four `upkeep_pay_or_*` entries above: a
    # pay-or-consequence upkeep trigger the upkeep registry runs.
    "upkeep_pay_or_destroy_self": "upkeep_effect",
    # --- Ice Age's promotion -------------------------------------------------
    # Written while ICE was measured, where this guard - which reads
    # `load_catalog()`, the shipped pool - could not see them. Each names what
    # the ability is *for*, which is the question the support report and
    # `SimulationResult` ask. The `may` and `if_then` wrappers among ICE's new
    # triggers are in TRIGGERED_LABELS_BY_CONDITION instead, for this table's
    # own stated reason: a wrapper says nothing about its contents.
    "discard_target_cards": "triggered_discard",
    "return_bound_card_to_owners_hand": "triggered_return",
    "reanimate_bound_card": "triggered_return",
    # "When this creature enters, look at the top four cards of your library,
    # then put them back in any order." (Sage Owl.) Beside
    # ``reorder_target_library_top``'s ``activated_library`` in the other
    # table: what the label reports is what the ability does, and the only
    # difference here is the position the line occupies.
    "reorder_own_library_top": "triggered_library",
    # "When this creature dies, shuffle it into its owner's library."
    # (Alabaster Dragon.) The card goes from one zone to another, which is what
    # every self-move in these tables reports.
    "shuffle_source_card_into_library": "triggered_library",
    # "When this creature enters, shuffle the cards from your hand into your
    # library, then draw that many cards." (Whirlpool Rider; the Drake prints
    # it on dying too.) The same effect as the Warrior's row in the other
    # table, in the position that makes it a trigger — and it needs the row for
    # more than a bucket: without one it kept the `spell_pattern` marker, and
    # the `triggered_` prefix is what the web layer serializes a stack item's
    # `is_triggered` from.
    "shuffle_hand_into_library": "triggered_library",
    "add_named_counter_to_target": "triggered_counter",
    "prevent_damage_to_target_until_eot": "triggered_prevention",
    "exile_target_permanent": "triggered_exile",
    "exile_bound_card_from_graveyard": "triggered_exile",
    "deny_regeneration_to_block_pair": "spell_pattern",
    # Icatian Skirmishers. The activated twin above is `activated_pump`,
    # because there the ability is a pump however it is spelled; a keyword
    # granted to the *band* on attacking is a combat ability, which is the
    # bucket the vocabulary already has for a trigger that only exists
    # inside a declare-attackers step.
    "grant_team_keyword_until_eot": "triggered_combat",
    # --- Weatherlight, at its promotion -------------------------------------
    # Six triggered kinds that fell back to the `spell_pattern` marker the
    # moment `load_catalog()` widened. Each takes the word its own **activated**
    # twin already carries in the activated table (`activated_labels`), which
    # is the vocabulary's settled rule: the bucket names what the ability does,
    # and whether a player activated it or an event announced it is not part
    # of that question.
    #
    # Abduction untapping what it enchants -- `untap_enchanted_creature` is
    # `activated_untap`.
    "untap_enchanted_creature": "triggered_untap",
    # Silkenfist Fighter and Silkenfist Order (NEM, at its promotion):
    # "Whenever this creature becomes blocked, untap it." The self-subject twin
    # of the row above, and `untap_self` is `activated_untap` — same rule.
    "untap_self": "triggered_untap",
    # Ancestral Knowledge shuffling its owner's library -- `shuffle_library` is
    # `activated_library`: the library is the object.
    "shuffle_library": "triggered_library",
    # Festering Evil on its own upkeep -- `deal_damage_each_creature_and_player`
    # is `activated_damage`, and a sweep is still damage.
    "deal_damage_each_creature_and_player": "triggered_damage",
    # Gaea's Blessing, from its owner's *library* (CR 113.6k) --
    # `shuffle_graveyard_into_library` is `activated_recursion`: cards come back.
    "shuffle_graveyard_into_library": "triggered_recursion",
    # Jangling Automaton untapping a described set on an attack --
    # `untap_all_matching` is `activated_tapping`, added directly above for
    # Llanowar Druid, and how many permanents is not the question.
    "untap_all_matching": "triggered_tapping",
    # Mana Web tapping the lands that could pay for what was just tapped. A tap
    # sweep like the row above it, and the same word for the same reason.
    "tap_lands_sharing_produced_mana": "triggered_tapping",
    # --- Tempest, at its promotion ------------------------------------------
    # Four kinds falling back to the `spell_pattern` marker, all four this
    # set's. They were **masked**: the activated half of
    # ``test_no_grammar_read_ability_falls_back_to_the_category_default``
    # asserts first, so seven activated rows had to land before this half of the
    # same test could say anything. A guard with two assertions reports the
    # first one only.
    #
    # The fallback is not merely a bucket here. `web/serialization.py` reads a
    # stack item's `is_triggered` off this label's ``triggered_`` prefix, and
    # `spell_pattern` has none -- so each of these four announced itself on the
    # stack as though it were a spell.
    #
    # Duplicity's entry exiles the top five face down. ``exile_entire_library``
    # and ``exile_all_matching`` are already `triggered_exile`, which is the
    # word this side spells the family with -- the same kind reads
    # `activated_recursion` for Knowledge Vault on the other side, exactly as
    # ``exile_target_graveyard`` and ``put_exiled_with_source`` do.
    "exile_top_of_library": "triggered_exile",
    # Elven Warhounds puts its blocker on top of a library --
    # ``put_target_on_library_top`` is `activated_library` for Civic Guildmage
    # ("a permanent on top of a library"), and ``shuffle_source_card_into_library``
    # is already the triggered spelling of the same act on this side.
    "put_target_on_library_top": "triggered_library",
    # Magnetic Web's magnet counters make every other one block the attacker.
    # The sweep twin of ``force_target_to_block_until_eot``, added to the
    # activated table (`activated_labels`) as `activated_combat` for
    # Trumpeting Armodon: a blocking requirement (CR 509.1c), and how many
    # creatures it names is payload rather than a different act.
    "force_subject_to_block_until_eot": "triggered_combat",
    # Unstable Shapeshifter takes the copiable values of whatever just entered
    # (CR 707.2). `triggered_copy` is the bucket for an ability whose point is
    # that something is copied; its other member (``copy_triggering_spell``)
    # copies an object on the stack rather than a permanent's layer-1 values,
    # which is the payload's business and not what the label answers.
    # Deliberately not `triggered_pump`: that is this side's word for a P/T or
    # keyword change, and a report saying "pump" of an ability that can *shrink*
    # the creature to a 1/1 is the misleading kind this table refuses.
    "become_copy_of_bound_permanent": "triggered_copy",
    # --- Exodus, at its promotion -----------------------------------------
    # One kind, and it was **masked** exactly as Tempest's four were: the
    # activated half of
    # ``test_no_grammar_read_ability_falls_back_to_the_category_default``
    # asserts first, so this row could not be seen until Thrull Surgeon's and
    # Volrath's Dungeon's landed above. A guard with two assertions reports the
    # first one only, and that is now twice.
    #
    # Limited Resources' entry has each player keep five lands and give up the
    # rest. ``sacrifice_matching_permanent`` is already `triggered_sacrifice`
    # on this side, and which permanents survive is payload: what the ability
    # is for is that permanents are sacrificed. Deliberately not a `board`
    # word — the keeps are how the sacrifice is *chosen*, not a second act.
    "keep_chosen_sacrifice_rest": "triggered_sacrifice",
    # --- Nemesis, wave 1 group 3 --------------------------------------------
    # Blinding Angel's "that player skips their next combat phase" — the first
    # *triggered* skip in the pool (Moment of Silence is a spell, and its kind
    # is read by no label table at all). Its own word rather than
    # `triggered_combat`: the phase skipped is payload, and the same kind skips
    # a main phase as readily as a combat one, so a combat bucket would be a
    # claim about the payload rather than about what the ability does to the
    # turn.
    "skip_next_phase": "triggered_turn",
    # --- Odyssey, at its promotion ------------------------------------------
    # Battle of Wits and Chance Encounter: "At the beginning of your upkeep,
    # if <you have 200 or more cards in your library / this enchantment has
    # ten or more luck counters on it>, you win the game." The other end of
    # `player_loses_game` above and the same bucket: the game ends.
    "player_wins_game": "triggered_game_end",
    # Decaying Soil: "At the beginning of your upkeep, exile a card from your
    # graveyard." Beside `exile_graveyard_cards` -- whose pile and how the
    # card is picked are payload.
    "exile_cards_from_graveyard": "triggered_exile",
    # --- Torment, at its promotion rehearsal --------------------------------
    # Hypnox: "When this creature enters, if you cast it from your hand, exile
    # all cards from target opponent's hand." The guard's second assert, shown
    # once its first (Major Teroh's) was answered. Hand disruption, beside
    # `exile_cards_from_hand`'s `activated_discard` (Parallax Nexus) for that
    # row's reason: the cards come back when Hypnox leaves, to the player they
    # were taken from, and the point of the ability is the taking. Not only a
    # report bucket: the trigger reached the client with `spell_pattern`, so
    # `web/serialization` sent it as `is_triggered: False` - the Planeshift
    # rehearsal's two entry triggers exactly. Driven: the trigger is on the
    # stack after the cast, the hand is exiled, and handed back when Hypnox
    # leaves.
    "exile_hand_pile": "triggered_discard",
    # --- Judgment, at its promotion rehearsal -------------------------------
    # Wormfang Manta: "When this creature enters, you skip your next turn." and
    # "When this creature leaves the battlefield, you take an extra turn after
    # this one." Each is what the ability does to the order of turns, beside
    # `skip_next_phase`'s `triggered_turn` above: whether a turn is taken away
    # or added, and that it is a turn rather than a phase, is payload. Not only
    # a report bucket: under `spell_pattern` both reached the client as
    # `is_triggered: False`, Hypnox's finding above again.
    "skip_next_turn": "triggered_turn",
    "grant_extra_turn": "triggered_turn",
    # --- Mirrodin, W1G10 -----------------------------------------------------
    # Timesifter's upkeep contest ends in an extra turn: what the ability does
    # to the order of turns, beside the two rows above. Without it the trigger
    # reached the client as `is_triggered: False` (`spell_pattern`).
    "contest_top_cards": "triggered_turn",
    # Scalpelexis: "...that player exiles the top four cards of their library.
    # If two or more of those cards have the same name, repeat this process."
    # A **wrapper** (its payload carries the exile it repeats), so the label
    # names the shape, as `activated_repeated` does for Grindstone on the
    # other side, never the leaf's bucket. Here rather than in
    # TRIGGERED_LABELS_BY_CONDITION, where the other triggered wrappers are,
    # because Scalpelexis is the kind's only triggered printing, and an entry
    # there needs a second label for the kind to disambiguate
    # (`test_the_by_condition_table_only_holds_genuine_ambiguities`).
    "repeat_process_while": "triggered_repeated",
    # --- Onslaught, at its promotion rehearsal ---------------------------
    # Leery Fogbeast: "Whenever this creature becomes blocked, prevent all
    # combat damage that would be dealt this turn." The first trigger to reach
    # the unnarrowed Fog (every shipped printing is a spell, or the activated
    # row's `activated_prevent`), and the bucket its narrowed twin
    # `prevent_all_combat_damage_to_matching` already takes above. Shown by
    # the guard's second assertion only once the activated half was green.
    "prevent_all_combat_damage": "triggered_prevent",
    # --- Legions, at its promotion rehearsal -------------------------------
    # Three leaves the set's triggers are the first to reach in the triggered
    # position, each settled against the spelling its family already has
    # rather than the `spell_pattern` marker they fell back to.
    #
    # Daru Mender: "When this creature is turned face up, regenerate target
    # creature." The activated table's `activated_regenerate` for the same
    # kind, with the triggered prefix: what the ability does is a shield, and
    # that a morph turning face up sets it off is the condition's business.
    "grant_regeneration_to_target_creature": "triggered_regenerate",
    # Weaver of Lies: "When this creature is turned face up, turn any number
    # of target creatures with morph abilities other than this creature face
    # down." The mirror of `turn_target_face_up`'s `activated_pump` (Ixidor):
    # the permanent stops being the card it is and becomes the blank 2/2
    # (CR 708.2), every characteristic at once, which is the report's one word
    # for a permanent changing what it is.
    "turn_target_face_down": "triggered_pump",
    # Phage the Untouchable: "Whenever Phage deals combat damage to a player,
    # that player loses the game." The other spelling of `player_loses_game`
    # above (the seat the damage froze rather than a described one), and its
    # bucket: the game ends.
    "target_player_loses_game": "triggered_game_end",
    # --- Scourge, at its promotion rehearsal -----------------------------
    # Seven leaves the set's triggers are the first to reach in the triggered
    # position, shown by the guard's second assertion once Thundercloud
    # Elemental's activated row turned the first green — each settled against
    # the bucket its family already has rather than the `spell_pattern` marker
    # they fell back to.
    #
    # Frontline Strategist ("When this creature is turned face up, prevent all
    # combat damage non-Soldier creatures would deal this turn") and Karona's
    # Zealot ("…all damage that would be dealt to it this turn is dealt to
    # target creature instead"): the activated
    # table's `activated_prevent` for both kinds, with this side's prefix —
    # Leery Fogbeast's unnarrowed Fog above is the same word.
    "grant_source_class_prevention_shield": "triggered_prevent",
    "redirect_next_damage_from_source_until_eot": "triggered_prevent",
    # Lingering Death: "At the beginning of the end step of enchanted
    # creature's controller, that player sacrifices that creature." Beside
    # `sacrifice_self` and `sacrifice_matching_permanent`.
    "sacrifice_attached_permanent": "triggered_sacrifice",
    # Mischievous Quanar: "When this creature is turned face up, copy target
    # instant or sorcery spell." Beside the storm trigger's
    # `copy_triggering_spell`: a copy of a spell either way.
    "copy_top_stack_spell": "triggered_copy",
    # "…you may copy the other. If you do, you may cast the copy without
    # paying its mana cost." (Spellweaver Helix.) CR 707.12's copy of a card,
    # cast as the trigger resolves — a copy, beside the row above.
    "cast_copy_of_exiled_card": "triggered_copy",
    # Xantid Swarm: "Whenever this creature attacks, defending player can't
    # cast spells this turn." `forbid_land_plays_this_turn`'s
    # `activated_restriction`, the other half of CR 305.1's pair, with this
    # side's prefix: a seat is barred from an action for the turn.
    "forbid_casting_types_this_turn": "triggered_restriction",
    # Grip of Chaos: "Whenever a spell or ability is put onto the stack, if it
    # has a single target, reselect its target at random." No shipped bucket
    # names a change of targets; its grammar category's own word, the way
    # `counter_top_stack_spell` reads `triggered_counterspells`.
    "change_event_object_targets": "triggered_retargeting",
    # Form of the Dragon: "At the beginning of each end step, your life total
    # becomes 5." A total *set*, which can be a gain or a loss — so neither
    # `triggered_damage` (`target_loses_life`) nor a gain's bucket, for Mirror
    # Universe's reason on the activated side; its category's own word.
    "set_life_total": "triggered_life",
    # --- Mirrodin, at its promotion rehearsal ----------------------------
    # Four leaves the grammar reads that had no row, so each reached the
    # client as the `spell_pattern` marker; each takes the bucket its nearest
    # shipped neighbour already has.
    # Chimney Imp: "When this creature dies, target opponent puts a card from
    # their hand on top of their library." Beside `put_target_on_library_top`
    # and `shuffle_hand_into_library`.
    "put_hand_cards_on_library": "triggered_library",
    # Duskworker: "Whenever this creature becomes blocked, regenerate it."
    # `grant_regeneration_to_target_creature`'s bucket, as the activated
    # table files the two together (`activated_regenerate`).
    "grant_regeneration_to_self": "triggered_regenerate",
    # Neurok Familiar: "When this creature enters, reveal the top card of
    # your library. If it's an artifact card, put it into your hand.
    # Otherwise, put it on the bottom of your library." Beside
    # `reveal_top_sorting_by_filter` and `look_top_pick_to_hand`.
    "reveal_top_to_hand_or_bottom": "triggered_look",
    # Vulshok Battlemaster: "When this creature enters, attach all Equipment
    # on the battlefield to it." No triggered bucket names an attachment;
    # its grammar category's own word (`attachments`), the way
    # `change_event_object_targets` reads `triggered_retargeting`.
    "attach_all_to_source": "triggered_attachments",
    # Carry Away: "When this Aura enters, unattach enchanted Equipment." The
    # same bucket, the other direction of CR 701.3.
    "unattach_attached_permanent": "triggered_attachments",
    # Confusion in the Ranks: "Whenever an artifact, creature, or enchantment
    # enters, its controller chooses target permanent another player controls
    # that shares a card type with it. Exchange control of those permanents."
    # The fused targeted exchange W2G4 lowered it to, on a trigger for the
    # first time; Gauntlets of Chaos files the same kind `activated_steal`,
    # so the triggered twin of that bucket.
    "exchange_control_of_targets": "triggered_steal",
}

# The wrapper kinds whose label depends on what triggered them: `may` wraps
# whatever the optional clause offers, so the wrapper says nothing about the
# effect, and the **condition names the moment** — never the effect behind the
# wrapper, which differs card by card. One condition, one word: every wrapper
# row sharing a condition shares its label, and a word that is also a leaf
# effect's bucket names the moment only where the moment is of that kind (a
# draw, a discard, a destruction) — both held by
# ``tests/engine/test_kg3_chores_moment_labels.py``. Until kg3 eleven rows named
# the effect of the card that prompted them (Thelon's Chant's damage,
# Insubordination's destruction, Verduran Enchantress's draw, Bazaar of
# Wonders' counterspell) or the `spell_pattern` fallback marker.
TRIGGERED_LABELS_BY_CONDITION: dict[tuple[str, str], str] = {
    # The cast moment: "whenever a player casts a spell" / "whenever an
    # opponent casts" / "whenever you cast an enchantment spell" / "when you
    # cast this spell". Bazaar of Wonders ("counter it if …"), Ice Cave (a
    # price offered round the table), Mana Vortex (its own counter), Verduran
    # Enchantress (a draw), the Crystal Rod cycle and Rhystic Study (life, a
    # card) — what each offers differs, and the moment, a spell cast, does
    # not: `triggered_cast`, the word ("you_cast_spell", "may") already had.
    # The first three read `triggered_counterspells`, the Enchantress
    # `triggered_draw`, the rest `spell_pattern`.
    ("spell_cast", "if_then"): "triggered_cast",
    ("spell_cast", "unless_player_pays"): "triggered_cast",
    ("spell_cast", "may"): "triggered_cast",
    ("opponent_casts_spell", "may"): "triggered_cast",
    ("enchantment_cast", "may"): "triggered_cast",
    ("self_cast", "may"): "triggered_cast",
    # --- Mercadian Masques, at its promotion -----------------------------
    # Five `may` wrappers over three conditions, each taking the bucket the
    # condition's nearest neighbour already has. The set prints
    # "whenever this creature becomes blocked, you may …" four times
    # (Chambered Nautilus, Port Inspector, Saprazzan Heir — and Robber Fly's
    # sibling shape), which is `creature_blocks_or_blocked_by` one narrowing
    # over and takes its bucket.
    ("creature_becomes_blocked", "may"): "triggered_combat",
    # Psychic Membrane (MRD, at its promotion rehearsal): "Whenever this
    # creature blocks, you may draw a card." The other side of the row above
    # and the narrower half of `creature_blocks_or_blocked_by`, so the same
    # moment's bucket; without a row the `may` read the `spell_pattern`
    # marker, a leaf's bucket.
    ("creature_blocks", "may"): "triggered_combat",
    # Gustcloak Savior (ONS): "Whenever **a creature you control** becomes
    # blocked, you may untap that creature and remove it from combat." The
    # board-wide reading of the row above, and the same moment.
    ("matching_creature_becomes_blocked", "may"): "triggered_combat",
    # Saber Ants, beside `damage_dealt` above: being dealt damage is a combat
    # moment whatever dealt it.
    ("creature_dealt_damage", "may"): "triggered_combat",
    # Foster, beside `dies` and `attached_creature_dies`: whose creature died
    # narrows the trigger, not what the ability is about.
    ("creature_you_control_dies", "may"): "triggered_death",
    # Fecundity, Inheritance, Soul Net: "whenever a creature dies, … may …".
    # The death moment, beside the two rows above; it read `spell_pattern`.
    ("creature_dies", "may"): "triggered_death",
    # Icy Prison: "At the beginning of your upkeep, sacrifice this enchantment
    # unless any player pays {3}." The wrapper says nothing about what is
    # offered, so the condition names the moment, beside ("upkeep_self", "may").
    # It was a condition-blind row in TRIGGERED_LABELS until the kg round, which
    # gave every `unless_player_pays` trigger the upkeep's word whatever
    # triggered it: a second card printing the offer on a cast or a combat
    # would have been reported as an upkeep effect rather than falling back,
    # which is what makes this table name it.
    ("upkeep_self", "unless_player_pays"): "upkeep_effect",
    # Living Artifact, once its fused reading went away. The condition is what
    # says this is an upkeep effect; the wrapper still says nothing, and the
    # optional clause behind it ("remove a counter … gain 1 life") is neither a
    # draw nor damage.
    ("upkeep_self", "may"): "upkeep_effect",
    # The Dark's pay-or-consequence upkeeps, which reach the stack as an
    # ordinary optional trigger rather than through the `upkeep_pay_or_*` kinds:
    # Curse Artifact and Erosion ask the *enchanted permanent's* controller,
    # Worms of the Earth asks every player. Same bucket as the four
    # `upkeep_pay_or_*` entries above — what differs is who is asked, which is
    # payload, not a different kind of ability.
    ("upkeep_enchanted_controller", "may"): "upkeep_effect",
    ("upkeep_each", "may"): "upkeep_effect",
    # Onslaught's cycling triggers. Every one of the ten "when you cycle this
    # card" lines and four of the five "whenever a player cycles a card" lines
    # open "you may", and what they offer ranges over life, a shield, a tap, a
    # counterspell, a pump, a search, an exile and a ping — so the condition
    # names the moment, the rule this table has kept since M21.
    ("self_cycled", "may"): "triggered_cycling",
    ("cycles_card", "may"): "triggered_cycling",
    # Spitting Slug's first strike, bought or given away. `triggered_combat`
    # rather than `triggered_pump`: both branches happen in combat and only one
    # of them pumps anything of yours.
    ("creature_blocks_or_blocked_by", "may"): "triggered_combat",
    # M21's seventeen optional triggers. `may` still says nothing about the
    # effect, and the *condition* is the only thing in the pair that does — so
    # each row names the moment rather than the effect, which is the honest
    # answer for a wrapper whose contents differ card by card.
    ("combat_your_turn", "may"): "triggered_combat",
    ("damage_dealt", "may"): "triggered_combat",
    ("dies", "may"): "triggered_death",
    # --- Urza's Destiny, at its promotion ---------------------------------
    # Three more optional triggers whose wrapper says nothing about what it
    # offers, so the condition names the moment — the rule this table has
    # followed since M21's seventeen above. Compost's is a card reaching an
    # opponent's graveyard, Sanctimony's a land tapped for mana, and Pattern
    # of Rebirth's the death of the creature it enchants; Pattern of Rebirth
    # is shipped and reached this table for the first time here, which is the
    # promotion gate doing its job rather than the card changing.
    ("card_put_into_graveyard", "may"): "triggered_death",
    ("land_tapped_for_mana", "may"): "triggered_mana",
    ("attached_creature_dies", "may"): "triggered_death",
    ("enters_battlefield", "may"): "triggered_etb",
    ("draws_card", "may"): "triggered_draw",
    ("end_step", "may"): "triggered_end_step",
    ("end_step_self", "may"): "triggered_end_step",
    ("main_phase_first", "may"): "triggered_main_phase",
    # "At the beginning of each of your main phases, … **you may** add X mana
    # of any one color." (Carpet of Flowers.) The same pair one condition over:
    # the wrapper says nothing about what the offer does, so the condition is
    # what names the bucket.
    ("main_phase_each_yours", "may"): "triggered_main_phase",
    ("permanent_becomes_untapped", "may"): "triggered_untap",
    ("self_becomes_target", "may"): "triggered_targeted",
    # Riddleform, once its animation trigger compiled (round 137). The
    # condition is what says when; the wrapper still says nothing about
    # the optional clause behind it.
    ("you_cast_spell", "may"): "triggered_cast",
    # Burgeoning's "whenever an opponent plays a land, you may put a land card
    # from your hand onto the battlefield". Added at Stronghold's promotion,
    # not because Burgeoning changed but because Horn of Greed gave
    # `land_played` a third value on its seat axis and the pair reached this
    # table for the first time. `may` says nothing about what follows, so the
    # row names the moment — CR 305.1's land drop, which is neither a cast nor
    # a step.
    ("land_played", "may"): "triggered_land_played",
    # --- Prophecy, at its promotion ---------------------------------------
    # Reveille Squad: "Whenever one or more creatures attack you, if this
    # creature is untapped, you may untap all creatures you control." The one
    # `may` the set puts behind a condition this table had not met. The wrapper
    # says nothing about the offer, so the condition names the moment, and the
    # declaration of attackers is a combat moment — the bucket
    # `creature_becomes_blocked` and `combat_your_turn` already take above.
    ("attackers_declared", "may"): "triggered_combat",
    # Antiquities' two optional death triggers (Tablet of Epityr, Urza's
    # Miter), added at its promotion. `permanent_dies` is the wider condition
    # `dies` above narrows to a creature, and it names the same moment.
    ("permanent_dies", "may"): "triggered_death",
    # Legends' four optional triggers, added at its promotion. Same rule as
    # M21's block: `may` says nothing, so the row names the moment.
    ("attacks_unblocked", "may"): "triggered_combat",
    ("creature_attacks_or_blocks", "may"): "triggered_combat",
    ("draw_step_self", "may"): "triggered_draw",
    # Imprison's second trigger. The moment is an ability being activated —
    # neither a cast nor a combat step, so it gets the word for what it watches,
    # beside `("you_cast_spell", "may")` above.
    ("nonmana_ability_activated", "may"): "triggered_activation",
    # --- Ice Age's promotion ---
    # `may`, `if_then` and `for_each` are wrappers: they say a decision or a
    # loop happens and nothing about what it does, so the condition is the only
    # half of the pair that names the moment. Three of these read
    # `spell_pattern` — the fallback marker, which is also a leaf's bucket —
    # until kg3: an attack is the combat moment, and a permanent becoming
    # tapped is the tap moment, as ("permanent_becomes_untapped", "may") is the
    # untap's. Oath of Lim-Dûl's `for_each` now takes the condition-blind
    # shape row, and Insubordination's end-step `if_then` (which read
    # `triggered_destruction`, though the card deals damage) the conditional
    # one, as every other end step's `if_then` does.
    ("creature_attacks", "may"): "triggered_combat",
    ("permanent_becomes_tapped", "may"): "triggered_tap",
    ("upkeep_self", "if_then"): "upkeep_effect",
    ("upkeep_self", "for_each"): "upkeep_effect",
    # --- Fallen Empires, at its promotion -----------------------------------
    # Goblin Flotilla's "At the beginning of each combat, unless you pay {R},
    # …", beside ("combat_your_turn", "may") and the other combat offers above.
    # The condition is the bare `combat`, which this set is also the reason
    # anything *announces* — it sat in both front-end tables with no fire site
    # until the wave gave it one.
    ("combat", "may"): "triggered_combat",
    # Thelon's Chant and Tourach's Chant: "Whenever a player puts a <land type>
    # onto the battlefield, this enchantment deals 3 damage to that player
    # unless they put a -1/-1 counter on a creature they control." — and eight
    # more "whenever a <noun> enters, … may …" (Aura Shards destroys, Mana
    # Echoes adds mana, Totem Speaker gains life). The moment is a permanent
    # entering, so the word is ("enters_battlefield", "may")'s. It read
    # `triggered_damage`, the Chants' declined branch, until kg3; the guard
    # that tells a moment's word from an effect's is the declared list of
    # shared words in ``test_kg3_chores_moment_labels``.
    ("matching_permanent_enters", "may"): "triggered_etb",
    # --- Odyssey, at its promotion ------------------------------------------
    # `may` says nothing, so each row names the moment, as M21's and Legends'
    # blocks above do. Confessor: "Whenever a player discards a card, you may
    # gain 1 life."
    ("discards_card", "may"): "triggered_discard",
    # Karmic Justice: "Whenever a spell or ability an opponent controls
    # destroys a noncreature permanent you control, you may destroy target
    # permanent that opponent controls." The moment is a destruction, and so
    # is the answer.
    ("permanent_destroyed", "may"): "triggered_destruction",
    # --- Judgment, at its promotion rehearsal -------------------------------
    # Web of Inertia: "At the beginning of combat on each opponent's turn, that
    # player may exile a card from their graveyard. If the player doesn't,
    # creatures they control can't attack you this turn." `may` says nothing,
    # so the row names the moment, beside ("combat", "may") and
    # ("combat_your_turn", "may") above: whose turn the combat is in is the
    # condition's narrowing, not another kind of ability.
    ("combat_opponent_turn", "may"): "triggered_combat",
    # --- Legions, at its promotion rehearsal --------------------------------
    # Four morphs whose face-up trigger opens "you may": Chromeshell Crab's
    # exchange, Dermoplasm's creature from hand, Master of the Veil's turn face
    # down, Imperial Hellkite's search. A condition-blind `may` falls back to
    # `spell_pattern`, which is a leaf's bucket too
    # (`test_a_triggered_wrapper_row_never_borrows_a_leaf_effects_bucket`), so
    # the condition names the moment, as every other `may` row here does:
    # CR 702.37e / 708.8's turning face up, which is neither an entry nor a
    # cast — the permanent was on the battlefield all along.
    ("turned_face_up", "may"): "triggered_face_up",
    # Scourge: the same moment watched from anywhere on the board ("Whenever
    # a permanent is turned face up, you may draw a card", Aphetto
    # Runecaster) — the same bucket, because it is the same event.
    ("permanent_turned_face_up", "may"): "triggered_face_up",
}
