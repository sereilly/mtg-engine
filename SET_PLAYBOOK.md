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
integrator-hour per wave-hour, spent on merges rather than on cards. A fix
round with no set (kg, the Known gaps) runs the same way: one group per
subject, and a pool-wide refactor alone and last, on the merged tree. The
scripts named below are in `scripts/integration/`, run from Git Bash with
`ROUND` set (a set's code in lower case, or the round's name).

### Agents and the machine

- **Make each worktree inside the repo**:
  `git worktree add .worktrees/<round>-<group> -b <round>/<group>` (agents
  cannot write outside the project root), and run its tests through the main
  checkout's venv by absolute path. Where worktrees are unavailable, fan out
  *design* instead: each agent returns an exact spec (file, function, current
  code, replacement, tests) and one applier lands them in sequence.
- **Size the fan-out from the memory you measure, never from a number here.**
  Read free *commit* (not just free RAM) with nothing of yours running, and
  count about 2.5 GB for every process that compiles the pool — a suite worker,
  an instrument, an agent's serial pytest (a worker's peak since `load_cards`
  is cached; it was 5 GB before 2026-10-31). Five agents was right on an idle
  machine; at Judgment the owner's other work left ~18 GB, so three agents
  testing serially plus the integrator's `-n 2` meeting runs, and the full
  gate alone at `-n 4`; at kg ~55 GB was free and eleven agents ran at once
  beside `-n 2` meeting runs. **And read it again before every launch and every
  gate**: at Onslaught free commit went from 29 GB to 0.8 GB and back within a
  day as the owner's own work opened and closed (a game engine; an IDE that
  starts a pytest discovery for every worktree added or removed — nineteen at
  once took the machine to zero free commit, before `tests/memory_guard.py`
  ran discoveries one at a time per checkout). Hold the
  rest of a wave and start each as a slot frees; stop your own oldest run first
  when it falls, never theirs. Past the limit nothing fails loudly: a suite
  dies as a `MemoryError`
  formatting a collection error, a `sim_fingerprint` "moves" a run whose log
  is truncated, and agents stop mid-edit.
- **An agent never runs the full suite.** It runs the files it wrote, every
  test file it edited, and the files that cover the modules it touched (grep
  `tests/` for the module names — a guard sits far from its code), serially or
  at `-n 2`, and lists them in its report — grepping for the names of the
  functions it adds a caller to as well as for its modules, because a caller
  census lists callers by name (Onslaught's
  `test_aura_host_protection` was red for four links after a branch added one).
  The full suite is the integrator's,
  one at a time: `-n 8` when the machine is yours, `-n 4` while agents run.
  The runner caps any `-n` at what free memory holds (`tests/memory_guard.py`
  prints the cap when it bites), which keeps a run alive but slows it: read
  the line rather than the number you asked for.
- **A worker killed for memory is not a red test.** It reads as
  `INTERNALERROR … KeyError: <WorkerController gw1>`, as "Different tests were
  collected", as a run that stops thousands of tests short, as a bare
  `MemoryError` in unrelated guards, or as exit 3/137 with no `FAILED` line.
  A client test whose `node` child cannot start reads as a `FAILED` line
  with exit status 3221225794 (0xC0000142): Onslaught's promotion gate had
  96, every one in `tests/ui`, all green on a re-run. Re-run smaller. Read
  free memory before starting anything beside a gate and
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
  to drive. Such an agent drives with the set promoted, so its decks hold the
  set's cards; it **re-runs its tests on the measured manifest before it
  reports**, because a route that reads the shipped catalog cannot see the set
  yet (an Onslaught wire test was green in its tree and red on its link).
  Prefer one client group holding every prompt the reports say a
  person could not answer over every group making one client change.
- **A group launched after the first merges starts from the latest gated
  link**, not the wave's base: it reuses its siblings' work instead of
  rebuilding it, and its merge meets less. Tell it what the link already holds.
- **Brief wave 2 from wave 1's reports as they arrive**, on the link holding the
  files it will touch, and extend a running group by message — census path,
  parts, and the names a sibling already took, so the two union rather than
  fork. File the measured-and-declined pile **by subject**, not by reporting
  group: five reports each holding a piece become one brief.
- **Brief a Known-gaps entry by its subject, not its example.** At kg four of
  twelve groups found a larger defect beside their entry than in it (the
  effect-label prefix read as dispatch; every "creature dies" trigger reading
  the printed type; Balance counting its three rounds at once; 932 combat
  triggers announced as targeting the object they were about), and in four
  more the entry's example or premise was wrong (the nineteen prompt kinds
  never wedged; Carrionette's spec existed). The census of the subject is the
  brief.
- **Verify a report's correction before relaying it.** A report is model output
  about code, and the code is one grep away.
- **A test asserts an invariant, never a sibling's progress.** "These four
  morph cards stay unsupported" went red at the link where a sibling supported
  one, and a strict `xfail` of a defect a sibling was fixing turned into an
  XPASS(strict) at the same kind of merge (Onslaught). Assert what holds in
  every state the wave passes through (morph is never the reason a card is
  unsupported), and leave a sibling's defect to the sibling's own test.
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
  `oracle_diff`, the duplicate and missing-name scans, the whole suite as
  the quick pass — `full` as a fourth argument only on the promotion commit,
  `check_all`, the support report) **runs at each wave's close and on the
  promotion commit — and after the first merge that changes a shared seam**
  (a new `PlayerState`/`Game` field, the static recompute, the rehearsal).
  The meeting run reads the files the branches touched; a regression in a file
  nobody touched waits for a full gate, and at Judgment six such reds from the
  first merge surfaced only at the wave's close. Whatever it finds that the
  meeting run did not goes into `surprises.txt` that day. A branch arriving
  after the wave's gate has started needs no gate of its own when the
  promotion's is next.
- **A census samples by a stable digest of the card's name**
  (`tests.helpers.stable_sample`), never by position. A position sample over
  a pool that includes the measured set re-samples at every merge that
  supports cards, so a red appears, or vanishes, at a merge that did not
  cause it (Judgment). The censuses that still sample by position read only
  the shipped pool and re-sample at a promotion (Known gaps): compute such a
  sample on both trees before blaming the set.
- **A merge commit claims only what was verified when it was made** — the
  conflict resolutions, `oracle_diff` over that merge, the scans, the meeting
  run — and says where the full gate's result will be recorded.
- **The integrator's own commit between merges gets the gate a merge gets.**
  Nothing a group is asked to do is optional for the integrator.
- **Bisect a red on a cumulative tree by running the failing test on each link
  beneath it** — seconds, not a suite.
- **A red carried across links is read again at each link, by what it names,
  not by its id.** A census that is red on the base stays red at every merge
  and reads as "the base's"; at Legions' fifth link the same failing test
  named two more cards, from the branch just merged, and was waved through
  until the next link's run.
- **Do not re-run a red gate and take the green.** A test that fails in one
  full run and passes alone is a finding with a schedule — two tests, one
  worker, one order — and is read the day it is reported, including when it
  failed in a group's batch. When someone can name the mechanism, reproduce
  the order in ten lines (fill the memo, clear the cache, call the test). When
  nobody can, ask the process: a scratch `pytest_runtest_teardown` plugin
  replaying the failing scenario after every test names the polluter in one
  suite (it found the `id()`-keyed memos). When the polluter may be the
  module-level RNG — an AI seat or a shuffle reached through the web, which
  is not seeded per session — run the test in one process under
  `random.seed(0..N)`: Onslaught's Phase 5 flake (Tangle Wire's trigger
  order over the wire) failed 3 of 120 that way, and the cause was an AI
  hand the fixture had left full.
- **Resolve a conflict with a script that asserts what it read**
  (`resolve_both.py`, `merge_blocks.py`): bytes in and out, line endings kept,
  every conflict region asserted to be the one that was read. A replayable
  resolution can be tested before it is the merge, re-run when the merge is
  re-staged, and reviewed as intent.
- **Bump the client's script versions once, after the last client merge.** Each
  client group bumps `index.html`'s `?v=` to name its own build; the merge keeps
  one, and a browser holding the other group's cached `app.js` is served it.
  The integrator names the merged build (Onslaught's two client groups).
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
- **A new `PlayerState` or `Game` field is read by every `vars()` walker** —
  `ai_rehearsal.seat_standing` and the AI censuses' board signatures. One that
  moves on every resolution (a graveyard arrival stamp) reads as a lasting
  change: the AI cast spells that did nothing, and two censuses drifted.
  Decide at the merge whether a new field is bookkeeping.
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
2. Run the **full pass** (`pytest --full`) and **treat what fires as yield,
   not noise** — the quick pass samples the censuses, and Legions' one
   engine yield (a trigger census naming Chromeshell Crab) hid in a sample
   until a meeting run named the file and it ran whole: a new set's
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
   tests before the work is done: the quick pass over the whole tree, first
   on the day of the ingest for a reprint-shaped set (otherwise while the
   last wave runs), then as often as the tree changes shape (an inventory
   written as an equality can live in `tests/ai` or `tests/ui`). Rehearse a
   tree that closes a wave: Onslaught's first rehearsal, on a link three
   merges short of it, was read after those merges had fixed most of what it
   found. The full pass waits for the promotion commit (step 9). Promotion
   widens every `load_catalog()` guard and shows the set
   to `parse_coverage` for the first time, so findings surface here by
   construction; rehearsing early hands them to somebody still in the code. A
   wave-2 group can take the rehearsal's inventories — driving each card,
   committing what holds either way, and writing the rows that name a set card
   as a replay script the promotion commit runs. **A replay's data is a reading
   of the tree it was made on, and it expires**: re-run it and re-read what
   it asserts on the final link. Onslaught's inserted 44 deletion-probe rows
   read before another group taught the parser "have" and on a base lacking
   the group that supported the last four cards, so at the promotion some
   rows were stale and one card had never been read.
2. **Rehearse the wrong insert at every promotion**: `promote.py <CODE> --wrong`
   appends the entry after the last shipped set by the same textual move, so
   `test_the_shipped_sets_are_in_printing_order` is the only thing that may turn
   red. The prefix guard cannot see a new set's own card whose origin moves
   (CLAUDE.md, "The manifest"). **Rehearse it on the promotion commit's
   content** — check the commit out, put back the unpromoted manifest, then
   move the entry — never on the link it was staged from: that tree lacks
   the accepts and the replay, and their guards turn red beside the one that
   matters (Onslaught's first wrong-insert run read seven reds, five of them
   accepts it did not have).
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
8. **The sampled censuses run whole once**, in step 9's full pass, which sets
   `MTG_FULL_CENSUS` for every file that calls `tests.helpers.stable_sample`
   (a sample's floor is a statement about the cards it happened to draw).
   What it finds is mostly older than the set — run the red files on `main`
   to tell — and is fixed in the promotion, the card pinned into that
   census's sample so the sampled run keeps examining it (Onslaught's, the
   first since sampling: Mindstab Thrull announcing its own controller
   targeted, and Mogg Assassin's death scan recursing, both red on `main`).
9. **Gate the promotion commit with the full gate as the full pass —
   `gate.sh <tree> <tag> <workers> full` — and move `main` only after it.**
   It is the one run of the tests marked `full` (the seeded AI-game batches,
   the heavy censuses: `tests/passes.py`), so their findings arrive here. A
   targeted rehearsal re-runs what was red; a later merge can turn a
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
   A recorded pass also moves `BEHAVIOUR_CLASSES.md` (a verified card covers
   its class), so the agent's last commit is one `check_all --freshness`
   reads clean — not the two freshness regenerations alone, which left
   Onslaught's merge stale.
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
one adds it. Re-check an entry against the code before briefing it. **An
entry is drained when the board it names is driven, as it names it** — kg2
drained the colour-blind planner with a test on the neighbouring board (the
Angel already face down), and Legions' Phase 5 found Onslaught's own board
(the Angel cast face down) still stranding its turn-up.

- **CR 508.1d's maximisation is not computed for attacks.** The block side's
  is (`engine/phases/block_requirements.py`); `declare_attackers_step.
  declare_attackers` clears every requirement once a cap is reached, so under
  Dueling Grounds a vanilla creature attacking alone is accepted (CR 508.1d's
  own example says it is illegal), and its cost clause knows only tap costs
  (Juggernaut under Propaganda is compelled to attack and pay). *Clears:* a
  round of its own. Parts: one attack-requirement list over
  `_must_attack_if_able` and `_must_attack_beside`; a search over attackers ×
  defenders under `attack_declaration_refusal` and the per-defender caps;
  costs (`_attack_mana_costs_of`, `_declaration_sacrifice_plan`) left out of
  the maximum; how a conditional requirement counts (Ekundu Cyclops); the AI's
  `_legal_declaration` asking it. Probes: `scratch/kg/blocks/attack_probe.py`,
  `attack_cost_probe.py`. (Measured at kg.)


- **Twenty-one damage calls outside `engine/handlers` ask no CR 616.1e
  question** — each dealt where no resumable loop holds the work behind it,
  so the affected seat takes the default. The handlers and combat damage ask
  (`tests/engine/test_kg_damage_handler_asks.py`). Upkeep effects resolved
  inline (`phases/upkeep_effects.py`: Cyclone's two sweeps and two pay-or-damage
  effects); prompt answers (`effects._apply_opponent_damage_choice` ×2,
  `choices/card_names._resolve_name_then_reveal_top`,
  `choices/optional_pay._apply_optional_pay_decline`,
  `choices/sacrifice._apply_sacrifice_shortfall`); land riders
  (`stack/resolution._resolve_card`'s extra-land damage,
  `land_tapped_for_mana._resolve_tapped_land_trigger_step`); Earthbind
  (`oracle_instructions._apply_aura_effect`); Eye for an Eye
  (`effects._apply_mirror_damage`); and eight CR 614.9 redirects in
  `replacements/redirects.py`, which deal a new event inside another event's
  616.1 process (CR 616.1g wants a design). And a loop asks its recipients in
  its own order, not APNAP (CR 616.1's last sentence), visible only when two
  seats are asked in one effect. *Clears:* a round of its own per family; the
  APNAP order moves the sim logs.

- **A CR 614 replacement choice does not hold its stack object.** The prompt
  queue holds a resolution until its last answer, but the replacement queue
  does not: Blood of the Martyr's redirect is answered after Shock has
  finished resolving, Mind Twist finishes before Library of Leng's choice,
  and Mox Diamond's stack is empty while its discard toll is owed. End states
  are right; the CR 608.2 timing is not, so anything that reads "while it
  resolves" is wrong. ROADMAP had this as read and not measured; the boards in
  `tests/regressions/test_kg_prompts_answered_choice_leaves_queue.py` measure it.
  *Clears:* a round of its own, beside ROADMAP's "two prompts that meet".
  Parts (Legions' W2G3, which found it a different mechanism from the
  headless hold below): `pending_replacement_choices` are never stamped with
  the stack item, and `choices_for_stack_item` reads only `pending_choices` —
  stamp in `offer_replacement_choice`, have `choices_for_stack_item` /
  `stack_item_is_waiting` read both queues, and answer
  `resolve_replacement_choice` inside the `_answer_pending_choice` envelope so
  `_release_stack_item` runs.

- **The AI never activates a graveyard ability.** No caller of
  `activate_from_graveyard` exists outside the web route, so Ashen Ghoul,
  Carrionette, Coffin Puppets, Glory, Hammer of Bogardan, Necrosavant, Shard
  Phoenix and Whiteout are never used by a simulated seat. *Clears:* the next
  AI round; it needs an honesty count (`activations_from_graveyard`) beside it.

- **Printed types are still read off the battlefield and in two sweeps.**
  `handlers/_filters.graveyard_card_matches`' `graveyard_subtypes` branch reads
  printed subtypes (Conspiracy does not reach "target Griffin card"), and
  `search_matches`' Conspiracy override is asked of the chooser rather than
  the zone's owner — the type twin of the colour fix (every matcher already
  takes `game=`/`owner=`). `mixins/game_ending.py`'s CR 704.5m / 702.16c
  sweeps read the printed word "Aura", so a Gliding Licid that became an Aura
  stays on a host given protection from blue (`scratch/kg/layers/
  probe_licid_sba.py`). Two colour reads stay printed outside the matchers:
  the wire's hand and stack cards (`web/serialization.py`, display only) and
  `ai_valuation.CounterProfile.can_counter` (baselined in `test_layer_reads`).
  *Clears:* one round, census over boards × the pool.

- **Ten censuses over the shipped pool sample by position**
  (`tests/engine/test_kg_steps_stable_sampling.py`'s `POSITIONAL_SAMPLERS`),
  so each re-samples at a promotion. Each is a one-line switch to
  `tests.helpers.stable_sample` and one re-measure of its floors. *Clears:* any
  round; until then a promotion's red in one of them is computed on both trees
  before it is blamed on the set.

- **Four prompts answer a permanent by index.** `untap_select` stores indices
  across requests (the shape the upkeep target had); `opponent_damage_choose`
  also takes an id; `optional_untap_confirm` has no id form
  (`sacrifice_confirm` gained its id form at Legions' W2G3). *Clears:* the round that next opens those prompts. Parts per prompt:
  an `id` on each offered entry, the answer read by id, a stale id a refusal.

- **Activated roles with a seat role skip the all-targets-illegal check.**
  `legality_resolution.ability_target_verdicts` has no per-role verdict for a
  seat, so Keeper of the Dead, Planeswalker's Scorn and Favor and Goblin Welder
  are judged per target only (CR 608.2b's "every target illegal" never
  fires); and Keeper of the Dead's creature is not destroyed when its
  opponent gains shroud in response though the creature is still legal.
  *Clears:* a small round. Part: one branch in `ability_target_verdicts`.

- **The seat channel still carries two meanings.** `StackItem.target_player_index`
  holds either the player a controller chose or an event's seat ("that
  player"). kg split the permanent half (`about_permanent_id`) and gated the
  discard fire site's seat stamp (`trigger_utils.bound_event_seat`); a static
  census of every seat stamp against lines that announce a player target found
  only Goblin Cadets and Guerrilla Tactics, both fixed. The stamps left
  (unblocked, attached-combat, "one or more attack", upkeep "that player",
  delayed bound-player) are right only because no line beside them names a
  player target. The "becomes the target" announcement read a stamp as a
  target until Onslaught's promotion (Mindstab Thrull announced its own
  controller, Psychic Purge the discard's causer, and Rayne drew); it now
  asks a trigger `announces_a_target`, the picker's question. *Clears:* a round adding `about_player_index`, read the way
  `about_permanent_id` is; `target_permanent_index` keeps its int-or-list shape
  beside it and goes in the same round.


- **The request-body guard derives presence, not shape.**
  `tests/ui/test_kg_client_request_schemas.py` holds every body to its
  route's required fields and its handler's refusals, but ten handlers refuse
  on the prompt's own state (`activate` at three seats, `discard_confirm`,
  `enter_choice_confirm`, `face_down_cast_confirm`,
  `outside_game_pick_confirm`, `permanent_choice_confirm`,
  `pile_search_confirm`, `put_from_hand_confirm`, `trigger_target_confirm`,
  `word_of_command_confirm`) and no value's type is checked. *Clears:* Phase 5
  of a set whose prompt reaches one of those routes.

- **Effect labels that name one card's effect, not the moment.**
  `("matching_permanent_enters", "may")` → `triggered_damage` (Thelon's and
  Tourach's Chant), `("end_step_enchanted_controller", "if_then")` →
  `triggered_destruction` (Insubordination deals damage), and
  `TRIGGERED_LABELS["if_then"]` is `triggered_label`, a word naming neither.
  Report-only since kg (dispatch reads `StackItem.ability_kind`), but
  `triggered_abilities.py:130` still reads `effect_kind == "triggered_delayed"`
  as a flag (one producer, self-consistent). *Clears:* a label round with
  `oracle_diff`; each move is label-only.

- **About thirty-five comments cite CR 109.5 for "a spell's damage source is
  its printed card"**; the rule is CR 120.7 (the source of damage is the
  object that dealt it). List: `scratch/kg/grammar/spell_source_family.txt`,
  including `tests/rules/test_damage_source_identity.py`'s marker. The
  citation guard reads only the 701 block. *Clears:* any time.

- **A text change cannot name a spell.** Magical Hack, Sleight of Mind, Crystal
  Spray, Alter Reality and Artificial Evolution print "target spell or
  permanent" and offer only a permanent: a stack object has no text channel.
  *Clears:* a round of its own (Onslaught's W2G4 declined it with its parts):
  a `spell_or_permanent` target spec; a text-change record on the `StackItem`;
  one `spell_text_card` reader at the thirteen sites that read a resolving
  spell's text; the change carried to the permanent the spell becomes (CR
  400.7a's exception, as `color_changes` carries a colour); copies dropping it.

- **Seven "an opponent" picks made at announcement take the first opponent.**
  With several opponents the controller chooses which (CR 601.7a, 602.3a,
  700.2e); Callous Oppressor's entry and Wormfang Crab's pick ask it since
  Onslaught, but a mode (Fatal Lore, Library of Lat-Nam, Misfortune) and a
  target (Cuombajj Witches, Echo Chamber, Nova Pentacle, Preacher) chosen by
  an opponent still go to the first one. Multiplayer only. *Clears:* a
  multiplayer round; the census
  `tests/regressions/test_an_opponent_chooses_asks_which.py` names the seven,
  so a new silent pick fails.

- **Whether a sweep is one "next instance of damage from that source" is not
  settled.** CR 615.8's source-keyed shields (Penance, both Pilgrims,
  Shadowbane, Reflect Damage, Desperate Gambit, Impulsive Maneuvers) answer
  one chunk of an Earthquake; no ruling on any of the seven says whether a
  sweep's simultaneous chunks are one instance. The recipient-keyed "next
  time" is settled (Mirrorwood Treefolk's and Glarecaster's rulings:
  `damage_redirects.SharedNextTime`). *Clears:* a rules reading with the
  `mtg-rules` skill before any code;
  `tests/regressions/test_next_time_is_a_time.py` counts them.




- **Face-down leftovers on the wire.** Dream Halls beside a morph card is
  two alternative costs, and the wire's `alternative_cost` is a bool (Force
  of Will's limit); Chain of Vapor's two offers (sacrifice a land; copy the
  spell) reach a person as the same card text with no question. *Clears:*
  the next client group. Legions' W2G1 took the rest ("played from", the
  {3} no longer called a morph cost, `hidden_card` in prompt lists) and its
  Phase 5 the retarget prompt's two identical "Face-down creature" buttons.

- **A cast announcement carries one seat and no graveyard slot.**
  `ai_actions.CastAction` has no `target_role_refs` (`ActivationAction` has),
  so an AI seat names at most one player in a chain of seat roles (Wheel and
  Deal's weighing, `ai_targets._weighed_seat_prefix`, stops at the second
  seat; Kaboom! names one) and never names Cruel Revival's optional Zombie
  card. And Kaboom!'s players
  are dealt with in turn-order groups as its 2022-09-09 ruling says, but the
  caster is never asked the order within a group. *Clears:* the next AI round
  that opens casting. Parts: the field on `CastAction`, read where
  `cast_announcement` builds the cast's roles; the AI's role chain answering
  it; the within-group order as a prompt.

- **Three unasked defaults pick by position, not by worth.** Strongarm
  Tactics' seat nobody asks discards its first cards (it lost 4 life holding a
  creature card in 5 of 12 discards); Risky Move's permanent-choice default
  takes board order (Butcher Orgg risked over Festering Goblin, 5 of 24);
  Meddle's forced re-aim takes the first legal change
  (`handlers/retargeting.py`), where `ai_prompts.choose_target_change` already
  answers the optional "may change". *Clears:* an engine-defaults round, each
  with a census of its prompt kind's defaults over the pool. Measured by
  Onslaught's W2G5 (`scratch/ons/w2g5/probe_defaults.txt`).

- **A quick-pass rehearsal leaves the `full`-marked inventories to the
  promotion commit.** Phase 4's rehearsals run the quick pass, so step 9's
  full pass is the first run over the promoted tree of every test marked
  `full`, and an inventory there that the set widens turns red after the
  promotion commit rather than while a group is still in the code. Measured
  against Onslaught's second rehearsal (run before the passes split): of its
  ten real findings nine came from quick-pass guards, and one — the Charms
  rows of `tests/ai/test_ai_mode_chooser_census.py` — is `full`-only now.
  Legions repeated it: the zone-cast census
  (`tests/regressions/test_ody_w2g2_zone_cast_census.py`, `full`) first ran
  over the promoted tree in the promotion's full pass and named two branches'
  changes (a land's "played from" log line, and the rehearsal miscounting a
  zone buyback's card), two follow-up commits on the promotion link. The
  parse, grammar, hook and behaviour ratchets are untouched: `check_all` runs
  their `--check`. *Clears:* the owner's call — the full pass on the
  wave-close rehearsal tree (~1,300 s at `-n 6` on 2026-10-31), or the
  `full`-marked files that read `load_catalog()` named in the rehearsal.

- **No planner prices a source's own drawback** (a depletion counter, a
  painland's damage, "doesn't untap"): kg2's preference kept an Island by
  tapping Timberline Ridge. The other half of this entry is drained: since
  Legions' closer C2, floating mana pays generic against the payer's wants at
  every reader (`mana_payment.floating_units_for_generic`; 23,106 of 77,796
  pool shapes stranded a colour before, 0 after). A payer told nothing still
  spends colourless first (`scratch/kg2/payment/pool_order.py` reads 470 of
  1,344 either way; 0 with the want named). *Clears:* a payment follow-up
  round; part: a per-source price beside the wants in `_sparing_choice`.

- **The web's sequential mulligan table is not CR 103.5's rounds.** Each seat
  mulligans until it keeps before the next declares; CR 103.5 has every
  player declare each round, then every mulligan of the round happen
  together (the simulator's `ai_mulligan.take_opening_mulligans` does). And
  in the simulator the coin flip's winner sets the deal and declaration
  order, but seat 0 always takes turn one. *Clears:* the next pregame round;
  parts: `web/pregame._pregame_advance_mulligan_offer` advancing by round,
  and the simulator's first turn read from the flip.

- **A refused cast's "insufficient mana" no longer says what taxed it.** The
  tax line ("Memory Lapse is taxed by Kaervek's Torch") was an announcement
  the refused attempt wrote, and kg2 takes it back with the attempt (CR
  733.1), so the actor's reason reads only the shortfall; the web's
  payment-plan preview still shows the whole price. *Clears:* any round that
  opens `pool_payment`; part: fold the taxing sources into the refusal's own
  reason.

- **The simulator and a headless resolution do not hold a stack object while
  an optional prompt is owed.** The web always does (CR 608.2): there the
  object stays on the stack until its last answer. With a `prompt_driver` (the
  simulator) the driver answers before the next object resolves, but after
  one state-based check and after destruction triggers are announced. Legions'
  W2G3 counted 120 of 1,071 driven resolutions that armed a prompt and held
  nothing (optional_pay 87, revealed_hand_pick 12, discard 11,
  reorder_library 10; 8 seeded games), and in 3 the state-based check acted
  before the answer. *Clears:* an engine round with the simulator's games
  reseeded, since most "finished resolving" lines move. Parts:
  `resolution._settle` pauses when `prompt_driver` is set (with a held top,
  skip the loop-top state check, drive the prompts, don't break);
  `phase_steps._resolve_window_answering_prompts` calls
  `resolve_top_of_stack(pause_for_choices=True)` and skips
  `_check_between_resolutions` / `offer_priority` while the top is held;
  Power Sink's `mana_payment` branch then reaches the driver (check its
  default against `_auto_resolve_mana_payment`); `ai_rehearsal.scratch_copy`
  carries the driver, so rehearsals change too. Probe:
  `scratch/lgn/w2g3/probe_driven_hold.py`.

- **A trigger fired during a resolution chooses before that resolution's
  state-based check.** Legions' W2G2 made a trigger choose its targets as its
  unit of play's window closes, after the event and its state-based check —
  every windowed road. A trigger fired *inside* a resolving spell still
  chooses at once: Chandra's Incinerator triggered by Earthquake's damage is
  offered creatures Earthquake is about to kill. *Clears:* whoever opens
  `Game.putting_triggers_on_stack` around a resolution; part: the resolution
  is the unit of play, closed after its own state-based check
  (`PhaseStepsMixin._check_between_resolutions`).

- **Rishadan Brigand, Cutpurse and Footpad at three or more seats offer the
  payment to one opponent.** Only `context.target`'s seat is asked, and its
  decline makes every opponent sacrifice (`scratch/lgn/w2g3/probe_rishadan3p.py`:
  P1 paid, P2 was never asked). Two-player games are right. *Clears:* a
  multiplayer round; part: lower as `may` with actor `each_opponent` and the
  otherwise branch's `who` None (moves these three cards in `oracle_diff`).

- **The AI casts no ambush blocker and never toggles Swooping Talon.**
  Legions' W2G4 taught the AI to cast flash creatures at another seat's end
  step and in response, not in the opponent's declare-attackers step:
  `ai_simulator._instant_speed_window` answers no priority there, and a
  rehearsal started there declares no blocks on its copy (`_run_out_the_turn`
  decides nothing; `_fight_the_combat` starts only from the active seat's main
  phase) — ROADMAP's "other priority windows". Swooping Talon's provoke is
  always declined when the target cannot block a flier: the activation is a
  hamper on its own source (`harms_its_own_source` skips
  `SOURCE_HAMPER_KINDS`), and `compelled_block_declined` would have to value
  the block with flying removed, activated before blockers are declared.
  *Clears:* the next AI round that opens the defending seat's windows.

- **Three wire leftovers from Legions' client group.** Burnt Offering's
  cast-side mana split (`mana_combination` on the cast) has no client chooser,
  where Goblin Clearcutter's activation has one. `prompt_owed_by` reads the
  pending-choice queue only, so a session-level decision (a cleanup discard,
  an upkeep payment) leaves the other viewer's panel blank rather than naming
  who owes it. And a human-vs-human host tab made thousands of state GETs in
  minutes (the poll does not back off while nothing changes). *Clears:* the
  next client group.

- **Trample damage is assigned without asking a human attacker.** With one
  blocker, the damage step divides lethal to the blocker and the rest to the
  player (Scion of Darkness: a 3/3 split) without offering the attacker CR
  510.1c–d's choice of more to the blocker. `_needs_manual_damage_assignment`
  does not count trample as a choice. *Clears:* a combat round; part: a
  trampler with an interactive controller and a choice to make (more than
  lethal available) is manual, through the existing assignment announcement
  (`engine/combat_assignment.py`).

- **An "as it enters" choice is made with the permanent already on the
  battlefield** (CR 614.12a: the choice is made before it enters). Legions'
  closer C1 cast 40 choosers from a person's hand. All 40 sat on the
  battlefield with their spell still on the stack while the prompt was open.
  37 had a provisional `chosen_*` default recorded, and Soul Warden fired
  before the choice for all 11 creatures. The wire now shows the board as it
  was before the choice (`serialization.entry_choice_view`; the permanent
  carries `entering: true`). What remains is what the engine sees. Nothing
  can act in the window, but an entry trigger fires before the choice it
  should follow. *Clears:* an engine round. Parts:
  1. In `zone_funnels._enter_battlefield`, an entry that arms a person's
     prompt makes everything from the battlefield append onward a
     continuation, run at the last answer (the recompute,
     `apply_entry_riders`, the `matching_permanent_enters` emit, its own enter
     trigger). Meanwhile the permanent sits in no zone, as
     `pending_replacement_choices` already does.
  2. `_perform_entry_state` and `mixins/entry_choices` stamp no default
     before arming a person's prompt (readers use `.get`).
  3. The answer funnel runs the continuation on the last `_entering_permanent`
     prompt, then releases the held spell.
  4. Census every caller that acts on the permanent after `_enter_battlefield`
     returns (an Aura's attach, tapped-and-attacking, token returns, linked
     exile returns).
  5. Amplify's `place_plus1_counters` must work outside a zone, or run after
     the append.
  6. The entry renderers in `web/prompt_values` must not assume a battlefield
     position.
  7. `tests/ui/test_entry_choice_prompt_ui_api.py`, which calls
     `_initialize_permanent_state` directly, must change with it.

- **What a payment's wants cannot see.** Since Legions' closer C2, a
  face-down spell's hidden card wants its turn-up cost
  (`mana_wants.wants_brought_by`). Two later costs are still not wants:
  - A face-up permanent spell's own activated abilities. `wants_brought_by`
    is not told the payment is a cast. Its callers know it:
    `_PaymentPlanner.spell is not None`, `PaymentPurpose.kind == CAST` in
    `web/payment_plan.planned_taps`, and `pool_payment._floating_mana_wants`.
    Told, it adds the card's non-mana activated abilities to the abilities
    tier, skipping a {T} ability on a creature without haste (CR 302.6).
  - Flashback. `mana_wants` reads no graveyard. Two parts: each graveyard
    card the seat may cast under a permission joins the cards tier at the
    permission's cost (`ai_weighed_cast.permitted_casts`,
    `flashback.has_flashback(game, …)`); and `wants_brought_by` adds the
    flashback cost of an instant or sorcery cast from the hand, since it
    lands in the graveyard as it resolves.

  The turn-up special action also counts the permanent being turned up as one
  of its own wants, which is redundant but harmless. *Clears:* a payment
  round.

- **Phase 5's log wording.** Each of these moves seeded logs, so a round
  taking them reseeds once:
  - A token's name is doubled ("Goblin Token token").
  - A colour choice is logged by its letter ("chose U"), and a creature type
    in lower case ("chose wizard").
  - Bane of the Living's −X/−X is logged as "buffed".
  - "Reanimated creature to battlefield".
  - Toxin Sliver's untargeted "that creature" is logged as "its target is gone
    (608.2b)".
  - "Goblin Dynamo dealt 1 damage" names no recipient.
  - "Declare attackers step complete" is written before the step's window
    drains, in every game.

  *Clears:* a log-wording round.

- **Legions' Phase 5 client leftovers.**
  - Two same-named permanents one seat controls read the same on the retarget
    prompt ("Willbender — yours" twice).
  - The floating main-phase prompt panel covers a permanent at 1920×1080.
  - A session with `use_pregame=False` ignores the rematch's CR 103.1 chooser.
    The UI always uses the pregame.

  *Clears:* the next client group.

- **A dealt-damage trigger fires once per source, not once per event.**
  Blood Hound ("Whenever you're dealt damage, you may put that many +1/+1
  counters on this creature") triggered four times when four attackers dealt
  their combat damage together (CR 510.2: one simultaneous event). By CR
  603.2c it triggers once, for the total. Boros Reckoner's 2017-03-14 ruling
  states it for "is dealt damage": "If Boros Reckoner is dealt damage by
  multiple sources at once, such as by two creatures blocking it, its ability
  triggers once". The same game also logged "Blood Hound gets 3 +1/+1
  counters" after it had died. 24 pool cards print a "whenever … dealt damage"
  trigger (Jackal Pup, Filthy Cur, Saber Ants, Wall of Souls, Lich, Soul
  Link, …), though "whenever a creature is dealt damage" (Repercussion)
  rightly triggers per creature. *Clears:* an engine round. Parts:
  - a census of the 24 under one multi-source combat damage step;
  - the damage event's per-recipient total read by a recipient-keyed
    trigger;
  - the counters step refusing, with no log line, a source that has left
    (CR 400.7: the card in the graveyard is a new object).

- **Two observations seen once and not reproduced.**
  - **Goblin Assassin triggered once, not twice**, when Planar Guide returned
    it beside Goblin Clearcutter. Two browser and three headless re-runs
    triggered twice (`scratch/lgn/p5/assassin_single_trigger_state.json`,
    `repro_assassin_*.py`). C1's step censuses do not explain it: it is an
    entry trigger, not a held window.
  - **A turn-up from floating mana spent {W}{W} with seven colourless
    floating**, on a browser board with an untapped Savannah and other cards
    held. On the same board without the extra cards, headless
    (`scratch/lgn/probe_savannah.py`), it spends {W} and {C}, and
    `floating_units_for_generic` spends colourless first in every shape
    probed.

  *Clears:* whoever reproduces either.
