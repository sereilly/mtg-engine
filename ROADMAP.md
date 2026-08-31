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
    change on purpose, not gaps to close on sight. **The graveyard half now has
    a reproduction** showing the clamp is not the whole of it — when *no* copy
    remains the fallback names a different card, which is the one case the data
    model can establish; see the Hymn of Rebirth entry in the Ice Age section.
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

## Ice Age (ICE) — shipped

The set's journal. Numbers live here; the process is `SET_PLAYBOOK.md`.

**Final: 373/373 supported, hollow lines 0, unclaimed parse sentences 0, and
the manifest entry moved from `measured` to `sets` at printing-order index 9.**
The pool went from 1,162 unique cards to **1,508** — 346 of ICE's 373 were new,
the largest single addition since Alpha. Ingest census was 184/373 (49.3%).

**Forty-two serial rounds took it to 284; four parallel waves took it the rest
of the way.** The waves ran five agents each in their own `git worktree`, with
integration serial in the main checkout: full suite, duplicate-definition scan
and every `--check` between merges.

**What the parallel shape actually cost and bought.** Authorship parallelised
cleanly; *integration* was the constraint, exactly as the playbook predicts.
The recurring integration failure was not a merge conflict but a **cap breach
no single branch caused** — `lowering/board.py`, `statements.py`, `phrases.py`,
`effects/board.py`, `triggers.py` and two per-set test files all crossed their
guard because two groups' additions *summed*. That is the guard working: the
family boundary was already there, and the collision is what made it visible.
Every split reused a name the other side already carried — `destruction`,
`keywords`, `tapping`, `types`, `trigger_tables`, `sentence_clauses`, `upkeep`.

**Three merges would have passed green while losing work**, and each is a
distinct shape worth naming:

* **One fact, two names.** `ast.GainControl` gained the same field twice in one
  wave — `gained_by` (Infernal Denizen) and `gainer` (Chaos Lord). Unified.
* **One rule, two mechanisms.** "Activate only once" was implemented as a
  per-line tally (CR 602.5c) and as a per-permanent counter. Kept the
  line-keyed one: a per-permanent count cannot follow an ability *granted* onto
  another creature, which is exactly Touch of Vitae.
* **A semantic collision no textual merge can see.** One branch split "an
  opponent" from "target opponent" into two parsed kinds; another branch's
  offered-steal table was written when one kind covered both. The merge was
  clean and three tests failed at runtime.

Add a fourth, which is about *my own* recipe: reconstructing a test file as
"ours + the branch's delimited block" silently drops imports the branch added
at the **file header**. It cost one `NameError` before I started diffing
branch-minus-block against the base every time.

**The declines compounded, which is the thing to keep.** Ten cards were
declined across waves 1–3, every one with its missing pieces enumerated
individually rather than as "too complex" — and other groups then finished
those pieces as a side effect of their own work. Chaos Moon's parity condition
was built by *Chaos Lord's* group; Ice Cauldron's two hard halves by the
noted-mana round; Winter's Chill's cast-time X plumbing by Spoils of War's.
Fumarole turned out to need **one** piece rather than four, because the
multi-target machinery had existed since Glyph of Delusion. Every one of those
ten cards eventually landed.

**Twenty-four silent defects in already-supported cards**, found by reading
compiled programs rather than the census — the single highest-yield activity of
the set, and none of them had a failing test. A sample, all in *shipped* cards:

* **Control Magic** returned to its controller's hand left the creature stolen
  for the rest of the game — an Aura's effects were removed when it reached the
  graveyard rather than when it *left the battlefield*. Steal Artifact,
  Conquer, Binding Grasp, Enthralling Hold and Evil Presence shared it.
* **Triskelion** was a free repeatable pinger: the activation-cost parser
  matched counter kinds with `[a-z]+` and a `+1/+1` counter is spelled in
  symbols, so its cost matched *nothing* — and a cost that matches nothing is
  not a refused ability, it is a free one.
* **Drain Life** ignored "but not more life than", so ten damage at a 2/2
  gained ten life.
* **Guardian Beast**'s "other players can't gain control of them" was enforced
  inside a single artifact-only handler, so Gauntlets of Chaos exchanged a
  protected permanent away with the Beast untapped.
* **Massacre Wurm** drained only when the death came through the lethal-damage
  sweep — the path its own tests take.
* **Kudzu** reached a graveyard with a raw `append`, the last destruction
  outside the seam: the land it destroyed fired no trigger and passed no
  replacement.
* **Four cards** were played as an even damage split where the card says the
  caster chooses.
* **107 cards** printing a non-mana activation cost had that option *dropped*
  from the browser's ability menu, index-shifting City of Shadows onto the
  wrong ability.

**The promotion rehearsal turned twelve guards red and was worth every one.**
The split between "the card is wrong" and "the guard is wrong" was again the
opposite of intuition in both directions. Three cards were at fault — Barbarian
Guides was **wholly inert**, logging "no valid creature target" on every
activation — while the mandatory-target sweep and Gaze of Pain were stale
guards. And the **4ED proxy trap repeated exactly**: a guard proved parse
coverage reads measured sets by finding a card that is not shipped, and an
empty `measured` role is legitimate, so it read "the instrument stopped
watching" when the truth was "there is nothing to watch". It now asserts the
invariant.

**A sweep over what the target pickers *offer*** — rather than over what the
compiler accepts — found three more, and it is the angle no card-level
instrument has: all three compile supported, carry no hollow line and claim
every printed sentence. **Goblin Ski Patrol** sacrificed the *opponent's* first
permanent instead of itself and kept its pump for good; **Aggression** and
**Faith's Fetters** were uncastable in the app, because their enchant clauses
derived `kind: "none"` and the client tests exactly that value to decide
whether to ask for a target.

**Hook reliance fell while the pool grew by a third**: 6.0% → 4.2% of supported
cards name-keyed. Nine hooks were retired and **none added** across four waves
— Abu Ja'far, Power Leak, Magnetic Mountain, Animate Dead, Lord of the Pit,
Drain Life among them. Grammar coverage rose to 87.2% parsed / 54.9% executed.

**Three follow-on rounds were taken after the promotion, and all three found
the recorded scope wrong** — twice too narrow, once too wide. Worth reading as
a warning about carrying a finding between rounds without re-probing it.

1. **A departed target was resolved by index.** `pick_target_permanent` tried
   the recorded id, then the *index*, then a scan; when the id no longer
   resolved it fell to the index, which CR 400.7's renumbering had turned into
   the decoy. Recorded as a delayed-trigger binding bug; it was **half that**.
   The same resolver carried the activation's *immediate* effect, so Sandals of
   Abdallah's islandwalk, Runesword's pump, Goblin Sappers' unblockable and the
   two Kjeldoran pumps all landed on a permanent nobody targeted — and
   **Merieke Ri Berit gained control of the decoy**, which the turn ending does
   not undo. Nine cards live, all activated abilities; the five spells were
   never reachable because `illegal_targets_refusal` is instants and sorceries
   only, which is exactly why the hole sat where it did. Fixed at the resolver:
   an id that resolves to *nothing* is a fizzle, an id that resolves to a
   permanent the caller cannot use is not. `fallback_on_invalid_choice=False`
   was already set on the broken path — it disables the scan, never the index.
2. **"That player" was the wrong player.** Recorded as The Abyss never asking
   the affected player to choose — true, and the second of two defects. The
   first: `destroy_target_permanent`'s single-target tail takes a fixed keyword
   list that has no `controller`, so `controller: "that_player"` was dropped and
   the destroy scanned the *default opposing seat*. **Feline Sovereign** (M21)
   shared it. The lowering's own guard against an unfrozen "that player" existed
   but was wired only into the sweep branch. (The journal also recorded that The
   Abyss destroys two creatures per upkeep; that was a bad reproduction —
   `start_turn` already resolves the upkeep and the probe called it again.)
3. **A sweep is not a target, on 17 cards rather than six.** `_from_instruction`
   read `type_filter` off any instruction kind, but that key is the target
   description on one kind and the affected class on another. Recorded as a
   client-only annoyance; it was also a real engine misplay —
   `_choose_trigger_targets` reads the same derivation and struck the ability
   off the stack under CR 603.3c when the board held nothing. Two of the
   seventeen are an artifact and an enchantment whose ETB sweep reached the
   *cast* picker, so a {4} artifact was uncastable on a creature-free board.
   Wrath of God was only accidentally right. **The ratchet that let this survive
   ran in one direction** — a card that targets must derive a prompt — and its
   twin now exists on both sides.

**Still open, with reproductions:**

* ~~**Preacher** (DRK) never asks the opponent for the choice the card gives
  them.~~ **Withdrawn 2026-08-31 — a false positive, and instructive.** Run
  with both seats interactive, Preacher arms a `permanent_choice` owed by the
  *opponent*, offers both their creatures, and honours the answer: choosing the
  Serra Angel steals the Angel, not the slot-0 Bears. What the reporting sweep
  saw was the **non-interactive default**, which takes the first candidate
  because that is what a headless seat's default is specified to do. That is
  the second "silent mis-play" this month that was the AI default behaving as
  documented, and the lesson is that a headless probe cannot tell "nobody was
  asked" from "nobody was there to ask" — arm the prompt with
  `interactive_seats` set before believing either.
* ~~**Hymn of Rebirth** compiles `any_graveyard` while its derived spec says
  own-graveyard-only, so the cast is refused outright.~~ *Fixed 2026-08-31.*
  **ICE, not LEG** — and it did not belong with the "graveyard target" item
  below, which is CR 608.2b's fizzle and was never about a derivation.
  `own_graveyard_only` was a *constant* in `_reanimation_spec`; the payload
  already knew. Three more places had the same seat baked in and only the widened
  target could reach them: `_validate_cast_targets` refused every seat but the
  caster's, `_reanimate_creature_to_battlefield` recorded no owner (CR 108.3 —
  the creature would have died into the reanimator's graveyard), and the
  unnamed-slot fallback searched the caster's pile, so an AI announcement
  resolved and reanimated nothing. Whole-pool spec differential: this card alone.
  Two residuals, both with reproductions, both deliberately not taken:
  * **CR 608.2b's graveyard decline is right about its own case and over-broad
    in practice.** The stated reason is the ambiguous one — two copies of one
    card in one graveyard are one `CardDefinition`, so resolution clamps. The
    *unambiguous* case is answerable and answered wrong: with the chosen card
    gone from the pile entirely, `graveyard_index_of` returns None and
    `chosen_graveyard_index` falls through to the stale index, which now names a
    different card. Exile the Serra Angel a Resurrection targeted and it
    reanimates the Grizzly Bears beneath it. The docstring's "this can only turn
    a wrong answer into a right one" is false for that path.
  * **Two cast-side graveyard targets reach no gate at all.** `cast_target_refusal`
    excludes `graveyard_creature` and `_validate_cast_targets`'s arm keys on the
    *primary* instruction kind, so a spell whose targeting sits inside a
    `sequence` — Fungal Rebirth, Experimental Overload — accepts an announcement
    naming an opponent's graveyard and re-points it at the caster's own. Only
    Fungal Rebirth is genuinely targeted, and the web picker never offers the
    illegal choice, so it is engine-level laxity rather than a reachable misplay.
* **Five handler paths still resolve by index alone**, reached today only by
  instants and so caught by the CR 608.2b gate first. The next *activated*
  ability printed with "return target creature to its owner's hand" walks in.
* ~~39 supported cards arm a free `optional_pay` whose headless default accepts
  every one — nobody chose that; it falls out of the affordability check.~~
  **Closed.** The count was 58 cards / 60 offers, and "39" and the later "59"
  were counting different walks of the same tree rather than different things.
  The policy is stated now: **take gifts, pay tolls, make no trades**. A free
  offer is refused when its *offered action* spends the seat's own resources —
  `ai_valuation.offered_action_is_a_payment`, over the instruction kinds the
  rules define as done to oneself (CR 701.21a sacrifice, 701.9a discard,
  118.3b pay life, 407.4 ante, 701.13a exile) — **and** the card prints nothing
  for refusing. Eight offers flip to declined (Crypt Lurker, Dire Fleet
  Warmonger, Ice Cauldron, Leviathan, Rebirth, Safe Haven, Tetravus' second
  upkeep trigger, Worms of the Earth); the nine *tolls* are deliberately
  untouched, because refusing one is not free either and picking the smaller of
  two losses is valuation, not a default — the same rule that says pay Season
  of the Witch's 2 life says sacrifice Curse Artifact's artifact, and no
  property of the compiled program separates them.
* **The same defect one layer in, found by the sweep and fixed with it:**
  `_default_mode_choice` answered "Choose one —" with **printed order**, which
  is fine while the alternatives are alike and is not for the one card in the
  pool where they are not. Sylvan Library's "pay 4 life or put the card on top
  of your library" put the price first, so a headless seat drew two extra cards
  every draw step and paid 8 life for them — **dead on the third**. It now takes
  the first alternative that costs it nothing; an all-priced modal (Crypt
  Lurker) keeps printed order.
* **Still open in this area:** a *toll* has no default anybody chose either. It
  is asked and answered by affordability today (pay if the mana is floating,
  else take the penalty), and nine cards ride on it. The missing piece is a
  valuation — which of two losses is smaller — and by CLAUDE.md's split that is
  `ai_policy` work with an `ai_valuation` derivation behind it, not another
  branch in `_default_optional_pay`.

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

**Round 4 — combat-relation target descriptions. 216 → 220 supported.**

"Target creature **it's blocking**" (Goblin Snowman, Tinder Wall) and "target
creature without flying **that's attacking you**" (Ice Floe, Snow Fortress,
Giant Trap Door Spider). Both are relations rather than characteristics, so
neither is answerable by `permanent_matches_filter`: the first needs the
ability's source, the second the seat it is controlled by — which is exactly
what `subject_matches` takes, so both are testable there and nowhere else.
`creatures_blocked_by` is the mirror of `creatures_blocking`, extracted out of
`creatures_in_combat_with` so the relation keeps one reader in both directions.

**The round's real finding is a whole bug class, and it is silent.**
`nouns._FilterDraft` is a hand-written mirror of `ast.ObjectFilter`, and a
draft is an ordinary dataclass — so a postmodifier that sets a field the draft
does not declare *succeeds*, the phrase parses, and the restriction vanishes
before the filter is built. "target creature it's blocking" was written that
way and compiled to a bare "target creature": every creature on the board, for
a ping the card aims at exactly one. Nothing raised and nothing failed; it was
found by printing the payload by hand.

So the construction is now a named `_build_object_filter`, and
`tests/engine/test_grammar_parser.py` builds an empty draft and checks that
every declared field arrives. Writing that guard found five more fields already
living outside the convention — defaulted onto the instance mid-parse rather
than declared — which is two conventions for "a field of the draft" and one too
many. They are declared now.

**Round 5 — the Aura keyword-grant vocabulary was a second copy. 220 → 222.**

Two cards (Wings of Aesthir, Imposing Visage) and one architectural finding
worth more than either.

`auras._GRANTABLE_KEYWORDS` was a hand-written tuple beside
`vocabulary.IMPLEMENTED_KEYWORDS`, and it had **drifted in both directions** —
which is what a second copy of one fact always does, and both directions are
wrong in a way nothing catches. It listed `shadow`, which this engine does not
implement anywhere, so an Aura granting it would have been *admitted*, entered
play and given its host an evasion ability that does nothing. And it omitted
menace, lifelink, deathtouch, indestructible, flash, hexproof, prowess and
rampage, so an Aura granting any of those was reported unsupported for a
mechanic the engine has. It is derived now, through the same three exclusions
`lord_buffs.grantable_keywords` makes and asserted equal to it.

**Fear joined the registry** as a consequence. It was in the Aura copy and not
in the registry, so deriving one from the other would have unshipped the card
Fear — and the reason it was missing is the shroud story again: CR 702.36b's
"can't be blocked except by artifact creatures and/or black creatures" has been
enforced in the declare-blockers step, with three CR-cited tests behind it,
since before the registry existed. Only the word was absent, and outside the
registry the grammar refuses every printed grant of it.

The second half is smaller and the same shape: the Aura keyword grant read
**one** keyword where a card may print several ("gets +1/+0 and has flying and
first strike"). The line matched, so an Aura giving two abilities shipped
giving one, with nothing to say so.

**Round 6 — snow, which the rules engine already knew how to read. 222 → 226.**

Phase 2 called snow one of the set's two big rocks and it was not one: "snow
land" already parsed to `supertypes: ["snow"]`, `permanent_matches_filter`
already tested it, and a Snow-Covered Forest already matched while a Forest did
not. **Measuring the machinery before scheduling the round is what found that**
— the census had ranked 33 cards behind a subsystem that existed.

What was actually missing was three narrow things, and two of them were bugs
rather than gaps:

* **An expired refusal.** "…as long as you control a snow land" was declined by
  the grammar with the reason "derived by engine/static_bonuses.py", and that
  table read five hand-written conditions and not this one — so the clause was
  read by *nobody*, with both halves individually correct and no test able to
  notice. The table now reads "you control <noun phrase>" through the grammar's
  own noun parser, so the phrase has one meaning here and at every recompute; a
  *counted* version still refuses rather than being answered as presence.

* **CR 702.14a's "any combination", taken literally.** "Snow forestwalk" is a
  supertype *and* a subtype and the defending player must control one land
  answering both, so a landwalk requirement is a tuple of qualities rather than
  one. Keeping only the last word would have made Rime Dryad unblockable
  against any Forest.

* **And that is exactly what was happening**, through a seam nowhere near the
  keyword. `layer_bridge._TEXT_KEYWORDS` is a substring scan whose own comment
  says a bare word is safe "for the reason it is not for hexproof: there is no
  narrower keyword whose name contains this one". "Snow forestwalk" contains
  "forestwalk", and the containing phrase is the narrower ability — so layer 6
  seeded plain forestwalk and the block check found a plain Forest sufficient.
  A comment stating an assumption is worth reading as a to-do list: this set is
  where that one came due.

**Round 7 — "can't be blocked by <noun phrase>", one vocabulary. 226 → 228.**

Two cards, and the reason it took a change rather than a row: the restriction
was **four** rows with four capture names (`blocker_subtype`, `blocker_type`,
`blocker_color`, `blocker_power`), each translated back into a subject filter
by a matching branch at the enforcement site. Two vocabularies for one thing —
so a printed noun both parsers could already read needed a fifth capture *and* a
fifth branch, and with only the first it would parse and never be enforced.
Stone Spirit ("creatures with flying") is the card that needed the fifth, and
`_blocker_noun` — the parser the *whitelist* form has used all along — could
already read the phrase.

One row now, one filter list on the payload, one `subject_matches` loop at the
enforcement site. The power threshold moved into `_blocker_noun` on the way, so
the whitelist form gains it for free and the two cannot disagree.

**The union splitter needed a fallback, and where it goes is the finding.**
"creatures with power 2 or greater" contains the word "or" and is not a union,
so the split produced two unreadable members. Retrying the whole phrase as one
noun *before* splitting looked right and broke Akron Legionnaire: "creatures
named Akron Legionnaire and artifact creatures" fullmatches the name pattern
greedily and the union collapses into one creature nobody is named. The retry
is after a member fails instead, which leaves every phrase that already worked
untouched.

**Round 8 — a self-reference's noun is not a filter. 228 → 232 supported.**

Four cards printing "{cost}: Return this <noun> to its owner's hand" across
three different nouns (Blinking Spirit, Foul Familiar, Leshrac's Sigil,
Freyalise's Charm). The lowering refused the printed noun as an unhonoured
restriction — correct machinery (`_restrictions_beyond` refuses by default, so
a filter field added later cannot be silently ignored) applied to a phrase that
is not a restriction. "This creature", "this enchantment" and "this permanent"
all name the object the ability is printed on (CR 109.5); nothing is being
selected, so there is no set for the type to narrow, which is why the engine's
own self-reference collapser already reads the three as one phrase.

**The size guard fired on the way out and the split was taken with the work in
hand**, as Phase 3 asks. `lowering/zones.py` reached 1,004 lines and one
function was 618 of them: `lowering/returns.py` is that function and its three
helpers. The boundary is the file's own — the rest of `zones` decides where an
object *goes* when something puts it somewhere, while a return also names where
it comes **from**, and it is the pair of zones that picks the handler.

**Round 9 — three characteristic-defining P/Ts (CR 604.3). 232 → 235.**

Drift of the Dead, Lhurgoyf and Pestilence Rats, all three through the one
`dynamic_pt_count` instruction and its one counter — three rows in the pattern
table and three payload keys, no new dispatch. Each key is a parameter the
sentence prints rather than a template:

* `supertype` — "the number of **snow** lands you control". No layer computes a
  supertype (CR 205.4), so the effective type line is the whole answer, through
  the same `printed_supertypes` reader landwalk uses.
* `toughness_plus` — Lhurgoyf is printed **\*/1+\***, so "its toughness is
  equal to that number plus 1" is half the card. Derived from the same value
  rather than counted twice, which is what makes it a number instead of a
  second template.
* `owner: "all"` on a zone count — "in **all** graveyards" is every player's,
  and `evaluate_count` only knew one player's. `exclude_self` covers "other
  Rats", by identity rather than by name.

**Round 10 — a sweep and a grant over the set the sentence names. 235 → 237.**

Jokulhaups and Stampede, and both were a *routing* fix rather than new
machinery. "Destroy all artifacts, creatures, and lands" is a type union no
per-scope sweep kind names, and the filtered sweep beside them already answers
it — `type_filter` takes a list and the matcher reads one as a union — so an
unlisted scope routes there instead of refusing, and a fourth union costs no
row. The named kinds stay for the unions that have one, because the compiler
and the behaviour snapshots key on them.

Stampede is the more interesting half. "Attacking creatures get +1/+0 **and
gain trample** until end of turn": both halves of one sentence name one set,
and only the P/T half could read it — the keyword grant refused any narrowing
and was scoped to the caster's board besides. Supporting the card without
fixing that would have pumped every attacker and given trample to none of them.
The grant carries the narrowing as a filter now, asked through
`subject_matches` so the two halves are one question, plus `every_seat` for the
fact the sentence names no controller — Stampede is castable by the *defending*
player, whose board holds none of the creatures it names.

The deletion probe moved, and in the good direction: "each" stopped being a
word the combat-pair rule could ignore, because the widened branch is reached
first and refuses an unnarrowed "creatures" with no controller. A shrunk
finding still reads as new to the ratchet, which is worth knowing before
accepting one.

**Round 11 — "If that land was a snow land, …" (CR 608.2h). 237 → 239.**

Icequake and Thermokarst: a destroy with a rider about the permanent it just
destroyed. The rider's *effects* both already lowered ("you gain 1 life",
"deals 1 damage to that land's controller"); only the condition in front of
them refused. It is a back-reference like `ItWas` and gated the same way —
nothing in front of it that destroyed a permanent, no condition.

**The table that declares those records could not say what this needs**, which
is the finding. `_PRODUCES` maps one instruction kind to one scratchpad key,
and `destroy_target_permanent` has written *two* for as long as both riders
have existed (the victim's mana value and its controller's seat) — so the
declaration has been under-describing the handler. A value may be a tuple now,
with the **first** entry the primary: that is the one "if you do" tests, since
that rider asks whether the step took place.

The production sits after "that <noun> was **destroyed this way**", whose
prefix it is. Tried first it consumed "that creature was", failed on the rest
and stopped Infinite Authority's condition parsing — four Legends tests caught
it, which is the ordering rule this grammar keeps re-learning: a production
whose opening is another's prefix goes second, and guards its own tail so a
near-miss rewinds instead of raising.

**Round 12 — a counted amount, and a name that is also a creature type. 239 → 241.**

Two unrelated cards and one silent bug apiece.

Songs of the Damned: "Add {B} for each creature card **in your graveyard**".
The mana multiplier wrote `"zone": "battlefield"` into every spec it built,
while the evaluator behind it has read the zone off the spec all along — so the
only thing missing was carrying the zone the phrase named. A card in a zone has
no computed characteristics (CR 613.1), so the narrowing goes through
`card_only_filter` rather than the permanent matcher.

Aurochs is the better find. Its name **is** a creature type, and it prints "for
each other attacking Aurochs". Both self-reference readers — the lexer's SELF
collapsing and `oracle._collapse_self_references` on the static-line path — read
the word as the card naming itself, giving "each other attacking **this
creature**": a set of one permanent that excludes itself, therefore always
empty, therefore a pump that always resolves for +0/+0 on a card reporting
itself supported. Both readers now leave the name alone in a *type position* (a
determiner or an adjective in front of it) and collapse it everywhere else,
which keeps Lhurgoyf's, Nightmare's and Shapeshifter's possessive
self-references working — the three other cards in the pool whose names are
creature types.

Also this round: a "for each" pump *with a duration* on the ability's own
source (Aurochs' trigger) lowers to the same `pump_self` the where-clause form
already uses. "+X/+0, where X is the number of …" and "+1/+0 for each …" are one
amount with two spellings, and `resolve_amount`'s `times_x` is where the
printed repetition size already lived.

**Round 13 — "when you control no <noun>", with the noun as payload. 241 → 242.**

One card and two retired condition kinds. Gorilla Pack prints the sentence Sea
Serpent prints, about Forests instead of Islands — and the engine read it
through a `no_islands` kind with the land type welded into the *name*, plus a
`no_lands` kind beside it saying the same thing about a wider set. Two kinds,
one rule, and every third type unreadable: idiom 19's exact shape.

Both are gone. `controls_no_matching` carries the printed noun and is answered
by `subject_matches` — the same reader the *positive* twin
(`controls_matching_permanent`, Goblins of the Flarg) already used, so the two
halves of one question have one answer. The state-based sweep and the upkeep
registry entry both read it, so the immediate firing and the upkeep firing
cannot disagree about what the card names. `no_lands_anywhere` stays: "no lands
**on the battlefield**" is a genuinely different set from "you control no
lands", and Mana Vortex is not sacrificed while an opponent still has one.

**Round 14 — a hook that had a second card. 242 → 243, and hook reliance falls.**

"Look at the top three cards of target player's library, then put them back in
any order" was a name-keyed entry on Natural Selection. `card_hooks`' entry bar
is that **no second card, real or plausibly printable, shares the shape** — and
Ice Age prints it twice. Portent compiled *supported* on the strength of its
cantrip line while its main effect was a bare whitelist marker; Elemental
Augury has no second line and was unsupported outright.

It is a production now, and the hook is retired: ALL hook reliance 6.4% → 6.3%,
79 entries, and the grammar's shipped parse rate rose 85.7% → 85.8% off a real
production rather than off membership. `may_reorder` picks between two existing
handlers rather than becoming a flag on one — Visions looks at five cards and
never rearranges them, and folding the two together would hand its controller a
rearrangement the card does not give.

The guard this broke is worth recording: `test_look_at_requires_the_object_it_looks_at`
asserted Natural Selection's line was **unparseable**, which was true while it
was a hook and is exactly the wrong probe for a production. Its point — "look
at" must consume its object — is kept with a line that has no object at all.

**Round 15 — two Aura lines with a P/T half in front. 243 → 245.**

Spectral Shield ("gets +0/+2 **and** can't be the target of spells") and
Errantry ("gets +3/+0 and **can only attack alone**"). Both are two effects on
one printed line owned by two different readers, and in both cases the second
reader could not see past the first: `auras._KEYWORD_GRANT` has carried an
optional "gets ±N/±N and" prefix for exactly this shape, and the immunity and
restriction tables had not. The prefix is stripped in the one place the support
gate and the runtime reader share, because a prefix stripped in only one of
them is a card that compiles supported and protects nobody.

"Can only attack alone" is CR 506.5 as a restriction on the **declaration**
rather than on the creature — a per-creature predicate has no way to say "and
nobody else", which is the same reason the attack cap beside it is checked over
the declared set. It is read from the Aura table *and* from a
`combat_restrictions` row, so the printed-on-a-creature spelling cannot be
enforced without the granted one.

**Round 16 — a pay-or-else prompt aimed at the event's player. 245 → 247.**

"…deals 2 damage to **that player** unless **they** pay {2}" (Soul Barrier,
Seizures). Both pay-or-else flows offered the cost to the ability's
*controller*, so a card aiming it at somebody else was unsupported outright —
and the seat it wants was already frozen into the trigger's context by the fire
site (CR 603.10) under the key "deals 1 damage to that player" reads. Payer and
recipient are required to agree: a clause damaging one player while offering
the cost to another is a card neither flow implements. Which seat is payload,
not a second kind — same prompt, same damage, same decline.

**A note for whoever touches `lowering/damage.py` next: it is at 997 of its
1,000 lines, and the obvious split is illegal.** The guard forbids one family
reaching sideways into another, and `_lower_damage` dispatches to every counted
variant — so pulling those out makes `damage` import `damage_counts`, which
`test_families_import_only_their_package_shared_module` refuses (correctly:
that is one family in two files). Only three functions are unreachable from
`_lower_damage` and they total ~100 lines and share no subject. The real
boundary, when someone needs it, is inside `_lower_damage` itself.

**Round 17 — a keyword family named whole, and a negated supertype. 247 → 249.**

Staff of the Ages says "Creatures with **landwalk abilities** can be blocked as
though they didn't have **those abilities**" — the family rather than one
member, and the evasion-negation table read exactly one keyword per sentence.

**The members are open, and that is the whole finding.** The first fix
enumerated the five basic landwalks out of `KEYWORD_FAMILIES`, which is the
right instinct and the wrong set: CR 702.14a builds a landwalk's name out of a
printed *quality*, so "snow forestwalk" is a landwalk and no list of words can
hold every one there will be. The negation carries the family **word**, and the
enforcement site asks `landwalk_requirement` — the same reader that decides the
restriction exists in the first place, so the negation covers exactly what the
restriction covers. Rime Dryad blocked through a Staff that said it could not
until that changed.

Hallowed Ground's "target **nonsnow** land" is the smaller half: a negated
supertype (CR 205.4), the mirror of the `supertypes` key and answered off the
same effective type line, since no layer computes one.

**Round 18 — "enters with X <kind> counters", with the kind as data. 249 → 250.**

`enter_effects.py`'s own comment already told this story about the *printed*
count: "the two constants above were literal sentences, so Clockwork Beast's
seven worked and Triskelion's three did not, for no reason anyone had decided."
The **X** form was still one of those literals, naming +1/+1 — so Rock Hydra
worked and Balduvian Hydra, printing the identical template one counter kind
over, was unsupported. It is a pattern now, with the kind read off the line
exactly as its printed-count sibling reads it, and the literal is retired. What
still separates the two is the count, which is the announced X (CR 601.2b) and
not a printed number — read from a different place at a different time.

**Round 19 — an offer whose action shares the printed subject. 250 → 251.**

"You may **gain 1 life**" (Thoughtleech) refused while "you may draw a card"
parsed, and the difference is grammatical rather than semantic: "draw" is a bare
imperative the statement parser reads on its own and "gain" is not. The offer
prints its subject once, in front of "may", so the action behind it is a clause
sharing that subject — which is the shape a conjunction already handles one
clause later ("Target player draws a card **and loses 1 life**"). The retry is
placed the same way and for the same reason: an action naming a subject of its
own is a different sentence, and carrying "you" over it would aim it at the
wrong player.

**Round 20 — a possessive back-reference written with its noun. 251 → 252.**

Word of Blasting: "Destroy target Wall. It can't be regenerated. This spell
deals damage equal to **that Wall's** mana value to **the Wall's** controller."
One card, three readers, and every one of them was narrowed by a *word* rather
than by a meaning — the amount read only the pronoun "its"; the recipient read
only "that/this <card type>'s controller", and a Wall is a subtype; and the
damage handler had no branch for the scratchpad channel **at all**, so the
lowering was already emitting `amount_from` and nothing read it. That last one
is the one worth having found: the card would have compiled supported and dealt
0.

**Round 21 — a regeneration rider on a subject nothing targets. 252 → 254.**

Two cards printing CR 701.19c's "can't be regenerated" about something no
sentence chose. Incinerate says it about **the effect** — "A creature dealt
damage this way" — where the rider parser required the sentence to open with
"it" or "if"; it is the damage twin of War Barge's "A creature destroyed this
way", and it exists for the same reason, that by the time the rider is read
there is no pronoun left to point at. Lim-Dûl's Cohort says it about the other
half of a blocking pair, the third subject the rider can have beside a chosen
target (Hurr Jackal) and the ability's own source (Clergy of the Holy Nimbus);
`_lower_cant_be` was never handed the trigger's event, so every subject that
was neither refused.

**The defect was one field over from the card that found it.** Every branch of
the damage lowering that is *not* the plain single-recipient one builds its own
payload dict — a board sweep, a narrowed creature sweep, a bound set, a fused
two-target bite — and each of them dropped `no_regen` and `exile_if_dies` on
the floor. Nothing raised: the sentence parsed, the sentence loop folded the
riders onto the node, the branch never looked at them, and the card compiled
*supported* dealing damage that any regeneration still answers. Only
`_lower_split_recipients` had noticed, and it guarded itself alone. The fix is
a **post-condition on the lowered result** rather than a line in each branch —
the rider has to arrive on an instruction of a kind that reads it — so the next
branch is covered by construction. Adding Incinerate's noun form is what made
it reachable from a printed sweep, which is the second time in this set that
widening a reader exposed a drop the narrower reader was hiding.

**Two splits, both at the 1,000-line guard, both along a line already drawn.**
`effects/prevention.py` took the shields, the redirects and Whippoorwill's lock
out of `effects/damage.py`, reusing `lowering/prevention.py`'s name — and it
carries the *redirects* as well, which the lowering side keeps apart, because
`_parse_source_of_choice_effect` reads one printed sentence and returns either
node. `lowering/_amounts.py` took the counted quantities out of
`lowering/damage.py` and is a **floor, not a family**: `damage.py` reads it, and
the family rule is that families do not import each other. That is
`ast/_primitives.py`'s argument exactly, and it is the answer whenever a leaf
turns out to be what a family needs.

**Round 22 — "if it's <colour>", where the colour is payload and the pronoun
is not. 254 → 256.**

Hydroblast and Pyroblast: one printed template, mirrored by a colour word, and
both halves of each card already lowered. What was missing was the trailing
condition — which the grammar has read since "destroy target creature **if it
has flying**", so the whole card is one condition node, one lowering and one
evaluator branch, with the colour riding as the symbol every filter in the
engine already uses. A third card printing "if it's white" needs no parser
change.

**The pronoun is the part that does not generalise, and that is the design.**
"Counter target spell if it's red" and "Destroy target permanent if it's red"
print the *identical* condition about a spell on the stack and a permanent on
the battlefield — two objects resolved from different halves of the resolution
context, with nothing in the condition's own words to separate them. So the
referent is read off the effect the clause guards (`pronoun_target_referent`),
at the one point where CR 608.2c's single sentence has both its halves in view,
and an unbound referent **refuses**. A resolver that asked one half and fell
back to the other would have answered about whichever object happened to be in
reach — which is the bug `target_has_keyword` beside it already names.

Lowering the counter as `counter_top_stack_spell` with a `color_filter` was the
smaller diff and the wrong card: "target spell" is the whole of the printed
restriction (CR 608.2b), so Hydroblast may legally target a blue spell and do
nothing, where the narrowing would have refused the cast and greyed the picker.

**The defect was in the second reader.** `web/serialization.py` derives a modal
mode's picker kind from the mode's instruction, keyed by instruction *kind* —
and both Hydroblast modes lower to a whole `if_then`, which fell past every
branch of that table to its "designates a player" default. The card would have
offered a **player** as the target of a counterspell. `engine/legality.py` has
done the descent through control-flow wrappers since Lesser Werewolf; this was
a second reading of the same question that did not, so the reader is public now
(`legality.targeting_instruction`) and the web layer asks it. One reader asked
twice is what stops a picker and a gate describing different cards.

**Round 23 — a combat restriction is about the declaration, not the creature.
256 → 258.**

Goblin Mutant's "can't attack **if** defending player controls an untapped
creature with power 3 or greater" is the question Sea Serpent's "**unless**
defending player controls an Island" already asks, one polarity over. Both are
one kind now, carrying the printed noun phrase and the printed word. The noun
used to be one of five basic land *words* — and the five were the
**enforcement's** limit, not the card's: the check scanned the defender's lands
by name, so a creature naming anything else had nowhere to go and the
production refused a phrase the noun parser reads perfectly well. It reads a
filter through `subject_matches` now, and the land scoping the old check spelled
out is CR 205.3i's rather than the payload's — a land subtype can only be on a
land. A card printing "a Desert" works, which is one card past the one that
needed the change.

Orcish Conscripts is the other half of the title: "can't attack unless at least
two other creatures attack", and its blocking twin. CR 508.1c and CR 509.1b ask
their restrictions of the **declaration** — "if any restrictions are being
disobeyed, the declaration is illegal" — so neither can live in `can_attack` or
`_can_block_attacker`, which see one creature at a time. They join Errantry's
"can only attack alone" where the declaration is assembled, through one reader
(`combat_restrictions.declaration_company_required`) whose count is payload.

**The defect is what an all-or-nothing refusal does to a seat that cannot see
it.** `ai_policy.choose_attackers` builds its set out of `legal_attackers`,
which is the per-creature predicate — so it proposed a declaration the engine
refused *whole*, and a Conscripts beside one Bear kept the **Bear** home too,
every turn, for the rest of the game. Nothing crashed and nothing logged a
rules violation; the seat simply stopped attacking. The fix is that the AI asks
the engine (`attack_declaration_refusal`) rather than carrying a second reading
of CR 508.1c, and the engine names the offending permanent — which is what
makes the AI's response a prune rather than a search. Errantry has the same
shape and had the same bug; no card in the shipped pool prints either clause,
which is why it had never been seen.

Two guards fired on the way and both were right to. The blocker check reached
for `defender.battlefield[idx]` when the loop above it had already resolved the
permanent, and the AI's prune did the same with a slot from the wire — the
positional-indexing ratchet named both. They read the collected objects and
`game.permanent_at` now, which is the seam's whole purpose: an index becomes a
permanent once.

**Round 24 — an attack cost printed on a permanent, scaled by the attack.
258 → 260.**

Flooded Woodlands and Reclamation: one sentence with the colour word changed,
and the largest multi-card refusal site left in the set. "Green creatures can't
attack unless their controller sacrifices a land of their choice **for each
green creature they control that's attacking**" is CR 508.1g printed on a
permanent that names a *class* rather than itself, with the payer being that
class's controller. The "for each" tail is what makes it a **per-attacker**
cost, which is the shape `_attack_costs_of` already returns — so the cost joins
the ones a creature prints about itself and the declaration sums them with no
second adder to keep in step. The tail is read and held to the subject by
equality rather than skipped: a tail consumed and dropped would be a card that
charges once for a whole team.

Two small general readers came out of it. "that's attacking" is the relative
clause spelling of the bare adjective, so it sets the same field — two
spellings of one state, not a second field every matcher has to remember. And
"of their choice" is *lifted* rather than carried: it says the paying player
picks, which is what the charger already does, so a payload key would be one
nothing reads — while somebody **else** picking is outside the allowed set and
refuses.

**The defect is the same shape as the round before it, one rule over.** The
sacrifice half of CR 508.1g was gated per creature and charged per declaration:
`can_attack` can say "there is a land for this one" and cannot say "and another
for the next", so two green creatures with one Forest were each gated as
payable, declared, and then charged **once**. The card did less than it prints
on exactly the board it was printed to stop. The mana half of the same rule has
been planned over the whole declaration since it was written — this is now its
twin, and Leviathan's "sacrifice two Islands" had the same hole for as long as
it has been implemented (two of them owed four Islands and paid two); nothing
in the pool ever had two out at once.

The plan is a **matching**, not a greedy pass, for `plan_payment`'s reason one
rule over: costs overlap — "a land" beside "two Islands" — and spending the
Island on the looser one under-reports a board that could pay, which is exactly
what CR 508.1g's "able to" forbids. Which permanent answers a cost is still
`default_sacrifice_pick`'s policy, now split into an ordering
(`sacrifice_preference_key`) the planner sorts by; the matching only decides
which cost each one answers.

**Round 25 — a borrowed permanent, and what the sentences after it name.
260 → 262.**

Ray of Command and Magus of the Unseen print one paragraph with the noun
changed: "Untap target <noun> an opponent controls and gain control of it until
end of turn. It gains haste until end of turn. When you lose control of the
<noun>, tap it." Three sentences, and every one of them is about the object the
first sentence chose.

Two of the three were nearly there. "Gain control of **it**" was refused where
Disharmony's "gain control of **that creature**" was admitted, because a bare
"it" parses as the ability's own source — `rebinding.py` says so, and that is
what the word means on a line naming nothing else — and the lowering read that
default as a *narrowing the card printed*. It is not one: the filter is checked
on the repeated noun and not on the pronoun now, which is how
`_lower_remove_from_combat` has read the identical pronoun all along, on the
very card that prints both spellings.

The third sentence is new: CR 603.7's delayed trigger, folded onto the control
change it watches rather than parsed as a step, because alone it names no
object at all. It fires where control is actually lost — the cleanup that drops
an until-end-of-turn contribution, which is the one place that happens — so the
creature goes home tapped without a second reader of what "lose control" means.
The rider walks the effect to find the change rather than reading the last step,
because both cards print a sentence in between.

**The defect: two branches of one handler left different things behind.**
`gain_control_until_eot` rescopes the resolution's target seat when it takes a
*chosen* target — the comment beside it says why, that the sentences after it
are about a creature now on another battlefield — and its **bound** branch did
not. So under the pronoun spelling the announced id stayed scoped to the seat
the creature had left: it resolved to nothing, and the haste grant logged "no
valid creature target" while the card compiled clean and stole the creature
perfectly well. What differs between those two branches is how the object was
named, which is nothing the sentences after them can see.

Beside it, the targeted branch wrote `controlled_permanent` into the resolution
scratchpad and **nothing has ever read it** — round 20's `amount_from` finding
in the other direction, a record with no reader rather than a reader with no
record. Deleted rather than declared, because the sentences that follow reach
the creature through the rescope.

**Round 26 — a printed restriction clause is a conjunction of restrictions.
262 → 265.**

Arcum's Sleigh ("Activate only during combat and only if defending player
controls a snow land"), Kjeldoran Guard (the same clause with "no snow lands")
and Grizzled Wolverine ("Activate only during the declare blockers step, only if
at least one creature is blocking this creature, and only once each turn"). Every
other sentence on all three already compiled — Kjeldoran Guard's CR 603.7
delayed sacrifice included — and each card was unsupported for its **last**
sentence alone.

CR 602.5 puts no limit on how many restrictions a clause states, and the cards
print them as one sentence. `engine/activation_restrictions.py` read a clause
whole, so a conjunction was a row of its own: three rows carried an optional
`(?: and only once each turn)?` tail, which is **one row per pairing** — quadratic
in the clauses that exist — and Speaker of the Heavens' "…7 life more than your
starting life total **and only as a sorcery**" was a single row whose predicate
read two rules under one name. `_conjuncts` splits the sentence and every
conjunct must have a row, so the tails are gone, the life row is the life half
alone, and the pairings a future card prints cost nothing. A conjunct no row
reads makes the *whole* clause unreadable, which is what stops a card being
admitted with half its sentence enforced.

Beside it, one row where there were two hand-written ones: "only if <seat>
controls <noun phrase>" with the seat, the noun and the polarity all payload —
`combat_restrictions.py`'s choice about its land type, on this table. The phrase
is read by the grammar's noun parser and answered by `subject_matches`, the same
pair `static_bonuses._controls_noun_condition` uses for the identical phrase
after "as long as", so a second reader of "a snow land" cannot disagree with the
first about what one is. It absorbed `_control_a_creature_with_flying`
(Celestial Enforcer), and the article is the quantifier: "a" is presence, "no"
its negation, and a *threshold* ("two or more") refuses rather than being read as
presence. A row ending in `.+` matches sentences it does not implement, so it
declares a `payload_readable` and is unmatched where the phrase is one nothing
can test — over-restriction is as silent as under-restriction, and this file's
whole subject is the silent direction.

CR 506.2 defines the defending player *during the combat phase*, so outside
combat the clause is unanswerable rather than vacuously true and refuses in both
polarities. `_resolve_defending_player_index` is the one reader — the other seat
in a duel, and in a CR 802 multi-defender combat only once exactly one opponent
is under attack — because a clause printed in the singular that no single seat
answers must refuse rather than widen.

**The defect: the two callers of this module spell the same sentence
differently.** `_clauses` splits the printed oracle text and keeps "step, only";
the grammar consumes the sentence token by token and rebuilds it with `" ".join`,
producing "step , only" — the comma having been a token of its own. Every row is
written the printed way, so a clause with a comma inside it matched from one
caller and not the other: the gate would call it readable and the parser would
refuse the line, or the reverse, depending on which asked. It has been latent
since the row was added, because Nettling Imp is the only shipped card printing
one and it is unsupported three sentences earlier — the refusal that hides a
second refusal behind it. Grizzled Wolverine is the card that reaches the clause
with everything before it working. Normalised in `_conjuncts`, which is the one
place both callers now pass through.

**Round 27 — a supertype is a computed characteristic. 265 → 267.**

Arcum's Weathervane ("{2}, {T}: Target nonsnow basic land becomes snow." and
"{2}, {T}: Target snow land is no longer snow.") and Melting ("All lands are no
longer snow."). CR 613.1d puts supertypes in layer 4 alongside card types and
subtypes, and CR 205.4b says gaining or losing one keeps the rest.

**The channel existed and was connected at neither end.**
`Characteristics.supertypes` was a field, `_SET_CHARACTERISTICS` listed it, and
`add_types` took a `supertypes=` keyword — all written when the layer system
was. Nothing seeded the set, `remove_types` had no supertype half, and no
`computed_supertypes` read it back. Meanwhile **nine call sites in seven
modules** asked what supertypes a permanent had by parsing its printed type
line through `layer_bridge.printed_supertypes`: the subject-filter matcher's
"a snow land", snow landwalk (CR 702.14c), Drift of the Dead's count, the
legend and world rules (CR 704.5j/k), Arena of the Ancients' untap block, Blood
Moon's "nonbasic", and the trigger-subject matcher.

That was *right* while nothing in the pool could change a supertype, which is
what makes it the `has_type` story one layer up rather than a bug anyone could
have found: every reader agreed with every other, and with reality. Arcum's
Weathervane is the day it stops being right, and eight of the nine now go
through `Permanent.has_supertype` / `effective_supertypes`. The ninth stays on
the printed line and is the one that should: `permanent_matches_filter`'s
card-level arm answers about a thing in a hand or a graveyard, where CR 613
does not apply at all.

The two cards are the two *flavours* a layer-4 channel has in this engine, which
is why they belong in one round. Arcum's Weathervane is **recorded** — a
`GAINED_TYPES` / `LOST_TYPES` entry per resolution, ended by dropping the
contribution. Melting is **derived** — a board-wide static, cleared and rebuilt
from the board on every continuous-effects refresh, on a channel of its own
because a rebuilt contribution recorded beside a stamped one accumulates an
entry per pass, forever. `land_types.py`'s docstring has said that since
Conversion; this is the second family to need both halves.

Melting is a derivation-table entry (`static_supertype_removal`) and not a
production, for the reason "All Mountains are Plains" is one. The production for
the targeted spelling therefore **declines a quantified subject in the parse**,
not in the lowering: `derived.py` is consulted only where the grammar refuses
the line *in full*, so a production that parsed "All lands are no longer snow"
and left the lowering to raise would take the table's line away and give it back
to nobody. Parsed-but-unlowered is still parsed — which is a thing worth knowing
before adding any production whose sentence a derivation table also reads.

**The size guard fired mid-round**, on `effects/characteristics.py` at 1,015
lines. `counters` split off, reusing the name `lowering/counters.py` has carried
since it left the same family one package over — the mirror re-forming rather
than forking, which is what the layering notes keep asking for, and the CR's own
line: a counter (CR 122) is a marker on an object, where what a `+1/+1` counter
does to power is a layer-7 consequence. The one fragment the two families shared
went down into `phrases.py`, which is where the layering rule sends a production
two families need — `phrases` rising without new work of its own for the second
time, exactly as its note predicts.

**Round 28 — N cards from a hand back onto the top of a library. 267 → 269.**

Brainstorm ("Draw three cards, then put two cards from your hand on top of your
library in any order.") and Stunted Growth ("Target player chooses three cards
from their hand and puts them on top of their library in any order."). One
effect printed twice, differing in who does it — so the seat is payload, on the
same `recipient` key `_lower_mill` already reads, and a seat the lowering cannot
name refuses rather than defaulting to the caster.

**It is not a discard, and that is the whole design decision.** CR 701.9a moves
a discarded card to a *graveyard*, and CR 701.9b makes the choice of which card
part of the discard — so the engine's `discard` prompt already does almost
exactly what these two cards need, and it even carries a `to_library` flag for
Library of Leng. Reusing it would have been three lines and would have fired
every "whenever you discard" ability in the pool on a Brainstorm (Necropotence
exiles what you discard). A new `hand_to_library` prompt instead: one
`register_choice`, one renderer, one arming site, which is what
`engine/pending_choices.py` says adding a prompt costs.

It **suspends**, because Brainstorm's two halves are one resolution and the
second reshapes the hand and the library the first filled (CR 608.2, CR 117.3b).
Three ratchets caught the parts that go with that, which is the registry working
as designed rather than three separate lessons: the simulator's drain list (a
suspending prompt left owed wedges every later resumable loop), the
completeness guard (no web renderer, no `ActionKind`), and the client-coverage
guard (`app.js` never read `state.hand_to_library`, so the seat owing it could
never have answered).

The order is the card's, not the engine's. "In any order" means the player picks
which of the two goes on top, so the answer is a *sequence* and both the client
selection and the resolver keep it — sorting the indices anywhere along the way
would have silently taken the choice away. The cards are read out of the hand
before any of them move, because taking one renumbers the rest, and each one
travels through `take_card_from_hand` and `put_card_into_library`: the two seams
that exist because a hand holds the *same object* for every copy of a card and
CR 903.9b can divert a card headed for a library. A test puts one of two
identical cards back and checks the other is still in hand.

**No in-game verification, and that is the `measured` role doing its job.**
Neither card can be decked — ICE is not in `load_catalog`, and the Debug Menu's
raw-state injection looks cards up in the shipped catalog too — so the browser
cannot reach either prompt. What was checked in the running app is what the
change could break for *shipped* cards: `app.js` parses, the three new functions
load, the board renders, console clean. The prompt's own behaviour is covered by
the engine tests, and the in-game pass waits for promotion, which is what
SET_PLAYBOOK Phase 5 says it should.

**Round 29 — restricted mana is about a payment, not about a cast. 269 → 270.**

Soldevi Machinist ("{T}: Add {C}{C}. Spend this mana only to activate abilities
of artifacts."). Adarkar Unicorn prints the round's other clause — "Spend this
mana only to pay cumulative upkeep costs" — and is deliberately still
unsupported; see below.

CR 106.6 restricts "how that mana can be spent". Every clause the pool printed
until Ice Age happened to name a *cast*, so `engine/restricted_mana.py`'s
predicate took the card being cast and the only payment path that consulted a
restricted bucket was `mixins/stack/casting.py`. The engine has **three**
payment paths — casting (CR 601.2g), activating (CR 602.2b) and an upkeep cost
(CR 702.24a) — and two of them had never heard of restricted mana. That is the
`become_tapped` shape again, and it was invisible for the reason those always
are: every existing restriction genuinely was cast-only, so every reader agreed.

The predicate takes a `PaymentPurpose` now, and all three paths pass one. Three
things fell out of that which a boolean would not have given: the cast-only rows
say `purpose.kind == CAST` explicitly rather than by omission; "…only to
**activate abilities of** artifacts" and Mishra's Workshop's "…to **cast**
artifact spells" are two different narrowings the old predicate could not have
told apart (each correctly refuses the other's payment, and there is a test that
says so); and the merge/debit pair moved out of `casting.py` into
`restricted_mana.py`, because with three callers a second copy would be a second
opinion about what a bucket may pay for.

**Adarkar Unicorn is left unsupported on purpose, and that is the finding.**
"{T}: Add {U} or {C}{U}" — with its restriction clause now implemented, the card
compiled clean and made the *wrong mana*. `pips_choice` is a tuple of
`(symbol, count)` pairs, one per alternative, which says "one of these colours"
and cannot say "{U}, or {C} and {U} together"; the parser merged the two runs
into one bag and the payload came out reading "either one {C} or two {U}" —
neither of the two things the card prints. Every one of the fifteen cards in the
pool that prints an "or" between mana symbols is a dual land whose alternatives
are one symbol each, so the shape has been right for every card that exists and
is wrong for the first card that does not fit. The parse refuses the alternation
now, naming it. Reshaping the payload is its own round, and it is blocked on a
*presentation* question rather than an engine one: an alternative is named to the
engine by its colour, which cannot distinguish "{U}" from "{C}{U}".

**Round 30 — the instrument stopped at the shipped pool. 270 → 270, and one card
started doing what it says.**

`parse_coverage.py` is the only thing in the repo that fails when a card
compiles *supported* while carrying a printed line nothing implements. It read
`manifest_set_paths()`, which defaults to the shipped sets — not a decision, the
default that call carries. So the check that exists precisely for "the compiler
called this done and it isn't" had never been pointed at the set where that is
most likely to be true.

It reads `include_measured=True` now. The gate is still the shipped pool, for
the reason `GRAMMAR_COVERAGE.md`'s floors and `HOOK_RELIANCE.md`'s ceilings
exclude the same sets: a set is ingested so its gaps can be *counted* before
anyone has closed them, and gating on them would make every ingest red on
arrival. The measured findings get their own section in the report and a line on
`--check`'s output, and `collect_findings` / `collect_measured_findings` are two
functions so "what fails the build" and "what is owed" cannot be confused for
each other.

**Panic is the card it found first, and the shape is worth keeping.** Its three
lines are a cast restriction, "Target creature can't block this turn", and a
delayed draw. The first and third compiled; the second produced **no instruction
at all**, and the card has been counted among the supported since ingest while
doing nothing it is played for. The sentence was not unparsed — the production
exists and the *lowering* refused a targeted subject, because the only card that
had ever printed it named a described set ("Creatures without flying can't block
this turn", Destructive Tampering). Two kinds now, and deliberately two: the
blanket arms a board-wide filter the blocker gate tests, where the targeted one
marks the single permanent the spell chose. Folding them would make Panic reach
every creature its noun phrase describes, which on "target creature" is all of
them.

The mark's key is named once, in `engine/combat_permissions.py`, and read by the
handler, the cleanup sweep and the blocker gate. That module is about CR 609.4
*permissions* and this is a restriction; it lives there anyway because it is the
same kind of channel — one mark on one permanent, swept with the turn — and
because it is the leaf that imports nothing, which is what lets the sweep name
the key without closing a cycle through `combat_restrictions.py`.

**The count did not move, and that is the point.** Panic was already inside the
270. What this round bought is one card that now does what it prints, and an
instrument that can see the other 29.

**Round 31 — a cumulative upkeep cost is a cost, and the reader has to consume
all of it. 270 → 271, and a second card started doing what it prints.**

CR 702.24a admits *any* cost after the keyword. `engine/cumulative_upkeep.py`
read mana, said so in its own docstring, and refused the three Ice Age cards
that print something else. That refusal was the honest half. The other half was
not: the cost phrase went straight to `mana_cost_from_symbols`, which **scans**
for symbols and ignores everything else by design — so "Pay {B} and 1 life"
matched, came back `{B}`, and **Infernal Darkness had been supported since
ingest charging half its upkeep**. A refusal you can see and a rider you cannot
are the same bug wearing different clothes, and only the second one ships.

`engine/upkeep_costs.py` is what a cost is now: mana, life and a sacrifice, any
of them zero. Three decisions in it are worth keeping.

*It is a leaf, not part of the keyword's module.* Every pay-or-consequence
upkeep prompt holds one — Erosion's "unless you pay {U}", Cyclone's longhand of
CR 702.24a, Nafs Asp's payment before the draw step — and Nafs Asp importing a
module named for a keyword it does not have is the wrong shape. The field names
are `cast_costs.AdditionalCost`'s deliberately: CR 601.2b's additional cost, CR
602.2b's activation cost and this one are the same act, and the sacrifice's noun
phrase is read by the compiler's own `_chargeable_sacrifice_filter`, so this
cost and an activation cost printing the same phrase cannot admit different
permanents.

*The phrase reader consumes the whole phrase or refuses it* — the grammar's hard
invariant carried into a derivation table, and the direct fix for the bug above.
"Pay {B}, discard a card" and "Pay X life" are both None, and either costs its
card support rather than costing the card its cost.

*Every part of the cost escalates.* "For each age counter on it" is about the
[cost], not about its mana — Glacial Chasm's third upkeep is 6 life and Polar
Kraken's is three lands. One `scaled_cost` still does that arithmetic for the
prompt and the handler both, which is what stopped Cyclone charging double when
the two shared a reader.

`can_pay_upkeep_cost` / `pay_upkeep_cost` wrap the mana pair rather than
replacing it: the mana question is unchanged and has one answer, and what is new
is that it is no longer the only one. Partial payment is not allowed, so the
question is asked about all three parts at once — a player holding the {B} and
not the life pays neither. The sacrifice goes through `arm_forced_sacrifice`,
which is what makes *which* land the payer's choice; the affordability test is
what stops that prompt being armed for a payment they could not have made.

The prompt carries the cost where it carried a mana dict, because "{B} and 1
life" is not a run of symbols and the number in it is this upkeep's rather than
the printed one. Three keys — the payload the affordability pass reads back, and
**two** renderings, because "Pay sacrifice a land" is not a sentence and only the
cost knows which of its parts it has. Four collectors build those dicts and two
read them back, so the keys are written in one place.

**What it bought:** Polar Kraken (271), Infernal Darkness charging what it
prints, and Glacial Chasm's refusal moving off the keyword and onto the two
lines that are genuinely unread ("Creatures you control can't attack", "Prevent
all damage that would be dealt to you").

**Round 32 — the pool taught the engine the exceptions before the rule.
271 → 273.**

Two CR 615 shields, and the same shape of gap under both: `engine/prevention.py`
had every *narrowed* form of a sentence and not the sentence.

**Pentagram of the Ages** — "{4}, {T}: The next time a source of your choice
would deal damage to you this turn, prevent that damage." That is CR 615.8
verbatim, and the pool had four cards printing it plus something: a colour
(Circle of Protection), a card type (CoP: Artifacts), a fraction (Dark Sphere)
and a rider (Reverse Damage). Each narrowing got a shield kind; the plain form
refused as "no handler for this source-scoped shield", because the lowering read
an *empty* source filter as no axis rather than as the whole class of sources.
`PREVENT_WHOLE` is its own kind rather than a rider-less `PREVENT_AND_GAIN_LIFE`
for the reason `shields.py` gives: `kind` names the interceptor that consumes
the shield, and gaining life is what that interceptor does.

**Fylgja** — "Remove a healing counter from this Aura: Prevent the next 1 damage
that would be dealt to enchanted creature this turn." A CR 615.1 shield around
the Aura's *host*: a fourth recipient beside "you", "this permanent" and a
chosen target, in the same shape as the three booleans `grant_prevention_shield`
already reads, because only the lookup differs. The host is found through
`attached_host`, the one accessor for that relation.

**Its refusal was the finding, and it was not about prevention at all.**
`engine/auras.py` gates an Aura's lines, and its claim for "this line is an
activated ability" was a **regex for the shape of one** — a run of mana symbols,
an optional comma-separated tail, a colon — standing in for
`_parse_activated_ability`. A stand-in disagrees with what it stands for in both
directions, and this one did, once each:

- CR 602.1 admits **any** cost, and the shape demanded a leading mana symbol.
  Fylgja's cost is a counter removal. The compiler parsed the whole ability —
  cost charged, effect lowered — and the card was reported unsupported for the
  shape of its cost. Round 26's direction: over-restriction, hidden behind a
  second refusal.
- The other way, a line matching the shape whose effect the compiler *cannot*
  read was claimed anyway. Chromatic Armor's "{X}: Put a sleight counter on this
  Aura and choose a color…" is one, and a claim there is how an Aura reports
  supported carrying an ability that does nothing.

The claim asks the parser now. **Measured before changing it**: over the whole
shipped-plus-measured pool those two ICE cards are the *only* disagreements in
either direction, so no shipped card moved.

**One number moved that is not progress.** `PARSE_COVERAGE.md`'s channel table
shows card_hooks 117 → 116 and parse rule 982 → 983. That is Reverse Damage's
first sentence, which the grammar can now lower on its own; the card still
compiles through its hook, because its printed *line* is both sentences and the
grammar refuses that. A sentence changed which reader claims it, not what
happens. Read a channel move as a measurement change before crediting it —
the same rule 4ED's promotion diff taught.

**Two findings measured this round and deliberately not acted on**, both bigger
than they look:

*The scheduled artifact/enchantment gate round is not the one recorded above.*
The note under Phase 3 says tightening it affects no shipped card. That was
measured against the *ability* form of the check. The land gate's other half —
`_unread_land_text`, the unread **static** line — is the one the round is really
about, and pointed at non-attachment artifacts and enchantments it names **15
shipped cards** (Blood Moon, Kormus Bell, Kismet, Lich, Time Vault, Living
Plane…). Every one is legitimately implemented, through a reader the claim chain
does not consult: `land_types`, `land_animation`, `enter_tapped_statics`, card
hooks. So the round is "extend the claim chain to the readers a non-land
permanent uses", which is most of what `scripts/parse_coverage.py`'s registry
already knows — two readers of one question, and the instrument has the complete
one. Bigger than one round; do not start it on the strength of the old note.

*The self-reference noun in an entry phrase is baked into the phrase.*
`enter_effects.py`'s `_SELF_SUBJECTS` is a hand-written list of five nouns, and
three constants beside it write one into the sentence
(`CHOOSE_COLOR_ON_ENTER = "as this enchantment enters, choose a color"`), while
`ENTERS_WITH_PT_COUNTERS` already uses `this [a-z]+`. So "As this **Aura**
enters, choose a color" is refused, on both sides — the claim reader *and*
`permanent_state.py`'s substring probe, which is why it is a gap rather than a
silent bug. Prismatic Ward and Chromatic Armor print it. Fixing it gains no card
on its own (both need a static Aura prevention as well), so it is scheduled
rather than done.

**Round 33 — the rest go back on top, and that is a decision. 273 → 275.**

Two Ice Age cards end with the same clause: "…then put the rest on top of your
library in any order." The engine had the clause one word over — See the Truth's
"the rest on **the bottom**" — and the difference is not a wording. On the bottom
CR 401.4's "the owner may arrange them in any order" is a freedom nothing can
observe, so the resolver had always just laid the cards down; on top it *is* the
effect, because it is the next N draws. So the top branch asks, through the
`reorder_library` prompt that already exists, armed by *answering* the pick —
one resolution, two decisions, which is what `ChoiceSpec.holds_priority` is for.

**Diabolic Vision** — "Look at the top five cards of your library. Put one of
them into your hand and the rest on top of your library in any order." See the
Truth prints the same template with three differences, and every one of them was
a **required word** in the production: the pronoun ("them" vs "those cards"), the
destination, and a cast-zone rider that is See the Truth's own sentence. All
three are parameters now; the rider is optional because it is a rider.

**Orcish Librarian** — "{R}, {T}: Look at the top eight cards of your library.
Exile four of them at random, then put the rest on top of your library in any
order." Its own node rather than a mode of the pick, because nothing is picked:
no card reaches a hand and no player chooses which cards go. What the two share
is the tail, and they share it where it is carried out. The exile draws on the
module RNG `run_ai_simulation` seeds, so a seed still replays a run exactly.

**The set's test file split, and the guard is what said so.**
`test_ice_cards.py` passed 2,600 lines on this round's tests and
`test_set_test_convention.py` failed. Split by the printed type of the card each
test is about, which is what M21 did and what `tests/sets/README.md` prescribes:
six files (creatures 42 tests, enchantments 33, instants 14, artifacts 7,
sorceries 6, lands 4), each keeping its share of every round section together
with that section's own helpers. No test was lost — the count went 103 → 106,
which is exactly this round's three.

**Round 34 — one verb over two noun phrases, and how many of them may be
targeted. 275 → 277.**

`_parse_further_subjects` reads "destroy **all** X, **all** Y, and **all** Z"
(Remove Enchantments) — one verb over a union of noun phrases, which no single
`ObjectFilter` says because its keys are AND'd. It took the quantifiers `all`
and `each` only, and its own comment says why: "and" is the commonest word on a
Magic card and most of its uses join two *effects*, so a quantifier is the one
signal available before the verb arrives.

**"target" is a third such signal, and the safest of them.** The word starts a
noun phrase and nothing else, and the shape that looks dangerous — "…**and
target player** draws a card" — was never a candidate, because a targeted
*player* parses to `ast.PlayerRef` and the union already required a
`TargetSpec`. Snow Hound ("Return **this creature and target** green or blue
creature you control to their owner's hand") and Giant Trap Door Spider ("Exile
**this creature and target** creature without flying that's attacking you") both
had each half working alone; what was missing was only the union. `exile` did
not read one at all and now does.

**Fumarole is the card that says where the limit is.** "Destroy target creature
and target land" parses under the widened union, and the *picker* cannot follow:
a spell is asked for one target — `targeting.derive_cast_spec` answers with one
`kind` — so admitting it compiles a card that is supported and uncastable, its
second target chosen by nobody. The union refuses more than one targeted phrase,
naming that. A multi-target cast picker is its own round.

**And Fumarole found a second thing on the way through.** For the few minutes it
*was* supported, `parse_coverage` went 44 → 45 unclaimed sentences and named the
reason: "as an additional cost to cast this spell, **pay 3 life**" is a cost
nothing charged, so the card was cast for free. `cast_costs.ADDITIONAL_COSTS`
was a table of two whole *phrases*, each writing the preamble out again — so the
only part that varied was the clause after the comma, and a clause nobody had
listed made the line unread. It is a preamble plus a clause vocabulary now, the
shape `_SELF_PERMISSION_COSTS` one function down already had, and **one** table
serves both sentences: "…, pay 3 life" and "…by paying 3 life in addition to
paying its other costs" list the same cost in two grammatical forms, and two
tables would be two answers to what this engine can charge.

That fix is currently latent, which is worth saying plainly: Fumarole is refused
for its targets, so no card in the pool exercises the life cost today. "Pay **X**
life" (Fire Covenant) stays deliberately unread — X is announced as the spell is
cast (CR 601.2b) and this engine resolves it *after* additional costs are
charged, so a clause for it would charge zero. It stays in the parse-coverage
backlog, which is where an unimplemented cost belongs.

**Round 35 — the pronoun names what the sentence in front of it chose.
277 → 278, and one supported card stopped killing the wrong permanent.**

`_parse_delayed_self_action` reads "Destroy **this artifact** at the beginning
of the next end step" (Rocket Launcher) and "Destroy **it** …" (Glyph of
Destruction), and its comment already says the hard part: the printed pronoun
does not say whether the spell chose a target or the ability is its own subject,
so the referent is decided at resolution with the source as the fallback. That
is right, and it read two verbs — `destroy` and `return`.

**"Sacrifice" was not one of them**, so "Sacrifice it at the beginning of the
next end step" fell through to the general delayed-trigger production, which
reads "it" as the source. Krovikan Elementalist — "{U}{U}: Target creature you
control gains flying until end of turn. Sacrifice it at the beginning of the
next end step" — was **supported** and armed the sacrifice on *itself*: the
Elementalist died at end of turn and the creature it had just given flying to
walked away. One sentence, two productions, and only one of them asked what the
pronoun named.

Celestial Sword prints the same delayed sacrifice with the actor written out —
"**Its controller** sacrifices it at the beginning of the next end step" — and
was refused as "no handler for another player sacrificing", which is the one
reading the sentence cannot have: a sacrifice is its controller moving their own
permanent and nobody else can perform it (CR 701.21a), so naming them narrows
nothing. Both spellings are the same production now.

The end step already swept `sacrifice_at_next_end_step` beside
`destroy_at_next_end_step`, and its comment already said why the two are kept
apart — a sacrifice is not a destruction, so no replacement effect applies to
it. Only the arming handler had no way to write the first key.

**Measured before and after over the whole pool**: exactly two cards' compiled
programs changed, Celestial Sword and Krovikan Elementalist. Dragon Whelp's
"sacrifice this creature at the beginning of the next end step" and every other
printing of the sentence are byte-identical, which is what says the explicit
spelling kept the reading it had.

**Norritt is the next round and the measurement is worth recording.** It prints
Nettling Imp's ability *verbatim* apart from the activation restriction —
"Activate only before attackers are declared" against "Activate only during an
opponent's turn, before attackers are declared" — and Nettling Imp is a
**name-keyed card hook whose key is the whole line, restriction included**. So
the second card printing the effect gets nothing, which is exactly what
`HOOK_RELIANCE.md` measures. Retiring it needs a paragraph production for the
three-sentence template (none of whose sentences parses today) plus the shorter
restriction; Arcum's Whistle prints the same opening sentence and would move
with it.

**Round 36 — a hook that had a second card. 278 → 278, and the number that
matters fell.**

The round scheduled last time, and it paid three ways.

**Nettling Imp was a name-keyed card hook whose key was its whole printed
line**, activation restriction included. Norritt prints that ability *verbatim*
apart from the last sentence — "Activate only before attackers are declared"
against "Activate only during an opponent's turn, before attackers are
declared" — and so reached nothing at all. That is the arithmetic
`HOOK_RELIANCE.md` exists to state: a name-keyed entry buys one card where a
production buys every card printed the same way.

The template is a paragraph production now (`engine/grammar/paragraphs.py`),
three sentences and one effect, because "that creature" and "it" both name what
the first sentence chose. The shorter restriction is a row in
`activation_restrictions.py` sharing one predicate with the longer one — the two
clauses are one window and one extra condition, and two predicates spelling the
same window would be two answers to when attackers stop being declarable.
**Norritt is supported and the hook is gone**: hooked cards 73 → 72, entries 79
→ 78, and the projection to the full release line 1,775 → 1,753 entries.

**The handler was ignoring the target.** "**Choose target** non-Wall creature
the active player has controlled continuously since the beginning of the turn"
— and it scanned the target player's battlefield and marked the first non-Wall
creature it found. A player who picked the Hill Giant got the Grizzly Bears
marked instead: the card said "choose target" and the engine chose. Both other
clauses were dropped too, which made this Siren's Call with a target — any
creature at all, including one cast a moment ago. `forced_attacker_is_legal` is
one reader for the whole noun phrase, asked by the handler that marks the
creature and by the legality gate that fills the picker, so what a player is
offered and what the engine accepts cannot differ.

**Adding a restriction row can make a hollow card report supported**, and that
surfaced on the way through. Arcum's Whistle's opening sentence started parsing,
its ability still did not compile, and the artifact/enchantment gate passed it —
because the new restriction leaves a `derived_static_rule` instruction behind
and the gate took any instruction that was not a bare whitelist marker as
evidence the permanent does something. It is not: a restriction says *when an
ability may be activated*, so it is a clause of that ability, and when no
ability of the card is readable it is a rule about nothing. **Amulet of Quoz was
already supported on exactly that evidence**, with its whole card in one
unreadable ability; it is correctly unsupported now, which is why the count is
flat at 278 and the parse-coverage backlog fell 44 → 43. The narrowing is one
claim wide, measured: thirty shipped cards have a `derived_static_rule` and
nothing else — Winter Orb, Howling Mine, Gloom, Meekstone — and each of those
*is* what the permanent does.

**And the module-size guard fired, correctly, on a file whose growth is
structural.** `grammar/lower.py` crossed 1,000 lines on this round's three-line
dispatch entry. The families *had* absorbed the work — the new lowering went to
`lowering/combat.py` — but the dispatch chain grows by three lines per node type
by construction, which is not the failure the guard describes. 78 of its
branches were pure `isinstance(statement, X) → _lower_x(statement)`: 156 lines
saying what a dict says in 78. They are `_BY_NODE_TYPE` now, read before the
chain, which is safe by construction rather than by inspection — no class in the
table appears elsewhere in the chain and none inherits from another, so at most
one branch could ever have matched. The chain keeps every branch that *decides*
something. `lower.py` is 909 lines, and the next node costs one line rather than
three.

**Round 37 — the "unless" cost of an upkeep toll is payload, not a kind.
278 → 279.**

The same search that found round 36, run again: for every unsupported card,
which hooked *line* does it nearly print? Two answers came back, and this is the
first.

Mishra's War Machine — "At the beginning of your upkeep, this creature deals 3
damage to you unless you **discard a card**. If it deals damage to you this way,
tap it" — was a card hook with its number and its cost baked into the key.
Minion of Leshrac prints the same sentence with 5 for 3 and "**sacrifice a
creature other than this creature**" for the discard, and reached nothing.

Both are payload now, on one paragraph production: two sentences and one effect,
because the tap rides the *damage* branch and the second sentence has no subject
of its own. The sacrifice's noun phrase goes through the same reducer every
other charged sacrifice reads, so what the offer asks for and what the charger
collects cannot disagree — and "other than this creature" is compared by
identity, which is what keeps the card from paying with the one permanent its
sentence rules out. **Hooked cards 72 → 71, entries 78 → 77, and the projection
to the full release line 1,753 → 1,730.**

**Three guards fired on the way, and each was pointing at something real.**

*A family reached sideways.* `lowering/damage.py` needed the sacrifice-filter
reducer that lived in `lowering/board.py`, and families do not import each
other. It is `lowering/_sacrifices.py` now — a floor, for `_amounts`' reason
exactly: a module two families import cannot itself be one. Moving it into
`_common` was the first attempt and pushed *that* past the size guard, which is
the same rule arriving from the other side.

*A paragraph reached upward.* The production wanted `phrases`'
`_accept_self_reference`, and `paragraphs` sits below `phrases`. The reader it
should have asked is `readers.accept_source_reference` — the layer whose whole
description is "small printed readers `nouns` shares upward, a comparison, **a
self-reference**" — and it covers "it" as well, which the sentence's rider needs.

*The deletion probe found a new ignored word*, `creature` in "this creature
deals 3 damage". Reviewed and accepted: `accept_source_reference` consumes "this
&lt;the card's own type&gt;", the noun names nothing a payload would carry, and Mana
Vault and Basalt Monolith have had that reading for rounds.

**And accepting it exposed a ratchet that oscillates.** `--accept-probe`
snapshotted findings from *every* coverage, while `collect_findings` gates on
the shipped half — so since round 30 pointed the analysis at measured sets too,
accepting one reviewed finding wrote 90 entries the very next `--check`
reported as stale. It snapshots the shipped half now. A ratchet has one
denominator or it is not a ratchet, which is the same rule `HOOK_RELIANCE.md`'s
measure names say out loud.

**The other answer that search returned is the next round**: Withering Wisps
prints Pestilence's end-step line *byte-identically* — "At the beginning of the
end step, if no creatures are on the battlefield, sacrifice this enchantment" —
and Pestilence is a hook. Generalising it retires a third entry but gains no
card on its own: Withering Wisps also needs "Activate no more times each turn
than the number of snow Swamps you control", an activation limit counted off the
board rather than printed as a number.

**Round 38 — the board is the cap, and an end-step gate with no seat in it.
279 → 280.**

The round scheduled last time. Withering Wisps needed two pieces and both were
generalisations of something already here.

**Pestilence's end-step line was a hook whose key was the whole sentence.**
"At the beginning of the end step, if no creatures are on the battlefield,
sacrifice this enchantment" — and Withering Wisps prints it byte for byte, so
it reached nothing. Every part of that sentence was already read except the
condition: the trigger opener is in the compiler's table, the effect lowers to
`sacrifice_self`, and CR 603.4's intervening-if travels on the payload and is
re-checked at resolution. What was missing is a count over the **battlefield**,
with no player in it.

So `ast.OnBattlefield` sits beside `Controls` rather than inside it. The
distinction is not pedantry: `Controls` is relative to a seat, and reading
"no creatures are on the battlefield" as a per-seat count would agree with the
board's count for "no" and disagree for every other quantifier the node can
carry. The quantifier is the comparison, as it is on `Controls`, and a printed
number is left unread rather than taken as presence.

**Retiring the hook retired a scan and a handler with it.** The end step had a
bespoke block that counted creatures itself and then looked for one instruction
kind; the generic gated scan two blocks below it — keyed on the payload's shape,
which is the arrangement round 45 of Legends arrived at — now reads the same
trigger. `sacrifice_if_no_creatures`, `END_STEP_EMPTY_BOARD_KINDS` and the
Pestilence entry are all gone. **Hooked cards 71 → 70, entries 77 → 76, and the
projection to the full release line 1,730 → 1,708.**

**The second piece is a cap with no number on the card.** "Activate no more
times each turn than the number of snow Swamps you control" is the first
per-turn limit in the pool whose value is a board count, and the machinery that
answers "how often may this line be activated" was one text-only function. A
text-only reader can only answer a counted cap with `None` — which is the value
that means *no cap at all*, so the tally would stop and the ability would be
uncapped on every board.

The fix is that these are two questions. **Whether a line is capped** is a fact
about the sentence (`printed_activation_caps`, what the tally asks); **what the
cap is** is a fact about the board (`activations_allowed_each_turn`, what the
refusal asks). One `ActivationCap` carries both shapes, so the refusal and the
tally still come through one reader. The noun phrase is payload and goes through
the grammar's noun parser — the same one `_controlled_board_phrase` asks — so a
card counting Islands needs no row, and a phrase that parser cannot read leaves
the clause unmatched and its card unsupported rather than admitted with an
uncapped ability.

**And the round found the next one.** Two halves of `support_report.py` count
the pool with two different readers: the census calls `classify_card` and the
refusal list calls `compile_card_oracle`, and they disagree — 93 unsupported
against 94. `classify_card` carries an override that admits a card whose
compiler refusal was "unsupported triggered ability" **if any other triggered
ability of it is supported**, which is the widened-gate shape this journal keeps
finding, with the same consequence: Illusionary Presence reports supported, is
castable, and drops its second upkeep trigger in silence. Measured over the
whole shipped-plus-measured pool, it is the **only** card in either direction —
so no shipped card is affected, and the number the census has been reporting for
this set is one too high.

**Round 39 — a landwalk's name is its printed quality, so no list can hold it.
280 → 280, and the number underneath it rose.**

The round round 38 scheduled, and it turned into one thesis with three askers.

**First the gate that was widening the count.** `engine/classifier.py` took the
compiler's verdict and overrode it: a card refused for "unsupported triggered
ability" was reported **supported** as long as any *other* triggered ability of
it compiled. The census in `scripts/support_report.py` asks `classify_card` and
its `--refusals` list asks `compile_card_oracle`, which is how one script came
to print two totals for one set — but the reach was not a report.
`mixins/stack/casting.py`, `web/catalog.py` and `engine/ai_policy.py` all ask
this question rather than the compiler's, so such a card was castable, browsable
and playable with a printed trigger doing nothing at all.

Measured over the shipped-plus-measured pool before removing it: **one** card,
Illusionary Presence, in the measured half. So no shipped card moved, and the
guard that replaces the override reads both halves — over the shipped pool alone
it would have passed on the day it was written and every day before it.

**Then the card it was hiding, which needed the same sentence twice.**
"At the beginning of your upkeep, choose a land type. This creature gains
landwalk of the chosen type until end of turn" is Giant Slug's production over
a wider domain: CR 205.3i fixes the five **basic** land types, and "a land type"
is every land subtype printed — eighteen today, out of the vocabulary catalog
that already answers it. Reading the wider phrase as the narrower one would
offer five options where the card offers eighteen, so the domain is read off the
words.

And the grant then refused thirteen of them. `_check_grantable` asks
`IMPLEMENTED_KEYWORDS`, a frozenset — and **CR 702.14a builds a landwalk's name
out of a printed quality**, so the names are open and no frozenset can hold
them. The six `[type]walk` words in that registry are a sample, not a family.
`engine/landwalk.py` is the reader that decides whether a quality is one the
block check can test, and it is already the gate `engine/oracle.py` asks about a
printed keyword *line*; the grant and the removal ask it now too. Granting the
bare family word is refused for `BANDS_WITH_OTHER`'s reason exactly — it names
no land, so it restricts no block.

**The third asker had the bug.** "Target creature loses all landwalk abilities
until end of turn" (Hammerheim) expanded the family **in the parser**, into the
list `IMPLEMENTED_KEYWORDS` happens to name — so Rime Dryad kept its **snow**
forestwalk while the log said it had lost it. Silent, green, and in the same
direction as every other finding in this journal: the card doing less than it
prints, which is the creature doing more than it should.

`engine/evasion_negation.py` had already learned this exact lesson one sentence
over ("Creatures with landwalk abilities can be blocked as though they didn't
have those abilities") and answers with the **family word**, leaving the
expansion to the site that knows what the permanent has. That is what the
removal does now: `expand_ability_removal` moved from `engine/banding.py` to
`engine/keywords.py`, beside the layer-6 write API, and holds one entry per
family as a *predicate* rather than a list. Banding was the first family, which
is why the function lived in banding's module; landwalk is the second, which is
why it does not any more.

**The count is flat and both halves of it moved.** Illusionary Presence is
genuinely supported (+1) and the override that had been reporting it supported
all along is gone (−1). Every number this journal has published for Ice Age
since the ingest was one too high; 280 is the first that is the compiler's own.

**Barbarian Guides is the next card in this template and declines with one piece
named.** "Choose a land type. Target creature you control gains snow landwalk of
the chosen type until end of turn. **Return that creature to its owner's hand at
the beginning of the next end step.**" The first two sentences parse and lower
now — the supertype qualifier is payload, exactly as `engine/landwalk.py` reads
it — and the third does not: nothing in the grammar returns a *bound* subject to
its owner's hand, at a delay or otherwise.

**Round 40 — an untap block is a noun phrase, not one field per card.
280 → 282, and two shipped-shaped cards stopped doing nothing.**

`UntapRestriction` had three fields for one sentence. "Creatures with power 3
or greater don't untap during their controllers' untap steps" was `min_power`,
"red creatures" was `color`, "legendary creatures" was `supertype` — three
patterns, three aggregate sets in `_untap_constraints`, three branches in the
untap loop, and one field added per card that had been printed. The supertype
row was even pinned to the literal word `legendary`, with a comment explaining
that a wider alternation would be untested by construction.

**Two Ice Age cards print a fourth wording and were reporting supported.**
Energy Storm and Blizzard both say "Creatures **with flying** don't untap during
their controllers' untap steps", which matched none of the three fields — so the
line was unclaimed, the table returned None, and the untap step never heard of
it. Both cards passed the support gate on their other abilities (cumulative
upkeep, a prevention shield) and have played that way since the ingest. Silent,
green, and in the usual direction: the card plays better than it is printed.

The subject is a **noun phrase** now, read by the grammar's noun parser — the
same reader `activation_restrictions._controlled_board_phrase` and
`static_bonuses._controls_noun_condition` ask about the identical words — and
carried as a filter payload `subject_matches` tests. One row, one aggregate, one
test in the loop, and the six phrases the pool prints all fall out of it:
power threshold, colour, supertype, with-a-keyword, without-a-keyword, and a
land subtype. A phrase the parser cannot read leaves the line unclaimed and its
card unsupported, which is what keeps the row from admitting a sentence and then
blocking nothing — or everything.

**And the block came out of the creature branch.** All three fields were read
inside `if permanent.card.primary_type == "creature"`, which was an assumption
the three cards behind them happened to share. Curse of Marit Lage names
Islands.

**Two cards land.** Curse of Marit Lage needed its other half too: "When this
enchantment enters, tap all Islands" was refused by the sweep's lowering, which
lists the `ObjectFilter` fields it honours and did not list `subtypes`. That
list is not redundant — it is round 4's guard, catching a field `to_payload`
would drop before the matcher saw it — but the check behind it already asks the
question that matters (can `subject_matches` test every key of the payload?),
and `subtype_filter` is a key it tests. Mudslide lands on the strength of its
restriction line alone.

**One number went the other way and the movement is honest.** Hollow lines
9 → 10 cards: Mudslide was unsupported before this round and is now
supported-with-a-gap, its "that player may choose any number of tapped creatures
… and pay {2} for each" upkeep offer still unread. That is round 1's accounting
again — the debt moved from one report to the other rather than appearing. The
unclaimed-sentence count fell 43 → 42 despite it, because Energy Storm's and
Blizzard's lines are now claimed by the table that enforces them.

**A refusal expired, and the test that guarded it said the opposite.**
`test_502_3_supertype_block_is_not_claimed_for_unimplemented_supertypes`
asserted that "Snow creatures don't untap…" stays unclaimed. Its stated reason
was that the enforcement had no card behind the word — but the real reason was
the hand-written `legendary` alternation, and `subject_matches` has tested
supertypes through layer 4 all along. The assertion is inverted now, with the
playbook's rule written into it: when a round builds machinery near an old
decline, re-probe the decline. The widening guard beside it points at phrases
that really are outside the engine.

**Round 41 — a combat restriction can be conditional, and the condition is
payload. 282 → 283.**

Arctic Foxes: "This creature can't be blocked by creatures with power 2 or
greater **as long as defending player controls a snow land**." Every word of it
but the last clause was already read — the blocker union has handled "creatures
with power N or greater" since Amrou Kithkin — and the row's capture ends in
`.+`, so the qualifier went *into* the union, which could not read it, and the
whole line refused. That refusal was correct: admitting the match and leaving
the tail unread is an evasion ability nothing enforces.

The qualifier is stripped once, before any row is tried, exactly as
`untap_restrictions._WHILE_UNTAPPED` strips "as long as this artifact is
untapped". Both the seat and the noun phrase are payload, so "as long as you
control an Island" is this clause rather than another one.

**A clause read at the gate and ignored at the enforcement is worse than one
nobody reads**, so the attachment is gated. `CONDITIONAL_RESTRICTION_KINDS`
holds the kinds whose enforcement site actually asks — one today — and a
qualifier on any other kind refuses the line instead of riding a payload nobody
consults. That is `activation_restrictions.payload_readable`'s claim in another
file: a row may match more sentences than it implements, and the ones it does
not implement must refuse.

**The condition's noun phrase goes through the grammar's noun parser**, not
through `_blocker_noun` beside it. That reader is a hand-written mini-parser for
the members of a blocker union and knows five shapes; "a snow land" is not one,
and teaching it a sixth would be one more entry in the second vocabulary this
file keeps. The board question here is the one
`activation_restrictions._controlled_board_phrase` and round 40's
`untap_restrictions._blocked_subject` already ask, so it gets the same answer.
**`_blocker_noun` is still a second reader of printed nouns and is the obvious
next thing to retire in that file** — not here, because its callers are unions
and the noun parser reads one member at a time.

**Hipparion is the other half of this sentence and is a round of its own.**
"This creature can't block creatures with power 3 or greater **unless you pay
{1}**" is CR 509.1b's cost-to-block, and the engine has the attack-side mirror
of it already (round 24: `cant_attack_unless_pay`, with a per-declaration mana
plan made before anything is tapped, because a per-creature predicate cannot say
"and again for the next one"). The block side needs that plan built again over
`declare_blockers`, which is why it is not folded in here.

**Round 42 — X targets for a destroy, and the shape the untap beside it had
already read. 283 → 284.**

Avalanche: "Destroy X target snow lands." The destroy lowering refused it
outright — *unsupported destroy quantifier* — while `untap_target_permanent`
has read the identical shape since Candelabra of Tawnos (Antiquities round 16),
through helpers that were written to be shared: `_names_several_targets` to
recognise a chosen **list**, `_describe_several_targets` to say the handler
reads one, and `resolve_target_permanents` to resolve each slot strictly, so a
target that has left is dropped rather than slid onto another (CR 608.2b).
The destroy simply never opted in.

**The refusal was hiding a second shape that did not refuse.** "Destroy up to
two target creatures" passes the quantifier check — `up_to` is on the allowed
list — and then reaches `_describe_targets`, which asks `_targets_payload`,
which *declines* a several-target spec and returns None. So the instruction went
out with **no target description at all**: the picker had nothing to read and
the spell would have destroyed one of the two permanents it names. No card in
this pool prints that sentence, which is the only reason it was latent rather
than live, and it is now a regression test.

The new branch is gated the way the untap's is — the filter must be one the
handler answers in full, checked twice for two different reasons (round 4's
dropped-`ObjectFilter`-field guard, then the payload keys against
`TESTABLE_SUBJECT_FILTER_KEYS`). It records `destroyed_this_way` under the key
the *sweep* uses, because "the number of Mountains put into a graveyard this
way" is the same question whichever branch destroyed them.

**Which is the next card in this template.** Volcanic Eruption is a name-keyed
hook whose key is its whole printed line, and its first sentence is now exactly
Avalanche's. The hook is still live — the grammar refuses the second sentence,
"Volcanic Eruption deals damage to each creature and each player equal to the
number of Mountains put into a graveyard this way" — so retiring it needs an
amount that counts what the step in front of it destroyed. The record is already
there.

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
cards over **10** sets, 100% supported. Grammar parses 85.8% of lines and
executes 52.4% (`GRAMMAR_COVERAGE.md`). 6.3% of supported cards carry a
name-keyed hook, 79 entries in **6** registries (`HOOK_RELIANCE.md`) — the
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
| `lowering/_common.py` | 995 |
| `phrases.py` | 992 |
| `lower.py` | 990 |
| `lowering/characteristics.py` | 954 |
| `lowering/categories.py` | 894 |

**Three modules are within ten lines of the cap**, which is the tightest this
table has been. `phrases.py` moved 965 → 992 in round 27 without a production of
its own: the fragment two families shared came down into it when `counters`
split off the parse side, which is where the layering rule sends one and the
second time this has happened. The next template landing in any of the three
splits it, and `lowering/_common.py` and `lower.py` are the two with no obvious
family line drawn through them yet — worth thinking about before the guard picks
the moment.

Both damage modules were on the cap and split in round 21 —
`effects/damage.py` 996 → 573 and `lowering/damage.py` 997 → 745 — which is
what a two-card round costs when it lands in the two files every damage
template lands in. `phrases.py` is the one that moved *up* without new work of
its own: a fragment two families needed came down into it, which is where the
layering rule sends one. The Dark took **six** splits in one set, which is more
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

Ice Age's first split is the other kind of evidence: `effects/characteristics.py`
crossed the cap in round 27 and cut along a line the **lowering side had already
drawn one set earlier**, under the same name and for the same reason. A boundary
found independently by two packages, a set apart, is as structural as one found
by two agents at once.
