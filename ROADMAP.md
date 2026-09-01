# Scaling Roadmap

Target: grow the card pool from **1,508** unique cards (LEA/LEB/2ED/ARN/ATQ/
3ED/LEG/DRK/4ED/ICE/M21, all shipped and all supported) to the full release
line — **137 sets, 33,594 printings, 26,113 unique cards** per
`set_progress.json`. Eleven sets, and the two most recent sit at opposite
extremes: 4ED is a pure reprint set that bought printings rather than cards,
and Ice Age brought 346 new ones, the largest addition since Alpha.

**The reprint shape recurs and is worth planning for** — `set_progress.json`
records 13 sets in the release line with zero new cards, and ten are still
ahead: the foreign-language base sets (FBB, SUM, 4BB), the rest of the core-set
line (5ED through 10E), and Timeshifted. Each promotes roughly the way 4ED did,
so their cost is an ingest and a rehearsal rather than a set of rounds. Sequence
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

**Why the journal is culled, and this is the second time.** It first reached
2,700 lines, of which 2,350 were narrative that no longer changed anyone's
decisions; that cull is at `ee28617`. Ice Age then put 1,800 lines back, and the
same rule applies to them — those rounds are readable at and before `49f74af`.
A file nobody reads to the end is a file whose *live* items go unread with the
dead ones. The parts that were still doing work are all below.

---

## Standing invariants

Anything that weakens these is a regression regardless of what it enables:

1. **No silent wrongness.** A card may fail loudly as unsupported with a
   reason; it may never resolve as something other than what it says.
2. **The suite stays fast.** **10,821 tests**, CI budget **240s**, CI-measured
   baseline **110s** (`ci.yml`). The budget catches a step change; the baseline
   is what catches creep, and it is the number to keep honest. Raising the
   budget is a decision, not maintenance — it has been raised three times on
   purpose.

   **Both numbers are runner-measured, and that is the whole lesson.** They sat
   wrong in opposite directions for three sets because `BASELINE` was recorded
   from a *local* run and compared against an `ELAPSED` the step measures on the
   runner — the multiplier was never in the arithmetic at all, it was the
   arithmetic's missing term. Do not "fix" a suspicious ratio by editing either
   number from a local timing; read the step's own output across several runs.

   **Re-read at Phase 0, 2026-08-31, from four runner runs**: 172s, 186s,
   163s, 205s at 10,821 tests. `BASELINE` moved 110 → 180 as the record of
   that growth; `BUDGET` stays 240, and the latest run is **85% of it** with an
   ingest ahead. The shape matters more than the level: +19% tests took +64%
   runner wall time (a local machine measured the same super-linearity, +40%),
   so per-test cost rose during ICE's waves — read `--durations` on a runner
   run before letting the next ingest force the budget decision, and remember
   the `slow` marker exists if the AI-batch tests are the growth.
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
  battlefield; neither names `command_zone`, so an AI commander sits there for
  the whole game and Commander-vs-AI is a handicap match. The CR 903.9 zone
  prompt already defaults safely for AI seats — this is a missing *policy*, not
  a rules gap. Wants the same shape as every other AI read: derived from the
  compiled program in `ai_valuation.py`, weight tuning in `ai_policy.py`.
- **A *toll* has no default anybody chose.** Its twin is closed: a *free*
  `optional_pay` offer is refused when the offered action spends the seat's own
  resources and the card prints nothing for refusing
  (`ai_valuation.offered_action_is_a_payment`, over the instruction kinds the
  rules define as done to oneself — CR 701.21a sacrifice, 701.9a discard,
  118.3b pay life, 407.4 ante, 701.13a exile). That is the stated policy **take
  gifts, pay tolls, make no trades**. A toll is still asked and answered by
  affordability alone — pay if the mana is floating, else take the penalty — and
  nine cards ride on it. The missing piece is a valuation of which of two losses
  is smaller, because nothing in the compiled program separates "pay Season of
  the Witch's 2 life" from "sacrifice Curse Artifact's artifact". By CLAUDE.md's
  split that is `ai_policy` work with an `ai_valuation` derivation behind it,
  not another branch in `_default_optional_pay`.

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

- **A trigger's "that player" back-reference falls through to `target_player`
  rather than refusing.** `lowering/_events.py` says in its own docstring that
  "a condition absent from a table refuses the line instead", and the damage
  family's last `elif` breaks that contract: a condition in neither
  `_EVENT_SUBJECT_CONTROLLERS` nor `_EVENT_SUBJECT_PLAYERS` silently becomes a
  *target* the card never offers.

  **Re-censused 2026-08-31: still 11 triggered abilities**, the same count as
  when it was written and not the same list — the three live bugs left and
  Lim-Dûl's Hex (ICE) joined. Every one is correct **by accident**, and there
  are now three different accidents: Ankh of Mishra and Dingus Egg replace the
  compiled instruction outright at a hand-written fire site carrying their own
  `victim_player_index`; Manabarbs and the seven `upkeep_enchanted_controller`
  Auras get the seat from a registry; and Lim-Dûl's Hex is inside a `for_each`
  over each player, so the **loop** binds the pronoun the table would have.
  Closing the fall-through means giving those fire sites the compiled
  instruction first, or Ankh of Mishra becomes unsupported. **Its own round, and
  that census is its work list.**

- **Two layer reads disagree about the same land.** In `engine/land_types.py`,
  `static_supertype_removal_applies` asks `permanent.has_type` (layer 4) while
  `static_land_type_change_applies` beside it tests its `from_type` against
  `effective_card.type_line` (layer 3) — so Conversion cannot see a Mountain
  that Blood Moon made, two layer-4 effects CR 613.7 says should chain by
  timestamp. Confirmed still open 2026-08-31, and reachable now that Blood Moon
  ships. Deliberately **not** taken with the CR 305.7 round: asking `has_type`
  there reads layer 4's result while computing layer 4's inputs, so the fix is a
  dependency ordering rather than a changed accessor. The caller's `break` after
  the first matching source (`permanent_state._refresh_static_land_types`) is
  the same round's second half — CR 613.7 chains statics, it does not pick one.

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

    **Two graveyard residuals have reproductions and were deliberately left**
    (2026-08-31). The *unambiguous* case is answerable and answered wrong: with
    the chosen card gone from the pile entirely, `graveyard_index_of` returns
    None and `chosen_graveyard_index` falls through to the stale index, which
    now names a different card — exile the Serra Angel a Resurrection targeted
    and it reanimates the Grizzly Bears beneath it. The docstring's "this can
    only turn a wrong answer into a right one" is false for that path. And two
    cast-side graveyard targets reach no gate at all: `cast_target_refusal`
    excludes `graveyard_creature`, and `_validate_cast_targets` keys on the
    *primary* instruction kind, so a spell whose targeting sits inside a
    `sequence` (Fungal Rebirth, Experimental Overload) accepts an announcement
    naming an opponent's graveyard and re-points it at the caster's own. The web
    picker never offers the illegal choice, so it is engine-level laxity rather
    than a reachable misplay.

- **Five handler paths still resolve by index alone**, reached today only by
  instants and so caught by the CR 608.2b gate first. The next *activated*
  ability printed with "return target creature to its owner's hand" walks in.
  Recorded at five after Ice Age's follow-on rounds and **not re-counted since**
  — most target resolution goes through `resolve_target_permanent`, which reads
  the id itself, so the census has to distinguish the paths that never had one.

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

**Re-censused 2026-08-31 against the post-ICE compiler**, five near-term
candidates fetched to a scratch directory (never `cards/`), measured with
`support_report.refusals_report` so "a refused line" means what the work lists
mean by it:

| Set | Cards | New to pool | New & unsupported | New per unit work | Lines/distinct | Blocked by exactly one line |
| --- | --: | --: | --: | --: | --: | --: |
| 5ED | 434 | 58 | 18 | 3.2 | **1.00** | 18 of 18 |
| FEM | 102 | 102 | 33 | 2.6 | **1.00** | 28 of 33 |
| 6ED | 335 | 169 | 62 | 2.5 | **1.00** | 57 of 62 |
| HML | 115 | 115 | 41 | 2.5 | **1.00** | 36 of 41 |
| ALL | 144 | 144 | 88 | 1.3 | 1.02 | 67 of 88 |

(TMP/MIR/VIS/WTH were not re-fetched — none is a near-term candidate and their
pre-ICE rows all read ~1.7–2.2 new-per-unit with no repeated sentence.)

**The headline movement is 5ED, and it is Ice Age's doing**: its "new to pool"
fell 147 → 58, because most of what 5ED still had to offer was ICE reprints. At
58 new cards over 434, Fifth Edition is now closer to 4ED's shape than to a
work set — 18 pieces of work, every one a card blocked by exactly one line —
but it still reprints from FEM and HML, so the sequencing rule holds it behind
them. Alliances got cheaper too (99 → 88 unsupported; cumulative upkeep
shipped with ICE and its ALL 9 / MIR 5 / VIS 5 / WTH 14 printings now cost
whatever *else* they print).

**The leverage argument did not move.** Four of the five candidates measure
exactly 1.00 lines per distinct sentence — every refused line a different
sentence, no production shared by even two cards — and ALL's 1.02 is noise, not
a subsystem. ICE was the last candidate that forced one. So the next set is
chosen on card count, block position and what the ingest teaches, not on
leverage that is not there — and on that reading **FEM is the pick**: smallest
(102 cards, 33 unsupported), the only near-term insert (which rehearses the
printing-order machinery), and the first of 5ED's two remaining sources.

**FEM is the only near-term candidate that inserts rather than appends.**
Fallen Empires released 1994-11-01, between DRK (index 7) and 4ED (index 8), and
the manifest is printing-ordered because `CardDefinition.original_printing` is
the first entry in `printings`. Nothing in the pool would move — all 102 of its
cards are new here — but `test_the_shipped_sets_are_in_printing_order` compares
the `released` dates the entries carry, so the index is not optional. HML
(1995-10-01) and everything later append.

**The three remaining zero-new-card sets are not 4ED again.** FBB, SUM and 4BB
are the only sets that would bring nothing new to *this* pool, and they are the
Revised and Fourth lists a second and third time: they buy printings and no
cards, and 4ED already produced the one finding that shape had to give (a guard
that could not tell the manifest roles apart). `set_progress.json` lists ten
more zero-new-card sets, but that field is relative to the whole **release
line**, not to this pool — 5ED and 6ED read 0 there and bring 147 and 200 cards
here, because the sets they reprint from are not ingested. Sequence a core set
after its sources or it arrives carrying cards nothing supports.

**Three structural gaps bound everything after Innistrad**, and the first is a
hard wall rather than a backlog. `card_loader.REQUIRED_FIELDS` demands a
top-level `mana_cost`, which a transform card does not have, so a double-faced
card raises `ValueError` on *load*. `_load_faces` populates
`CardDefinition.faces` and the only reader in the repo is `commander.py`'s
colour-identity derivation — the compiler has never seen a second face. That is
CR 709/710/712/714/715/720, 45 rules, none implemented; it already costs Origins
5 cards and M19 one. Second, keyword abilities stand at **28** of CR 702's 192
(`vocabulary.IMPLEMENTED_KEYWORDS`; cumulative upkeep was the twenty-eighth).
Third, **alternative costs (CR 118.9) do not exist** — `cast_costs.py` implements
*additional* costs well, and the phrase appears in the engine only in comments —
which blocks the buyback/flashback/evoke/madness family wholesale.

## Fallen Empires (FEM) — measured, in progress

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

Open, each recorded with what it costs rather than scheduled here:

- **A mana ability with a rider uses the stack** (CR 605.3/605.1a).
  `is_mana_ability` reads only the top-level instruction kind, so Farrelite
  Priest, Initiates of the Ebon Hand, Barbed Sextant and all six Ice Age
  painlands are pushed and resolved like ordinary abilities — which means their
  mana cannot be produced while a cost is being paid.
- **A coloured pay-or-sacrifice upkeep cannot tap lands.**
  `can_pay_upkeep_mana` covers coloured pips from floating mana alone while
  letting the generic part tap, so **Stasis, Drought, Justice, Conversion, Dance
  of Many, Sunken City, Glaciers, Breeding Pit** and both FEM Chants are
  sacrificed on the first upkeep in AI or headless play with the right lands
  untapped. Every other offered price in the engine taps lands, citing
  CR 605.3b. Ten cards across six sets.
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

**Where the pool stands** (regenerate rather than trust these): 1,508 unique
cards over **11** sets, 100% supported. Grammar parses 87.3% of lines, lowers
86.4% and executes 55.1% (`GRAMMAR_COVERAGE.md`). 4.2% of supported cards carry
a name-keyed hook — 63 cards, **69** entries in 6 registries
(`HOOK_RELIANCE.md`) — the number that decides whether this architecture reaches
26,113 cards. Parse coverage: 1,506 of 1,508 supported cards fully claimed, 2
acknowledged, **0 unclaimed** (`PARSE_COVERAGE.md`). `RULES_PROGRESS.md` is the
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
What is close, at the cull:

| Module | Lines |
| --- | ---: |
| `riders.py` | 995 |
| `parser.py` | 995 |
| `lowering/library.py` | 995 |
| `lower.py` | 993 |
| `subject_verb.py` | 989 |
| `lowering/game.py` | 969 |
| `lowering/_common.py` | 964 |
| `effects/board.py` | 958 |

**Four modules are within ten lines of the cap and three are within five**,
which is the tightest this table has ever been — the next template landing in
any of them splits it, and eight modules are now in the danger band where two
used to be. That is what a set of Ice Age's size does to a grammar: the families
absorbed the work, and the absorption is visible as a file count pressing on one
number.

`lower.py` is the one whose growth is **structural rather than a failure to
split**: its dispatch chain grows by three lines per node type by construction.
78 of its branches were pure `isinstance(statement, X) → _lower_x(statement)`,
156 lines saying what a dict says in 78; they are `_BY_NODE_TYPE` now, read
before the chain, which is safe because no class in the table appears elsewhere
in the chain and none inherits from another. The chain keeps every branch that
*decides* something, and the next node costs one line rather than three. When
this file crosses the cap again, look for the same shape before looking for a
family line.

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
