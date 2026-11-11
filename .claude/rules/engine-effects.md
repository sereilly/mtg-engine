---
paths:
  - "engine/handlers/**"
  - "engine/replacements/**"
  - "engine/prevention/**"
  - "engine/subject_filters.py"
  - "engine/pt.py"
  - "engine/tokens.py"
  - "engine/characteristic_defining.py"
  - "engine/static_bonuses.py"
  - "engine/piles.py"
  - "engine/counted_names.py"
  - "engine/object_colors.py"
  - "engine/object_creature_types.py"
  - "engine/color_census.py"
  - "engine/turn_replacements.py"
  - "engine/replacement_choices.py"
  - "engine/shields.py"
  - "engine/effect_ordering.py"
  - "engine/resumption.py"
  - "engine/damage_events.py"
  - "engine/simultaneous_damage.py"
  - "engine/damage_redirects.py"
  - "engine/destruction_events.py"
  - "tests/engine/test_subject_filters.py"
  - "tests/engine/test_kg3_dealings_one_dealing_census.py"
  - "tests/engine/test_kg3_types_off_battlefield_reads.py"
  - "tests/engine/test_kg4_asks_replacement_sites.py"
  - "tests/engine/test_kg_colour_off_battlefield_reads.py"
---

# Executing effects; replacement, prevention and CR 616

Part of `CLAUDE.md`, kept here so it loads when you open a file it
describes (the `paths` above). The root file's rule for editing applies,
and you can open this file directly whenever its subject is yours.

## Executing effects

- `engine/handlers/` — `@effect_handler(kind)` functions, registered into
  `EFFECT_HANDLERS` and dispatched by dict lookup; a new handler module joins
  the import list in `engine/handlers/__init__.py`. The helpers handlers share
  are floors: `_targets.py` (target resolution, `pick_target_permanent`, roles),
  `_filters.py` (filter matching), `_amounts.py` (counts and amounts),
  `_chosen.py` ("the chosen ..." words), and `_common.py` (shared actions,
  damage application).
- `engine/handlers/control_flow.py` — `sequence`, `if_then`, `may`, `for_each`
  (its conditions are in `_conditions.py`, `_record_conditions.py`,
  `_color_conditions.py`).
  Compose effects through these, never a fused kind
  (`deal_damage_and_gain_life` is two steps in a `sequence`); values pass
  through `OracleExecutionContext.results`.
- `engine/subject_filters.py` — what a printed noun phrase means, tested against
  one permanent. `subject_matches` is the one answer and
  `TESTABLE_SUBJECT_FILTER_KEYS` names what it tests; a compiler admits a
  narrowed line only when every payload key is in that set, or the restriction
  would be silently ignored. `OBJECT_ONLY_FILTER_KEYS` is what a caller with no
  observer or source may be handed. Each key is demonstrated in
  `tests/engine/test_subject_filters.py`.
- `engine/pt.py` — the single write API for power/toughness (`set_base_pt`,
  `add_pt_modifier`, `switch_pt`); never poke metadata.
- `engine/tokens.py` — `make_token_card(...)` with the generic `create_token`
  kind. A token-making card is one parse rule, never a bespoke handler.
- `engine/characteristic_defining.py` (CR 604.3, one `dynamic_pt_count`
  instruction) and `engine/static_bonuses.py` (conditional static P/T, layer 7c,
  both word orders).
- `engine/piles.py` — separating into piles (CR 700.3): one
  `separate_into_piles` instruction, one seat splits, another chooses, each
  pile's fate is payload; nothing moves until the last answer.
- `engine/counted_names.py` — whether a card answers to a name (CR 201.2a over a
  set of names) and "effects … count it as a card named X".
- `engine/object_colors.py`, `engine/color_census.py` — colour as a relation
  (`share_a_color`, `is_multicolored`, `of_each_color`) and as a count, both
  read through the layers. A card off the battlefield is asked through
  `object_colors.card_colors` with its seat (Celestial Dawn): every card
  matcher takes keyword-only `game=`/`owner=` and every call names both
  (`tests/engine/test_kg_colour_off_battlefield_reads.py`) — and its creature
  types through `object_creature_types.card_creature_types` (Conspiracy, CR
  205.1a; `tests/engine/test_kg3_types_off_battlefield_reads.py`).

## Replacement, prevention and the CR 616 process

- `engine/replacements/` — CR 614 interceptors, one module per kind of event,
  each a pure
  `applies` predicate plus the effect, an explicit `order`, and a required
  `label` and `sources` (as for prevention, below). An interceptor
  produces no instruction, so a permanent whose only ability is one is held up
  by `REPLACEMENT_LINES` (`replacements/lines.py`; read by the grammar's parse
  claim and the support gate) — adding an interceptor means adding its line there.
- `engine/turn_replacements.py` — a replacement **a resolving spell creates for
  the turn**: a `TurnReplacement` record with a lifetime and a CR 614.5 key,
  ended by one `clear_turn_replacements` at cleanup. A new one adds a field or
  an event value, never a `Game` field.
- `engine/replacement_choices.py` — an optional replacement offers a
  `ReplacementChoice`; a `@replacement_choice(kind)` resolver finishes it, for
  an interactive seat (queued) and every other seat (default) alike. A queued
  one is a prompt like any other: stamped with the object resolving
  (`_stack_item`), it holds that object and suspends the loop its event was a
  step of, and is answered inside `_answer_pending_choice`.
- `engine/prevention/` — CR 615 shields, `@prevention_effect(order, applies=…,
  label=…, sources=…)` over one `{recipient, amount, source, combat}` event
  (recipient a player or a permanent): `label` is what the effect does (one
  line, never a docstring) and `sources` reads what generates it for the
  event, so the `effect_order` option is "<label> (<sources>)"
  (`effect_ordering.option_text`; a face-down source named as every seat sees
  it). The statics a permanent prints over itself or what it wears are
  `prevention/static.py`, over others `prevention/blankets.py`. A new "prevent …" card is an entry here, never a branch in a
  damage path. `engine/shields.py` is the state they read: one `Shield`
  collection per recipient with what it answers to, amount, uses and lifetime —
  never a new `PlayerState` field and never a clearing line in a turn step.
- `engine/effect_ordering.py` — CR 616.1: gather every applicable effect, the
  affected player chooses one, apply, re-ask (616.1f). That is why applicability
  is a separate, pure predicate. A re-runnable caller passes a `restart` thunk
  (or `asks=True` to a damage entry point) so a contended choice can be asked;
  a move whose every contending effect sends the object somewhere else asks
  through `answered_restart` (a suspended move reports "did not arrive",
  whatever is answered); an entry asks the same way and tells its suspension
  apart (`_begin_entry` returns `entry_awaiting.ENTRY_SUSPENDED`; the answer
  re-runs the entry and then the caller's `then`,
  `ZoneFunnelsMixin._enter_answered_entry`, and a newcomer that asks leaves
  its event), and Worms of the Earth's "can't" is its own event,
  `cant_enter_battlefield`, never a contender (CR 614.17c). Events the
  registry spells separately but CR 616.1 treats as one are one contention
  set (`apply_replacements(..., joined=)`): a death is `would_die` +
  `would_leave_battlefield` + `put_into_graveyard`; a discard's destination
  (`Game.discarded_card_destination`), which both discard seams settle
  through — the chosen one passing `leng_declined` when its prompt offered
  the library top — is `discard` + `put_into_graveyard`.
  `tests/engine/test_kg4_asks_replacement_sites.py` classes every call site:
  asks, one registered effect, or declined. A seat nobody asks takes
  `choose_effect`'s stated order, except a damage event's first contended
  round, measured on scratch copies (`engine/measured_effect_order.py`:
  least loss to the affected seat; a tie keeps the stated order).
- `engine/resumption.py` — a loop records the rest of itself before each step,
  so answering resumes the targets, instructions and tail behind it. **A loop
  using it must be the last thing its function does**; what follows the loop
  is its own last step (`run_resumable(..., then=)`).
- `engine/damage_events.py` — a damage event start to finish (CR 120.4's two
  halves, with 616.1's contention set inside each); `deal_damage` returns both
  numbers. Every damage path calls it. It carries who dealt the damage,
  `damage_source_seat`, derived inside (a permanent's controller, the last
  controller of one that left — `control.LAST_CONTROLLER` /
  `Game.controller_or_last_known` — else `Game.resolving_seats[-1]`, CR 109.5)
  — restored while a prompt's answer re-runs the event and the loop behind
  it: a prompt on either queue is stamped with what was resolving as it was
  armed (`replacement_choices.stamp_resolving`: the cause seat and
  `Game.resolving_targets`' entry, a divided spell's targets included), and
  `_answer_inside_its_window` pushes both for the answer.
- **Damage dealt at once is one event** (CR 603.2c, 608.2f): the combat damage
  step and every spell or ability dealing damage to several recipients open
  one dealing (`simultaneous_damage.deal_at_once`; a split damage sentence's
  `sequence` carries `oracle_types.ONE_DEALING`: its steps run in printed
  order while the dealing collects their chunks at the two damage seams,
  `begin_sentence` / `collect`, and its last step, `deal_sentence`, deals them
  as one loop in APNAP order of the seat each chunk's CR 616.1 question goes
  to, printed order within a seat), and a damage trigger naming one end of it
  — delayed ones included — is announced once, for that end's total. A new
  loop dealing damage to several recipients goes through `deal_at_once`
  (`tests/engine/test_kg3_dealings_one_dealing_census.py`).
- **A source-keyed "next time" is one instance — everything its source deals
  in one simultaneous dealing** (CR 615.8; the owner's ruling, 2026-11-07): a
  one-use `Shield`, `DamageRedirect`, `next_damage` rider or
  `next_damage.DamageMirror` (Eye for an Eye) spent on a chunk
  of an open dealing (`damage_redirects.dealing_moment`) opens a
  `shields.SharedNextTime` (`by_source`) there — open for that source's other
  chunks, closed by `simultaneous_damage.finish` — and a source-keyed shield's
  CR 615.5 additional effect runs once, with the total, as the dealing
  finishes (`prevention.shields._spend(afterward=)`); a share shield (Dark
  Sphere's half, Forcefield's all but 1) takes its share of the instance's
  total (`Shield.would_prevent`, `simultaneous_damage.still_to_come`). Two
  printed sentences are two instances (CR 608.2c; a divided instruction
  marked `oracle_types.SEPARATE_DEALINGS` deals each target its own event);
  CR 615.7's numeric shields stay per point; the recipient-keyed template
  (Glarecaster) is one dealing wide too.
- `engine/destruction_events.py` — a destruction (CR 701.8) is one event,
  announced where it is decided (after indestructible, regeneration and a land's
  shield decline) and carrying its cause; a sacrifice or a state-based move to
  the graveyard is not one.
