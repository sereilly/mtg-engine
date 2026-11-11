---
paths:
  - "engine/cast_*.py"
  - "engine/activation_*.py"
  - "engine/flashback.py"
  - "engine/madness.py"
  - "engine/refusals.py"
  - "engine/cost_modifier*.py"
  - "engine/self_cost_modifiers.py"
  - "engine/alternative_costs.py"
  - "engine/targeting.py"
  - "engine/legality*.py"
  - "engine/target_*.py"
  - "engine/stack_targets.py"
  - "engine/bare_announcements.py"
  - "engine/announced_creature_type.py"
  - "engine/spell_copies.py"
  - "engine/game_types.py"
  - "engine/mixins/stack/cast*.py"
  - "engine/mixins/stack/activation*.py"
  - "engine/mixins/stack/card_activation.py"
  - "tests/engine/test_cast_prohibition_readers.py"
  - "tests/engine/test_kg2_refusal_seam.py"
  - "tests/engine/test_target_requirement_census.py"
  - "tests/engine/test_targeting.py"
  - "tests/engine/test_activation_targeting.py"
  - "tests/regressions/test_kg3_seats_about_player.py"
---

# Casting, activating and targets

Part of `CLAUDE.md`, kept here so it loads when you open a file it
describes (the `paths` above). The root file's rule for editing applies,
and you can open this file directly whenever its subject is yours.

## Casting and activating

- `engine/cast_costs.py` — additional costs (CR 601.2b, f–h), including buyback
  and kicker as rewrites onto them, and entwine (`engine/entwine.py`, the same
  reader, mana and non-mana; a paid entwine is the choose-one-or-more cast
  naming every mode, and a mode's graveyard target rides
  `ChosenMode.target_graveyard_card`). An activated ability printing two costs
  ("{3}, {T} or {U}, {T}", the Mirrodin Shards) is one ability whose activator
  announces which (`alternative_cost_index`,
  `engine/activation_cost_alternatives.py`); every tax and reduction then
  applies to the one chosen. Whether a cost was paid rides
  `choices["additional_costs_paid"]`. "Kicked" has three readers at three times:
  a resolving spell (`was_kicked`), the permanent afterwards (`cast_costs.KICKED`
  / `KICKED_WITH`, since a card may print two kickers, CR 702.33b/f), and a cast
  trigger (`cast_kicked`); `target_was_kicked` asks it of the *targeted* spell.
  A permanent named to pay a cost pays it or the spell is not cast (CR 601.2h,
  `cast_additional_costs._named_cast_cost_refusal`). An alternative cost or
  waiver still owes
  what a tax adds (CR 118.9d, `Game.alternative_cost_mana`).
- `engine/flashback.py` — flashback (CR 702.34): a graveyard cast permission
  that requires an alternative cost (`CastPermission.cost`) and a destination as
  the card leaves the stack (`leaves_stack_to_exile`). `StackItem.flashback`
  says a cast was one; `has_flashback` takes the game (a grant counts).
- `engine/madness.py` — madness (CR 702.35): the keyword line compiles to a
  trigger (`keyword_lines.keyword_line_triggers`), the static half is a discard
  destination (`replacements/registry.DISCARD_INTO_EXILE`), and the trigger casts the
  card during its own resolution (CR 608.2g, `madness_cast`).
- `engine/refusals.py` — **a refused cast or activation is the actor's
  alone** (CR 733.1): `refuse(card_name, effect_kind, details)` is the only
  constructor of a refused result (a `Refusal`) and writes nothing; the four
  attempt wrappers take back what a refused attempt wrote
  (`take_back_refused_attempt`), safe because nothing is refused below the
  mana payment; a land's tap answers the same way
  (`tap_land_for_mana_or_refusal`). `game.log` is served whole to every
  seat. Held by `tests/engine/test_kg2_refusal_seam.py`.
- `engine/cast_prohibitions.py` — **may this card be cast at all** (CR 601.3):
  one ordered table behind `cast_prohibition(game, seat, card)`, asked by the
  cast path, the AI and the castable highlight. Each row says what it binds
  (CR 305.1: some bind land plays). `tests/engine/test_cast_prohibition_readers.py`
  fails a reader that calls a row's predicate itself.
- `engine/activation_prohibitions.py` — its CR 602.5 twin, behind
  `activation_prohibition`, asked by the activation path, the AI, the
  highlight, hand/graveyard activations and a land's tap
  (`Game.land_tap_prohibition`); refusals reach the client as
  `ability_denials`. Whether a non-mana cost can be paid is one question,
  `Game.unpayable_activation_cost` (CR 601.2h). The activation window's other
  pre-choice refusals are methods the wire asks too:
  `Game.loyalty_activation_refusal`, `tap_symbol_refusal` (CR 602.5a),
  `targeting_ban_activation_refusal`, `owner_only_activation_refusal`,
  `activation_limit_refusal`.
- `engine/cast_restrictions.py` / `engine/activation_restrictions.py` —
  text-keyed timing gates ("cast this spell only during…", "activate only if…").
  Ordered tables keyed by the printed clause, read by the path **and the support
  gate**, so a clause cannot be admitted and ignored. An unenforced restriction
  is an ability that works more often than the card allows — nothing crashes.
- `engine/cost_modifiers.py` (with `cost_modifier_lines.py` and
  `self_cost_modifiers.py`) — text-keyed cost taxes and reductions (CR 601.2f).
  Both directions are live; a generic reduction touches only generic mana, a
  coloured one spills its excess onto generic (CR 118.7a–d), and one that
  "reduces only the amount of colored mana you pay" (Edgewalker,
  `CostReduction.colored_only`) never spills — `reduce_cost`, in one place.
  Every price the wire shows is the one the cast charges:
  `cost_modifiers.cast_mana_charge` (increases, then reductions) is read by
  the hand badge, the castable highlight and `ways`.

## Targets

- `engine/targeting.py` — what a spell or ability targets, derived from the
  *compiled program*: `derive_cast_spec` per card, `derive_activation_spec` per
  ability, one kind→spec table. Returns None rather than guessing; the guards in
  `tests/engine/test_targeting.py` / `test_activation_targeting.py` ratchet what
  still needs `legality.py`'s one text fallback. A modal spell is held to the
  mode it announces (`cast_targets.announced_mode_instructions`, read by both
  gates,
  the picker and `Game.announceable_modes`).
- **The gates, in `engine/legality.py` and the `legality_*.py` modules beside it
  (`_cast_gates`, `_abilities`, `_stack`, `_resolution`), all over the picker's
  own list**
  (`_enumerate_targets`), so the engine and the picker agree:
  - `no_legal_cast_target_refusal` — a spell that must target cannot be cast
    with nothing to name (CR 601.2c);
  - `cast_target_refusal` / `cast_stack_target_refusal` /
    `stray_stack_target_refusal` — a named target must be one the picker offers,
    before mana is spent; `exact_target_count` makes a printed count a count;
  - `activation_target_refusal` / `activation_target_obligation` — the same for
    an ability, before any cost is paid; a named *cost* permanent is paid as
    named (`_named_cost_refusal`);
  - `illegal_targets_refusal` (CR 608.2b) — every target illegal at resolution,
    the object leaves unresolved — and `blank_illegal_resolution_targets`, which
    blanks each illegal slot before any instruction runs. Asked of every object
    whose targets somebody chose: spells, activated abilities
    (`StackItem.activated`) and triggers with a chosen target
    (`StackItem.targets_chosen`).
  Both announcement and resolution ask the same predicate,
  `CastTargetGatesMixin._described_cast_target_slots`, and read targets by
  `permanent_id`, never index. A named player is a target like any other
  (`stack_targets.announcement_targets`).
- **A headless announcement that names no target is answered once, as it is
  announced** (`engine/bare_announcements.py`): the first entry of the picker's
  own list, stamped on the stack object as a named target is, so CR 608.2b
  re-checks it. A count, an X, a role announcement, an Aura's target and a
  division are refused rather than defaulted.
- **"A source of your choice" is chosen, not targeted** (CR 609.7a,
  `legality.spec_chooses_a_source`); a Circle's shield binds the source named
  (CR 615.8).
- Roles: "counter target spell and … target creature" is a roles announcement
  with a stack role (`targeting.role_is_stack`, `target_role_refs` with a
  `stack_index`); "target spell or permanent" is one slot in either zone; a
  slot list of printed targets is a count
  (`target_descriptions.slot_list_is_exact`); "up to N
  target cards from a single graveyard" is `target_descriptions.SINGLE_GRAVEYARD`; two
  players may be two roles (`choices["role_seats"]`). `Game.stack_target_seat`
  is the controller of a targeted spell ("its controller"). An "up to one"
  slot is an optional role (`target_roles.OPTIONAL_ROLE`); "any number of
  target opponents / players or planeswalkers" is a chain of optional roles
  (Wheel and Deal, Kaboom!), "for each opponent, … target permanent that
  player controls" one mandatory role per live opponent
  (`target_roles.per_opponent_roles`, Blatant Thievery), and an empty
  `target_role_refs` on a cast names no target;
  "that player controls" after a seat role is a role relation
  (`same_controller_role`, `role_seat_of`); a seat a slot cannot carry (a
  pile's owner, a count's opponent, an opponent beside a division) rides the
  seat field as `target_descriptions.ANNOUNCED_SEAT`. A narrowing known only
  at announcement (Phyrexian Splicer's chosen keyword; the creature type a
  spell announces before its targets, Aphetto Dredging —
  `engine/announced_creature_type.py`) is asked with the word the cast or
  activation announces and rides the stack object.
- `engine/target_requirements.py` — a target an opponent **must** choose (the
  Flagbearers): two gates over a whole announcement, deliberately not a
  narrowing in `_enumerate_targets` (which also serves resolution, retargets and
  copies). Held by `tests/engine/test_target_requirement_census.py`.
- `engine/stack_targets.py` — **which targets a stack object chose**
  (`chosen_targets(item)`) and how they may change (CR 115.7). Every way an
  object comes to have targets announces it once through
  `Game.announce_targets_chosen`; "becomes the target" triggers hang off it.
  A copy whose targets may be chosen anew is pushed unannounced and announced
  once they are decided (`Game.announce_copy_put_onto_stack`, CR 707.10c):
  becomes-the-target, "chooses targets" only where one moved, then put onto
  the stack. Every copy road offers them through one offer
  (`spell_copies.offer_new_targets`): a prompt for a seat somebody asks, the
  measured answer for one nobody asks, slot by slot for several targets or a
  mode (`change_slots`, CR 115.7d's `new_target_options`). A spell judged from outside its own
  resolution (a retarget, a copy's new target, Grip of Chaos) is read as it
  is — its colour and text (`_enumerate_targets(stack_item=…)`,
  `object_colors.judging_targets_of`) — and a spell's one target may be
  another stack object (`targeting.single_spell_target`'s `"stack"` answer;
  a retargeting spell is a legal new target while it resolves).
  **The object a trigger is about is never its target**: a fire site records it
  as `StackItem.about_permanent_id` only for a line that names no target of
  its own (`trigger_utils.bound_event_object`), and the context builder hands
  it to the effect. The seat it is about ("that player": whose upkeep, who
  caused the discard, whom the attack was at, a delayed ability's bound
  player, the controller whose attachment or unblocked attacker it is) rides
  `StackItem.about_player_index`; `target_player_index` is a choice and only a
  choice, and the context builder hands the about seat over where nothing
  chose one (`tests/regressions/test_kg3_seats_about_player.py`). A player
  role in an activated ability is judged at resolution by whether that role
  still offers the player (`Game.role_seat_is_offered`, CR 608.2b).
  `target_permanent_id` is `None` or a list of ids on every
  holder (`game_types.check_target_ids` on each write), read through
  `target_ids` / `single_chosen_id` / `first_target_id`;
  `target_permanent_index` has the same one shape (`check_target_slots`;
  `target_slots` / `single_slot` / `first_slot`), is consumed into ids at
  the push (`_stamp_stack_targets`), so a stack object carries none, and
  every resolution context re-derives it from the ids
  (`bare_announcements.resolving_slots`). A graveyard target is its stamp
  (`target_graveyard_card`, None or a list, `check_graveyard_stamps`), read
  through `handlers/_targets.chosen_graveyard_slots`. The API keyword still
  takes a slot (SET_PLAYBOOK's Known gaps).
