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
free.** This is the highest-leverage instruction in the whole process. Ice Age
declined ten cards across three waves, every one with its missing pieces
enumerated individually rather than as "too complex" — and other groups then
built those pieces as a side effect of unrelated work. Chaos Moon's parity
condition was built by *Chaos Lord's* group; Winter's Chill's cast-time X
plumbing by Spoils of War's. All ten eventually landed. **State in each brief
which pieces other groups have already finished**, or the wave rebuilds them.

**Ask every group what the brief got wrong, and expect a third of it to be.**
Every report across four waves corrected roughly a third of its own brief, and
that section was consistently the most valuable part. The corrections were not
quibbles: one brief called a card "the hardest in the set" when it was the
cheapest, another scoped a subsystem migration that turned out to be the wrong
file entirely, and a third counted 89 call sites for a change that touched
seven functions. **A refusal site is a work-list entry, not a diagnosis**, and
an inherited estimate is a lead to correct rather than a fact to trust.

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

   **First confirm the suite actually loaded the new set.** A green run over a
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
5. **Ask how many of the set's cards are new to the pool**, before planning any
   round. Every phase after this one is written for a set that brings cards,
   and a reprint set brings printings: 4ED's 378 entries were 368 unique cards
   and *all* of them were already shipped, so the census read 368/368 supported
   at ingest and Phases 2 and 3 had no work in them at all. Diff the ingested
   file's `oracle_id`s against the shipped pool — one comparison, and it decides
   whether this is a set you implement or a set you promote. Do not read a
   100%-supported census as an anticlimax and skip the rest: the ingest still
   pays, and where it pays is Phase 4. Ten such sets are still ahead (ROADMAP's
   header names them), so this is a shape, not a curiosity.

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
   reading the diff it blesses. **And the exit is three numbers, not one.**
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
5. Append the round's narrative to the set's ROADMAP.md entry as you go —
   what the round bought, what it cost, what it exposed. Numbers live there,
   not here.

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

Mirage's instance is the sharpest so far and the cheapest to check for: the
activation-clause census called its reader **without the card's name**, so a
card naming itself inside its own restriction (CR 201.4) never had the
self-reference collapsed, and Hakim, Loreweaver's fully-enforced clause was
reported unenforceable. **When a pool-wide census disagrees with a card, run the
card first** — the enforcement path and the census must be handed the same
arguments, and a census that takes fewer of them is reading a different
sentence.

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
   are deckable, one human-vs-AI pass via the `run-magic` skill. **For a
   reprint set this is the only step that shows what promotion bought**, and
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
