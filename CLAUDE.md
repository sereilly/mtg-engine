# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**This is the short form, and it is short on purpose.** It is loaded into every
session and every subagent, so it holds what changes what you *do*: the
commands, the conventions, and each seam's rule with the guard that holds it.
The reasoning behind each rule — the incident, the cards, the measurements — is
the long form:

- `engine/ARCHITECTURE.md` — every seam below, in full ("Extension points, in
  full"), the web layer, and the tests, instruments and AI simulator.
- `SET_PLAYBOOK.md` — the set lifecycle, and the pool's history set by set.
- `ROADMAP.md` — what is measured and not yet fixed, and what the next set is.

**Read a module's long-form entry before changing it.** A rule here is one
sentence of a paragraph there. New history goes there, never here:
`tests/engine/test_claude_md_size.py` holds this file's size.

## What this is

**MTG Simulacrum** — a text-based **Magic: The Gathering rules engine** plus a
FastAPI web app with a browser game UI. The card pool lives in `cards/` as one
JSON per set, registered in `cards/manifest.json` (the single source of truth
for which sets ship): **33 sets — Alpha through Odyssey in release order, plus
Core Set 2021 — 5,246 unique cards (7,741 printings), all classified as
supported.** `SET_PROGRESS.md` lists them. `scripts/support_report.py` reports
on the whole manifest pool, not one set. Card files hold only the fields the
engine and web layer read; `scripts/ingest_set.py` produces them. The engine is
**registry-based**: card support grows by adding small isolated entries, never
by editing core control flow.

**The manifest has two roles.** `sets` is the shipped pool, held at 100%
supported — the web app offers those cards to players, and two guards
(`tests/engine/test_front_end_safety.py`, `tests/engine/test_card_format.py`)
fail if one of them is unsupported. `measured` is a set ingested so its numbers
can be read *before* the work of supporting it is done: the coverage
instruments load it (`manifest_set_paths(include_measured=True)`),
`load_catalog` does not, and no player can put one of its cards in a deck. It
is empty today. **The next ingested set goes there first** and moves up to
`sets` when every card is supported. `--set <CODE>` names a measured set and
labels it "measured, not shipped"; `--all` means the shipped pool alone. The
trackers report a measured set and leave it out of their floors, ceilings and
gate. Guarded by `tests/engine/test_manifest_roles.py`. The end-to-end process
— ingest → measure → rounds → promotion → retrospective — is `SET_PLAYBOOK.md`.

**The manifest is printing-ordered, and the order is load-bearing.**
`CardDefinition.original_printing` is the first entry in `printings`, so a set
is inserted *between* the sets it was printed between, never appended. Two
guards, with different blind spots:

- `test_appending_a_set_never_changes_an_existing_original_printing` compares
  prefixes of the ordering, so inserting is legal and reordering is not. It is
  **silent** for an all-reprint set, for an all-new set, and for the new set's
  own cards.
- `test_manifest_roles.test_the_shipped_sets_are_in_printing_order` compares
  the `released` dates — the invariant itself.

**Rehearse the wrong insert at every promotion**, whatever the overlap looks
like, and **count a reprint against the sets that actually print it, not the
set you expect.** Mirage, Stronghold, Urza's Saga, Invasion, Planeshift and
Seventh Edition each carried cards whose only other printing is M21, so the
set's index decided those cards' origin with every guard but the
printing-order one green.

**Three numbers that mislead, and what corrects each:**

- **Supported is not working.** A card is supported when *any* of its lines
  is. `scripts/parse_coverage.py --set <CODE>` and `support_report.py
  --hollow-lines` see a dropped sentence; the support count cannot. Read them
  beside the percentage on the day of the ingest.
- **`set_progress.json`'s "new cards" counts against the whole release line**,
  and this manifest is a subset of it: two "reprint sets" brought 2 and 17 new
  cards. Measure at Phase 1.
- **A hooked card can hide an unimplemented line.** A hook writes the end
  state directly, so it is a place a general rule can be skipped in silence.
  Fourteen sets have reached 100% adding no name-keyed hook; reliance is
  **0.9% of supported cards** (49 of 5,246, `HOOK_RELIANCE.md`). A hook is the
  last resort.

`ROADMAP.md` tracks the work to scale from this pool to the full ~26,000-card
release line — read it before parser or card-data work.

## Commands

All Python runs through the workspace venv (Windows / PowerShell):
`.\.venv\Scripts\python.exe` (referred to below as `python`).

```powershell
# Tests (pytest.ini sets testpaths=tests, addopts=-q)
python -m pytest                                  # full suite (serial — the CI-comparable number)
python -m pytest -n 8 --dist worksteal            # full suite in parallel: the gate (about 24 minutes here; without worksteal the long censuses queue on two workers)
python -m pytest -m "not slow"                    # skip the AI-simulation batch tests
python -m pytest tests/ui/test_web_api.py -q      # one file
python -m pytest tests/sets/test_lea_creatures.py::test_name -q   # one test
python -m pytest tests/regressions -q             # in-game bug regressions (batched by fix round)
```

Tests are organized by subject — put new tests in the matching subfolder:
`tests/ai/` (AI policy/simulator), `tests/ui/` (web API + frontend/end-to-end),
`tests/engine/` (loader, oracle compiler, parsing, dispatch internals),
`tests/rules/` (Comprehensive Rules sections: phases, combat, mana, layers,
keywords, replacements, and the casual variants — ante, Commander, Brawl),
`tests/sets/` (per-card tests for a specific set),
`tests/regressions/` (in-game bug regressions). Shared fixtures live in
`tests/conftest.py` and helpers in `tests/helpers.py`, both at the root.

- **A loaded card is shared, so never write to one.** `load_cards` returns the
  same `CardDefinition` objects to every caller that names the same files. A
  test that needs a card with different numbers builds one
  (`tests.helpers._mk_card`).
- **Per-set tests follow `tests/sets/README.md`**, enforced by
  `tests/engine/test_set_test_convention.py`: get a set's cards from
  `set_pool("ARN")` / `set_cards("ARN")` — never a new `conftest.py` fixture and
  never a spelled-out `cards/*.json` path; split a per-set file by the printed
  type of the card each test names once it outgrows one file; put anything
  pool-wide in `tests/engine/`, not in a set's file.
- **Every test in `tests/rules/` must carry a `@pytest.mark.cr("508.1a", ...)`
  marker** citing the rule(s) it verifies — a numbered rule or subrule, never a
  bare section number, and one that exists in `MagicCompRules.txt`.
  `scripts/rules_progress.py` regenerates `RULES_PROGRESS.md` from them;
  `tests/engine/test_rules_progress.py` fails on an unannotated test or a
  nonexistent rule. Its `SCOPE` dict is what counts; `EXCLUDED` is only for a
  rule whose *mechanic* the engine does not have, never for an implemented rule
  no card exercises.
- **A test that casts a permanent and asserts its entry effect drains the
  stack first** (`tests.helpers.resolve_stack`) — never a bare
  `while game.stack:` loop, which spins once a seat is owed a prompt.

**A CR bump is a silent, repo-wide correctness event.** The shipped rules file
is the **September 25, 2026** edition. An edition renumbers by insertion, so a
citation goes on naming a real rule about something else.
`tests/engine/test_cr_citation_subjects.py` makes that loud for the 701 block;
`scripts/cr_edition_diff.py` reads the rest by text. Install a download with
`--install`. `scripts/rules_gaps.py` ranks untested rules and flags stale
citations (advisory).

```powershell

# Web server (browser game UI)
python -m uvicorn web.app:app --host 127.0.0.1 --port 8010   # then open http://127.0.0.1:8010/
python scripts/serve_lan.py --port 8010   # same app, dual-stack IPv4+IPv6 for LAN play

# Engine scripts
python scripts/run_duel.py            # scripted deterministic duel, no server (default LEA)
python scripts/simulate_ai_games.py --set DRK   # AI-vs-AI batch over one set; deterministic per seed (default LEA)
python scripts/support_report.py      # per-category card-support coverage (whole pool)
python scripts/support_report.py --set ATQ --hollow-lines   # supported cards carrying an ability with no instruction behind it (a Phase 3 exit criterion)
python scripts/support_report.py --set LEG --refusals   # every refused line of every unsupported card with its exact refusal site (the plain census quotes only the first) — the work list backlog rounds are planned from; the rollup counts lines / distinct sentences / cards per site
python scripts/support_report.py --set HML --fragments   # n-gram census over the refused lines, ranked by how many cards share each fragment — the leverage number below the sentence (--json emits every census as one object)
python scripts/retrieve_oracle.py "Black Lotus"   # oracle text by name (whole pool)
python scripts/picker_sweep.py --set <CODE>   # every supported card whose cast/activation picker disagrees with its printed line (the Roots class) — run it over a measured set in Phase 3, when the test ratchets cannot see it
python scripts/oracle_diff.py snapshot   # record every card's full compiled program (both manifest roles) before a change
python scripts/oracle_diff.py compare    # every card whose program moved since the snapshot, payloads and all; exit 1 if any did
python scripts/set_progress.py        # regenerate SET_PROGRESS.md (per-set implementation tracker); --refresh re-fetches Scryfall data
python scripts/check_all.py           # every CI guard check, in ci.yml's order, one summary table (--freshness adds the tracker regenerations + a clean-tree check)
python scripts/meeting_point.py --base main --set <CODE>   # what a merge gets instead of the suite: changed test files, the set's own, the structural guards, every file a gate has surprised (--list prints it; a missing path or an empty run is an error)
python scripts/set_test_sections.py open <CODE> --groups W1G1 W1G2   # a set's test files with one marked section per group; `report <CODE>` is lines per section against the cap, `move <file> --to later_groups --sections W1G6` moves whole sections and leaves their markers
python scripts/rules_progress.py      # regenerate RULES_PROGRESS.md (CR test-coverage tracker); --check fails on unannotated tests
python scripts/rules_gaps.py          # rank untested CR rules by engine citations + section momentum; also flags stale CR citations in engine/web (advisory, stdout only)
python scripts/cr_edition_diff.py old.txt   # a CR bump: every citation here of a rule that moved, changed or went between two editions (old.txt = `git show HEAD:MagicCompRules.txt`); --install <download> writes the new file in the repo's convention
python scripts/unasked_narrowings.py  # printed narrowings whose handler never supplies the seat `subject_matches` needs — the fail-closed half of the asymmetric-gate class (advisory; --check to fail)
python scripts/behaviour_classes.py   # regenerate BEHAVIOUR_CLASSES.md (behavioural-equivalence tracker); --check fails on drift, --accept re-snapshots; --set <CODE> prints which existing classes that set's cards land in (stdout only)
python scripts/parse_coverage.py      # regenerate PARSE_COVERAGE.md (oracle-text parse-coverage tracker); --check fails on unclaimed text; --set <CODE> prints that set's per-card claims/unclaimed (stdout only)
python scripts/grammar_coverage.py    # regenerate GRAMMAR_COVERAGE.md (how much of the pool the parser reads); --check fails on regression, --accept re-snapshots floors; --set <CODE> prints that set's row (stdout only)
python scripts/hook_reliance.py       # regenerate HOOK_RELIANCE.md (how much of the pool is supported by its *name*); --check fails on a rise, --accept re-snapshots ceilings; --set <CODE> prints that set's row + its hooked cards (stdout only)
python scripts/fetch_vocabulary.py    # re-fetch data/vocabulary/*.json from Scryfall (run when a new set adds creature/land types); --check only confirms the catalogs are present (CI)
python scripts/ingest_set.py 3ED --fetch --register   # add a new set: download from Scryfall into the engine's card format and insert its `measured` manifest entry (release-ordered); promotion to `sets` stays a reviewed hand move
python scripts/ingest_set.py --all --check # report card-file sizes without writing
```

**The AI simulator plays the set you name, and it plays a whole turn through
the engine's own stepping.** `run_ai_simulation` deals each seat a random
limited deck (40 cards, 17 lands) out of the pool it is given, seeded so a seed
reproduces a run exactly; `required=` pins a card into every deck, for a
regression test whose subject has to be in play.

- **Never re-walk the turn structure in the simulator.** Ten times a piece was
  missing — the beginning phase, the main phase, combat, the ending phase,
  mana, a step's prompt, turn order, non-land mana, a hand activation left on
  the stack, casts from any zone but a hand — and every time the run completed
  with a non-zero interaction count and no issue. The first seven were each
  fixed by calling the engine's own stepping instead of a copy of it
  (`Game.start_turn`, `start_next_turn`, `advance_combat_phase`, the
  `prompt_driver` seam).
- **Read the honesty counts, not only the issue list**: `interaction_count`,
  `refused_casts`, `refused_attacks`, `lands_played`, `steps_left_owing`,
  `extra_turns_taken`, `modal_casts`, `casts_from_zones`. A count that reads
  zero is a half of the game that did not happen.
- Every cast site goes through `ai_policy.cast_announcement` (an AST test fails
  a site that spells a cast keyword itself).
- Still missing, and named in ROADMAP: the AI casts only in its own main
  phases, so no counterspell and no combat trick is cast in a simulated game.

**Naming a set:** every script that runs over a set takes `--set <CODE>` /
`--all` / `--cards <path>`, resolved through `cards/manifest.json` by
`scripts/set_argument.py` — never a spelled-out filename. An unknown code exits
naming the codes that ship. The four whole-pool instruments (grammar_coverage,
hook_reliance, parse_coverage, behaviour_classes) scope with `--set` only, as a
stdout report; their `--check`/`--accept` always cover the whole pool. Guarded
by `tests/engine/test_script_set_argument.py`.

**`engine/card_loader.py` is the only module that opens the manifest.** Import
its helpers (`manifest_sets`, `manifest_measured_sets`, `manifest_set_paths`,
`MANIFEST_PATH`); a private reader is a second copy of the registry and goes
stale without failing. `include_measured` defaults to False everywhere except
`ingest_set.py --all`, which is about a card file's format. Guarded by
`test_the_manifest_is_parsed_in_one_place`.

**Parse coverage:** `scripts/parse_coverage.py` verifies that every sentence of
every supported card's oracle text is claimed by a known consumer; it reads
shipped *and* measured sets and gates on the shipped half
(`tests/engine/test_parse_coverage.py`). Deliberate shortcuts live in its
`ACKNOWLEDGED` dict, with reasons. A deletion probe flags words a matching rule
ignored, ratcheted through `scripts/parse_coverage_probe_baseline.json` —
review new findings, then `--accept-probe`. When adding a parse rule or a
text-keyed behaviour, run `--check`; a handler that implements trailing
sentences of a clause declares them in `HANDLER_CLAIMS`.

To **launch and drive the running web app**, use the `/run-magic` skill
(`.claude/skills/run-magic/`); it drives the browser with `playwright-cli`. The
board is canvas-rendered, so DOM selectors won't find cards.

## Engine architecture

The compile-and-dispatch pipeline:

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
no instruction and the card is reported unsupported naming the clause. Read
`ROADMAP.md` before doing parser work; coverage lives in `GRAMMAR_COVERAGE.md`.

**Where a new template goes.** Both halves are layered, bottom to top, and the
effect families are the *same names* on each side — so one template has one home
per side:

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

- **Families do not import each other.** A fragment two families need goes in
  `phrases` / `_common` / `_core`; a module a family imports is a floor, not a
  family (`lowering/_amounts.py`, `ast/_primitives.py`).
- **No module may exceed 1,000 lines.** That is the signal that a family
  stopped absorbing new work. When one splits, reuse the other side's family
  name so the mirror re-forms instead of forking.
- **A production whose sentence a derivation table also reads must refuse in
  the *parse*.** A table (`engine/grammar/derived.py`) is reached only where
  every production refuses the line in full; parsed-but-unlowered is still
  parsed, and takes the table's line away.
- A new node gets a class in `ast/<family>.py`, parses in `effects/<family>.py`
  and lowers in `lowering/<family>.py`. Each `__init__` re-exports flat.

Held by `tests/engine/test_grammar_layering.py`.

### Extension points

Each is a small registered function — **adding a card means adding entries, not
editing dispatch.** One or two sentences each; the paragraph is in
`engine/ARCHITECTURE.md` under the same name.

**Parsing and compiling**

- `engine/grammar/` — a new pattern is a *production*, with no precedence
  number to pick. A production must consume **every token** of its line or
  raise `GrammarError`. `GRAMMAR_CATEGORIES` is held equal to every category
  `lowering/categories.py` declares (`tests/engine/test_grammar_categories.py`);
  an effect that should *not* execute is a `LoweringError` naming what is
  missing. Vocabulary is data in `data/vocabulary/`
  (`scripts/fetch_vocabulary.py`) — never hardcode a type list.
- **Which keywords the engine implements is one frozenset**,
  `vocabulary.IMPLEMENTED_KEYWORDS`. Adding one means the word plus behaviour
  that covers **everywhere the CR says it applies**, not just the path the pool
  exercises (lifelink is the worked example:
  `damage_events.lifelink_life_gained`, one rule with three callers). A keyword
  the CR defines as another ability is a **rewrite** in
  `oracle.expand_ability_lines` and is *not* in the set — equip, cycling, echo,
  buyback, kicker and flashback among them.
  `tests/engine/test_keyword_registry.py`.
- **Every reader of a card's lines starts from `oracle.expand_ability_lines`**
  (`legality.py`, `parse_coverage.py`, `hook_reliance.py`), or it is reading a
  different card.
- `engine/effect_labels.py` — the `effect_kind` *label* an ability reports.
  Never dispatch. `tests/engine/test_effect_labels.py`.
- `engine/card_hooks.py` — **the only sanctioned place to key behaviour on a
  card name**, across `engine/` and AI heuristics alike
  (`tests/engine/test_card_name_reads.py`). The bar is that no second card,
  real or plausibly printable, shares the shape: give an invented card the same
  text and see whether it works. `CARD_LINE_INSTRUCTIONS` is read after the
  grammar refuses; a line that grows a production leaves its entry dead, and
  `tests/engine/test_card_lines.py` fails on a dead one.
  `scripts/hook_reliance_ratchet.json` holds **ceilings**
  (`tests/engine/test_hook_reliance.py`).
- **A trigger condition's narrowing is data, not a kind**: a `<name>_subject`
  / `<name>_count` group in `engine/oracle.py`'s pattern table. Ability words
  (CR 207.2c) are dropped by `oracle_types.strip_ability_word` — threshold is
  one condition, `cards_in_zones`.
- **A trigger condition needs a dispatcher, and parsing is not one**
  (`tests/engine/test_trigger_dispatchers.py`). An announcement with no single
  call site goes on the state-based sweep (`mixins/game_ending.py`).
- **Text-keyed tables** — derived from oracle text with the parameters as
  payload, so a card printed with a known template needs no registration:
  `combat_restrictions.py`, `untap_restrictions.py`, `draw_step_modifiers.py`,
  `cast_restrictions.py`, `activation_restrictions.py`, `cost_modifiers.py`
  (both directions; `reduce_cost` is CR 118.7's arithmetic),
  `land_animation.py`, `land_play_allowance.py`, `landwalk.py`,
  `mana_could_produce.py`, `counter_conditions.py`, `target_requirements.py`,
  `counted_names.py`. Where a table gates support, the gate reads the same
  table the dispatch does — a restriction clause nobody listed is *unenforced*,
  not dead. A table joins the grammar's `registry_for_line` for its line to
  parse at all (`tests/engine/test_static_line_support.py`).

**Executing**

- `engine/handlers/` — `@effect_handler(kind)` functions, dispatched by dict
  lookup; shared helpers in `handlers/_common.py`.
- `engine/handlers/control_flow.py` — `sequence`, `if_then`, `may`, `for_each`.
  Compose, never fuse: "deal damage, then gain life" is two instructions in a
  `sequence`. Values pass through `OracleExecutionContext.results`.
- `engine/handlers/conditions.py` — one `@condition(kind)` handler per lowered
  condition kind behind `evaluate_condition` (still importable from
  `control_flow`). A new condition is a registered function, never an arm
  (`tests/engine/test_condition_registry.py`). Conditional statics keep their
  own vocabulary in `engine/static_bonuses.py`.
- `engine/subject_filters.py` — what a printed noun phrase means, tested
  against one permanent: `subject_matches`. A compiler admits a narrowed line
  only when every payload key is in `TESTABLE_SUBJECT_FILTER_KEYS`
  (`tests/engine/test_subject_filters.py`).
- `engine/pt.py` — the single write API for power/toughness. Token creation is
  `tokens.make_token_card` plus the generic `create_token` kind.
- `engine/replacements.py` — CR 614 interceptors by event kind, each a pure
  `applies` predicate, the effect and an explicit `order`. **Add the line to
  `REPLACEMENT_LINES`** or the card is unsupported however well it works. An
  optional or choosing replacement offers a `ReplacementChoice`
  (`engine/replacement_choices.py`).
- `engine/prevention.py` + `engine/shields.py` — CR 615. A new "prevent …"
  card is a `@prevention_effect` entry and a `Shield`, never a branch in a
  damage path, a new `PlayerState` field or a clearing line in a turn step.
- `engine/effect_ordering.py` — CR 616.1. Applicability is a **separate, pure**
  predicate. `engine/resumption.py` makes a contended event resumable: **a loop
  using it must be the last thing its function does.**
- `engine/damage_events.py` — `deal_damage` is the one entry point; there is no
  half-event. The event carries who dealt it (`damage_source_seat`, derived).
- `engine/destruction_events.py` — a destruction is announced where it is
  *decided*, with its cause; a sacrifice and a state-based move are not one.
- `engine/phases/upkeep_effects.py` — `@upkeep_effect(condition, kind)`.
- `engine/piles.py`, `engine/state_triggers.py` (CR 603.8's latch, both
  halves), `engine/object_colors.py`, `engine/color_census.py`,
  `engine/characteristic_defining.py`, `engine/static_bonuses.py`.

**One seam each — do not go round it**

- **Drawing**: `Game._draw_with_replacements`. `PlayerState.draw` is banned
  outside it (`tests/engine/test_draw_seam.py`), and draws are made one at a
  time.
- **Discarding**: `Game._discard_card`; the event says who caused it.
- **Every "put this card into a hand / a library"**: `Game.put_card_into_hand`
  / `put_card_into_library` (CR 903.9b has no single fire site).
- **Leaving the battlefield is one transition**: `remove_from_battlefield` /
  `remove_all_from_battlefield`.
- **Leaving a hand is one too**: `Game.take_card_from_hand(owner, card)`. Every
  copy of a card in a hand is the *same object*, so an identity filter removes
  all of them (`tests/engine/test_hand_removal_seam.py`).
- **"Tapped for mana" is one event**: `Game._land_tapped_for_mana`.
- **Targets chosen**: `Game.announce_targets_chosen`, read back with
  `stack_targets.chosen_targets`.
- **A colour is written through `color_changes.change_color`**
  (`tests/engine/test_color_write_seam.py`); a one-shot type change through
  `engine/type_changes.py`.

**The board: who controls what, and what it is**

- **Never iterate `player.battlefield` directly.** Use the control seam on
  `Game` (`all_permanents()`, `permanents_with_controller()`,
  `controlled_by(seat)`, `permanents_matching(pred)`,
  `controller_index_of(perm)`, `controls(seat, perm)`,
  `is_on_battlefield(perm)`): the lists are the *projection* of the derived
  controller, and `in` / `.remove()` on them compare by value
  (`tests/engine/test_control_reads.py`).
- **Address a permanent by its id, not its slot.** `permanent_by_id`,
  `find_permanent_by_id`, `permanent_id_of`; `.battlefield.index()` /
  `.remove()` are banned. An id names a battlefield as well as an object:
  `Game.announced_target_seat`. A combat map joins
  `_renumber_combat_after_removal`.
- `engine/control.py` — a control change is a *contribution*
  (`change_control` / `end_control_change`); `base_controller_index` is never
  rewritten.
- `engine/continuous.py` + `engine/layer_bridge.py` — the CR 613 layers.
  **Characteristics are computed, not stored**: ask `has_type`, `is_creature`,
  `effective_power`, `has_keyword` (`Game._has_keyword` from inside the
  engine), the colour accessors and `Game.controller_index_of`, never
  `card.type_line` or a metadata flag (`tests/engine/test_layer_reads.py`).
- **"What does it say?" is `Permanent.effective_card`**, not
  `perm.card.oracle_text`. Its folds are memoised by `copies.card_identity`,
  **never by `id()`** (`tests/regressions/test_derived_card_memo_identity.py`),
  and its accessors execute no import statement
  (`tests/engine/test_hot_accessor_imports.py`).
- Layer 5 is ordered by timestamp; layer 4 is applied once for the whole board
  with dependency (`engine/type_statics.py`). CR 305.7 is one strike, in
  `effective_card`.
- `engine/auras.py` — `attach_aura` / `detach_aura`, never the raw metadata.
  `engine/equipment.py` — `equip_refusal` is the one legality predicate.
- `engine/enter_effects.py` — `enter_effect_line` is read by the support gate
  *and* the grammar; `ENTRY_CHOICES` is what a permanent may choose as it
  enters, and the client has to be able to answer it
  (`tests/ui/test_entry_choice_prompt_ui_api.py`).
- `engine/faces.py` — **a face is a card**, and a split card is cast by the
  name of the half. The whole card's program has no instructions, so anything
  that asks about *text that compiles* iterates
  `faces.compilation_units(pool)` / `oracle.compiled_units`
  (`tests/engine/test_face_blind_guards.py`).
- `engine/commander.py` — CR 903, opt-in. Colour identity is derived, not read
  off the ingested field; the commander is a card object, per seat. Its deck
  rows in `web/deck_legality.py` are mirrored in `web/static/legality.js`.

**Casting, activating, targeting**

- `engine/cast_prohibitions.py` — may this card be cast at all: one table, and
  three readers make one call (`cast_prohibition(game, seat, card)`): the cast
  path, the AI and the castable highlight
  (`tests/engine/test_cast_prohibition_readers.py`).
- `engine/cast_costs.py` — additional costs. "Kicked" has three readers at
  three times (`was_kicked`, the `KICKED` / `KICKED_WITH` stamp,
  `cast_kicked`); a named cost permanent pays or the spell is not cast; an
  alternative cost still owes what a tax adds (`Game.alternative_cost_mana`).
  `engine/flashback.py` is a permission, an alternative cost and a destination.
- `engine/mana_payment.py` — casting spends the *pool* (`_pay_mana_cost`); an
  effect's "you may pay" also taps lands **for mana**
  (`Game._pay_planned_cost`). `plan_payment` is told who is paying (`payer=`).
  **What a mana ability is, is one predicate**, `is_mana_ability` (CR 605.1a's
  four criteria). A cost is a symbol dict (`generic_cost(n)`).
  `engine/board_payment.py`'s `board_can_pay` is what a highlight asks.
- `engine/targeting.py` — what a spell or ability targets, derived from the
  *compiled program*; None rather than a guess. **One enumeration
  (`_enumerate_targets`) is the picker's list and every gate's list**, and
  targets are read by `permanent_id`, never by index. A spell is held at
  announcement (`legality.cast_target_refusal`,
  `no_legal_cast_target_refusal`; CR 601.2c) and every object whose targets
  somebody chose at resolution (`illegal_targets_refusal`,
  `blank_illegal_resolution_targets`; CR 608.2b), by the same predicate. An
  ability is held by `legality.activation_target_refusal`, before any cost is
  paid. A modal spell is held to the mode it announces
  (`targeting.announced_mode_instructions`).
- **A cast trigger's "it" is a stack object, not a card** (`cast_item`,
  `handlers/_common.triggering_spell`).
- **A permanent's entry trigger is a stack object** (CR 603.3), so its source
  can leave first: a handler that moves something "until this leaves the
  battlefield" asks `linked_exile.until_leaves_has_ended`.
- "Assign combat damage as though it weren't blocked" is an announcement on
  `resolve_combat_damage`, not a `pending_choices` prompt.

**Prompts and the turn**

- `engine/pending_choices.py` — every decision a seat owes part-way through:
  one `PendingChoice` queue, one `ChoiceSpec` per kind (registered at the
  bottom of `engine/mixins/stack/choices.py`), one renderer in
  `web/prompts.py`. **Adding a prompt is one `register_choice` + one renderer +
  the code that arms it — never a new `Game` field.**
- **While a prompt is owed, the game waits** (`ChoiceSpec.holds_priority`,
  `Game.waiting_prompt`): the object stays on the stack and nobody receives
  priority until its last prompt is answered.
- **A private look stays private in the log** (`Game.find_is_public`), and "in
  any order" is the owner's to choose (`offer_library_bottom_order` /
  `offer_library_top_order`).
- `engine/phases/` — one mixin per phase and step. `engine/mixins/` —
  cross-cutting flow; consumes compiled programs and **must never parse oracle
  text**. A step does not end on an empty stack alone
  (`_resolve_priority_window`). `engine/mixins/stack/` — `casting`,
  `activation`, `resolution`, `choices`.

`engine/oracle.py` is the compiler. `engine/oracle_types.py` holds shared
dataclasses and imports nothing from the engine.

### Precedence: there isn't any any more

A grammar has no precedence knob: a production consumes its line or refuses it.
Two orderings remain, both asserted: **the grammar before the card hooks**
(`tests/engine/test_card_lines.py`), and **productions before the derivation
tables** (`tests/engine/test_grammar_derived_lines.py`).

### Adding support for a new card

Work top-down, stop at the first step that covers it (recipe in
`engine/ARCHITECTURE.md`):

1. Already covered? (`compile_card_oracle(card).supported`) → done.
   `python scripts/support_report.py --set <CODE>` names each unsupported
   card's unrecognized line.
2. New text, existing effect → add a *production* to `engine/grammar/`
   returning an existing kind.
3. New effect → invent an instruction kind (verb_object naming), give it an
   entry in `INSTRUCTION_CATEGORIES` *and* `GRAMMAR_CATEGORIES`, then add a
   `@effect_handler`. Token creation → `create_token`. P/T → `engine/pt.py`.
   "Would happen, instead" → `engine/replacements.py`.
4. Bespoke behaviour → a hook in `card_hooks.py`, as the last resort.
5. Add a focused test in `tests/sets/`, in the file for that set and that
   card's printed type (`tests/sets/README.md`). Fixtures keep the per-set
   pools separate so name lookups stay unambiguous: `set_pool("<CODE>")` for
   any set, `all_cards` / `cards` (LEA) and `arn_cards` / `arn_by_name` as
   grandfathered aliases; `catalog` / `catalog_by_name` are the whole manifest
   pool, for pool-wide work only. The comprehensive-cast sweep
   (`tests/engine/test_catalog_sweep.py`) covers a newly ingested set
   automatically.

Cards whose text falls outside recognized patterns degrade gracefully:
classified unsupported with an explicit reason, never crashing simulation.

### Determinism

`run_ai_simulation` seeds the module-level RNG, so a given seed reproduces a run
exactly — required for the AI-behavior regression tests. Preserve this when
touching anything that consumes randomness.

## Web layer

`web/app.py` is the FastAPI app (`/api/...` routes + static UI in `web/static/`)
and **nothing else** — it is the one place a route is declared. Everything else
is a module beside it, **layered**: `web/__init__.py` declares the order in
`LAYERS` and a module may import only from one *earlier* in it
(`tests/ui/test_web_layering.py`, which catches a function-level import too).

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

- **The pool is loaded once**, from `cards/manifest.json` into `CARD_CATALOG`
  (`runtime.py`). Adding a set means ingesting it and adding one manifest
  entry. Reprints dedupe to a single card by `oracle_id` (first printing wins).
- State lives in in-memory stores: `session_store.py`, `deck_store.py`,
  `verification_store.py`.
- **Game actions funnel through one endpoint**, `POST
  /api/sessions/{id}/action`, dispatched by the `ActionKind` literal in
  `web/schemas.py`. The wire carries a permanent's `id` and resolves it once at
  the top of `web/actions.py`; a stale id is a 404.
- Session `mode` is one of `human_vs_ai`, `ai_vs_ai`, `human_vs_human`,
  `free_for_all` (3–4 seats, configured per seat via `seats`).
- **`web/prompts.py` owns every prompt's presentation**, and its three loops
  read the registry, so a new prompt is covered by construction.
- **The client keeps no copy of the engine's rules.** What a card can do right
  now is *sent*: `waiting_on_prompt`, a card's `ways`, a permanent's
  `ability_denials` / `ability_mana` / `abilities_lost` / `entry_choices`, a
  payment's `payable`, a search's `min_picks`. The client reads those, never
  the oracle text.
- AI-owned prompts are answered before **and after** an action's handler. **An
  AI step never advances a human's turn.**
- **A client change is not done until it has been clicked.** The board UI is
  canvas-rendered (`web/static/battlefield-canvas.js`), and a text-level test
  reads the handler behind the gate.

## Card verification tracker

`CARD_VERIFICATION.md` / `card_verification.json` track which cards have been
manually validated in-game: 754 of the 5,246 catalog cards passing (497 checked
in-game, 257 auto-passed), 59 more reported `equivalent`, 0 failing. The summary
at the top of the markdown is the current number.

- **It is a log, never a coverage target**, and an in-game pass does not gate a
  promotion — `SET_PLAYBOOK.md` Phase 5 owns it. The number rises as a
  by-product of driving cards to find bugs.
- **Generated automatically** — results are edited via the in-game Debug Menu,
  not by hand.
- **A failing row stays until the card is fixed *and re-checked in the app*.**
  Fixing the code does not clear it.
- A *simple* card (`engine.oracle.simple_card_keywords`: no abilities, or only
  implemented keyword lines) is **auto-passed**, derived on read from
  `web/runtime.py`'s `AUTO_PASSES`. A recorded result always wins over it.
- An untested card is reported `equivalent` when a *passing* card shares its
  behaviour class (`engine/behaviour_signature.py`); derived on read, never
  stored. `scripts/behaviour_classes.py --check` fails when classes drift.
- `tests/regressions/test_card_verification_regressions.py` guards verified
  cards.

## MTG rules questions

For rules/timing/layers/interaction questions, the `mtg-rules` skill
(`.claude/skills/mtg-rules/`) is authoritative; it consults `MagicCompRules.txt`
(the full Comprehensive Rules, in the repo root). Don't answer non-trivial
rulings from memory — cite that file.
