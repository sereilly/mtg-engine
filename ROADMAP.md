# Scaling Roadmap

Target: grow the card pool from 388 unique cards (LEA/LEB/2ED/ARN/3ED shipped,
M21 measured at 257/285) to the full release line - **137 sets, 33,594
printings, 26,113 unique cards** per `set_progress.json`.

A chronological engineering journal, kept to the last three rounds. Everything
before them — the founding audit, the parser migration (finished:
`engine/parsing/` is deleted and `engine/grammar/` is the only parser), the
per-set narratives, and M21 rounds 1–104 — lives in git history at and before
commit `57001f4`. What those rounds established that outlives their narrative is
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

## Round 128: the untap seam, eleven years late

*(2026-08-18.)* M21 **277 → 278** — Ghostly Pilferer.

> Whenever this creature becomes untapped, you may pay {2}. If you do, draw a card.
> Whenever an opponent casts a spell from anywhere other than their hand, draw a card.
> Discard a card: This creature can't be blocked this turn.

**`become_tapped` has existed since the round that found Lifetap firing on one
path out of seventeen. Its twin did not.** `perm.tapped = False` was written in
eleven places, so a "becomes untapped" trigger could only ever have seen
whichever one its implementer wired into — the untap step, probably, and not
Twiddle, not an untapper's own ability, not the nine other ways a permanent
untaps. Ghostly Pilferer is the first card in the pool to ask, so the seam came
first and the trigger second.

CR 701.26b gives the same two exclusions the tap seam records: re-untapping an
untapped permanent is no state change and no trigger, and a permanent that
*enters* untapped never becomes untapped — it was never tapped on the
battlefield.

**The condition kind is the event's name.** Naming it `self_becomes_untapped`
while the seam emitted `permanent_becomes_untapped` compiled a trigger that
collected nothing — the shape rounds 93, 105 and 119 each found a different way.
The identity check that makes it "**this** creature" is an event filter, so a
board of Pilferers does not all fire when one untaps.

**"From anywhere other than their hand" is a narrowing on the cast's zone**,
which the stack item has recorded since the cast-permission seam. It now rides
the cast event too; an event with no zone counts as a cast from the hand, which
is the ordinary case and the one that must not fire.

**"This creature can't be blocked this turn" is not a target.** Its own
instruction kind, the same split round 115's "exile it" makes — a handler that
resolves a target and one that reads `context.source_permanent` share nothing
beyond the flag they set — and a source already gone grants nothing rather than
falling back to a scan that would free some other creature.

Whole-pool diff: **one card**. Suite green, every `--check` gate green, shipped
pool 388/388, AI simulation byte-identical at 443 interactions, **zero hooks
added**. Six new tests, five watched to fail on the round-127 engine.

## Round 129: two events already announced, asked from the other side

*(2026-08-18.)* M21 **278 → 279** — Mangara, the Diplomat.

> Whenever an opponent attacks with creatures, if two or more of those creatures
> are attacking you and/or planeswalkers you control, draw a card.
> Whenever an opponent casts their second spell each turn, draw a card.

Both events were already announced — the attack declaration and the cast — and
both needed the *other* seat's version. Each gets its own condition kind rather
than a flag, because the fire sites differ in who is asked: the existing cast
ordinal is announced for the caster's own permanents, and this one for
everyone's.

**"Those creatures" binds the count to this declaration.** A board count of
attacking creatures would include another opponent's, so the number is computed
at the declaration and stamped into the trigger's context. CR 603.4 checks an
intervening-if when the trigger would fire *and* again on resolution, and both
readings want the number the declaration had — a recount at resolution asks
about a combat that may have moved on.

**"You and/or planeswalkers you control" is one question.** A creature attacking
a planeswalker is attacking its controller for this purpose, and the card says
so — so one lookup answers both halves, and the per-seat tally the declaration
carries is keyed by that answer.

**The ordinal counts, it does not flag.** "Their second spell" is `len(spells
cast this turn) == 2` with the firing spell already on the list; CR 121.2's
per-spell reading is what makes "their third" a different card and not this one.

Whole-pool diff: **one card**. Suite green, every `--check` gate green, shipped
pool 388/388, AI simulation byte-identical at 443 interactions, **zero hooks
added**. Five new tests, all watched to fail on the round-128 engine — the two
negative ones carry an in-test control.

## Round 130: a token that carries printed abilities

*(2026-08-18.)* M21 **279 → 280** — Pursued Whale, scoped out of round 108 and
finished here.

> When this creature enters, each opponent creates a 1/1 red Pirate creature
> token with "This token can't block" and "Creatures you control attack each
> combat if able."
> Spells your opponents cast that target this creature cost {3} more to cast.

**A token's abilities can be printed lines, not just keywords.** They are
carried as *text* and compiled when the token's card is built, so a token
ability works exactly as the same words on a printed card do — one reading of
one text. Gated at lowering: a line the compiler cannot read refuses the whole
card, because a token silently lacking an ability is precisely the shape the
support gate exists to stop.

Testing that gate needed a probe that builds a throwaway token and compiles it,
rather than asking `compile_line` — several abilities a token can carry are
implemented by *text-keyed registries* that produce no instruction at all, and
`compile_line` refuses those. The gate reads the same card the battlefield will.

**"This token can't block" is the same self-reference as "this creature."** Both
spellings are admitted rather than one normalized to the other, because the
normalizer would have to know which cards are tokens.

**"Creatures you control attack each combat if able" is a board-wide static**,
and the global-static table already had the shape: the ability is appended to
each affected permanent's effective card, so `combat_restrictions.py` reads it
as though the creature printed it and the declare-attackers step needs no code.
Its scope is *relative* — "you control" is a seat comparison (CR 109.5) — which
no read of the affected permanent alone can answer, so the predicate now takes
the source and refuses when handed neither.

That table also had the round-113 problem one file over: the **creature** static
gate never asked it, so a creature (or a token) printing a global static
reported unsupported while the effect worked. Two guards were widened with it.

**The mana tax is the twin of round 107's life tax**, sharing the scope and now
the target list, which is computed once at the cast and handed to both — the
same fact asked at CR 601.2f and again at 601.2h.

`parser.py` crossed 1,000 lines and split along the **rider** family: a sentence
that modifies the one before it. Every one of them reads a referent the previous
step bound, which is why they are driven by the sentence loop and why that loop
stays behind with the line-level productions.

Whole-pool diff: **one card**. Suite green, every `--check` gate green, shipped
pool 388/388, AI simulation byte-identical at 443 interactions, **zero hooks
added**. Five new tests, all watched to fail on the round-129 engine.
