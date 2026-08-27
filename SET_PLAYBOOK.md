# Set implementation playbook

**Hand-written. Not generated.** Every other ALL-CAPS file at this level is a
tracker a script rewrites; this one is maintained by the person or agent who
just finished a set, in Phase 6 below. If you are reading this with no memory
of writing it, that is by design: trust the phase text as current truth and
the changelog at the bottom as history.

A set's lifecycle is `absent → measured → sets` in `cards/manifest.json`.
"Done" means the entry **moves** from `measured` to `sets` — the
machine-checked claim that every card in it is supported, enforced by
`tests/engine/test_front_end_safety.py` and `tests/engine/test_card_format.py`,
with the role split itself guarded by `tests/engine/test_manifest_roles.py`.
CLAUDE.md's "The manifest has two roles" explains why the split exists; this
document is the process that walks a set through it. **A set is not finished
until Phase 6 has run.**

This playbook owns *sequence and gates* — which steps, in what order, with
what exit criteria. It owns nothing else. The per-card recipe belongs to
`engine/ARCHITECTURE.md` ("Adding support for a new card"), test placement to
`tests/sets/README.md`, script invocations to CLAUDE.md's Commands section,
and the work queue to `GRAMMAR_COVERAGE.md`'s backlog table. No number a
tracker owns appears here, so finishing a set changes this file only where the
*process* changed.

**Execution model:** analysis may fan out, implementation is serial. Read-only
classification of a backlog — which cards need which machinery — parallelizes
well and is sanctioned in Phase 2. Edits to the grammar
(`engine/grammar/parser.py`, `lower.py`, the effect families) land one at a
time: concurrent edits break the differential guard, a lesson ROADMAP.md
records from the first parallel implementation pass.

**Parallelising the rounds themselves** is possible in one of two shapes,
and the difference is where the serial step lives. With *worktree
isolation*, each group edits its own copy of the repo and authorship
parallelises — the serial rule then applies to **integration**: merge one
branch at a time, running the full suite and every `--check` between merges,
because two groups that each pass alone can still collide in
`lowering/categories.py`, `effect_labels.py` or `tests/sets/`. Worktree
isolation **works** (verified 2026-08-23: `git worktree add` succeeds, the
worktree imports its *own* copy of `engine/` — no editable-install redirect
back to the main checkout — and the suite runs inside it through the main
checkout's venv by absolute path). An earlier note here said the repo
refused it; that refusal was an agent *sandbox* reading the worktree's
`.git`-file redirect into the main repo as a write outside itself — a
property of the harness's managed isolation, not of git. Create worktrees
with plain `git worktree add <dir> -b <branch>` and point agents at them.

**Two merge hazards where taking either side passes the suite.** Resolving a
conflict by picking a side is safe only when one side is the whole truth, and
Legends produced two rounds where it was not. Two branches **deleted a
different entry at the same spot** in a registry, so git presented each side as
"keeping" the other's deletion — taking either resurrects a dead entry, green.
And two branches **rewrote the same function**, each carrying a fix the other
lacked (one made a loop resumable and corrected an arity bug, the other taught
it to iterate a recorded set) — taking either silently drops the other's fix.
Read both sides for what each *adds*, and union unless they genuinely
contradict. Same reason the duplicate-helper scan exists: a clean textual merge
is not a clean merge.
Where worktrees are unavailable, fan out **design** instead:
each agent verifies its group against the live compiler and returns an
exact spec — file, function, current code, replacement code, tests — and
one applier lands them in sequence. The second shape is slower per round but
keeps the differential intact, and the specs are reviewable in a way a merge
conflict is not.

Budget the fan-out before starting it. A group agent that reads the docs,
probes the compiler and writes a spec is not cheap, and several of them share
the session's request budget with the main loop — four at once exhausted it
here and returned nothing, which cost the round rather than parallelising it.
Two agents that finish beat four that die: launch the number you can afford
to see through, and prefer one round's worth of groups at a time.

## Known gaps / pending pre-work

A drainable list of things the playbook knows are not yet true, each naming
the phase that clears it. A retrospective that drains an item deletes it; a
set that hits a new one adds it.

The list is empty. The two items it held drained after the M21 promotion:
`scripts/set_progress.py` and `CARD_VERIFICATION.md` regeneration joined CI's
tracker-freshness step (the deferred decision came due — the roadmap read "19
untested cards" for a week while the true number was 299), and
`SET_PROGRESS.md` now reports a `measured`-role set as "Measured (N/M
supported, not shipped)" rather than a bare "Partial".

## Phase 0 — Pre-flight

**Entry:** a set has been chosen. **Exit:** clean tree, every gate green,
instruments current.

1. Run the full suite and every `--check` gate, then the tracker
   regenerations from `.github/workflows/ci.yml`'s freshness step — all must
   be a no-op on a clean tree. Starting a set on a red or stale HEAD
   conflates pre-existing drift with the set's own diffs.
2. If the set postdates `data/vocabulary/manifest.json`'s `fetched_at`, run
   `scripts/fetch_vocabulary.py` (network) and commit the vocabulary diff on
   its own. A creature type or keyword the vocabulary has never heard of does
   not fail loudly later — it refuses to parse in a way that looks exactly
   like a grammar gap, and gets debugged as one.
3. Clear anything above in Known gaps marked for Phase 0.

## Phase 1 — Ingest and measure

**Entry:** Phase 0 exit. **Exit:** the set sits under `measured`, the suite
is green, the trackers carry its row, and the census is in hand.

1. `python scripts/ingest_set.py <CODE> --fetch`, then append one entry under
   `measured` in `cards/manifest.json`. That is the whole registration — the
   web app, the fixtures and the coverage scripts all read the manifest
   (`tests/sets/README.md`, "Adding a set").
2. Run the full suite and **treat what fires as yield, not noise**. A new
   set's text reaches code the old pool never executed; the M21 ingest
   surfaced a never-run import that was 66 failures waiting. These are engine
   bugs, found early and cheap — fix them now.
3. Regenerate the trackers. The set appears as a *(measured)* row in
   `GRAMMAR_COVERAGE.md` and `HOOK_RELIANCE.md`; the floors and ceilings do
   not move, by design.
4. Record the census: `python scripts/support_report.py --set <CODE>` — total,
   supported, and the unsupported-reason histogram. This is the input to
   Phase 2. Know what the histogram is: each reason quotes only the **first**
   refused line of its card, so a card counted under a keyword may carry three
   more gaps behind it — the histogram sizes the buckets, it does not promise
   a bucket's fix supports its cards. `--refusals` is the whole list: every
   refused line of every unsupported card with the grammar's exact refusal
   site, plus a rollup by site — run it too, and plan Phase 3's rounds from
   it rather than re-probing the compiler card by card.

## Phase 2 — Machinery census (the big rocks)

**Entry:** the census exists. **Exit:** every unsupported card is assigned to
exactly one bucket, and a round plan has been opened as the set's journal
entry in ROADMAP.md.

The census question: *what does this set need that no amount of per-card work
provides?* Three sweeps, in order of blast radius:

1. **Card types and layouts.** `test_card_format.py` holds the shipped pool
   to known layouts and the support gate to known types, so a set carrying
   planeswalkers, split/transform/adventure/modal-double-faced cards, or any
   other new machine cannot promote regardless of text work. Each of these is
   a subsystem project (new CR sections, new zones of behaviour). Scope them
   first — they gate Phase 4 absolutely and their size decides whether the
   set is one session or ten.
2. **Keywords.** Diff the set's keyword lines against
   `vocabulary.IMPLEMENTED_KEYWORDS` — **and against
   `oracle.UNSUPPORTED_KEYWORDS`, which is a third table and outranks both.**
   That set is matched against the *ingested* `keywords` field before any line
   is classified, so a keyword can be implemented in full and still cost every
   card that prints it: Legends' rampage had working behaviour and three
   passing CR-cited tests while all seven of its cards compiled unsupported.
   The registry diff alone reports such a keyword as *missing*, which sends the
   round off to build what is already there. Each genuinely missing keyword is
   one frozenset entry plus behaviour that covers **everywhere the CR says it
   applies, not just the paths this pool exercises** — CLAUDE.md's lifelink
   precedent is the cautionary tale. Keyword tests go in `tests/rules/` with
   `@pytest.mark.cr` markers; widen `scripts/rules_progress.py`'s `SCOPE` if
   the CR section is new. Keywords usually open Phase 3: highest
   cards-unlocked-per-change in the census.
3. **Everything else** goes to the backlog via `GRAMMAR_COVERAGE.md`'s
   reason table, sorted by the Lines/Distinct ratio — many lines over few
   distinct shapes is where a production pays best.

   Rank by the **sentence shape**, never by a word the sentences share. Legends'
   largest census bucket was "prevention", nineteen cards; it took two rounds to
   reach eight of them and needed four different mechanisms, because "prevent"
   is a verb rather than a template. The bucket that actually paid was the one
   where nineteen cards printed *the same sentence with one word changed*.

Optional tactic, recorded because it worked: fan out read-only subagents to
classify the unsupported cards into *implementable now* (recipe steps 2–3),
*needs a new handler*, and *blocked on a subsystem*, then merge the
classification serially. Implementation never fans out (see the execution
model above). Have the classifiers **compile, not read**: running each
refused line through the live grammar names the exact refusal site and
catches what eyeballing misses — the M21 census found cards whose reason
string hid a second gap, and a set of unanchored trigger regexes that would
have compiled cards firing on the wrong event had the effect side been fixed
first.

Ask each group for two things the census cannot give you: **what its brief
got wrong**, and **which already-supported cards its group silently
mis-plays**. A card is supported when *any* of its lines is, so a whole
mechanic can be missing while every card printing it reports fine —
M21's scry was absent from the engine entirely while seven cards carrying it
compiled clean, and a shipped ability's cost was parsed by the grammar and
charged by nobody. `support_report.py` counts cards; these are sentences, and
only something that reads the compiled program line by line will find them.

## Phase 3 — Backlog rounds (generalise first)

**Entry:** the round plan exists, and `set_pool("<CODE>")` resolves the
measured set so per-card tests can land as the cards do. **Exit:**
`support_report.py --set <CODE>` reports every card supported.

1. Each round, pick the card whose gap is **not about that card** — the
   change that clears the most other cards. ROADMAP.md's Revised narrative is
   the worked example: six cards, then three, then three, then one, then
   none, each round opening with the most general gap left. Apply
   `engine/ARCHITECTURE.md`'s recipe top-down and stop at the first covering
   step. A name-keyed hook only under `card_hooks.py`'s entry bar — no second
   card, real or plausibly printable, shares the shape — and a hook-reliance
   ceiling raise is a decision recorded in the commit, not maintenance.
   When a change widens a *gate* (a line admitted that used to be refused, or
   admitted under a different classification), grep for readers keyed on the
   old classification before trusting the suite — behaviour that read the
   refused shape can go quietly missing, and the guard that catches it may
   sit far from the gate. M21's keyword round moved standalone protection
   lines from static to keyword classification and would have dropped the
   shield had `tests/rules/test_protection.py` not been in the first targeted
   run.
   A printed **restriction** is only done when something enforces it. The
   failure is not a crash and not a missing ability — it is an ability that
   works *more often than the card allows*, wrong in the player's favour and
   silent (M21 round 138: "Activate only during your upkeep" clauses parsed
   and never checked). So a restriction clause lands as a table the support
   gate reads too (`activation_restrictions.py` is the model), never as a
   parsed-and-dropped rider.
   And a **guard that asks where a name appears is satisfied by the
   declaration it guards**: round 140 found a trigger condition that sat in
   both front-end tables, compiled real instructions on two supported cards,
   and fired nowhere — `test_trigger_dispatchers` passed because the
   declaration itself was a place the engine "named the kind". Point a
   census classifier or a guard at the corpus that *acts* (emit sites, the
   registries, the sweeps), not at where the name occurs.
   **When a round extends a fragment production, look for the other one
   first.** Round 8 went to add an alternative to "the" where-clause parser and
   found two, accepting different definitions — so which definitions a card
   could use depended on which sentence it printed them in. Nothing was failing
   and no guard could have caught it: both halves worked. A fork in a *fragment*
   is only ever found by someone extending it, which makes the extension the
   moment to grep.

   **And write a refusing gate's refusal test before trusting the gate.** A
   production that ends in a catch-all has to parse the tail itself and refuse
   what it cannot read. Round 7's did, and the test written to prove it found
   that it accepted "creatures with three heads" as a keyword filter — which,
   in a whitelist, is a creature nothing can legally block. The positive cases
   all passed.

   **A refusal site is a work-list entry, not a diagnosis — record which
   *layer* each failure is in.** `--refusals` names where the parser stopped,
   which is often the generic error for an unfinished line and names a
   production that already works. Legends lost three rounds to this: a scoping
   note written from a refusal site was carried between rounds and was wrong
   four times running, always the same way — the failure attributed to the
   nearest interesting-looking clause rather than the one that failed. Probing
   each sentence individually and writing down *parse / lowering / no handler /
   gate* turned three "needs a subsystem" estimates into work already done, and
   the reverse once (a gap reported as one piece was two, in two layers).
   Treat an inherited estimate as a lead, and ask the next reader to correct
   it rather than to trust it.

   **A refusal can expire without anything failing.** A gate that declines for
   a reason that later stops being true keeps declining, silently and in the
   direction of doing less, and no test goes red. Legends found two: a
   "whole effect is optional" refusal whose stated reason (the prompt rode a
   queue only a triggered ability drained) stopped holding two rounds later,
   and a cost/benefit refusal that was correct at forty cards left and wrong at
   seven. When a round builds machinery near an old decline, re-probe the
   decline.

   **A decline that names the exact missing piece is a mechanism, not an
   absence.** Infinite Authority was declined by seven rounds and landed
   without a round of its own: each decline listed its gaps, and other cards
   that needed those pieces built them until the card fell out. The
   distinction that makes this work is between "too big for this round" and
   "here are the four things, individually named" — only the second
   compounds.

   **A guard that iterates a hand-maintained list needs an assertion that the
   list is complete.** Otherwise a new entry escapes the guard by being
   forgotten — silently, with the suite green. Three were found in one day of
   Legends work (the grammar layer order, the family lists, and the same
   family guard catching a family added an hour later), and at promotion three
   more turned out to be second copies *inside* guards written to catch second
   copies.

2. Every card lands with a focused test in `tests/sets/test_<set>_cards.py`
   (conventions and the split-by-type rule: `tests/sets/README.md`). A new
   set needs zero `tests/conftest.py` changes; the fixture factory covers any
   manifest set, and the convention guard holds it to that.
3. Between rounds: the supported count from `support_report.py --set <CODE>`
   must have risen; regenerate the trackers; run any `--accept` only after
   reading the diff it blesses. **And the exit is two numbers, not one**:
   `--hollow-lines` must also reach zero — **check it every round, not at the
   end**. Legends reached 310/310 supported with fourteen abilities still
   instruction-less, and only Phase 4 caught them; each was a card that
   compiled, reported supported, and did nothing when activated. A card is supported when *any* of its
   lines is, so a set can read 85/85 with three cards doing less than they
   print — Antiquities did, for thirty rounds. Take the split a grammar size
   guard asks for when it fires, too: the family boundary is easiest to see
   while the work that crossed the line is still in hand.
4. Append the round's narrative to the set's ROADMAP.md entry as you go —
   what the round bought, what it cost, what it exposed. Numbers live there,
   not here.

## Phase 4 — Promotion gate

**Entry:** every card supported. **Exit:** one promotion commit, every gate
green, the trackers agreeing the set ships.

Step 1 is a **rehearsal**, and it is implementation work rather than a
formality — budget for it. Move the manifest entry from `measured` to `sets`
locally and run everything *before* committing. Promotion instantly widens
every `load_catalog()`-driven guard — the catalog sweep, card coverage,
no-hollow-support, behaviour classes — and `parse_coverage.py` sees the set
for the first time (measured sets are invisible to it), so parse debt
surfaces here by construction. Read every new finding before accepting
anything.

**Expect two kinds of failure and do not guess which is which — run the card.**
Legends' rehearsal turned eleven guards red and the split was the opposite of
intuition in both directions. Fourteen abilities the hollow-lines report named
were **genuinely inert** — compiling, reporting supported, doing nothing when
activated — while twelve static lines that looked broken were **all working**,
and it was the guard that had gone stale (it kept a hand-written copy of the
compiler's derivation-table list: 13 tables where the compiler has 18). A third
category came from `parse_coverage.py` seeing the set for the first time: four
clauses nothing implemented at all, one an uncapped activation limit on a card
reporting supported. The report's own footer states the test — give the
behaviour a game and watch it happen — and it is the only way to tell the three
apart.

**Read the guards themselves as suspects.** Four second-copies-of-one-fact came
out of this rehearsal and three were *inside* guards written to catch exactly
that, each inventing a disagreement it then reported. A guard that re-spells
the thing it checks is the most expensive kind, because its failures look like
real findings.

The checklist, each line naming its guard:

- `tests/engine/test_front_end_safety.py` — the catalog is 100% supported,
  and no card lost an instruction to the grammar.
- `tests/engine/test_card_format.py` — ingested fields only, known layouts,
  required fields, reprints deduped by `oracle_id`. Its `KNOWN_UNSUPPORTED`
  and the sweep's `SWEEP_EXCLUSIONS` are sanctioned escape hatches, held
  empty by preference; any entry needs a written reason and a mention in the
  Phase 6 retrospective.
- `tests/engine/test_manifest_roles.py` — the roles stayed disjoint; the
  move was a move, not a copy.
- The pool-wide sweeps: catalog sweep, card coverage,
  `test_no_hollow_support.py`, `test_effect_labels.py`.
- `scripts/parse_coverage.py --check`, then `--accept-probe` only after
  reading what the deletion probe found.
- `scripts/grammar_coverage.py --accept` and `scripts/hook_reliance.py
  --accept` — the set joins the All row, the floors and the ceilings; both
  diffs get read, because accepting is the review.
- `scripts/behaviour_classes.py --accept` — the set adds classes; the
  largest class must stay under a tenth of the catalog, and the diff is the
  review (the script exits before diffing once told to accept).
- `python scripts/set_progress.py` — CI's freshness step now regenerates it
  and fails on a diff, so a stale run here is caught rather than shipped.
- CLAUDE.md's pool description names the new set and counts.

## Phase 5 — Post-promotion verification

**Entry:** the promotion landed. **Exit:** the verification tracker has
caught up, or the remaining delta is recorded in the retrospective with a
plan.

In-game verification is **deliberately not a promotion gate** — a decision,
stated here so a future retrospective can reverse it on purpose rather than
by drift. The burden is the set's new cards minus those reported
`equivalent` through a passing behaviour-class peer (derived on read; see
CLAUDE.md's verification tracker section), so Phase 4's behaviour-class
review directly shrinks this phase.

1. Work the untested cards through the in-game Debug Menu (the only writer
   of `CARD_VERIFICATION.md`).
2. Smoke the set where a player meets it: the web app serves it, its cards
   are deckable, one human-vs-AI pass via the `run-magic` skill.
3. `scripts/simulate_ai_games.py` — a seeded run is byte-identical unless a
   fix legitimately changed AI-visible behaviour, in which case the change is
   named in the retrospective.

## Phase 6 — Retrospective and playbook update

**Entry:** Phases 4–5 done (or the session is ending mid-set — a partial
retrospective beats none). **Exit:** *this file contains no instruction the
set's execution proved wrong.*

1. Close the set's ROADMAP.md journal entry: what held, what it cost, the
   final numbers. Numbers go there, never here.
2. Diff this playbook against what actually happened, three questions:
   - **Engine changes** — a new subsystem or seam the set forced gets one
     pointer line in the phase that meets it (the real documentation lives in
     `engine/ARCHITECTURE.md` and CLAUDE.md, which the change itself already
     updated).
   - **Process changes** — edit the phase text **in place**. The next reader
     gets current truth, never a patch series to reconstruct.
   - **New sharp edges** — add to Known gaps, naming the phase that will
     clear them.
3. Append one bounded entry (five to ten lines) to the changelog below: set
   code, date, what changed in this file and why, what was drained from
   Known gaps.

## Per-set retrospectives

Append-only. The audit trail for why the phase text above says what it says.

**M21 — 2026-08-10 (partial: Phases 0–3, round 1; set still measured).**
The playbook's first execution, in the session that wrote it. Phase 0 drained
the two pre-work gaps it opened with: the measured-set fixture seam
(`manifest_set_path` gained `include_measured`; `set_pool("M21")` resolves)
and the stale tracker rows. The census ran as three compile-driven read-only
classifiers; round 1 took the six keywords (106 → 110 supported). Playbook
edits from this run: Phase 1 now warns that a census reason names only the
first refused line; Phase 2's classifier tactic now says compile-not-read;
Phase 3 gained the widened-gate rule (grep for readers keyed on the old
classification). Remaining Known-gaps items stand unchanged.

**M21 — 2026-08-10, later the same day (rounds 2–4; 110 → 120).** ROADMAP
trimmed to the live work (history in git at `22bd726`), then three rounds
executed off the census ranking: token naming (CR 111.4), counters on
non-source subjects, each-opponent recipients. No playbook text needed
changing — the round loop ran as written; one confirmation worth recording:
a round whose direct yield is small (round 3, one card) is still right to
take when ranked machinery sits under later cards, exactly as Phase 3's
generalise-first rule intends. Round 5 (keyword grants, 120 → 123) extended
the same session; the ROADMAP entry carries the numbers and the next
ranking (search templates first).

**M21 — 2026-08-11 (rounds 9–11, three groups in parallel; 128 → 137).**
The first fan-out over *implementation* groups. Two process findings, both
now in the phase text above: the parallel-round shapes and their budget, and
this one, which changed Phase 2 — **a design agent should compile, and it
should be asked what it finds beyond its brief.** All three specs corrected
their instructions on evidence (scry is CR 701.22, not 701.18; "See the
Truth" contains no scry at all), and two found live silent wrongness nobody
had asked about: seven cards compiling supported while their scry line
produced nothing, and a shipped-pool ability whose cost was parsed and never
charged. Both were invisible to `support_report.py`, because a card is
supported when *any* line is — the census counts cards, not sentences, and
the thing to ask a group agent for is the sentences its group drops.

**M21 — 2026-08-11 (rounds 12–14, three more groups in parallel; 137 → 137).**
The flat number is the finding. Two of the three rounds *withdrew* cards —
Rewind was untapping one land of "up to four", Adherent of Hope was putting
its counter down without the planeswalker its text requires — and one fixed a
mode that resolved having done nothing. **A round that lowers the supported
count can be the most valuable one in a set**, and Phase 3's "the count must
have risen" check is therefore a prompt to look, not a gate: when it falls,
the entry in the ROADMAP has to say which card left and what it was doing
wrong. What made all three findable was asking each agent the two questions
above; the third one also found that a *previous round of this same effort*
had shipped a card whose test asserted the bug. Ask the question about the
cards you supported last round, not only about the ones you are adding.

**M21 — 2026-08-11 (round 15, three groups; nothing shipped).** The round that
justifies the whole design-first shape. All three specs came back, none was
applied, and the round was still worth running: two of them found live defects
that have to be fixed *before* the feature work they were asked for — including
one this effort had introduced two rounds earlier. **A spec that says "do not
build what you asked me to build yet, and here is why" is the most valuable
thing a group agent returns**, so the brief must leave room for it: ask what
the group needs *first*, not only what it can deliver. The playbook's phase
text is unchanged; what changed is Phase 3's stopping rule — **a round may
correctly end with a revert.** The planeswalker stage was applied, surfaced an
interaction in a seam nobody had questioned, and was reverted rather than
shipped half-understood; the ROADMAP entry records what was learned so the next
attempt starts from it instead of rediscovering it.

**M21 — 2026-08-11 (round 16, round 15's three fixes applied; 137 → 134).** The
second round to *lower* the count, and the first where lowering it was the
stated goal: three permanents were reporting support with no ability the engine
could read. Two lessons for the phase text. **A spec's diagnosis is a hypothesis
until it is measured** — round 15 named `Nine Lives` as sharing Mazemind Tome's
shape and it does not (it has one supported trigger), while the conjunct the
spec said kept Howling Mine legitimate turns out not to be the one doing it.
Both were found by running the classifier over the pool before writing the gate,
which is Phase 2's census applied to a fix rather than to a set. **And verify
the fix against the real path, not against the repro that found the bug** —
round 15's P0 transcript executed a card's instructions by hand, which showed a
real ordering bug but hid a second one underneath it: on the actual cast path
Opt's second printed line never ran at all. Both are fixed, and the second would
not have been found by making the first one's test pass. Note also what the
supported count does *not* measure: three cards stopped playing as strictly
smaller cards this round and the number did not move for any of them. See
ROADMAP round 16.

**M21 — 2026-08-11 (round 17, multi-targeting; 134 → 136).** Two lessons about
scoping a round, both from the census rather than from the plan. **Sort the
backlog by the shape of the fix, not by the cards that prompted it** — the two
cards this round was scheduled around ("Rewind and Basri's Acolyte") turned out
to need different mechanisms, one a targeting question and one a
resolution-time choice, and counting the pool's lines showed the targeted family
was six lines to Rewind's one. **And land a multi-layer feature in dependency
order, with the grammar last.** The production that flips the cards was written
after the resolver, the handler, the picker spec, the AI and the browser prompt,
so at every intermediate point the cards stayed honestly unsupported rather than
becoming castable with half their targets collected. See ROADMAP round 17.

**M21 — 2026-08-19 (rounds 18–140, promoted at round 138; 136 → 285, shipped).**
The closing entry, written a day after the promotion it records — 120 rounds
ran without one, which is itself the finding: **run Phase 6 at promotion, not
when the next set forces it**, or the phase text goes stale exactly when a new
operator needs it. Final numbers live in ROADMAP rounds 138–140: 285/285
supported with **zero name-keyed hooks**, hook reliance on the whole pool
nearly halved, grammar floors up on every axis. Two lessons moved into Phase 3
above: the unenforced-restriction class (an ability that works more often than
the card allows — round 138's `activation_restrictions.py`), and the
dispatcher guard a declaration satisfies (round 140's dead trigger condition).
Phase 5 stands open and is recorded here per its exit's second branch: 280 of
M21's 285 cards have no in-game verification result (plus the 19 Revised
added; behaviour classes cover 10). The plan: verification sweeps run
*alongside* the next set's rounds through the Debug Menu — promotion stays
ungated on them by the standing decision above, and CI now regenerates the
tracker so the delta cannot silently misreport. Known gaps drained to empty
in the pre-set cleanup round: `set_progress.py` and `CARD_VERIFICATION.md`
joined CI's freshness step, and `SET_PROGRESS.md` learned the `measured` role.

**ATQ — 2026-08-22 (ingest through promotion; 48 → 85, shipped at round 30).**
The first set run end to end in the playbook's own shape, and the first with
**no name-keyed hook added at any point** — ATQ ships at 10.6% hooked cards,
every one of them inherited from the 19 Revised reprints. Three findings moved
into the phase text above.

**Phase 3 gained "a card that reports supported is not a card that works".**
Round 1 spent a whole round *lowering* the count by fixing gates that could not
ask the question, and round 30 spent another closing the three cards
`--hollow-lines` had named since. Both were right, and the second is the one
worth stating: a set is not implemented while that census is non-empty, so
**run `support_report.py --set <CODE> --hollow-lines` as a Phase 3 exit
criterion**, not only at the ingest. It is in Phase 3's step 3 now.

**Phase 4's rehearsal is where the set's real defects surface, and that is the
design working.** Six guards fired on the widened catalog and each named live
wrongness rather than bookkeeping: a printed timing clause nobody enforced, a
conditional whose targets had no prompt, seventeen unlabelled abilities, and a
card (Cursed Rack) whose whole second line was a literal `7` in the cleanup
step. None of these was visible while the set was `measured` — the guards read
`load_catalog()`. Phase 4's checklist already said "read every new finding
before accepting anything"; what this run adds is the reason to budget time for
it, so the wording now says the rehearsal is *implementation work*, not a
formality.

**And a size guard is a scheduling signal, not a chore.** Two grammar modules
crossed the thousand-line cap mid-set (`nouns.py` → `references.py`,
`statements.py` → `paragraphs.py`) and both splits fell along a line the CR
already draws — what a noun phrase *describes* against what it *points at*, and
a sentence against a paragraph. Phase 3 now says to take the split when the
guard fires rather than deferring it: the family boundary is easiest to see
while the work that crossed the line is still in hand.

Known gaps: still empty. Phase 5 stands open, as for M21 — 346 of 734 cards have
no in-game result, and the two promoted-before-verification sets are the whole
of it.

**LEG — 2026-08-23 (partial: Phases 0–2 and rounds 1–8; set still measured).**
The largest set the engine has taken (310 cards) and the lowest starting
coverage (121, 39.0%). Eight rounds took it to 160. Three findings moved into
the phase text above.

**A keyword can be implemented and refused, and the census says "missing".**
Round 1's whole finding: `oracle.UNSUPPORTED_KEYWORDS` is a third keyword table
that outranks the registry and the line gate, and rampage sat in it with working
behaviour and three passing CR tests behind it. Phase 2's keyword sweep now
names that table. The guard added with the fix compiles a card carrying each
implemented keyword **in its ingested field** — every previous probe built its
card from oracle text, which the blocklist never reads.

**A census bucket is not a unit of work.** "Prevention" was nineteen cards and
needed four mechanisms across two rounds; "landwalk negation" was eight cards
and one table. Phase 2 now says to rank by sentence shape rather than by a
shared verb.

**And the long tail is the set.** After eight rounds the ranking is flat: 113 of
the 135 cards still unsupported refuse *exactly one line*, and the largest group
of those shares only an opening phrase. Legends was designed before templating
existed, so the generalise-first rule runs out of general work earlier than in a
modern set — which is a fact about this set to plan around, not a reason to
abandon the rule.

**LEG — 2026-08-26 (ingest through promotion; 121 → 310, shipped at round 36).**
The longest set so far and the one that most tested the phase text. Phase 3
gained four paragraphs, all from things that cost rounds: a refusal site is a
work-list entry and the *layer* of each failure is what to record (a scoping
note carried between rounds was wrong four times running, always by blaming the
nearest interesting clause); a refusal can expire without anything failing, so
re-probe an old decline when machinery lands near it; a decline that names its
exact gaps compounds where "too big" does not (Infinite Authority landed after
seven of them without a round of its own); and a guard iterating a
hand-maintained list needs an assertion that the list is complete — three were
found in one day. Phase 3's exit gained "check `--hollow-lines` every round":
the set reached 310/310 supported with fourteen abilities still
instruction-less. Phase 4 gained the rehearsal's real shape — fourteen hollow
abilities genuinely inert, twelve failing static lines all working with a stale
guard behind them, and four clauses nothing implemented at all — plus the
instruction to read guards as suspects, since three of the four second-copies
found at promotion were inside guards written to catch second copies. The
parallel section gained two merge hazards where taking either side leaves the
suite green. Known gaps: still empty. Phase 5 stands open — Legends' 310 cards
have no in-game result, joining M21 and Antiquities, and the three
promoted-before-verification sets are now the whole backlog.
