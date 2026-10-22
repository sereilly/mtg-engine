# Set retrospectives

The history of each set's run through `SET_PLAYBOOK.md`: what happened, what
it cost, and what the playbook changed because of it. The playbook holds the
current process and this file holds why it says what it says. Append-only,
newest last: Phase 6 of each set appends one entry here.

## Per-set retrospectives

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

**The Dark — 2026-08-28 (Phases 0–6; ingest to promotion in one session).**
119 cards, 57 supported at ingest (47.9%), promoted at 119/119 with zero hollow
lines. Twelve group agents in git worktrees across three waves (5 / 4 / 3),
eleven finishing; the twelfth died mid-verification with committed work and an
unverified tree, which its integrator finished and verified rather than merging
on trust. Nine merges, six grammar-module splits, 8,682 → 9,110 tests.

**Phase 1's yield step was measuring nothing, and had been for three sets.**
`test_catalog_sweep.py` promised in its docstring that a set is swept "the
moment it is ingested" and parametrized over `load_catalog()`, which is
shipped-only by design — so a `measured` set was swept the moment it was
*promoted*, after all the work the crashes could have paid for was done. The
whole suite ran green over 119 cards it had never loaded. The sweep now reads
both manifest roles and a guard holds it there. **Phase 1 gained a line saying
to confirm the yield step actually loaded the new set**: a step that reports
success over an empty set looks exactly like a step that found nothing.

**Phase 4's rehearsal earned its billing again, and the three categories held.**
Six guards red: one genuinely missing behaviour (nothing implemented Fasting's
draw-step skip — invisible until promotion, because `parse_coverage.py` only
sees shipped sets), one stale guard that had pinned itself to one of a table's
return values, one payload-key collision between two subsystems that had never
met in one card, two vocabulary tables needing new labels, and one guard whose
*premise* was wrong for a legitimate shape. Running the card is still the only
way to sort them.

**What changed in the phase text.** The execution model now records that twelve
agents is affordable where four once was not, that **integration** rather than
budget is the constraint, that a dead agent's branch is worth checking before
its work is written off, that briefing hooks as a last resort is what actually
holds the hook ceiling down, and that each group needs a delimited block in the
shared per-set test files. Two parallel-authorship hazards are named with their
ROADMAP idioms (25, 26): git turning "both added a function" into a silent
shadow, and a field-only carry dropping the branch that emits the field.

**What is deliberately unchanged.** Promotion still does not gate on Phase 5,
so The Dark is the fourth set to ship ahead of its in-game pass and the
verification backlog grew again — 708 untested of 1,162. That is the decision
working as stated, and the retrospective is where it stays visible.

**4ED — 2026-08-28 (Phases 0–6, one session).** The first set to ship without
implementing a card. Fourth Edition is 378 printings of 368 unique cards and
every one was already in the pool, so the census read 368/368 supported at
ingest, Phases 2 and 3 were empty, and the promotion moved neither the unique
count (1,162) nor the verification backlog (708). Phase 1 gained a step for it:
diff the ingested `oracle_id`s against the shipped pool before planning rounds,
because every phase downstream is written for a set that brings cards. Ten more
zero-new-card sets are ahead (ROADMAP's header lists them), so this is a shape
to plan for rather than a one-off.

**The value of a reprint set's ingest is in Phase 4, and it is guards.** Two
fired, both about premises rather than cards. `test_the_catalog_does_not_load_measured_sets`
proved its point by finding a card name only the measured set has, which an
all-reprint set cannot supply — and it *passed*, because its author had written
the self-check for exactly that day ("pick a different assertion"). The
replacement asserts printings instead of names and is the stronger probe even
where the old one worked: a widened `load_catalog()` adds 368 `4ed` printings to
cards whose names were already there. The printing-order guard had no such
self-check: it verifies the consequence, no card's origin moves, which a set
whose every card already has an earlier printing satisfies from any position.
Probed by appending 4ED after M21 — the whole suite stayed green four places out
of order. Phase 4 now says to assert a proxy's *availability*, and manifest
order is asserted directly off the `released` dates.

**And the two coverage trackers disagree about what "the pool" means.** Only a
reprint set makes it visible: GRAMMAR_COVERAGE's All row is printing-weighted
and moved 85.2% → 85.7% parsed with nothing in the parser touched, while
HOOK_RELIANCE's is deduped and did not move at all. Both are defensible, neither
is a hole — the ratchets are re-accepted at each promotion — but the diff reads
as progress and is not. Phase 4 now says to ask what changed in the membership
first, and the sentence lives in the generated report where the number is read.

**Phase 0 drained its standing item.** Three real CI runs settled the suite-time
budget: the ratio never worked because `BASELINE` was measured locally and
compared against an `ELAPSED` measured on the runner. Both numbers were wrong in
opposite directions — 40 → 110 (runner-measured) and 120 → 240. Phase 5's
simulator step gained a note that `--set` is unrunnable for most sets, since the
simulator's one fixed deck needs cards those pools lack; `--all` across the
promotion commit is the comparison that would catch something, and it was
byte-identical. 9,110 → 9,117 tests.

**ICE — 2026-08-31 (Phases 3–6; the set shipped).** 184/373 at ingest, 284
after forty-two serial rounds, then **four parallel waves of five worktree
agents** to 373/373. 21 agents, all finished. Pool 1,162 → 1,508 unique cards.

*Drained:* nothing — the Known-gaps list was already empty. *Added to the phase
text, all in place:* two more merge hazards (two branches inventing **one fact
under two names**, and two branches implementing **one rule as two
mechanisms**) plus the observation that a *semantic* collision — one branch
splitting a parsed kind another branch's table assumed was single — merges
clean and fails only at runtime, which is why the suite runs *between* merges;
the warning that reconstructing a test file from its delimited block drops
header imports; and the finding that cap breaches at integration, from two
groups' additions merely summing, are routine (seven across four waves) and
should be split along a family name the other side already carries.

*The instruction that paid most:* **write each decline as an enumerated list of
missing pieces.** Ten cards were declined that way across waves 1–3 and every
one eventually landed, several because a *different* group built their pieces
as a side effect. Say in each brief which pieces are already done.

*Also added:* ask every group what its brief got wrong — a third of each was,
including a card called "the hardest in the set" that was the cheapest and a
scoped subsystem migration aimed at the wrong file; and two operational notes,
that `git stash` and a shared scratch directory are both **shared across
worktrees** and cost two agents their tree.

*Phase 4 gained two steps.* The proxy trap collected a third time and now fires
on every promotion: a guard that finds "a card in a measured set" breaks when
promoting the last measured set empties the role, which is legitimate — assert
that `CARD_PATHS` reads both roles instead. And **sweep what the target pickers
offer**, which has no guard behind it and found three defects every card-level
instrument was blind to, including two shipped Auras that were uncastable in
the app because their enchant clause derived `kind: "none"`.

*The numbers that matter:* 24 silent defects fixed in already-supported cards,
found by reading compiled programs rather than the census — none had a failing
test. Nine name-keyed hooks retired and **none added**, so reliance fell 6.0% →
4.2% while the pool grew by a third. Grammar coverage 87.2% parsed / 54.9%
executed. Two engine-wide findings left for their own rounds, recorded in
ROADMAP: a delayed trigger binding a departed target *by index*, and The Abyss
arming no prompt for "of their choice". *(Both were taken as follow-on rounds
the same day and both found the recorded scope wrong — the first was nine live
activated abilities rather than a delayed-trigger binding, the second was a
dropped `controller` keyword before it was a missing prompt. The ROADMAP entries
they pointed at are gone with the fixes; the warning they left is in ROADMAP's
Ice Age section.)*

**FEM — 2026-09-01 (Phases 0–6; the set shipped).** 69/102 at ingest, 101/102
after **one wave of five worktree groups**, and 102/102 after one more agent
took the single declined card. Pool 1,508 → 1,610 unique cards; the manifest
entry inserted at printing-order index 8, the first insert rather than an
append. **Zero name-keyed hooks added and one retired** (Dragon Whelp, whose
printed clause two FEM cards share), so reliance fell 4.2% → 3.9%.

*Drained:* nothing — the list was empty on entry. *Added:* one item, the
`permanents_from` channel carrying two arities.

*The instruction that paid most, and it is new:* **run `parse_coverage.py` and
`--hollow-lines` at Phase 1, not at Phase 4.** FEM's refusal census measured 39
refused lines over 39 distinct sentences — the reading that says a set contains
no shared production — and those two instruments then found four *supported*
cards each holding a second copy of a sentence a refused card needed. The pairs
became the group split and each cost one production for two cards. The census
counts cards and cannot see that population by construction; this is now a
numbered step in Phase 1.

*Added to the phase text, all in place:* two merge hazards about **how a
conflict is resolved** rather than what conflicted — a whole-file `--theirs`
discards the hunks that were never in dispute (it would have dropped a third
branch's cleanly-merged node), and a union of two `if` branches can break an
`if`/`elif` chain so one branch's answer is computed and overwritten. The
per-set test convention is rewritten: **block-local imports**, with the files
opened on `main` before the fan-out, which designs out the header-import hazard
instead of watching for it — and a note that the same failure survives wherever
a *function* moves between modules, which is how it caught the integrator during
a cap split. And Phase 3 gains the **whole-pool compiled-program differential**
as a step rather than a tactic.

*The scope error worth repeating:* a decline recorded during the wave named a
parser feature ("cross-sentence pronoun rebinding is missing"), and building it
broke eight shipped cards that already played correctly — the engine reads that
pronoun in the *lowering*, and each of those lowerings already had a branch for
it. The differential found that in one run; the real fix was one branch in one
lowering. Roughly a third of every brief was wrong again, in the usual
direction.

*Phase 4 collected on the proxy trap a fourth time.* A guard asserted that every
anthem-shaped line is claimed by `engine/lord_buffs.py`'s table — but the grammar
runs *before* the derivation tables, so a production claiming such a line is
exactly when the table must stay silent. It now asks whether the line is read by
anything. Three cap breaches fired at integration and none was caused by a
single branch.

*The numbers:* grammar 88.0% parsed / 56.1% executed (FEM itself 99.0%); ten
defects fixed in already-supported cards, two of them free abilities and one
five sets old; behaviour classes 57 → 62; suite 10,934 → 11,176 tests.

**HML — 2026-09-02 (Phases 0–6 complete; 76 → 115/115, promoted at index 11).**
Two waves of five worktree groups plus one follow-up, **zero name-keyed hooks
across all 39 cards**, so reliance fell 3.9% → 3.6% while the pool grew 1,610 →
1,725. Six phase edits, all in place.

*Phase 1 gained two instruments and both paid on the day of the ingest.* The
**fragment census** — an n-gram over the refused lines — is now step 4 beside the
sentence one, because the refusal rollup measured 1.00 lines per distinct
sentence for the fourth set running and was wrong: ten HML cards print an
untap-denial clause and three already compiled, so seven cards cost one group one
*subject widening*. It named every wave-1 group boundary; the sentence census
named none. And the **picker sweep moved up from Phase 4**, where it found Roots
— a supported Aura, no hollow line, every sentence claimed, and no cast spec, so
no player could put it on the battlefield. Phase 4 keeps its own copy and now
says why running it earlier is cheaper.

*Phase 3 gained three rules.* The whole-pool differential must record
instructions and abilities **in full with their payloads**, because keying on
counts hides a narrowed trigger and keying on kinds hides a narrowed payload —
two of five groups and the integrator each shipped a lossy version, and each
hid a real defect. The failure taxonomy gained a **fifth layer**,
`engine/oracle.py`'s trigger-condition table, which is the only trigger front
end that feeds dispatch. And a new step 3 says **the Rock Hydra test cannot be
run in the app while a set is `measured`** — `CARD_PATHS` is shipped-only, so
"give the behaviour a game" means headless plus
`run_ai_simulation(required_cards=…)` until promotion.

*Phase 4 gained the rule the rehearsal collected on:* **a reader of a card's
lines that does not start from `expand_ability_lines` is reading a different
card.** CLAUDE.md names three; this found a fourth, and Orcish Mine's conjoined
trigger reported as implemented by nothing while working perfectly.

*The execution model gained two merge hazards.* The per-set block convention has
**exactly one failure mode** — two branches whose helpers end with the same lines
split one append into two conflict regions, and a naive union splices one helper
onto the other's signature; refuse anything but a single region and reconstruct
from the merge base with "both sides are pure appends" asserted. And a module
split needs **two scans, not one**: the documented dead-import sweep, and a
missing-import scan, which is the half that is actually a bug and the half that
does not fail at import time.

*Known gaps:* `permanents_from` stays open with its scope measured (17 producers,
13 readers, one normalising) — HML added two producers and both happened to match
their reader, which is the item's own point restated. Nothing was drained.

*The numbers:* grammar 88.0% → 88.3% parsed and 56.1% → 56.5% executed with every
existing set's floor rising; hook reliance 3.9% → 3.6%, entries/100 4.2 → 3.9;
behaviour classes 62 → 69; suite 11,176 → 11,667 tests. **Nine already-supported
cards were found mis-playing**, every one invisible to the census, to
`--hollow-lines` and to `parse_coverage.py`, because all three ask whether a line
produced *something* and each of these produced the wrong thing.

**5ED — 2026-09-02 (Phases 0–6, one session; the second pure-reprint
promotion).** 434 printings, 434 unique oracle_ids, zero new to the pool —
promoted the same session at index 12 (between HML and M21), moving neither
the unique count (1,725) nor the verification backlog. The 4ED shape held
end to end and the phase text needed no correction: Phase 1's oracle_id diff
called the shape before any round was planned, Phase 4's rehearsal produced
exactly the two predicted ratchet-scope failures (accept adds the set's
floor and ceiling rows), grammar's printing-weighted All row moved on
membership alone (88.3% → 88.8% parsed) while hook reliance's deduped ALL
row did not, and the picker sweep read 0 before and after the move. The one
finding was Phase 1 yield of the Ice Age promotion's emptiness class from
the other side: `test_registration_inserts_in_release_order` copied the real
manifest and asserted `measured` equals exactly its three fake entries —
"measured is empty" baked in, true since HML's promotion, false on the first
real ingest. Fixed to assert the invariant (the list is release-ordered; the
fakes keep their relative order) rather than the population. Nothing drained
from Known gaps; nothing added.

**ALL — 2026-09-02 (Phases 0–6, one session; 62/144 → 144/144).** Three waves
of five worktree groups plus three closers; pool 1,725 → 1,869 over fifteen
sets, suite 11,547 → 12,758, grammar 88.8% → 89.2% parsed, hook reliance
3.6% → 3.3% with **zero hooks added across 144 cards and one retired**.

*The headline finding is about the instruments, not the set.* **Six
already-shipped cards were mis-playing and every one was stronger than
printed** — a divided spell resolving as a no-op, three dealing their whole
amount to a face the card cannot target, two aiming the AI at its own board.
None was visible to any instrument, because the census, `--hollow-lines` and
`parse_coverage.py` all ask whether a line produced *something* and none asks
whether it produced the right thing. Five of the six were found as a side
effect of work on a different card. Phase 3's Rock Hydra step is the only
thing that finds these, and the phase text now says the census cannot.

*Phase 3's split guidance went from two scans to three*, in place: the
dead-import sweep, the **missing-name** scan (run it *before* the suite — it
fired three times in one wave, once for 246 failures) and a
**duplicate-definition** sweep, which is the one no guard can see because
`test_no_module_defines_the_same_name_twice` looks within a module and a copied
production imports clean and is never reached.

*Integration gained two rules.* A module crossing the cap **with no branch at
fault** is the integrator's split — two happened in one wave — and the module
usually names its own seam; cut where its docstring already draws the line and
move the half that grows with the pool. And after resolving one per-set block
conflict, **sweep every block in every per-set file the wave touched**: the
convention's documented failure mode fired for real and a naive union spliced
four lines of one group's helper onto another's.

*Phase 4 gained the manifest mechanics* (textual edit, not a json round-trip)
and the instruction to **rehearse a wrong insert** before trusting the order
guard — an all-new set's position is invisible to the prefix comparison, now
FEM's, HML's and ALL's blind spot. The rehearsal turned nine guards red and
**five were the guard**, including the emptiness-premise class for the third
consecutive set, this time written into a test's docstring.

*Nothing was drained from Known gaps.* `permanents_from` stays open;
`_cost_picker_spec`'s missing **offer** shape is now owed by two cost kinds
(the alternative cost from W1G4 and the repeated additional cost from W3G1),
which is the one item this set added.

### MIR — 2026-09-04

*Phase 3's exit is three numbers now, not two.* Mirage reached 335/335 supported
with zero hollow lines and **13 printed sentences on 11 cards that nothing
implemented**, six admitted by a *single whitelist word*. Neither existing number
can see that class, and `parse_coverage` is advisory for a measured set — so
nobody is made to read it until the promotion, where it becomes a fourth wave
instead of a round. Phase 3 step 4 now says read it every round.

*Phase 4's wrong-insert rehearsal is no longer an all-new set's rule.* MIR shares
22 cards and the prefix guard still could not see the bad position, because
appending moves no **existing** card's origin — what moves is the new set's own.
Volcanic Geyser is the named card; the instruction is now unconditional.

*Guards-as-suspects gained its cheapest instance.* A pool-wide census called its
reader without the card's name, so a card naming itself (CR 201.4) was reported
unenforceable while working perfectly. Phase 4 now says: when a census disagrees
with a card, **run the card first** — a census taking fewer arguments than the
enforcement path is reading a different sentence.

*Two brief-writing errors worth not repeating*, both mine and both about where a
rule lives: an additional cost does not go on the pending-choice queue (CR
601.2b's choices arrive *with* the action), and a life-gain prohibition is not a
CR 614 replacement (CR 119.7 makes such a replacement do nothing, so it must be
asked *before* the contention set rather than inside it).

*Nothing was drained from Known gaps.* One item added: the testable-keys
preamble, copied three times inside `lowering/prevention.py` with the looser
form across 32 lowering modules — invisible to the merge scans because it is not
a duplicate *definition*, and load-bearing because a drifted copy drops a
narrowing the matcher cannot test. (`_per_recipient_count` was already logged at
wave 1, not here.)

### VIS — 2026-09-05

*Phase 0's caps step now says "per module the wave will touch", not "the
tightest one".* Visions pre-split `lowering/_common.py` for exactly the right
reason — every family imports it, so no group would cross it alone — and then
crossed five more caps anyway, three at integration by two groups' additions
summing. The prediction that works is per-family: note which modules each
*group's* family lands in and pre-split the ones two groups will both reach. A
module one group owns can be briefed; a shared one cannot, because neither
crosses it.

*Phase 3 step 4 gains a taxonomy: there are three ways a card reports supported
and does nothing, and only one has an instrument.* Beside the hollow line, this
set found the **channel mismatch** (Equipoise chose the right permanents and
phased out none, because wave 1 settled `permanents_from`'s arity and nobody
settled its element type — settling an arity is only half of settling a channel)
and the **runtime decline** (Three Wishes' sentence parsed, lowered, compiled and
did nothing, because the handler refuses at run time). Nothing here can see the
third. Only driving a game finds it, which is why the Rock Hydra test is not
optional.

*Two new species of brief error, both mine.* An **engine refusal message that was
itself false** — quoted straight into a brief, wrong for two sets, pointing at a
module that had been doing the job correctly all along. And a **deferral whose
premise expired**: "no client can load a `measured` set" stopped being true at
*Alliances'* promotion, and nobody re-read the role because the cards had not
changed. That left Fire Covenant, a shipped Ice Age card, uncastable as printed.
The playbook already says a refusal can expire; a deferral can too.

*Four items added to Known gaps* (cast-side "target opponent" offering the
caster's own face; bare stack-drain loops as latent hangs; `_PLAYER_DEEDS`
needing a design decision rather than a row; ~60 non-701 CR citations corrected
but unguardable). *Three drained*: the testable-keys preamble (40 copies across
21 files, not 39 across 11 — and now enforceable rather than swept), the
`permanents_from` arity, and the optional-cost picker's four parts.

### WTH — 2026-09-05

*Phase 0's caps rule is now tested in both directions, and it is binary.* Wave 1
gave each of the seven tight modules a **single owning group**, briefed to expect
its own split, and left one unowned as the control: integration crossed **zero**
caps, two groups split in round along a line their module's docstring already
drew, and the control was the only module that drifted. Wave 2 then shared two
modules between two groups, told both to keep their additions small, and both
went over at integration anyway — by 3 lines and by 1. So there is no third
option: **a shared module is pre-split at Phase 0, an owned one is briefed.**

*Phase 1 gained the sentence that nearly cost the ingest its whole yield.* The
suite was run as `pytest … | tail`, which reports `tail`'s exit code, so a run
with three failures read green. A gate piped into anything is not a gate.

*Phase 4 gained the far side of "read the guards as suspects".* Seven guards
went red at the rehearsal and **every one was a real finding** — the first
promotion here where none of them was the guard itself. Ten effect labels, two
divided cards for the AI's inventory, and a deletion probe whose five non-new
findings each named a word the payload provably carried.

*The merge-hazard section gained the reverse of its own entry.* Two branches
fixed one bug two ways — a hand-written noun list versus a derivation from the
grammar's own — and **the derivation is what survives, because the list was the
bug**. Its mirror is one name meaning two things, which merges silently: sweep
for names defined in two modules, then check whether any single file imports
both. That is the check; the count is not.

*One item drained* (the cast-side "target opponent", whose card list was wrong
in both directions — three cast-side cards, not five, plus two on the activation
path nobody had looked at). *Two added*: `control_flow.may` firing its `then`
branch on an action that did nothing, invisible to `oracle_diff` because no
program moves; and the half of the `primary_type`/`printed_shape` disagreement
that stayed open one zone over in `cast_permissions`.

### TMP — 2026-09-06

*The caps rule ran four times and held four times.* Three Phase 0 pre-splits and
three integrator splits, every pre-split moving **0 of 2,824** compiled programs,
and every cap crossed at integration on a module two groups had both reached.
Phase 0's text now says the prediction is mechanical, and adds the sharper half:
**a split's seam is a lead, not a fact** — the third pre-split was briefed with a
seam a previous group reported, checked it, found the code contradicted the prose
and cut a sentence earlier. The reported cut would have bought 42 lines of 940.

*Two post-split scans added, making five.* Anything **keyed on a file path**
(`test_cr_citation_subjects.REVIEWED` broke in both directions at once, with
nothing undefined, unused or duplicated), and **execution order for module-level
code** (a name imported by a later block passes a presence check and still
raises at collection — the block convention is self-contained in isolation and
does not survive a split that changes which block is first).

*The per-set reconstruction gained its counter-example.* Its base-prefix
assertion fired correctly on a file the **integrator** had edited mid-wave when a
decline expired. Keep the assertion; union at the hunk when it fires that way.

*Phase 3 gained the finding this set is the evidence for:* **a decline ages in
the direction of becoming free.** Eighteen cards declined with enumerated parts
came back three-of-five, two-of-three and one-of-three already built, twice
because a group had read the absence of the *wrong* channel as the absence of
the mechanism.

*Phase 5 gained a failure class of its own.* Smoking the set found a **display
list nothing derives**: 25 shadow creatures reported no shadow to the client,
phasing had been missing since Mirage, and no engine instrument can see any of
it — the cards compile, claim every sentence and play correctly. Read what the
**wire** carries for the set's headline mechanic.

*Four items added to Known gaps* (a multi-slot picker offering one list for every
slot; `unless_player_pays` labelled with a family rather than a shape, plus its
guard's blind spot; the bare `spell` noun dropped pool-wide, with Ersatz Gnomes
live; `test_layer_reads` scanning `engine/` only). *Nothing drained.*

### EXO — 2026-09-07

*The per-group caps prediction is retired; the shared-module one is kept.* Three
shared modules were pre-split at Phase 0 and all three were right, but **six of
the set's eight cap crossings were in modules no brief named**, and three of the
five handed to a group as "yours, expect to split it" were never opened. Two
waves and eleven groups is enough evidence: Phase 0's text now says to name the
shared modules, declare everything else within 30 lines unowned, and let a group
split what it crosses — which it does well, three sets running.

*The instrument ranking is written down for the first time, because this set
measured it.* Fifteen shipped cards were fixed and the census found **none** of
them. `--hollow-lines` and `parse_coverage` were at zero on the day of the
ingest and stayed there all set — the first time either has found nothing, and
the argument *for* running them every round rather than against it. What found
things: driving a game (nine of fifteen), `oracle_diff` (two regressions caught
in flight that no test would have failed on), the deletion probe (one card no
other instrument can see).

*Phase 5 found the largest defect of the set and it was not a card.* Every CR
116 special action the UI has ever offered had been unreachable for four sets,
because one of 125 `sendAction` call sites left `seat` out of the body — no log
line, no error on screen, a 422 in a console nobody reads. **Nothing in the repo
reads that envelope but a browser**, which is the new Known-gaps entry: the
guard added checks one required field of one schema by parsing JavaScript, and
every other required field is in the same position. Fixing it then exposed the
rules half — a special action is not a resolution (CR 116.1), and the SBA sweep
only ran after resolutions, so an ended Licid left its stolen creature stolen.

*Two entries drained, both in the shape they asked for.* The "if you do" rider
became `control_flow._action_is_takeable`, a registry asked **before** the
prompt rather than a measurement after it — and the two cards it was costing
were shipped ones in other sets. `ast/_references.py` split along exactly the
seam Stronghold recorded, at exactly the cost Stronghold budgeted plus one line
nobody had counted.

*And Phase 6's own check paid again.* Re-reading each carried entry against the
code found the "if you do" gap already closed by this set's own wave 1 — the
work was done and the ledger still said open, which is the mirror of the failure
that rule was written for.

### STH — 2026-09-07

*The caps rule was applied once and skipped once, and skipping it cost a card.*
Ten modules sat within 30 lines at Phase 0; one shared-and-tight module was
pre-split and `lowering/characteristics.py` at **7** under was read as shared,
judged too expensive and briefed instead. Wave 1 declined **Spined Sliver**
naming that module as the entire blocker. Phase 0's text now says the rule is
"pre-split every module two groups will reach", not "pre-split the tightest",
and adds the wave's other splitting finding: **a cap breach is more often a
misplaced function than a missing module** — three crossings, one new file, the
other two resolved by moving code to a home that already existed.

*Both wave-2 groups that were briefed with a seam refused it, and both were
right.* `lowering/characteristics.py`'s docstring seam was four splits out of
date and would have bought 45 lines; `ast/_references.py`'s reported seam was
measured at 29 lines of 997 and shown to invert `_primitives.py`'s stated
invariant. "A split's seam is a lead, not a fact" now has two more instances and
they were both *briefed* leads, which is the case that matters: the integrator
is as capable of handing over a wrong seam as a previous group is.

*Re-probing a decline paid on every card of wave 2, and the sharpest one is a
warning about how a decline is written.* Volrath's Shapeshifter was declined
partly on "granting a quoted activated ability is unimplemented — `parser.py`
raises GrammarError". It has been implemented since Tempest, via `grants_text`,
and **the parser never reads a quote at all**. The absence of the wrong channel
was read as the absence of the mechanism, for the second set running. Contempt's
seven parts came back three-already-built; Reins of Power's five came back
three-expired against a brief that called it one of the two hardest cards left.

*Phase 6's own new rule paid immediately and found its own limit.* Checking that
each carried Known-gaps entry is still **true** found the bare-`spell` entry
drained the day before this set's ingest — after it had been re-read at Phase 1
and written into a group brief as live. The group corrected it in its report.
Both mechanisms are needed and neither is sufficient: Phase 6 catches what a
brief asserts, and the brief's "tell me what this got wrong" catches what Phase
6 has not reached yet.

*Phase 4's wrong-insert rehearsal found something in a set that looked immune.*
142 of 143 cards are new, so the ROADMAP entry written at Phase 1 said no card's
origin could move from any position. Wrong: the one reprint is **Shock**, whose
only other printing is **M21** rather than Tempest, so the insert decides its
origin — Volcanic Geyser's shape in a set whose single shared card makes it look
impossible. Count a reprint against the set that actually prints it.

*Phase 5's wire check found its second instance in two sets*, and the entry now
carries why the obvious fix is also wrong: a Licid's "becomes an Aura
enchantment" is a layer-**4** type change, so `effective_card.type_line` — the
documented answer to "what does it say?" — is as blind as the printed one.

*Two items added to Known gaps* (`StackItem.target_permanent_id`'s two arities
across 119 reader sites, already paid for with one live defect; three near-cap
grammar modules with no owner, two with measured seams). *One drained* (the bare
noun `spell`, drained before the set began). *One amended* (the `web/` layer-read
scan, with its second site).

### USG — 2026-09-08

*The round with no cards in it was the round that paid best.* Three waves, but
the fifth group of wave 3 was given **no Urza's Saga cards** — only the shipped
defects earlier waves had found, measured and correctly declined to fix inside a
wave. It returned twenty shipped permanents dealing damage as the printed
`CardDefinition` rather than as the permanent (CR 120.7, four handlers wide),
`_apply_lifelink`'s documented fallback that had **never run once**, four cards
whose triggers targeted themselves, and CR 603.4's fire-time half. Phase 3's
text now says a wave may spend a group this way when earlier waves have
enumerated enough deferred work to fill one.

*It also produced the first instrument this process has gained from a wave.*
`scripts/unasked_narrowings.py` answers "which predicates are asked on one of a
pair of paths?", and it was **validated backwards** — run against its own
round's parent it names all three dead cards and nothing else the round found.
That validation is now the bar Phase 3 states for a new instrument: a census
that cannot reproduce a known finding is a census nobody should trust.

*Probing the two keywords before briefing anyone changed the whole plan.* The
census reads Cycling (34 cards) and Echo (14) as the set's big rocks and both
look like grammar work; both were already parsed, and both are the equip shape —
a rewrite plus a registry entry. Phase 1's text now says to probe a keyword's
*rewrite target* against the live grammar before sizing it.

*Two groups independently refused the same brief instruction and both were
right.* `IMPLEMENTED_KEYWORDS` admits a keyword being **granted or named**, so a
rewrite-defined keyword is absent from it by design — equip, buyback and
cumulative upkeep already were. Phase 2's keyword text says so now, because the
brief said the opposite twice.

*The wrong-insert rehearsal earned its minute for the third consecutive set.*
USG shares 17 oracle_ids, of which exactly **three** (Duress, Glorious Anthem,
Rewind) have their only other printing in M21 — so its index decides those three
cards' origin. Appended after M21 the prefix guard passed and all three read
`m21`; the order guard failed at index 20 and was the only one that did.

*Two items added to Known gaps* (a hooked card's every sentence is
blanket-claimed, so `parse_coverage` is blind to an unimplemented line on one —
found only by retiring a hook; and `simulate_ai_games.py` never enters a main
phase, so no `main_phase_*` trigger has ever fired in an AI game). *Two amended
rather than drained*: `StackItem.target_permanent_id` gained a **third axis** —
the field carries "the target chosen" and "the object this is about" with
nothing recording which, which is a relation problem rather than the arity one
the entry described — and CR 615.8's chosen source had its trigger condition
corrected, because USG printed the phrase eight times and all eight were
activated abilities the engine already handles. Printing the phrase was never
the trigger; printing it on a **spell with its own target** is.

### ULG — 2026-09-09

*The two rounds with no cards in them were, again, the rounds that paid best —
and this time there were two of them because the pile said so, not the card
count.* Six cards were left when wave 2 opened; three groups took them and two
took the shipped-defect pile wave 1 had enumerated. Those two returned
**protection's damage half, which did not exist** — `deal_damage`, the one seam,
never asked `_is_protected_from`, so 64 shipped cards printing protection took
damage from 69 sweep lines for the life of the engine — an attack cap the AI
could not satisfy, so a seat under Crawlspace *or* Caverns of Despair attacked
with nobody for the rest of the game, and **an upkeep prompt addressed by card
name**, so two Bad Moons shared one answer and both got paid for, across 112
shipped cards. Phase 3's text now says the count of no-card groups is set by the
size of the enumerated pile.

*Four pre-splits, zero cap crossings at integration — and three of four recorded
seams were wrong.* The first half is the pre-split rule's cleanest result: eight
modules sat within 30 lines, the four that two or more groups would reach were
cut at Phase 0, and two waves of five groups crossed **no** cap. The second half
is the warning that goes with it. `lowering/control_flow.py`'s docstring named
four composers of which two had already left; `conditions.py` claimed the record
clauses were read elsewhere when eleven were read by the dispatcher itself;
`delayed.py` called itself "the one place the rows become a node" and there were
two. **And the fourth is the shape to watch: `parser.py`'s own seam was right and
`riders.py` denied it** — the wrong sentence was in a different module's
docstring, which is exactly the sentence a briefer hands over.

*The set arrived 80.4% supported, the highest ever, and that is a fact about the
previous set.* 25 ULG cards print echo or cycling, both built at Urza's Saga as
`expand_ability_lines` rewrites, so they compiled on arrival with nothing to do.
Phase 1's text now says to read a high arrival number as "the last set did this
already" and to check which census big rocks are already-built rewrites.

*The promotion rehearsal produced exactly one real card and exactly one stale
guard, which is the split the phase text predicts and cannot be told apart by
reading.* Thran Weaponry dropped "for as long as this artifact remains tapped"
in its lowering, so the buff outlived the untap **and** died at the cleanup step
of a card whose other line exists to keep it tapped across turns; Aura Flux was a
guard asking only the lord-buff table about a line whose subject is enchantments.
A minute of driving each settled both.

*One brief instruction earned its place twice.* Ten groups were told a
name-keyed hook was the last resort; **the set ships with zero**, the eighth to
do so, and pool reliance held at 1.5% while the pool grew by 143.

*Phase 4 drained the hooked-claim gap and Phase 5 found the fourth `web/`
layer-read site — in a new shape.* A hook now claims only the lines
`CARD_LINE_INSTRUCTIONS` compiles (the blanket was 80 sentences and is now 3),
and the pool-wide re-run found one card, City in a Bottle, whose second line was
implemented and unattributed. The `web/` site is the one worth carrying: it is
not a printed-card read but an accessor whose **narrower sibling** answers a
smaller question, so no grep would have found it — Yavimaya Scion, whose entire
text is "Protection from artifacts", reached the client with no badge at all.

*Three items added to Known gaps* (the AI simulator has no combat phase, so
`simulate_ai_games.py` cannot validate any combat change; an off-battlefield
colour read ignores a colour-defining static, so Gloom does not tax a spell
Celestial Dawn made white; and the blocking side of the declaration-legality gap,
declined with its four parts named). *Two drained* (the hooked-card blanket
claim, and the simulator's missing main phase — whose re-baseline, unlike its
`begin_turn_bookkeeping` sibling, was **not** a no-op). *Two amended*: a **card**
can now be a role, which is three of the multi-slot entry's four named pieces
built, and CR 615.8's chosen source was re-checked against its own amended
condition and correctly did not fire.

### 6ED — 2026-09-09

*The set with no cards in it, and the wave that proves what the Known-gaps list
is for.* Classic Sixth Edition arrived **335/335 supported** with zero hollow
lines, zero unclaimed sentences and zero picker findings, so Phases 2 and 3 had
no card work at all and all five wave briefs were Known-gaps entries. It worked:
the wave fixed defects on **well over a hundred shipped cards** while
implementing none. The condition that made a cold start possible was that every
one of the five entries had its parts *individually enumerated* by the group
that declined it — the entries in this list written as prose would not have
supported a brief, and that is the argument for the decline convention restated
from the consuming end.

*`oracle_diff` reported 0 of 3,572 on all five merges, and that is the finding
rather than the absence of one.* Over a hundred mis-playing cards and the
compiled-program differential moved nothing, correctly, because none of these
defects were in compilation — they were in dispatch, on the wire, in a prompt's
address and in the AI's declaration. **That is where the pool's remaining
defects now live.** Phase 3's text now says to keep running it and never to read
its zero as a finding: a text-keyed or wire-level round owes a census of its
own, and W1G3's four-boards-by-whole-pool comparison is the model.

*Three of five briefs were wrong in the same place — the sentence that bounded
the problem.* W1G1's said the block cap totals every defender's blockers "because
CR 509.1b"; **CR 802.4b says the opposite in as many words**, so Caverns of
Despair had been refusing *legal* blocks in multiplayer for the life of the
engine. W1G3's said "the battlefield side is clean"; the tax family was not, and
Gloom's second line was blind to all three colour statics in the pool. W1G2's
said "some of the seven sites are already fixed"; all nine live reads were live,
because an entry that accretes instalments reads as progress even when nothing
has been closed. **A brief's reassurance needs a probe exactly as much as its
claim does**, and it is the half nobody probes.

*W1G4's entire brief had been drained two days earlier by the set that raised
it.* Two consecutive Phase 6 re-checks had each counted their set's printings of
"a source of your choice", correctly concluded the set did not meet the trigger,
and never opened the file the entry names. **A re-check owes one probe of the
code, not just one probe of the set** — now in Known gaps' preamble. What landed
instead is a fail-closed guard on the *class*, since only two of six cast walks
reach the chosen-source stage.

*The set is the third reprint-shaped one and the first where that is only almost
true.* `set_progress.json` records 6ED with 0 new cards; it brought two, because
that column counts against the release line and this manifest is a subset of it.
Phase 1 now says to diff against the pool, never against that column. The
promotion rehearsal turned three guards red and **all three were ratchets** — no
real finding, on a set where 4ED's and Ice Age's proxy guards would once have
fired, because both had since been rewritten to assert their invariants.

*Three items drained* (CR 615.8's chosen source on a cast, the two prompts whose
subject is not a permanent, the off-battlefield colour read), *one taken and
left open with its remainder named* (`web/`'s layer reads), *three added* (the
engine's own layer guard omits `primary_type` and exempts by file rather than by
count; `web/serialization.py` still prices Gloom by hand, which this wave turned
into a live divergence; Balance and Kudzu count by printed type in five engine
sites plus a client that cannot reach the fix). Zero hooks added, zero caps
crossed, and the CI baseline Phase 0 owed was refreshed 571s → 677s.

### UDS — 2026-09-10

*The two rounds with no cards in them found more broken shipped cards than the
set had cards, and both numbers were measured rather than estimated.* Wave 2
gave two of five groups the pile wave 1 had enumerated. One found that
`_activate_onto_stack` settled "which seat is this pointed at" **before** the
StackItem existed, so an announcement with no seat reached the stack as "the
opponent" and every id on the activator's own battlefield was thrown away behind
it: **382 shipped cards in the class, 209 demonstrably misresolving** — 163
acting on a permanent nobody chose while logging success — plus **151 of 275**
targeting instants and sorceries on the cast path, which wave 1 never mentioned.
The other found `Game._settle` running resolutions with `pause_for_choices`
False whoever was playing, so **267 prompt-armings across 255 shipped cards**
were queued with nothing holding them and CR 704.3's sweep ran on a resolution
that had not finished. Both reported `oracle_diff` 0 of 3,715, correctly.

*Both groups' censuses were wrong before they were right, in the same shape, and
so was the integrator's.* One sweep called `activate_permanent_ability`, which
settles the stack itself — so it examined **zero** announcements and **passed on
the broken engine**; it now asserts a floor on how much it measured. And the
promotion gate's own "another" brief claimed the parser drops the word, from a
probe that walked `ObjectFilter` and never looked at `TargetSpec`, where
`parse_target_spec` had recorded it for sets; its "40 cards" came from grepping
the payload for `other_than_source`, the **AST field name**, when the payload
key is `exclude_self`. Phase 4's text now says a census gets the same probe a
refusal site does.

*The real finding under that wrong brief is the one to keep.* The graveyard
family **has** a gate for narrowings it cannot honour — `_reads_no_return_
restriction`, which explicitly refuses `other_than_source`. It reads the
ObjectFilter; the word was on the neighbouring TargetSpec. Junk Diver returned
itself from an empty graveyard, supported the whole way through. **A rider on
the dataclass beside the one a gate reads is invisible to it.**

*The rehearsal split eight red guards three ways and only running the card told
them apart.* Three ratchets, four review items, one real finding. One review
item was the guard: `test_static_line_support` keeps its own list of which
derivation tables exist and had never been told about `combat_permissions`, so
Wall of Glare's working ceiling of 1,000,000 read as an unbacked line. And the
discipline cut the other way too — Thran Golem read 4/5 with no keywords on both
the engine *and* the wire until the probe ran a state-based-action check, which
a real game does constantly. **A card that looks broken from outside a game is
not evidence until it is driven inside one.**

*Zero hooks added across 143 cards, the ninth consecutive set*, and reliance
fell to **1.4%**. Ten group briefs said a name-keyed hook was the last resort.

*Two waves, ten groups, three cap crossings and one merge hazard that mattered.*
`lowering/zones.py` crossed at integration on nobody's branch — two groups'
additions summing — and the shuffles left under their own name.
`_chosen_graveyard_cards` did **not** stay behind, measured rather than assumed:
both halves call it, so it went to `_piles`. Two branches wrote
`_STATE_TESTS["enchanted"]` independently and agreed on the reading; the merge
kept one helper and routed the other's filter key through it.

*One mechanical hazard worth the line it costs.* The per-set block
reconstruction reads the merge base with `git show` — and doing that in **text**
mode decodes UTF-8 as cp1252 on Windows and silently mangles every em dash in
both branches' blocks. Read bytes. The per-line survival sweep caught it because
the mangled lines stopped matching, which is the sweep earning its place.

### MMQ — 2026-09-13

*Three waves, eleven groups, 335 cards from 73.7% — and the two rounds with no
cards in them again outweighed the cards.* W3G5 verified an inherited CR 605.3a
diagnosis instead of building on it, and the verification is the whole finding:
the symmetric difference between "what CR 605.1a calls a mana ability" and
"what the engine's fast path admitted" was **45 abilities, all one-directional**,
so every painland, storage land, Mana Battery, Urza tri-land and Gemstone Mine
put its mana ability on the stack. The reachable symptom was not the one the
brief named — there is no mid-cast state on this wire — it was **Imprison
countering a mana ability**, on the strength of a comment asserting every mana
ability resolves inline. Verifying first also caught two bugs the widening would
have *introduced*: Witch Engine targets (CR 605.5a) and Chandra's `−9: Add six
{R}` is a loyalty ability, which the reader's docstring said could not produce
mana in this pool.

*W3G4 named the hard part of a three-set-old entry, and it is a fact the AST
throws away.* The parser resolves anaphora at parse time, so "Untap target
Griffin. **It** gets +2/+2" produces two identical `TargetSpec`s — by lowering,
one target named twice and two targets named once are literally the same shape.
Of 46 announcements carrying two or more target descriptions, **42 are one
target named twice**. Any fix must first re-acquire a fact that was discarded,
which is why five parts had been enumerated three times without anyone building
them. It also settled a census disagreement the entry had carried: UDS's list of
seven was four false positives, and its live list matched W3G1's exactly.

*Four groups were interrupted mid-round with nothing committed, and all four
were recovered.* Their worktrees held 20+ modified files each and every one
compiled — +6, +4, +8 and +5 cards. The playbook's "check a dead agent's branch
before writing its work off" is worth more than it reads: the cost of checking
is one census per worktree, and the cost of not checking was four rounds.

*Zero hooks added across 88 cards, and the count moved **down**.* W2G1 retired
Metamorphosis' entry — Food Chain is the second card to print its
cost-record-plus-spend-restriction pair, which that hook's own comment said no
second card printed. Pool reliance 53/3,715 -> 52/4,026, and ARN fell 23.1% ->
21.8%.

*Phase 5's finding was the instrument, not the engine.* `simulate_ai_games.py
--set MMQ` reported Disenchant destroying nothing on a game whose own log read
`Destroyed Toymaker` one line above. Toymaker is an Artifact Creature and
`primary_type` answers "creature", so the destroyed permanent was in neither
count. The engine was right; the honesty check was lying, which is the expensive
direction — a false issue costs an investigation, and a check that cries wolf is
one nobody reads. CLAUDE.md records this class from Weatherlight at **77**
artifact creatures; the sweep that closed it did not reach `engine/ai_simulator.py`
and the population is now **114**.

*And a suspicion that measurement killed, which is worth as much as one it
confirmed.* Chasing the same Phase 5 pass, the client's activated-line regex
looked like a second instance: it is symbol-only, and a priced land's
`{T}, Remove a depletion counter from this land:` has a word in its cost. The
census said **577 of 1,743 activated lines (33%) miss it — including Black
Lotus**, which is plainly playable, so that predicate is not the offer gate and
there was no finding. A census disbelieving its own author, one commit before it
would have become a retrospective paragraph about a defect that does not exist.

*Two near-misses on one name meaning two things, in one set.* My own Phase 0
split nearly created a second `effects/prohibitions.py` where
`lowering/prohibitions.py` already means "can't be blocked"; the block went into
`effects/permissions.py` instead, the same question with the sign flipped, on
that module's own stated rule. And W3G3 added a row to `PER_OBJECT_SEAT_RECORDS`
under the key `"owner"` — which is a *printed possessive* that table is keyed by
— silently rerouting Exhume and turning four guards red. Neither is visible to a
duplicate-definition sweep: there is one definition per module either way.

### NEM — 2026-10-02

*One wave of six groups landed 53 of 56 cards with **no declines** across six
briefs — and the closing wave's three pile
groups again outweighed the cards.* Fading was a rewrite (both sentences CR
702.32a defines compiled on the day of the ingest), so one group took the
keyword and all fourteen cards that print or count it, and the three Parallax
cards that needed it waited one wave. Briefs were written as two shared files
and a per-group sheet generated from the instruments rather than from memory;
every group still corrected about a third of its own, in the direction UDS
named (the refusal site over-stated the gap: three "new" alternative-cost
shapes were MMQ's, Rusting Golem needed no code).

*Phase 0 edits:* the pre-split trigger is "shared and tight", confirmed from
the side Exodus could not see. *Phase 3:* Nemesis' no-card wave as the second
data point for the scheduling rule. *Phase 4:* rehearse the wrong insert with
the same move script. *Phase 5:* read a zero against the pre-set commit.
Zero hooks added, the eleventh consecutive set; reliance 1.3% -> 1.2%. Nothing
drained from Known gaps; the shipped defects the set measured and left are
ROADMAP entries, not playbook ones.

### PCY — 2026-10-04

*Three waves and sixteen groups; the set stood at 142 of 143 after the second,
so the third spent one group on the last card (Rhystic Cave) and four on the
pile waves 1–2 had measured and declined.* Those four fixed a colour read off
the announcement instead of asked at resolution (CR 608.2d, eleven shipped
readers), a copy entering as the printed card (CR 707.5: 165 token copies and
127 Clones whose entry trigger never fired), an AI simulator in which nothing
had ever cost mana, and cost choices the engine made for a human seat.
`oracle_diff` read **9, 0, 0 and 0** on those four merges — 6ED's finding
again.

*Integration edits:* the semantic-collision paragraph gains the wave's two
guard-versus-sibling collisions and the rule that came out of them (make the
guard state its invariant with the engine's own predicate; never allow-list
the card), plus "prove a subsuming resolution with the losing branch's tests"
and "check each worktree for uncommitted work". *Phase 4:* the wrong insert was
made with the same move script as the real one and the order guard was the
only thing that fired, as Nemesis' entry asked. Zero hooks added. Nothing
drained from Known gaps; what the wave measured and left is one ROADMAP entry
with its parts named.

### INV — 2026-10-05

*Two waves, fifteen groups and a closer, on the first set to bring machinery
the engine did not have: kicker, the pool's first multi-face layout, piles.*
Wave 1's eight groups took 221 to 323 with no hook; wave 2 spent three groups
on the twelve cards left and four on the pile wave 1 had measured, and the pile
was again the larger half — 182 spells castable with no legal target, 17
counterspells castable onto an empty stack, ten cards with an unprinted
keyword, the simulator's sixth and seventh missing pieces of a turn.
`oracle_diff` read 0 on three of wave 2's seven merges and 1 on two more -
the four pile groups moved two compiled programs between them. The closer was
one card, Psychic Battle, declined twice with its parts named, and it landed on a fact the engine was missing rather than on grammar: which targets a stack object chose (`engine/stack_targets.py`).

*Edits in place:* Integration gains the wave's three written-twice ideas and
the rules that came out (reconcile only where it is not a rules reading;
rebuild interleaved methods whole), "a gate that trusts a list" with its second
sweep, the integrator's own commits getting a merge's gate, and a guard that is
right about a sibling. *Phase 1:* supported on arrival is not driven. *Phase 2:*
the set's machinery, sized by probing. *Phase 4:* rehearse early in a throwaway
worktree; a new layout makes guards blind, not red. Briefs now tell an agent
not to end its turn waiting on a background suite. Nothing drained from Known
gaps; what the set left is one ROADMAP entry with its parts named.

### PLS — 2026-10-05

*Two waves and fourteen groups for 49 cards, on a set that brought no
machinery: Invasion's block-mate, and the second half of what Invasion built.*
Wave 1's eight groups took 94 to 142 with no hook and no decline but Goblin
Game, cleared all twelve supported cards carrying an unimplemented sentence,
and drove about eighty supported-on-arrival cards besides. Wave 2 spent one
group on the last card and five on the pile, which was again the larger half
(Phase 3 has the numbers). Zero hooks added.

*Edits in place:* Integration gains the chain of integration worktrees (gates
overlap, trees do not), rehearsing a briefed pair with its tests and a
scripted resolution, the nested-`if` union, moving whole test blocks at the
cap, resuming a dead agent, and the regression a green chain carried (a
recorded precondition read one merge late; a census that responds).
*Phase 0:* both handed seams wrong again, and a sixth split scan - what reads
the module by name. *Phase 1:* the supported-on-arrival cards are assigned and
driven; a hollow line is not a missing behaviour. *Phase 2:* a brief that
states a ruling gives its source. *Phase 3:* the five-pile wave, and "measure
first" as the brief for the risky item. *Phase 4:* a guard fix is measured by
how many lines its new arm excuses. *Phase 5:* drive one card per prompt kind
as a human seat, and read the payload while the prompt is open (three cards
driven; 404 -> 407 checked in-game; one wire defect found and fixed). Nothing
drained from Known gaps; what the set measured and left is one ROADMAP entry
with its parts named.

### 7ED — 2026-10-06

*A reprint-shaped set with seventeen cards the pool had never compiled, and
the round of fixes that ran beside it.* Ingested at 333 of 335 with a green
suite; one group implemented two productions (Sleight of Hand, Baleful
Stare) and drove the other fifteen; promoted at index 29 with no hook. In
the same two days eight agents in two rounds closed what Planeshift had
measured and left - the activation gate, the AI's mode chooser, layer 4 with
dependency, CR 305.7 for a land's own abilities, a combat choice a human
could not make - and what those rounds found on the way.

*Edits in place:* Integration gains briefing a second round from the first
round's reports on a chain link, meeting-point tests before a link's gate, a
client change is not done until clicked, and a port and a browser session per
agent. *Phase 1:* compute "new to this pool" at the ingest and give every
such card to a group. *Phase 4:* rehearse a reprint-shaped set the day it is
ingested. *Phase 5:* drive what the round changed, not only what the set
brought. What stands is in ROADMAP, with parts.

### APC — 2026-10-12

*Two waves and thirteen groups under a cap of five agents, then a closer, on
the third set of Invasion's block: 65.7% on arrival, no machinery, 143 cards
all new.* Wave 1's nine groups landed 48 of the 49 unsupported cards with no
hook, cleared the three supported cards carrying an unimplemented sentence,
and drove all 94 that arrived compiling - nine mis-played. Wave 2 was the one
declined card (Suffocating Blast) with its neighbour, five prompts a person
could not answer, CR 608.2b for abilities (479 of 622 single-target
activations wrong), and seven small defects with a card of the set standing on
each. `oracle_diff` read 3, 1, 0 and 0. The wave-2 gate's one "flaky" failure
was four memos keyed by `id(card)`; Phase 5 found a skipped main phase and two
cards failing in the browser, and a closer cleared all three.

*Edits in place:* Integration gains the Apocalypse block - the fan-out sized
to the machine and the account (five agents; no agent runs the full suite),
batch-and-bisect gates with meeting-point tests per merge, never editing a
worktree under a run, a simulation floor of one, marked test sections and
the whole-section split, resuming an interrupted wave, briefing wave 2 on a
chain link and extending a running group by message, and a red gate that
passes alone as a finding (the probe-after-every-test plugin). *Phase 1:* the
ingest's yield handed to its owning groups with the table in every brief.
*Phase 3:* wave 1 kept out of `web/static/`, one client group in wave 2.
*Phase 4:* after the first, rehearse with the guards and not the suite; the
promotion's own two reds were both guards assuming less than their invariant.
*Phase 5:* one agent with four lists, a whole game played, and the closer as
a second gate. *Known gaps:* three grammar modules inside the pre-split band
and a CI baseline nine sets old, both for the next Phase 0. Nothing drained;
what the set measured and left is one ROADMAP entry with its parts named, and
CR 608.2b's entry there is rewritten to what is now true.

### ODY — 2026-10-13

*Two waves and seventeen groups under a cap of five agents on a 16 GB
machine: 65.4% on arrival, the first machinery set since Invasion, 322 of 335
new.* Flashback was three things the engine already had and had never joined;
threshold was one condition asked in three places. Wave 1's nine groups
landed 330 with no hook and retired three; wave 2 took the five declined
cards in four groups and spent four on the pile (CR 118.9d on alternative
costs, an AI that never cast from a graveyard, "tapped for mana" as one
event, the client). `oracle_diff` moved no card a group had not named, on
any of seventeen merges. Two full gates and a rehearsal found six reds, none
in the engine, each in a file the meeting-point list did not hold.

*Edits in place:* Integration gains the Odyssey block - the meeting-point
list grows with every gate's surprises and every group reports the reds on
its base; the script and never a hand list; a test that failed once is read
the day it is reported; gate on free memory; verify a correction before
relaying it; resolve conflicts by asserting scripts; a late merge rides the
promotion's gate. *Phase 0:* count a module's reach in non-merge commits and
ask the splitters where the next set lands. *Phase 1:* run the sentence
instruments before believing the percentage (27 cards "supported" with their
keyword dropped). *Phase 4:* two rehearsals with the guards, the inventories
answered ahead by running the cards they name, and the four accepts
previewed and read in a throwaway tree.
*Phase 5:* two closers split by where the defects live - the browser's
agent for the client, a second with a census per item for the engine - and
the first re-drives the second's fixes before any row is re-recorded.
*Known gaps:* Apocalypse's entry is drained (six modules pre-split in two
rounds; the CI baseline read: 4,253 s against a budget of 940) and
rewritten - seven modules inside the band for the next Phase 0, and the
budget decision still the owner's. What the set measured and left is one
ROADMAP entry with its parts named.

*After the close:* the rules file was bumped from the April to the September
2026 edition - `scripts/cr_edition_diff.py`, five cited rules re-pointed -
and CR 605.1a's fourth criterion became a rule the engine asks rather than a
ruling it held to one cost. Phase 0 gains the bump as a step of its own.

### TOR — 2026-10-21

*Two waves and twelve groups on Odyssey's block-mate: 70.6% on arrival, one
keyword the engine lacked, 142 of 143 new.* Phase 0 pre-split ten modules in
three rounds - the last after the wave was planned, on the three modules two
groups would reach - and integration crossed no cap. Wave 1's eight groups
landed all 143 cards with no hook; madness was machinery (a keyword line
compiled to a trigger, a third discard destination, a cast during
resolution), not a rewrite. Wave 2 took no card: the client (ten items
driven in a browser), the engine and AI piles wave 1 had measured, and the
promotion rehearsal answered by an agent with a replay script. `oracle_diff`
moved no card a group had not named on any merge. The ingest's yield was
twenty reds over seven cards, each owned; the promotion's full suite found
three more, in a census no rehearsal ran.

*Edits in place:* Integration gains the Torment block - the meeting-point
run predicted every full gate, shapes deduped at briefing, every agent in
flight can stop at once, a wave-2 group answers the rehearsal. *Phase 0:*
three rounds and what each measured (ask a splitter where a card will be
*taught*; nine of ten docstrings said something false). *Phase 4:* the
promotion's own full suite is the gate. *Phase 5:* one agent; a whole game to turn 19 lost a turn to a torn state read (a per-session request lock), and 57 rows recorded, none failing. *Known gaps:*
Odyssey's module entry is drained (ten pre-splits) and replaced - five
modules inside the band and `ast/__init__.py`'s format decision, for the
next Phase 0. What the set measured and left is one ROADMAP entry with its
parts named.

### CAP — 2026-10-22 (a round, not a set)

*The module cap raised to 2,000 lines and widened from `engine/grammar/` to
every module in `engine/`, `web/` and `scripts/`, and the 35 modules over it or
inside its band split by eleven agents in two waves; beside it, the process
documents cut to what they say now.* The 1,000-line grammar cap had cost a
pre-split round before every set (Torment's was ten splits in three rounds),
because splits were cut to just under it, and nothing capped anything else:
`mixins/stack/choices.py` was 13,312 lines and `handlers/zones.py` 11,769, the
two files every wave's groups edited. Thirteen merges onto a chain of links,
each read 0/0/0 on `oracle_diff` and 0 moved on the new `sim_fingerprint` (twelve
seeded AI games, byte-compared); conflicts were import lines, guard keys and
prose, every one resolved by an asserting script. Wave 1's full gate read green
on the whole suite. The largest module afterwards is 1,789 lines.

Alongside: `CLAUDE.md` 155 KB -> 59 KB (the rules, said once; no tracker
counts), this playbook 341 KB -> 64 KB with its history moved here, `ci.yml`'s
budget narrative to five rules, and the integrator's toolkit committed as
`scripts/integration/` (with `import_names.py`, which this round needed). The
gate cadence is the meeting-point run between merges and the full gate at a
wave's close and the promotion. `.worktrees/scratch` pruned from 3.4 GB to the
hand-written notes of every round (`scratch/_archive/`).

*Edits in place:* Module splits gains the split round's five rules (temporary
re-exports and the sweep, `import_names.py`, blind module-list guards, ordered
tables whole, cutting a method by step). *Known gaps:* the restructure deleted
Phyrexian Splicer's runtime narrowing as drained when it is not, found by
reading the code comments that cite the list; it is restored. Nothing else
drained.
