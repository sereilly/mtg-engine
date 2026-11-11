---
paths:
  - "tests/**"
  - "pytest.ini"
  - "engine/program_store.py"
  - "scripts/rules_progress.py"
  - "scripts/rules_gaps.py"
---

# Running and writing tests

Part of `CLAUDE.md`, kept here so it loads when you open a file it
describes (the `paths` above). The root file's rule for editing applies,
and you can open this file directly whenever its subject is yours.

**The pool compiles once per engine, not once per process**
(`engine/program_store.py`). Each test process reads the compile at configure
time — before collection, which compiles the pool, since `tests/helpers.py`
imports `web.app` — from a store in `.program_store/`, named by a hash of every
`engine/**/*.py`, `data/` and `cards/*.json` file, so any edit to the engine — a
comment included — names a new store and the old one is never opened. The
first worker of a folder or whole-suite run to find none builds it in a
subprocess that imports only the engine (~15 s) and the rest wait for it; a run
naming files builds one only when the web layer's import is about to compile the
pool anyway (`tests/passes.py`'s `_read_before_the_pool_compiles`), so the first
run after an engine edit pays the build and the next reads it (one per-set
file: 19 s, then 3), while a guard file that never imports the web layer builds
nothing. **A script that walks the whole
pool reads it too**, calling `program_store.warm()` before its first compile
(the first to find none builds it): `regen.sh`'s five pool walkers, which
compiled the pool five times after every merge, `oracle_diff`, and
`support_report`/`picker_sweep` over the whole pool. **So does the web
server**, as `web/runtime.py` loads the catalog: it starts in ~2 s, ~15 s on the
first start after an engine edit. Never on a process's first compile miss — a
probe that patches a production would be handed what the unpatched compiler
wrote; one that patches before importing the web layer sets
`MTG_NO_PROGRAM_STORE=1`. In a test process `warm()` asks the test runner,
which read the store at configure time.
`tests/engine/test_program_store.py` holds every script the merge path runs to
reading it or naming why it walks no pool.
Reading takes under a second. Stored programs go into
`_compile_card_oracle`'s own `lru_cache`, so `clear_compilation_caches()` clears
them too. An engine module that starts reading a file adds its folder to
`program_store.INPUTS` (`tests/engine/test_program_store.py` fails until it
does). `MTG_NO_PROGRAM_STORE=1` turns the store off.

**The runner holds itself to the machine's memory** (`tests/memory_guard.py`,
hooked in by `tests/conftest.py`): `-n N` and `-n auto` run as at most what
free memory holds — a worker peaks near 1.5 GB, and 4 GB is kept free
(`MTG_PYTEST_NO_MEMORY_CAP=1` overrides) — and a `--collect-only` session, which
is what an IDE's test discovery is, waits for the one before it in the same
checkout. `load_cards` is cached per file version, so the test modules that load
the pool at import share one copy (each held its own, 5 GB a process, until
2026-10-31). An exit code 3 or 137 with no `FAILED` line is a worker that died,
not a red tree — re-run with fewer workers. Never pipe pytest through
`tail`/`head`: the pipe replaces its exit code.

**Every run records its tests' times** (`tests/passes.py`): setup + call +
teardown by node id, merged into `.test_timings.json` at the tree's root
(gitignored), so the last full pass's numbers stand until a run re-times those
tests. `scripts/tests_for_diff.py` reads them (this tree's over the main
checkout's) to say what a list of files costs, quick and full apart, before
it starts; `--run` passes `--quick`, which keeps the quick pass in the files
named. **`MTG_PROMOTE=<CODE>`** runs any test with a measured set read as
shipped (`engine/card_loader.py`) — the way to run a census over
`load_catalog()` against the set you are implementing; the run's header says
so, and the shipped-pool guards are expected red under it.

Tests are organized by subject — put new tests in the matching subfolder:
`tests/ai/` (AI policy/simulator), `tests/ui/` (web API + frontend/end-to-end),
`tests/engine/` (loader, oracle compiler, parsing, dispatch internals, the
convention guards), `tests/rules/` (Comprehensive Rules sections and the casual
variants — ante, Commander, Brawl), `tests/sets/` (per-card tests for a specific
set), `tests/regressions/` (in-game bug regressions). Shared fixtures live in
`tests/conftest.py` and helpers in `tests/helpers.py`. A test that reads the
board after something resolves calls `tests.helpers.settle(game)` (prompts
answered by default or by `answers=`, the stack resolved through
`resolve_next_object`, state-based actions performed, until nothing moves;
`defaults=False` returns the first owed prompt); `resolve_stack` is only the
safe swap for a bare drain loop. A combat is walked with
`drive_combat(game, through=...)`, whose default leaves the end of combat step
so combat is over (CR 511.3); the step's "at end of combat" triggers fire as
it begins (CR 511.2), so every stop from the arrival on has resolved them.
Both are held by
`tests/engine/test_settle_and_drive_combat_helpers.py`. A web test that means
"seat 0 acts first" on a table created without the pregame calls
`tests.helpers.seat_plays_first(sid)`: that deal plays first whoever its flip
names. A web test whose games must be one per seed calls `random.seed(seed)`
before it creates the session: a session's seed builds its decks and flips
its coin, and every shuffle and random pick after that reads the module RNG
where the tests before it left it (SET_PLAYBOOK's Known gaps; kg5's
`ai_vs_ai` census was green in a meeting run and red in a folder run).

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
