# Scaling Roadmap

Target: grow the card pool from 388 unique cards (LEA/LEB/2ED/ARN/3ED shipped,
M21 measured at 229/285) to the full release line - **137 sets, 33,594
printings, 26,113 unique cards** per `set_progress.json`.

A chronological engineering journal, kept to the last three rounds. Everything
before them — the founding audit, the parser migration (finished:
`engine/parsing/` is deleted and `engine/grammar/` is the only parser), the
per-set narratives, and M21 rounds 1–75 — lives in git history at and before
commit `7876c06`. What those rounds established that outlives their narrative is
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

## Round 76: a trigger that fires from a graveyard

*(2026-08-16.)* M21 **227 → 228** — Silversmote Ghoul, and the round is worth
taking for the seam rather than the card.

**"Every trigger this engine dispatches is on a permanent" was wrong, twice.**
Emblems already fire from the command zone, and **Nether Shadow already fires
from a graveyard** — name-keyed in `card_hooks.py` since long before this
effort. So this is not a new seam, it is the second card of a shape, which is
what turns a special case into a rule.

**The gate is derived, not declared.** CR 113.6 says an object's abilities
function only on the battlefield *unless the ability says otherwise*, and
CR 113.6m is the clause that says otherwise — for an ability whose effect moves
its own source out of a zone. So the zone the sentence names as the source *is*
the zone the ability functions from, stamped by the lowering as `functions_from`
and read by the scan. No card name, and no list of instruction kinds: a list is
only ever as complete as the last card that touched it.

**Two of my three framings were wrong**, both corrected against the rules file.
`_SELF_CONDITIONS` is not the reader for this card's condition — that maps the
*contraction* ("you've gained"), Sanguine Indulgence's cast-cost gate; the Ghoul
prints an intervening-if whose reader was already complete, and Griffin Aerie and
Indulging Patrician print the identical clause and work today. And
`enter_effects.py` is the wrong home for "tapped": it answers for a permanent's
own printed entry line, which CR 603.6d makes a static ability, where this is
CR 110.5b — a rider on the *move*. Putting it there would have made the Ghoul
enter tapped when somebody else's reanimation returned it.

**The look-alike trap, in the zone where it is worst.** A graveyard holds
`CardDefinition` objects, and two copies of one card are *the same immutable
object* — so the filter-by-identity rebuild this codebase bans on `battlefield`
is worse here: it removes **all** copies, not merely the wrong one. Measured:
`[c for c in gy if c is not card]` on a graveyard holding two Ghouls leaves
neither. The handler pops at an identity-found index instead, and a test puts two
in one graveyard and asserts both come back with distinct ids.

**The guard that had to come with it.** Measured while building this: with the
grammar, the lowering and the handler in place but the scan omitted, the card
**compiled supported, the whole suite passed, and all five `--check` gates
passed, while the ability never once fired.** `test_trigger_dispatchers.py`
cannot see it — it asks per condition kind, and `end_step_self` has had a
dispatcher since round 68, over battlefields. That is round 58's `draws_card`
failure on a new axis, so the round adds a behavioural guard: put the card in a
graveyard, arm its condition, run the step, look at the battlefield. Verified by
neutering the scan and watching it fail.

Suite green, every `--check` gate green, shipped pool 388/388, AI simulation
byte-identical, **zero hooks added**. Whole-pool compile diff: exactly one card.

**Recorded, not fixed** (its own round — it changes shipped, manually-verified
behaviour): **Nether Shadow deletes cards from the game** by that same
filter-by-identity rebuild, its trigger never touches the stack (applied inline,
so CR 603.4's second check is unobservable rather than skipped), and its prompt
is name-keyed and deduped so two eligible copies get one prompt whose answer
decides both.

## Round 77: a graveyard slot is not an identity either

*(2026-08-16.)* No card — the fix the last three rounds kept pointing at, and it
turned out to be hiding **three** shipped-pool defects rather than one.

`_stack_push` stamps a stable `permanent_id` for a battlefield target because "a
stack object is the engine's only structure that outlives the moment it was
built" — its own docstring. A card in a **graveyard** had no such stamp, so
resolution re-read a raw index against a list that had since shifted:

* **Raise Dead** named Grizzly Bears, one card left the graveyard in response,
  and it returned **Hill Giant**. The several-card path was worse — Sanguine
  Indulgence named two and returned one.
* **Reconstruction was uncastable.** Its picker offers artifact cards; its
  cast-time re-check hardcoded `primary_type != "creature"`. The only card a
  player could name was one the check then refused, so with no creature in the
  graveyard the card could not be played at all. One shared predicate now serves
  picker, re-check and handler, and `legality.py` gets 22 lines shorter.
* **A protection check read `battlefield[slot]` for a graveyard slot**, so a
  White Knight the spell never targeted refused Raise Dead.

**The identity is a card plus which copy of it**, because the dedupe leaves the
engine nothing else: two copies of one card in one graveyard are the same
`CardDefinition` object, and neither an id nor `is` separates them. The residual
is stated rather than hidden — with two copies the engine cannot know *which* one
left, so the read clamps to the last surviving copy and reports "gone" only when
no copy remains, the one case the data model can actually establish.

**Three things my brief got wrong**, all corrected on evidence: Fungal Rebirth
does not target a graveyard card (thirteen cards do, four of which I had not
named); `_stack_push` *can* know the zone, and today does something worse than
nothing — it stamps a **battlefield** id onto a graveyard target; and the casting
path cannot be the home, because it never sees an ability, a trigger or a mode.

**Deliberately not fixed, and measured.** CR 608.2b's fizzle — a target that has
become illegal — has the identical gap *on the battlefield*, and it is far more
reachable: Lightning Bolt aimed at a creature that dies in response deals its 3 to
whatever slid into the slot. Round 65 chose that fallback in writing. It wants one
seam for both zones, which is the next round rather than a rider on this one.

Suite green, every `--check` gate green, shipped pool 388/388, AI simulation
byte-identical at 443 interactions. Four regressions, all four watched to fail on
the round-76 engine.

## Round 78: what a card *was*, read after it stopped being there

*(2026-08-16.)* M21 **228 → 229** — Scavenging Ooze, which round 77 had to
precede.

> {G}: Exile target card from a graveyard. If it was a creature card, put a
> +1/+1 counter on this creature and you gain 1 life.

Three things looked new and only one was. **"A graveyard"** — any pile, not the
controller's — the engine already did. **An activated ability** targeting a
graveyard card it did for the targeting spec, but not for the stack identity
(round 77) and not in the browser at all: the activation cascade has no
`graveyard_creature` case, so five M21 cards are unpickable there today, and this
round adds the missing branch.

**Last-known information was the one that needed building** (CR 608.2h, idiom
#6). The mechanism existed — `_PRODUCES` and the resolution scratchpad, with
`had_plus1_counter` as the worked example — but no producer: the exile recorded
nothing, so there was nothing for "it was" to read. `ItWas(filter)` parses with
no referent, exactly as `ThatMuch(None)` does, and lowering resolves it against
what this same effect produced and **refuses without a producer**. Otherwise the
condition answers False forever and the card compiles clean with a rider that
never fires — the shape this repo has now found on four separate axes.

The exile is unconditional and only the rider is gated, which is what the two
tests pin: an instant still leaves the graveyard and the Ooze gets nothing.

**The size-guard premise I gave the agent was out of date** — round 73's split
had already bought the room, and the file was 2,180 against the 2,600 cap rather
than at its edge. No split, no audit.

Suite green, every `--check` gate green, shipped pool 388/388, AI simulation
byte-identical at 443 interactions, **zero hooks added**, no ratchet touched.
Whole-pool compile diff: exactly one card.

**Next**, carried from this session and unfixed:

- **One fizzle seam for both zones** (round 77's deferral, and the largest
  remaining): CR 608.2b on the battlefield is the same gap and more reachable —
  Lightning Bolt aimed at a creature that dies in response deals its 3 to
  whatever slid into the slot.
- **Nether Shadow deletes cards from the game** (round 76): the
  filter-by-identity graveyard rebuild removes every copy, its trigger never
  touches the stack, and its prompt is name-keyed and deduped.
- The counter-removal activation cost the grammar admits and nobody charges
  (round 66); "another" past the sole-target case (round 73); Read the Tides'
  browser-unreachable second mode and Fungal Rebirth's dropped "permanent"
  (round 69); `parse_coverage.py` blind to measured sets; the Shrine cycle; a
  reflexive trigger; the legend rule.

