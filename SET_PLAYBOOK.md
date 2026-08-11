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

## Known gaps / pending pre-work

A drainable list of things the playbook knows are not yet true, each naming
the phase that clears it. A retrospective that drains an item deletes it; a
set that hits a new one adds it.

1. **`scripts/set_progress.py` and card verification sit outside CI's
   tracker-freshness step.** Until that changes, Phase 4 carries
   `set_progress.py` as an explicit checklist line and Phase 5 owns the
   verification tracker. (Candidate fix: add `set_progress.py` to the
   freshness step in `.github/workflows/ci.yml`; decide after the next
   promotion shows what its diff churn looks like.)
2. **`SET_PROGRESS.md` has no `measured` wording.** An ingested-but-unshipped
   set reads "Partial (N/M supported)" — honest about the numbers, silent
   about the manifest role. Harmless until a reader takes "Partial" as a
   promise; fix in `scripts/set_progress.py` if that happens.

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
   Phase 2.

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
   `vocabulary.IMPLEMENTED_KEYWORDS`. Each missing keyword is one frozenset
   entry plus behaviour that covers **everywhere the CR says it applies, not
   just the paths this pool exercises** — CLAUDE.md's lifelink precedent is
   the cautionary tale. Keyword tests go in `tests/rules/` with
   `@pytest.mark.cr` markers; widen `scripts/rules_progress.py`'s `SCOPE` if
   the CR section is new. Keywords usually open Phase 3: highest
   cards-unlocked-per-change in the census.
3. **Everything else** goes to the backlog via `GRAMMAR_COVERAGE.md`'s
   reason table, sorted by the Lines/Distinct ratio — many lines over few
   distinct shapes is where a production pays best.

Optional tactic, recorded because it worked: fan out read-only subagents to
classify the unsupported cards into *implementable now* (recipe steps 2–3),
*needs a new handler*, and *blocked on a subsystem*, then merge the
classification serially. Implementation never fans out (see the execution
model above).

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
2. Every card lands with a focused test in `tests/sets/test_<set>_cards.py`
   (conventions and the split-by-type rule: `tests/sets/README.md`). A new
   set needs zero `tests/conftest.py` changes; the fixture factory covers any
   manifest set, and the convention guard holds it to that.
3. Between rounds: the supported count from `support_report.py --set <CODE>`
   must have risen; regenerate the trackers; run any `--accept` only after
   reading the diff it blesses.
4. Append the round's narrative to the set's ROADMAP.md entry as you go —
   what the round bought, what it cost, what it exposed. Numbers live there,
   not here.

## Phase 4 — Promotion gate

**Entry:** every card supported. **Exit:** one promotion commit, every gate
green, the trackers agreeing the set ships.

Step 1 is a **rehearsal**: move the manifest entry from `measured` to `sets`
locally and run everything *before* committing. Promotion instantly widens
every `load_catalog()`-driven guard — the catalog sweep, card coverage,
no-hollow-support, behaviour classes — and `parse_coverage.py` sees the set
for the first time (measured sets are invisible to it), so parse debt
surfaces here by construction. Read every new finding before accepting
anything.

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
- `python scripts/set_progress.py` — manual; this line is currently the only
  thing that keeps it true (Known gaps, item 1).
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

*(none yet — M21 will be the first)*
