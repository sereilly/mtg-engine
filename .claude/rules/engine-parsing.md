---
paths:
  - "engine/grammar/**"
  - "engine/oracle.py"
  - "engine/oracle_types.py"
  - "engine/front_ends.py"
  - "engine/line_*.py"
  - "engine/ability_lines.py"
  - "engine/keyword_lines.py"
  - "engine/card_hooks.py"
  - "engine/*_labels.py"
  - "engine/vocabulary.py"
  - "engine/whenever_trigger*.py"
  - "engine/trigger_conditions.py"
  - "engine/derived_static_claims.py"
  - "engine/amplify.py"
  - "engine/storm.py"
  - "data/vocabulary/**"
  - "scripts/parse_coverage*.py"
  - "scripts/grammar_coverage.py"
  - "scripts/hook_reliance.py"
  - "tests/engine/test_grammar_*.py"
  - "tests/engine/test_card_lines.py"
  - "tests/engine/test_card_name_reads.py"
  - "tests/engine/test_keyword_registry.py"
  - "tests/engine/test_effect_labels.py"
  - "tests/engine/test_trigger_dispatchers.py"
  - "tests/engine/test_parse_coverage.py"
---

# The compiler and the grammar

Part of `CLAUDE.md`, kept here so it loads when you open a file it
describes (the `paths` above). The root file's rule for editing applies,
and you can open this file directly whenever its subject is yours.

## Where a new template goes

Both halves are layered, bottom to top, and the
effect families are the *same names* on each side — one template has one home
per side, and both `__init__`s re-export flat:

```
ast/_core.py   the vocabulary nodes are built from
ast/           damage characteristics board cards stack combat game
ast/statements.py  the roof: Effect / Statement unions
ast/lines.py       the line layer on the roof: ability-line nodes / AbilityNode
phrases.py     shared fragment productions          |  lowering/_common.py
                                                    |  lowering/_amounts.py
effects/       damage characteristics board cards   |  lowering/  (those eight,
               stack combat game prevention         |  + zones library mana
               counters                             |    returns keywords …)
statements.py  one whole sentence                   |  lowering/categories.py
parser.py      one printed line (parse_line)        |  lower.py (dispatch)
```

The lowering side carries families the parse side does not
(`test_grammar_layering.py` documents each with its reason). When a module
splits, reuse the other side's family name so the mirror re-forms. **Families do
not import each other**: a fragment two families need goes in
`phrases`/`_common`/`_core` (or a floor module beside `_common`, like
`lowering/_amounts.py`), never in one of them. A **derivation table**
(`engine/grammar/derived.py`) is reached only where every production refuses the
line in full, so a production whose sentence a table also reads must refuse in
the **parse**. `tests/engine/test_grammar_layering.py` enforces the layer order,
family independence and flat re-export.

## Parsing and compiling

- `engine/grammar/` — adding a card pattern means adding a *production*; there
  is no precedence number. A production must consume **every token** of its line
  or raise `GrammarError` — a loud failure (card unsupported, clause named) beats
  a silent partial match. An effect that should not execute is a `LoweringError`
  naming what is missing. `GRAMMAR_CATEGORIES` is held equal to every category
  `lowering/categories.py` declares (`tests/engine/test_grammar_categories.py`);
  a category left off costs its cards their support. Vocabulary (creature types,
  keywords) is data in `data/vocabulary/` — never hardcode a type list.
- **Implemented keywords are one frozenset**, `vocabulary.IMPLEMENTED_KEYWORDS`,
  which the keyword-line classifier (`engine/keyword_lines.py`) reads. Adding one means the
  set plus behaviour that covers **everywhere the CR says it applies** (lifelink
  is CR 702.15b damage, not combat damage: one rule in
  `damage_events.lifelink_life_gained`, gained as the damage is dealt — or,
  for a chunk of a simultaneous dealing, once per lifelink source as the
  dealing finishes, CR 702.15e; `Game._apply_or_tally_lifelink`,
  `engine/simultaneous_damage.py`). Held by
  `tests/engine/test_keyword_registry.py`, which checks behaviour, not two lists.
  A keyword admitted by the reader that implements it is not in the set
  when listing it would admit more than that reader does: one that carries an
  argument, because listing it would admit the bare word — morph, madness,
  and amplify (CR 702.38, `NUMERIC_ARGUMENT_KEYWORDS`, `engine/amplify.py`'s
  `entry_reveal` as the creature enters) — and storm, which takes none but
  is built for instants and sorceries only (`engine/storm.py`'s `is_storm`;
  `unread_storm_line` refuses it on a permanent, whose copy would become a
  token, CR 707.10f).
- **Rewrite keywords** are expanded by `line_rewrites.expand_ability_lines` before any
  line is classified, so the word is not in `IMPLEMENTED_KEYWORDS`: equip
  (CR 702.6a), buyback (702.27a), kicker (702.33a), flashback (702.34),
  affinity (702.41a, `engine/affinity.py` — onto the self-reduction sentence,
  whose price reader sums every reduction, 702.41b), entwine (702.42a,
  `engine/entwine.py` — an optional additional cost that, paid, names every
  mode) and modular (702.43a, `engine/modular.py` — "enters with N +1/+1
  counters" and the dies trigger whose count is the departure look-back;
  `has_printed_modular` answers "a creature with modular"). Every
  reader of a card's lines (`legality.py`, `parse_coverage.py`,
  `hook_reliance.py`) must start from that function or it reads a different card.
- **Ability words** (CR 207.2c) are dropped by `oracle_types.strip_ability_word`
  in both front ends. Threshold is one condition ("seven or more cards are in
  your graveyard", `cards_in_zones`) asked where each printing already has a
  seam: a conditional static, an activation restriction row, and a spell's
  "instead" (`line_rewrites.expand_instead_paragraph_lines`).
- `engine/effect_labels.py` — the `effect_kind` *label* an ability reports,
  looked up in two family tables, which is where a row goes:
  `engine/activated_labels.py` (`ACTIVATED_LABELS`) and
  `engine/triggered_labels.py` (`TRIGGERED_LABELS` and its by-condition
  rows). Never dispatch: it feeds `SimulationResult` and `StackItem.ability_effect_kind`,
  and a wrapper is labelled by its shape, never by a leaf's effect — a
  triggered wrapper's by-condition row names the moment its condition names
  (`TRIGGERED_LABELS_BY_CONDITION`). Its prefix is not
  the ability's kind: whether a stack object is activated or triggered is
  `StackItem.ability_kind` (how it got there), read by `is_triggered`,
  `stack_targets` and "counter target activated ability". Held to the pool
  both ways by `tests/engine/test_effect_labels.py`.
- `engine/card_hooks.py` — name-keyed registries for truly bespoke behaviour
  plus `CARD_LINE_INSTRUCTIONS` (one printed line of one card). The compiler
  reads it after the grammar refuses, so a line that later grows a production
  makes its entry dead — `tests/engine/test_card_lines.py` fails on a dead one.
  The bar: **no second card, real or plausibly printable, shares the shape**. It
  is the only sanctioned place to key behaviour on a card name, enforced across
  `engine/` by `tests/engine/test_card_name_reads.py` (a name in a comparison is
  dispatch; in a log line or a fixture it is data) — AI heuristics included:
  which cards a weight reaches is derived from the compiled program in the
  valuation modules (`engine/ai_valuation.py` and its family). Before writing a name, give an invented card the
  same text and see whether it works. **A hook writes the end state directly, so
  it is a place a general rule can be skipped in silence**; the pile is measured
  by `scripts/hook_reliance.py` against ceilings
  (`scripts/hook_reliance_ratchet.json`, `--accept` only after deciding a rise
  was worth it), over supported cards.
- **Trigger conditions**: the pattern tables (`engine/whenever_triggers.py`,
  `engine/trigger_conditions.py`) delimit a printed
  noun phrase as `<name>_subject` (`_subjects` when counted) and a number as
  `<name>_count`, so a different tribe or number needs no code; two rows may
  share a kind when only the question differs. The "whenever" table is rows
  only: why a row sits where it does is its note in
  `engine/whenever_trigger_notes.py`, `(kind, phrase, text)` in the table's
  own order (`tests/engine/test_dst_w2g3_whenever_trigger_notes.py` holds each
  note to one row and the notes to that order), so a new row is a row in the
  table and its note at the same position. **A condition needs a dispatcher,
  and parsing is not one**: `tests/engine/test_trigger_dispatchers.py` asks of
  every condition the pool produces whether anything outside the declaration
  tables names it. Where an event has no single call site (a draw, a life gain,
  a sacrifice), announce it on the state-based sweep (`mixins/game_ending.py`)
  over the record every path feeds.

## The compiler

`engine/oracle.py` is the compiler: the per-card cache and the gates every card
passes. It tokenizes, rewrites lines (`line_rewrites`), classifies them as
keyword/triggered/activated/static (`line_classification`, `ability_lines`,
`keyword_lines`) and delegates effect clauses to `engine.grammar`, then to the
card hooks (`front_ends`). `engine/oracle_types.py` holds shared dataclasses and
imports nothing from the engine at run time (`ActivatedAbilityCost` lives in
`engine/activated_ability_cost.py`, named under `TYPE_CHECKING`).

**Two caches sit above the text compile and one inside it, all cleared by
`clear_compilation_caches()`** (a test that swaps a piece of the compiler out
calls that, never one cache's `cache_clear`). `compile_card_oracle` keeps a
card's program on the card object (`models.COMPILED_PROGRAM_SLOT`, under the
generation `oracle._ProgramsHeldOnCards` moves on at each clearing;
`CardDefinition.__getstate__` leaves it out of every copy), because the engine
asks for a permanent's program on every scan of the board. Beneath it,
`_compile_card_oracle`'s `lru_cache` is what the program store seeds. And
while a card compiles (`grammar.parser.each_line_parsed_once`) each
(line, card name) is parsed once — the compiler asks the same line from
several readers — so the store builds in ~13 s; outside a compile, a parse
(the parse-coverage probe's) is never kept. **An answer derived only from a
compiled program or ability is held on that object** by
`oracle.held_on_compiled` (the land mana walk on the program of a land's
*effective* card, `is_tap_alone_mana_ability` on the ability), under the same
generation, in a slot named with `oracle_types.DERIVED_SLOT_PREFIX` that
`__getstate__` leaves out of every copy, pickle and the program store; under
`fast_paths.CHECKING` each is derived again and compared. Nothing is keyed by
`id()`, and an answer that also reads a table a test patches without
clearing the caches (`is_mana_ability`, `LIBRARY_SAFE_ZONE_KINDS`) is not held.
