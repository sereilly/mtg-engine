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
    # for; life loss is not damage by the rules (CR 118.2) but is the same
    # bucket for a report about what an ability does to a player.
    "source_fights_target": "activated_damage",
    "source_bites_target": "activated_damage",
    "target_loses_life": "activated_damage",
    # Granting a keyword until end of turn, to the source, a target or the team.
    # `activated_pump` already holds the flying grants and the P/T setters, and
    # these are the same ability with a different word after "gains".
    "grant_self_keyword_until_eot": "activated_pump",
    "grant_target_keyword_until_eot": "activated_pump",
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
    "exile_target_graveyard": "activated_recursion",
    # "Until end of turn, you may cast …" (Idol of Endurance). Not any of the
    # above: nothing moves and nothing changes characteristics — the ability's
    # whole effect is a permission (CR 601.3).
    "grant_cast_permission": "activated_permission",
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
    # Xenic Poltergeist turns a noncreature into a creature; Mishra's Factory
    # turns itself into one. Both are the layer-4 type change the
    # `characteristics` category names, and the report's existing word for a
    # permanent changing what it is is `activated_pump` — the P/T comes with it
    # in both cases.
    "gain_type": "activated_pump",
    "animate_self_until_eot": "activated_pump",
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
    "redirect_damage_from_target_until_eot": "activated_prevent",
    # …and the counted twin, which moves a *pool of points* onto the
    # permanent whose ability it is (Daughter of Autumn, Hazduhr the Abbot).
    # The same bucket: what the ability is *for* is keeping damage off
    # something, and how much of the event it moves is payload. Without a
    # row here it falls back to `activated_<category>`, which for this
    # family is `activated_damage` — a label saying the ability deals damage
    # when it deals none.
    "redirect_next_damage_to_source_until_eot": "activated_prevent",
    # Quarum Trench Gnomes changes what a land produces. The mana is the point,
    # which is what `activated_mana` answers.
    "produce_mana_instead": "activated_mana",
    # Tempest Efreet is Bronze Tablet's sibling — an ownership exchange with a
    # card that ends up somewhere it can be used again.
    "ante_or_exchange_ownership": "activated_recursion",
    "random_reveal_ownership_exchange": "activated_recursion",
    # Alchor's Tomb changes a permanent's colour. Antiquities' `gain_type`
    # settled this: the report's word for a permanent changing what it *is* is
    # `activated_pump`, and a colour change is layer 5 beside that layer 4 one.
    "recolor_target_chosen_color": "activated_pump",
    # Dream Coat recolours the creature its Aura is on rather than a target.
    # Same layer-5 change, same bucket — the report's question is what the
    # ability *does*, and "which permanent" is the payload's business.
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
    "return_self_from_graveyard": "activated_return",
    "return_source_card_to_owners_hand": "activated_return",
    "reorder_target_library_top": "activated_library",
    "look_top_exile_random": "activated_library",
    "reassign_blockers_between_attackers": "activated_combat",
    "redirect_source_class_damage_until_eot": "activated_prevention",
    "grant_whole_prevention_shield": "activated_prevention",
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
    # between modes (CR 700.2), lowered onto the same `choose_one` the modal
    # spells use. The shape again: what the ability is for depends on which
    # mode is taken.
    "choose_one": "activated_modal",
    # Fungal Bloom. `add_named_counter_to_self` is already `activated_counter`
    # above, and the target twin is the same ability pointed elsewhere.
    "add_named_counter_to_target": "activated_counter",
    # Orcish Spy, beside `look_at_target_hand` above — the same ability about
    # a different hidden zone.
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
}

# Instruction kind -> label, for an ability the grammar reads in the **triggered**
# position (the clause after a trigger condition).
TRIGGERED_LABELS: dict[str, str] = {
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
    "buff_creatures_global": "triggered_pump",
    "copy_triggering_spell": "triggered_copy",
    "create_token": "triggered_token",
    "destroy_target_permanent": "triggered_destruction",
    "discard_then_draw_that_many": "triggered_draw",
    "draw_controller_cards": "triggered_draw",
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
    "pump_self": "triggered_pump",
    "pump_target_creature_until_eot": "triggered_pump",
    "tap_any_number_then_pump_self": "triggered_pump",
    # Looking at cards and choosing among them.
    "look_top_pick_to_hand": "triggered_look",
    "reveal_hand_and_choose": "triggered_look",
    "scry": "triggered_look",
    "mill_target_player": "triggered_mill",
    # Life loss is not damage by the rules (CR 118.2), but for a report about
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
    # Gabriel Angelfire's modal upkeep grant. `choose_one` is a wrapper and says
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
    # Aisling Leprechaun turns a blocker green — the colour change whose bucket
    # `recolor_target_chosen_color` settles on the activated side.
    "recolor_target_from_text": "triggered_pump",
    # Divine Intervention's countdown and Venarian Gold's sleep counter. Not
    # `upkeep_effect`: that label belongs to the pay-or-consequence upkeep
    # registry, and these are ordinary triggers that go on the stack, where the
    # prefix is read.
    "move_counter_from_self": "triggered_counter",
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
}

# The one instruction kind whose label depends on what triggered it: `may` wraps
# whatever the optional clause offers, so the wrapper says nothing about the
# effect. Verduran Enchantress's optional draw was labelled a draw; the
# pay-{1}-gain-1-life cycle (Crystal Rod and its four siblings, Soul Net) was
# never claimed by a rule at all and kept the `spell_pattern` marker.
TRIGGERED_LABELS_BY_CONDITION: dict[tuple[str, str], str] = {
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
    ("enters_battlefield", "may"): "triggered_etb",
    ("draws_card", "may"): "triggered_draw",
    ("end_step", "may"): "triggered_end_step",
    ("end_step_self", "may"): "triggered_end_step",
    ("main_phase_first", "may"): "triggered_main_phase",
    ("permanent_becomes_untapped", "may"): "triggered_untap",
    ("self_becomes_target", "may"): "triggered_targeted",
    # Riddleform, once its animation trigger compiled (round 137). The
    # condition is what says when; the wrapper still says nothing about
    # the optional clause behind it.
    ("you_cast_spell", "may"): "triggered_cast",
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
