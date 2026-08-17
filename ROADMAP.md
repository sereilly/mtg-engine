# Scaling Roadmap

Target: grow the card pool from 388 unique cards (LEA/LEB/2ED/ARN/3ED shipped,
M21 measured at 220/285) to the full release line - **137 sets, 33,594
printings, 26,113 unique cards** per `set_progress.json`.

A chronological engineering journal, kept to the last three rounds. Everything
before them — the founding audit, the parser migration (finished:
`engine/parsing/` is deleted and `engine/grammar/` is the only parser), the
per-set narratives, and M21 rounds 1–64 — lives in git history at and before
commit `eceefef`. What those rounds established that outlives their narrative is
kept below under **Carried forward**. The process a set follows is
`SET_PLAYBOOK.md`.

---

## Standing invariants

Anything that weakens these is a regression regardless of what it enables:

1. **No silent wrongness.** A card may fail loudly as unsupported with a
   reason; it may never resolve as something other than what it says.
2. **The suite stays fast.** 4,454 tests at a steady 23s, against a CI budget of
   35s. The budget catches a step change; the *baseline* recorded beside it in
   `ci.yml` is what catches creep, and it is the number to keep honest — it
   went 9s → 17s across four phases with the gate green the whole way. Raising
   the budget is a decision, not maintenance.

   The baseline moved 17 → 23 in this session, and that is a *record* of growth
   rather than permission for it: ~130 tests were added (permanent ids, the
   grammar layering guards, two renumbering regression suites) and 17 stopped
   being true. Leaving it would have parked the warning threshold
   (`BASELINE × 1.5` = 25.5s) two and a half seconds away, so the next
   unrelated change would have been blamed for drift this one caused. The
   budget is untouched.

   **The variance recorded here earlier did not reproduce.** Two back-to-back
   local runs once measured 43.98s and 16.79s, which read as a runner-weather
   problem serious enough to question the mechanism; three consecutive runs
   later landed on 23s exactly. Treat one slow run as noise. The distinction
   still matters — "the budget is too tight" and "this box is noisy" have the
   same symptom and opposite fixes — but there is currently no evidence for
   either.
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

The parts of rounds 1–52 that are about the *next* card rather than about the
round that wrote them. Everything here was established by a round now in git
history; the round number is given so the reasoning can be read in full.

### How a round is chosen

Sort the unsupported cards by **first failing clause** — `compile_line` names
the exact refusal, which beats reading the aggregate report buckets — then rank
by cards-per-change. Round 37 found **59 of 87 remaining cards blocked by
exactly one line**, at which point the question stops being "what is the biggest
mechanism" and becomes "which single line is cheapest per card". A block that
needs two rounds is worth splitting only if neither half ships a card alone
(rounds 7 + 8 did exactly that, one card each plus one together).

### Open blocks, still standing

- **The legend rule reads the printed name** (round 49, restated by every round
  since). CR 707.2 copies the name, so a Clone of Barrin is a second Barrin and
  CR 704.5j should bin one — verified, and it does not. Two reads are wrong, not
  one: `perm.card.name`, and the `Legendary` supertype, which `has_type` does
  not cover at all (round 48 exempted `game_ending.py` for exactly that). All
  eleven legendary creatures in the pool are M21, so nothing can hit this until
  the set ships — which makes it worth doing before it does. A ratchet on
  `card.name` needs its own census first: hundreds of reads are log lines.
- **Activating an ability of a card in hand.** "Discard this card:" (Waker of
  Waves) is an activation cost paid from *hand* — a mechanic with no seam in
  this engine, not a wording gap. Niambi, Subira and Sanctum of Shattered
  Heights want the same seam. Round 51 built the discard *picker* for a
  permanent's ability and left this half untouched.
- **The exiled-with linkage**: an object exiled *with* a permanent and returned
  when that permanent leaves (Kitesail Freebooter, Idol of Endurance,
  Archfiend's Vessel). The pool's only exile-until-leaves is Oubliette's, which
  phases out and is name-keyed in `card_hooks.py`; routing Freebooter through it
  buys one card at the cost of a ceiling raise, so the linkage wants deriving
  first. The shape is `cast_permissions.py`'s — a collection on `Game`, granted
  by an effect, swept when its source leaves.
- **The Shrine cycle and the where-clause cards**: see round 57's *Next* below,
  which is current.

### Recorded, measured, and not yet fixed

- **The Nine Lives class — partial implementation reported as full.** A card is
  supported when **any** line is, so a card can report supported while other
  lines produce nothing. Nine Lives' damage-prevention replacement and its exile
  trigger produce nothing. Round 53's hollow gate closes only the *fully* hollow
  case (nothing supported, nothing static, markers only), and round 20's all-of
  gate closes the modal shape; the general class is still open and has been
  found one card at a time — Return to Nature's third mode (round 12), Read the
  Tides' second (17), Garruk's Uprising' third line (34), Sanctum of Stone
  Fangs, Fiery Emancipation and Teferi's Ageless Insight (53). Two of those
  three are implemented (rounds 54 and 57) and Teferi's is still open — which
  closes three cards and not the class. It wants a census of its own, in the
  shape Phase 2 uses for a set.
- **Fabled Passage** is hollow and stays supported: a land with no mana ability
  whose only ability is unreadable, kept by the separate "a land is always at
  least playable" rule in the compiler. That rule is right for a land that taps
  for mana and wrong for one that does not, and overturning it is a decision
  with its own reasoning to write down.
- **Rock Hydra's automatic counter shield.** "For each 1 damage that would be
  dealt to it, remove a +1/+1 counter from it and prevent that 1 damage" is
  acknowledged in `IMPLEMENTED_ELSEWHERE` as `prevention.py`, but that file
  implements only his *activated* {R} shield — nothing reads counters in any
  damage path. So the automatic half is the Nine Lives class hiding behind a
  verified-sounding acknowledgement. Round 26's counter record is the
  prerequisite for fixing it honestly.
- **The verification tracker holds 19 untested cards** (the ones Revised added).
  Rounds 46–47 checked all nineteen behaviour by behaviour and fixed three real
  bugs in them, but a headless sweep is not a manual in-game pass and
  `card_verification.json` records what a human checked. A generated artifact
  that is stale does not read as stale; it reads as an answer.

### Deliberate refusals, with their reasons

Not gaps to close on sight — each was measured and left refusing:

- **Pursued Whale** — "spells your opponents cast **that target this
  creature**": a narrowing about the spell's *targets*, which no filter here
  expresses.
- **Faith's Fetters / Enthralling Hold** — "its activated abilities can't be
  activated unless they're mana abilities"; "you can't choose an untapped
  creature as this spell's target as you cast it".
- **Crypt Lurker** — an either/or action cost ("sacrifice a creature **or**
  discard a creature card") needs an or-composed cost prompt, not round 23's
  single-action one.
- **Protection past what the shields test.** Round 25 gave qualities colours,
  "multicolored", planeswalkers and creature subtypes; Feat of Resistance
  ("protection from the color of your choice" — a chosen-colour grant plus a
  layer-6 read), Runed Halo (player protection from a chosen *name*) and Feline
  Sovereign (protection as a lord-buff grant) stay out. Hexproof stays
  colour-only, because its targeting branch reads colour words alone.
- **Cost reductions that cannot be computed** — the {X} self-reductions
  (Volcanic Salvo, Chandra's Incinerator) and Sanctum of Tranquil Light's
  per-Shrine *activation* reduction. Reading an unrecognized condition as
  satisfied makes a spell cheaper than it is, and cheaper is the one direction a
  cost error must never go.
- **El-Hajjâj's "you gain that much life"** is deliberately *not* a row in
  `_EVENT_QUANTITIES`: its fire site records the amount under a different key,
  so claiming its line would retire a hook onto a handler reading the wrong
  name.
- **A durationless doubling** (a continuous effect the layers would have to own)
  and **doubling toughness** (a different effect — consuming the noun without
  checking it is how one card's production quietly claims another's).
- **Demonic Embrace's graveyard cast** — "by paying 3 life and discarding a
  card", a *cast* additional cost over the round-19 permission seam.
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
   nothing off the battlefield touches, so it can be read at resolution.
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
    the guard is the signal that a family stopped absorbing new work.

---

## Round 65: the duration in front, and a word that was being dropped

*(2026-08-16.)* M21 **220 â†’ 220** â€” Rookie Mistake in, Selfless Savior out. The
flat number is the round, in the sense rounds 12â€“14 and 16 established: a card
left because it was playing wider than it prints.

**The card was scheduled for the wrong reason, and the fix was one probe away.**
"Until end of turn, target creature gets +0/+2 and **another target** creature
gets -2/-0" was ranked as a multi-targeting gap. It is not: the second target has
parsed since round 40 (`TargetSpec.distinct_from_prior`), and the sentence join
already builds two statements. The actual first refusal is the **leading duration
adverbial** â€” `Until end of turn, target creature gets +0/+2.` refuses on its own
with the identical message, and it is card-independent. Sorting the backlog by
the *reason string* would have had the fuser written first and the real blocker
discovered underneath it.

**A leading duration is distributed, not stored.** The trailing spelling attaches
to the clause it follows, so the front-position one has to reach every effect
behind it; a wrapper node holding it would be a second place to ask what a
statement's duration is. It refuses rather than dropping in three shapes â€” a
statement with no duration field, a statement already printing a different one,
and any sequence containing either â€” because a dropped "until end of turn" is a
permanent effect the card never printed. The production is placed **after**
`_parse_cast_permission`, which prints the same prefix and reads it itself:
ahead of it, both Chandras go unsupported. That ordering has its own test.

**Two chosen creatures in one sentence cannot be two steps.** Every single-target
handler resolves through `_one_choice`, which reads the first entry of the target
list â€” so lowered as a `sequence` the card would compile supported and put both
boosts on one creature. It fuses to one `pump_targets_until_eot` carrying a slot
per clause, the third member of the family `target_bites_target` and
`prepare_then_interact` opened. The printed "another" rides as `distinct` beside
per-slot `filters`, not folded into a filter: it is a relation between two slots,
and `permanent_matches_filter` tests one permanent, so it could never answer.

**The slots are resolved positionally, and that needed a third resolver.**
`resolve_target_permanents` *compacts* â€” it drops a decayed slot without padding
â€” so `chosen[1]` becomes `chosen[0]` the moment the first target leaves. Primal
Might and Hunter's Edge survive that only because their slot filters are
disjoint and the impostor is rejected; Rookie Mistake's two slots are both a bare
"target creature", where the surviving creature would take the other slot's
effect. `resolve_target_slots` pads instead. (`prepare_then_interact` still reads
the compacting one. It is correct today by that accident of the pool and wants
moving over with a regression test of its own.)

**And the word that was being dropped.** `parse_coverage.py`'s deletion probe
reports `('another',)` on Selfless Savior â€” the emitted filter excluded nothing,
so the picker offered the Savior as the target of "another target creature you
control", an illegal choice a player could announce, whose cost then sacrificed
it and whose ability then fizzled. CR 601.2c is why the word has to be said at
all: two instances of "target" may otherwise name the same object. A
one-recipient description has nowhere to record which *other* choice this one
must differ from, so it now refuses. The alternative â€” reading a sole target's
"another" as CR's source exclusion â€” is a larger change that conflates two
meanings the AST deliberately separates, and it is the next round's, written up
in the spec.

Landed in dependency order with the grammar **last**, so at no intermediate point
was the card castable with half its targets collected. That order was load-
bearing twice: without the AI's per-slot side the AI put both targets on its own
board (measured `[0, 1]`, seat 0 â€” it shrank its own creature), and the browser
picker reset the selection on a click on the second board, so a human could never
pump one of theirs and shrink one of the opponent's. Which slot wants which board
is *derived* â€” the sign of the slot's P/T delta â€” never a name.

One finding taken from the same measurement and fixed here, because it is
unambiguous where the above is not: **`exclude_self` was honoured at resolution
and ignored by every picker.** Basri's Acolyte's "up to two **other** target
creatures you control" offered the Acolyte; so did Barrin and Brash Taunter. All
three handlers already refuse the source. `legality.py` has honoured
`exclude_source` all along â€” nothing read the filter key into it. One line.

Suite **5,138** green, every `--check` gate green, shipped pool 388/388, AI
simulation byte-identical at 443 interactions. Ten of the eleven new tests were
watched to fail on the round-64 engine; the eleventh is the control that both
Chandras keep their cast permissions.

**Next:**

- **"Another" as a source exclusion**, the alternative above: translate
  `distinct_from_prior` on a sole target to `exclude_self` rather than refusing,
  which returns Selfless Savior and covers Subira's and Niambi's same drop. It
  needs a guard separating it from the two-slot meaning first.
- **The headless AI simulator throws its chosen permanent target away.**
  `grep target_permanent engine/ai_simulator.py` returns nothing, so every
  targeted-permanent spell in a seeded run resolves through a handler fallback,
  and a several-target spell resolves to *nothing at all*. Latent for the shipped
  pool, live for M21, and live for the shipped pool the day M21 promotes. Fixing
  it moves the 443-interaction baseline, which is why it is recorded rather than
  folded in here.
- The Shrine cycle, a static P/T contribution with a computed X (Kinetic Augur,
  Jolrael), a reflexive trigger (Tolarian Kraken), then the legend rule.

## Round 66: a cost the engine had never charged, and a coin it had only ever flipped by name

*(2026-08-16.)* M21 **220 â†’ 221** â€” Tavern Swindler, whose one line needed two
things, and the second of them **retired a hook** rather than adding one.

**"Pay 3 life" is an activation cost with no seam to join.** There is no generic
non-mana additional-cost mechanism here: `ActivatedAbilityCost` is a record of
named fields and `_activate_onto_stack` a straight-line sequence of per-field
blocks. Adding a seventh field is the shape the file already has, and inventing
an abstraction for one card would be a bigger change than the card. `ast.PayLife`
turned out to **already exist with no producer** â€” declared, exported, never
wired â€” so the parse side was a branch, not a node.

**The rule is off by one from where you would put it.** CR 119.4 is "greater than
**or equal to**", so exactly 3 life pays a 3-life cost; illegal starts at 2. And
CR 602.5c makes an unpayable cost an *unactivatable ability*, not a free one â€”
so the check refuses before anything is spent rather than clamping at the
payment. Paying the last of your life is legal and CR 704.5a then ends the game;
an engine that refused the payment to protect the player would be enforcing
neither rule. Each of those is a test in `tests/rules/` with its citation.

**The two readers, again.** The grammar's cost nodes are *discarded* â€”
`lower_ability` never reads `node.costs` â€” and the real charger is the regex
reader in `engine/oracle.py`. That split is why `tests/engine/test_activation_costs.py`
exists at all ("Atog sacrificed nothing for its +2/+2 for as long as both readers
existed and only one was consulted"), so the new cost joins the comparison, and
the comparison is on the **amount**, not on the presence: a charger reading a
smaller number is an ability cheaper than the card.

**The coin flip is where the round pays for itself.** `flip_coin()` has existed
for a long time and every card reaching it did so through a *name-keyed hook*.
The general shape is not a fused `flip_coin(won=â€¦, lost=â€¦)` wrapper â€” it is
**one `flip_coin` instruction recording its result, and ordinary `if_then`s
reading the record**. Two reasons, one of them measured: a wrapper's payload keys
have to be added to four separate nested-key enumerations and forgetting one is
silent; and composing gives CR 705.2 for free â€” one flip, both branches reading
the one result, where a design that re-asked would let a card win *and* lose its
own flip. It also gets round 33's rule for nothing: "the flip" is a
back-reference, so `_PRODUCES` makes a card printing only "If you win the flip, â€¦"
refuse at lowering instead of compiling supported and doing nothing.

**Bottle of Suleiman retires its hook.** Its whole line â€” both branches â€” now
goes through the production, so `card_hooks.py` loses an entry and
`hook_reliance.py`'s **ceilings come down**: ALL 26.3 â†’ 26.0 entries per 100
supported cards and 24.5% â†’ 24.2% hooked, ARN 46.2 â†’ 44.9, 3ED 19.9 â†’ 19.6. The
grammar floors go up in the same commit (ALL parsed 78.0 â†’ 78.1, ARN 64.8 â†’
65.7). Both ratchets tightening at once is the shape a round should have.
Retiring it also fixed something nobody had asked about: the hook named its token
`"Djinn"`, the one hand-spelled token name in the file, where CR 111.4 and
`tokens.default_token_name` say `"Djinn Token"`.

Mijae Djinn and Ydwen Efreet **cannot** retire: both are blocked on the verb
`remove` ("Remove this creature from combatâ€¦"), which routes only to
`_parse_remove_counter`. Named here so the next attempt starts from the token
rather than from the card.

**The size guard fired, and obeying it found a misfiling.**
`test_m21_creatures.py` crossed 2,600 lines, and the four tests moved out were
not creature tests at all â€” each compiles a sentence and asserts a refusal, which
is what `test_m21_cards.py` is for. The growth that broke the guard was tests in
the wrong file, which is exactly what idiom #13 predicts a split will show.

Suite **5,152** green, every `--check` gate green, shipped pool 388/388, AI
simulation byte-identical at 443 interactions (one printed flip is one RNG draw,
asserted). CR 705 goes 0/3 â†’ 2/3 and CR 119 1/10 â†’ 2/10.

**Next:**

- **A counter-removal activation cost is admitted by the grammar and charged by
  nobody.** `_parse_counter_removal_cost` admits any counter kind for any
  effect; `ActivatedAbilityCost` has no field for it, and the only charge is a
  branch gated on one instruction kind *and* a literal substring of the card's
  normalized text. An invented card printing "Remove a +1/+1 counter from this
  creature: This creature gets +1/+1 until end of turn." compiles supported and
  activates for free with zero counters. It is invisible because the two-reader
  guard branches only on `SacrificeCost`, `DiscardCost` and now `PayLife` â€”
  adding the `RemoveCounterCost` branch fails immediately, which is the fix's
  own test.
- The rest of round 65's *Next*, unchanged: "another" as a source exclusion, the
  headless simulator's discarded permanent target, the Shrine cycle, a static
  P/T contribution with a computed X, a reflexive trigger, the legend rule.

## Round 67: the gate on an object nothing reads

*(2026-08-16.)* M21 **221 â†’ 221**, and the flat number is again the point:
Sabertooth Mauler has been supported this whole time and its trigger had **never
once fired**. Not a fizzle, not a log line â€” never enqueued.

> At the beginning of your end step, if a creature died this turn, put a +1/+1
> counter on this creature and untap it.

**A new route into the Nine Lives class.** Every earlier member was a line that
lowered to *nothing*. This one lowers to two perfectly good instructions,
`add_counter_to_self` and `untap_self`, and `lower_ability` attaches CR 603.4's
intervening-if to each of them, correctly, because it attaches the gate to every
**top-level** instruction. `engine/oracle.py` then wraps the pair in a `sequence`
â€” and the wrapper is the new top level. Both readers of the gate look at the top
level: the end step's scan decides whether to enqueue the trigger at all, and
`mixins/stack/resolution.py` re-checks it on resolution. So the condition sat on
a payload nothing reads, and the card did nothing.

The fix carries the gate onto the wrapper, and only when **every** step agrees â€”
the gate belongs to the *line*, and a wrapper cannot express two different ones.
Steps that disagree keep their own and the wrapper stays ungated, which is
today's behaviour; no card in the pool prints that shape. Whole-pool program
diff: **one card**.

**The guard for exactly this failure existed, and was vacuous twice over.**
`test_every_executed_end_step_trigger_lands_on_a_kind_the_step_enqueues` was
written against this bug class. It missed it because:

1. **It read `compile_line`'s unfused instruction list** â€” two instructions that
   each *do* carry the gate â€” where the step is handed the fused one. A guard
   reading a different object from its dispatcher is checking a card nobody
   plays. It now reads the fused instruction, through `compile_card_oracle`.
2. **It did not know the step also dispatches on the gate itself**, whatever the
   instruction kind. Over the measured pool it would have flagged five healthy
   cards (Griffin Aerie, Barrin, Liliana's Devotee, Indulging Patrician,
   Twinblade Assassins) beside the one sick one â€” which is the reason it could
   only ever be run somewhere those cards do not exist.

Both halves fixed, and the fix is demonstrated rather than asserted: the guard's
logic over the whole pool including M21 finds **zero** with the fix in and
**exactly Sabertooth Mauler** with it reverted.

**One thing deliberately not done.** The guard's fixture stays the shipped
`catalog`, so it still cannot see the card that broke it â€” widening a
shipped-pool guard to a measured set is `SET_PLAYBOOK.md`'s policy call, not a
bug fix, and it is recorded here rather than taken quietly. It has been measured
as free (zero findings). The card itself is covered by
`tests/regressions/test_fused_trigger_gate.py`, whose two tests were watched to
fail and pass on the round-66 engine respectively.

Suite green, every `--check` gate green, shipped pool 388/388, AI simulation
byte-identical at 443 interactions.

**Next:** widen that fixture, or decide in the playbook that it stays narrow.
Then Liliana's Scrounger, whose spec is what found this.
