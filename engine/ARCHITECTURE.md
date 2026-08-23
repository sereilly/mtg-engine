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
| `engine/characteristic_defining.py` | Characteristic-defining power/toughness (CR 604.3) — "<name>'s power and toughness are each equal to the number of X". The possessive subject is the card's own name, which normalization does not replace, so these were four literals containing four card names. One `dynamic_pt_count` instruction now carries what to count (`land`/`creature`/`same_name`) and whose battlefield to count it on. |
| `engine/static_bonuses.py` | Conditional static P/T bonuses (CR 613 layer 7c) — "gets +N/+N as long as you control a <land>", "as long as it's untapped". Both printed word orders, because only the trailing one was ever dispatched while the leading one sat in the support gate as a literal naming Swamp. Also `singular_land_type`, since Plains is spelled the same singular and plural. |
| `engine/lord_buffs.py` | The lord/anthem template (CR 611.3a, layers 6 and 7c) — "Other Goblins get +1/+1 and have mountainwalk", "Black creatures get +1/+1", "Attacking creatures you control get +1/+0". Derives **who** (colour, creature subtype, "other", controller scope, and a state qualifier: attacking/blocking/tapped/untapped) and **what** (P/T delta, keyword abilities, a granted activated ability). The support gate, both parser front ends and `_recalculate_lord_buffs` all read this one table. A clause carrying a **duration** is deliberately not claimed: that is the spell reading of the same sentence, which locks its set in at resolution (CR 611.2c) and stays on `buff_creatures_global`. |
| `engine/combat_restrictions.py` | Text-keyed combat restrictions (CR 506, 509): "can't attack unless defending player controls a <land type>", "attacks each combat if able", "can't be blocked by Walls", "can't block creatures with power N or greater". The land type and the threshold are payload data, not part of the instruction kind. The support gate consults this table rather than listing the same sentences, so a rider the table does not recognize fails loudly instead of compiling to a bare static line. |
| `engine/enter_effects.py` | Entry-state phrases `_initialize_permanent_state` carries out (enters tapped, enters with counters, enter-as-a-copy, choose-on-enter, no maximum hand size, spend white as red). `enter_effect_line` is the whole-line matcher; the compiler's support gate and `engine/grammar/registries.py` both read it, so the phrases cannot drift between what is implemented and what is claimed. |
| `engine/draw_step_modifiers.py` | Text-keyed symmetric bonus draws (CR 504): "at the beginning of each player's draw step, that player draws an additional card", with the optional untapped-source clause. |
| `engine/land_animation.py` | Text-keyed land animation (CR 613 layers 4/5/7): "All &lt;land type&gt;s are P/T \[colour] creatures that are still lands". The land type, the P/T and the colour are all payload on one `animate_all_lands` instruction, so a third animator needs no code. Replaced two parse rules that baked the land type into the instruction *kind* and a refresh that matched `card.name == "Kormus Bell"` — the two halves failing in opposite directions at once. |
| `engine/land_play_allowance.py` | Text-keyed extra land plays (CR 305.2): "You may play any number of lands on each of your turns", the "\[N] additional land(s)" forms, and the self-damage rider that may accompany them. Every land-drop gate — cast validation, the AI's land policy, the web layer's playable list — and the support gate all ask this one table, so they cannot disagree about what a card grants. |
| `engine/ai_valuation.py` | What a card does in the terms `ai_policy`'s heuristics ask about — how many cards it makes its target draw, whether it bounces a creature, what it destroys, whether it counters a spell, how much mana its ability adds — derived from the compiled program. Replaced eight `card.name == "…"` comparisons that had already decayed: Shatter, Terror, Stone Rain and Desert Twister print Disenchant's template, were not on the list, and the AI aimed all four at its own permanents. A heuristic's *weight* stays tuning in `ai_policy`; **which cards it reaches** is a claim about the pool and lives here. |
| `engine/card_hooks.py` | Name-keyed registries for truly bespoke card behavior: spell-resolved triggers, counterspell riders, leave-battlefield effects, draw-step modifiers, the Aura on a land tapped for mana, and `CARD_LINE_INSTRUCTIONS` — the instruction one printed *line* of one card compiles to, for texts that are a single card's sentence rather than a template. `engine/oracle.py` reads it after the grammar refuses, and it is the last front end there is, so a line that grows a production leaves its entry dead rather than wrong; `tests/engine/test_card_lines.py` fails on a dead entry and on a key matching no printed line, and `tests/engine/test_front_end_safety.py` fails if the production that took a hooked line over produces less than the hook did. The only sanctioned place in the engine to key behavior on a card name — enforced by `tests/engine/test_card_name_reads.py`, which scans `engine/` for a name in a comparison (dispatch) rather than in a log line (data), with one acknowledgement: `ai_simulator._assert_expected`, a test oracle whose expectations must stay independent of the parse they check. |
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
| nodes | `ast/_core.py` (the vocabulary nodes everything is built from), `ast/{damage,characteristics,board,cards,stack,combat,game}.py`, `ast/statements.py` (the `Effect` / `Statement` / `AbilityNode` unions). Frozen dataclasses, **append-only** — repurposing a field invalidates every golden and ratchet entry at once. | — |
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
