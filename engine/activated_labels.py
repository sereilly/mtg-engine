"""The activated family of the ``effect_kind`` vocabulary: one row per
instruction kind the grammar reads in the **activated** position.

``engine/effect_labels.py`` is the reader (``activated_label``) and holds the
vocabulary's story — what reads a label, what never may, and why the rows are
kept rather than derived. A kind with no row here takes the reader's fallback,
``activated_<category>`` (the grammar category its instruction lowered to), so a
row is needed only when a card must keep a label the category cannot produce.

``tests/engine/test_effect_labels.py`` holds this table to the pool both ways
(every row reached, no grammar-read activated ability falling back), and
``tests/engine/test_kg_kinds_wrapper_labels.py`` holds a wrapper's row to its
shape. The table is keyed by kind, so its order is not behaviour; its
headings name the set or round that settled the rows under them.
"""

from __future__ import annotations

# Instruction kind -> label, for an ability the grammar reads in the **activated**
# position (the clause right of an ability's colon).
ACTIVATED_LABELS: dict[str, str] = {
    # --- Mirage, at its promotion ----------------------------------------
    # Ten kinds that arrived with the set and take the grammar category's
    # default until they are named here. The default buckets by *grammar
    # family*, which is not the vocabulary `SimulationResult` and the support
    # report were built on -- so every one is settled against a shipped
    # neighbour rather than against its family:
    #
    # Civic Guildmage / Shadow Guildmage put a permanent on top of a library,
    # beside `reorder_target_library_top`'s `activated_library`.
    "put_target_on_library_top": "activated_library",
    # Its self-subject twin (Thalakos Mistfolk), which reads the same way
    # and belongs in the same bucket — the difference between them is which
    # object the sentence names, not what the ability does. The row was
    # dead for one wave: W1G5 built the tuck while the card was still
    # unsupported on its *shadow* line, which W1G1 landed in the same wave.
    "put_source_card_on_library_top": "activated_library",
    # Volrath's Stronghold, the third of that group and the one that reaches a
    # *graveyard* for what it tucks. Same bucket for the two rows above's
    # reason: which zone the card comes from is not what the ability does, and
    # the library is still the object it acts on.
    "put_graveyard_cards_on_library_top": "activated_library",
    # Ersatz Gnomes and Raging Spirit change a colour, which Alchor's Tomb
    # settled as `activated_pump`: the report's word for a permanent changing
    # what it *is*.
    "recolor_target_from_text": "activated_pump",
    "recolor_targets_until_eot": "activated_pump",
    "recolor_self_until_eot": "activated_pump",
    # Mist Dragon phases itself out and drops its own keyword. Phasing is a
    # zone-shaped disappearance rather than a destruction, and the settled word
    # for a permanent leaving and coming back is `activated_recursion`; the
    # keyword removal is a layer-6 change to what the permanent *is*.
    "phase_out_self": "activated_recursion",
    # Vanishing phases out what it enchants. The same word for the same reason:
    # a permanent leaving and coming back, and which permanent is not the
    # question the bucket answers.
    "phase_out_enchanted": "activated_recursion",
    "remove_self_keyword": "activated_pump",
    # Spatial Binding stops somebody else phasing out -- a restriction it
    # imposes on another permanent, which is the `activated_combat` family's
    # question asked outside combat, so it takes the restriction word.
    "forbid_phase_out": "activated_restriction",
    # "Target creature can't block this turn" (Jamuraan Lion, MIR), reached
    # from an activated ability. A restriction like `forbid_phase_out` above:
    # what the ability produces is a thing the target may no longer do. It
    # surfaced at Visions' promotion rather than Mirage's because the printed
    # clause only became a grammar production in this set's second wave; before
    # that the kind existed and no activated ability reached it.
    "target_cant_block_until_eot": "activated_restriction",
    # "{R}: Enchanted creature can't block this turn." (Manacles of Decay.)
    # The row above with the Aura's host in place of a chosen creature, and
    # the same bucket for the same reason.
    "attached_cant_block_until_eot": "activated_restriction",
    # "{1}{R}: Target creature can't block this creature this turn."
    # (Duct Crawler.) The same denial as the row above, narrowed to one
    # named attacker, so it reads the same bucket: what the ability is for
    # is that a block may not happen.
    "target_cant_block_source_until_eot": "activated_restriction",
    # Subterranean Spirit damages a described set, beside
    # `deal_damage_each_creature_and_player`.
    "deal_damage_each_matching": "activated_damage",
    # Mangara's Tome arms a one-shot draw replacement. A **wrapper**, so it
    # takes a label naming its shape rather than its leaf's bucket, beside
    # `create_delayed_trigger` below -- what the replacement eventually does is
    # the payload's business, and reading it off the leaf is the guess this
    # table's own note calls wrong in proportion to how well the wrapper works.
    "arm_draw_replacement": "activated_replacement",
    # --- Judgment ---------------------------------------------------------
    # Ring of Ma'rûf's line left `card_hooks.CARD_LINE_INSTRUCTIONS` when the
    # Wishes gave its "instead put a card you own from outside the game into
    # your hand" a production. The hook labelled it `activated_draw`; carried
    # here so retiring the hook does not re-bucket the card.
    "arm_outside_game_draw_replacement": "activated_draw",
    # --- Homelands ------------------------------------------------------
    # An enchantment any player may destroy by paying life (Aether Storm),
    # the expansion sweep Golgothian Sylex already had a production for
    # (Apocalypse Chime), the shroud waiver Autumn Willow grants one seat,
    # and Torture's counters onto the creature it enchants. Labels rather
    # than dispatch: this is the vocabulary `SimulationResult`, the support
    # report's buckets and the web layer's `is_triggered` prefix read.
    "destroy_self": "activated_destroy",
    "destroy_all_matching": "activated_destroy",
    "waive_shroud_for_target_player": "activated_targeting",
    "add_pt_counters_to_attached": "activated_counters",
    # --- The Dark ---
    # Declared rather than defaulted, for the reason the whole table exists: the
    # category default would bucket each of these by the *grammar family* its
    # kind sits in, which is not the vocabulary `SimulationResult` and the
    # support report were built on. Bone Flute is the tell — it is a shipped
    # card that had a settled bucket, and it only appears here because Orc
    # General's narrowed anthem generalised its kind out of a bespoke one.
    # Nettling Imp / Norritt. The bucket the card hook carried before the
    # grammar read the template, kept across the retirement so the support
    # report does not silently re-bucket a shipped card (the reason this
    # table exists at all): the grammar family is combat_restrictions, and
    # the settled vocabulary is "combat".
    "mark_non_wall_target_to_attack": "activated_combat",
    "buff_creatures_global": "activated_pump",
    "grant_cant_be_blocked_by_until_eot": "activated_evasion",
    "grant_cant_be_blocked_except_by_until_eot": "activated_evasion",
    "grant_half_prevention_shield": "activated_prevent",
    "skip_next_untap": "activated_tapping",
    "swap_controller_land_mana_until_eot": "activated_mana",
    "exile_target_permanent": "activated_destruction",
    # "Unless an opponent pays {2}, gain control of target artifact…"
    # (Scarwood Bandits), "…gets +1/+1 until end of turn unless any player pays
    # {2}" (Nakaya Shade), "…unless a player has this creature deal 4 damage to
    # them" (Barbarian Bully), "Any player may pay {1}. If no one does, …"
    # (Rhystic Circle). A **wrapper** -- its payload carries the effect behind
    # each answer -- so it takes the label naming its shape, which is `may`'s:
    # CR 118.12a defines "[do something] unless [a player does something else]"
    # as "[a player may do something else]. If [that player doesn't], [do
    # something]". It read `activated_control` for eight sets, after the card
    # that prompted the row; that was true of Scarwood Bandits and false of the
    # other three, a pump and a prevention among them -- the guess the
    # `sequence` row below calls wrong in proportion to how well the wrapper
    # generalises. It passed `test_a_wrapper_kind_never_borrows_a_leaf_effects_bucket`
    # only because no leaf had been filed under `activated_control` yet.
    "unless_player_pays": "activated_optional",
    "add_counter_to_self": "activated_counter",
    "add_power_counters_to_self": "activated_counter",
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
    # Mindslaver (CR 723): a turn given to another decider, the extra
    # turn's neighbour and its bucket.
    "control_player_next_turn": "spell_pattern",
    "grant_prevention_shield": "activated_prevent",
    "grant_regeneration_to_enchanted_creature": "activated_regenerate",
    "grant_regeneration_to_self": "activated_regenerate",
    "grant_regeneration_to_target_creature": "activated_regenerate",
    "grant_self_flying_until_eot": "activated_pump",
    "grant_target_flying_until_eot": "activated_pump",
    "hurricane_damage": "activated_damage",
    "look_at_target_hand": "activated_look",
    "mill_target_player": "activated_mill",
    "pump_enchanted_creature": "activated_pump",
    "pump_self": "activated_pump",
    "pump_target_creature_until_eot": "activated_pump",
    "remove_counter_from_self": "activated_counters",
    # A composed effect (Orcish Artillery's "deals damage to X and damage to
    # you"). A wrapper kind cannot say what the ability is *for* — it says only
    # that there is more than one step — so the label names the shape, exactly
    # as `triggered_sequence` does on the other side. It read
    # `activated_damage` for four sets, which was right for Orcish Artillery
    # and wrong for the other 53 abilities that lower to a `sequence`: six Mana
    # Batteries, Maze of Ith, Preacher, Knowledge Vault and five planeswalkers
    # were all reported as damage. Naming a leaf bucket from a wrapper is
    # guessing, and the guess is wrong in proportion to how well the wrapper
    # generalises.
    "sequence": "activated_sequence",
    "set_base_pt_target_until_eot": "activated_pump",
    "tap_target_permanent": "activated_tapping",
    # The equip keyword (CR 702.6a), compiled as the activated ability it is
    # defined to be. Its own bucket: the support report and the AI read the
    # label, and "activated_attachments" names what the ability does.
    "attach_source_to_target": "activated_equip",
    "untap_enchanted_creature": "activated_untap",
    "untap_self": "activated_untap",
    "untap_target_land": "spell_pattern",
    # --- M21's activated abilities, added at its promotion -------------------
    # Every one of these would otherwise take the `activated_<category>`
    # fallback, which is a label the support report has never bucketed by. Each
    # is placed in the bucket the *ability* belongs to rather than the one its
    # instruction kind reads like: a label answers "what is this ability for?".
    # Where the kind is a *wrapper* the question has no answer and the label
    # names the shape instead — see "sequence" and "if_then" above.
    #
    # Damage, however it is spelled. A fight (Brash Taunter) and a bite
    # (Heartfire Immolator) differ in who deals back, not in what the ability is
    # for; life loss is not damage by the rules (CR 120.3) but is the same
    # bucket for a report about what an ability does to a player.
    "source_fights_target": "activated_damage",
    # Triangle of War's two-target exchange. The same bucket as the fight above
    # it: what the ability is *for* is dealing damage, and which of the two
    # fighters the ability's own source is does not change that.
    "target_fights_target": "activated_damage",
    "source_bites_target": "activated_damage",
    "target_loses_life": "activated_damage",
    # Granting a keyword until end of turn, to the source, a target or the team.
    # `activated_pump` already holds the flying grants and the P/T setters, and
    # these are the same ability with a different word after "gains".
    "grant_self_keyword_until_eot": "activated_pump",
    "grant_target_keyword_until_eot": "activated_pump",
    # ...and to the creature an Aura is attached to: Keldon Mantle's "{G}:
    # Enchanted creature gains trample until end of turn." The same ability
    # with the Aura's host for a subject - its two siblings on that card are
    # a regeneration and a pump, each already in the bucket its verb names.
    "grant_enchanted_keyword_until_eot": "activated_pump",
    # Phyrexian Splicer's move, which is a removal and a grant in one
    # instruction — the bucket its two halves would each have had.
    "move_chosen_keyword_between_targets": "activated_pump",
    "grant_team_keyword_until_eot": "activated_pump",
    "set_team_base_pt_until_eot": "activated_pump",
    # Evasion. Dwarven Warriors, Tawnos's Wand and Subira's second ability
    # all reach the one grant now that the power bound is payload rather
    # than a kind of its own — and each keeps the bucket it reported
    # before, which is the whole reason this table exists.
    "grant_unblockable_to_target": "activated_evasion",
    "grant_unblockable_to_self": "activated_evasion",
    # Looking at cards and choosing among them. Scry is the paradigm case and
    # the look-and-pick (Waker of Waves) is the same question with a keep.
    "scry": "activated_look",
    "look_top_pick_to_hand": "activated_look",
    # Moving a card out of a graveyard. Three destinations, one bucket: what the
    # ability is for is that the graveyard stops holding it.
    "put_graveyard_card_on_library_bottom": "activated_recursion",
    "put_top_of_graveyard_on_library_bottom": "activated_recursion",
    "reanimate_creature": "activated_recursion",
    # Hakim, Loreweaver. The graveyard stops holding the Aura, which is what
    # the bucket above is for; that it arrives attached is the same answer.
    "reanimate_aura_onto_source": "activated_recursion",
    "exile_target_graveyard": "activated_recursion",
    # Phyrexian Furnace: one card off a named end of the pile rather than
    # the whole zone. Same bucket for the reason the three above share one:
    # what the ability is for is that the graveyard stops holding it.
    "exile_graveyard_position": "activated_recursion",
    # Goblin Welder. The bucket the six above share, and it is the right one
    # for the same reason: what the ability is *for* is that a graveyard stops
    # holding an artifact card. The sacrifice beside it is the price the card
    # charges for that, and paying it out of the same sentence does not make
    # this a destruction ability — a bucket keyed on the price rather than on
    # the point is how a label stops being a description of what the card does.
    "sacrifice_and_return_targets": "activated_recursion",
    # Urza's Saga's three, added at its promotion — the moment
    # `load_catalog()` first sees them, which is what this file's own note two
    # hundred lines down says promotion is for. All three take the same bucket
    # for the reason the four above share one: what the ability is for is that
    # the graveyard stops holding it, and which zone the card lands in is
    # payload rather than a family.
    #
    # Carrion Beetles exiles up to three cards out of a single pile;
    # Crystal Chimes and No Rest for the Wicked hand a whole class of card back
    # (enchantments, and creatures that died this turn). Exile and hand are
    # already both here — `exile_target_graveyard` and
    # `return_creature_from_graveyard_to_hand` — so neither destination is new.
    "exile_cards_from_graveyard": "activated_recursion",
    "return_all_cards_from_graveyard": "activated_recursion",
    # "Until end of turn, you may cast …" (Idol of Endurance). Not any of the
    # above: nothing moves and nothing changes characteristics — the ability's
    # whole effect is a permission (CR 601.3).
    "grant_cast_permission": "activated_permission",
    # "You may copy the exiled card. If you do, you may cast the copy without
    # paying its mana cost." (Isochron Scepter.) A cast offered during the
    # resolution (CR 707.12) — a permission to cast, of one copy.
    "cast_copy_of_exiled_card": "activated_permission",
    # "…as though they had flash" (Winding Canyons). A permission like its
    # neighbours, about timing rather than about a zone.
    "grant_flash_timing": "activated_permission",
    # "{T}, Sacrifice this land: Search your library for a basic land card…"
    # (Fabled Passage). A tutor, whatever the destination: `activated_look`
    # is for cards seen and chosen among, and a search is chosen from a
    # zone nobody sees.
    "search_library": "activated_search",
    # --- Antiquities' activated abilities, added at its promotion ------------
    # Each would otherwise take the `activated_<category>` fallback, which is a
    # label the support report has never bucketed by. Placed in the bucket the
    # *ability* belongs to rather than the one its instruction kind reads like —
    # the rule M21's block above states.
    #
    # Recursion, whatever the zone it pulls from and puts into: Argivian
    # Archaeologist and Feldon's Cane both put cards back where they can be
    # drawn again, and Obelisk of Undoing returns a permanent to a hand.
    "return_creature_from_graveyard_to_hand": "activated_recursion",
    "shuffle_graveyard_into_library": "activated_recursion",
    "bounce_target_creature": "activated_recursion",
    # A P/T change with a duration nobody else prints (Ashnod's Battle Gear,
    # Tawnos's Weaponry: "for as long as this artifact remains tapped"). The
    # duration is not what the ability is *for*, so it takes the pump bucket
    # every other P/T change takes.
    "pump_target_while_source_tapped": "activated_pump",
    "buff_creatures_global_while_source_tapped": "activated_pump",
    # Xenic Poltergeist turns a noncreature into a creature; Mishra's Factory
    # turns itself into one. Both are the layer-4 type change the
    # `characteristics` category names, and the report's existing word for a
    # permanent changing what it is is `activated_pump` — the P/T comes with it
    # in both cases.
    "gain_type": "activated_pump",
    # Opal Acrolith turning itself back from the creature its own trigger made
    # it. The same layer-4 change and the same bucket, for `gain_type`'s reason
    # — the report has one word for a permanent changing what it is.
    "set_card_types_self": "activated_pump",
    "animate_self_until_eot": "activated_pump",
    # "…becomes a 3/6 Golem artifact creature **until end of combat**."
    # (Jade Statue.) The same layer-4 change over the third window, so the
    # same bucket — the report has one word for a permanent changing what it
    # is, and the window is not what the word is about.
    "animate_self_until_end_of_combat": "activated_pump",
    # Stalking Stones, the same sentence with no end to it. Same bucket — the
    # report has no word for a duration.
    "animate_self_indefinitely": "activated_pump",
    # Golgothian Sylex sweeps a whole expansion off the board.
    "sacrifice_expansion_permanents": "activated_destruction",
    # Priest of Yawgmoth eats a permanent and pays out mana; the mana is the
    # point, which is what the bucket answers.
    "sacrifice_creature_for_mana": "activated_mana",
    # A conditional, and the same wrapper rule as `sequence` above. This
    # entry used to read `activated_mana` and justify itself by citing
    # `sequence`'s `activated_damage` — the two wrong entries in this table
    # held each other up. It was true of the Urza's cycle, whose guarded branch
    # produces mana, and false of the other half of its cards: Eater of the
    # Dead exiles, Land's Edge deals damage, Lesser Werewolf debuffs. A
    # condition is not an effect family.
    "if_then": "activated_conditional",
    # Tawnos's Coffin and Bronze Tablet both move objects out of the game and
    # decide later what becomes of them. Exile is where they go.
    "exile_until_leaves_or_untaps": "activated_recursion",
    "exchange_ownership_unless_paid": "activated_recursion",
    # --- Legends' activated abilities, added at its promotion ----------------
    # Same rule as the two blocks above: the bucket the *ability* belongs to,
    # named in the vocabulary the shipped pool already uses, rather than a
    # rendering of the instruction kind. Where an existing kind already answers
    # the question the new one asks, the new one takes that kind's label.
    #
    # A CR 122.1 counter put on the source (the five Mana Batteries' charge
    # counters, Triassic Egg's hatchling counter). `add_counter_to_self` above
    # is the +1/+1 twin and `add_named_counter_to_self` is already
    # `triggered_counter` on the other side.
    "add_named_counter_to_self": "activated_counter",
    # Ayesha Tanaka counters an ability on the stack. `activated_counter` is
    # taken — it means a +1/+1 counter — and `counter_top_stack_spell`'s
    # `spell_pattern` is the "nothing claimed this clause" marker rather than a
    # bucket, so the label is the grammar category's own word, pinned here so a
    # category rename cannot re-bucket the card.
    "counter_stack_ability": "activated_counterspells",
    # Giant Slug's "{5}: At the beginning of your next upkeep, …". The label
    # `engine/ability_lines.py` already reports for an activated ability that creates a
    # delayed trigger (CR 603.7); the grammar reads this one, so it takes the
    # same word rather than a second name for the same shape.
    "create_delayed_trigger": "activated_delayed_trigger",
    # Clergy of the Holy Nimbus, beside `deny_regeneration_to_target`.
    "deny_regeneration_to_self": "activated_deny_regeneration",
    # A player discards (Gwendlyn Di Corci at random, Nebuchadnezzar by named
    # card). The triggered side's word for the same event is `triggered_discard`
    # — the legacy `spell_pattern` on `discard_target_cards` above is the
    # unclaimed marker carried across the deletion, not a bucket to copy.
    "discard_x_target_cards": "activated_discard",
    "name_and_random_reveal": "activated_discard",
    # Volrath's Shapeshifter's own `{2}: Discard a card.`, and the CR 707.9a
    # copy of it the card grants itself. Beside the row above: the discarding
    # seat is the difference between them and not what the ability does, which
    # is the same reading `draw_target_cards` takes from `draw_controller_cards`
    # two rows down.
    "discard_controller_cards": "activated_discard",
    # Xira Arien, beside `draw_controller_cards`: a draw is a draw whoever does
    # it.
    "draw_target_cards": "activated_draw",
    # Gauntlets of Chaos swaps two permanents. `activated_steal` is the pool's
    # word for an ability whose point is who controls what.
    "exchange_control_of_targets": "activated_steal",
    # Knowledge Vault puts cards aside face down to be handed back later —
    # Tawnos's Coffin and Bronze Tablet's bucket above, for the same reason:
    # exile is where they go and the ability is about their coming back.
    "exile_top_of_library": "activated_recursion",
    # Al-abara's Carpet, beside `grant_prevention_shield`.
    "grant_source_class_prevention_shield": "activated_prevent",
    # North Star produces no mana; its whole effect is permission to spend what
    # you have as though it were another type (CR 609.4b). `activated_mana` is
    # for an ability whose point is that mana appears, so this takes Idol of
    # Endurance's `activated_permission` instead.
    "grant_spend_mana_as_though": "activated_permission",
    # Hyperion Blacksmith's "You may tap or untap …". The `may` wrapper says
    # nothing about what it wraps, exactly as `sequence` does not — and with no
    # trigger condition to name the moment, the honest label names the shape.
    # This was the one wrapper on this side that always got that right; the
    # triggered table reaches the same answer a different way, by letting the
    # *condition* name the moment (`TRIGGERED_LABELS_BY_CONDITION`).
    "may": "activated_optional",
    # Petra Sphinx: the top card is seen and then sorted. `activated_look` is
    # the bucket for an ability whose point is cards being looked at.
    "name_then_reveal_top": "activated_look",
    # Prevention, however the shield is spelled: a blanket over the combat
    # damage step (Angus Mackenzie), one creature's damage (Horn of Deafening,
    # Lady Evangela), or damage sent somewhere else instead (Shimian Night
    # Stalker — the bucket Jade Monolith's hook already declares).
    "prevent_all_combat_damage": "activated_prevent",
    # Its narrowed twin (Undergrowth with its additional cost paid) has **no**
    # row, and deliberately: these tables label an activated or a triggered
    # ability, and that kind is only ever produced by a *spell* — nothing
    # would reach a row for it, which is what the dead-entry guard says.
    "prevent_damage_by_target_until_eot": "activated_prevent",
    "prevent_damage_by_target_spell_until_eot": "activated_prevent",
    "redirect_damage_from_target_until_eot": "activated_prevent",
    # …and the counted twin, which moves a *pool of points* onto the
    # permanent whose ability it is (Daughter of Autumn, Hazduhr the Abbot).
    # The same bucket: what the ability is *for* is keeping damage off
    # something, and how much of the event it moves is payload. Without a
    # row here it falls back to `activated_<category>`, which for this
    # family is `activated_damage` — a label saying the ability deals damage
    # when it deals none.
    "redirect_next_damage_to_source_until_eot": "activated_prevent",
    "redirect_next_damage_from_source_until_eot": "activated_prevent",
    # Shaman en-Kor's second ability, and the same reason: what it is *for* is
    # keeping damage off the creature it named.
    "redirect_chosen_source_damage_off_target_until_eot": "activated_prevent",
    # Quarum Trench Gnomes changes what a land produces. The mana is the point,
    # which is what `activated_mana` answers.
    "produce_mana_instead": "activated_mana",
    # Tempest Efreet is Bronze Tablet's sibling — an ownership exchange with a
    # card that ends up somewhere it can be used again.
    "ante_or_exchange_ownership": "activated_recursion",
    "random_reveal_ownership_exchange": "activated_recursion",
    # Dream Coat recolours the creature its Aura is on. Antiquities'
    # `gain_type` settled the bucket: the report's word for a permanent
    # changing what it *is* is `activated_pump`, and a colour change is layer 5
    # beside that layer 4 one. (Alchor's Tomb's `recolor_target_chosen_color`
    # had this entry too until PCY W3G2 put the CR 608.2d colour question in
    # front of it: the ability is a `sequence` now, which names its shape.)
    "recolor_enchanted_chosen_color": "activated_pump",
    # Diamond Valley and Life Chisel. Life gain has no legacy bucket: the
    # spell table marks `target_gains_life` `spell_pattern` (unclaimed), and
    # the only life kind here is `target_loses_life`, which sits under
    # `activated_damage` because that is where a *loss* has always been
    # reported. A gain is not damage, so it gets its own word rather than
    # being filed under the opposite of itself.
    "target_gains_life": "activated_lifegain",
    # Mirror Universe. Deliberately not `activated_lifegain`: an exchange can
    # cost its controller life, and a bucket that says "gain" of an ability
    # that can halve your total is a report that misleads.
    "exchange_life_totals": "activated_life_exchange",
    # Losing a keyword until end of turn (Radjan Spirit, Shelkin Brownie,
    # Tolaria, Urborg) is `grant_target_keyword_until_eot` with a minus sign.
    "remove_target_keyword_until_eot": "activated_pump",
    # Sentinel, beside `set_base_pt_target_until_eot`.
    "set_source_base_pt_from_target": "activated_pump",
    # Every linked-duration steal: Aladdin's artifact, Merieke Ri Berit's and
    # Willow Satyr's creature, Orcish Squatters' land. One kind, because what
    # differs between them is which fact the sweep re-checks and that is
    # payload.
    "steal_target_linked_to_source": "activated_steal",
    # --- Ice Age's promotion -------------------------------------------------
    # Every kind below was written while ICE was a *measured* set, where this
    # guard could not see it: it reads `load_catalog()`, the shipped pool. The
    # labels feed `SimulationResult`, the support report's buckets and the
    # `triggered_` prefix `web/serialization.py` turns into `is_triggered`, so
    # a kind without one falls back to `activated_<category>` and silently
    # re-buckets its card. Promotion is where that debt comes due, by design.
    "change_supertype": "activated_characteristic",
    # Neurok Transmuter's "…isn't an artifact": the same layer-4 bucket.
    "lose_type": "activated_characteristic",
    "change_land_type_until": "activated_characteristic",
    "animate_target_until_eot": "activated_characteristic",
    "grant_self_ability_text": "activated_pump",
    # Its negative twin (Glittering Lion's "…loses "Prevent all damage …""),
    # in the bucket `remove_self_keyword` already shares with the grant.
    "remove_self_ability_text": "activated_pump",
    # Whipgrass Entangler (LGN): "{1}{W}: Until end of turn, target creature
    # gains "This creature can't attack or block unless its controller pays
    # {1} for each Cleric on the battlefield."" `grant_self_ability_text`
    # aimed at a target rather than the source, and its bucket: which
    # permanent gains the quoted ability is the target's business, not
    # another kind of ability.
    # (The category default already said `activated_pump`; named so the
    # bucket is the table's answer rather than the grammar family's.)
    "grant_target_ability_text": "activated_pump",
    # Quicksilver Elemental: the grant's abilities read off a target.
    "gain_activated_abilities_of_target": "activated_pump",
    "return_self_from_graveyard": "activated_return",
    "return_source_card_to_owners_hand": "activated_return",
    # "{W}: Return enchanted creature to its owner's hand" (Sun Clasp). The
    # same family as the source's own return above — a bounce is what the
    # ability does — with the Aura's host as the subject rather than the source.
    "return_attached_permanent_to_hand": "activated_return",
    "reorder_target_library_top": "activated_library",
    "look_top_exile_random": "activated_library",
    "reassign_blockers_between_attackers": "activated_combat",
    "redirect_source_class_damage_until_eot": "activated_prevention",
    # Soltari Guerrillas moves its **own** combat damage off an opponent and
    # onto a creature it targets. Same bucket for the same reason: what the
    # ability is for is where the damage lands, not that it deals any — the
    # fallback would label it `activated_damage`, which is the one thing this
    # ability never does.
    "redirect_source_damage_to_target_until_eot": "activated_prevention",
    # Pentagram of the Ages, and with a CR 615.5 rider as payload Cho-Arrim
    # Alchemist's life (Reverse Damage's sentence, one activation over) and
    # Bone Mask's exile — one bucket, because what each ability is for is the
    # prevention, and the sentence after it is what that prevention pays.
    "grant_whole_prevention_shield": "activated_prevention",
    "grant_chosen_source_blanket_shield": "activated_prevention",
    # --- Invasion, at its promotion ---------------------------------------
    # Urborg Phantom: "{U}: Prevent all combat damage that would be dealt to
    # and dealt by this creature this turn." The kind was triggered-only in
    # the shipped pool (its row is in `triggered_labels.TRIGGERED_LABELS`);
    # this is the first card to *activate* it, and it takes the bucket every
    # other activated shield in this block has.
    "prevent_damage_to_target_until_eot": "activated_prevention",
    # --- Fallen Empires' activated abilities, added at its promotion --------
    # Same rule as M21's block above: the bucket the *ability* belongs to, not
    # the one its instruction kind reads like — and where the kind is a
    # **wrapper**, the label names the shape, because a wrapper has no leaf to
    # name. `for_each` is the case that proves the rule rather than the one
    # that bends it: Heroism prevents combat damage and Tidal Flats grants
    # first strike, both through one `for_each`, so any leaf bucket would be
    # right about one card and wrong about the other. `sequence`,
    # `if_then` and `may` are already here for exactly that reason.
    "for_each": "activated_repeated",
    # Dwarven Armorer's "+0/+1 counter **or** a +1/+0 counter" is a choice
    # between alternatives, lowered onto the same `choose_one` the modal heads
    # use. The shape again: what the ability is for depends on which one is
    # taken. The bucket's word is older than the distinction — no activated
    # `choose_one` in the pool is modal in CR 700.2's sense (a printed modal
    # activated ability is rewritten one ability per bullet), and every one is
    # chosen at resolution (CR 608.2d, `modal_triggers.MODAL_HEAD_KEY`). The
    # label is kept so the support report's buckets do not move.
    "choose_one": "activated_modal",
    # Fungal Bloom. `add_named_counter_to_self` is already `activated_counter`
    # above, and the target twin is the same ability pointed elsewhere.
    "add_named_counter_to_target": "activated_counter",
    # Orcish Spy, beside `look_at_target_hand` above — the same ability about
    # a different hidden zone.
    "graveyard_top_to_library": "activated_look",
    "look_at_target_library_top": "activated_look",
    # Thelonite Druid's "Forests you control become 2/3 creatures until end of
    # turn. They're still lands", beside `animate_target_until_eot` and the two
    # type changes above: CR 205 is what a permanent *is*, which is the bucket
    # rather than the P/T it arrives with.
    "animate_matching_until_eot": "activated_characteristic",
    # Vodalian War Machine. A permission to attack (CR 508.1c) rather than a
    # characteristic change: the Wall keeps defender and the restriction is
    # lifted for the turn.
    "attack_as_though_no_defender_until_eot": "activated_combat",
    # --- Alliances ---------------------------------------------------------
    # Mishra's Groundbreaker, beside ``animate_target_until_eot`` above and for
    # its reason: CR 205 is what a permanent *is*, which is the bucket rather
    # than the P/T the animation arrives with. Its own entry because it is its
    # own instruction kind — the duration is what separates them.
    "animate_target_indefinitely": "activated_characteristic",
    # --- Alliances, at its promotion ----------------------------------------
    # Four kinds the grammar reads whose label was falling through to
    # ``activated_{grammar family}``. Declared for the reason the whole table
    # exists: the default is a fact about which `grammar/lowering/` module the
    # kind happens to sit in, so a family split — three of which this set took —
    # would silently re-bucket a shipped card in the support report.
    #
    # Ivory Gargoyle's self-exile takes ``exile_target_permanent``'s bucket
    # above: what the ability does is remove a permanent, and which permanent is
    # not the question the bucket answers.
    "exile_self": "activated_destruction",
    # Soldier of Fortune, beside ``reorder_target_library_top`` and
    # ``look_top_exile_random``: the library is the object.
    "shuffle_library": "activated_library",
    # Gustha's Scepter returning a card it exiled — a card changing zones, which
    # is the settled reading and also today's default; pinned so it stays that
    # after the next split rather than by luck.
    "put_exiled_with_source": "activated_zones",
    # Phantasmal Fiend's switch is a P/T change, which is the bucket every other
    # P/T kind reports; pinned for the same reason.
    "switch_self_pt_until_eot": "activated_pump",
    # --- Weatherlight, at its promotion -------------------------------------
    # Four kinds whose label was falling through to ``activated_{grammar
    # family}``, all four surfaced the moment `load_catalog()` widened. Settled
    # against a shipped neighbour rather than against the family the lowering
    # happens to sit in, which is the whole reason this table exists.
    #
    # Vodalian Illusionist phases out somebody else. ``phase_out_self`` and
    # ``phase_out_enchanted`` above both read `activated_recursion` — a
    # permanent leaving and coming back — and which permanent is not the
    # question the bucket answers.
    "phase_out_target": "activated_recursion",
    # Ertai's Familiar stops **itself** phasing out. ``forbid_phase_out`` above
    # is the same sentence aimed at another permanent and takes
    # `activated_restriction`; whose phasing is denied is not the question
    # either.
    "forbid_source_phase_out": "activated_restriction",
    # Llanowar Druid untaps a described set. ``tap_target_permanent`` and
    # ``skip_next_untap`` are both `activated_tapping`, and a sweep is not a
    # different act from a single tap — how many permanents is not the question.
    "untap_all_matching": "activated_tapping",
    # Dwarven Thaumaturgist switches somebody else's power and toughness.
    # ``switch_self_pt_until_eot`` directly above is the same act on its own
    # source and reads `activated_pump`, for the reason that entry states.
    "switch_target_pt_until_eot": "activated_pump",
    # --- Tempest, at its promotion ------------------------------------------
    # Seven kinds whose label was falling through to ``activated_{grammar
    # family}``, every one surfaced the moment `load_catalog()` widened. All
    # seven are this set's -- no earlier set's card reaches any of them -- and
    # each is settled against a shipped neighbour rather than against the family
    # its lowering happens to sit in, which is the whole reason this table
    # exists. ``activated_combat_restrictions`` is the tell: that bucket held
    # *nothing* but the two defaulted kinds below, so it was a grammar family
    # name leaking into the report's vocabulary rather than a word the support
    # report had ever bucketed by.
    #
    # Grindstone's "...repeat this process". A **wrapper** -- its payload
    # carries the mill it repeats -- so it cannot say what the ability is for,
    # only that the steps happen again. ``for_each`` is already
    # `activated_repeated` for exactly that reason, and this is the same shape
    # with the loop's bound read off a condition rather than off a count. Its
    # default was `activated_zones`, a **leaf** bucket
    # (``put_exiled_with_source`` holds it), which is the borrowing
    # `test_a_wrapper_kind_never_borrows_a_leaf_effects_bucket` forbids -- and
    # which that guard could not see, because it only reads kinds this table
    # already names.
    "repeat_process_while": "activated_repeated",
    # Jinxed Idol hands its own source to an opponent, and takes nothing.
    # Deliberately **not** `activated_steal`, for the reason
    # ``exchange_life_totals`` is not `activated_lifegain`: a bucket that says
    # "steal" of an ability whose whole effect is giving your own permanent away
    # is a report that misleads. `activated_control` was unavailable for a
    # second reason when this row was written -- ``unless_player_pays`` held it,
    # and is a *wrapper*, so filing a leaf there would have made that entry
    # borrow; the wrapper takes its shape's label now. The kind
    # arrived in this set's wave 2 for Starke of Rath's second sentence, where
    # it lowers inside a ``sequence``; Jinxed Idol is the card that reaches it
    # as a whole activated ability.
    "give_control_of_source_to_player": "activated_give_control",
    # Legacy's Allure, the other direction, and the settled word for it: Old Man
    # of the Sea's hook declares `activated_steal` for
    # ``steal_creature_while_tapped_and_weaker`` -- "gain control of target
    # creature with power less than or equal to ...", which is this card's
    # sentence with the bound read off counters instead of off power -- and
    # ``steal_target_linked_to_source`` is the same act with a linked duration.
    "gain_control_of_target": "activated_steal",
    # Mounted Archers may block one more creature than CR 509.1a allows;
    # Trumpeting Armodon imposes a blocking requirement (CR 509.1c). A
    # permission and a requirement, which is the pair
    # ``attack_as_though_no_defender_until_eot`` and
    # ``mark_non_wall_target_to_attack`` already are one declaration step over
    # -- and both of those read `activated_combat`, whose entry states the rule
    # these two follow: "the grammar family is combat_restrictions, and the
    # settled vocabulary is combat". Not `activated_restriction`, which
    # ``target_cant_block_until_eot`` holds for the *denial*: what these two
    # produce is a thing that may or must happen, not one that may not.
    "grant_additional_blocks_until_eot": "activated_combat",
    "force_target_to_block_until_eot": "activated_combat",
    # Phyrexian Grimoire empties two cards out of a graveyard, one to exile and
    # one to a hand. Both destinations are already `activated_recursion` --
    # ``exile_graveyard_position`` (Phyrexian Furnace) and
    # ``return_creature_from_graveyard_to_hand`` (Adun Oakenshield) -- and that
    # bucket's own note is why one row covers both: "what the ability is for is
    # that the graveyard stops holding it". Which of the two the opponent picks
    # is payload.
    "reveal_top_opponent_chooses": "activated_recursion",
    # Sacred Guide digs down its own library and exiles everything it passes.
    # Beside ``look_top_exile_random`` (Orcish Librarian), which is the same act
    # with the stopping point read off a count rather than off a colour: the
    # library is the object. Not `activated_search`, which is for a tutor
    # "chosen from a zone nobody sees" -- this one is revealed as it goes and
    # can whiff, and a deck with no white card left exiles itself.
    "reveal_until_match": "activated_library",
    # --- Exodus, at its promotion -----------------------------------------
    # Two kinds the promotion gate surfaced, which is the asymmetry
    # ``measured_grammar_abilities``' docstring explains: "no ability falls
    # back" reads the **shipped** pool, so a measured set's new kinds cannot
    # fire this guard until the entry moves.
    #
    # Thrull Surgeon looks at a hand and takes a card out of it. Beside
    # ``look_at_target_hand`` (Orcish Spy) rather than beside the discard
    # kinds, and settled by its own twin: ``reveal_hand_and_choose`` is already
    # ``triggered_look`` in the triggered table (``triggered_labels``), and the
    # two positions of one kind do not name two different things. The discard
    # is the tail of looking, not what the ability is for.
    "reveal_hand_and_choose": "activated_look",
    # Volrath's Dungeon puts a card from a hand on top of its owner's library,
    # beside the three ``put_*_on_library_top`` rows above. Their note is the
    # reason one bucket covers a fourth: which zone the card comes from is not
    # what the ability does, and the library is still the object it acts on.
    "put_hand_cards_on_library": "activated_library",
    # --- Mercadian Masques, at its promotion -----------------------------
    # Eleven kinds the set brought that take the grammar category's default
    # until they are named here. Each is settled against its **nearest existing
    # sibling** rather than against the family its lowering lives in, which is
    # this table's standing method: what the ability is *for* decides the
    # bucket, and the grammar family is the thing the default already answers.
    #
    # Cho-Arrim Alchemist's shield is Reverse Damage's, one activation over: a
    # source of your choice, the whole of its damage, and life for what was
    # prevented. Its own row here until the round that folded the riders into
    # `grant_whole_prevention_shield`'s payload; it takes that row's bucket now.
    # General's Regalia moves damage from a chosen source onto a creature. The
    # redirect family is split across two spellings of one bucket name and this
    # one takes `activated_prevent`, beside
    # `redirect_chosen_source_damage_off_target_until_eot` — same phrase, same
    # chosen source, opposite end.
    "redirect_damage_from_chosen_source_until_eot": "activated_prevent",
    # Credit Voucher puts cards from a hand into a library and draws that many;
    # Soothsaying reorders the top of its own. Both beside
    # `put_hand_cards_on_library` and `reorder_target_library_top`, whose note
    # is the reason one bucket covers them: which zone the cards come from is
    # not what the ability does, and the library is still the object it acts on.
    "shuffle_hand_cards_into_library": "activated_library",
    "reorder_own_library_top": "activated_library",
    # Whirlpool Warrior: "{R}, Sacrifice this creature: Each player shuffles
    # the cards from their hand into their library, then draws that many
    # cards." The whole-hand spelling of Credit Voucher's row two up, and in
    # its bucket for that row's reason: the library is the object it acts on.
    "shuffle_hand_into_library": "activated_library",
    # Rishadan Pawnshop shuffles a permanent into its owner's library — the
    # same destination, reached from the battlefield instead, and beside
    # `put_target_on_library_top` for that row's reason.
    "shuffle_target_permanent_into_library": "activated_library",
    # Crooked Scales' coin-flip toll loop, beside `repeat_process_while`.
    # **A wrapper, so it must not borrow a leaf bucket**: what it repeats is a
    # destroy, and labelling it `activated_destroy` is the borrowing
    # `test_a_wrapper_kind_never_borrows_a_leaf_effects_bucket` exists to
    # forbid — the repeat is what the ability is, the destroy is what it
    # repeats.
    "repeat_process_on_request": "activated_repeated",
    # Instigator compels an attack and Trap Runner makes an unblocked attacker
    # blocked. Both are the declaration itself rather than a restriction on
    # one, which is the line `force_target_to_block_until_eot` and
    # `reassign_blockers_between_attackers` already draw against
    # `target_cant_block_until_eot` below.
    "force_subject_to_attack_until_eot": "activated_combat",
    "become_blocked": "activated_combat",
    # War Tax and War Cadence price a declaration rather than making one, so
    # they take the other side of that same line, beside
    # `target_cant_block_until_eot`: the ability's whole effect is that a
    # declaration the rules would allow now costs something.
    "creatures_cant_attack_unless_pay_until_eot": "activated_restriction",
    "creatures_cant_block_unless_pay_until_eot": "activated_restriction",
    # Warmonger's sweep, and the one row here the fallback would have got
    # right — named anyway, because a kind that is only correct by accident of
    # which grammar family it lowered in is the debt this table exists to pay.
    "earthquake_damage": "activated_damage",
    # --- Nemesis, at its promotion ------------------------------------------
    # Four kinds the set put in the activated position for the first time,
    # each settled against a shipped neighbour rather than its grammar family.
    #
    # Netter en-Dal's "Target creature can't attack this turn." -- the attack
    # half of `target_cant_block_until_eot` above, and the same bucket.
    "target_cant_attack_until_eot": "activated_restriction",
    # Parallax Inhibitor puts a fade counter on each permanent with fading you
    # control, beside `add_counter_to_self`'s `activated_counter`: how many
    # objects receive the counter is not what the ability does.
    "add_counter_to_each_matching": "activated_counter",
    # Parallax Nexus: "Target opponent exiles a card from their hand." The
    # card leaves a hand its owner chose from -- hand disruption, which is
    # `name_and_random_reveal`'s and `discard_x_target_cards`' bucket, not
    # `activated_recursion`, which is for cards put aside to come back to
    # *their* controller (the Nexus hands them back, but to the player it
    # took them from, and the point of the ability is the taking).
    "exile_cards_from_hand": "activated_discard",
    # Divining Witch names a card and digs to it -- a tutor whose zone is
    # walked in the open rather than searched, so `name_then_reveal_top`'s
    # `activated_look` rather than `search_library`'s `activated_search`.
    "name_then_consult": "activated_look",
    # --- Odyssey, at its promotion ----------------------------------------
    # Four kinds five of the set's activated abilities reach, each of which
    # existed already and had only ever been a spell's or a trigger's. Settled
    # against a shipped neighbour, as Mirage's block at the top was:
    #
    # Aboshan, Cephalid Emperor: "{U}{U}{U}: Tap all creatures without
    # flying." The sweep of `tap_target_permanent`, and the mirror image of
    # `untap_all_matching` above -- how many permanents is not what the
    # ability does.
    "tap_all_matching": "activated_tapping",
    # Aven Windreader: "{1}{U}: Target player reveals the top card of their
    # library." A card is seen and stays where it was, which is
    # `look_at_target_library_top`'s bucket; that the table sees it too is
    # not a different thing to do.
    "reveal_top_of_library": "activated_look",
    # Crypt Creeper and Steamclaw: "Sacrifice this: Exile target card from a
    # graveyard." One card out of a pile by name, beside
    # `exile_graveyard_position` (one card off a named end) and
    # `exile_target_graveyard` (the whole zone): what the ability is for is
    # that the graveyard stops holding it.
    "exile_target_graveyard_card": "activated_recursion",
    # Pardic Miner: "Sacrifice this creature: Target player can't play lands
    # this turn." A thing its target may no longer do, which is the
    # restriction word wherever the thing denied happens to be -- a block, a
    # phasing, here a land play.
    "forbid_land_plays_this_turn": "activated_restriction",
    # Major Teroh (TOR): "{3}{W}{W}, Sacrifice Major Teroh: Exile all black
    # creatures." Named at Torment's promotion rehearsal, where it was the
    # first *activated* ability the grammar reads to produce this kind (every
    # shipped one is a trigger, `triggered_exile` in `triggered_labels`) and
    # so took the category default, `activated_zones`. Driven: the activation
    # sacrifices Teroh and exiles every black creature on both sides. It
    # removes permanents, which is ``exile_target_permanent``'s and
    # ``exile_self``'s bucket above — how many, and by which description, is
    # not the question the bucket answers.
    "exile_all_matching": "activated_destruction",
    # --- Onslaught, at its promotion rehearsal ---------------------------
    # Four kinds the set's activated abilities are the first to reach in the
    # activated position, each a leaf and each settled against a shipped
    # neighbour rather than its grammar family (the defaults were
    # `activated_zones`, `activated_characteristics`, `activated_destruction`
    # and `activated_zones`):
    #
    # Aven Soulgazer: "{2}{W}: Look at target face-down creature." A card is
    # seen by one player and stays where it was, which is
    # `look_at_target_hand`'s bucket; that the card is a face-down permanent
    # rather than a hand is where it is looked at, not what the ability does.
    "look_at_target_face_down": "activated_look",
    # Ixidor, Reality Sculptor: "{2}{U}: Turn target face-down creature face
    # up." The permanent becomes the card it is (CR 708.8) - every
    # characteristic at once - and the report's one word for a permanent
    # changing what it is, `gain_type`'s and the recolours', is
    # `activated_pump`.
    "turn_target_face_up": "activated_pump",
    # Wall of Deceit (LGN): "{3}: Turn this creature face down." The mirror
    # of Ixidor's row above, on the permanent itself: it stops being the card
    # it is and becomes the blank 2/2 (CR 708.2) — the same every-
    # characteristic change read the other way, so the same bucket. (The
    # category default was `activated_characteristics`, which would file the
    # two directions of one change under two words.)
    "turn_self_face_down": "activated_pump",
    # Nova Cleric: "{2}{W}, {T}, Sacrifice this creature: Destroy all
    # enchantments." The one-card-type sweep of
    # `destroy_all_artifacts_creatures_enchantments` above, and its bucket.
    "destroy_all_enchantments": "activated_destruction",
    # Rummaging Wizard: "{2}{U}: Surveil 1." Scry's twin with a graveyard for
    # the bottom (CR 701.25a), so scry's `activated_look`, as the triggered
    # table already files the upkeep surveil beside its scry.
    "surveil": "activated_look",
    # --- Scourge, at its promotion rehearsal -----------------------------
    # Thundercloud Elemental: "{3}{U}: All other creatures lose flying until
    # end of turn." Whiteout's sweep in the activated position for the first
    # time, and the bucket of its two neighbours here — the team grant it
    # mirrors and the one-target removal, `remove_target_keyword_until_eot` —
    # which is also what the `pump` category default already said, so the
    # row moves no label: it pins one.
    "remove_team_keyword_until_eot": "activated_pump",
    # --- Mirrodin, at its promotion rehearsal ----------------------------
    # Soul Foundry: "{X}, {T}: Create a token that's a copy of the exiled
    # card. X is the mana value of the exiled card." A token made, so
    # `create_token`'s bucket — the one the triggered table already files
    # `create_copy_token` under (`triggered_token`) — rather than the
    # `tokens` category's default.
    "create_copy_token": "activated_token",
}
