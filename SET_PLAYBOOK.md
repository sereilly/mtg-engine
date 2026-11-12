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
subject, and a pool-wide refactor alone and last, on the merged tree. Its
later waves are briefed from the earlier groups' measured-and-left as each
report lands, and launched beside the groups still running from the link
that holds their first-wave neighbour's work (kg4 ran three waves that way,
none waiting for a wave to close). The
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
  count about 1.5 GB for every process that compiles the pool — a suite worker,
  an instrument (`parse_coverage`'s eight processes together ~1.4 GB), an
  agent's serial pytest (a worker's full-pass peak since the source guards
  stopped keeping syntax trees twice; 2.5 GB before 2026-11-08, 5 GB before
  2026-10-31). Five agents was right on an idle
  machine; at Judgment the owner's other work left ~18 GB, so three agents
  testing serially plus the integrator's `-n 2` meeting runs, and the full
  gate alone at `-n 4`; at kg ~55 GB was free and eleven agents ran at once
  beside `-n 2` meeting runs; at kg5 the owner's game engine held ~13 GB and
  9–17 GB stayed free, so gates ran at `-n 3` or `-n 4` and four of seven
  wave-2 groups launched at once, the other three as wave-1 agents finished.
  **And read it again before every launch and every
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
  test file it edited, and the files that cover the modules it touched,
  serially or at `-n 2`, and lists them in its report. `scripts/tests_for_diff.py`
  lists them — the edited tests, the importers of an edited module or helper,
  and every census that enumerates a registry the diff added a member to —
  with each file's recorded quick and full seconds, before anything runs;
  `--run` runs their quick tests only (`pytest --quick`: a named file
  otherwise runs its `full` tests, and some hold hour-long AI censuses). It
  still greps for the names of the functions it adds a caller to, because a
  caller census lists callers by name (Onslaught's
  `test_aura_host_protection` was red for four links after a branch added one).
  While a set is measured, its fourth reason (**measured**) names every test
  whose population walks the set for any `engine/`, `web/`, `data/` or
  `cards/` diff — the censuses no import or registry reaches: Darksteel's
  W1G3 shipped a red in the AI's graveyard-denial census it never ran, and
  the conditional-grants and upkeep-window censuses surfaced only in the
  rehearsal; all three are on that list. Between sets a brief still says to
  grep `tests/` for the card names and the functions a change reaches. Its
  base is where the branch started (`--base` / `$MTG_DIFF_BASE`), not
  `main`.
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
  runs nothing and reports a blank exit code. **An agent's long run goes
  through `scripts/integration/run_and_wait.sh <log> <command…>`**: a
  foreground call is cut off near three minutes, and every Mirrodin report
  hand-wrote a background job and a poll loop for it (a loop grepping for
  "passed" never ends here; an agent that ends its turn waiting never wakes).
  It detaches the command, writes its exit code as the log's last line and to
  `<log>.exit`, and waits a bounded 110 s from the call (under the agent shell
  tool's 120-second foreground limit): done, it exits with the command's
  code and the `FAILED` lines; not done, it exits 75 with the `--wait` command
  to resume. Every brief names it.
- **A stopped background task is not a stopped process**: the stop kills the
  tool's shell, not the Python under it. Look for survivors after a stop, write
  a long loop inline rather than in a script, and never edit a script something
  may still be reading. **Stop a process only by a PID you started**: a group
  that stopped its own `pytest tests/ai --full` by command line also killed
  two siblings' identical runs (kg4), which then read as unexplained exit-127
  deaths. Every brief says so.
- **Never edit a worktree while a test run is reading it.** The run's result
  would describe no tree that existed. Stage the next merge on a new link.
- **Never `git stash`** — the stash is shared across worktrees, and agents have
  popped a sibling's work into their own tree. Commit instead.
- **Give each group a private scratch folder**
  (`.worktrees/scratch/<round>/<group>/`); a shared one gets overwritten.
  **Save each group's final report verbatim the day it lands**
  (`scratch/<round>/reports/<group>.md`), beside the merge notes: Phase 6 is
  briefed from both, and kg5's had to be recovered from the session
  transcript for it. **A subagent cannot write a report file** (the file
  tool refuses one; Darksteel's nine were each briefed to and refused), so
  the hand-back in the session transcript is the only copy: a brief asks
  for the report as the final message, and `extract_reports.py
  <scratch>/reports <transcript-dir> --groups agents.json` writes each as
  `<group>.md` — a resumed agent's follow-up as `<group>.2.md`, never over
  it — and names the groups still owed.
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
`gen_cards.py`, `furthest.py`), not from memory: **`write_briefs.py CODE
--groups <groups.json> --census <dir> --out <scratch> [--yield YIELD.md]`**
writes the common brief from `scripts/integration/brief_templates/` — the
rules below once, the census's counts, hollow cards, keyword reading, groups,
base, size band, per-set sections and yield filled — and a skeleton per
group; its `TODO` lines are the integrator's (`--wave 2` for wave 2). A rule a
set corrects is corrected in the template, once. Every brief says:

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
  line was refused, not what is absent, and it usually over-states: probe the
  sentence before believing it, and treat "this is only a probe artifact" as the
  claim most likely to cost a card. **Probe it with `scripts/probe_line.py
  --card NAME`** (or a raw line), not a hand-written probe — Mirrodin's groups
  wrote seven: it runs the compiler's own compile with every reader it
  consults traced, and names the layer that refused each line (a grammar
  production with its furthest accepted frame, a trigger-condition row, a card
  gate, the Aura/Equipment gate, a missing handler). The census's sites
  (`support_report --refusals`, `furthest.py`) are its verdicts since the
  speed round; before it a grammar-only watch put a fifth of Mirrodin's
  refused lines in the wrong layer. When a brief would say "widen the
  whitelist", check first whether the whitelist is consulted at all — it may be
  a fork of the shared reader.
- **An AI cast question starts with `print(explain_cast(game, seat, card))`**
  (`engine/ai_cast_explain.py`), before any tracing probe: every candidate the
  real chooser built, its score's terms, and each dropped one's gate reason. A
  new candidate builder finishes through `ai_cast_score.finished_cast_candidate`,
  and a new gate returns `cast_trace.dropped("reason")`.
- **Verify an inherited diagnosis as part of the round**, not as a preamble to
  it; measuring one has caught defects the briefed fix would have introduced.
- **A census red's brief says "trace first"**, never "look in module M".
  Mirrodin's W2G9 brief guessed two of four promotion reds were one defect and
  named the nearest code for each; they were three causes (a P/T sign stored
  in the amount, a zone bonus one candidate builder skipped, a test executor
  dropping the mode list) and none was in the code named. A census red names
  a card and a symptom; the brief hands over those and the tools to trace
  them, and lets the trace find the module.
- **Require a census to disbelieve its own author.** A suspicion that survives
  its census is worth writing down; one that does not is worth the census.
- **A ruling** (how a card is played, as against what a rule says) **carries its
  source** — Scryfall's per-card `rulings_uri` — or is not stated. Rulings are
  not in `MagicCompRules.txt`, and two briefs have stated a wrong one from
  memory. Check every rule a brief states against the CR as well:
  `scripts/integration/check_brief_crs.py <repo> <briefs>` prints each cited
  number with its rule's opening words, and a `SUBJECT?` line for a citation
  whose rule shares no word with the sentence citing it — a wrong section
  (722, Preparation Cards, for controlling a player) is caught; a neighbour
  that shares the vocabulary is not, so **read the words**: Mirrodin's
  brief cited 205.2a (the list of card types) where 205.2b (an object with
  two types) was meant, and the printed subject said so. Rulings come from
  `bulk_rulings.py CODE <out>` (Scryfall's bulk file, one download; the
  per-card fetch is rate-limited).
- **List the base's known reds in every brief, and ask for both
  differentials before the first edit** (`oracle_diff snapshot` and
  `sim_fingerprint snapshot`). Darksteel's wave-1 groups built base worktrees
  to tell their reds from the base's, and three rebuilt a base fingerprint
  from an export because the brief asked only for the first snapshot. The
  same paragraph says **never `sed -i` a source file** — in Git Bash it
  rewrites CRLF as LF (three Darksteel groups) — beside the heredoc warning.
- **Put the test helpers in the common brief**, not in a mid-wave
  broadcast. A test reads the board after `tests.helpers.settle(game)` —
  every owed prompt answered (its default, or `answers={kind: fn}`), the
  stack resolved with CR 704.3's check between objects, state-based actions
  performed, until nothing moves — never after `resolve_stack`, which answers
  only what blocks the stack (an offer a step's trigger left on an empty
  stack stays owed) and performs no state-based actions;
  `settle(game, defaults=False)` returns the first owed prompt instead of
  answering it. A combat is walked with `tests.helpers.drive_combat(game)`
  after `declare_attack`: it settles each step before leaving it and by
  default leaves end of combat, so combat is over (CR 511.3); "at end of
  combat" triggers fire as that step begins (CR 511.2), so
  `through="combat_damage"`, which stops on arriving there, finds them
  resolved and the creatures still in combat. Three Mirrodin
  groups lost a round each before these existed (forty-odd private copies
  replaced since). A probe builds its board with
  `scripts/integration/board.py`, and a client group sets up a live one with
  `serve_board.py`.
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
- **Brief wave 2 from wave 1's reports as they arrive — and launch it then**,
  on the link holding the files it will touch (Darksteel's AI group waited for
  all nine merges, though its blocking item was known from Phase 1's
  yield), and extend a running group by message — census path,
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
  about code, and the code is one grep away. **And a brief's CR numbers before
  sending it**: Scourge's carried four wrong ones, each corrected by the group
  it misled — the pool empties under 500.5, not 500.4; an Aura told its host
  is 303.4i, not 303.4f; "permanent card" is 110.4a, not 110.4b; a single
  target is counted by 115.9a, not 115.10. A group checking its own found ten
  engine comments citing 202.3b (a double-faced card's back face) for X on the
  stack (202.3e). Since kg4 `test_kg4_citations_rule_subjects.py` fails a
  cited number or letter the CR does not have and a 113.7a / 112.2 citation
  made for a neighbour's claim (54 of 66 engine 113.7a citations were), and
  the 701 heading guard reads `tests/` and `scripts/` too; a rule's other
  neighbours are still read by hand.
- **A test asserts an invariant, never a sibling's progress.** "These four
  morph cards stay unsupported" went red at the link where a sibling supported
  one, and a strict `xfail` of a defect a sibling was fixing turned into an
  XPASS(strict) at the same kind of merge (Onslaught). Assert what holds in
  every state the wave passes through (morph is never the reason a card is
  unsupported), and leave a sibling's defect to the sibling's own test. The
  same holds across sets: a per-set premise ("these cards are new", "this
  reprint's origin turns on the index") asks the sets **released before** the
  set and M21, never "every other shipped set" — 8ED reprinted nine of 7ED's
  seventeen new cards and turned three 7ED tests red at its promotion.
- **Brief a speed group from a profile of two sets of different shape**, with
  the numbers and not a design: the call counts reproduce, a proposed design
  usually does not.

### The chain: merging and gating

- **Every cumulative tree is tested before `main` rests on it.** Stage each
  merge in its own link worktree on top of the previous link (`chain_stage.sh`),
  commit it with its trackers regenerated (`chain_commit.sh`, which runs
  `regen.sh` — never an `--accept`), and fast-forward `main` only to a link
  whose full gate was read green. A red link is fixed in that link, then the
  links above it are rebuilt or merged forward. **Short of memory, commit the
  links with their scans and regenerate at a chain tip**: `regen.sh` runs
  `parse_coverage` at eight processes on every link, and no group's branch
  regenerates, so one regeneration at the tip (`parse_coverage --workers 3`)
  covers every link beneath it (kg5 did it at two tips).
- **Before staging a branch, `git status` its worktree and list its scratch for
  anything newer than its last commit** (`chain_stage.sh` refuses a dirty
  tree). Uncommitted work is a decision for the integrator that `git merge`
  never shows.
- **The gate between merges is the meeting-point run** (`MEETING_BASE=$(git
  merge-base <link> <branch>) meeting.sh <tree> <tag>`): every test file any merged branch added or edited, the set's own
  files, the ingest's yield (`yield.txt`), every file a full gate has surprised
  you with (`surprises.txt`) and the structural guards. **Read the list from
  the branch's merge-base** (`MEETING_BASE`; the default is `main`): that is
  the branch's own files plus every link merged since its base — which is
  exactly the first blind spot below, closed by construction — and it does
  not accumulate while `main` is held at the round's base (Mirrodin's list
  read from `main` grew from 47 files to 87, 230 s to 504 s). Never a hand-picked
  list; the script refuses a path that does not exist, because xdist reports a
  typo as "no tests ran". **It adds every census over a registry the merged
  branches moved** (`tests_for_diff.py --censuses` against the same base,
  listed in `gate/meeting_censuses_<tag>.txt`): it imports the base's engine
  and the link's and compares their registries, and names each test file that
  enumerates one whose members changed. Mirrodin's wave-close gate found eight
  reds no meeting named, each such a census in a file no branch edited;
  replayed over the wave's twelve merges it names five of the seven files at
  the merge that caused them (the other two read the AI policy's source and
  the compiled pool, which no registry diff can see). Add by hand the
  censuses of any seam two merged branches both touched and every ratchet
  either side lowered — an instrument is code that meets other code at a merge. **The list is "changed since `main`",
  which has two blind spots** (kg3): once `main` moves past a link, that link's
  files leave the list, so a branch whose base is older than `main` — it never
  met the links merged since — also runs the test files those links added or
  edited (kg3 kept them in `gate/wave1_tests.txt`; Scourge held `main` at the
  round's base until the promotion, which keeps every link's files in the list
  by construction — `main` need not move at a wave's close); and a per-set file no branch
  edited is in no list, so a link whose branch changes behaviour broadly (a
  default, an entry road, combat assignment, log wording) also runs `tests/sets`
  whole (three per-set reds surfaced late in kg3). It takes about a minute
  at `-n 4`; Mirrodin skipped it for the graveyard's arrival seam and a full
  gate found the Tempest Efreet red two links later. A link whose branch
  changes what a wire field means runs `tests/ui` and `tests/regressions`
  whole too: a test reading the payload through `web.app`'s `TestClient`
  imports none of the modules the change edits, so neither `tests_for_diff`
  nor the meeting names it (kg5's `client` made a copy's `name` its copiable
  name; `test_batch15` looked a Copy Artifact up by the old one, and the red
  waited seven links for a gate that ran `tests/regressions`).
- **Two branches may share one meeting**: stage and commit the first link
  with its scans (oracle_diff, dups, missing and import names), stage the
  second on it, and run the meeting at the top. A red is bisected onto the
  lower link in seconds. Mirrodin batched four pairs, Darksteel three
  pairs and two triples; none needed the bisect. A follow-up commit on a
  branch already merged (a rehearsal red sent back to its group) is staged
  under an alias, since its link name is taken: `git branch <round>/fu3
  <round>/w1g3`, then `chain_stage.sh fu3 <tip>`.
- **Name the `full`-marked structural guards in every group brief**
  (`tests/engine/test_face_blind_guards.py`, `test_grammar_layering.py`,
  `test_cast_prohibition_readers.py`): an agent's quick-pass `tests/engine` never
  runs them, and the meeting run does (it names files whole). kg3's first wave
  went red on the face-blind scan at two meetings.
- **The full gate** (`gate.sh <tree> <tag>`, read with `gate_report.sh`:
  `oracle_diff`, the duplicate and missing-name scans, the whole suite as
  the quick pass — `full` as a fourth argument on the last wave-close
  rehearsal and on the promotion commit,
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
  cause it (Judgment). Every census does since kg3
  (`tests/engine/test_kg_steps_stable_sampling.py`: `POSITIONAL_SAMPLERS` is
  empty).
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
  hand the fixture had left full. kg5's `ai_vs_ai` web census was green in
  a meeting run and red in a folder run of the same tree for that reason: a
  session's seed builds its decks and coin flip and nothing else (Known
  gaps; how a web test seeds itself is `.claude/rules/tests.md`'s).
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
  — most are backwards checks a second layer now satisfies. The same holds for
  two sibling groups: kg4's `aiact` gate (every ability rehearsed) held back
  what three of `aivalue`'s backwards checks switched `aivalue`'s fix off to
  see; each backwards context switches both layers off, the forward tests
  untouched.
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
- **A resolver anchors its markers and refuses to stage on a failed check.**
  A per-set section marker ends in a run of `=`, and an unanchored
  `=======` split one region inside such a line (Mirrodin's W2G1 merge; the
  resolver's own assertion refused it, and a `git add` after it staged the
  markers anyway). Match `^=======$`. `engine/ARCHITECTURE.md`'s module table
  conflicts at most merges, each time two branches inserting phrases into
  the same rows: `wordmerge_rows.py` merges them word by word against the
  base and aborts on a word-level conflict.
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
  a wave-2 group by name. **Two groups whose cards fell through one hole each
  close it from their own side**, and the second fix is dead code after the
  merge: Scourge's storm and cycling groups each added a hollow-spell gate to
  the compiler (both merged clean; the earlier one fired first), and its last
  card's group and the engine-pile group each wrote CR 113.6k's reader for an
  exiled card's upkeep trigger (one conflict, at two call sites). Read every
  report's "shipped cards found" and "what the brief got wrong" against the
  others' by subject before staging the second, and keep one reader with both
  reasons in its comment.
- **Two fixes of one bug: take the one that subsumes the other, and prove it
  with the losing branch's tests.** When one is a hand-written list and the
  other derives the set, take the derivation and carry the list's additions
  onto it — the list was the bug.
- **One channel carrying two value shapes** (a list from one producer and a bare
  id from another; ids from one and live objects from another). Settle the
  channel's arity **and** its element type in one round, at one reader, never by
  another local normalisation.
- **A semantic collision** — one branch splits a kind, another's table assumed
  one; one moves every caller onto a new seam, another adds a caller of the
  old one — merges textually clean, and the tests between merges find it only
  where one reaches that caller. **So every brief asks the report for each
  function it touched in a file another group's row names, and that list is
  the merge's reading list**: read each one in the merged tree against the
  sibling's report before the meeting. kg5's kindred added a single find
  calling `shuffle_library_of` where grammar had put every search shuffle
  behind `shuffle_after_search` (Tithe's one shuffle); the merge was clean and
  the read caught it. A function one branch moved and another edited
  conflicts in its old home alone: resolve that file to the mover's side and
  apply the edit in the new home (`aiact` moved `_rehearse_activation` into
  `ai_activation_rehearsal` while `airesp` changed one of its lines).
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
- **A seeded AI row red only under several AI branches together is reseeded
  once, after the last AI branch merges** — not at each link, where the next
  AI branch moves the games again. Each branch is green alone; carry the red
  as known, read again at each link by what it names, and reseed on the tip
  with a search that holds each candidate seed to the test's own assertions.
  kg5 reseeded two that way (`test_kg5_mana_substitution_simulation` 5151 to
  5155, `test_kg_layers_ai_balance_and_deaths` 69 to 141;
  `scratch/kg5/tools/reseed_*.py`).
- **A new `PlayerState` or `Game` field is read by every `vars()` walker** —
  `ai_rehearsal.position_digest` and the AI censuses' board signatures. One that
  moves on every resolution (a graveyard arrival stamp) reads as a lasting
  change: the AI cast spells that did nothing, and two censuses drifted.
  Decide at the merge whether a new field is bookkeeping.
- **Read a new mechanism for what it lets the code know.** Ask at the merge what
  it can see that it should not (a rehearsal copy holding the opponent's real
  hand) and what can now fail without anybody being told (an exception
  swallowed into "cannot be weighed"); answer the second with an honesty count.

### Per-set test files

- **Open the set's per-set test files on `main` before the fan-out, one marked
  section per group** (`open_test_files.py CODE <group>… [--later TYPES]`), each group's imports
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
  whichever file has room. A type most groups write into reaches the cap at a
  meeting, mid-wave (Scourge's creatures file, nine sections, 2,601 lines at
  the seventh merge): when more than five groups open a section in one type's
  file, open its `_later_groups` sibling on the base and split the sections
  between the two before the fan-out (`open_test_files.py --later
  creatures,artifacts`: the first half of the groups in the file, the rest in
  its sibling — Darksteel's nine groups).

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
- **A third differential for a split: a dump of every moved definition** —
  bytecode, constants, defaults and what each global resolves to — of the base
  file against the new modules, under `PYTHONHASHSEED=0` or with set reprs
  canonicalised (they reorder between processes); and **an import-order
  diff**: a new module's slot in a package's import list can move what loads
  first (pre5dn S4: `bound_reanimation`'s alphabetical slot moved 18 engine
  modules earlier, so it sits beside `reanimation`). **A method cut adds a
  call hop**: a census that counts calls from a seam (`test_kg3_batch_roads`)
  counts the moved step at its caller. A split's own final run is two runs —
  the importers `tests_for_diff` names with `--quick`, and the `full`-marked
  structural guards (plus any full test patching a moved name) whole.
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
  line runs. It reads `tests/` too since kg4: a test importing a moved name at
  its old home is otherwise a collection ERROR the meeting reports late.
- **A guard over a list of modules, or `inspect.getsource` of a package, goes
  blind when the module splits** — `getsource` of a package reads only its
  `__init__`. Make such a guard walk the package (`pkgutil.iter_modules`, or the
  directory) with a floor on how many modules it saw. Three groups of the round
  each found one that would have passed over nothing.
- **An ordered table stays whole even past the runway** (the prompt registry,
  the first-match-wins trigger table): a table whose order is behaviour does
  not scatter across modules. Dump a table or registry before and after — the
  entries in order, each function by its code — and compare. **What makes
  such a table long is often not its rows**: Darksteel's
  `whenever_triggers.py` sat in the band at 1,807 lines, 78% of them the
  rows' rationale. The notes moved to `engine/whenever_trigger_notes.py` in
  the table's own order (a guard holds each note to one row), the rows
  byte-identical and the table's dump equal, and the module fell to 526 —
  a table in the band is measured for that before it is called unsplittable.
- **A method over the runway on its own is cut into its rule's steps by
  script**: each step a run of the method's top-level statements copied
  verbatim into a helper, the run replaced by generated glue (the call, inputs
  passed as themselves, an early return where the run could return), inputs
  and outputs from a liveness analysis. The proof is that inlining every
  helper back gives an AST equal to the original. `_cast_onto_stack` and
  `_activate_onto_stack` (1,865 and 2,433 lines), and in pre5dn `_cast_onto_stack`
  and `_resolve_card` again, were cut that way by CR
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
   into its own diffs. Every run merges its tests' times into the tree's
   `.test_timings.json`, and the main checkout's is what `tests_for_diff.py`
   shows every agent of the round before it runs a file: run this suite as the
   full pass (`--full`) there, or copy in the file from the tree where the
   latest full pass ran (Phase 1's). **When `main`'s tip already passed a
   full pass** — the last promotion's or round's gate, any fix re-run as the
   full pass — the quick pass and `check_all --freshness` are enough: the full
   pass Darksteel's Phase 0 ran repeated its predecessor's gate (26 minutes).
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
2. **First, `tests_for_diff.py --ingest <CODE> --run -n 4`**: every test whose
   population walks the measured set, by node id, in the full pass, longest
   first — checked against six ingests' full passes (every one of their reds
   named: DST 13, JUD 32, LGN 2, MRD 13, ONS 8, SCG 6) — so its reds go into
   `yield.txt` and the briefs before the fan-out, where Darksteel's arrived 80
   minutes into the wave. Then run the **full pass** (`pytest --full`) and **treat what fires as yield,
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
   nothing. **Run it in the ingest's own worktree**, never in the checkout the
   card work starts in, and **not in the tree the wave's base is cut from**:
   the work starts while this pass runs (8ED's integrator edited the main
   checkout under it and had to put two files back; Mirrodin's opened the
   per-set test files in the ingest tree while its pass read it). Launch the
   wave while it runs, and send each red to its owner when it lands.
3. Regenerate the trackers. The set appears as a *(measured)* row; the floors
   and ceilings do not move.
4. The census, all of it, before believing any number —
   `scripts/integration/census.sh CODE <tree>` runs every instrument below
   under the names `gen_cards.py`, `card_table.py` and `furthest.py` read:
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
   snapshot reprs reads its real moves: `compare` counts a card moved only by
   the new field's default spelling on that field's own line. Know its blind spots: a **text-keyed table** (a
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
  A probe on one can hide a defect as well: 8ED's AI cast chooser, asked at a
  step name the engine does not have, proposed nothing, which read as the AI
  rightly holding a Primeval Force it in fact cast.

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
   found. **The rehearsal of the tree that closes the last wave runs the full
   pass** (`gate.sh <tree> <tag> <workers> full`; earlier rehearsals run the
   quick pass): the `full`-marked inventories and censuses are the ones a set
   widens, and read first on the promotion commit (step 9) they turn red after
   it rather than while a group is still in the code (Onslaught's Charms rows,
   Legions' zone-cast census). A round with no promotion runs it too: kg3's
   wave gates ran the quick pass, and its rehearsal, the round's first whole
   full pass, found four censuses no group had run, each driving a table
   that did not yet answer a branch's new question (an entry prompt, a
   trample assignment, a flashback left behind as a want, the defender's
   window after the blocks). kg5's found four more: two seeded rows the AI
   branches moved only together, and two of the last group's own — a double
   count its new id keyword made in the divided-target gate, found by a
   full-marked sweep, and a census file it had edited and run in the quick
   pass alone. `tests_for_diff.py --run` keeps the quick pass, so a brief
   says to run each test file the group edits by name, which runs it whole.
   Promotion
   widens every `load_catalog()` guard and shows the set
   to `parse_coverage` for the first time, so findings surface here by
   construction; rehearsing early hands them to somebody still in the code.
   **Most of a rehearsal's new reds are censuses over `load_catalog()`**
   (Mirrodin's first: 11 of 14) — a table the set's own groups widened that
   only sees a shipped set. **So the promotion runs in memory too**:
   `MTG_PROMOTE=<CODE>` (`engine/card_loader.py`) reads the measured set as
   shipped, at `promote.py`'s position, with the manifest untouched, so a
   group runs its family's censuses in round (`MTG_PROMOTE=DST pytest
   <files>`) and has nothing to restore before it commits. The integrator runs
   `census_rehearsal.sh <tree> <tag> <CODE>` at each wave's close beside the
   gate — the quick pass whole and every sampled census whole
   (`MTG_FULL_CENSUS=1`, minutes) under the overlay, the shipped-pool guards'
   reds listed apart — **and again before the promotion's full pass**:
   Mirrodin's four promotion reds were all sampled-census shares, found by a
   32-minute full pass and fixed in a 76-minute round before `main` could
   move. The gates (`gate.sh`, `meeting.sh`, `regen.sh`) and `check_all`
   refuse to run under the overlay. A census whose rows check themselves against the shipped catalog gets
   a promotion-row script the promotion commit runs (W2G0b's
   `promotion_rows.py`, idempotent, `--check` until applied). When every
   group has reported and the promotion is the next commit, its full pass
   is the last wave-close rehearsal too (Mirrodin). A
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
   Onslaught's merge stale. A pass carries no note
   (`verification_store.record` keeps a reason for a fail only), so what
   was watched for a pass goes in the commit message.
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

   Closers are parallel branches, and three things that hold for a wave's
   groups hold for them too (Scourge's four):
   - **They shadow each other** ("Silent merge hazards"). The AI closer and
     the web closer each fixed the unregenerated Krosan Warchief: the AI
     closer inside the main-phase chooser, the web closer by sending the web
     AI through the engine's priority answer. That left the first fix with no
     caller. Read the closers' reports against each other before the chain.
   - **A closer that changes what an AI decision is worth runs `tests/ai -m
     full` whole.** Its own files are not enough. Re-scoring one redirect
     sent two seeded Legions games another way, and only the closers' full
     gate saw it.
   - **A seam a closer adds reaches the Debug Menu's raw-state builder too**
     (`web/debug_actions._apply_raw_state`), because the re-drive sets its
     boards up through that builder. It had rebuilt exile by card name after
     the engine closer made each exiled copy its own object.

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
   promotion itself changed anything. **Pin the set's new cards too**
   (`run_ai_simulation(..., required_cards=[...])`): a random limited deck
   from a reprint set rarely holds them — ten 8ED games dealt three of eleven
   — and the pinned run is what showed the AI casting Primeval Force into its
   own sacrifice, a defect fourteen shipped cards shared. **A zero in the combat counts is a
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
     CLAUDE.md (with its subject files in `.claude/rules/`), which the change
     itself updated. Edit a CLAUDE.md **rule** in place, in whichever of those
     files holds it, only when the set changed one — CLAUDE.md carries no counts
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

- **Two `DamageRedirect` records on one creature are one candidate**, oldest
  first, so CR 616.1e's choice between them is never offered: Jade Monolith
  beside Daughter of Autumn, Shimian Night Stalker or an en-Kor (kg5
  `prevent`, which made Jade Monolith a record, measured it). Parts:
  `damage_events.damage_candidates` hands the game and the event to
  `replacement_candidates`, so an `instances=` registration expands for
  damage; the recorded redirect registers `instances=`, one per applicable
  record (a plural of `damage_redirects.applicable_redirect`). Smaller, same
  subject: Eye for an Eye's mirrored damage is dealt with no source, where
  its ruling (2009-02-01) has Eye for an Eye deal it, so a Circle of
  Protection: White cannot prevent it; Forcefield's shield lasts to the end
  of combat though it prints "this turn". Seen, not measured: the Phantoms'
  `prevention/static.SIMULTANEOUS_RIDER_SPENT` is kept for combat damage
  alone, and a non-combat dealing can have several sources now. *Clears:* a
  prevention round.

- **The announcement gates still read a battlefield target by slot, and the
  tests still announce one.** Since kg5 each zone has its own target keyword
  at the API (`engine/target_keywords.py`: `target_permanent_ids`,
  `target_graveyard_indices`, `target_ante_index`); the AI's actions and the
  wire announce by them, and `announced_slot` derives the slot once, at the
  entry point (`tests/engine/test_kg5_ids_api_keywords.py`). Left, each
  measured by kg5 `ids`:
  - (a) The gates take and read that derived slot —
    `cast_target_validation`, `legality_cast_gates`, `legality_abilities`,
    `activation_charges`, `activation_checks`, `cast_announcement`,
    `pool_payment._resolved_cast_x` and `bare_announcements.names_an_object`
    / `announced_fields` — with their 31 `isinstance` arity checks, which go
    once the tests' adapter (c) does. The AI choosers work in picker slots
    and convert only at the action (`ai_casts._announced_candidate`,
    `ai_abilities._activation_candidate`,
    `ai_cast_gates._aimed_under_target_requirements`,
    `ai_foreign_activations`), and `divided_targets`' `(seat, slot)` entries
    are a second slot channel.
  - (b) The client's cast bodies still send a slot: `resolvePendingCastTarget`'s
    cast body sends `permanent_index`, and the several-target senders send
    graveyard picks as slots; the activation bodies fall back to the slot
    when the state names no id; the prompt answers `resolve_optional_trigger`
    (`web/action_turn`) and `opponent_damage_choose`
    (`web/action_prompt_board`) take a seat and slot when no id is given.
    The server reads each old field in the card's zone
    (`web/action_helpers.wire_target_keywords`), so these are accepted
    fields, not wrong ones.
  - (c) 1,236 test calls in 234 files still pass `target_permanent_index`,
    which every entry point accepts as the tests' adapter
    (`scratch/kg5/ids/tests_census_after.txt`; the most in
    `test_lea_enchantments.py`, `test_legends_instants.py`,
    `test_arabian_nights_cards.py`, `test_batch05.py`, `test_mir_instants.py`).
    1,206 name a seat beside the slot, so each becomes
    `target_permanent_ids=[game.permanent_at(seat, slot).permanent_id]` (or a
    `tests/helpers.py` helper); the 136 that name their card by a non-literal
    need it read at runtime. The graveyard calls are converted.
  *Clears:* a round of its own, (c) then (a); (b) in any client round.

- **A payable Alliances toll is charged after Land Equilibrium, so its
  controller is never offered paying first.** Since kg5 an entry asks CR
  616.1e's question (`_begin_entry` returns `entry_awaiting.ENTRY_SUSPENDED`;
  Worms of the Earth's "can't" is its own `cant_enter_battlefield` event), but
  a toll its land can pay (Lake of the Dead beside a Swamp, the six other
  Alliances lands) is paid in the entry state, after Land Equilibrium, at a
  seat nobody asks and at a person's alike: the player loses the extra land,
  where Land Equilibrium's ruling (2009-10-01) lets them pay first, which can
  switch it off (`scratch/kg5/asks/probe_payable.py`). The other order is
  settled: with Land Equilibrium applied first, the toll then replaces the
  entry inside its modified event and the "then sacrifices a land" still
  happens (CR 614.6, 616.1f; the same ruling: "After applying one, if the
  other one would still be applicable, it's then applied"). Parts (kg5
  `entry2`):
  1. `replacements/permanents.py`: a `would_enter_battlefield` registration
     for the payable toll at order 18 (after `UNPAYABLE_ENTRY_SACRIFICE`'s 16
     and Mox Diamond's 17, before Land Equilibrium's 20, so a seat nobody asks
     pays first), applying while `_entry_sacrifice_refuses_entry` holds, the
     candidates cover the count and the permanent is not marked paid (the
     `ENTRY_TOLL_ANSWERED` arrangement); a seat nobody asks pays inline, and
     CR 616.1f re-asks Land Equilibrium against the smaller board;
  2. `choices/sacrifice.arm_forced_sacrifice` takes a continuation its
     resolver calls after the sacrifice: the entry's re-run, for an asked
     seat;
  3. `ZoneFunnelsMixin._entry_question_owed` recognises any owed prompt
     carrying the entry's `_restart`, not only `effect_order`, so the entry
     suspends and the caller's `then` runs once;
  4. `mixins/permanent_state._perform_entry_state` skips the toll for a
     permanent marked paid;
  5. a seat nobody asks changes order, so a sim fingerprint and new cases in
     `tests/regressions/test_kg5_asks_contended_entry.py`.
  Same seam: a permanent that becomes a land only through the copy it
  chooses as it enters (Clone of an animated land, Sculpting Steel of an
  artifact land) still enters under Worms of the Earth, where its ruling
  (2008-08-01) sends it to the graveyard (CR 614.17d;
  `scratch/kg5/entry2/probe_clone.py`) — part: ask `cant_enter_battlefield`
  again in `_begin_entry` after `_initialize_permanent_state`'s copy choice,
  and at `_finish_answered_entries` for an "as it enters" copy prompt; and at
  an interactive seat Mox Diamond's answered toll re-enters without the
  caller's `then` (no "put onto battlefield" line, the cast's `arrived` never
  runs; `replacements/permanents._resolve_entry_discard_toll`, the base too).
  *Clears:* an entry-seam round.

- **The web leaves a person unasked in three windows** (kg5 `webturn2` and
  `cleanup`; every step the AI's turn arrives at with objects on the stack
  goes round since kg5, `game_flow._ai_answers_over_the_stack`).
  (a) A person's own upkeep and draw-step objects resolve unasked when the
  step is not flagged (Copper Tablet;
  `scratch/kg5/webturn2/probe_unasked_own.py`): `turn_steps._resolve_upkeep_step`
  (the no-decision road) and `_finish_beginning_phase` need the AI turn's
  deferral, and `_advance_after_upkeep_choices`, `_resume_deferred_upkeep`
  and the Island Sanctuary road hand the person's pay answers into
  `resolve_upkeep`, which would have to survive a deferred window.
  (b) The End Turn button (`turn_steps._end_turn`) drains the end step's
  objects with the AI never offered priority (Ball Lightning); the jump
  itself is deliberate.
  (c) A person is never given priority in the cleanup step (CR 514.3a): the
  engine gives it only at a table a priority driver plays, and with an
  interactive seat the window collapses to its outcome. Parts:
  `phases/cleanup_step.resolve_cleanup_step`, when the table has an
  interactive seat and 514.3a applies, leaves the objects on the stack, calls
  `start_priority_window(active)` and `hold_step_open()`, and returns False;
  a new `Game.close_cleanup_step()` begins another cleanup step once the
  stack is empty and everyone has passed; `web/game_flow._advance_phase`
  leaves a `"cleanup"` step through `_leave_step(session,
  game.close_cleanup_step)` before `_start_next_turn`; `turn_steps._end_turn`
  and `action_turn._action_cleanup_select` tell a False meaning "window
  open" from one meaning "discard owed" (every False sets
  `cleanup_required_discards` today); and a priority panel in the client's
  cleanup step. Beside it: a hand a cleanup trigger fills past its maximum
  (Thawing Glaciers' return) is discarded down by the AI's default in the
  second pass, not by the person (`_action_cleanup_select` handles one
  deferral); and CR 603.7g makes a flash Aura's delayed sacrifice as the
  spell is cast, so a countered one still triggers, inertly, at cleanup,
  which a mark on a permanent cannot say (part: a `DelayedTrigger` armed at
  `_cast_onto_stack` and bound to the permanent at `_resolve_card`).
  Seen, not measured: Time Vault untaps at the skip, not as the first thing
  of the next turn taken (CR 614.10b; its ruling of 2008-10-01). *Clears:* a
  web turn-flow round.

- **`effect_order`'s measured default covers a damage event's first
  contended round only.** A seat nobody asks takes `choose_effect`'s stated
  order everywhere else; there it takes the effect whose result costs the
  affected seat least, each forced first on a scratch copy, a tie keeping the
  stated order (`engine/measured_effect_order.measured_damage_default`,
  `tests/rules/test_kg5_prevent_measured_effect_order.py`). Left, each
  measured by kg5 `prevent`: a non-damage kind keeps the stated order (a copy
  has no result to read without its caller: a per-kind result reader its
  caller hands to `apply_in_order(default=)`); a later contended round of a
  damage event is stated; an effect deferred to a dealing's finish is not
  seen by the measurement; and the copy does not conceal hidden zones (no
  damage contention reads one today). *Clears:* an engine-defaults round.

- **AI leftovers.** The engine plays each correctly; the AI chooses badly or
  not at all. From kg5's AI groups, each measured:
  - Lethal Vapors is activated by nobody. `ai_standing.seat_standing` prices
    a skipped turn since kg5 (`SKIPPED_TURN_WORTH`; an extra turn is
    unpriced); left: `ai_valuation.foreign_activation_use` has no use for
    "removes its source, at a price to the activator" (`destroy_self` and
    `skip_next_turn`; Wall of Vipers is its one twin), which
    `ai_foreign_activations._foreign_activation_candidate` would weigh by
    rehearsal; and no reader prices a creature-entry lock (Lethal Vapors,
    Spreading Plague, Suleiman's Legacy, Eye of Singularity): a standing term
    for the creature cards a seat holds while one stands, read only on a
    rehearsal copy (CR 400.2: `ai_prompt_picks` asks `seat_standing` of the
    real table), which must not make casting a creature into the lock free.
  - Power Conduit and Spike Rogue are never activated:
    `ai_abilities._activation_candidate` declines every
    `remove_counter_filter` cost. Parts: the sacrifice weighing's twin (each
    permanent and counter kind, rehearsed with the whole cost paid), an
    `ActivationAction.cost_counter_kind` that `activation_announcement`
    forwards, and a standing that prices charge, fate and age counters.
  - Quicksilver Elemental's {U} is never proposed: a two-step rehearsal (the
    chooser again over the gained abilities, on the copy where the gain
    resolved) and `ai_payment._plan_land_taps` honouring the activation's
    "spend blue mana as though it were any color".
  - Vhati il-Dal's mode is the `choose_one` default (its first, "base
    power"): `ai_prompt_picks` does not weigh the two.
  - Krark's Thumb's `ignore_coin` default
    (`choices/numbers._default_ignore_coin`) keeps the win or heads where the
    loss is better (Puppet's Verdict against bigger creatures, Winter Sky,
    Impulsive Maneuvers on an opponent's attacker): a reader in
    `ai_prompt_picks` that rehearses both coins.
  - Tricks around the blocks. The rehearsal copy's fight answers the
    deciding seat's own abilities after the blocks since kg5
    (`ai_rehearsal._fight_priority_driver`); not read: a turn-up after the
    blocks or in the end step, and a Licid's `end_own_continuous_effect` in
    response (`ai_special_actions.special_action_in_response` asks the
    response window alone); an instant held for the blocks (the cast chooser
    does not price a card's other uses against holding it: Healing Salve's
    life mode was cast where its shield was held for); the opponent's tricks,
    whose hand on the copy is a redeal (M21 seed 7 lost Keen Glidemaster to
    Heartfire Immolator); an unblocked attacker's pump; and inside a
    rehearsal the attack policy still reads printed bodies.
  - Combat and Aura prices: a payable toll's own price reads zero
    (`ai_combat_triggers._walk_toll`); a host kill that takes several
    activations is never chosen (`ai_targets._host_its_ability_kills`);
    Consuming Ferocity's printed +1/+0 keeps it on its caster's creature
    (`_HOST_GIFT`); Crown of Suspicion's sacrifice ability is not read;
    Lumengrid Augur's untap payoff is unpriced (it breaks ties only); a
    one-shot certainly lost stays unpriced by design (when to spend one is a
    timing question).
  - Picks (kg5 `ai2`): `ai_slot_targets._role_chain`'s graveyard roles rank by
    mana value with no can-enter check (Cruel Revival returns to a hand, so
    no shipped card); a return to a library is unranked (Bone Harvest,
    Reinforcements, Misinformation); Adarkar Unicorn's "{U} or {C}{U}" is not
    a shape `planned_mana_yield` states, and cumulative upkeep is not a
    `_PaymentPlanner` purpose; the 106 battlefield abilities whose cost
    discards a card outside madness stay declined by policy.
  - Overload is kicked against a two-drop (INV seed 7):
    `ai_casts._times_worth_taking` takes "kicked" whenever the lands can pay,
    the main phase's policy, which the instant-speed builder shares since
    kg5.
  - From Darksteel's W2G2, each measured: **a spell that does nothing is
    proposed when a cast trigger pays for it** — the rehearsal gives the
    spell's card back on the premise that every cast spends one, so the
    Feather cycle's 1 life nets it positive (Hallow in response to Aether
    Vial, a defender's Tears of Rage, seed 4242). Part: `ai_rehearsal.
    _rehearse` resolves only the objects above the spell (its cast triggers,
    CR 603.3) and reads the standing there; if the spell's own resolution
    moves nothing beyond that, the card is not given back. **Weights held
    for the owner's call**: Eater of Days is always cast (body 34.9 against
    two `SKIPPED_TURN_WORTH` 16; permanents are not rehearsed); Lich's Tomb
    scores a flat 2.3 at any life (part: a cast gate weighing the "don't
    lose" static against the seat's life); Death Cloud's X=6 at 10 life read
    +26.5 on its board, consistent with the standing. Seen in W2G1's whole
    game: Nourish cast at 17 life with nothing threatening, and an untapped
    Nim Abomination left to cost 3 life three end steps running. Found by
    reading: Aggravated Assault's second-main activation is not read through
    the combat it adds (`_read_through_the_fight` gates on
    `combat_is_still_to_come` first); Aether Vial is never activated in the
    simulations because the creatures it would put are cast for mana first
    (the doors' order); Panoptic Mirror's imprint picks the lowest slot among
    cards of one mana value.
  *Clears:* the next AI round.

- **Three mana readers still skip what a substitution does** (kg5 `mana2`,
  `scratch/kg5/mana2/probe_gaps.py`). (a) `land_mana_swaps.payment_colors`
  starts from the printed summary, not from what a bare tap makes: Henge of
  Ramos under Hall of Gemstone's {R} is offered {R} and {C}, and a tap asked
  for {R} makes {C} (School of the Unseen and Castle Sengir are presumably
  the same; only the Henge was driven) — part: `_base_symbols` reads
  `board_payment.tap_alone_symbols`, guarding the controller lookup for a
  land that has left when its tap event runs. (b) CR 106.7's fixpoint misses
  a granted any-colour ability: `mana_could_produce.lands_could_produce`
  reads the summary, so a Forest under Overlaid Terrain "could produce" {G}
  alone. (c) The three hookless `plan_payment` calls in `legality_cast_spec`
  (`cast_cost_offers`' kicker payable flag and repeatable-offer count,
  `_optional_x_ceiling`) see no substitution, so a Plains under Infernal
  Darkness pays {W} — part: pass `produces=self._land_payment_colors`; the AI
  reads them, so it needs its own differential. *Clears:* a mana round.

- **A counted search that splits its finds between the battlefield and
  another zone still refuses a card phrase that can name an instant or
  sorcery** (`lowering/search.MIXED_SLOTS_ADMIT_A_NONPERMANENT`). Every other
  road onto the battlefield asks CR 400.4a and CR 614.17 before it takes the
  card since kg5 (`permanent_cards.stays_out_of_battlefield`; every caller of
  `_put_permanent_onto_battlefield` held by
  `tests/engine/test_kg5_kindred_entry_roads.py`), but this finder says which
  find fills which slot only after the finds have left their zones. Parts:
  `choices/search._resolve_search_library_picks` leaves a find that cannot
  enter in its zone and marks it on the `search_destination` prompt beside
  `_cards` and the searched seat; `_place_found_card` takes such a find only
  into a slot that is not the battlefield; `_default_search_destination`
  fills the other slots with such finds first. Beside it, not an entry road:
  "Reveal the top card of your library. If it's a Goblin card, put it into
  your hand" refuses (`lowering/reveal._lower_reveal_top` tests one card
  type; `revealed_card_is` reads a creature type since kg5). No shipped card
  prints either (Cultivate's finds are basic lands). *Clears:* the set that
  prints one.

- **A copy of a roles spell, or of one printing "target" twice with
  different descriptions, keeps the original's targets.** Since kg5 a copy
  is offered new targets slot by slot on every road, several targets and
  modes included (`stack_targets.change_slots`, CR 115.7d's
  `new_target_options` / `may_keep_target`; a person answers one
  `retarget_choice` per slot). Left (kg5 `airesp`): Donate, Decimate,
  Cultural Exchange, Hull Breach's third mode and Reign of Chaos
  (`change_slots` refuses the role channel, `_CHANGEABLE_CHANNELS`; 33 census
  rows), and Deadshot, Fiery Justice, Gaea's Blessing, Dwell on the Past and
  Krosan Reclamation (two descriptions). Parts: a per-role candidate walk
  (`legality_roles._role_target_walk`) and a role-channel writer in
  `stack_targets.apply_target_change`. The AI's re-aim is greedy per slot
  (`ai_prompts.choose_copy_new_targets`), not a joint optimum. *Clears:* any
  targets round.

- **Mishra's War Machine and Minion of Leshrac never offer their damage.**
  `phases/upkeep_effects._on__upkeep_self__upkeep_damage_unless_cost`
  discards `hand[0]` for the War Machine with nobody asked, where its ruling
  (2004-10-04) lets its controller take the 3 damage instead; the Minion asks
  which creature to sacrifice and never offers the 5
  (`scratch/kg5/costs/probe_wm.py`). Part: lower both as a `may` whose action
  is the discard or the sacrifice and whose `otherwise` is the damage and a
  tap that asks whether the damage was dealt (the Minion's 2008-10-01 ruling:
  damage all prevented, no tap). *Clears:* the round that takes the fused
  upkeep kinds.

- **A copy's name in the effect handlers' sentences** (CR 707.2). Since kg5
  a permanent is named by its name (`effective_card.name`) on the wire
  (`printed_name` beside it) and in the engine's offered lists, refusals,
  stack lines and state-based-action lines, and an ability by its source
  (`stack_targets.source_name`;
  `tests/engine/test_kg5_copies_copy_name_census.py`). Left, from kg5
  `copies`' site census (275 sites over 3,149 copies,
  `scratch/kg5/copies/census_dyn.py`): (1) `engine/handlers/*`, 228 sites —
  an ability's source read as `context.card.name`, the source's printed card
  ("Clone dealt 1 damage to P1"), and a subject as `perm.card.name`
  ("Lightning Bolt dealt 3 damage to Clone"); (2) the delayed triggers'
  names (`handlers/delayed.py` stores `source_name=context.card.name`;
  `delayed_triggers`' mark events carry no source permanent, so "Clone
  ability resolved" at end of combat); (3) `activation_charges.py`'s twelve
  cost-payment lines ("A sacrificed Clone to activate its ability"); (4) the
  107 prompt `card_name` labels the handlers arm, and the `choices/*` answer
  lines echoing them; (5) `prevention/*`, `replacements/redirects.py`,
  `replacements/damage_substitutions.py`, `mixins/effects.py`'s life lines
  and `ai_combat.py`. Each is `source_name(context)` or
  `effective_card.name`, swept census-driven, and never a protocol key
  (`dead_name`, `lock_card_in_hand`, `control_seam`'s wire-addressing reads
  find the physical card). And the client's prompt panel reads "Blockers: 0"
  for a blocker whose attacker left combat (`app.js` counts the
  `combat.blockers` pairs; the canvas draws it in combat since kg5).
  *Clears:* a handlers round with no other group in the handlers (the
  sweep); a client round (the count).

- **A seeded web session does not seed the game's RNG.** The session's seed
  (`SessionStore._resolve_seed`, `web/session_store.py`) builds the decks
  (the seed plus the seat) and flips the pregame coin (`random.Random(seed +
  2)` in `_begin_pregame`); the opening shuffle and every later shuffle, flip
  and random pick read the module-level `random`, wherever the process's
  earlier work left it. So two web games on one seed differ (kg5 `webturn2`),
  and a web census's games depended on the order its tests ran in:
  `tests/ui/test_kg5_webturn2_ai_vs_ai_casts.py` passed in a meeting run and
  failed in a folder run of the same tree until it called `random.seed(seed)`
  before creating its session. Part: the session's seed seeds the game's RNG
  at the deal, as `run_ai_simulation` seeds the module RNG; sessions in one
  server share that RNG, so one game per seed beside another table needs the
  engine's random reads on an RNG the game owns. *Clears:* a web round.

- **Darksteel's engine and client leftovers, each measured.** (a) A damage
  redirect re-issues the damage as a separate event, so a creature dealt
  Incinerate's or Flamebreak's damage through a redirect is not stamped
  "can't be regenerated" (`handlers/damage._after_dealt` reads the original
  event; no ruling covers it). (b) The engine log names a restricted mana's
  raw key ("spendable only on artifact_or_artifact_ability",
  `handlers/mana.py`) where the wire's `restricted_mana_words` has the
  sentence. (c) A granted ability's served text is lowercased by the Aura
  reader ("{t}, unattach Heartseeker: …"). (d) To respond to a spell a person
  must click it on the canvas stack within about a second, before the
  client's auto-pass; Leonin Battlemage's "you may untap" is asked on every
  cast while it is already untapped. (e) Not driven in a browser: Sundering
  Titan's leaves-the-battlefield trigger, Leonin Bola's and Surestrike
  Trident's granted abilities (text checked), the Cataclysm and Planar
  Overlay paths of the restructured keep modal. *Clears:* (a) a damage
  round; (b)–(e) a client round.

- **What the pre-Fifth-Dawn round left** (pre5dn cleared the rest of
  Darksteel's toolkit wishes: `oracle_diff`'s defaulted fields, `snapshot
  --rev`, `probe_line --ast` and its raise site, `--require`, `fails_before.sh`,
  `tests_for_diff`'s base, LF and `--ingest`, the canvas position accessor and
  `serve_board.py --reload`). Left: no `explain_cast` for an activation
  (W2G2 spied on `_land_ability_worth` by hand); `--ingest` names ~495 tests
  because ten sharded AI censuses walk both roles — `stable_sample` always
  taking the measured set's cards and sampling the rest would cut it (T2's
  proposal, `tests/helpers.py`); and three of the profiler's speed items not
  taken: the continuous-effect recompute inside every state-based pass
  changes nothing ≥98.3% of the time (a dirty marker under
  `fast_paths.CHECKING`; a missed invalidation is a stale P/T or type, so
  high risk; ~7% of the full pass), backwards censuses re-run whole (~858 s;
  a smaller sample weakens what they prove), and the state-based pass's own
  internals (ten sweeps a pass, `has_supertype`). Its profiles are in
  `scratch/pre5dn/p1/`. *Clears:* a speed round with `fast_paths.CHECKING`
  runs as its gate; the rest a toolkit round.
