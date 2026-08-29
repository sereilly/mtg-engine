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
2. **The suite stays fast.** **9,176 tests**, CI budget **240s**, CI-measured
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

  **The census reads two today** — Creature Bond and Howling Mine, each a line a
  registry implements in full and the compiler cannot see (the death-damage
  template, which must read a toughness no payload can hold; the draw-step
  table). Kudzu left it on 2026-08-28, and it is the entry that shows why the
  census is worth running: applying the Rock Hydra test to all three found that
  two were fine and the third **had never fired at all**. Its dispatcher lived
  inside `tap_land_for_mana`, so a land tapped by an Icy Manipulator destroyed
  nothing — the exact bug `become_tapped`'s docstring says that seam was built
  to end, still present in the one card that predates it. As a
  `CARD_LINE_INSTRUCTIONS` line the trigger is announced by the seam like any
  other, so it fires however the land became tapped *and* uses the stack
  (CR 603.3) instead of resolving inline. Hooked cards and entries did not
  move (74 / 80); one registry went away.
  Paralyze and Capture Sphere left the census during Legends, when the machinery
  under them grew a real instruction; nothing about them was individually
  rescued, and the number is the census's to report rather than this bullet's to
  carry. Rock Hydra's automatic counter shield — the
  one the bullet below used to call "the Nine Lives class hiding behind a
  verified-sounding acknowledgement" — is implemented
  (`prevention.py:_remove_counter_per_damage`) rather than acknowledged, and
  its `IMPLEMENTED_ELSEWHERE` entry is gone. What the census cannot see is a
  *registry that claims a line and does less than it says*: that class is only
  findable the Rock Hydra way, by giving the behaviour a game. **The census is a
  Phase 3 exit criterion, not only a Phase 2 reading** — Antiquities read 85/85
  supported for thirty rounds with three cards in it (ATQ 30), and reaching zero
  took a round of its own.
- **The verification backlog is accepted, by decision, 2026-08-28.** It stood
  here as the largest standing debt in the repo, with derived `equivalent`
  named as the lever nobody had pulled. The lever was measured and it is
  exhausted: `behaviour_signature.py` distinguishes **1,049 behaviours over
  1,162 cards**, 148 cards share a class at all, and 48 unverified cards are
  covered by a passing peer. It cannot reach 708 — the pool is that diverse —
  so no amount of pulling clears the debt. An in-game pass is therefore **not a
  required validation step**: promotion gates on Phase 4, regressions are caught
  by the suite and `simulate_ai_games.py`, and `CARD_VERIFICATION.md` is read as
  a log of what a human happened to check rather than as a coverage target. See
  SET_PLAYBOOK.md's Known gaps for the same decision stated where the phases
  are.

  **A card recorded *failing* is still a live bug**, and that is the half this
  decision does not touch. Both open failures were closed in the round that
  wrote it: Candelabra of Tawnos (below) and Silent Dart, which the CR 602.2b
  activation gate had already fixed without anyone re-checking the row. The
  count that matters is failures, not blanks.

- ~~**Three shipped cards damaged the wrong player.**~~ *Fixed 2026-08-28.*
  Psychic Venom, Haunting Wind and Artifact Possession all print "that
  <object>'s controller" and all hang off the two tap announcements that
  `emit`ted with no payload — so the phrase fell through to `target_player` and
  hit the *trigger controller's opponent*. Psychic Venom on your own land
  damaged your opponent; Haunting Wind did it when you tapped your own Mox.
  `become_tapped` now freezes `event_subject_controller` (and the subject's
  `permanent_id`) into both announcements, and the two conditions joined
  `_EVENT_SUBJECT_CONTROLLERS`.

  **The tests that should have caught it could not**, and that is the reusable
  part: every existing fixture put the object on the *opposing* seat, where "the
  land's controller", "the seat that tapped it" and "the trigger controller's
  opponent" are one player. One of them even asserted the right claim in its own
  docstring — "the damage goes to the land's controller, not the Aura's" — and
  passed either way. The discriminating fixture is the one nobody plays:
  enchanting your **own** permanent.

- ~~**Candelabra of Tawnos resolves without asking how many lands to untap.**~~
  *Fixed 2026-08-28*, and the engine was never the problem — given an X and a
  list of ids it untapped exactly those lands, and `tests/sets/` proved it. The
  whole gap was the client, in three places that each hid the next: the
  activation cascade asked "does this target a land?" before "does it name
  several?", so the single-land picker claimed the card; the ability X prompt
  ran *after* that cascade and sent the ability the moment a number was chosen,
  with no targets; and `resolvePendingCastX` explicitly excluded
  `castAction === "activate"` from continuing into the picker. **An engine test
  that supplies the X and the targets itself cannot see any of this** — which is
  the general lesson, and the reason the new test is a wire test.

- **A trigger's "that player" back-reference falls through to `target_player`
  rather than refusing.** `lowering/_events.py` says in its own docstring that
  "a condition absent from a table refuses the line instead", and the damage
  family's last `elif` breaks that contract: a condition in neither
  `_EVENT_SUBJECT_CONTROLLERS` nor `_EVENT_SUBJECT_PLAYERS` silently becomes a
  *target* the card never offers. Censused at **11 triggered abilities**, of
  which only Brash Taunter genuinely prints "target opponent". Three were live
  bugs and are fixed (below); the other seven are correct **by accident** —
  Ankh of Mishra and Dingus Egg because their hand-written fire sites replace
  the compiled instruction outright with a `deal_damage_to_player` carrying
  their own `victim_player_index`, Manabarbs and the four
  `upkeep_enchanted_controller` Auras because a registry supplies the seat.
  Closing the fall-through therefore means moving those fire sites onto the
  compiled instruction first, or Ankh of Mishra becomes unsupported. **Its own
  round, and the census above is its work list.**
- **Two layer reads still disagree about the same land.**
  `_refresh_static_land_types` tests its *from* side against
  `effective_card.type_line` (layer 3) rather than `has_type` (layer 4), so
  Conversion cannot see a Mountain that Blood Moon made — two layer-4 effects
  CR 613.7 says should chain by timestamp. Deliberately **not** taken with the
  305.7 round above: asking `has_type` there reads layer 4's result while
  computing layer 4's inputs, so the fix is a dependency ordering rather than a
  changed accessor. Its `break` after the first matching source is the same
  round's second half — CR 613.7 chains statics, it does not pick one.

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

- ~~**CR 305.7's ability-loss half does not exist.**~~ *Fixed 2026-08-28.*
  `land_types.lost_abilities_to_type_change` is the one predicate and it has
  **three** readers, because an ability can act three ways and the rule has to
  reach all of them: layer 6 drops the printed keywords, the activation gate
  refuses the activated ones (beside Titania's Song, for the same reason), and
  `iter_triggered_abilities` skips the triggered ones. The last was the reader
  the recorded entry did not name — City of Brass's trigger is read off the card
  by the scan, not from the ability channel layer 6 strips, so a layer-6-only
  fix would have left it firing.

  The condition is that an effect **set** the type, asked of the *contributions*
  and never of the layer-4 result: "is this a Mountain?" is true of a printed
  Mountain, which has lost nothing. 305.7's last sentence — a land that gains a
  type *in addition* keeps its rules text — is the same distinction, and those
  live on the separate `GAINED_TYPES` channel the predicate deliberately does
  not read.
- ~~**`ACTIVATED_LABELS["sequence"]` reports 54 shipped abilities as damage.**~~
  *Fixed 2026-08-28.* Both wrapper kinds were wrong, not one:
  `sequence` → `activated_damage` and `if_then` → `activated_mana`, and each
  comment justified itself by citing the other. `if_then` was true of the
  Urza's cycle and false of Eater of the Dead, Land's Edge and Lesser Werewolf.
  They are `activated_sequence` and `activated_conditional` now, and the guard
  is structural rather than a list: a wrapper is a kind whose payload carries
  other instructions, and borrowing is that kind's label also being produced by
  a kind that composes nothing. **A wrapper label cannot be a leaf's bucket**,
  which is the general form of the bug and needs no list of either.
- ~~**A land whose colour was swapped away gives the wrong colour.**~~ *Fixed
  2026-08-28, and it was reachable from the shipped pool after all.* Quarum
  Trench Gnomes on a **Tundra** (a Plains, printed `("U", "W")`) leaves
  `("U", "C")`; asking for white paid **{U}**. `Permanent.produced_symbol_for`
  maps the request through the same swaps rather than falling back to
  `produced[0]`. The reason it read as unreachable is worth keeping: every
  existing test tapped a *basic*, whose one-entry list makes the fallback right
  by having nothing else to pick.
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

**Re-censused 2026-08-28** against the live compiler, ten candidates fetched to
a scratch directory (never `cards/`). 4ED has shipped, so the free option is
spent. The standing rule held: the shape did not change much, and the numbers
below are the current ones.

**The leverage is gone everywhere, and the measurement is now sharper than
"1.00 to 1.15".** Lines-per-distinct-sentence over each candidate's refused
backlog:

| Set | Cards | New to pool | New & unsupported | New per unit work | Lines/distinct | Blocked by exactly one line |
| --- | --: | --: | --: | --: | --: | --: |
| 6ED | 335 | 200 | 75 | 2.7 | **1.00** | 69 of 75 |
| FEM | 102 | 102 | 39 | 2.6 | **1.00** | 32 of 39 |
| HML | 115 | 115 | 48 | 2.4 | 1.02 | 39 of 48 |
| 5ED | 434 | 147 | 66 | 2.2 | 1.01 | 55 of 66 |
| TMP | 335 | 315 | 145 | 2.2 | — | — |
| ICE | 373 | 346 | 189 | 1.8 | **1.09** | 135 of 189 |
| VIS | 167 | 167 | 96 | 1.7 | — | — |
| MIR | 335 | 317 | 183 | 1.7 | — | — |
| WTH | 167 | 167 | 99 | 1.7 | — | — |
| ALL | 144 | 144 | 99 | 1.5 | — | — |

**6ED and FEM measure exactly 1.00** — 81 refused lines over 81 distinct
sentences, 45 over 45. Not "nearly a long tail": every single refused line in
those sets is a different sentence, so 75 cards cost 75 separate pieces of work
and no production is shared by even two of them. The best "new per unit work"
ratio in the table belongs to the set with the least reusable work in it, which
is the trap that ratio sets.

**ICE is the only candidate where a production buys more than one card**, and
its three most repeated sentences are all cumulative upkeep (8x, 6x, 5x). Its
1.09 is not noise around the others' 1.00; it is one keyword.

**Ice Age is therefore where the rules coverage is**, and the big rock is
confirmed rather than remembered: **cumulative upkeep (CR 702.24)**, re-counted
at 30 of its own cards and **63 across the block** (ALL 9, MIR 5, VIS 5, WTH
14), of which **61 are unsupported today**. Within ICE, 14 of those 30 are
blocked by the cumulative-upkeep line **and nothing else** — one keyword ships
them outright — and the other 16 have it plus one more clause. The engine
already has both seams it needs (the upkeep registry, the counter API). Nothing
else in any candidate comes close, and it is still the only genuine subsystem
any of them forces.

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
top-level `mana_cost`, which a transform card does not have, so a
double-faced card raises `ValueError` on *load*. `_load_faces` populates
`CardDefinition.faces` and the only reader in the repo is `commander.py`'s
colour-identity derivation — the compiler has never seen a second face. That is
CR 709/710/712/714/715/720, 45 rules, none implemented; it already costs Origins
5 cards and M19 one. Second, keyword abilities stand at 27 of CR 702's 192.
Third, **alternative costs (CR 118.9) do not exist** — `cast_costs.py` implements
*additional* costs well, and "alternative cost" appears once in the engine, in a
comment — which blocks the buyback/flashback/evoke/madness family wholesale.

## Ice Age (ICE) — in progress

The set's journal, kept here while it runs so the "next set" section above stays
a *forecast* and this stays the record. Numbers live here; the process is
`SET_PLAYBOOK.md`.

**Phase 1 (ingest and measure).** 383 printings, 373 unique cards, **346 new to
the pool** — the largest set ingested and the first since M21 that is mostly new
cards. Census at ingest: **184/373 supported (49.3%)**, 58.9% of lines parsed
against the shipped pool's 85.7%, the lowest of any set. All 383 are layout
`normal`, so nothing gates promotion the way a planeswalker or a split card
would. The suite was green with the set loaded and the ingest yielded no engine
bug — confirmed against the sweep's parametrization count (1163 → 1509) rather
than against the green run, which is the check Phase 1 asks for.

**Phase 2 (census).** The forecast above was right about the big rock and wrong
about nothing that mattered. Two pieces of machinery carry the set:

* **Cumulative upkeep (CR 702.24)**, 27 cards, sitting in
  `oracle.UNSUPPORTED_KEYWORDS` — which outranks every line gate, so those cards
  refused before a line was read.
* **Snow**, 33 cards: a supertype on five basic lands plus a family of
  references (snow landwalk, "as long as you control a snow land", "the number
  of snow lands you control").

The refusal rollup's own top line is **not** either of them — "expected a
subject" leads at 97 lines over 80 cards and is the generic refusal, exactly the
"a refusal site is a work-list entry, not a diagnosis" warning in the playbook.
Cumulative upkeep is most of what sits under it.

**Round 1 — cumulative upkeep (CR 702.24). 184 → 205 supported.**

Built as the rewrite `engine/rampage.py` and `engine/equipment.py` established:
the printed keyword line becomes the triggered ability CR 702.24a says it *is*
(`engine/cumulative_upkeep.py`), and from there the upkeep step's ordinary
`upkeep_self` dispatch fires it. Nothing downstream of the compiler knows the
word. Non-mana costs — "Pay 2 life", "Sacrifice a land", 3 cards — refuse the
keyword line naming the clause rather than shipping a permanent whose upkeep is
silently free.

Three findings worth more than the card count:

1. **The rewrite reached creatures only, and the cards it missed reported
   *supported*.** A creature's lines and a non-creature permanent's are parsed
   by different loops, and the first version hooked the creature loop. Ten Ice
   Age enchantments that print cumulative upkeep beside another ability compiled
   clean with the keyword silently dropped — strictly worse than not
   implementing it, because the card reads as done and plays as a better card
   than the one printed. `oracle.keyword_line_triggers` is now the one reader
   both loops ask. **A keyword rewrite belongs to a line, not to a card type**,
   and the count that exposed it was per-card instrumentation written before
   believing the census (+11 became +23 once both front ends agreed).

2. **A widened gate hid a static line.** The land support gate asked for unread
   static text only `if not any((activated_abilities, triggered_abilities))` —
   so the moment a land's cumulative upkeep became an ability, the land was
   exempt from the check entirely and Halls of Mist went supported with
   "Creatures that attacked during their controller's last turn can't attack"
   unimplemented and now invisible. The guard was standing in for "is this line
   read?" and answering "does this card have *some* ability?". It reads every
   land now, with the parsed abilities passed in so their own lines are skipped.
   Measured over the whole pool before changing it: 2 cards move, both ICE,
   **no shipped card affected**. This is Phase 3's widened-gate rule paying
   for itself in the round that wrote it.

3. **Cyclone was cumulative upkeep printed longhand.** Its escalating {G}-per-
   wind-counter cost was hardcoded twice — once in its handler, once as an
   `if kind == …` branch in the prompt loop — so the card and the keyword had
   two copies of one arithmetic. Both now go through `per_counter` payload and
   `cumulative_upkeep.scaled_cost`, and the branch naming a card's instruction
   kind is gone. The **two callers stand on opposite sides of the counter being
   placed**, which the first shared version got wrong: one function that looked
   the count up charged Cyclone double. The count is a parameter now and
   `upcoming_cost` is the prompt's separate question.

Hollow lines: 8 → 10 cards, and the rise is honest. Cold Snap and Mystic Remora
were unsupported before this round and are now supported-with-a-gap, so the debt
moved from one report to the other rather than appearing. Phase 3's exit is both
numbers at zero.

**Round 2 — a conditional static on an Aura's host. 205 → 210 supported.**

The Scarab cycle: five cards printing one sentence with the colour word
changed, which is the shape Phase 2 says to rank a backlog by. "Enchanted
creature gets +2/+2 as long as an opponent controls a black permanent" is the
sentence a creature already prints about *itself* (Beasts of Bogardan) — same
effect, same condition, same evaluator, same seat (CR 109.5) — differing only in
which permanent the delta lands on. So it lowers through the one conditional
static, with `subject: "attached"` as payload, and the P/T refresh reads that.
No second reader of "a black permanent", which is what the existing lowering's
own comment asks for.

**The round's finding is what the flat reader was already doing.**
`auras.aura_static_pt_grant`'s pattern is `gets ([+-]\d+)/([+-]\d+)`, which
matches the *prefix* of a conditional grant — so the layer bridge would have
attached +2/+2 unconditionally, and making the card supported without touching
that would have shipped five Auras whose printed condition does nothing. It now
declines an "as long as" tail exactly as it declines a per-counter one, and the
decline is the second of its kind in this file. No shipped card is affected:
that reader is only asked of attachments, and every shipped card matching the
same prefix is a creature talking about itself.

**Round 3 — "at the beginning of the next turn's upkeep". 210 → 216 supported.**

Ice Age's cantrip cycle: Portent, Pyknite, Panic, Touch of Vitae, Krovikan
Fetish, Barbed Sextant and Urza's Bauble all print the same trailing sentence,
on five different card types and in three different positions (a spell's second
sentence, an Aura's enters trigger, an artifact's activated ability). Six of the
seven shipped; Urza's Bauble is held by its *other* clause.

It is a delayed triggered ability (CR 603.7) and the machinery was all there —
one row in `grammar/delayed.py`'s opener table, one key in `DELAYED_EVENTS`, one
`fire_delayed_triggers` call in the upkeep step.

**What is not there is a second spelling of an existing event.** The engine
already had `controllers_next_upkeep` for "at the beginning of **your** next
upkeep", and folding this into it would have been wrong by a whole turn: "your
next upkeep" skips every opponent's, "the next turn's upkeep" is whichever
upkeep comes next. A cantrip cast on an opponent's turn would have drawn a turn
late — no crash, no failing test, and the wrong card. So `next_turns_upkeep` is
its own event, announced unseated exactly as `next_end_step` is, and
`tests/rules/test_delayed_triggered_abilities.py` asserts the two apart in both
directions.

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
cards over **10** sets, 100% supported. Grammar parses 85.7% of lines and
executes 52.3% (`GRAMMAR_COVERAGE.md`). 6.4% of supported cards carry a
name-keyed hook, 80 entries in **6** registries (`HOOK_RELIANCE.md`) — the
number that decides whether this architecture reaches 26,113 cards.
`RULES_PROGRESS.md` is the CR coverage tracker. `CARD_VERIFICATION.md` is a log,
not a target — see the accepted-backlog decision above.

**One ratchet moved up on 2026-08-28 and the reason is worth keeping**, because
a ceiling that rises usually means a regression and this one did not. Retiring
Kudzu's dispatcher moved its line into `CARD_LINE_INSTRUCTIONS`, which is the
registry the *line* measure counts — so hooked lines read 69 → 70 while hooked
cards (74) and entries (80) did not move at all and the registry count fell from
7 to 6. Reliance did not rise; the old number was under-reporting a line that
was hooked all along in a registry the measure could not see. Read a ratchet
move as a measurement change before crediting it as a regression — the mirror of
4ED's lesson about reading a promotion diff as membership before crediting the
parser.

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
