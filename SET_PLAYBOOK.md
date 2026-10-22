# Set implementation playbook

**Hand-written, not generated.** Every other ALL-CAPS file at this level is a
tracker a script rewrites; this one is maintained by whoever just finished a
set, in Phase 6. Read it as current truth. How each rule was learned is in
`SET_RETROSPECTIVES.md` and in the commits.

A set's lifecycle is `absent → measured → sets` in `cards/manifest.json`.
"Done" means the entry **moves** from `measured` to `sets` — the
machine-checked claim that every card in it is supported
(`tests/engine/test_front_end_safety.py`, `tests/engine/test_card_format.py`;
the role split is guarded by `tests/engine/test_manifest_roles.py`). CLAUDE.md's
"The manifest" says why the roles exist. **A set is not finished until Phase 6
has run.**

This playbook owns *sequence and gates* — which steps, in what order, with
what exit criteria — and how a parallel round is integrated. The per-card
recipe is `engine/ARCHITECTURE.md`'s ("Adding support for a new card"), test
placement is `tests/sets/README.md`'s, script invocations are CLAUDE.md's
Commands section, the integrator's scripts are `scripts/integration/` (its
README has the table) and the work queue is `GRAMMAR_COVERAGE.md`'s. No number
a tracker owns appears here, so finishing a set changes this file only where
the *process* changed.

Contents: **Integration** (agents, briefing, the chain, silent merge hazards,
per-set test files, module splits) · **Phase 0 – Phase 6** · **Known gaps**.

## Integration

A set runs as **waves** of parallel **groups**, each an agent in its own git
worktree on its own branch. The **integrator** briefs them, merges their
branches one at a time and gates the result. Analysis and authorship fan out;
integration is serial. Integration, not budget, is the limit: expect about one
integrator-hour per wave-hour, spent on merges rather than on cards. The
scripts named below are in `scripts/integration/`, run from Git Bash with
`ROUND` set (a set's code in lower case).

### Agents and the machine

- **Make each worktree inside the repo**:
  `git worktree add .worktrees/<round>-<group> -b <round>/<group>` (agents
  cannot write outside the project root), and run its tests through the main
  checkout's venv by absolute path. Where worktrees are unavailable, fan out
  *design* instead: each agent returns an exact spec (file, function, current
  code, replacement, tests) and one applier lands them in sequence.
- **At most five agents at once.** Hold the rest of a wave and start each as a
  slot frees; a wave-2 group may take a slot while wave 1 finishes. *Why:* the
  machine has 16 GB and a suite worker peaks near 2 GB, and the account's rate
  limit stops agents mid-edit.
- **An agent never runs the full suite.** It runs the files it wrote, every
  test file it edited, and the files that cover the modules it touched (grep
  `tests/` for the module names — a guard sits far from its code), serially or
  at `-n 2`, and lists them in its report. The full suite is the integrator's,
  one at a time: `-n 8` when the machine is yours, `-n 4` while agents run,
  never `-n auto` (killed for memory).
- **A worker killed for memory is not a red test.** It reads as
  `INTERNALERROR … KeyError: <WorkerController gw1>`, as "Different tests were
  collected", as a run that stops thousands of tests short, as a bare
  `MemoryError` in unrelated guards, or as exit 3/137 with no `FAILED` line.
  Re-run smaller. Read free memory before starting anything beside a gate and
  stop your own run below a gigabyte free — a starved process does not fail, it
  stops making progress.
- **Never pipe a gate.** `pytest … | tail` reports `tail`'s exit code, and a
  gate read that way has passed with tests failing. Redirect to a file, read
  `$?`, grep `FAILED`.
- **Start long jobs as tracked background tasks with absolute paths, and read
  the exit file before trusting the notification.** A shell `&` inside a
  foreground command finishes unnoticed; a `cd` followed by a relative redirect
  runs nothing and reports a blank exit code.
- **A stopped background task is not a stopped process**: the stop kills the
  tool's shell, not the Python under it. Look for survivors after a stop, write
  a long loop inline rather than in a script, and never edit a script something
  may still be reading.
- **Never edit a worktree while a test run is reading it.** The run's result
  would describe no tree that existed. Stage the next merge on a new link.
- **Never `git stash`** — the stash is shared across worktrees, and agents have
  popped a sibling's work into their own tree. Commit instead.
- **Give each group a private scratch folder**
  (`.worktrees/scratch/<round>/<group>/`); a shared one gets overwritten.
- **Commit as each item lands, and before any long run on a commit.** An
  expired session stops every agent at once, and the ones with commits resume
  cheaply. Work in an exported tree or left uncommitted is invisible to a merge
  (a shipped defect once sat in a worktree for eleven days).
- **Each browser-driving agent gets a port and a session name**
  (`playwright-cli -s=<group> …`). Use one yourself, and never `close-all`: it
  closes everybody's browser.
- **A stopped or dead agent resumes by message.** Read `status.sh`, its branch,
  its worktree's diff, its newest scratch files and its last words, then tell it
  exactly what state you see and what is left. Only if that fails, finish its
  verification yourself — never merge work nobody watched run. What a stopped
  agent measured is a brief, and it expires: re-measure on the merged tree
  before building on it.

### Briefing

Assemble a brief from the instruments (Phase 1's census, `card_table.py`,
`gen_cards.py`, `furthest.py`), not from memory. Every brief says:

- **A name-keyed hook is the last resort** — every wave, explicitly. The brief
  does that work, not the reviewer.
- **Report what this brief got wrong** (expect about a third), **which
  already-supported cards your family silently mis-plays**, **any red on your
  base beyond the ones named here**, and **each decline as a list of named
  parts**. The reds are the earliest gate there is: fix them on the link the day
  the first group reports one. A decline with its parts named is the next
  wave's brief, and other groups often build those parts as a side effect;
  "too complex" is answerable by nobody.
- **Which pieces other groups have already built**, or the wave rebuilds them.
- **Measure before building, and a measured decline is an honest outcome.** That
  sentence is what gets the riskiest item landed.
- The per-set test section and module headroom (below), the Rock Hydra test
  (Phase 3), and the ingest's yield table where it names the group's cards
  (Phase 1).

And when writing one:

- **A refusal site is a work-list entry, not a diagnosis.** It names where the
  parser stopped, not what is absent, and it usually over-states: probe the
  sentence before believing it, and treat "this is only a probe artifact" as the
  claim most likely to cost a card. When a brief would say "widen the
  whitelist", check first whether the whitelist is consulted at all — it may be
  a fork of the shared reader.
- **Verify an inherited diagnosis as part of the round**, not as a preamble to
  it; measuring one has caught defects the briefed fix would have introduced.
- **Require a census to disbelieve its own author.** A suspicion that survives
  its census is worth writing down; one that does not is worth the census.
- **A ruling** (how a card is played, as against what a rule says) **carries its
  source** — Scryfall's per-card `rulings_uri` — or is not stated. Rulings are
  not in `MagicCompRules.txt`, and two briefs have stated a wrong one from
  memory. Check every rule a brief states against the CR as well.
- **Grep ROADMAP for the mechanism before briefing the group that changes it**,
  and paste what it says: a recorded precondition belongs to whoever removes
  the thing it waits on.
- **Dedupe shapes before the groups exist.** Read the sentences for a shared
  shape and put one shape in one group; two mechanisms reconciled at a merge
  cost more.
- **A wire change and its client are one unit.** Give that group the client, or
  put the client half in the same wave's plan before the first agent starts;
  until it lands, the merge message says the feature is not finished.
- **An agent that edits `web/static/` drives the change in a browser before it
  reports** — both directions, the state API read after each click — and says
  what it did not drive. A comment saying what the code "then" does is a claim
  to drive. Prefer one client group holding every prompt the reports say a
  person could not answer over every group making one client change.
- **Brief wave 2 from wave 1's reports as they arrive**, on the link holding the
  files it will touch, and extend a running group by message — census path,
  parts, and the names a sibling already took, so the two union rather than
  fork. File the measured-and-declined pile **by subject**, not by reporting
  group: five reports each holding a piece become one brief.
- **Verify a report's correction before relaying it.** A report is model output
  about code, and the code is one grep away.
- **Brief a speed group from a profile of two sets of different shape**, with
  the numbers and not a design: the call counts reproduce, a proposed design
  usually does not.

### The chain: merging and gating

- **Every cumulative tree is tested before `main` rests on it.** Stage each
  merge in its own link worktree on top of the previous link (`chain_stage.sh`),
  commit it with its trackers regenerated (`chain_commit.sh`, which runs
  `regen.sh` — never an `--accept`), and fast-forward `main` only to a link
  whose full gate was read green. A red link is fixed in that link, then the
  links above it are rebuilt or merged forward.
- **Before staging a branch, `git status` its worktree and list its scratch for
  anything newer than its last commit** (`chain_stage.sh` refuses a dirty
  tree). Uncommitted work is a decision for the integrator that `git merge`
  never shows.
- **The gate between merges is the meeting-point run** (`meeting.sh <tree>
  <tag>`): every test file any merged branch added or edited, the set's own
  files, the ingest's yield (`yield.txt`), every file a full gate has surprised
  you with (`surprises.txt`) and the structural guards. Never a hand-picked
  list; the script refuses a path that does not exist, because xdist reports a
  typo as "no tests ran". Add by hand the censuses of any seam two merged
  branches both touched and every ratchet either side lowered — an instrument is
  code that meets other code at a merge.
- **The full gate** (`gate.sh <tree> <tag>`, read with `gate_report.sh`:
  `oracle_diff`, the duplicate and missing-name scans, the whole suite,
  `check_all`, the support report) **runs at each wave's close and on the
  promotion commit.** Whatever it finds that the meeting run did not goes into
  `surprises.txt` that day. A branch arriving after the wave's gate has started
  needs no gate of its own when the promotion's is next.
- **A merge commit claims only what was verified when it was made** — the
  conflict resolutions, `oracle_diff` over that merge, the scans, the meeting
  run — and says where the full gate's result will be recorded.
- **The integrator's own commit between merges gets the gate a merge gets.**
  Nothing a group is asked to do is optional for the integrator.
- **Bisect a red on a cumulative tree by running the failing test on each link
  beneath it** — seconds, not a suite.
- **Do not re-run a red gate and take the green.** A test that fails in one
  full run and passes alone is a finding with a schedule — two tests, one
  worker, one order — and is read the day it is reported, including when it
  failed in a group's batch. When someone can name the mechanism, reproduce
  the order in ten lines (fill the memo, clear the cache, call the test). When
  nobody can, ask the process: a scratch `pytest_runtest_teardown` plugin
  replaying the failing scenario after every test names the polluter in one
  suite (it found the `id()`-keyed memos).
- **Resolve a conflict with a script that asserts what it read**
  (`resolve_both.py`, `merge_blocks.py`): bytes in and out, line endings kept,
  every conflict region asserted to be the one that was read. A replayable
  resolution can be tested before it is the merge, re-run when the merge is
  re-staged, and reviewed as intent.
- **When two groups are briefed to edit one function, rehearse their merge in a
  throwaway worktree and run their tests there.** The defect that matters can
  sit in a file with no conflict (one branch renamed a local, the other read the
  old name).
- **Once the chain is on `main`, run `dup_ideas.py <round-base>` and tidy the
  chain.** Remove a worktree only after checking both that its branch is an
  ancestor of `main` *and* that it holds no modified or untracked file — being
  an ancestor is necessary, not sufficient. Keep the scratch folder; the next
  wave's briefs cite it.
- **An upstream that ships while a round runs is merged like a branch, by
  intent.** Where both sides did the same work, keep one and move the other's
  callers onto it; where one replaced what the other extended, keep the
  replacement and port the extension; name each choice in the merge message.
  Expect reds on the resolved tree and read each as a meeting, not a regression
  — most are backwards checks a second layer now satisfies.
- **A no-behaviour-change contract is checked on the tree it lands on.**
  Snapshot `sim_fingerprint.py` on `main` before the merge and require 0 moved
  after it; after touching a fast path, run the seeded games under
  `fast_paths.CHECKING` (`checked_sim.py`) on the merged tree.

### Silent merge hazards

A clean textual merge is not a clean merge, and each of these passes the suite
on at least one resolution.

- **Taking either side passes the suite** when both branches deleted a different
  entry at one spot (git shows each side "keeping" the other's deletion) or both
  rewrote one function, each with a fix the other lacks. Read both sides for
  what each *adds*, and union unless they contradict.
- **Resolve the conflict, never the file.** A whole-file `--theirs`/`--ours`
  drops hunks that were never in dispute, including a third branch's clean
  merge into the same file. `git checkout -m <file>` and go hunk by hunk.
- **When two methods conflict through identical middle lines, rebuild the
  region from each side's whole functions**; a hunk-wise union splices one
  signature onto the other's body.
- **A union can break an `if`/`elif` chain, or nest one `if` inside another**
  (two regions ending on a shared `return` become an AND where the rule is an
  OR). When both sides add an arm, check what the arms are arms of and what
  follows the closing marker.
- **Two definitions of one name merge clean, and Python takes the later**
  (ROADMAP idiom 25): `dups.py` on every merge. When one branch *moves* a class
  another *adds* to, carrying the fields across is not carrying the method that
  emits them (idiom 26).
- **One name meaning two things**: a new definition shadowing an identically
  named import silently disables the import's users. Sweep for names defined in
  two modules and check whether any one file imports both.
- **Two names meaning one thing**: one fact under two field names, one printed
  clause built as two mechanisms. `dup_ideas.py` after each wave and a read of
  the merged diff, because a duplicate idea need not share a name. Reconcile at
  the merge only when the answer is not a rules reading; otherwise hand both to
  a wave-2 group by name.
- **Two fixes of one bug: take the one that subsumes the other, and prove it
  with the losing branch's tests.** When one is a hand-written list and the
  other derives the set, take the derivation and carry the list's additions
  onto it — the list was the bug.
- **One channel carrying two value shapes** (a list from one producer and a bare
  id from another; ids from one and live objects from another). Settle the
  channel's arity **and** its element type in one round, at one reader, never by
  another local normalisation.
- **A semantic collision** — one branch splits a kind, another's table assumed
  one — merges textually clean; only running the tests between merges finds it.
- **A pool-wide guard from one branch turns red on a card another branch
  touched.** Drive the card before touching either side. If the guard asserted
  more than its invariant, restate the invariant with the engine's own predicate
  — never add the card's name to an allow-list. If the guard is right, convert
  the sibling's code.
- **A gate that trusts a list makes the list load-bearing.** A sweep holding a
  gate to its source agrees by construction; add one holding the source to what
  acts (turn the gate off, resolve, name anything the handler acted on that the
  picker did not offer).
- **A log line is an interface.** Before changing a string the engine logs, grep
  the tests for its smallest distinctive token, and read every `not` you find as
  a guard that will pass for ever once the string moves.
- **A seeded simulation test asserts its subject was exercised, never how
  often.** A count over a seeded game is a statement about every other card in
  a set still being implemented; the floor is one.
- **Read a new mechanism for what it lets the code know.** Ask at the merge what
  it can see that it should not (a rehearsal copy holding the opponent's real
  hand) and what can now fail without anybody being told (an exception
  swallowed into "cannot be weighed"); answer the second with an honesty count.

### Per-set test files

- **Open the set's per-set test files on `main` before the fan-out, one marked
  section per group** (`open_test_files.py CODE <group>…`), each group's imports
  at the top of its own section. Every per-set conflict is then two appends and
  the union is mechanical. A group's tests in `tests/rules/` go in a file of its
  own.
- **`merge_blocks.py` resolves those**: it asserts both sides start with the
  merge base byte for byte, writes base + ours-tail + theirs-tail, and checks
  that every non-blank line of the branch's section survived. When the assertion
  fires because the shared prefix changed (a group edited the header, or the
  integrator edited an earlier group's section mid-wave), union by hunk instead,
  with the same survival check. Never accept a union git presented as two
  regions: two helpers ending in the same lines are matched as common context,
  and a naive union splices one body onto the other's signature. After any hand
  resolution, run the survival check over every section of every per-set file
  the wave touched.
- **A per-set file over its cap at integration is split by moving whole
  sections** to a `_later_groups` sibling — assert every moved line is in both
  the old text and the new file, and leave the marker pairs behind so a branch
  still in flight merges against unchanged context. Later groups append to
  whichever file has room.

### Module splits

- **No module in `engine/`, `web/` or `scripts/` passes 2,000 lines**
  (`tests/engine/test_module_size.py`; per-set test files have their own
  2,600), and **the band is the last 200** (`check_all --caps`, or
  `headroom.py` alone). Never raise a cap: it is the signal that a module
  stopped absorbing new work by subject. A cap crossed at integration by two
  groups' additions summed is the integrator's split, taken then and there.
- **A split leaves every module it touches at about 1,500 lines or less**, or it
  has bought one set.
- **A split is code motion, proven by two differentials**: `oracle_diff.py`
  0/0/0 and `sim_fingerprint.py compare` 0 moved. Run `oracle_diff compare`
  before the suite; it fails in seconds where the suite scatters failures.
- **Six scans, and only one of them fails at import time:**
  1. *Dead imports* (`tests/engine/test_import_hygiene.py`) in the module code
     moved **out of** as well as into — a moved function leaves its imports
     behind. A function-level import of a name the module already imports at
     the top is a shadow that hides whether the top-level binding is still
     used: delete it on sight.
  2. *Missing names* (`missing_names.py`), **before** the suite: a `NameError`
     in a function body waits for its line, so a smoke import passes. String
     annotations under `from __future__ import annotations` read as false
     positives.
  3. *Duplicate definitions across the package* (`dups.py`, and a grep of
     top-level `def`/`class` names): a split that copied instead of moving
     leaves a dead copy that imports clean.
     `test_no_module_defines_the_same_name_twice` looks within one module only.
  4. *Anything keyed on a file path* — `test_cr_citation_subjects.py`'s
     `REVIEWED` is keyed by path and number, so a moved block breaks it both
     ways at once.
  5. *Execution order of module-level code*: a name imported by a later block
     satisfies "is it imported?" and still raises at import or collection.
  6. *What reads the module by name*: grep the tests for its bare name. A guard
     with a hand-written list of modules stops reading whatever moves out.
- **A category names the migration family a kind belongs to, never the module
  its lowering lives in.** A new category name is missing from
  `GRAMMAR_CATEGORIES`, which has no fallback, so every card whose kind moved
  goes unsupported.
- **Read the code before the docstring; the docstring is what the split
  corrects.** A recorded seam is a lead and has been wrong more often than
  right, in the module's own docstring and in its neighbours' — read the seam
  *and* everything that points at it. Hand a splitter the measurements to make
  (call graph, importers, blame since the last split) rather than a seam, and
  have its report say what each *file* would be, placing by subject the nodes
  the call graph cannot.
- **Ask "where does this already belong?" before "what should the new module be
  called?"** A crossing is more often a misplaced function than a missing
  module, and the cut that restores a module's subject beats the cut that only
  buys lines. Prefer moving the half that grows with the pool, and reuse the
  mirror's family name so the mirror re-forms instead of forking.
- **Point importers at the new module rather than re-exporting**;
  `test_import_hygiene.py` fails a re-export nobody pulls. In `engine/grammar/`
  a new top-level module is declared once (`PARSE_LAYERS`); one inside
  `lowering/` needs `FAMILY_SHARED` and the `shared` tuple in
  `test_families_import_only_their_package_shared_module`; a new `ast` floor
  needs `ast`'s shared tuple and `FAMILY_SHARED`.
- **Two branches splitting one module in a wave meet in the import blocks**, and
  neither side is necessarily right: count references in the merged body.
- **Count a module's reach in non-merge commits** (`git log --no-merges`); a
  merge commit touches every file its branch did.
- **A split round runs like a wave**, one group per subsystem, and it has one
  extra rule: **a group keeps a temporary re-export, marked as such, for every
  name it moves that a file another group is splitting imports** — editing that
  import line would conflict with the other group's move. One sweep after the
  last merge repoints those importers and deletes the re-exports
  (`test_import_hygiene.py` names each one nobody pulls any more). The 2,000-line
  round left 133 and removed them in one pass.
- **Run `scripts/integration/import_names.py` on every split and every merge
  of one.** It imports every module any `from X import Y` names, function-level
  imports included, and asks it for each name. A function-level import of a
  moved name passes every smoke import and every scan, and fails only when its
  line runs.
- **A guard over a list of modules, or `inspect.getsource` of a package, goes
  blind when the module splits** — `getsource` of a package reads only its
  `__init__`. Make such a guard walk the package (`pkgutil.iter_modules`, or the
  directory) with a floor on how many modules it saw. Three groups of the round
  each found one that would have passed over nothing.
- **An ordered table stays whole even past the runway** (the prompt registry,
  the first-match-wins trigger table): a table whose order is behaviour does
  not scatter across modules. Dump a table or registry before and after — the
  entries in order, each function by its code — and compare.
- **A method over the runway on its own is cut into its rule's steps by
  script**: each step a run of the method's top-level statements copied
  verbatim into a helper, the run replaced by generated glue (the call, inputs
  passed as themselves, an early return where the run could return), inputs
  and outputs from a liveness analysis. The proof is that inlining every
  helper back gives an AST equal to the original. `_cast_onto_stack` and
  `_activate_onto_stack` (1,865 and 2,433 lines) were cut that way by CR
  601.2 / 602.2 step.

### Mechanical edits

- **Rebuilding an import statement drops any `as` alias**: compare the names
  each module binds before and after, and refuse the file if one vanished.
- **A `while` with a second statement in its body is not a two-line
  substitution.**
- **A cleanup that changes what tests can observe is not a cleanup** (a
  stack-drain helper that settled every prompt broke 41 tests that inspect what
  a resolution asked).
- **A ratchet that fires on new code is answered in the code** — the helper,
  the accessor — never by re-snapshotting its baseline.

## Phase 0 — Pre-flight

**Entry:** a set has been chosen. **Exit:** clean tree, every gate green,
instruments current, and no module the set will reach inside the band.

1. Run the full suite, then `python scripts/check_all.py --freshness` — every
   `--check` gate plus the tracker regenerations, in ci.yml's order. All must be
   a no-op on a clean tree; a set started on a red or stale HEAD mixes old drift
   into its own diffs.
2. If the set postdates `data/vocabulary/manifest.json`'s `fetched_at`, run
   `scripts/fetch_vocabulary.py` and commit the diff on its own: an unknown
   creature type or keyword refuses to parse exactly like a grammar gap and gets
   debugged as one.

   If the Comprehensive Rules have a newer edition, bump them on a commit of
   their own, before the set. `git show HEAD:MagicCompRules.txt > old.txt`;
   `python scripts/cr_edition_diff.py --install <download.txt>`; then
   `python scripts/cr_edition_diff.py old.txt` **before touching a citation** —
   it lists every citation of a rule that moved, changed or went. Re-point the
   moved ones, re-read the changed ones, then `rules_progress.py --check` and
   `rules_gaps.py`. No test fails on a citation that now names a different rule,
   and a set printing a mechanic newer than the file cites rules this repo
   cannot.
3. **Read the size headroom before briefing anyone**: `headroom.py` (or
   `check_all --caps`). `test_module_size.OVERSIZED` must be empty — a held
   module cannot grow by a line, so any group whose work lands in one fails.
   Split every module inside the band, plus any module two groups will both
   reach (`furthest.py` over the planned groups) whose summed additions could
   carry it into the band. With a 2,000-line cap, expect most sets to need none.
   Split as in Integration, "Module splits".
   - **A module two groups will reach is split here; a module one group owns is
     briefed** to that group with "expect to split it". There is no third
     option: a shared module left alone was crossed at integration every time,
     by a few lines, however hard both groups were told to stay small — and
     once cost a card a wave.
   - **Read `furthest.py` as a lead, not as an ownership map.** A group's cards
     have landed in modules no brief named more often than in the ones named,
     and a furthest-production probe names where the parser stopped, not where
     the sentence will be taught. Tell every group that everything else in the
     band is unowned, and that a group which crosses a cap splits it in round
     (groups cut well in round).
   - **Ask each splitter where the set's cards will be *taught*.** Someone
     inside a module knows its neighbours better than a line count, and the
     answer is the most useful part of the report.
4. Clear anything in Known gaps (at the end of this file) marked for Phase 0.

## Phase 1 — Ingest and measure

**Entry:** Phase 0 exit. **Exit:** the set sits under `measured`, the suite is
green or each red is handed to the group that will own its card, the trackers
carry its row, and the census is in hand.

1. `python scripts/ingest_set.py <CODE> --fetch --register` — the whole
   registration: the card file is written and the `measured` entry inserted
   release-ordered (`card_loader.register_measured_set`). Everything else reads
   the manifest (`tests/sets/README.md`, "Adding a set"). Promotion to `sets`
   stays Phase 4's reviewed move.
2. Run the full suite and **treat what fires as yield, not noise**: a new set's
   text reaches code the old pool never ran, and these are engine bugs found
   early and cheap. Fix them now — or, where a red names a card a wave-1 group
   will own, hand it over with the card: list it in `yield.txt` (the meeting run
   reads it), put the table of known reds and their owners in every brief
   ("these are the base and not you; report any other"), and merge the owners
   first. Then **confirm the suite loaded the set** — check the collected count
   moved; a green run over a pool without it looks the same as one that found
   nothing.
3. Regenerate the trackers. The set appears as a *(measured)* row; the floors
   and ceilings do not move.
4. The census, all of it, before believing any number:
   - `support_report.py --set <CODE>`: total, supported, and the
     unsupported-reason histogram. Each reason quotes only the **first** refused
     line of its card, so the histogram sizes buckets; it does not promise that
     a bucket's fix supports its cards.
   - `--refusals`: every refused line with its exact refusal site, and a rollup
     by site. Plan Phase 3 from it rather than re-probing card by card.
   - `--fragments`: an n-gram census over the same lines, ranked by how many
     **cards** share each fragment. Rank the backlog by that column; a sentence
     census can read "no leverage" while ten cards share one clause inside ten
     sentences.
   - `parse_coverage.py --set <CODE>` and `support_report.py --set <CODE>
     --hollow-lines`: **supported** cards carrying a line nothing implements,
     which no card count can see. Run them before believing the supported
     percentage — a keyword the engine has never heard of, beside a line that
     compiles, leaves the card "supported" and the keyword dropped. What they
     find is often a second card for a production a refused card needs.
   - `picker_sweep.py --set <CODE>`: whether each supported card's cast and
     activation pickers offer what its printed line names — the only instrument
     that sees a supported card no player can cast (a picker of None makes the
     client send a bare cast). A choice made as a permanent enters or inside a
     trigger is out of its scope and reads as a false positive. A picker finding
     is half the card: read the resolution path for the permissive fallback
     beside it.
   - `census_new.py <CODE>`: which cards are **new to this pool** (an
     `oracle_id` diff against the shipped pool — never `set_progress.json`'s
     column, which counts against the whole release line) and **the origin
     trap**: reprints whose only other printing here is later than the set, so
     the insert position decides their origin (Phase 4).
5. **Probe a keyword's rewrite target against the live grammar before sizing
   it.** A keyword defined as a rewrite (equip, cycling, echo, buyback, kicker,
   flashback) costs a rewrite in `line_rewrites.expand_ability_lines` plus whatever the
   rewritten sentence still needs, and the census reports only the printed line
   refusing. Check which of the census's big rocks are already-built rewrites: a
   block's second set inherits its first set's keyword work, so a high arrival
   percentage usually means the last set did it.
6. **Give every new card to a group, supported or not.** A card supported on
   arrival has compiled, not run; a brief says "compiles", never "works". Each
   wave-1 card sheet carries a second list — its family's supported-on-arrival
   cards — to drive headless after the group's own (fix what is local, measure
   what is not). A hollow line names an ability nothing compiles, not a
   behaviour nothing performs: drive the card before an instrument's finding
   becomes a brief's first sentence.
7. **Decide whether this is a set you implement or a set you promote.** A
   reprint-shaped set (every card, or all but a handful, already shipped) has no
   Phase 2 or 3 work beyond its new cards: it is an ingest, one group driving
   the new cards, and a promotion rehearsal on the day of the ingest (Phase 4).
   Do not skip the later phases on a 100% census; the ingest and the rehearsal
   still pay.

## Phase 2 — Machinery census (the big rocks)

**Entry:** the census exists. **Exit:** every unsupported card is assigned to
exactly one bucket, and a round plan exists — in the wave briefs and the
commit that opens the set, not in ROADMAP.md.

The question: *what does this set need that no amount of per-card work
provides?* Three sweeps, in order of blast radius:

1. **Card types and layouts.** `test_card_format.py` holds the shipped pool to
   known layouts and the support gate to known types, so a set with
   planeswalkers, a new multi-face layout or any other new machine cannot
   promote whatever its text work. Each is a subsystem: scope it first, because
   it gates Phase 4 absolutely and decides whether the set is one session or
   ten. A face is a card (`engine/faces.py`) is the precedent for a layout, and
   a new layout owes the face-blind census before its promotion (Phase 4).
2. **Keywords.** Diff the set's keyword lines against
   `vocabulary.IMPLEMENTED_KEYWORDS` **and** `keyword_lines.UNSUPPORTED_KEYWORDS` — a
   third table that outranks both and is matched against the ingested
   `keywords` field before any line is classified, so a keyword implemented in
   full can still cost every card that prints it. A keyword defined as a
   rewrite is absent from `IMPLEMENTED_KEYWORDS` by design (that set admits a
   keyword being granted or named); listing one fails `test_keyword_registry`
   or admits a costless ability. Each genuinely missing keyword is one entry
   plus behaviour covering everywhere the CR says it applies, not just the
   paths this pool exercises (CLAUDE.md's lifelink). Its tests go in
   `tests/rules/` with `@pytest.mark.cr`; widen `rules_progress.py`'s `SCOPE`
   for a new section. Keywords usually open Phase 3: most cards per change.
3. **Everything else** goes to the backlog through `GRAMMAR_COVERAGE.md`'s
   reason table and the fragments census. **Rank by sentence shape, never by a
   word the sentences share**: "prevent" is a verb, not a template, and a
   nineteen-card bucket sharing it took four mechanisms.

Read-only agents may classify the backlog in parallel — *implementable now*,
*needs a new handler*, *blocked on a subsystem* — merged serially. **They
compile, not read**: run each refused line through the live grammar to name
its exact refusal site, which catches a second gap behind a reason string. A
card is supported when *any* of its lines is, so a whole mechanic can be absent
while every card printing it reports fine; only reading the compiled program
line by line finds that.

## Phase 3 — Backlog rounds (generalise first)

**Entry:** the round plan exists, and `set_pool("<CODE>")` resolves the
measured set. **Exit:** `support_report.py --set <CODE>` reports every card
supported, `--hollow-lines` reports none, and `parse_coverage.py --set <CODE>`
lists no unclaimed sentence.

Rounds run as waves of groups, briefed, merged and gated as in Integration.

1. **Each round, take the gap that is not about one card** — the change that
   clears the most others (the Revised narrative at and before `ee28617` is the
   worked example). Apply `engine/ARCHITECTURE.md`'s recipe top-down and stop at
   the first covering step. A name-keyed hook only under `card_hooks.py`'s entry
   bar; a hook-reliance ceiling raise is a decision recorded in the commit.
2. **Diff the whole pool's compiled programs before believing a change is
   local**: `oracle_diff.py snapshot` before, `compare` after, and read every
   card that moved. It stores programs in full with payloads, because counts and
   kinds are both blind to a narrowing; every lossy hand-rolled version has
   hidden a real defect. A round that adds a defaulted field to a dataclass the
   snapshot reprs strips that field's default spelling from both sides and
   reports the filtered count. Know its blind spots: a **text-keyed table** (a
   round editing one owes a differential over that table — a census of boards ×
   the whole pool), and dispatch, the wire, prompts and AI policy, which is
   where the pool's remaining defects mostly live. Keep running it, and never
   read its zero as a finding.
3. Every card lands with a focused test (`tests/sets/README.md`); a new set
   needs no `conftest.py` change.
4. **Give the behaviour a game — the Rock Hydra test — headless.** No path in
   the running app can put a measured set's card on a board (the catalog is
   shipped-only), so drive a `Game` through the steps and read the log, or use
   `run_ai_simulation(..., required=[...])`. Brief it, or each group spends the
   discovery. It is not optional: a **runtime decline** (a sentence that parses,
   compiles and is refused by its handler at run time) is visible to nothing
   else.
5. Between rounds: the supported count has risen; regenerate the trackers; run
   an `--accept` only after reading the diff it blesses. Read `--hollow-lines`
   and `parse_coverage --set` **every round**: `parse_coverage` gates only the
   shipped half, and a set has reached 100% supported with sentences nothing
   implemented — admitted by a single whitelist word — and paid for it as an
   extra wave at the promotion.
6. Write the round's narrative in the commit message that lands it, not in
   ROADMAP.md, which carries only live sections.

**The round's code.** Each of these is a mistake that has shipped.

- **A widened gate** (a line admitted that used to be refused, or classified
  differently): grep for readers keyed on the old classification before
  trusting the suite.
- **A printed restriction is done only when something enforces it.** Unenforced
  it is an ability that works more often than the card allows, silently. Land it
  as a table the support gate reads too (`activation_restrictions.py`), never as
  a parsed-and-dropped rider.
- **Extending a fragment production: look for the other one first.** Revised's
  round 8 found two where-clause parsers accepting different definitions; a
  fork in a fragment is only found by someone extending it.
- **Write a refusing gate's refusal test before trusting the gate**; the
  positive cases all pass.
- **Record which layer a failure is in** — parse, lowering, no handler, gate, or
  `engine/trigger_conditions.py`'s trigger-condition table (the trigger front end that feeds
  dispatch; a condition can parse and still fire on the wrong event). **A
  refusal can be manufactured by probe order**: when it names a verb the
  sentence does not contain, suspect the production above it.
- **A refusal can expire without anything failing**, silently and in the
  direction of doing less. When a round builds machinery near an old decline,
  re-probe the decline; declines age toward free, so budget the re-probe as
  cheaper than its estimate. A decline that names its missing pieces is a
  mechanism, not an absence: other cards build them until it falls out.
- **A guard that iterates a hand-maintained list needs an assertion that the
  list is complete**, and **a guard asking where a name appears is satisfied by
  the declaration it guards** — point a guard or a census at the corpus that
  *acts* (emit sites, registries, sweeps).
- **A guard whose exemptions are per file cannot ratchet**; hold a count per
  module.
- **A docstring that states an invariant is not a guard.** One stated exactly
  the guarantee a Known-gaps entry said was missing.
- **Validate a new census or instrument backwards** — run it against a commit
  where its defects are present and require it to name them — **and have it
  assert a floor on how much it examined**: a sweep that measured nothing looks
  like one that found nothing.
- **"No card in the pool can do X" is a census nobody ran**; run the query.
- **When a change makes something possible "in response" for the first time,
  its census responds** (destroy the source between the trigger and its
  resolution), lives in the suite, and is validated backwards.
- **A refactor whose blast radius is the whole pool does not travel with a
  wave**; it gets its own round and its own differential.
- **Never write a test asserting behaviour known to be wrong**; a test pinning a
  defect is worse than none. Record the defect in Known gaps instead.
- **Give a seat a decision it never had, and read the seeded logs for what it
  gets wrong first** — and for what happens after the thing that should have
  stopped it. **A fixture standing on a state the rules cannot reach is a test
  of the defect**: when a rules-correct fix turns many tests red at once, check
  whether their boards are reachable before reading the reds as regressions.

**What each instrument sees.** The census sizes buckets and names no defect.
`--hollow-lines` sees an ability part with no instruction; `parse_coverage` a
sentence nothing claims, and its deletion probe a word a rule ignored;
`picker_sweep` a picker that disagrees with the printed line; `oracle_diff` what
else a change touched. Nothing sees a **channel mismatch** (a reader filtering
on the wrong element type) or a **runtime decline**: only driving a game does,
and driving found most of the defects of every set measured.

**A late wave may spend groups on no cards.** By then the earlier waves have
usually measured and declined a pile of shipped defects with their parts named,
and that pile is a brief. Set the number of no-card groups by the size of the
enumerated pile, not by the cards left, and only once the pile is enumerated —
finding the work is a different job. Keep wave 1 out of `web/static/` and ask
every report to name any prompt its cards arm that a person could not answer;
those become one client group's brief, with a port and a browser of its own.

## Phase 4 — Promotion gate

**Entry:** every card supported. **Exit:** one promotion commit, its full gate
green, the trackers agreeing the set ships.

1. **Rehearse early, in a throwaway worktree.** Move the entry with
   `promote.py <CODE>` — a textual move, because a json round-trip re-escapes
   the role descriptions' em dashes and trips
   `test_registration_preserves_everything_else_byte_for_byte` — and run the
   tests before the work is done: the first rehearsal a full suite (on the day
   of the ingest for a reprint-shaped set, otherwise while the last wave runs),
   later ones `-m "not slow"` over the whole tree as often as the tree changes
   shape (an inventory written as an equality can live in `tests/ai` or
   `tests/ui`). Promotion widens every `load_catalog()` guard and shows the set
   to `parse_coverage` for the first time, so findings surface here by
   construction; rehearsing early hands them to somebody still in the code. A
   wave-2 group can take the rehearsal's inventories — driving each card,
   committing what holds either way, and writing the rows that name a set card
   as a replay script the promotion commit runs.
2. **Rehearse the wrong insert at every promotion**: `promote.py <CODE> --wrong`
   appends the entry after the last shipped set by the same textual move, so
   `test_the_shipped_sets_are_in_printing_order` is the only thing that may turn
   red. The prefix guard cannot see a new set's own card whose origin moves
   (CLAUDE.md, "The manifest").
3. **Read every red, and run the card rather than guess its kind.** Reds come
   as cards still unsupported, ratchets (accepting is the review), inventories
   asking for a review, real findings, and stale guards — and the last two
   cannot be told apart by reading.
   - **Run the card an inventory or a census names.** A census can disagree with
     a card because it was handed fewer arguments than the enforcement path (a
     card naming itself, CR 201.4). A card that looks broken from outside a game
     is not a finding until it is driven inside one — nothing outside a game ran
     the state-based check that recomputes a conditional static.
   - **Read guards as suspects.** A guard that re-spells what it checks (its own
     list of derivation tables, modules or families) invents disagreements. Fix
     it to state its invariant, and **measure the fix**: how many lines across
     the pool does the new arm excuse? An arm that excuses forty is a new hole.
   - **A guard that checks a proxy needs the proxy's availability asserted** —
     a reprint set or an empty `measured` role satisfies a proxy vacuously.
     Assert the invariant (printings, `released` dates, the paths built), not a
     symptom.
   - **A guard with two asserts shows one inventory per run**, and **a census
     that derives its subjects needs an arm for each place a subject can be
     printed.**
   - **Spell a key you grep for out of the code that reads it**, never out of
     the AST field's name.
4. **When the set added a rewrite to `expand_ability_lines`, grep every reader
   of a card's lines before the rehearsal**: a reader that does not start from
   that function reads a different card.
5. **Re-run `picker_sweep.py`**: promotion is what puts the set in front of the
   client.
6. **A new layout makes guards blind, not red.** A multi-face card's whole-card
   program is supported and has no instructions, so every guard whose
   population is "each card, compiled" walks past both halves. The next layout
   owes the census `tests/engine/test_face_blind_guards.py` came from (a scratch
   plugin that promoted the set in memory and recorded every site handed a
   multi-face card whole) before its promotion, as a group's work.
7. **Preview the `--accept`s in a second throwaway tree and read their diffs
   there**; the promotion commit is then the same commands again. Expect the
   trackers' aggregates to move on membership alone (the All row is
   printing-weighted): ask what changed in the membership before crediting the
   parser.
8. **Gate the promotion commit with the full gate, and move `main` only after
   it.** A targeted rehearsal re-runs what was red; a later merge can turn a
   different file red that only the promoted tree shows.

The checklist, each line naming its guard:

- `tests/engine/test_front_end_safety.py` — the catalog is 100% supported, and
  no card lost an instruction to the grammar.
- `tests/engine/test_card_format.py` — ingested fields only, known layouts,
  required fields, reprints deduped by `oracle_id`. Its `KNOWN_UNSUPPORTED` and
  the sweep's `SWEEP_EXCLUSIONS` are sanctioned escape hatches held empty by
  preference; any entry needs a written reason and a mention in the
  retrospective.
- `tests/engine/test_manifest_roles.py` — the roles stayed disjoint; the move
  was a move, not a copy; the shipped sets are in printing order.
- The pool-wide sweeps: catalog sweep, card coverage,
  `test_no_hollow_support.py`, `test_effect_labels.py`.
- `scripts/parse_coverage.py --check`, then `--accept-probe` only after reading
  what the deletion probe found.
- `scripts/grammar_coverage.py --accept` and `scripts/hook_reliance.py --accept`
  — the set joins the All row, the floors and the ceilings; both diffs get read,
  because accepting is the review.
- `scripts/behaviour_classes.py --accept` — the largest class stays under a
  tenth of the catalog, and the diff is the review (the script exits before
  diffing once told to accept).
- `scripts/check_all.py --freshness` clean — it regenerates `SET_PROGRESS.md`
  and `CARD_VERIFICATION.md`, the trackers that carry the pool's counts.

## Phase 5 — Post-promotion verification

**Entry:** the promotion landed. **Exit:** the verification tracker has caught
up with what this phase drove — every row recorded failing re-checked passing —
or the remaining delta is recorded in the retrospective with a plan.

**In-game verification is deliberately not a promotion gate**, and the backlog
of cards with no recorded result is accepted as-is: derived `equivalent`
cannot clear it, because the pool really is that diverse. The tracker is a log
of what someone watched, never a coverage target, and its number rises as a
by-product of driving cards to find defects. This is a decision; a later
retrospective may reverse it on purpose, not by drift. It does not change two
things: **a card recorded failing is a live bug**, and **fixing the code does
not close the row** — the round that fixes it re-checks the card in the app and
records it through the Debug Menu.

1. Record what is driven through the in-game Debug Menu, the only writer of
   `CARD_VERIFICATION.md`. A reprint set adds no untested card: the tracker is
   keyed to the deduped catalog, so its cards arrive carrying their results.
2. **Play the set where a player meets it.** Give this to one agent with a port,
   a browser session and four lists, and the instruction "record what you
   watched":
   - **A smoke game**: a whole human-vs-AI game through `run-magic`, played to
     its end. Budget it as the main event — most of the serious defects this
     phase has found came from playing, not from the lists (a human's phase
     skipped, a phase ended by a prompt, a turn lost to a torn state read).
   - **One card per headline mechanic, read off the payload** — the wire, not
     only the engine. A display list nothing derives drops what the engine
     enforces (shadow and phasing were never sent), and an accessor narrower
     than the question drops what the engine has (protection from a card type
     reached the client with no badge).
   - **One card per prompt kind the set arms, driven as a human seat.** Every
     engine test answers a prompt through the engine, so a prompt the client
     cannot answer soft-locks a person invisibly; keep the test that comes out
     of it, driving the kind under an interactive seat through the client's own
     code. **Read the payload while the prompt is still open** — ask "what is
     there before?" as well as "what is there after?": a field derived from a
     record shows the engine's provisional default as a choice. When a test's
     comment explains why a surprising value is fine, read it as a finding
     first.
   - **Every client-visible change merged since the last promotion, with the
     neighbour that must still work**, the last merge included — nobody has
     clicked it.

   **A row recorded failing is this phase working.** When the report is long,
   send closers split by where the defects live: the agent with the browser
   takes the client; a second takes the engine with a census per item (which
   finds the class the card belonged to) and reports the wire bodies; the first
   then drives every fix as a human seat. **A fix is not watched until the
   reporter watches it**, and a failing row is re-recorded only after that.
   Budget the closers as a second and a third gate after the promotion.

   For a reprint set this step is the only one that shows what promotion
   bought: check the deck editor's set filter's count against the census.
3. `scripts/simulate_ai_games.py --set <CODE>`, as part of the promotion: each
   seat gets a random limited deck from the set. Read the **exit code of every
   set's run**, not the summary of one — a run that dies is invisible to every
   number it prints. **Interactions** must be non-zero (the script exits 1
   otherwise), and **refused casts** should be zero: a refused cast breaks no
   rule but leaves a seat re-proposing it every turn. A seeded run is
   byte-identical unless a fix legitimately changed AI-visible behaviour, which
   the retrospective names; `--all` across the promotion commit shows whether
   promotion itself changed anything. **A zero in the combat counts is a
   question for the pre-set commit, not a finding**: run the same seed in a
   throwaway `git worktree add <dir> <rev>`, and remove it from the main
   checkout, never from inside it (Windows holds the directory open).

## Phase 6 — Retrospective and playbook update

**Entry:** Phases 4–5 done (or the session is ending mid-set — a partial
retrospective beats none). **Exit:** this file contains no instruction the
set's execution proved wrong, and Known gaps no entry that is no longer true.

1. Update ROADMAP.md's live sections: the set's row in "Where the sets landed",
   the pool numbers, any open item the set found or drained, any idiom it
   earned. No journal — the narrative is in the set's commits.
2. Diff this playbook against what happened:
   - **Process changes**: edit the phase or Integration text **in place**, each
     rule once, so the next reader gets current truth and not a patch series.
   - **Engine changes**: a new seam the set forced gets a pointer line in the
     phase that meets it; its documentation is in `engine/ARCHITECTURE.md` and
     CLAUDE.md, which the change itself updated. Edit a CLAUDE.md **rule** in
     place only when the set changed one — CLAUDE.md carries no counts
     (`SET_PROGRESS.md` and `CARD_VERIFICATION.md` do).
   - **New sharp edges**: add to Known gaps with why, the phase that clears it,
     and the parts. Read the list first — a duplicate under a near-identical
     heading once survived three sets.
3. **Re-check every Known-gaps entry against the code, and delete what is
   drained.** Open the file each entry names and ask whether the work is still
   undone *and* whether its premise still holds — a card list, a manifest role
   ("nothing breaks while the set is measured" expires at a promotion), a
   reassurance that bounds its scope. Entries have been carried as open for two
   and three sets after their fix landed, and briefed as live. Counting the
   set's printings of a trigger phrase is not a re-check; one probe of the code
   is. An entry that accretes instalments reads as progress when nothing is
   fixed: rewrite it to what is left. A brief's "tell me what this got wrong"
   catches what this step has not reached yet; both are needed.
4. Append one bounded entry (five to ten lines) to `SET_RETROSPECTIVES.md`: set
   code, date, what the set did, what changed in this file and why, what left
   Known gaps.

## Known gaps / pending pre-work

What the playbook knows is not yet true: each entry says why it matters, the
phase that clears it and the parts. A Phase 6 that drains an entry deletes it
(the story goes in the commit and the retrospective); a set that meets a new
one adds it. Re-check an entry against the code before briefing it.

- **The module cap's split round is open.** `tests/engine/test_module_size.py`'s
  `OVERSIZED` holds every module that was past 2,000 lines when the cap was
  widened, each frozen at its size. A frozen module cannot grow by a line, so a
  group whose work lands in one fails the guard. *Clears:* the split round,
  before the next set's Phase 0 (step 3 checks it). Each module leaves the dict
  when split to ~1,500 lines or less, as code motion (both differentials 0).

- **Two kinds of target slot cannot be roles yet.** *Why:* each leaves a printed
  narrowing or a choice to the handler at resolution. *Clears:* a round of its
  own, with `oracle_diff`.
  - *An optional slot.* "…fights **up to one** target creature an opponent
    controls" (Primal Might): a roles walk answers every role or refuses, so
    `target_descriptions._slot_roles_spec` leaves such a card on one shared list that
    loses the per-slot narrowing (the description records `optional_slots`).
    Part: an optional role in the walk and in the client.
  - *A seat chosen by one instruction and read by the next.* Keeper of the Dead
    ("Choose target opponent … Destroy target nonblack creature **that player**
    controls"): the announcement's yes/no half is enforced (`dependent_slots`),
    but which creature is the handler's pick. Parts: the earlier role's seat
    pushed into the enumeration (`lowering/_roles._UNENUMERABLE_CONTROLLERS`),
    and the re-lowering of a shipped card's two instructions.
  - *A narrowing known only at activation.* Phyrexian Splicer's slot 0 is
    "target creature **with the chosen ability**", and which keyword that is
    depends on the activation's cost choice. It has per-slot enumeration
    (`tests/sets/test_tmp_artifacts.py` asserts the two roles) but
    `_narrowing_flags` has no key for a runtime fact and the enumerator has no
    answer at picker time, so slot 0 offers every creature. Part: the keyword
    choice reaching the enumerator.

- **A target player inside another slot or a count is not announced.**
  "Target player … target cards from their graveyard" (Drafna's Restoration,
  Gaea's Blessing) and "target opponent" inside a count (Reap, Superior
  Numbers) derive a spec without the player, so the handler picks the seat
  (Superior Numbers: the target creature's controller if an opponent, else the
  first opponent) and at three seats the caster cannot choose. Two same-kind
  slots in one line are likewise read as one target named twice unless
  `lowering/_roles._CONTRADICTORY_CONTROLLERS` says no permanent could fill
  both. *Clears:* a round of its own. Parts: a count payload's
  `owner: "target_opponent"` as an announced role, a player role over a
  graveyard slot's owner, and the AI's chosen seat as a valuation. (Measured at
  Urza's Destiny; Shower of Sparks, Phelddagrif and Soldevi Heretic have since
  become roles — re-probe the rest before briefing.)

- **`StackItem.target_permanent_id` means two things.** Two arities (the cast
  and activation paths stamp the whole id list, a prompt's answer a bare id)
  and two relations (the target the controller chose, and the object a combat
  trigger is about), across about a hundred reads in 26 files.
  `oracle_types.single_chosen_id` settles the arity at the seam; the field is
  the remainder. *Why:* three shipped cards mis-played through the relation
  (Seasoned Marshal, Elite Javelineer, Sidar Jabari), fixed by gating the
  picker rather than at the field. *Clears:* a pool-wide round of its own that
  settles arity, element type and relation together — a separate field for "the
  object this is about" touches every combat fire site and
  `resolve_own_combatant`.

- **Off-battlefield colour reads ignore a colour-defining static.**
  `handlers/_filters.graveyard_card_matches`' colour branch (about twenty call
  sites with no game or owner in scope), the `@staticmethod`
  `_exile_search_matches` in `mixins/stack/choices/search.py`, and
  `_card_matches_filter`'s `game=`/`owner=` (passed by only some callers)
  read the printed `card.colors`; Celestial Dawn reaches a
  graveyard. *Why:* the narrowing answers from the card as printed where the CR
  asks the object. *Clears:* one round. `oracle_diff` is blind to it; the
  differential is a census over boards × the pool, as the battlefield half's
  was.

- **CR 509.1c's maximisation is not computed for blocks.** `declare_blockers`'
  requirement checks do not compare requirements obeyed with the most obeyable,
  so three Watchdogs under a Caverns of Despair have no legal declaration and
  combat deadlocks for a human seat as for an AI. *Clears:* a round of its own.
  Parts: one "is this creature compelled?" predicate over the requirement
  channels; a substitution test rather than an addition test; the count of
  requirements obeyed against the maximum; the AI's prune keeping compelled
  blockers. (Measured at 6ED.)

- **The client's request bodies are held to the schemas for one field.**
  `tests/ui/test_special_action_wire.py` checks that every `sendAction` body in
  `app.js` carries `GameActionRequest.seat`; every other required field of every
  `web/schemas.py` model is supplied by hand at each call site, unchecked.
  *Why:* a missing field is a 422 in a console nobody reads — every CR 116
  special action was unreachable for four sets that way. *Clears:* a round
  deriving the required fields from the schemas and asserting the JS agrees;
  until then, Phase 5 of any set whose cards reach a route no browser test
  drives.

- **The state-based check after a non-resolution is audited for special actions
  only.** It runs after a resolution and after a special action; turn-based
  actions and cost payments have not been audited. *Why:* CR 704.3 checks
  before any player receives priority, and a missed check left a stolen
  creature stolen through a combat. *Clears:* Phase 3 of the next set adding a
  non-resolution state change. (Not re-probed since Exodus.)

- **A confirmed answer may not leave the prompt queue.** Urza's Destiny found
  `_resolve_pay_any_amount` leaving its own choice queued — the game then
  refused every action by the seat that had answered — and listed nineteen more
  kinds with the same shape (`body_choice`, `cast_choice`,
  `choose_cards_in_hand`, `entry_exile`, `graveyard_exile_pick`,
  `opponent_damage`, `permanent_choice`, `player_choice`, `retarget_choice`,
  and ten delegating to `resolve_replacement_choice`). Only an interactive
  seat's confirm wedges; AI and headless seats discard. *Clears:* a per-kind
  probe, then one of two one-line changes with a whole-pool blast radius —
  `ChoiceSpec.open_for` treating an `_answered` choice as closed, or a discard
  in `resolve_pending_choice` — as a round of its own. (Not re-probed since
  Urza's Destiny.)

- **`upkeep_step._resolve_upkeep_trigger_target` falls back to `candidates[0]`
  on a stale index**, silently replacing a player's choice with the engine's. It
  is unreachable only because nothing resolves inside the upkeep-decision window
  — a fact about `web/actions.py`'s gate, not about the reader. *Clears:*
  whoever lets anything resolve in that window. Parts: three engine readers, one
  web writer, an `id` on `valid_targets`, `session_store`'s annotation, and six
  test call sites passing `(seat, index)`.

- **`web/prompt_board.py`'s Balance lists ask the printed type.** The engine counts
  lands and creatures through the layers; the prompt lists them by
  `card.primary_type` (two of the reads ratcheted in
  `tests/ui/test_layer_reads_in_web.py`), so an animated land or an
  Opalescence enchantment is offered in the wrong list, and a land creature
  belongs in both. `prompt_board` sits below `serialization` in `web.LAYERS`, so the
  part missing is a second injected callable on `PromptContext` that takes a
  permanent. *Clears:* a small round of its own.

- **Eight `card.primary_type` reads in `engine/ai_policy.py` and the modules
  split out of it are untriaged**
  (`PRIMARY_TYPE_BASELINE` in `tests/engine/test_layer_reads.py`): each wants
  the card-or-permanent judgement the other sites got. Krovikan Vampire's death
  record beside them wants a "was a creature" stamp at the removal seam
  (CR 603.10a). *Clears:* the round that next opens those modules.

- **The chosen-source shield is four instruction kinds.**
  `grant_reverse_damage_shield`, `grant_team_prevention_shield`,
  `grant_exile_prevention_shield` and `grant_reflecting_prevention_shield` share
  one body and differ by rider. Folding them into one kind with the rider as
  payload moves every affected card's compiled program, because the kind is
  read by `instruction_targets`' picker table and the effect-label buckets. *Clears:* a
  round of its own with `oracle_diff`, never a wave's tail.

- **"Who <did X>" is spelled two ways.** `PlayerRef` carries
  `attacked_this_turn` (Fire and Brimstone) and `damaged_by_source` (Diseased
  Vermin) as picker-enforced flags beside `ast.PlayerDeed` and
  `lowering/_common._PLAYER_DEEDS`. Folding them is a decision about which
  deeds the picker can answer at announcement (these two can; the table's are
  resolution-time records) and a refusal for the rest — a seat narrowing the
  picker passes silently acts on every player. *Clears:* a round of its own;
  it moves two shipped programs.

- **`unless_player_pays` is labelled with an effect family.** It is a wrapper
  filed under `activated_control`, which
  `test_a_wrapper_kind_never_borrows_a_leaf_effects_bucket` forbids and passes
  only because no leaf shares that bucket, so the first control leaf filed there
  fires it. And that guard skips kinds missing from `ACTIVATED_LABELS`, so a
  defaulting wrapper on a leaf bucket stays invisible until its row is added.
  *Clears:* a round with `oracle_diff` (re-bucketing moves Scarwood Bandits).

- **`engine/grammar/costs.py` is a third reader of "another".** Its comment's
  reason for being separate is stale (`parse_target_spec` has had two "another"
  branches for sets), though the decision stands: the word is consumed before
  `parse_target_spec` sees it, and if it were not, `_parse_cost_object` would
  drop the `distinct_from_prior` narrowing. Unifying the three moves every cost
  payload in the pool. Its citation is also wrong — CR 602.5c is about an
  acquired ability's restriction; "another" is CR 113.7 (113.7a for
  last-known information) — and comments around `engine/subject_filters.py`
  cite CR 109.5 for it, outside the 701 block the citation guard reads.
  *Clears:* the round that next touches the cost grammar; the citations at any
  time.
