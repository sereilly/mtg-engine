# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**MTG Simulacrum** — a text-based **Magic: The Gathering rules engine** plus a
FastAPI web app with a browser game UI. The card pool lives in `cards/` as one
JSON per set, registered in `cards/manifest.json` (the single source of truth
for which sets ship): Limited Edition Alpha (290 cards), Limited Edition Beta
(292), Unlimited Edition (292 — same list as Beta), Arabian Nights (78) and Revised Edition (296),
388 unique cards, all classified as supported. `scripts/support_report.py` reports on the whole manifest pool, not one set. Card files hold only the fields
the engine and web layer read; `scripts/ingest_set.py` produces them. The
engine is **registry-based**: card support grows by adding small isolated
entries, never by editing core control flow.

**The manifest has two roles.** `sets` is the shipped pool above, held at 100%
supported — the web app offers those cards to players, and two guards
(`tests/engine/test_front_end_safety.py`, `tests/engine/test_card_format.py`)
fail if one of them is unsupported. `measured` is a set ingested so its numbers
can be read *before* the work of supporting it is done: the coverage instruments
load it (`manifest_set_paths(include_measured=True)`), `load_catalog` does not,
and no player can put one of its cards in a deck. Core Set 2021 (M21,
285 cards, 58% supported) sits there.

**A measured set is nameable by the reporting scripts** — `--set M21` works, and
the label says "measured, not shipped" so its numbers can't be read as
shipped-pool ones. That is the point of ingesting it: `support_report.py` naming
the unsupported cards and their reasons is the tool you implement a set *with*,
and it used to exit "no set 'M21' in the manifest", leaving `--cards
cards/M21_cards.json` — the spelled-out filename the convention forbids — as the
only way through. Reading a card file is not shipping it; `load_catalog` is the
seam that decides what a player can deck. `--all` still means the shipped pool
alone, in the paths *and* in the label. A measured set is reported by
`GRAMMAR_COVERAGE.md` / `HOOK_RELIANCE.md` and deliberately left out of their
floors and ceilings — a ratchet over a set nobody has implemented fires on its
composition rather than on anything anyone did. It moves up to `sets` when it is
fully supported. Guarded by `tests/engine/test_manifest_roles.py`. The
end-to-end process — ingest → measure → rounds → promotion → retrospective —
is `SET_PLAYBOOK.md`.

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
python scripts/serve_lan.py --port 8010   # same app, dual-stack IPv4+IPv6 for LAN play

# Engine scripts
python scripts/run_duel.py            # scripted deterministic duel, no server (default LEA)
python scripts/simulate_ai_games.py   # AI-vs-AI batch; deterministic per seed (default LEA)
python scripts/support_report.py      # per-category card-support coverage (whole pool)
python scripts/retrieve_oracle.py "Black Lotus"   # oracle text by name (whole pool)
python scripts/set_progress.py        # regenerate SET_PROGRESS.md (per-set implementation tracker); --refresh re-fetches Scryfall data
python scripts/rules_progress.py      # regenerate RULES_PROGRESS.md (CR test-coverage tracker); --check fails on unannotated tests
python scripts/behaviour_classes.py   # regenerate BEHAVIOUR_CLASSES.md (behavioural-equivalence tracker); --check fails on drift, --accept re-snapshots
python scripts/parse_coverage.py      # regenerate PARSE_COVERAGE.md (oracle-text parse-coverage tracker); --check fails on unclaimed text
python scripts/grammar_coverage.py    # regenerate GRAMMAR_COVERAGE.md (how much of the pool the parser reads); --check fails on regression, --accept re-snapshots floors
python scripts/hook_reliance.py       # regenerate HOOK_RELIANCE.md (how much of the pool is supported by its *name*); --check fails on a rise, --accept re-snapshots ceilings
python scripts/fetch_vocabulary.py    # re-fetch data/vocabulary/*.json from Scryfall (run when a new set adds creature/land types)
python scripts/ingest_set.py 3ED --fetch   # add a new set: download from Scryfall into the engine's card format
python scripts/ingest_set.py --all --check # report card-file sizes without writing
```

**Naming a set:** every script that runs over a set takes `--set <CODE>` /
`--all` / `--cards <path>`, resolved through `cards/manifest.json` by
`scripts/set_argument.py` — never a spelled-out filename, which is a second
copy of the registry. An unknown code exits naming the codes that ship, because
a `--set` resolving to an empty pool would let `support_report.py` report
perfect coverage over zero cards and `simulate_ai_games.py` report a clean run
it never had. Guarded by `tests/engine/test_script_set_argument.py`.

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

```
ast/_core.py   the vocabulary nodes are built from
ast/           damage characteristics board cards stack combat game
ast/statements.py  the roof: Effect / Statement / AbilityNode unions
phrases.py     word tables + fragment productions   |  lowering/_common.py
effects/       damage characteristics board cards   |  lowering/  (same seven)
               stack combat game                    |  lowering/categories.py
statements.py  one whole sentence                   |
parser.py      one printed line (parse_line)        |  lower.py (dispatch)
```

Prowess gets a node in `ast/characteristics.py`, parses in
`effects/characteristics.py` and lowers in `lowering/characteristics.py`.
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
  permanent, `base_controller_index` for one that has left, and otherwise
  `Game.resolving_seats[-1]` — CR 109.5's answer, pushed around
  `_execute_oracle_instruction`. "A source you control" (Fiery Emancipation,
  Chandra's Pyreling) reads it.
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
  `legality.py`'s one surviving text fallback.
- `engine/cost_modifiers.py` — text-keyed cost taxes (CR 601.2f): "<colour>
  spells cost {N} more to cast", "activated abilities of <colour> <type>s cost
  {N} more to activate". Increases only; reduction should arrive with the card
  that needs it, since it clamps at zero and there is nothing to verify against.
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
  the index. **Combat is still index-keyed, but its maps follow their creatures**:
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
  (spell-resolved and counterspell riders, leave-battlefield effects,
  draw-step modifiers, the Aura on a land tapped for mana) plus
  `CARD_LINE_INSTRUCTIONS`, the instruction one printed *line* of one card
  compiles to. The compiler reads it after the grammar refuses and before the
  legacy rules, so a line that later grows a production makes its entry dead
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
- `engine/land_animation.py`, `engine/land_play_allowance.py` — the newest two
  derivation tables: "All <type>s are P/T creatures that are still lands"
  (CR 613 layers 4/5/7) and "You may play <N> additional lands on each of
  your turns" (CR 305.2). Same model as `combat_restrictions.py`: the parameters
  are payload, and the support gate reads the same table the dispatch does.
- `engine/phases/upkeep_effects.py` — `@upkeep_effect(condition, kind)` handlers
  for the interactive pay-or-consequence upkeep triggers, keyed by the
  `(trigger condition, instruction kind)` pair the compiler produces. Everything
  a handler reads arrives on `UpkeepContext`. A duplicate pair raises at import.
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

## Web layer

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
the routes.

The board UI is **canvas-rendered** (`web/static/battlefield-canvas.js`).

## Card verification tracker

`CARD_VERIFICATION.md` / `card_verification.json` track which cards have been
manually validated in-game (369 of the 388 catalog cards, passing; the 19
Revised added have no recorded result yet). **Generated
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
