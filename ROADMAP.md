# Scaling Roadmap

Target: grow the card pool from 388 unique cards (LEA/LEB/2ED/ARN/3ED shipped,
M21 measured at 217/285) to the full release line - **137 sets, 33,594
printings, 26,113 unique cards** per `set_progress.json`.

A chronological engineering journal, kept to the last three rounds. Everything
before them — the founding audit, the parser migration (finished:
`engine/parsing/` is deleted and `engine/grammar/` is the only parser), the
per-set narratives, and M21 rounds 1–57 — lives in git history at and before
commit `198ca7e`. What those rounds established that outlives their narrative is
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
- **Three zones handlers call `player.draw` directly**, skipping any armed draw
  replacement, which is `_draw_with_replacements`' own docstring's warning.
  Round 31 banned the equivalent shortcut for counter placement by AST guard
  while the debt was still cheap to prevent; the draw debt is still owed — and
  since round 58 it has a card behind it. Teferi's Ageless Insight does not
  double a Wheel of Fortune, a Timetwister or a Bazaar of Baghdad, because those
  three take their cards off the library themselves. The *trigger* half is safe:
  "whenever you draw a card" is announced by a sweep over
  ``cards_drawn_this_turn``, which every path feeds, so the shortcut costs the
  replacements and nothing else.
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

## Round 58: a replacement that changes the number, and a condition nothing said

*(2026-08-16.)* M21 **213 → 214** in the count and **three more cards that
actually work** — which is the whole shape of this round. Teferi's Ageless
Insight is the +1. Lorescale Coatl and Burlfist Oak were already counted as
supported and had never once done anything.

**Teferi's needed the draw seam to change, not the gate.** Round 57's seventh
registry meant a claim was waiting for it, but "If you would draw a card except
the first one you draw in each of your draw steps, draw two cards instead" is a
*modifying* replacement, and every draw replacement before it **consumed** the
event — Aladdin's Lamp and Ring of Ma'rûf both take the draw and report what
they did. So `_draw_with_replacements` took its own local `count` at the end and
never read the payload's, which meant a replacement that only changed the number
could not be written at all: the interceptor would run, the number would change,
and the draw would take the old one. `place_plus1_counters` has read its count
back since Conclave Mentor; the draw seam is the same rule and did not.

**The rider is one draw, not one event.** CR 121.2 makes an event of N draws
that many individual draws, and "the first one you draw in each of your draw
steps" exempts one of them — so a draw step with a Howling Mine out draws 1 + 1
in one call and three cards arrive, not two. The exemption is a flag the draw
step passes (`turn_based=True`), because the engine genuinely cannot derive it:
a later draw during your own draw step is also made by the active player while
the step is the draw step, and it is not the first one.

**Then the round found something.** Checking that a doubled draw fires "whenever
you draw a card" the right number of times turned up the fact that it fires it
**no** times: `draws_card` parsed in the oracle table *and* in the grammar's
phrase table and had no dispatcher anywhere. Two supported M21 cards compiled a
real instruction under a condition the game never announced — Lorescale Coatl
("put a +1/+1 counter on this creature") and Burlfist Oak ("gets +2/+2 until end
of turn") — and both entered play and did nothing, invisibly, because the
support report can see that a condition parsed and cannot see whether anything
says it happened. That is idiom 4's fifth instance and its first with cards
behind it.

**It goes on the sweep, not on the draw sites**, beside the "your second card
each turn" trigger and off the same record. That choice is what makes it
complete rather than nearly complete: three zones handlers reach `player.draw`
directly, and a per-site announcement would have missed exactly those three the
way the replacements already do. Counting rather than flagging is the only
difference from its neighbour — CR 121.2 again.

**And the guard that should have caught it now exists.**
`tests/engine/test_trigger_dispatchers.py` takes every condition a *supported*
card compiles with a real instruction and asks whether the engine names that
kind anywhere at all. Deliberately the weak question: a trigger can be
dispatched by `emit`, by an `iter_triggered_abilities` scan, by the upkeep
registry's `(condition, kind)` pair or by a plain comparison in a phase step, and
enumerating those mechanisms is a list that goes stale exactly like a list of
fire sites. Docstrings are excluded — `engine/events.py`'s own docstring names
`draws_card`, as an example of this very failure — and so are the parse tables
and the event-filter rows, because a filter with no announcement behind it
narrows an event that never happens.

The recorded draw debt got a card, too: Teferi's does **not** double a Wheel of
Fortune, a Timetwister or a Bazaar of Baghdad, because those three take their
cards off the library themselves. The trigger half is safe — the sweep sees
them — so the shortcut now costs exactly the replacements and nothing else,
which is a sharper statement of the debt than "still owed".

Suite **5,095** at 21.9s, every `--check` green, shipped pool 388/388, AI
simulation byte-identical at 443 interactions. Five of the eight new card tests
were watched to fail on the round-57 engine; the rest are controls — an
opponent's draw, and the draw-step exemption, which passed before only because
nothing happened at all.

**Next:**

- **The Shrine cycle**, unchanged: Fruitful Harvest's colour choice at a
  trigger's resolution, Shattered Heights' discard cost from the
  hand-activation block, Tranquil Light's per-Shrine cost reduction, Sanctum of
  All's two-zone search and trigger-doubling static.
- **The draw debt itself** now has both a card and a guard's shape to copy:
  round 31 banned the counter-placement shortcut by AST guard, and the three
  `player.draw` callers are a smaller list than that one was.
- **Experimental Overload's variable-P/T token and Jolrael's team base-P/T**,
  then the legend rule from round 49.

## Round 59: how many creatures attacked

*(2026-08-16.)* M21 **214 → 216** — Tide Skimmer and Makeshift Battalion, two
cards that ask a question no announcement in the engine could answer.

**Three attack-trigger shapes existed and none of them was about the group.**
`_fire_attack_triggers` fires once per declaration for one card's own ability
(Raging River), `_fire_creature_attacks_triggers` fires each attacker's own
ability, and `_fire_matching_creature_attacks_triggers` announces each attacker
to the whole board. "Whenever you attack with **two or more** creatures with
flying" and "whenever this creature and **at least two other** creatures attack"
are neither per-card nor per-creature: they are about the declaration (CR 508.1),
and the count is only knowable while the whole declaration is in hand.
`attackers_declared` is the fourth shape, announced once, carrying the attackers
themselves — not the `combat_attackers` map, because that is index-keyed and a
later removal renumbers it.

**One kind, two rows, and the difference is payload.** The two printed spellings
could have been two condition kinds; they are one, because what differs is not
the event but what the card asks about it — a count and a noun phrase for the
Skimmer, a count of *others* plus "the source is one of them" for the Battalion.
That is round 34's rule (a narrowing is data on the condition) applied to the
count as well as the filter, and the count needed its own delimiter suffix:
`<name>_count` is a printed number word, read by the same table every other
text-keyed count uses, and a word that table does not know refuses the whole
condition rather than defaulting to one.

**The noun parser needed a plural reading, and it is worth being exact about
why.** `parse_subject_filter` admits only "a creature you control …", refusing a
bare plural because everywhere else that is the *sweep* quantifier and a trigger
claiming to fire on "each creature" would be a different card. In "two or more
**creatures with flying**" the phrase is counted rather than quantified: it names
a kind and the number in front says how many. So the plural is admitted in that
one position, and which position it is comes from the pattern's own group name —
`_subjects` rather than `_subject`.

**Ability words are gone, by rule rather than by card.** CR 207.2c: an ability
word is italic flavour with no rules meaning at all, so "Battalion —" is dropped
before either front end reads the line, from **one** function both call — a word
stripped on one side only is a line whose two halves disagree about what was
printed. The list is the printed vocabulary rather than the one word this pool
has, because a word left out is a card whose whole line fails for a reason the
parser is allowed to ignore. The control test is that a dash *without* an ability
word in front of it is left alone: the strip is keyed on the vocabulary, not on
the punctuation.

A test had to change its mind rather than its expectation, which is the honest
form: `test_an_ability_word_is_no_longer_filed_under_modal` pinned "Battalion —"
failing on the trigger rather than on the dash, and that was right when the
trigger genuinely could not be read. It now pins the line parsing.

Suite **5,101** at 22.1s, every `--check` green, shipped pool 388/388, AI
simulation byte-identical at 443 interactions. M21's parsed share moved 70.2% →
70.6%. Three of the six new tests were watched to fail on the round-58 engine;
the rest are controls — a grounded attacker, a two-creature attack, and a
Battalion that stayed home.

**Next:**

- **The Shrine cycle**, unchanged: Fruitful Harvest's colour choice at a
  trigger's resolution, Shattered Heights' discard cost from the
  hand-activation block, Tranquil Light's per-Shrine cost reduction, Sanctum of
  All's two-zone search and trigger-doubling static.
- **An optional cost that is not generic.** "You may pay {1}{B}. If you do, …"
  (Liliana's Devotee) refuses, and the reason is that there is no one way to pay
  a mana cost here: the activation path spends from the pool and expects the
  lands already tapped, the optional-pay prompt taps lands itself but only for
  generic, and the two disagree about what "can pay" means. One payer would
  serve every "you may pay" ever printed.
- **The draw debt** (three `player.draw` callers, with round 31's AST-guard
  shape to copy), then **Experimental Overload's variable-P/T token and
  Jolrael's team base-P/T**, then the legend rule from round 49.

## Round 60: one way to pay a cost

*(2026-08-16.)* M21 **216 → 217** — Liliana's Devotee, and the reason it was
refused rather than missing.

**"You may pay {1}{B}" was not a parser gap.** The line parsed; the *lowering*
refused it, and its message said why: "optional colored costs need a real
cost-payment prompt". There are two questions about paying a mana cost, and the
engine answered only one of them well. Casting and activating spend the **pool**
— the right question there, because producing the mana is the player's own
separate action, taken before the cost is collected. An effect that says "you
may pay" gives its player no priority window at all, so it has to look at the
untapped lands too — and that answer *counted to a number*: floating mana plus
untapped mana-producing lands, against a generic cost. A {B} had nothing to
collect it with, so the honest thing was to refuse the card, and the refusal
would have stood forever.

`engine/mana_payment.py` is the answer that replaced the number. It plans a
payment rather than performing one, which is what lets "could this be paid?"
(CR 601.2h) and "pay it" be the same code: pool first for the coloured pips —
floating mana is already spent-in-advance and an untapped land is worth more
than a tapped one — then the lands, then the generic part from whatever is left.

**The matching is exact, and the reason is which way the error goes.** A
one-pass picker gets a board wrong that can genuinely pay: a Swamp and an
Underground Sea against {U}{B} is fine until the pass spends the Sea on the {B}
and strands the {U}. That error *under*-reports — a cost the player could pay is
never offered — and CR 601.2h is about what a player is **able** to do rather
than about what an approximation could find. The numbers are a handful of pips
against a handful of lands, so the exact answer is a dozen lines of
augmenting-path matching and there is no reason to accept a heuristic.

**One shape for a cost, at the cost of a migration.** The prompt's `cost` was an
integer and four effects handed one over; it is now the symbol dict the rest of
the engine already uses for a mana cost, and `generic_cost(n)` is the one line
that says which cost a legacy number is. The non-interactive default is stated
rather than derived: it spends mana it already has and never taps a land for an
optional cost, because tapping is a real decision about the rest of the turn —
and it is *not* the payability test, which belongs to the seat that was asked.

**And the card found something on the way in.** With the cost payable, the
trigger still did not fire: the end step enqueues a CR 603.4 intervening-if
trigger from a list of **instruction kinds** holding exactly one entry
(`draw_controller_cards`, for Barrin), and Liliana's Devotee lowers onto `may`.
Round 45's lesson, and the fourth time it has been paid for — so the scan is
keyed on the payload's *shape* now. The gate lives on the payload, so "does it
have one" is the whole question, and a trigger with a gate is enqueued whatever
its effect turned out to be. The three kind-keyed scans beside it stay: each
needs a specific trigger context, and none of their kinds carries a gate — which
is checked in code rather than asserted in a comment, because "today" is the
part that expires.

Suite **5,111** at 22.1s, every `--check` green, shipped pool 388/388, AI
simulation byte-identical at 443 interactions. Two of the ten new tests were
watched to fail on the round-59 engine — the payment module's tests cannot
import against it at all — and the rest are controls: two Forests are two mana
and still not {1}{B}, a land cannot pay two pips at once, and a Devotee with
nothing dead is silent.

**Next:**

- **The Shrine cycle**, unchanged: Fruitful Harvest's colour choice at a
  trigger's resolution, Shattered Heights' discard cost (whose "a land card or
  **Shrine** card" is a noun-phrase *union* the parser has no production for),
  Tranquil Light's per-Shrine cost reduction, Sanctum of All's two-zone search
  and trigger-doubling static.
- **A reflexive trigger** — "you may pay {1}. **When you do**, …" (Tolarian
  Kraken). Deliberately not folded into this round: CR 603.11 puts a second
  object on the stack, and the `may` machinery resolves its consequence inline,
  so reading "when you do" as "if you do" would be claiming a distinction the
  engine does not make.
- **The draw debt** (three `player.draw` callers, with round 31's AST-guard
  shape to copy), then **Experimental Overload's variable-P/T token and
  Jolrael's team base-P/T**, then the legend rule from round 49.
