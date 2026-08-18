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

## Round 116: a tribe is not a card type, and a count is a count

*(2026-08-18.)* M21 **265 → 266** — Rin and Seri, Inseparable.

> Whenever you cast a Dog spell, create a 1/1 green Cat creature token.
> Whenever you cast a Cat spell, create a 1/1 white Dog creature token.
> {R}{G}{W}, {T}: Rin and Seri deals damage to any target equal to the number
> of Dogs you control. You gain life equal to the number of Cats you control.

**The cast trigger narrowed by card type and refused a subtype on purpose.**
Its word list was exactly what the event filter tested against the type line, so
the comment beside it said a subtype word "must keep refusing rather than
compile and fire on every spell" — a refusal recorded as a known limit rather
than left to be discovered. Both front ends carried the same list and the same
note. Lifting it meant teaching the filter first: the subtype is read through
the printed-subtype reader the layer seed uses, not searched for in the type
line, so a tribe cannot answer for a longer word and a card type cannot answer
a tribe. The vocabulary supplies the words, so a set adding a tribe needs
`fetch_vocabulary.py` and nothing here.

**Counted damage was one card wearing a general shape.** "Deals damage equal to
the number of …" had exactly one lowering — Karma's, fused down to a kind whose
handler damages the player whose upkeep is resolving. Everything needed for the
general form was already there: `count_spec` describes the noun phrase,
`x_from_count` carries it, and the instruction executor resolves it into
`x_value` before any handler runs. So the general case is `deal_damage` with a
counted amount, and Karma's kind stays because its *recipient* is not something
this shape can express.

The life gain took the same route, and that is the point of routing it there:
the ability counts **Dogs** for its damage and **Cats** for its life in one
sentence pair, so the two steps carry two specs and the executor resolves each
against its own instruction. A second counter with its own spelling of the spec
is exactly the drift `count_spec` exists to prevent.

Rin and Seri is a Dog **Cat**, so it answers both counts — which is the check
worth writing down, because a tribal count that read the type line as a whole
would have found it once and a matcher asking for a single subtype would have
missed it entirely.

Whole-pool diff: **one card**. Suite green, every `--check` gate green, shipped
pool 388/388, AI simulation byte-identical at 443 interactions, **zero hooks
added**. Seven new tests, six watched to fail on the round-115 engine; the
seventh states the printed-subtype reader's contract, which the new filter asks
and which predates it.

## Round 117: three sentences, one pile

*(2026-08-18.)* M21 **266 → 267** — Transmogrify.

> Exile target creature. That creature's controller reveals cards from the top
> of their library until they reveal a creature card. That player puts that card
> onto the battlefield, then shuffles the rest into their library.

The exile already worked. The rest is **one procedure written as three
sentences**, and it is lowered as one instruction for a reason that is not
convenience: "that card" names what the reveal stopped on and "the rest" names
exactly the cards it turned over first, so split apart the last two sentences
would dangle referents into a pile nothing had recorded. Every word of both
destinations is required by the production — a card that milled the rest instead
of shuffling it back is a different card, and the difference does not appear
until the third sentence.

**"That creature's controller" is a back-reference, and it demands its
producer.** The seat is the one the *exile* step recorded, which is the same
channel "its controller creates a token" (Angelic Ascension, Secure the Scene)
already reads. Without an exile in front of it the phrase names nobody, so the
lowering refuses — reading the caster instead would aim the whole effect at the
opposite player from the one the card names, and the card would still report
supported.

**A library with no match is not an error.** CR 701.20a's reveal is bounded by
the library: an empty one ends the search, the player reveals everything, puts
nothing onto the battlefield and shuffles it all back. Any other reading is an
infinite loop on a real board, and this is a card an opponent can aim at a
library they have seen.

The creature enters through the ordinary seam with `from_zone="library"` and
`was_cast` false, so it is a permanent put onto the battlefield rather than
cast — which round 111's Containment Priest asks about and round 115's origin
stamp records.

Whole-pool diff: **one card**. Suite green, every `--check` gate green, shipped
pool 388/388, AI simulation byte-identical at 443 interactions, **zero hooks
added**. Four new tests, all watched to fail on the round-116 engine.

## Round 118: a token as big as a graveyard, and a spell that exiles itself

*(2026-08-18.)* M21 **267 → 268** — Experimental Overload.

> Create an X/X blue and red Weird creature token, where X is the number of
> instant and sorcery cards in your graveyard. Then you may return an instant or
> sorcery card from your graveyard to your hand. Exile Experimental Overload.

Three sentences, three small gaps — and the third had been fixed three rounds
earlier without the card noticing.

**An X/X token.** `CreateToken` stored printed integers and the refusal beside
it said so, which was true when it was written and had quietly stopped being the
only option: the where-clause machinery stamps its count onto the instruction
and the executor resolves it into the context's X *before any handler runs*, so
the payload says "x" and the handler reads a number, exactly as a pump or a
counted damage does. Both halves must be the **same** variable — "X/Y" is two
counts and the clause defines one, so admitting it would give the token a
toughness nothing stated.

Taken at resolution and then fixed onto the token's card. A token has no
characteristic-defining ability, so a card later leaving the graveyard does not
shrink it; and Experimental Overload is still resolving while the count is
taken, which is why it does not count itself (CR 608.2n bins it last).

**A chosen card that is not a target.** "Return **an** instant or sorcery card
from your graveyard" resolved nowhere: every graveyard return the engine had was
targeted. Admitted in exactly the shape where the distinction cannot matter —
the chooser's own graveyard — because there is nothing for targeting to protect
there: no shroud, no protection, no "changes target" effect can reach a card in
your own graveyard, and the picker is the one the targeted spelling already
uses. A bare quantifier over anyone else's zone still refuses.

**A spell exiling itself.** Round 115 gave "exile it" a handler, and that
handler exiles the ability's *source permanent* — of which a sorcery has none.
So the words compiled, the handler ran, and it exiled nothing. The object here is
the spell on the stack, which makes this CR 608.2n's "where the card goes"
rather than a zone change of something in play, and it routes through the same
flag the "if that spell would be put into your graveyard, exile it instead"
rider uses. Set rather than performed: the card is still resolving, and the
resolution tail is the one place that bins it.

Whole-pool diff: **one card**. Suite green, every `--check` gate green, shipped
pool 388/388, AI simulation byte-identical at 443 interactions, **zero hooks
added**. Six new tests, all watched to fail on the round-117 engine; one guard
that recorded the old token refusal was rewritten to state what replaced it and
what still refuses.
