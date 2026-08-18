# Scaling Roadmap

Target: grow the card pool from 388 unique cards (LEA/LEB/2ED/ARN/3ED shipped,
M21 measured at 246/285) to the full release line - **137 sets, 33,594
printings, 26,113 unique cards** per `set_progress.json`.

A chronological engineering journal, kept to the last three rounds. Everything
before them — the founding audit, the parser migration (finished:
`engine/parsing/` is deleted and `engine/grammar/` is the only parser), the
per-set narratives, and M21 rounds 1–93 — lives in git history at and before
commit `05642fa`. What those rounds established that outlives their narrative is
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

## Round 94: half a characteristic, and a count that is the answer to a prompt

*(2026-08-17.)* M21 **243 → 244** — Kinetic Augur, closing the batch.

> Kinetic Augur's power is equal to the number of instant and sorcery cards in
> your graveyard.
> When this creature enters, discard up to two cards, then draw that many cards.

**The CDA table had only ever seen whole P/Ts.** Every entry reads "power **and
toughness are each** equal to", and the apply site wrote `set_base_pt(perm,
value, value)`. Kinetic Augur is */4: it defines *half* a P/T, and the printed
toughness stands. Which half it defines rides on the payload rather than in the
kind — a card printed the other way round is the same template — and
`set_base_pt` already took `None` for "leave this one tracking whatever else
applies", so there was nothing to build, only something to stop assuming.

**And it counts cards in a zone**, which the CDA tally cannot: a card in a
graveyard has no computed characteristics at all (CR 613.1), so it is a different
question of a different matcher. The payload carries the same `count_spec` every
other computed amount uses and goes through `evaluate_count` — the evaluator the
computed 7c bonus two lines below was already using, so "the number of instant
and sorcery cards in your graveyard" means one number whichever sentence prints
it.

**"Then draw that many" is one instruction because the second number is the
answer to the first.** How many are drawn is however many the player chose to
discard, and that choice is a *pending prompt* — so decomposed, the draw would
run while the prompt was still owed and draw nothing at all, with the card
reporting supported. `_fused_discard_then_draw` is the mirror of the
draw-then-discard fuser beside it and is fused for the opposite reason: that one
because no controller-discard handler existed, this one because the pair cannot
be separated in time.

The follow-on rides the *prompt* rather than the resolution, which is the
arrangement Library of Leng's `to_library` already uses: what happens when a
discard is answered belongs to the discard.

**"Up to" is a ceiling, not a count.** The discard prompt has always demanded its
exact number; a ceiling read as an exact count is a card that forces its
controller to pitch cards they were offered the choice of keeping. One flag makes
fewer legal — none included — and a prompt without it is unchanged, which a test
pins in both directions.

Whole-pool diff: **one card, one line**. Suite green, every `--check` gate green,
shipped pool 388/388, AI simulation byte-identical at 443 interactions, **zero
hooks added**. Ten new tests, seven watched to fail on the round-93 engine.

## Round 95: how much any-colour mana is data

*(2026-08-17.)* M21 **244 → 245** — Sanctum of Fruitful Harvest, and a card hook
retired.

> At the beginning of your first main phase, add X mana of any one color, where X
> is the number of Shrines you control.

**The whole card was one number.** Everything else compiled. "Add X mana of any
one color" refused because `add_mana_from_text`'s any-colour path is
`_add_mana_from_text` **probing the clause text** for the literal phrase "one
mana of any color" — it recognizes one mana and no other count, so any other
number lowered onto it would have added nothing while reporting success. That is
why the refusal was written rather than a guess, and round 54's "an X nothing
reads" guard is what found it before a card did.

The count travels on the payload now. It is an `Amount`, so a printed digit, an
X, and an X *defined by a where-clause* are the same instruction with different
data — and the where-clause resolves through `count_from_payload`, the one
evaluator every computed amount in the engine shares. "Any **one** color" stays
one choice for the whole clause: the count multiplies a single symbol rather than
asking again per mana.

**Black Lotus was the card that had been paying for the old shape.** "{T},
Sacrifice this artifact: Add three mana of any one color" kept a name-keyed
`sacrifice_self_for_mana` hook for exactly as long as "three" had nowhere to go.
The sacrifice is an ordinary activation cost and the mana an ordinary
instruction, so the decomposition is the card as printed — and the guards said so
before the ROADMAP did: `test_card_lines` failed on the entry as *dead* the
moment the number could travel. **The hook is deleted**, and both ratchets
tightened onto the improvement: hooked cards 24.2% → **24.0%**, entries per 100
supported 26.0 → **25.8**, executed lines 41.6% → **41.8%**.

The clause text still rides along, and that is not a leftover: `activation.py`
injects the chosen colour by keying on the `any_color` payload flag, and the AI's
mana valuation reads the number — which now comes off the payload, with 1 as the
honest floor for a count that is an X the valuation cannot have.

Whole-pool diff: **one card, one line**. Suite green, every `--check` gate green,
shipped pool 388/388, AI simulation byte-identical at 443 interactions, **one
hook removed**. Seven new tests, six watched to fail on the round-94 engine;
three tests that asserted the old refusals were rewritten to state what replaced
them.

## Round 96: a sweep over what something is attached to

*(2026-08-17.)* M21 **245 → 246** — Turn to Slag.

> Turn to Slag deals 5 damage to target creature. Destroy all Equipment attached
> to that creature.

**The damage already worked.** The second sentence needed two things: a sweep
that takes a *filter* rather than a card type, and a way to say what the
Equipment is attached to.

`destroy_all_matching` is the first; the per-scope kinds beside it each name one
scope ("all creatures", "all lands of a type"), and a narrowed set has no scope to
name. It is gated on `object_only_filter`, so a phrase the matcher cannot test
refuses rather than sweeping wider than the card says.

**The attachment rides beside the filter, not in it.** What an Equipment is
attached to is a *relation*, and `permanent_matches_filter` answers about a
permanent alone — so the handler resolves it, the same split the `controls`
condition already makes for "another". Only the referents the table names are
admitted: an attachment clause whose object nothing can resolve would be dropped
and the sweep would take every Equipment on the board.

**The interesting case is the one the intuitive reading gets wrong.** "That
creature" is the spell's own target, and after 5 damage it is usually dead — so
the natural expectation is that its Equipment survives, unattached. It does not.
CR 704.3 checks state-based actions only when a player would receive priority, so
the lethally damaged creature is *still on the battlefield* while the rest of the
spell resolves, still wearing its Equipment. Both die, in that order. I wrote the
test the intuitive way first and the engine disagreed; the engine was right, and
the case is pinned because that is exactly the reading a later edit would
"fix" the wrong way.

Whole-pool diff: **one card, one line**. Suite green, every `--check` gate green,
shipped pool 388/388, AI simulation byte-identical at 443 interactions, **zero
hooks added**. Five new tests, three watched to fail on the round-95 engine.
