# Engine Architecture

The engine is built so that card support grows by **adding registry entries**,
never by editing core control flow. Every extension point is a small function
in a category module; dispatch is data-driven.

## Pipeline

```
cards/manifest.json → the set JSONs it registers (card_loader.manifest_set_paths)
   │  card_loader.load_cards
   ▼
CardDefinition (immutable)
   │  oracle.compile_card_oracle        ← cached: each card compiles once per process
   │    ├─ engine/grammar/                    per line: tokenize → AST → lower
   │    └─ card_hooks.CARD_LINE_INSTRUCTIONS  one printed line of one card
   ▼
OracleProgram
   ├─ instructions          (primary effects, e.g. deal_damage)
   ├─ activated_abilities   (cost + instruction)
   ├─ triggered_abilities   (TriggerCondition + instruction)
   └─ static_lines          (keywords, static buffs)
   │  Game mixins (stack/casting → oracle_instructions)
   ▼
EFFECT_HANDLERS[instruction.kind](game, instruction, context)   ← O(1) dict dispatch
```

**One parser.** `engine/grammar/` reads a line; where it refuses,
`card_hooks.CARD_LINE_INSTRUCTIONS` supplies the reading of one printed line of
one named card. There is nothing after that — a line neither claims produces no
instruction, and the card is reported unsupported naming the clause. The flat
`@parse_rule` registry in `engine/parsing/` (2,303 lines of substring
predicates hand-ordered against one another, which claimed a clause on a prefix
and dropped whatever followed) is deleted. See "Grammar front end" below.

## Packages

| Package / module | Role |
| --- | --- |
| `engine/oracle_types.py` | Shared dataclasses (`OracleInstruction`, `OracleProgram`, …) and text helpers. No engine imports — safe to import from anywhere. |
| `engine/events.py` | Trigger event bus: `emit(game, kind, **payload)` announces something that happened and enqueues every matching triggered ability in APNAP order. `@event_filter(kind)` registers per-kind applicability predicates ("…casts a *blue* spell"). Prefer this over adding another hand-placed `iter_triggered_abilities` scan. |
| `engine/continuous.py` | The CR 613 layer system: layers, sublayers, timestamps, and dependency. Pure — it computes characteristics from effects and never touches game state, so it is tested directly against the rule text. |
| `engine/layer_bridge.py` | Adapter from the engine's stored channels to `ContinuousEffect`s (layers 6 and 7 today). The seam that lets storage change without touching the rules logic. |
| `engine/keywords.py` | Single write API for keyword abilities (layer 6): `grant_keyword` / `remove_keyword`, recorded in order with timestamps. Never set a `gains_<keyword>` flag by hand — grants and removals share a layer, so only the recorded order can decide which wins. |
| `engine/copies.py` | Single write API for copy effects (layer 1, CR 707): `become_copy` records the copied object's *copiable* values, the characteristics this effect takes (`copies=EXCEPT_COLOR` for Vesuvan Doppelganger), CR 707.9's modifications, a source and a timestamp; `copiable_card` folds them. Nothing about a copy is stamped onto the copy — a stamp records an answer, and CR 707.2 is a question about where the answer came from. |
| `engine/grammar/` | **The parser**: tokenizer → recursive-descent productions → typed AST → lowering to `OracleInstruction`. A production must consume every token of its line or raise `GrammarError`; see "Grammar front end" below. Imports only `oracle_types`. |
| `engine/effect_labels.py` | The `effect_kind` reporting label an ability's instruction carries, by instruction kind and by the position it occupies. Not dispatch: it feeds `SimulationResult`, the support report's buckets, and the `triggered_` prefix `web/serialization.py` serializes as a stack item's `is_triggered`. It is the vocabulary `engine/parsing/` used to produce, carried across that deletion so 57 cards were not silently re-bucketed, and held to the pool in both directions by `tests/engine/test_effect_labels.py`. |
| `engine/oracle.py` | The compiler: tokenizes oracle text, classifies lines (keyword / triggered / activated / static), delegates effect clauses to `engine.grammar` and then to the card hooks, and caches one `OracleProgram` per card. |
| `engine/handlers/` | Effect executors. Each `@effect_handler(kind)` function mutates game state for one instruction kind. Registered into `EFFECT_HANDLERS` and dispatched with a single dict lookup. `engine/handlers/_common.py` hosts shared helpers (`resolve_target_permanent`/`pick_target_permanent`, `permanent_matches_filter`, damage application). |
| `engine/pt.py` | The single write API for power/toughness channels (`set_base_pt`, `add_pt_modifier`, `switch_pt`, `clear_base_pt`) — see "P/T channels" below. All P/T mutation should go through here, never direct metadata pokes. |
| `engine/replacements.py` | CR 614 replacement-effect registry (`life_gain`, `damage_to_creature`, `would_die`, …). An interceptor may consume an event or adjust its amount before the default action runs; see "Replacement effects" below. |
| `engine/prevention.py` | CR 615 damage-shield registry. Each `@prevention_effect(order, applies=…)` function reports how many points it removes from one damage event, over players and permanents alike. See "Prevention effects" below. |
| `engine/effect_ordering.py` | CR 616.1: gather every applicable replacement and prevention effect, choose one, apply it, re-ask the rest. Both registries run through it, which is why each registration carries a pure `applies` predicate. See "Effect ordering" below. |
| `engine/damage_events.py` | A damage event start to finish: CR 120.4's two halves (damage dealt, then its result), with CR 616.1's contention set — shields *and* replacements together — inside each. `deal_damage(game, event)` is what every damage path calls, and there is no half-event alternative. |
| `engine/tokens.py` | `make_token_card(...)` — the one place that builds a token's `CardDefinition`. A token-creating card is a production lowering to a generic `create_token` instruction, never a bespoke handler. |
| `engine/cast_restrictions.py` | Text-keyed "Cast this spell only during..." timing gates — an ordered predicate table, since the restriction is the same for any card printed with that phrase (not name-specific). |
| `engine/targeting.py` | Cast-time target kind derived from the compiled program — an Aura's `Enchant <subject>` line or an instruction's `type_filter`. The strangler seam replacing `legality.py`'s text cascade: it answers where the program carries evidence, `legality.py` answers otherwise, and a differential guard keeps them equal. |
| `Game.become_tapped(permanent)` | The single untapped→tapped transition (CR 701.26a). It announces `permanent_becomes_tapped` on the event bus, so a "whenever a `<type>` [an opponent controls] becomes tapped" card is dispatched by its own compiled condition and goes on the stack (CR 605.5a — it is not a mana ability). Never set `perm.tapped = True` directly — a trigger registered on one tapping path silently misses every other, which is exactly how Lifetap came to ignore Icy Manipulator. Entering the battlefield tapped is *not* becoming tapped and deliberately bypasses it. |
| `engine/cost_modifiers.py` | Text-keyed cost increases (CR 601.2f) — "<colour> spells cost {N} more to cast" and the activated-ability form. Applied once per taxing permanent on any battlefield. Increases only; reduction is deliberately absent until a card needs it. |
| `engine/untap_restrictions.py` | Text-keyed untap-step restrictions (CR 502): skip the step, per-type untap limits, power- and color-gated blocks, and the "as long as this is untapped" qualifier that composes with any of them. Derived from oracle text, so a card printed with a known template needs no registration. |
| `engine/auras.py` | What an Aura's effect lines say and whether the engine implements them. Two jobs: the **support gate** requires every effect line of an Aura to be claimed here, so an Aura whose effect is unimplemented is reported unsupported instead of entering play and doing nothing; and the **derivations** an Aura's continuous effects are read from while it is attached (static P/T, keyword grants, combat/untap restrictions, protection colours, artifact animation). Removal is the Aura ceasing to be attached — there is no remembered delta to subtract. `attach_aura`/`detach_aura` keep `attached_to` and `attached_auras` in step; `attached_aura` is a single slot a second Aura overwrites, so the list is the authority. |
| `engine/equipment.py` | Equipment (CR 301.5), the equip keyword (CR 702.6) and the attach action (CR 701.3). Equip is compiled as the activated ability CR 702.6a defines it to be — `expand_equip_lines` rewrites "Equip {1}" into "{1}: Attach this permanent to target creature you control. Activate only as a sorcery." before the compiler classifies a line, applied through `oracle.expand_ability_lines` beside the modal-head rewrite — so the grammar's `Attach` production, the `attach_source_to_target` handler, the activation-restriction table and the target picker carry it with no equip-specific path. `equip_refusal` is the one legality predicate (CR 301.5, 301.5c, 702.16d), read by the handler, the picker and `unattach_illegal_equipment`, the CR 704.5n sweep that also drops a departed Equipment from its host (CR 701.3d). Attachment state is the Aura record (`attach_aura`/`detach_aura`), and `engine/auras.py`'s templates read "equipped" beside "enchanted" (CR 301.5f). |
| `engine/cycling.py` | Cycling (CR 702.29), the second keyword the rules define as a rewrite. CR 702.29a: "Cycling [cost]" *means* "[Cost], Discard this card: Draw a card.", so `expand_cycling_lines` rewrites the printed line before the compiler classifies anything (applied through `oracle.expand_ability_lines` beside the equip and buyback rewrites) and from there it is an ordinary activated ability to the grammar, the cost parser, the stack and the web layer — none of which know the word. Typecycling (CR 702.29e) searches a library rather than drawing, so the expansion refuses it and `unread_cycling_line` reports the card unsupported naming the line: the wide-shape gate `equipment.is_equip_line` keeps, for the same reason. The *other* half of the keyword — CR 702.29b's ability that exists in every zone and functions in one — is not a rewrite and is not here; it is CR 113.6j, in `engine/activation_zones.py`. |
| `engine/activation_zones.py` | Which zone an activated ability functions in (CR 113.6), and the one reader every activation path asks. CR 113.6b's *stated* zone (the `functions_from` payload key `activation_restrictions.py` and `lowering/_bound_returns.py` stamp) outranks CR 113.6j's *derived* one — an ability whose cost discards the card it is printed on is payable in a hand and nowhere else (CR 701.9a), so cycling and Waker of Waves get the same answer off the compiled cost with no card and no keyword named. It is the **negative** half that was missing: `activate_from_hand` asked `cost.discard_self` and nothing asked the converse, so `usable_activated_abilities`, `queue_permanent_ability` and the AI's activation loop all offered a hand-only ability on the battlefield and ran it — a free repeatable draw that discarded nothing. The zone read now lives in `usable_activated_abilities(program, zone=…)`, which is the list all three index an ability by, so the web picker, the AI and the engine cannot disagree about what a permanent's abilities are. |
| `engine/characteristic_defining.py` | Characteristic-defining power/toughness (CR 604.3) — "<name>'s power and toughness are each equal to the number of X". The possessive subject is the card's own name, which normalization does not replace, so these were four literals containing four card names. One `dynamic_pt_count` instruction now carries what to count (`land`/`creature`/`same_name`) and whose battlefield to count it on. |
| `engine/static_bonuses.py` | Conditional static P/T bonuses (CR 613 layer 7c) — "gets +N/+N as long as you control a <land>", "as long as it's untapped". Both printed word orders, because only the trailing one was ever dispatched while the leading one sat in the support gate as a literal naming Swamp. Also `singular_land_type`, since Plains is spelled the same singular and plural. |
| `engine/lord_buffs.py` | The lord/anthem template (CR 611.3a, layers 6 and 7c) — "Other Goblins get +1/+1 and have mountainwalk", "Black creatures get +1/+1", "Attacking creatures you control get +1/+0". Derives **who** (colour, creature subtype, "other", controller scope, and a state qualifier: attacking/blocking/tapped/untapped) and **what** (P/T delta, keyword abilities, a granted activated ability). The support gate, both parser front ends and `_recalculate_lord_buffs` all read this one table. A clause carrying a **duration** is deliberately not claimed: that is the spell reading of the same sentence, which locks its set in at resolution (CR 611.2c) and stays on `buff_creatures_global`. |
| `engine/combat_restrictions.py` | Text-keyed combat restrictions (CR 506, 509): "can't attack unless defending player controls a <land type>", "attacks each combat if able", "can't be blocked by Walls", "can't block creatures with power N or greater". The land type and the threshold are payload data, not part of the instruction kind. The support gate consults this table rather than listing the same sentences, so a rider the table does not recognize fails loudly instead of compiling to a bare static line. |
| `engine/enter_effects.py` | Entry-state phrases `_initialize_permanent_state` carries out (enters tapped, enters with counters, enter-as-a-copy, choose-on-enter, no maximum hand size, spend white as red). `enter_effect_line` is the whole-line matcher; the compiler's support gate and `engine/grammar/registries.py` both read it, so the phrases cannot drift between what is implemented and what is claimed. |
| `engine/draw_step_modifiers.py` | Text-keyed symmetric bonus draws (CR 504): "at the beginning of each player's draw step, that player draws an additional card", with the optional untapped-source clause. |
| `engine/land_animation.py` | Text-keyed land animation (CR 613 layers 4/5/7): "All &lt;land type&gt;s are P/T \[colour] creatures that are still lands". The land type, the P/T and the colour are all payload on one `animate_all_lands` instruction, so a third animator needs no code. Replaced two parse rules that baked the land type into the instruction *kind* and a refresh that matched `card.name == "Kormus Bell"` — the two halves failing in opposite directions at once. |
| `engine/land_play_allowance.py` | Text-keyed extra land plays (CR 305.2): "You may play any number of lands on each of your turns", the "\[N] additional land(s)" forms, and the self-damage rider that may accompany them. Every land-drop gate — cast validation, the AI's land policy, the web layer's playable list — and the support gate all ask this one table, so they cannot disagree about what a card grants. |
| `engine/ai_valuation.py` | What a card does in the terms `ai_policy`'s heuristics ask about — how many cards it makes its target draw, whether it bounces a creature, what it destroys, whether it counters a spell, how much mana its ability adds — derived from the compiled program. Replaced eight `card.name == "…"` comparisons that had already decayed: Shatter, Terror, Stone Rain and Desert Twister print Disenchant's template, were not on the list, and the AI aimed all four at its own permanents. A heuristic's *weight* stays tuning in `ai_policy`; **which cards it reaches** is a claim about the pool and lives here. |
| `engine/card_hooks.py` | Name-keyed registries for truly bespoke card behavior: spell-resolved triggers, counterspell riders, leave-battlefield effects, draw-step modifiers, and `CARD_LINE_INSTRUCTIONS` — the instruction one printed *line* of one card compiles to, for texts that are a single card's sentence rather than a template. `engine/oracle.py` reads it after the grammar refuses, and it is the last front end there is, so a line that grows a production leaves its entry dead rather than wrong; `tests/engine/test_card_lines.py` fails on a dead entry and on a key matching no printed line, and `tests/engine/test_front_end_safety.py` fails if the production that took a hooked line over produces less than the hook did. The only sanctioned place in the engine to key behavior on a card name — enforced by `tests/engine/test_card_name_reads.py`, which scans `engine/` for a name in a comparison (dispatch) rather than in a log line (data), with one acknowledgement: `ai_simulator._assert_expected`, a test oracle whose expectations must stay independent of the parse they check. |
| `engine/control.py` | CR 613 layer 2: a control change is a recorded *contribution* with a source and a timestamp (`change_control` / `end_control_change`), never a move; `base_controller_index` is the seat the permanent entered under and is never rewritten. `Game._sync_control` projects the derived controller onto the battlefield lists. |
| `engine/commander.py` | CR 903, the Commander variant and its Brawl option — inert unless `Game.commander_variant` is set. Colour identity is derived here (not read off the ingested field), the designation is per seat by card-object identity, and CR 903.9b's return-to-command-zone is why every "put into a hand / a library" goes through `Game.put_card_into_hand` / `put_card_into_library`. |
| `engine/subject_filters.py` | What a printed noun phrase means, tested against one permanent: `subject_matches` is the one answer, `TESTABLE_SUBJECT_FILTER_KEYS` names exactly the payload keys it can test, and a compiler admits a narrowed line only when every key is in that set. |
| `engine/search_filters.py` | What a library/graveyard search may *find* — one predicate over a `ObjectFilter` payload, asked by the search prompt, its default and the AI. |
| `engine/target_restrictions.py` | Printed restrictions on what a spell may *choose* (CR 601.2c — "you can't choose an untapped creature as this spell's target"), read by the cast path and the AI's Aura chooser. |
| `engine/named_protection.py` | Protection a *player* has from a card name (CR 702.16i, Runed Halo): the cast-target check and the player-damage path both ask it. |
| `engine/activation_restrictions.py` | Text-keyed "Activate only …" clauses (CR 602.5) — an ordered predicate table the activation path *and* the support gate read, so a printed restriction nobody listed cannot be admitted unenforced. |
| `engine/cast_costs.py` / `engine/cast_permissions.py` | The CR 601.2b additional costs a spell prints in its own text, and permission to cast from somewhere other than the hand (a graveyard, the top of the library) — both tables, not per-card. |
| `engine/mana_payment.py` | Whether a cost can be paid from the board and how: `plan_payment` is an exact matching of coloured pips to lands, because "you may pay {1}{B}" inside a resolution gives its player no priority window to produce the mana themselves. |
| `engine/restricted_mana.py` | Mana that may be spent only on certain spells (CR 106.6) — the spend restriction travels with the mana in the pool. |
| `engine/hand_size.py` | CR 402.2's seven and the printed lines that change it, read by the cleanup step, the support gate and the parse-coverage report. |
| `engine/named_counters.py` / `engine/text_changes.py` / `engine/land_types.py` | Single write APIs: counters with no rules meaning of their own (CR 122), text-changing effects (layer 3), basic-land-type changes (layer 4). |
| `engine/phases/` | One mixin per turn phase and per step within a phase (CR 500–514): `beginning_phase` + `untap_step`/`upkeep_step`/`draw_step`, `precombat_main_phase`, `combat_phase` + its five step modules, `postcombat_main_phase`, `ending_phase` + `end_step`/`cleanup_step`. Each is composed onto `Game`. See `engine/phases/__init__.py` for the full taxonomy. |
| `engine/mixins/` | Cross-cutting game flow not tied to a single phase: turn-structure navigation and priority (`phase_steps`), per-turn/pregame management (`turn_management`), state-based actions, effects, helpers. Consumes compiled programs; should never parse oracle text itself. |
| **The turn's phase plan** (`phase_steps`) | `Game.turn_phases_remaining` is the phases this turn still has to take, in order — CR 500.1's five at the start of every turn (`begin_turn_bookkeeping`), CR 500.8's extras *inserted* into it (`add_extra_phase`), each entry spent as its phase is entered (`_set_phase_and_step`, the line every entry point already passes through). **No driver names its own successor**: `next_unskipped_phase_after` peeks and `enter_next_turn_phase` / `enter_turn_phase` enter, and the headless flow, the combat phase and `web/game_flow._advance_phase` all go through them. A *list* rather than a dict keyed by phase name, because a repeated phase is two entries — an extra combat phase and the turn's own one have the same name, and a name-keyed record cannot tell them apart. Adding a phase means adding an entry point in `enter_turn_phase`; `tests/rules/test_turn_phases.py` fails if a phase the plan can hold has none. |
| `engine/mixins/stack/` | The stack (CR 405), one mixin per stage of an object's life on it: `casting` (CR 601), `activation` (CR 602), `resolution` (CR 603/608), and `choices` — the `pending_choices` queue every part-way-through decision uses, plus the table registering them. |

## Adding support for a new card

Work top-down; stop at the first step that covers the card.

1. **Already covered?** If the parser reads the card's oracle text
   (run `compile_card_oracle(card)` and check `supported`), nothing to do.
   `python scripts/support_report.py` reports coverage for the whole manifest
   pool and `--set <CODE>` for one set, and the "creature text too complex"
   reason now names the specific unrecognized line.
2. **New text pattern, existing effect.** Add a *production* to
   `engine/grammar/`. Noun phrases, amounts, durations and player references
   are already parsed, so most patterns are a branch in an existing production
   plus a lowering — and there is no precedence number to pick, because a
   production either consumes its line or refuses it. If the lowering cannot
   honour part of the clause, raise `LoweringError` naming what is missing
   rather than emitting an instruction that means something narrower.
3. **New effect.** Invent a new instruction kind (verb_object naming, e.g.
   `exile_target_creature_until_eot`), lower to it, give it an entry in
   `INSTRUCTION_CATEGORIES` *and* in `GRAMMAR_CATEGORIES` (they are held equal),
   then add one `@effect_handler` function in the matching `engine/handlers/`
   module.
   Creating tokens: emit `create_token` (payload: name/power/toughness/
   type_line/colors/keywords/count) — never write a bespoke token handler.
   Setting/modifying power or toughness: go through `engine/pt.py`, never
   metadata directly. "If X would happen, Y instead": register an interceptor
   in `engine/replacements.py` instead of an inline metadata check.
4. **Card-specific behavior.** If the behavior can't be expressed generically,
   register a hook in `engine/card_hooks.py` keyed by card name (or, for a
   genuinely textual timing restriction, an entry in
   `engine/cast_restrictions.py`). Don't put card names anywhere else in the
   engine.
5. **Tests.** Add a focused test per new rule/handler (see
   `tests/sets/test_lea_cards.py` for per-card patterns). The comprehensive-cast
   sweep (`test_every_catalog_card_resolves_without_exception`) is driven by
   `pytest_generate_tests` over the whole `cards/manifest.json` catalog, so a
   new set is swept the moment it is ingested. Only add to that file's
   `SWEEP_EXCLUSIONS` if a card needs setup the generic body can't provide.

## Grammar front end

`engine/grammar/` parses an oracle line into a typed AST and lowers it to the
`OracleInstruction` IR. Both halves are layered bottom to top, and the seven
effect *families* carry the same names on each side — so one template has one
home per side. The order is asserted by `tests/engine/test_grammar_layering.py`
(`PARSE_LAYERS` / `LOWER_LAYERS`), along with family independence, the flat
re-export from each `__init__`, and a 1,000-line cap per module that is a
scheduling signal, not style: a family that crosses it has stopped absorbing
new work and splits along a CR boundary (`nouns.py` → `references.py`,
`statements.py` → `paragraphs.py`, `lowering/characteristics.py` →
`lowering/counters.py` are the precedents).

| Layer | Parse side | Lowering side |
| --- | --- | --- |
| vocabulary | `lexer.py` (tokenizer; P/T as one token, reminder text stripped and recorded, self-references collapsed to `SELF`), `stream.py`, `errors.py`, `vocabulary.py` (creature/land/artifact types, supertypes, keywords from `data/vocabulary/` — never the network at import), `amounts.py` | — |
| nodes | `ast/_core.py` (the vocabulary nodes everything is built from), `ast/{damage,characteristics,board,cards,stack,combat,game}.py`, `ast/statements.py` (the `Effect` / `Statement` unions and the composable statement nodes), `ast/lines.py` (the ability-line nodes and the `AbilityNode` union — the type of the *line* row below, as `statements` is of the *sentence* row). Frozen dataclasses, **append-only** — repurposing a field invalidates every golden and ratchet entry at once. | — |
| noun phrases | `nouns.py` (what an object phrase *describes*: `ObjectFilter`, `TargetSpec`, `PlayerRef`), `references.py` (what it *points at*: "that creature", "it", the enchanted permanent), `paragraphs.py` (a whole paragraph: the self-reference and linked-duration shapes) | `lowering/_common.py` (shared payload builders) |
| phrases | `phrases.py` (word tables and fragment productions shared by every family), `triggers.py` (trigger heads), `conditions.py`, `riders.py` | — |
| effects | `effects/{damage,characteristics,board,cards,stack,combat,game}.py` — one family per module | `lowering/` — the same seven, plus `zones`, `library`, `mana`, `counters`, whose lowering halves outgrew the cap while their parse halves stayed small |
| sentence | `statements.py` (one whole sentence), `costs.py` (activation and additional costs), `statics.py` | `lowering/categories.py` (the instruction → category table the support report and `GRAMMAR_CATEGORIES` read) |
| line | `parser.py` (`parse_line`: classification as keyword / activated / triggered / static / spell, then the statement grammar) | `lower.py` (dispatch: AST → instructions emitting the payload keys the existing handlers already read) |
| sidecars | `registries.py` — which text-keyed registry, if any, implements a whole line (the untap table, the cast-timing gate, the cost taxes, the CR 614 interceptors, the entry-state phrases); those lines carry no instruction because the registry runs them off the card's text. `derived.py` — derivation tables consulted **after** every production has refused (the lord/anthem table, the land animations, the land type changes), each handing over the table's own instruction. | — |

Two properties define how it behaves:

- **Full token consumption.** A production must account for every token of its
  line; leftovers raise `GrammarError`. So "parsed" means "understood in full",
  and a gap fails loudly (unsupported, with the clause named) rather than
  resolving as something the card doesn't say. This is the structural fix for
  the dropped-rider class that `scripts/parse_coverage.py`'s deletion probe
  detects empirically.
- **Category gating, which now means completeness.** A line's output is used
  when every category it lowered to is in `engine.grammar.GRAMMAR_CATEGORIES`.
  While `engine/parsing/` existed this was the migration's valve — a category
  left off fell back to the legacy rules, so work could land and be measured
  before it was switched on. With nothing underneath, leaving one off does not
  route its lines anywhere; it makes those cards **unsupported**. So the set is
  held equal to every category `lower.py` can emit
  (`tests/engine/test_grammar_categories.py`), and a category that genuinely
  should not execute belongs as a `LoweringError` in `lower_statement` — which
  carries a reason the coverage report can group — rather than as an
  unexplained absence from a frozenset.

Composition lives in the IR: `sequence`, `if_then`, `may`, and `for_each`
(`engine/handlers/control_flow.py`) nest instruction tuples in their payloads,
and `OracleExecutionContext.results` carries values between steps of one
resolution ("deals X damage… you gain that much life"). That is what removes the
need for fused kinds like `deal_damage_and_gain_life` — 28 of the legacy
compiler's 120 kinds were conjunctions of this sort.

What an `if_then` asks is a registry too: `engine/handlers/conditions.py` holds
one `@condition(kind)` handler per lowered condition kind behind
`evaluate_condition`. It was one function of 72 arms; a new condition is a
registered function, and `tests/engine/test_condition_registry.py` fails a kind
the pool compiles with no handler, which would otherwise read False for ever.

Coverage is tracked in `GRAMMAR_COVERAGE.md` with floors in
`scripts/grammar_ratchet.json`, guarded by `tests/engine/test_grammar_ratchet.py`.
Those floors were the migration ratchet and are now a division-of-labour one:
every line the grammar does not read has to be read by something narrower, so a
**fall** means the pool became more special-cased than it was.

## Destruction is a state-based action

Lethal damage (CR 704.5g) and deathtouch damage (704.5h) destroy creatures in
`check_state_based_actions` and nowhere else. Effect handlers mark damage and
stop — they do not sweep for deaths, and nothing else should either.

This used to be the opposite: destruction happened only when an effect called
`_destroy_marked_creatures()` by hand, at nine separate sites. Any new damage
effect that forgot left a lethally damaged creature alive, and composed effects
made that easy to hit, since a damage step no longer necessarily sits inside a
handler that knows to run the sweep. If a new code path needs deaths applied
before it continues, call `check_state_based_actions()` — that is CR 704.3, and
it is what the phase steps do before handing out priority.

## Continuous effects — the CR 613 layer system

`engine/continuous.py` implements the layer system: effects are placed in
layers 1–7, layer 7 is split into sublayers 7a–7d, and within a layer or
sublayer effects apply in **timestamp** order — except where **dependency**
(CR 613.8) overrides it. Dependency is detected generally, by asking what an
effect *would* do before and after applying another, rather than by enumerating
known card interactions; dependency loops fall back to timestamp order as
613.8b requires, and the order is re-evaluated after every application (613.8c).

Two consequences for anyone adding an effect:

- **`modify` and `applies_to` must be pure.** Both are applied speculatively to
  throwaway state while probing dependency, so they may run many times per
  recompute. A side effect outside the `Characteristics` passed in will fire
  spuriously.
- **Ordering is a rule, not a coding convention.** Put an effect in its layer
  and give it a timestamp; do not try to sequence it by where the code runs.

`engine/layer_bridge.py` adapts the engine's stored channels into effects and is
what `Permanent.effective_power`/`effective_toughness` and
`Permanent.has_keyword` call. Keeping the adapter separate keeps the layer
engine pure and testable directly against the rule text
(`tests/rules/test_layers.py`), while the storage it reads from can move without
the rules logic changing.

**Layers 1–7 are live.** The accessors that read them:

| Accessor | Layer |
| --- | --- |
| `Permanent.effective_card` | 1 (copy), then 3 (text-changing) |
| `Permanent.copied_from` | 1 (copy) |
| `Game.controller_index_of` / `controls` / `controlled_by` | 2 (control-changing; `engine/control.py`, contributions with timestamps over `base_controller_index`) |
| `Permanent.is_creature`, `Permanent.has_type`, `Permanent.basic_land_types` | 4 (type-changing) |
| `Permanent.effective_colors` | 5 (colour-changing) |
| `Permanent.has_keyword` | 6 (ability add/remove) |
| `Permanent.effective_power` / `effective_toughness` | 7a–7d |

**Layer 1 produces the seed rather than applying over it.** CR 613.2c: once
layer 1 has been applied, the object's characteristics *are* its copiable
values. So `engine/copies.py` answers with a `CardDefinition` — the copied
object's copiable values, folded by `copiable_card` and read by
`effective_card` — and `apply_layers` refuses a layer-1 `ContinuousEffect`
rather than silently dropping it. A copy effect records what it *takes*
(`copies=EXCEPT_COLOR` is Vesuvan Doppelganger) plus CR 707.9's modifications,
so an exception is a named value and not an unwritten stamp. Nothing about a
copy is stamped onto the copy: P/T, colours, types and abilities are all read
back through the layers from the recorded contribution, which is what keeps
CR 707.2's boundary — printed values as modified by *copy* effects, and nothing
else. `tests/engine/test_copy_reads.py` enforces it.

A printed keyword is part of an object's copiable values, so it is *seeded*
by layer 1 rather than granted afterwards; grants and removals are continuous
effects recorded in order by
`engine/keywords.py`. A removal can therefore take a printed ability away, and
a later grant can put it back — CR 613.9's worked example, and neither was
expressible when the engine stored one `gains_<keyword>` / `loses_<keyword>`
flag per keyword and checked removals first.

Layer 4 distinguishes *adding* a type (animation: a Kormus Bell Swamp is a
creature **and** still a land) from *replacing* subtypes (Evil Presence: the
land is a Swamp **instead of** a Forest, CR 305.7). Ask `perm.has_type("swamp")`
or `perm.basic_land_types`; nothing else may read the storage, which
`tests/engine/test_layer_reads.py` enforces.

**Layers 3 and 4 record contributions, not values.** `engine/text_changes.py`
holds each text change (a colour word, a basic land type, and every written
form of it) with a timestamp; `engine/land_types.py` holds each land-type
change with a timestamp *and a source*. Removal is dropping one contribution,
so an effect ending restores what the others still say rather than the printed
characteristic — a Gaea's Liege Forest ending on an Evil Presence Swamp leaves
a Swamp. **Neither layer commutes**, which is what the timestamps are for: two
land-type changes each *replace*, and two text changes each rewrite what the
previous one produced. Both were previously a single stamped value that only
one effect could occupy at a time.

Layer 3 is applied by `Permanent.effective_card`, which rewrites the rules
text, the type line and the parsed keywords — so a Magical Hack land swap and a
Sleight of Mind colour swap are one effect each, and every text-keyed table
downstream (untap restrictions, cost taxes, protection colours, lord grants)
reads the changed text without knowing text can change. The no-change path
returns the card object itself, unallocated.

**Layer 7c splits by lifetime, and the split is load-bearing.** `power_bonus` is
persistent (counters, one-shot boosts); `static_buff_*`, `derived_buff_*` and
`lord_buff_while` are derived — cleared and rebuilt from the board on every
recompute. A continuous
effect that writes to the persistent channel has to subtract itself again later,
and a subtraction that doesn't exactly match its addition compounds on every
refresh, which CR 611.3a guarantees is constant. Each derived channel is cleared
by the same function that rebuilds it; splitting those apart reintroduces the
bug.

`lord_buff_while` splits again, by *when the contribution is evaluated*. It maps
a state qualifier ("attacking", "blocking", "tapped", "untapped") to its P/T
delta, and `layer_bridge.qualifier_holds` checks the qualifier when power and
toughness are **read** — not when the board was last recomputed. Nothing
recomputes when a creature taps, so a bonus contributed at recompute time
outlives its own condition: Castle's "Untapped creatures you control get +0/+2"
stayed on a creature for the whole declare-attackers step after it had attacked.
The qualifier vocabulary is `lord_buffs.QUALIFIER_FIELDS`, and a qualifier with
no predicate to evaluate it raises at import rather than applying
unconditionally.

All writes go through `engine/pt.py`;
characteristic-defining P/T (layer 7a) is registry-driven via
`engine.mixins.permanent_state.DYNAMIC_PT` (instruction kind → count
function) — a new CDA card is one table entry, not a new branch.

## Replacement effects

"If X would happen, Y instead" effects (Lich, Disintegrate's exile-instead,
Jade Monolith's redirect, …) are interceptors registered in
`engine/replacements.py` by event kind (`life_gain`, `damage_to_creature`,
`life_loss`, `would_die`, …). Each registration is a pure `applies` predicate
plus the effect itself; `apply_replacements(game, kind, payload)` runs them
through CR 616.1 (see "Effect ordering" below). An interceptor may consume the
event (skip the default action) or adjust `payload["amount"]` and let the process
continue. Interceptors self-select from game/permanent state, so the registry
stays name-free — Veteran Bodyguard's redirect reads the damage source's own
combat state rather than trusting which loop of the combat step it arrived in,
which is what makes it correctly decline a blocked trampler's excess.

### Replacements that need a decision

Some replacement effects are optional ("you *may* put it on top of your library
instead") or let the player choose among outcomes ("look at the top X cards,
draw one of them"). Those can't be applied inline — `apply_replacements` returns
synchronously while a human's answer arrives on a later request.

Such an interceptor *offers* a `ReplacementChoice` (`engine/replacement_choices.py`)
carrying the seat, the option labels, a default, and whatever its resolver will
need. An interactive seat gets it queued on `game.pending_replacement_choices`
and the event is suspended — the affected card sits in no zone until
`Game.resolve_replacement_choice` answers. Any other seat takes the default
immediately. Both paths finish through the same `@replacement_choice(kind)`
resolver, so there is one completion path rather than an inline AI branch and a
`confirm_` method that must agree.

Adding an interactive replacement is an interceptor plus a resolver — no new
`Game` field, confirm method, or prompt plumbing. `pending_lamp_draw`,
`pending_outside_game_draw` and `pending_leng_discards` remain as read-only
views over the queue in the shapes the web layer reads.

## Pending choices

Every other decision a seat owes part-way through a spell, an ability or a turn
step — a library search, a discard, Balance's removals, Power Sink's payment,
Word of Command's borrowed card — is a `PendingChoice` on
`Game.pending_choices`, with a `ChoiceSpec` registered in
`engine/pending_choices.py` (the table itself lives at the bottom of
`engine/mixins/stack/choices.py`).

A prompt has five parts: something arms it, a **resolver**, a **default** for
non-interactive seats, a **renderer**, and an **action** that answers it. The
spec carries the last four plus the gating metadata — the 400 message that
refuses other actions, whether the whole game waits or only the choosing seat,
whether a spectator sees it, and whether a non-interactive seat takes the
default the moment it is armed (`default_at_arm`) or stays queued for the
auto-resolver.

```
handler / upkeep effect / entry replacement
  → game.arm_pending_choice(kind, seat, **data)
      interactive seat  → queued on game.pending_choices
      other seat        → spec.default(...) now, or on the next auto-resolve pass
  → web/prompts.py renders it, refuses other actions, and answers AI-owned ones
  → confirm_*  → game.resolve_pending_choice(kind, seat, **response) → spec.resolve
```

The web layer loops over `game.iter_pending_prompts()` rather than naming each
kind, and that iterator spans **both** queues — a suspended `ReplacementChoice`
carries the same `kind`/`player_index`/`data` attributes, so no adapter is
needed. `pending_<name>` properties remain as read-only views derived from the
queue, each taking its seat from `choice.player_index` so the two cannot drift.

Adding an interactive choice is one `register_choice(...)`, one renderer, and
the code that arms it; `tests/engine/test_pending_choices.py` fails if a kind is
armed with no spec, registered with no renderer, or given an action `web/app.py`
never dispatches. That last check exists because the failure is silent and
asymmetric: a missing default *hangs an AI seat forever*, a missing gate lets a
player act around their own prompt, and a missing renderer means the prompt is
armed and never shown — which is exactly what Primal Clay shipped with.

## Prevention effects

Damage shields (CR 615) are a separate registry with the same shape,
`engine/prevention.py`. A `@prevention_effect(order, applies=…)` function
inspects one event — `{recipient, amount, source, combat}`, where `recipient` is
a `PlayerState` *or* a `Permanent` — and returns how many points it removes, or
`None` to pass. `combat` marks the event as combat damage and is what scopes the
blanket shields (Fog, Ebony Horse) — every other shield ignores it.

The *state* is generic too. A shield is a `Shield` in one collection on its
recipient (`engine/shields.py`): what it answers to (`source`, `color`), how
much it absorbs (`amount` points, `leave` points let through), how many `uses`
remain, and its `lifetime`. Both models carry the collection, so CR 615.7's
numeric shield is one interceptor covering creatures and players; shields whose
additional effect needs a player (Reverse Damage's life gain) check the
recipient type themselves. `kind` names the interceptor that consumes the
shield, so state and behaviour cannot drift.

`Shield.would_prevent` computes and `Shield.spend` mutates — the split CR 616.1
needs, since a predicate that consumed a charge would spend shields the player
was only asked about.

**Adding a shield is one `@prevention_effect` plus a `Shield`.** No
`PlayerState` field, no clearing line in the cleanup or end-of-combat step (the
sweeps read `lifetime`), and no change to the web payload. The old per-card
field names (`damage_prevention_pool`, `color_prevention_shields`,
`forcefield_capped_sources`, `reverse_damage_charges`/`_sources`,
`combat_damage_cap_one_charges`) survive as views over the collection, derived
on every read, so the web layer and the AI simulator keep reading what they
always did. `damage_prevention_color` is the one read-only view: the colour is
what its shield matches the source against (CR 615.9), so there is nothing to
set that isn't a shield.

## Effect ordering (CR 616.1)

Replacement and prevention effects are not two pipelines that happen to run one
after the other. CR 616.1 gathers everything applicable to an event, lets the
affected player choose one, applies it, then repeats over what is *still*
applicable (616.1f). `engine/effect_ordering.py` is that process and the only
place either registry decides what runs next.

Which is why every registration is split in two: a pure `applies` predicate and
the effect. An effect that answers "do I apply?" by applying itself makes the
rule unimplementable — counting the contenders would mean running one, which is
exactly what 616.1 forbids before the choice is made. The predicate must not
consume a charge, because an effect that is asked about may then not be chosen.

### Asking the choice (616.1e)

The choice belongs to the affected player, and `apply_in_order` puts it to them
through its `ask` hook — an `effect_order` pending choice, registered like every
other prompt.

Purity is what makes suspending cheap. When a contended round is reached,
*nothing has been applied yet*, so the process can be abandoned and the **whole
event re-run** later: it arrives at the same round with the same contenders and
the recorded answer waiting. No continuation, no snapshot, no rollback — there
is nothing yet to undo. (Snapshotting would in fact be wrong here: the engine
compares damage sources and band members by identity, which a deep copy breaks.)

The re-run is supplied by the caller as a `restart` thunk, because an event is
more than its replacements — a draw nothing replaces still has to draw. Passing
one is a caller declaring "this event can suspend"; a suspended event reports
`consumed` so the caller skips the default action and the re-run does it
properly. Non-interactive seats are never asked anywhere.

Two things have to be true before a caller can offer a re-run. Its own
consequences must be *inside* the event — damage callers pass them as `then`,
so a suspended event does not get logged as 0 damage or gain life equal to
nothing (`tests/engine/test_damage_continuations.py` holds engine code to
that). And the work *behind* the event must be recorded, which is
`engine/resumption.py`: a loop registers the rest of itself before each step, so
answering resumes the divided damage, the sequence, and the spell's graveyard
move in that order. A loop using it must be the last thing its function does.

**Every damage path satisfies both and asks**, combat included. The combat
damage step was the last to convert and the only one where it was a restructure
rather than a two-line change: its dealing half is now nested resumable loops
(blockers by defender, by blocker, by band member; then the two attacker loops),
its tail — the lifelink gain, the state-based actions and the
`combat_first_strike_done` / `combat_damage_resolved` flags — is the last *step*
of the outermost loop rather than code after it, and both strike passes (CR
510.4) run through one `resolve_all_combat_damage` so a first-strike pass that
suspends records the second behind it instead of being re-run by a caller that
saw "not resolved yet".

`engine/damage_events.py` is where a *damage* event's members of both registries
become the one candidate list the rule describes. `deal_damage(game, event)` is
the entry point every damage path uses — there is deliberately no shields-only
or replacements-only alternative, because a caller holding half a contention set
is the shape this pipeline exists to remove.

Unlike parse rules, order here is semantic rather than a precedence tiebreak: it
is the *default choice* a non-interactive seat makes, so the two registries share
one order space for damage and a collision between them raises at import — as
does a duplicate within either one.

### A damage event has two halves (CR 120.4)

616.1 is not the only sequencing a damage event has. CR 120.4 runs it in parts:

- **120.4b** — the damage is *dealt*, as modified by the effects that interact
  with damage: shields absorb points, redirects send the event elsewhere.
  Triggers on damage being dealt trigger on what comes out of this half.
- **120.4c** — what was dealt is *processed into its results*, as modified by the
  effects that interact with those results: life lost for a player, damage
  marked for a creature.

616.1 chooses within each half, so they are four registry kinds:
`damage_to_player` / `damage_to_creature` for the first, `life_loss` /
`damage_marked` for the second. `deal_damage` returns a `DamageOutcome` carrying
both numbers — `dealt` and `result`.

Two numbers, not one, because they genuinely differ. Ali from Cairo ("damage
that would reduce your life total to less than 1 reduces it to 1 instead") is a
120.4c effect: the damage is dealt in full, so lifelink gains the full amount
(CR 120.3f) and a "deals damage to a player" trigger sees the full amount, and
only the life loss is capped. Collapsing them is what forced the combat damage
step to apply its shields where the event was recorded and its replacements
where life was applied — one moment short of a second number, not two moments by
necessity.

## Precedence: there isn't any

A section here documented the `@parse_rule` order bands — one global integer
space, nine named `BAND_*` constants, and the rule that a specific pattern had
to be given a lower number than a generic one so `"destroy all creatures"` beat
`"destroy target"`. **It went with `engine/parsing/`, and its absence is the
point.** Precedence was a property of the registry, needed because every rule
was a substring predicate that could match any clause: the ordering was how a
rule was told which other rules it was allowed to be wrong about, and a new
card meant choosing a number relative to rules its author had not read.

A grammar has no such knob. `"destroy all creatures"` and `"destroy target
creature"` are one production whose difference falls out of the noun phrase's
quantifier, so there is nothing to order and nothing to get wrong. Two
orderings remain, both structural rather than numeric, and each is asserted
rather than assumed:

- **the front ends, most general first** — the grammar, then the name-keyed
  card hooks. A line the grammar learns to read stops reaching its hook, which
  makes a superseded hook *dead* rather than wrong;
  `tests/engine/test_card_lines.py` fails on a dead one, and
  `tests/engine/test_front_end_safety.py` fails if the production that took the
  line over says less than the hook did.
- **productions before derivation tables**, inside the grammar. `parse_line`
  runs every production and consults `engine/grammar/derived.py` only after a
  `GrammarError`; reversing that would let `engine/lord_buffs.py` claim every
  anthem in the pool. Asserted by
  `tests/engine/test_grammar_derived_lines.py`.

## Scale properties

- **Compile once:** `compile_card_oracle` is cached unbounded; parsing cost is
  paid once per distinct card per process, regardless of how many games run.
- **O(1) execution:** instruction dispatch is a dict lookup. Adding the
  1000th effect kind does not slow down the 1st.
- **Parsing was the real growth term, and no longer is.**
  `parse_primary_instruction` was a linear scan over the whole `@parse_rule`
  registry for every clause, so compile cost was O(cards × clauses × rules)
  with the rule count itself growing per card — the reason the grammar exists.
  Parsing is now O(tokens) recursive descent plus hash lookups, and the card
  hooks behind it are a two-level dict lookup keyed by (name, line).
- **Precompiled regexes:** trigger tables and parse rules compile their
  patterns at import. Python's internal regex cache (512 entries) is never
  relied on.
- **Deterministic simulations:** `run_ai_simulation` seeds the module-level
  RNG, so a given seed reproduces a run exactly — required for regression
  tests over AI behavior.

## The long form of CLAUDE.md

Everything from here to the end of this file was moved, verbatim, out of
`CLAUDE.md` on 2026-10-13, when that file became its own short form. It is
loaded into every session and every subagent, and at 133 KB it cost each of
them some thirty thousand tokens before the brief. CLAUDE.md keeps each rule
and the guard that holds it; this is the reasoning - the incident, the cards
and the measurements behind each one. "This file" below means CLAUDE.md as it
was, a pointer to `engine/ARCHITECTURE.md` means the sections above, and the
code blocks it refers to are still in CLAUDE.md.

**New history is written here**, under the entry it belongs to, and the rule
it changes is changed in CLAUDE.md in a sentence
(`tests/engine/test_claude_md_size.py` holds that file's size). The pool's
history set by set, and the verification tracker's, are in `SET_HISTORY.md`.

## Extension points, in full

Full details in `engine/ARCHITECTURE.md`. The compile-and-dispatch pipeline:

*(The diagram is kept in CLAUDE.md, under "Engine architecture".)*

**`engine/grammar/` is the parser** — tokenizer → recursive-descent grammar →
typed AST → lowering to `OracleInstruction`. The compiler reads a line through
it and then through `card_hooks.CARD_LINE_INSTRUCTIONS` (one printed line of one
named card), and there is **nothing after that**: a line neither claims produces
no instruction and the card is reported unsupported naming the clause. The flat
`engine/parsing/` rule registry it replaced is deleted, along with its
precedence bands — a grammar has no precedence knob, because a production
consumes its line or refuses it. Read `ROADMAP.md` before doing parser work;
coverage lives in `GRAMMAR_COVERAGE.md`.

**Where a new template goes.** Both halves are layered, bottom to top, and the
effect families are the *same names* on each side — so one template has one home
per side, and moving a production between families is not a caller-visible
change (both `__init__` re-export flat):

*(The diagram is kept in CLAUDE.md, under "Engine architecture".)*

The lowering side carries families the parse side does not — `zones`, `library`,
`mana`, `redirection` among them — because their lowering halves outgrew the
1,000-line cap while their parse halves stayed small
(`test_grammar_layering.py` documents every one with its reason). If an
`effects/` module splits, reuse those names so the mirror re-forms instead of
forking: `effects/prevention.py` did, when the damage productions crossed the
cap, and `effects/counters.py` did a set later — `lowering/counters.py` had
carried the name since it left the same family, so the boundary was found twice,
one package and one set apart. `prevention` carries the redirects too, which the
lowering side keeps separate — one printed sentence returns either node, so two
parse modules would be one importing the other.

**A module a family imports is a floor, not a family** — the family rule is
"families do not import each other", so a leaf several lowerings read sits
beside `_common` however small it is. `lowering/_amounts.py` is the newest
(CR 107.2/107.3: a quantity counted off a board or out of the scratchpad,
against the sentence that spends it), for exactly `ast/_primitives.py`'s reason
one package over.

Prowess gets a node in `ast/characteristics.py`, parses in
`effects/characteristics.py` and lowers in `lowering/characteristics.py`.
A **derivation table** the grammar falls back to (`engine/grammar/derived.py`)
is reached only where every production refuses the line *in full*, so a
production whose sentence a table also reads must refuse in the **parse**:
parsed-but-unlowered is still parsed, and takes the table's line away.
`tests/engine/test_grammar_layering.py` enforces the layer order, family
independence, and flat re-export from each `__init__` — a fragment two families
need goes in `phrases`/`_common`/`_core`, never in one of them, because that
coupling is what makes the grouping stop being information. No module may exceed
1,000 lines; that is not style, it is the signal that a family stopped absorbing
new work.

Extension points, each a small registered function — **adding a card means
adding entries, not editing dispatch**:

- `engine/grammar/` — the parser. Adding a card pattern here means adding a
  *production*, and there is no precedence number to pick. Hard invariant: a
  production must consume **every token** of its line or raise `GrammarError` —
  loud failure (card unsupported, clause named) is always preferable to a silent
  partial match. `GRAMMAR_CATEGORIES` is held equal to every category
  `lowering/categories.py` declares (`tests/engine/test_grammar_categories.py`,
  which still imports it from `engine.grammar.lower` — the table moved, its
  address did not): with no
  fallback underneath, a category left off does not route its lines elsewhere,
  it costs those cards their support. An effect that should *not* execute
  belongs as a `LoweringError` naming what is missing. Vocabulary (creature
  types, keywords) is data in `data/vocabulary/`, refreshed by
  `scripts/fetch_vocabulary.py` — never hardcode a type list.
  **Which keywords the engine implements is one frozenset**,
  `vocabulary.IMPLEMENTED_KEYWORDS`, and `engine/oracle.py`'s keyword-*line*
  classifier reads it rather than keeping its own. Adding a keyword means that
  set plus the behaviour behind it — and the behaviour has to cover everywhere
  the CR says it applies, not just the path the pool happens to exercise.
  Lifelink is the worked example: the mechanic existed in the combat damage step
  alone, so adding the word would have gained life in combat and silently gained
  nothing for a ping ability (CR 702.15b is about damage, not combat damage). It
  now goes through `damage_events.lifelink_life_gained`, one rule with three
  callers. Held by `tests/engine/test_keyword_registry.py`, which checks the
  gate's *behaviour* against the registry — comparing two lists is something a
  second copy would also pass.
- `engine/effect_labels.py` — the `effect_kind` *label* an ability reports
  (`activated_regenerate`, `triggered_sacrifice`, `upkeep_effect`). Never
  dispatch: it feeds `SimulationResult`, the support report's buckets and the
  `triggered_` prefix `web/serialization.py` turns into a stack item's
  `is_triggered`. It is the vocabulary `engine/parsing/` used to produce,
  carried across the deletion so 57 cards were not silently re-bucketed, and
  held to the pool in both directions by `tests/engine/test_effect_labels.py`.
- `engine/handlers/control_flow.py` — `sequence`, `if_then`, `may`, `for_each`.
  Effects compose through these instead of getting a fused instruction kind:
  write "deal damage, then gain life" as two instructions in a `sequence`, never
  as a new `deal_damage_and_gain_life`. Values pass between steps through
  `OracleExecutionContext.results`.
- `engine/handlers/conditions.py` — what a lowered `condition` payload asks:
  one `@condition(kind)` handler per kind behind `evaluate_condition` (still
  importable from `control_flow`). A new condition is a registered function,
  never an arm; an unregistered kind answers False, so
  `tests/engine/test_condition_registry.py` holds the registry to the compiled
  pool both ways. Conditional statics keep their own vocabulary in
  `engine/static_bonuses.py`.
- `engine/handlers/` — `@effect_handler(kind)` functions mutate game state for one
  instruction kind. Registered into `EFFECT_HANDLERS`, dispatched by dict lookup.
  `engine/handlers/_common.py` holds shared helpers (target resolution, filter
  matching, damage application).
- `engine/subject_filters.py` — **what a printed noun phrase means, tested
  against one permanent**. `handlers/_common.permanent_matches_filter` is the
  pure half; three keys need the game (a keyword is layer 6, "you control" is a
  seat, "another" is an identity), so `subject_matches` is the one answer and
  `TESTABLE_SUBJECT_FILTER_KEYS` names exactly what it tests. A compiler admits
  a narrowed line only when every payload key is in that set — outside it, the
  line refuses, because a restriction the matcher cannot test is one the
  dispatcher would silently ignore. `OBJECT_ONLY_FILTER_KEYS` is the subset a
  caller with no observer and no source (a forced-sacrifice prompt, a cost
  charger) may be handed. The key set is held to what
  `tests/engine/test_subject_filters.py` *demonstrates*, one key at a time: a
  key listed without a matcher behind it admits every card printing that phrase
  and then drops the phrase.
- `engine/pt.py` — the single write API for power/toughness (`set_base_pt`,
  `add_pt_modifier`, `switch_pt`). All P/T mutation goes through here, never
  direct metadata pokes; see "P/T channels" in `engine/ARCHITECTURE.md`.
- `engine/replacements.py` — CR 614 "if X would happen, Y instead" interceptors,
  registered by event kind (`life_gain`, `damage_to_creature`, `would_die`).
  Each registration is a pure `applies` predicate plus the effect, and an
  explicit `order` — see `engine/effect_ordering.py`. An interceptor produces no
  instruction, so a permanent whose *only* ability is one is held up by
  `REPLACEMENT_LINES`: the phrases this file implements in full, read both by
  the grammar's parse claim (`engine/grammar/registries.py`) and by the support
  gate (`_derived_static_claims`). Adding an interceptor means adding its line
  there, or the card is unsupported however well the interceptor works.
- `engine/replacement_choices.py` — for a replacement that is optional or offers
  a choice: the interceptor offers a `ReplacementChoice` (seat, option labels,
  default) instead of applying the effect, and a `@replacement_choice(kind)`
  resolver finishes it. Interactive seats queue on
  `game.pending_replacement_choices`; every other seat takes the default at
  once, through that same resolver. Two registrations, no new `Game` field.
- **Drawing is one seam.** `Game._draw_with_replacements` is where a draw
  becomes a CR 614 event; `PlayerState.draw` is the library operation
  underneath. Reaching for the latter skips every armed draw replacement, which
  five handlers did until round 61 — so it is banned outside the seam by
  `tests/engine/test_draw_seam.py`, whose allow-list holds only the pregame
  draws (CR 103.4: no battlefield, so no replacement can exist) and names them
  with that reason. **And draws are made one at a time.** A prompt armed
  while a seat's draw is being made is stamped with that seat
  (`replacement_choices.DRAW_OF`), and a later draw for it is parked
  (`Game.parked_draws`) until the answer — CR 616.1f finishes one event
  before the next begins. Without it a declined replacement remade its
  draw, a second replacement asked about that one, and the draw *behind*
  armed its own offer beside it: 69 of 198 pairs of draw replacements left a
  multi-card draw with two prompts each refusing the other (Abundance with
  Pursuit of Knowledge, found by a person playing them). A doubler has one
  opportunity per event too (CR 614.5), passed down every tail as
  `exclude_sources`.
- **Discarding is one seam, and the event says who caused it.**
  `Game._discard_card` raises the CR 614 `discard` event and announces the
  discard; the event carries `cause_seat` (`discard_cause_seat`: the seat
  resolving, or the one a prompt recorded when it was armed), because "a
  spell or ability an opponent controls causes you to discard this card"
  (Dodecapod's replacement, Psychic Purge's trigger) is a question about the
  cause and a seat answering a prompt is no longer resolving anything. Seven
  shipped ways of discarding went round it until Apocalypse — Megrim never
  fired for Wand of Ith, Sirocco or Balance's hand half, and Psychic Purge
  never triggered off Coercion.
- `engine/mana_payment.py` — **whether a cost can be paid from the board, and
  how**. Two different questions: casting and activating spend the *pool*
  (`_pay_mana_cost`), because producing mana is the player's own prior action;
  an effect that says "you may pay {1}{B}" gives its player no priority window,
  so it must also tap lands - **for mana**, one at a time, through
  `Game._pay_planned_cost`, which re-asks the planner after each tap (so an
  adder's extra mana counts) and then spends the pool. The plan used to tap
  with `become_tapped` and deem the cost paid: no mana ability ran, so a
  painland dealt no damage and no watcher of "taps a land for mana" saw it.
  `plan_payment` answers the second, exactly (an
  augmenting-path matching of coloured pips to lands, because a greedy pick
  under-reports a board that could pay and CR 601.2h asks what a player is
  *able* to do), over the lands whose tap would in fact pay
  (`Game.payment_lands` — five lands answered "can pay" and then failed).
  **What a mana ability *is* is one predicate here, `is_mana_ability`** (CR
  605.1a), and it asks all four criteria: no target, could add mana, not a
  loyalty ability, and - in the rules since September 2026 - neither its cost
  nor its effect moves a card to or from a library. So Chromatic Sphere and
  Odyssey's five Eggs ("Add …. Draw a card.") and Millikin and Charmed
  Pendant ("{T}, Mill a card: …") use the stack, can be responded to, and are
  refused in the middle of a payment; Barbed Sextant's draw "at the beginning
  of the next turn's upkeep" is a delayed ability's (CR 603.7) and leaves its
  mana ability one. The effect half is asked **fail-closed**: a zone-moving
  step beside an add-mana step is presumed to reach a library unless it has
  been read and does not (`LIBRARY_SAFE_ZONE_KINDS`), and
  `tests/engine/test_mana_ability_library_criterion.py` fails on one nobody
  has read. Activation, the tap seam, the payment prompt, the AI and Faith's
  Fetters all ask this one function, which is why the rule change was one
  edit.
  A cost is a symbol dict everywhere — `generic_cost(n)` is the
  one line that turns a legacy number into one. **The planner is told who is
  paying** (`plan_payment(..., payer=)`): a seat holding a CR 106.6 spending
  permission (Celestial Dawn, Sunglasses of Urza, False Dawn's turn-long
  one) is planned by one matching over floating units and lands, and an AST
  guard fails a planner call that names no payer — under Celestial Dawn
  1,559 of 2,054 payable effect costs were refused while the castable
  highlight said yes.
- `engine/pending_choices.py` — every *other* decision a seat owes part-way
  through a spell, an ability or a turn step (a discard, a library search,
  Balance's removals, Power Sink's payment). One `PendingChoice` queue on
  `Game.pending_choices` and one `ChoiceSpec` per kind, registered in the table
  at the bottom of `engine/mixins/stack/choices.py`: how it is answered, what a
  non-interactive seat does instead, which action answers it, and how the web
  layer renders and gates it. `web/prompts.py` holds the renderers and the three
  loops that drive it. Adding a prompt is one `register_choice` + one renderer +
  the code that arms it — never a new `Game` field, and never another branch in
  a per-card cascade.
  **While a prompt is owed, the game waits**, and that too is the registry's
  answer rather than a list of kinds. A prompt armed part-way through a
  resolution records the stack object that armed it (`_stack_item`, stamped in
  `arm_pending_choice`); the object stays on the stack, `Game.waiting_prompt`
  reports the decision, and no step advances and nobody receives priority until
  the last of that object's prompts is answered (CR 608.2, CR 117.3b) — including
  a prompt armed by *answering* an earlier one, which is how a chain of decisions
  stays one resolution. `ChoiceSpec.holds_priority` is which kinds count, derived
  from `blocked_detail` so "refuses every action" and "the game waits" cannot
  disagree. This was three kinds named by hand in `pass_priority` and one more in
  `web/turn_steps.py`, so Sanctum of All's "you may search your library" logged
  itself resolved, left the stack a decision early, and let the turn run on to
  the main phase with the offer still on screen.
  One kind is **hidden until the last answer arrives**: `secret_number`
  (Goblin Game's "each player hides at least one item"). An answer is written
  to the resolution scratchpad and nowhere else — no log line, no payload
  field for any other viewer — and a test serialises the state for the other
  seat, a spectator and the answering seat between answers.
  **A private look stays private in the log, and its owner orders what it
  puts back.** Every viewer is sent the whole log, so a line names a card a
  look kept or a search found only where the table may know it
  (`Game.find_is_public`: a printed reveal, a public destination) — ten
  looks and seven tutors had told the opponent which card went to hand.
  And "the rest on the bottom of your library in any order" is the looker's
  order to choose (CR 401.4): `Game.offer_library_bottom_order` arms the
  `reorder_library` prompt with `position: "bottom"` for an interactive
  seat, for the look-and-pick family and the Apocalypse recruiters alike.
  Abundance's is asked too, since a draw now waits for the one in front of
  it, and what is put on **top** "in any order" is the library owner's as
  well (`Game.offer_library_top_order` — Lodestone Bauble, Reinforcements).
- `engine/commander.py` — CR 903, the Commander variant and its Brawl option
  (CR 903.12). Opt-in like `engine/ante.py`: every seam is inert unless
  `Game.commander_variant` is `"commander"` or `"brawl"`, so an ordinary duel is
  untouched. **Colour identity (CR 903.4) is derived here, not read off the
  ingested Scryfall field** — a token, a test fixture and a card the engine
  invents have no field and would come back colourless, which is the value that
  passes every deck check; `tests/rules/test_commander.py` holds the derivation
  to Scryfall's answer over the whole pool. **The commander designation is
  per-seat, by card-object identity** (CR 903.3: an attribute of the card, kept
  across every zone change), because a `Permanent` is a new object each time it
  enters the battlefield. Identity is what keeps a token copy — a fresh
  `CardDefinition` carrying the copied name — from being the commander; the
  owner check is what keeps an opponent's copy of the same catalog-shared
  object from being one.
  Both halves of CR 903.9's return to the command zone are optional, and both go
  through one `ReplacementChoice` kind. **CR 903.9b is why every "put this card
  into a hand / a library" in the engine goes through
  `Game.put_card_into_hand` / `put_card_into_library`**: the rule has no single
  fire site — a bounce, a tuck, a regrowth and a draw are all "would be put into
  its owner's hand or library from anywhere" — and thirty fire sites is
  twenty-nine places to forget it. Deck construction is `web/deck_legality.py`'s
  `commander` / `brawl` rows, which opt in with a `variant` key and are mirrored
  in `web/static/legality.js`.
- `engine/prevention.py` — CR 615 damage shields, `@prevention_effect(order,
  applies=…)` functions over one `{recipient, amount, source, combat}` event.
  `recipient` is a player *or* a permanent, so a shield that applies to both is
  written once. A new "prevent …" card is an entry here, never a branch in a
  damage path.
- `engine/shields.py` — the *state* those interceptors read: one `Shield`
  collection per recipient carrying what it answers to, how much it absorbs,
  how many uses remain and its lifetime. Adding a shield is one registration
  plus a `Shield` — never a new `PlayerState` field and never a clearing line in
  a turn step, because the sweeps read `lifetime`. The old per-card field names
  (`damage_prevention_pool`, `color_prevention_shields`, …) survive as views
  over the collection for the web payload and the AI simulator.
- `engine/effect_ordering.py` — CR 616.1, the process both registries above run
  through: gather every applicable effect, let the affected player choose one,
  apply it, re-ask the rest (616.1f). That is why applicability is a *separate,
  pure* predicate — an effect that answered "do I apply?" by applying itself
  would make the contenders uncountable. Purity is also what lets the choice be
  *asked*: at a contended round nothing has been applied, so the event is simply
  re-run once answered. A caller that can be re-run passes a `restart` thunk to
  `apply_replacements`, or `asks=True` to a damage entry point.
- `engine/resumption.py` — what makes that safe when the event was one step of
  something larger: a loop records the rest of itself before each step, so
  answering resumes the targets, instructions and resolution tail behind it,
  innermost first. **A loop using it must be the last thing its function does.**
  Every damage path asks, combat included — the combat damage step's dealing
  half is nested resumable loops and its completion flags are the last step of
  the outermost one.
- `engine/damage_events.py` — a damage event start to finish. CR 120.4's two
  halves (the damage is dealt; then what was dealt is processed into its
  result), with 616.1's contention set — shields *and* replacements together —
  inside each. `deal_damage` returns both numbers, because Ali from Cairo caps
  the life lost without capping the damage dealt, and lifelink reads the latter.
  Every damage path calls it; there is no half-event entry point, and order is
  compared across both registries so a collision raises at import.
  **The event also carries who dealt it** — `damage_source_seat`, derived inside
  `deal_damage` so no call site has to remember it. `source` alone cannot
  answer: for a spell it is a `CardDefinition`, the card as printed, shared by
  every copy and controlled by nobody. So the seat is the control seam's for a
  permanent, its last controller for one that has left
  (`control.LAST_CONTROLLER`, stamped by the removal transition and read by
  `Game.controller_or_last_known`; the seat it entered under where nothing
  stamped one - a stolen creature paid its lifelink to its owner until Bomb
  Squad), and otherwise
  `Game.resolving_seats[-1]` — CR 109.5's answer, pushed around
  `_execute_oracle_instruction`. "A source you control" (Fiery Emancipation,
  Chandra's Pyreling) reads it.
- `engine/faces.py` — multi-face cards (CR 709; split cards are the first
  layout). **A face is a card**: each half is derived once as a normal-layout
  `CardDefinition` of its own (name, cost, mana value, colours, type, text)
  carrying `face_of`, and that half is what compiles and what the stack holds —
  so CR 709.3b (on the stack only the cast half's characteristics exist) is
  true for every stack reader with no edit, because they all already read
  `item.card`. CR 709.4 (everywhere else the card is both halves combined) is
  one function, `whole_card`, asked at the zone seams. A split card is cast
  **by the name of the half**; the whole card's own program is supported only
  if every half is and **has no instructions**. That last fact is the trap:
  a guard or instrument whose population is "each card, compiled" passes
  over every half without examining one — blind, not red. Anything that asks
  about *text that compiles* iterates `faces.compilation_units(pool)` /
  `oracle.compiled_units`; anything that asks about a *card* (one draw, one
  deck slot, one verification row) keeps the card. Held by
  `tests/engine/test_face_blind_guards.py`, an AST scan with a four-entry
  allow-list of loops that really do ask about a card. A later layout joins
  `faces.CAST_FACE_LAYOUTS` and `oracle.SUPPORTED_LAYOUTS`.
- `engine/cast_costs.py` — additional costs to cast (CR 601.2b, 601.2f–h),
  including the two keywords that are **rewrites onto it**: buyback
  (CR 702.27a) and kicker (CR 702.33a: "Kicker [cost]" *means* "You may pay an
  additional [cost] as you cast this spell"). `oracle.expand_ability_lines`
  applies both, so neither word is in `IMPLEMENTED_KEYWORDS`; the client is
  offered the price through `legality.cast_cost_offers`, and whether it was
  paid survives on the stack item as `choices["additional_costs_paid"]`.
  "Kicked" has three readers and they are at three different times: a spell's
  resolution (`ast.WasKicked`, condition `was_kicked`), the permanent
  afterwards (`cast_costs.KICKED` metadata — Skizzik asks at the end step,
  turns later; a permanent that did not come from a cast was not kicked), and
  a trigger watching casts (`cast_kicked`). A target printed only in the
  kicked half is chosen only if kicked (CR 702.33g, `targeting._as_kicked`).
  **A kicker cost need not be mana and a card may print two.**
  "Kicker—Sacrifice a land." goes through the path buyback's Constant Mists
  form takes, keyed by `AdditionalCost.optional_key`; "Kicker {1}{G} and/or
  {2}{U}" (CR 702.33b) is two offers, so `kicker_costs` is a **tuple**,
  `kickers_paid` says which were taken, the permanent is stamped `KICKED_WITH`
  beside `KICKED`, and `was_kicked` carries a `kicker` key for "kicked with its
  {1}{G} kicker" (CR 702.33f) — which is why `_as_kicked` takes the *paid keys*
  rather than a bool. `target_was_kicked` asks the question of the **targeted**
  spell: Ertai's Trickery ("Counter target spell if it was kicked") compiled
  supported and asked whether *it* had been kicked, so it never countered
  anything. **"Kicked with its {1}{U} kicker" is also an entry state**
  (`enter_effects.kicked_entry`, the five Volvers): a keyed line applies only
  when its key is in `KICKED_WITH`, two such lines may both apply, and a
  copy of a kicked Volver was not kicked (CR 707.2). A kicker's `{X}` may
  carry a spend restriction (`OptionalManaCost.x_one_of_each_color`,
  Emblazoned Golem), enforced by setting aside one real unit of each colour
  — and a card printing that sentence over an X nothing charges that way is
  refused by the support gate. **A permanent named to pay an additional
  cost pays it, or the spell is not cast** (CR 601.2h;
  `casting._named_cast_cost_refusal`, the cast-side twin of the activation
  gate's `_named_cost_refusal`): 43 of 43 spells had substituted a default
  for an illegal named payer. A bare cast still chooses one. **Which cards
  a counted graveyard cost exiles is the caster's to name too**
  (`cost_graveyard_indices`; Skeletal Scrying, Haunting Misery). **A cost
  may be the choice of a number** ("choose a number between 0 and 5", Liquid
  Fire): `AdditionalCost.choose_number` charges nothing, and the number is
  the cast's announced X (CR 601.2b), so it rides `x_value` - the wire, the
  stack object, a copy. **And an alternative cost or a waiver still owes
  what a tax adds** (CR 118.9d; `Game.alternative_cost_mana`): the two
  branches that pay no mana cost never asked, so Force of Will was free
  under Sphere of Resistance - 43 of 43.
- `engine/cast_prohibitions.py` — **may this card be cast at all** (CR 601.3):
  the run of refusals the cast path makes before any cost, as one table in the
  order it logs them, behind `cast_prohibition(game, seat, card)`. Three
  readers make that one call — the cast path, the AI's proposal gate and the
  web's castable highlight — so a ban the next set prints is asked by all three
  because there is one place to add it. They were three lists: the AI proposed
  a cast the engine refused under six prohibitions (and re-proposed it every
  turn), and the highlight asked two of thirteen. Each row declares what it
  binds, because some bind land plays and most must not (CR 305.1) — Arcane
  Laboratory refused a land drop after the turn's one spell until it did.
  Held by `tests/engine/test_cast_prohibition_readers.py`, which also fails a
  reader that calls a row's predicate itself.
- `engine/board_payment.py` — `board_can_pay`: **can this seat pay this cost
  from its pool plus what its untapped lands would add**, answered by
  `mana_payment.plan_payment` over what each land's tap really yields. It is
  what the castable highlight and a hand ability's button ask. They used to
  sum each land's possible colours into one pool, so a two-colour land counted
  once per colour: Craw Wurm over three Tropical Islands glowed and the cast
  was refused — 3,543 of 14,626 land-and-cost pairs. Lands only, on purpose: a
  creature's or artifact's mana ability is the player's to activate first.
- `engine/piles.py` — separating into piles (CR 700.3). One instruction,
  `separate_into_piles`, over three kinds of thing (revealed cards, graveyard
  cards, permanents): one seat separates (`pile_split`), another chooses
  (`pile_choice`), and what happens to each pile is payload
  (`piles.PILE_FATES`). Nothing moves until the last answer.
- `engine/flashback.py` — flashback (CR 702.34), which the rules define as
  two static abilities and which this engine already had as three things it
  had never joined: a **permission** to cast from a graveyard (the card's
  own, derived from its text while it sits there), an **alternative cost
  that permission requires** (CR 118.9b; `CastPermission.cost`, an
  `AlternativeCost` whose `mana` field is the one thing that class lacked),
  and a **destination** as the card leaves the stack
  (`leaves_stack_to_exile`: "any time it would leave the stack", so
  countered and fizzled as well as resolved, and it wins over a buyback
  that was also paid). The keyword line is a **rewrite** in
  `oracle.expand_ability_lines`, beside buyback and kicker, so the word is
  not in `IMPLEMENTED_KEYWORDS`; whether a cast was a flashback is a fact
  about one cast and rides `StackItem.flashback`. "Has flashback"
  (Tombfire) is the printed keyword *or a grant* (Recoup), so
  `has_flashback` takes the game. A spell cast from a graveyard names its
  targets through the picker a hand cast uses: 54 shipped cards castable by
  an older permission had read the *hand* slot for theirs.
- **Threshold is an ability word and one condition.** CR 207.2c gives the
  word no rules meaning, so `strip_ability_word` drops it and what is left
  is "seven or more cards are in your graveyard" - `cards_in_zones`, asked
  where each of its three printings already had a seam: a conditional
  static (`static_bonuses.conditional_static_holds`), an activation
  restriction row (CR 602.5, `activation_restrictions.py`), and a spell's
  "instead" (`oracle.expand_instead_paragraph_lines` rewrites the paragraph
  into the conditional the grammar already read). A count over "each
  graveyard" refuses rather than being summed.
- `engine/destruction_events.py` — **a permanent is destroyed** (CR 701.8)
  is one event, and it says who caused it. Announced where a destruction
  is *decided* - the two destroy paths, once indestructibility, a
  regeneration shield and a land's shield have each declined to replace it
  - and nowhere else, because CR 701.8b makes a sacrifice and a
  state-based move to the graveyard not a destruction and the board cannot
  tell them apart afterwards (Karmic Justice asks). The cause is CR 109.5's
  resolving seat by default; a delayed destruction records the seat when
  its mark is set (`mark_delayed_destruction`), a state-based one passes
  `NO_SPELL_OR_ABILITY`, and a move that is not a destruction says so. It
  is the discard seam's arrangement one zone over, and driving every
  destroy site through it found Chaos Orb and eleven end-of-combat
  destroyers ignoring indestructible.
- `engine/state_triggers.py` — a state trigger about **another** permanent
  ("Whenever a creature has four or more fuse counters on it", Bomb Squad),
  fired once per ability and watched permanent, and CR 603.8's latch with
  both its halves: a state trigger does not trigger again while it is on
  the stack, and **does** once it has left without resolving. The second
  half was missing - a countered state trigger never triggered again, for
  all ten in the pool that reach the stack - so the latch key rides the
  stack object and both removals give it back. Twenty-four more are still
  carried out inside the state-based sweep; ROADMAP has them.
- `engine/counted_names.py` — whether a card in a zone answers to a
  **name** (CR 201.2a over a *set* of names, so a split card is named by
  both halves) and the one printed static that widens it: "If this card is
  in a graveyard, effects from spells named Flame Burst count it as a card
  named Flame Burst" (Pardic Firecat). Text-keyed; both names are payload.
- **"Tapped for mana" is one event** (CR 106.12):
  `Game._land_tapped_for_mana` holds the per-turn record, the CR 106.12b
  replacement, the production, the Aura adders and the triggers, and three
  roads call it - the explicit tap, a cost an effect collects (above), and
  a land whose mana ability costs more than {T} activated through the
  activation path. Two of the three told nobody until Odyssey printed
  Price of Glory. The seven such triggers that are not mana abilities
  still resolve at the tap rather than on the stack; ROADMAP has the parts.
- `engine/object_colors.py`, `engine/color_census.py` — colour as a relation
  and as a count. `share_a_color`, `is_multicolored`, `colors_among`,
  `of_each_color` are CR 105.2 over colour *sets*, so a sweep filter, a
  prevention predicate, a cast ban and a condition all ask one function; the
  census is "the most common color among all permanents", ties included,
  empty when no permanent has a colour. Both read colour through the layers.
- `engine/tokens.py` — `make_token_card(...)`, paired with the generic
  `create_token` instruction kind. A token-making card is one parse rule, never
  a bespoke handler.
- `engine/targeting.py` — what a spell or an ability targets, derived from the
  *compiled program* (Aura enchant line, instruction kind, `targets` /
  `type_filter` payloads) rather than from a second reading of the oracle text.
  `derive_cast_spec` answers per card, `derive_activation_spec` per **ability**
  — an ability picks its targets on activation (CR 115.1c) and one permanent may
  carry several that target differently. Both share one kind→spec table: what an
  instruction targets does not depend on whether a spell or an ability produced
  it. Returns None when the program lacks the evidence rather than guessing; the
  guards in `tests/engine/test_targeting.py` and
  `tests/engine/test_activation_targeting.py` ratchet what still needs
  `legality.py`'s one surviving text fallback. **Whether an ability may be
  activated at all is `legality.activation_target_refusal`** (CR 602.2b/601.2c):
  one gate, read once in `mixins/stack/activation.py` before any cost is paid,
  over the same `_enumerate_targets` list the web picker gets — so the engine
  and the picker agree on what is a legal target, and an ability with a
  mandatory object target it cannot fill is refused with nothing paid rather
  than activated to hit the face (Silent Dart) or no-op. It replaced a per-kind
  if-chain that named four instruction kinds and left every other one
  unenforced.
  **The gate asks one question of every ability** —
  `legality.activation_target_obligation`, the picker's own slot and its
  printed quantifier — and compares a *named* target with the picker's list
  whether or not one was owed. It used to walk for a quantifier it
  recognised, so 159 of 818 abilities accepted a target their picker does not
  offer (93 print "any target": a Prodigal Sorcerer could be aimed at a Sol
  Ring) and 21 that must target could be activated at nothing. A named *cost*
  permanent is paid as named or the activation is refused
  (`_named_cost_refusal`; the default used to be substituted in silence — CR
  601.2h), an activated ability whose named graveyard card has left does not
  go looking for another (`vanished_graveyard_target_refusal`, bounded by
  `StackItem.activated`), and over the wire an activation that owes a target
  and names none is a 400. One thing is deliberately still open, by
  measurement: a bare activation **with a legal target available** resolves
  on the handler's pick, the headless convention 43 tests stand on; ROADMAP
  has the parts.
  **A spell has both ends of the same question.** `legality.cast_target_refusal`
  is CR 601.2c at announcement — the named target must be one
  `_enumerate_targets` offers, checked beside `_validate_cast_targets` (not
  inside it, which would recurse through its own per-candidate probe) and
  before mana is spent; `legality.illegal_targets_refusal` is CR 608.2b at
  resolution — if **every** target is illegal by then, the object leaves the
  stack unresolved, above the instructions rather than inside each handler.
  **And before either of those, whether there is anything to name at all.**
  `legality.no_legal_cast_target_refusal` is CR 601.2c's other half — a spell
  that must announce a target cannot be cast with none — over the picker's own
  list, and asked by the engine, the AI and the web's castable highlight
  alike. It replaced a per-kind arm keyed on the spell's *first* instruction,
  which a `sequence`, `may` or `if_then` never reached: 182 spells were
  castable at nothing, and the same arms refused eight spells that may
  legally name nobody. A target that is **a spell on the stack** has the same
  gate (`cast_stack_target_refusal`), and the stack picker reads every type a
  spell has (CR 205.2) — it read `primary_type` until that list became the
  gate, which made Annul refuse an artifact creature spell.
  A handler declining its own target is the rule's *last* sentence only, so
  "Destroy target artifact. You gain life equal to its mana value" gained the
  life for destroying nothing. Both read targets by `permanent_id`, never by
  index, and **both ask the same predicate** —
  `LegalityMixin._described_cast_target_slots`, the whole enumeration of what
  the printed target phrase admits — so a Terror target turned black in
  response is illegal at resolution exactly as it would have been at
  announcement. It asked only "still there and targetable?" until Nemesis, and
  130 resolutions in a census acted on an illegal target, most of them on a
  bystander a handler's fallback scan found. **A modal spell is held to the
  mode it announces** — `targeting.announced_mode_instructions` is the one
  derivation of what mode *n* targets, read by both gates, by the picker
  (`Game.cast_target_spec(mode_index=)`) and by the highlight
  (`Game.announceable_modes`). It was "excluded (their derived spec is mode
  0's)" until Planeshift printed five Charms: an illegal permanent named for a
  mode was accepted in 1,066 of 1,516 cases, and the web kept its own per-mode
  table, which sent the wrong picker for 33 of 47 object modes. The same round
  made a printed count a count (`legality.exact_target_count` — "two target
  creatures" naming one was accepted 19 times in 19) and refuses a division on
  a spell that divides nothing. A cast naming no mode is judged as mode 0.
  **A named player is a target like any other.** Both gates read
  `stack_targets.announcement_targets`: for a spell whose only target is a
  player the seat is the target, for "any target" it is the target only when
  no object is named, and each entry of a division is its own. The cast gate
  had checked a named permanent and never a named player — 591 of 774 casts
  accepted a seat the picker does not offer, a Lightning Bolt reached a
  player behind an Ivory Mask — on a decline ROADMAP carried for a reason
  (`target_player_index` is ambiguous) that `stack_targets` had answered two
  sets earlier. The announcement gates are a spell's; **the resolution gate
  is asked of every object whose targets somebody chose** — a spell, an
  activated ability (`StackItem.activated`) and a triggered ability whose
  target was chosen through its own picker (`StackItem.targets_chosen`),
  the last two through `ability_target_verdicts`, the activation picker's
  list asked again. It was spells only until Apocalypse: 479 of 622
  single-target activations did something wrong with an illegal target
  (Savage Gorilla drew its card; 185 hit a bystander). **And each target is
  judged separately in an object that still resolves** —
  `legality.blank_illegal_resolution_targets` rewrites every illegal slot
  before any instruction runs, so a handler meets a departed target rather
  than a stale index (42 of 48 multi-target spells had acted on a target
  given shroud in response). A trigger target *stamped* by a fire site, or
  defaulted while a permanent is on its way to a graveyard
  (`Game.departing`), is not marked and not judged; that and the other
  declines — an ability printing "target" twice with one derived slot, a
  roles slot that is not a permanent, an Aura or an ambiguous graveyard
  target — are in `ROADMAP.md` with the reason each is a separate round.
  **A spell may be one slot of several.** "Counter target spell and … deals
  3 damage to target creature" (Suffocating Blast) is a roles announcement
  with a stack role (`targeting.role_is_stack`): both targets are owed at
  the cast, each half survives the other's target becoming illegal, and
  the wire carries `target_role_refs` with a `stack_index`. "Target spell
  or permanent" is one slot in either zone (`spell_or_permanent`, the
  Laces' picker — the noun phrase used to keep only the permanent). A
  stack target named for an object that targets nothing on the stack is
  refused (`legality.stray_stack_target_refusal`; it was accepted and
  ignored by 888 of 888 casts). And **a slot list of two printed targets
  is a count, not a ceiling** (`targeting.slot_list_is_exact`).
  **"Up to N target cards from a single graveyard"** (Decompose, Ebony
  Charm) is a slot list out of one pile (`targeting.SINGLE_GRAVEYARD`),
  announced at the cast or the activation and held by both gates; it was a
  choice made at resolution, so nothing could respond knowing which cards.
  **Two players may be two roles of one cast** (Cultural Exchange:
  `choices["role_seats"]`, and `target_role_refs` entries that carry a
  `seat`) - a player named for one role of several had never become a
  target at all, 30 times in 30. **And a stack target names its
  controller**: `Game.stack_target_seat` is `announced_target_seat`'s twin
  for an object whose every chosen target is a spell (CR 112.2), which is
  what "its controller" after "counter target spell" reads - Undermine had
  never made anyone lose life.
- `engine/target_requirements.py` — **a target an opponent must choose**
  (the Flagbearers: "…that player must choose at least one Flagbearer on
  the battlefield if able"). A text-keyed table whose noun is payload, and
  two gates over a *whole announcement*
  (`Game.cast_target_requirement_refusal`,
  `activation_target_requirement_refusal`), asked before anything is paid.
  Deliberately **not** a narrowing inside `_enumerate_targets`: that list
  also serves resolution, retargets, copies and every trigger, all of which
  the card's ruling exempts. "If able" is the un-narrowed list, so
  protection, shroud, a wrong type and a player-only spell bind nothing. A
  one-slot picker is narrowed to the Flagbearers; a several-slot, divided
  or roles picker keeps its list and carries `required_targets`, which the
  client shows and holds its confirm on. The AI asks the same gate, so it
  re-aims burn at the Flagbearer and does not propose a pump it would have
  to gift. Held by `tests/engine/test_target_requirement_census.py`.
- `engine/stack_targets.py` — **which targets a stack object chose**, and how
  they may be changed (CR 115.7). `chosen_targets(item)` reads every
  announcement channel a `StackItem` carries against the object's derived
  spec, so a chosen player and a permanent's seat — which share
  `target_player_index` — are told apart by which channel the spec says is the
  target. Every way an object comes to have targets announces it once through
  `Game.announce_targets_chosen`: a cast, an activation, a trigger's target
  whether defaulted or answered, a modal mode, a re-aimed copy, a retarget.
  "Becomes the target of a spell or ability" and Psychic Battle's "whenever a
  player chooses one or more targets" both hang off that seam; an object with
  no targets, or an "up to" that named none, does not fire it. Held by
  `tests/engine/test_stack_targets.py`, a pool-wide census in which every
  targeted cast and activation reads back the target its own picker offered.
- `engine/cost_modifiers.py` — text-keyed cost taxes (CR 601.2f): "<colour>
  spells cost {N} more to cast", "activated abilities of <colour> <type>s cost
  {N} more to activate". This entry read "increases only; reduction should
  arrive with the card that needs it" for a long time after that stopped being
  true — the cards arrived, and the module's own docstring says so. **Both
  directions are live**, and they are not one mechanism with a sign: CR 118.7a–d
  makes a reduction touch only the generic component, fall back to generic where
  the cost has no mana of that colour, and spill an excess coloured reduction
  onto generic. That arithmetic is `reduce_cost`, in one place, because getting
  it wrong makes a spell castable that is not.
- `engine/continuous.py` + `engine/layer_bridge.py` — the CR 613 layer system.
  Characteristics are **computed**, not stored: `has_type`, `is_creature`,
  `effective_power`, `has_keyword`, the colour accessors and
  `Game.controller_index_of` all resolve through it. Layers 2–7 are live.
  Anything asking "what type/colour/P/T is this?" must go through these
  accessors — reading `card.type_line` or a metadata flag instead is how the
  same question ends up with several disagreeing answers, which is the bug
  class `tests/engine/test_layer_reads.py` guards.
  **"What does it say?" is the same question**, and its accessor is
  `Permanent.effective_card`: layer 1 folds in what the permanent copies
  (CR 707.2), layer 3 folds in a text change (CR 612.1), and a board-wide
  static's granted ability is appended after both. `perm.card.oracle_text` and
  `perm.card.keywords` are the card as printed, so a Clone of a Wall had no
  defender and a Magical Hack rewrote a word nothing then read; that guard
  ratchets both fields too, and a keyword additionally wants `_has_keyword`,
  which asks layer 6 as well.
  **Its folds are memoised by what the card *is*, never by `id()`.** A card
  with lines granted, struck or stripped is built once and kept, keyed by
  `copies.card_identity` — the card's printed fields. Four of those memos
  were keyed by `id(card)` until Apocalypse, and CPython hands a freed
  object's address to the next allocation: a creature given an ability by
  an Aura read as *another creature* — its name, its power, its toughness —
  whenever a card object freed earlier in the process had been granted the
  same words. The catalog's definitions never die; a token, a token copy
  and a test's invented card do. It surfaced as one "flaky" test in a full
  run and was named by replaying that test's scenario after every other
  test. `tests/regressions/test_derived_card_memo_identity.py` fails any
  module-level dict under `engine/` keyed by an `id()`.
  **Layer 5 is ordered by timestamp (CR 613.7), and a colour is written through
  one API.** `engine/color_changes.change_color` puts the stamp inside the
  write, and `Permanent.timestamp` (CR 613.7d; re-stamped on attach, 613.7e)
  comes off the clock layer 2 already used. Colour effects had been ordered by
  *what kind of effect they were* — so under Darkest Hour or Shifting Sky a
  later "becomes black until end of turn" did nothing, 145 of 362 ordered
  cases — and eight handlers wrote the colour slots directly, which is the
  `become_tapped` problem; `tests/engine/test_color_write_seam.py` fails a
  ninth. A permanent's own "is the chosen color" (Alloy Golem) is ordered
  by the permanent's timestamp like everything else. It shipped as a
  characteristic-defining ability and that was a ruling to settle: a CDA
  "functions in all zones" (CR 604.3) and does not set its value "only if
  certain conditions are met" (CR 604.3a), and a colour chosen as the
  permanent enters does neither. The reasoning, and the one argument that is
  the other reading, are beside the call in `layer_bridge`.
  **Layer 4 is applied once for the whole board, with dependency**
  (`engine/type_statics.py`, CR 613.8): a static whose scope is a type waits
  while applying an effect not yet applied would change what it reaches, is
  re-asked after every application, and does not wait on another member of a
  dependency loop. One effect per step, so the walk ends in exactly as many
  steps as there are effects. It replaced three refreshes that chained by
  timestamp alone — Conversion then Blood Moon was a Mountain — and the
  census that found three wrong meetings now holds 61, fifteen of which were
  wrong. One-shot type changes are written through `engine/type_changes.py`
  (`gain_types` / `lose_types`, the stamp inside the write), with a guard
  that fails a sixth direct writer.
  **CR 305.7 is one strike, in `effective_card`.** A land whose type an
  effect *set* has no ability of its own for any reader — static, triggered,
  activated or mana — and keeps what another effect granted it; "in addition
  to its other types" is not a set. The Tabernacle at Pendrell Vale under
  Blood Moon went on taxing every creature while six readers each asked the
  predicate for themselves and a seventh read the printed text. It reaches a
  land *entering* under the effect too (CR 614.12,
  `Game.fold_land_type_statics_onto_entering`). `Game.lost_abilities_refusal`
  is the door's answer and the payload's `abilities_lost` the client's — and
  the client reads that field, `taps_for_mana` and `produced_mana`, never the
  text, to decide that such a land is clicked for mana.
- `engine/control.py` — CR 613 layer 2. A control change is a **contribution**
  (`change_control(permanent, seat, source=…)`) with a timestamp, not a move;
  ending one is `end_control_change(permanent, source=…)`, and whatever
  contributions remain decide. `base_controller_index` is the seat the
  permanent entered under and is never rewritten, so an ended effect reverts
  correctly and CR 108.3 ownership reads off it.
- **The control seam on `Game`** — `all_permanents()`,
  `permanents_with_controller()`, `controlled_by(seat)`,
  `permanents_matching(pred)`, `controller_index_of(perm)`,
  `controls(seat, perm)`, `is_on_battlefield(perm)`, all in
  `engine/mixins/helpers.py`. **Never iterate `player.battlefield` directly**:
  this engine keeps the battlefield lists as the *projection* of the derived
  controller (`Game._sync_control`), so a raw read is a second opinion about
  who controls what — and `in`/`.remove()` on them compares `Permanent` by
  value, which matches an opponent's look-alike. Guarded by
  `tests/engine/test_control_reads.py`; zone *writes* (rebuilding the list) are
  exempt by shape.
  **Address a permanent by its id, not its slot.** `Permanent.permanent_id` is a
  monotonic counter, stamped on entering the battlefield (CR 400.7 — a returning
  permanent is a new object, so it gets a new id). Resolve one through the same
  seam: `permanent_by_id`, `find_permanent_by_id`, `permanent_id_of`. An index
  is unstable — anything leaving renumbers every later slot, so an index held
  across a resolution step can address the wrong permanent — and locating by
  value hits the look-alike, which was six live bugs (Crumble destroying the
  first of two equal Moxen, among them). `.battlefield.index()` / `.remove()`
  are **banned outright** by that guard; positional subscripting is ratcheted
  per module. The wire carries `id` alongside `index` and resolves it once at
  the top of `web/actions.py`, where a stale id is a 404, never a fall back to
  the index.
  **An id names a battlefield as well as an object, and the engine had to be
  told.** That sentence is about the wire and was true of it — `web/actions.py`
  writes `target_seat` back off the id — and the *engine's* own announcement
  API held the opposite. `activate_permanent_ability(..., target_permanent_ids
  =[id])` defaulted the unsaid seat to the opponent's before the object reached
  the stack, and `handlers/_common.pick_target_permanent` scopes an announced id
  to exactly that seat, so an id on the activator's own battlefield was
  discarded by the resolver it was handed to and the scan beneath it took
  whichever permanent it met first. **209 shipped cards** did that (163 acting
  on the wrong permanent, 47 doing nothing) and 151 more on the cast side; no
  compiled program moved, so `oracle_diff` and every coverage instrument were
  blind to all of it and only running a card could see it.
  `Game.announced_target_seat` is the seam — the seat the ids already name, asked
  where an announcement's seat is settled, which for an activation is **before
  the cost is paid** (CR 601.2c precedes CR 601.2h, and Skull Catapult
  sacrifices the creature it is aimed at). Held pool-wide by
  `tests/regressions/test_announced_target_seat.py`, whose sweep carries a floor
  on how many announcements it examined — asked of `activate_permanent_ability`,
  which settles the stack itself, it reached zero of them and passed on the
  broken engine.
  **Combat is still index-keyed, but its maps follow their creatures**:
  `_renumber_combat_after_removal` runs from the removal transition below and
  drops an entry whose creature left, shifting the rest. Adding a combat map
  means adding it there — every index has a resolvable seat (an attacker's is
  always the active player, a blocker's comes from `combat_blockers`' outer key
  or from `_combat_seat_of_blocker`), and a map left out silently keeps pointing
  at whichever creature slid into the slot.
  **Leaving the battlefield is one transition**: `remove_from_battlefield(perm)`
  / `remove_all_from_battlefield(perms)`, also on the seam. It was 41 open-coded
  rebuilds in three spellings (filter-by-identity, `pop` by index,
  rebuild-from-survivors), which is the `become_tapped` problem again — anything
  that must happen when a permanent leaves had 41 places to be forgotten. Where
  it goes next is still the caller's business. Two writes are legitimately not
  removals and are exempted by name in `tests/engine/test_control_reads.py`:
  `_sync_control`'s move between battlefields (a control change is not a zone
  change) and the Debug Menu's wholesale board replacement.
  **And leaving a *hand* is one too, for the opposite reason.** A hand is a
  `list[CardDefinition]` and a deck repeats one immutable definition per copy
  (`web/deck_builder.py`: `[card] * count`), so every copy of a card in a hand
  is the **same Python object** — which makes
  `[c for c in player.hand if c is not card]` remove all of them where the
  caller then puts exactly one somewhere. Five sites spelled it that way and
  each deleted cards from the game: Sylvan Library put one card back and
  destroyed the other two, a forced discard binned one and vanished the rest.
  `Game.take_card_from_hand(owner, card)` removes exactly one, by index found
  through identity (`list.remove`/`index` compare by *value*, which matches a
  different printing of the same card). Guarded by
  `tests/engine/test_hand_removal_seam.py`, which also fails on any new
  identity filter over a hand. `engine/phases/upkeep_step.py` documents the
  same class found in a graveyard, where the fix was to carry the index.
- `engine/auras.py` — what an Aura's effect lines say and whether the engine
  implements them. Gates support (an Aura whose effect is unimplemented is
  reported unsupported rather than entering play and doing nothing) and derives
  the Aura's continuous effects while it is attached. Removal is the Aura
  ceasing to be attached; there is no remembered delta. Use
  `attach_aura`/`detach_aura`, never the raw metadata. Its effect templates read
  "enchanted" **and** "equipped" (CR 301.5f: both words name the attached
  permanent), so an Equipment's "+1/+1", keyword grant or restriction is the
  same derivation.
- `engine/equipment.py` — Equipment (CR 301.5), the equip keyword (CR 702.6)
  and the attach action (CR 701.3). **Equip is a rewrite, not a keyword flag**:
  CR 702.6a defines "Equip [cost]" as "[Cost]: Attach this permanent to target
  creature you control. Activate only as a sorcery.", and
  `oracle.expand_ability_lines` rewrites the printed line into exactly that
  before any line is classified — so from there it is an ordinary activated
  ability to the grammar (`Attach` node, `attach_source_to_target` kind), the
  cost parser, `activation_restrictions.py`, `targeting.py`'s picker and the web
  layer, none of which know the word. Every *other* reader of a card's lines
  (`legality.py`, `parse_coverage.py`, `hook_reliance.py`) must start from that
  same function or it is reading a different card. `equip_refusal` is the one
  legality predicate (a creature only; never itself or from an Equipment that
  is a creature, CR 301.5c; never onto protection, CR 702.16d), asked by the
  handler at resolution, by the picker at activation and by
  `unattach_illegal_equipment`, the CR 704.5n sweep — which also forgets an
  Equipment that has *left* the battlefield (CR 701.3d), read off the host at
  the sweep rather than wired into each zone-change path, because the phasing
  handler needs the record to survive removal. The support gate in
  `oracle.py` holds an Equipment to both halves: its equip ability must compile
  and every effect line must be claimed — Short Sword used to be "supported" on
  the substring `gets +` with an equip line nothing read.
- `engine/characteristic_defining.py` — characteristic-defining P/T (CR 604.3),
  one `dynamic_pt_count` instruction carrying what to count and whose
  battlefield to count it on.
- `engine/static_bonuses.py` — conditional static P/T bonuses (CR 613 layer 7c)
  in both printed word orders.
- `engine/enter_effects.py` — entry-state phrases `_initialize_permanent_state`
  carries out. `enter_effect_line` is read by the support gate *and* the
  grammar, so what is implemented and what is claimed cannot drift.
  `ENTRY_CHOICES` is the table of what a permanent may *choose* as it enters
  (a colour, a card name, a creature type, a land type, a player), and
  `web/serialization` derives the permanent's `entry_choices` from it — the
  named card on a Meddling Mage was on no payload before. **The client has to
  be able to answer the prompt as well as show the answer**: it rendered an
  `enter_choice` only when it named an opponent, so 28 shipped choosers
  soft-locked a human seat, invisibly to every engine instrument.
  `tests/ui/test_entry_choice_prompt_ui_api.py` enters every chooser under an
  interactive seat and requires the client's own code to read each question.
- `engine/combat_assignment.py` and the combat damage step — **"You may have
  this creature assign its combat damage as though it weren't blocked"**
  (Lone Wolf, Thorn Elemental, Rhox, Pride of Lions; one granted form) is an
  announcement with two answers, `resolve_combat_damage(as_though_unblocked=
  [ids])` or an ordinary assignment, and anything between is refused — the
  cards' ruling is all or nothing. A human seat is stopped for it with one
  blocker and with several (`web/combat_prompts.py`, beside banding and
  multi-block). It is **not** a `pending_choices` prompt: CR 510.1e checks an
  assignment as one announcement, and a stored answer would have to be asked
  again for each strike. Until this was driven in a browser a human had one
  of the two answers, and which one depended on the number of blockers.
- `engine/combat_restrictions.py` — text-keyed combat restrictions (CR 506):
  "can't attack unless defending player controls a <land type>", "attacks each
  combat if able", "can't be blocked by Walls". The land type is payload data,
  not part of the instruction kind.
- `engine/untap_restrictions.py`, `engine/draw_step_modifiers.py` — text-keyed
  turn-step tables (CR 502/504): "players skip their untap steps", "creatures
  with power N or greater don't untap", "that player draws an additional card".
  Same model as `cast_restrictions.py` — derived from oracle text, so a card
  printed with a known template needs no registration at all.
- `engine/cast_restrictions.py` — text-keyed "cast this spell only during..."
  timing gates (an ordered predicate table; genuinely textual, not per-card).
- `engine/activation_restrictions.py` — its twin for CR 602.5, "Activate only
  if a creature died this turn" / "…only during your upkeep" / "…only as a
  sorcery". Same shape and the same reason it is a table: the clause reads the
  same on any card printing it. It replaced a hand-written if-chain inside
  `mixins/stack/activation.py` whose branches were substring tests — so a
  printed clause nobody had listed was **unenforced**, and that is the quiet
  failure this file exists for. An unenforced restriction is not a dead
  ability; it is an ability that works more often than the card allows, so
  nothing crashes and nothing is missing. The **support gate reads the same
  table**, which is what stops a card being admitted with its clause ignored.
- `engine/card_hooks.py` — name-keyed registries for truly bespoke behavior
  (spell-resolved and counterspell riders, leave-battlefield effects,
  draw-step modifiers) plus
  `CARD_LINE_INSTRUCTIONS`, the instruction one printed *line* of one card
  compiles to. The compiler reads it after the grammar refuses and there is
  nothing after it, so a line that later grows a production makes its entry dead
  rather than wrong — and `tests/engine/test_card_lines.py` fails on a dead
  one. The entry bar is that **no second card, real or plausibly printable,
  shares the shape**: a sentence two cards could carry belongs in
  `engine/grammar/`, where the second card gets it for free.
  **This is the only sanctioned place to key behavior on a card name**, enforced
  across `engine/` by `tests/engine/test_card_name_reads.py`: a name in a
  comparison is dispatch and fails there; a name in a log line, a prompt label
  or a fixture decklist is data and does not. There are no `# TODO(card-hooks)`
  exceptions left: every one turned out to be a template or a general CR rule,
  not one card. Before writing a name, check by *behaviour* — give an invented
  card the same printed text and see whether it works. **AI heuristics are in
  scope**: a weight is tuning and stays in `engine/ai_policy.py`, but which
  cards a weight reaches is a claim about the pool and is derived from the
  compiled program in `engine/ai_valuation.py`.
  **The pile is measured too, not just each entry.** Those guards check that an
  entry is honest; `scripts/hook_reliance.py` checks how many there are, because
  a name-keyed entry buys one card while a grammar production buys every card
  printed the same way — so the hooked share of the pool is the engine's
  marginal cost per card, and the number that decides whether this reaches the
  full release line. Every ratcheted denominator is **supported** cards (the
  measure names say so), because counting cards the engine cannot play would let
  ingesting a barely-supported set read as falling reliance.
  `HOOK_RELIANCE.md` reports it and
  `scripts/hook_reliance_ratchet.json` holds **ceilings**, the opposite
  direction to the grammar ratchet's floors: adding a hook to a card the grammar
  could have read fails `tests/engine/test_hook_reliance.py`. Raise them with
  `--accept` only after deciding the rise was worth what it bought.
- `engine/landwalk.py` (a static granting landwalk of each basic land type its
  controller's lands name — Magnigoth Treefolk), `engine/mana_could_produce.py`
  ("any color that a <land phrase> could produce", whose-lands and which-lands
  as payload) and `engine/counter_conditions.py`'s class half ("Creature spells
  can't be countered") are what Planeshift added or rewrote. A text-keyed table
  is asked by `tests/engine/test_static_line_support.py` through the grammar's
  `registry_for_line`, which it has to join for its line to parse at all — the
  guard kept its own list of tables until the fourth time that list was stale.
- `engine/land_animation.py`, `engine/land_play_allowance.py` — two older
  derivation tables: "All <type>s are P/T creatures that are still lands"
  (CR 613 layers 4/5/7) and "You may play <N> additional lands on each of
  your turns" (CR 305.2). Same model as `combat_restrictions.py`: the parameters
  are payload, and the support gate reads the same table the dispatch does.
- `engine/phases/upkeep_effects.py` — `@upkeep_effect(condition, kind)` handlers
  for the interactive pay-or-consequence upkeep triggers, keyed by the
  `(trigger condition, instruction kind)` pair the compiler produces. Everything
  a handler reads arrives on `UpkeepContext`. A duplicate pair raises at import.
- **A trigger condition's narrowing is data, not a kind.** `engine/oracle.py`'s
  pattern table delimits a printed noun phrase as a `<name>_subject` group
  (`<name>_subjects` where it is *counted* rather than quantified) and a printed
  number as `<name>_count`; the noun parser and `_NUMBER_WORDS` read them, so a
  card printed with a different tribe or a different number needs no code. Two
  rows may share one kind when what differs is the question rather than the
  event (`attackers_declared`). Ability words (CR 207.2c) are dropped by
  `oracle_types.strip_ability_word`, called by **both** front ends.
- **A trigger condition needs a dispatcher, and parsing is not one.** A
  condition can be in `engine/oracle.py`'s pattern table *and* the grammar's
  phrase table and still have nothing that announces it: `draws_card` was, with
  two supported cards compiling real instructions and doing nothing.
  `tests/engine/test_trigger_dispatchers.py` asks of every condition the pool
  produces whether the engine names that kind anywhere outside the declaration
  tables — the weak question deliberately, because a trigger is announced by
  `emit`, by an `iter_triggered_abilities` scan, by the upkeep registry or by a
  phase-step comparison, and a list of mechanisms goes stale like a list of fire
  sites. Where a draw, a life gain or a sacrifice has no single call site, the
  announcement goes on the **state-based sweep** over the record every path
  already feeds (`mixins/game_ending.py`), not on the call sites.
- **A cast trigger's "it" is a stack object, not a card.** A deck repeats one
  immutable `CardDefinition` per copy, so with two copies of one spell on
  the stack a trigger that looked its spell up by card found the first: the
  cast events carry `cast_item` beside `cast_card`, and
  `handlers/_common.triggering_spell` is the one reader ("counter it", the
  copy handler, Ice Cave's price). Eight of nine such cards acted on the
  earlier spell. The class is the hand's and the graveyard's identity
  problem, found on the stack.
- **A permanent's entry trigger is a stack object** (CR 603.3), on every road
  onto the battlefield: `resolution._entry_trigger_triggers` goes through
  `_enqueue_triggered_ability` like every other trigger. It was resolved
  inline, as the permanent entered, for 268 of the pool's 278 entry triggers —
  history from the Arabian Nights commit, not a decision — so nothing could
  respond to one, and Cavern Harpy could not be returned in response to its own
  gate. **A test that casts a permanent and asserts its entry effect must
  drain the stack first** (`tests.helpers.resolve_stack`). The cast's
  announcement rides the stack object (`announced_at_cast`): an entry
  trigger's target is still *named as the permanent is cast*, a convention
  measured and deliberately kept — ROADMAP has what moving it would take.
  **That name is held to what the trigger itself could choose** (CR 603.3d):
  the cast picker offers the trigger's own list
  (`LegalityMixin.entry_trigger_cast_targets`), and an announcement the
  trigger could not have made is set aside at the push, where it chooses
  again. Nothing asked before, so a Nekrataal cast at a White Knight
  destroyed it — 16 cards, protection above all.
  Held by `tests/engine/test_entry_trigger_stack_census.py`, over three roads
  with floors.
  **So a source can now leave before its own entry trigger resolves, and a
  handler that moves something "until this leaves the battlefield" asks
  first**: `linked_exile.until_leaves_has_ended` (CR 610.3b — the object
  doesn't move), which knows that a *phased-out* source has not left
  (CR 702.26d). On the day the triggers moved, three shipped cards exiled for
  good, phased a creature out for ever, or armed a prompt nobody could answer;
  ROADMAP had named the precondition a set earlier and it was read one merge
  late. `tests/engine/test_entry_trigger_source_leaves_census.py` destroys the
  source in response to every entry trigger in the pool — the census a change
  that makes something possible "in response" owes.
- `engine/phases/` — one mixin per turn phase and per step within a phase
  (CR 500–514): beginning phase (untap/upkeep/draw steps), the two main phases,
  combat phase (its five steps), and the ending phase (end/cleanup steps). Each is
  composed onto `Game`; see `engine/phases/__init__.py` for the taxonomy. Put
  phase/step turn-based logic here.
- `engine/mixins/` — cross-cutting game flow *not* tied to a single phase:
  turn-structure navigation and priority (`phase_steps`), per-turn/pregame
  management (`turn_management`), state-based actions, effects, helpers.
  Consumes compiled programs; must never parse oracle text. **A step does
  not end on an empty stack alone**: `_resolve_priority_window`, which every
  step uses, makes the state check the players' passes would make before it
  closes and goes round again if that put something on the stack (CR 500.2,
  117.5). It used to drain and return, so whatever the last resolution set
  off was announced a step late — all ten state triggers that reach the
  stack, on the headless, the web's and the simulator's paths (Bomb Squad's
  fourth counter detonated after the draw).
- `engine/mixins/stack/` — the stack (CR 405), one mixin per stage of an
  object's life on it: `casting` (CR 601), `activation` (CR 602), `resolution`
  (CR 603/608), and `choices` — the `pending_choices` queue every
  part-way-through decision goes through, plus the table registering them.

`engine/oracle.py` is the compiler (tokenize → classify lines as
keyword/triggered/activated/static → delegate effect clauses to `engine.grammar`,
then to the card hooks).
`engine/oracle_types.py` holds shared dataclasses and imports nothing from the
engine, so it's safe to import anywhere.

### Precedence: there isn't any any more

A section here described `@parse_rule`'s nine order bands and the rule that a
specific pattern needed a lower number than a generic one. It went with
`engine/parsing/`. Precedence was a property of a registry of substring
predicates — the ordering was how a rule was told which other rules it was
allowed to be wrong about — and a grammar has no such knob: `"destroy all
creatures"` and `"destroy target creature"` are one production whose difference
falls out of the noun phrase's quantifier.

Two orderings remain, both structural and both asserted: **the grammar before
the card hooks** (so a line that grows a production leaves its hook dead rather
than wrong — `tests/engine/test_card_lines.py`), and **productions before the
derivation tables** inside the grammar (so `engine/lord_buffs.py` cannot claim
every anthem in the pool — `tests/engine/test_grammar_derived_lines.py`).

### Adding support for a new card

Work top-down, stop at the first step that covers it (recipe in
`engine/ARCHITECTURE.md`):
1. Already covered? (`compile_card_oracle(card).supported`) → done.
   `python scripts/support_report.py --set <CODE>` reports coverage for
   a whole set; unsupported creatures now name the specific unrecognized line.
2. New text, existing effect → add a *production* to `engine/grammar/`
   returning an existing kind. Most patterns are a branch in an existing
   production plus a lowering; the noun phrases, amounts and durations are
   already parsed.
3. New effect → invent an instruction kind (verb_object naming), give it an
   entry in `INSTRUCTION_CATEGORIES` *and* `GRAMMAR_CATEGORIES`, then add a
   `@effect_handler`. Token creation → emit `create_token`. P/T changes → go
   through `engine/pt.py`. "Would happen, instead" effects → register in
   `engine/replacements.py`.
4. Bespoke behavior → register a hook in `card_hooks.py` keyed by name (or a
   `cast_restrictions.py` entry for a textual timing gate).
5. Add a focused test in `tests/sets/`, in the file for that set and that card's
   printed type — `tests/sets/test_lea_creatures.py`,
   `tests/sets/test_arabian_nights_cards.py`, and so on
   (`tests/sets/README.md`). Fixtures keep the per-set pools separate so name
   lookups stay unambiguous: `set_pool("<CODE>")` for any set,
   `all_cards`/`cards` (LEA) and `arn_cards`/`arn_by_name` as grandfathered
   aliases; `catalog`/`catalog_by_name` are the whole manifest pool, for
   pool-wide work only. The comprehensive-cast sweep
   (`tests/engine/test_catalog_sweep.py`) parametrizes over the whole manifest,
   so a newly ingested set is swept automatically.

Cards whose text falls outside recognized patterns degrade gracefully: classified
unsupported with an explicit reason, never crashing simulation.

### Determinism

`run_ai_simulation` seeds the module-level RNG, so a given seed reproduces a run
exactly — required for the AI-behavior regression tests. Preserve this when
touching anything that consumes randomness.

## Tests, instruments and the AI simulator, in full

All Python runs through the workspace venv (Windows / PowerShell):
`.\.venv\Scripts\python.exe` (referred to below as `python`).

*(The command block is kept in CLAUDE.md, under "Commands".)*

Tests are organized by subject — put new tests in the matching subfolder:
`tests/ai/` (AI policy/simulator), `tests/ui/` (web API + frontend/end-to-end),
`tests/engine/` (loader, oracle compiler, parsing, dispatch internals),
`tests/rules/` (Comprehensive Rules sections: phases, combat, mana, layers,
keywords, replacements, and the casual variants — ante, Commander, Brawl),
`tests/sets/` (per-card tests for a specific set),
`tests/regressions/` (in-game bug regressions). Shared fixtures live in
`tests/conftest.py` and helpers in `tests/helpers.py`, both at the root.

**A loaded card is shared, so never write to one.** `load_cards` returns the
same `CardDefinition` objects to every caller that names the same files (the
list is the caller's own). Collecting the suite used to build 111 copies of
the catalog and leave every xdist worker at 3.1 GB before its first test,
which is what decided how many workers this machine could run. A test that
needs a card with different numbers builds one (`tests.helpers._mk_card`).

**Per-set tests follow `tests/sets/README.md`**, enforced by
`tests/engine/test_set_test_convention.py`. In short: get a set's cards from
`set_pool("ARN")` / `set_cards("ARN")` — never a new `conftest.py` fixture and
never a spelled-out `cards/*.json` path; split a per-set file by the printed
type of the card each test names once it outgrows one file
(`test_lea_creatures.py`, `test_lea_instants.py`, …); and put anything
pool-wide in `tests/engine/`, not in a set's file.

Every test in `tests/rules/` **must** carry a `@pytest.mark.cr("508.1a", ...)`
marker citing the Comprehensive Rules rule(s) it verifies (numbered rule or
subrule — never a bare section number; verify the number exists in
`MagicCompRules.txt`). `scripts/rules_progress.py` collects these markers and
regenerates `RULES_PROGRESS.md`, the per-rule coverage tracker; a guard test
(`tests/engine/test_rules_progress.py`) fails on unannotated tests or
citations of nonexistent rules. The tracked scope (which CR sections/rules
count) is the `SCOPE` dict in that script — widen it as the engine grows.
`EXCLUDED` beside it drops the handful of rules whose *mechanic* this engine
does not have (Karn's restart, shared team turns, Commander Draft); they are
reported in an appendix rather than dropped silently. That is **not** for a
rule the engine implements that no card exercises — CR 724.2's end-the-phase
half and CR 705.3's "an effect may state a flip's result" stay in the
denominator and show as untested, which is the honest reading.

`scripts/rules_gaps.py` is the read side: it ranks the untested rules by
whether `engine/`+`web/` cite them (a cited-but-untested rule is live
behaviour nothing verifies), by section momentum and by subrule breadth. It
also checks those source citations against the CR both ways — a rule number
that does not exist, **and** a subrule letter that does not exist under a rule
that does. The second is the one that hides: `CR 603.8b` folds to `603.8`,
which is real, so nine stale citations sat in `engine/` until the letter was
checked. Advisory only; nothing fails on its output.

**Neither question is whether the rule is *about* what the comment claims**, and
that is the one that rotted: `CR 701.15c` is a real subrule of a real rule and it
is **Goad**, not the no-regeneration rider. VIS wave 4 read every CR citation in
`engine/` and `web/` against `MagicCompRules.txt` and rewrote **185** of them —
almost none a typo. The April 2026 edition had inserted
`701.4 Behold` and `701.11 Triple` and shifted the whole keyword-action block, so
a citation written against the older numbering now names a different action:
`701.7` (Create) for destroying, `701.13a` (Exile) for milling, `701.5a` (Cast)
for countering. **A CR bump is a silent, repo-wide correctness event.**
`tests/engine/test_cr_citation_subjects.py` makes it loud for the 701 block,
where each rule is headed by one keyword word: it reads the heading map out of
`MagicCompRules.txt` at test time, so a later edition fails every citation whose
keyword moved. Outside 701 the headings are prose and no test can read them —
`scripts/cr_edition_diff.py` does, by **text**: it compares two editions rule by
rule and lists every citation here of a rule that moved, changed or went.

**The shipped CR is the September 25, 2026 edition**, bumped at Odyssey's close
with that script, and the bump is the run to copy. It left the 701 and 702
headings where they were (three appended to each) and renumbered by insertion
elsewhere: five cited rules moved - 506.6 to 506.7 ("had to attack"), 506.7
to 506.8 (the combat cast windows), 601.5 to 601.6, 601.7 to 601.8, and 704.5y
to 704.5z (the Role rule) - 53 citations in ten files, each of which would
have gone on naming a real rule about something else. Install a download with
`--install`: Wizards' text marks blank lines with a NO-BREAK SPACE in some
editions, and left alone the diff is four thousand whitespace lines around the
hundred that changed. What the edition brought the engine is CR 605.1a's
fourth criterion (below, under `engine/mana_payment.py`).

*(The command block is kept in CLAUDE.md, under "Commands".)*

**The AI simulator plays the set you name.** `run_ai_simulation` deals each
seat its own random *limited* deck out of the pool it is given — CR 100.2b's
"this product and basic land cards", 40 cards at 17 lands — seeded from the
run's seed so a seed still reproduces a run exactly. It replaced a hand-written
36-card Alpha decklist, which meant `--set` worked for the three base sets and
refused the other seven for want of an `Island`; the refusal was right and the
scope was the bug. Basics come from the set when it prints them and from the
manifest when it does not, which is what makes Antiquities, Legends and The
Dark playable at all — their own lands cannot cast their own spells.
`required=` pins a card into every deck, for a regression test whose subject
has to be in play; without it such a test passes on any seed that dealt none.
**It plays a whole turn, and that took three goes to be true.** The loop
open-coded the turn structure and left pieces out, each time invisibly: the
untap/upkeep/draw steps (which froze every per-seat-turn record), then the
precombat main phase (so no `main_phase_*` trigger had ever fired), then combat
— no simulated game had declared an attacker, a block or a damage step in this
project's history. All three failed the same way, which is worth knowing before
adding a fourth: the run completes, the interaction count is non-zero and the
issue list is empty, so nothing is wrong and half a turn is missing. Combat is
driven by `engine/ai_combat.py` as a loop over the engine's own
`advance_combat_phase`, which returns without moving at exactly the points where
a player owes a turn-based action — so the driver supplies declarations rather
than re-walking the steps.

**Three became seven, and the last four are why "re-walking" is the word to
distrust.** The ending phase (Prophecy), then mana — nothing had ever cost
anything in a simulated game (Prophecy) — then a step's prompt being answered
in a *later* step, so an upkeep trigger's "you may" was taken after the card
was drawn and ten prompt kinds were never answered at all, and then the turn
order itself: the loop read `for active in (0, 1)`, so Time Walk and eight
other cards that add or skip a turn had never done anything (both Invasion).
Each was fixed the way combat was — by calling the engine's own stepping
(`Game.start_turn`, `start_next_turn`, the `prompt_driver` seam that answers
what a step owes before the next begins) instead of a copy of it — and each
left an honesty count behind: `lands_played`, `steps_left_owing`,
`extra_turns_taken`. What is still not there is named in ROADMAP: the AI
casts only in its own main phases, so no counterspell and no combat trick is
ever cast in a simulated game.

**It chooses a mode now.** Every modal spell an AI seat cast was announced as
its first bullet, in the simulator and in a web game alike, long after the
engine, the picker and both legality gates had become per-mode — a Charm in
an AI hand was a third of a card. `CastAction` carries the mode, every cast
site goes through one function (`ai_policy.cast_announcement`; there were
five sites and a second chooser for instants, and an AST test fails a site
that spells a cast keyword itself), and the chooser loops over
`Game.announceable_modes`. `SimulationReport.modal_casts` is the honesty
count. *Which* bullet wins when several are castable is still the scorer's
text probes, and ROADMAP pins the 25 modes that lose their own board.

**Planeshift found an eighth, of a different kind: mana that was never
tapped.** The tap planner planned *lands*, so in a simulated Alpha game the
Moxen, Sol Ring, Birds of Paradise, Mana Vault and Black Lotus were cast and
none ever produced mana — 122 non-land permanents in the pool have a mana
ability. A non-land source whose whole cost is {T} and whose output is readable
off its payload is planned now, after every land (`ai_valuation.planned_mana_yield`);
a costed or sacrifice source is still not, and ROADMAP says why.

**And a ninth, of the first seven's kind.** `Game.activate_from_hand` is the
*queue* form — the web's, which leaves the ability on the stack for the table
to respond to — and the simulator's hand pass called it and moved on, where
the battlefield pass beside it calls `activate_permanent_ability`, which
settles what it queues. A cycling ability sat on the stack as the step ended,
so all three Urza's sets exited 1 on `steps_left_owing` from the day that
count existed, and no other set prints the keyword on enough cards for ten
games to show it. The pass settles it with the engine's own loop.

**And a tenth: a zone the loop never read.** Every cast an AI seat proposed
came out of its hand, so no card was ever flashed back, cast from exile under
a permission, or played off the top of a library in a simulated game.
`ai_valuation.permitted_casts` is the one reader of what
`cast_permissions` opens, `CastAction.from_zone` carries it through the same
announcement function every cast uses, and
`SimulationReport.casts_from_zones` is the honesty count.

The honesty checks in the report exist because "no illegal interactions" over a
game where nothing happened is a true statement about nothing.
`interaction_count` (a run that cast nothing proves nothing, and the script
exits 1); `refused_casts` (casts the engine declined — no rule broken and
nothing spent, but the AI re-proposes the same card every turn, so a non-zero
count is a seat doing nothing all game); `refused_attacks`, its attack-side twin
for a declaration refused the same way; and the combat counts, which are what
stop a future regression to no-combat from reading green. A seat whose *fallback*
declaration is also refused attacks with nobody for the rest of the game and is
reported as an issue rather than a count.

**Naming a set:** every script that runs over a set takes `--set <CODE>` /
`--all` / `--cards <path>`, resolved through `cards/manifest.json` by
`scripts/set_argument.py` — never a spelled-out filename, which is a second
copy of the registry. An unknown code exits naming the codes that ship, because
a `--set` resolving to an empty pool would let `support_report.py` report
perfect coverage over zero cards and `simulate_ai_games.py` report a clean run
it never had. Guarded by `tests/engine/test_script_set_argument.py`.
The four whole-pool instruments (grammar_coverage, hook_reliance,
parse_coverage, behaviour_classes) scope with `--set` only, as a stdout report
— their `--check`/`--accept` and the committed .md always cover the whole
pool (a per-set baseline would fork the ratchets), and they refuse `--all` /
`--cards` at runtime because their default already reads both manifest roles.

**`engine/card_loader.py` is the only module that opens that file.** A private
reader is the same second copy as a spelled-out filename and goes stale the same
way, but it does not grep like one: `ingest_set.py` kept its own, walked only
the `sets` key, and so stopped covering M21 the day M21 was ingested under
`measured` — no edit, no failing test, and a run that reports success over a
smaller pool than it appears to describe. Import the helpers (`manifest_sets`,
`manifest_measured_sets`, `manifest_set_paths`, `MANIFEST_PATH`); prose naming
`cards/manifest.json` in a docstring is a mention, not a copy. Guarded by
`test_the_manifest_is_parsed_in_one_place` in the same file. Note the one place
the wider default is right: `ingest_set.py --all` covers **both** manifest roles,
because it is about a card file's format rather than about whether a player may
deck it, and everywhere else `include_measured` must keep defaulting to False.

**Parse coverage:** `scripts/parse_coverage.py` verifies that every sentence of
every supported card's oracle text is claimed by a known consumer (the parser,
compiler tables, the text-keyed channels in its `CHANNELS`/`HANDLER_CLAIMS`
registries, card hooks) — the guard test
(`tests/engine/test_parse_coverage.py`) fails when a supported card carries
text nothing parses. **It reads shipped *and* measured sets and gates on the
shipped half**: a supported card in a measured set is exactly what this catches
(the compiler calls it done and no other instrument can see the line it
dropped — `--hollow-lines` finds only lines that produced an *ability part*),
but failing on one would make every ingest red on arrival. Its findings get
their own section in the report. Deliberate shortcuts live in its `ACKNOWLEDGED` dict
(with reasons); a deletion probe additionally flags words a matching rule
ignored (the dropped-rider bug class), ratcheted through
`scripts/parse_coverage_probe_baseline.json` — review new findings, then
`--accept-probe` to re-snapshot. When adding a parse rule or a new text-keyed
engine behavior, run `--check`; if you add a handler that implements trailing
sentences of a clause, declare them in `HANDLER_CLAIMS`.

To **launch and drive the running web app** (screenshots, scripted UI flow), use
the `/run-magic` skill at `.claude/skills/run-magic/` — it drives the browser
with `playwright-cli` (see the `playwright-cli` skill for the general command
reference). The board is canvas-rendered, so DOM selectors won't find cards; that
skill documents the working harness.

## Web layer, in full

`web/app.py` is the FastAPI app (`/api/...` routes + static UI in `web/static/`)
and **nothing else** — it is the one place a route is declared. Everything it
used to hold is a module beside it, **layered**: `web/__init__.py` declares the
order in `LAYERS` and a module may import only from one *earlier* in it, guarded
by `tests/ui/test_web_layering.py` (which catches a function-level import, the
form that produces no `ImportError` and so rots silently).

| Module | Job |
| --- | --- |
| `runtime.py` | the card pool, the three store instances, session lookup |
| `events.py` | server-sent events — the one thing the API *pushes* |
| `seats.py` | seat kind, who has lost, whether to hold priority |
| `serialization.py` | engine object → client JSON, one function per kind |
| `catalog.py` | the pool and decks as the client browses them |
| `verification_report.py` | the verification tracker's read side |
| `pregame.py` | coin flip and mulligans |
| `turn_steps.py` | the beginning phase and the turn's boundaries |
| `combat_prompts.py` | banding / multiblock / pile-division assignments |
| `game_flow.py` | priority, phase advancement, AI stepping |
| `state_view.py` | the whole-state payload a client polls |
| `debug_actions.py` | Debug-Menu board manipulation, raw-state injection |
| `actions.py` | the one dispatch over `ActionKind` |

The card pool is `CARD_PATHS`, read from `cards/manifest.json` via
`engine.card_loader.manifest_set_paths()` and loaded once into `CARD_CATALOG`
at process startup (`runtime.py`). **Adding a set means ingesting it and appending one
manifest entry** — the web app, the test fixtures, and the coverage scripts all
read that one registry. A newly ingested set goes under `measured` first (see
above); appending it to `sets` is the claim that every card in it is supported,
and two guards check that claim. Reprints dedupe to a single card by `oracle_id` (first
printing wins) with every printing recorded in `CardDefinition.printings`.
State lives in in-memory stores: `session_store.py`
(games; takes the loaded catalog, not a path — never re-reads the JSON per
session), `deck_store.py` (decks, incl. Moxfield import), `verification_store.py`.
Game actions funnel through one endpoint, `POST /api/sessions/{id}/action`,
dispatched by the `ActionKind` literal in `web/schemas.py` — one chain in
`web/actions.py`, because the preamble and tail around it apply to every action.
Session `mode` must
be one of the literals `human_vs_ai`, `ai_vs_ai`, `human_vs_human`,
`free_for_all` (the last is 3–4 seats, configured per seat via the `seats`
list instead of the host/guest field pairs).

`web/prompts.py` owns every interactive prompt's presentation: one renderer per
kind plus the three loops that render the prompts a viewer may see, refuse the
actions a pending prompt blocks, and answer AI-owned prompts with their
defaults. All three read the registry (see `engine/pending_choices.py`), so a
new prompt is covered by construction rather than by remembering three edits in
the routes. **The client does not keep its own copy of that registry either**:
the state payload carries `waiting_on_prompt` — whether a `pass_priority` from
this viewer would be refused — and the auto-pass reads it. The client's own
list of blocking kinds had covered 49 of the registry's 86, so an auto-pass
fired into 37 kinds of open prompt and was refused, silently, until a human's
answer armed an AI-owned prompt and the stray pass ended a phase (Tahngarth's
Glare). AI-owned prompts are answered both before and **after** an action's
handler, so a prompt a human's answer arms is answered in the same request.
And **an AI step never advances a human's turn**: `_advance_ai_turn` returns
unless the active seat is an AI — a human's precombat main phase was being
walked into combat whenever the AI had acted in its second main phase.

**What a card can do right now is sent, not re-derived by the client**
(Odyssey). A card in a zone a permission opens carries `ways` — each way it
may be cast, its price, and whether that is payable now — so a flashback cost
is on screen before the click, and the client asks "cast how?" when two
permissions cover one card. A permanent carries `ability_denials`, the
activation gate's own refusal per ability (a threshold land at six cards),
and `ability_mana`, each mana ability's symbols and whether a colour is
chosen: the client asked a filter land which colour it adds until it read
that instead of the land's colour summary. A payment prompt carries
`payable`, and **a person's "pay" that cannot be collected is refused with the
prompt kept, never read as a decline** — a land's tap and a mana ability are
admitted while a payment is owed (CR 605.3a) and nothing else is. A search
carries `min_picks` for every search, so "fail to find" is withheld from one
that must find (CR 701.23d). And **every automatic sender in the client
re-asks by fetching the state when its in-flight flag clears**: a POST's
response can be mid-transition at a turn boundary, and a render skipped for a
flag was never retried, which is how End Turn stalled its own turn in declare
blockers.

The board UI is **canvas-rendered** (`web/static/battlefield-canvas.js`).
