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

**Four merge hazards where taking either side passes the suite.** Resolving a
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

**Weatherlight's wave 2 produced the shape twice in one wave, and the second
one is the reverse.** Two branches found the same bug — an activation cost
spelled "Sacrifice this **Aura**" that no self-cost reader matched, so five
shipped Auras had a free repeatable ability — and fixed it two ways: one added
"aura" to the hand-written alternation, the other derived the whole set from the
grammar's `_SELF_NOUNS`. **Take the derivation, not the list**: the list *was*
the bug, a second copy of something the module already owned, and it will go
stale again the next time a subtype is printed. Carry the other branch's
additions across onto the derived form rather than dropping them with its list.

The reverse is **one name meaning two things**, and it merges silently: a new
`controller_cast_ban` reader shadowed an identically named import from
`engine/auras.py` in the same file, and Brand of Ill Omen stopped enforcing
anything. A duplicate-*definition* grep cannot see it, because there is only
one definition per module. Sweep for a name defined in **two modules** across
the merged tree and then check, for each, whether any single file imports both;
Weatherlight's wave 2 ended with three such names and all three were
alias-imported at every call site, which is the check — not the count.

Ice Age's four waves added two more, both from groups **inventing the same
thing twice**. Two branches gave one AST node the same new field under two
names (`gained_by` and `gainer`) for two different cards — one fact, two
spellings, and either side alone loses a card. And two branches implemented one
printed clause ("Activate only once") as two whole mechanisms, a per-line tally
and a per-permanent counter; keeping both is the second-copy-of-one-fact this
repo forbids, and the choice between them is a *rules* question rather than a
merge one (a per-permanent count cannot follow an ability granted onto another
creature). **After every wave, grep the merged diff for two names that mean one
thing** — the duplicate-definition guard catches a repeated *name*, not a
repeated *idea*.

And one hazard that is not a merge at all: a **semantic** collision. One branch
split "an opponent" from "target opponent" into two parsed kinds; another
branch's table had been written when a single kind covered both. Every file
merged cleanly and three tests failed at runtime. Nothing textual can find
this; what finds it is running the suite between merges rather than at the end.

**Prophecy's third wave produced it twice more, and both times one side of the
collision was a *guard*.** A pool-wide guard written on one branch states an
invariant over the pool that branch could see, and a sibling branch of the same
wave changes the pool. W3G2's "every chosen colour is asked at resolution"
sweep named Rhystic Cave, which W3G1 had just made a mana ability that answers
at activation (CR 605.3b); W3G1's "the AI's plan counts a land exactly when the
tap seam taps it" sweep named six lands W3G4 had just taught the plan to
decline. Neither was a regression and neither guard was wrong when written —
each had asserted an equality where the invariant was narrower. **The fix is
to make the guard state its invariant, using the engine's own predicate, never
to add the card's name to an allow-list**: the first now skips a line whose
abilities are all `is_mana_ability`, which its own docstring had already
exempted in prose for a different spelling; the second asserts the plan never
counts a refused land and declines only what `_land_mana_is_unplannable` names,
with a ceiling on how many. When a merge turns a *new* pool-wide guard red on a
card the *other* branch touched, drive the card before touching either side.

The same wave had **two branches fix one line by two routes** (the AI tap
planner's land filter: one asked `taps_for_payment`, the other the tap seam's
own gate). That is Weatherlight's Aura shape below — take the one that
subsumes the other, and prove it with the *losing* branch's tests rather than
by reading: W3G1's Cave tests passed on W3G4's predicate, which is what made
dropping W3G1's spelling safe. And **look in each worktree for uncommitted
work before merging its branch**: one held a change written against a premise a
sibling had since removed (a card it special-cased as unsupported was
supported), which is a decision for the integrator, not something `git merge`
will ever show.

**Invasion ran sixteen groups through two waves and produced each of those
shapes again, with three things worth adding.**

*The same idea was written twice in one wave three times, and a conflict is
the cheap place to find it.* W1G3 and W1G5 each read "a <noun> of each <kind>"
at the same line of `condition_counts.py`; W1G4 and W1G1 each resolved an
"…instead" sentence's back-reference at the same line of a rider; W1G2 and
W1G8 each built CR 601.2c for a spell that targets a spell as a method at the
same spot. All three surfaced as conflicts, which is luck — the name sweep
found none of them, because each pair had different names. Two rules came out
of it. **Reconcile at the merge only when the answer is not a rules reading**:
the first pair was (one reader per characteristic, and it landed Coalition
Victory, which neither branch could), the other two were kept side by side and
handed to wave-2 groups by name, and the group that folded the "instead" pair
found that one of the two behaviours was simply wrong. And **when two methods
conflict through their identical middle lines, rebuild the region from each
side's whole functions** rather than hunk by hunk — git interleaves the bodies,
and a hunk-wise union splices one signature onto the other's body.

*A gate that trusts a list makes the list load-bearing, and the sweep written
with the gate cannot see it.* W1G2 made the stack picker's list the
announcement gate; the picker read a spell's type off `primary_type`, so from
that merge Annul refused an artifact creature spell — a regression the
integrator merged with a green suite, because every victim in the new sweep
had one card type and a gate that *is* the picker agrees with the picker by
construction. It was found only because a sibling group had built the same
gate, measured the picker against the handler, and scoped around the
disagreement. **A sweep that holds a gate to its source needs a second sweep
holding the source to what acts** (here: turn the gate off, resolve, and name
anything the handler acted on that the picker did not offer).

*An integrator's own commit between merges gets the gate a merge gets.* That
fix shipped with a misplaced import and broke four tests; the targeted run it
was committed on had not included either card that reached the branch. The
next full gate caught it, one merge late. Nothing a group is asked to do is
optional for the integrator.

**And one that is new: a guard written on one branch that is *right* about a
sibling's work.** Prophecy's collisions were guards asserting too much. W2G4's
face-blind guard (below) fired at three later merges, naming six sweeps five
other groups had written in parallel over the raw pool — and each time the
guard was right and the loops were converted. Read which it is before touching
either side; the test is still "drive the card".

**Planeshift ran fourteen groups through two waves and changed where the
integrator's time goes.** Four things, each a procedure rather than a moral.

*Gates may overlap in time; trees may not.* "Merge one branch at a time, full
suite between merges" was costing a suite's length per branch with the
integrator idle. The rule it protects is that **every cumulative tree is tested
before main rests on it** - and nothing in that needs the suites to queue. So:
stage each merge in its own integration worktree on top of the previous one,
start that tree's full gate, and build the next link while it runs; main only
ever fast-forwards to a tree whose **own** gate came back green. Five wave-1
merges went through in about forty minutes of wall clock instead of three
hours, eleven in all across the set, and no gate was red - which is a
statement about the gates, and the last paragraph of this entry is about what
they could not see. Three conditions make it honest. A merge commit claims
only what was verified when it was made (the conflict resolutions,
`oracle_diff`, the duplicate and missing-name scans) and says where the suite
result will be recorded - a commit that closes the wave.
The tracker regeneration is committed per link, so `check_all` at the end of a
gate reads clean rather than "stale". And a red link stops the fast-forward
there: fix it *in that link*, then rebuild or merge forward the links above
it. Three or four gates at `-n 4` fit this machine with nothing else running.

*When two groups are briefed to edit one function, rehearse the pair - and run
their tests in the rehearsal.* W1G1 and W1G2 both rewrote the kicker reader and
were told so. Trial-merged in a throwaway worktree before either was merged,
git reported four files in conflict - and the defect that mattered was in a
fifth with none: one branch renamed a local, the other added a line reading
the old name. Eighteen tests failed in the rehearsal and nothing failed at the
merge, because the resolution had been **written as a script** by then
(assert the conflict regions are the ones you read, rewrite them, apply the
semantic fix) and was replayed. A resolution you can replay is one you can
test before it is the merge.

*A union can also nest.* Two branches each added a CR 601.3 refusal to the same
reader at the same spot, and both regions ended on a shared `return False`. A
hunk-wise union puts the second `if` inside the first: an AND where the rule is
an OR, syntactically valid and green on any test that needs only one of them.
It is the `if`/`elif` hazard above with the arms stacked instead of chained;
check what follows the closing marker before keeping both sides.

*The per-set test cap is crossed by what you asked for.* Wave 1's groups wrote
a test per driven card (Phase 1), so the creatures file crossed its cap three
times at integration, on nobody's branch. A block carries its own imports, so
the fix is mechanical and belongs in the merge step rather than after it:
while the file is over the cap, move its **last** block whole to a second file
(`test_<set>_creatures_later_groups.py`), assert every line survived, and let
later groups append to whichever has room.

*And a dead agent resumes.* One group died mid-task on an API authentication
error with four commits and a three-line measurement uncommitted. The older
advice - check its branch, finish the verification yourself - is the fallback.
First look at the branch, the worktree's diff and the newest files in its
scratch, then **send it a message saying exactly what state you see and what
is left**: it resumed from its transcript, reverted the measurement, ran its
suite and reported, forty minutes later, with everything the brief asked for.

*A green chain says what the tests say, and the last link of this one put a
regression on `main` with every gate green.* ROADMAP had recorded a set
earlier, by card name, that when entry triggers moved to the stack one handler
would need a check that its source was still on the battlefield (CR 610.3b).
The group that moved them was not handed the sentence. Its census - 807
scenarios, identical by both roads - was run with nobody responding, which is
the one table on which a trigger's timing cannot matter. And the integrator
read the entry while drafting this retrospective. All three cards the pool
prints "until this leaves the battlefield" on were wrong: cards exiled for
good, a creature phased out for ever, a prompt no seat could answer. It was
fixed before the promotion, for the price of a second promotion gate. Three
procedures came out of it:

- **Grep ROADMAP for the mechanism before briefing the group that changes
  it**, and paste what it says into the brief. A recorded precondition belongs
  to whoever removes the thing it waits on.
- **When a change makes something possible "in response" for the first time,
  its census has to respond** - destroy the source between the trigger and its
  resolution - and that census belongs in the suite, validated backwards
  (`test_entry_trigger_source_leaves_census.py`: 511 entries; it names two of
  the three cards on the unfixed handlers, and the third is a stuck prompt its
  own test names).
- **"No card in the pool can do X" is a census nobody ran.** The first draft
  of the fix said, in a docstring, that nothing could *phase* one of these
  sources out in response, and so treated a phased-out source as gone. Four
  cards can, and CR 702.26d says phasing is not leaving. One query over the
  pool is cheaper than the sentence.

Fallen Empires added two more, both about *how the conflict is resolved* rather
than about what conflicted. **A whole-file `--theirs` (or `--ours`) discards the
hunks that were never in dispute.** Resolving one conflicted file that way would
have silently dropped a **third** branch's node, which had merged cleanly into
the same file minutes earlier — the file was in conflict, the node was not.
Resolve the conflict, never the file: restore the conflicted version with
`git checkout -m <file>` and take the sides hunk by hunk. And **a union can
break an `if`/`elif` chain.** Two branches each added a branch to one dispatch
function; keeping both put the second one's `if` where the first's `elif` had
been, so the first branch's answer was computed and then overwritten by an arm
that found nothing. Three tests were green on each branch alone and red on the
merge. When both sides add an arm, check what the arms are arms *of*.

**One scratchpad channel can end up carrying two value shapes**, which is the
same class one level down. Two branches wrote to the same record key, one a list
and one a bare id, and the single reader that received both raised. Normalising
at the reader is the local fix; the question of what arity the *channel* has is
a real one, and belongs in Known gaps rather than in a comment.

**Give every group's test block its own imports, and the header hazard is
designed out.** The block convention below makes per-set test merges
mechanical, and the mechanical move is "take `ours`, append the branch's
block" — which silently loses any `import` a branch added at the *top* of the
file. Ice Age's answer was to diff branch-minus-block against the merge base
before trusting the reconstruction. Fallen Empires' is better and costs
nothing: **open the per-set test files on `main` before the fan-out, with a
header telling each group to put its imports at the top of its own block.** A
self-contained block cannot lose an import, and every group's first write
becomes an append rather than a file-creation collision. Still assert it rather
than trust it — the reconstruction script should check that the branch's copy
of the shared header is byte-identical to the merge base's, which is one
comparison and catches the case where a group edited the header anyway.

The hazard survives in one place the convention does not reach: **a function
*moved* between modules leaves its imports behind.** That is the same failure
with the file boundary in a different spot, and at FEM's integration it caught
the integrator rather than a group, when a cap split carried three functions
into a new module and left one of their imports in the old header. It fails
loudly — 132 collection errors — so the fix is cheap; sweep every module you
moved code out of before running the suite.

**A split needs five scans, and three of them fail nothing at import time.**
Tempest added the fourth and fifth. The fourth is **anything keyed on a file
path**: `tests/engine/test_cr_citation_subjects.py`'s `REVIEWED` set is keyed by
path *and* number, so a moved block breaks it in both directions at once — the
new file's citation has no excuse and the old file's excuse has no citation —
with nothing undefined, unused or duplicated. The fifth is **execution order for
module-level code**: a name imported by a *later* block satisfies a
"is it imported anywhere" check and still raises at import or collection. A
per-set test file split failed exactly this way, with `import pytest` at line 746
and a module-level `@pytest.mark.parametrize` at line 281. The block convention
makes each block self-contained *in isolation*; it does not survive a split that
changes which block comes **first**.

**A split needs three scans, and only one of them is documented anywhere else.**
A **dead-import** sweep asks "what does this module import and no longer use";
a **missing-name** scan asks "what does it use and never import *or define*";
a **duplicate-definition** sweep asks "did the split copy this rather than move
it". Only the second and third are bugs, and neither fails at import time.

The missing-name scan is the one to run **before** the suite rather than after.
A `NameError` in a function body waits for its line to run, so a smoke import
of the package passes; at Alliances it fired three times in a single wave, once
for **246 test failures** when a helper stayed behind while its only caller
moved out. Run it as an AST walk over every module the split touched — collect
each module's defined names plus its imports, subtract from the names it loads,
and expect an empty set (string annotations under `from __future__ import
annotations` are inert and read as false positives).

The duplicate-definition sweep is the one nothing else can see. At Alliances a
production was defined **byte-identically** in both halves of an earlier split,
with the only caller in the new home — a copy, not a move.
`test_no_module_defines_the_same_name_twice` looks *within* a module, so it is
blind to this; the dead copy imports clean, tests green, and is simply never
reached. Grep top-level `def`/`class` names across the package after any split.

The dead half is not harmless either, only silent: 310 such imports have
accumulated across `engine/` from earlier splits, which is a ROADMAP item now.

**And a dead import can be invisible until a move exposes it, because a
function-level import of the same name reads as using it.** The Phase 0 after
MMQ moved two functions out of `lowering/_records.py` and
`test_import_hygiene.py` then failed on a module-level `from .. import ast` —
which had been dead *before* the move as well. Its only `ast.` references were
inside those two functions, and each of them opened with its own
`from .. import ast`, so the module-level binding was shadowed at every use. To
a scan asking "is this name loaded anywhere in the module" the answer was yes,
and it stayed yes for as long as the shadowing functions sat there.

Two things follow. **Run the dead-import sweep on the module you moved code
*out of*, not only on the one you moved it into** — that is the half of the
"imports left behind" hazard the playbook already names, and this is its
quietest form. And **a function-level import of a name the module already
imports at the top is worth deleting on sight**: it is not a cycle break, it is
a shadow, and its only lasting effect is to hide whether the top-level binding
is still earning its place.

**A module crossing the 1,000-line cap with no branch at fault is the
integrator's split, and the module usually names its own seam.** Alliances
produced two in one wave — four groups adding a few dispatch arms each took
`lower.py` from 964 to 1,006, and two groups took `effects/cards.py` to 1,005.
Neither is a branch to send back. Cut where the module's own docstring already
draws a line, and prefer the half that **grows with the pool** over the half
that has been stable: `by_node.py` recorded that principle at Fallen Empires
("the table is a registry either way, and `lower.py` is dispatch") and it
applies unchanged when *both* halves are dispatch. Reuse the mirror's family
name if one exists, so the split re-forms the mirror instead of forking it.

**Two branches splitting the same module in one wave is a real shape** — both of
HML's waves produced one. Their import blocks are where they meet, and **neither
side is necessarily right**: one kept an import whose users had moved out, the
other dropped one still used. Resolve by counting references in the *merged*
body, not by taking a side.

**Expect cap breaches that no single branch caused.** The 1,000-line grammar
guard and the 2,600-line per-set test guard both fired at *integration* seven
times across Ice Age's four waves, on files where two groups' additions merely
summed. This is the guard working rather than failing: the family boundary was
already there and the collision is what surfaced it. Take the split then and
there, and **reuse a family name the other side already carries** —
`destruction`, `keywords`, `tapping`, `types`, `trigger_tables`,
`sentence_clauses` and `upkeep` all re-formed that way rather than forking a
new vocabulary. Never raise a cap.
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

**The Dark revised that number upward, with conditions.** Twelve group agents
ran across three waves — five, then four, then three — and eleven finished. The
budget is not the constraint it was; **integration** is. Each wave cost the
integrator roughly as long as the wave itself, and almost all of that went on
merges rather than on cards. Plan the round with that ratio in mind, and note
that one agent died mid-task with committed work plus an unverified working
tree: check a dead agent's branch before writing its work off, and finish its
verification yourself rather than merging what nobody watched run.

**Ice Age held that shape at scale: 21 group agents over four waves of five,
and every one finished.** The budget is not the constraint. Integration is,
and the ratio was roughly one integrator-hour per wave-hour — spent on cap
splits and on the four merge hazards below, not on cards. Two operational
notes the waves earned: **`git stash` is shared across sibling worktrees** (two
agents popped another group's WIP into their own tree; brief every group never
to use it, and commit instead), and a **shared scratch directory collides**
— give each group a private subdirectory or they overwrite each other's probes.

**Write each decline as a list of parts, and the next wave finishes them for
free.** This is the highest-leverage instruction in the whole process. Expect
the *parts* to be wrong and take them anyway: UDS's three wave-2 cards each
arrived with a list of four to nine named pieces, and in every case roughly half
were already built — a resolver where the list said an enumeration, two words
where it said a subsystem, an existing prompt kind where it said a new one. A
list that is half wrong still routes the round to the right file and is
answerable in an afternoon; "too complex" is answerable by nobody. Ice Age
declined ten cards across three waves, every one with its missing pieces
enumerated individually rather than as "too complex" — and other groups then
built those pieces as a side effect of unrelated work. Chaos Moon's parity
condition was built by *Chaos Lord's* group; Winter's Chill's cast-time X
plumbing by Spoils of War's. All ten eventually landed. **State in each brief
which pieces other groups have already finished**, or the wave rebuilds them.

**A group that verifies an inherited diagnosis before building on it is worth
a group that builds.** MMQ's W3G5 was handed a one-paragraph CR 605.3a finding
from an earlier wave and told to measure it first. The diagnosis held — unusually
— but measuring it caught two defects the fix would have *introduced* (a mana
ability that targets, and a loyalty ability that produces mana, both of which a
naive widening would have broken), and corrected the symptom: the reachable
failure was a counterspell hitting a mana ability, not the "cannot tap mid-cast"
the brief described. **Budget the verification as part of the round, not as a
preamble to it.**

**And require a census to disbelieve its own author.** The same Phase 5 nearly
recorded a second finding — the client's activated-line regex looked blind to a
priced land's cost — and the census killed it: 577 of 1,743 lines miss that
regex, Black Lotus among them. One measurement, one commit before it became a
retrospective paragraph about a defect that does not exist. A suspicion that
survives its own census is worth writing down; one that does not is worth the
census.

**Ask every group what the brief got wrong, and expect a third of it to be.**
Every report across four waves corrected roughly a third of its own brief, and
that section was consistently the most valuable part. The corrections were not
quibbles: one brief called a card "the hardest in the set" when it was the
cheapest, another scoped a subsystem migration that turned out to be the wrong
file entirely, and a third counted 89 call sites for a change that touched
seven functions. **A refusal site is a work-list entry, not a diagnosis**, and
an inherited estimate is a lead to correct rather than a fact to trust.

**Urza's Legacy named the direction the error runs in, which makes it
predictable.** One group put its correction rate at "roughly half, and
consistently in the same direction — it over-estimated four cards and
under-estimated two", and the four over-estimates were all the same mistake:
*the brief's diagnosis was written from a refusal site, and a refusal site names
where the parser stopped rather than what is absent.* Molten Hydra's whole card
was that `+1/+1` lexes as a `PT` token so a `peek_word()` answered None; Viashino
Heretic's was **one article**; both of the "extra pieces" that brief scoped for
it had been built two sets earlier. Meanwhile the two under-estimates were
sentences whose refusal really was a probe-order artifact *and* which needed two
more layers nobody had mentioned. So: assume a refusal site over-states, probe
before believing it, and treat "this is only a probe artifact" as the claim most
likely to cost a card.

**Two cards in one wave were reported as needing a whitelist widened, and both
diagnoses were wrong in the same expensive way.** The `becomes a … creature with
⟨keyword⟩` body was not gating on a keyword list — the list had held `first
strike` all along; the loop read **one token** with `peek_word()` against a set
of ability names, a fork of the shared `parse_keyword_list`. Fixing it as
briefed would have produced a *second* whitelist rather than removing the fork.
**When a brief says "widen the whitelist", check first whether the whitelist is
being consulted at all.**

**Brief every group to make a name-keyed hook the last resort, explicitly.**
Twelve independent agents under that instruction produced *one* new hook in 119
cards and retired another, so the hooked share of the pool fell while the pool
grew. The brief is doing the work there, not the reviewer. Ice Age went
further under the same instruction and the direction compounds: **nine hooks
retired, none added**, across a set that grew the pool by a third — reliance
6.0% → 4.2%. Say it in every brief, every wave.

**Give each group a delimited block in the shared per-set test files.** Groups
split by grammar family still collide in `tests/sets/test_<set>_*.py`, because
the file is chosen by the card's printed type and every group has creatures. A
`# --- G3: <topic> ---` header per group makes every one of those an
append-conflict resolved by union, which is mechanical. Without it the
integrator is reading two unrelated diffs in one hunk.

**The convention works and it has exactly one failure mode.** Every per-set
conflict across HML's two waves was two appends. One came back as **two conflict
regions**, because both branches' helper functions happened to end with the same
two lines (`game.enforce_mana_costs = False` / `return game`) and git matched
them as common context — a naive union would have spliced one group's helper
body onto the other's signature. So make the union **refuse anything but a
single two-append region**, and keep a fallback that reconstructs from the merge
base: assert both sides start with the base byte for byte, then base +
ours-tail + theirs-tail. The assertion is the point — a branch that edited the
shared prefix cannot be reconstructed this way, and that is the case worth
failing on rather than guessing through.

**The reconstruction's premise is that only groups append, and the integrator
breaks it.** Its assertion — both sides start with the merge base byte for byte —
fired correctly at Tempest on a file whose `main` copy no longer did, because
*the integrator* had edited an earlier group's block mid-wave when a decline
expired. Keep the assertion; it is right. The fallback when it fires for that
reason is a union at the **hunk** rather than at the file, with the same
per-line survival check afterwards.

**Alliances hit that failure mode for real, and taught the follow-up: after
resolving one, sweep *every* block in *every* per-set file the wave touched.**
Two groups' helpers both ended with the same line, git took it as common
context between the two regions, and a union spliced four lines of one helper's
body onto the other's — the four that actually put a permanent on the
battlefield. Three tests caught it; nothing else would have. The sweep is
mechanical: for each branch and each file, check that every non-blank line of
the branch's block is present in the merged file. It found nothing else that
wave, which is the result you want and cannot assume.

**Two hazards specific to parallel authorship, both silent.** Git resolves
"both branches added a function" as *two functions* rather than as a conflict,
and Python takes the later one — see ROADMAP idiom 25, and run
`test_no_module_defines_the_same_name_twice` after every merge. And when one
branch *moves* a class while another *adds* to it, the conflict presents as
"ours: nothing, theirs: the whole class"; carrying the fields across is not
carrying the method that emits them (idiom 26).

## Known gaps / pending pre-work

A drainable list of things the playbook knows are not yet true, each naming
the phase that clears it. A retrospective that drains an item deletes it; a
set that hits a new one adds it.

**Added at USG's Phase 6: a hooked card's every sentence is blanket-claimed, so
`parse_coverage` cannot see an unimplemented line on it.** W3G3 retired Drop of
Honey's `card_hooks.py` entry and the retirement *exposed* a second printed line
— "when there are no creatures on the battlefield, sacrifice this enchantment" —
that nothing had ever implemented. `parse_coverage` had been reporting the card
fully claimed the whole time, because a card with **any** hook entry has all of
its sentences attributed to that entry.

That is a hole in the one instrument built to find unimplemented lines, and it
is exactly the failure mode the instrument exists to catch, hiding inside the
instrument. It is bounded by the hook count — 53 cards — and it shrinks every
time a hook is retired, which is the wrong direction for a guard: the *fewer*
hooks there are, the more it looks like the instrument is working.

**Drained 2026-09-09, at ULG's Phase 4, as both parts the entry asked for.**
The claim is attributed to the lines `CARD_LINE_INSTRUCTIONS` names, and only
the four **event**-keyed registries (`ON_LEAVE_BATTLEFIELD`, `ON_SELF_RESOLVED`,
`ON_SPELL_COUNTERED`, `DRAW_STEP_MODIFIERS`) still claim a whole card, because
each implements an event rather than a sentence and has no line to point at.
That exception is 3 sentences where the blanket was 80, and it is listed by
registry name rather than discovered, so a new *line*-keyed registry cannot be
folded in and handed back the blanket.

**The first draft was wrong in the safe direction and the correction is the
carryable part.** A `CARD_LINE_INSTRUCTIONS` key is a whole printed **line** and
the script claims per **sentence**, so demanding equality reported the body of
every multi-sentence hooked line as unclaimed — 66 sentences on 39 cards, none of
them real. The test is containment, which is still exact where it matters: a
sentence the hook's line does not contain is a sentence the hook does not
compile.

**The second number was 1**, and it is a *reporting* gap rather than a missing
implementation — which is what a claim table is for. City in a Bottle's hook
compiles its sacrifice trigger; its second line ("Players can't cast spells or
play lands with a name originally printed in the Arabian Nights expansion") is
enforced by `mixins/effects._set_lockout_banning_card`, which scans for the
instruction the *first* line produces. Driven before naming it, and it now has a
`CARD_CHANNELS` entry. Two guards hold the narrowing, because the report's own
numbers cannot fail.

**Added at USG's Phase 6: `simulate_ai_games.py` never enters a main phase.**
W3G3 checked a claim in its brief rather than believing it and found the
simulator's turn loop is bookkeeping → untap → upkeep → draw → cast, with no
`_enter_main_phase` call at all. So every `main_phase_first` /
`main_phase_each_yours` trigger in the pool — Sanctum of Fruitful Harvest,
Eladamri's Vineyard, USG's Carpet of Flowers — has **never fired in an AI game**,
and a Rock Hydra test routed through the simulator silently exercises nothing.

Not a wrong result, an absent one, which is why no guard sees it: the run
completes, the interaction count is non-zero, and the issue list is empty. It is
the same shape as the `begin_turn_bookkeeping` omission this set fixed between
waves, in the same function, and that one cost six shipped cards their per-turn
records.

**Drained 2026-09-09, at ULG's Phase 0.** `_enter_main_phase(precombat=True)`
plus the priority-window drain the entry deliberately does not do (a main phase
is not closed before the active player acts in it). Validated backwards, which
is what makes it a finding rather than a hope: a seeded six-game run pinned to
Carpet of Flowers produces **9** log lines against the parent commit — the cast
and the permanent entering, and nothing else ever — and **51** with the fix.
Unlike the `begin_turn_bookkeeping` omission it repeats, **the re-baseline was
not a no-op**: four of seven seeded set runs moved and two moved their game
outcomes, because the loop now casts *during a main phase*, so a sorcery-speed
activation the phase gate had been refusing all along is legal.

**And clearing it exposed the sibling, which is larger: the AI simulator has no
combat phase at all.** W2G4 went to add a `refused_attacks` counter — the attack
side of the `refused_casts` honesty check — and found the counter would read 0
for ever, because the loop never declares an attacker, never blocks and never
runs the combat damage step. So **`simulate_ai_games.py` cannot validate any
combat change**, and "run the sim" is not an end-to-end check for combat work;
that group replaced it with a census parametrised over every card printing a
declaration-level restriction, backwards-validated at 4 of 8 cases failing
against the pre-fix engine. Adding combat to the loop is its own round and owes
a re-baseline that will certainly move every seeded run. **Phase 0 of the next
set is where to decide whether to take it**, and the honest reading is that the
loop is a *casting* simulator with a main phase, not a game.

**Drained 2026-09-09, as its own round.** `engine/ai_combat.py` drives the
phase, and it is a loop over the engine's own `advance_combat_phase` rather than
a second step walker: that method returns *without moving* at exactly the three
points where a player owes a turn-based action, so "advance, and if nothing
moved, supply what it is waiting for" needs no list of wait states to go stale.
All 23 shipped sets now attack, block and deal combat damage — 57–196
declarations each, up to 261 attackers, 96 blockers, and 37 multi-blocked or
banding splits on Mirage, which is a path no simulated game had ever reached.

**The re-baseline moved every seeded run, and the honest summary is that the
runs got shorter.** Interaction counts fall across the board (LEA 398 → 332)
because games now *end* — creatures kill people, where before every game ran to
the turn cap with both seats near 20 life. That is the change being real rather
than a regression, and it is the second consecutive re-baseline in this function
that was not a no-op.

**Two lessons worth keeping.** The counter W2G4 declined to add was right to be
declined and is now right to exist: `refused_attacks` could only ever have read
zero before a simulated seat could declare an attack, and a census that reports
zero and means nothing is exactly what that group refused to build. And **the
declaration, not the walking, is what had to be shared** with `web/` — a refused
declaration is silent, and that silence is what hid both attack caps, so a
second copy of the fallback chain would have been a second place for it to hide.

**And the round found a shipped crash before it found anything about combat.**
`simulate_ai_games.py --set TMP` did not fail an assertion, it died with a
traceback: `event_durations.holds_window` asked `REMOVED_ABILITY_LINES` for a
`duration` key on a channel that is bare strings by construction, where it meant
`REMOVED_ABILITY_KEYWORDS` — two constants one word apart. It needs a Licid *and*
a creature spell, so both halves worked alone and Tempest had no simulation
coverage at all. **A set whose run dies is invisible to every number the script
prints**, which is an argument for reading the exit code of each set's run rather
than the summary of the one you happened to name.

**Added at FEM's Phase 6: `permanents_from` carries two arities and only one
reader knows.** That payload key names a scratchpad record, and its producers
disagree about shape — a reanimation writes a *list* of permanent ids, a
choose-one prompt writes a bare id. Two branches of one wave wrote each, both
reached `add_counter_to_target`, and it raised. That reader now normalises and
says so; every *other* reader (`handlers/destruction.py`,
`handlers/control_changes.py`) reads the scalar shape only and would raise on a
list. Nothing is broken today because no list-producer feeds those readers, which
is the kind of "safe by which cards exist" this repo does not like. **Phase 3 of
whichever set next adds a `permanents_from` producer clears it**, by deciding
the channel's arity once — most likely always-a-tuple, with the readers that
want one object asserting they got one — rather than by adding a third local
normalisation.

**HML added two producers and still did not settle it, so this stays open with
its scope now measured.** Both new producers matched the reader they fed —
Joven's Ferrets writes a *list* under a key whose reader iterates, and W2G1's
sacrifice writes the *scalar* shape — so nothing raised and nothing forced the
decision. Which is the item's own point restated: it is safe by which cards
exist, and two more cards existing did not change that. The next set that adds a
producer feeding a reader of the *other* shape is the one that pays for it;
whoever takes it should take it as the arity decision rather than as a bug fix,
because the bug will present as a single raised exception on a single card.

**Alliances grew it again without settling it, and the growth is the argument
for taking it.** The spread went from 17 producers / 13 readers to **20
producers across `lowering/` and 20 reader sites across eight files in
`handlers/`** (combat, control_changes, damage, destruction, permanent_choices,
prevention, pump, tapping), still with **exactly one** reader normalising, in
`pump.py`, whose own comment calls itself "the *local* half of a wider question".
Three sets have now paid interest on this and none has paid the principal. The
readers are no longer a short list somebody can hold in their head while adding
a producer, which is the condition under which "safe by which cards exist"
stops being safe.

**Drained 2026-09-05, at VIS wave 1** (`09a5f9ad`), as the arity decision rather
than as a bug fix, which is what the entry above asked for. The channel is
**always a sequence**, read by `handlers/_common.recorded_permanent_ids` and
nowhere else: a producer writing a bare id is read as a sequence of one, and the
readers that want a single object go through a sibling that asserts it got one
rather than normalising locally. Both local normalisations are gone.

**And Visions found the half nobody had named, at wave 4.** Settling an arity is
only half of settling a channel — the other half is the **element type**.
Equipoise chose the right permanents and **phased out none of them**, logging "0
permanent(s) phased out" while reporting supported with every sentence claimed
and no hollow line, because `recorded_permanent_ids` filtered on
`isinstance(entry, int)` while `chosen_this_way_objects` holds live `Permanent`s.
A channel whose arity is settled and whose element type is not fails exactly the
way the arity did: silently, on one card, in the direction of doing nothing.
Whoever settles the next shared channel owes both questions in the same round.

**A re-check owes one probe of the *code*, not just one probe of the set.** 6ED's
W1G4 found its entire brief had been drained two days earlier by the set that
raised it, after two consecutive Phase 6 re-checks had each counted their set's
printings of the phrase, correctly concluded the set did not meet the trigger,
and never opened the file the entry names. Amending a trigger condition is not a
substitute for opening the implementation. A decline ages in the direction of
becoming free, so the question a carried entry needs answered is "is this still
undone?", which only the code can answer.

**This entry outlived its own drain by two sets, which is the process finding
worth keeping.** It was drained at VIS wave 1 and went on being carried as open
through the VIS, WTH and TMP retrospectives, each of which re-read it and left it
— because a Known-gaps entry is read as a work item and nobody re-checks a work
item's *premise* against the code. That is the same failure mode the alternative-
cost entry hit from the other side (its premise "the set is measured" expired at
a promotion). **Phase 6 owes each entry it carries forward a check that the entry
is still true**, not just a check that its work is still undone.

**Added at ALL's Phase 6: an optional cost has no picker, and two cost kinds now
want the same one.** `web/_cost_picker_spec` models a **mandatory** additional
cost — "you will pay {1}{R}" — and both of the optional kinds this engine has
grown need an *offer* shape instead: "cast for {1}{R}, or plus {1}{R}, or plus
{1}{G}?", with a per-offer counter, because one printed sentence can offer two
independently (Primitive Justice's `{1}{R} **and/or** {1}{G} any number of
times"). W1G4 recorded it for CR 118.9's alternative cost and W3G1 hit it again
for CR 601.2b's repeated additional cost. Nothing is broken: the only
announcement today's client can make is the no-offers one, which is the cast the
existing picker already gets right, so every affected card is playable at its
printed default and unplayable at any other. **Phase 3 of the next set that
prints either kind clears it**, as four parts — the offer prompt, a payability
ceiling per offer computed from pool and board, a several-target collection
whose maximum is recomputed from the answer through
`oracle_types.cost_target_count`, and sending the map on the cast action.

**Drained 2026-09-05, at VIS wave 4, and the deferral was costing more than it
looked.** All four parts landed: `legality.cast_cost_offers` describes each
offer with a ceiling computed through `mana_payment.plan_payment` over the pool
*and* the untapped lands; `cast_target_spec` takes the answer so far and
recomputes both that ceiling and CR 601.2c's count; `startCastOfferPrompt` in
`web/static/app.js` is the prompt, re-asking the spec after every click; and the
answer rides `pendingCastCost` onto whatever body the cast finally posts.

The reason to record it is the premise the deferral rested on. Each wave wrote
that the affected cards were unreachable because their set was `measured` — and
that was true when W1G4 wrote it and false by the time W3G1 repeated it. **Nine
of the ten cards are shipped**: Force of Will, Pyrokinesis, Contagion, Bounty of
the Hunt and Scars of the Veteran (CR 118.9, all ALL), Primitive Justice, Taste
of Paradise and Undergrowth (CR 601.2b, all ALL), and Fire Covenant (ICE). Only
Infernal Harvest is in Visions. A gap whose entry says "nothing is broken while
the set is measured" needs its **role** re-read, not just its cards: a promotion
drains the premise without touching the entry, and nobody looks again.

A fifth part came with it, from the same premise. `web/static/app.js` decided
"does this card need an X?" by substring-probing the printed **mana cost**,
which is one of the four places CR 107.3a names — so Fire Covenant ({1}{B}{R},
"pay X life") and Infernal Harvest ({1}{B}, "return X Swamps you control to
their owner's hand") were offered no X box and cast at CR 107.3b's default of 0.
`cast_costs.cast_announces_x` is now the one reader, and `announces_x` /
`max_x` on the cast spec are what the browser asks.

**Added at MIR's wave 1, and half-drained at wave 2: the chosen-source shield.**
Three prevention handlers had byte-identical bodies differing only in which
`shields.make_*` builder they called. W2G3 removed the duplication itself
without being asked to: one `chosen_shield_source` reader of "a source of your
choice" shared by all five shields *and* by a redirect, one
`_arm_chosen_source_shield` body, one `make_chosen_source_shield` builder the
ten named wrappers delegate to.

What is left is the part it was right to refuse: the four instruction **kinds**
are still four. `Shield.kind` is read by `targeting.py`'s picker table and
`effect_labels.py`'s support buckets as well as by the interceptors, so folding
them into one kind with the rider as payload moves every affected card's
compiled program. **That wants its own round and its own `oracle_diff`**, not a
ride on a round that was about cards — which is the general rule this entry is
now here to record: a refactor whose blast radius is the whole pool does not
travel with a wave.

**Drained 2026-09-05, at VIS wave 4: `_per_recipient_count` meant two
things** — a per-seat count spec in `lowering/_amounts.py` and a per-object
multiplier in `lowering/_sweeps.py`, both module-private, neither broken, and
invisible to the duplicate-definition sweep because it was already true before
the wave that found it. **Neither kept the name.** Renaming only one would have
left the other reading as the real `_per_recipient_count`, and the point of the
entry was that there never was one: they are now `_recipient_seat_count` and
`_per_recipient_multiplier`, each saying which fact it is. The payload key
`per_recipient_count` is unchanged, because it is read by handlers and renaming
it would move every affected card's compiled program for a naming fix.

**Added at MIR's Phase 6: the testable-keys preamble is copied, and the copy is
load-bearing.** Three places in `lowering/prevention.py` open with the same two
lines — `described = _filter_payload(x)` then `if not described or
set(described) - TESTABLE_SUBJECT_FILTER_KEYS: raise LoweringError(...)` — and
the looser form of the same question (`_restrictions_beyond`, or an inline set
difference) appears across **32** of the lowering modules in several spellings.
It is not a duplicate *definition*, so the merge scans cannot see it, and every
copy is correct today.

What makes it a gap rather than a style note is the direction it fails in. The
check is what stops a narrowing the matcher cannot test from being silently
dropped, which is the same failure `TESTABLE_SUBJECT_FILTER_KEYS` exists to
prevent — so a copy that drifts admits a card and then ignores half its noun
phrase. W4G2 declined to fold it because at `prevention.py`'s size the helper
costs more lines than it saves; that argument expires the moment that module is
split.

**Drained 2026-09-05, at VIS wave 1**, the round Remedy and Honorable Passage
took `lowering/prevention.py` past the guard. It was **four** copies rather than
the three counted here, and they are now one call to
`lowering/_filters.testable_filter_payload`, re-exported through `_common`. The
fold bought more than the line count, and the extra is the reason the entry was
worth keeping: the helper asks `untestable_filter_keys`, which **recurses** into
a nested noun phrase where a flat `set(payload) - TESTABLE_SUBJECT_FILTER_KEYS`
answers "testable" whatever the inner phrase says — so two of the copied
spellings had already drifted from the rule they were copies of. Its refusal
also names the offending keys, which turns each one from a work-list entry into
a diagnosis.

**Fully drained 2026-09-05, at VIS wave 4, and the count was wrong in both
directions.** The entry said "39 flat spellings across eleven `lowering/`
modules". The real number was **40 across twenty-one files**: 36 in *seventeen*
`lowering/` modules, plus four the entry could not see because it had only ever
looked at `lowering/` — `engine/oracle.py` twice (the trigger-subject gate,
where a dropped narrowing is a trigger announcing on a wider set than the card
prints), `engine/cost_modifiers.py` and `engine/enter_tapped_statics.py`. All
forty now go through one of two helpers: `testable_filter_payload` where the
site builds the payload from one noun phrase, `refuse_untestable` where it built
the payload itself, and the three that return None rather than refusing call
`untestable_filter_keys` directly.

**Nothing moved, and that is the finding rather than the absence of one.** The
differential was empty, and a direct measurement says why: the recursive answer
and the flat one were compared on every call the whole pool makes — 1,431 calls
over 4,085 printings, both manifest roles, the compiler and both text-keyed
tables — and they **never disagree**. No card in the pool prints a nested noun
phrase whose inner phrase is untestable. So forty copies stayed correct for as
long as they did because no card had yet asked the question they answer
differently, which is this repo's "safe by which cards exist" again and is
exactly why the fix could not be a sweep.

So it is not a sweep. `tests/engine/test_testable_filter_gate.py` holds
`TESTABLE_SUBJECT_FILTER_KEYS` to being **named in code in two modules** — the
one that defines it beside its matcher, and the one that reads it as the two
helpers' default — and a forty-first flat spelling fails there. It tokenizes,
so the dozen comments explaining why a lowering gates on the key set are
untouched; what fails is *using* the name outside its two homes.

**Added and drained together 2026-09-05, at VIS wave 4: CR citations rot by
*subject*, not by number, and 185 of them had.** `scripts/rules_gaps.py` checks
that a cited rule number exists and that a cited subrule letter exists under it.
Neither question catches "the no-regeneration rider (CR 701.15c)", because
701.15c is a real subrule of a real rule — **Goad**. Every citation in
`engine/` and `web/` was read against `MagicCompRules.txt` and 185 were wrong.

Almost none was a typo. The shipped CR is the **April 17, 2026** edition, which
inserted `701.4 Behold` and `701.11 Triple` into the alphabetical keyword-action
block; everything after them shifted, by one in places and by four in others,
and the comments had been written against the older numbering. `701.7` (then
Destroy, now Create) was cited nine times for destroying, `701.13a` (then Mill,
now Exile) six times for milling, `701.19` (then Search, now Regenerate)
seventeen times for searching and shuffling, `701.5a` (then Counter, now Cast)
sixteen times for countering. Outside 701 the same shape: `609.3` ("does only as
much as possible") cited 24 times for a choice made on resolution, which is
`608.2d`; `706.2` (rolling a die) three times for copying, which is `707.2`;
`121.x` (drawing) twelve times for counters, which is `122.x`; `118.x` (costs)
nine times for life and damage, which are `119.x`/`120.x`.

**A CR bump is a silent, repo-wide correctness event**, and that is the entry
worth keeping. `tests/engine/test_cr_citation_subjects.py` makes it loud for the
one block where it is mechanically askable: the 701 keyword actions, where every
rule is headed by a single keyword word. It reads the heading map **out of
`MagicCompRules.txt` at test time**, so replacing that file with a later edition
fails every citation whose keyword moved underneath it. Ten sites whose comment
is right but never prints the keyword ("finding fewer" for fail-to-find,
"doesn't untap during your next untap step" for exert) are listed in `REVIEWED`,
and a second test fails on a stale entry so the list cannot outlive them.

What is **not** covered: the rest of the CR, where headings are prose and the
same check would be noise. Those 60-odd fixes were made by reading. Whoever
bumps `MagicCompRules.txt` should re-run that reading, not only the guard.

**Added at VIS wave 4, deferred by the same round: `PlayerRef` carries two
relative clauses as bools, and folding them is a design decision rather than a
row.** W3 generalised "target player who <did X> this turn" into
`ast.PlayerDeed` with a two-row `_PLAYER_DEEDS` table, and left
`attacked_this_turn` as its own parse site and its own picker enforcement. It is
not the only one left: `damaged_by_source` ("target opponent previously dealt
damage by it", Diseased Vermin) is a **fourth** clause of the same family
carried the same way, so folding one leaves the other and the entry's "one row
plus a picker read" is not the whole job.

The reason it is not mechanical: both bools are enforced by the **picker**
(`legality.py`'s seat loop reads `attacked_this_turn` off the target spec), and
neither of `_PLAYER_DEEDS`' existing kinds can be. `tapped_land_for_mana_this_turn`
and `sacrificed_this_way` are resolution-time seat records with no cast-time
answer. Fold the bools into `did` and the picker reads one generic key it can
answer for one row and silently passes for the other two — an unenforced seat
narrowing, which is a sentence acting on **every** player, which is the exact
failure this family was built to prevent. So the fold owes a decision about
which deeds are picker-answerable and a refusal for the rest, and it moves Fire
and Brimstone's and Diseased Vermin's compiled programs, so it owes its own
`oracle_diff` too.

**This entry was written twice in one Phase 6**, once by wave 4 and once by the
retrospective, and the two copies sat fifty lines apart under near-identical
headings for three sets. The second said strictly less and neither pointed at
the other, so a reader who found one had no way to know the other existed.
**A Phase 6 that adds an entry reads the list first** — it is short enough to
read and long enough to hide a duplicate in.

Drained 2026-08-28: **the verification backlog is accepted as-is.** It sat here
as the largest standing debt — 708 of 1,162 cards with no recorded in-game
result, grown by four promotions — with derived `equivalent` named as the lever
that would clear it. That lever is exhausted and the arithmetic says so:
`engine/behaviour_signature.py` distinguishes **1,049 behaviours across 1,162
cards**, only 148 cards share a class at all, and 48 unverified cards are
covered by a passing peer. It cannot reach 708 no matter who pulls it, because
the pool really is that diverse.

So the decision is made rather than deferred a fifth time: **an in-game pass is
not a required validation step.** What gates a promotion is Phase 4, and what
catches regressions is the suite plus `simulate_ai_games.py`. The tracker stays
what it is — a record of what a human has actually checked, and the place an
in-game bug report lands with a card name on it — and it is read as a log, never
as a coverage target. Nothing is owed to it and no phase is blocked on it.

What that does *not* change: a card recorded **failing** is still a live bug.
Both open failures were closed in the same round this decision was written
(Candelabra of Tawnos, an unplayable `{X}` activation, and Silent Dart, already
fixed by the CR 602.2b gate and never re-checked), and each now has a test.

**Amended 2026-08-31: fixing the card is not closing the report.** Both rows
went on reading ❌ for three days after that round, because a tracker row
records what a human saw in the app and no code change clears one. They were
re-checked in the running app and recorded through the Debug Menu, and the
failure count is 0. A round that fixes a reported card owes the re-check, not
just the fix — put it in the same round or the repo advertises a live bug it
has already closed.

Drained at 4ED's Phase 0: the CI suite-time budget. The item said not to touch
either number until someone read a real run, and reading three settled it — the
ratio never worked because `BASELINE` was a local measurement compared against
an `ELAPSED` measured on the runner. Both numbers were wrong in opposite
directions; ROADMAP invariant 2 carries the evidence.

Drained after the M21 promotion: `scripts/set_progress.py` and
`CARD_VERIFICATION.md` regeneration joined CI's tracker-freshness step (the
deferred decision came due — the roadmap read "19 untested cards" for a week
while the true number was 299), and `SET_PROGRESS.md` now reports a
`measured`-role set as "Measured (N/M supported, not shipped)" rather than a
bare "Partial".

**Added at VIS's Phase 6, swept 2026-09-07: a bare stack-drain loop in a test is
a latent hang.** `while game.stack: resolve_top_of_stack()` spins forever once
an interactive seat is owed a prompt, because the game correctly waits
(CR 608.2, CR 117.3b). One helper hung the whole suite the moment a card started
announcing a trigger target.

`tests.helpers.resolve_stack` is the drain, and **207 of the 252 loops were
swapped mechanically**. The 45 that stay are counted per file in
`tests/engine/bare_stack_drain_baseline.json` and held there as a **ceiling**:
40 read the prompt queue a few lines later, so converting one means deciding
what that test actually asserts, and 5 have a second statement in the loop body.
The fix for a new test is the helper, never a re-snapshot.

**The part worth keeping is what the sweep cost to make safe.** The helper's
first draft settled the prompt queue whenever it was non-empty — the contract
that reads as obviously more useful — and **broke 41 tests**, because a test that
resolves a spell and then *inspects* what the resolution asked was reading a
prompt the helper had defaulted out from under it. It now answers a decision only
while that decision is **blocking the stack**, which is the hazard's real shape:
the resolution is held, not the queue is dirty. A cleanup that changes what tests
can observe is not a cleanup, and the difference between those two contracts is
invisible until the suite runs.

**Two mechanical-edit hazards came with it**, for whoever runs the next sweep.
Rebuilding an import statement from its names **drops any `as` alias** — silent
at import, surfacing much later as a NameError inside one test — so compare the
set of names each module binds before and after and refuse the file if any
vanished. And a `while` whose body holds a *second* statement is not a two-line
substitution: the extra line is left orphaned at the loop's own indentation.

**Drained 2026-09-05, at WTH's wave 1: the cast-side "target opponent" offered
the caster's own face.** W1G5 took it and the activation side with it, and fixed
it where the entry did *not* predict: at the source, in the three lowerings that
record the description the printed phrase always stated, rather than by gating
on the printed line the way the trigger-side fix had to. The picker enforces
what the **spec** says, so giving the spec the narrowing is the whole fix.

**The entry's card list was wrong in both directions, which is the part worth
keeping.** Of the five it named, Game of Chaos already carried the flag, Vito's
is a trigger and Liliana's a loyalty activation — so the cast-side population
was **three** (Ebony Charm, Forbidden Ritual, Necromentia). And the sweep found
**two the entry could not have named**, on the activation path where nobody had
looked: Liliana, Death Mage's −7 and Mirror Universe. A gap entry's card list
ages exactly as badly as its premise.

**Added at WTH's Phase 6: `control_flow.may` runs its `then` branch whenever the
offer is accepted, whether or not the action did anything.** `on_accept` is
`action + then`, so "you may X. **If you do**, Y" fires Y on an empty X — Bone
Dancer accepting over a creature-less graveyard still marks itself as assigning
no combat damage. It is engine-wide across every `may … if you do` card and
**invisible to `oracle_diff`**, because no compiled program moves: the defect is
in the handler's composition, not in what the card compiled to. W2G3 found it
driving a game and recorded it rather than taking it, correctly — it wants a
decision about what "did anything" means per instruction kind, which is a
registry question rather than a branch. **Phase 3 of the next set that prints an
"if you do" rider clears it**, and it owes a behavioural differential over every
card in the pool that composes the two, not a compiled one.

**Drained 2026-09-07, at EXO's wave 1, and it drained as the registry this
entry asked for rather than as a branch.** The answer is
`control_flow._action_is_takeable`, asked **before** the prompt rather than
measuring the action afterwards: CR 601.2 offers a choice, an action nobody
could take is not one of the things being offered, so the offer is not made, the
rider does not fire, and the decline branch (a "…unless you pay" penalty) still
applies. One rule serves both halves, which is why it is a table of kinds and
not a test inside `may`. A kind is listed only where its "nothing to give" case
is a **fact rather than a guess** — a wrongly-False answer withdraws an offer
the card makes — and everything unlisted answers True, which is what the engine
did for all of them before.

**The two cards it was costing were both shipped and neither was in Exodus.**
Bone Dancer (ALL) accepting over a creature-less graveyard reanimated nothing
and still set `assigns_no_combat_damage_until_eot`; Duplicity (TMP) exiled
nothing from an empty hand and handed the whole exiled pile back for free, which
is the trade that *is* the card. The part worth keeping is that
`handlers/zones.reanimate_graveyard_position`'s **own docstring asserted the
guarantee that was missing** — it claimed to return False from the `may` it sits
inside "which is what keeps 'If you do …' from firing", and `_run` folds a
handler's first return into resolved/no-effect while `on_accept` never branched
on it. The sentence had never been true. **A docstring that states an invariant
is not a guard, and this is the second time in three sets that one has been
read as though it were** — see the filter-draft entry below, where a guard's
docstring described a check its body did not perform.

**Drained 2026-09-07, at EXO wave 1 (W1G2) — and the registry it asked for
already existed.** The entry wanted "a decision about what 'did anything' means
per instruction kind, which is a registry question rather than a branch".
`handlers/control_flow._action_is_takeable` **is** that registry, and it had
fifteen rows and its own written rule for adding one ("a kind added here has to
be one whose 'nothing to give' case is real and checkable"). It also asks the
question one step earlier and better: CR 601.2 offers a choice, an action nobody
could take is not among the things offered, so the offer is never made, the
rider never runs, and any "if you don't" penalty still applies. What was missing
was rows, not a design.

**How many rows was measured rather than guessed, and the answer is two.** Every
instruction kind that appears as a `may`'s action with a `then` behind it, over
both manifest roles, was enumerated: 26 of them across 82 cards. Twenty either
always do something (a coin flip, a life gain, a reveal, a mana ability),
legally do nothing (Tetravus' "any number of", Scroll Rack's), or are *targeted*
and so already refused at CR 601.2c / 608.2b. Two more are empty in a way whose
rider is itself a no-op — Ice Cauldron grants cast permission over an empty
pile, Flash offers a cost computed from a permanent nothing recorded — and are
listed as reviewed rather than fixed. **Two are real, silent and in the player's
favour**: `reanimate_graveyard_position` (Bone Dancer, the card this entry
named) and `exile_hand_pile` (Duplicity, where an empty hand paid nothing and
took the whole exiled pile back — the trade *is* the card).

**The part worth keeping is where the false claim was written down.**
`handlers/zones.reanimate_graveyard_position`'s docstring said an empty pile
"returns False from the `may` it sits inside, which is what keeps 'If you do,
this creature assigns no combat damage this turn' from firing on a turn where
nothing came back". `_run` folds a handler's first return value into
`resolved`/`no effect` and `on_accept` never branches on it, so the sentence was
never true — and a docstring asserting the very guarantee a Known-gaps entry
says is missing is the most expensive kind of comment there is. Reproduced
before the fix, in `tests/engine/test_optional_offer_defaults.py`, which also
holds the 26 kinds as a reviewed list so a twenty-seventh fails there and is
read before it is added rather than after.

The behavioural differential the entry asked for is that list plus the two
cards' tests: no compiled program moves (`oracle_diff` confirms), and the only
runtime behaviour that changes is an offer withdrawn from a seat that could not
have taken it.


**Added at WTH's Phase 6: two readers of "is this a ⟨type⟩ card" disagreed, and
only one of the two questions got settled.** W2G4 measured it over the whole
pool: `CardDefinition.primary_type` returns the *first* of `land, creature,
artifact, …` in the type line, so **77 artifact creatures** answer "creature" to
a reader asking "artifact", and **zero** land creatures exist — which is why
every "creature" reader was right by accident and every "artifact" reader was
wrong. All of them now go through `search_filters.card_has_type` (CR 205.2b).
What is **not** settled is the same question one zone over: `cast_permissions`
and the graveyard-cast picker were only ever safe because the single card
granting a typed permission names instant and sorcery. A card granting
"artifact spells from your graveyard" would reopen it.

**Added at VIS's Phase 6: ~60 non-701 CR citations are corrected but not
guarded.** The 701 keyword-action block is now checked against headings read out
of `MagicCompRules.txt` at test time, so a CR edition bump fails every citation
whose keyword moved. The rest of the corrections — 609.3 for 608.2d, 706.2 for
707.2, the 121/122 and 118/119/120 confusions — are prose headings that no
guard can match. **A CR edition bump owes a re-read, not just a green suite.**

**Added at TMP's Phase 4, mostly drained 2026-09-07: a multi-slot target's
picker offers one list for every slot.** Phyrexian Splicer prints "target
creature **with the chosen ability** … and another target creature", and the
derived spec was one `{"kind": "creature", "max_targets": 2}` over two slots
whose payload filters differ. So `_enumerate_targets` offered every creature for
both, the gate read the same list and admitted it, the cost was paid, and the
handler dropped a slot at resolution. CR 601.2c makes that an illegal
announcement. **No instrument here can see it**: the card compiles, has no
hollow line, claims every sentence, and `picker_sweep` asks whether a picker is
*derived*, not whether its list is right per slot.

**The blast radius was measured rather than guessed, and the entry's guess was
wrong.** "Every multi-target spell in the pool" is **fourteen descriptions, of
which twelve differ, across eight cards** — small enough to take in one round.
And six of the eight were worse than the card that named the gap: Triangle of
War, Political Trickery, Gauntlets of Chaos, Hunter's Edge, Primal Might and
Garruk, Savage Herald all print a **controller** restriction on one slot
("target land you control and target land **an opponent controls**"), and
intersecting "you control" with "an opponent controls" leaves *nothing*, so the
printed restriction was enforced by nothing at all and the caster could name two
of their own.

`_from_targets_payload` now derives ordered **roles** when the slots differ, so
each slot is enumerated with its own filter, CR 601.2c's distinctness comes free,
and the picker and the gate stay one call. The description is untouched, so no
compiled program moves for it and every handler goes on reading `filters`
positionally — the answers arrive in role order.

**Two things are left, and both are named because the shape of each is now
known.**

*An optional slot cannot be a role.* "…it fights **up to one** target creature an
opponent controls" (Primal Might) may name nothing, and a roles walk answers
every role or refuses the announcement — so converting it would turn an optional
target into a required one, which is a different wrongness rather than a smaller
one. Those keep the shared list and its narrowing loss. The description now
records `optional_slots` so the case is *visible* instead of being invisible in
a flattened `count`; closing it means an optional role in the walk and in the
client.

*A runtime narrowing is not a picker flag.* Phyrexian Splicer's own slot 0 is
"with the chosen ability", and which keyword that is depends on the activation's
cost choice. `_narrowing_flags` has no key for it and the enumerator has no
answer at picker time, so the card has per-slot enumeration and still no
narrowing on the slot that needed one. It wants the keyword choice to reach the
enumerator, which is its own piece.

*A **card** can be a role, as of ULG's wave 2, and that is three of this
entry's four named pieces built.* Goblin Welder ("Choose target artifact a player
controls and target artifact card in that player's graveyard") needed a role that
is not a battlefield permanent, and the pipeline now has one:
`legality.role_object_at` is the single place a role candidate becomes an object;
CR 115.3 distinctness is an identity **key** rather than `id(perm)`, because two
copies of one card in one graveyard are literally one `CardDefinition` and `id`
cannot separate them; `ROLE_RELATION_TESTS["in_graveyard_of_role"]` is the first
relation whose two sides are not both permanents, and **its `(earlier, candidate,
game)` signature took it unchanged** — the table was already general and only its
three call sites were not; and `target_role_refs` is one announcement channel
naming a `permanent_id` *or* a graveyard `(seat, index)`, describing every role
rather than interleaving with `target_permanent_ids`.

What is still open is the **seat**, and it is now the smaller half of what it
was. Keeper of the Dead needs a *player* role, and a second thing besides: its
two targets are announced by two **instructions** of a sequence, so converting it
moves a **shipped** card's compiled program and owes its own differential.

*A seat cannot be a role*, measured at EXO wave 2 and the reason a third
leftover is recorded rather than closed. Keeper of the Dead is the card
("Choose target opponent … Destroy target nonblack creature **that player**
controls"): two slots, the first a **player**, the second an object on that
player's board. Every part of the roles pipeline is permanent-only —
`role_target_options` resolves each candidate through `permanent_at` and drops
what is not a `Permanent`, distinctness is `id(perm)`, `ROLE_RELATION_TESTS`
takes `(earlier, candidate, game)` over two permanents, and the announcement
arrives as `target_permanent_ids`. So a seat cannot be role 0, and the brief's
"`_slot_roles_spec` only splits `filters` within one description" understates it:
splitting across two *instructions* of a sequence is the smaller half.

What **was** closed is the announcement's yes/no half. `_activation_spec`
attaches `dependent_slots` — the specs of later mandatory slots narrowed by
`that_player_only` — and `_enumerate_targets`' seat loop drops a candidate seat
whose board cannot fill them, so the picker and the gate refuse the same seats
and CR 602.2b is enforced before any cost is paid. What is left is *which*
object fills the slot: the activator still does not choose it, the handler picks
at resolution. Closing that wants (1) a player role in `roles_spec` /
`role_target_options` / `_role_targets_legal`, (2) an announcement field that can
carry a seat beside permanent ids, (3) a relation entry for "controlled by the
seat an earlier role chose", and (4) the client walking a role list whose first
entry is a seat picker.

**Updated at ULG wave 2: three of those four pieces now exist, built for a
*card* rather than for a seat.** Goblin Welder is the same shape one zone over
— "Choose target artifact a player controls **and target artifact card in that
player's graveyard**" — two slots where the first is a permanent, the second is
**not on a battlefield at all**, and the second's pile is decided by the first.
What it needed and what it left:

* *built* — a role the walk can resolve outside the battlefield.
  `legality.role_object_at` is the one place a candidate becomes an object, and
  CR 115.3's distinctness is now an identity *key* (`_role_object_key`) rather
  than `id(perm)`, because two copies of one card in one graveyard are literally
  one `CardDefinition`.
* *built* — `ROLE_RELATION_TESTS["in_graveyard_of_role"]`, the first relation
  whose two sides are not both permanents. The table's `(earlier, candidate,
  game)` signature took it unchanged, which is the finding: the shape was
  general and only its three call sites were not.
* *built* — an announcement field that can name something other than a
  permanent. `target_role_refs` (`web/schemas.TargetRoleRef`) describes **every**
  role of one announcement, each entry naming a `permanent_id` **or** a
  graveyard `(seat, index)`; `target_permanent_ids` is untouched and is still
  what every all-permanent roles ability sends. Adding a *seat* to it is one
  more optional field, not a new channel — which is the piece Keeper of the Dead
  was missing.
* *built* — the client walking a role list whose entries are not all board
  clicks (`revealRoleGraveyards` opens the pile panel at whichever step of the
  walk asks for one).
* *not built* — a **player** role. Nothing here makes a seat an object the walk
  can hold, and Keeper of the Dead needs a second thing besides: its two targets
  are announced by two *instructions* of a sequence (`choose_target_player`,
  then a destroy narrowed by `that_player`), so converting it moves a **shipped**
  card's compiled program. That is a differential over the shipped pool and
  wants its own round.

So the entry is not closed, and it is a smaller entry: the pipeline no longer
assumes a role is a permanent, and what is left is one more kind of object plus
one shipped card's re-lowering.

**The picker sweep's question stops one level above all of this**, and its
docstring now says so.

**Added at TMP's Phase 4: `unless_player_pays` is labelled with an effect family
rather than a shape.** It is a **wrapper** carrying `activated_control`, which is
the borrowing `test_a_wrapper_kind_never_borrows_a_leaf_effects_bucket` exists to
forbid; it passes today only because no *leaf* shares that bucket. It constrained
Jinxed Idol's row at the promotion (a new bucket had to be invented rather than
reused). Its only card is Scarwood Bandits, so the first control **leaf** filed
there fires the guard. **And that guard has a structural blind spot**: it skips
kinds not already in `ACTIVATED_LABELS`, so a *defaulting* wrapper sitting on a
leaf bucket is invisible until somebody adds its row — which is exactly how
Grindstone sat on `activated_zones`. Fixing the label re-buckets a shipped card,
so it wants a round with an `oracle_diff` rather than a promotion's tail.

**Added at TMP's Phase 4: the bare noun `spell` is dropped pool-wide.**
`parse_object_filter` records `zone="stack"` only after a *type union*, so
`target spell` and `target permanent` produce byte-identical `ObjectFilter`s.
The live consequence is **Ersatz Gnomes** (Mirage, shipped): `{T}: Target spell
becomes colorless.` is offered the `spell_or_permanent` picker — the same spec
Chaoslace's "target spell **or** permanent" gets — so the ability can be aimed
at a permanent the card does not allow. Measured rather than guessed: setting
`zone="stack"` for the bare head noun takes **Deflection, Mountain Titan and
Reflecting Mirror** unsupported, because their lowerings refuse a `zone`
narrowing they do not honour. Four pieces: the noun change, those two lowerings
honouring the narrowing, the `you_cast_spell` delayed-trigger subject filter
honouring one, and a `targets` payload on `recolor_target_from_text` so the spec
stops coming from a shared kind.

**Drained 2026-09-06, in commit `2a2fe8dc` — which landed the day *before*
Stronghold's ingest, and the entry was carried through all of Phase 1 anyway.**
`parse_object_filter` records `zone="stack"` for the bare head noun, the two
lowerings honour the narrowing, and Ersatz Gnomes' first ability now derives
`{"kind": "stack"}`. **The finding is not the fix, it is how long the entry
outlived it.** This list already records that "a Known-gaps entry is read as a
work item and nobody re-checks a work item's *premise*", and the very next set
re-read this one, wrote it into a group brief as live, and only found out at
Phase 6 — because Phase 6 is now the step that checks. The group corrected it
in its report, which is the other mechanism working. **Both are needed: the
check at Phase 6 catches what a brief asserts, and the brief's "tell me what
this got wrong" catches what Phase 6 has not reached yet.**

**Added at STH's Phase 4: `StackItem.target_permanent_id` carries two arities,
across 119 reader sites.** `stack/activation` and `stack/casting` stamp the
whole `target_permanent_ids` *list*; a prompt's answer in `stack/choices` stamps
a bare id. This is the `permanents_from` shape one level up and it is much
larger — twenty files, against that channel's eight.

It has already cost one live defect. `chosen_permanent` is the seam whose whole
job is "prefer the stable id", and it asked `isinstance(permanent_id, int)`, so
it silently ignored every list and fell through to the index its twelve callers
had. `deal_damage`'s single-permanent branch was gated on the index for the same
reason, so an `any_target` ability named by id alone fell past it and burned the
**player** — reproduced on Rod of Ruin, 20 to 19, with the named creature
untouched. `web/actions.py` fills an index in and masked it from every game.

Settled *at the seam* rather than a thirteenth time at a call site:
`oracle_types.single_chosen_id` is the arity rule, read by `chosen_permanent`
and by that gate. One element is one address; several is not and gets None
rather than a guess at slot zero. **What is left is the field**, and folding 119
readers onto one shape is a pool-wide refactor rather than a fix — the kind
this list already says does not travel with a wave. Whoever takes it owes the
element-type question in the same round, which is the half Visions found nobody
had named.

**Re-read at USG's Phase 6, and the entry was one axis short.** W3G5 found three
shipped cards mis-played through this field — Sidar Jabari (MIR), Seasoned
Marshal (USG) and Elite Javelineer (TMP) — and they are **not** the arity
disagreement this entry describes. The combat fire sites stamp a **scalar**, the
same arity `stack/choices` uses, and `resolve_own_combatant` reads it correctly.
What is wrong is the **relation**: one field carries "the target the controller
chose" *and* "the object this ability is about", with nothing recording which.
Seasoned Marshal tapped itself and Elite Javelineer damaged itself, because the
self-stamp suppressed CR 603.3d's choice; Sidar Jabari tapped **nothing**,
because its `defending_player` narrowing correctly refused the self-stamp.

Same root — one field, two facts — different axis, and the entry now names both.
The three cards were fixed by gating the picker; the principled fix is a
**separate field**, which touches every combat fire site and
`resolve_own_combatant`. Whoever takes the 119-reader refactor should settle
arity, element type **and** relation in the one round, because a field that
means two things cannot be folded onto one shape until it means one.

**Cleared at EXO's Phase 0 — and the measured seam was right, which is the
first time an inherited one has been.** `effects/prevention.py` was at 990 with
two of wave 1's groups about to land in it, and STH's W1G1 had reported by call
graph that it split into two components with **zero edges between them**. Read
as a lead and re-measured, the call graph was exactly that: seven functions
reachable from the shield entry points, six from CR 615.8's, and one node
(`_parse_prevented_this_way_rider` + `_PREVENTED_THIS_WAY_RIDERS`) called by
both. It cut into `effects/prevention.py` (429), `effects/damage_instances.py`
(469) and a new floor `grammar/prevented_riders.py` (183), moving **0 of 2,966**
compiled programs. Two corrections worth carrying, because both are the shape a
seam report takes when it is written from a call graph alone:

* **The reported line counts were the halves, not the files.** ≈395/≈533 sums
  past the module, because the shared rider was counted into one of them and
  the header into neither. A seam report should say what the *files* would be.
* **The reported cut left the file unbalanced and it was one function.**
  Silhouette's `_parse_bound_targeting_prevention` is an isolated node — no
  call edges either way — so the call graph cannot place it and the report put
  it with the 615.8 half on physical position alone. It is a shield around a
  named recipient, prints no "next time" and chooses no source, and it belongs
  with the shields; moving it there is what made the two halves 429 and 469
  instead of 386 and 512.

The `records.py` objection was right and understated: `amounts.py` imports
`records` at **module level**, so reading `amounts.accept_counter_kind` from
inside `records` is a real import cycle, not only a docstring's warning.
**`ast/_references.py` drained at EXO's Phase 0 along exactly the seam
recorded here** — 997 -> 698 + `_payloads.py` (336), `ObjectFilter.to_payload`
moved whole with the class arriving as an argument so nothing cycles. The
budgeted cost was real and it was **two** lines rather than one: the layering
test hard-codes `ast`'s shared tuple **and** `FAMILY_SHARED`, so a new floor is
invisible to one guard and a violation of the other until both are told.

**`lowering/sequences.py` is what is left**, at 920 after STH's wave 2 moved two
fusers into it, with four of its six opening on a `(Tap, payoff)` pair — still
unowned, and the observation still unspent.

**And the pattern across three sets is worth more than the list.** Every module
named in this entry has eventually been split along the line somebody had
already written down, but **never on the first reading of it**: STH's two groups
measured their briefed seams and refused both, EXO's `_bound_returns` seam was
one clause stale, and `exile.py`'s docstring named three forms of which two were
8 and 32 lines. A recorded seam is a lead worth having and is not a fact; budget
the measurement, not just the cut.

**Added at TMP's Phase 5: `tests/engine/test_layer_reads.py` scans `engine/`
only.** `web/serialization.py` asked "is this a creature" of
`perm.card.type_line` — the printed type, the exact second answer that guard
exists to catch — and no guard could see it because `web/` is outside the scan.
Fixed at the one site found; the scope is not. Widening it means reading every
type/colour/P/T question in `web/` against the layer accessors, which is a round.

**EXO's Phase 5 found the third and fourth, and the entry should now be read as
a round somebody owes rather than as a watch-list.** Both ask a *permanent*
"is this a creature" through the printed card: `web/combat_prompts.py`'s blocker
check drops an animated land blocking a band (CR 702.22k), and
`web/prompts.py`'s Balance lists show an animated land as a land only, when it
is both. Three consecutive promotions have each turned up one of these, which is
the evidence the instalments cost more than the scan.

**STH's Phase 5 found the second site, and it says the entry was right to stay
open.** `is_aura` read the printed type line, so a **Licid** — "this creature
loses this ability and becomes an Aura enchantment" — reached the client as a
non-Aura while the engine had it right at every seam it owns. The part worth
carrying is *why the usual instinct also fails here*: "becomes an Aura
enchantment" is a CR 613 **layer-4** type change, and layer 1 folds a copy while
layer 3 folds a text change, so `perm.effective_card.type_line` still reads
"Creature — Licid" too. Reaching for `effective_card` is the documented fix for
"what does it say?" and it is the *wrong* fix for "what type is it?"; only the
layer accessors (`has_type`, `is_creature`, `layer_bridge.displayed_type_line`)
answer. `tests/ui/test_layer_reads_on_the_wire.py` now pins both known sites
from the wire side. Two promotion smoke tests in a row have found one of these,
which is the argument for the widened scan rather than a third.

**Added at EXO's wave 2: a *cast* cannot announce CR 615.8's chosen source.**
"A source of your choice" is not a target (CR 615.8), so it travels on its own
announcement field — `choices["chosen_source"]`, filled from
`source_seat`/`source_permanent_index`/`source_stack_index`. Only
`mixins/stack/activation.py` writes it. Every **spell** in the pool that prints
the phrase gets away with that because it names nothing else, so the source
rides the spell's own target slot instead (`targeting` gives them
`source_of_choice` + `also_stack`, and `handlers/prevention.chosen_shield_source`
reads it there): Reverse Damage, Reflect Damage, Invulnerability, Shadowbane and
Eye for an Eye are all cast correctly that way.

**The gap is a spell that names a target *as well*, and it already has a shipped
victim.** Honorable Passage ("The next time a source of your choice would deal
damage to **any target** this turn, prevent that damage") derives
`{"kind": "any", "requires_source": True}` — but `web/static/app.js` runs the
`requires_source` stage only inside `if (pending.castAction === "activate")`, so
a human casting it is never offered the second prompt and the shield arms
sourceless. It is *bounded* rather than wrong: `uses=1` means the effect is
spent on one instance either way, which is the documented AI/headless fallback.
That is exactly why it went unnoticed.

**EXO's Kor Chant is the same gap where the fallback is no longer bounded**, and
that is what makes this worth draining. "All damage that would be dealt this
turn to target creature you control by a source of your choice is dealt to
another target creature instead" announces *three* things — two targets and the
source — and it is **blanket for the turn**, not one instance. Armed against any
source it would move every point of damage dealt all turn onto the second
creature. So the lowering refuses by name
(`lowering/redirection.py`: "a cast cannot announce CR 615.8's chosen source
beside its own targets") rather than taking a fallback that is wider than the
card in the silent direction. Everything else for the card is built: the
production reads the phrase in its printed position and the node is complete.

**Phase 3 of the next set printing either shape clears it**, as four parts:
1. `casting.cast_from_hand` / `_cast_onto_stack` take
   `source_seat`/`source_permanent_index`/`source_stack_index` and stash the
   resolved object under `choices["chosen_source"]`, exactly as
   `activation.py` already does around its own stack push;
2. `web/actions.py`'s cast branch forwards those three fields, with the same
   top-first-to-bottom-first stack-index conversion the activate branch does;
3. `web/static/app.js` lifts the `requires_source` stage out of the activate
   branch so it runs after a cast's target walk — including after a **roles**
   walk, which is the shape Kor Chant needs and no existing card exercises;
4. the redirect kind itself
   (`redirect_chosen_source_damage_between_targets_until_eot`: two per-slot
   `filters`, no `uses`, the taker resolved from slot 1), its
   `INSTRUCTION_CATEGORIES`/`GRAMMAR_CATEGORIES` rows, and a
   `_KIND_TO_SPEC_FROM_PAYLOAD` row — `_off_target_chosen_source_redirect_spec`
   already serves it unchanged, because it reads the payload and
   `_slot_roles_spec` turns two differing slots into ordered roles.

Parts 1–3 are what makes part 4 safe; landing 4 alone is the wide-fallback
mis-play this entry exists to refuse. Verify with **Honorable Passage**, which
is shipped and so can be driven in the running app.

**Re-checked at USG's Phase 6 and it survives, with its scope now measured
rather than assumed.** Urza's Saga prints "a source of your choice" on **eight**
cards — the seven Runes of Protection and Sanctum Guardian — so on the entry's
own trigger condition ("the next set printing either shape") it looked due.
All eight are **activated** abilities, which `mixins/stack/activation.py`
already announces correctly through `choices["chosen_source"]`, so not one of
them touches the gap. The gap is a **cast** that names a target *as well*, and
the pool's only instance is still Kor Chant, still refused by name in
`lowering/redirection.py`.

Which is the check this list asks every retrospective for: the entry's *work* is
undone, and its *premise* — that the next set printing the phrase will meet it —
turned out to be wrong. Printing the phrase is not the trigger; printing it on a
**spell with its own target** is. The condition is amended to say so.

**Re-checked at ULG's Phase 6 against the amended condition, and it holds.**
Urza's Legacy prints "a source of your choice" exactly once, on **Martyr's
Cause** — an *activated* ability, which `mixins/stack/activation.py` already
announces correctly through `choices["chosen_source"]`. So the set does not meet
the trigger, the entry's work is still undone, and the amended condition did its
job: under the *old* wording this would have read as due for the second set
running and been read as a live work item for the second time.

**Drained at 6ED's wave 1 — and it had been drained for two days before that,
by the set that raised it.** All four parts, plus the fifth the entry did not
name, landed in commit `233b35bf` ("EXO 143/143: a cast can announce CR 609.7a's
chosen source") on 2026-09-07, at EXO's own Phase 3. `casting.cast_from_hand` /
`_cast_onto_stack` take the three `chosen_source_*` parameters,
`web/action_helpers._queue_spell_from_request` forwards them,
`app.js`'s `startCastChosenSourceStage` runs after both a target walk and a
roles walk, `redirect_chosen_source_damage_between_targets_until_eot` exists
with its categories and spec rows, and `legality._attach_chosen_source_targets`
fills `source_targets` on the cast path. Kor Chant compiles supported;
`lowering/redirection.py` has no by-name refusal left to remove.

**Two Phase-6 re-checks read the entry's trigger condition and never re-probed
the code, and both reported the work still undone.** USG's re-check counted the
set's eight printings of the phrase and correctly found all eight were activated
abilities; ULG's counted Martyr's Cause and found the same. Both conclusions
about *the set* were right. Neither asked whether the **entry** was still true,
and the honest reading is that amending a trigger condition is not a substitute
for opening the file the entry names: a decline ages in the direction of
becoming free, and this one had already gone free. **A re-check owes one probe
of the code, not just one probe of the set.**

**What the re-checks could not have known is now measured, in the app.** The
entry's own proof card is Honorable Passage, whose walk is `kind: "any"`; the
shape nobody had ever driven is Kor Chant's **roles** walk followed by the
source stage, which the EXO commit built and verified only by reading `app.js`
as text. Driven end to end in the running app at 6ED's wave 1: the two role
clicks, then the source stage, then

    Kor Chant: damage Mons's Goblin Raiders would deal to Grizzly Bears this
    turn is dealt to Hill Giant instead
    ...
    1 damage to Grizzly Bears is dealt to Hill Giant instead (Kor Chant)

with Hill Giant's own 2 combat damage to the same creature staying put, which is
what says the record answers to the chosen source and not to every source.

**What is left is one kind wider than the two cards.** `requires_source` rides
on top of whatever target description the card prints
(`targeting._off_target_chosen_source_redirect_spec` returns
`{**described, "requires_source": True}`), so the next card printing the phrase
picks its own walk — and only `resolvePendingCastTarget` and `confirmRoleTargets`
reach the stage. A `divided`, `several`, `stack` or `player` description would
route to a walk with none, and fail exactly as this entry's original defect did:
the cast completes, the record arms, and it answers to every source.
`tests/ui/test_cast_target_kinds.py::test_every_cast_that_asks_for_a_source_ends_in_a_walk_that_offers_one`
sweeps the pool for that and fails naming the card, so the class is fail-closed
rather than waiting for a fifth set to notice. Backwards-validated against
`233b35bf^`, where it names Honorable Passage.

**Added at EXO's Phase 5: a client-only envelope has no guard, and one had
been wrong for four sets.** `GameActionRequest.seat` is required of every
action and `sendAction` does not supply it, so all 125 call sites in
`web/static/app.js` add it by hand — and `renderSpecialActions` did not. **Every
CR 116 special action the UI has ever offered was unreachable**: Tempest's five
Licids, Stronghold's, Exodus's two, Volrath's Curse, Circling Vultures. No log
line, no error on screen, a 422 in a console nobody reads. The engine seam was
right, the state payload served the offer, the button rendered.

Nothing in the repo could see it, because nothing in the repo reads that
envelope but a browser: the engine tests call the seam directly and the API
tests post bodies they construct themselves. `tests/ui/test_special_action_wire.py`
now reads every `sendAction` body out of `app.js` and requires the field — the
bug **class** rather than the bug — and drives one offer end to end over HTTP.

**What is left is the shape, not this instance.** That guard checks one required
field of one schema by parsing JavaScript. Every other `web/schemas.py` required
field is in the same position: supplied by hand at every call site, with no
check that the hand-written bodies and the schema agree. **Phase 5 of a set
whose cards reach a route no browser test drives is where the next one
surfaces**, and the general fix — deriving the required fields from the schema
and asserting the JS agrees — is its own round.

**Added at EXO's Phase 5, and it is the rules half of the same click: a special
action is not a resolution, and the SBA sweep only knew about resolutions.**
With the button finally reaching the server, ending a Licid's effect left the
stolen creature stolen — through a whole combat phase. CR 116.3 gives the taker
priority back and CR 704.3 checks state-based actions before anyone gets
priority, but `phase_steps.pass_priority` only checks after a **resolution**,
which CR 116.1 explicitly says a special action is not. Fixed at the two entry
points a special action has rather than at each consequence.

The entry is here rather than closed because the *category* is: a special action
is one of several things that change the game without resolving. Turn-based
actions and cost payments are others, and nobody has audited whether the sweep
runs after those either. **Phase 3 of the next set that adds a non-resolution
state change owes that audit.**

**Added at EXO's Phase 6, escalated at ULG's: `web/`'s layer reads now have
**seven** named sites, four consecutive promotions have each found one, and the
grep that would have caught the first six does not catch the seventh.**

TMP's Phase 5 opened this with `web/serialization.py` asking `perm.card.type_line`;
STH's added `is_aura` and the Licid; EXO's Phase 5 added `web/combat_prompts.py`'s
blocker check (CR 702.22k: an animated land blocking a band is dropped) and
`web/prompts.py`'s Balance lists; ULG's wave 1 added `web/combat_prompts.py:138`
and `web/state_view.py:241` and `:617`, all three asking a *permanent*'s type
through `card.primary_type`.

**And ULG's Phase 5 found the one that changes the entry's shape.**
`_effective_keywords` asked `game._protection_colors` — a **real accessor**, and
the deliberate colour *slice* of `_protection_qualities`. Nothing about it is a
printed-card read, so a scan for `card.type_line` / `card.colors` /
`card.primary_type` finds every other site and misses this one. Two shipped cards
paid: Angelic Curator showed only "Flying" and Yavimaya Scion, whose entire
printed text is "Protection from artifacts", reached the client with no badge at
all. Fixed and pinned in `tests/ui/test_layer_reads_on_the_wire.py`.

So the round this entry has been asking for is **two questions, not one**: which
`web/` reads ask the printed card, and which ask an accessor **narrower than the
question**. The second cannot be grepped and has to be read — every place `web/`
calls an engine accessor, against what the caller actually needs to know.

**Taken at 6ED's W1G2, and the round found the entry had been read backwards.**
Four instalments made it look like a list of sites being closed one at a time,
so the brief said "some are already fixed; establish which are live". **All nine
greppable reads were live**, including the three ULG's wave 1 had just added;
only the non-greppable one had ever been closed. An entry that accretes
instalments reads as progress even when nothing has been fixed.

`tests/ui/test_layer_reads_in_web.py` is the scan, ratcheted **per module**
rather than exempted per file, so `web/serialization.py` — where three of the
sites lived — stays at zero instead of getting a blanket. Eight fixes, each
proven from the payload: the untap picker filtered on `("land", "creature")`
where the engine has four `LIMITED_SCOPES` and wrote the pruned list back onto
the session, so Damping Field and Static Orb offered nothing *and* refused the
click; a Clone of a Bears reported its printed `{3}{U}` and a base `0/0`, which
paints the P/T green; an animated land was dropped from a band's blocker
assignments and drawn as "Basic Land — Swamp"; Dingus Egg fired twice.

**And the biggest one is the entry's second question with a card name in it.**
The castable highlight priced a spell as `3 if a permanent is named "Gloom" and
the card is white` — one name, one hardcoded amount, one colour — where
`engine/cost_modifiers.py` is a text-keyed table knowing **28 shipped cards** and
covering reductions too. Chill, Derelor and Irini Sengir had never appeared in
the UI's cost at all. The highlight now calls the same four functions the cast
path and `ai_policy._cost_for` call, so all three price a spell identically by
construction.

**Two things the round found that the *engine's* own guard cannot see**, both now
Known gaps of their own below: its pattern is `\.card\.(type_line|colors)`, which
omits `primary_type` — the field every one of the seven `web/` sites used, and
**70** reads in `engine/` — and `mixins/helpers.py` is exempted *by file*, which
hides two Licid-class `"Aura" in permanent.card.type_line` reads in the engine's
own graveyard path.

**A guard whose exemptions are per-file cannot ratchet**, which is the general
form: `test_layer_reads.py` exempts files and `test_control_reads.py` ratchets
counts, and only the second makes a new offence in an old file fail.

**Added at ULG's Phase 6: an off-battlefield colour read ignores a
colour-defining static.** `engine/object_colors.py`'s own docstring names the
class ("has not been taught the seat"), and W2G2 measured two live instances
while landing Thran Lens. **Gloom does not tax a spell Celestial Dawn made
white**: `cost_modifiers._subject_matches` reads `card.colors`, so a Dark Ritual
in hand under the Dawn reads `('W',)` to `object_colors.card_colors` and is taxed
`(0, [])` where a real white card is taxed `(3, ['Gloom'])` — and CR 601.2f asks
about the *spell*, which the Dawn's second sentence makes white. And
**protection stops a spell by its printed colour**: `permanent_state.
_card_has_quality` reads `card.colors`, so under the Dawn a Terror is a white
spell and White Knight still reports it untargetable.

The battlefield side is **clean** and that is what makes this bounded:
`_permanent_has_quality`, `damage_source_colors`, `subject_matches` and the lord
buffs all resolve through `effective_colors`, so layer 5 is read correctly
everywhere `tests/engine/test_layer_reads.py` covers. What is not covered is a
card that is not on the battlefield, where there is no `Permanent` to ask.
`_matches` feeds five loops and every tax in the pool, so this is a round with
its own differential rather than a rider. **It is the same shape as the `web/`
entry above — an accessor that answers a narrower question than its caller
needs — and whoever takes either should look at both.**

**Drained at 6ED's W1G3 — and "the battlefield side is clean" was the wrong
half of the entry to trust.** That sentence was inferred from `subject_filters`
and the lord buffs, which are clean. The **tax** family is not: `ability_cost_tax`
taxes a *permanent* and read its printed colours off `effective_card`, which
folds layers 1 and 3 and stops, because layer 5 lives on the object. So Gloom's
second line was blind to all three colour statics in the pool. **An entry that
bounds itself with a reassurance owes that reassurance a probe, not just its
claim** — the claim reproduced exactly and the bound was wrong.

`object_colors(game, obj, seat)` is the seam, dispatching on `effective_colors`
the way `_source_has_quality` already dispatched. Nine reads in five families —
the taxes, protection and hexproof-from-a-colour, damage-source colours, the
colour narrowings on cast triggers, and the graveyard/stack pickers. The damage
half cost one keyword argument per site because `damage_events` already derives
`source_seat` per event, which is that seam paying for itself a third time.

**The differential is the model for a text-keyed change.** `cost_modifiers` never
reaches a compiled program, so `oracle_diff` is structurally blind and reported
0 of 3,572 — correctly and uselessly. The census beside it is four boards x the
whole pool, and **the containment is the finding**: a bare board moves 0 rows in
all three censuses, Celestial Dawn moves 4,444 spell-tax rows, 516
activation-tax rows and 11,966 targeting rows, and on the parent all four boards
were byte-identical because the engine could not see a colour static at all.
Every moved row is accounted for by name.

Left, as one round with its parts named: `graveyard_card_matches`' colour branch
(19 call sites, no game and no owner in scope), `_exile_search_matches` (a
`@staticmethod`, so the fix is making it an instance method), and
`_card_matches_filter`'s `game=`/`owner=` passed by only 15 of ~35 sites.
Celestial Dawn reaches a graveyard too, so they belong together.

**Added at ULG's W2G4, declined there with its parts named: the *blocking* side
of the declaration-legality gap.** The attack side was fixed (both caps moved
behind `attack_declaration_refusal`, so the AI no longer proposes an over-cap set
and then attacks with nobody). Blocking has the identical failure and **no
predicate at all**: `declare_blockers` enforces `max_blockers_each_combat` and
the company/greater-power requirements inline, `choose_combat_blockers` prunes
against nothing, and `web/game_flow.py` falls back to `{}` — the defender blocks
with nobody. It is not a transcription of the attack fix, and the parts are:
(1) a predicate that needs the *game* and the declaring seat, because the block
cap totals **every** defender's blockers (CR 509.1b) plus the Camouflage
exemption; (2) hoisting `resolved_blockers` out of `declare_blockers`; (3) an AI
prune over a **map** (blocker → attacker), so "drop the offender" means removing
a key and `choose_combat_blockers` needs a substitution mode; (4) a census twin
over the block kinds. Population: Caverns of Despair, Mogg Flunkies, Orcish
Conscripts, Okk.

**Amended 2026-09-09: the AI simulator can now validate this, which it could not
when the entry was written.** It said "note that it cannot be validated by the
AI simulator, which has no combat phase"; the simulator drives combat as of the
round that drained the entry above, so a block declaration refused for the whole
seat is now observable there.

**Drained at 6ED's W1G1 — and part (1), the only part the entry stated as a
rule, was itself the bug.** `block_declaration_refusal` is the predicate,
`refused_blocks` the census, and `web/game_flow.py` lost its second copy of the
fallback chain (whose safety valve wiped *every* seat's blocks). Parts (2) and
(3) were both already free: `resolved_blockers` is `defender.battlefield[idx]`
and never needed hoisting, and `ignore_substitution=` had existed since Melee.

The part worth carrying is part (1). It said the cap "totals **every**
defender's blockers (CR 509.1b)", which is what the code did — and **CR 802.4b
says the opposite in as many words**: "When determining whether a defending
player's blocks are legal, ignore any creatures attacking other players and any
blocking creatures controlled by other players." So Caverns of Despair had been
refusing *legal* blocks in multiplayer for the life of the engine, on top of the
AI defect the entry was about. A restriction firing more often than the card
allows is the same silent wrongness as one firing less often, pointed the other
way — and this list's own instruction ("check the CR, do not rule from memory")
is what found it, applied to the brief rather than to a card.

**What is left is CR 509.1c's maximisation**, declined at 6ED with four parts
named *after* the naive fix was built and backed out — which is the right way to
decline. The five requirement checks in `declare_blockers` consult menace only,
so the three declaration-wide restrictions are invisible to them: **three
Watchdogs under a Caverns of Despair has no legal block declaration at all**,
and combat deadlocks for a human seat as thoroughly as for an AI one. The parts:
(1) "is this creature compelled?" as one predicate over all six channels that
currently each read their own; (2) a *substitution* test rather than an addition
test, so "the cap is full of creatures that also owe requirements" is
distinguishable from "the cap is full of creatures that don't"; (3) the count
itself — obeyed vs maximum obeyable — which is the only shape that expresses "2
of these 3 Watchdogs"; (4) the AI prune preferring to keep compelled blockers.
It is a simulator issue now rather than a silent hang.

**Added at ULG's W2G5, drained at 6ED's W1G5: two prompts whose subject has no
`permanent_id`.** Both are addressed now. Nether Shadow's graveyard return and a
Nafs Asp obligation carry a `subject_ordinal` and are filed under
`upkeep_step.subject_prompt_key`; `prompt_subject_ordinal` is its wire half,
required of a prompt that has one exactly as `prompt_permanent_id` is. Two
eligible Nether Shadows are two offers, and declining the first while accepting
the second returns exactly one — driven in the app, not only headless.

Three things the entry got wrong, worth keeping because each is a shape a brief
takes:

* **It named the wrong machinery.** "The fix is registry-shaped —
  `engine/pending_choices.py`, the `ChoiceSpec` table, the renderers in
  `web/prompts.py`" is true of every prompt in the engine *except* these. The
  upkeep protocol is the one channel that does not run through
  `pending_choices` (`tests/ui/test_upkeep_prompt_wire.py` says so in a
  comment), and none of those three files was touched. `ChoiceSpec.
  holds_priority` is likewise not what makes this prompt wait —
  `_upkeep_decisions_pending` and `web/actions.py`'s gate are.
* **It named the wrong shape to reuse.** `TargetRoleRef`'s graveyard half is
  `(seat, index)`, and an index is a slot: it renumbers, and the obligation list
  has no graveyard to index at all. What both subjects share is the thing
  `TargetRoleRef` *resolves into* — `GraveyardTarget.ordinal`, which copy of
  this card, computed by the one function that computes it,
  `Game.graveyard_target_at`.
* **Its residual was right for a reason it did not give.** `trigger_targets`
  values are still `(seat, battlefield index)`, and re-measuring says leave them
  there. The window looked open — `web/actions.py` lets `tap` and `activate`
  through while an upkeep decision is owed — but an activation during that
  window only puts an ability on the *stack*; nothing resolves and the
  battlefield cannot renumber before `resolve_upkeep` reads the index (measured:
  two Erhnam Djinns, a Prodigal Sorcerer pinging the 1/1 between the two
  answers, both Djinns still hit the creatures they named). The stack-bound
  reader is safe for a *different* reason than "same call": the index it hands
  to `_enqueue_triggered_ability` is stamped into an id by
  `_stamp_stack_targets` at the push, which is the boundary that function exists
  to guard.

  **The residual, recorded because "unreachable today" is this repo's own
  warning phrase.** `_resolve_upkeep_trigger_target` falls back to
  `candidates[0]` on a stale index *silently* — replacing a player's choice with
  the engine's, in the direction of doing something rather than nothing. It is
  unreachable only because nothing resolves inside the upkeep-decision window,
  which is a fact about today's gate rather than about the reader. The day
  anything does resolve there it is live. Cost to close, measured rather than
  estimated: three engine readers, one web writer, an `id` on `valid_targets`,
  `session_store`'s annotation, and six test call sites passing `(seat, index)`
  tuples.

**Added at 6ED's W1G2: the engine's own layer-read guard has two holes, and the
`web/` twin built this wave has neither.** Its pattern is
`\.card\.(type_line|colors)`, which omits **`primary_type`** — the field every
one of the seven historical `web/` sites used, and **70** reads in `engine/`.
And its exemptions are **per file**, so `mixins/helpers.py` ("the Aura shape,
plus a stack item's card colours") hides two live Licid-class reads:
`"Aura" in permanent.card.type_line` at `:1066` and `:2084`, in the engine's own
graveyard path. A Licid is a creature that *becomes* an Aura by a layer-4 type
change, so the printed line is the wrong question and `effective_card` is also
the wrong fix — only `has_type` answers.

Two parts, and the second is the one that keeps it fixed: widen the pattern to
`primary_type` and triage the 70; and convert the file exemptions to **per-module
counts** the way `test_control_reads.py` and this wave's `web/` guard do, so a
*new* offence in an already-exempt file fails. A guard that exempts a file
cannot ratchet, which is why this one went four sets without moving.

**Part two drained 2026-09-13, at the Phase 0 before the next set; part one is
now a ratchet instead of a round.** All four patterns in
`tests/engine/test_layer_reads.py` — type/colour, the non-permanent colour,
text/keywords, and `primary_type` at last — are **per-module counts** that may
only go down, with a companion test that refuses a baseline sitting *above* the
real count (which subsumes the three stale-exemption checks: an entry for a
module with no such read left is slack of exactly its own size).

The triage of the 64 is still a round and is still unclaimed — each site needs a
judgement about whether it means the card or the permanent, and some cannot be
fixed on this side alone (Balance's land/creature counts are the worked example,
five engine sites and a rule for a permanent that is both). What changed is that
there cannot be a **65th**, which is what four sets of one-site instalments were
failing to buy.

**Two corrections to this entry, both from measuring rather than reading it.**
The population is **64**, not 70 — the difference is the instalments each
promotion paid, `engine/ai_simulator.py`'s among them. And the file exemption was
not merely unable to ratchet, it was **already covering live offences**:
`mixins/helpers.py` sat on the list for "the Aura shape, plus a stack item's card
colours" and holds two Licid-class `"Aura" in permanent.card.type_line` reads and
**no colour read at all**. Half the stated reason had gone stale while the other
half hid the offences, and `test_no_printed_read_exemption_has_gone_stale` passed
throughout because it only ever asked whether *any* hit remained. Backwards-
validated in all three directions before being believed: a new read in an
already-exempt module fails, a 65th `primary_type` read fails, and a baseline
above the truth fails.

**Added at 6ED's W1G3, and it is a divergence the same wave created:** the
engine now prices a spell through `cost_modifiers` and `web/serialization.py`
still prices Gloom by hand. W1G2 replaced the *castable highlight*'s copy —
which decides whether a card is offered — and declined the *displayed cost
string*, `_gloom_white_tax` at `web/serialization.py:576`: `any(perm.card.name ==
"Gloom" ...)` returning a hardcoded `3`. So a Dark Ritual under Gloom +
Celestial Dawn is charged `{3}` by the engine and displayed as `{B}`, and the
client will not auto-tap for it.

It is the last card-name dispatch left in `web/` and the guard that would catch
it (`test_card_name_reads.py`) scans `engine/` only — the same file-scope hole
as the entry above. Three parts: call the same four cost functions; a cost-dict
to `{…}` renderer, which `mana_payment.mana_cost_label` nearly is except that it
renders from the normalized dict and **loses `{X}`**, so it would change every X
spell's displayed cost; and `tests/ui/test_batch9_ui_api.py` pins the current
string shape.

**Added at 6ED's W1G2, declined with its parts named: Balance and Kudzu count by
printed type, and the `web/` half cannot be fixed alone.** `web/prompts.py`'s
filter is a *faithful mirror* of five engine sites (`board_misc.balance_resources`
counts by `primary_type`; `_resolve_balance` and `_default_balance` validate by
it), so fixing the client would offer a permanent the resolver then refuses —
strictly worse than the bug. Six parts, five in `engine/` and one that follows
for free; the design piece is part five, **a permanent that is both a land and a
creature**, because Balance's printed text is two separate steps and under
Living Lands or Kormus Bell the two chosen sets overlap. Payers: Living Lands,
Kormus Bell, an animated Mishra's Factory.

There is a second reason it is worth taking whole: `web/prompts.py` **cannot
reach** the fix even when the engine is right, because `prompts` sits below
`serialization` in `web/__init__.LAYERS`, which is why `PromptContext` injects
`serialize_card` at all. The missing piece is a second injected callable taking
a permanent — one line at each of three sites once it exists.

**Added at UDS's wave 2, declined with its parts named: a spell's targets live
in one description, a *sequence's* live in several, and the roles walk only
reads the first.** Donate's two slots (a player and a permanent) are one
`targets` description on one instruction, which is what W2G1 taught
`role_object_at` and the walk to resolve. **Shower of Sparks** (USG) and
**Superior Numbers** (MIR) are not that shape: the first is a `sequence` of two
independent `deal_damage` steps each with its own description, so both points
land on the creature and the player takes none; the second's opponent is a bare
`owner: "target_opponent"` inside an `x_from_count` payload and is not a
`targets` description at all — measured, the engine substitutes the target's
controller when that is an opponent and the first opponent otherwise, so at
three seats the caster cannot say whose creatures are counted.

Five parts: `_from_instructions` builds roles **across** a sequence's steps
instead of returning the first step's spec; each targeting step carries its own
`role` name in the shared description; `deal_damage` and every other per-step
handler resolves through `resolve_role_permanent` / `resolve_role_player`
instead of `resolve_target_permanent`; a count payload's `owner:
"target_opponent"` becomes an announced role (Superior Numbers alone,
independent of the rest); and the AI's chosen seat for a player role, which is a
valuation rather than a policy weight. The pool census for the class is **seven
shipped cards** — Drafna's Restoration, Gaea's Blessing, Phelddagrif, Reap,
Shower of Sparks, Soldevi Heretic, Superior Numbers. No regression tests were
written for them, deliberately: a test asserting the current wrong behaviour is
worse than none.

**Added at UDS's wave 2: nineteen choice kinds whose resolver never takes its
own choice off the queue.** `_resolve_pay_any_amount` was one and is fixed —
after Liege of the Hollows died and both seats paid, the game reported a
decision nobody owed and refused every further action by the seat that had
already answered. It was hidden because `auto_resolve_pending_choices` discards
for AI and headless seats, so only a *confirmed* answer wedges. The other
nineteen are `body_choice`, `cast_choice`, `choose_cards_in_hand`,
`entry_exile`, `graveyard_exile_pick`, `opponent_damage`, `permanent_choice`,
`player_choice`, `retarget_choice`, plus ten that delegate to
`resolve_replacement_choice` and use the other queue (probably fine). Each needs
a per-kind probe to say whether it actually wedges. The general fix is one of
two one-line changes with a whole-pool blast radius — teach `ChoiceSpec.open_for`
that an `_answered` choice is closed (Word of Command is `suspends=False`, so
untouched), or discard in `resolve_pending_choice` — which is why it is an entry
rather than a round's tail.

**Added at UDS's Phase 4: a triggered ability with a graveyard target announces
nothing.** `graveyard_creature` is deliberately outside
`_CHOOSABLE_TRIGGER_TARGET_KINDS`, so Junk Diver's "return **another** target
artifact card from your graveyard to your hand" resolves doing nothing when no
legal card exists, rather than being removed from the stack by CR 603.3c — and
with two legal artifact cards a human never picks which comes back. The
observable outcome is now right (the source excludes itself); the announcement
is not. The same gap covers every graveyard-targeting trigger in the pool,
including Iridescent Drake, whose target is chosen by `reanimate_creature`'s
fallback search rather than by its controller. Widening that set is the round.

**Added at UDS's Phase 4: `costs.py` is now the third reader of the printed word
"another", and its recorded reason for being separate is stale.** The comment at
`engine/grammar/costs.py:59-63` says teaching the noun parser an "another"
quantifier "would change every targeted line in the pool"; `parse_target_spec`
has had **two** `another` branches for sets, recording `distinct_from_prior`.
The decision itself must stand as-is — `costs.py` consumes the word before
`parse_target_spec` sees it, and if it stopped, the spec would come back
quantifier `"a"` with `distinct_from_prior=True` and `_parse_cost_object`'s
`replace(spec.filter, …)` would **silently drop it**, which is this round's own
bug class. Unifying the three readers moves every cost payload in the pool.
Its CR citation is also wrong: 602.5c is about a restriction on an ability
acquired from another object. **CR 113.7** is the rule that makes "another" mean
the source (113.7a for last-known information); several comments in
`engine/subject_filters.py` and around it miscite **CR 109.5**, which is about
"you"/"your", and `test_cr_citation_subjects.py` polices only the 701 block.

**Added at MMQ's Phase 6: a *priced* mana ability has no land-click route, and
32 lands are on the far side of it.** `tap_land_for_mana` takes no ability index
and pays only the tap, so it refuses by design (CR 602.2b) any land whose mana
ability costs something else — Gemstone Mine and the five MMQ depletion lands.
The wire's land-click branch routes there, so clicking such a land in the app
does nothing; the ability *is* reachable, and correct, through
`{"action": "activate", "ability_index": N}`, which was driven end to end in the
running app at Phase 5 (Peat Bog: counter 2 -> 1, `{B}{B}` produced, stack
empty). W3G5 measured the population at **32** lands that never reach the
tap-for-mana seam — 26 tap-alone and 6 priced — and named the fix: move the
tap-for-mana announcement into the mana ability's *resolution* rather than
having the wire choose between two seams, which is the only shape that also
covers the priced six.

**Do not read this as "the client cannot see these abilities".** That was the
first diagnosis here and a census killed it: the client's activated-line regex
is symbol-only and misses **577 of 1,743** lines (33%) — including Black Lotus,
which is plainly playable — so it is not the offer gate and the routing is the
whole question. Whoever takes the round should start by establishing what the
canvas click actually dispatches for a land, which this Phase 5 did not manage
to exercise before the turn cycle ran out of patience.

**Added at MMQ's Phase 6: `test_layer_reads.py`'s pattern still omits
`primary_type`, and Phase 5 paid for it again.** The entry two sets ago recorded
that the engine guard's pattern is `\.card\.(type_line|colors)` and that
**70** `primary_type` reads in `engine/` are outside it. `engine/ai_simulator.py`
was one of them, and it produced a **false** promotion-gate issue on Disenchant
— the engine had destroyed exactly the right permanent. The population of
artifact creatures that `primary_type` mis-answers is now **114**, up from the
77 measured at Weatherlight. The instalment is fixed and the scan is not; this
is the fifth consecutive promotion to turn up one of these.

**The scan is fixed 2026-09-13, at the Phase 0 before the next set** — see the
6ED entry above, which this one is the fifth instalment of. `primary_type` is in
the pattern, and all four patterns ratchet per module rather than exempting a
file. The remaining 64 reads are recorded in `PRIMARY_TYPE_BASELINE` as
**untriaged debt rather than blessings** — the one baseline in that file whose
entries deliberately carry no reason, because nobody has yet asked of those
sites whether they mean the card or the permanent.

## Phase 0 — Pre-flight

**Entry:** a set has been chosen. **Exit:** clean tree, every gate green,
instruments current.

1. Run the full suite, then `python scripts/check_all.py --freshness` —
   every `--check` gate plus the tracker regenerations, in ci.yml's order
   (a guard test holds the two lists equal, so the script cannot drift from
   the workflow). All must be a no-op on a clean tree. Starting a set on a
   red or stale HEAD conflates pre-existing drift with the set's own diffs.
2. If the set postdates `data/vocabulary/manifest.json`'s `fetched_at`, run
   `scripts/fetch_vocabulary.py` (network) and commit the vocabulary diff on
   its own. A creature type or keyword the vocabulary has never heard of does
   not fail loudly later — it refuses to parse in a way that looks exactly
   like a grammar gap, and gets debugged as one.
3. **Read the size-guard headroom before briefing anyone**:
   `python scripts/check_all.py --caps`. It fails nothing and is not a gate —
   the point is that the *gate* only fires once a module is already over, and
   by then the work that crossed the line is usually two groups' additions
   summed at integration, where the seam has to be found with none of the work
   in hand. Mirage crossed five caps that way across two waves, every one on
   nobody's branch. A module a few lines from a cap is a module the next set
   will breach on arrival: either split it now, while nothing is in flight and
   the family boundary is the only question, or brief the group that owns that
   area to expect the split as part of its round.

   **Visions pre-split the tightest *unowned* module and still crossed five
   caps, so read the headroom per module the wave will touch rather than for
   the tightest one.** `lowering/_common.py` was split at Phase 0 for the right
   reason — every lowering family imports it, so no single group would have
   crossed it alone — and `lowering/categories.py`, `conditions.py` and
   `lowering/board.py` then went over at integration anyway, each by two
   groups' additions summing. The prediction that works is per-family: take the
   census, note which modules each *group's* family lands in, and pre-split any
   that two groups will both reach. A module one group owns can be briefed; a
   module two groups share cannot, because neither will cross it.

   **Tempest ran the rule four times and it held four times, at a cost worth
   knowing: three pre-splits and three integrator splits.** Every wave's Phase 0
   split moved **0 of 2,824** compiled programs, and every module that crossed a
   cap at integration was one two groups had both reached. The prediction is now
   cheap enough to make mechanically: take the census, note which modules each
   group's family lands in, pre-split the shared ones, brief the owned ones.

   **And read the seam you inherit as a lead, not a fact.** Tempest's third
   pre-split was briefed with a seam a previous group had reported; the agent
   checked it, found the docstring never says it and the *code* contradicts it
   (both halves read the same table and called the same sub-production), and cut
   one sentence earlier where the code agreed. A cut on the reported line would
   have bought 42 lines out of 940. **A split's seam gets the same treatment as a
   refusal site.**

   **Exodus measured the rule's two halves against each other and only one
   survives.** Three shared modules were pre-split at Phase 0 and each was
   right — but of the set's **eight** cap crossings, **six were in modules no
   brief named**, and three of the five modules handed to a group as "yours,
   expect to split it" were never opened at all. Two waves, eleven groups, and
   the per-group prediction was wrong more often than it was right.

   So the rule has one half, not two. **Pre-splitting a module two groups will
   reach works** and should keep happening. **Predicting which module a group's
   *cards* will land in does not work**, and the honest move is to stop: name
   the shared modules, say that everything else within 30 lines is unowned, and
   tell every group to split what it crosses and to ask "where does this
   already belong?" first. A group that crosses a cap in round cuts it well —
   that has now held at Weatherlight, Stronghold and here.

   **Stronghold priced the other half of that rule: a shared-and-tight module
   left un-split costs a card.** Ten modules sat within 30 lines at Phase 0 and
   exactly one — `subject_verb.py`, 13 under, reached by every group's work —
   was pre-split. `lowering/characteristics.py` at **7** under was read as
   shared, judged too expensive, and briefed instead. Wave 1's G3 then declined
   **Spined Sliver** naming that module as the whole blocker ("it needs a split
   first, and splitting a shared module mid-wave is the integration cost the
   playbook warns about"), and the card went into a second wave for a reason
   that had nothing to do with the card. The rule is not "pre-split the
   tightest"; it is **pre-split every module two groups will reach**, and the
   count of those is what Phase 0 has to produce.

   **And a cap breach is more often a misplaced function than a missing
   module.** Three crossings across STH's two waves and only one made a new
   file: G4 moved its production to `lowering/board.py` where its twin already
   lived, G5 reverted a new module and put its production in
   `lowering/linked_exile.py`, whose stated subject already covered it, and W2G5
   moved two fusers into `lowering/sequences.py` because that module's docstring
   says a fuser lives with the sequence it folds. Ask "where does this already
   belong?" before "what should this module be called?".

   **Weatherlight tested that sentence in both directions and it held exactly.**
   Wave 1 gave each of the seven tight modules a **single owning group**, named
   in that group's brief with the instruction to expect its own split, and left
   one module deliberately unowned as the control. Integration crossed **zero**
   caps; two groups crossed one in round and split it themselves, each along a
   line the module's docstring had already drawn; and the control module was the
   only one that drifted. Wave 2 then shared two modules between two groups on
   purpose, told both to keep their additions small, and **both went over at
   integration anyway** — by 3 lines and by 1. So the rule is not "brief harder":
   **a shared module is pre-split at Phase 0 and an owned one is briefed**, and
   there is no third option.

   **A split moves no card, and there is exactly one way it can.** Giving a
   moved lowering table a new *category* name to match its new module leaves
   that name out of `GRAMMAR_CATEGORIES`, which has no fallback underneath it —
   so every card whose kind moved goes unsupported. A category names the
   migration family a **kind** belongs to, never the module its lowering lives
   in. Two cards and eleven guards, at Weatherlight's wave-2 integration.

   The consolation is that the seam is findable late: every one of those splits
   went along a line the repo had already written down in prose, and two wave-2
   groups independently made the *same* split of `lowering/stack.py`, moving
   seven byte-identical functions. Splitting at the cap beats raising the
   number.

   **And the cut that restores a module's *subject* beats the cut that only
   buys lines.** The Phase 0 after MMQ had two shared modules to pre-split and
   the second one's obvious cut — 768 of `lowering/_records.py`'s 982 lines are
   one table — fought the module's own docstring, which argues the table and
   its accessors belong together because "the only thing that can say the two
   agree is a declaration both sides are held to". The real seam was two
   functions at the bottom that **read no part of that table**: a pair of
   CR 615.5 predicates that had landed there because it was a convenient floor
   rather than because it was *their* floor. Moving them to
   `lowering/_prevented_riders.py` — whose stated subject is the rider a shield
   carries, and whose docstring already cited the same two cards — bought 55
   lines and made the first paragraph of `_records`' docstring true again.
   So when the size cut and the stated subject disagree, **the module has
   usually accumulated something that is not its subject**; look for that before
   cutting the thing the docstring defends.

   The same Phase 0's first split is the ordinary case and worth citing beside
   it: `records.py` at 973 went to `cost_records.py` along a seam the *mirror*
   had already taken and named — `lowering/_cost_records.py` left
   `lowering/_records.py` at ULG wave 1 because `_PRODUCES` is keyed by
   instruction kind and a cost has none, and the parse halves of those two
   subjects had simply stayed in one file until this one hit the guard. Reusing
   the mirror's name re-formed the mirror instead of forking a vocabulary, and
   the mirror's *other* decision was reused too: point the four importers at the
   new module rather than re-exporting, because a re-export is a hop that is
   invisible until somebody greps for the reader. Both splits moved **0 of
   4,026** compiled programs.

   **Urza's Legacy is the rule's cleanest result and the seam advice's worst.**
   Eight modules sat within 30 lines at Phase 0; the four that two or more of the
   wave's groups would reach were pre-split, and **integration crossed zero
   caps** across two waves and ten groups — the first set where it crossed none.
   Pre-splitting a shared module works, and this is the run to cite.

   What the same exercise says about *seams* is the opposite. Each of the four
   agents was told its module's recorded seam was a lead rather than a fact, and
   **three of the four found a written line that was wrong** — not stale by a
   clause, wrong: `lowering/control_flow.py`'s docstring named four composers of
   which two had already left, `conditions.py`'s comment claimed the record
   clauses were read elsewhere when eleven were read by the dispatcher itself,
   and `delayed.py` called itself "the one place the rows become a node" with a
   second place one layer up. **And the fourth is the shape to watch for: the
   wrong sentence was in a *different module's* docstring.** `parser.py`'s own
   seam was right and `riders.py` denied it ("the loop … stays behind in
   `parser.py` with the line-level productions it belongs to") — which is the
   sentence a briefer would most likely hand over, because it is the one that
   mentions the module you are cutting. Read the seam **and** everything that
   points at it.

   Three brief corrections the same wave produced, all mechanical and all worth
   carrying: declaring a new top-level `engine/grammar/*.py` is **one** place
   (`PARSE_LAYERS` satisfies both layering guards; `FAMILY_SHARED` is only ever
   compared against members of `effects/`, `lowering/` and `ast/`, so a
   top-level module cannot reach it), while a module *inside* `lowering/` needs
   `FAMILY_SHARED` **and** the `shared` tuple in
   `test_families_import_only_their_package_shared_module`'s parametrize.
   Re-export is enforced in the **opposite** direction from "so no caller moves":
   `tests/engine/test_import_hygiene.py` fails on a re-export nobody *pulls*, so
   the rule is re-export exactly what a caller pulls and nothing else. And
   **`oracle_diff compare` belongs before the suite, not after** — it caught an
   arity mismatch that all five post-split scans are structurally blind to,
   failing in seconds with a full traceback where the suite scatters failures.

   **Nemesis is the rule's second clean run, and it says what the trigger
   is.** Four grammar modules sat within 25 lines; the three that several
   groups' families *could* reach were pre-split and the fourth was briefed to
   its one owner. Integration then crossed **zero** caps across ten groups and
   two waves — while two of the three splitters reported that the set's cards
   would mostly **not** land in their module (the conditions this set prints
   parse in `condition_counts.py`, and only one of fading's counter sentences
   is a placement). The split paid anyway, because at 14 lines under, any one
   group adding any one clause crosses it. So the trigger is **"shared and
   tight"**, not "this set's cards land here" — Exodus's finding that the
   second question cannot be answered, confirmed from the other side. The one
   owned module split cleanly in round, and the one that drifted to 978 during
   wave 1 was relieved by its next owner moving a single misplaced function.

   **Planeshift pre-split the two modules that were shared and tight, and both
   seams handed over were wrong - the third set running.** `lowering/board.py`'s
   docstring said the toll productions were "all here"; they had left at Urza's
   Saga, seven sets earlier. `ast/board.py`'s listed five subjects and none of
   them grows; the cut was fifteen nodes the docstring did not list. A handed
   seam is now reliably a lead and nothing more - which is an argument for
   handing over the *measurements to make* (call graph, who imports what, blame
   since the last split) instead of a seam.

   **And a split owes a sixth scan: what reads the module by name.** A guard
   that keeps a hand-written list of module names stops reading whatever a
   split moves out, with nothing undefined, unused or duplicated. The
   `ast.Effect` union guard listed eight of fourteen families that way - five
   earlier splits had each shrunk it - and read its "dispatch" out of a file
   the dispatch had left, so it was examining nine of 223 dispatched nodes.
   Widened to the layering guard's own list and the live dispatch tables, it
   named two nodes missing from the union on the day. Grep the tests for the
   split module's bare name before running anything.
4. Clear anything above in Known gaps marked for Phase 0.

## Phase 1 — Ingest and measure

**Entry:** Phase 0 exit. **Exit:** the set sits under `measured`, the suite
is green, the trackers carry its row, and the census is in hand.

1. `python scripts/ingest_set.py <CODE> --fetch --register`. That is the
   whole registration: the card file is written and the `measured` entry is
   inserted release-ordered (`card_loader.register_measured_set` — the
   manifest has one parser, and the write lives beside it). The web app, the
   fixtures and the coverage scripts all read the manifest
   (`tests/sets/README.md`, "Adding a set"). Promotion to `sets` stays
   Phase 4's reviewed hand move.
2. Run the full suite and **treat what fires as yield, not noise**. A new
   set's text reaches code the old pool never executed; the M21 ingest
   surfaced a never-run import that was 66 failures waiting. These are engine
   bugs, found early and cheap — fix them now.

   **Run the suite so that its exit code is the one you read.** `pytest … |
   tail` reports `tail`'s status, so Weatherlight's ingest run read green with
   three tests failing and the whole yield of Phase 1 was nearly lost — a
   self-reference ratchet that wanted a card read, a shipped activation cost
   charged by nobody, and CR 601.2b's no-unread-cost gate naming four cards.
   Redirect to a file, read `$?`, and grep for `FAILED`. A gate piped into
   anything is not a gate.

   **Then confirm the suite actually loaded the new set.** A green run over a
   pool that does not contain it looks exactly like a green run that found
   nothing. The catalog sweep read `load_catalog()` — shipped-only by design —
   for three sets running, so every ingest's yield step had been measuring the
   old pool; The Dark's 119 cards went through it untouched.
   `test_the_sweep_covers_every_measured_set` now asserts the coverage, but the
   habit is the point: check the count moved before believing the zero.
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

   **Beside it, run the census below the sentence:** `support_report.py --set
   <CODE> --fragments`, an n-gram over the same refused lines ranked by how
   many **cards** share each fragment. The rollup's lines-per-distinct-sentence
   ratio measured 1.00 for four sets running ("no production here buys two
   cards") while ten HML cards shared one untap-denial clause inside ten
   different sentences; the fragment census named every wave-1 group boundary
   and the sentence census named none. Rank the backlog by its cards column.
   (`--json` carries every census this script computes in one object.)

   **Then run the two sentence-level instruments, here and not at Phase 4:**
   `scripts/parse_coverage.py` (whose measured-set section is reported and not
   gated) and `support_report.py --set <CODE> --hollow-lines`. Both name
   **supported** cards carrying a line nothing implements, and that population
   is the one the census structurally cannot see: it counts *cards*, and a card
   is supported when any of its lines is. Fallen Empires is the worked example
   and it changed the round plan. Its refusal census measured 39 refused lines
   over 39 distinct sentences — no production shared by even two cards, which
   reads as "this set has no leverage in it" — while these two instruments found
   five supported cards carrying eight unimplemented sentences, four of which
   were a *second card* for a production a refused card already needed. The
   pairs became the group split and each cost one production for two cards.
   Left to Phase 4 they would have been promotion-gate findings instead, after
   the work they could have halved was already done.

   **The third is the picker sweep, moved up from Phase 4 for the same reason.**
   `python scripts/picker_sweep.py --set <CODE>` asks of every *supported* card
   whether `targeting.derive_cast_spec` / `derive_activation_spec` offer what
   the printed line names — the probes are the ratchet tests' own
   (`engine/targeting.py`'s `line_names_a_cast_target` / `cast_picker_expected`
   / `card_names_a_chooser`, one function per question with two readers each),
   so the script and the shipped-pool ratchets cannot drift. It costs nothing
   and it found Roots on the day of HML's ingest: a supported Aura, no hollow
   line, every sentence claimed, and a cast spec of None — which is the exact
   value the client tests to decide whether to ask for a target, so the app sent
   a bare cast and the engine refused it. **A supported card no player could put
   on the battlefield**, and this is the only instrument in the repo that sees
   one. Know its scope: it answers for the *cast* and *activation* pickers, so a
   choice made as a permanent enters, or at resolution inside a triggered
   ability, is out of scope and reads as a false positive.

   And read a picker finding as *half* the card. Roots' one printed line had two
   contradictory failures — the spec derivation could not read `Enchant creature
   without flying`, **and** the attach check took its permissive fallback, so the
   printed exclusion was enforced by nothing and the Aura could be attached to a
   flyer. The sweep sees only the first, and one gate hid both: the support claim
   and the coverage channel each accepted any line starting with "enchant ".
5. **Probe a keyword's *rewrite target* against the live grammar before sizing
   it.** A keyword whose CR definition is a rewrite (equip, cycling, echo,
   buyback, cumulative upkeep) costs a rewrite in `oracle.expand_ability_lines`
   plus whatever the rewritten sentence still needs — and the census cannot tell
   you which, because it reports the *printed* line refusing at the line gate.
   USG's census read Cycling (34 cards) and Echo (14) as the set's two big rocks
   and both looked like grammar rounds; `parse_line` on "{2}, Discard this card:
   Draw a card." and on "At the beginning of your upkeep, sacrifice this creature
   unless you pay {1}{G}" answered in full, and the real work was a rewrite each
   plus one intervening-if. Two probes, before any brief was written, and they
   changed the shape of the wave.

   **And the *next* set is where that work is paid back, which is worth knowing
   before you read an arrival percentage as a fact about the set.** Urza's Legacy
   arrived **80.4% supported**, the highest of any set ever ingested here against
   a previous best of 67.8% — not because its cards are simpler but because 25 of
   them print echo or cycling, which Urza's Saga had built as rewrites the block
   before. A block's second set inherits its first set's keyword work wholesale.
   Read a high arrival number as "the last set did this already", and check which
   of the census's big rocks are already-built rewrites before sizing anything.

   **A card that is supported on arrival has not been run, and a brief must not
   cite it as working.** Invasion's colour brief said "two of the dragons
   already work" because Rith and Treva compiled; driven, both ignored the
   colour they asked for and counted their controller's permanents alone. The
   group found it by doing what the brief told it to do with a card it
   distrusted. Write "compiles" when you mean compiles.

   **So give the supported-on-arrival cards to somebody, by family.**
   Planeshift's wave-1 card sheets each ended with a second list - the cards of
   that group's family that arrived supported with every instrument quiet - and
   the instruction to give each one a headless game after the group's own
   cards: fix what is local, measure what is not. About eighty cards were
   driven that way and it paid on the first day. Ertai's Trickery ("Counter
   target spell if it was kicked") had never countered anything - it asked
   whether *it* was kicked. Phelddagrif's "target opponent may draw a card"
   drew for its controller. The AI returned the creature it had just cast on
   112 of 127 gating triggers. None of those is visible to a census, and each
   was found by the group that had just built the machinery beside it.

   **And a hollow line names an ability nothing compiles, not a behaviour
   nothing performs.** The ingest's headline was "the five Lairs cannot tap
   for mana", read off `--hollow-lines`. They could: the tap seam fell back to
   the card's `produced_mana` summary, which is the door the web, the AI and
   every payment planner use. What was missing was the *ability* - nothing to
   activate, an unclaimed line. The group measured it and said so. Drive the
   card before the instrument's finding becomes the brief's first sentence.

6. **Ask how many of the set's cards are new to the pool**, before planning any
   round. Every phase after this one is written for a set that brings cards,
   and a reprint set brings printings: 4ED's 378 entries were 368 unique cards
   and *all* of them were already shipped, so the census read 368/368 supported
   at ingest and Phases 2 and 3 had no work in them at all. Diff the ingested
   file's `oracle_id`s against the shipped pool — one comparison, and it decides
   whether this is a set you implement or a set you promote. Do not read a
   100%-supported census as an anticlimax and skip the rest: the ingest still
   pays, and where it pays is Phase 4. Eight such sets are still ahead (ROADMAP's
   header names them), so this is a shape, not a curiosity.

   **Diff against *this pool*, never against the release line's own column.**
   `set_progress.json` records 6ED with **0** new cards and it brought **two** —
   Blaze and Regal Unicorn, whose earlier printing was Portal, a set the manifest
   does not carry. That column counts against all of Magic; a reprint set
   reprints from the manifest, and the difference is however many of its sources
   are still unshipped. Two cards is small enough to look like nothing and large
   enough that "no per-card tests, this is a pure reprint" would have been false
   in the set's own test file.

## Phase 2 — Machinery census (the big rocks)

**Entry:** the census exists. **Exit:** every unsupported card is assigned to
exactly one bucket, and a round plan exists — in the wave briefs and the
commit that opens the set, not in ROADMAP.md, which carries only its live
sections.

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
   **And a keyword defined as a *rewrite* is absent from the registry by
   design** — read that before sending anyone to add one. `IMPLEMENTED_KEYWORDS`
   admits a keyword being **granted or named** ("gains flying", "creatures with
   flanking"); equip, buyback and cumulative upkeep are all missing from it for
   the reason cycling and echo are. By the time any reader sees the card the word
   is gone and the ability it means is in its place, and
   `test_keyword_registry`'s bare-keyword-card guard forces the point: listing
   one means either failing that guard or admitting a costless ability that
   charges nothing. USG's brief said the opposite to two groups and both refused
   it, correctly.

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

**Invasion is the set with machinery in it, and the census sized it right by
probing rather than reading.** Kicker (35 cards) is CR 702.33a's rewrite onto
buyback's optional-cost machinery — one group built it and landed 30 cards,
eight of them spells held back as "fourteen different second sentences".
Split cards were a subsystem and five cards, and the group's design — **a face
is a card**, so every stack reader is right with no edit — is the precedent for
every later layout. What the census could not size was the *other* half of a
new layout: see Phase 4, "blind, not red".

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
mis-plays**. And when a brief states a **ruling** - how a card is played, as
opposed to what a rule says - give its source or do not state it. Invasion's
brief and Planeshift's both said, from memory, that a dual land may be the
chosen land for one basic land type only (Global Ruin, Planar Overlay). The
cards' rulings say it may be chosen for each of its types. Rulings are not in
`MagicCompRules.txt`; Scryfall serves them per card (`rulings_uri`), and the
group that was handed the correction fetched them again rather than trust a
brief twice - which is how a third, shipped card with the same ruling
(Cataclysm) was found. A card is supported when *any* of its lines is, so a whole
mechanic can be missing while every card printing it reports fine —
M21's scry was absent from the engine entirely while seven cards carrying it
compiled clean, and a shipped ability's cost was parsed by the grammar and
charged by nobody. `support_report.py` counts cards; these are sentences, and
only something that reads the compiled program line by line will find them.

## Phase 3 — Backlog rounds (generalise first)

**Entry:** the round plan exists, and `set_pool("<CODE>")` resolves the
measured set so per-card tests can land as the cards do. **Exit:**
`support_report.py --set <CODE>` reports every card supported.

**A late wave may spend a group on no cards at all.** By the last wave the
earlier ones have usually enumerated a pile of *shipped* defects they found,
measured and correctly declined to fix in round — the rule that a change whose
blast radius is the whole pool does not travel with a wave. That pile is a
group's brief. USG's third wave gave its fifth group **no cards from the set**,
and it returned twenty shipped permanents dealing damage as the printed card
rather than as the permanent (CR 120.7), a lifelink fallback that had never run
once, four cards whose triggers targeted themselves, and CR 603.4's fire-time
half. Spend the group this way only when the pile is already enumerated —
finding the work is a different job from doing it, and the enumeration is what
makes it one round's worth.

**Urza's Legacy spent two of five that way and both paid more than the cards
did.** Its second wave had six cards left, so three groups took them and two took
the pile: one found that **protection's damage half (CR 702.16e) did not exist**
— `_is_protected_from` was asked only from the two combat steps and
`damage_events.deal_damage`, the one seam, never asked it at all, so 64 shipped
cards printing protection took damage from 69 sweep lines for the life of the
engine — plus an attack cap the AI could not satisfy, so a seat under Crawlspace
*or* Caverns of Despair attacked with nobody for the rest of the game. The other
found the **upkeep prompt addressed by card name**: two Bad Moons, one answer,
both paid — 112 shipped cards, and CLAUDE.md's "address a permanent by its id,
not its slot" is the same rule with an index instead of a name.

The scheduling rule that follows: **the count of no-card groups is set by the
size of the enumerated pile, not by how many cards are left.** Six cards did not
need five groups; the pile did.

**Nemesis ran it with three cards left and four groups**, one on the cards and
three on the pile wave 1 had measured and declined. The pile groups fixed, each
with a census validated backwards: an activation that spent mana or exiled
cards and was *then* refused (493 shipped refusals that had paid something);
CR 608.2b never re-checking a target's description (130 resolutions acting on
an illegal target, most of them on a *bystander* through a handler's fallback
scan); Blood Moon not reaching the land tap path (103 shipped lands tapping for
their printed mana); and the AI aiming 56 of 112 denial spells at its own
creatures. `oracle_diff` read **0, 1 and 0** on those three engine merges —
6ED's finding again, that the pool's remaining defects live in dispatch, on the
wire and in policy, where the compiled map cannot look. And a wave-1 group that
merely *lists* what it measured and left is what made a wave-2 group's cold
start possible: every one of the three pile briefs was a wave-1 report's
"measured, not fixed" section with the parts already named.

**Planeshift had one card left after its first wave and spent five groups on
the pile.** What they fixed, each with a census written first and required to
name the known defect on the tree before the fix: a modal spell held to the
mode it announces (1,066 of 1,516 illegal named targets accepted; the browser
was sent the wrong picker for 33 of 47 object modes, so most Charm modes could
not be cast correctly at all), exact target counts and divisions; one
cast-prohibition predicate for three readers and a castable highlight that
asks the payment planner (3,543 land-and-cost pairs glowing unpayable); layer 5
ordered by timestamp (145 of 362 ordered cases wrong); the AI's sides, its
unused non-land mana and its take-everything defaults; and entry triggers as
stack objects (268 of 278 resolved inline). `oracle_diff` read **0 on all five**
and 1 on the card group.

Two things about briefing such a wave. **A group told to measure before
building, and that a measured decline is an honest outcome, is the group most
likely to land the risky item** - the entry-trigger group's census (807
scenarios identical both ways, 27 failing tests all of one mechanical kind) is
what made a change to 229 shipped triggers a one-round job, where the brief
had called it the riskiest in the wave. And **the pile's sections map onto
groups only if they are written by subject as the reports arrive**, not by
reporting group: five wave-1 reports each saw a piece of "what a cast may
announce", and it became a brief when the pieces were put under one heading
with every census path beside its number.

**6ED took that rule to its limit: a wave of five groups and *no* cards at
all.** The set arrived 335/335 supported with every instrument at zero, so
Phases 2 and 3 had no card work in them, and all five briefs were Known-gaps
entries. It worked — the wave fixed defects on **well over a hundred shipped
cards** — and the two things it proved are worth stating.

First, **an entry with individually named parts is a brief and an entry without
them is not**. Every one of the five had its parts enumerated by the group that
declined it, and that is what made a cold start possible; the entries that sat
in this list as prose would not have supported one.

Second, and this is the number to remember: **`oracle_diff` reported 0 of 3,572
on all five merges.** A whole wave, over a hundred mis-playing cards, and the
compiled-program differential — the instrument this playbook calls the cheapest
in the repo and the one that answers "what else did this touch?" — moved
nothing, correctly. Because none of these defects were in compilation. They were
in dispatch, on the wire, in a prompt's address and in the AI's declaration, and
**that is where the pool's remaining defects now live.** Keep running it (it is
what proves a change was local), and do not read its zero as a finding: a
text-keyed or wire-level round owes a census of its own, which is what W1G3's
four-boards-by-whole-pool comparison and W1G2's 28-card cost census are.

**A new census or instrument must be validated *backwards* before anyone trusts
it.** Run it against a commit where the defects it is meant to find are still
present, and require it to name them. USG's `scripts/unasked_narrowings.py` was
held to exactly that — against its round's parent it names all three dead cards
and nothing the round did not find; against HEAD they are gone. Two details of
its construction were both discovered *because* the first draft reported the
pre-round engine clean, which is the outcome a backwards validation exists to
disbelieve. A census that cannot reproduce a known finding is a census that will
report zero and mean nothing.

1. Each round, pick the card whose gap is **not about that card** — the
   change that clears the most other cards. The Revised narrative in git
   history (at and before `ee28617`) is the worked example: six cards, then
   three, then three, then one, then none, each round opening with the most
   general gap left. Apply
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

   **Diff the whole pool's compiled programs before believing a change is
   local.** `python scripts/oracle_diff.py snapshot` before the change,
   `python scripts/oracle_diff.py compare` after — and read every card that
   moved. The script exists because the by-hand rebuild of this map kept being
   lossy; it stores the programs
   **in full, with their payloads: not their kinds, and not their counts**
   (pinned by `tests/engine/test_oracle_diff.py`). Both abbreviations are natural and both
   are blind to exactly the narrowing class this instrument exists to catch,
   because a narrowing changes neither how many of a thing there are nor what the
   thing is called. Keyed on counts it cannot see a trigger narrowed from "blocks
   anything" to "blocks a black creature"; keyed on kinds it cannot see a
   `type_filter` restored to a payload. On HML two of five groups and the
   integrator each wrote a lossy version independently, and each version hid a
   real defect. The same substitution appears in *tests* — Whippoorwill's own
   test asserted instruction kinds and passed while the card exiled itself — and
   the map cannot see a **text-keyed table** at all, so a round that edits one
   owes a second differential over that table.
   **And a round that adds a defaulted field to a dataclass the snapshot reprs
   owes the reader a filtered number.** Alliances did it twice, reporting 710
   and 713 changed of 1,869 where ten and seven had really moved — every card
   with an activated ability moves when `ActivatedAbilityCost` gains a field.
   That is not noise to suppress: the full repr is what makes the narrowing
   class visible in the first place. Strip the new field's default spelling
   from both sides, re-compare, and report the filtered count — a round that
   reports the raw one has told the next integrator nothing.
   It is a minute's work over 1,600 cards and it is the cheapest instrument in
   this repo, because it answers the question every other one only approximates:
   *what else did this touch?* Three of Fallen Empires' five groups ran it
   unprompted and each named it as the thing that let them be sure. It also
   turned one inherited estimate inside out: Orcish Captain's decline was
   recorded as "cross-sentence pronoun rebinding is missing", a parser feature —
   and building that broke **eight shipped cards** which already played
   correctly, because the engine reads that pronoun in the *lowering* and each
   of those lowerings already had a branch for it. The differential said so in
   one run; the real fix was one branch in one lowering, and it moves 1 card of
   1,610.

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

   **The taxonomy has a fifth entry: `engine/oracle.py`'s trigger-condition
   table.** There are two trigger front ends and only one feeds dispatch — that
   regex table produces the `TriggerCondition` the phase steps read, and the
   grammar's `TriggerEvent` does not. A condition can be read perfectly by the
   grammar and still fire on the wrong event, which is what Rashka the Slayer
   did: its effect compiled and fired, its *narrowing* did not, and both the
   census and `parse_coverage.py` reported the sentence as unimplemented when it
   was implemented **too widely**.

   **And a refusal site can be manufactured by probe order.** Giant Oyster
   refused at `expected 'gain'` for two whole waves on a sentence that is a
   control change in nobody's reading, because the fronted-duration parser hands
   its tail to `_parse_gain_control`, which opens with `expect_word("gain")` and
   **raises** — replacing the real production's refusal with one from a
   production that was never a candidate. When a refusal names a verb the
   sentence does not contain, suspect the probe above it before the card.

   **A refusal can expire without anything failing.** A gate that declines for
   a reason that later stops being true keeps declining, silently and in the
   direction of doing less, and no test goes red. Legends found two: a
   "whole effect is optional" refusal whose stated reason (the prompt rode a
   queue only a triggered ability drained) stopped holding two rounds later,
   and a cost/benefit refusal that was correct at forty cards left and wrong at
   seven. When a round builds machinery near an old decline, re-probe the
   decline.

   **A decline ages in the direction of becoming free, and Tempest is the
   evidence.** Its last eighteen cards were each declined once or twice with
   their parts enumerated, and re-probing those lists found the machinery
   usually already built: Ertai's Meddling's five parts came back
   three-already-built, Coffin Queen's three came back two-expired, and
   Excavator's "an activation cost that records what it sacrificed" was answered
   by a channel written at both of `activation.py`'s sacrifice-cost sites and
   read by three handlers — the previous group had read the absence of the
   *wrong* channel as the absence of the mechanism. **Budget a decline's
   re-probe as cheaper than its estimate, and always re-probe.**

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
3. **"Give the behaviour a game" cannot be done in the app during this phase,
   and every group rediscovers that.** `web/runtime.CARD_PATHS` is built from
   `manifest_set_paths()` — shipped-only by design — and the Debug Menu reads the
   same catalog, so no path in the running app can put a *measured* set's card on
   a board. The Rock Hydra test, which this repo names as the only way to tell a
   working registry from one that claims a line and does less, therefore runs
   headless until promotion: drive a `Game` directly through the steps and read
   the log at each one, and use `run_ai_simulation(..., required_cards=[...])`,
   whose `required=` pin exists for exactly this. Brief it, or each group spends
   the discovery.

4. Between rounds: the supported count from `support_report.py --set <CODE>`
   must have risen; regenerate the trackers; run any `--accept` only after
   reading the diff it blesses.

   **And know what each instrument is actually for, because Exodus measured
   it.** Fifteen shipped cards were fixed across that set and the census found
   **none** of them; `--hollow-lines` and `parse_coverage` were at zero on the
   day of the ingest and stayed there all set, finding nothing. That is not an
   argument against running them — it is the argument *for* running them every
   round, since an instrument that costs nothing while quiet is only expensive
   when you skip it and it was not. What did the finding was, in order:
   **driving a game** (nine of the fifteen — the only thing that sees a runtime
   decline), **`oracle_diff`** (two regressions caught in flight that no test
   would have failed on), and **the deletion probe** (one card no other
   instrument in the repo can see). The census sized the buckets and named no
   defect, which is its job and its ceiling.

   **There are three ways a card reports supported and does nothing, and only
   one of them has an instrument.** Visions found all three:

   * the **hollow line** — an ability part with no instruction, which
     `--hollow-lines` sees;
   * the **channel mismatch** — Equipoise chose the right permanents and phased
     out none, because a reader filtered `permanents_from` on
     `isinstance(entry, int)` while the producer writes live `Permanent`s.
     Wave 1 had settled that channel's *arity* and nobody had settled its
     element type. **Settling an arity is only half of settling a channel**;
   * the **runtime decline** — Three Wishes' opening sentence parsed, lowered,
     compiled and did nothing, because the handler refuses at run time (a
     face-down exile with no source permanent, and Three Wishes is an instant).
     **Nothing in this repo can see that one.** The sentence is claimed, it
     produces a real instruction, and the refusal happens where no census
     looks. Only driving a game finds it, which is what the Rock Hydra test is
     for and why it is not optional.

   **And the exit is three numbers, not one.**
   `--hollow-lines` must reach zero — **check it every round, not at the end**
   — and so must `parse_coverage.py --set <CODE>`'s unclaimed list, which is
   the one Mirage learned the hard way. It reached 335/335 supported with zero
   hollow lines and **13 printed sentences on 11 cards that nothing
   implemented**, six of them admitted into the support gate by a *single
   whitelist word* (`gain`, `loses`, `deals`, `prevent the next`). Neither of
   the other two numbers can see that: a card is supported when **any** of its
   lines is, and `--hollow-lines` only sees a line that produced an ability
   *part*. And `parse_coverage` gates on the shipped half alone, so for a
   measured set it is advisory — which means nobody is forced to read it until
   the promotion, and by then it is a fourth wave of work rather than a round.
   Read it every round from Phase 3 onward. Legends reached 310/310 supported with fourteen abilities still
   instruction-less, and only Phase 4 caught them; each was a card that
   compiled, reported supported, and did nothing when activated. A card is supported when *any* of its
   lines is, so a set can read 85/85 with three cards doing less than they
   print — Antiquities did, for thirty rounds. Take the split a grammar size
   guard asks for when it fires, too: the family boundary is easiest to see
   while the work that crossed the line is still in hand.
5. Write the round's narrative — what it bought, what it cost, what it
   exposed — in the commit message that lands it, **not** in ROADMAP.md. The
   roadmap carries only its live sections (an open item, a refusal, an idiom,
   a row in "Where the sets landed"); a journal written there is culled every
   few sets, and the fourth cull removed 5,300 lines of it. Numbers live in
   those sections, not here.

## Phase 4 — Promotion gate

**Entry:** every card supported. **Exit:** one promotion commit, every gate
green, the trackers agreeing the set ships.

**Make the manifest move a textual edit, not a json round-trip.** `json.dumps`
re-escapes the em dashes in the role descriptions, which trips
`test_registration_preserves_everything_else_byte_for_byte` — a second failure
on top of whatever the rehearsal is really telling you. Cut the entry's block
out of `measured` and paste it into `sets` at the release-ordered position.

**Rehearse a deliberately *wrong* insert before trusting the order guard.**
An all-new set's position is invisible to
`test_appending_a_set_never_changes_an_existing_original_printing` — it shares
no oracle_id, so no card's origin moves from any position and the prefix
comparison is green wherever the entry sits. That has now been FEM's, HML's and
ALL's blind spot — **and Mirage proved it is not only an all-new set's
problem.** MIR shares 22 cards with earlier sets, so it is not all-new, and the
prefix guard *still* could not see the wrong insert: appending a set moves no
**existing** card's origin, which is the only thing that comparison tests. What
moves is the new set's own card. Volcanic Geyser is in MIR and M21 and nowhere
earlier, so appended after M21 its `original_printing` reads `m21` and every
guard stays green. Rehearse the wrong insert at every promotion, all-new or
not. `test_the_shipped_sets_are_in_printing_order` is the one that
can fire; append the entry at the wrong end once and watch it, which costs a
minute and converts an assumption into an observation.

**Make the wrong insert with the same textual move as the right one.**
Nemesis' rehearsal was hand-spliced and the splice left a stray comma line, so
`test_registration_preserves_everything_else_byte_for_byte` fired beside the
order guard — a second red that was the rehearsal's own formatting rather than
anything the rehearsal was asking. One move script with a "wrong end" switch
makes the order guard the only thing that can fire, which is the observation the
rehearsal exists to make.

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

**A reader of a card's lines that does not start from `expand_ability_lines`
is reading a different card**, and the promotion gate is where that collects.
CLAUDE.md names three such readers; HML found a fourth nobody had listed —
`tests/rules/test_aura_support.py` split raw `oracle_text`, so Orcish Mine's
conjoined trigger, which that rewrite splits into the two triggers the claim
table implements, reported as implemented by nothing. The card worked. **When a
round adds a rewrite to `expand_ability_lines`, grep for every reader of a
card's lines before the rehearsal** — a new rewrite is exactly what turns a
long-green guard red on a card that is fine.

**Read the guards themselves as suspects.** Four second-copies-of-one-fact came
out of this rehearsal and three were *inside* guards written to catch exactly
that, each inventing a disagreement it then reported. A guard that re-spells
the thing it checks is the most expensive kind, because its failures look like
real findings.

**Urza's Legacy's rehearsal is the cleanest instance of the split and worth
copying as a procedure.** Five guards went red: three were ratchets (accepting is
the review) and the other two were **exactly one of each kind**. Thran Weaponry
was real — "All creatures get +2/+2 **for as long as this artifact remains
tapped**" dropped its duration in the lowering, so the payload fell back to end
of turn and the buff both outlived the artifact untapping *and* died at the
cleanup step of a card whose other printed line exists to keep it tapped across
turns. Aura Flux was the guard: `test_every_lord_shaped_line_in_the_pool_derives`
finds candidates with a substring and then asked only the lord-buff table, so it
reported a disagreement it had invented about a card whose subject is
enchantments. **Run the card.** Neither could be told from the other by reading,
and driving each took a minute.

**And the rule cuts the other way, which UDS is the instance of.** Thran Golem
— "As long as this creature is enchanted, it gets +2/+2 and has flying, first
strike, and trample" — read 4/5 with no keywords off **both** the engine and the
wire, which looks exactly like the set's headline mechanic being dropped on the
client. It was the probe: nothing in it had run a state-based-action check, and
`check_state_based_actions` is what recomputes a conditional static. A real game
runs one constantly. **A card that looks broken from outside a game is not a
finding until it is driven inside one**, and the cost of skipping that is a
retrospective naming a defect that never existed.

**And expect that to stop being true once the guards are fixed.** Weatherlight's
rehearsal turned seven guards red and **every one was a real finding** — the
first promotion in this project where none of them was the guard.

**6ED is the other end of that: three guards red and every one a ratchet.** No
real finding at all, on a set with two new cards — and the two proxy guards that
fired at 4ED and at Ice Age, for a reprint set and for an emptied `measured`
role, both stayed green because each had been rewritten to assert its invariant
rather than a symptom. That is the accumulated fixes working, and it is the
reason to keep ingesting a reprint-shaped set through the full phase rather than
short-cutting it: the rehearsal is cheap precisely when it finds nothing, and
the two occasions it found something were both occasions nobody expected. Ten effect
labels falling through to the grammar-family default, two divided cards wanting
review into the AI's inventory, and a deletion probe whose five non-new findings
each turned out to be a word the payload provably carried. That is what the
accumulated fixes look like from the far side, and it is a reason to read each
finding on its merits rather than to open with "which guard is stale this time".

Mirage's instance is the sharpest so far and the cheapest to check for: the
activation-clause census called its reader **without the card's name**, so a
card naming itself inside its own restriction (CR 201.4) never had the
self-reference collapsed, and Hakim, Loreweaver's fully-enforced clause was
reported unenforceable. **When a pool-wide census disagrees with a card, run the
card first** — the enforcement path and the census must be handed the same
arguments, and a census that takes fewer of them is reading a different
sentence.

**Urza's Destiny paid that twice in one set, once at the gate and once inside a
round, so the rule is now: a census gets the same probe a refusal site does.**
A promotion-gate finding sized a dropped rider at "40 supported cards, none
carrying the exclusion" — from a probe that walked `ObjectFilter` and never
looked at the neighbouring `TargetSpec`, where the word had been recorded for
sets, and from grepping the compiled payload for the **AST field name** rather
than the payload key that is actually written. The real number was three. A
wave-2 census had the same shape one level worse: it called
`activate_permanent_ability`, which settles the stack itself, so it examined
**zero** announcements and **passed on the broken engine**. Both were caught by
re-deriving rather than by reading. Two habits follow — spell the key you grep
for out of the code that reads it, never out of the AST; and make a sweep assert
a floor on how much it measured, because a sweep that measured nothing looks
exactly like a sweep that found nothing.

**A guard that checks a proxy needs the proxy's availability asserted too**, and
a reprint set is what collects on that. Two fired at 4ED. One proved
`load_catalog()` ignores a measured set by finding a card name only the measured
set has — an assertion an all-reprint set cannot supply — and it passed *because
its author had written the self-check*: "shares every card name with the shipped
pool, so this test cannot tell the two apart — pick a different assertion". Copy
that habit. The other did not have it: the printing-order guard checks the
consequence (no card's origin moves), which a set whose every card already has
an earlier printing satisfies from *any* position, so the whole suite stayed
green with 4ED four places out of order and nothing said so. The fix in both
cases was to assert the invariant rather than a symptom of it — printings rather
than names, `released` dates rather than origins.

**Ice Age collected on it a third time, and this one fires on every promotion
from here.** A guard proved `parse_coverage.py` reads *measured* sets by
looking for a card that is not shipped — and promoting the only measured set
empties that role, which is a legitimate state (it was empty before the ingest
and is empty again after). The guard read "the instrument stopped watching"
when the truth was "there is nothing to watch". Assert the invariant —
`CARD_PATHS` is built over both manifest roles — which is checkable whatever
the roles contain, and let the per-card assertions range over an empty set.

**Sweep what the target pickers *offer*, not just what the compiler accepts** —
**and run it at Phase 1, where it is a work-list entry rather than a
promotion-gate finding** (Phase 1 step 4 now says so; HML moved it and it paid
on the day of the ingest). Re-run it here anyway, because promotion is what puts
the set in front of the client.
This step has no guard behind it and it found three defects Ice
Age's every other instrument was blind to, because all three cards compile
supported, carry no hollow line and claim every printed sentence. Two shipped
Auras were **uncastable in the app** — their `Enchant <noun>` clauses derived
`kind: "none"`, which is the exact value the client tests to decide whether to
ask for a target, so it sent a bare cast and the engine refused it. And a
creature sacrificed the *opponent's* first permanent instead of itself, because
resolving a bound subject that named nothing falls through to a battlefield
scan over `context.target`. For every supported card ask: does the picker offer
what the printed line says, and does an unchosen target fall back to the right
object? Both answers are behavioural; neither is visible from a compiled
program.

**And expect the trackers' aggregates to move on membership alone.** Promoting
4ED raised `GRAMMAR_COVERAGE.md`'s All row from 85.2% to 85.7% parsed with no
production touched, because that row is printing-weighted; `HOOK_RELIANCE.md`'s
is deduped and did not move at all. Neither is a bug and the ratchets are
re-accepted at every promotion anyway — the trap is reading the diff as
progress. Ask what changed in the *membership* before crediting the parser.

**Rehearse early, in a throwaway worktree, while the last wave runs.** Invasion
moved its entry to `sets` twice before the real promotion — once with twelve
cards unsupported, once with one — in `git worktree add` trees that were
deleted afterwards. The first run separated the thirteen red guards into the
state of the work, the ratchets, and five findings that could be worked in
parallel (one was the integrator's, one went to a wave-2 group by message);
the real promotion then had only its own delta to read. It costs one suite.

**Planeshift's first rehearsal ran with one card unsupported and a wave in
flight, and sorted the way Urza's Legacy's did: the guard, the guard, and an
inventory.** A static-line guard named a working card's line as implemented
nowhere - the **fourth** time it has done that, each time because it keeps its
own list of which derivation tables exist; it now also asks the grammar's
`registry_for_line`, which a table has to join for its line to parse at all.
An activation-targeting guard read "of the color of your choice" as a target.
And three missing effect-label rows turned out to be a small wire defect: two
entry triggers reaching the client without the `triggered_` prefix. Each new
arm was **measured before it was trusted** - over the shipped pool plus the
set, how many lines does it newly excuse? - and each excused exactly one. That
is the test for a guard fix: an arm that excuses forty is a new hole. The
second rehearsal, a wave later, turned red only the four ratchets.

**A new layout makes guards blind, not red.** A split card's whole-card
program is supported and has no instructions, so every guard and instrument
whose population is "each card, compiled" walks past both halves and reports
the card clean. About 55 test files and one script were reading it that way,
and a grep for `compile_card_oracle(` in a catalog loop under-counted by half
(the rest scan `oracle_text`). What found them was a scratch pytest plugin that
promoted the measured set in memory and recorded every site handed a
multi-face card whole; what holds them is `tests/engine/test_face_blind_guards.py`.
**The next layout owes the same census before its promotion**, and it is a
group's work, not a rehearsal finding.

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
   of `CARD_VERIFICATION.md`). A reprint set adds none: the tracker is keyed to
   the deduped catalog, so its cards arrive carrying whatever result they
   already had, and this step is *derivably* empty rather than skipped.
2. Smoke the set where a player meets it: the web app serves it, its cards
   are deckable, one human-vs-AI pass via the `run-magic` skill. **This step has
   its own failure class and Tempest found it: a display list nothing derives.**
   `web/serialization._DISPLAY_KEYWORDS` is hand-ordered, and Soltari Priest went
   onto a real battlefield reporting only its protection — the shadow deciding
   whether it could block or be blocked was enforced by the engine and never sent
   to the client, on all 25 of the set's shadow creatures. Phasing had been
   missing the same way since Mirage. **No engine instrument can see this**: the
   card compiles, claims every sentence, has no hollow line and plays correctly.
   Read what the *wire* carries for one card of the set's headline mechanic, not
   only what the engine computes.

   **Urza's Legacy found the fourth site and it is a new shape of the same
   class.** The three before it read a printed **type line** where a CR 613
   accessor was needed, so a grep for `card.type_line` would have found them all.
   This one reads a real accessor whose **narrower sibling** answers a strictly
   smaller question: `_effective_keywords` asked `_protection_colors`, the
   deliberate colour slice of `_protection_qualities`, which was right for as
   long as every protection in the pool was from a colour. Urza's Legacy printed
   two from a card type and the wire went silent about both — Yavimaya Scion,
   whose *entire* printed text is "Protection from artifacts", reached the client
   carrying **no badge at all** while the engine had the shield right at every
   seam it owns. Nothing greppable would have found it; driving one card of the
   set's new mechanic and reading the payload did.

   **Planeshift found the fifth site, and it is not about what the wire carries
   but about whether the client can answer it.** Verifying that an entry choice
   reached the payload, a group drove Runed Halo in a browser and could not get
   past its prompt: the client rendered an `enter_choice` only when it named an
   opponent, so for a colour alone, a card name, a creature type or a land type
   the panel read "Main Phase" while the server refused every action.
   Twenty-eight shipped cards had soft-locked a human seat for as long as they
   shipped, and three of the set's own would have at promotion. Every test of
   those cards answers the prompt through the engine. **Drive one card per
   prompt kind the set arms, in the browser, as a human seat** - and keep the
   test that came out of it: enter every chooser in the pool under an
   interactive seat and require the client's own code to read each question.

   **And read the payload while the prompt is still open.** Doing exactly
   that at the promotion - Voice of All's colour prompt on the screen - showed
   the wave's new `entry_choices` field already saying "Chosen color: white",
   to both seats. The entry state stamps a provisional default before it arms
   the prompt, and a field derived from a record is derived from whatever the
   engine has parked there. A UI test had pinned it as intended ("the default
   is stamped as it enters and is already visible"), and every engine test of
   the field entered its permanent at a seat nobody asks, where the default
   *is* the choice. Ask of a new wire field not only "is the answer there
   afterwards?" but "what is there before?" - and when a test's comment
   explains why a surprising value is fine, read it as a finding first.

   **For a reprint set this step is the only one that shows what promotion
   bought**, and
   what it buys is the set as a deckbuilding constraint: the deck editor's set
   filter gains the code, and every card under it renders that set's own art.
   Check the filter's count against the census, not just that the option exists.
3. `scripts/simulate_ai_games.py --set <CODE>` — the set plays itself. Each
   seat gets a random limited deck built from the set under test (CR 100.2b:
   that product plus basic lands), so this is a real exercise of the new cards
   rather than a run of Alpha's. **Run it as part of the promotion**, not only
   as a determinism check: over eight sets it found five defects nothing else
   had, four of them AI gates the engine refuses and one a card-deleting bug
   in the engine. A seeded run is byte-identical unless a fix legitimately
   changed AI-visible behaviour, in which case the change is named in the
   retrospective; `--all` across the promotion commit is the comparison that
   catches whether promotion itself changed anything.

   Read two numbers besides the issue list. **Interactions** must be non-zero —
   the script now fails when a run casts nothing, because "no illegal
   interactions" over games where nobody could pay for anything is a true
   statement about nothing. And **declined casts** should be zero: a cast the
   engine refuses costs nothing and breaks no rule, but the AI re-proposes the
   same card every turn, so a seat holding one does nothing for the rest of the
   game. Neither number existed while the simulator played one fixed decklist.

   **A zero in the combat counts is a question for the pre-set commit, not a
   finding.** At Nemesis' close the seeded Alpha run declared **0 blockers**
   against 59 attackers, right after a wave that had rewritten the AI's target
   choice. The same run at the commit before W2G4, and at the commit before the
   set, read the same 0 — it is what those seeded Alpha games do, not what the
   wave did. One extra run against a throwaway `git worktree add <dir> <rev>`
   settles it; remove the worktree from the main checkout, never from inside
   it, or Windows holds the directory open.

## Phase 6 — Retrospective and playbook update

**Entry:** Phases 4–5 done (or the session is ending mid-set — a partial
retrospective beats none). **Exit:** *this file contains no instruction the
set's execution proved wrong.*

1. Update ROADMAP.md's live sections: the set's row in "Where the sets
   landed", the pool numbers, any open item the set found or drained, any
   idiom it earned. No journal entry — the narrative is in the set's commits.
   Numbers go there, never here.
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
