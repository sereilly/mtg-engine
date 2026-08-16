# Scaling Roadmap

Target: grow the card pool from 388 unique cards (LEA/LEB/2ED/ARN/3ED shipped,
M21 measured at 214/285) to the full release line - **137 sets, 33,594
printings, 26,113 unique cards** per `set_progress.json`.

A chronological engineering journal, kept to the last three rounds. Everything
before them — the founding audit, the parser migration (finished:
`engine/parsing/` is deleted and `engine/grammar/` is the only parser), the
per-set narratives, and M21 rounds 1–55 — lives in git history at and before
commit `b0c5a26`. What those rounds established that outlives their narrative is
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

## Round 57: a damage event that knows who dealt it

*(2026-08-16.)* M21 **211 → 213** — Fiery Emancipation, which round 53 had to
take away, and Chandra's Pyreling beside it. Two cards, one missing fact and one
missing question.

**The missing fact: a damage event carried its `source` and never its seat.**
Every payload has held `source` since there were payloads, and reading it works
right up until the source is a spell — at which point what the damage paths hold
is the spell's `CardDefinition`, which is *the card as printed*. One object per
card, shared by every copy in every deck in the process, controlled by nobody.
So "a source **you** control" was not unimplemented, it was unanswerable, and
the two cards that print it had been sitting behind that since M21 was ingested.

`damage_source_seat` answers it in three, most specific first: the control seam
for a permanent (so a stolen creature's damage is the thief's, CR 613 layer 2);
`base_controller_index` for a permanent that has *left*, which is the case of a
source sacrificed to pay for its own ability; and otherwise the seat whose spell
or ability is resolving. The third is not a fallback — CR 109.5 says a spell's
"you" is its controller — and it is the only one that needed anything new:
`Game.resolving_seats`, pushed around `_execute_oracle_instruction`. **That is
the one dispatch point**, the same seam round 54 used to hand a where-clause's X
to every effect family at once, and the alternative was threading a seat through
45 damage call sites, which is idiom 3 exactly: a list of sites is only ever as
complete as the last card that touched one. The seat is derived *inside*
`deal_damage` for the same reason.

**Fiery Emancipation is a multiplier, and a multiplier has an order.** It sits
at 700, after every prevention shield (10–600), and that is a rules decision
rather than a numbering one: CR 616.1e gives the order to the affected player,
and a shield spent first absorbs from the printed damage where a shield spent
after absorbs from three times as much. "Prevent the next 3" against a tripled 3
is 0 dealt one way round and 6 the other. The default should not be the one that
costs the player six life. Flipping the constant fails the test that pins it.

**Two Emancipations are ×9, and one interceptor has to say so.** An effect
applies once per event (`engine/effect_ordering.py` drops the chosen candidate),
so an interceptor returning a flat ×3 would silently ignore the second copy. It
counts the sources and returns `3 ** n` instead — which is exact rather than
approximate, because every copy is the same effect at the same order, so
applying them together *is* the sequence the default choice produces.

**The missing question: the support gate asked six text-keyed tables and not the
seventh.** `_derived_static_claims` asks untap restrictions, land plays, global
statics, draw-step bonuses, cost modifiers and entry effects — every table that
reads a permanent's own text at the step that needs it and therefore needs no
instruction. The CR 614 registry is exactly that shape and was not on the list,
so a permanent whose *only* ability is a replacement effect produced nothing,
claimed nothing, and reported unsupported however well the interceptor ran. The
gap had no card behind it because every replacement in the shipped pool prints a
second readable line — Lich, Ali from Cairo, Library of Leng and Conclave Mentor
all do — and Fiery Emancipation prints one line and nothing else.

The phrase table moved from `engine/grammar/registries.py` to
`engine/replacements.py` with it. One reader could keep its list beside itself;
two cannot, and a drifted copy claims a line nothing implements — which is the
silence the whole registry module exists to remove. The guard is parametrized
over the table rather than over a list of cards, so an interceptor added without
a claim behind it fails on the day it is written.

**Chandra's Pyreling needed only the question.** Its effect half — "gets +1/+0
and gains double strike until end of turn" — already parsed and lowered; what
was missing was the trigger condition, which landed on both sides of the
pipeline (round 7's lesson) and became one more row in `_SEAT_SCOPED_EVENTS`,
the set of events whose whole narrowing is the word "you". The seat it carries
is the **source's** controller and not the damaged player's, which is what the
"an opponent burns you" control test pins. "Noncombat" needed no flag at all:
the fire site is `_deal_damage_to_player`, and the combat damage step reaches
players by its own path because it applies prevention where the event is
recorded — so noncombat is a property of *where* the announcement lives.

Chandra's Incinerator prints the same trigger and stays unsupported, correctly:
its cost line is the `{X}`-self-reduction that has been a deliberate refusal
since round 25, and reading an unrecognized condition as satisfied makes a spell
cheaper than it is.

Suite **5,084** at 21.5s, every `--check` green, shipped pool 388/388, AI
simulation byte-identical at 443 interactions. M21's parsed share moved 68.6% →
70.2%. Four of the eight new card tests were watched to fail on the round-56
engine, and the two new engine test files do not import against it; the rest are
controls — an opponent's spell, combat damage, and the shield ordering.

**Next:**

- **Teferi's Ageless Insight**, the last of round 53's three. "If you would draw
  a card except the first one you draw in each of your draw steps, draw two cards
  instead" now has a support claim waiting for it, and wants two things:
  `_draw_with_replacements` honouring a `count` a replacement *modified* (the
  symmetry `place_plus1_counters` already has, and its absence is why a
  modifying draw replacement could not be written), and the draw step's first
  draw being distinguishable from the rest.
- **The Shrine cycle**, unchanged: Fruitful Harvest's colour choice at a
  trigger's resolution, Shattered Heights' discard cost from the hand-activation
  block, Tranquil Light's per-Shrine cost reduction, Sanctum of All's two-zone
  search and trigger-doubling static.
- **Experimental Overload's variable-P/T token and Jolrael's team base-P/T**,
  then the legend rule from round 49.

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
