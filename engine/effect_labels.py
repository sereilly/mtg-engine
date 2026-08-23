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
    "grant_unblockable_to_low_power_target": "activated_evasion",
    "hurricane_damage": "activated_damage",
    "look_at_target_hand": "activated_look",
    "mill_target_player": "activated_mill",
    "pump_enchanted_creature": "activated_pump",
    "pump_self": "activated_pump",
    "pump_target_creature_until_eot": "activated_pump",
    "remove_counter_from_self": "activated_counters",
    # A composed effect (Orcish Artillery's "deals damage to X and damage to
    # you"). The label names what the ability is *for*, which is why it cannot
    # be read off the wrapper kind.
    "sequence": "activated_damage",
    "set_base_pt_target_until_eot": "activated_pump",
    "steal_target_permanent_linked_to_self": "activated_steal",
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
    # instruction kind reads like: a label answers "what is this ability for?",
    # which is why "sequence" above is `activated_damage`.
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
    # Evasion, beside `grant_unblockable_to_low_power_target`.
    "grant_unblockable_to_self": "activated_evasion",
    # Looking at cards and choosing among them. Scry is the paradigm case and
    # the look-and-pick (Waker of Waves) is the same question with a keep.
    "scry": "activated_look",
    "look_top_pick_to_hand": "activated_look",
    # Moving a card out of a graveyard. Three destinations, one bucket: what the
    # ability is for is that the graveyard stops holding it.
    "put_graveyard_card_on_library_bottom": "activated_recursion",
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
    # The Urza's cycle. Its assembled bonus is a conditional, and the branch it
    # guards produces mana — so the wrapper takes the bucket of what it does,
    # exactly as `sequence` above takes damage's.
    "if_then": "activated_mana",
    # Tawnos's Coffin and Bronze Tablet both move objects out of the game and
    # decide later what becomes of them. Exile is where they go.
    "exile_until_leaves_or_untaps": "activated_recursion",
    "exchange_ownership_unless_paid": "activated_recursion",
}

# Instruction kind -> label, for an ability the grammar reads in the **triggered**
# position (the clause after a trigger condition).
TRIGGERED_LABELS: dict[str, str] = {
    "add_corpse_counters_for_each_creature_died": "triggered_counter",
    "add_counter_to_self": "triggered_counter",
    # A CR 122.1 counter (Malefic Scythe, Armageddon Clock). The same
    # bucket as a +1/+1 one: the report asks what the ability is for.
    "add_named_counter_to_self": "triggered_counter",
    "add_mana_for_tapped_land": "spell_pattern",
    "add_plus1_counters_for_each_creature_died": "triggered_counter",
    "deal_damage": "spell_pattern",
    "deal_damage_equal_to_swamps": "upkeep_effect",
    "delayed_destroy_blocked_or_blocker": "triggered_delayed_destroy",
    "opponent_discards_random_card_on_damage": "triggered_discard",
    "sacrifice_self": "triggered_sacrifice",
    "self_damage_unless_pay": "triggered_damage",
    "target_gains_life": "spell_pattern",
    "upkeep_chosen_player_hand_overflow_damage": "upkeep_effect",
    "upkeep_pay_or_deal_damage_to_controller": "upkeep_effect",
    "upkeep_pay_or_sacrifice_enchantment": "upkeep_effect",
    "upkeep_pay_or_sacrifice_self": "upkeep_effect",
    "upkeep_pay_to_untap_self": "upkeep_effect",
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
    # Battering Ram's banding, added at Antiquities' promotion. A keyword
    # granted until end of combat is the same bucket the activated table gives
    # one granted until end of turn.
    "grant_self_keyword_until_eot": "triggered_pump",
    # A keyword granted until end of turn is what `activated_pump` holds on the
    # other side; same ability, other position.
    "grant_self_flying_until_eot": "triggered_pump",
    "grant_target_flying_until_eot": "triggered_pump",
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
