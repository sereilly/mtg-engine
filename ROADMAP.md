# Scaling Roadmap

Target: grow the card pool from 388 unique cards (LEA/LEB/2ED/ARN/3ED shipped,
M21 measured at 224/285) to the full release line - **137 sets, 33,594
printings, 26,113 unique cards** per `set_progress.json`.

A chronological engineering journal, kept to the last three rounds. Everything
before them — the founding audit, the parser migration (finished:
`engine/parsing/` is deleted and `engine/grammar/` is the only parser), the
per-set narratives, and M21 rounds 1–67 — lives in git history at and before
commit `40e81df`. What those rounds established that outlives their narrative is
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

## Round 68: a counter on a permanent the controller chooses

*(2026-08-16.)* M21 **221 â†’ 222** â€” Liliana's Scrounger, whose one sentence the
grammar had already read in full. What refused was the lowering, and what the
round actually cost was a fourth thing nobody had listed.

> At the beginning of each end step, if a creature died this turn, you may put a
> loyalty counter on a Liliana planeswalker you control.

**The restriction was lifted, not deleted.** "Loyalty counters only land on the
ability's own source" was true of every card in the pool until this one:
`_is_source` still routes to `add_loyalty_counters`, and a non-source noun phrase
now gets `add_loyalty_counters_to_chosen` beside it. One write function under
both, because there is now more than one way a loyalty counter arrives and CR
306.5c makes it the key damage and loyalty costs read.

**"Liliana" is a planeswalker subtype and never a card name** â€”
`planeswalker_types.json` â†’ `PLANESWALKER_TYPES` â†’ `SUBTYPE_INDEX` â†’
`subtype_filter`, with the `named` key absent. All three payload keys were
already in `TESTABLE_SUBJECT_FILTER_KEYS`, so the card needed no vocabulary work
and no new filter. That mattered: had it compiled to a name match it would have
been dispatch on a card name outside `card_hooks.py`.

**No "target" is printed, so nothing is chosen when the ability goes on the
stack** (CR 115.1b). The controller picks at resolution out of what the phrase
names *then* â€” the `untap_up_to` shape, not the targeted one. Reading it as a
target would move the choice to announcement and let the ability do nothing on
resolution when the walker it named has left, where the printed card simply picks
another. One candidate is applied inline, none does nothing, several arm a
`loyalty_recipient` prompt: one `register_choice`, one renderer, one AI default,
no new `Game` field. The default is a stated policy â€” **fewest loyalty counters,
ties by scan order** â€” because loyalty is a planeswalker's life total and
CR 704.5i bins one at zero.

**The fourth thing, which was the actual work.** `engine/oracle.py` collapsed
"the"/"each"/"your" end step into one condition kind, and the CR 603.4 scan this
card lands in is scoped to the *active player*. So without splitting the
condition (`end_step_self`, mirroring `upkeep_self`/`combat_your_turn`) the card
would have compiled supported and **never fired on an opponent's end step** â€”
the same silent-wrongness shape as round 67, arrived at from the other side. Eight
cards move to the new kind with no behaviour change. Two guards had to follow the
split or quietly stop covering things: `test_trigger_tables.py` fails loudly,
`test_grammar_lowering.py` fails *silently*, dropping Erg Raiders â€” the only
shipped card with a "your end step" trigger.

**And a rule about the payload gate that is worth keeping.**
`TESTABLE_SUBJECT_FILTER_KEYS` alone is **not sufficient**, because
`ObjectFilter.to_payload` does not emit `zone`, `is_enchanted`, `supertypes` or
`colored` at all â€” so "a planeswalker card **in your graveyard**" reduces to the
same payload as the plain phrase and would have compiled a graveyard clause into
a battlefield picker. The gate has to be the payload keys *paired with*
`_restrictions_beyond` over the AST. That is now three refusal tests.

**The size guard again, one round after last time.** The block landed
`test_m21_creatures.py` at 2,692 against a 2,600 cap. Every assertion in it reads
a *planeswalker's* loyalty â€” the Scrounger is only the source of the counter â€” so
it lives in `test_m21_planeswalkers.py`, which keeps loyalty behaviour in one
place. Worth recording plainly: **M21 has 149 creatures and the printed-type axis
is nearly exhausted**, so the next round that adds creature tests has to split the
file for real rather than find it another home.

Suite green, every `--check` gate green, shipped pool 388/388, AI simulation
byte-identical at 443 interactions, **zero hooks added**. Nine of the thirteen new
tests were watched to fail on the round-67 engine; the four that pass vacuously
are the negative controls, which earn their keep only now the card works.

**Next:**

- The counter-removal activation cost from round 66's *Next*, still open and
  still a free ability.
- "Another" as a source exclusion (round 65), the headless simulator's discarded
  permanent target (round 65), the Shrine cycle, a static P/T contribution with a
  computed X, a reflexive trigger, the legend rule.
- Split `tests/sets/test_m21_creatures.py`.

## Round 69: several cards in a graveyard, where a slot is all there is

*(2026-08-16.)* M21 **222 â†’ 223** â€” Sanguine Indulgence. Its cost-reduction line
turned out to be the *finished* half, and the round is about what a target means
in a zone that has no identities in it.

**"Up to two target creature cards from your graveyard."** Every earlier "up to
N" in this engine names *permanents*, which carry a `permanent_id`. Round 65
added `resolve_target_slots` for exactly the positional hazard â€” a resolver that
compacts hands slot 1's card to slot 0 the moment the first target leaves â€” and
the obvious move was to reuse it. It does not apply, and the reason is the
interesting part: **in a graveyard there is no identity to resolve to.**
`load_cards` dedupes by `oracle_id`, so two copies of one card are literally one
`CardDefinition` â€” `gy[0] is gy[1]` is True. Neither an id nor `is` can tell two
slots apart.

What can is **order**. Each slot is resolved to its card before anything leaves
the zone, and the removals then run **highest index first**, because popping slot
0 slides every later card down one. Ascending removal on `[A, B, C]` with slots
`[0, 1]` returns `{A, C}` â€” the graveyard spelling of the bug the battlefield
resolver exists for. A repeated slot collapses to one card, which is CR 601.2c:
one instance of "target" cannot name the same object twice.

**The second blocker was one this round created for itself.** Reusing
`_describe_several_targets` fails, because round 68 hardened `_filter_payload` to
refuse any card- or non-battlefield-scoped filter â€” the gate that stops a
graveyard clause compiling into a battlefield picker. That gate is right, so the
several-*card* case gets its own describer rather than a hole in the gate.

**Zero targets is a legal cast** (CR 601.2c: the caster announces *how many*, and
none is one of the answers), so an empty graveyard must not refuse the spell â€”
where a spell requiring its one target could not be cast at all. That is one
line in the cast-legality check and one in the browser prompt, and it is the
difference between "up to two" and "two".

**The cost reduction was measured, not assumed**, because the ROADMAP records
uncomputable cost reductions as a deliberate refusal and "cheaper is the one
direction a cost error must never go". `_SELF_CONDITIONS` already maps "you've
gained 3 or more life this turn"; measured, 0 and 2 life gained give no
reduction, 3 and 5 give `{3}` exactly, and under the patch one black mana casts
the card after three life gained and fails before it. Not claimed-but-unapplied,
not unconditional. Gates are all-of and both halves hold.

Suite green, every `--check` gate green, shipped pool 388/388, AI simulation
byte-identical at 443 interactions, **zero hooks added**. Nineteen new tests, all
nineteen watched to fail on the round-68 engine. CR 115.2 and 601.2 gain a test
each.

**Next â€” and the first of these is the largest thing this session found:**

- **A graveyard target is a slot on the stack and it goes stale, live in the
  shipped pool.** Named Grizzly Bears in a graveyard, let one card leave in
  response, and Raise Dead returns **Hill Giant**. The same shape reaches
  Regrowth, Reconstruction, Resurrection, Rise Again, Animate Dead, Fungal
  Rebirth, Shipwreck Dowser and Liliana, Death Mage. It is currently unreachable
  in the shipped pool only because Timetwister is the sole card that disturbs a
  graveyard and it is a sorcery â€” **M21 makes it reachable**, through Return to
  Nature (an instant) and Scavenging Ooze. This wants its own round and it has to
  precede promotion.
- **Read the Tides' second mode is engine-correct and unreachable in the
  browser**: `_mode_target_kind` has no entry for `bounce_target_creature` and
  defaults to `"player"`, so the API serves two player seats as its valid targets
  and the cast logs "No creatures to return".
- **Fungal Rebirth returns an instant.** "target **permanent** card" parses with
  `card_types=()` â€” "permanent" is a generic noun recording no restriction â€” so
  it reduces to the same payload as "target card". Measured: the picker offered
  Lightning Bolt and the cast returned it.
- **`scripts/parse_coverage.py` reads `manifest_set_paths()` without
  `include_measured`**, so its deletion probe is blind to M21 â€” which is why the
  dropped "permanent" above was never flagged.

## Round 70: a trigger on the activation, not on what it resolves into

*(2026-08-16.)* M21 **223 â†’ 224** â€” Keral Keep Disciples. The effect half was
already finished; the whole round is the trigger, and the most valuable edit in
it is not the card's.

> Whenever you activate a loyalty ability of a Chandra planeswalker, this
> creature deals 1 damage to each opponent.

**A trigger subject was dropping any restriction the payload has no key for, and
that is a bug this round found rather than a feature it needed.**
`ObjectFilter.to_payload` emits nothing for `supertypes`, `is_enchanted` or
`blocked` â€” so "a **legendary** creature you control" reduced to *exactly* the
payload of "a creature you control", and the `TESTABLE_SUBJECT_FILTER_KEYS` gate
downstream saw a clean, unnarrowed filter, because what was missing left no key
behind. Measured on the round-69 engine: an invented "Whenever a legendary
creature you control attacks, you gain 1 life" compiled **supported**, and a
plain Dog attacking alone took its controller to 21. Round 68 found the same hole
one layer down and paired the payload gate with `_restrictions_beyond` over the
AST; this is that pairing on the trigger side, where the consequence is a
condition announcing itself on a strictly larger set than the card prints. The
honoured set is *derived* from the fields `to_payload` reads, so a restriction
added to `ObjectFilter` later refuses instead of silently vanishing.

**One condition, two narrowings, failing in opposite directions.** The *actor* is
CR 109.5's "you" â€” drop it and an opponent ticking up their own Chandra pings
them on your behalf. The *object* is a printed noun phrase â€” drop it and every
planeswalker in the format is a Chandra. Neither existing table can express both:
`event_filter` raises on duplicate registration, so a kind can be seat-scoped
**or** subject-led, never both, and the three subject-led events carry their whole
narrowing inside the noun phrase where this card's "you" sits outside it. One
predicate, because there is one card; a second one makes the pair a row.

**"Chandra" is a subtype and never a card name** â€” four cards in this pool alone
are called Chandra-something, and a name match would have been dispatch on a card
name outside `card_hooks.py`. The regex only delimits the phrase; the noun parser
reads it, and both front ends produce a byte-identical filter, which the existing
whole-pool guard checks with no new test needed.

**The fire site is CR 606.4's payment**, and its position is load-bearing in two
directions. Below the legality gate, because that gate returns early and
announcing above it would fire the trigger on activations the rules refused â€”
tested for both CR 606.3 (one loyalty ability per turn) and CR 606.6 (a minus
larger than the loyalty). And while the walker is still on the battlefield, so a
minus that bins it (CR 704.5i) is still something the trigger saw. CR 603.3's
ordering is *not* settled by the fire site: this engine pays costs before it
pushes, so `queue_permanent_ability`'s existing `deferring_triggers` wrapper is
what puts the trigger above the ability. Asserted off the stack, not the log.

**The size guard, third round running â€” and this time it was a real split.**
`test_m21_creatures.py` went 2,550 â†’ 2,315 by five moves, three of them
misfilings the split turned up: Garruk's Uprising (an Enchantment), two artifact
creatures, a per-turn record naming an Instant, and a grammar probe naming no
card. The rest is a new `test_m21_legendary_creatures.py` â€” `Legendary` is part
of the printed type line (CR 205.4a), M21 prints eleven and only four are
supported, so seven future rounds land there rather than back in the file that
just overflowed, and the standing "legend rule reads the printed name" work
(round 49) has a home when it is done.

Suite green, every `--check` gate green, shipped pool 388/388, AI simulation
byte-identical at 443 interactions, **zero hooks added**. Eight of the eleven new
tests were watched to fail on the round-69 engine; the three that pass are
controls that earn their keep only now the card works.

**Next:**

- **The graveyard-slot staleness from round 69** â€” still the largest open item,
  and it must precede promotion.
- **A planeswalker with a non-loyalty activated ability cannot compile at all**,
  so this round's `is_loyalty` narrowing has no representable counter-example in
  the pool. Said in the test docstring rather than pretended away.
- **`mana_like_kinds` does not exclude loyalty abilities** (CR 605.1a) â€” latent,
  nothing in the pool reaches it.
- **Every triggered `deal_damage` in the pool reports
  `effect_kind="spell_pattern"`**, so `is_triggered` is false on the wire for all
  21 of them. Carried vocabulary from the parser migration, deliberately not
  touched here.
- **`tests/sets/test_lea_cards.py` is at 2,598 of 2,600** â€” the next LEA test of
  any kind trips the guard with two lines of warning.
- Round 66's counter-removal cost, round 65's "another"-as-source-exclusion and
  the headless simulator's discarded target, the Shrine cycle, a computed static
  P/T, a reflexive trigger, the legend rule.
