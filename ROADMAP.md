# Scaling Roadmap

Target: grow the card pool from **1,725** unique cards (LEA/LEB/2ED/ARN/ATQ/
3ED/LEG/DRK/FEM/4ED/ICE/HML/5ED/M21, all shipped and all supported) to the full
release line — **137 sets, 33,594 printings, 26,113 unique cards** per
`set_progress.json`. Fourteen sets, and the recent arrivals span the whole
range: 4ED and 5ED are pure reprint sets that bought printings rather than
cards, Ice
Age brought 346 new ones (the largest addition since Alpha), Fallen Empires
brought 102 of which every single one was new — the smallest work set so far,
and the first inserted into the middle of the printing order rather than
appended — and Homelands repeated that all-new shape at 115 of 115, inserted
at index 11 between Ice Age and M21.

**The reprint shape recurs and is worth planning for** — `set_progress.json`
records 13 sets in the release line with zero new cards, and nine are still
ahead: the foreign-language base sets (FBB, SUM, 4BB), the rest of the core-set
line (6ED through 10E), and Timeshifted. Each promotes roughly the way 4ED and
5ED did, so their cost is an ingest and a rehearsal rather than a set of
rounds. Sequence
them after the sets they reprint from, not before, or they arrive carrying cards
nothing supports and the shape is lost.

**Read this before parser or card-data work. It is the standing brief for the
next set, and nothing else.** Every claim below is either a rule the next round
must not break, a piece of work nobody has done, or a lesson that cost a round
to learn. It is deliberately *not* a journal: the round-by-round narrative —
the founding audit, the parser migration (finished: `engine/parsing/` is
deleted and `engine/grammar/` is the only parser), M21's 140 rounds,
Antiquities' 30, Legends' 36, The Dark's twelve parallel groups and Ice Age's
42 rounds plus four waves — lives in git history. Read a round there when you
need the reasoning behind one of these bullets; do not add a new round here.

The process a set follows, phase by phase, is `SET_PLAYBOOK.md`. Numbers go
here, process goes there, and neither repeats the other.

**Why the journal is culled, and this is the third time.** It first reached
2,700 lines, of which 2,350 were narrative that no longer changed anyone's
decisions; that cull is at `ee28617`. Ice Age then put 1,800 lines back
(readable at and before `49f74af`), and Homelands put 400 back (readable at
and before `0a1ce5d1`) — the same rule applies each time. A file nobody reads
to the end is a file whose *live* items go unread with the dead ones. The
parts that were still doing work are all below.

---

## Standing invariants

Anything that weakens these is a regression regardless of what it enables:

1. **No silent wrongness.** A card may fail loudly as unsupported with a
   reason; it may never resolve as something other than what it says.
2. **The suite stays fast.** **12,035 tests**, CI budget **500s**, CI-measured
   baseline **260s** (`ci.yml`). The budget catches a step change; the baseline
   is what catches creep, and it is the number to keep honest. Raising the
   budget is a decision, not maintenance — it has been raised four times on
   purpose.

   **`ELAPSED` is runner-measured, and that is the whole lesson.** The two
   numbers sat wrong in opposite directions for three sets because `BASELINE`
   was recorded from a *local* run and compared against an `ELAPSED` the step
   measures on the runner — the multiplier was never in the arithmetic at all,
   it was the arithmetic's missing term. A local timing may enter a *budget*
   through a multiplier that was itself measured — time a commit this workflow
   has already run and divide — but **`BASELINE` takes the step's own output and
   nothing else**, because even that measured multiplier under-predicted by 10%
   (see below). `gh run view <id> --log | grep "suite wall time"` is where the
   runner's half lives, and every successful run has it.

   **Re-read at Phase 0, 2026-08-31, from four runner runs**: 172s, 186s,
   163s, 205s at 10,821 tests. `BASELINE` moved 110 → 180 as the record of
   that growth; `BUDGET` stays 240, and the latest run is **85% of it** with an
   ingest ahead. The shape matters more than the level: +19% tests took +64%
   runner wall time (a local machine measured the same super-linearity, +40%),
   so per-test cost rose during ICE's waves — read `--durations` on a runner
   run before letting the next ingest force the budget decision, and remember
   the `slow` marker exists if the AI-batch tests are the growth.

   **HML made that decision due and it was taken: `BUDGET` 240 → 500 and
   `BASELINE` 180 → 260, 2026-09-02, the fourth raise.** Both are runner
   readings of this tree — run 33644611682 on `homelands` reported
   `suite wall time: 260s` at 11,923 tests. It was overdue rather than
   precautionary: the last run before the set (33564882929, commit `1a294522`)
   read **217s**, already 90% of the old 240, and the set added ~750 tests on
   top of that. `BUDGET` is ~2x `BASELINE`, which is the headroom this gate is
   documented to want and which puts the creep warning (1.5x = 390s) ~22% below
   the gate so it can fire first.

   **And the method note, which cost a commit to learn.** An interim pass set
   `BASELINE` from a *measured* multiplier rather than a guessed one: time a
   commit this workflow has already run and divide. That gave 217/126 = **1.72**
   on `1a294522`, projecting 138s local to ~237s. **The truth was 260s** — the
   multiplier itself grows with the suite (1.72 at 11,176 tests, 1.88 at 11,923),
   because the runner degrades faster than a local machine does. So a measured
   multiplier is good enough to size a *budget* and not good enough to set
   `BASELINE`, which wants the step's own output. That is one dispatch away
   (`gh workflow run CI --ref <branch>`, then `gh run view <id> --log | grep
   "suite wall time"`), and it is the only honest source for this number.

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
are the M21-era rounds, `ATQ n` is Antiquities', `LEG n` is Legends', `ICE n`
is Ice Age's.

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

**Re-probe the refusal itself, not only its priority.** The cleanup before Ice
Age found nine "deliberate refusals" already implemented. The cleanup after it
(2026-08-31) found five recorded items closed without their entries moving: four
leads the parallel waves had finished (Hipparion's cost-to-block, Adarkar
Unicorn's mana alternation, Barbarian Guides' delayed return, Fumarole's second
target) and one recorded defect — `ObjectFilter.blocked` parsed and never
emitted — fixed with a comment beside the fix describing the exact bug this file
was still listing as open. A refusal or a defect recorded here is a claim about
the code with no test behind it.

### Open blocks, still standing

- **Drained 2026-09-02: `card.name` has its ratchet.**
  `tests/engine/test_printed_name_reads.py` separates a *dispatch* on the
  printed name from a *mention* of it (956 reads censused across `engine/` and
  `web/`: 45 dispatch-shaped, the rest f-strings, labels and serialization).
  Four dispatch sites were live Clone-shaped bugs, each fixed with a CR 707.2
  test that fails on the old engine: the same-name CDA count (a Clone of
  Plague Rats neither was one nor counted one), `UNTAPPED_ARTIFACT_PROTECTORS`
  (a Clone of Guardian Beast protected nothing), `ON_LEAVE_BATTLEFIELD` (a
  Clone of Gaea's Liege left its Forests standing) and Goblin Artisans' rival
  scan. 39 reads in 9 modules are ratcheted (counts may only shrink). The
  largest ratcheted family — 29 reads — is one migration: the upkeep-prompt
  wire protocol keys prompts by printed name on both the write and read side;
  draining it means `permanent_id` keys on both sides in one round, which also
  stops two same-named permanents sharing one prompt answer. Two
  dispatch-in-spirit shapes are invisible to the classifier and recorded here:
  `commander.py`'s CR 903.10a damage tally keys by name through an
  intermediate tuple (harmless today — no pool commander can change names),
  and names carried into records whose comparisons happen later on plain
  `.name` (`dead_name` is *correct* by CR 707.2 — copy effects end on leaving
  the battlefield, so a graveyard card is the printed face).

- **Drained 2026-09-02: an AI seat casts its commander.**
  `ai_valuation.castable_commanders` asks the engine's own commander seam
  (`may_cast_from_command_zone`, `commander_tax`) rather than the compiled
  program — CR 903.8 is a rule, not oracle text, so the seam is the honest
  derivation — and `choose_cast_action` runs its ordinary per-card body over
  the command zone with the tax threaded in as extra generic cost;
  `COMMAND_ZONE_CAST_BONUS` in `ai_policy.py` prices the netted card.
  `CastAction` carries `from_zone`, and both executors forward it. A duel's
  command zone is never read, and determinism is untouched.

- **Drained 2026-09-02: a toll compares its two losses.**
  `ai_valuation.toll_branch_loss` prices one branch's loss off the compiled
  program — life paid or damage taken, cards discarded or anted, self-mill,
  and the actual permanents lost via the engine's own sacrifice ordering —
  returning None for any step it cannot price;
  `ai_policy.toll_decline_is_smaller_loss` compares the sides in
  life-equivalents (lethal outprices everything), asked once beside the
  existing unpriced-trade question in `_default_optional_pay` — no per-shape
  branch, no card name. The item's "nine cards" was stale: the pool holds
  **22** toll cards. **8** are now decided by the comparison (Curse
  Artifact's victim takes the 2 damage rather than sacrificing, paying only
  when declining would be lethal; Hecatomb sacrifices itself, not four
  creatures), **8** are mana-priced and deliberately left to the
  floating-mana policy, and **6** have an unpriceable side — counter that
  spell, a coin flip, counter placement (Mana Vortex, Amulet of Quoz, the
  Chants, Koskun Falls, Essence Vortex) — where pay-tolls stands. Those six
  are the item's residue: the comparison reaches them when those losses have
  valuations.

### Recorded, measured, and not yet fixed

Each of these was measured when it was written; each carries the date it was
last re-probed. Re-probe before scheduling one.

- **The Nine Lives class — partial implementation reported as full.** A card is
  supported when **any** line is, so a card can report supported while other
  lines produce nothing. The census is
  `scripts/support_report.py --hollow-lines`: every supported card whose
  compiled program carries an ability with no instruction behind it. **It reads
  two today** (2026-08-31) — Creature Bond and Howling Mine, each a line a
  registry implements in full and the compiler cannot see (the death-damage
  template, which must read a toughness no payload can hold; the draw-step
  table).

  Kudzu left the census on 2026-08-28 and is why the census is worth running:
  applying the Rock Hydra test to all three found that two were fine and the
  third **had never fired at all**, because its dispatcher lived inside
  `tap_land_for_mana` and a land tapped by an Icy Manipulator destroyed nothing.
  What the census cannot see is a *registry that claims a line and does less
  than it says*; that class is only findable the Rock Hydra way, by giving the
  behaviour a game. **The census is a Phase 3 exit criterion, not only a Phase 2
  reading** — Antiquities read 85/85 supported for thirty rounds with three
  cards in it (ATQ 30), and reaching zero took a round of its own.

- **The verification backlog is accepted, by decision, 2026-08-28.** It stood
  here as the largest standing debt in the repo, with derived `equivalent`
  named as the lever nobody had pulled. The lever was measured and it is
  exhausted: `behaviour_signature.py` distinguished **1,049 behaviours over
  1,162 cards**, 148 cards shared a class at all, and 48 unverified cards were
  covered by a passing peer. It could not reach 708 — the pool is that diverse
  — so no amount of pulling clears the debt. An in-game pass is therefore **not
  a required validation step**: promotion gates on Phase 4, regressions are
  caught by the suite and `simulate_ai_games.py`, and `CARD_VERIFICATION.md` is
  read as a log of what a human happened to check rather than as a coverage
  target. See SET_PLAYBOOK.md's Known gaps for the same decision stated where
  the phases are. Ice Age took the untested count from 708 to 1,020, which is
  the decision working as intended rather than the debt growing.

  **A card recorded *failing* is still a live bug**, and that is the half this
  decision does not touch. The count that matters is failures, not blanks, and
  it stands at **0** (2026-08-31).

  **Getting it to zero taught something about the tracker itself.** Both rows —
  Candelabra of Tawnos and Silent Dart — were fixed in code, given tests, and
  written up here and in the playbook as "closed", and both went on reporting
  ❌ for the three days after. Nothing was wrong with the fixes; the row is a
  record of what a *human saw in the app*, and no code change clears one. They
  were re-checked in the running app on 2026-08-31 and both behave: Candelabra
  asks "Choose X", then "Choose 2 targets", and untaps exactly the two lands
  chosen out of three (the third stays tapped); Silent Dart with no creature in
  play refuses with the message it always gave and **nothing paid** — the
  artifact still on the battlefield, the mana pool untouched — and with a
  legal target deals its 3, kills the Hill Giant and sacrifices itself. So:
  fixing the card is not closing the report. Re-check it in the app and record
  the pass through the Debug Menu, or the repo goes on advertising a live bug.

- **Drained 2026-09-02: the "that player" fall-through refuses.** The damage
  family's last `elif` in `lowering/_events.py` now raises a `LoweringError`
  naming the event that freezes no seat, restoring the module's own documented
  contract. The pre-fix census read **12** trigger riders, not the recorded 11
  — Takklemaggot's granted upkeep line had joined — plus five spells
  (Detonate, Icequake, Leeches, Word of Blasting, Worms of the Earth) whose
  "that player" is a sentence back-reference resolved off the resolution
  context: the fall-through's legitimate remainder, untouched. The
  hand-written fire sites (Ankh of Mishra, Dingus Egg) now enqueue the
  compiled instruction with the land's controller frozen under
  `event_subject_controller`, retiring the synthetic swap; the upkeep-registry
  seats ride `event_subject_player`; Lim-Dûl's Hex's pronoun binds to the
  innermost `for_each` loop by marker. Twelve programs moved, nothing else.
  Incidental yield: a `may` whose frozen seat has **left the game** now runs
  its decline branch (CR 800.4f — a departed player's cost "is not paid");
  the old fallback had skipped Erosion's consequence for a departed payer.

- **Drained 2026-09-02: the two layer-4 reads agree, and board-wide layer-4
  statics chain in timestamp order (CR 613.7).** Both `land_types.py`
  predicates now judge against `layer_bridge.types_before_timestamp` — the
  intermediate state built by replaying only the layer-4 effects stamped
  earlier than the asking effect — and `_refresh_static_land_types` walks all
  applicable statics timestamp-sorted instead of breaking at the first, so
  Conversion sees the Mountain Blood Moon made (Blood Moon earlier: Tundra
  ends a Plains; Conversion earlier: Tundra ends a Mountain). The same
  intermediate state also lets a static chain with the *recorded* channel — a
  Phantasmal-Terrain-shaped contribution with an earlier stamp is visible to
  a later Conversion — a third disagreement the item never named.
  `static_source_timestamp` now stamps the first refresh that *sees* a source
  rather than the first that applies it (CR 613.7a wants the ability's
  object; an inapplicable-on-arrival static previously had no place in the
  order at all). Zero compiled programs moved; seven CR-cited tests.

- **CR 613.8 dependency is not implemented, and Blood Moon/Conversion is its
  reproduction.** Under full rules Conversion *depends on* Blood Moon
  (applying one changes what the other applies to), so it would apply after
  it regardless of timestamps and **both** orders would yield Plains; the
  engine's timestamp-only answer is what makes the order observable. The
  Conversion-first test documents in its docstring that its expectation is
  the one that must flip when dependency arrives. Recorded 2026-09-02; no
  pool interaction beyond this pair is known to need it.

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
    enters attached to nothing and is binned by CR 704.5m one sweep later — the
    same destination by a different rule. The graveyard decline's stated reason
    is the ambiguous case: two copies of one card in one graveyard are literally
    one `CardDefinition`, so resolution clamps to the last surviving copy.

    **The two answerable graveyard residuals were closed 2026-09-02.** The
    unambiguous stale-index fall-through is gone: a graveyard stamp whose
    card has no surviving copy answers None, `illegal_targets_refusal` reads
    the stamps, and a Resurrection whose Serra Angel is exiled in response
    now leaves the stack unresolved (CR 608.2b) instead of reanimating the
    Grizzly Bears beneath it; the same-name clamp for surviving copies
    deliberately stays. On the cast side, `graveyard_creature` left the
    unchecked list and sequence-wrapped graveyard targets (Fungal Rebirth,
    Experimental Overload) are validated against the same enumeration the
    picker uses (CR 601.2c). One deliberate behaviour shift rode along:
    Drafna's Restoration naming an ineligible card is refused at announcement
    with nothing spent, where it used to be accepted and dropped at
    resolution. Two residuals remain recorded: an activated or triggered
    ability whose stamped graveyard choice vanishes no longer reads the stale
    slot but falls to its untargeted deterministic pick, which can still pick
    a card nobody named (it belongs to the triggered-ability round above);
    and an *untargeted* sequence-wrapped graveyard spell is still accepted
    against an empty graveyard and resolves doing nothing — CR 601.2c's "can
    the announcement be made at all?" half is asked per primary kind only.

- **Five handler paths still resolve by index alone**, reached today only by
  instants and so caught by the CR 608.2b gate first. The next *activated*
  ability printed with the same text walks in. **Re-counted 2026-09-02: still
  five, and now named** — an AST census over `engine/handlers/` for functions
  that read `context.target_permanent_index` and subscript a battlefield
  without ever touching `target_permanent_id` or the resolution seam:
  `board_misc.mark_text_modified`, `combat.remove_creature_from_combat`,
  `prevention.apply_prevention_shield`, `zones.exile_target_creature_until_eot`
  and `zones.exile_creature_gain_life_equal_to_power`. All five also carry a
  "fall back to the first matching permanent" default, the look-alike class.
  (The graveyard-index paths the same census surfaces are index-addressed by
  design and belong to the CR 608.2b graveyard entry above, not here.)

- **CR 508.5's second sentence is not implemented** — "if that creature is no
  longer attacking, the defending player it's referring to is the player that
  creature *was* attacking". `_prune_combat_state` clears `attacking` and
  `defending_player_index` together before rebuilding, so the memory is gone
  by the time anything could ask. Nothing in the pool asks after removal from
  combat, so this is a gap with no card behind it — recorded rather than
  fixed, because a fix with no card to verify it is a guess (the same reason
  "a filter with no card behind it is untested by construction" sits below).

- **Two smaller ones, each with no card behind it today** (re-probed
  2026-08-31; a third, `ObjectFilter.blocked`, has since been fixed).
  `_perform_entry_state`'s "enters with N +0/+1 counters" branch writes
  `metadata["plus_0_1_counters"]`, a key nothing reads — `pt.pt_counter_key`
  answers `"+0/+1_counters"` for that kind, while its `+1/+0` sibling agrees
  with its readers — and it assigns rather than accumulates.
  `prevention.source_has_type` falls back to the printed type line for a source
  that is not a `Permanent`, so a shield reading "by creatures" would answer for
  a creature *spell* on the stack.

- **`handlers/_common.py`'s `"triggering_spell"` mana value has CR 202.3b's
  gap** — it reads the cast card's `cmc`, so an {X} spell's mana value on the
  stack is wrong. The same bug was fixed for Spell Blast and Mana Drain through
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

- **Drained 2026-09-02: the dead-import backlog is swept and guarded.** It stood
  here as 310 imports across 36 modules that no module used and none re-exported
  — the moved-block hazard's silent twin, deposited by every grammar family split
  since the layering began. **306 bindings removed** (a second pass caught one
  that only became dead once its sibling went), and the whole-pool differential
  moved **zero of 1,725 cards**, which is what a purely cosmetic change should
  look like. `tests/engine/test_import_hygiene.py` now asserts it per module,
  with re-exports resolved through real module paths so the two façades
  (`statements`, `sentence_clauses`) keep the names other modules pull back out
  of them, and with the "used" test kept deliberately **textual** so a name that
  appears only in a string annotation survives.

  The distinction worth keeping: a dead-import sweep asks "what does this module
  import and no longer use", a missing-import scan asks "what does it use and
  never import". Only the second is a bug, and it is the **loud** one — a
  `NameError` the moment its line runs, which the suite finds and a smoke import
  does not. The silent one is the one that needed a guard, and now has one.

- **Drained 2026-09-02: a count narrowed to a combat role reads the whole
  battlefield.** It stood here as `count_spec` defaulting an unscoped noun phrase
  to `owner: "you"`, with Márton Stromgald and Alpine Houndmaster named as
  riders. Re-probing narrowed it *and* widened it. CR 508.1a puts every attacking
  creature on the active player's battlefield, so both attacking counts were
  already right — but CR 509.1a and CR 802.2 give a multiplayer game several
  defending players, each declaring their own blockers, so **Márton's blocking
  half counted one where the rule says two** at a three-seat table. Reproduced
  before the fix; the differential then named a third card nobody had, Aurochs
  (ICE).

  One scope decision rather than a special case: a combat role is a property of
  the *battlefield*, and the seat that asks is not necessarily the seat the
  objects are on — which also closes the latent case of a defending player's card
  counting attackers, where `owner: "you"` answers zero. It is what the
  sentence's **other** reader already did: `buff_creatures_global` takes the same
  printed noun phrase over every seat, so a seat-scoped count had one clause
  meaning two sets (idiom 36). Three cards moved, four CR-cited tests in
  `tests/rules/test_multiplayer_combat.py`, and the duel answer is unchanged.

### Deliberate refusals, with their reasons

Not gaps to close on sight — each was measured and left refusing. This list used
to be three times as long; a pre-set cleanup found nine of its entries
implemented and still listed as refusing, and the entry that taught the rule was
El-Hajjâj's "you gain that much life" — recorded as "its fire site records the
amount under a different key", which was a fact about a fire site and never
about the rule. There is one announcement per damage event now, so there is one
key. A refusal resting on where an event happens to be announced from expires
the moment the announcement moves. **Re-verify an entry against `compile_line`
before citing it.**

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
- **"Pay {X} life" as an additional cost** (Fire Covenant). X is announced as
  the spell is cast (CR 601.2b) and this engine resolves it *after* additional
  costs are charged, so a clause for it would charge zero. It stays in the
  parse-coverage backlog, which is where an unimplemented cost belongs.

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
   frozenset beside the loop. The same is true of a reader enumerating *payload
   keys* rather than kinds.
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
   everything matching in an any-number search, `default_sacrifice_pick`'s
   "keep the one whose death loses the game for last, then take the smallest",
   "take gifts, pay tolls, make no trades" for a free offer, and the *largest*
   alternative of a printed mana "or" (no mana burn, so more of the same is
   never worse). A card that should choose otherwise needs a valuation, not a
   branch.
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
    index **to a card** before anything leaves the zone (round 50). An id that
    resolves to *nothing* is a fizzle; an id that resolves to a permanent the
    caller cannot use is not — falling back to the index makes the decoy that
    inherited the slot the target (ICE follow-on 1, nine live cards).
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
    spelling (LEG 9). One event is one kind and the subject is *payload*. The
    symptom is silent in the way this engine's worst bugs are: the seam emits,
    nothing listens for that name, and an emit nobody listens for reads exactly
    like an event that never happened.
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
    what kept it there for four sets (LEG 10). When the gap is "this event has
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
    first and shadowing it with the second. A cross-module shadow needs a
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
30. **A keyword rewrite belongs to a line, not to a card type.** Cumulative
    upkeep's rewrite hooked the loop that reads a *creature*'s lines, and ten
    Ice Age enchantments printing the keyword beside another ability compiled
    clean with it silently dropped (ICE 1) — strictly worse than not
    implementing it, because the card reads as done and plays as a better card
    than the one printed. `oracle.keyword_line_triggers` is the one reader both
    loops ask. The count that exposed it was per-card instrumentation written
    *before* believing the census: +11 became +23 once both front ends agreed.
31. **A widened gate stops asking about the line it was widened for.** Three
    times in one set. A land's unread-static check ran only `if not
    any((activated_abilities, triggered_abilities))`, so the moment cumulative
    upkeep became an ability the land skipped the check entirely and Halls of
    Mist shipped with its real static unimplemented (ICE 1). An
    artifact/enchantment gate took a `derived_static_rule` as evidence the
    permanent does something, and a restriction is a clause of an ability, not a
    thing a card does (ICE 36). And `classifier.classify_card` overrode the
    compiler outright — a card refused for "unsupported triggered ability" was
    reported supported if any *other* trigger compiled, which made it castable,
    browsable and playable with a printed trigger doing nothing (ICE 39). Each
    time the guard was standing in for "is this line read?" and answering "does
    this card have *some* ability?".
32. **A stand-in for a parser disagrees with it in both directions.**
    `engine/auras.py` claimed "this line is an activated ability" with a regex
    for the *shape* of one — a run of mana symbols, an optional tail, a colon.
    CR 602.1 admits any cost, so Fylgja's counter-removal cost was refused
    although the compiler had parsed the whole ability; and a line matching the
    shape whose effect the compiler cannot read was claimed anyway, which is how
    an Aura reports supported carrying an ability that does nothing (ICE 32).
    Ask the parser. Measure both directions over the pool before changing it.
33. **A family word is not a list of its members.** CR 702.14a builds a
    landwalk's name out of a printed *quality*, so "snow forestwalk" is a
    landwalk and no frozenset can hold every one there will be. Three readers
    learned this separately: the negation table (ICE 17), the grant
    (ICE 39), and the removal — which expanded the family **in the parser** into
    whatever `IMPLEMENTED_KEYWORDS` happened to name, so Hammerheim's "loses all
    landwalk abilities" left Rime Dryad its snow forestwalk while the log said
    otherwise. Carry the family word; let the site that knows what the permanent
    *has* do the expansion.
34. **Measure the machinery before scheduling the round.** Phase 2 called snow
    one of Ice Age's two big rocks; "snow land" already parsed to
    `supertypes: ["snow"]` and `permanent_matches_filter` already tested it, so
    33 cards had been ranked behind a subsystem that existed (ICE 6). What was
    actually missing was three narrow things, two of which were bugs.
35. **A ratchet has one denominator.** `--accept-probe` snapshotted findings
    from *every* coverage while `collect_findings` gates on the shipped half, so
    accepting one reviewed finding wrote 90 entries the next `--check` called
    stale (ICE 37). The same rule `HOOK_RELIANCE.md`'s measure names say out
    loud: a ceiling and the thing it measures must count the same population.
36. **Two callers of one table must spell the sentence the same way.**
    `activation_restrictions._clauses` splits printed oracle text and keeps
    "step, only"; the grammar consumes the sentence token by token and rebuilds
    "step , only". Every row is written the printed way, so a clause with a
    comma inside it matched from one caller and not the other — the gate calling
    a line readable while the parser refused it, or the reverse, depending on
    which asked (ICE 26). Normalise where both callers pass through.
37. **A cost reader consumes the whole phrase or refuses it** — the grammar's
    hard invariant, carried into every derivation table that reads a cost.
    Cumulative upkeep's cost went to `mana_cost_from_symbols`, which *scans* for
    symbols and ignores the rest by design, so "Pay {B} and 1 life" came back
    `{B}` and Infernal Darkness charged half its upkeep from the day it shipped
    (ICE 31). A refusal you can see and a rider you cannot are the same bug
    wearing different clothes, and only the second one ships.
38. **A restriction printed as one sentence is a conjunction, and each conjunct
    needs a row.** CR 602.5 puts no limit on how many restrictions a clause
    states. Reading the sentence whole makes every *pairing* its own row —
    quadratic in the clauses that exist — and hides a row whose predicate reads
    two rules under one name (ICE 26). Split, require a row per conjunct, and a
    conjunct nothing reads makes the whole clause unreadable, which is what
    stops a card being admitted with half its sentence enforced.
39. **A headless probe cannot tell "nobody was asked" from "nobody was there to
    ask".** Preacher was reported as never offering the opponent their choice;
    run with both seats interactive it arms a `permanent_choice` owed by the
    opponent, offers both their creatures and honours the answer. What the sweep
    saw was the **non-interactive default** taking the first candidate, which is
    what a headless seat's default is specified to do. The same month,
    `_default_mode_choice` looked identical and *was* a real bug — it answered
    "Choose one —" in printed order, so Sylvan Library's price-first modal made a
    headless seat pay 8 life for two extra cards and die on the third. Arm the
    prompt with `interactive_seats` set before believing either reading.

---

## The next set, measured rather than guessed

**Re-censused 2026-09-02 against the post-HML compiler**, the candidates
fetched to a scratch directory (never `cards/`), measured with
`support_report.refusals_report` so "a refused line" means what the work lists
mean by it:

| Set | Cards | New to pool | New & unsupported | New per unit work | Lines/distinct | Blocked by exactly one line |
| --- | --: | --: | --: | --: | --: | --: |
| 5ED *(shipped since)* | 434 | **0** | 0 | — | — | — |
| ALL *(shipped since)* | 144 | 144 | 82 | 1.4 | 1.02 | 61 of 82 |
| 6ED | 335 | 152 | 53 | 2.6 | **1.00** | 48 of 53 |

**This table is now out of date in the way it always goes out of date, and the
row that matters is missing.** MIR/VIS/WTH were skipped here on the grounds
that "none is a near-term candidate"; Alliances shipping makes **Mirage the
next set by release order** (1996-10-08, 335 printings, 313 new to the pool),
and its row has never been measured against a modern compiler — its last
reading is pre-ICE. So **Phase 1 opens with the census, not with the ingest**:
fetch MIR, VIS and WTH to a scratch directory (never `cards/`), measure with
`support_report.refusals_report`, and read the fragment census beside the
sentence one. Five consecutive sets have had the sentence census read 1.00–1.02
— "no leverage" — and been wrong every time; the fragment census is what found
Alliances' land cycle and Homelands' untap-denial family.

**Fifth Edition shipped 2026-09-02, the day of this census.** Its post-ICE row
read 58 new cards, and those 58 were exactly its FEM and HML reprints (29
each); both sets shipping took it to **434 of 434 already in the pool, all
supported** — origins: LEA 158, ICE 89, LEG 53, ATQ 31, HML 29, FEM 29,
DRK 28, ARN 16, LEB 1. It ran 4ED's shape exactly: entered `measured` fully
supported, promoted the same session at index 12 (between HML and M21), bought
printings and the rehearsal. The rehearsal's one new finding was Phase 1's,
not Phase 4's: the manifest-write guard had baked in "measured starts empty"
(true since HML's promotion) by asserting the copied manifest's measured list
equals exactly its test entries — the emptiness-premise class from the Ice Age
promotion, found from the other side. The release-line note below still
applies to the rest of the core-set line.

**Alliances shipped 2026-09-02** — the section below is its ingest estimate,
kept because its predictions were graded in the retrospective. **The next work
set is Mirage (MIR), then Visions and Weatherlight, and only then 6ED**, whose
152 new cards are their reprints: a core set ingested before its sources
arrives carrying cards nothing supports with their origins mis-stamped. Re-run
the census table above before choosing — the last three re-fetches were all
stale by the time they were read.

**Alliances (ALL), as estimated at ingest.** It **inserted at index 12** (released
1996-06-10, after HML's 1995-10-01 and before 5ED's 1997-03-24), it closes the
Ice Age block, and for the first time the leverage instruments agree with the
refusal census at ingest-estimate time rather than contradicting it later:

**That "index 12" corrects this paragraph's own first draft**, which read "it
appends" — true when it was written and false the same day, because 5ED shipped
between the census and the first round. And the correction is invisible to the
guard built for it: ALL shares **zero** oracle_ids with 5ED or M21, so no card's
`original_printing` moves from any position, and
`test_appending_a_set_never_changes_an_existing_original_printing` is green with
the set anywhere. FEM's and HML's blind spot for the third time. The assertion
that can see it is
`test_manifest_roles.test_the_shipped_sets_are_in_printing_order`, which
compares the `released` dates the entries already carry — the invariant rather
than a symptom of it.

- The fragment census over its refused lines has real groups — **"at the
  beginning of" (17 cards)**, "of your library" (13), "until end of turn" (13),
  "exile the top" (8), "onto the battlefield" (8) — where four consecutive
  earlier sets measured no shared fragment at all. The delayed/upkeep-trigger
  and library-top families are where its wave groups are.
- `--hollow-lines` over its 62 supported new cards reads **five** (Tidal
  Control, Dystopia, Death Spark, Tornado, Sol Grail) — the FEM class (a
  supported card carrying an unimplemented sentence) visible *before* the
  ingest this time. Those five are work-list entries the refusal census cannot
  see.

6ED came down to 53 pieces of work (its own leverage is the tutor family —
"search your library" over 7 cards) but stays sequenced behind Mirage, Visions
and Weatherlight: its 152 new cards are their reprints, and a core set ingested
before its sources arrives carrying cards nothing supports with their origins
mis-stamped.

**Read the next candidate's `parse_coverage.py` and `--hollow-lines` numbers
beside this table**, not after the ingest — FEM proved the refusal census alone
asks the wrong question (its repeated sentences paired a refused card with a
**supported** one, invisible to a census built from refusals only), and ALL's
five hollow lines above are that lesson applied at estimate time. **And run the
fragment census as well as the refusal one** — four candidates in a row
measured exactly 1.00 refused lines per distinct sentence, the reading that
said HML had no leverage in it, while ten of its cards printed one untap-denial
clause and three already compiled. Read both beside the **picker sweep** (run
at Phase 1 it turns a promotion-gate finding into a work-list entry; at HML it
found a shipped Aura no player could cast).

**Two structural gaps bound everything after Innistrad**, and the first is a
hard wall rather than a backlog. `card_loader.REQUIRED_FIELDS` demands a
top-level `mana_cost`, which a transform card does not have, so a double-faced
card raises `ValueError` on *load*. `_load_faces` populates
`CardDefinition.faces` and the only reader in the repo is `commander.py`'s
colour-identity derivation — the compiler has never seen a second face. That is
CR 709/710/712/714/715/720, 45 rules, none implemented; it already costs Origins
5 cards and M19 one. Second, keyword abilities stand at **28** of CR 702's 192
(`vocabulary.IMPLEMENTED_KEYWORDS`; cumulative upkeep was the twenty-eighth).
**The third gap is closed.** "Alternative costs (CR 118.9) do not exist —
the phrase appears in the engine only in comments" was true until Alliances,
whose pitch cycle paid for it: `engine/alternative_costs.py` reads the
"You may &lt;clauses&gt; rather than pay this spell's mana cost" template, and five
cards cast through it (Force of Will, Pyrokinesis, Contagion, Bounty of the
Hunt, Scars of the Veteran). The buyback/flashback/evoke/madness family is no
longer blocked *wholesale*; each still needs its own keyword, which is the
second gap above. What the subsystem still lacks is a **client picker** — the
engine charges an alternative or repeated cost correctly and the browser can
only announce the default — recorded as a named four-part item in
SET_PLAYBOOK.md's Known gaps.

## Mirage (MIR) — shipped (335/335, manifest index 13)

**Ingest census: 184/335 supported (54.9%), 312 of 335 cards new to the pool.**
Registered under `measured` on 2026-09-02 at release date 1996-10-08, which
places it between Alliances (1996-06-10) and Fifth Edition (1997-03-24) —
printing-order index 13, an insert rather than an append. Every card is
`layout: normal` and every printed type is one the engine already ships
(131 Creature, 64 Instant, 41 Enchantment, 37 Sorcery, 23 Artifact, 20 Basic
Land, 12 Legendary Creature, 10 Artifact Creature, 6 World Enchantment, 6 Land,
1 Legendary Land), so **Phase 2's first sweep is empty**: no new layout and no
new card type gates the promotion. The whole of the set's machinery cost is
keywords and text.

**The censuses, all five, read at ingest rather than at the gate:**

| Instrument | Reading |
| --- | --- |
| `support_report --set MIR` | 151 unsupported |
| `--refusals` | 168 refused lines over 164 distinct sentences — **1.02** |
| `--fragments` | "at the beginning of" 32 cards, "until end of turn" 19, phasing's reminder text 7 |
| `--hollow-lines` | 5 supported cards, 8 instruction-less parts |
| `parse_coverage --set MIR` | 19 cards, 25 unclaimed sentences |
| `picker_sweep --set MIR` | 4 findings (Dazzling Beauty, Soul Rend, Telim'Tor's Edict, Early Harvest) |

**1.02 for the sixth consecutive set, and for the sixth consecutive set it is
the wrong number to plan from.** The sentence census says no production here
buys two cards. The *keyword* census says two words buy twenty-four:

- **Flanking (CR 702.24) — 10 cards, one ability.** Femeref Knight, Mtenda
  Herder, Sidar Jabari, Zhalfirin Commander, Zhalfirin Knight, Cadaverous
  Knight, Burning Shield Askari, Searing Spear Askari, Telim'Tor, Jolrael's
  Centaur. Nine of the ten refuse with **every line grammar-clean** — the
  refusal is the reminder-text line gate, not a production — so the whole
  bucket is invisible to the refusal rollup's site column.
- **Phasing (CR 702.25) — 7 keyword cards plus 12 more that print the action.**
  And this one is the opposite of what the census implies: **the subsystem is
  already here.** `Game.phase_out_permanent` / `phase_in_for` / the per-seat
  `phased_out` list / the CR 702.26e call at the top of the untap step all
  arrived with M21's Teferi planeswalkers. What is missing is the *keyword* —
  the alternation CR 702.25b describes, where a permanent with phasing phases
  out and back in on successive untap steps — plus the ways a card grants it
  (Cloak of Invisibility, Teferi's Curse, Shimmer), one trigger ("whenever this
  creature phases out", Teferi's Imp) and one restriction ("can't phase out",
  Spatial Binding). `"Phasing"` also sits in `oracle.UNSUPPORTED_KEYWORDS`,
  which outranks every line gate — Legends' rampage lesson, and the reason the
  registry diff alone would have sent this round off to build what exists.

### Round 1 — flanking (CR 702.25): 184 → 194 supported

Ten cards for one keyword, and the change was a *deletion* as much as an
addition. `engine/flanking.py` is the rewrite `rampage.py` and
`cumulative_upkeep.py` established — CR 702.25a defines flanking rather than
describing it, so the printed keyword line becomes the trigger it already is
and the existing becomes-blocked dispatcher fires it. The "without flanking"
half is the ordinary `blocker_filter` payload every printed "becomes blocked by
a &lt;noun&gt;" produces, which is also what makes it fire once per blocking
creature (CR 509.3d) rather than once for the block.

**The engine had already implemented flanking, inline, and its own docstring
named this round as the one that would remove it.** `_apply_flanking` ran at
*declaration*, and it said so: "Flanking stays because CR 702.25a is a
triggered ability the engine has no *card* for … moving it would be inventing a
card's worth of work with nothing to verify it against." Mirage prints ten. The
inline version had rampage's three old defects — the -1/-1 landed before anyone
could respond, one instance was applied however many the creature had
(CR 702.25b), and the block map was walked by battlefield index, which a
removal renumbers. Two CR-cited tests were asserting the wrong moment and now
assert the right one; two more were added for the stack window and for two
instances.

**Flanking is the first keyword that needs the word *and* the line, and one
card in the set proved it.** `keywords.LINE_DERIVED_KEYWORDS` exists because
layer 6's ability set holds words, not triggers, so a grant of rampage grants
the printed *line*. Flanking has to do that too — and Agility ("Enchanted
creature gets +1/+1 and **has flanking**") showed that the word matters
independently, because the *next* flanker's "without flanking" filter asks it.
Both halves travel together for free once the line is granted:
`layer_bridge._TEXT_KEYWORDS` seeds layer 6 from the compiled keyword lines, so
the appended line puts the word back. The Aura path needed the same rule the
one-shot path already had (`aura_granted_line_derived_lines`), derived per read
like every other half of `auras.py`, so detaching takes the ability away with
nothing to undo. **This was a live gap for rampage too** — an Aura granting
rampage would have granted the word and no ability — with no card behind it
until now.

`oracle_diff` after the round: **11 changed of 2181**, every one a Mirage card
that prints the word. Two cards the round did *not* buy, both now refusing for
the right reason and both cheap follow-ups: Telim'Tor ("all attacking creatures
**with** flanking get +1/+1" — `the global buff cannot narrow by:
with_keywords`) and Barbed Foliage ("it **loses** flanking until end of turn" —
`remove_ability_line` has no duration channel, deliberately, because nothing in
the pool had needed one).

### Round 2 — phasing (CR 702.26): 194 → 204 supported

**The census said "subsystem" and the truth was "keyword".** `Game.phase_out_permanent`,
`phase_in_for`, the per-seat `phased_out` holding list and a CR 702.26 call at
the top of the untap step all arrived with M21's Teferi planeswalkers. What was
missing was CR 702.26a — the *alternation*, which is the whole of what the
keyword does — plus the ways a card says the word.

`Game.resolve_phasing_for(seat)` is that rule, and it is one method rather than
two calls because 702.26a makes the halves **simultaneous**: both sets are read
off the board before either is applied, so what has just phased out is not swept
straight back in and what has just arrived does not leave again. The outgoing
half reads the keyword off layer 6 and the incoming half reads the holding list,
which is what makes a permanent phased out by a one-shot (Reality Ripple) come
back exactly once while one *with* phasing alternates forever.

**CR 702.26m came free and had been wrong.** "If an effect causes a player to
skip their untap step, the phasing event simply doesn't occur that turn" — the
old call sat above the skip check, so a Teferi'd creature phased in through a
Stasis. Reading the untap constraints one line earlier fixes it and settles the
ordering question the rule leaves open: a Stasis that phases *in* during the
event does not retroactively skip the step it arrived in.

**`oracle.UNSUPPORTED_KEYWORDS` is now empty, and that is the state to keep.**
Phasing was its last entry. That table outranks every line gate and is the only
refusal in the engine that names no clause — Legends' rampage sat in it with the
behaviour built and tested and seven cards unsupported — so an empty one is
worth saying out loud in the comment beside it.

What the round bought, and how: four cards from the keyword alone (Merfolk
Raiders, Sandbar Crocodile, Teferi's Drake, Teferi's Isle); two more from two
new phase-out subjects — the ability's own source (`phase_out_self`: Mist
Dragon, Crystal Golem, Vaporous Djinn, Warping Wurm, Frenetic Efreet) and a
sweep over a printed noun phrase (`phase_out_matching`: Taniwha's "all lands you
control"); and Teferi's Imp from the two `phases_in` / `phases_out` trigger
conditions, announced from the two seams that *move* a permanent rather than
from the untap step — the untap step is one of several ways to phase, and a
trigger wired there would miss Reality Ripple and every activated phase-out in
the set. The phase-out announcement fires **before** the permanent leaves,
because the trigger scan reads battlefields and a permanent that has phased out
is on none.

**Two defects in already-supported cards, both found by giving one a game.**
Reality Ripple ("Target **artifact, creature, or land** phases out") compiled
supported, claimed every sentence and derived a correct picker — and then
declined two of its three types at resolution, because the handler took
`resolve_target_permanent`'s default predicate, `is_creature`. It logged "no
valid target" and the spell resolved having done nothing. The fix reads the
printed noun phrase through the same `subject_matches` the picker enumerated
with, which also newly enforces Teferi, Master of Time's "creature you don't
control" at resolution rather than only at announcement. And the land support
gate did not classify keyword lines at all, so Teferi's Isle reported "no static
ability of this land is implemented: Phasing" — the creature front end's
`_is_supported_keyword_line` now answers for both.

`oracle_diff` after the round: **21 changed of 2181**, every one a Mirage card
(the eleven from round 1 and ten more here). Still open in this family: Dream
Fighter (a conjoined subject, "this creature **and that creature** phase out"),
Spatial Binding ("can't phase out"), and the three cards that *grant* phasing —
Cloak of Invisibility (two effects on one Aura line), Teferi's Curse ("Enchant
artifact **or** creature") and Shimmer (a chosen land type). None is a phasing
gap any more; each is now blocked on something else.

### Round 3 — the flash-Aura cycle (CR 113.6b): 204 → 206 supported

**The one place Mirage's sentence census has leverage in it.** Five Auras —
Armor of Thorns, Grave Servitude, Lightning Reflexes, Soar, Ward of Lights —
print the identical sentence, and it is the only printed line in the set that
more than two unsupported cards share:

> You may cast this spell as though it had flash. If you cast it any time a
> sorcery couldn't have been cast, the controller of the permanent it becomes
> sacrifices it at the beginning of the next cleanup step.

`engine/cast_timing.py` is the new table, and it is the **mirror** of
`cast_restrictions.py` rather than an extension of it: that one narrows legal
timing and fails by casting a card too often; this one widens it and fails the
other way, by refusing a cast — which breaks no rule and fails no test, because
a spell nobody can cast simply never appears. It is a third axis from
`cast_permissions.py`, which is about *where* a spell may be cast from.

**Both halves or neither**, and `cast_permission_line` says so out loud: the
permission alone would ship five Auras that can be flashed in and never
sacrificed, a strictly better card than the one printed. The rider is enforced
across three places, none of which knows the sentence — the cast path freezes
whether a sorcery could have been cast (a `StackItem.choices` key, because
CR 601.3d's timing is a fact about the moment of announcement and by resolution
the stack has emptied down to this spell), the permanent spell's resolution
copies the answer onto the permanent, and the cleanup step sweeps what is
marked.

`CardDefinition.has_flash`'s docstring had predicted the shape exactly — "a
granted flash is a permission about a card outside the battlefield, so it will
arrive as its own seam on `Game`, not here". It did. And the seam **removed** a
second copy on arrival: the web layer spelled the sorcery-speed gate twice
(`web/actions.py` and `web/state_view.py`), so a third source of the answer
would have been two more places to forget it. Both now ask
`casts_at_instant_speed`. CR 601.3d's timing predicate is likewise now one
function with two readers — `activation_restrictions`' "Activate only as a
sorcery" and this cast path ask the same CR sentence.

**One guard was blind in a way worth fixing rather than working around.**
`test_stack_item_choices` scans for a `choices` key as a *string literal*, so a
key named once as a module constant and imported by its three users read as
declared-and-unused — the guard rewarding four copies of a literal over one
constant. It now resolves a module-level `NAME = "literal"` before matching.

`oracle_diff` after the round: **26 changed of 2181**, still every one a Mirage
card. Two cards land (Lightning Reflexes, Soar); the other three are now blocked
on one clause each and nothing to do with timing — Armor of Thorns on "Enchant
nonblack creature", Grave Servitude on "gets +3/-1 **and is black**", Ward of
Lights on "has protection from the chosen color. This effect doesn't remove this
Aura."

### Round 4 — a player-quantity intervening-if (CR 603.4): 206 → 209 supported

Three cards, one printed shape with the threshold as data: "at the beginning of
each &lt;player&gt;'s &lt;step&gt;, **if that player has &lt;N or more/fewer&gt;
&lt;quantity&gt;**, this artifact deals 2 damage to that player" (Misers' Cage,
Paupers' Cage, Razor Pendulum). The intervening-if machinery was already there
and worked for "if that player **controls** a Forest"; what was missing was two
condition productions and one English word.

- "&lt;player&gt; has &lt;N&gt; cards in hand" is the *same question* the
  possessive spelling already asked ("your library has ten or more cards in
  it"), so it produces the same node and reaches the same evaluator — one
  behaviour, two printed word orders.
- "&lt;player&gt; has &lt;N&gt; life" is a new node, because a life total is
  not a pile: `getattr(player, "life")` returning an int where the zone branch
  expects a list is a near-miss that answers rather than failing.
- **"fewer".** `parse_comparison` knew "less", "greater" and "more". Magic
  prints "fewer" for countable nouns and "less" for life, so every printed
  threshold over cards or creatures had been refusing. One row.

**Two live CR 603.4 defects, both found by giving a card a game.**

*The upkeep step never checked an intervening-if at all.* Only the resolution
re-check downstream, so a gated upkeep trigger went on the stack and was talked
out of it on the way down. That is not the same ability: one that never
triggered holds no priority, cannot be countered, and nothing in response sees
it — the end step has said exactly that since round 45. The gate now sits
*above* the `UPKEEP_EFFECTS` lookup rather than in either branch, because
whether an ability triggered is prior to how it is carried out, and the
pay-or-consequence handlers reach the player without ever building a stack
object to re-check.

*The end step's gated scan enqueued without the seat.* It stamped
`event_subject_player` on the catch-all path and not on the gated one, so a
condition naming "that player" passed the fire-site check and failed the
resolution re-check — Razor Pendulum fired at exactly 5 life and then logged
that its condition was no longer true. Both the check's context and the
enqueued event carry the same stamp now.

**The grammar's size guard fired at integration, on nobody's branch**:
`ast/conditions.py` crossed 1,000 lines. The cut is the one
`lowering/conditions.py` had been drawing in prose card by card — a condition
answered by looking at the game **now** (a board count, a zone's height, a life
total, whose turn it is) against one answered by looking at a **record** of
something already done ("if you do", "died this way", "if you've gained 3 or
more life this turn"). The new module is `ast/records.py`, reusing the name
`grammar/records.py` and `lowering/_records.py` already carry, so the mirror
re-forms across all three layers instead of forking a fourth vocabulary.

And the split found a stale list under it: `ast.Condition` had drifted
**twelve** entries behind the module it names — `ZoneHasCards`, `MilledThisWay`,
`CouldNot` and nine more were nodes the parser produced and the union did not
know about. Nothing failed, because a `Union` alias is documentation at runtime.
It is complete now and `test_the_condition_union_names_every_condition_node`
keeps it so.

`oracle_diff` after the round: **29 changed of 2181**, still every one a Mirage
card — the "fewer" row moved no existing card, which is the reading to expect
for a word that was previously a hard refusal.

### Round 5 — the Enchant clause's fourth quality (CR 702.5): 209 → 213 supported

Four Auras, all refusing at their **attachment** line while every other line on
them read fine: "Enchant **black** creature" (Decomposition), "**nonblack**"
(Armor of Thorns), "**red or green**" (Mind Harness) and "**artifact or
creature**" (Teferi's Curse). A colour is a fourth independent half of
CR 702.5's [quality], so it composes with the noun, the seat and the
keyword-exclusion instead of multiplying rows; a union of *nouns* is the one
half that cannot compose, so it is a second alternative rather than a suffix.

**And widening the gate broke two readers keyed on the old shape, exactly as
CLAUDE.md's Phase 3 note says it will.** `auras.aura_enchants` asked
`clause.startswith(noun)`:

- "red or green creature" answered **no** to every branch of the attach
  cascade, so Mind Harness resolved, reported supported, attached to nothing and
  stole nothing.
- "artifact or creature" answered **yes to both** branches, so the first one won
  and looked for a host of the wrong type — the Curse went to the graveyard
  reporting "no legal target" over a target the picker had offered and the cast
  gate had accepted.

Both are the same fix: the clause is reduced by `targeting.enchant_clause_nouns`
— the same three splitters the picker and the cast gate already use — and a
*union* dispatches on what was actually chosen. Neither defect is visible from a
compiled program; both were found by casting the card.

The round also closed round 3's one loose end: `parse_coverage.py` reads a card
sentence by sentence, and the flash cycle prints two, so `cast_timing`'s two
halves are two channels there rather than one.

`oracle_diff`: **4 changed of 2181**, exactly the four Auras.

### Round 6 — three narrowings the engine was dropping: 213 → 218 supported

Five cards, no new machinery, and every one of them a **restriction carried
rather than pinned**. The set's long tail is 101 cards blocked by exactly one
line, so from here a round is a handful of small families rather than one big
rock; these three were the cheapest.

- **The tuck pinned a type its card does not print.** `put_target_on_library_top`
  demanded `card_types == ("creature",)` in the lowering *and* `is_creature` in
  the handler — Reality Ripple's defect one file over, and found the same way.
  CR 400.3's owner lookup and the library move are the same for every permanent
  type, so Disempower ("target artifact or enchantment") and Fallow Earth
  ("target land") refused on a narrowing the effect has no opinion about. Both
  ends now read the printed noun phrase, through the same `subject_matches` the
  picker enumerated with — which is what keeps Disempower from tucking a
  creature.
- **The tap sweep's whitelist knew `colors` and not `excluded_colors`.** The
  sweep already resolves through `subject_matches`, which tests the key like any
  other, so the whitelist was the only thing refusing "Tap all **nonwhite**
  creatures" (Blinding Light). Dropping the word instead would have tapped the
  caster's own white team.
- **"…gains X and loses Y until end of turn" had no parse arm.** Two, in fact:
  the conjunction after a `gains` (Canopy Dragon) and after a `gets` (Leering
  Gargoyle), plus the self-subject keyword loss *with* a duration, which the
  durationless branch above it and the targeted branch below it both missed.
  Each is its own arm rather than a verb alternative inside the grant, for the
  reason `auras.py` keeps `_KEYWORD_REMOVAL` separate from `_KEYWORD_GRANT`: a
  grant and a removal are opposite contributions to one layer (CR 613.4/613.9),
  and folded together "loses flying" comes back as a grant of it.

`oracle_diff`: **5 changed of 2181**, all Mirage.

### Round 7 — two conditions built at one end: 218 → 222 supported

Both halves of this round are the **refusal-can-expire** shape, and one of them
had already been caught once in the same file.

- **"…has first strike as long as it's attacking"** (Purraj of Urborg, Spirit of
  the Night). `conditional_static_holds` has answered `is_state` since Snow
  Devil — but that payload only ever arrived from the grammar's *attached* path,
  an Aura's "enchanted creature has first strike as long as it's blocking". The
  same-subject spelling refuses in the grammar with the reason "derived by
  `engine/static_bonuses.py`", and that table had no row for a state of the
  permanent itself: every condition it knew asks what its *controller* has. An
  evaluator built at one end and connected at neither, with both halves
  individually correct and no test able to notice. The row's neighbour carries a
  comment describing exactly this, from the last time it happened.
- **"becomes colorless"** (Raging Spirit, Ersatz Gnomes). CR 105.2c makes
  colourless the *absence* of colour, so it cannot ride `COLOR_WORDS` — those
  values are mana symbols — and the layer-5 channel had to learn that the empty
  set is an answer rather than a missing one: `collect_color_effects` tested the
  key for truthiness, which reads "no colours" as "no override". It tests for
  None now, which is safe because every writer of that channel already refuses a
  falsy symbol at its own end. Raging Spirit also needed the source-subject
  branch of a durationed recolour; the two beside it read a chosen object, and
  reading the source as one would have recoloured whatever the picker offered.

`oracle_diff`: **4 changed of 2181**, all Mirage.

### Round 8 — a ceiling on how many creatures may block (CR 509.1b): 222 → 223

One card, one row, and it is here because the row is a template rather than a
card: "This creature can't be blocked by more than one creature" (Stalking
Tiger) is the **ceiling** to the floor `cant_be_blocked_by_fewer_than` already
carried, and Magic prints it on dozens of creatures. Its own kind rather than a
signed number on the existing one, because CR 509.1b makes every restriction
apply — a card printing both wants the tighter of each end, and one field
carrying a signed value could not say which end a number bounded. Checked over
the finished assignment beside the floor, because a count is a restriction on
the declaration and not on any single blocker pair (CR 509.1c).

**Order is the only thing that separates it from the general row.** "…can't be
blocked by &lt;noun&gt;" reads any bare noun phrase, and it matched "more than
one creature" as one — which produces a filter matching nothing, so the
restriction goes inert and the Tiger becomes blockable by *anything*. That is
the widening direction, so the specific row goes above the general one and its
test says so.

Everything after those two was the long tail, ranked by refusal site: `expected
a subject` (50 cards), `unconsumed text` (29), `unrecognized effect verb` (13),
then singletons. Rounds are planned from `--refusals`, and each is written up
below as it lands.

### Round 9 — the tutor cycle (CR 701.19): 223 → 226 supported

Two pieces of search machinery, both of which pay forward past this set.

**A search may find one of several printed types.** "an **artifact or
enchantment** card" (Enlightened Tutor), "an **instant or sorcery** card"
(Mystical Tutor). The lowering refused a union outright — "the search picker
tests one card type" — which was the safe direction and true of
`search_matches` as it stood. It is not true any more: that predicate now reads
the key as an OR, the same reading it already gave `any_colors` beside it and
the same one every noun-phrase matcher in this engine gives a multi-type filter.
The key takes a tuple *or* a word, so every payload written before is
byte-identical, and nothing outside the engine reads it — the client renders the
search prompt from the legal indices, not from the type.

**A search may put its find on top of the library, and the order is the
effect.** "…, reveal it, **then shuffle and put that card on top**" is the same
search with its last two clauses the other way round, and reading it as the
ordinary destination clause would place the card and *then* shuffle it back in —
the card doing nothing at all. So `library_top` is a third destination with its
own branch in the flow, which shuffles first and places after, and returns
rather than falling through to the shared shuffle below it.

`oracle_diff`: **3 changed of 2181**, the three tutors.

### Round 10 — the block relation, spelled out: 226 → 227 supported

One card and one token run: "Destroy target creature **this creature is
blocking**" (Wall of Corpses) is the relation Goblin Snowman prints as "target
creature **it's blocking**", written out. The lexer collapses a card's own name
to the self-reference, so under a self-scoped ability the two are one referent
and one already-implemented payload key; the parser knew only the pronoun, so
the spelled-out form failed the line on unconsumed text.

**The round's other half was written and reverted, and the reverting is the
point.** Urborg Panther's mirror sentence ("Destroy target creature **blocking
it**") refuses because `blocking_source` is deliberately not emitted as a
payload key. Making it emitted and testable — the symmetry the AST's own
comment argues for, since `subject_matches` takes the source exactly as it does
for `blocked_by_source` — turned out to buy **nothing**: the pronoun there
parses as `blocking_bound_target`, a different field, so the Panther still
refused, while three shipped Wurms gained a redundant key inside a count spec
that already carried it outside. A change with no card behind it and three
cards perturbed is the shape this repo refuses, so it went back. Urborg Panther
needs the *pronoun* rebound — "it" under an ability that targets nothing
earlier names the source — which is a round of its own.

### Wave 1 — five worktree groups, split by grammar family

After ten serial rounds the set had no big rocks left and 92 of its 108
remaining cards were blocked by exactly one line each, so the work changed shape
from "find the next keyword" to "one production per card". That is what a
fan-out is for. Five groups, one worktree each, split by **grammar family**
rather than by printed type — combat, turn steps, damage, zones, statics —
because a split by card type puts every group in `tests/sets/test_mir_creatures.py`
and in each other's productions.

The five per-set test files were opened on `main` first with the block
convention in their docstrings (FEM's lesson, applied before the fan-out rather
than after it), and the between-merges gate was built and verified clean at the
merge base: missing-name scan **before** the suite, dead-import and
newly-duplicated-definition scans, the per-set block sweep, the size caps, the
full suite, `check_all.py`. Integration is serial; the gate runs after every
merge, never at the end.

#### W1G4 — zones and cards: 227 → 240 supported

Thirteen of twenty-two. **Its correction of its own brief is the yield**, and it
is the refusal-site lesson four more times: Lion's Eye Diamond refused at
`expected a subject` and was blocked by its *last* sentence ("Activate only as
an instant"), one missing `activation_restrictions.py` row, with the whole cost
already parsing and charging; Jungle Patrol's cost-path refusal was Scryfall
listing "Token" among the **supertypes**, so the noun parser ate the singular as
an adjective and the phrase had no head noun; Cadaverous Bloom's mana
alternatives have been one payload since Alliances and only the hand-exile cost
was missing; and Afterlife's "no exile in this effect" was not a missing
producer at all — the destroy handler had been writing that seat all along under
a second name.

**Five already-supported cards it found silently mis-playing**, every one
reporting supported while dropping the sentence that *is* the card:

| Card | What it does instead |
| --- | --- |
| Tombstone Stairwell | pays escalating cumulative upkeep and never makes a Zombie or destroys one — three of its four triggers have no instruction |
| Malignant Growth | accumulates growth counters and never makes the opponent draw, never deals the damage |
| Grim Feast | takes its 1 damage every upkeep and never gains the life — strictly *worse* than printed, against its own controller |
| Telim'Tor's Edict | draws the delayed card and exiles nothing ("you own **or control**" is a union of two seat relations the matcher ANDs) |
| Soul Rend | draws the delayed card and destroys nothing (a conditional destroy) |

And two outside its family, from `parse_coverage`: **Aleatory** and **Lure of
Prey** carry "Cast this spell only …" clauses nothing claims, so nothing
enforces them and both can be cast at any time.

#### W1G3 — damage and prevention: a hook **retired**

Thirteen of twenty-one, and the direction that matters: Bone Mask prints Reverse
Damage's whole sentence with a different rider, so CR 615.5's rider became a
production and `card_hooks['Reverse Damage']` died. The proof it was a duplicate
is that Reverse Damage's compiled program is byte-identical after the deletion.

Its four audits for silently mis-playing shipped cards all came back **false
positives**, and each was closed by giving the card a game rather than by
reading a payload: Gaseous Form stops combat damage in both directions and
Demonic Torment in one, which is what they print; Earthquake spares the flier
and Hurricane the ground creature. That is how an audit should close.

Brief corrections: Burning Palm Efreet's "no handler removes a keyword" was a
true statement and the wrong diagnosis — Vertigo prints the identical clauses
with a full stop and has worked since Ice Age, and joined with "and" the
conjunction loop never reaches the pronoun rider. One printed word. And
Floodgate's two refusals had stated reasons that had **stopped being true**.

#### W1G1 — combat: two live bugs in a shipped card

Eleven of twenty, including the two cards round 1 and round 10 had left open.
Round 10 declined `blocking_source` because making it an emitted, testable key
bought no card and perturbed three; this branch made the same change *with two
cards behind it*, which is exactly what that decline said it needed.

**Blaze of Glory was wrong twice, and had been since it shipped.** "Target
creature defending player controls" reached the picker as a bare creature spec
and the seat was enforced nowhere else, so the attacking player could grant the
permission to their own creature and the spell reported success. And its two
"this turn" flags were written by the handler, read by the blockers step and the
AI, and cleared by nothing — one cast made a creature able to block every
attacker, and *obliged* to, for the rest of the game.

The differential earned its keep on the way: reading "the" as a possessive
article made the where-clause parser swallow the "the" of "the number of", and
the noun parser's refusal escaped instead of rewinding — **26 shipped cards**
lost their where-clause, and nothing else would have said so.

#### W1G5 — statics and characteristics: four cards that were "supported"

Seventeen: thirteen from its list and four the picker sweep had flagged. **Three
of those four were supported only on their cantrip line** — Soul Rend, Telim'Tor's
Edict and Dazzling Beauty each print "Draw a card at the beginning of the next
turn's upkeep" beside their real effect, the cantrip compiled, the effect
compiled to nothing, and the card reported supported. Early Harvest resolved,
went to the graveyard and untapped nothing on every cast. The picker finding was
the symptom; the defect was one layer down.

Two more it found by reading compiled programs: `exile_target_permanent` ignored
every relative narrowing (it asked the pure matcher while the picker derived a
bare permanent spec), and "put a counter on it" after a targeted step lowered to
`add_counter_to_self` — the counter landed on the ability's source, or on
nothing when the source was a spell. Neither raised.

#### The integration, and what it cost

Four merges, each through the full gate. **The two hazards SET_PLAYBOOK names
both fired.** Two per-set test files came back as *two* conflict regions rather
than one, because both branches' helpers end with the same lines and git read
them as common context — a naive union would have spliced one group's helper
body onto the other's signature, so all of them were reconstructed from the
merge base (base + ours-tail + theirs-tail, both sides asserted to start with
the base byte for byte) and then swept: every block of every branch present.
And W1G1 and W1G5 each added a *different* field to `LordBuffFilter` and to both
halves of its round trip; git presented each side as a rewrite of the same three
places, and taking either would have silently dropped the other's card.

`engine/grammar/conditions.py` crossed the thousand-line guard at integration on
nobody's branch, four groups' additions merely summing — the guard surfacing a
boundary that was already there. The record-asking half moved down into
`condition_clauses.py`, the cut `ast/conditions.py` and `ast/records.py` already
draw one package over. The missing-name scan then named **six** bindings the
move left behind, before the suite ran.

**After four merges: 227 → 276 of 335 supported, 59 left.**

#### W1G2 — turn steps: a player at -7 life who never lost

Twelve of twenty-one, plus two mis-plays fixed and one card's ability free.
**Forsaken Wastes drained the wrong player on both upkeeps** — "that player
loses 1 life" hit the opponent twice and its own controller never, because the
life-loss lowering had a "that player" branch for events about an *object* and
none for events about a *player*. And **Spatial Binding's "can't phase out" was
a read with no writer**: `resolve_phasing_for` had been checking a metadata key
since phasing landed that nothing in the engine ever wrote.

The finding it could not fix, and the wave's worst: **Soul Echo is strictly
stronger than printed**. "You don't lose the game for having 0 or less life" is
live, the enters-with-counters half produces nothing, and the upkeep trigger
that would sacrifice it is unsupported — verified in a game, a player at **−7
life never loses, forever**.

#### After the wave: 227 → 288 of 335, 47 left

| | Wave 1 |
| --- | --- |
| Cards landed | **61** (13 + 13 + 11 + 17 + 12, minus overlaps) |
| New name-keyed hooks | **0** — and one *retired* |
| Cap splits | 5, four taken in-branch and one at integration |
| Serial suite | 12,758 → **13,324** tests, green |
| Hollow lines | 8 → **6** |
| Picker findings | 5 → **3** |
| Unclaimed parse sentences | 25 → **16** |

**The instruction that did the work was "make a hook the last resort,
explicitly".** Five independent agents under it produced zero new entries across
61 cards and deleted one — the third wave in this repo's history to move hook
reliance the right way while the pool grew.

**Every group corrected roughly a third of its own brief**, as the playbook
predicts, and the corrections were never quibbles: "the combat family" was the
wrong frame for half of W1G1's list; W1G2's turn-step machinery needed almost
nothing and six of its twelve cards were ordinary noun-phrase work; three
refusal sites named a layer that was not the one that failed (Lion's Eye Diamond
blocked by its *last* sentence, Burning Palm Efreet by one printed word,
Abyssal Hunter by its recipient rather than its amount).

**The post-wave duplicate-*idea* sweep found one**, which is what it is for —
the duplicate-*name* guard cannot see it. `grant_reverse_damage_shield`,
`grant_exile_prevention_shield` and `grant_whole_prevention_shield` are one
instruction spelled three times: identical bodies differing only in which
`make_*` builder they call, and `Shield.kind` already carries that difference.
Five builder pairs underneath repeat the same two lines. It predates the wave
(the wave added two of the five), nothing is wrong, and collapsing it wants its
own differential — so it is a Known gap in SET_PLAYBOOK rather than an
end-of-wave refactor.

### Wave 2 — the last 47, five groups again

Briefed from wave 1's declines rather than from the census: every group got its
cards as *enumerated missing pieces*, which is the highest-leverage thing a
decline can be. Two of those pieces turned out to be one clause each.

#### W2G3 — damage: seven, and the shield gap closed unprompted

Reign of Terror, Builder's Bane, Seeds of Innocence, Benevolent Unicorn, Binding
Agony, Circle of Despair, Reflect Damage — merged with **no conflicts at all**.

It cleared the Known gap wave 1 recorded, without being told to: one
`chosen_shield_source` reader of "a source of your choice" shared by all five
shields *and* by a redirect, one arming body, one builder behind ten named
wrappers. And it was right to stop where it did — the four instruction *kinds*
stay four, because `Shield.kind` is read by `targeting.py`'s picker table and
`effect_labels.py`'s buckets as well as by the interceptors, so folding them
moves every affected card's compiled program.

Six brief corrections, every one the same shape as wave 1's: **Circle of Despair
needed no new prompt at all** — `choices["chosen_source"]` has been a declared
announcement field since Jade Monolith, and it was the *handlers* misusing the
target channel. Binding Agony's "even the simplest attached trigger refuses" was
untrue: one table row and one call.

#### W2G5 — statics: six, and a game that could not be read

Shimmer, Psychic Transfer, Jabari's Influence, Waiting in the Weeds, Null
Chamber, and Dazzling Beauty (already "supported", doing nothing).

**Runed Halo, shipped, made its own game unfetchable.** Its enter-choice prompt
raised `KeyError: 'needs_color'` out of `/api/sessions/{id}/state` — so the
prompt could not be shown and the choice could not be answered. The card-name
shape had no branch in the API's answer chain either.

**And the fifth piece of Shimmer is the one to remember.** `statics._lord_filter`'s
round trip proves the *table* can carry a restriction and says nothing about the
emitted instruction: `lord_buff_payload`/`lord_buff_from_payload` is a **second,
unchecked** round trip, and `chosen_land_type` passed the first and was dropped
by the second — an anthem that compiles, reports supported, and gives phasing to
every land on the board. Two round trips, one checked.

#### W2G2 — upkeep and counters: Soul Echo can lose again

Four newly supported (Grave Servitude, Purgatory, Hall of Gemstone, Consuming
Ferocity) and **three that were already counted supported and did nothing** —
Soul Echo, Afiya Grove, Energy Vortex. The set's hollow-line population went
4 cards / 8 parts to **1 card / 3 parts**.

**The merge's one real collision was semantic rather than textual**, and the
first of its kind in either wave: this branch and W2G3 each added a damage
replacement and both claimed order slot 6. `engine/replacements.py` compares
orders across both registries and raises at import, so the merge had to *decide*
rather than combine — Benevolent Unicorn changes the damage's **amount** and
belongs beside the cap, Soul Echo **substitutes the event** and has to run after
the amount is settled, because how many counters come off is "for each 1 damage
that would be dealt". 6 and 7.

Six brief corrections, four of them the shape every wave has produced — the
stated blocker was already built. Soul Echo's enters-with-counters half has
worked since Iceberg and everything *downstream* was missing; Purgatory's
linked-exile store already reached the battlefield; Energy Vortex's seat had
been frozen since Takklemaggot. And one that is worse than a refusal: Consuming
Ferocity's "standalone sentence parses" was true, and it lowered to a damage
instruction with **no recipient at all** and the Aura as the dealer.

#### W2G4 — zones and cards: nine, and 18 shipped cards fixed by one regex

Hakim Loreweaver, Ebony Charm, Flash, Ether Well, Phyrexian Dreadnought, Bazaar
of Wonders, Meddle, Mind Bend, Sirocco — nine of ten, declining only Forbidden
Crypt, which it was told not to half-ship and did not.

**A colour-word text change had never reached `non<colour>`, and had not since
Alpha.** `` does not fit between "non" and "black", so Sleight of Mind, Mind
Bend and 16 more never rewrote the compound word — Terror, Dark Banishing,
Blinding Light, Exile and Hellfire among them. Mind Bend's own reminder text is
the evidence: "change 'nonblack creature' to 'nongreen creature'". **The oracle
differential cannot see a text-keyed table**, which is the rule this group
proved by obeying it: it ran a *second* differential over `text_changes._forms`
and that is where the 18 showed up.

Its brief corrections were the sharpest of either wave. **Flash's "one clause"
would have shipped a card that reports supported and does nothing**: the
sentence the brief called "compiles clean right now" lowers to a kind only the
upkeep registry dispatches, with no `EFFECT_HANDLERS` entry — and "sacrifice it"
bound to the *spell* rather than to the creature just put down. Ebony Charm's
`player_choice` could not be "chained in front" because it records and discards,
so it needed a spec whose *resolver* arms the pick; Ether Well is a rider on the
**first** sentence's node, because "instead" is one zone change with two ends and
two statements would tuck and then move again.

Reported and left alone, one module over: **Night Soil's "from a single
graveyard" cost is unenforced** — `exile_same_zone` reaches `targeting.py`'s
picker spec and nothing else, so the cost can be paid with one card from each of
two graveyards.

#### W2G1 — combat: ten of ten, and a brief that was wrong seven times

Barbed Foliage, Mtenda Lion, Reparations, Dream Fighter, Coral Fighters,
Mindbender Spores, Basalt Golem, Barreling Attack, Blind Fury, Acidic Dagger.
Zero declined, zero new hooks, and it closed one of the two deliberately-open
cards named below.

**Seven brief corrections, all one class**: a piece the brief called missing
already existed, so the real work was one layer in. The plain attack trigger
already froze the defending player; a conjoined subject already had a production
and could not read a *bound* phrase inside the union; the granted-ability line
and the counter-conditional untap lock both already worked, and only the counter
*placement* was absent. Acidic Dagger's activated ability, whose whole effect is
two delayed triggers, was the piece the brief said would be the most work and
the piece that already parsed — while "an `activation_restrictions` row, cheap
and standalone" was the one that was not, because a row with no card behind it
is a claim nothing checks.

**Mindbender Spores' grant did not refuse; it mis-aimed.** On the *blocks* half
of a block trigger the stack item's target is the blocking creature itself, so
"the creature gains …" fell through to the target-shaped reading and granted
both abilities to the Spores. Unsupported at the time, so nothing shipped was
wrong — and the group swept the pool for the class rather than stopping at its
own card. Three sweeps, all closing clean on shipped cards.

### The integration's own findings — five cap breaches on nobody's branch

Wave 2's merges cost more than wave 1's and every extra hour was the same shape:
**a guard fired at integration that no branch had broken**, because two groups'
additions summed past it. Worth recording as a cost of the parallel model rather
than as five accidents.

Four grammar modules crossed the thousand-line cap in the last merge alone, and
each split along a line the code had already written down. `lowering/prevention`
gave `_lower_damage_becomes_counter_removal` to `redirection`, whose newest
arrival had just stated the taxonomy out loud — CR 614 replacements on a damage
event, separated by *which half they change*: recipient, amount, or whether it
happens at all. `triggers` shed CR 603.8's state triggers, its third split and
its third along a line the family already had. `lowering/destruction` gave its
fused cost-repeated destroy to `sequences`, the same move one of the branches
had just made with the tap-then-counters fuser, and the fuser's one piece of
destroy-specific data travelled with it — which is what made it a move rather
than a cut. `lowering/damage` gave `_sweep_kind` to `_sweeps`, ending a
half-exile two docstrings there already described. `engine/grammar/phrases.py`
had crossed one merge earlier and shed its **price** fragments, a seam it had
also already written down in prose: the mana alternatives lived there and their
three life-cost siblings did not, so one printed offer was read in two modules.

Two per-set test files crossed the 2,600-line guard the same way, one of them
**by a single line**, and both were cut at a section boundary rather than
mid-topic.

The lesson is cheap to state and was not obvious: *the size guards are the
integration's findings, not the branches'*. A group cannot see the sum, so the
integrator has to check every cap before the suite rather than after it — and
the import-hygiene guard is what then catches the bindings each split leaves
behind, which is the half of that hazard nothing else fails on.

### Wave 3 — the last twelve, five groups

Every remaining card was a *system* rather than a template, which is what the
first two waves bought. All fifteen items landed: twelve cards, the set's one
hollow card and both picker findings.

Each group found shipped defects beside its own cards. **W3G3's sweep is the one
to copy**: enumerate every instruction kind that appears as a `may`'s action
beside an `otherwise`, and ask which have no entry in `_action_is_takeable`. Two
did not, and four shipped cards were taking an offer nobody could afford —
Balduvian Horde accepted "sacrifice it unless you discard a card at random" on
an **empty hand**, discarded zero cards, and stayed on the battlefield for free.
**W3G1** found Chromatic Orrery and North Star honouring their spending
permission at one payment site out of four, so an {X} spell inferred X = 0, cast
successfully, and resolved for nothing. **W3G5** closed both picker findings and
both were worse than their labels: Sealed Fate reached its handler, logged "no
player chosen" and resolved **having looked at nothing**, on every cast.
**W3G2** closed the hollow card and turned 28 open-coded graveyard writes into
one CR 614 seam — whose guard caught another branch's code an hour after it
merged.

**Celestial Dawn was declined, and the decline was the useful half.** W3G1
compiled a probe card with line 1 replaced and the other two intact: it reported
**supported**, because a card is supported when *any* of its lines is. So
landing any single line would have shipped a card that compiles green and does a
third of what it prints. The three pieces went in as one round: a seat-narrowed
untyped land-type static, colour over three populations (board, stack, and
`engine/object_colors.py` — one reader where there were three, each reading the
printed field and two documenting that as deliberate), and CR 609.4b spending.
That last one fixed a shipped defect the decline had reported and left: all
three spending permissions were *stamped* on the seat at entry and never
cleared, so destroying Sunglasses of Urza left its owner spending white as red
for the rest of the game.

The line worth remembering: **"only as though it were colorless mana" takes away
the unit's own colour too.** Written the obvious way round — equality first,
because "as though it were" only ever adds — the card lets a seat cast
everything its own lands could have cast anyway, which is most of what the
restriction exists to stop.

### The promotion rehearsal, which found a fourth wave's worth of work

Phase 4 step 1 says the rehearsal is implementation work rather than a
formality. It has never been more true than here.

**Rehearsed at the wrong end first**, as the playbook says to: the order guard
fired naming index 13. The prefix guard beside it stayed green — and Mirage is
the first set where that documented silence has a **named card** behind it.
Volcanic Geyser is in MIR and M21 and nowhere earlier, so appended wrongly its
`original_printing` reads `m21`. Appending moves no *existing* card's origin,
which is all the prefix comparison tests; what moves is the new set's own card.

**A guard that re-spelled the thing it checks reported a working card as
broken.** The activation-clause census called its reader **without the card's
name**, so Hakim, Loreweaver's "Activate only if Hakim isn't enchanted" never
had its self-reference collapsed (CR 201.4). Given a game, the restriction
denies the ability exactly as printed. That failure looked precisely like a
finding, which is what makes the class expensive.

**And the rehearsal blocked the promotion, correctly: 13 printed sentences on 11
cards were unimplemented**, six admitted into the support gate by a *single
whitelist word* (`gain`, `loses`, `deals`, `prevent the next`). Every one of
those cards read 335/335 supported with **zero hollow lines**, because a card is
supported when any of its lines is and `--hollow-lines` only sees a line that
produced an ability part. `parse_coverage.py` is the one instrument that can see
this, and it gates on the shipped half alone — so the debt was invisible until
the manifest entry moved. The manifest went back to `measured` and a fourth wave
cleared it.

### Wave 4 — the thirteen sentences, four groups

All thirteen implemented, none declined, and it found more live defects than any
wave before it.

**Every "becomes the target" trigger in the pool was dead in the running app.**
`_stack_push_object` had three exits and only the last announced targeting — and
the middle exit is the one **the web layer always takes**, because it resolves
`target_permanent_ids` off the wire. Warden of the Woods is shipped and manually
verified; it never fired for a real player. Invisible to every instrument here:
the cards compile supported, carry no hollow line, claim every sentence, and
their tests drive the headless path that happens to take the announcing exit.

**Three shipped cards were charging life for casts that never happened.** Terror
of the Peaks and Pursued Whale deducted their tax above the support gate, the
timing gate, the target gates and the mana, so every refusal below left the
caster poorer for a spell never cast — and CR 601.2 is a rewind. Phyrexian Purge
charged 3 life for a zero-target cast, which the **AI simulator** caught rather
than a test.

**Roots of Life's second line compiled to no trigger at all**, and the cause was
one frozenset: three `chosen_*` keys were missing from
`_PAYLOAD_HONOURED_FILTER_FIELDS` while sitting in
`TESTABLE_SUBJECT_FILTER_KEYS` and being emitted unconditionally — a false
refusal of a phrase the payload carries perfectly well, and the fourth of its
exact kind.

Two of the four briefs were wrong in ways worth recording. The sacrifice cost
does **not** go on the pending-choice queue (a queued prompt puts the spell on
the stack before its cost is collected; CR 601.2b's choices arrive *with* the
action). And "Players can't gain life" is **not** a `REPLACEMENT_LINES` entry:
CR 119.7 says a replacement that would replace a life gain does nothing, so as
an interceptor the ban joins CR 616.1's contention set and the affected player
could take Lich's "draw that many cards instead" first — drawing off a gain the
rules say never happened.

### Where the set landed

**335/335 supported, 0 hollow lines, 0 picker findings, 0 unclaimed sentences,
and zero name-keyed hooks added across ten solo rounds and four waves.** The
pool is **2,181 cards, 100% supported, sixteen sets**; whole-pool hook reliance
is 2.8% of supported cards.

Mirage is **313 new cards of 335**, with 22 already in the pool — which breaks
the FEM/HML/ALL run of all-new sets and is why its insert position is
load-bearing. The deck editor's set filter shows those 313; the other 22 are
served under their earlier printing, which is "first printing wins" working.

Verified in a browser after promotion: a Mirage card casts and resolves, and
Celestial Dawn's three lines are visible in the UI itself — Wind-Scarred Crag
renders as `Land — Plains` producing {W} (CR 305.7 replacing the subtype *and*
the mana ability), and a Black Knight is drawn in a white frame while the land
beside it stays colourless. `simulate_ai_games --set MIR` is 12/12 with 588
interactions and no illegal ones; `--all` is 6/6.

**The in-game verification backlog is the honest remaining delta**: 313 new
cards, of which a handful auto-pass and some inherit `equivalent` from a passing
behaviour-class peer. Phase 5 deliberately does not gate promotion on it, and
the tracker stands at 515 passed / 0 failed / 27 equivalent of 2,181.

## Alliances (ALL) — shipped

**Final: 144/144 supported, hollow lines 0, unclaimed parse sentences 0, picker
findings 0**, and the manifest entry moved from `measured` to `sets` at
printing-order index 12 — between Homelands and Fifth Edition. The pool went
1,725 → **1,869** unique cards over fifteen sets. Ingest census was 62/144
(43.1%). Three waves of five worktree groups plus three closers; grammar
88.8% → **89.2%** parsed with every existing set's floor rising, hook reliance
3.6% → **3.3%** of supported cards. The suite went 11,547 → **12,758** tests.

**Zero name-keyed hooks across all 144 cards, and one retired.** The first set
to reach 100% without a single entry in `card_hooks.py` — 82 cards implemented
across three waves, none of them by name — while Serendib Djinn's bespoke
`upkeep_sacrifice_land_conditional_damage` became a general sequence, which is
what let Gargantuan Gorilla's near-identical paragraph work for free.

**Six already-shipped cards were mis-playing, and every one was *stronger* than
printed rather than broken.** That is the finding to carry. Spoils of War (ICE)
resolved as a silent no-op under AI play; Pyrokinesis, Fire Covenant (ICE) and
Dwarven Catapult (FEM) print "among … target **creatures**" and dealt their
whole amount **to a player's face**; Dust to Dust (DRK/5ED) and Ashes to Ashes
made the AI exile its *own* permanents. None was visible to any instrument: all
six compile supported, carry no hollow line, claim every printed sentence and
derive a correct picker. **The census, `--hollow-lines` and `parse_coverage.py`
all ask whether a line produced *something*; none asks whether it produced the
right thing**, and a card that is too strong crashes nothing and misses nothing.
Every one was found by giving a behaviour a game — five of the six as a side
effect of work on a *different* card.

**The wave-3 groups found their own subject that way too.** W3G5's ten
mis-playing Alliances cards were found by compiling its eleven cards and
printing their instructions side by side — a read no instrument makes — and two
of them (Nature's Wrath, Royal Decree) had their triggers lowered into the
card's *spell* instructions, so they fired never and were invisible to
`--hollow-lines` **and** to `--refusals` because they produced no ability part
at all. Only `parse_coverage.py` saw them, and only as "unclaimed text".

**Two modules crossed the 1,000-line cap with no branch at fault**, both
integrator splits: `lower.py` at 1,006 (four groups, a handful of dispatch arms
each) and `effects/cards.py` at 1,005 (two groups). `statement_dispatch.py` took
`lower_statement`'s 79 arms on `by_node.py`'s recorded principle — both halves
are dispatch, so the half that *grows per card* is the half that moves — and
`effects/exile.py` reused `lowering/exile.py`'s name so the mirror re-formed.
Groups took five more splits in-branch.

**The missing-name scan is now the thing to run before the suite, not after.**
It fired three times in one wave — 246 test failures the first time, when
`_guard_is_the_arms_own_precondition` stayed behind while its only caller moved.
The package imported clean every time. `test_import_hygiene.py` sees the *dead*
half of that hazard and structurally cannot see this one.

**A module split needs three scans, not two.** The wave-2 post-merge sweep found
`_parse_entering_counters` defined **byte-identically** in both halves of an
earlier split, with the only caller in the new home — W3G4's split had copied
rather than moved it. No guard can see that:
`test_no_module_defines_the_same_name_twice` looks *within* a module, and the
dead copy imports clean, tests green and is simply never reached.

**The per-set block convention hit its documented failure mode, and the
documented recovery is what saved it.** `test_all_artifacts.py` came back as two
conflict regions because two groups' `_put` helpers end with the same line, and
a naive union spliced four lines of one helper's body onto the other's. Three
tests caught it; reconstruction from the merge base with "both sides are pure
appends" asserted byte-for-byte fixed it. **Sweep every block after resolving
one**, not just the file that failed.

**The promotion rehearsal turned nine guards red and five were the guard.** The
`land_tapped_for_mana` fire-site guard kept its own list of the kinds that site
runs and reported two verified-working cards as undispatched; the
combat-restriction guard was missing a table-only kind; the divided-card
inventory's docstring said "Alliances is still `measured`" — the
emptiness-premise class for the **third** consecutive set, this time from
inside a test's prose. Only two were real, and both existed *because* the set
now ships: Suffocation's defining line did nothing and its cast restriction was
unenforced, and Tidal Control's client read a different activation cost than the
engine charged.

**Two of Suffocation's four declined parts were already built**, in
`engine/damage_ledger.py`, written two sets earlier for Backdraft: every damage
event of the turn is already recorded at the one `deal_damage` seam with its
recipient seat, source seat and source cast. The decline had been written from
`PlayerState` outward and never looked at the ledger. **A decline names where
its author looked, not where the mechanism is.**

**The differential needs a filter when a dataclass gains a defaulted field.**
Two rounds added one and reported 710 and 713 changed of 1,869 where ten and
seven had really moved. The repr is what makes the narrowing class visible, so
this is not noise to suppress — but a round that reports the raw count has told
the next integrator nothing. Now recorded in `scripts/oracle_diff.py`, along
with a fix for the compare crashing outright on a U+2212 in a moved card's
payload under a Windows console.

### The rounds, as they ran


**Census at ingest (2026-09-02): 144 cards, 62 supported (43.1%), 82
unsupported over 105 refused lines.** All 144 new to the pool, every one
`normal` layout, no planeswalkers — so Phase 2's first two sweeps are clean and
the whole set is text work. Its keyword field carries nothing in
`UNSUPPORTED_KEYWORDS` (only `Phasing` is gated, and ALL prints none); the tags
that look missing — Enchant, Cumulative upkeep, Regenerate, Mill, Scry — are
Scryfall's, not CR 702's, and are implemented elsewhere. Registered under
`measured` at release index between HML and M21; the promotion insert is
Phase 4's hand move.

**The ingest's own yield was the set's code.** `grammar_coverage.py` and
`hook_reliance.py` each build one row per manifest entry plus an aggregate
keyed `"ALL"` — safe for exactly as long as no set was called ALL. While the
set is `measured` the collision is loud: `_measures` drops it from the per-set
rows and then re-adds the string as the aggregate, so the guard proving a
measured set is never ratcheted reported a leak that was really the aggregate
wearing Alliances' code. **After promotion it would have gone silent instead** —
the per-set entry computed and immediately overwritten, `"ALL"` genuinely in
the baseline, and Alliances' own floor and ceiling simply absent with every
guard green. The aggregate is now keyed `set_argument.POOL_SCOPE` (`"<pool>"`),
a spelling no alphanumeric set code can take, both baselines migrated key-only,
and `tests/engine/test_scope_keys.py` asserts the shape and the *row count*
rather than today's set list — the count being the only assertion that can see
the post-promotion form.

**This is the first set where the leverage instruments agreed with the refusal
census at estimate time**, which is what HML's retrospective asked for. The
fragment census has real groups in it after four consecutive sets measured no
shared fragment at all:

| Fragment | Cards |
| --- | --: |
| `at the beginning of` | 17 |
| `until end of turn` | 13 |
| `of your library` | 13 |
| `exile the top` | 8 |
| `onto the battlefield` | 8 |
| `if this land would enter` | 6 |

The sentence census reads 1.02 lines per distinct sentence — the reading that
says a set has no leverage in it — and is wrong again, for the fifth time.

**Three instruments run at Phase 1 found what the census cannot see.**
`--hollow-lines`: five supported cards carrying an ability part with no
instruction behind it (Tidal Control, Dystopia, Death Spark, Tornado, Sol
Grail). `parse_coverage.py --set ALL`: 16 unclaimed sentences on 14 supported
cards, including **Force of Will's and Pyrokinesis' defining line** — the
alternative cost is claimed by nothing and both cards compile supported on
their other line. `picker_sweep.py --set ALL`: three findings, Arcane Denial in
the Roots class (text names a choice, derivation offers no picker, so the client
sends a bare cast) plus Tidal Control and Tornado.

### Round plan — wave 3, the closing wave. 125 → 144 the target

Nineteen cards left, and the split is no longer by fragment: the fragment
census is exhausted, and what remains is four families of singletons plus one
group that owns the population no census can see.

- **W3G1 — repeated additional costs (CR 601.2b).** Primitive Justice, Taste of
  Paradise, Undergrowth, Bounty of the Hunt. `you may pay {1}{G} **any number
  of times**` has no machinery anywhere in the engine — one grep, one hit, in
  `shields.py` about something else — and the load-bearing question is that
  "for each additional {1}{R} you paid" needs the *count* to survive from
  announcement to resolution, not the boolean Undergrowth alone would want.
  W1G4 named this in its own scope and it did not land. Bounty of the Hunt's
  pitch half already reads through `alternative_costs`, so it is its effect
  half only — the refusal census quotes that line because the census probes the
  grammar and the grammar is not its claimant.
- **W3G2 — chosen modes, counters, granted abilities.** Fatal Lore, Misfortune,
  Nature's Blessing, Martyrdom. W2G4's modal head and CR 700.2e chooser are
  built, so two of three lines already read on both modal cards; what is
  missing is a draw with a **ceiling the drawer chooses under**, and an ability
  **granted in quotes**.
- **W3G3 — iterative library procedures.** Gustha's Scepter, Helm of Obedience,
  Phyrexian Portal, Lim-Dûl's Vault. Each is a *procedure* rather than an
  effect. The machinery is mostly there and unobvious: `pending_choices`
  already makes the game wait through a chain of decisions armed by answering
  earlier ones (CR 608.2 / 117.3b), `resumption.py` already lets a loop record
  the rest of itself, and W2G4's `effects/search` is the first parse-only
  family. Briefed to prefer two verified cards with two individually-named
  declines over four half-built ones.
- **W3G4 — the creature singletons.** Sworn Defender, Stromgald Spy, Benthic
  Explorers, Soldevi Sentry, Gargantuan Gorilla. Two carry W2G1's enumerated
  declines as leads, and one of those leads is already half disproved:
  `engine/revealed_hands.py` exists and `web/serialization.py` reads it, so the
  Spy's "without which the card is hollow" part is done — but the module is a
  table of *static* lines and the Spy's is a one-shot with a duration.
- **W3G5 — the cards that already look done.** Winter's Night and Omen of Fire
  are the only unsupported two; the group's real subject is the four hollow
  lines (Tidal Control, Dystopia, Tornado, Sol Grail), the two picker findings
  (the same cards again), and the five remaining unclaimed parse sentences.
  Its leverage is that Dystopia, Nature's Wrath and Omen of Fire all print
  `sacrifices a <X> or <Y> permanent of their choice` — three cards, one
  production. This is the group that decides whether the set can be promoted
  honestly, and its brief says so: three numbers must reach zero.

### W3G1 — repeated additional costs. Merged; 125 → 128.

Three cards (Taste of Paradise, Undergrowth, Bounty of the Hunt), Primitive
Justice declined to one part with four pieces, zero hooks. ALL's grammar row
79.7% → **81.3% parsed**. The differential moved exactly three programs of
1,869 — including after a `statements.py` change that puts a trailing delay
*inside* a `ForEach` rather than around it, which touches every card printing a
delay after its effect and moved none of them.

**The subsystem was one property, not a gate.** `cast_costs.py` already read
life, discards, sacrifices and exiles — and every one of them is **mandatory**,
which is what makes CR 601.2h's check a refusal. An *offer* is not a price: it
never belongs in `_unpayable_additional_cost` at all, because an offer nobody
takes costs nothing, and one taken past the pool is refused by the mana payment
itself, which already spends nothing on the way to refusing. Three small edits
to the casting seam rather than a new one.

**What actually decided the shape was that one printed sentence offers two
costs independently** (Primitive Justice's `{1}{R} and/or {1}{G}`), so the cost
carries a tuple and the record a dict keyed by canonical symbols — and the
canonicalisation has to be *one* function shared with the payment
(`mana_payment.mana_cost_label`), or the sentence and the charge quietly name
different offers.

**Three of wave 1's four named blockers for Bounty of the Hunt were wrong, and
its whole first half already worked.** W2G2 had shipped the enumerated bound
complete — `_accept_target_bound` reads "one, two, or three" and names the card
in its own comment. The iterator was not a `_parse_for_each_this_way` row (that
reader wants `for each <word> <participle> this way`; here the noun is a PT
token and the participle a four-word relative clause, so nothing was consumed
at all), and the removal needed the *counted* twin of the bound removal Giant
Oyster already had — eight lines.

**The CR 603.7 choice the brief called open was closed by the card.**
`arm_self_action_at_next_end_step` is per-*permanent* metadata swept in the
**end** step; Bounty's ability names the **cleanup** step and its source is a
spell already in a graveyard, so there is no permanent to hang it on.
`create_delayed_trigger` was the only one of the two that can express it — and
W1G5 had already written the `next_cleanup_step` opener row *and* its fire
site, naming the card. The one missing half was `next_cleanup_step`'s absence
from `_BOUND_OBJECT_DELAYED_EVENTS`.

**A shipped card resolves as a no-op under AI play, and the round found it by
accident.** Spoils of War (ICE) logs "no creatures were given counters" and goes
to the graveyard every time the AI casts it; Contagion and Bounty of the Hunt
share the shape. `ai_policy.CastAction` has no `divided_targets` field, so a
divided spell is announced with no division at all — and
`_cast_onto_stack` runs `division_refusal` **only** `if divided_targets is not
None`, so CR 601.2c never gets asked and the spell is castable with no legal
creature on any battlefield. The **damage** twin falls through to ordinary
target resolution instead, which is why Fireball works under AI play and the
counter family does not. Sent to its own closer branch rather than fixed in
place: the resolution-time default cannot be chosen without the counter's
**sign** — all counters on the caster's first creature is right for Bounty of
the Hunt and hands Contagion's −2/−1 to its own caster — so the decision is
`ai_valuation.py`'s, derived from the compiled program.

### W3-divided — the divided-target announcement. Merged; three shipped cards were mis-playing.

A closer branch off W3G1's accidental finding, and the finding grew by an order
of magnitude on contact: **ten cards print a divided target and all ten were
castable naming nothing at all** — verified on an empty board before the fix,
every one returning `supported=True, 'resolved'`. `_cast_onto_stack` ran
`division_refusal` only `if divided_targets is not None`, so CR 601.2c was
never asked of the announcement that omitted one.

**The two failure modes are opposite and the quieter one is the dangerous one.**
Where the effect places counters the spell resolves into a no-op — Spoils of
War (ICE, shipped), Contagion and Bounty of the Hunt log "no creatures were
given counters" and go to the graveyard. Where the effect deals damage the
older single-target path reads `target_player_index` and **hits the face**:
Pyrokinesis, Fire Covenant (ICE, shipped) and Dwarven Catapult (FEM, shipped)
all print "among … target **creatures**" and all three dealt their whole amount
to a player. Nothing crashed, nothing was missing, and the cards were simply
*stronger than printed* — which is the class an instrument cannot see, because
every one of them compiles supported, carries no hollow line and claims every
printed sentence.

**W3G1's brief said the damage twin was fine and that is what made the round
worth running.** "The damage twin falls through to ordinary target resolution,
which is why Fireball works" is true of the four **any-target** burn spells and
false of the three creature-only ones — the fall-through *is* the bug when the
card cannot target a player. Four of the ten (Fireball, Pyrotechnics, Meteor
Shower, Fiery Justice) were correct throughout and stayed byte-identical.

**The floor was a new question, not a reachable old one.**
`division_refusal`'s "an absent division is never a refusal" is right and stays
— an evenly-divided spell announces nothing and a non-interactive seat takes
the even split. What is refusable is an absent **target**, which is a different
clause (`named_targets`); making the existing predicate reachable would have
refused nothing.

**And the resolution-time branch splits rather than raises.** With the floor in
place it is still reached two ways, and only one is a defect: every announced
target having left by resolution is CR 608.2b and must not crash, while a
target named the older way with no division is a lawful announcement the
handler was ignoring. The second now gives that target the whole amount
(CR 601.2d permits one target taking all of it). Both run through the *divided*
placement loop rather than falling into the generic single-target path below —
which matters, because only the divided branch writes `counters_placed_this_way`,
so the other route would have placed Bounty of the Hunt's counters and left its
cleanup-step removal unarmed.

**Declines, as named parts.** `legality._enumerate_targets` ignores a divided
description's `controller` filter, so Dwarven Catapult's picker offers the
*caster's own* creatures for "all creatures target opponent controls" — the AI
is unaffected and a human in the browser is not; the parts are reading
`filter.controller` in the seat loop the way `own_only`/`opponent_only` are
read, and deciding whether the engine should model that card's target as the
opponent, which is what the card actually says. And `_pick_x_value` reads only
`{X}` in the mana cost, so Fire Covenant's X — announced in text and paid in
life (CR 601.2b) — comes back `None`; the parts are an X chooser that reads
`cast_costs.additional_costs`' life price and a policy for spending life on X.

### W3-justice — the last card. 143 → 144; the set is complete, zero hooks.

Primitive Justice, and the inherited decline was **half wrong in the direction
the playbook predicts**: of its four named pieces, one was already done, one was
the wrong mechanism, one does not exist as a problem, and only the fourth
survives — as an item this round deliberately did not take.

**The parse was already complete, and the decline never said which layer it was
in.** `parse_line` returns the whole three-sentence line as
`Sequence(Destroy, ForEach(EachAdditionalCostPaid, Destroy), ForEach(…,
Sequence(Destroy, GainLife)))`, with `distinct_from_prior=True` on both
"another"s — W3G1 built every bit of that. The refusal was one line in the
*lowering* (`_refuse_unfused_distinctness`), which is the taxonomy entry the
playbook asks each round to record and the decline did not.

**Piece 2 named the fix in its own refusal text, and pieces 1 and 3 dissolved
against it.** `_refuse_unfused_distinctness`' docstring says a shape that grows
a **fused** lowering is claimed above it and never reaches it, and
`_fused_two_target_pump` one family over is the worked example: two clauses, one
instruction, `count` + `distinct` on one target description. Three destroys over
disjoint targets *are* "destroy 1+n distinct target artifacts", so the fuser is
the whole of pieces 2 and 3 — there is no slot list to index into, because there
is one slot list and `destroy_target_permanent` has read one since Avalanche.
Piece 3's "the `for_each` body must name the i-th target" is a problem that
stops existing the moment the destroys are one instruction; what stays in a loop
is the {1}{G} clause's *life gain*, which is what the sentence prints.

**Piece 1 was right about the need and wrong about the shape.** There is no
`min_targets`/`max_targets` pair to derive, because the number is not derivable
from the card: it is `1 + n({1}{R}) + n({1}{G})`, fixed by CR 601.2c one step
after a CR 601.2b announcement that `derive_cast_spec` — which reads the
compiled program and nothing else — never sees. So the spec carries the
*arithmetic* (`cost_targets: {base, per_cost}`), exactly as `x_targets` carries
a flag rather than a number one branch over, and one reader
(`oracle_types.cost_target_count`) resolves it for the picker, the cast gate and
the AI. Three copies of that sum would be three answers, and the quiet one is a
picker offering a count the engine then refuses.

**The floor is real and it is the engine's only one.**
`legality.cast_target_refusal` now takes the announcement and refuses a cast
whose target count is not the one the payment bought, and refuses a repeated id
under the printed "another" (CR 601.2c: the same target can't be chosen twice
for one instance of the word). Both refusals land before any mana leaves the
pool. **This does not touch W2G5's negative finding**: "one or more target" still
has no floor and Heaven's Gate and its four colour siblings may still be cast
naming nothing. What makes the count answerable *here* and not there is that it
came from an announcement the same cast already made; a general floor is a
different change with a different blast radius.

**Piece 4 is still owed, and it is now owed by two cost kinds.** No client emits
`optional_cost_payments` — `_cost_picker_spec` models a *mandatory* cost, and an
offer needs an offer shape ("cast for {1}{R}, or for {1}{R} plus {1}{R} plus
{1}{G}?") that does not exist, plus a several-target collection whose maximum is
recomputed as the offer is answered. The card is supported and plays correctly
without it because the announcement a client *can* make — no offers — is the
one-target cast, which the existing single-target picker gets right. See
`web/schemas.py`'s `optional_cost_payments` and W1G4's twin item for the
alternative cost.

**The card that made a lowering module cross the guard also showed where its
family line was.** `lowering/destruction.py` went to 1,051 lines. The cut is the
three `… unless <someone> pays` productions: all three are parsed in
`effects/board.py`, all three are one printed shape with three verbs — an
*offer*, whose refusal is the effect — and the CR 701.7 split had carried two of
them into `destruction` while `_lower_sacrifice_unless_pay` stayed behind. They
are together again in `lowering/board.py` (959 / 641 lines), which is the mirror
re-forming rather than a size cut. Both scans were run after the move: the
dead-import one and a missing-name walk of every module touched.

**The AI could not cast the card at all, and the floor is what exposed it.**
`_choose_several_targets` derives which cards it answers for from
`max_targets` — a number this spec does not carry — so the seat proposed
Primitive Justice with **no target named** and was refused every turn:
`refused_casts` 81 over eight games, which is exactly the "a seat doing nothing
all game" signal the report exists to raise. The chooser now falls back to the
cost-sized count with no offers taken (which is 1, and one is still a number a
several-target handler has to be given, because it has no resolution-time board
scan to fall into the way a single-target one does). And
`ai_valuation._SLOT_DISPOSITION` gained `destroy_target_permanent: "opponent"`
beside the tap already there — a destroy is a denial — without which the
single-seat fallback pointed the spell at the caster's own artifacts. No shipped
card reaches either change: every other several-target destroy in the pool is a
sweep or announces its count off an X. After it: `refused_casts` empty,
`interaction_count` 383 → 412.

**And the entry beside it found two shipped cards.** `_SLOT_DISPOSITION` had no
row for `exile_target_permanent`, so Dust to Dust (DRK, 5ED) and Ashes to Ashes
— the pool's only two several-target exiles, both printing a bare noun with no
side in it — fell to the same single-seat fallback and had the AI exiling **its
own** two artifacts and its own two creatures, every time it drew either. No
instrument could see it: both compile supported, carry no hollow line, claim
every sentence and derive a correct picker. Fixed with the row and pinned two
ways (an invented card, and a pool sweep naming the two real ones).

**Verification.** 12,602 passed / 0 failed. `support_report.py --set ALL`
**144/144, 0 unsupported**; `--hollow-lines` 0; `picker_sweep.py --set ALL` 0
findings; `parse_coverage.py --set ALL` unchanged at 2 unclaimed sentences on 1
card (Suffocation). The whole-pool differential moved **exactly one program of
1,869** — Primitive Justice — with no defaulted-field noise, because the round
added no field to a dataclass the snapshot reprs. ALL's grammar row 89.6%
parsed, 88.8% → **89.2% lowered**, 69.7% → **70.1% executed**; hook reliance
0 entries over 144 supported cards.

### Round plan — wave 1, five worktree groups

Split by grammar family, ranked by the fragment census rather than the
sentence one:

- **W1G1 — the land cycle.** Six lands print `If this land would enter,
  sacrifice a <type> instead. If you do, put this land onto the battlefield. If
  you don't, put it into its owner's graveyard.` with one word changed, plus
  Sheltered Valley's unconditional variant. One CR 614 replacement for six
  cards; the highest-leverage single production in the set. Mishra's
  Groundbreaker and Storm Cauldron ride the existing `land_animation.py` /
  `land_play_allowance.py` tables.
- **W1G2 — library-top costs.** `Exile the top N cards of your library` as a
  component of an activation cost (CR 118.3) over six cards, plus Chaos
  Harlequin (the same phrase as an *effect*) and Soldevi Digger. Several need
  the exiled card readable by the sentence after the one that exiled it, which
  is the `permanents_from` arity question in `SET_PLAYBOOK.md`'s Known gaps.
- **W1G3 — Aura effect templates.** Eight `unimplemented aura effect` lines in
  four shapes: a conditional static with an `Otherwise` branch, two
  blocks/becomes-blocked triggers, three activated abilities whose cost is
  tapping the enchanted creature, and a reanimating death trigger.
- **W1G4 — alternative costs, CR 118.9.** The subsystem ROADMAP names as one
  of three structural gaps bounding everything after Innistrad, and Alliances
  is the set that pays for it: the pitch cycle (Force of Will, Pyrokinesis,
  Contagion, Bounty of the Hunt, Scars of the Veteran) plus the repeated
  additional cost (`you may pay {1}{G} any number of times`).
- **W1G5 — delayed triggers.** `at the beginning of the next <step>` over five
  cards, the graveyard-position pair (Krovikan Horror, Death Spark) and the
  graveyard→library-top production Lodestone Bauble bridges to.

Wave 2 holds the unblocked-attacker family (`defending_player` life loss,
poison, hand-revealing), the `An opponent chooses one —` modal, and the
remaining singletons.

### W1G1 — the land cycle. Merged; supported 62 → 70 (all eight cards).

Lands 1/8 → 7/8 (only W1G5's Thawing Glaciers left), artifacts 3/14 → 5/14,
**zero hooks added**, and the differential moved exactly the eight programs it
should have out of 1,869.

**The brief was wrong about both derivation tables and about the decline.**
`land_animation.py` is a board-wide static keyed to a land *type* ("All Swamps
are 1/1 creatures"), recomputed every pass — Mishra's Groundbreaker is a
one-shot *targeted* animation with an indefinite duration, a different
mechanism the file explicitly distinguishes itself from. `land_play_allowance.py`
existed but was `you`-scoped, so Storm Cauldron was a widening rather than a
lookup. And Storm Cauldron's second line, flagged as a possible decline, was
**the most valuable card in the group**: its refusal site was accurate and its
*layer* was wrong — `land_tapped_for_mana` already parsed and
`engine/oracle.py`'s condition table already produced the right
`TriggerCondition`, so the gap was one lowering branch plus one fire-site arm.

**The five-card cycle is not a `REPLACEMENT_LINES` job; it is both files with
one claim.** Frankenstein's Monster had already established the shape — the
"if you can't" half is a CR 614 interceptor, the cost itself is entry state,
and the claim for all three sentences lives in `enter_effects.py` and
deliberately *not* in `REPLACEMENT_LINES`, because three sentences are one
paragraph and claiming one twice is two claims free to drift. **The sacrifice
is mandatory-if-able**, not optional (CR, plus Gatherer's Lake of the Dead
ruling), which is what kept the web layer untouched: the only choice left is
*which* permanent, and the existing `sacrifice` pending choice already renders
that end to end. Read as optional it would have cost a new `ReplacementChoice`
kind, a renderer, an action handler, a schema literal and ~8 edits in `app.js`.

**Three silent defects, all in the name-reading path, all found by the first
card in the pool that names itself in its own rules text.** `parse_card_name`
swallowed a trailing seat clause — `permanents named X you control` produced
a name that matches nothing **and** dropped `controller`; both halves silent
and both toward a wider sweep. `_self_normalized` collapsed a card's own name
*inside* a `named` clause, so Sheltered Valley would have compiled supported
and sacrificed nothing, forever. And `_unread_land_text` handed
`enter_effect_line` a pre-collapsed line with no card name, so the gate and the
runtime reader were reading different cards — the exact hazard that function's
own docstring warns about, and every other caller already passed the name.

**A gate asymmetry worth its own round.** The artifact/enchantment support gate
asks "is *any* ability implemented" where the creature gate asks "is *every*
trigger". Storm Cauldron briefly compiled supported with its bounce line inert
the moment its first line was claimed. It was left alone deliberately — the two
shipped cards a tightening would fail on are legitimate (Howling Mine's
draw-step modifier and Creature Bond's Aura death trigger both live where the
compiler cannot see them) — but the population it admits is now named: in
measured ALL, **Sol Grail, Dystopia, Tidal Control, Tornado and Death Spark**.
Any group that makes one of those cards' *other* line supported ships a dead
ability.

Free for every set: **"or fewer" now parses** in the `you control N ...`
condition. `_compare_count` had answered "le" all along and nothing had ever
printed the word that reached it.

### W1G2 — library-top costs. Merged; supported 77 → 85 (all eight cards).

Zero hooks added, and the differential moved exactly the eight programs it
should have.

**Six of the brief's eight scoping claims were wrong in the same direction as
W1G1's and W1G3's: the machinery already existed, and the gap was a spelling.**
Chaos Harlequin's exile half already worked and the refusal was the *second*
sentence — "**that card** is a land card" is the pronoun with its noun spelled
out, where only "it was ..." had a production. Storm Elemental's read-back of
what the cost exiled was not an extra piece at all: the evaluator and the
channel had shipped with Soul Exchange, and the production demanded the past
tense (`the exiled <noun> **was** ...`) while the card prints **is**. Seasoned
Tactician's whole CR 615 effect half — shield, source-of-choice picker and all
— was already implemented, making the card cost-only. Phyrexian Devourer's
variable counter count already parsed and lowered; `+1/+1` was **excluded by
hand** from the branch that reads that exact sentence so older payloads stayed
byte-identical, which made the pool's commonest counter kind the only one a
variable count could not place. And cumulative upkeep was already implemented
for mana **and life and a sacrifice**, so a library exile was one field through
five small places.

**A third front end nobody names.** `When this creature's power is 7 or
greater` failed *twice* for different reasons, and then a third time: the
grammar needed a production, `engine/oracle.py`'s condition table needed a row,
and the `<name>_count` fan-out reads its numbers through `_NUMBER_WORDS` —
which holds **words only**, so the printed `7` came back `None` and refused the
whole condition after both front ends already read it. The playbook's failure
taxonomy has five layers; this is a sixth.

**Three shipped cards were activating an ability, paying its cost, resolving,
and tapping nothing.** `legality._ability_target_legal`'s `tap_target_permanent`
arm asked `permanent_matches_filter` — the **pure** half, which by design
cannot answer a keyword (layer 6), a controller (a seat) or "attacking you" (a
combat record), and **ignores** those keys rather than refusing. So the printed
narrowing was enforced by nobody at the gate while the *handler* still read it:
**Flood** (DRK/4ED/5ED) tapped at a flier, **Ice Floe** (ICE/5ED) at a creature
attacking someone else, **Shacklegeist** (M21) at its own controller's
creature. No crash, no missing ability — a cost paid for nothing. Fixed by
routing that arm through `subject_matches`, which the function's own generic
tail already documented as the right reader, with regression tests naming the
shipped cards.

**Two more of that class, declined with the reason, and the reason is the
finding.** Seasinger (HML) drops `controller_controls` through
`steal_target_linked_to_source`; the same one-line fix was tried and
**reverted**, because that arm also serves Orcish Squatters' "target land
*defending player* controls" — a seat belonging to the combat rather than to
the permanent, which `subject_matches` refuses outright. The swap trades a
widened picker for an empty one. The two phrases want different readers, and
that is a round of its own. And `grant_regeneration_to_target_creature` uses
the pure matcher too, saved today only by a gate further up — "safe by which
cards exist" again.

**Declines, as named parts:** CR 603.8 state triggers do not use the stack here
(Phyrexian Devourer is sacrificed inline in the state-based sweep like the
other three), so the rules-correct version needs a state-trigger *announcement*
path that enqueues instead of acting, plus CR 603.8's "doesn't trigger again
until it has left the stack" bookkeeping — two answers to one question if done
for one card. The bare imperative "Exile all cards from your library" (Leveler's
shape) is one branch away. And Varchild's War-Riders' `Cumulative upkeep—Have
an opponent create a token` remains the only unreadable upkeep cost in the
pool, wanting an `UpkeepCost` term for "an opponent does X".

**Cap pressure is now the integration risk.** `lowering/counters.py` crossed
1,000 on the group's first attempt and was rewritten as a widening of the
branch that already read the sentence, landing at 997; `subject_verb.py` sits
at 998. Seven grammar modules are within 50 lines of the cap. The next group to
touch one takes the split.

### W1G3 — Aura effect templates. Merged; supported 70 → 77 (7 of 8).

Enchantments 10/24 → 17/24, zero hooks added, and the differential moved seven
of 1,869 — all seven the group's own, no collateral across the other 313
enchantments.

**Four of the brief's claims about the seam were wrong, and all in the same
direction: the machinery already existed.** `Tap enchanted creature:` already
parses as a cost, is already paid, and three shipped cards already use it — all
three cards' real gaps were noun-phrase and restriction clauses. Veteran's
Voice's "Activate only if enchanted creature is untapped" was already enforced
verbatim; only Nature's Chosen's **colour** conjunct had a gap.
`AURA_REANIMATION_PHRASES` is Animate Dead's *enters* trigger and not False
Demise's seam at all — its blocker was one lowering branch, and the handler it
needed already existed for Seraph and Krovikan Vampire. **The verb was the
entire difference.** And a line the brief omitted from Bestial Fury turned out
to already work on `main`.

**Two already-supported behaviours were silently wrong, and one is the
attachment seam.** `aura_static_pt_grant` read "gets +N/+N" off *any* line, so
a P/T printed inside a **triggered** ability also became a permanent layer-7c
grant: Bestial Fury got +4/+0 the moment it attached, kept it through
opponents' turns, and got a **second** +4/+0 when actually blocked. Two
independent defects — no static/triggered distinction, and a duration check
that only looked immediately after the numbers, so "+4/+0 and gains trample
until end of turn" slipped between both — and the trample half being correct is
what hid it. Separately, `attach_source_to_target` asked `equip_refusal` at all
three sites, and that predicate's CR 301.5c guard refuses anything without the
Equipment subtype: **any Aura with its own attach ability got an empty picker
and an ability that logged "resolved" having moved nothing**, plus a log line
calling the Aura "no longer an Equipment". CR 701.3a says an attachment cannot
go where it could not "enchant, equip, or fortify, **respectively**";
`equipment.attachment_refusal` is now that *respectively*.

Two audits came back clean and are recorded as negatives so nobody re-runs
them: the 12 Auras whose trigger conditions no `attached_subject_triggers` call
scans all fire through `emit`/`event_filter` instead, and the 3 attachments
with two P/T readers genuinely print a static line *and* an activated one.

**Declined — Awesome Presence, four named parts:** a `combat_restrictions.py`
entry for the "can't be blocked unless a player pays a cost" template; a cost
scaled by the *declaration* (3 generic per blocker assigned to this attacker,
computed at CR 509.1b when the assignment is known but not yet legal); a
`PendingChoice` offering that payment to the **defending** player with
`holds_priority` so the step waits; and **a rollback of the block declaration**
when the payment is declined or unpayable, for which the declare-blockers path
has no seam today. Parts 1 and 3 are the ones another group may build
incidentally.

**Size watch:** `engine/auras.py` is now 2,111 lines. It is outside the grammar
cap, but it is visibly two files — the claim tables, and the attach/derive
machinery from `auras_attached_to` down — and should be split before the next
Aura-heavy round.

### W1G4 — alternative costs (CR 118.9). Merged; supported 62 → 62.

**The flat count is the finding, and the brief was wrong about the size in
both directions.** All three cards this round fixed were *already* counted as
supported, so the census could not move; what the round bought was
correctness. `parse_coverage.py --set ALL` went 130 → **133** fully claimed.

**"Alternative costs do not exist" was half wrong**, which changed the design.
`engine/cast_permissions.py`'s `CastPermission.free` already implemented CR
118.9's *waiver* ("without paying its mana cost") and `queue_from_hand` already
had the branch that skips the payment. What was missing was the **priced** half
— an alternative cost whose payment is something other than nothing — so the
new `engine/alternative_costs.py` is a sibling of `cast_costs.py` plus one `if`
ahead of the existing waiver branch, not a new subsystem. That reading also
produced a rule the scoping would have missed: **CR 118.9a forbids applying two
alternative costs, and a waiver is one**, so the two now exclude each other.

The *casting seam* was smaller than billed (one announcement site, one CR
601.2h gate, one payment fork) and the **blast radius larger**: `ai_policy.py`,
`ai_simulator.py`, `web/game_flow.py`, `web/schemas.py` and
`web/action_helpers.py` all had to forward the announcement, or the cast falls
back silently to the mana cost.

**Three shipped-adjacent cards were mis-playing, and one bug predates the set.**
Force of Will and Pyrokinesis compiled supported with the line they are famous
for claimed by nothing. **Surge of Strength cast discarding nothing** — its
additional cost was printed, unread and uncharged; the diagnosis took three
layers, and only the third was real (not a missing discard clause, not the
noun parser, but `any_colors` missing from `CARD_ONLY_FILTER_KEYS`, so nothing
could test the filter the parser had read correctly all along). Charging that
cost then exposed a **pre-existing** hole: `_cast_candidate` never asked
`_unpayable_additional_cost`, and **Village Rites with no creature on board had
the identical shape**. `refused_casts` is 0 across five seeds. Six stale
**CR 118.4** citations for the life-payment rule were corrected to **CR 119.4**
(118.4 is `{X}`).

**Unowned and worth taking early in wave 2: the bounded distributed target
count (CR 601.2c).** `_parse_distribute_counters` exists and works, but
requires the literal `among any number of`; Contagion prints `among one or
two` and Bounty of the Hunt `among one, two, or three`. The bound must also be
*enforced*, not just parsed. It unblocks **Contagion outright** and Bounty of
the Hunt jointly with the delayed-trigger work. Three of this group's five
refusal sites were misleading in the usual way — Contagion's "expected a mana
cost to pay" and Scars'/Bounty's "unconsumed text" are one failure at three
tokenizer offsets, and none of them is about a mana cost.

**One shape deliberately left unbuilt, and it becomes real at promotion:** the
wire carries `alternative_cost` / `alternative_cost_hand_index` to the engine,
but there is **no cost picker**, because `_cost_picker_spec` models a
*mandatory* cost and emitting one would make the UI demand the pitch on every
cast. An optional alternative cost needs an **offer** shape ("cast for {3}{U}{U}
or for 1 life + a blue card?") which does not exist. `picker_sweep` cannot see
it and the set is measured, so nothing is broken today — but this is a Phase 4
item, not a Phase 3 one.

### W1G5 — delayed triggers. Merged; supported 85 → 89.

Four cards landed (Thawing Glaciers, Krovikan Horror, Reinforcements,
Lat-Nam's Legacy) and two more were fixed without moving the count — which is
where the round's value is.

**Arcane Denial was a supported counterspell that countered nothing.** Its line
refused at `no draw handler offers a ceiling the drawer chooses under` — "may
draw **up to** two cards", nothing to do with the delay the brief named — and
because the *whole line* refused, `Counter target spell` compiled to **no
instruction at all**. The card reported supported on its second line's delayed
draw plus two `SUPPORTED_SPELL_PATTERNS` substrings. Its picker finding was a
symptom, not the diagnosis. Fixed, and the countered spell's controller now has
to be written down as the counter happens (`COUNTERED_SPELL_CONTROLLER`),
because CR 108.4 gives a card in a graveyard no controller and the ability fires
a turn later.

**Death Spark's decline was the opposite of what the brief said.** Nothing
claimed its trigger — there was no rival claimant to find — and the missing
piece was a **dispatcher**: `engine/phases/upkeep_step.py` had **no graveyard
scan at all**, where the end step has had one since Silversmote Ghoul. The
graveyard-position family is also three cards, not two: Nether Shadow (LEA,
shipped) prints the same clause and is claimed by a card hook.

**The graveyard→library-top production already existed**, written for Drafna's
Restoration (ATQ) — a fourth card in the family the brief did not mention — and
routed by the *quantifier* (`any_number`), a fact about how many cards move
rather than where they come from. The three ALL cards then failed in three
different places, only one of which was that production.

**CR 603.7 has two implementations here and only one uses the stack.** 26 pool
cards print "at the beginning of the next end step"; 8 arm a
`create_delayed_trigger`, twelve use `arm_self_action_at_next_end_step` →
per-permanent metadata swept in `resolve_end_step`, and six are per-card kinds.
Rakalite and Varchild's Crusader were driven headless and **both fire
correctly**, so this is not a bug — but nobody can respond to the second
mechanism, and it is invisible to `DELAYED_EVENTS`' fire-site guard.

**A test that baked in its subject's properties.** `test_graveyard_triggers.py`
held three of Silversmote Ghoul's facts as constants — which step announces it,
what its intervening-if wants armed, which zone it lands in — and each of this
round's three new subjects differed in a *different* one. All three are now read
off the card.

### W2G1 — combat triggers and restrictions. Merged; supported 89 → 97 (8 of 10).

Zero hooks added. Grammar 88.9% → **89.2%** parsed with every shipped set's
floor rising (HML 92.6 → 93.7, ATQ 90.0 → 90.8).

**A wave-1 decline dissolved on contact, and that is the round's transferable
finding.** W1G3 declined Awesome Presence naming four parts; **three of them do
not exist as work.** CR 509.1d–f put the payment *inside* the block declaration,
before 509.1g makes anything a blocker — so there is no `PendingChoice`, no
`holds_priority`, and **nothing to roll back**, because an unpayable declaration
is simply illegal and `declare_blockers` already refuses one with nothing spent.
`_block_declaration_mana_plan` already implemented the shape for Hipparion, and
the scaling was free: the plan sums per (blocker, attacker) pair, so a per-pair
`{3}` *is* "{3} for each creature blocking it". What was actually missing was
one template row plus a second channel in `_block_mana_costs_of`, which read the
blocker's program only while this cost is printed on the *attacker*. A decline's
named parts are a lead to re-probe, not a specification to implement.

**The seventh consecutive brief wrong in the same direction.** Gorilla
Berserkers' `Trample; rampage 2` was never broken — a keyword line's reader is
`oracle._is_supported_keyword_line`, and `normalize_creature_line` already
rewrites `;` to `,`, so the census was reporting the *grammar* refusing a line
the grammar does not own. And Whip Vine's untap-denial half was not missing
machinery either: `_holds_a_live_untap_lock` was fine and the gap was the
**pronoun**, the lock accepting `it` and the card's own name where Whip Vine
prints "That creature".

**Four shipped cards had their end-of-combat ability executed by a hard-coded
string probe.** Clockwork Beast, Avian, Steed and Swarm compiled their line as a
*static* and `end_of_combat_step.py` matched the whole printed sentence to run
it. Two defects: it bought nothing for the next card printing that sentence
(Kjeldoran Home Guard, this set), and it read `attacked_this_turn` for the
attack half — a **turn**-scoped mark, so in a turn's *second* combat phase it
answered yes for a creature that attacked in the first. Now a real trigger with
a real intervening-if, verified to identical numbers on attack and on block.

**A negated combat adjective would have dropped its narrowing.**
`ObjectFilter.attacking` / `.blocking` have been `bool | None` since state
adjectives were read, and only the `True` half had a payload form — so
`nonattacking` would have emitted the payload of a bare "creature". No shipped
card prints one, so nothing was broken; it is the same silent drop already
recorded one field over on `blocked`/`unblocked`.

**Known and not fixed:** `blocked_this_combat` is swept *before* the priority
window that resolves the end-of-combat batch. Worked around by freezing the
answer at the fire site as that file already does for `combat_opponents`, but
any future end-of-combat trigger asking a board question about this combat hits
it.

**Declines, as named parts.** *Stromgald Spy* — six, of which the load-bearing
ones are an AST node for the **causative** `have <player> <verb>` (the grammar
has no "have X do Y" shape at all), a general `for as long as this creature
remains on the battlefield` duration in `_parse_duration` (it exists only as a
bespoke read inside the control-change production), a per-seat "hand is
revealed" record with the CR 611.2b sweep that ends it, and a
`web/serialization.py` change without which the effect is invisible and the card
is hollow. *Sworn Defender* — six, including a `ToughnessOfSubject` amount node
mirroring the existing `PowerOfSubject`, a `Minus` mirroring `Plus`, and
`ChangeBasePT` accepting **two different computed quantities**, which parse and
lowering both refuse by name today. Its handler is the small part.

**Cap pressure is now acute.** `postmodifiers.py` sits at **exactly 1,000** —
legal, zero headroom — and only because the group rewrote the existing
`blocking or blocked by` branch to absorb both new readings rather than
appending. The next group to touch it must split, and the seam is already
visible: the `if stream.at_word("that")` run (~170 lines, one relative-clause
family, almost all reading *histories* off records) against the bare
participial and prepositional modifiers around it. `lowering/counters.py` and
`subject_verb.py` are both at 998.

### W2G2 — costs. Merged; 97 → 102.

Five cards (Contagion, Ritual of the Machine, Wandering Mage, Soldevi Adnate,
Viscerid Drone), zero hooks. ALL's grammar row 66.5% → 68.9% parsed.

**Traitorous Greed (M21, shipped) could be cast naming a land.** "Gain control
of target **creature** until end of turn" — the announcement was legal, the
spell resolved, found nothing, and the caster lost a card to a cast CR 601.2c
forbids. `_validate_cast_targets` is a per-kind chain with **no control-change
arm**, and `derive_cast_spec` reduces those kinds to a bare `{"kind":
"creature"}` picker carrying no printed narrowing. Nothing looked wrong because
Greed's only narrowing *is* its head noun; it took the first card in the pool to
print a real one (Ritual of the Machine's "nonartifact, nonblack") to expose it.

**A cost regex that read a word where the card prints a token.** Wandering
Mage's `-1/-1` is a **PT token**, and both readers — the production and the
charger — read the counter kind off a bare word, so the clause matched nothing.
For a charger that is a **free ability**, not a refused one. A second latent
free-ability hole closed beside it: the self-targeting counter-cost regex was
`[a-z]+` only.

**The disjunction correction that matters for later sets.** W1G4's
shared-head reading was *one axis* (`a red or green card`, the `any_colors`
union). `black or artifact creature` straddles **two** — CR 105 colour × CR
205.2 card type — and `any_classes` had no payload form and no matcher at all,
being explicitly listed as a narrowing every lowering must refuse.

The group handed `lowering/counters.py` back at **998**, the size it was lent
at, by moving the divided-target description into `_common` rather than
appending — "a 999 with four sibling branches still to merge is precisely the
cap breach the playbook records as caused by no single branch".

### W2G3 — upkeep and counters. Merged last; 115 → 125.

Ten cards (Diseased Vermin, Fyndhorn Druid, Ivory Gargoyle, Juniper Order
Advocate, Phantasmal Sphere, Rogue Skycaptain, Scars of the Veteran, Spiny
Starfish, Splintering Wind, Varchild's War-Riders), zero hooks. ALL's grammar
row 70.5% → **79.7% parsed**, and the set's hook reliance is **0.0% of 125
supported cards** — sixty-three cards implemented across three waves without a
single name-keyed entry.

**Five of ten scopings were wrong and four in the usual direction: the
machinery existed and the gap was a spelling.** `Trample; rampage 1` was never
a question — `normalize_creature_line` rewrites `;` to `,` and
`_is_supported_keyword_line` admits the result, so the census was reporting the
*grammar* refusing a line the grammar does not own, an artefact of the report
re-probing every line of a card that failed overall. Scars of the Veteran's
declared blocker ("reading back how much a shield absorbed") shipped with
Sacred Boon; what was missing was two spellings, "on **it**" where Sacred Boon
prints "that creature" and the "if it's a creature" guard that "any target"
needs. Juniper Order Advocate was filed under `static_bonuses.py`, whose effect
half is anchored on the literal subject `this creature ` — the Advocate buffs a
*set*, so it is a `lord_buffs` anthem, which already carried conditions.

**Three latent traps, none of them a mis-play, all closed.**
`@upkeep_effect("upkeep_self", "deal_damage")` ignores its recipient payload and
always damages the controller — safe today only by which cards exist, and named
rather than fixed because no card can demonstrate the wrong answer.
`cumulative_upkeep` had no `INSTRUCTION_CATEGORIES` row, so reached from the
grammar it lowered to `__ungated__` and was reported as "the grammar cannot
parse this" — an instruction produced and then discarded. And `create_token`
resolved its seat with `game.players.index(caster)`, the equality-search-over-a-
mutable-dataclass class CLAUDE.md bans.

**The differential moved 11 of 1,869 programs and the eleventh was free**:
Phelddagrif, which the "target opponent creates a token" production picked up
without being asked. Cyclone, Sacred Boon, Storm Cauldron and Puppet Master
were byte-identical.

### W2G4 — library and modal. Merged; 102 → 108.

Six cards (Browse, Ashnod's Cylix, Diminishing Returns, Misinformation,
Lodestone Bauble, Library of Lat-Nam), zero hooks, and **three cap splits taken
in-branch**: `imperatives` out of `subject_verb`, `effects/search` out of
`effects/library`, `zones` out of `postmodifiers`. `search` is the first
**parse-only** family — a tutor lowers to one instruction however elaborately it
is printed — and is subtracted from `LOWERING_FAMILIES` and `AST_FAMILIES` with
the reason recorded.

**Winds of Change (LEG/4ED/5ED, shipped) lost a commander to the library.**
Under the Commander variant it shuffled a commander out of a hand *into the
library* instead of the command zone: `shuffle_hand_into_library` moved the whole
hand with `player.library.extend(player.hand)`, so `Game.put_card_into_library`
— and therefore CR 903.9b — was never asked. Nothing crashed and nothing was
missing; the commander was simply gone for the rest of the game. This is exactly
why CLAUDE.md requires those two seams: the rule has no single fire site.

**CR 700.2e is the sentence the brief should have named.** It is the one that
says *when* the other player chooses a mode — "when the spell or ability's
controller normally would", i.e. inside CR 601.2b as the spell is cast.
Reasoning from 601.2b alone puts the choice on the caster; deferring it to
resolution makes a different card again.

**`parse_coverage.py`'s "modal machinery" claim was a substring**
(`startswith("choose one")`) — a second reading of a line the compiler already
reads, and it went stale the moment a head printed its chooser: Library of
Lat-Nam compiled, carried its modes, and reported its own head as text nothing
parses. Now routed through the compiler's own reader, `oracle.modal_head_line`.

**Four of W1G5's named parts were already done or misdiagnosed** — including
"the seat, the hard one", which has been on the wire since Drafna's Restoration.
The real gap was **scope**: `own_graveyard_only` had no opponent-side twin, so
an unscoped picker would have offered Misinformation's caster their own
graveyard. Second wave-1 decline in two rounds to shrink on contact.

**Stale CR citations are wider than what was fixed.** CR 701.19 is *Regenerate*;
Search is 701.23 and Shuffle is 701.24. Six were corrected; roughly a dozen
remain in `engine/`. `rules_gaps.py` cannot flag them — the numbers exist, they
are just the wrong rule.

### W2G5 — damage, prevention and zones. Merged; 108 → 115.

Seven of thirteen landed (Hail Storm, Stench of Decay, Exile, Phelddagrif,
Energy Arc, Floodwater Dam, Scarab of the Unseen), six declined with parts
named, zero hooks.

**A card whose name is an effect verb had its own verb eaten.** The lexer
collapsed *Exile*'s printed verb to a SELF token, so the card parsed as a
subject with no verb and refused naming a word it does not print. The fix
mirrors the `_in_type_position` rule already beside it and requires **two**
conditions, because a pool scan finds four cards whose name is followed by a
noun-phrase opener and three are genuine self-references. The differential is
the whole safety argument: a lexer change touches every card in the pool and
**moved exactly one**.

**A draw that dealt damage.** The inline land-tap fire site's Manabarbs arm was
the loop's `else`, so any unrecognized instruction kind was read for an `amount`
and dealt as damage, **defaulting to 1** — "Whenever a Mountain is tapped for
mana, that player draws a card", a sentence the grammar has lowered all along in
the passive voice, dealt a point of damage. Pre-existing; the round widened the
exposure and then named the kind.

**A shipped handler with two caller shapes.** `return_all_matching` read
`context.target_permanent_id` raw, but a *spell* records one id where an
*activated ability* records the announced list — Word of Undoing is a spell and
never saw it.

Recorded as a negative: **"one or more target" has no enforced floor.** There is
no `min_targets` anywhere in the engine, so Heaven's Gate and its four colour
siblings may already be castable naming nothing. Inherited, not introduced.

Seven of thirteen scoping claims were wrong, and again in one direction:
Scarab's "plural owners" part did not exist (`return_all_matching` already reads
`owner_index_of` per permanent), Phelddagrif was **one** broken line rather than
three — a round that "fixed three" would have changed two working programs —
and Floodwater Dam's refusal was not about X at all but a `card_types` demand
its own untap twin does not make.

### W3G2 - modes, counters and granted abilities. 125 -> 129 (4 of 4).

Fatal Lore, Misfortune, Nature's Blessing and Martyrdom, **zero hooks**, and
the whole-pool differential moved exactly five programs of 1,869 - the four
plus Basri's Solidarity, which rode a kind rename. ALL's grammar row 79.7% ->
**80.5%** parsed, 77.7% -> 78.9% lowered, 58.6% -> 59.8% executed, with no
shipped set's floor touched. Parse coverage came back to where it started (11
unclaimed on 9 measured cards) after the instrument was corrected - see below.

**CR 700.2e gives a spell a seat no board can answer, and two of these cards
refer back to it.** W2G4 built the head and the mode choice; what nothing had
was a home for the player the head names. Misfortune's second mode says it
twice ("each creature **that player** controls", "deals 4 damage to **that
player**") and Fatal Lore's says it once. The engine already has exactly one
answer to "which seat does 'that player' name" - the seat a fire site *froze*,
under `EVENT_SUBJECT_PLAYER`, read by `frozen_that_player_seat`, by the damage
recipient and by the gain-life lowering - so the mode choice freezes one the
same way rather than inventing a channel. `lowering/_events.OPPONENT_CHOSE_MODE`
joins `_EVENT_SUBJECT_PLAYERS`; it is not a trigger condition and never reaches
`emit`, because that table is about the events that froze a seat and a mode
choice is one. `lower_ability` and `compile_line` gained an `event=` naming the
**position** a line occupies, which a trigger reads off its own node and an
effect line could not state.

**Four refusal sites, and three of them were a layer off.** "no handler for
-1/-1 counters" had a second gap immediately behind it ("counters on a scope no
handler sweeps") and a third behind that; "no draw handler offers a ceiling"
named a handler that already exists (Arcane Denial's `draw_up_to_cards`, whose
drawer comes off a *record*); "granted ability in quotes" was about the
sentence printed **after** the closing quote, not about the quote. Only
Nature's Blessing's "unconsumed text" pointed at its own gap.

**The load-bearing refusal was one the census never quoted.** `engine/oracle.py`
refused any "An opponent chooses one -" card whose mode targets, on the correct
reasoning that CR 601.2c announces targets after CR 601.2b picks the mode and
here the two steps belong to different players. **And it was blind in the one
direction that mattered**: it asked `"targets" in payload` at the top level, and
Fatal Lore's mode is a `sequence` whose *step* targets - so it never fired on
the only card in the pool it was written for, and fixing the draw made the card
report supported with a mode nobody could name a target for. The gate is
deleted and the announcement shape built: `arm_modal_mode_targets` asks the
caster for the mode's targets the moment the chooser answers, a prompt armed by
the answer to another prompt. Both `blocks_every_seat`, so nobody has priority
between CR 601.2i and the targets being named - the spell being on the stack by
then is a departure from the rules' internal order that nothing can observe.

**A picker with an unanswerable narrowing must offer nothing, and this was the
fourth seat test.** "target creature **that player** controls" is
`defending_player_only`'s exact shape one record over - relative to something
the announcement froze rather than to whoever is choosing - so it is a second
flag/seat pair rather than a reuse, because they read two different records.
Unnarrowed the picker offers every creature in the game.

**One latent hole in a shipped handler, and no shipped card printing it.**
`destroy_target_permanent`'s several-target branch tests its filter with
`subject_matches`, which **refuses** `controller: "that_player"` rather than
ignoring it - so the branch would have rejected every target, destroyed nothing
and logged itself resolved. The singular branch, the sweep above it and all
three tapping handlers already strip the key and ask the frozen seat; this one
did not. Feline Sovereign (M21) prints the phrase but with one target, so it
takes the singular branch and was never wrong. Swept the whole pool for the
shape after the fix.

**Two counter facts that were one kind's name.**
`add_counter_to_each_you_control` had its scope in its name and its P/T pair
hard-coded, so "each creature **that player** controls" had nowhere to go and
"-1/-1 on each" had no reader at all. One kind now
(`add_counter_to_each_matching`) whose printed noun phrase is a filter payload,
because the width is the only difference between the two sentences.

**The keyword list's connective was being normalised away.** `_parse_keywords`
consumed "and" and "or" identically, so "gains banding, first strike, **or**
trample" would have granted all three. No card in the pool printed the shape,
which is the whole point: it was one word away from a silent wrong answer, and
the card that prints it is the one that found it. The comma branch now reads
"and" as well as "or" - which the comment above it already claimed and the code
did not, leaving an "and" list of three one item short.

**An indefinite grant to a chosen object was one payload entry.** CR 611.2b: no
printed duration means it lasts as long as the object, and the *source* branch
of `_lower_gain_keyword` already said so with a `None` duration that
`KEYWORD_GRANT_DURATIONS` documents and no sweep looks at. The target branch
refused it. (`grant_banding_to_target`'s log line was hard-coded to "until end
of turn" and would have said so over a grant that outlives the turn.)

**"Only you may activate this ability" is a permission, not a restriction**, and
`engine/activation_permissions.py`'s `_PERMISSION_SHAPE` already *matched* it -
so Martyrdom was refused for a permission with no row, exactly as that module
intends. What the row needed was the seat: "you" is CR 109.5's controller of the
ability's **source**, and the source is a spell that granted the ability and
then left. Read off the permanent's controller the sentence would be no rule at
all (CR 602.1a already says that) and an opponent who stole the creature would
inherit the ability the card forbids them. `grant_ability_line` records the
granting seat on every granted line now. The sentence itself folds into the
quoted text, because what reaches the battlefield is that string and a clause
left outside it belongs to a spell in a graveyard.

**The sixth pronoun rebinder, and the first whose antecedent is a sibling.**
"Put a +1/+1 counter on **target creature** or **that creature** gains ..." -
the alternatives of a `OneOf` are two readings of one action, so the ability
announces its target once and either branch acts on it. The bound spec stays a
*target*, which is `rebind_pump_pronoun_to_sentence_target`'s choice and the
opposite of the delayed one's.

**A statement-level "or" was claimed in the one position where the trade is
free.** `_parse_optional_action` reads it behind "you may" and its docstring
records why it was not claimed at large. `_parse_statement_alternatives` sits
*after* `parse_statement` has succeeded with the cursor on a word that is
neither a full stop nor a semicolon - which is the state the line fails in
three lines further down, so it can only claim text that is being refused
today.

**`parse_coverage.py` was reading a different card from the compiler**, one
layer deeper than the readers CLAUDE.md names. Its `_rule_match` re-parses a
clause in isolation, and a *mode* of an opponent-chosen head is a clause whose
meaning depends on the position it occupies: read without the chooser event,
Fatal Lore's bullet refuses at its third sentence and two sentences the engine
implements are reported unclaimed. The fix is the one `trigger_prefix` already
makes for the same reason ("reading it that way here is mirroring the compiler,
not excusing it") - `_rule_match` and `_probe` take the event, and the bullet
branch reads it off the compiled program rather than re-detecting the head.

**Declines: none.** All four cards landed.

**One thing the wave-3 base commit carried in, fixed here because it blocks
every group's first assertion:** `engine/grammar/subject_verb.py` imported
`NUMBER_WORDS` and neither used nor re-exported it after W2G4's `imperatives`
split, so `tests/engine/test_import_hygiene.py` was red on `fb458f76`.

**Two non-append edits to other groups' test blocks**, both recorded in place
where the integrator's "both sides are pure appends" assertion will fire:
W2G5's Nature's Blessing and Martyrdom decline tests are **deleted**, because a
decline test whose subject now works asserts something false and cannot be kept
in any form. Both decline lists were right about their parts - Martyrdom's part
3 named `activation_restrictions.py` where the answer was
`activation_permissions.py`, which is a decline list working as intended: it
pointed at the question and the next reader corrected the address.

### Wave 2 integration: two branches split one module, and both moved the same function

`postmodifiers.py` was split **twice in one wave** — W2G4 extracting `zones`,
W2G5 extracting `readers` — and **both moved `_parse_zone_owner_of`**. One
function, two homes, and `test_no_module_defines_the_same_name_twice` cannot see
it because it looks for a repeated name *within* a module. `zones` keeps it:
that module's own docstring makes the argument, since CR 404.1 means a card is
in the graveyard of the player who owns it, so the pile and the seat are one
answer read together.

The same merge carried idiom 26 in its purest form: W2G4 **moved** the
token-recipient block into `imperatives.py` while W2G5 **rewrote it in place**
in `subject_verb.py`, so the conflict presented as "ours: nothing, theirs: the
whole function". Taking either side loses a group's work; the resolution is to
take the *structure* from the mover and re-apply the *change* in the file it
moved to.

And the per-set convention hit its documented failure mode: one file came back
as **two** conflict regions rather than one. Reconstructing from the merge base
with an explicit assertion is what makes that safe — and the assertion **fired
once**, correctly, when W2G2 had edited a W1G4 decline docstring in place to
record that its named part had landed. That is the convention working, not
breaking: the strict "both sides are pure appends" rule inverts to "the incoming
side must be", and the file is resolved on that instead.

### Wave 2 closed: 89 → 125 of 144, zero hooks added

Five worktree groups, and the last of them merged into a main that had already
absorbed the other four — which is the integration shape the wave's findings
come from. **Zero name-keyed hooks across 36 cards**, so ALL's hooked share of
its supported pool stands at **0.0%** after three waves and 63 implemented
cards.

**The mover-versus-in-place hazard fired a second time in the same wave, and
from the other direction.** W2G4 had extracted `imperatives` out of
`subject_verb`; W2G3, branched before that split, rewrote the same dispatch
region in place to route its three upkeep paragraphs through one
`parse_upkeep_paragraph` entry point. The conflict presented as ~430 lines of
"ours: a short imperative call, theirs: the whole dispatcher". Idiom 26's
resolution held exactly: take the *structure* from the mover and re-apply the
*change* in the file it moved to — the consolidation now sits in
`imperatives.py`, where its call site went.

**Two branches wrote the same production and the merge was clean.** W2G3's
"target opponent creates a token" and W2G5's Phelddagrif work are the same
widening of the same prefix table; because W2G4 had *moved* that block into
`effects/game.py` as `_parse_create_token_for_recipient`, the incoming copy
conflicted only in its comment, and the code was already identical. A pure
comment conflict is what a duplicated *idea* looks like when the duplication is
benign — the same shape with the block still in place would have been idiom 25,
silent.

**And idiom 25 had already fired, unnoticed, in the previous merge.** The
post-wave duplicate-idea sweep found `_parse_entering_counters` defined
**byte-identically** in both `subject_verb.py` and `imperatives.py`: W2G4's
split had copied it rather than moved it, and the only caller was in the new
home. `test_no_module_defines_the_same_name_twice` cannot see it — it looks for
a repeated name *within* a module — and nothing else can either, because the
dead copy imports clean, tests green and is simply never reached. **A module
split needs three scans, not two**: the documented dead-import sweep, the
missing-import scan, and a cross-module duplicate-definition sweep over the
names the split touched.

**The per-set test convention held, with its documented failure mode absent.**
Three shared files conflicted; `test_all_creatures.py` and
`test_all_enchantments.py` reconstructed from the merge base with "both sides
are pure appends" asserted byte for byte, and `test_all_instants.py` needed the
weaker form — both sides had *deleted* a decline test whose card had since
landed (W2G2's Contagion, W2G3's Scars of the Veteran), non-overlapping, so the
deletions auto-merged above the append region and only the two per-set blocks
collided.

### Wave 1 closed: 62 → 89 of 144, zero hooks added

Five worktree groups, five merges, and the integration cost ran at roughly the
predicted ratio. **Zero name-keyed hooks across 27 cards**, so reliance fell
while the pool's supported denominator grew.

**Two integration findings, both predicted by the playbook and both real.** The
per-set block convention produced five append conflicts and every one
reconstructed mechanically from the merge base with the "both sides are pure
appends" assertion holding. And `lowering/returns.py` reached **1,020 lines**
with no single branch responsible — W1G1, W1G3 and W1G5 each added a reading
under the cap. Split at the line the module's own docstring already drew, into
`_bound_returns` as a **floor** rather than a second family, because the
layering guard forbids families importing each other and `returns` is its only
reader (`_sweeps` is the precedent). The post-split **missing-import** scan then
paid: `_back_reference_payload` was used in `returns.py` after the move, which
is a `NameError` in a function body — the package still imported clean.

**The substring support gate, measured rather than argued.**
`SUPPORTED_SPELL_PATTERNS` appends a no-op `spell_pattern` instruction for every
listed substring in a card's text, and the support gate answers True to one — so
a card whose every real line refuses can still compile supported, which is
exactly how Arcane Denial shipped. Swept over both manifest roles: **66 cards
are supported on a substring alone**, and all 66 are legitimately implemented in
a derivation the compiler cannot see — 58 Auras through `engine/auras.py`, and 8
through replacements or derived statics (Titania's Song, Zur's Weirding,
Fastbond, Island Sanctuary, Lich, Chains of Mephistopheles, Fiery Emancipation,
Teferi's Ageless Insight). **After wave 1 no Alliances card is in that
population.** So the hole is real and currently empty: nothing is broken today,
and nothing but a substring is stopping the next broken card from reporting
supported. It pairs with the gate asymmetry W1G1 named (the
artifact/enchantment gate asks "is *any* ability implemented" where the creature
gate asks "is *every* trigger"), and the two together are one round: give every
one of those 66 cards a real claim from the derivation that implements it, then
narrow the substring list to nothing.

## Homelands (HML) — shipped

**Census at ingest: 115 cards, 76 supported (66.1%), 44 refused lines over 44
distinct sentences.** All 115 new to the pool — the second all-new set after
FEM — inserted at printing-order index 11 (released 1995-10-01, after ICE,
before M21). **Final: 115/115 supported, hollow lines 0, unclaimed sentences
0**, pool 1,610 → **1,725** over thirteen sets, grammar 88.0% → **88.3%**
parsed with every existing set's floor rising, suite 11,176 → **11,547** tests.
Two waves of five worktree groups plus one closer for Giant Oyster; **zero
name-keyed hooks across all 39 cards**, so reliance fell while the pool grew:
3.9% → **3.6%** of supported cards. The wave-by-wave narrative is readable at
and before `0a1ce5d1`; what follows is only what changes future decisions.

**Apocalypse Chime is the second card to read `original_printing` as data**
(Golgothian Sylex's twin, aimed at its own set): if HML's manifest entry ever
sits after a set that reprints it, the Chime stops seeing its own set. The
insert itself was held by `test_the_shipped_sets_are_in_printing_order` — the
prefix guard cannot fire on an all-new set from any index, FEM's blind spot
again.

**Rank the next set by the fragment, not the sentence** — the set's headline
transferable finding, now folded into "The next set" above: the sentence census
read 1.00 (no leverage) while ten cards shared one untap-denial fragment,
three already compiling, so seven cards cost one group one subject widening.

**Nine shipped cards were mis-playing and no instrument could see any of them**
— each found by a group giving the behaviour a game, each invisible to the
census, `--hollow-lines` and `parse_coverage.py` because all three ask whether
a line produced *something* and each of these produced the wrong thing:
Pyroclasm damaging every Mountain (two drifted lowerings of one sweep); a Copy
Artifact copying Su-Chi surviving Golgothian Sylex (CR 206.3b names, not
physical printings — three sites); Whippoorwill exiling itself (bare-pronoun
collapse); six permanents releasing a linked lock a turn early under AI play
plus Phyrexian Gremlins re-locking without a second activation (CR 611.2a/b —
fixed post-wave, `_holds_a_live_untap_lock`); an activation cost charged during
the "may I activate?" half (CR 601.2h asked destructively); Amulet of Quoz
anteing nothing against an empty library; Winter Sky drawing for the wrong
seat; Divine Offering gaining 5 or 0 depending on how its target was named;
the AI aiming Daughter of Autumn at the opponent's creature (a CR 614.9
redirect categorised `damage` — right family, backwards side).

**The whole-pool differential map must carry the compiled program's full
`repr`.** Keyed on ability counts it cannot see a trigger narrowed from
"blocks anything" to "blocks a black creature" (Rashka the Slayer — reported
unimplemented, actually implemented *too widely*); keyed on instruction kinds
it cannot see a `type_filter` restored to a payload (Pyroclasm). Both natural
abbreviations are blind to precisely the narrowing class the instrument exists
to catch. Two groups and the integrator each wrote a lossy version
independently. (`scripts/oracle_diff.py` is this finding as a script.)

**The refusal taxonomy has a fifth layer: `engine/oracle.py`'s
trigger-condition table.** Two trigger front ends exist and only the regex
table feeds dispatch — a condition the grammar reads perfectly can still fire
on the wrong event, which is what Rashka did. And a refusal site is a work-list
entry, not a diagnosis: Giant Oyster refused at `expected 'gain'` for two waves
on a sentence that is a control change in nobody's reading, because a probe
order manufactured the site.

**A decline list is a lead the next reader corrects, like a brief.** Giant
Oyster landed on the third pass: W2G4 disproved two of W1G1's six named
blockers, and the closer found a sixth nobody had named — "remove all counters
from **the** creature" read as the bare source pronoun, so the card compiled
supported, claimed every sentence, carried no hollow line, and took its own
counters off.

**The promotion gate's carryable finding**: `tests/rules/test_aura_support.py`
split raw `oracle_text` instead of starting from `expand_ability_lines` — a
fourth reader beyond the three CLAUDE.md names, reading a different card than
the compiler compiles. The picker sweep, run at Phase 1 rather than Phase 4,
found Roots (a supported Aura no player could cast, its "without flying"
exclusion enforced by nothing) on the day of the ingest; narrowed and run over
the whole shipped pool, no other card carries the shape.

## Fallen Empires (FEM) — shipped

**Final: 102/102 supported, hollow lines 0, unclaimed parse sentences 0, and the
manifest entry moved from `measured` to `sets` at printing-order index 8 —
between The Dark and Fourth Edition.** The pool went 1,508 → **1,610** unique
cards over twelve sets. Ingest census was 69/102 (67.6%), the highest of any
work set. **One wave of five worktree groups took it to 101/102 in a single
pass**, and one follow-up agent took the declined card. Grammar coverage
87.4% → **88.0%** parsed and 55.2% → **56.1%** executed, with FEM itself at
99.0%. Hook reliance 4.2% → **3.9%**: one hook retired, **none added**, across
all 33 cards. The suite went 10,934 → **11,176** tests.

**The census could not see this set's leverage, and that is the finding to
carry.** Four of the five candidates re-censused before the ingest measured
exactly 1.00 refused lines per distinct sentence, FEM included — no production
shared by even two cards, which reads as "no leverage, pick on card count". The
refusal rollup at ingest said the same: 39 refused lines, 39 distinct sentences.
Both were true and both were measuring the wrong population. `support_report.py`
counts **cards**, and a card is supported when *any* of its lines is — so a
sentence that repeats between a refused card and a *supported* one is invisible
to it by construction. Running `parse_coverage.py` and `--hollow-lines` at
**Phase 1** rather than at Phase 4 found five supported cards carrying eight
sentences nothing implemented, and four of them paired with a card on the work
list: Tidal Influence with Homarid, Goblin Grenade with Soul Exchange, Delif's
Cube with Delif's Cone, and the two Chants with each other. Those pairs became
the group split, and every one of them cost a single production for two cards.

**Integration cost roughly what authorship did, and every merge hazard the
playbook names fired at least once** — one fact under two names, two moves out
of one over-cap file, two rewrites of one guard, and a semantic collision that
merged clean and failed at runtime. Three cap breaches fired *at integration*
and none was caused by a single branch. Two new hazards are recorded in
SET_PLAYBOOK.md: a whole-file `--theirs` discards the hunks that were never in
dispute, and a union of two `if` branches can break an `if`/`elif` chain so that
one branch's answer is computed and then overwritten.

**Ten defects were found in cards that already shipped**, none with a failing
test, all found by reading compiled programs or sweeping the pool for a shape.
Two were free abilities — the class Ice Age's Triskelion was — and one of those
predated this pool by five sets. Two more came from the promotion gate itself.
The list is above, with what each cost.

**The instrument that mattered most was the cheapest.** A whole-pool
compiled-program differential (1,610 cards, base versus HEAD) is what turned
Orcish Captain's recorded scope — "cross-sentence pronoun rebinding is missing",
a parser feature — into a one-node fix, by showing that the obvious version
broke eight shipped cards which already played correctly. Three of the five
groups ran the same differential unprompted and each reported it as the thing
that let them be sure. It belongs in Phase 3 as a step, not as a tactic
somebody rediscovers.

### How it went, phase by phase


**Census at ingest: 102 cards, 69 supported (67.6%), 33 unsupported, 39 refused
lines.** 187 printings dedupe to 102 by `oracle_id` — FEM prints most of its
commons in two or three arts, which is the largest printing-to-card ratio in the
pool and worth knowing before reading any per-set count. All 102 cards are new
here, so Phase 1 step 5's question ("is this a set you implement or a set you
promote?") answers *implement*.

**It is the first set that inserts rather than appends.** FEM released
1994-11-01, between The Dark (index 7) and Fourth Edition (index 8).
`CardDefinition.original_printing` is the first entry in `printings`, so the
promotion commit places the manifest entry at index 8 rather than at the end.
Nothing in the shipped pool moves — every FEM card is new — which means
`test_appending_a_set_never_changes_an_existing_original_printing` cannot fail
whatever index is chosen, exactly the blind spot 4ED collected on. The guard
that does fire is
`test_manifest_roles.test_the_shipped_sets_are_in_printing_order`, which
compares the `released` dates the entries already carry.

**Both Phase 2 subsystem sweeps came back empty**, which is the finding that
sizes the set. Every card is `layout: normal` with a known type — no
planeswalker, no split, no transform — so nothing gates promotion structurally.
And every keyword the set prints (banding, protection, first strike, trample,
islandwalk, landwalk, defender, plus the Scryfall tags Regenerate / Enchant /
Mill whose behaviour lives elsewhere) is already in `IMPLEMENTED_KEYWORDS`, with
none of them in `UNSUPPORTED_KEYWORDS` — the third table that outranks both and
cost Legends seven rampage cards with the behaviour built and tested. So FEM
opens with **no keyword round**, which is unusual: keywords normally open Phase
3 because they have the highest cards-unlocked-per-change in a census.

**The refusal rollup is as flat as the re-census predicted** — 14 lines at
"expected a subject", 9 at "unconsumed text", 3 at "unrecognized effect verb",
and thirteen sites with exactly one line each. Every one of the 39 is a distinct
sentence. There is no production here that buys ten cards.

**The leverage is somewhere the census structurally cannot look, and that is the
transferable finding.** `support_report.py` counts cards, and a card is
supported when *any* of its lines is — so the sentences that repeat in this set
repeat between a *refused* card and a *supported* one, where only an instrument
reading line by line can see the pair. Two of those instruments were run at
ingest rather than at Phase 4:

- `parse_coverage.py`'s measured-set section: **8 unclaimed sentences across 5
  supported cards** (Delif's Cube, Goblin Grenade, Thelon's Chant, Tidal
  Influence, Tourach's Chant).
- `support_report.py --hollow-lines`: **1 card, 1 part** — Delif's Cube's
  activated ability compiles to no instruction at all.

Four of those five pair with a refused card: Tidal Influence prints Homarid's
three tide-counter sentences with the subject changed, Goblin Grenade prints
Soul Exchange's additional-cost clause, Delif's Cube prints Delif's Cone's
"attacks and isn't blocked … assigns no combat damage", and Thelon's Chant and
Tourach's Chant are each other's sentence with the land type changed. Five of
the set's repeated shapes, none of them visible in the census histogram.

**The wave ran and 32 of the 33 landed**, in one pass of five worktree groups
— 69/102 to 101/102, with Raiding Party declined as an enumerated list of ten
parts. **Zero name-keyed hooks were added and one was retired** (Dragon Whelp,
which prints Farrelite Priest's clause verbatim), so reliance fell 4.2% → 4.1%
while the measured pool grew. Every group's pairing paid: Homarid and Tidal
Influence cost one production between them, Delif's Cone and Delif's Cube one,
Goblin Grenade and Soul Exchange one, and the two Chants one.

**Integration cost about what authorship did, and every merge hazard the
playbook names fired at least once.** Two branches invented the cost-object
back-reference under two names (`SacrificedForCostWas` and
`CostObjectWas(channel, filter)`); two moved *different* functions out of the
same over-cap `subject_verb.py`, so git offered each side as "keep mine" and
either alone resurrects the other's move; two rewrote one guard in
`_lower_doesnt_untap_next_step`, each adding a term the other lacked; and a
union of two `if` branches in `skip_next_untap` broke an `if`/`elif` chain, so
one branch's answer was computed and then overwritten — three tests green on
each branch alone, red on the merge. Two new ones are worth recording:

- **A whole-file `--theirs` discards the hunks that were never in dispute.**
  Resolving `ast/conditions.py` that way would have silently dropped a *third*
  group's node that had merged cleanly into the same file. Resolve the conflict,
  not the file.
- **One channel, two value shapes.** `permanents_from` names a scratchpad key,
  and one producer writes a list where another writes a bare id. Both reached
  one reader and it raised. Normalised at that reader with the disagreement
  named — but every *other* reader (`destruction`, `control_changes`) reads the
  scalar shape only and would raise on the list, so **the channel's arity is
  still an open question**, not a settled convention.

**Three cap breaches fired at integration and none was caused by one branch** —
`lowering/counters.py` (three groups' additions summing), `lowering/game.py` and
`lower.py`. All three split along a line that was already there:
`counter_removal` on CR 121.1/121.2 versus 121.3, `tokens` on CR 111.1 (an
object the game creates, where what stays in `game` changes the state a *player*
is in), and `by_node` on the distinction `lowering/_records.py` had already
recorded about the two tables that left `lower.py` before it — the table is a
registry either way, and `lower.py` is dispatch. The guard that fails on an
unlisted family fired straight after each, which is a hand-maintained list
checking itself.

**And the moved-block import hazard caught the integrator rather than a group.**
`lowering/tokens.py` lost `_restrictions_beyond`, which lives in the header its
functions left behind — the same failure the per-set test files were
restructured to prevent, in the one place that restructuring does not reach. It
fails as 132 collection errors, which is loud; the sweep for a second instance
across `engine/` came back clean.

## Live defects the wave found in *already-supported* cards

Every one was found by reading compiled programs or by sweeping the pool for a
shape, not by the census — and none had a failing test. **The free-ability ones
are the class Ice Age's Triskelion was**: a cost that matches nothing is not a
refused ability, it is a free one.

Fixed in the wave:

- **Goblin Grenade was castable with no Goblin anywhere**, dealing 5 for `{R}`:
  `cast_costs._COST_CLAUSES` spelled "sacrifice a creature" out as a literal, so
  a typed noun matched no clause and the additional cost was claimed by nothing
  and charged by nobody.
- **Hecatomb and Karplusan Giant had free unlimited abilities** because
  `_NUMBER_WORDS` carried `"a"` and not `"an"`, so the charger read a count of
  zero from "Tap **an** untapped Swamp" while the grammar's amount reader read
  one. **Osai Vultures** (Legends and Fourth Edition) pumped forever because a
  counted counter-removal cost matched no printed count. Both survived a
  pool-wide guard whose whole job is that class; it now covers tap, exile,
  counter-removal and counter-adding costs with their counts.
- **Vodalian War Machine's two tap costs charged nothing** — the lines parsed
  and were free, which is the brief's suspicion confirmed rather than dismissed.
- **`combat`, the bare "at the beginning of combat", had no fire site at all**
  while sitting in *both* front-end tables. `test_trigger_dispatchers.py` could
  not see it because no pool card produced the kind — the guard's blind spot
  rather than a gap in it.
- **"Sacrifice a land of an opponent's choice" dropped its `chosen_by_opponent`
  flag**, so the sacrificing player would have chosen. Demonic Hordes was
  shielded only by its name-keyed hook, which means the fix is what kept that
  hook honest.
- **Mystic Remora offered its toll to the wrong seat** in a three-seat game —
  "that player" under a player-subject event reached a fallback reading
  `context.target`, right in a duel by coincidence.
- **A keyword grant dropped its target narrowing entirely** (Whalebone Glider's
  "with power 3 or less", Krovikan Elementalist's "you control", Phantasmal
  Mount), because the single-keyword shortcut carried only a duration.
- **`add_counter_to_target` announced a target it never chose**, so a trigger
  with no legal creature was removed from the stack under CR 603.3c — live for
  The Abyss, Dread Wight, Frost Breath, Telekinesis and Melee.

- **Orcish Captain shrank itself instead of the Orc it targeted** — the
  losing arm's bare "it" lowered to `pump_self`. Fixed, and **the recorded
  scope was wrong in the way this roadmap keeps warning about.** The wave
  wrote it up as "cross-sentence pronoun rebinding is missing", which reads
  as a parser gap; building that broke **eight shipped cards** (Phyrexian
  Gremlins, Telekinesis, Glyph of Destruction, Whippoorwill, Mole Worms,
  Goblin Sappers, Ice Floe, Elvish Scout), every one of which prints a bare
  "it" after a targeting sentence and already played correctly. The engine
  does have a convention for that pronoun — it is read by the *lowering*,
  not the parser, and each of those lowerings carries its own bare-pronoun
  branch. What was missing was one lowering's branch: `_lower_pump` tests
  `filter.is_source`, cannot tell "it" from "this creature", and fell
  through to the source. **A whole-pool compiled-program differential is what
  turned a parser feature into a one-node fix**, and it is the cheapest
  instrument in this repo for that: 1 of 1,610 programs changes.

Fixed after the wave (2026-09-01):

- **A coloured upkeep cost could not tap lands.** `can_pay_upkeep_mana`
  covered coloured pips from floating mana alone and let only the generic part
  tap, so every coloured upkeep in the pool was sacrificed on its first upkeep
  in AI or headless play with the right lands untapped. Recorded here as ten
  cards; the census at the fix read **27** — eleven pay-or-sacrifice
  enchantments, eleven coloured cumulative upkeeps, Island Fish Jasconius'
  untap toll, and four cards (Demonic Hordes, Force of Nature, Minion of Tevesh
  Szat, Rohgahh) in three handlers that had never asked the pair at all and
  honoured a human "pay" against an empty pool for free. The pair now asks
  `mana_payment.plan_payment` (CR 605.3a), the same question every other
  offered price asks; `tests/rules/test_upkeep_payment.py` holds it. A count
  written in prose under-read the class by nearly three to one, which is the
  decay this file keeps warning about.

Open, each recorded with what it costs rather than scheduled here:

- **A mana ability with a rider uses the stack** (CR 605.3/605.1a).
  `is_mana_ability` reads only the top-level instruction kind, so Farrelite
  Priest, Initiates of the Ebon Hand, Barbed Sextant and all six Ice Age
  painlands are pushed and resolved like ordinary abilities — which means their
  mana cannot be produced while a cost is being paid.
- **`land_enters` has one fire site, inside the land-*play* resolution**, so a
  land an effect puts onto the battlefield triggers nothing — Ankh of Mishra
  deals no damage for one. This wave makes the fix nearly free: the row can fall
  to `matching_permanent_enters`, whose "that land's controller" now reads
  `event_subject_controller`.
- **An offer priced in a non-mana action arms with no prompt string**, so Deep
  Spawn's "unless you mill two cards" and Oath of Lim-Dul's discard reach the
  web layer as a bare Yes/No with no statement of the price.
- **Living Artifact's vitality counters bypass the counter seam**, writing
  `perm.metadata[...] += damage` with the counter word in a substring test. No
  live bug — that card has no cap and no last-counter trigger — but it skips the
  cap enforcement and the emptied-kinds record every other placement goes
  through.
- **The browser can name only one object for a counted cost.**
  `web/static/app.js` sends a single `cost_permanent_index`, so Goblin Warrens'
  second Goblin and Night Soil's second card take the deterministic default. The
  cost is fully charged; only the *choice* is partly the engine's.

**Round plan: one wave of five worktree groups**, split by the machinery rather
than by the printed type, each carrying the supported-but-hollow card that
shares its shape:

| Group | Machinery | Cards |
| --- | --- | ---: |
| G1 | counters as named state | 6 + Tidal Influence |
| G2 | self-clocks, delayed self-sacrifice, card-flow order | 7 |
| G3 | combat triggers, block restrictions, damage substitution | 7 + Delif's Cube |
| G4 | costs from the board and the graveyard, taxes, land animation | 6 + Goblin Grenade |
| G5 | prices offered to another player, prevention, control | 7 + both Chants |

**One process change went in with the wave**, against the playbook's own
warning that reconstructing a per-set test file from its delimited block drops
header imports. The six `tests/sets/test_fem_*.py` files were opened on `main`
before the fan-out, and their header instructs each group to put **its own
imports at the top of its own block**. The mechanical merge is "take ours,
append the branch's block"; a block that carries its imports cannot lose them,
so the hazard is designed out rather than watched for.

## Ice Age (ICE) — shipped

**Final: 373/373 supported, hollow lines 0, unclaimed parse sentences 0, and the
manifest entry moved from `measured` to `sets` at printing-order index 9.** The
pool went from 1,162 unique cards to **1,508** — 346 of ICE's 373 were new, the
largest single addition since Alpha. Ingest census was 184/373 (49.3%), the
lowest of any set, with 58.9% of lines parsed against the shipped pool's 85.7%.
Forty-two serial rounds took it to 284; four parallel waves of five worktree
agents took it the rest of the way. Hook reliance fell 6.0% → 4.2% of supported
cards with **nine hooks retired and none added**, while the pool grew by a
third. The process account — waves, briefs, merge hazards, what each phase
gained — is SET_PLAYBOOK.md's ICE retrospective.

**What the set is worth remembering for: supported is not working, and the
instruments that say otherwise are card-level.** Twenty-four silent defects were
found in *already-supported* cards by reading compiled programs rather than the
census, and **none had a failing test**. Control Magic left a creature stolen
forever when the Aura was bounced, because an Aura's effects were removed on
reaching the graveyard rather than on *leaving the battlefield* (five other
cards shared it). Triskelion was a free repeatable pinger, because its
activation cost matched `[a-z]+` against a counter kind spelled in symbols — and
a cost that matches nothing is not a refused ability, it is a free one. Drain
Life ignored "but not more life than". 107 cards printing a non-mana activation
cost had that option dropped from the browser's ability menu.

Three more came from a sweep over **what the target pickers offer**, which is
the angle no card-level instrument has: all three compile supported, carry no
hollow line and claim every printed sentence. Goblin Ski Patrol sacrificed the
*opponent's* first permanent instead of itself; Aggression and Faith's Fetters
were uncastable in the app because their enchant clauses derived `kind: "none"`
and the client tests exactly that value. That sweep is a Phase 4 step now.

**The promotion rehearsal turned twelve guards red and the split was again the
opposite of intuition in both directions** — three cards were at fault
(Barbarian Guides was *wholly inert*, logging "no valid creature target" on
every activation) and the rest were stale guards, including the 4ED proxy trap
repeating exactly: a guard proved parse coverage reads measured sets by finding
a card that is not shipped, and promoting the last measured set empties that
role legitimately, so it read "the instrument stopped watching" when the truth
was "there is nothing to watch". It asserts the invariant now.

**Three follow-on rounds were taken after promotion and all three found the
recorded scope wrong** — twice too narrow, once too wide. That is the warning
worth carrying: a finding written down during a wave is a snapshot of what one
agent could see. A departed target resolved by index was recorded as a delayed-
trigger binding bug and was half that — the same resolver carried nine
activated abilities' immediate effects, and Merieke Ri Berit gained control of
the decoy. "That player" was the wrong player was recorded as The Abyss not
asking, and the first defect was a fixed keyword list silently dropping
`controller: "that_player"` (M21's Feline Sovereign shared it). "A sweep is not
a target" was recorded as a client annoyance over six cards and was a real
engine misplay over 17.

**The lead this set left is taken (2026-08-31): Volcanic Eruption's hook is
retired**, onto Avalanche's destroy production plus "equal to the number of
<noun> put into a graveyard this way" — one spelling of the record Hellfire's
where-clause already read (CR 700.4: "dies" *is* "put into a graveyard from the
battlefield"), so both front ends now ask one `accept_this_way_count`. Hooked
cards 64 → 63, entries 70 → 69, and the whole-pool program differential was
this card alone. **The round's real finding is a fire-site class, not the
card**: `land_dies` (Dingus Egg) was announced from inside the single-target
destroy path plus a second call inside the hook — so a land destroyed by the
several-targets branch (Avalanche), a board sweep (**Armageddon**) or a
sacrifice fired no trigger at all, in the shipped pool, with every test green.
It rides `_permanent_to_graveyard` now, idiom 5's seam, asked through
`has_type` so a type-changed land still counts. The retirement also forced the
spec derivation to carry a subtype/supertype narrowing under `filter` — the
enumeration was offering a Forest for a spell that destroys Mountains, because
the per-candidate cast probe never asks a several-target instruction's filter —
which narrowed Avalanche's picker to snow lands as a side effect.

## Where the sets landed

The numbers a Phase 1 census is estimated against. Rounds are ROADMAP rounds,
not commits.

| Set | Cards | Supported at ingest | Rounds to 100% |
| --- | ---: | ---: | ---: |
| M21 | 285 | 58% | ~140 |
| ATQ | 85 | 56.5% | 30 |
| LEG | 310 | 32.9% | 36 |
| DRK | 119 | 47.9% | 12 groups, 3 waves |
| 4ED | 368 | 100% | 0 (pure reprint) |
| ICE | 373 | 49.3% | 42 + 4 waves of 5 |
| FEM | 102 | 67.6% | 1 wave of 5, + 1 for the decline |
| HML | 115 | 66.1% | 2 waves of 5, + 1 for the decline |
| 5ED | 434 | 100% | 0 (pure reprint) |

Legends is the useful data point and the warning: the lowest starting coverage,
the largest card count *at the time*, and the flattest ranking — after eight
rounds, 113 of its 135 remaining cards refused *exactly one line* and the largest
group of those shared only an opening phrase. It was designed before templating
existed, so the generalise-first rule runs out of general work earlier than in a
modern set. Its first census read 121/310 (39.0%) rather than the 32.9% recorded
at ingest, because the ingest round's own engine fixes moved it — Phase 1 says to
treat what the suite surfaces on a new set as yield, and that gap is the yield.

Ice Age is the second data point of a different kind: the largest set, the
lowest ingest census, and the first where **serial rounds ran out before the
cards did**. Forty-two rounds bought 100 cards; four waves of five bought the
remaining 89 in a fraction of the calendar time, with integration — not
authorship — as the constraint throughout.

**Where the pool stands** (regenerate rather than trust these): 1,725 unique
cards over **14** sets, 100% supported. Grammar parses 88.8% of lines, lowers
87.9% and executes 56.9% (`GRAMMAR_COVERAGE.md` — the 5ED promotion moved that
printing-weighted row on membership alone, the 4ED lesson again). 3.6% of supported cards carry
a name-keyed hook — 62 cards, **68** entries in 6 registries
(`HOOK_RELIANCE.md`) — the number that decides whether this architecture reaches
26,113 cards, and the projection it implies has fallen from 1,195 hand-written
entries to **1,029** across three sets that added none. That is the measure
moving the way the architecture needs it to: the entry count has not changed
since FEM, and the denominator has grown by 217 cards. Parse coverage: 1,723 of
1,725 supported cards fully claimed, 2 acknowledged, **0 unclaimed**
(`PARSE_COVERAGE.md`). `RULES_PROGRESS.md` is the
CR coverage tracker. `CARD_VERIFICATION.md` is a log, not a target — see the
accepted-backlog decision above.

**Read a ratchet move as a measurement change before crediting it as a
regression.** Two cases, opposite directions, same lesson. Retiring Kudzu's
dispatcher moved its line into `CARD_LINE_INSTRUCTIONS`, the registry the *line*
measure counts, so hooked lines rose 69 → 70 while hooked cards and entries did
not move at all and the registry count fell 7 → 6: reliance did not rise, the old
number was under-reporting a line that was hooked all along in a registry the
measure could not see. And a channel move in `PARSE_COVERAGE.md` (card_hooks 117
→ 116, parse rule 982 → 983) was one sentence changing which reader claims it,
not what happens. The mirror of 4ED's lesson about reading a promotion diff as
membership before crediting the parser.

## Size watch

The 1,000-line cap on `engine/grammar/` modules is a scheduling signal, not
style: it fires when a family stops absorbing new work, and the split is
cheapest while the work that crossed the line is still in hand (idiom 13).

**There used to be a table of the closest modules here, and it is gone on
purpose.** It went stale the moment anyone worked, and at HML two groups
reported independently that they had planned around it and been wrong — it named
five modules at 989–995 that were actually at 571–978, while the two that
*did* breach (`lowering/damage.py` at 999, twice; `lowering/library.py` at
1,004) were the ones it did not name. A number that is wrong in the reassuring
direction is worse than no number. The live reading is one line:

```powershell
find engine/grammar -name "*.py" | xargs wc -l | sort -rn | head
```

HML crossed the guard five times and every split reused a name the other side of
the pipeline already carried: `lowering/damage.py` → `_sweeps` and `upkeep`,
`lowering/library.py` → the existing `exile`, `effects/board.py` →
`attachments`, `lowering/tapping.py` → `untap_restrictions`, and `amounts.py` →
a new `records`, the parse-side mirror of `lowering/_records.py`.

**Every split so far fell along a line something else had already drawn**, and
that is the strongest available evidence a boundary is structural rather than a
matter of taste. The Dark took six in one set, each along a line the CR or the
call graph already drew. Two of those were invented **twice, independently**, by
parallel branches that each hit the cap on the same module and cut it in the same
place. Ice Age's first split (`effects/characteristics.py` → `counters`) cut
along a line the *lowering* side had drawn one set earlier, under the same name
and for the same reason: a boundary found independently by two packages, a set
apart. Reuse the other side's family name every time and the mirror re-forms
instead of forking — `destruction`, `keywords`, `tapping`, `types`,
`trigger_tables`, `sentence_clauses`, `upkeep`, `prevention`, `counters`.

**And a module two families import is a floor, not a family.**
`lowering/_amounts.py` and `lowering/_sacrifices.py` both arrived that way,
each because a family reached sideways for a helper and the layering guard
refused it — which is the same rule arriving from the other side when moving one
into `_common` pushes *that* past the cap.
