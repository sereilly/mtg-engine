"""The `pump` half of `lowering/categories.INSTRUCTION_CATEGORIES`.

Split out at Urza's Saga's wave-2 integration, when `categories.py` crossed the
thousand-line guard at **1,003** — three lines over, from two groups' rows
summing with neither branch at fault. That is the case the guard is documented
to catch late, and the case where the seam has to be found with none of the work
in hand.

It is found the way that table's three earlier splits were: take a whole
**category**, not a slice of the file. `pump` is 50 of the 310 rows still
declared here and the largest remaining family by a factor of one and a half,
exactly as `zones` was when it left at Visions and `_zone_categories` records.

The line is a real one rather than a size cut, and CLAUDE.md already draws it:
every kind here modifies power or toughness, and **all P/T mutation goes through
one write API** (`engine/pt.py`: `set_base_pt`, `add_pt_modifier`, `switch_pt`).
A kind whose category is `pump` is a kind whose handler ends in that API; every
kind left in `categories` ends somewhere else. That is the same shape of
question `_zone_categories` asks — "does this kind name two zones?" — one layer
of the CR down (613 layer 7c rather than 400).

A floor, not a family: it is 50 rows of data with no call graph, `categories.py`
folds it in with `update()` exactly as it folds the zone and ownership halves,
and `INSTRUCTION_CATEGORIES`' address is unchanged for every reader. What the
split gives up is adjacency inside one file, which is what a cap split always
gives up.
"""

#: The `pump` rows of `INSTRUCTION_CATEGORIES`, folded in by `categories.py`.
PUMP_INSTRUCTION_CATEGORIES: dict[str, str] = {
    "pump_target_creature_until_eot": "pump",
    "pump_target_while_source_tapped": "pump",
    # One pump per chosen slot, each with its own P/T delta (Rookie Mistake).
    # The same category as the one-target pump above: what differs is how many
    # targets the sentence names, not what the effect is.
    "pump_targets_until_eot": "pump",
    "pump_self": "pump",
    "pump_enchanted_creature": "pump",
    "buff_creatures_global": "pump",
    # Thran Weaponry: the same board sweep whose duration is a *condition*
    # rather than a step boundary, so it is contributed by the recompute
    # instead of stamped. Same category — what differs is how it ends.
    "buff_creatures_global_while_source_tapped": "pump",
    "set_base_pt_target_until_eot": "pump",
    # "…becomes a 3/3 Sphinx creature … until end of turn" (Riddleform).
    # The "pump" family, because what the sentence does is set a P/T — the
    # type change beside it is the layer bridge reading the same record.
    "animate_self_until_eot": "pump",
    # "…becomes a 3/6 Golem artifact creature until end of combat."
    # (Jade Statue.) The same animation over the third window, so the same
    # category and GRAMMAR_CATEGORIES is unchanged.
    "animate_self_until_end_of_combat": "pump",
    # "{6}: This land becomes a 3/3 Elemental artifact creature that's still a
    # land." (Stalking Stones.) The row above with no end to it (CR 611.2a), so
    # the same category for `animate_target_indefinitely`'s reason: what differs
    # is the duration, not what the sentence does.
    "animate_self_indefinitely": "pump",
    # "Target snow land becomes a 2/2 creature until end of turn." (Balduvian
    # Conjurer.) The same record on a permanent the sentence names rather than
    # on the source, so the same category: what differs is which permanent
    # holds it, not what the sentence does.
    "animate_target_until_eot": "pump",
    # "Target land becomes a 3/3 artifact creature that's still a land. (This
    # effect lasts indefinitely.)" (Mishra's Groundbreaker.) The same record on
    # the same permanent with no end to it (CR 611.2a), so the same category:
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
    # "…target creature with the chosen ability loses it and another target
    # creature gains it." (Phyrexian Splicer.) One keyword leaving one creature
    # and landing on another — the same family as the grants above it, because
    # what the sentence is *about* is a keyword an object has. Same category, so
    # GRAMMAR_CATEGORIES is unchanged.
    "move_chosen_keyword_between_targets": "pump",
    # The quoted-text grants (Life Matrix): the same layer-6 family, carrying a
    # whole printed ability instead of a word.
    "grant_target_ability_text": "pump",
    "grant_self_ability_text": "pump",
    # The negative twin ("It loses indestructible until end of turn", Soul Sear).
    "remove_target_keyword_until_eot": "pump",
    # "Until end of turn, target creature loses **all abilities** …" (Humble.)
    # The same layer-6 removal over every ability rather than one named word, so
    # the same category and GRAMMAR_CATEGORIES is unchanged.
    "remove_target_abilities_until_eot": "pump",
    # The same removal aimed at the object the *trigger's event* was about
    # ("Whenever a creature attacks you, it loses flanking until end of
    # turn", Barbed Foliage). One family, because what differs is which
    # object the words name and that is the payload.
    "remove_event_subject_keyword": "pump",
    # The P/T twin of the row above, aimed at the same object ("Whenever a
    # Sliver becomes blocked, that Sliver gets +1/+1 until end of turn for each
    # creature blocking it", Spined Sliver). Same category, so
    # GRAMMAR_CATEGORIES is unchanged — what is new is which object the words
    # name, and that is the payload.
    "pump_event_subject": "pump",
    # The board-wide negative twin ("All creatures lose flying until end of
    # turn", Whiteout), beside `grant_team_keyword_until_eot`.
    "remove_team_keyword_until_eot": "pump",
    # The removal twin of ``grant_keyword_to_block_pair`` below (Talruum
    # Champion). Same category as every other keyword write, so the two halves
    # of a block cannot have one switched on without the other.
    "remove_keyword_from_block_pair": "pump",
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
    "grant_team_keyword_until_eot": "pump",
    # "…that creature gains first strike until end of turn" on a block trigger
    # (Goblin Flotilla) — the keyword half of the same family, over the pair the
    # trigger named rather than over a board.
    "grant_keyword_to_block_pair": "pump",
    # "…that creature gets +1/+1 until end of turn" on a block trigger
    # (Flailing Drake) — the P/T half of the pair above, and the kind
    # ``engine/flanking.py`` has always built by hand (CR 702.25a). It had no
    # row here because until the grammar could read the *printed* sentence
    # nothing lowered to it, and a category is what a lowering needs.
    "pump_block_pair": "pump",
    # A durationless keyword grant to the enchanted creature (Cocoon's hatch):
    # recorded on the creature through the layer-6 write API, so it survives
    # the Aura (CR 611.2c).
    "grant_keyword_to_attached": "pump",
    "grant_team_assign_unblocked_until_eot": "pump",
    # "Each creature blocking or blocked by this creature gains first strike
    # until end of turn." (Spitting Slug.) The keyword family, like every other
    # grant: what differs is which permanents receive it.
    "grant_keyword_to_creatures_in_combat_with_source": "pump",
}
