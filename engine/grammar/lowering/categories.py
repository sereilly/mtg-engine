"""Which migration category each lowered instruction kind belongs to.

One table, in its own module because it is a *registry* rather than logic: the
gate in `engine/grammar/__init__.py` turns categories on one at a time, and an
instruction whose kind is missing here can be lowered but never gated on.

`GRAMMAR_CATEGORIES` is held equal to the set of values here by
`tests/engine/test_grammar_categories.py`. With no fallback underneath the
grammar, a category left off does not route its lines elsewhere — it costs
those cards their support, which is why the equality is a test and not a
convention.

**And ``categories_of`` left the same way, one set later.** This module is a
registry, which is what its first paragraph claims and what the split above
established; a walk over a lowered sequence is not one, and it belongs beside
the wrapper table it has to consult on every step
(``lowering/control_flow.nested_instructions``). Its address is unchanged —
``lowering/__init__`` and ``lower.py`` both re-export it — which is the same
promise this file's own move made about ``INSTRUCTION_CATEGORIES``.

**And which kinds are *zone changes* is `lowering/zones.py`'s**, for the same
reason and by the same move — the third time this table has been split at the
thousand-line guard, and the first time it crossed at *integration* rather than
on a branch. Five wave branches each added a handful of rows to Visions'
wave 1; no group crossed the line and the sum did, which is the case the size
guard is documented to catch late and the case that makes the seam hardest to
find. It was found anyway, because the line was already drawn in prose one
module over: a zone change names **two** zones, the one an object leaves and the
one it goes to, and that pair is what picks the handler, where every kind left
here acts on an object where it stands. 121 rows of 380, the largest category by
a factor of three.

**Which kinds are wrappers is `lowering/control_flow.py`'s**, not this module's.
The table used to sit at the bottom of this file, and the split came at the
thousand-line guard: the half that grows with the pool is the registry above,
and the half that has been stable is the walk over `sequence` / `if_then` /
`for_each` — which are exactly the kinds that family *produces*. Reusing the
family name rather than inventing a module for the walk is the same move
`by_node` recorded at Fallen Empires: the table is a registry either way, and
what a wrapper carries belongs beside what builds one.
"""

from ...lord_buffs import (LORD_BUFF_KIND)
from ...enter_tapped_statics import ENTER_TAPPED_STATIC_KIND
from ...land_animation import LAND_ANIMATION_KIND
from ...land_types import STATIC_LAND_TYPE_KIND, STATIC_SUPERTYPE_REMOVAL_KIND
from .control_changes import BID_LIFE_FOR_CONTROL_KIND
from .zones import ZONE_INSTRUCTION_CATEGORIES
INSTRUCTION_CATEGORIES: dict[str, str] = {
    "deal_damage": "damage",
    # "If the creature deals damage to a creature this turn, the creature
    # dealt damage can't be regenerated this turn." (Runesword.) It deals no
    # damage; it says what damage dealt later will do. Same family, because
    # what the sentence is *about* is a damage event.
    "grant_damage_riders_until_eot": "damage",
    "earthquake_damage": "damage",
    "hurricane_damage": "damage",
    "deal_damage_each_creature_and_player": "damage",
    "deal_damage_each_attacking_creature": "damage",
    # "…deals 1 damage to each Goblin creature." (Goblin Shrine); "…deals 2
    # damage to **each creature you control**" (Sorrow's Path). The
    # generalisation of the row above: the described set is payload, so a card
    # printing any other noun phrase needs no kind of its own. Two parallel
    # branches landed this twice under two names in one round — a filtered
    # sweep is the shape everyone reaches for — and the survivor is the one
    # that batches, so simultaneous lethal damage kills together.
    "deal_damage_each_matching": "damage",
    # "…to each opponent and planeswalker **it has dealt damage to this
    # game**" (The Fallen). The recipients are a record on the source rather
    # than a set on a board. Same category, so GRAMMAR_CATEGORIES is unchanged.
    "deal_damage_to_those_damaged_this_game": "damage",
    # Mana Clash's coin-flip loop (CR 705). The randomiser is control flow, but
    # what the paragraph *does* is deal damage, which is what this table names.
    "coin_flip_damage_loop": "damage",
    "deal_damage_to_recorded_permanents": "damage",
    "deal_damage_and_opponent_choice": "damage",
    # Soul Echo. In the damage category because what the sentence is about is a
    # damage event — the counters are the substitution, not the subject.
    "arm_damage_to_counter_removal": "damage",
    "self_damage_unless_pay": "damage",
    # Dispatched by the (trigger condition, instruction kind) registry in
    # engine/phases/upkeep_effects.py rather than by EFFECT_HANDLERS, so they
    # share the category of the other upkeep pay-or-else shapes.
    "upkeep_pay_or_deal_damage_to_controller": "upkeep",
    "upkeep_chosen_player_hand_overflow_damage": "upkeep",
    "deal_damage_equal_to_swamps": "upkeep",
    "pump_target_creature_until_eot": "pump",
    "pump_target_while_source_tapped": "pump",
    "sacrifice_expansion_permanents": "destruction",
    "gain_type": "characteristics",
    "change_supertype": "characteristics",
    # "Target land becomes a Swamp until its controller's next untap step."
    # (Orcish Farmer.) CR 305.7 replaces the land's subtypes, which is the
    # same layer-4 question the two above ask about a card type and a
    # supertype — so the same category, with the land type as payload.
    "change_land_type_until": "characteristics",
    # "Choose a land type and a basic land type. Each land of the first
    # chosen type becomes the second chosen type until end of turn."
    # (Vision Charm.) The same CR 305.7 replacement over a set the *answer*
    # names rather than one the sentence does, so the same family.
    "swap_land_types_until_eot": "characteristics",
    "restrict_untap_while_source_tapped": "tapping",
    # Its counter-conditioned sibling: "…doesn't untap during its controller's
    # untap step **for as long as it has a paralyzation counter on it**"
    # (Dread Wight). The condition is a fact about the restricted permanent
    # rather than about the source, so the two are different restrictions with
    # the same category.
    "restrict_untap_while_counter": "tapping",
    "arm_self_action_at_next_end_step": "destruction",
    # "…**Exile it** at the beginning of the next end step." (Zirilan of
    # the Claw, Shallow Grave.) Beside the two bound removals it is a
    # sibling of rather than with the exile family: what decides the handler
    # is that the object is bound, not that the move is an exile.
    "exile_bound_permanent": "destruction",
    "add_power_counters_to_self": "counters",
    # One pump per chosen slot, each with its own P/T delta (Rookie Mistake).
    # The same category as the one-target pump above: what differs is how many
    # targets the sentence names, not what the effect is.
    "pump_targets_until_eot": "pump",
    "pump_self": "pump",
    "pump_enchanted_creature": "pump",
    "buff_creatures_global": "pump",
    # A permanent's continuous anthem/lord buff. Its own category rather than
    # "pump": that one is a one-shot boost with a duration, and these two
    # readings of the same printed sentence answer to different rules
    # (CR 611.2c vs 611.3a). Sharing a switch would tie them together.
    LORD_BUFF_KIND: "static_buffs",
    # The self-conditional twin of the anthem above ("This creature gets +1/+1
    # as long as an opponent controls a nontoken white permanent") — the same
    # layer-7c/layer-6 contribution with the source as its own subject.
    "conditional_static": "static_buffs",
    # A permanent's continuous bonus **to itself**, sized by a computation
    # (Carrion Grub). The same category as the anthem above and for the same
    # reason: it is a CR 613 layer 7c contribution the P/T refresh rebuilds,
    # not a one-shot pump with a duration. Who it applies to — the whole board
    # or the source alone — is not what the category is about.
    "dynamic_pt_bonus": "static_buffs",
    # A permanent's board-wide static effect on *lands* (CR 613 layer 4):
    # Kormus Bell animating every Swamp, Conversion turning every Mountain into
    # a Plains. Their own category rather than "static_buffs" because the two
    # answer to different layers and to different consumers —
    # `_refresh_dynamic_creatures` and `_recalculate_derived_land_types` — so
    # one switch would tie two migrations together.
    LAND_ANIMATION_KIND: "land_statics",
    STATIC_LAND_TYPE_KIND: "land_statics",
    STATIC_SUPERTYPE_REMOVAL_KIND: "land_statics",
    # A permanent's board-wide replacement of how *other* permanents enter
    # (CR 614.1c, Kismet). Its own category rather than either of the two
    # above: nothing about it is a P/T contribution or a land, and the
    # consumer is the entry seam rather than a continuous recompute.
    ENTER_TAPPED_STATIC_KIND: "enter_statics",
    "set_base_pt_target_until_eot": "pump",
    # "…becomes a 3/3 Sphinx creature … until end of turn" (Riddleform).
    # The "pump" family, because what the sentence does is set a P/T — the
    # type change beside it is the layer bridge reading the same record.
    "animate_self_until_eot": "pump",
    # "Target snow land becomes a 2/2 creature until end of turn." (Balduvian
    # Conjurer.) The same record on a permanent the sentence names rather than
    # on the source, so the same category: what differs is which permanent
    # holds it, not what the sentence does.
    "animate_target_until_eot": "pump",
    # "Target land becomes a 3/3 artifact creature that's still a land. (This
    # effect lasts indefinitely.)" (Mishra's Groundbreaker.) The same record on
    # the same permanent with no end to it (CR 611.2b), so the same category:
    # what differs is the duration, not what the sentence does.
    "animate_target_indefinitely": "pump",
    # "Forests you control become 2/3 creatures until end of turn." (Thelonite
    # Druid.) The same record again, over every permanent a noun phrase
    # describes rather than over one the sentence named — so the same category
    # for the same reason.
    "animate_matching_until_eot": "pump",
    "set_team_base_pt_until_eot": "pump",
    # The CR 613.4b rewrite template (Sentinel, Wall of Tombstones, Halfdane,
    # Brine Hag). The same category as the setters above: a one-shot layer-7b
    # write, however its value is computed and however long it lasts.
    "set_source_base_pt_from_target": "pump",
    "set_source_base_toughness_from_count": "pump",
    "set_source_base_pt_from_target_until_next_upkeep": "pump",
    "set_base_pt_of_creatures_that_damaged_source": "pump",
    "grant_target_flying_until_eot": "pump",
    "grant_self_flying_until_eot": "pump",
    "grant_target_keyword_until_eot": "pump",
    # The quoted-text grants (Life Matrix): the same layer-6 family, carrying a
    # whole printed ability instead of a word.
    "grant_target_ability_text": "pump",
    "grant_self_ability_text": "pump",
    # The negative twin ("It loses indestructible until end of turn", Soul Sear).
    "remove_target_keyword_until_eot": "pump",
    # The same removal aimed at the object the *trigger's event* was about
    # ("Whenever a creature attacks you, it loses flanking until end of
    # turn", Barbed Foliage). One family, because what differs is which
    # object the words name and that is the payload.
    "remove_event_subject_keyword": "pump",
    # The board-wide negative twin ("All creatures lose flying until end of
    # turn", Whiteout), beside `grant_team_keyword_until_eot`.
    "remove_team_keyword_until_eot": "pump",
    # The durationless half of the same effect, on the ability's own source
    # (Elder Land Wurm). Same family: what changes is how long the removal
    # lasts, not what kind of effect it is.
    "remove_self_keyword": "pump",
    "grant_self_keyword_until_eot": "pump",
    "grant_enchanted_keyword_until_eot": "pump",
    "grant_banding_to_target": "pump",
    "add_named_counter_to_self": "pump",
    "add_named_counter_to_target": "pump",
    "add_counter_to_self": "pump",
    "add_counter_to_target": "pump",
    # Giant Oyster's draw-step drip. The bound-object twin of the row above,
    # in the same category because it is the same effect about an object the
    # creating ability named rather than one the picker offers.
    "add_counter_to_bound_permanent": "pump",
    "double_target_power_until_eot": "pump",
    # CR 613.4d layer 7d. "pump" because the switch is the same
    # question the pump category answers — what this permanent's
    # power and toughness are — and a category of its own would be a
    # switch that could gate half of layer 7 off without the rest.
    "switch_target_pt_until_eot": "pump",
    "switch_self_pt_until_eot": "pump",
    # "…can attack this turn as though it didn't have defender" (Wall of
    # Wonder). CR 609.4 — a permission, not a characteristic change, but it is
    # printed as the tail of the same sentence as the pump and a category of
    # its own would let one half of one sentence be gated off without the
    # other.
    "attack_as_though_no_defender_until_eot": "pump",
    "add_counter_to_each_matching": "pump",
    # Counter placements sized by a board count. Their own category rather than
    # "pump": a corpse counter never touches power or toughness (it is
    # regeneration fuel), so gating it behind the pump switch would tie two
    # unrelated migrations together. Keeping it out of the differential's
    # MIGRATED_CATEGORIES also means these two lines stay compared against the
    # legacy rules for as long as those rules exist.
    "add_corpse_counters_for_each_creature_died": "counters",
    "add_plus1_counters_for_each_creature_died": "counters",
    # A counter on a *player* (CR 122.1f poison) — the store is a seat field
    # rather than permanent metadata, but what the sentence does is place a
    # counter, which is what the category is about.
    "player_gets_poison_counters": "counters",
    # Afiya Grove. In the counter category and not in ``pump``, where the
    # placement half lives: what the sentence does is take a counter off one
    # object and put it on another, and CR 121.6 makes that one action.
    "move_counter_from_self": "counters",
    "remove_counter_from_self": "counters",
    "remove_all_counters_from_self": "counters",
    # Corrosion: the sweep spelling of the row above, over a described set
    # rather than one permanent. Same category, so GRAMMAR_CATEGORIES is
    # unchanged.
    "remove_all_counters_from_matching": "counters",
    # Giant Oyster's release. The bound-object twin of the row above — same
    # effect, and the object is the one the creating ability bound rather
    # than the ability's own source.
    "remove_all_counters_from_bound": "counters",
    "remove_counters_from_bound": "counters",
    # A counter on a **player** (CR 122.1f poison) coming off, the mirror of
    # ``player_gets_poison_counters`` above it. Same category: the store differs
    # and the question does not.
    "remove_all_counters_from_target_player": "counters",
    "remove_any_number_of_counters_from_self": "counters",
    # Pestilent Haze's second mode: loyalty stripped from every walker at once.
    "remove_loyalty_from_each_planeswalker": "counters",
    "add_pt_counters_to_attached": "counters",
    # Its named-counter twin ("…put X sleep counters on it", Venarian Gold).
    "add_named_counter_to_attached": "counters",
    # The same marker on a set named by a combat relation to the source
    # ("…on each creature blocking or blocked by this creature", Dread Wight).
    "add_named_counter_to_creatures_in_combat_with_source": "counters",
    # Its removal ("remove a sleep counter from that creature", Venarian
    # Gold), fired by the upkeep registry.
    "remove_counter_from_attached": "counters",
    "target_gains_life": "life",
    # "That player's life total becomes 20." (Rebirth.) CR 119.5 makes it a
    # gain or a loss of the difference, so it is the life family — the
    # printed number being the result rather than the delta is a fact about
    # the handler, not about which switch gates the card.
    "set_life_total": "life",
    "exchange_life_totals": "life",
    # The ante zone (CR 407). Its own category rather than "zones": every
    # other member of that family moves an object between zones the ordinary
    # game has, and this one is inert outside the ante variant.
    "ante_top_card": "ante",
    "target_loses_life": "life",
    # "Pay 4 life." (Sylvan Library.) CR 119.4 makes paying life a loss of
    # that life, so the family is the same one; what it is not is the same
    # *kind* — see ``lowering/game._lower_pay_life``.
    "pay_life": "life",
    "destroy_target_permanent": "destruction",
    "destroy_all_artifacts": "destruction",
    "destroy_all_creatures": "destruction",
    "destroy_all_enchantments": "destruction",
    "destroy_all_lands": "destruction",
    "destroy_all_lands_of_type": "destruction",
    "destroy_all_matching": "destruction",
    # "Destroy all creatures blocking or blocked by this creature."
    # (Abu Ja'far on a dies trigger, Kjeldoran Frostbeast on an
    # end-of-combat one.) A sweep whose scope is a combat relation the
    # matcher cannot answer, so it is its own kind rather than a
    # narrowing of `destroy_all_matching` — but the same family.
    "destroy_creatures_in_combat_with_source": "destruction",
    "destroy_each_unless_life_paid": "destruction",
    "destroy_attached_permanent": "destruction",
    # "…destroy **that creature**" inside a delayed ability (War Barge):
    # the object the creating ability bound, by id, rather than a pick.
    "destroy_bound_permanent": "destruction",
    # Suleiman's Legacy: the object the trigger's own event was about, which the
    # fire site froze — no pick, so it is not the targeted destroy. Same
    # category, so GRAMMAR_CATEGORIES is unchanged.
    "destroy_event_subject": "destruction",
    # "…destroy **that non-Wall creature**" (Acidic Dagger): the same
    # destroy at the other end of the event, on the creature the entry was
    # bound to having damaged rather than on the entry's own object.
    "destroy_delayed_agent": "destruction",
    # Its sacrifice twin (Phantasmal Mount). CR 701.21a, not CR 701.7 — a
    # sacrifice is not a destruction and no replacement may stop it — so it is
    # its own kind with its own handler, in the family that owns the verb.
    "sacrifice_bound_permanent": "destruction",
    # "That player chooses and sacrifices one of those creatures."
    # (Retribution.) The sacrifice acting on a permanent a ``choose_permanent``
    # step recorded, beside the one acting on a permanent a trigger bound.
    "sacrifice_recorded_permanent": "destruction",
    "destroy_self": "destruction",
    "destroy_all_artifacts_creatures_enchantments": "destruction",
    "delayed_destroy_blocked_or_blocker": "destruction",
    "tap_target_permanent": "tapping",
    # CR 701.3's attach, reached through CR 702.6a's equip. Its own category:
    # moving an Equipment onto a creature is neither a tap nor a zone change,
    # and sharing a switch with either would let one be gated off by the other.
    "attach_source_to_target": "attachments",
    # "…to **another permanent of that type**" (Enchantment Alteration): the
    # permanent the controller picks as the spell resolves, recorded for the
    # attach behind it. The same category, so GRAMMAR_CATEGORIES is unchanged —
    # the choice is one step of the attachment sentence, and gating it apart
    # from the attach would leave the card half-lowered.
    "choose_permanent": "attachments",
    # "…**chooses up to two Plains**" (Raiding Party): the plural of the pick
    # above, in the same category for the same reason — it is one step of the
    # sentence around it, and gating it apart would leave that sentence half
    # lowered. The family is the pick's, not the Plains': what this instruction
    # does is choose.
    "choose_permanents": "attachments",
    "tap_self": "tapping",
    "untap_target_permanent": "tapping",
    "untap_target_land": "tapping",
    # "Untap up to four lands." (Rewind) — the controller picks the lands on
    # resolution through the pending-choice queue; no "target" is printed.
    "untap_up_to_matching": "tapping",
    # "Tap any number of untapped creatures you control. This creature gets
    # +1/+1 … for each creature tapped this way." (Siege Striker.) The tapping
    # family rather than "pump": the pick is the effect and the boost is sized by
    # it, so gating it behind the pump switch would tie two migrations together.
    "tap_any_number_then_pump_self": "tapping",
    # "Each player may tap any number of untapped white creatures they
    # control." (Raiding Party.) The unfused half of the same pick: the offer
    # and the ceiling collapse into one prompt per seat, and what the taps buy
    # is a separate sentence rather than a boost this instruction could apply.
    "tap_any_number_matching": "tapping",
    "untap_self": "tapping",
    "untap_enchanted_creature": "tapping",
    # The enchanted untap's tap twin (Paralyze's enter-tap), and the
    # non-targeted sweep pair over a described set ("Untap all lands you
    # control", Reset; "tap all legendary creatures", Arena of the Ancients).
    "tap_enchanted_creature": "tapping",
    "tap_all_matching": "tapping",
    # "Tap all creatures blocking target attacking creature." (Feint.) A sweep
    # over a set named by a combat relation to the spell's own target.
    "tap_creatures_blocking_target": "tapping",
    # "…and tap **those creatures**." (Dread Wight.) Neither a sweep nor a
    # choice: the set is what an earlier step of the same effect recorded.
    "tap_recorded_permanents": "tapping",
    "untap_all_matching": "tapping",
    # Sands of Time's one-instruction inversion: "simultaneously untaps … and
    # taps …", where two sweeps in order would tap the whole board. Same
    # category, so GRAMMAR_CATEGORIES is unchanged.
    "untap_and_tap_matching": "tapping",
    "grant_prevention_shield": "prevention",
    # "…prevent half that damage, rounded down" (Dark Sphere) — a CR 615.8
    # whole-instance shield that absorbs a share of the event. Same category, so
    # GRAMMAR_CATEGORIES is unchanged.
    "upkeep_damage_unless_cost": "damage",
    "grant_half_prevention_shield": "prevention",
    "grant_whole_prevention_shield": "prevention",
    # Honorable Passage: the same any-target shield with CR 615.5's
    # sentence after it. The rider deals damage, and the category is
    # still "prevention" — the category names what the *line* is, and
    # this line is a shield whose interceptor answers back.
    "grant_reflecting_prevention_shield": "prevention",
    # CR 615.5's additional effect: the same absorption with a sentence
    # after it. `grant_reverse_damage_shield` reached the engine through a
    # name-keyed hook until Mirage printed a second rider on the same
    # sentence, which is what made it a production; it is declared here now
    # because the grammar emits it.
    "grant_reverse_damage_shield": "prevention",
    "grant_exile_prevention_shield": "prevention",
    "grant_team_prevention_shield": "prevention",
    "prevent_all_combat_damage": "prevention",
    # The same blanket, narrowed to a printed noun phrase (Pack Leader). Same
    # category: what differs is who it covers, not what kind of effect it is.
    "prevent_all_combat_damage_to_matching": "prevention",
    "prevent_all_combat_damage_except_from": "prevention",
    "prevent_damage_by_target_until_eot": "prevention",
    "prevent_damage_to_target_until_eot": "prevention",
    # The negation of both families (Whippoorwill): no shield and no redirect
    # may touch the marked creature's damage. Filed with prevention because
    # that is the machinery it switches off, and GRAMMAR_CATEGORIES is
    # unchanged.
    "lock_damage_to_target": "prevention",
    "grant_source_class_prevention_shield": "prevention",
    "prevent_damage_from_targeting_sources_until_eot": "prevention",
    # A redirect is *not* a prevention (CR 614.9): the damage is still
    # dealt, by the same source, to somebody else. Categorised with the
    # damage it moves rather than with the shields it sits beside in the
    # contention set.
    "redirect_damage_from_target_until_eot": "damage",
    "redirect_damage_from_chosen_source_until_eot": "damage",
    "redirect_damage_from_target_spell_until_eot": "damage",
    # "…it deals **double** that damage to that creature instead" (Blind
    # Fury). The third half of a damage event a CR 614 replacement can
    # change, beside the recipient above and the prevention elsewhere:
    # categorised with the damage it multiplies.
    "double_combat_damage_until_eot": "damage",
    # The class-scoped, optional one (Blood of the Martyr). Same category
    # for the same reason: what it moves is damage, and being optional and
    # being about a class are payload differences.
    "redirect_matching_damage_to_you_until_eot": "damage",
    # "…by <printed noun phrase>" rather than by one chosen object
    # (Kjeldoran Royal Guard): the class is re-asked of each source when
    # the damage would be dealt, so it is a different record and a
    # different handler, in the same family.
    "redirect_source_class_damage_until_eot": "damage",
    # "**The next N** damage that would be dealt to target <noun> this turn"
    # (Daughter of Autumn, Hazduhr the Abbot). A point pool rather than the
    # whole event, and a chosen recipient rather than the controller — both
    # payload differences over one family, so the same category.
    "redirect_next_damage_to_source_until_eot": "damage",
    # Zhalfirin Crusader: the same sentence with its two ends swapped.
    "redirect_next_damage_from_source_until_eot": "damage",
    "recolor_target_from_text": "recolor",
    # The same layer-5 colour change with a duration and several targets
    # (Dwarven Song and its four siblings). Same category: what differs is how
    # long it lasts and how many it names, not what it does.
    "recolor_targets_until_eot": "recolor",
    # "{2}: This creature becomes colorless until end of turn." (Raging
    # Spirit.) The source-subject twin of the row above.
    "recolor_self_until_eot": "recolor",
    # "…becomes the color of your choice" — the colour arrives with the answer
    # rather than with the text (CR 609.3), which is a payload difference and
    # not a category one.
    "recolor_target_chosen_color": "recolor",
    # Dream Coat: the same effect on an Aura's own host rather than on a
    # target, and on the set of colours the card offers rather than one.
    "recolor_enchanted_chosen_color": "recolor",
    "recolor_self_chosen_color": "recolor",
    # CR 701.12b, an atomic swap of two layer-2 contributions.
    "exchange_control_of_targets": "control",
    "exchange_control_of_bound": "control",
    # A printed text change (CR 612). Its own category rather than "recolor":
    # the Lace cycle makes an object a colour, while this replaces a *word*
    # wherever the object's text uses it, and one of the two modes does not
    # touch colour at all.
    "mark_text_modified": "text_change",
    "gain_control_of_target": "control",
    "gain_control_until_eot": "control",
    # An auction for one permanent's control (Illicit Auction). The same
    # category as the steals above, because where the permanent ends up is
    # what the sentence is about — the bidding is how the seat is chosen, not
    # a second thing the card does.
    BID_LIFE_FOR_CONTROL_KIND: "control",
    # "Target opponent gains control of this creature." (Chaos Lord.) The same
    # family read from the other end — the permanent hands itself over rather
    # than taking something — so the same category.
    "give_control_of_source_to_player": "control",
    # The monitored linked durations (CR 611.2b): "for as long as you control
    # this creature and this creature remains tapped" (Willow Satyr, Rubinia
    # Soulsinger) and The Wretched's end-of-combat blocker steal. The
    # conditions are payload; the state-based sweep ends them.
    "steal_target_linked_to_source": "control",
    "steal_blockers_of_source": "control",
    # CR 702.24a's own kind, reached from the grammar as well as from the
    # keyword rewrite: Phantasmal Sphere prints the ability longhand with a
    # +1/+1 counter where the keyword says "age". Without a row here the
    # lowering was `__ungated__` — an instruction produced and then discarded,
    # which reads as a card the grammar cannot parse.
    # "You skip your next draw step." (Ivory Gargoyle.) CR 500.7's skip, which
    # is a change to the turn's structure rather than to the board — the family
    # `grant_extra_turn` is already in.
    "skip_next_step": "turns",
    # "You may play up to three additional lands this turn." (Summer Bloom) /
    # "Target player can't play lands this turn." (Solfatara.) CR 305.2's land
    # drop is part of the turn's structure rather than of the board, which is
    # the family the skip above and `grant_extra_turn` are already in — and both
    # halves take the same one, because a permission and its withdrawal are the
    # same question answered twice.
    "grant_extra_land_plays_this_turn": "turns",
    "forbid_land_plays_this_turn": "turns",
    "cumulative_upkeep": "upkeep",
    # Rogue Skycaptain's decline: clear the counters and hand the permanent
    # over. Cumulative upkeep's own decline is a sacrifice and stays on the
    # `cumulative_upkeep` kind, so this is the family's second consequence
    # rather than a second reading of the paragraph.
    "upkeep_counter_toll_or_cede_control": "upkeep",
    "upkeep_pay_or_sacrifice_enchantment": "upkeep",
    "upkeep_pay_or_sacrifice_self": "upkeep",
    # The destroy twin (Cosmic Horror). Same family: it is the upkeep's
    # pay-or-consequence prompt, and what the consequence is does not change
    # which registry dispatches it.
    "upkeep_pay_or_destroy_self": "upkeep",
    "upkeep_pay_to_untap_self": "upkeep",
    # The Aura twin (Paralyze): the same offer made to the enchanted
    # permanent's controller, untapping what the Aura is on. Same family, same
    # registry, so GRAMMAR_CATEGORIES is unchanged.
    "upkeep_pay_to_untap_enchanted": "upkeep",
    "grant_regeneration_to_target_creature": "regeneration",
    "grant_regeneration_to_self": "regeneration",
    "grant_regeneration_to_enchanted_creature": "regeneration",
    # "Target creature can't be regenerated this turn" is the negative half of
    # the same subject, so it shares the category rather than minting one that
    # would always be switched on and off alongside it.
    "deny_regeneration_to_target": "regeneration",
    "deny_regeneration_to_self": "regeneration",
    # …and the block-pair subject (Lim-Dûl's Cohort). Same category for the same
    # reason: what differs is which creature the sentence names, not what the
    # rider does to it.
    "deny_regeneration_to_block_pair": "regeneration",
    "grant_extra_turn": "turns",
    # CR 724.1: an expedited replacement for the rest of the turn, not an effect
    # on any object - the same family as granting one.
    "end_the_turn": "turns",
    "opponents_who_could_not_discard_lose_life": "life",
    "grant_team_keyword_until_eot": "pump",
    # "…that creature gains first strike until end of turn" on a block trigger
    # (Goblin Flotilla) — the keyword half of the same family, over the pair the
    # trigger named rather than over a board.
    "grant_keyword_to_block_pair": "pump",
    # A durationless keyword grant to the enchanted creature (Cocoon's hatch):
    # recorded on the creature through the layer-6 write API, so it survives
    # the Aura (CR 611.2c).
    "grant_keyword_to_attached": "pump",
    "add_loyalty_counters": "counters",
    # The same counter on a permanent the controller chooses at resolution
    # (Liliana's Scrounger). Same category, so GRAMMAR_CATEGORIES is unchanged:
    # a counter is a counter whether the ability names its own source or a noun
    # phrase, and a second switch would let one be gated off without the other.
    "add_loyalty_counters_to_chosen": "counters",
    "target_bites_target": "damage",
    "source_fights_target": "damage",
    "source_bites_target": "damage",
    "prepare_then_interact": "damage",
    "grant_team_assign_unblocked_until_eot": "pump",
    # Ending the game (CR 104). Their own category rather than "life": nothing
    # about a life total is involved, and the three outcomes share one set of
    # handlers in engine/handlers/life_and_game.py.
    "player_wins_game": "game_end",
    "player_loses_game": "game_end",
    "target_player_loses_game": "game_end",
    "game_is_draw": "game_end",
    # "Each creature blocking or blocked by this creature gains first strike
    # until end of turn." (Spitting Slug.) The keyword family, like every other
    # grant: what differs is which permanents receive it.
    "grant_keyword_to_creatures_in_combat_with_source": "pump",
    # The other half of Tracker's exchange: the creature the sentence before it
    # bit, biting back. The damage family, like the one-way half it answers.
    "bound_bites_source": "damage",
    "bound_bites_player": "damage",
    "grant_unblockable_to_target": "evasion",
    # "Target creature can't be blocked **by Walls** this turn." (Tower of
    # Coireall.) The same evasion family: what differs is that the restriction
    # names a class of blocker instead of every blocker, and that class is
    # payload the blockers step tests — the arrangement the static printings in
    # engine/combat_restrictions.py already use.
    "grant_cant_be_blocked_by_until_eot": "evasion",
    "grant_cant_be_blocked_except_by_until_eot": "evasion",
    "grant_unblockable_to_self": "evasion",
    # Restrictions on declaring attackers/blockers (CR 506, 509).
    "cant_attack_unless_defender_controls": "combat_restrictions",
    # CR 508.1c / 509.1b: a restriction on the whole declaration rather
    # than on the creature, so the count is payload and the check lives
    # where the declaration is assembled.
    "cant_attack_unless_others_attack": "combat_restrictions",
    # CR 508.1g printed on a permanent that names a class of creatures
    # rather than itself (Flooded Woodlands, Reclamation).
    "creatures_cant_attack_unless_sacrifice": "combat_restrictions",
    "cant_block_unless_others_block": "combat_restrictions",
    # "That creature can't attack during its controller's next turn." (Wall of
    # Dust's block trigger) — a one-shot stamp on the blocked creature, read
    # back by `can_attack` for exactly one of that controller's turns.
    "cant_attack_during_controllers_next_turn": "combat_restrictions",
    "cant_block_subject": "combat_restrictions",
    # Heat Wave: the same restriction printed about a described set of
    # blockers rather than about the permanent carrying it, so the
    # blocker gate finds it by scanning the board rather than by reading
    # the blocker's own program.
    "subject_cant_block_subject": "combat_restrictions",
    # The one-shot, turn-scoped blanket ("Creatures without flying can't block
    # this turn", Destructive Tampering's second mode).
    "cant_block_until_eot": "combat_restrictions",
    "target_cant_block_until_eot": "combat_restrictions",
    # The permission twin of the two above (Yare): CR 509.1b's block-count
    # ceiling raised for a turn rather than a restriction imposed for one.
    "grant_additional_blocks_until_eot": "combat_restrictions",
    # "Creatures can't attack this turn." (Festival.) The same category as its
    # blocking twin above, so GRAMMAR_CATEGORIES is unchanged.
    "cant_attack_until_eot": "combat_restrictions",
    # "This creature can't attack unless you sacrifice two Islands."
    # (Leviathan.) A restriction with a cost behind it, enforced by the
    # declaration rather than by a handler — same category, so
    # GRAMMAR_CATEGORIES is unchanged.
    "cant_attack_unless_sacrifice": "combat_restrictions",
    # "…and remove it from combat" (Disharmony, CR 506.4c). A one-shot combat
    # action rather than a restriction, filed with the family whose steps
    # dispatch it.
    # "Attacking doesn't cause creatures you control to tap this combat…"
    # (Johan.) A restriction on what declaring an attacker does, so it files
    # with the other CR 506/508 clauses and GRAMMAR_CATEGORIES is unchanged.
    # "This creature assigns no combat damage this turn." (Floral Spuzzem.)
    # CR 510.1's assignment switched off for one permanent — a restriction on
    # what the combat damage step does, so it files with the other CR 506/510
    # clauses.
    "assign_no_combat_damage_until_eot": "combat_restrictions",
    "exempt_from_attack_tapping": "combat_restrictions",
    "remove_from_combat": "combat_restrictions",
    # "Target unblocked attacking creature becomes blocked." (Dazzling Beauty;
    # CR 509.1h.) A one-shot change to what a creature's being in combat means,
    # filed beside `remove_from_combat` for that entry's reason: the family
    # whose steps dispatch it is the combat one.
    "become_blocked": "combat_restrictions",
    # "You choose which creatures block this combat and how those creatures
    # block." (Melee.) CR 509.1a's chooser substituted for the declare-blockers
    # turn-based action — a restriction on how that declaration is made rather
    # than an effect on any permanent, so it files with the other CR 506/509
    # clauses and GRAMMAR_CATEGORIES is unchanged.
    "choose_blocks_for_defenders": "combat_restrictions",
    # "…each creature that's blocking exactly one of those attacking creatures
    # stops blocking it and is blocking the other attacking creature."
    # (General Jarkeld.) A one-shot rewrite of an existing block (CR 509.1g),
    # filed beside Sorrow's Path's mirror of it for the same reason
    # `remove_from_combat` is here: the family whose steps dispatch it.
    "reassign_blockers_between_attackers": "combat_restrictions",
    "mark_non_wall_target_to_attack": "combat_restrictions",
    # Kookus: CR 508.1a's requirement for one turn, which is not the printed
    # static `combat_restrictions.py` reads for "attacks **each combat** if
    # able". Same category, so GRAMMAR_CATEGORIES is unchanged.
    "force_self_to_attack_until_eot": "combat_restrictions",
    "counter_top_stack_spell": "counterspells",
    # CR 115.7a, changing a spell's target. Its own category rather than the
    # counterspells one beside it: a counter removes an object from the stack
    # and a retarget leaves it there resolving in full, so filing them together
    # would let the report say a card countered something it did not touch.
    # Both steps of the pair carry it — the choice of who replaces you is not a
    # separate effect, it is the retarget deciding what it will do.
    "choose_new_spell_target": "retargeting",
    "change_target_spell_target": "retargeting",
    # "Choose target creature." — a sentence whose whole content is CR 601.2c's
    # choosing of targets, printed by a spell whose *next* sentence says what
    # becomes of what it chose. Its own category rather than borrowing one,
    # because it touches nothing: it is the targeting, and saying otherwise
    # would let the report claim the spell destroys or pumps something.
    "choose_target_permanent": "targeting",
    # "…can be the target of spells and abilities controlled by target player
    # as though it didn't have shroud" (Autumn Willow): a permission about
    # who may choose this permanent as a target, which is this category.
    "waive_shroud_for_target_player": "targeting",
    # "Choose X target attacking creatures." (Winter's Chill.) The same
    # category and the same nothing-happens-here reading; the plural records
    # what it chose so the loop behind it has a set to walk.
    "choose_target_permanents": "targeting",
    # A delayed triggered ability (CR 603.7). The category is the *creating*
    # act; what the ability does when it fires is its inner instruction's, read
    # through `_nested_instructions` below for the reason `choose_one`'s
    # options are.
    "create_delayed_trigger": "delayed_triggers",
    "counter_stack_ability": "counterspells",
    # Double Vision. Its own category name would be a family of one; copying a
    # spell on the stack is the same family as countering one.
    "copy_triggering_spell": "counterspells",
    # Chain Lightning. Copying the *resolving* spell rather than one still on
    # the stack; the same family either way, so GRAMMAR_CATEGORIES is unchanged.
    "copy_this_spell": "counterspells",
    "tap_or_untap_target": "tapping",
    # "Those creatures don't untap during their controller's next untap step."
    # (Frost Breath.) The same category as the tap that names them: what the
    # sentence does is hold a permanent through one untap step, which is the
    # tapping family's business either way.
    "skip_next_untap": "tapping",
    "add_mana_from_text": "mana",
    # "Note the type of mana spent to pay this activation cost."
    # (Jeweled Amulet.) No mana is produced; what the instruction does is
    # remember CR 107.4b's symbols on the source for a later ability of the
    # same permanent to add back.
    "note_mana_spent": "mana",
    # "Add an amount of {B} equal to the sacrificed artifact's mana value"
    # (Priest of Yawgmoth). The handler predates the grammar reading this
    # sentence — two hooks produced it — so the kind is named for the creature
    # the first of them sacrificed; what it actually reads is the mana value of
    # whatever the cost ate, artifact or otherwise.
    "sacrifice_creature_for_mana": "mana",
    # A triggered *mana* ability on a land being tapped (CR 605.1b): resolved
    # inline by Game.tap_land_for_mana, not through EFFECT_HANDLERS on the
    # stack, because CR 605.4a says a triggered mana ability never uses it.
    "add_mana_for_tapped_land": "mana",
    # "If target Plains is tapped for mana, it produces colorless mana instead
    # of white mana." (Quarum Trench Gnomes.) A CR 611.2 continuous effect on
    # one land rather than a production of mana — the same category because
    # what it changes is the land's mana ability, and nothing else in the
    # engine asks about that.
    "produce_mana_instead": "mana",
    # The class-scoped, until-end-of-turn twin (Deep Water). Same category:
    # what changes is which lands it covers and how long it lasts.
    "swap_controller_land_mana_until_eot": "mana",
    # "For one spell this turn, you may spend mana as though it were mana of
    # any type…" (North Star.) A CR 609.4 permission the payment reads, not a
    # production of mana — the same category because what it is about is how
    # mana pays, and nothing else in the engine asks that.
    "grant_spend_mana_as_though": "mana",
    "create_token": "tokens",
    "create_copy_token": "tokens",
    # Flipping a coin (CR 705). Its own category rather than sharing one with
    # the effect it gates: the flip is a randomiser, and every branch behind it
    # keeps the category of whatever that branch does — a coin flip over a
    # damage effect must not be able to turn "damage" on.
    "flip_coin": "coin_flips",
    "coin_flip_stakes_loop": "coin_flips",
    # "Choose a number between 0 and 7." (Shapeshifter.) Its own category for
    # the reason the coin flip has one: the number is a *value* a player picks,
    # and what reads it back is a different sentence with a category of its own.
    "choose_number": "chosen_numbers",
    # "Choose a color." (Chromatic Armor.) Its own category rather than
    # sharing the number's: what is recorded and what reads it back are
    # different questions, and one switch must not be able to gate half of
    # either off.
    "choose_color": "chosen_colors",
    # "That player chooses artifact, creature, land, or non-Aura enchantment."
    # (Teferi's Realm.) Beside `choose_color` and in its family: a sentence that
    # produces a value and no effect of its own, read back by the next sentence
    # of the same ability. The value is a *card type* rather than a colour,
    # which is what the key it records under says and not what the family does.
    "choose_card_type": "chosen_colors",
    # "…put a +0/+1 counter on that creature for each 1 damage prevented
    # this way." (Sacred Boon.) A counter placement whose number is what an
    # earlier step's shield absorbed, so it sits in the counters family with
    # every other placement.
    "add_pt_counters_per_damage_prevented": "counters",
    # "Choose a player who cast one or more sorcery spells this turn."
    # (Backdraft.) Its own category for the reason the number above has one: the
    # choice is a *value* a player picks and the sentence that reads it back has
    # a category of its own — here, damage. A choice sharing the category of
    # what reads it would let one switch gate half of a two-sentence card.
    "choose_player_who_cast": "chosen_players",
    # "**An opponent** gains control of this land …" (Rainbow Vale.) The same
    # category and for the same reason: the seat is a value one step records and
    # the step behind it reads back, and the hand-over that reads it carries the
    # control family's category of its own.
    "choose_opponent": "chosen_players",
    # "Choose target opponent." (Soldevi Sentry.) The targeted twin of the row
    # above — CR 601.2c rather than CR 608.2c — and the same category, because
    # what the category names is the answer the sentence produces.
    "choose_target_player": "chosen_players",
    # "Count the number of permanents." (Chaos Moon.) Its own category for the
    # reason the chosen number and the chosen player have theirs: the count is a
    # *value* the effect records, and the sentences that read it back carry the
    # categories of whatever they do — a count sharing one of those would let a
    # single switch gate half of a three-sentence card.
    "count_objects": "counted_numbers",
    # "…the damage dealt by **one of those** sorcery spells this turn." The
    # second half of the same decision, and a separate step because it is a
    # separate question: which player, then which of their spells.
    "choose_cast_this_turn": "chosen_players",
    "create_emblem": "tokens",
    # Optional actions. Parsed and lowered, not switched on — see
    # `control_flow.WRAPPER_KINDS`.
    "may": "optional",
    # "Unless an opponent pays {2}, …" (Scarwood Bandits) — the same family
    # asked of another seat, so GRAMMAR_CATEGORIES is unchanged: what differs is
    # who is offered the cost and which branch the effect sits on.
    "unless_player_pays": "optional",
}

# The zone-change half lives with the family that produces it (see
# `zones.ZONE_INSTRUCTION_CATEGORIES` for the line). Composed rather than
# referenced, so every reader still asks one table one question.
INSTRUCTION_CATEGORIES.update(ZONE_INSTRUCTION_CATEGORIES)
