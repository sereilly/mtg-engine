---
paths:
  - "engine/trigger_*.py"
  - "engine/state_triggers.py"
  - "engine/mixins/stack/resolution*.py"
  - "engine/mixins/stack/trigger_targets.py"
  - "engine/mixins/stack/triggered_abilities.py"
  - "engine/mixins/stack/choices/**"
  - "engine/mixins/entry_choices.py"
  - "engine/phases/declare_blockers_step.py"
  - "engine/phases/upkeep_effects.py"
  - "engine/phases/divided_damage_wait.py"
  - "engine/pending_choices.py"
  - "engine/enter_effects.py"
  - "engine/entry_choices.py"
  - "engine/combat_assignment.py"
  - "web/prompt_*.py"
  - "web/action_prompt_*.py"
  - "tests/regressions/test_kg_prompts_answered_choice_leaves_queue.py"
  - "tests/ui/test_entry_choice_prompt_ui_api.py"
  - "tests/engine/test_entry_trigger_*census.py"
---

# Triggers and prompts

Part of `CLAUDE.md`, kept here so it loads when you open a file it
describes (the `paths` above). The root file's rule for editing applies,
and you can open this file directly whenever its subject is yours.

## Triggers

- **A permanent's entry trigger is a stack object** (CR 603.3), on every road
  onto the battlefield. **A test that casts a permanent and asserts its entry
  effect must drain the stack first** (`tests.helpers.resolve_stack`). The
  target is named as the permanent is cast (`announced_at_cast`) but is the
  trigger's, never the spell's (a creature spell targets nothing, CR 115.1;
  `stack_targets.permanent_spell_targets_nothing`), and is held to what the
  trigger itself could choose (CR 603.3d,
  `CastTargetSpecMixin.entry_trigger_cast_targets`). A source can leave before
  its own
  entry trigger resolves, so a handler moving something "until this leaves the
  battlefield" asks `linked_exile.until_leaves_has_ended` (CR 610.3b; a
  phased-out source has not left). Censuses:
  `test_entry_trigger_stack_census.py`, `test_entry_trigger_source_leaves_census.py`
  — a census that seats a person answers an entry's "as it enters" prompt
  before looking for its trigger: the entry waits on its way (CR 614.12a)
  and has not triggered (CR 603.6a; `_answer_the_entry`).
- **A cast trigger's "it" is a stack object, not a card** — the cast events carry
  `cast_item`, read by `handlers/_targets.triggering_spell`.
- `engine/state_triggers.py` — a state trigger about another permanent, and CR
  603.8's latch both ways (no retrigger while on the stack; retrigger once it
  left without resolving).
- `engine/trigger_order.py` — a controller orders the triggers they put on the
  stack together (CR 603.3b). A re-entrant window
  (`Game.putting_triggers_on_stack`) wraps each unit of play; when the outermost
  closes, each interactive seat with two or more distinguishable triggers is
  asked (`order_triggers`). A seat nobody asks keeps the fire sites' order.
  **A trigger chooses its mode and targets as that window closes** (CR
  603.3d, 117.5): one pushed while a window is open and still owing a choice
  waits on `Game.unannounced_triggers` and is announced, oldest first, after
  the event and its state-based check — a resolution's check included
  (`resolve_next_object`), and for a resolution held for an answer, after its
  release (`StackItem.held_triggers`); every answer is a window — so a
  sweep's dying creatures are never offered; `resolve_top_of_stack` announces
  anything still waiting. **A trigger set off while triggers are being put on
  the stack is CR 603.3b's next round** (`Game.announcing_trigger_round`): the
  ordering is asked per seat per round (`StackItem.trigger_round`), and a later
  round sits above.
- **A trigger fires only from the zone it functions in** (CR 113.6m):
  `trigger_utils.matching_triggers` (the battlefield by default) and
  `battlefield_triggers` never yield an ability stated for another zone
  (`trigger_functions_from`); the graveyard and exile scans name theirs.
- **"Attacks and isn't blocked" triggers as the declaration of blockers
  completes** (CR 509.3g), in that declaration's trigger window before the
  active player's priority (CR 509.2a): the last defender's
  `declare_blockers`, or `Game._lock_block_declaration` where nobody left had
  a legal block; at a table with a person a lock that put something on the
  stack gives the active player priority and keeps the step. **A turn with no
  attack skips declare blockers and combat damage** (CR 508.8) at the one
  seam that enters them (`_leave_combat_step`,
  `Game.combat_skips_blocks_and_damage()`, by the declaration, not the live
  attacker map).
- `engine/phases/upkeep_effects.py` — `@upkeep_effect(condition, kind)` for the
  pay-or-consequence upkeep triggers; a duplicate pair raises at import.

## Prompts

- `engine/pending_choices.py` — every other decision a seat owes part-way
  through a spell, an ability or a step: one `PendingChoice` queue on
  `Game.pending_choices` and one `ChoiceSpec` per kind (how it is answered,
  what a non-interactive seat does, which action answers it, how the web
  renders and gates it), defined beside its resolver in its family's module
  and registered by `engine/mixins/stack/choices/table.py`'s one
  `register_choices(...)` list, in an order that is behaviour.
  **Adding a prompt is its `<KIND>_SPEC` row and its answer, together in the
  family module of `engine/mixins/stack/choices/` (an entry-time prompt's,
  beside `entry_exile`'s and `entry_reveal`'s, in
  `engine/mixins/entry_choices.py`) + its name appended at the bottom of
  `table.py`'s list + one renderer in `web/prompt_cards.py`,
  `prompt_board.py` or `prompt_values.py` (by what the prompt is answered
  with) and its `@action_handler` in the matching
  `web/action_prompt_cards.py`, `action_prompt_board.py` or
  `action_prompt_values.py` + the code that arms it + a scenario in
  `tests/regressions/test_kg_prompts_answered_choice_leaves_queue.py`** — never a
  new `Game` field. The queue closes an accepted answer itself
  (`_close_answered_choice`, in both answer funnels).
- **While a prompt is owed, the game waits** (CR 608.2, 117.3b): a prompt on
  either queue armed mid-resolution records its stack object, which stays on
  the stack until its last prompt (including one armed by answering an
  earlier one) is answered, at a table with an interactive seat or a prompt
  driver (`Game.holds_for_answers`); a bare headless table pops it and its
  caller drains.
  `ChoiceSpec.holds_priority` is derived from `blocked_detail`.
- `secret_number` is hidden until the last answer (written to the scratchpad
  only). A private look stays private in the log (`Game.find_is_public`); "the
  rest in any order" is the looker's order (`Game.offer_library_bottom_order` /
  `offer_library_top_order`). A sentence that asks each player waits for the
  last answer before acting (`new_keep_batch` / `finish_keep_batch`); a choice
  each player makes **in turn order** (CR 101.4, each seeing the earlier
  answers) is `resumption.ask_in_turn_order` — each player choosing a creature
  type, the each-seat discards and hand picks, each player choosing
  permanents, each player's sacrifice and Cataclysm's keep (chosen in turn
  order, performed together in the round's last step) — while "each player
  **secretly** chooses a number" arms every seat at once
  (`secretly_choose_numbers`); Balance
  is three rounds, each counted as it starts and asked one seat at a time in
  turn order (`_finish_balance_round`).
- `engine/enter_effects.py` — entry-state phrases `_initialize_permanent_state`
  carries out; `enter_effect_line` is read by the support gate *and* the grammar.
  `ENTRY_CHOICES` (`engine/entry_choices.py`) is what a permanent may choose
  as it enters, and
  `web/serialization` derives `entry_choices` from it. **The client must be able
  to answer the prompt**: `tests/ui/test_entry_choice_prompt_ui_api.py` enters
  every chooser under an interactive seat.
- `engine/combat_assignment.py` — "assign its combat damage as though it weren't
  blocked" is an announcement with two answers, not a `pending_choices` prompt.
  Who announces is `Game.combat_damage_assigner` (the defender under banding /
  Defensive Formation, CR 702.22j). An assignment is checked whole by one gate
  for both seats (`_attacker_division_refusal`, CR 510.1c–e), and each damage
  step is its own announcement (CR 510.4). A trampler blocked by one creature
  with more than lethal to assign is a manual assignment for an interactive
  assigner (`trample_assignments_to_ask`, CR 702.19b); an attacking seat
  nobody sits in keeps lethal-then-the-rest, and a defending one that assigns
  (banding, Defensive Formation) keeps all of it on the blocker
  (`defender_assignments_owed` lists it for every defending seat;
  `ai_combat.choose_defender_damage_assignment`). A block spread across a
  band (CR 702.22h) is kept when the member it was declared on leaves combat
  (`_keep_band_blocks_past`). A division among the defending
  player and their creatures (Butcher Orgg) has its own gate
  (`divided_among_defenders_refusal`), and the step waits for an interactive
  controller's answer (`engine/phases/divided_damage_wait.py`).
