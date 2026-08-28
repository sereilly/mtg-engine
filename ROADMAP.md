# Scaling Roadmap

Target: grow the card pool from **1,162** unique cards (LEA/LEB/2ED/ARN/ATQ/
3ED/LEG/DRK/4ED/M21, all shipped and all supported) to the full release line —
**137 sets, 33,594 printings, 26,113 unique cards** per `set_progress.json`.
Ten sets, and 4ED did not move the card count: it is a pure reprint set, so it
bought printings rather than cards. **That shape recurs and is worth planning
for** — `set_progress.json` records 13 sets in the release line with zero new
cards, and ten are still ahead: the foreign-language base sets (FBB, SUM, 4BB),
the rest of the core-set line (5ED through 10E), and Timeshifted. Each of those
promotes roughly the way 4ED did, so their cost is an ingest and a rehearsal
rather than a set of rounds. Sequence them after the sets they reprint from,
not before, or they arrive carrying cards nothing supports and the shape is
lost.

**Read this before parser or card-data work. It is the standing brief for the
next set, and nothing else.** Every claim below is either a rule the next round
must not break, a piece of work nobody has done, or a lesson that cost a round
to learn. It is deliberately *not* a journal: the round-by-round narrative —
the founding audit, the parser migration (finished: `engine/parsing/` is
deleted and `engine/grammar/` is the only parser), M21's 140 rounds,
Antiquities' 30, Legends' 36 and its promotion — lives in git history, at and
before commit `ee28617`. Read a round there when you need the reasoning behind
one of these bullets; do not add a new round here.

The process a set follows, phase by phase, is `SET_PLAYBOOK.md`. Numbers go
here, process goes there, and neither repeats the other.

**Why the journal was culled.** It reached 2,700 lines, of which 2,350 were
narrative that no longer changed anyone's decisions — and a file nobody reads
to the end is a file whose *live* items go unread with the dead ones. The parts
that were still doing work are all below.

---

## Standing invariants

Anything that weakens these is a regression regardless of what it enables:

1. **No silent wrongness.** A card may fail loudly as unsupported with a
   reason; it may never resolve as something other than what it says.
2. **The suite stays fast.** **9,117 tests**, CI budget **240s**, CI-measured
   baseline **110s** (`ci.yml`). The budget catches a step change; the
   baseline is what catches creep, and it is the number to keep honest.
   Raising the budget is a decision, not maintenance — it has been raised three
   times on purpose (35 → 60 ahead of a set ingestion, so the next set's tests
   had somewhere to land; 60 → 120 because GitHub's runners take the same suite
   longer than a local one, and a budget tuned to local timings failed on the
   runner with nothing wrong; 120 → 240 on the measurement below). The baseline
   has only ever moved as a *record* of growth: 9 → 17 → 23 → 35 → 40 → 110,
   proportional every time except the last, which was a **unit** change.

   **The 40s baseline does not reproduce here, and that is an open question.**
   Three consecutive local runs at the cull measured 86s, 88s, 87s — 72% of the
   CI budget, and past the point where `ci.yml` emits its creep warning. It is
   not this session's changes: disabling the new cast-time target gate and
   re-timing gives the same 87s. Two explanations remain and they have opposite
   fixes — the suite has crept (it grew from ~6,845 tests to 8,682, +27%, while
   the time roughly doubled), or this machine is slower than the one that
   recorded 40s. One timed run on the machine that set the baseline settles it.
   Do not "fix" it by editing the baseline; that is the one move that destroys
   the evidence.

   **After The Dark the same machine measures 78s, 87s, 78s at 9,110 tests** —
   +5% tests for no change in wall time, which is evidence *against* the creep
   explanation and for the slower-machine one.

   **Settled at 4ED's Phase 0 by reading three real runs.** The budget step
   measured 60s at run 7 (2026-08-20, pre-Legends), then 106s and 112s at runs
   11 and 12 (2026-08-27, 9,110 tests). So the answer to "creep or slower
   machine" is *neither*: **the ratio was comparing two machines.** `BASELINE`
   was recorded from a local run and compared against `ELAPSED`, which the step
   measures on the runner — the multiplier was never in the arithmetic at all,
   it was the arithmetic's missing term. The real multiplier against ~82s local
   is ~1.3x, not the 2–3x the 120 was sized on, and 112 of 120 is 93% of budget
   with a set ingest about to add several hundred tests. Both numbers were
   therefore wrong in opposite directions: `BASELINE` is now a runner-measured
   110s so the creep warning compares like with like, and `BUDGET` is 240s,
   roughly 2x it. Local timings are no longer an input to this gate; the way to
   move either number is to read the step's own output across several runs.

3. **Determinism.** A given seed reproduces a run exactly. Parsing and lowering
   are pure functions of card text.
4. **Ratchets only tighten.** Coverage floors, probe baselines, and accepted-diff
   lists shrink or hold — never grow without review. "Tighten" is the
   invariant, not "shrink": `hook_reliance_ratchet.json` holds *ceilings*, so
   tightening moves it down while `grammar_ratchet.json` tightens by moving up.
   The pair is deliberate — one guards the general reader keeping ground, the
   other guards the special-case readers not taking any — and a ceiling needs
   its measurement asserted, because unlike a floor it passes when it breaks.
5. **No card name decides behaviour outside `card_hooks.py`** — anywhere under
   `engine/`, heuristics and AI code included. The rule is about *dispatch*, not
   mention: a name in a log line, a prompt label or a fixture decklist is data;
   a name in an `if` is a claim, and `tests/engine/test_card_name_reads.py`
   enforces exactly that shape. "Only one card does this" is a claim about the
   *pool*, and it expires without anyone editing the comment — so before a name
   goes anywhere else, give an invented card the same printed text and check
   that it behaves. A name-keyed dispatch and a CR rule written as a card
   special case grep identically and have opposite fixes.

   Two things this covers that the earlier wording did not, both found by
   writing the guard rather than by reading the rule. **Heuristics are in
   scope.** A weight is tuning and stays tuning, but *which cards a weight
   reaches* is a claim about the pool and decays exactly like a parse rule —
   `ai_policy` named eight cards and aimed four unnamed removal spells at its own
   board. Derive the reach (`engine/ai_valuation.py`) and keep the weight.
   **Test oracles are out of scope, with their reason measured.**
   `ai_simulator._assert_expected` asserts a card did what the *printed* card
   says; deriving that from the compiled program makes it a tautology, and the
   only exemptions that stay are ones where the tautology has actually been
   demonstrated. An acknowledgement carries the measurement, not an opinion.

---

## Carried forward

The parts of a round that are about the *next* card rather than about the round
that wrote them. Everything here was established by a round now in git history;
the round number is given so the reasoning can be read in full — plain numbers
are the M21-era rounds, `ATQ n` is Antiquities', `LEG n` is Legends'.

### How a round is chosen

Sort the unsupported cards by **first failing clause** — `compile_line` names
the exact refusal, which beats reading the aggregate report buckets — then rank
by cards-per-change. Round 37 found **59 of 87 remaining cards blocked by
exactly one line**, at which point the question stops being "what is the biggest
mechanism" and becomes "which single line is cheapest per card". A block that
needs two rounds is worth splitting only if neither half ships a card alone
(rounds 7 + 8 did exactly that, one card each plus one together).

**Re-measure a block's priority before acting on it, including the ones below.**
The legend rule sat open for a year and a half arguing its own urgency from
"all eleven legendary creatures in the pool are M21" — true when written, and
stale the day Legends shipped, which took the pool to 91 legendary permanents.
Nothing failed, because a card count written in prose is a claim about the pool
with no test behind it, and it decayed *upward*: the block got eight times more
reachable while its entry went on quoting eleven cards. It is the same decay as
a `# only one card does this` comment, and it is why every bullet here that
carries a number should be re-run before it is cited.

### Open blocks, still standing

- **`card.name` has no ratchet.** The legend rule read the printed name for a
  year and a half (fixed post-LEG; `perm.effective_card.name` and
  `printed_supertypes(perm.effective_card.type_line)` now, the idiom
  `engine/landwalk.py` was already using). The guard that would have caught it
  does not exist: `tests/engine/test_layer_reads.py` ratchets `card.type_line`,
  `card.colors`, `card.oracle_text` and `card.keywords`, and `card.name` is not
  among them because hundreds of reads are log lines, prompt labels and fixture
  decklists. It needs a census that separates a *dispatch* on the name from a
  *mention* of it — the same distinction `test_card_name_reads.py` already
  draws for `engine/`, applied to one field.
- **An AI seat never casts its commander** (the Commander variant's known
  deferral). `ai_policy.py` and `ai_valuation.py` read the hand and the
  battlefield; nothing reads `command_zone`, so an AI commander sits there for
  the whole game and Commander-vs-AI is a handicap match. The CR 903.9 zone
  prompt already defaults safely for AI seats — this is a missing *policy*, not
  a rules gap. Wants the same shape as every other AI read: derived from the
  compiled program in `ai_valuation.py`, weight tuning in `ai_policy.py`.

### Recorded, measured, and not yet fixed

- **The Nine Lives class — partial implementation reported as full.** A card is
  supported when **any** line is, so a card can report supported while other
  lines produce nothing. The census this bullet asked for exists now:
  `scripts/support_report.py --hollow-lines` names every supported card whose
  compiled program carries an ability with no instruction behind it. Its first
  run held **four cards** (Creature Bond, Howling Mine, Paralyze, Capture
  Sphere), each leaning on a registry the compiler cannot see — and each
  verified *live* by a per-card test in `tests/sets/`. LEG round 9 added
  Kudzu's "when enchanted land becomes tapped", which reached no trigger table
  before that round, so the ability was instruction-less and invisible to the
  census at the same time; its registry (`ENCHANTED_LAND_TAPPED_FOR_MANA`)
  implements the line only from the mana-tap path, which is the half of that
  round's finding it did not close.

  **The census reads three today** — Creature Bond, Howling Mine, Kudzu.
  Paralyze and Capture Sphere left it during Legends, when the machinery under
  them grew a real instruction; nothing about them was individually rescued, and
  the number is the census's to report rather than this bullet's to carry. Rock
  Hydra's automatic counter shield — the
  one the bullet below used to call "the Nine Lives class hiding behind a
  verified-sounding acknowledgement" — is implemented
  (`prevention.py:_remove_counter_per_damage`) rather than acknowledged, and
  its `IMPLEMENTED_ELSEWHERE` entry is gone. What the census cannot see is a
  *registry that claims a line and does less than it says*: that class is only
  findable the Rock Hydra way, by giving the behaviour a game. **The census is a
  Phase 3 exit criterion, not only a Phase 2 reading** — Antiquities read 85/85
  supported for thirty rounds with three cards in it (ATQ 30), and reaching zero
  took a round of its own.
- **The verification tracker holds 708 unrecorded cards** of 1,162 — M21,
  Antiquities, Legends and The Dark, all four promoted before their in-game pass
  (SET_PLAYBOOK Phase 5 owns that delta and promotion deliberately does not
  gate on it); 443 pass (383 checked in-game, 60 auto-passed), two are recorded
  **failing**, and more read `equivalent` off a passing peer. Four sets have
  now been promoted ahead of Phase 5 and the backlog has grown with each, which
  is the decision working as stated rather than drifting — but the derived
  `equivalent` results across 35 behaviour classes are still the lever nobody
  has pulled, and this is now the largest standing debt in the repo. **Candelabra
  of Tawnos is one of the two failures** and has been since before The Dark
  began: it resolves without asking how many lands to untap. A headless sweep is not a manual in-game pass: `card_verification.json`
  records what a human checked, including a **failure**, which is a bug report
  with a card name on it. A stale generated number does not read as stale, it
  reads as an answer — this bullet said "19 untested" for a week after M21
  shipped, which is why CI regenerates the tracker now and why
  `CARD_VERIFICATION.md`, not this line, is the number.

- **CR 608.2b is enforced for instants and sorceries only, and the rest is
  blocked on a different bug.** The rule ("if all its targets are now illegal,
  the spell or ability doesn't resolve") is one gate,
  `legality.illegal_targets_refusal`, asked once above the instructions;
  CR 601.2c's announcement half is its twin, `legality.cast_target_refusal`.
  Three parts of the rule are deliberately not asked, each with its own reason
  and each worth its own round:

  * **A triggered ability's targets.** The death sweep enqueues a dies-trigger
    *while the dying permanent is still listed*, so Blazing Effigy's "it deals
    3 damage to target creature" records the dying Effigy itself — a permanent
    CR 603.3d would never have offered — and resolution reaches the right
    creature only by falling back to the index. Asking 608.2b of that id
    counters an ability the engine **mis-targeted** and reports it as a
    rules-correct fizzle, burying the real bug under a rule. The fire sites
    have to choose targets after the permanent has left first.
  * **A spell whose target may be a player** ("any target", a divided one). A
    seat and a chosen player reach a stack item through the same
    `target_player_index`, so "every target is illegal" is not answerable:
    a Fireball split between a creature and its controller looks exactly like
    one aimed at the creature alone.
  * **An Aura, and a graveyard target.** An Aura whose enchant target has left
    enters attached to nothing and is binned by CR 704.5m one sweep later —
    the same destination by a different rule. A graveyard target already has a
    deliberate answer (clamp to the last surviving copy, because two copies of
    a card in one graveyard are literally one object). Both are decisions to
    change on purpose, not gaps to close on sight.
- **CR 508.5's second sentence is not implemented** — "if that creature is no
  longer attacking, the defending player it's referring to is the player that
  creature *was* attacking". `_prune_combat_state` clears `attacking` and
  `defending_player_index` together before rebuilding, so the memory is gone
  by the time anything could ask. Nothing in the pool asks after removal from
  combat, so this is a gap with no card behind it — recorded rather than
  fixed, because a fix with no card to verify it is a guess (the same reason
  "a filter with no card behind it is untested by construction" sits below).

- **CR 305.7's ability-loss half does not exist.** "Nonbasic lands are
  Mountains" changes a land's *types* and its mana, and stops there. Verified in
  a game: with Blood Moon out, Mishra's Factory reads as a Mountain, produces
  {R} — and still carries all three of its activated abilities, animation
  included; City of Brass keeps its damage trigger. The rule says a land whose
  basic land types are set loses its old abilities and gains the mana ability
  for those types. `Permanent.effective_produced_mana` implements only the
  second half. This has applied to Evil Presence, Phantasmal Terrain, Conversion
  and Cyclopean Tomb the whole time; Blood Moon (The Dark) is the first card
  that makes it reachable on every nonbasic land at once, which is how it was
  found. The seam already exists — `global_statics.removes_abilities` is
  enforced in `mixins/stack/activation.py` for Titania's Song — so this wants
  the same refusal plus a layer-6 removal, keyed on the land's derived basic
  types differing from its printed ones. **A whole CR rule, one round.**
- **`ACTIVATED_LABELS["sequence"]` reports 54 shipped abilities as damage.**
  Verified by compiling the pool: every activated ability that lowers to a
  `sequence` takes the `activated_damage` bucket, which is right for Banshee and
  wrong for six Mana Batteries, Bottle of Suleiman, Ebony Horse, Ashnod's
  Transmogrant and four planeswalkers. The triggered side already fixed exactly
  this with a `triggered_sequence` label; the activated side never got the twin.
  Nothing crashes — it is the support report and `SimulationResult` describing a
  third of their damage bucket wrongly. Cheap, and its own round because
  re-bucketing 54 cards is a diff worth reading.
- **A land whose colour was swapped away gives the wrong colour, not
  colourless.** `tap_land_for_mana` ends its symbol choice with
  `mana_symbol = produced[0]` when the requested colour is no longer in
  `effective_produced_mana` — so a Quarum Trench Gnomes'd dual asked for its
  swapped colour yields *the other one* rather than the {C} the Gnomes grant. A
  basic Plains is right only because its list has one entry. Recorded from the
  code path rather than a game: arming the effect headlessly needs the activation
  API the web picker uses, and the fallback line is unambiguous. The fix is to
  map the chosen colour through the land's swaps instead of falling back to the
  first entry.
- **Two layer reads that disagree about the same land.**
  `_refresh_static_land_types` tests its *from* side against
  `effective_card.type_line` (layer 3) rather than `has_type` (layer 4), so
  Conversion cannot see a Mountain that Blood Moon made — two layer-4 effects
  CR 613.7 says should chain by timestamp. Documented in place, reachable now
  that Blood Moon ships.
- **Three smaller ones, each with no card behind it today.** `ObjectFilter.blocked`
  is parsed and `to_payload` never emits it, so "sacrifice a blocked creature"
  would lower to plain "a creature". `_perform_entry_state`'s "enters with N
  +0/+1 counters" branch writes `metadata["plus_0_1_counters"]`, a key nothing
  reads — `pt.pt_counter_key("+0/+1")` says `"+0/+1_counters"` — and assigns
  rather than accumulates. `prevention.source_has_type` answers "creature" for a
  creature *card on the stack*, so a shield reading "by creatures" would answer
  for a creature spell. None is reachable from the shipped pool, which is why
  each is recorded rather than fixed: a fix with no card to verify it is a guess.
- **`handlers/_common.py`'s `"triggering_spell"` mana value has CR 202.3b's
  gap** — it reads `card.cmc`, so an {X} spell's mana value on the stack is
  wrong. The same bug was fixed for Spell Blast and Mana Drain through
  `targeting.stack_object_mana_value`; this site cannot use it because the cast
  fire site records only the `CardDefinition`, not the stack item. Fixing it
  means giving that fire site the object.
- **`_offer_to_seat` moves `context.target` to the offered seat and deliberately
  not `context.caster`**, so a bare imperative inside "each player may …" would
  act on the controller's board while `_action_is_takeable` tested the offered
  player's. Inert today — Rebirth is the only other pool card with the shape and
  it names its seat in the payload, and Mind Bomb collapsed into a plain discard
  prompt. The reason is written beside the code; this entry exists so the next
  card printing the shape does not have to rediscover it.

### Deliberate refusals, with their reasons

Not gaps to close on sight — each was measured and left refusing. This list
used to be three times as long; the pre-set cleanup round before the next
ingest found nine of its entries implemented (Pursued Whale's target
narrowing and the {X} self-reductions in `cost_modifiers.py`, Enthralling
Hold in `target_restrictions.py`, Runed Halo in `named_protection.py`, Feat of
Resistance as `PROTECTION_FROM_CHOSEN_COLOR`, Demonic Embrace in
`cast_costs.py`, Crypt Lurker as `may → choose_one`, Faith's Fetters and
Feline Sovereign in `auras.py` / `lord_buffs.py`) and still listed as
refusing. A refusal recorded here is a claim about the code; re-verify it
against `compile_line` before citing it.

- ~~**El-Hajjâj's "you gain that much life"**~~ — *retired, LEG 10.* It was
  recorded here as "its fire site records the amount under a different key",
  which was a fact about a fire site and never about the rule. There is one
  announcement for every damage event now, so there is one key, and the words
  lower for El-Hajjâj, Spirit Link and Backfire alike. A refusal resting on
  where an event happens to be announced from expires the moment the
  announcement moves — which is the reason this list says to re-verify an
  entry against `compile_line` before citing it.
- **Hexproof stays colour-only**, because its targeting branch reads colour
  words alone.
- **A durationless doubling** (a continuous effect the layers would have to own)
  and **doubling toughness** (a different effect — consuming the noun without
  checking it is how one card's production quietly claims another's).
- **A filter with no card behind it is untested by construction** — round 43's
  sacrifice *trigger* is unnarrowed for that reason, even though the
  subject-group machinery could read a narrowing. Still standing for the
  trigger; the cost and effect halves stopped being covered by it in round 56,
  when two cards printed the narrowing.

### Idioms these rounds established

1. **A narrowed trigger condition lands on both sides of the pipeline.** The
   compiler takes a condition from `engine/oracle.py`'s regex table and the
   effect from the grammar, so a condition narrowed on one side only compiles
   the card **supported and firing on the wrong event** (rounds 7, 28, 54).
   Where a regex cannot describe the narrowing it only *delimits* the phrase — a
   named group ending in `_subject`, handed to `grammar.parse_subject_filter`,
   with a guard comparing the two over the whole pool (round 34). The same
   shape, for the same reason, wherever a *second* reader of one clause exists:
   round 56 applied it to an activation cost's "Sacrifice <noun phrase>", where
   the two readers drift towards a cost nobody pays.
2. **A restriction the dispatcher cannot test refuses at compile time.** An
   ignored restriction on a trigger is not a narrower card, it is a card firing
   on everything (`TESTABLE_SUBJECT_FILTER_KEYS`, round 34). Same rule for a
   search filter, a picker filter and a cost the charger cannot express.
   **And the question has to recurse as far as the filter nests.** A noun
   phrase can carry another noun phrase — "Auras attached to permanents you
   control" — and a set difference over the outer payload's keys answers
   "testable" for the nested one whatever it says. That is a gate and its
   dispatch reading two different things again, with the nesting hiding the
   difference; `untestable_filter_keys` recurses exactly where the matcher does
   (round 35).
3. **A fire site that enumerates instruction kinds cannot be complete** — it is
   only as complete as the last card that touched it. Onulet never gained a
   point of life across four shipped sets because its kind was not in a list
   (round 45). Fire every trigger of the shape; name genuine exceptions in a
   frozenset beside the loop.
4. **A condition can parse in both tables and have no dispatcher at all.** Four
   were found that way — `creature_attacks_or_blocks` (28),
   `creature_you_control_dies` (30), `you_gain_life` (33),
   `creature_becomes_blocked` (34). Check the dispatcher exists before believing
   a condition works.
5. **"Whenever X" goes on the one seam X passes through**, never a new fire
   site: `_draw_with_replacements` (draw), `Game._gain_life` (life gain),
   `Game.place_plus1_counters` (counters), `Game.sacrifice_permanent`
   (sacrifice), `_mark_damage_on_permanent` (damage),
   `_put_permanent_onto_battlefield` (enters). Where no seam exists, build it
   first: round 43 found thirteen sacrifices in three spellings, seven of which
   skipped ownership, tokens, replacements, Aura teardown, the death count and
   the dies-triggers.
6. **Last-known information (CR 603.10) is frozen at the fire site**, not read
   at resolution — a dead creature's counters (30), its power (31), its
   controller (32), the damage an event dealt (39). The measured exception is
   round 42: a *sacrificed source*'s P/T lives in `Permanent` metadata, which
   nothing off the battlefield touches, so it can be read at resolution. The
   longest gap between freezing and reading is Tawnos's Coffin's noted counters
   (ATQ 28) — a whole turn cycle, and what comes back is a new object (CR 400.7)
   with none of its own.
7. **A back-reference names its producer or refuses.** "That much" parses as
   `ThatMuch(None)`; lowering resolves it against `amount_from` (this
   resolution's scratchpad) or `amount_from_trigger` (the firing event's
   captured context), which are separate keys because reading either for the
   other yields a silent zero (round 33).
8. **Stated AI policies, not special cases**: the maximum for "up to N", the
   first printed mode, the costliest legal card in a reveal-and-choose,
   everything matching in an any-number search, and `default_sacrifice_pick`'s
   "keep the one whose death loses the game for last, then take the smallest". A
   card that should choose otherwise needs a valuation, not a branch.
9. **A picker's enumeration is a hint; the engine re-checks the answer.** A
   client offering a whole library or hand would otherwise turn "a creature card
   with mana value 6 or greater" into Demonic Tutor (round 11), or an
   additional cost into nothing (rounds 38, 50).
10. **A cost is not a target** (CR 601.2b vs 601.2c) — two announcements, two
    fields, and a card can have both (Dwarven Weaponsmith). A cost payment is
    also not targeted, so protection, shroud and hexproof have nothing to say
    about what may pay (round 52).
11. **An index is not an identity.** On the battlefield that is `permanent_id`;
    in a hand, where two copies are literally one object, resolve the named
    index **to a card** before anything leaves the zone (round 50).
12. **Gates are all-of.** A modal card with a dead mode, a planeswalker with one
    unreadable ability, an Aura whose effect line is unimplemented, a permanent
    whose lines are all markers — refused naming the clause, rather than
    resolving the readable part.
13. **Obey a size guard rather than raising it.** `parser.py` at 1,000 lines
    (round 31) and the per-set test files (round 33) were both split instead;
    the guard is the signal that a family stopped absorbing new work. Take the
    split *when it fires*: Antiquities' two (`nouns.py` → `references.py`,
    `statements.py` → `paragraphs.py`) each fell along a line the CR already
    draws — what a noun phrase describes against what it points at, a sentence
    against a paragraph — and that boundary is easiest to see while the work
    that crossed the line is still in hand.
14. **The same sentence about a different subject is the same table, asked with
    the subject rewritten.** Artifact Ward prints Argothian Pixies' combat
    restriction and Argothian Treefolk's damage shield about the creature it
    *enchants* (ATQ 22); Drafna's Restoration prints an ordinary graveyard
    return about a *chosen player's* pile (ATQ 27). Reuse costs a rewrite of the
    subject and nothing else — but it needs a gate naming the kinds a reader
    actually consults, or asking a table gets every row for free and claims
    lines nothing enforces.
15. **A card has every type its line names (CR 205.2).** `primary_type` picks
    one of them by the order of a list, and three readers asked it that way — a
    counter refused every artifact creature, a search could not find one, and
    only the graveyard reader was right (ATQ 25, 29). One
    `search_filters.card_has_type` now.
16. **A clause about a player says so in its payload.** The damage handler told
    a player from a permanent by looking for a permanent index on the resolution
    context — which in a `sequence` is the *previous* step's, so Detonate's
    "deals X damage to that artifact's controller" was aimed at the artifact it
    had just destroyed (ATQ 23). Inference from an absence is not a reading.
17. **A loop over a permanent's triggers must not stop at the first.** CR 603.3
    puts *every* ability that triggered on the stack; the upkeep step's `break`
    was correct until Tetravus printed two (ATQ 26). Same family as idiom 3, one
    control-flow keyword smaller.
18. **A guard whose control is a pool card stops controlling when the pool
    moves.** `test_no_hollow_support` proved "a land with *some* readable
    ability is not hollow" by asserting Mishra's Factory *had* an unread line —
    a fact about the pool, not about the guard, which would have started passing
    vacuously the day that line was implemented (ATQ 30). A fixture the test
    invents cannot go stale underneath it.
19. **A condition kind is a dispatcher's address, so spelling the subject into
    the kind gives one card its own fire site.** `enchanted_land_tapped` and
    `self_becomes_tapped` were CR 701.26a asked about two named subjects; each
    got a kind, and each kind then got a hand-written pass inside
    `tap_land_for_mana` instead of riding the tap seam beside the quantified
    spelling (LEG 9). One event is one kind and the subject is *payload* — the
    arrangement `permanent_becomes_tapped` already used for
    `tapped_subtype`/`tapped_controller`. The symptom is silent in the way this
    engine's worst bugs are: the seam emits, nothing listens for that name, and
    an emit nobody listens for reads exactly like an event that never happened.
20. **A pronoun names the object the sentence already named** — the same rule
    as idiom 7, one word smaller. "It" is the source only where the trigger's
    condition names nothing else, so it is resolved where both halves of the
    line are in hand rather than at the noun (LEG 9). It needs its own AST
    quantifier: a card naming *itself* mid-sentence parses to the same filter
    and means the opposite thing, and rewriting that would aim an Aura's effect
    at the permanent it enchants.
21. **A comment recording a gap is not a fire site that fires.**
    `_fire_combat_damage_to_player_triggers` said in its own docstring that
    El-Hajjâj should also fire on damage dealt to a creature and that "that path
    isn't wired up (a documented gap, not silent)" — and being documented is
    what kept it there for four sets (LEG 10). The distinction the note draws is
    real and the note is still not a dispatcher. When the gap is "this event has
    more than one announcement", the fix is the seam every one of them already
    passes through, and the tell is a *condition kind per fire site*: five kinds
    naming one event is five places to be announced from and five to be
    forgotten.

22. **A citation can name a rule that exists and still be wrong.**
    `scripts/rules_gaps.py` checks both halves of a stale citation it knows
    about — a rule number that does not exist, and a subrule letter that does
    not exist under a rule that does. Six sites in four modules cited **CR
    115.6** for "a card can be immune to spells and to abilities separately";
    115.6 is the zero-targets permission and says nothing of the kind, and
    every one of those citations passed both checks because the number is real
    and carries no letter. Nothing mechanical finds this third member of the
    class. It also polluted the gap ranking: 115.6 read as "cited by the
    engine" for six reasons unrelated to what it says.
23. **A derivation answers about the card; a gate needs the answer about this
    announcement.** `derive_cast_spec` reads a whole card, so the cast-time
    target gate had to decline three shapes before it stopped refusing legal
    casts: a **modal** spell (the spec is mode 0's, and the caster chose mode
    1 — Healing Salve), a **roles** spell (one spec per role plus a relation
    between them — Glyph of Delusion), and a **permanent** spell (the spec
    belongs to an ETB trigger that chooses its targets later, CR 603.3d —
    Niambi). Each was a legal cast being refused, which is strictly worse than
    the hole being gated. Ask what *this* object announced, and when the
    derivation cannot say, decline rather than guess.
24. **A test that records current behaviour as deliberate is an invitation.**
    `test_a_target_that_has_left_falls_back_to_the_old_index_behaviour` said in
    its own docstring that it was "deliberately not a fizzle … stated so a
    later change to it is a deliberate one", and CR 608.2b is that change. That
    docstring is the right shape for a behaviour nobody has decided yet: it
    fails loudly when the behaviour moves, and it tells whoever moves it that
    the old answer was a placeholder rather than a rule.

25. **Git resolves "both branches added a function" as two functions.** Not as a
    conflict — as a *shadow*, because Python takes the later definition
    silently while the earlier one still imports by name and never runs. The
    Dark's parallel round landed four in one merge and they failed four
    different ways: two harmless twins, one that dropped a guard
    (`_lower_reveal_hand`'s refusal of an unhandled player kind, so "each player
    reveals their hand" would have lowered to one player revealing), and one
    that replaced a production returning `Statement | None` with one that raised
    — right after the caller had been taught to expect None. Only the *shape* is
    common, which is why `test_no_module_defines_the_same_name_twice` asks the
    shape across the whole repo rather than any one symptom. A fifth was worse
    and is still not caught by it: `_parse_that_object` was defined in
    `phrases.py` **and** in `effects/board.py`, with board.py importing the
    first and shadowing it with the second, so two families read one phrase
    through two functions one edit apart. A cross-module shadow needs a
    different question than a within-module one.
26. **Carrying a dataclass field across a move is not carrying the branch.**
    When a merge presents "ours: nothing, theirs: the whole class" — because one
    side moved the class to a new module and the other added to it — the fields
    are the visible half. `ObjectFilter` had also grown a line in `to_payload`
    emitting `dealt_damage_this_turn`, and a field-only carry dropped it: the
    class compiled, the key vanished, and Giant Shark's trigger fired against an
    unhurt blocker. Diff the whole class, not its field list.
27. **A guard that names one of a table's return values ages with the table.**
    `test_static_line_support` asked `land_play_line(...) == "allowance"`. When
    the same table grew a `"prohibition"` answer, the guard reported Worms of
    the Earth as an unbacked static line while `_land_play_refusal` was refusing
    land plays perfectly well. Ask whether the table claims the line, not
    whether it claims it under the one name you happened to know — a guard that
    re-spells part of what it checks invents a disagreement and then reports it,
    which is the most expensive failure shape because it looks like a finding.
28. **A payload key means one thing across the engine.** Angry Mob's
    `dynamic_pt_count` used `otherwise` for a *number*; `handlers/control_flow.py`
    owns that key for the else-branch of a `may`, and every guard that walks a
    composed effect recurses into it expecting steps. The front-end-safety guard
    crashed trying to iterate a 2. The collision is invisible until two
    subsystems meet in one card.
29. **"Only this card does that" is a claim about the pool, even inside a
    guard's exemption list.** Preacher derives no activation prompt *correctly*
    — the opponent chooses the target at resolution and the activating seat
    never chooses at all — so the guard needed an exemption. Written as a name
    it would expire the day a second card printed "of an opponent's choice";
    written as "the compiled program has a `choose_permanent` whose chooser is
    another seat" it cannot. Same rule as `card_hooks.py`, applied to a test.

---

## The next set, measured rather than guessed

Sixteen candidates were ingested to a scratch directory and censused against the
live compiler before The Dark was chosen. Re-run the numbers before acting on
them — that is this file's standing rule — but the shape of the answer is worth
keeping, because it took a morning to produce and it will not have changed much.

**Fourth Edition is free, now, and should be taken next.** 368 cards, **zero**
outside the shipped pool and **zero** unsupported — verified against the pool as
it stands after this promotion, not projected. Every one of the 32 cards it held
that the pool lacked was a The Dark card, and all 11 of its unsupported ones
were among them. It costs an ingest, a manifest entry at index 8 and a Phase 4
rehearsal; it buys a completed set, 368 recorded printings and the reprint data
for every card it shares. There is no Phase 3 at all. Nothing else on the list
is close to that ratio, and the ratio only exists because The Dark went first.

**After that the leverage is gone and the sets are all long tails.** Every one
of the sixteen has a refusal backlog whose lines-per-distinct-sentence is
between 1.00 and 1.15 — one refused sentence per refused line, everywhere. The
generalise-first rule that carried Alpha through Revised has run out; Legends
was the warning and it is now the universal condition. Rank candidates by
unsupported-card count and by what machinery they force, not by hoping for a
production that clears thirty cards.

Ranked by new cards per unsupported card, after The Dark:

| Set | Cards | New to pool | New & unsupported | New per unit work |
| --- | --: | --: | --: | --: |
| 4ED | 368 | 0 | **0** | free |
| 6ED | 335 | ~200 | ~74 | 2.7 |
| M19 | 298 | 273 | 102 | 2.7 |
| 5ED | 434 | 147 | 66 | 2.2 |
| ORI | 268 | 251 | 108 | 2.3 |
| ICE | 373 | 346 | 195 | 1.8 |

**Ice Age is where the rules coverage is**, when card count stops being the
question. Its big rock is named in advance: **cumulative upkeep (CR 702.24)**,
30 of its own cards and 63 across the Ice Age block (ALL, MIR, VIS, WTH), of
which 61 are unsupported today. The engine already has both seams it needs — the
upkeep registry and the counter API — so it is one keyword plus one
registration for 61 cards. Nothing else in any candidate set comes close to that
ratio, and it is the only genuine subsystem any of them forces.

**Three structural gaps bound everything after Innistrad**, and the first is a
hard wall rather than a backlog. `card_loader.REQUIRED_FIELDS` demands a
top-level `mana_cost`, which a transform card does not have, so a
double-faced card raises `ValueError` on *load*. `_load_faces` populates
`CardDefinition.faces` and the only reader in the repo is `commander.py`'s
colour-identity derivation — the compiler has never seen a second face. That is
CR 709/710/712/714/715/720, 45 rules, none implemented; it already costs Origins
5 cards and M19 one. Second, keyword abilities stand at 27 of CR 702's 192.
Third, **alternative costs (CR 118.9) do not exist** — `cast_costs.py` implements
*additional* costs well, and "alternative cost" appears once in the engine, in a
comment — which blocks the buyback/flashback/evoke/madness family wholesale.

## Where the sets landed

The numbers a Phase 1 census is estimated against. Rounds are ROADMAP rounds,
not commits.

| Set | Cards | Supported at ingest | Rounds to 100% |
| --- | ---: | ---: | ---: |
| M21 | 285 | 58% | ~140 |
| ATQ | 85 | 56.5% | 30 |
| LEG | 310 | 32.9% | 36 |
| DRK | 119 | 47.9% | 12 groups, 3 waves |

Legends is the useful data point and the warning: the lowest starting coverage,
the largest card count, and the flattest ranking — after eight rounds, 113 of
its 135 remaining cards refused *exactly one line* and the largest group of
those shared only an opening phrase. It was designed before templating existed,
so the generalise-first rule runs out of general work earlier than in a modern
set. Its first census read 121/310 (39.0%) rather than the 32.9% recorded at
ingest, because the ingest round's own engine fixes moved it — Phase 1 says to
treat what the suite surfaces on a new set as yield, and that gap is the yield.

**Where the pool stands** (regenerate rather than trust these): 1,162 unique
cards over 9 sets, 100% supported. Grammar parses 85.2% of lines and executes
52.3% (`GRAMMAR_COVERAGE.md`). 6.4% of supported cards carry a name-keyed hook,
80 entries in 7 registries (`HOOK_RELIANCE.md`) — the number that decides
whether this architecture reaches 26,113 cards. 334 of 611 tracked CR rules
have a test (`RULES_PROGRESS.md`). 443 of 1,162 cards have a passing in-game
result (`CARD_VERIFICATION.md`).

The Dark is the first set where **every shipped set's parse rate went up with
it** — ARN 75.0 -> 75.9, 3ED 83.5 -> 84.1, LEA 81.7 -> 82.0 — because twelve
parallel groups all reached for general machinery under a brief that made a
name-keyed hook the last resort. The hooked share *fell* while a set was added,
which is the first time that has happened: 7.1% -> 6.4%, entry count flat at 80,
because Ebony Horse's hook was retired when Maze of Ith turned out to print the
identical sentence.

## Size watch

The 1,000-line cap on `engine/grammar/` modules is a scheduling signal, not
style: it fires when a family stops absorbing new work, and the split is
cheapest while the work that crossed the line is still in hand (idiom 13).
What is close, at the cull:

| Module | Lines |
| --- | ---: |
| `effects/damage.py` | 996 |
| `lowering/_common.py` | 994 |
| `lowering/zones.py` | 992 |
| `lowering/damage.py` | 981 |
| `lower.py` | 971 |

Nothing is at the cap. The Dark took **six** splits in one set, which is more
than the previous four sets combined, and every one fell along a line the CR or
the call graph had already drawn: `ast/_core.py` into `_primitives` +
`_references` (`ObjectFilter` alone was 428 lines) and again into `costs`;
`effects/cards.py` into `library`; `effects/board.py` into `control_changes`;
`lowering/board.py` into `control_changes`; `lowering/damage.py` into
`redirection`, `fighting` and `prevention`. Reusing the other side's family name
each time is what kept the halves mirrored rather than forking.

Two of those splits were invented **twice, independently**, by parallel branches
that each hit the cap on the same module and cut it in the same place. Two
agents reaching the same boundary with no knowledge of each other is the
strongest evidence a split is structural rather than a matter of taste.
