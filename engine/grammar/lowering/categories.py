"""Which migration category each lowered instruction kind belongs to.

One table, in its own module because it is a *registry* rather than logic: the
gate in `engine/grammar/__init__.py` turns categories on one at a time, and an
instruction whose kind is missing here can be lowered but never gated on.

`GRAMMAR_CATEGORIES` is held equal to the set of values here by
`tests/engine/test_grammar_categories.py`. With no fallback underneath the
grammar, a category left off does not route its lines elsewhere — it costs
those cards their support, which is why the equality is a test and not a
convention.
"""

from ...lord_buffs import (LORD_BUFF_KIND)
from ...enter_tapped_statics import ENTER_TAPPED_STATIC_KIND
from ...land_animation import LAND_ANIMATION_KIND
from ...land_types import STATIC_LAND_TYPE_KIND, STATIC_SUPERTYPE_REMOVAL_KIND
from ...oracle_types import OracleInstruction
from ._events import (CHOSEN_CAST_DAMAGE, CHOSEN_PERMANENT, CHOSEN_PLAYER,
                      CREATED_TOKEN, EXILED_THIS_WAY)
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
    "shuffle_graveyard_into_library": "zones",
    "shuffle_hand_into_library": "zones",
    "gain_type": "characteristics",
    "change_supertype": "characteristics",
    "restrict_untap_while_source_tapped": "tapping",
    "arm_self_action_at_next_end_step": "destruction",
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
    "set_team_base_pt_until_eot": "pump",
    # The CR 613.4b rewrite template (Sentinel, Wall of Tombstones, Halfdane,
    # Brine Hag). The same category as the setters above: a one-shot layer-7b
    # write, however its value is computed and however long it lasts.
    "set_source_base_toughness_from_target_power": "pump",
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
    # The durationless half of the same effect, on the ability's own source
    # (Elder Land Wurm). Same family: what changes is how long the removal
    # lasts, not what kind of effect it is.
    "remove_self_keyword": "pump",
    "grant_self_keyword_until_eot": "pump",
    "grant_banding_to_target": "pump",
    "add_named_counter_to_self": "pump",
    "add_named_counter_to_target": "pump",
    "add_counter_to_self": "pump",
    "add_counter_to_target": "pump",
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
    "add_counter_to_each_you_control": "pump",
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
    "remove_counter_from_self": "counters",
    "remove_any_number_of_counters_from_self": "counters",
    "exile_any_number_of_own_tokens": "zones",
    "put_graveyard_cards_on_library_top": "zones",
    # Pestilent Haze's second mode: loyalty stripped from every walker at once.
    "remove_loyalty_from_each_planeswalker": "counters",
    "add_pt_counters_to_attached": "counters",
    # Its named-counter twin ("…put X sleep counters on it", Venarian Gold).
    "add_named_counter_to_attached": "counters",
    # Its removal ("remove a sleep counter from that creature", Venarian
    # Gold), fired by the upkeep registry.
    "remove_counter_from_attached": "counters",
    "draw_then_discard_self": "zones",
    "discard_then_draw_that_many": "zones",
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
    "destroy_each_unless_life_paid": "destruction",
    "destroy_attached_permanent": "destruction",
    # "…destroy **that creature**" inside a delayed ability (War Barge):
    # the object the creating ability bound, by id, rather than a pick.
    "destroy_bound_permanent": "destruction",
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
    "untap_all_matching": "tapping",
    "grant_prevention_shield": "prevention",
    # "…prevent half that damage, rounded down" (Dark Sphere) — a CR 615.8
    # whole-instance shield that absorbs a share of the event. Same category, so
    # GRAMMAR_CATEGORIES is unchanged.
    "grant_half_prevention_shield": "prevention",
    "grant_whole_prevention_shield": "prevention",
    "prevent_all_combat_damage": "prevention",
    # The same blanket, narrowed to a printed noun phrase (Pack Leader). Same
    # category: what differs is who it covers, not what kind of effect it is.
    "prevent_all_combat_damage_to_matching": "prevention",
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
    # The class-scoped, optional one (Blood of the Martyr). Same category
    # for the same reason: what it moves is damage, and being optional and
    # being about a class are payload differences.
    "redirect_matching_damage_to_you_until_eot": "damage",
    "recolor_target_from_text": "recolor",
    # The same layer-5 colour change with a duration and several targets
    # (Dwarven Song and its four siblings). Same category: what differs is how
    # long it lasts and how many it names, not what it does.
    "recolor_targets_until_eot": "recolor",
    # "…becomes the color of your choice" — the colour arrives with the answer
    # rather than with the text (CR 609.3), which is a payload difference and
    # not a category one.
    "recolor_target_chosen_color": "recolor",
    # Dream Coat: the same effect on an Aura's own host rather than on a
    # target, and on the set of colours the card offers rather than one.
    "recolor_enchanted_chosen_color": "recolor",
    # CR 701.12b, an atomic swap of two layer-2 contributions.
    "exchange_control_of_targets": "control",
    "exchange_control_of_bound": "control",
    # A printed text change (CR 612). Its own category rather than "recolor":
    # the Lace cycle makes an object a colour, while this replaces a *word*
    # wherever the object's text uses it, and one of the two modes does not
    # touch colour at all.
    "mark_text_modified": "text_change",
    # A control change whose duration is linked to its source (CR 611.3).
    "steal_target_permanent_linked_to_self": "control",
    "gain_control_until_eot": "control",
    # The monitored linked durations (CR 611.2b): "for as long as you control
    # this creature and this creature remains tapped" (Willow Satyr, Rubinia
    # Soulsinger) and The Wretched's end-of-combat blocker steal. The
    # conditions are payload; the state-based sweep ends them.
    "steal_target_linked_to_source": "control",
    "steal_blockers_of_source": "control",
    "sacrifice_self": "zones",
    # The controller-chosen sacrifice (Dire Fleet Warmonger's optional cost).
    "sacrifice_matching_permanent": "zones",
    "sacrifice_attached_permanent": "zones",
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
    "discard_target_cards": "zones",
    # The controller's own chosen discard (Jeskai Elder's if-you-do branch).
    "discard_controller_cards": "zones",
    # "Each player may discard up to three cards." (Mind Bomb.) One prompt
    # per seat, and a discard like every other one in this category.
    "each_player_discards_up_to_cards": "zones",
    # "Each opponent discards two cards." (Bad Deal) — one pending discard
    # choice per opponent, same flow as the targeted form.
    "each_opponent_discards_cards": "zones",
    "discard_x_target_cards": "zones",
    "opponent_discards_random_card_on_damage": "zones",
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
    "reveal_hand_and_choose": "zones",
    # CR 701.16, the reveal on its own (Amnesia, Rag Man). The same category as
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
    # "…discards **all nonland cards**" (Amnesia). A discard like the counted
    # ones beside it; only who picks differs, and here nobody does.
    "discard_all_matching_cards": "zones",
    "look_at_target_hand": "zones",
    "look_at_target_library_top": "zones",
    # "…, then put them back in any order" (Natural Selection, Portent). The
    # look above with the rearrangement switched on — same prompt, same zone,
    # so the same family.
    "reorder_target_library_top": "zones",
    # A library search moves a card between hidden zones — same module, same
    # category as the other zone-change handlers.
    "search_library": "zones",
    # The cast-from-exile/graveyard subsystem (both Chandras, M21): two exiles
    # that record what they moved, and the permission their later sentences
    # grant over it. All zone work — the permission is about which zone a card
    # may be cast from — so no new category and GRAMMAR_CATEGORIES is unchanged.
    "exile_top_of_library": "zones",
    "put_exiled_with_source": "zones",
    "exile_graveyard_until_leaves": "zones",
    "exile_until_leaves_or_untaps": "zones",
    "exchange_ownership_unless_paid": "zones",
    "random_reveal_ownership_exchange": "zones",
    "take_ownership_of_exiled": "zones",
    "return_exiled_source_to_graveyard": "zones",
    "transmute_by_sacrifice": "zones",
    "place_held_card": "zones",
    "look_top_pick_to_hand": "zones",
    "look_top_exile_random": "zones",
    "search_and_exile_matching": "zones",
    "grant_cast_permission": "zones",
    "grant_extra_turn": "turns",
    # CR 724.1: an expedited replacement for the rest of the turn, not an effect
    # on any object - the same family as granting one.
    "end_the_turn": "turns",
    # The planeswalker block's one-shot zone movers (M21 loyalty abilities).
    "each_player_discards_a_card": "zones",
    "opponents_who_could_not_discard_lose_life": "life",
    "discard_hand": "zones",
    "put_target_on_library_top": "zones",
    # "Choose two cards in your hand drawn this turn." (Sylvan Library.) A
    # pick out of a hidden zone that moves nothing; the sentence after it is
    # what moves anything.
    "choose_cards_in_hand": "zones",
    "put_iterated_card_on_library": "zones",
    "put_graveyard_card_on_library_bottom": "zones",
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
    # "Choose a card name. Target opponent reveals X cards at random from their
    # hand. Then that player discards all cards with that name revealed this
    # way." (Nebuchadnezzar.) The same category as the naming paragraph above:
    # what it does is move cards out of a hidden zone.
    "name_and_random_reveal": "zones",
    # Petra Sphinx's guess. "zones" like the reveals above it: what the card
    # does is look at the top of a library and move that card somewhere, and
    # the name is only what decides which somewhere.
    "name_then_reveal_top": "zones",
    "exile_all_matching": "zones",
    "grant_team_keyword_until_eot": "pump",
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
    "phase_out_target": "zones",
    "grant_team_assign_unblocked_until_eot": "pump",
    "phase_out_opponent_creatures": "zones",
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
    "grant_unblockable_to_target": "evasion",
    # "Target creature can't be blocked **by Walls** this turn." (Tower of
    # Coireall.) The same evasion family: what differs is that the restriction
    # names a class of blocker instead of every blocker, and that class is
    # payload the blockers step tests — the arrangement the static printings in
    # engine/combat_restrictions.py already use.
    "grant_cant_be_blocked_by_until_eot": "evasion",
    "grant_unblockable_to_low_power_target": "evasion",
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
    "cant_block_power_n_or_greater": "combat_restrictions",
    # The one-shot, turn-scoped blanket ("Creatures without flying can't block
    # this turn", Destructive Tampering's second mode).
    "cant_block_until_eot": "combat_restrictions",
    "target_cant_block_until_eot": "combat_restrictions",
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
    "mark_non_wall_target_to_attack": "combat_restrictions",
    "counter_top_stack_spell": "counterspells",
    # CR 115.7a, changing a spell's target. Its own category rather than the
    # counterspells one beside it: a counter removes an object from the stack
    # and a retarget leaves it there resolving in full, so filing them together
    # would let the report say a card countered something it did not touch.
    # Both steps of the pair carry it — the choice of who replaces you is not a
    # separate effect, it is the retarget deciding what it will do.
    "choose_new_target_player": "retargeting",
    "change_target_spell_target": "retargeting",
    # "Choose target creature." — a sentence whose whole content is CR 601.2c's
    # choosing of targets, printed by a spell whose *next* sentence says what
    # becomes of what it chose. Its own category rather than borrowing one,
    # because it touches nothing: it is the targeting, and saying otherwise
    # would let the report claim the spell destroys or pumps something.
    "choose_target_permanent": "targeting",
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
    "draw_target_cards": "zones",
    "draw_controller_cards": "zones",
    "mill_target_player": "zones",
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
    # "Exile that token" (Stangg) — the token this same effect created, by the
    # id the token maker recorded. A zone change like the two beside it.
    "exile_created_token": "zones",
    "exile_target_graveyard_card": "zones",
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
    "add_mana_from_text": "mana",
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
    # "Choose a number between 0 and 7." (Shapeshifter.) Its own category for
    # the reason the coin flip has one: the number is a *value* a player picks,
    # and what reads it back is a different sentence with a category of its own.
    "choose_number": "chosen_numbers",
    # "Choose a player who cast one or more sorcery spells this turn."
    # (Backdraft.) Its own category for the reason the number above has one: the
    # choice is a *value* a player picks and the sentence that reads it back has
    # a category of its own — here, damage. A choice sharing the category of
    # what reads it would let one switch gate half of a two-sentence card.
    "choose_player_who_cast": "chosen_players",
    # "…the damage dealt by **one of those** sorcery spells this turn." The
    # second half of the same decision, and a separate step because it is a
    # separate question: which player, then which of their spells.
    "choose_cast_this_turn": "chosen_players",
    "create_emblem": "tokens",
    # Optional actions. Parsed and lowered, not switched on — see _WRAPPER_KINDS.
    "may": "optional",
    # "Unless an opponent pays {2}, …" (Scarwood Bandits) — the same family
    # asked of another seat, so GRAMMAR_CATEGORIES is unchanged: what differs is
    # who is offered the cost and which branch the effect sits on.
    "unless_player_pays": "optional",
}


# Values an instruction records in the resolution scratchpad, so a later
# back-reference ("that much") can verify it has a producer. A registry like
# the table above rather than logic: `_lower_may` and `_lower_steps` (in
# `lower.py`) read it to thread what each step records forward.
#
# **A value may be a tuple**, because a handler may record more than one thing
# and this table was under-describing when it could not say so:
# `destroy_target_permanent` has written both the victim's mana value and its
# controller's seat for as long as both riders have existed, and the table named
# one of them. The **first** entry is the *primary* record — the one "if you do"
# tests, because that rider asks whether the step took place and the primary is
# what a step of that kind always writes when it does.
_PRODUCES: dict[str, str | tuple[str, ...]] = {
    "deal_damage": "damage_dealt",
    # "This creature deals damage equal to its power to target creature.
    # **That creature** deals damage equal to its power to this creature."
    # (Tracker.) The bite records which permanent it chose, because that is the
    # only place the sentence after it can read the creature from: the ability
    # has one target and the second sentence names it without choosing again.
    "source_bites_target": "damaged_permanents",
    # "…chooses a creature that this card could enchant. **If the player does**,
    # return this card … **attached to that creature**." (Takklemaggot.) The
    # chosen permanent's id, which is both what the branch tests and what the
    # step behind it acts on — the choice is not a target, so nothing on the
    # board or on the stack records it.
    "choose_permanent": CHOSEN_PERMANENT,
    # "Choose a player who cast one or more sorcery spells this turn.
    # Backdraft deals damage to **that player** …" The seat is the whole of what
    # the first sentence does, and the only place the second can read it: a
    # chosen player is not a target and nothing on a board records the choice.
    "choose_player_who_cast": CHOSEN_PLAYER,
    # "…equal to half the damage dealt by **one of those** sorcery spells this
    # turn." The pick records what the chosen cast dealt, because by the time
    # this is asked the spell has resolved and left the stack — the ledger is
    # the record, and this is which row of it the player named.
    "choose_cast_this_turn": CHOSEN_CAST_DAMAGE,
    # "Counter target spell. … an amount of {C} equal to **that spell's** mana
    # value." (Mana Drain.) The countered spell's mana value — the one thing
    # about it that survives the counter, and only because the counter wrote it
    # down.
    "counter_top_stack_spell": "countered_spell_mana_value",
    # "Destroy all nonblack creatures. … where X is the number of creatures
    # that **died this way**." (Hellfire.) A sweep records how many permanents
    # it actually destroyed, which is the only place a later clause can read
    # that set from — by then the board no longer holds it.
    # "…destroy the other creature at end of combat. At the beginning of the
    # next end step, **if that creature was destroyed this way**, …" (Infinite
    # Authority.) The delayed destroy records which creature it marked and which
    # one the trigger was about, because the sentence after it names both and by
    # then neither is anything the board can be asked for — the victim is in a
    # graveyard and the pair the trigger bound is long past.
    "delayed_destroy_blocked_or_blocker": "end_of_combat_destruction",
    "destroy_all_creatures": "destroyed_this_way",
    "destroy_all_artifacts": "destroyed_this_way",
    "destroy_all_enchantments": "destroyed_this_way",
    "destroy_all_lands": "destroyed_this_way",
    "destroy_all_artifacts_creatures_enchantments": "destroyed_this_way",
    "destroy_all_matching": "destroyed_this_way",
    # "Exile all white creatures. **For each creature exiled this way**, …"
    # (Martyr's Cry.) The exile sweep's twin of the four rows above, and its own
    # marker rather than theirs: a sweep that exiles kills nothing, so "died
    # this way" over it would name an empty set.
    "exile_all_matching": EXILED_THIS_WAY,
    # CR 705.2: only the player who flipped wins or loses that flip, and both
    # "if you win" and "if you lose" read the one result — so the flip records
    # it and the conditionals after it read the record, rather than each
    # sentence flipping a coin of its own.
    "flip_coin": "coin_flip",
    # "Return that card to its owner's hand. **If that card is returned to
    # its owner's hand this way**, …" (Puppet Master.) The return records
    # whether it actually took place, which is what the rider after it asks —
    # the card may have been exiled in response, or diverted (CR 903.9b).
    "return_bound_card_to_owners_hand": "returned_bound_card",
    # "Discard X cards, **then** return a card from your graveyard to your hand
    # **for each card discarded this way**." (Recall.) The prompt records how
    # many were actually discarded when it is answered, which is the only place
    # the number exists — the hand the step was handed is not the hand the
    # player chose from.
    "discard_controller_cards": "discarded_count",
    # The per-seat form records the same thing, so a sentence reading "the
    # number of cards they discarded this way" has a producer to name.
    "each_player_discards_up_to_cards": "discarded_count",
    # "Choose two cards in your hand … **For each of those cards**, …"
    # (Sylvan Library.) The pick records what it chose, which is the only
    # place the next sentence can read that set from: nothing about a hand
    # says which of its cards an earlier step named.
    "choose_cards_in_hand": "chosen_hand_cards",
    # "Remove any number of +1/+1 counters … create **that many** … tokens"
    # (Tetravus). The removal records how many it took, under the key the token
    # maker's "that many" already reads.
    "remove_any_number_of_counters_from_self": "trigger_count",
    # "Exile any number of tokens created with this creature. If you do, put
    # **that many** +1/+1 counters on this creature." The same key, for the same
    # reason: the count is what the next sentence is about.
    "exile_any_number_of_own_tokens": "trigger_count",
    # The exile records whose permanent it removed, which is what "Its
    # controller creates a token" reads (Angelic Ascension, Secure the Scene).
    "exile_target_permanent": "exiled_permanent_controller",
    # "Create Stangg Twin, a … token. Exile **that token** when …" (Stangg).
    # The token maker records which permanent it made, which is the only place
    # a later sentence of the same effect can name it from — a token is a new
    # object with a fresh id (CR 400.7), so there is nothing about it to look
    # up by.
    "create_token": CREATED_TOKEN,
    # Both exiles record what they exiled, which is what "you may play cards
    # exiled this way" / "you may cast them this turn" read.
    "exile_top_of_library": "exiled_cards",
    "search_and_exile_matching": "exiled_cards",
    # And the graveyard exile, which is what "If **it** was a creature card"
    # reads (Scavenging Ooze) — the same key, because the question the
    # back-reference asks is the same one: what did this effect just exile?
    "exile_target_graveyard_card": "exiled_cards",
    # "Remove a pupa counter from this Aura. **If you can't**, …" (Cocoon).
    # The removal records whether a counter was there to remove, and the
    # if-you-can't branch reads the record back, negated.
    "remove_counter_from_self": "removed_counter",
    # "Tap up to two target creatures. **Those creatures** don't untap…"
    # (Frost Breath.) The tap records which permanents it affected, by id, and
    # the sentence after it reads that record rather than re-resolving the slots
    # — by then a target may have left, and CR 611.2c fixed the set when the
    # effect began.
    "tap_target_permanent": "tapped_permanents",
    # "…tap the creature, **remove it** from combat" (Imprison). The Aura's tap
    # names its own attachment rather than a target, so it is a different
    # producer of the same record — what this effect just tapped.
    "tap_enchanted_creature": "tapped_permanents",
    # "Untap target attacking creature and remove **it** from combat. Gain
    # control of **that creature** until end of turn." (Disharmony.) The untap
    # records what it resolved — affected, not merely flipped: a vigilance
    # attacker that was never tapped is still "it" (CR 611.2c fixes the set
    # when the effect begins) — and both later sentences read the record.
    "untap_target_permanent": "untapped_permanents",
    # "…reveal the top card of your library. **If it's** a creature or land
    # card, draw a card." (Track Down.) The reveal records what it showed and
    # the conditional after it reads that record — not the library, which the
    # draw in its own branch would have changed underneath it.
    "reveal_top_of_library": "revealed_card",
    # "Target player reveals a card at random from their hand." (Wand of
    # Ith.) The same record, from a different zone: the sentences behind it
    # ask what "it" is, and this is what answers.
    "reveal_random_card_from_hand": "revealed_card",
    # "Exile it. **If you do**, create a 5/5 black Demon creature token with
    # flying." (Archfiend's Vessel.) The self-exile records that it happened, so
    # the branch after it is the ordinary if-you-do rather than a fused kind.
    "exile_self": "exiled_self",
    # "Sacrifice this artifact. **If you do**, discard your hand, then put all
    # cards exiled with this artifact into their owner's hand." (Knowledge
    # Vault.) The same shape: the sacrifice records that it took place, so the
    # branch behind it is the ordinary if-you-do. A source that had already
    # left records nothing, and CR 608.2b's "as much as possible" is then
    # exactly the branch not running.
    "sacrifice_self": "sacrificed_self",
    # "Return another target creature you control to its owner's hand. If you
    # do, you gain life equal to **that creature's** mana value." (Niambi,
    # Esteemed Speaker.) The bounce records the mana value of what it returned,
    # because by the time the life gain runs the permanent is gone — reading it
    # off the battlefield would find nothing and gain nothing.
    "bounce_target_creature": "returned_mana_value",
    # "Destroy target artifact. You gain life equal to **its** mana value."
    # (Divine Offering.) The destruction records the mana value of the
    # permanent it was aimed at — read *before* the destroy, so a regenerated
    # or indestructible artifact still supplies the number the second sentence
    # asks for: the words name the object, not the outcome.
    # "Destroy target land. **If that land was a snow land**, you gain 1 life."
    # (Thermokarst, Icequake.) The destruction also records the permanent it
    # was aimed at, read before the destroy for the reason the mana value is
    # (CR 608.2h, last-known information) — a condition asking what the land
    # *was* has nothing on the board left to look at.
    "destroy_target_permanent": ("its_mana_value", "destroyed_target"),
}


def produced_keys(kind: str) -> frozenset[str]:
    """Every scratchpad value *kind* records."""
    recorded = _PRODUCES.get(kind)
    if recorded is None:
        return frozenset()
    return frozenset((recorded,) if isinstance(recorded, str) else recorded)


def primary_produced(kind: str) -> str | None:
    """The record "if you do" tests — the first of *kind*'s, or None."""
    recorded = _PRODUCES.get(kind)
    if recorded is None:
        return None
    return recorded if isinstance(recorded, str) else (recorded[0] if recorded else None)


# Control-flow wrappers take the categories of whatever they wrap, so gating
# "damage" is enough to turn on a sequence of damage instructions without
# inventing a category nobody could reason about.
#
# ``may`` is deliberately NOT in here: it gets its own ungated category above,
# because an offer is not the same switch as the effect behind it. Wrapping it
# with the others would let "optional" be turned off under a family that is on,
# which is a card that performs its offer's consequence without asking.
_WRAPPER_KINDS: dict[str, tuple[str, ...]] = {
    "sequence": ("steps",),
    "if_then": ("then", "else"),
    "for_each": ("effect",),
    # A round of offers repeated until nobody takes it (Eureka). A wrapper for
    # the same reason ``for_each`` is: what the round *does* is the act it
    # carries, and the repetition is not an effect of its own.
    "repeat_offer_round": ("action",),
}


def _nested_instructions(instruction: OracleInstruction) -> tuple[OracleInstruction, ...] | None:
    """The instructions a wrapper carries, or None if it is not one.

    ``choose_one`` is a wrapper too, and its options are ``{label, instruction}``
    pairs rather than a bare tuple — the modal shape the pending-choice prompt
    reads. Its categories are its options', because that is what the card can
    actually do; giving it a category of its own would say the *choosing* is the
    effect.
    """
    if instruction.kind == "create_delayed_trigger":
        # A delayed ability's effect is one instruction rather than a list, so
        # it cannot ride `_WRAPPER_KINDS` above — but it is a wrapper all the
        # same, and an inner effect no category gates must ungate the line that
        # arms it. An entry with no instruction is an ability that would fire
        # into nothing, which is the empty-wrapper refusal below.
        inner = instruction.payload.get("instruction")
        return (inner,) if inner is not None else ()
    if instruction.kind == "choose_one":
        return tuple(
            mode["instruction"] for mode in instruction.payload.get("modes") or ()
        )
    nested_keys = _WRAPPER_KINDS.get(instruction.kind)
    if nested_keys is None:
        return None
    nested: tuple[OracleInstruction, ...] = ()
    for key in nested_keys:
        nested += tuple(instruction.payload.get(key) or ())
    return nested


def categories_of(instructions: tuple[OracleInstruction, ...]) -> frozenset[str]:
    """Migration categories covered by a lowered instruction sequence."""
    found: set[str] = set()
    for instruction in instructions:
        nested_keys = _nested_instructions(instruction)
        if nested_keys is not None:
            if not nested_keys:
                return frozenset({"__ungated__"})
            inner = categories_of(nested_keys)
            if "__ungated__" in inner:
                return frozenset({"__ungated__"})
            found |= inner
            continue
        category = INSTRUCTION_CATEGORIES.get(instruction.kind)
        if category is None:
            return frozenset({"__ungated__"})
        found.add(category)
    return frozenset(found)
