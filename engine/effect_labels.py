"""The reporting label an ability's compiled instruction carries.

``effect_kind`` is a *label*, never dispatch. It reaches three places and no
others: ``SimulationResult.effect_kind`` (the string the duel scripts and the
per-card tests report a cast by), ``scripts/support_report.py``'s buckets, and
``StackItem.ability_effect_kind`` — whose ``triggered_`` prefix is what
``web/serialization.py`` serializes as a stack item's ``is_triggered``.

Its vocabulary was ``engine/parsing/``'s. Each string was named after the rule
that produced it (``activated_deny_regeneration`` because there was a rule
called that), and the compiler preferred the legacy label whenever a legacy rule
matched the same line the grammar had already read. Deleting the registry
without carrying the vocabulary would therefore have silently re-bucketed 57
cards — an activated regeneration reported ``activated_regeneration`` where it
had always said ``activated_regenerate``, and every trigger the grammar reads
losing the ``triggered_`` prefix that flag depends on.

So the vocabulary moves here, which is the move
``card_hooks.CardLine.effect_kind`` already made for the lines that became
name-keyed hooks: *"carried here so deleting the rule that produced it does not
silently re-bucket the card."* A hook supplies its own label and never consults
these tables; what they cover is the grammar's output.

**Both tables are held to the pool**, by ``tests/engine/test_effect_labels.py``:
every entry must still be reached by a card that compiles through the grammar,
and every such ability must take its label from an entry rather than the
fallback. A frozen list of strings nothing checks would rot into a description
of a pool that has moved on; this one fails when it stops describing the pool,
so it can be pruned and extended for cause rather than by guesswork.

The fallbacks below the tables are what a *new* card gets: an activated ability
is labelled by the grammar category its instruction lowered to, and a trigger
keeps the ``spell_pattern`` marker the compiler has always used when nothing
claimed the clause. A new entry is only needed when a card must keep a label the
category cannot produce.
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
    # (Scarwood Bandits). The offer is the control change's price, not an effect
    # of its own, so the ability reports what it *does* if the offer is declined.
    "unless_player_pays": "activated_control",
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
    # `engine/oracle.py` already reports for an activated ability that creates a
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
    # you have as though it were another type (CR 601.2g). `activated_mana` is
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
    "change_land_type_until": "activated_characteristic",
    "animate_target_until_eot": "activated_characteristic",
    "grant_self_ability_text": "activated_pump",
    # Its negative twin (Glittering Lion's "…loses "Prevent all damage …""),
    # in the bucket `remove_self_keyword` already shares with the grant.
    "remove_self_ability_text": "activated_pump",
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
    "grant_whole_prevention_shield": "activated_prevention",
    "grant_chosen_source_blanket_shield": "activated_prevention",
    "grant_exile_prevention_shield": "activated_prevention",
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
    # Vodalian War Machine. A permission to attack (CR 508.1a) rather than a
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
    # is a report that misleads. `activated_control` is unavailable for a second
    # reason worth recording -- ``unless_player_pays`` holds it and is a
    # *wrapper*, so filing a leaf there would make that entry borrow. The kind
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
    # ``triggered_look`` in the table below, and the two positions of one kind
    # do not name two different things. The discard is the tail of looking,
    # not what the ability is for.
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
    # prevented. It goes beside `grant_whole_prevention_shield`, the shield it
    # is a variant of.
    "grant_reverse_damage_shield": "activated_prevention",
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
}

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
    # contract of this table: the label feeds `SimulationResult`, the support
    # report's buckets, and the `triggered_` prefix the web layer turns into a
    # stack item's `is_triggered`.
    "if_then": "triggered_label",
    "remove_all_counters_from_matching": "triggered_counter",
    "search_library": "triggered_library",
    "pump_enchanted_creature": "triggered_pump",
    "untap_and_tap_matching": "triggered_tap",
    "phase_out_target": "triggered_phasing",
    "destroy_event_subject": "triggered_destruction",
    "exile_event_subject": "triggered_destruction",
    # No Quarter's two lines: the other half of the block pair, destroyed the
    # moment the pair is declared. Beside the block-pair pump and keyword rows
    # in this table and filed with the *destructions*, because the label is what
    # the ability does and not which referent it does it to.
    "destroy_block_pair_partner": "triggered_destruction",
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
    # The label is what the report and the web payload have always shown for it
    # — a triggered ability that creates something — so the card is not
    # re-bucketed by the change underneath it.
    "create_delayed_trigger": "triggered_token",
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
    "reveal_hand_and_choose": "triggered_look",
    "scry": "triggered_look",
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
    # or rampage 3" — a CR 608.2d choice, not a modal one; Elder Gargaroth and
    # Trufflesnout are the modal heads). `choose_one` is a wrapper and says
    # nothing by itself, but every mode of the one card that prints it grants a
    # keyword — so it takes the keyword-grant bucket, exactly as `if_then` takes
    # the bucket of the branch the Urza's cycle guards. A second card choosing
    # among something else splits this by condition.
    "choose_one": "triggered_pump",
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
    "add_named_counter_to_target": "triggered_counter",
    "prevent_damage_to_target_until_eot": "triggered_prevention",
    "exile_target_permanent": "triggered_exile",
    "exile_bound_card_from_graveyard": "triggered_exile",
    "unless_player_pays": "upkeep_effect",
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
    # twin already carries in the table above, which is this file's settled rule:
    # the bucket names what the ability does, and whether a player activated it
    # or an event announced it is not part of that question.
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
    # activated table above as `activated_combat` for Trumpeting Armodon: a
    # blocking requirement (CR 509.1c), and how many creatures it names is
    # payload rather than a different act.
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
}

# The one instruction kind whose label depends on what triggered it: `may` wraps
# whatever the optional clause offers, so the wrapper says nothing about the
# effect. Verduran Enchantress's optional draw was labelled a draw; the
# pay-{1}-gain-1-life cycle (Crystal Rod and its four siblings, Soul Net) was
# never claimed by a rule at all and kept the `spell_pattern` marker.
TRIGGERED_LABELS_BY_CONDITION: dict[tuple[str, str], str] = {
    # Bazaar of Wonders: "Whenever a player casts a spell, counter it if a card
    # with the same name is in a graveyard...". An `if_then` wrapper, so the
    # condition is the only half of the pair that says anything -- and what it
    # says is that this is a counterspell, which is the bucket Mana Vortex's
    # own cast trigger already takes below.
    # --- Mercadian Masques, at its promotion -----------------------------
    # Five `may` wrappers over three conditions, each taking the bucket the
    # condition's nearest neighbour already has. The set prints
    # "whenever this creature becomes blocked, you may …" four times
    # (Chambered Nautilus, Port Inspector, Saprazzan Heir — and Robber Fly's
    # sibling shape), which is `creature_blocks_or_blocked_by` one narrowing
    # over and takes its bucket.
    ("creature_becomes_blocked", "may"): "triggered_combat",
    # Saber Ants, beside `damage_dealt` above: being dealt damage is a combat
    # moment whatever dealt it.
    ("creature_dealt_damage", "may"): "triggered_combat",
    # Foster, beside `dies` and `attached_creature_dies`: whose creature died
    # narrows the trigger, not what the ability is about.
    ("creature_you_control_dies", "may"): "triggered_death",
    ("spell_cast", "if_then"): "triggered_counterspells",
    ("creature_dies", "may"): "spell_pattern",
    ("enchantment_cast", "may"): "triggered_draw",
    ("spell_cast", "may"): "spell_pattern",
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
    # Mana Vortex counters its own spell unless a land is sacrificed. The
    # condition is what makes this a cast trigger; the wrapper is silent.
    ("self_cast", "may"): "triggered_counterspells",
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
    # half of the pair that names the moment.
    ("opponent_casts_spell", "may"): "spell_pattern",
    ("creature_attacks", "may"): "spell_pattern",
    ("permanent_becomes_tapped", "may"): "spell_pattern",
    ("upkeep_self", "if_then"): "upkeep_effect",
    ("upkeep_self", "for_each"): "upkeep_effect",
    ("you_lose_life", "for_each"): "spell_pattern",
    ("end_step_enchanted_controller", "if_then"): "triggered_destruction",
    # --- Fallen Empires, at its promotion -----------------------------------
    # Goblin Flotilla's "At the beginning of each combat, unless you pay {R},
    # …", beside ("combat_your_turn", "may") and the other combat offers above.
    # The condition is the bare `combat`, which this set is also the reason
    # anything *announces* — it sat in both front-end tables with no fire site
    # until the wave gave it one.
    ("combat", "may"): "triggered_combat",
    # Thelon's Chant and Tourach's Chant: "Whenever a player puts a <land type>
    # onto the battlefield, this enchantment deals 3 damage to that player
    # unless they put a -1/-1 counter on a creature they control." The offer is
    # the damage's price, so the ability reports what it *does* when the offer
    # is declined — the same reading `unless_player_pays` takes for Scarwood
    # Bandits in the activated table above.
    ("matching_permanent_enters", "may"): "triggered_damage",
}


def activated_label(instruction_kind: str, category: str) -> str:
    """The label for *instruction_kind* read as an activated ability."""
    return ACTIVATED_LABELS.get(instruction_kind, f"activated_{category}")


def triggered_label(instruction_kind: str, condition_kind: str | None) -> str:
    """The label for *instruction_kind* read as a trigger's effect."""
    if condition_kind is not None:
        by_condition = TRIGGERED_LABELS_BY_CONDITION.get((condition_kind, instruction_kind))
        if by_condition is not None:
            return by_condition
    return TRIGGERED_LABELS.get(instruction_kind, "spell_pattern")


__all__ = [
    "ACTIVATED_LABELS",
    "TRIGGERED_LABELS",
    "TRIGGERED_LABELS_BY_CONDITION",
    "activated_label",
    "triggered_label",
]
