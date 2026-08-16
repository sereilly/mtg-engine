# Scaling Roadmap

Target: grow the card pool from 388 unique cards (LEA/LEB/2ED/ARN/3ED shipped,
M21 measured at 211/285) to the full release line - **137 sets, 33,594
printings, 26,113 unique cards** per `set_progress.json`.

A chronological engineering journal, kept to the last three rounds. Everything
before them — the founding audit, the parser migration (finished:
`engine/parsing/` is deleted and `engine/grammar/` is the only parser), the
per-set narratives, and M21 rounds 1–53 — lives in git history at and before
commit `b3f46cc`. What those rounds established that outlives their narrative is
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
- **The Shrine cycle and the where-clause cards**: see round 56's *Next* below,
  which is current.
- **A damage event does not know who dealt it** (round 56). The payload carries
  `source`, which is a `Permanent` for a permanent and a bare `CardDefinition`
  for a spell — and a printed card has no controller, so "a source **you
  control**" is unanswerable. Fiery Emancipation and Chandra's Pyreling both
  want it, and neither can be written honestly without it: a Permanent-only
  reading tripled a creature's damage and silently not a burn spell's, which is
  the Nine Lives class again. Threading a seat through the 45 call sites is the
  wrong shape (idiom 3); the seat is known at
  `_execute_oracle_instruction`, the single dispatch point round 54 used for the
  same reason.

### Recorded, measured, and not yet fixed

- **The Nine Lives class — partial implementation reported as full.** A card is
  supported when **any** line is, so a card can report supported while other
  lines produce nothing. Nine Lives' damage-prevention replacement and its exile
  trigger produce nothing. Round 53's hollow gate closes only the *fully* hollow
  case (nothing supported, nothing static, markers only), and round 20's all-of
  gate closes the modal shape; the general class is still open and has been
  found one card at a time — Return to Nature's third mode (round 12), Read the
  Tides' second (17), Garruk's Uprising' third line (34), Sanctum of Stone
  Fangs, Fiery Emancipation and Teferi's Ageless Insight (53). It wants a census
  of its own, in the shape Phase 2 uses for a set.
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
- **Three zones handlers call `player.draw` directly**, skipping any armed draw
  replacement, which is `_draw_with_replacements`' own docstring's warning.
  Round 31 banned the equivalent shortcut for counter placement by AST guard
  while the debt was still cheap to prevent; the draw debt is still owed.
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

## Round 54: a clause that defines X, and the one place X is read

*(2026-08-16.)* Both subsystems round 53 sized, built. M21 **206 → 208** —
Sanctum of Stone Fangs, which round 53 had to take away, and Sanctum of Calm
Waters beside it.

**"…, where X is the number of <filter>" is a statement-level clause now.** It
existed only inside `_parse_gets`, which is why exactly one sentence shape in
the pool could carry one. `parse_statement` became a thin wrapper whose whole
body is the rule: the clause binds the *whole* sentence, so it is read once
around the body rather than wherever the body happens to stop — and the body
returns early from `if`, from `you may`, and from a cast permission, so asking
each of them to remember the clause is how one of them forgets.

**Two binding mistakes, both found by execution rather than by reading**, and
both the same shape:

- The first version let the *recursive* call take the clause, so "each opponent
  loses X life and you gain X life, where X is …" gave the definition to the
  gain and the loss silently lost nothing. The life total moved, which is what
  makes it a bad bug: the card looked like it worked. `top_level=False` on
  every nested call is the fix.
- `_attach_if_you_do` then stopped finding its `May`, because the sentence is
  now a `WhereX` wrapping one. It lifts the clause off, folds, and puts it back
  outside — the definition binds the branch as well as the offer.

**X is resolved at one place, and that is what makes the clause general.** The
count is stamped onto the lowered instructions (and into the steps nested inside
a `sequence`, `if_then` or `may` — stamping the top level alone would leave the
inner ones reading the cast's X, which for a triggered ability is None), and
`_execute_oracle_instruction` turns it into `context.x_value` before dispatch.
Every amount path already resolves the string `"x"` against that, so one
substitution at the single dispatch point hands the clause to every effect
family at once.

**Except that not every amount path did.** The first end-to-end run died on
`int('x')`: **nineteen handlers read `int(payload["amount"])` directly** instead
of `resolve_amount`, so they could never have honoured an X at all. They all go
through the one rule now — which is the difference between a clause that works
for the four handlers this round happened to touch and one that works.

A count refuses rather than guesses in two places worth naming: a filter
narrowed to *another player's* permanents ("the number of Mountains **they**
control"), because `permanent_matches_filter` does not test a controller and the
key would have been handed over and ignored; and a where-clause defining an X no
instruction reads, which means one of the two was misread.

**"At the beginning of your first main phase"** landed on both sides of the
pipeline — the oracle regex table and the grammar's phrase table — because round
7's lesson is that a condition narrowed on one side only compiles the card
supported and fires it on the wrong event. Its fire site takes **no whitelist of
instruction kinds**: round 45 is the record of what that costs, and Onulet never
gained a point of life because its kind was not in a list.

Suite **5,040** at 21.4s, every `--check` green, shipped pool 388/388, AI
simulation byte-identical at 443 interactions.

**Next:**

- **The rest of the Shrine cycle**, now that both subsystems exist: Fruitful
  Harvest wants "add X mana **of any one color**" (a colour choice, not a
  count), Shattered Heights the filtered discard cost from round 51's family,
  Tranquil Light a per-Shrine cost reduction, Sanctum of All a two-zone search
  plus a trigger-doubling static.
- **The seven other cards the clause was built for** — Liliana's Standard
  Bearer, Experimental Overload, Jolrael and the rest — each of which now needs
  only its own second half.
- **The legend rule reads the printed name** (unchanged from round 49).

---

## Round 55: a count of what is no longer there

*(2026-08-16.)* A small round on round 54's clause. M21 **208 → 209** —
Liliana's Standard Bearer — plus a dropped rider the new guard found on its own,
in a card nobody had asked about.

**"…where X is the number of creatures that died under your control this
turn."** A count of a *history*, and it is the opposite set from the one the
bare filter names: the creatures counted are exactly the ones the battlefield no
longer holds, so reading it as "creature" would count the survivors. It gets its
own amount node (`CountOfDeaths`) beside `CountOf` for that reason, and reads
the per-seat tracker round 14 built — the game-wide tally cannot answer "under
**your** control", which the second test pins by killing two of the opponent's
creatures and drawing one card.

The lowering admits only the bare creature filter, because the tracker counts
creatures and nothing narrower: a narrowing it cannot apply would be counted as
if it were not there.

**And the guard earned its keep.** Round 54 refused "a where-clause defined an X
nothing reads", and Sanctum of Fruitful Harvest tripped it. The cause was not in
the clause: `_parse_add_mana` read the count as
`count.value if isinstance(count, ast.Fixed) else 1`, so **"Add X mana of any
one color" parsed as one mana**. It refuses now. No card in this pool reaches
the grammar with that shape — Black Lotus and Metamorphosis both keep their own
fused handlers — which is the point: the narrowing would have waited for the
card that finally printed it, and the guard found it without one.

Suite **5,043** at 21.4s, every `--check` green, shipped pool 388/388, AI
simulation byte-identical at 443 interactions. All three new tests were watched
to fail on HEAD.

**Next:** unchanged in substance from round 54 — the rest of the Shrine cycle
(Fruitful Harvest now needs only a colour choice at a trigger's resolution,
which is a new prompt kind; Shattered Heights the filtered discard cost;
Tranquil Light a per-Shrine cost reduction; Sanctum of All a two-zone search and
a trigger-doubling static), then Experimental Overload's variable-P/T token and
Jolrael's team base-P/T, and the legend rule from round 49.

---

## Round 56: the third reader of a noun phrase

*(2026-08-16.)* M21 **209 → 211** — Portcullis Vine and Run Afoul, one on each
side of a sacrifice. The round is really about the thing both of them were
waiting for, which had nothing to do with sacrifice.

**A filter payload had two matchers, and only one of them was shared.**
`permanent_matches_filter` answers every key readable off the permanent alone,
and every filter reader in the engine already used it. Three keys are not
readable that way — a keyword is a layer-6 question (CR 613.1f), "you control"
is a seat comparison, "another" is an identity comparison — so they were tested
*inline at the trigger fire sites*, next to the list of keys a compiler is
allowed to admit. That made `TESTABLE_SUBJECT_FILTER_KEYS` a claim about
triggers while reading as a claim about noun phrases, and the second caller is
what found the difference: **a sacrifice names its victim with the same noun
phrase a trigger names its subject**, and the paths that read it had only the
pure matcher. A keyword narrowing was structurally untestable there, so both
halves refused — correctly, and for a reason that was invisible from where they
refused. `engine/subject_filters.py` is the one matcher and the one key set.

**Both refusals were already written down, one of them naming the card.**
`_is_chargeable_sacrifice` said "everything the pool prints but 'a creature
**with defender**' (Portcullis Vine)"; the cost regex beside it said the same
thing from the other side, anchored so the phrase could not match. Neither was a
gap to be closed on sight — dropping the rider lets the Vine eat any creature
while still reporting supported — and both now delegate to
`object_only_filter` rather than deciding for themselves.

**The cost regex only delimits now.** Round 34's idiom for a narrowed trigger
condition — the regex marks out the noun phrase, `grammar.parse_subject_filter`
reads it, a pool-wide guard compares the two front ends — applied to the third
reader of one. That guard existed and asked the weaker question: *is something
charged*. It now asks *is **this** charged*, comparing the charger's payload
against the grammar's whole noun phrase, because "a creature with defender"
charged as "a creature" is the dropped-rider bug with the card still green.

**Four readers, one answer.** The activation-cost charger, the cast additional
cost, the forced-sacrifice prompt and the UI's target enumerator each had their
own idea of what may pay: two type-word comparisons, a two-branch
`if filter == "nontoken" … elif filter == "creature"`, and a picker `kind`. All
four now take a filter payload through `subject_matches`. The picker matters as
much as the charger and for the reason round 48 recorded: a list that offers the
Cat has its answer silently swapped for the deterministic pick at payment time,
so the game depends on whether a person or a script answered.

**"Of their choice" is read and then dropped, at the one place entitled to drop
it.** Run Afoul prints "a creature **of their choice** with flying", so the
phrase sits *between* the head noun and the restriction and cannot be consumed
by the verb's production without stranding "with flying". It is a noun-phrase
modifier, parsed as one, and `their_choice` is emitted into the payload
**precisely so that every gate refuses it** — no matcher can test who picks. The
sacrifice lowering names it as something the prompt already performs (CR 701.21a
gives the choice to the sacrificing player) and removes it there. Only "their"
is read: "of *your* choice" would be a different card.

**Two near-misses, both caught by existing tests rather than by reading.**
Widening the branch to any noun phrase routed "sacrifice **this** creature" (Sea
Serpent, Island Fish Jasconius, Pirate Ship) to the prompt with an *empty*
filter — a prompt over every permanent on the board — because a self-referential
subject emits no payload keys at all. And `_resolve_sacrifice_inline` turned out
to be a fourth copy of `default_sacrifice_pick`, carrying "keep the game-loser
for last" and neither the smallest-first half nor the id tiebreak — while
`default_sacrifice_pick`'s own docstring named it as one of the three callers it
had unified. Two seats owing the same sacrifice through different paths would
have given up different permanents. Both fixed; the AI simulation is
byte-identical either way, which is what the docstring was quietly relying on.

`nontoken` joined the payload vocabulary on the way (CR 111.1 — not a card type,
so neither an excluded type nor an excluded subtype), because Lich's prompt had
been carrying that restriction as one of the two magic words. A side effect
worth naming: "sacrifice a **land**" lowers now where only "creature" did, so
the template is general rather than one type wide.

Suite **5,067** at 21.4s, every `--check` green, shipped pool 388/388, AI
simulation byte-identical at 443 interactions. Five of the seven new tests were
watched to fail on HEAD; the other two are controls — the narrowing the prompt
*cannot* test, which must keep refusing, and Run Afoul against a board with no
flier. `tests/engine/test_subject_filters.py` holds the key set to what is
demonstrated rather than to what is listed: a key promised without a matcher
behind it admits every card printing that phrase and then ignores it.

**Next:**

- **The Shrine cycle**, unchanged from round 55: Fruitful Harvest needs a colour
  choice at a trigger's resolution, Shattered Heights the discard cost from the
  hand-activation block, Tranquil Light a per-Shrine cost reduction, Sanctum of
  All a two-zone search and a trigger-doubling static.
- **The two replacement effects round 53 had to take away** — Fiery Emancipation
  ("it deals triple that damage instead") and Teferi's Ageless Insight ("draw two
  cards instead"). Sized this round and deliberately not started: the CR 614
  registry is the **one** text-keyed registry `_derived_static_claims` does not
  ask, so a permanent whose only ability is a replacement is unsupported however
  well the interceptor works — and Fiery Emancipation additionally wants
  something the engine does not have, since a damage event carries its `source`
  but not the seat that controls it, and "a source **you control**" is
  unanswerable from a bare `CardDefinition`. That seat would also buy Chandra's
  Pyreling.
- **Experimental Overload's variable-P/T token and Jolrael's team base-P/T**,
  then the legend rule from round 49.
