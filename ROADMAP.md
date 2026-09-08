# Scaling Roadmap

Target: grow the card pool from **3,109** unique cards — twenty-one sets,
LEA/LEB/2ED/ARN/ATQ/3ED/LEG/DRK/FEM/4ED/ICE/HML/ALL/MIR/VIS/5ED/WTH/TMP/STH/EXO/
M21, all shipped and all supported — to the full release line: **140 sets,
33,594 printings, 26,113 unique cards** per `set_progress.json`.

**The reprint shape recurs and is worth planning for.** `set_progress.json`
records thirteen sets in the release line with zero new cards, and nine are
still ahead: the foreign-language base sets (FBB, SUM, 4BB), the rest of the
core-set line (6ED through 10E) and Timeshifted. Each promotes the way 4ED and
5ED did — an ingest and a rehearsal rather than a set of rounds — provided it is
sequenced *after* the sets it reprints from. Ingested before them it arrives
carrying cards nothing supports, with their origins mis-stamped, and the shape
is lost.

**Read this before parser or card-data work. It is the standing brief for the
next set, and nothing else.** Every claim below is either a rule the next round
must not break, a piece of work nobody has done, or a lesson that cost a round
to learn. It is deliberately *not* a journal. The round-by-round narrative —
the founding audit, the parser migration (`engine/parsing/` is deleted and
`engine/grammar/` is the only parser), M21's 140 rounds, Antiquities' 30,
Legends' 36, The Dark's twelve parallel groups, Ice Age's 42 rounds plus four
waves, and the wave-by-wave accounts of FEM, HML, ALL, MIR, VIS, WTH, TMP, STH
and EXO — lives in git history. Read a round there when you need the reasoning
behind one of these bullets; do not add a new round here.

The process a set follows, phase by phase, is `SET_PLAYBOOK.md`. Numbers go
here, process goes there, and neither repeats the other.

**Why the journal is culled, and this is the fourth time.** It first reached
2,700 lines, of which 2,350 were narrative that no longer changed anyone's
decisions (culled at `ee28617`). Ice Age put 1,800 back (readable at and before
`49f74af`), Homelands 400 (at and before `0a1ce5d1`), and the nine sets from
Fallen Empires to Exodus put **5,300** back — the file reached 6,360 lines, of
which fewer than a thousand were doing work. Those journals are readable at and
before `d7ba7f67`. The same rule applies each time: a file nobody reads to the
end is a file whose *live* items go unread with the dead ones. Everything that
was still doing work is below, and every open item was re-probed against the
code on 2026-09-07 before it was kept.

---

## Standing invariants

Anything that weakens these is a regression regardless of what it enables:

1. **No silent wrongness.** A card may fail loudly as unsupported with a
   reason; it may never resolve as something other than what it says.
2. **The suite stays fast.** **17,804 tests**, CI budget **940s**, CI-measured
   baseline **571s** (`ci.yml`), read from run 34081047302: `suite wall time:
   571s`, **60% of budget**, creep warning not firing. The test count is
   Exodus's Phase 6 reading (2026-09-07); the baseline predates the set, and
   the next Phase 0 owes CI a fresh one.

   The rules that number lives by, each learned at a cost:

   * **`BASELINE` takes the step's own output and nothing else** — `gh run
     view <id> --log | grep "suite wall time"`. It was recorded from a local
     run for three sets and compared against a runner-measured `ELAPSED`, so
     the creep warning never compared like with like. A *measured*
     local-to-runner multiplier is good enough to size a budget and not good
     enough to set the baseline: it grows with the suite (1.72 at 11,176
     tests, 1.88 at 11,923) and then collapsed to 1.00 at 17,000, so a local
     reading is no longer the conservative estimate and can err either way.
   * **A baseline cannot be read from a branch nobody pushed.** The number went
     stale for two sets because 215 commits sat unpushed, not because anyone
     declined to look.
   * **Raising `BUDGET` is a decision, not maintenance.** It has been raised
     five times, each against the gate (HML's at 90% of the old budget, VIS's
     at 94%), and it is deliberately *not* raised at 60%. The next raise takes
     it to ~1,140, on the reading that crosses ~750s, not on a set boundary.
     Today BUDGET is 1.65x BASELINE rather than the ~2x this gate wants, so the
     creep warning sits 9% below the gate instead of ~22% — it still fires
     first.
   * Growth is real and mild: +14.4% tests took +21.5% runner wall time, the
     same super-linearity ICE measured. `--durations` shows no single culprit
     (a 27s parse-coverage setup, one 17s AI simulation, then a long tail of
     pool-wide guards at 2–6s each); the sweeps that walk every card scale
     with the pool, and that is what grew. The `slow` marker exists if the
     AI-batch tests are ever the growth.
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
is Ice Age's, and a bare set code (FEM, ALL, VIS, TMP, STH, EXO) names that
set's wave journal, readable at and before `d7ba7f67`.

### How a round is chosen

Sort the unsupported cards by **first failing clause** — `compile_line` names
the exact refusal, which beats reading the aggregate report buckets — then rank
by cards-per-change. Round 37 found 59 of 87 remaining cards blocked by exactly
one line, at which point the question stops being "what is the biggest
mechanism" and becomes "which single line is cheapest per card". A block that
needs two rounds is worth splitting only if neither half ships a card alone.

**Re-measure a block's priority before acting on it, including the ones below.**
The legend rule sat open for a year and a half arguing its own urgency from
"all eleven legendary creatures in the pool are M21" — true when written, and
stale the day Legends took the pool to 91 legendary permanents. A card count
written in prose is a claim about the pool with no test behind it, and it
decays in either direction; every bullet here that carries a number should be
re-run before it is cited.

**Re-probe the refusal itself, not only its priority.** The cleanup before Ice
Age found nine "deliberate refusals" already implemented; the one after it found
five recorded items closed without their entries moving; this cull found three
more (the mana-ability rider, the counters back-reference, the noun-draft
guard). A refusal or a defect recorded here is a claim about the code with no
test behind it.

### Recorded, measured, and not yet fixed

Each of these was measured when it was written; each carries the date it was
last re-probed. Re-probe before scheduling one — and re-probe the *premise*,
not only the work: an entry whose premise expires ("the set is measured", "only
one card prints this") reads as a work item long after it stopped being true.

- **Supported is not working, and the card-level instruments cannot tell.** A
  card is supported when **any** line is, so a card can report supported while
  another line produces nothing — or the wrong thing. Four shapes, in the order
  they were named:

  1. **The hollow line** — an ability part with no instruction.
     `scripts/support_report.py --hollow-lines` sees it, and it is a Phase 3
     exit criterion rather than only a Phase 2 reading: Antiquities read 85/85
     for thirty rounds with three cards in it. **It reads one today**
     (2026-09-07): Cyclopean Tomb, a line a registry implements in full and the
     compiler cannot see.
  2. **The unclaimed sentence** — a line no reader claims, on a card some other
     line makes supported. `parse_coverage.py --set <CODE>` sees it and is
     advisory for a measured set, so read it from the first backlog round:
     Mirage reached 335/335 with thirteen such sentences on eleven cards, six
     admitted into the support gate by a single whitelist word, and needed a
     fourth wave.
  3. **The channel mismatch and the runtime decline** — a line that parses,
     lowers and compiles, and does nothing at run time. Equipoise chose the
     right permanents and phased out none (a scratchpad channel whose arity was
     settled and whose element type was not); Three Wishes' opening sentence
     reached a handler that refuses at run time for an instant. **No
     instrument in this repo can see these.**
  4. **The too-strong card** — a narrowing dropped, a cost charged as free, a
     sweep ignoring its own exemption. Every set since Ice Age found six to
     twenty-four of these in *already-shipped* cards, none with a failing test
     and none visible to any census, because all three instruments ask whether
     a line produced *something*. Two things find them: giving the behaviour a
     game (the Rock Hydra step), and the whole-pool compiled-program
     differential (`scripts/oracle_diff.py`) before and after any grammar
     change — filtered for defaulted-field repr noise it names exactly the
     cards that moved, and the repr is what makes the narrowing class visible,
     so filter the comparison rather than suppressing the field.

  What a registry claims and does less than it says is only findable the Rock
  Hydra way: Kudzu's dispatcher lived inside `tap_land_for_mana`, a land tapped
  by an Icy Manipulator destroyed nothing, and the census read it as done.

- **The verification backlog is accepted, by decision (2026-08-28).** Derived
  `equivalent` was the lever nobody had pulled, and it is exhausted:
  `behaviour_signature.py` distinguishes roughly one behaviour per card, so no
  amount of pulling reaches the untested count (**2,495** today). An in-game
  pass is therefore **not a required validation step**: promotion gates on
  Phase 4, regressions are caught by the suite and `simulate_ai_games.py`, and
  `CARD_VERIFICATION.md` is read as a log of what a human happened to check.
  The count that matters is **failures**, and it stands at **0**. A card
  recorded failing is a live bug, and fixing the code does not clear the row —
  Candelabra of Tawnos and Silent Dart went on reporting ❌ for three days after
  their fixes landed. Re-check it in the running app and record the pass
  through the Debug Menu, or the repo goes on advertising a live bug.

- **The printed-name ratchet's residue** (re-probed 2026-09-07).
  `tests/engine/test_printed_name_reads.py` separates a *dispatch* on
  `card.name` from a *mention* of it; the four dispatch sites that were live
  Clone-shaped bugs are fixed, each with a CR 707.2 test. **35 reads in 9
  modules are ratcheted** (counts may only shrink), and 25 of them are one
  migration: the upkeep-prompt wire protocol (`phases/upkeep_effects.py`,
  `phases/upkeep_step.py`) keys prompts by printed name on both the write and
  the read side. Draining it means `permanent_id` keys on both sides in one
  round, which also stops two same-named permanents sharing one prompt answer.
  Two dispatch-in-spirit shapes are invisible to the classifier: `commander.py`'s
  CR 903.10a damage tally keys by name through an intermediate tuple (harmless
  while no pool commander can change names), and names carried into records
  whose comparisons happen later on plain `.name` (`dead_name` is *correct* by
  CR 707.2 — copy effects end on leaving the battlefield).

- **Six toll cards have an unpriceable side.** `ai_valuation.toll_branch_loss`
  prices a toll's two losses and `ai_policy.toll_decline_is_smaller_loss`
  compares them. Of the pool's 22 toll cards, 8 are decided by the comparison,
  8 are mana-priced and deliberately left to the floating-mana policy, and 6 —
  counter that spell, a coin flip, counter placement: Mana Vortex, Amulet of
  Quoz, the Chants, Koskun Falls, Essence Vortex — still take "pay tolls". The
  comparison reaches them when those losses have valuations.

- **CR 613.8 dependency is not implemented, and Blood Moon/Conversion is its
  reproduction.** Both `land_types.py` predicates judge against
  `layer_bridge.types_before_timestamp` and board-wide layer-4 statics chain in
  timestamp order (CR 613.7), so the order is *observable*: Blood Moon earlier,
  Tundra ends a Plains; Conversion earlier, a Mountain. Under full rules
  Conversion depends on Blood Moon and both orders yield Plains. The
  Conversion-first test says in its docstring that its expectation is the one
  that must flip. Recorded 2026-09-02; no other pool interaction is known to
  need it.

- **CR 608.2b is enforced for instants and sorceries only.** "If all its
  targets are now illegal, the spell or ability doesn't resolve" is one gate,
  `legality.illegal_targets_refusal`, asked once above the instructions;
  CR 601.2c's announcement half is its twin, `legality.cast_target_refusal`.
  One clause is also asked of abilities, as a separately named gate (EXO):
  `legality.stale_comparison_refusal` re-asks a printed comparison between two
  seats ("target opponent who has more life than you do" — the Keepers, the
  Oaths) at resolution, bounded to specs carrying `compared` and to objects
  whose compared seat is their **only** printed target. It is not a down
  payment on the three declines below, each of which is its own round:

  * **A triggered ability's targets.** The death sweep enqueues a dies-trigger
    while the dying permanent is still listed, so Blazing Effigy's "it deals 3
    damage to target creature" records the dying Effigy itself and reaches the
    right creature only by falling back to the index. Asking 608.2b of that id
    counters an ability the engine mis-targeted and reports it as a
    rules-correct fizzle. The fire sites have to choose targets after the
    permanent has left first. The same resolver leaves an activated or
    triggered ability whose stamped graveyard choice vanishes falling to its
    untargeted deterministic pick, which can pick a card nobody named.
  * **A spell whose target may be a player** ("any target", a divided one). A
    seat and a chosen player reach a stack item through the same
    `target_player_index`, so "every target is illegal" is not answerable: a
    Fireball split between a creature and its controller looks exactly like
    one aimed at the creature alone.
  * **An Aura, and the same-name graveyard clamp.** An Aura whose enchant target
    has left is binned by CR 704.5m one sweep later — the same destination by a
    different rule. Two copies of one card in one graveyard are literally one
    `CardDefinition`, so resolution clamps to the last surviving copy; the
    *unambiguous* half is closed (a stamp with no surviving copy answers None,
    and a Resurrection whose target is exiled in response leaves the stack
    unresolved). One residue: an untargeted sequence-wrapped graveyard spell is
    still accepted against an empty graveyard and resolves doing nothing —
    CR 601.2c's "can the announcement be made at all?" is asked per primary
    kind only.

- **Five handler paths still resolve by index alone**, reached today only by
  instants and so caught by the CR 608.2b gate first; the next *activated*
  ability printed with the same text walks in. Re-verified 2026-09-07 — still
  five, none reading `target_permanent_id`: `board_misc.mark_text_modified`,
  `combat.remove_creature_from_combat`, `prevention.apply_prevention_shield`,
  `zones.exile_target_creature_until_eot` and
  `zones.exile_creature_gain_life_equal_to_power`. All five also carry a "fall
  back to the first matching permanent" default, the look-alike class.

- **`land_enters` has one fire site, inside land-*play* resolution**
  (`mixins/stack/resolution.py`), so a land an effect puts onto the battlefield
  triggers nothing — Ankh of Mishra deals no damage for one. The fix is nearly
  free: the row can fall to `matching_permanent_enters`, whose "that land's
  controller" already reads `event_subject_controller`. (FEM; re-verified
  2026-09-07.)

- **`engine/static_bonuses.py` line 340 holds literal backspace characters
  (U+0008)** where a regex word boundary was meant, so its "and" and "and from"
  alternatives have never fired and only the comma splits. A repo-wide scan for
  control characters in `.py` files finds exactly it and one harmless docstring
  twin. **Not fixed on purpose** — it wants its own round with a differential,
  because making those alternatives fire changes what the table reads. (STH;
  still there 2026-09-07.)

- **`web/` layer reads are unguarded.** `tests/engine/test_layer_reads.py`
  walks `engine/` only, and the last two layer-read bugs were both in `web/`
  and both found by a promotion smoke test rather than a guard — most recently
  `serialization.py` sending `is_aura: False` for a Licid that had become an
  Aura. The documented accessor is also the wrong one there: "becomes an Aura"
  is a CR 613 layer-4 type change, so `effective_card.type_line` (layers 1 and
  3) still reads "Creature — Licid"; only `has_type` / `is_creature` /
  `displayed_type_line` answer. Extend the guard's walk to `web/`. (STH.)

- **CR 508.5's second sentence is not implemented** — "if that creature is no
  longer attacking, the defending player it's referring to is the player that
  creature *was* attacking". `_prune_combat_state` clears `attacking` and
  `defending_player_index` together before rebuilding, so the memory is gone
  by the time anything could ask. Nothing in the pool asks after removal from
  combat, so this is a gap with no card behind it — recorded rather than
  fixed, because a fix with no card to verify it is a guess.

- **Four smaller ones, each with no card behind it today** (re-probed
  2026-09-07). `_perform_entry_state`'s "enters with N +0/+1 counters" branch
  writes `metadata["plus_0_1_counters"]`, a key nothing reads (`_PT_COUNTER_KEYS`
  has no `+0/+1` row, so `pt.pt_counter_key` spells it differently), and it
  assigns rather than accumulates. `prevention.source_has_type` falls back to
  the printed type line for a source that is not a `Permanent`, so a shield
  reading "by creatures" would answer for a creature *spell* on the stack.
  `@upkeep_effect("upkeep_self", "deal_damage")` ignores its recipient payload
  and always damages the controller — right for every card that reaches it.
  Living Artifact's vitality counters bypass the counter seam
  (`mixins/effects.py` writes `metadata["vitality_counters"]` behind a
  substring test), skipping the cap enforcement and the emptied-kinds record
  every other placement goes through.

- **`handlers/_common.py`'s `"triggering_spell"` mana value has CR 202.3b's
  gap** — it reads the cast card's `cmc`, so an {X} spell's mana value on the
  stack is wrong. The same bug was fixed for Spell Blast and Mana Drain through
  `targeting.stack_object_mana_value`; this site cannot use it because the cast
  fire site records only the `CardDefinition`, not the stack item. Fixing it
  means giving that fire site the object. (Re-verified 2026-09-07.)

- **The browser names one object for a counted cost.** `web/schemas.py` and
  `web/actions.py` accept `cost_permanent_ids`, but `web/static/app.js` still
  sends a single `cost_permanent_index`, so Goblin Warrens' second Goblin and
  Night Soil's second card take the deterministic default. The cost is fully
  charged; only the *choice* is partly the engine's. The same path has no
  graveyard picker at all: Haunting Misery's payer does not choose which X
  creature cards leave (CR 601.2b lets them), and the top-down default is the
  floor until there is one. (FEM, WTH; re-verified 2026-09-07.)

- **Ten flat spellings of the testable-keys check remain in `lowering/`**
  (down from 39 at VIS), each a set difference over the outer payload's keys
  that answers "testable" for a nested phrase whatever the inner phrase says,
  where `_filters.testable_filter_payload` recurses and names the untestable
  keys. Left alone as a merge hazard with no card behind it; take it between
  waves, not during one.

- **`engine/auras.py` is 2,839 lines.** It is outside the grammar cap, but it
  is visibly two files — the claim tables, and the attach/derive machinery from
  `auras_attached_to` down — and it has grown 700 lines since Alliances
  recorded the same observation at 2,111. Split before the next Aura-heavy
  round, not during it.

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
amount under a different key", a fact about a fire site and never about the
rule. A refusal resting on where an event happens to be announced from expires
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
40. **A decline names where its author looked, not where the mechanism is.**
    Two of Suffocation's four declined parts were already built in
    `engine/damage_ledger.py`, written two sets earlier for Backdraft (ALL);
    every one of Stronghold's five wave-2 parts lists was stale in the cheap
    direction, naming parts another group had already landed; and Visions' cost-
    picker deferral rested on "no client can load a `measured` set", which had
    stopped being true a promotion earlier. Re-read a decline's premise against
    the code before building what it names — the same decay as a card count in
    prose, one level up.
41. **A draft that accepts any attribute drops a narrowing silently, in the
    widening direction.** `nouns.py`'s filter draft was a plain dataclass, so a
    postmodifier assigning a field the builder never copied out *succeeded* and
    was dropped, and Ugin exiled the colourless permanents its sentence
    excludes (TMP); the guard comparing declared fields against the builder
    passed, because a bare local is not a field. `_FilterDraft` carries slots
    now, and the first thing the slots guard found was exactly that local. Give
    a scratch object slots wherever a typo would otherwise widen a card.
42. **Quoted text is oracle text no census walks.** An ability a card grants a
    token ("attacks each combat if able" on Pursued Whale's Pirates) or a tribe
    (`All Slivers have "…"`) is compiled from a string inside a payload, and
    none of the five instruments reads inside it (TMP). When a set prints the
    shape, sweep the quoted lines by hand and give one a game.
43. **The asymmetric gate: a question asked on one of the paths that must ask
    it.** Six of these were found during Urza's Saga, by five independent
    groups, and every one was found by *a card* rather than by an instrument.
    They are one class and the class has a shape worth stating:

    > A rules question — a predicate, a narrowing, a fact only the caller can
    > supply — has **more than one site that must ask it**, because the engine
    > has more than one route to the same rules moment. The relation between
    > those sites exists only in the author's head. One site asks; its twin does
    > not; nothing relates them, so nothing notices.

    What makes it its own class rather than "a bug" is the *evidence profile*.
    The correct code is present and provably correct where it is, so no test of
    the implemented site fails. No compiled program moves, so `oracle_diff` is
    blind. The line is claimed — by the site that does ask — so `parse_coverage`
    is blind. An instruction was produced, so `--hollow-lines` is blind. The
    failure is silent in both directions: **fails open** (a restriction enforced
    by nothing, wrong in the player's favour) or **fails closed** (a narrowing
    refused for want of an argument, so the card does nothing and says
    "found nothing to damage").

    The six, with the pair in each:

    - a non-creature permanent's own death (W1G4) — the `dies` enqueue inside
      `if permanent.is_creature:`, where CR 700.4 is about a permanent;
    - `max_targets` on the **cast** gate and not on the **activation** gate
      (W1G5) — Vile Requiem with one verse counter destroyed three creatures;
    - `_sweep_kind` dropping narrowings its own two sibling lowerings refuse
      (W2G1) — a fused damage sweep burning a larger board than the card
      prints;
    - the **damage dealer** passed as the permanent on one arm of
      `handlers/damage.py` and as the printed card on eleven others (W3G5) —
      twenty shipped permanents whose lifelink gained nothing;
    - the **defending seat** handed to `subject_matches` by two handlers and by
      neither of the three others that meet the same printed phrase (W3G5) —
      Sidar Jabari, Jangling Automaton and Scalding Salamander all dead;
    - CR 603.4's intervening-'if' checked at five hand-written fire sites and
      at neither of the two seams every other fire site funnels through (W3G5).

    **The instrument.** `scripts/unasked_narrowings.py` asks the question for
    one pair — the fail-closed half, which is the tractable one. It joins a
    census of the pool (for each instruction kind, which argument-requiring
    narrowings do the compiled payloads carry) against a static read of
    `engine/` (for each `@effect_handler` kind, which keyword arguments does
    anything within two hops hand to `subject_matches`). Validated
    retrospectively: run against the pre-round engine it names all three of the
    dead cards above and nothing else that this round found; run after, those
    three are gone. Advisory, like `rules_gaps.py` — eleven standing findings
    today, most of them handlers that answer a printed "that player" themselves
    before calling the matcher, which a static read cannot see.

    **The half it does not cover, and the cheapest next step.** The other pair
    shape — one *rules moment* enforced at N unrelated sites — has no shared
    helper to instrument. It does have a marker: `engine/` cites the CR rule at
    every site that enforces it. CR 603.4 is cited from **24 files**. Extend
    `scripts/rules_gaps.py`, which already reads every CR citation in
    `engine/`+`web/`, to rank rules by *how many files cite them with no shared
    call between those files* — a rule with five copies of its check is a rule
    four of them will drift from. That is an advisory in a file that already
    exists, and it is the version of "which predicates are asked on one of a
    pair of paths?" that does not need a new instrument at all.

---

## The next set, measured rather than guessed

**Which set is next is a rule, not a name.** This section named 6ED for three
sets and said Alliances "appends" for one, and each time the pool moved
underneath the sentence without anyone editing it. The rule, which does not
expire:

> Take the **earliest unshipped set by release date** whose reprint sources all
> ship. A set ingested before a set it reprints from stamps those cards with the
> wrong `original_printing`, and the prefix guard cannot see it (it compares
> what is already there); `test_the_shipped_sets_are_in_printing_order` is the
> assertion that can.

Run against `set_progress.json` on 2026-09-07 it answers **Urza's Saga** (USG,
1998-10-12, 335 cards, 309 new to the pool), then Urza's Legacy (143 cards, 140
new), then 6ED — dated 1999-04-21 with **0** new cards against the shipped pool,
so it waits for the whole Urza block the way it waited for the Mirage and Tempest
ones — then Urza's Destiny and Mercadian Masques. **USG has never been measured
here.** Every ingest estimate this file has carried was stale by the time it was
read, so no candidate table is kept: measure at Phase 1, against the compiler of
that day.

**Phase 1 opens with the census, not the ingest.** Fetch the candidate to a
scratch directory (never `cards/`) and read **all five** instruments beside each
other:

| Instrument | What only it can see |
| --- | --- |
| `support_report --set <CODE>` | the unsupported cards — the card census |
| `--refusals` | every refused line with its exact site; lines per distinct sentence |
| `--fragments` | the n-gram census over refused lines — where the cycles are |
| `--hollow-lines` and `parse_coverage --set <CODE>` | supported cards carrying a sentence nothing implements |
| `picker_sweep --set <CODE>` | a supported card no player can cast (the Roots class) |

The sentence census has read 1.00–1.03 for **nine consecutive sets** and been
the wrong number to plan from every time: its largest sites are the generic
errors ("expected a subject", "unconsumed text"), which name no family. The
fragment census one level down is what found Alliances' land cycle, Homelands'
untap-denial family, Weatherlight's graveyard-top spine, Tempest's Licids and
Slivers, Stronghold's en-Kor cycle and Exodus's Oaths and Keepers. The two
sentence-level instruments add the cards the card census structurally cannot
see — FEM 5, ALL 5, MIR 19, VIS 18, WTH 13, TMP 26, STH 7, EXO 0 — and at
Mirage that debt stayed invisible until the promotion because `parse_coverage`
gates on the shipped half alone.

**Read the keyword census against three tables, not one.** The registry diff
(`vocabulary.IMPLEMENTED_KEYWORDS`, 31 words) misreads in both directions: a
keyword implemented as the ability CR 702 says it *is* — cumulative upkeep,
buyback, equip — reads as missing, and `oracle.UNSUPPORTED_KEYWORDS` outranks
the registry entirely, so a word there costs every card printing it whatever
the grammar reads (Legends' rampage, Mirage's phasing). Shadow and flanking were
each a whole bucket the refusal census could not see, because the keyword line
fails at the line gate with every grammar line clean; buyback failed nowhere and
cast twelve cards at their printed cost with no offer.

**Rehearse the wrong insert at every promotion**, whatever the overlap count
says. The prefix guard tests whether an *existing* card's origin moves, so it is
blind to an all-new set from any position and to the new set's own cards
(Volcanic Geyser at MIR). Stronghold read as all-new, and its one reprint,
Shock, is in **M21** — so STH's position decided Shock's origin with every guard
green either way. Count a reprint against the set that actually prints it.
Exodus's clean result was *measured* at the promotion, in both directions, which
is the difference between "it looks immune" and "it is".

**Two structural gaps bound everything after Innistrad**, and the first is a
hard wall. `card_loader.REQUIRED_FIELDS` demands a top-level `mana_cost`, which
a transform card does not have, so a double-faced card raises `ValueError` on
*load*; `_load_faces` populates `CardDefinition.faces` and the only reader is
`commander.py`'s colour-identity derivation — the compiler has never seen a
second face. That is CR 709/710/712/714/715/720, 45 rules, none implemented;
it already costs Origins 5 cards and M19 one. Second, keyword abilities stand at
**31** of CR 702's 192 in the registry, with buyback, cumulative upkeep, equip
and now **cycling (CR 702.29) and echo (CR 702.30)** implemented below it.
**Read that number with the registry's actual question in mind**, which two USG
groups had to work out independently because this line does not say it:
`IMPLEMENTED_KEYWORDS` admits a keyword being *granted* or *named* ("gains
flying", "creatures with flanking"), so a keyword defined as a **rewrite** is
absent from it by design — by the time any reader sees the card, the word is
gone and the ability it means is in its place. `test_keyword_registry`'s
bare-keyword-card guard is what forces the choice: listing cycling would mean
either failing that guard or admitting a costless cycling that charges nothing.
So "31 in the registry" undercounts what the engine implements and always has;
the honest reading is 31 granted-or-named plus five rewrites. Alternative costs (CR 118.9) were the third gap and
are closed: `engine/alternative_costs.py` reads the "rather than pay this
spell's mana cost" template, the client offers optional and repeated costs
through `legality.cast_cost_offers`, and the buyback/flashback/evoke/madness
family is blocked only on its own keywords.

## Where the sets landed

The numbers a Phase 1 census is estimated against. A round is a serial round;
a wave is five parallel worktree groups integrated serially.

| Set | Cards | Supported at ingest | To 100% |
| --- | ---: | ---: | ---: |
| M21 | 285 | 58% | ~140 rounds |
| ATQ | 85 | 56.5% | 30 rounds |
| LEG | 310 | 32.9% | 36 rounds |
| DRK | 119 | 47.9% | 12 groups, 3 waves |
| 4ED | 368 | 100% | 0 (pure reprint) |
| ICE | 373 | 49.3% | 42 rounds + 4 waves |
| FEM | 102 | 67.6% | 1 wave + 1 closer |
| HML | 115 | 66.1% | 2 waves + 1 closer |
| ALL | 144 | 43.1% | 3 waves + 3 closers |
| MIR | 335 | 54.9% | 10 rounds + 4 waves |
| VIS | 167 | 59.3% | 4 waves |
| 5ED | 434 | 100% | 0 (pure reprint) |
| WTH | 167 | 59.9% | 2 waves + 1 closer |
| TMP | 335 | 67.8% | 4 waves |
| STH | 143 | 67.8% | 2 waves |
| EXO | 143 | 63.6% | 2 waves + 1 closer |

Three data points shape an estimate. **Legends** is the warning: the lowest
starting coverage and the flattest ranking — after eight rounds, 113 of its 135
remaining cards refused exactly one line — because it was designed before
templating existed, so the generalise-first rule runs out of general work early.
**Ice Age** is where serial rounds ran out before the cards did: 42 rounds
bought 100 cards and four waves bought the remaining 89 in a fraction of the
calendar time, with integration rather than authorship as the constraint.
**Tempest** is the modern shape: the largest work set, four waves and eighteen
groups at roughly one integrator-hour per wave-hour (the ratio ICE set), zero
hooks added across 335 cards — and around twenty already-shipped cards found
mis-playing along the way, which every set since Ice Age has repeated and which
is the argument for the Rock Hydra step.

**Where the pool stands** (regenerate rather than trust these; read
2026-09-07): 3,109 unique cards over 21 sets, 4,873 printings, 100% supported.
Grammar parses 90.5% of lines, lowers 89.8% and executes 60.0%
(`GRAMMAR_COVERAGE.md`). **1.9%** of supported cards carry a name-keyed hook —
58 cards, 64 entries in 6 registries (`HOOK_RELIANCE.md`) — and the projection
that implies for the release line has fallen from 1,195 hand-written entries to
**538**, across nine consecutive sets that added no hook and retired several.
That is the measure moving the way the architecture needs it to. Parse
coverage: 3,107 of 3,109 supported cards fully claimed, 2 acknowledged, **0
unclaimed** (`PARSE_COVERAGE.md`). `RULES_PROGRESS.md` is the CR coverage
tracker. `CARD_VERIFICATION.md` is a log, not a target: 572 passed (398
in-game, 174 auto), 42 equivalent, 0 failed, 2,495 untested.

**Read a ratchet move as a measurement change before crediting it as a
regression.** Retiring Kudzu's dispatcher moved its line into
`CARD_LINE_INSTRUCTIONS`, the registry the *line* measure counts, so hooked
lines rose while hooked cards did not: the old number was under-reporting a
line hooked all along in a registry the measure could not see. A channel move
in `PARSE_COVERAGE.md` is one sentence changing which reader claims it, not
what happens. And a pure reprint promotion moves the printing-weighted grammar
row on membership alone.

## Size watch

The 1,000-line cap on `engine/grammar/` modules is a scheduling signal, not
style: it fires when a family stops absorbing new work, and the split is
cheapest while the work that crossed the line is still in hand (idiom 13).

**There is deliberately no table of the closest modules here.** It went stale
the moment anyone worked, and at HML two groups planned around it and were
wrong — it named five modules at 989–995 that were at 571–978, while the two
that breached were the ones it did not name. The live reading is one line:

```powershell
find engine/grammar -name "*.py" | xargs wc -l | sort -rn | head
```

Read it at Phase 0 and pre-split every module **two or more groups will
reach**, not the tightest ones. Stronghold priced the difference with a card:
`lowering/characteristics.py` at 7 under was read as shared, left alone, and
cost Spined Sliver a wave. Every cap crossed since Visions was crossed *at
integration*, on nobody's branch, by two groups' additions summing — so a module
one group owns can be left to that group, and the module nobody owns is the one
that drifts.

**Every split so far fell along a line something else had already drawn.**
Reuse the other side's family name every time so the mirror re-forms instead of
forking: `destruction`, `keywords`, `tapping`, `types`, `trigger_tables`,
`sentence_clauses`, `upkeep`, `prevention`, `counters`, `redirection`, `exile`,
`zones`. Two wave groups independently made the *same* split of
`lowering/stack.py`, moving seven byte-identical functions — the strongest
evidence yet that these boundaries are found rather than invented. When no name
is there to reuse, take the name of the family the new one mirrors:
`lowering/prohibitions.py` is `permissions`' opposite on the same list. And a
module two families import is a floor, not a family — `lowering/_amounts.py`
and `lowering/_sacrifices.py` both arrived that way, when moving a shared helper
into `_common` would have pushed *that* past the cap.

**A module split needs three scans, not two**: the dead-import scan
(`tests/engine/test_import_hygiene.py`), the missing-name scan — a `NameError`
the moment the line runs, so run it *before* the suite; it fired three times in
one wave — and a scan for a function left byte-identical in both halves, which
no guard sees because the dead copy imports clean and is never reached.
