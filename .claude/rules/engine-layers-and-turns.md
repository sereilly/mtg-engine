---
paths:
  - "engine/models.py"
  - "engine/continuous.py"
  - "engine/layer_bridge.py"
  - "engine/type_layer.py"
  - "engine/type_statics.py"
  - "engine/type_changes.py"
  - "engine/printed_characteristics.py"
  - "engine/copies.py"
  - "engine/text_changes.py"
  - "engine/keywords.py"
  - "engine/color_changes.py"
  - "engine/fast_paths.py"
  - "engine/late_modules.py"
  - "engine/graveyard_statics.py"
  - "engine/graveyard_order.py"
  - "engine/control.py"
  - "engine/aura*.py"
  - "engine/equipment.py"
  - "engine/commander.py"
  - "engine/combat_restriction*.py"
  - "engine/untap_restrictions.py"
  - "engine/draw_step_modifiers.py"
  - "engine/land_animation.py"
  - "engine/land_play_allowance.py"
  - "engine/landwalk.py"
  - "engine/mana_could_produce.py"
  - "engine/counter_conditions.py"
  - "engine/game_over_guard.py"
  - "engine/phases/**"
  - "engine/mixins/*.py"
  - "web/actions.py"
  - "scripts/integration/checked_sim.py"
  - "tests/engine/test_color_write_seam.py"
  - "tests/engine/test_control_reads.py"
  - "tests/engine/test_effective_card_fast_path.py"
  - "tests/engine/test_kg3_textspell_spell_text_reads.py"
  - "tests/engine/test_layer_reads.py"
  - "tests/engine/test_scg_p5_game_over_stepping.py"
  - "tests/engine/test_static_line_support.py"
  - "tests/regressions/test_announced_target_seat.py"
  - "tests/regressions/test_derived_card_memo_identity.py"
---

# Layers, control, the board and the turn

Part of `CLAUDE.md`, kept here so it loads when you open a file it
describes (the `paths` above). The root file's rule for editing applies,
and you can open this file directly whenever its subject is yours.

## Layers, control and the board

- `engine/graveyard_statics.py` — **a static that functions from a graveyard**
  (CR 113.6b: the Incarnations, Riftstone Portal). A graveyard card whose
  static is stamped `functions_from: "graveyard"` is a source the lord
  recompute gathers beside the battlefield's, with the CR 613.7d timestamp of
  its arrival there (`engine/graveyard_order.py`, recorded only for such cards).
  **A new `PlayerState` or `Game` field is read by every `vars()` walker** — the
  rehearsal's `position_digest` and the AI censuses' board signatures: a field
  that moves on every resolution reads as a lasting change unless it is
  listed as bookkeeping (`ai_rehearsal._PLAYER_BOOKKEEPING`, or
  `_GAME_BOOKKEEPING` for a `Game` field).
- `engine/continuous.py` + `engine/layer_bridge.py` — the CR 613 layer system
  (the bridge collects layers 2, 5, 6 and 7 and holds the computed accessors;
  layer 4 is `engine/type_layer.py`, and the printed seed every layer starts
  from, which is also the answer off the battlefield, is
  `engine/printed_characteristics.py`). Characteristics are **computed**:
  `has_type`, `is_creature`, `effective_power`, `has_keyword`, the colour
  accessors and `Game.controller_index_of` resolve through it. Reading
  `card.type_line` or a metadata flag instead is the bug class
  `tests/engine/test_layer_reads.py` guards. **"What does it say?" is `Permanent.effective_card`** (layer 1 copy,
  layer 3 text change, granted abilities); `perm.card.oracle_text` and
  `perm.card.keywords` are the card as printed — except a face-down object's,
  whose `card` is the blank 2/2 (CR 708.2) — and a keyword also wants
  `_has_keyword` (layer 6). A spell's is `text_changes.spell_text_card(item)`
  (CR 612.1 on a stack object; `item.card` is the printed card that moves,
  held by `tests/engine/test_kg3_textspell_spell_text_reads.py`).
  - Folds are memoised by what the card *is* (`copies.card_identity`), **never by
    `id()`** — CPython reuses a freed object's address.
    `tests/regressions/test_derived_card_memo_identity.py` fails a module-level
    dict under `engine/` keyed by `id()`, or one whose validity stamp is
    built from `id()` (stored in it or compared with what it holds).
  - **Most reads have nothing to fold and skip the fold**: with every key in
    `models.fold_channels()` empty, `effective_card` returns the printed card
    (and `computed_types` likewise over `type_layer.TYPE_EFFECT_CHANNELS`;
    `has_type` / `is_creature` / `has_supertype` answer from the seed's
    frozensets through `layer_bridge.has_computed_type` / `has_computed_supertype`).
    The first question is one set test, in C, over the record's keys
    (`models.fold_channel_set`; `card_before_layer_6` and
    `card_through_layer_3` ask it too); a permanent whose only filled channel
    is its attached Auras is folded by the attachment loop alone
    (`Permanent._folded_attachments` — most folds that run: a creature wearing
    a pump or a Pacifism).
    A shortcut is a predicate over the current state, never a remembered
    answer: a text reader may be cached on its text (the Aura readers are),
    and a state-based sweep asks its cheap metadata test before a layer read,
    but nothing skips a recompute "because nothing changed" (ROADMAP, "The
    folds that do run").
    **A channel the fold starts reading belongs in that tuple**
    (`tests/engine/test_effective_card_fast_path.py`).
    `engine/fast_paths.CHECKING` recomputes every shortcut the long way; run the
    seeded games under it (`scripts/integration/checked_sim.py`) after touching
    a fold.
  - Hot accessors reach a later-loading module through
    `engine/late_modules.LateModules`, never a function-level import.
  - Layer 5 is ordered by timestamp (CR 613.7): colour is written through
    `color_changes.change_color` (`tests/engine/test_color_write_seam.py`).
    Layer 4 is applied once for the whole board with dependency (CR 613.8,
    `engine/type_statics.py`); one-shot type changes go through
    `type_changes.gain_types` / `lose_types`. "Loses all abilities" is layer 6
    by timestamp (`keywords.abilities_lost_at`). Layer 7 is applied in sublayers,
    each by timestamp (CR 613.4).
  - CR 305.7 is one strike, in `effective_card` (a land whose type an effect
    *set* has no ability of its own, and keeps what another effect granted).
  - A permanent enters as the board will make it (CR 614.12,
    `Game.fold_board_statics_onto_entering`).
  - Continuous effects are recomputed at the resolution seam, not by each
    handler.
- `engine/control.py` — CR 613 layer 2. A control change is a **contribution**
  (`change_control(permanent, seat, source=…)`) with a timestamp, ended by
  `end_control_change`; `base_controller_index` is never rewritten.
- **The control seam on `Game`** (`engine/mixins/control_seam.py`):
  `all_permanents()`, `permanents_with_controller()`, `controlled_by(seat)`,
  `permanents_matching(pred)`, `controller_index_of(perm)`, `controls(seat,
  perm)`, `is_on_battlefield(perm)`. **Never iterate `player.battlefield`
  directly** — the lists are a projection of the derived controller, and `in` /
  `.remove()` compare by value. Guarded by `tests/engine/test_control_reads.py`.
  - **Address a permanent by its id, not its slot**: `Permanent.permanent_id`
    (new on each entry, CR 400.7), resolved through `permanent_by_id` /
    `find_permanent_by_id` / `permanent_id_of`. `.battlefield.index()` /
    `.remove()` are banned; positional subscripting is ratcheted per module.
    The wire carries `id` and resolves it once at the top of `web/actions.py`
    (a stale id is a 404). The combat declarations and assignments too:
    `web.actions.COMBAT_ID_FIELDS` turns `attacker_ids`,
    `blocker_pairs_by_id`, `attacker_damage_by_id`, … into the engine's
    slot-keyed combat maps, each id checked against the battlefield its
    position is read on, and refuses the slot fields from a client (tests
    post them through `tests.helpers.combat_ids`).
  - **An id names a battlefield as well as an object**:
    `Game.announced_target_seat` settles an announcement's seat from its ids,
    before the cost is paid, and `resettle_announced_target_seats` asks again as
    the object resolves. Held by `tests/regressions/test_announced_target_seat.py`.
  - **Leaving the battlefield is one transition**:
    `remove_from_battlefield(perm)` / `remove_all_from_battlefield(perms)` —
    and what phased out "until this leaves the battlefield" (Oubliette,
    `phasing_locks.PHASED_OUT_UNTIL_SOURCE_LEAVES`) phases in from it, tapped
    as printed (`Game.phase_in_what_waited_for`).
  - Combat maps are index-keyed but follow their creatures
    (`_renumber_combat_after_removal`); a new combat map is added there, and
    a new combat request field goes in `COMBAT_ID_FIELDS`. A blocker whose
    attackers have all left combat stays in `combat_blockers` with an empty
    list (CR 509.1g): ask the state through `Permanent.is_blocking`, whom it
    blocks through `creatures_blocked_by`.
- `engine/auras.py` — what an Aura's effect lines say and whether they are
  implemented (the support gate); its continuous effects while attached are
  `aura_grants.py` and `aura_restrictions.py`. Use `attach_aura` / `detach_aura`
  (`aura_attachment.py`). The templates read "enchanted" and "equipped"
  alike (CR 301.5f).
- `engine/equipment.py` — Equipment (CR 301.5), equip as a rewrite, attach
  (CR 701.3); `equip_refusal` is the one legality predicate for moving an
  Equipment, also asked by the CR 704.5n sweep and by the AI's equip planner,
  and the activation's target picker asks `equip_target_refusal` (an
  Equipment that is a creature may activate equip, which then does nothing,
  CR 301.5c). An Equipment is supported only if its equip ability compiles
  and every effect line is claimed.
- Text-keyed derivation tables (parameters are payload, and the support gate
  reads the same table the dispatch does): `combat_restrictions.py` (CR 506; its
  rows in `combat_restriction_table.py`),
  `untap_restrictions.py` / `draw_step_modifiers.py` (CR 502/504),
  `land_animation.py`, `land_play_allowance.py` (CR 305.2), `landwalk.py`,
  `mana_could_produce.py`, `counter_conditions.py`. A table joins the grammar's
  `registry_for_line` for its line to parse, which is what
  `tests/engine/test_static_line_support.py` asks.
- `engine/commander.py` — CR 903 (Commander and Brawl), inert unless
  `Game.commander_variant` is set. Colour identity is derived, not read off
  the ingested field; the designation is per-seat, by card-object identity.

## Turn structure

- `engine/phases/` — one mixin per phase and step (CR 500–514), composed onto
  `Game`; phase/step turn-based logic goes here. The declaration steps have
  `attack_legality.py` (CR 508.1c), `attack_requirements.py` (CR 508.1d),
  `block_legality.py` (CR 509.1b) and `block_requirements.py` (CR 509.1c) —
  each requirements module the requirement list and the maximisation that
  judges a declaration and the AI's proposal — and `block_triggers.py` beside
  them, and the combat damage step has `combat_damage_assignment.py` (CR
  510.1) beside it. The cleanup step gives priority when a state-based action
  or a trigger needs it (CR 514.3a: active player first, an offer round on the
  empty stack, then another cleanup step, bounded by `_MAX_CLEANUP_ROUNDS`) —
  at a table a priority driver plays; a person is not yet asked there
  (SET_PLAYBOOK's Known gaps).
- `engine/mixins/` — cross-cutting flow not tied to one step: priority and step
  navigation (`phase_steps`), per-turn and pregame management, state-based
  actions, effects, helpers. Consumes compiled programs; must never parse oracle
  text. **A step does not end on an empty stack alone**:
  `_resolve_priority_window` makes the state check before closing and goes round
  again if it put something on the stack, **the check is made between
  resolutions, inside the resolution's trigger window** (`resolve_next_object`
  → `_check_between_resolutions`, CR 704.3), and
  **after each step's turn-based actions, before its first priority**
  (`_check_after_turn_based_actions`, CR 703.3). **At a table with a person,
  a step does not end while its stack is owed** (CR 500.2, 608.2): every
  site that leaves a step asks `window_left_unfinished()` (anything on the
  stack, or `awaits_an_answer()`); a step that must wait is held
  (`Game.held_step`) and resumes at its window, so its log line and sweeps
  run once, and the web's `turn_steps._leave_step` answers an AI seat's held
  prompt in the same request. **Once the game is over the engine's stepping
  goes no further** (CR 104.1): every stepping entry point wears
  `game_over_guard.goes_no_further`, held to every stepping-named `Game`
  method by `tests/engine/test_scg_p5_game_over_stepping.py`.
- `engine/mixins/stack/` — the stack (CR 405), one family of mixins per stage:
  `casting` with `cast_announcement`, `cast_additional_costs`,
  `cast_alternative_costs`, `cast_target_validation` and `pool_payment`
  (CR 601; `_cast_onto_stack` calls one helper per CR 601.2 step); `activation`
  with `activation_checks`, `activation_payment`, `activation_charges` and
  `card_activation` (CR 602); `resolution` with `trigger_targets` and
  `triggered_abilities` (CR 603/608); and the `choices` package (the prompt
  queue, one module per prompt family, and `table.py`).
