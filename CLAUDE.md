# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository. It says how the code works **now**. How each rule was
learned is in `SET_RETROSPECTIVES.md` and in `git log`; when a set or
a round changes a rule, edit the rule here in place and put the story in the
commit message. It carries no number a tracker owns — counts live in the
generated `*.md` trackers, so finishing a set does not edit this file to update
them.

**Subject detail lives in `.claude/rules/`**, one file per subject, and each
loads when you read or edit a file its `paths:` names — the extension-point
catalogue (indexed under "Extension points" below), the AI simulator, the web
layer, and running and writing tests. They are part of this file: the same
rule for editing applies, and a rule moves between them by subject. Open one
directly whenever its subject is yours, before the file that would load it.
Keep each under 40,000 characters: Claude Code cuts an on-demand file off at
that length.

## What this is

**MTG Simulacrum** — a text-based **Magic: The Gathering rules engine** plus a
FastAPI web app with a browser game UI. The card pool is one JSON per set in
`cards/`, registered in `cards/manifest.json`, the single source of truth for
which sets ship. Every shipped card is supported; per-set sizes and progress
are in `SET_PROGRESS.md`. Card files hold only the fields the engine and web
layer read; `scripts/ingest_set.py` produces them.

The engine is **registry-based**: card support grows by adding small isolated
entries, never by editing core control flow. `ROADMAP.md` tracks the work
toward the full ~26,000-card release line — read it before parser or card-data
work. `SET_PLAYBOOK.md` is the process for adding a set (ingest → measure →
rounds → promotion → retrospective), and `scripts/integration/` is the
integrator's toolkit for running one.

### The manifest

**Two roles.** `sets` is the shipped pool, held at 100% supported: the web app
offers those cards, and two guards (`tests/engine/test_front_end_safety.py`,
`tests/engine/test_card_format.py`) fail if one is unsupported. `measured` is a
set ingested so its numbers can be read *before* it is supported: the coverage
instruments load it (`manifest_set_paths(include_measured=True)`), `load_catalog`
does not, and no player can deck one of its cards. It moves to `sets` when every
card is supported, and `measured` is empty between sets. Guarded by
`tests/engine/test_manifest_roles.py`.

**`MTG_PROMOTE=<CODE>` is the promotion in memory**: `card_loader`'s one read
of the manifest moves that measured set into `sets` at its printing-ordered
place for the process, the file untouched, so the censuses over
`load_catalog()` can be run with the set shipped while it is being
implemented. A rehearsal, never a gate — the shipped-pool guards fail on its
unsupported cards; the test header names it, and `check_all` and the
integration gates refuse to run under it (`census_rehearsal.sh` is the one that
does).

A measured set is nameable by the reporting scripts (`--set <CODE>`, labelled
"measured, not shipped"); `--all` means the shipped pool alone. The four
whole-pool instruments (grammar_coverage, hook_reliance, parse_coverage,
behaviour_classes) report a measured set and leave it out of their floors,
ceilings and gate — a ratchet over a set nobody has implemented fires on its
composition rather than on anything anyone did.

**The manifest is printing-ordered, and the order is load-bearing.** Reprints
dedupe to one card by `oracle_id` (first printing wins), every printing is in
`CardDefinition.printings`, and `original_printing` is the first of them — so a
set inserted out of order changes which set a card "originates" in (Golgothian
Sylex asks). A new set goes *between* the sets it was printed between. Two
guards: `test_appending_a_set_never_changes_an_existing_original_printing`
(compares prefixes: inserting is legal, reordering is not) and
`test_manifest_roles.test_the_shipped_sets_are_in_printing_order` (the
`released` dates).

**The prefix guard is blind to the new set's own cards.** A reprint whose only
other printing here is *later* than the new set has its origin decided by the
insert position, with every other guard green (Stronghold's Shock, Urza's
Saga's three, Invasion's Opt, Planeshift's Quirion Dryad, Seventh Edition's
Mind Rot — each one card). Count reprints against the sets that actually print
them (`scripts/integration/census_new.py`), and rehearse the wrong-end insert at
every promotion (`scripts/integration/promote.py CODE --wrong`): only the
printing-order guard may turn red.

## Commands

All Python runs through the workspace venv (Windows / PowerShell):
`.\.venv\Scripts\python.exe` (referred to below as `python`).

```powershell
# Tests (pytest.ini sets testpaths=tests, addopts=-q)
python -m pytest                                  # the quick pass, serial
python -m pytest -n 8 --dist worksteal            # the quick pass in parallel; -n 4 while agents are running
python -m pytest -n 8 --dist worksteal --full     # the full pass: the last wave-close rehearsal's and the promotion gate's run
python -m pytest -n 4 --dist worksteal -m "not full" tests/ai   # one CI shard as ci.yml runs it (shards: tests/ai -m full [full pass only] | tests/ai -m "not full" | tests/engine | the rest)
python -m pytest tests/ui/test_web_api.py -q      # one file (a file named runs whole, `full` tests too)
python -m pytest tests/sets/test_lea_creatures.py::test_name -q   # one test
python -m pytest tests/regressions -q             # in-game bug regressions
```

**Two passes** (`tests/passes.py`). `pytest` is the quick pass; `pytest
--full` is the full pass, run by the rehearsal of the tree that closes the
last wave and by the promotion gate (SET_PLAYBOOK Phase 4, `gate.sh <tree>
<tag> <workers> full`). Some structural guards are `full`-marked too
(`test_face_blind_guards`' repo scan, `test_grammar_layering`,
`test_cast_prohibition_readers`), so a quick-pass run of `tests/engine` does
not ask them: name them before calling a branch done. A test marked
`@pytest.mark.full` runs only in the full pass — the seeded AI-game batches
and whole-pool censuses that take 10 s or more, 163 functions holding 88% of
the full pass's test-seconds on 2026-10-31 (at `-n 12`: 1,412 s against the
quick pass's ~175) — and the full pass runs every
sampled census whole (`MTG_FULL_CENSUS`, read by `tests.helpers.stable_sample`;
the trigger-order census, whose rows are pairs, takes sixteen times its share,
`FULL_FACTOR`).
A file or test named on the command line runs whole, unless `--quick` keeps
the quick pass in it too; `-m full` turns the full pass on (it used to collect
nothing). `python scripts/tests_for_diff.py` lists the test files a diff owes
— edited tests, importers of an edited module, every census enumerating a
registry the diff moved — with their quick and full seconds from the last run
that timed them (every run merges its times into `.test_timings.json`), and
`--run` runs their quick tests. The quick pass ends by
naming any unmarked test that took 20 s or more: make it faster or mark it
`full`. A large run compiles the pool before its first test, so every test's
time is its own; a test that clears the compile caches calls
`tests.passes.rewarm_compile_cache()` (`tests/engine/test_passes.py`). Prefer
`--dist worksteal`: a few long tests decide the wall time.

**Running and writing tests** — the compiled-program store (why the first run
after an engine edit pays ~20 s and the next ~4 s, and why a script that walks
the pool calls `program_store.warm()`), the memory guard behind `-n`, which
subfolder a test goes in, the per-set convention, and the `cr` marker every
`tests/rules/` test carries — is `.claude/rules/tests.md`, loaded with any
file under `tests/`.

**A CR citation must be about what the comment claims, and a CR bump is a
silent, repo-wide correctness event**: an edition that inserts a rule shifts
every number after it, so an old citation names a different rule (`701.15c` is
Goad). `tests/engine/test_cr_citation_subjects.py` reads the 701 keyword-action
headings out of `MagicCompRules.txt` and fails a citation in `engine/`, `web/`,
`scripts/` or `tests/` whose keyword moved;
`tests/engine/test_kg4_citations_rule_subjects.py` fails a cited number or
letter the shipped CR does not have (a list's later members and every `cr`
marker included) and a CR 113.7a / 112.2 citation made for a neighbouring
rule's claim (`RULE_SUBJECTS`: 113.7a is an ability outliving its source, not
"an ability is not a spell", 113.9). Outside 701, `scripts/cr_edition_diff.py old.txt` compares two editions by text
and lists every citation here of a rule that moved, changed or went; install a
download with `--install` (some editions mark blank lines with a NO-BREAK
SPACE). The shipped CR is the **September 25, 2026** edition.

```powershell
# Web server (browser game UI)
python -m uvicorn web.app:app --host 127.0.0.1 --port 8010   # then open http://127.0.0.1:8010/
python scripts/serve_lan.py --port 8010   # same app, dual-stack IPv4+IPv6 for LAN play

# Engine scripts
python scripts/run_duel.py            # scripted deterministic duel, no server (default LEA)
python scripts/simulate_ai_games.py --set DRK   # AI-vs-AI batch over one set; deterministic per seed (default LEA)
python scripts/support_report.py      # per-category card-support coverage (whole pool)
python scripts/support_report.py --set ATQ --hollow-lines   # supported cards carrying an ability with no instruction behind it
python scripts/support_report.py --set LEG --refusals   # every refused line of every unsupported card with its refusal site — the work list rounds are planned from
python scripts/support_report.py --set HML --fragments   # n-gram census over the refused lines, ranked by how many cards share each fragment (--json emits every census as one object)
python scripts/retrieve_oracle.py "Black Lotus"   # oracle text by name (whole pool)
python scripts/probe_line.py --card "<NAME>"   # why a line is refused: every layer the compiler consults, in order, one verdict a line (--json; raw lines: probe_line.py "<line>" [--type ...])
python scripts/picker_sweep.py --set <CODE>   # supported cards whose cast/activation picker disagrees with the printed line — run over a measured set in Phase 3
python scripts/oracle_diff.py snapshot   # record every card's full compiled program (both manifest roles) before a change
python scripts/oracle_diff.py compare    # every card whose program moved since the snapshot; exit 1 if any did
python scripts/sim_fingerprint.py snapshot   # twelve seeded AI games' logs, before a change
python scripts/sim_fingerprint.py compare    # which of those games played differently; exit 1 if any did (whole diffs in .sim_fingerprint/compare/)
python scripts/tests_for_diff.py --why   # the tests this diff owes and their recorded times; --run runs their quick tests
python scripts/set_progress.py        # regenerate SET_PROGRESS.md; --refresh re-fetches Scryfall data
python scripts/check_all.py           # every CI guard check, in ci.yml's order (--freshness adds the tracker regenerations + a clean-tree check; --caps the size-guard headroom; --workers N for parse_coverage)
python scripts/rules_progress.py      # regenerate RULES_PROGRESS.md; --check fails on unannotated tests
python scripts/rules_gaps.py          # rank untested CR rules; flags stale CR citations (advisory)
python scripts/cr_edition_diff.py old.txt   # a CR bump: every citation of a rule that moved, changed or went; --install <download> writes the new file
python scripts/unasked_narrowings.py  # printed narrowings whose handler never supplies the seat `subject_matches` needs (advisory; --check to fail)
python scripts/behaviour_classes.py   # regenerate BEHAVIOUR_CLASSES.md; --check fails on drift, --accept re-snapshots; --set <CODE> prints which classes that set lands in
python scripts/parse_coverage.py      # regenerate PARSE_COVERAGE.md; --check fails on unclaimed text; --set <CODE> prints that set's claims (stdout only)
python scripts/grammar_coverage.py    # regenerate GRAMMAR_COVERAGE.md; --check fails on regression, --accept re-snapshots floors; --set <CODE>
python scripts/hook_reliance.py       # regenerate HOOK_RELIANCE.md; --check fails on a rise, --accept re-snapshots ceilings; --set <CODE>
python scripts/fetch_vocabulary.py    # re-fetch data/vocabulary/*.json from Scryfall (a new set adds creature/land types); --check confirms presence (CI)
python scripts/ingest_set.py 3ED --fetch --register   # add a set under `measured`, release-ordered; promotion to `sets` is a reviewed hand move
python scripts/ingest_set.py --all --check # report card-file sizes without writing
```

**Two differentials answer "what did this change touch?"** `oracle_diff.py`
stores every card's compiled program in full (payloads and all, so a dropped
narrowing is visible); `sim_fingerprint.py` stores the logs of twelve seeded AI
games across the pool, which are deterministic to the byte. A change meant to
move nothing — a split, an extracted helper — reads 0 on both. A change meant to
move one card reads that card.

**Naming a set:** every script that runs over a set takes `--set <CODE>` /
`--all` / `--cards <path>`, resolved through the manifest by
`scripts/set_argument.py` — never a spelled-out filename, which is a second copy
of the registry. An unknown code exits naming the codes that ship (an empty pool
would report perfect coverage over zero cards). Guarded by
`tests/engine/test_script_set_argument.py`. The four whole-pool instruments take
`--set` only, as a stdout report; their `--check`/`--accept` and committed `.md`
always cover the whole pool.

**`engine/card_loader.py` is the only module that opens the manifest.** Import
its helpers (`manifest_sets`, `manifest_measured_sets`, `manifest_set_paths`,
`MANIFEST_PATH`); a private reader goes stale silently. Guarded by
`test_the_manifest_is_parsed_in_one_place`. `ingest_set.py --all` covers **both**
roles (it is about a file's format, not about decking it); everywhere else
`include_measured` defaults to False.

**Parse coverage:** `scripts/parse_coverage.py` verifies that every sentence of
every supported card is claimed by a known consumer — the parser, compiler
tables, the text-keyed channels and handler claims, card hooks. The tables
(`CHANNELS`, `CARD_CHANNELS`, `HANDLER_CLAIMS`, `ACKNOWLEDGED` with reasons) are
in `scripts/parse_coverage_claims.py`. It reads shipped *and* measured sets and
gates on the shipped half (`tests/engine/test_parse_coverage.py`). A deletion
probe flags words a matching rule ignored, ratcheted through
`scripts/parse_coverage_probe_baseline.json` (`--accept-probe` after review).
The script analyses the pool in processes (`--workers`, default 8; the probe
re-parses every sentence once per word, ~90 s in one process), reading the
cards back in pool order, so its report is the same byte for byte at any
count; `analyze_pool` called from a test runs in-process, where a monkeypatch
is seen. When you add a parse rule or a text-keyed engine behaviour, run `--check`; a
handler that implements trailing sentences of a clause declares them in
`HANDLER_CLAIMS`. Only the four event-keyed hook registries
(`ON_LEAVE_BATTLEFIELD`, `ON_SELF_RESOLVED`, `ON_SPELL_COUNTERED`,
`DRAW_STEP_MODIFIERS`) claim a whole card; a line hook claims its line.

To **launch and drive the running web app** (screenshots, scripted UI flow), use
the `/run-magic` skill at `.claude/skills/run-magic/` (with `playwright-cli`).
The board is canvas-rendered, so DOM selectors won't find cards; the skill
documents the working harness.

## The AI simulator

`run_ai_simulation` deals each seat a seeded limited deck and **plays the
engine's turn, never a copy of it**: every piece of the turn arrives with its
honesty count in `SimulationReport`, and a run that cast nothing exits 1. The
whole of it — casting, mana, mulligans, priority, rehearsal, hidden
information, the module families — is `.claude/rules/ai-simulator.md`, loaded
with `engine/ai_*.py`, `tests/ai/` and the web AI seat's modules.

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
no instruction and the card is reported unsupported naming the clause.
Coverage lives in `GRAMMAR_COVERAGE.md`.

**Module size.** No Python module in `engine/`, `web/` or `scripts/` may exceed
**2,000 lines** (`tests/engine/test_module_size.py`) — not style, but the signal
that a module stopped absorbing new work by subject. Split along the subject the
new work belongs to, never by raising the number, and leave every module the
split touches at ~1,500 or less so the next sets have room. `check_all --caps`
(or `scripts/integration/headroom.py`) lists the modules within 200 lines of the
cap; SET_PLAYBOOK's Phase 0 splits those before a set rather than during a wave.
A split is code motion: `oracle_diff` 0/0/0 and `sim_fingerprint` 0 moved.
`tests/` and `web/static/` are outside the cap (the per-set test files have their
own, 2,600).

### Extension points

Each is a small registered function or table — **adding a card means adding
entries, not editing dispatch**.

The catalogue is in `.claude/rules/`, one file per subject, each loaded with
the modules and guard tests it describes:

- `engine-parsing.md` — where a new template goes (the grammar's two layered
  halves, family independence, derivation tables), implemented and rewrite
  keywords, ability words, effect labels, card hooks and the bar for one,
  trigger conditions and their dispatchers, and what the compiler does.
- `engine-effects.md` — effect handlers and control flow, subject filters,
  P/T writes, tokens, piles, names and colour; CR 614 interceptors, turn
  replacements, optional replacements, CR 615 shields, CR 616 ordering,
  resumable loops, damage events and simultaneous dealings, destruction.
- `engine-zones-and-mana.md` — outside the game, the draw, discard, hand,
  library and exile seams, entries that wait and enter together, departures
  that look back, mana payment, what a mana ability is, multi-face and
  face-down cards.
- `engine-casting-and-targets.md` — additional and alternative costs,
  flashback, madness, refusals, cast and activation prohibitions and
  restrictions, cost modifiers; target derivation, the legality gates, bare
  announcements, roles, target requirements and the stack's targets.
- `engine-triggers-and-prompts.md` — entry triggers on the stack, cast
  triggers, state triggers, trigger order and rounds, the zone a trigger
  functions from, unblocked attackers, upkeep effects; the prompt queue,
  waiting for answers, hidden and turn-order choices, entry choices, combat
  damage assignment.
- `engine-layers-and-turns.md` — graveyard statics, the CR 613 layers and
  their fast paths, control and the control seam, ids, leaving the
  battlefield, Auras, Equipment, the text-keyed tables, Commander; the phase
  and step mixins, state checks, held steps, the stack mixins.

### Ordering

There is no parse precedence: a grammar production consumes its line or refuses
it. Two orderings remain, both structural and both asserted: **the grammar
before the card hooks** (`tests/engine/test_card_lines.py`) and **productions
before the derivation tables** (`tests/engine/test_grammar_derived_lines.py`).

### Adding support for a new card

Work top-down and stop at the first step that covers it (recipe in
`engine/ARCHITECTURE.md`):

1. Already covered? (`compile_card_oracle(card).supported`) → done.
   `python scripts/support_report.py --set <CODE>` reports a whole set and names
   each unsupported card's line.
2. New text, existing effect → add a *production* to `engine/grammar/` returning
   an existing kind. The noun phrases, amounts and durations are already parsed.
3. New effect → invent an instruction kind (verb_object naming), give it an entry
   in `INSTRUCTION_CATEGORIES` *and* `GRAMMAR_CATEGORIES`, add an
   `@effect_handler`. Tokens → `create_token`; P/T → `engine/pt.py`; "would
   happen, instead" → `engine/replacements/`.
4. Bespoke behaviour → a hook in `card_hooks.py` keyed by name (or a
   `cast_restrictions.py` entry for a textual timing gate). Last resort.
5. Add a focused test in `tests/sets/`, in the file for that set and the card's
   printed type, getting cards from `set_pool("<CODE>")`. The
   comprehensive-cast sweep (`tests/engine/test_catalog_sweep.py`) covers every
   manifest set automatically.

Cards whose text falls outside recognized patterns degrade gracefully: classified
unsupported with an explicit reason, never crashing simulation.

### Determinism

`run_ai_simulation` seeds the module-level RNG, so a given seed reproduces a run
exactly — required by the AI regression tests and by `sim_fingerprint.py`.
Preserve this when touching anything that consumes randomness.

## Web layer

`web/app.py` declares every route and nothing else; the modules beside it are
layered (`web/__init__.py`'s `LAYERS`), game actions funnel through one
endpoint, and what a card can do right now is sent rather than re-derived by
the client. The module table, the prompt loops and the wire's fields are
`.claude/rules/web.md`, loaded with any file under `web/` or `tests/ui/`.
**A client change is not done until it has been clicked in a browser** — a
text-level test has passed over a change that made every Blood Moon land
unclickable.

## Card verification tracker

`CARD_VERIFICATION.md` / `card_verification.json` record which cards have been
validated in a running game; the summary at the top of the markdown is the
current number. It is **generated** — results are edited through the in-game
Debug Menu, never by hand — and it is a log, not a coverage target: an in-game
pass is a by-product of finding bugs (SET_PLAYBOOK Phase 5) and does not gate a
promotion.

- **Auto-pass**: a card with no abilities, or only implemented keyword lines
  (`engine.oracle.simple_card_keywords`; amplify excluded, its reveal being a
  prompt a person answers), counts as a pass with the reason in its
  note — derived on read from `web/runtime.py`'s `AUTO_PASSES`, never stored; a
  recorded result wins over it.
- **Equivalent**: an untested card sharing a behaviour class with a passing card
  (`engine/behaviour_signature.py`, `BEHAVIOUR_CLASSES.md`). Derived on read, and
  withdrawn if the peer fails. `behaviour_classes.py --check` fails on drift,
  because a signature that stops distinguishing two behaviours raises apparent
  coverage.
- **Failing** is an in-game bug report with a card name on it, and it stays until
  the card is fixed **and re-checked in the app** — fixing the code does not clear
  the row. `tests/regressions/test_card_verification_regressions.py` guards
  verified cards.

## MTG rules questions

For rules/timing/layers/interaction questions, the `mtg-rules` skill
(`.claude/skills/mtg-rules/`) is authoritative; it consults `MagicCompRules.txt`
(the full Comprehensive Rules, in the repo root). Don't answer non-trivial
rulings from memory — cite that file.
