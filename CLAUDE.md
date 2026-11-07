# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository. It says how the code works **now**. How each rule was
learned is in `SET_RETROSPECTIVES.md` and in `git log`; when a set or
a round changes a rule, edit the rule here in place and put the story in the
commit message. It carries no number a tracker owns — counts live in the
generated `*.md` trackers, so finishing a set does not edit this file to update
them.

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
A file or test named on the command line runs whole. The quick pass ends by
naming any unmarked test that took 20 s or more: make it faster or mark it
`full`. A large run compiles the pool before its first test, so every test's
time is its own; a test that clears the compile caches calls
`tests.passes.rewarm_compile_cache()` (`tests/engine/test_passes.py`). Prefer
`--dist worksteal`: a few long tests decide the wall time.

**The pool compiles once per engine, not once per process**
(`engine/program_store.py`). Each test process reads the compile at configure
time — before collection, which compiles the pool, since `tests/helpers.py`
imports `web.app` — from a store in `.program_store/`, named by a hash of every
`engine/**/*.py`, `data/` and `cards/*.json` file, so any edit to the engine — a
comment included — names a new store and the old one is never opened. The
first worker of a folder or whole-suite run to find none builds it in a
subprocess that imports only the engine (~18 s) and the rest wait for it; a run
naming files only reads one that is there. Reading takes under a second. Stored programs go into
`_compile_card_oracle`'s own `lru_cache`, so `clear_compilation_caches()` clears
them too. An engine module that starts reading a file adds its folder to
`program_store.INPUTS` (`tests/engine/test_program_store.py` fails until it
does). `MTG_NO_PROGRAM_STORE=1` turns the store off.

**The runner holds itself to the machine's memory** (`tests/memory_guard.py`,
hooked in by `tests/conftest.py`): `-n N` and `-n auto` run as at most what
free memory holds — a worker peaks near 2.5 GB, and 4 GB is kept free
(`MTG_PYTEST_NO_MEMORY_CAP=1` overrides) — and a `--collect-only` session, which
is what an IDE's test discovery is, waits for the one before it in the same
checkout. `load_cards` is cached per file version, so the test modules that load
the pool at import share one copy (each held its own, 5 GB a process, until
2026-10-31). An exit code 3 or 137 with no `FAILED` line is a worker that died,
not a red tree — re-run with fewer workers. Never pipe pytest through
`tail`/`head`: the pipe replaces its exit code.

Tests are organized by subject — put new tests in the matching subfolder:
`tests/ai/` (AI policy/simulator), `tests/ui/` (web API + frontend/end-to-end),
`tests/engine/` (loader, oracle compiler, parsing, dispatch internals, the
convention guards), `tests/rules/` (Comprehensive Rules sections and the casual
variants — ante, Commander, Brawl), `tests/sets/` (per-card tests for a specific
set), `tests/regressions/` (in-game bug regressions). Shared fixtures live in
`tests/conftest.py` and helpers in `tests/helpers.py`. A web test that means
"seat 0 acts first" on a table created without the pregame calls
`tests.helpers.seat_plays_first(sid)`: that deal plays first whoever its flip
names.

**Per-set tests follow `tests/sets/README.md`**, enforced by
`tests/engine/test_set_test_convention.py`: get a set's cards from
`set_pool("ARN")` / `set_cards("ARN")` — never a new `conftest.py` fixture and
never a spelled-out `cards/*.json` path; split a per-set file by the printed type
of the card each test names once it outgrows one file (2,600 lines); put
anything pool-wide in `tests/engine/`.

Every test in `tests/rules/` **must** carry a `@pytest.mark.cr("508.1a", ...)`
marker citing the rule(s) it verifies (a numbered rule or subrule, never a bare
section; verify it exists in `MagicCompRules.txt`). `scripts/rules_progress.py`
collects them into `RULES_PROGRESS.md`; `tests/engine/test_rules_progress.py`
fails on an unannotated test or a nonexistent rule. The tracked scope is the
`SCOPE` dict in that script; `EXCLUDED` drops only rules whose *mechanic* the
engine does not have (never a rule the engine implements that no card
exercises — that stays in the denominator as untested).
`scripts/rules_gaps.py` ranks untested rules and checks the CR citations in
`engine/` and `web/` both ways (a rule that does not exist, and a subrule letter
that does not exist under a rule that does). Advisory only.

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
python scripts/picker_sweep.py --set <CODE>   # supported cards whose cast/activation picker disagrees with the printed line — run over a measured set in Phase 3
python scripts/oracle_diff.py snapshot   # record every card's full compiled program (both manifest roles) before a change
python scripts/oracle_diff.py compare    # every card whose program moved since the snapshot; exit 1 if any did
python scripts/sim_fingerprint.py snapshot   # twelve seeded AI games' logs, before a change
python scripts/sim_fingerprint.py compare    # which of those games played differently; exit 1 if any did
python scripts/set_progress.py        # regenerate SET_PROGRESS.md; --refresh re-fetches Scryfall data
python scripts/check_all.py           # every CI guard check, in ci.yml's order (--freshness adds the tracker regenerations + a clean-tree check; --caps the size-guard headroom)
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
When you add a parse rule or a text-keyed engine behaviour, run `--check`; a
handler that implements trailing sentences of a clause declares them in
`HANDLER_CLAIMS`. Only the four event-keyed hook registries
(`ON_LEAVE_BATTLEFIELD`, `ON_SELF_RESOLVED`, `ON_SPELL_COUNTERED`,
`DRAW_STEP_MODIFIERS`) claim a whole card; a line hook claims its line.

To **launch and drive the running web app** (screenshots, scripted UI flow), use
the `/run-magic` skill at `.claude/skills/run-magic/` (with `playwright-cli`).
The board is canvas-rendered, so DOM selectors won't find cards; the skill
documents the working harness.

## The AI simulator

`run_ai_simulation` deals each seat a random *limited* deck from the pool it is
given (CR 100.2b: 40 cards, 17 lands; basics from the set or, if it prints none,
the manifest), seeded from the run's seed so a seed reproduces a run exactly.
`required_cards=` pins a card into every deck, for a regression test whose
subject must be in play. Each seat is also dealt a **sideboard** — the rest of
the pool its deck was built from (CR 100.4b), by name and with no randomness,
so the decks are byte-identical with or without it — which is what a Wish or
Ring of Ma'rûf brings in from outside the game.

**It plays the engine's turn, never a copy of it.** Every piece the loop once
open-coded went missing silently — untap/upkeep/draw, the main phase, combat,
the ending phase, mana, a step's prompt answered in a later step, extra turns,
a cycling ability left on the stack, casts from zones other than the hand,
priority — and each time the run completed with a non-zero interaction count
and no issues. So the loop calls the engine's stepping (`Game.start_turn`,
`start_next_turn`, `advance_combat_phase` through `engine/ai_combat.py`, the
`prompt_driver` and `priority_driver` seams), and every piece has an **honesty
count** in `SimulationReport` (`interaction_count`, `lands_played`,
`steps_left_owing`, `extra_turns_taken`, `modal_casts`, `casts_from_zones`,
`casts_in_response`, `casts_in_combat`, `casts_on_opponents_turn`,
`casts_before_blocks`, `activations_at_instant_speed`,
`activations_from_graveyard`, `refused_casts`, `refused_attacks`,
`rehearsals_raised`, `special_actions_taken`, `refused_special_actions`,
`cards_from_outside_game`, `face_down_casts`, `mulligans_taken`, the combat
counts). A run that
cast nothing exits 1. A new piece of the turn arrives with its count. CR 116
special actions are weighed in `engine/ai_special_actions.py`, before the
first combat.

- **Casting**: every cast site goes through `ai_actions.cast_announcement` (an
  AST test fails a site that spells a cast keyword itself), and every
  activation site through `ai_actions.activation_announcement` (an AST test
  holds the executors to it; the text-change words ride `ActivationAction`);
  the mode chooser
  loops `Game.announceable_modes`; `ai_weighed_cast.permitted_casts` is the one
  reader of what `cast_permissions` opens (`CastAction.from_zone`). Whether a
  card may be cast at instant speed is the engine's question
  (`cast_timing.casts_at_instant_speed`, never its type); when the AI wants
  to is `ai_policy._weighed_at_instant_speed_now` (a creature at another
  seat's end step, in response when its entry trigger names a spell, or in
  the declare-attackers step of an attack on its seat, to block with; before
  the blocks a seat that is not defending casts nothing).
- **Mana**: one exact matching (`ai_payment._PaymentPlanner`, also asked by the
  web's auto-tap) over lands, then tap-only non-land sources
  (`ai_valuation.planned_mana_yield`), then a mana ability whose cost taps
  other permanents (Birchlore Rangers,
  `ai_mana_sources.tap_cost_mana_activations`: the summoning-sick and least
  valuable first, never the permanent being paid for), then a
  self-sacrificing source only when the lands cannot pay and the spell is
  worth more. Of the sources that could pay, the matching spends those the
  seat's other wants need least (`mana_payment._sparing_choice` over
  `mana_wants.mana_wants`: wants paid together first, a held card's price
  before an ability that can wait), then those charging least beyond the
  tap (`engine/mana_drawbacks.py`: a painland's damage, a depletion counter,
  a land that will not untap, a trigger the tap fires — read off what the
  tap runs), with the pips matched to the chosen sources the cheapest way —
  the one preference every planner shares. A face-down spell's hidden card
  still wants its turn-up cost (`mana_wants.wants_brought_by`, CR 702.37e);
  a cast permanent its own abilities and an instant or sorcery leaving the
  hand its flashback (`wants_left_behind`, told by `mana_wants(cast=…)`),
  and a card castable from outside the hand under a permission its price.
  Floating mana pays generic through the same choice
  (`mana_payment.floating_units_for_generic`,
  colourless first where nothing is wanted), in `plan_payment` and the cast
  path's pool spend.
  `tap_planned_lands` binds every slot to its permanent before the first
  tap (a sacrifice renumbers).
- **Mulligans**: `engine/ai_mulligan.py` is the one keep decision and London
  bottom choice (CR 103.5: lands against the curve on the hand left after
  the bottom choice), asked by the simulator (`take_opening_mulligans`, CR
  103.5's rounds), the web pregame (`web/pregame.py`, by the same rounds)
  and the no-pregame deal (`session_store._begin_pregame`); the cards owed are
  `Game.mulligan_effective_count` (CR 103.5c's free first mulligan).
- **Priority**: `Game.offer_priority` gives it in CR 117.3b–d order, before each
  resolution and at a step's end on an empty stack; inert without a driver, at
  a table with an interactive seat, and in the untap step. The simulator and
  the web AI seat answer with one function, `ai_priority.act_at_priority`, in
  the moments `instant_speed_window` names: the cast chooser
  (`choose_combat_instant_cast_action`), then
  `choose_instant_speed_activation` (every non-mana ability of a permanent,
  each turned-down one set aside alone — with that ability of every
  identical permanent, `ai_policy._making_the_same_proposal`; an effect
  removing its own source is a rescue there), then the hand
  (`ai_hand_activations.choose_hand_activation_action(at_instant_speed=True)`:
  a cycle whose trigger pays now; a cycle whose trigger finds nothing is held
  at sorcery speed), then the graveyard chooser
  (`ai_graveyard_activations.choose_graveyard_activation_action`, alone in
  the seat's own upkeep), each through its own executor; the web AI's own
  upkeep stops for it when the seat holds a graveyard ability. In the
  declare-attackers step before the blocks (`ai_rehearsal.blocks_still_to_come`)
  each proposal is read again through the rest of that combat and made only
  where it adds a block that pays (`pays_before_the_blocks`), and a response
  there (`blocks_owed`) is read through that combat too; at instant speed the
  activation chooser weighs a tapped or summoning-sick permanent's abilities
  without {T}. The web AI seat acts only while it holds priority
  (`game_flow._ai_holds_priority`, CR 117.1a) and gives that answer
  everywhere but its own main phase with an empty stack; there its doors are
  the casts and the main-phase chooser (`ai_abilities.choose_activation_action`,
  asked only at sorcery speed, as the simulator's `_play_activations` asks it),
  each door once a step (`Session.ai_doors_spent`). Whatever any door puts on
  the stack goes round the table before it resolves (`_hand_priority_round`,
  CR 117.3c). In declare attackers the AI answers in the request that
  declared its attack (`_ai_declares_attackers`, CR 508.2), and in declare
  blockers once the blocks are in; a person with no legal block has the
  empty declaration made through the engine's `declare_blockers`
  (`_declares_for_a_person_who_cannot_block`). The rail's hold on the AI's
  turn is `_hold_at_flagged_step`: the AI declares and answers first,
  `seats._hold_priority_for_human` refuses while a declaration is owed
  (`_declaration_owed`) and hands priority past any other AI seat to the
  person, or to nobody once every player still in the game has passed.
- **Rehearsal**: `ai_rehearsal.rehearse` casts the candidate on a scratch copy
  (`ai_scratch_copy.scratch_copy`), resolves on defaults and reads
  `ai_standing.seat_standing` (life, cards, `permanent_worth` through the
  layers) right after and at the end of the turn — what lasts counts in full,
  what ends this turn a quarter. A cast that moves nothing, or leaves its
  caster worse off, is not proposed — nor is an ability, read with its {T} on
  both copies (`ai_abilities._moves_something`; a one-shot artifact keeps its
  flat score). A precombat cast whose good is gone by the end of the turn is
  rehearsed through the fight (`through_combat=True`), and such an ability
  that changes neither the attack nor the blocks
  (`Rehearsal.declarations_changed`) waits for the declare-blockers step;
  `_fight_the_combat` also finishes a combat already under way, from the step
  it is in. A rehearsal's own randomness is seeded from
  `ai_scratch_copy.public_counts` (turn, step and what every seat can count),
  never the log or a process-wide counter, and a seeded run in one process
  plays as in a fresh one (`tests/ai/test_kg4_determinism_rehearsal_seed.py`,
  `test_kg4_determinism_process_state.py`). An opponent's mode choice (CR
  700.2e) and a copy offer's reply are the prompts rehearsed inside a
  rehearsal, one level down (`ai_prompt_picks._one_level_deeper`), so a
  caster's rehearsal prices the answer it will get.
- **A copy sees what its seat sees** (`ai_scratch_copy.conceal_from`, CR
  400.2): libraries reshuffled and other hands redealt before anything is
  cast on it. Held by `tests/ai/test_ai_hidden_information_census.py`.
- **A rehearsal that raises is counted** (`ai_rehearsal.REHEARSALS_RAISED`), each
  distinct one is an issue, and the script exits 1 — otherwise it is a card
  silently never cast.
- One decision's no-cast baseline is read once (`with deliberating():`). A
  class-level spy on `Game` sees rehearsal copies too (which run the end step
  and the next turn's bookkeeping), so guard a spy with
  `ai_rehearsal.rehearsing()`. The AI is two families of modules: the
  choosers (`ai_policy` and the `ai_*` modules it fronts — among them
  `ai_prompt_picks`, what a seat nobody asks picks, by worth, for every
  prompt kind's default) and what a card or a position is worth
  (`ai_valuation`, `ai_standing` — the one measure of a seat's position —,
  `ai_rehearsal`, `ai_scratch_copy`, `ai_weighed_cast`, `ai_target_sides` and
  `ai_slot_sides` — one target's side, and each slot's of an announcement
  naming several —, `ai_prompt_readers`, `ai_compelled_blocks` — a fight's
  outcome, read by the blocks and by a trigger that compels a block — and
  `ai_combat_triggers`, what a creature's own attack or block trigger
  gambles, read by the declarations).

What the simulator does not do yet is in ROADMAP.

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

**Where a new template goes.** Both halves are layered, bottom to top, and the
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

**Parsing and compiling**

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
  (CR 702.6a), buyback (702.27a), kicker (702.33a), flashback (702.34). Every
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
  share a kind when only the question differs. **A condition needs a dispatcher,
  and parsing is not one**: `tests/engine/test_trigger_dispatchers.py` asks of
  every condition the pool produces whether anything outside the declaration
  tables names it. Where an event has no single call site (a draw, a life gain,
  a sacrifice), announce it on the state-based sweep (`mixins/game_ending.py`)
  over the record every path feeds.

**Executing effects**

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

**Replacement, prevention and the CR 616 process**

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
  whatever is answered). Events the registry spells separately but CR 616.1
  treats as one are one contention set (`apply_replacements(..., joined=)`):
  a death is `would_die` + `would_leave_battlefield` + `put_into_graveyard`; a
  discard's destination (`Game.discarded_card_destination`) is `discard` +
  `put_into_graveyard`. `tests/engine/test_kg4_asks_replacement_sites.py`
  classes every call site: asks, one registered effect, or declined.
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
  one-use `Shield`, `DamageRedirect` or `next_damage` rider spent on a chunk
  of an open dealing (`damage_redirects.dealing_moment`) opens a
  `shields.SharedNextTime` (`by_source`) there — open for that source's other
  chunks, closed by `simultaneous_damage.finish` — and a source-keyed shield's
  CR 615.5 additional effect runs once, with the total, as the dealing
  finishes (`prevention.shields._spend(afterward=)`). Two printed sentences
  are two instances (CR 608.2c); CR 615.7's numeric shields stay per point;
  the recipient-keyed template (Glarecaster) keeps `damage_moment`.
- `engine/destruction_events.py` — a destruction (CR 701.8) is one event,
  announced where it is decided (after indestructible, regeneration and a land's
  shield decline) and carrying its cause; a sacrifice or a state-based move to
  the graveyard is not one.

**Zones, draws, discards, mana**

- **Outside the game is not a zone** (CR 400.11): it is `PlayerState.sideboard`,
  read through `Game._outside_game_choices` (CR 407.3's ante bar, CR 903.11a's
  Commander bar) and moved by `Game.bring_card_from_outside_game`. A printed
  "card you own from outside the game" is `ObjectFilter.outside_the_game`,
  refused by name by every lowering not written for it (the Wishes, Ring of
  Ma'rûf).
- **Drawing is one seam.** `Game._draw_with_replacements`
  (`mixins/draws_and_discards.py`) is where a draw becomes
  a CR 614 event; `PlayerState.draw` underneath is banned outside it by
  `tests/engine/test_draw_seam.py` (only pregame draws are allowed). **Draws are
  made one at a time** (CR 616.1f): a prompt armed during a seat's draw is
  stamped (`replacement_choices.DRAW_OF`) and a later draw for it is parked
  (`Game.parked_draws`) until the answer. A doubler has one opportunity per
  event (CR 614.5), passed down as `exclude_sources`.
- **Discarding is one seam, and the event says who caused it.**
  `Game._discard_card` raises the `discard` event with `cause_seat`
  (`discard_cause_seat`), because "a spell or ability an opponent controls causes
  you to discard" is a question about the cause — and with `as_cost` when the
  discard pays a cost, because "if an effect causes you to discard" (Library
  of Leng) is one too. Every discard in the four cost-paying modules passes it
  (`tests/engine/test_discard_cost_seam.py`).
- **Every "put into a hand / a library"** goes through `Game.put_card_into_hand`
  (`mixins/zone_funnels.py`)
  / `put_card_into_library` (CR 903.9b has no single fire site).
- **Arriving in exile is one transition**: `Game.put_card_into_exile` returns
  the object the pile now holds — a new, equal one when some exile already
  holds that object (CR 400.7) — and the caller writes that down, so no exile
  holds one object twice and every record about an exiled card names one card.
  The Debug Menu's raw-state paste goes through it too
  (`tests/engine/test_exile_arrival_seam.py`). A graveyard has no such seam
  yet (ROADMAP).
- **An entry that asks waits** (CR 614.12a): `_enter_battlefield` performs the
  entry state with the permanent in no zone (`engine/entry_awaiting.py`;
  `controller_index_of` answers its seat), and at a table that holds for
  answers an entry that leaves a prompt open finishes at its last answer
  (`_finish_answered_entries`). A caller acts on the entered permanent through
  `then` (`tests/engine/test_kg3_entry_callers.py`). No default is stamped
  before a person's prompt (`_stamps_entry_default`), and a table that holds
  for nothing takes an entry prompt's default as it is armed
  (`Game._an_entry_nobody_waits_for`). **Permanents one event puts onto the
  battlefield enter together** (CR 603.6a): a road that enters several wraps
  them in `Game.entering_together()` — each newcomer is handed to the event
  as its call is made (`entry_awaiting.DeferredEntry`, its id stamped then),
  and when the event closes each one's entry state is performed in no zone in
  APNAP order of the seat it enters under (CR 101.4, 613.7m;
  `entry_awaiting.apnap_order`), then all are appended, recomputed once and
  announced with every newcomer present; an event whose newcomers ask waits
  as one, at the last answer any of them owes. An event can outlive a
  decision: a prompt armed inside it carries it (`entry_awaiting.ENTRY_EVENT`),
  its answer re-joins it, and it closes once its opener is done and no
  suspending prompt it stamped is owed — a resumable loop opens one with
  `Game.entering_together_through` (a multi-seat `may`, Show and Tell; a
  single-leaf `for_each`). `tests/engine/test_kg3_batch_roads.py` holds every
  entry made in a loop to the block. **What one event takes off the
  battlefield looks back at itself** (CR 603.10a, 704.3): each state-based
  pass (`_state_based_pass`), each destruction of several permanents and
  every loop removing several permanents for one action runs inside
  `Game.leaving_together()`; the death scans, the `events.LOOKS_BACK_IN_TIME`
  announcements and the transition's attachment and token-maker scans add
  `departed_in_this_event()`; an inline leaves-the-battlefield effect waits
  for the event (`after_this_departure`); a loop whose repetitions sacrifice
  at their answers (Fade Away, Tariff) holds them on its context
  (`sacrificing_together_through`, `OracleExecutionContext.sacrifice_batch`)
  for its last step. `tests/engine/test_kg4_together_departure_roads.py`
  holds every departing call made in a loop to the block.
- **Leaving a hand is one transition**: `Game.take_card_from_hand(owner, card)`
  removes exactly one copy by identity — every copy of a card in a hand is the
  same `CardDefinition` object. Guarded by `tests/engine/test_hand_removal_seam.py`.
- `engine/mana_payment.py` — whether a cost can be paid, and how. Casting and
  activating spend the *pool* (`_pay_mana_cost`, `mixins/stack/pool_payment.py`);
  an effect's "you may pay"
  gives no priority window, so it taps lands **for mana**, one at a time,
  through `Game._pay_planned_cost`. `plan_payment` is an exact matching over
  `Game.payment_lands`, told who is paying (`payer=`, so a CR 106.6 spending
  permission is planned; an AST guard fails a call with none) — and for a
  cost an effect collects, each land is planned as the units one tap of it
  adds (`board_payment.plan_over_land_units`, named by
  `payment_units_in_force`), so Ancient Tomb is {C}{C} of one source: every
  such cost's "can this be paid?" and its plan ask `Game.effect_payment_plan`.
  Which sources pay is `_sparing_choice`'s, against the payer's wants
  (`engine/mana_wants.py`, read only from what that seat can see) and then
  each source's price (`engine/mana_drawbacks.py`); `Game._pay_planned_cost`
  names both for the length of a payment (`payment_wants_in_force`,
  `payment_prices_in_force`). A cost is a symbol dict everywhere
  (`generic_cost(n)`).
- **What a mana ability is** is one predicate, `is_mana_ability` (CR 605.1a's
  four criteria, including "doesn't move a card to or from a library"), asked
  **fail-closed**: a zone-moving step beside an add-mana step is presumed to
  reach a library unless listed in `LIBRARY_SAFE_ZONE_KINDS`
  (`tests/engine/test_mana_ability_library_criterion.py`).
- **"Tapped for mana" is one event** (CR 106.12), `Game._land_tapped_for_mana`,
  on all three roads (explicit tap, a cost an effect collects, an activation).
  **A tap is the activation of one mana ability, and asking for a symbol picks
  it** (`board_payment.tap_alone_ability_for`); what a land can make is read per
  ability (`tap_alone_symbols`), never off the printed summary.
- `engine/board_payment.py` — `board_can_pay`: can this seat pay from its pool
  plus what its untapped lands would add (default — what an automatic payment
  asks), or plus every tap-alone source and every mana ability whose cost taps
  other permanents (`nonland_sources=True` — what a player is asked; the
  castable highlight passes it), or from the pool alone (`pool_only=True`).
- `engine/faces.py` — multi-face cards (CR 709). **A face is a card**: each half
  is derived once as its own `CardDefinition` carrying `face_of`, and that half
  compiles and goes on the stack; `whole_card` is CR 709.4 at the zone seams —
  and CR 708.9 for a face-down object, whose real card it returns. The
  whole card's program has **no instructions**, so a guard whose population is
  "each card, compiled" passes over every half without examining one — blind,
  not red. Text questions iterate `faces.compilation_units(pool)` /
  `oracle.compiled_units`; card questions keep the card. Held by
  `tests/engine/test_face_blind_guards.py`.
- `engine/face_down.py` — morph (CR 702.37) and face-down spells and
  permanents (CR 708). **While hidden, a face-down `StackItem.card` /
  `Permanent.card` *is* the blank 2/2** (`face_down_card`) and the real card
  rides on it as `CardDefinition.face_down_of` — substitution, chosen because
  `.card.name` is read everywhere and a hidden card must be fail-closed;
  `copies.FACE_DOWN_AS_IT_LEFT` keeps last-known information. Casting face
  down is an alternative cost; turning face up is the `turn_face_up` special
  action (CR 116.2b); effects turn a permanent down or up through
  `turn_face_down` / `turn_face_up(game, perm, how=…)`. The wire carries
  `face_down` and, to the controller alone, `hidden_card`; the AI's rehearsal
  copy conceals an opponent's face-down cards (CR 708.5). A non-mana morph
  cost is read and paid by the alternative-cost reader
  (`alternative_costs._read_cost_clauses`) the special action's offer names.
  **`game.log` is every seat's, so a line names only what every seat may
  see**: a card exiled face down, a private find or a card behind a
  face-down object is counted, not named (`linked_exile.exiled_cards_for_the_log`),
  and a face-down exile stays face down after its exiler leaves
  (`keep_face_down_after_departure`). Held by
  `tests/engine/test_hidden_cards_stay_out_of_the_log.py`.

**Casting and activating**

- `engine/cast_costs.py` — additional costs (CR 601.2b, f–h), including buyback
  and kicker as rewrites onto them. Whether a cost was paid rides
  `choices["additional_costs_paid"]`. "Kicked" has three readers at three times:
  a resolving spell (`was_kicked`), the permanent afterwards (`cast_costs.KICKED`
  / `KICKED_WITH`, since a card may print two kickers, CR 702.33b/f), and a cast
  trigger (`cast_kicked`); `target_was_kicked` asks it of the *targeted* spell.
  A permanent named to pay a cost pays it or the spell is not cast (CR 601.2h,
  `cast_additional_costs._named_cast_cost_refusal`). An alternative cost or
  waiver still owes
  what a tax adds (CR 118.9d, `Game.alternative_cost_mana`).
- `engine/flashback.py` — flashback (CR 702.34): a graveyard cast permission
  that requires an alternative cost (`CastPermission.cost`) and a destination as
  the card leaves the stack (`leaves_stack_to_exile`). `StackItem.flashback`
  says a cast was one; `has_flashback` takes the game (a grant counts).
- `engine/madness.py` — madness (CR 702.35): the keyword line compiles to a
  trigger (`keyword_lines.keyword_line_triggers`), the static half is a discard
  destination (`replacements/registry.DISCARD_INTO_EXILE`), and the trigger casts the
  card during its own resolution (CR 608.2g, `madness_cast`).
- `engine/refusals.py` — **a refused cast or activation is the actor's
  alone** (CR 733.1): `refuse(card_name, effect_kind, details)` is the only
  constructor of a refused result (a `Refusal`) and writes nothing; the four
  attempt wrappers take back what a refused attempt wrote
  (`take_back_refused_attempt`), safe because nothing is refused below the
  mana payment; a land's tap answers the same way
  (`tap_land_for_mana_or_refusal`). `game.log` is served whole to every
  seat. Held by `tests/engine/test_kg2_refusal_seam.py`.
- `engine/cast_prohibitions.py` — **may this card be cast at all** (CR 601.3):
  one ordered table behind `cast_prohibition(game, seat, card)`, asked by the
  cast path, the AI and the castable highlight. Each row says what it binds
  (CR 305.1: some bind land plays). `tests/engine/test_cast_prohibition_readers.py`
  fails a reader that calls a row's predicate itself.
- `engine/activation_prohibitions.py` — its CR 602.5 twin, behind
  `activation_prohibition`, asked by the activation path, the AI, the
  highlight, hand/graveyard activations and a land's tap
  (`Game.land_tap_prohibition`); refusals reach the client as
  `ability_denials`. Whether a non-mana cost can be paid is one question,
  `Game.unpayable_activation_cost` (CR 601.2h). The activation window's other
  pre-choice refusals are methods the wire asks too:
  `Game.loyalty_activation_refusal`, `tap_symbol_refusal` (CR 602.5a),
  `targeting_ban_activation_refusal`, `owner_only_activation_refusal`,
  `activation_limit_refusal`.
- `engine/cast_restrictions.py` / `engine/activation_restrictions.py` —
  text-keyed timing gates ("cast this spell only during…", "activate only if…").
  Ordered tables keyed by the printed clause, read by the path **and the support
  gate**, so a clause cannot be admitted and ignored. An unenforced restriction
  is an ability that works more often than the card allows — nothing crashes.
- `engine/cost_modifiers.py` (with `cost_modifier_lines.py` and
  `self_cost_modifiers.py`) — text-keyed cost taxes and reductions (CR 601.2f).
  Both directions are live; a generic reduction touches only generic mana, a
  coloured one spills its excess onto generic (CR 118.7a–d), and one that
  "reduces only the amount of colored mana you pay" (Edgewalker,
  `CostReduction.colored_only`) never spills — `reduce_cost`, in one place.
  Every price the wire shows is the one the cast charges:
  `cost_modifiers.cast_mana_charge` (increases, then reductions) is read by
  the hand badge, the castable highlight and `ways`.

**Targets**

- `engine/targeting.py` — what a spell or ability targets, derived from the
  *compiled program*: `derive_cast_spec` per card, `derive_activation_spec` per
  ability, one kind→spec table. Returns None rather than guessing; the guards in
  `tests/engine/test_targeting.py` / `test_activation_targeting.py` ratchet what
  still needs `legality.py`'s one text fallback. A modal spell is held to the
  mode it announces (`cast_targets.announced_mode_instructions`, read by both
  gates,
  the picker and `Game.announceable_modes`).
- **The gates, in `engine/legality.py` and the `legality_*.py` modules beside it
  (`_cast_gates`, `_abilities`, `_stack`, `_resolution`), all over the picker's
  own list**
  (`_enumerate_targets`), so the engine and the picker agree:
  - `no_legal_cast_target_refusal` — a spell that must target cannot be cast
    with nothing to name (CR 601.2c);
  - `cast_target_refusal` / `cast_stack_target_refusal` /
    `stray_stack_target_refusal` — a named target must be one the picker offers,
    before mana is spent; `exact_target_count` makes a printed count a count;
  - `activation_target_refusal` / `activation_target_obligation` — the same for
    an ability, before any cost is paid; a named *cost* permanent is paid as
    named (`_named_cost_refusal`);
  - `illegal_targets_refusal` (CR 608.2b) — every target illegal at resolution,
    the object leaves unresolved — and `blank_illegal_resolution_targets`, which
    blanks each illegal slot before any instruction runs. Asked of every object
    whose targets somebody chose: spells, activated abilities
    (`StackItem.activated`) and triggers with a chosen target
    (`StackItem.targets_chosen`).
  Both announcement and resolution ask the same predicate,
  `CastTargetGatesMixin._described_cast_target_slots`, and read targets by
  `permanent_id`, never index. A named player is a target like any other
  (`stack_targets.announcement_targets`).
- **A headless announcement that names no target is answered once, as it is
  announced** (`engine/bare_announcements.py`): the first entry of the picker's
  own list, stamped on the stack object as a named target is, so CR 608.2b
  re-checks it. A count, an X, a role announcement, an Aura's target and a
  division are refused rather than defaulted.
- **"A source of your choice" is chosen, not targeted** (CR 609.7a,
  `legality.spec_chooses_a_source`); a Circle's shield binds the source named
  (CR 615.8).
- Roles: "counter target spell and … target creature" is a roles announcement
  with a stack role (`targeting.role_is_stack`, `target_role_refs` with a
  `stack_index`); "target spell or permanent" is one slot in either zone; a
  slot list of printed targets is a count
  (`target_descriptions.slot_list_is_exact`); "up to N
  target cards from a single graveyard" is `target_descriptions.SINGLE_GRAVEYARD`; two
  players may be two roles (`choices["role_seats"]`). `Game.stack_target_seat`
  is the controller of a targeted spell ("its controller"). An "up to one"
  slot is an optional role (`target_roles.OPTIONAL_ROLE`); "any number of
  target opponents / players or planeswalkers" is a chain of optional roles
  (Wheel and Deal, Kaboom!), "for each opponent, … target permanent that
  player controls" one mandatory role per live opponent
  (`target_roles.per_opponent_roles`, Blatant Thievery), and an empty
  `target_role_refs` on a cast names no target;
  "that player controls" after a seat role is a role relation
  (`same_controller_role`, `role_seat_of`); a seat a slot cannot carry (a
  pile's owner, a count's opponent, an opponent beside a division) rides the
  seat field as `target_descriptions.ANNOUNCED_SEAT`. A narrowing known only
  at announcement (Phyrexian Splicer's chosen keyword; the creature type a
  spell announces before its targets, Aphetto Dredging —
  `engine/announced_creature_type.py`) is asked with the word the cast or
  activation announces and rides the stack object.
- `engine/target_requirements.py` — a target an opponent **must** choose (the
  Flagbearers): two gates over a whole announcement, deliberately not a
  narrowing in `_enumerate_targets` (which also serves resolution, retargets and
  copies). Held by `tests/engine/test_target_requirement_census.py`.
- `engine/stack_targets.py` — **which targets a stack object chose**
  (`chosen_targets(item)`) and how they may change (CR 115.7). Every way an
  object comes to have targets announces it once through
  `Game.announce_targets_chosen`; "becomes the target" triggers hang off it.
  A copy whose targets may be chosen anew is pushed unannounced and announced
  once they are decided (`Game.announce_copy_put_onto_stack`, CR 707.10c):
  becomes-the-target, "chooses targets" only where one moved, then put onto
  the stack. Every copy road offers them through one offer
  (`spell_copies.offer_new_targets`): a prompt for a seat somebody asks, the
  measured answer for one nobody asks. A spell judged from outside its own
  resolution (a retarget, a copy's new target, Grip of Chaos) is read as it
  is — its colour and text (`_enumerate_targets(stack_item=…)`,
  `object_colors.judging_targets_of`) — and a spell's one target may be
  another stack object (`targeting.single_spell_target`'s `"stack"` answer;
  a retargeting spell is a legal new target while it resolves).
  **The object a trigger is about is never its target**: a fire site records it
  as `StackItem.about_permanent_id` only for a line that names no target of
  its own (`trigger_utils.bound_event_object`), and the context builder hands
  it to the effect. The seat it is about ("that player": whose upkeep, who
  caused the discard, whom the attack was at, a delayed ability's bound
  player, the controller whose attachment or unblocked attacker it is) rides
  `StackItem.about_player_index`; `target_player_index` is a choice and only a
  choice, and the context builder hands the about seat over where nothing
  chose one (`tests/regressions/test_kg3_seats_about_player.py`). A player
  role in an activated ability is judged at resolution by whether that role
  still offers the player (`Game.role_seat_is_offered`, CR 608.2b).
  `target_permanent_id` is `None` or a list of ids on every
  holder (`game_types.check_target_ids` on each write), read through
  `target_ids` / `single_chosen_id` / `first_target_id`;
  `target_permanent_index` has the same one shape (`check_target_slots`;
  `target_slots` / `single_slot` / `first_slot`), is consumed into ids at
  the push (`_stamp_stack_targets`), so a stack object carries none, and
  every resolution context re-derives it from the ids
  (`bare_announcements.resolving_slots`). A graveyard target is its stamp
  (`target_graveyard_card`, None or a list, `check_graveyard_stamps`), read
  through `handlers/_targets.chosen_graveyard_slots`. The API keyword still
  takes a slot (SET_PLAYBOOK's Known gaps).

**Triggers**

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

**Prompts**

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

**Layers, control and the board**

- `engine/graveyard_statics.py` — **a static that functions from a graveyard**
  (CR 113.6b: the Incarnations, Riftstone Portal). A graveyard card whose
  static is stamped `functions_from: "graveyard"` is a source the lord
  recompute gathers beside the battlefield's, with the CR 613.7d timestamp of
  its arrival there (`engine/graveyard_order.py`, recorded only for such cards).
  **A new `PlayerState` or `Game` field is read by every `vars()` walker** — the
  rehearsal's `position_digest` and the AI censuses' board signatures: a field
  that moves on every resolution reads as a lasting change unless it is
  listed as bookkeeping (`ai_rehearsal._PLAYER_BOOKKEEPING`).
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
    (and `computed_types` likewise over `type_layer.TYPE_EFFECT_CHANNELS`).
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
    a new combat request field goes in `COMBAT_ID_FIELDS`.
- `engine/auras.py` — what an Aura's effect lines say and whether they are
  implemented (the support gate); its continuous effects while attached are
  `aura_grants.py` and `aura_restrictions.py`. Use `attach_aura` / `detach_aura`
  (`aura_attachment.py`). The templates read "enchanted" and "equipped"
  alike (CR 301.5f).
- `engine/equipment.py` — Equipment (CR 301.5), equip as a rewrite, attach
  (CR 701.3); `equip_refusal` is the one legality predicate, also asked by the
  CR 704.5n sweep. An Equipment is supported only if its equip ability compiles
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

**Turn structure**

- `engine/phases/` — one mixin per phase and step (CR 500–514), composed onto
  `Game`; phase/step turn-based logic goes here. The declaration steps have
  `attack_legality.py` (CR 508.1c), `attack_requirements.py` (CR 508.1d),
  `block_legality.py` (CR 509.1b) and `block_requirements.py` (CR 509.1c) —
  each requirements module the requirement list and the maximisation that
  judges a declaration and the AI's proposal — and `block_triggers.py` beside
  them, and the combat damage step has `combat_damage_assignment.py` (CR
  510.1) beside it.
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

`engine/oracle.py` is the compiler: the per-card cache and the gates every card
passes. It tokenizes, rewrites lines (`line_rewrites`), classifies them as
keyword/triggered/activated/static (`line_classification`, `ability_lines`,
`keyword_lines`) and delegates effect clauses to `engine.grammar`, then to the
card hooks (`front_ends`). `engine/oracle_types.py` holds shared dataclasses and
imports nothing from the engine at run time (`ActivatedAbilityCost` lives in
`engine/activated_ability_cost.py`, named under `TYPE_CHECKING`).

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

`web/app.py` is the FastAPI app (`/api/...` routes + static UI in `web/static/`)
and **nothing else** — the one place a route is declared. Everything else is a
module beside it, **layered**: `web/__init__.py` declares the order in `LAYERS`
and a module may import only from an earlier one
(`tests/ui/test_web_layering.py`, which also catches function-level imports).

| Module | Job |
| --- | --- |
| `runtime.py` | the card pool, the three store instances, session lookup, the per-session request lock |
| `events.py` | server-sent events — the one thing the API *pushes* |
| `seats.py` | seat kind, who has lost, whether to hold priority |
| `offers.py` | what a viewer's object offers right now as the engine answers it: a tap's mana, each ability's mana and refusal, a cast's mana colour, text-change words, payable X |
| `serialization.py` | engine object → client JSON, one function per kind |
| `catalog.py` | the pool and decks as the client browses them |
| `verification_report.py` | the verification tracker's read side |
| `pregame.py` | coin flip and mulligans |
| `turn_steps.py` | the beginning phase (turn 1's included, `_settle_pregame`) and the turn's boundaries |
| `combat_prompts.py` | banding / multiblock / pile-division assignments |
| `game_flow.py` | priority, phase advancement, AI stepping |
| `state_view.py` | the whole-state payload a client polls |
| `debug_actions.py` | Debug-Menu board manipulation, raw-state injection |
| `payment_plan.py` | the auto-tap: which permanents pay for an action, planned and tapped by the server |
| `action_helpers.py`, `action_*.py` | the shared cast plumbing, then one module of registered handlers per group of `ActionKind`s; a prompt's answer in `action_prompt_cards.py`, `action_prompt_board.py` or `action_prompt_values.py`, split as the renderers are |
| `actions.py` | the one dispatch over `ActionKind` |
| `prompt_registry.py` | `PromptContext` and the renderer table |
| `prompt_cards.py`, `prompt_board.py`, `prompt_values.py` | one renderer per prompt kind, by what the prompt is answered with (cards; permanents, players or spells; a value) |
| `prompts.py` | the three loops over every prompt (below) |

The card pool is `CARD_PATHS` from `engine.card_loader.manifest_set_paths()`,
loaded once at startup into `CARD_CATALOG` (`runtime.py`). **Adding a set means
ingesting it and moving one manifest entry** — the web app, the fixtures and the
scripts all read that registry. State lives in in-memory stores
(`session_store.py`, which takes the loaded catalog; `deck_store.py`, including
Moxfield import; `verification_store.py`). Game actions funnel through one
endpoint, `POST /api/sessions/{id}/action`, dispatched by the `ActionKind`
literal in `web/schemas.py`. A session's routes run one at a time and a payload
is encoded as one moment (`web.runtime.one_request_at_a_time`). Session `mode` is
one of `human_vs_ai`, `ai_vs_ai`, `human_vs_human`, `free_for_all` (3–4 seats,
configured per seat via `seats`).

`web/prompts.py` and the renderer modules beside it own every prompt's
presentation: one renderer per kind plus the three loops that render the prompts a viewer may see, refuse the actions a
pending prompt blocks, and answer AI-owned prompts with their defaults — all
reading the registry, so a new prompt is covered by construction. **The client
keeps no copy of that registry**: the payload carries `waiting_on_prompt`, which
the auto-pass reads. AI-owned prompts are answered before **and after** an
action's handler (a human's answer can arm one), and **an AI step never advances
a human's turn** (`_advance_ai_turn` returns unless the active seat is an AI,
nor in a step a person holds priority in).

**What a card can do right now is sent, not re-derived by the client**: `ways`
(each way a card may be cast from a permission-opened zone, its price, whether
payable now), `ability_denials` (the activation path's pre-choice refusals
per ability, {T} included — `web/offers._ability_denial`), `ability_mana`
(each mana ability's symbols on this board — what the board, a record or the
cost decides included, `web/offers._decided_ability_mana`; whether a colour
is chosen; a mixed split's `combination` and an "or" of quantities'
`alternatives`, both answered on `mana_combination` —
`engine/mana_combination.py`; `symbols_by_cost` where the cost's permanent
decides; null for an ability that adds no mana), `ability_text_change` and a
cast's `text_change` (the words a text change announces), `x_payable` /
`ability_x_payable` (`{pool, board, colors}`: the payable X as the cast or
activation path prices it), `cast_mana`, a card's `cost_before_modifiers`
beside its charged price, `prompt_owed_by`
(which seat owes the decision holding the game — the pending-choice queue's,
else a session-held one, `state_view._SESSION_DECISIONS`),
`abilities_lost`, `taps_for_mana`, `produced_mana`, a payment prompt's `payable`
(a "pay" that cannot be collected is refused with the prompt kept, never read as
a decline), a search's `min_picks`, a graveyard ability's `target_spec`,
`target_spec.cost_offers` (every applicable alternative cost by
`alternative_index`, which the cast answers with `alternative_cost_index`, CR
118.9a), a castable spell's `mana_combination` when it makes mana in any
combination (`count`, or `count_by_cost` per permanent that could pay its
cost — `mana_combination.cast_split_offer`), the active seat's
`combat.attack_requirements` and a defending seat's `combat.block_requirements`
(each with `most_obeyable`); and while a permanent's "as it enters" choice is
owed, that permanent listed in its controller's `battlefield` as arriving
(`serialization._serialize_arriving`, `entering: true`; the engine has it in
no zone until the answer, CR 614.12a), as are an open entry event's puts —
to their controller alone (CR 101.4a). Every request body the client builds
is held to its route: presence (`tests/ui/test_kg_client_request_schemas.py`),
each value's type (`test_kg3_wire_request_shapes.py`), and what an armed
prompt's handler takes (`test_kg3_wire_prompt_state_bodies.py`). **Every
automatic sender in the client re-asks by fetching the state when its
in-flight flag clears** — one scheduled re-ask (`retryAutoAdvanceAfterFlight`)
serves every sender, delayed only while the state key stays unchanged — and
forgets the state key it last sent from when a game ends (a rematch can open
on the same turn, step and log length). A state is newer by the payload's
`revision` (one more per announced change, `web/events`), never by the log's
length, and each event stream is handed its events thread-safely,
coalesced with their reasons. The client does not plan taps: a
click on a castable card is answered by `web/payment_plan.py`
(`POST …/payment_plan` previews; `auto_tap` on the action taps), and every
paying action is previewed before it is sent (`previewPayingAction`), so a
pool that cannot pay opens the auto-tap dialog without a refused request.

The board UI is **canvas-rendered** (`web/static/battlefield-canvas.js`). **A
client change is not done until it has been clicked in a browser** — a
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
