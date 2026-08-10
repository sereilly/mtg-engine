# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**MTG Simulacrum** — a text-based **Magic: The Gathering rules engine** plus a
FastAPI web app with a browser game UI. The card pool lives in `cards/` as one
JSON per set, registered in `cards/manifest.json` (the single source of truth
for which sets ship): Limited Edition Alpha (290 cards), Limited Edition Beta
(292), Unlimited Edition (292 — same list as Beta), Arabian Nights (78) and Revised Edition (306),
388 unique cards, all classified as supported. `scripts/support_report.py` reports on the whole manifest pool, not one set. Card files hold only the fields
the engine and web layer read; `scripts/ingest_set.py` produces them. The
engine is **registry-based**: card support grows by adding small isolated
entries, never by editing core control flow.

`ROADMAP.md` tracks the work to scale from this pool to the full ~26,000-card
release line — read it before parser or card-data work.

## Commands

All Python runs through the workspace venv (Windows / PowerShell):
`.\.venv\Scripts\python.exe` (referred to below as `python`).

```powershell
# Tests (pytest.ini sets testpaths=tests, addopts=-q)
python -m pytest                                  # full suite
python -m pytest -m "not slow"                    # skip the AI-simulation batch tests
python -m pytest tests/ui/test_web_api.py -q      # one file
python -m pytest tests/sets/test_lea_creatures.py::test_name -q   # one test
python -m pytest tests/regressions -q             # in-game bug regressions (batched by fix round)
```

Tests are organized by subject — put new tests in the matching subfolder:
`tests/ai/` (AI policy/simulator), `tests/ui/` (web API + frontend/end-to-end),
`tests/engine/` (loader, oracle compiler, parsing, dispatch internals),
`tests/rules/` (Comprehensive Rules sections: phases, combat, mana, layers,
keywords, replacements), `tests/sets/` (per-card tests for a specific set),
`tests/regressions/` (in-game bug regressions). Shared fixtures live in
`tests/conftest.py` and helpers in `tests/helpers.py`, both at the root.

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

```powershell

# Web server (browser game UI)
python -m uvicorn web.app:app --host 127.0.0.1 --port 8010   # then open http://127.0.0.1:8010/

# Engine scripts
python scripts/run_duel.py            # scripted deterministic duel, no server
python scripts/simulate_ai_games.py   # AI-vs-AI batch; deterministic per seed
python scripts/support_report.py      # per-category card-support coverage
python scripts/set_progress.py        # regenerate SET_PROGRESS.md (per-set implementation tracker); --refresh re-fetches Scryfall data
python scripts/rules_progress.py      # regenerate RULES_PROGRESS.md (CR test-coverage tracker); --check fails on unannotated tests
python scripts/behaviour_classes.py   # regenerate BEHAVIOUR_CLASSES.md (behavioural-equivalence tracker); --check fails on drift, --accept re-snapshots
python scripts/parse_coverage.py      # regenerate PARSE_COVERAGE.md (oracle-text parse-coverage tracker); --check fails on unclaimed text
python scripts/grammar_coverage.py    # regenerate GRAMMAR_COVERAGE.md (parser-migration ratchet); --check fails on regression, --accept re-snapshots floors
python scripts/fetch_vocabulary.py    # re-fetch data/vocabulary/*.json from Scryfall (run when a new set adds creature/land types)
python scripts/ingest_set.py 3ED --fetch   # add a new set: download from Scryfall into the engine's card format
python scripts/ingest_set.py --all --check # report card-file sizes without writing
```

**Parse coverage:** `scripts/parse_coverage.py` verifies that every sentence of
every supported card's oracle text is claimed by a known consumer (parse rules,
compiler tables, the text-keyed channels in its `CHANNELS`/`HANDLER_CLAIMS`
registries, card hooks) — the guard test
(`tests/engine/test_parse_coverage.py`) fails when a supported card carries
text nothing parses. Deliberate shortcuts live in its `ACKNOWLEDGED` dict
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

## Engine architecture

Full details in `engine/ARCHITECTURE.md`. The compile-and-dispatch pipeline:

```
cards/*.json (set files) → card_loader.load_cards → CardDefinition (immutable)
  → oracle.compile_card_oracle (cached once per card per process) → OracleProgram
      { instructions, activated_abilities, triggered_abilities, static_lines }
  → Game mixins → EFFECT_HANDLERS[instruction.kind](game, instruction, context)  # O(1) dict dispatch
```

**The parser is mid-migration.** `engine/grammar/` (tokenizer → recursive-descent
grammar → typed AST → lowering) is progressively replacing the flat
`engine/parsing/` rule registry. Both lower to the same `OracleInstruction`, and
the compiler tries the grammar first per line, falling back to the legacy rules
when the grammar refuses or its category isn't switched on yet. Read
`ROADMAP.md` before doing parser work; coverage lives in `GRAMMAR_COVERAGE.md`.

Extension points, each a small registered function — **adding a card means
adding entries, not editing dispatch**:

- `engine/grammar/` — the grammar front end. Adding a card pattern here means
  adding a *production*, not a rule with a hand-picked precedence number.
  Hard invariant: a production must consume **every token** of its line or
  raise `GrammarError` — loud failure (card unsupported, clause named) is
  always preferable to a silent partial match. Categories are switched on in
  `GRAMMAR_CATEGORIES` only once
  `tests/engine/test_grammar_differential.py` is green for them. Vocabulary
  (creature types, keywords) is data in `data/vocabulary/`, refreshed by
  `scripts/fetch_vocabulary.py` — never hardcode a type list.
- `engine/parsing/` — legacy `@parse_rule(order)` functions mapping a normalized
  oracle-text clause to `(OracleInstruction, effect_kind)`. Organized by category
  (damage, zones, destruction, combat, …). Still the fallback for everything the
  grammar hasn't taken over; being deleted category by category (roadmap phase 3
  onward). Prefer extending the grammar over adding rules here.
- `engine/handlers/control_flow.py` — `sequence`, `if_then`, `may`, `for_each`.
  Effects compose through these instead of getting a fused instruction kind:
  write "deal damage, then gain life" as two instructions in a `sequence`, never
  as a new `deal_damage_and_gain_life`. Values pass between steps through
  `OracleExecutionContext.results`.
- `engine/handlers/` — `@effect_handler(kind)` functions mutate game state for one
  instruction kind. Registered into `EFFECT_HANDLERS`, dispatched by dict lookup.
  `engine/handlers/_common.py` holds shared helpers (target resolution, filter
  matching, damage application).
- `engine/pt.py` — the single write API for power/toughness (`set_base_pt`,
  `add_pt_modifier`, `switch_pt`). All P/T mutation goes through here, never
  direct metadata pokes; see "P/T channels" in `engine/ARCHITECTURE.md`.
- `engine/replacements.py` — CR 614 "if X would happen, Y instead" interceptors,
  registered by event kind (`life_gain`, `damage_to_creature`, `would_die`).
  Each registration is a pure `applies` predicate plus the effect, and an
  explicit `order` — see `engine/effect_ordering.py`.
- `engine/replacement_choices.py` — for a replacement that is optional or offers
  a choice: the interceptor offers a `ReplacementChoice` (seat, option labels,
  default) instead of applying the effect, and a `@replacement_choice(kind)`
  resolver finishes it. Interactive seats queue on
  `game.pending_replacement_choices`; every other seat takes the default at
  once, through that same resolver. Two registrations, no new `Game` field.
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
- `engine/prevention.py` — CR 615 damage shields, `@prevention_effect(order,
  applies=…)` functions over one `{recipient, amount, source, combat}` event.
  `recipient` is a player *or* a permanent, so a shield that applies to both is
  written once. A new "prevent …" card is an entry here, never a branch in a
  damage path.
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
  Spell damage asks; combat damage does not yet.
- `engine/damage_events.py` — a damage event start to finish. CR 120.4's two
  halves (the damage is dealt; then what was dealt is processed into its
  result), with 616.1's contention set — shields *and* replacements together —
  inside each. `deal_damage` returns both numbers, because Ali from Cairo caps
  the life lost without capping the damage dealt, and lifelink reads the latter.
  Every damage path calls it; there is no half-event entry point, and order is
  compared across both registries so a collision raises at import.
- `engine/tokens.py` — `make_token_card(...)`, paired with the generic
  `create_token` instruction kind. A token-making card is one parse rule, never
  a bespoke handler.
- `engine/targeting.py` — cast-time target kind derived from the *compiled
  program* (Aura enchant line, instruction `type_filter`), replacing part of
  `legality.py`'s text cascade. Returns None when the program lacks the
  evidence, and `legality.py` falls back; a guard test holds the two to
  agreement and ratchets how many cards still need the fallback.
- `engine/cost_modifiers.py` — text-keyed cost taxes (CR 601.2f): "<colour>
  spells cost {N} more to cast", "activated abilities of <colour> <type>s cost
  {N} more to activate". Increases only; reduction should arrive with the card
  that needs it, since it clamps at zero and there is nothing to verify against.
- `engine/continuous.py` + `engine/layer_bridge.py` — the CR 613 layer system.
  Characteristics are **computed**, not stored: `has_type`, `is_creature`,
  `effective_power`, `has_keyword` and the colour accessors all resolve through
  it. Layers 3–7 are live. Anything asking "what type/colour/P/T is this?" must
  go through these accessors — reading `card.type_line` or a metadata flag
  instead is how the same question ends up with several disagreeing answers,
  which is the bug class `tests/engine/test_layer_reads.py` guards.
- `engine/auras.py` — what an Aura's effect lines say and whether the engine
  implements them. Gates support (an Aura whose effect is unimplemented is
  reported unsupported rather than entering play and doing nothing) and derives
  the Aura's continuous effects while it is attached. Removal is the Aura
  ceasing to be attached; there is no remembered delta. Use
  `attach_aura`/`detach_aura`, never the raw metadata.
- `engine/characteristic_defining.py` — characteristic-defining P/T (CR 604.3),
  one `dynamic_pt_count` instruction carrying what to count and whose
  battlefield to count it on.
- `engine/static_bonuses.py` — conditional static P/T bonuses (CR 613 layer 7c)
  in both printed word orders.
- `engine/enter_effects.py` — entry-state phrases `_initialize_permanent_state`
  carries out. `enter_effect_line` is read by the support gate *and* the
  grammar, so what is implemented and what is claimed cannot drift.
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
- `engine/card_hooks.py` — name-keyed registries for truly bespoke behavior
  (spell-cast triggers, leave-battlefield effects, untap-step restrictions,
  draw-step modifiers, mana-production modifiers, cost-tax modifiers).
  **This is the only sanctioned place to reference a card by name**; do not put
  card names anywhere else in the engine (a few single-card exceptions are
  marked `# TODO(card-hooks)` — migrate them if a second card needs the shape).
- `engine/phases/upkeep_effects.py` — `@upkeep_effect(condition, kind)` handlers
  for the interactive pay-or-consequence upkeep triggers, keyed by the
  `(trigger condition, instruction kind)` pair the compiler produces. Everything
  a handler reads arrives on `UpkeepContext`. A duplicate pair raises at import.
- `engine/phases/` — one mixin per turn phase and per step within a phase
  (CR 500–514): beginning phase (untap/upkeep/draw steps), the two main phases,
  combat phase (its five steps), and the ending phase (end/cleanup steps). Each is
  composed onto `Game`; see `engine/phases/__init__.py` for the taxonomy. Put
  phase/step turn-based logic here.
- `engine/mixins/` — cross-cutting game flow *not* tied to a single phase:
  turn-structure navigation and priority (`phase_steps`), per-turn/pregame
  management (`turn_management`), state-based actions, effects, helpers.
  Consumes compiled programs; must never parse oracle text.
- `engine/mixins/stack/` — the stack (CR 405), one mixin per stage of an
  object's life on it: `casting` (CR 601), `activation` (CR 602), `resolution`
  (CR 603/608), and `choices` — the `pending_choices` queue every
  part-way-through decision goes through, plus the table registering them.

`engine/oracle.py` is the compiler (tokenize → classify lines as
keyword/triggered/activated/static → delegate effect clauses to `engine.parsing`).
`engine/oracle_types.py` holds shared dataclasses and imports nothing from the
engine, so it's safe to import anywhere.

### Parse-rule ordering (critical, non-obvious)

`@parse_rule` order determines precedence: **first match in ascending order
wins, so more specific patterns must use lower orders than generic ones**
(`"destroy all creatures"` before `"destroy target"`). All orders share one
global space; write new rules as `BAND_X + offset` using the named constants in
`engine/parsing/base.py`. A **duplicate order raises at import time**, so
collisions surface immediately. The current order bands (×100 of the historic
LEA numbering, opening ~99 free slots between former neighbors) are documented
in `engine/ARCHITECTURE.md` (1,000–6,500 upkeep … 113,000–117,000 global/static
buffs, lowest precedence).

### Adding support for a new card

Work top-down, stop at the first step that covers it (recipe in
`engine/ARCHITECTURE.md`):
1. Already covered? (`compile_card_oracle(card).supported`) → done.
   `python scripts/support_report.py --cards <set.json>` reports coverage for
   a whole set; unsupported creatures now name the specific unrecognized line.
2. New text, existing effect → add one `@parse_rule` returning an existing kind
   (reuse `engine/parsing/common.py` helpers where they fit).
3. New effect → invent an instruction kind (verb_object naming) + add a
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

## Web layer

`web/app.py` is the FastAPI app (`/api/...` routes + static UI in `web/static/`).
The card pool is `CARD_PATHS`, read from `cards/manifest.json` via
`engine.card_loader.manifest_set_paths()` and loaded once into `CARD_CATALOG`
at process startup. **Adding a set means ingesting it and appending one
manifest entry** — the web app, the test fixtures, and the coverage scripts all
read that one registry. Reprints dedupe to a single card by `oracle_id` (first
printing wins) with every printing recorded in `CardDefinition.printings`.
State lives in in-memory stores: `session_store.py`
(games; takes the loaded catalog, not a path — never re-reads the JSON per
session), `deck_store.py` (decks, incl. Moxfield import), `verification_store.py`.
Game actions funnel through one endpoint, `POST /api/sessions/{id}/action`,
dispatched by the `ActionKind` literal in `web/schemas.py`. Session `mode` must
be one of the literals `human_vs_ai`, `ai_vs_ai`, `human_vs_human`,
`free_for_all` (the last is 3–4 seats, configured per seat via the `seats`
list instead of the host/guest field pairs).

`web/prompts.py` owns every interactive prompt's presentation: one renderer per
kind plus the three loops that render the prompts a viewer may see, refuse the
actions a pending prompt blocks, and answer AI-owned prompts with their
defaults. All three read the registry (see `engine/pending_choices.py`), so a
new prompt is covered by construction rather than by remembering three edits in
`app.py`.

The board UI is **canvas-rendered** (`web/static/battlefield-canvas.js`).

## Card verification tracker

`CARD_VERIFICATION.md` / `card_verification.json` track which cards have been
manually validated in-game (all 369 catalog cards, passing). **Generated
automatically** — results are edited via the in-game Debug Menu, not by hand.

A card is also reported `equivalent` when it is untested but a *passing* card
shares its behaviour class: the engine resolves both through the same code
paths, so a separate manual pass would exercise nothing new. That status is
derived on read, never stored, so it can't be mistaken for a human check and it
withdraws automatically if its peer is later marked failing.
`engine/behaviour_signature.py` computes the classes and
`scripts/behaviour_classes.py` regenerates `BEHAVIOUR_CLASSES.md`; `--check`
fails when classes drift, because a signature that stops distinguishing two
behaviours silently *raises* apparent coverage.
`tests/regressions/test_card_verification_regressions.py` guards against regressions in
verified cards.

## MTG rules questions

For rules/timing/layers/interaction questions, the `mtg-rules` skill
(`.claude/skills/mtg-rules/`) is authoritative; it consults `MagicCompRules.txt`
(the full Comprehensive Rules, in the repo root). Don't answer non-trivial
rulings from memory — cite that file.
