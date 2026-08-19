# Scaling Roadmap

Target: grow the card pool from 668 unique cards (LEA/LEB/2ED/ARN/3ED/M21, all
shipped and all supported) to the full release line - **137 sets, 33,594
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
  eleven legendary creatures in the pool are M21, **which now ships** — so this
  is reachable in a real game rather than hypothetical, and it is the oldest
  open block. A ratchet on `card.name` needs its own census first: hundreds of
  reads are log lines.
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

## Round 137: three triggers that compiled and did nothing

*(2026-08-18.)* The three cards round 136's second rehearsal named. Same shape
as that round's three, one level up: the permanent support gate is any-of for
**triggered** abilities too, so a working line hid a dead one.

**Teferi's Tutelage** — "Whenever you draw a card, **target opponent** mills two
cards." The handler already milled `context.target`; the lowering refused the
recipient. What "opponent" changes is which seats the picker may offer
(CR 115.4), and that rides on the targets description every other
opponent-targeted effect already carries — read as a plain target player, the
caster could have milled themselves.

**Riddleform** — "…you may have this enchantment become a 3/3 Sphinx creature
with flying **in addition to its other types** until end of turn." Three layers
off one record: the creature type and the Sphinx subtype are layer 4, the flying
is layer 6, the P/T goes through `engine/pt.py`. The record *is* the effect, so
cleanup sweeping it is the whole of ending it — nothing stashed, nothing
restored. Both printed clauses are required by the production: "in addition to
its other types" is the difference between animating the permanent and replacing
what it is, and "until end of turn" is the difference between this and a
permanent animation.

The keyword half taught its own lesson. Written into the *type* collector it did
nothing at all, because `computed_abilities` reads the layer-6 collector — a
grant recorded in the wrong collector is a grant nothing sees, and the comment
beside it now says so.

**Alpine Houndmaster** — "search your library for a card named Alpine Watchdog
**and/or** a card named Igneous Cur". One find per printed name, each optional,
which is what "and/or" says. The union is what the *picker* offers; the name a
find used is dropped, so a library holding two Watchdogs cannot answer both
finds with them and never reach the Cur — which is what the test puts on the
board.

Whole-pool diff: **no card changed support status**, and exactly three changed
what their abilities do. Suite green, every `--check` gate green, shipped pool
388/388, AI simulation byte-identical at 443 interactions, **zero hooks added**.
Six new tests, all six watched to fail on the round-136 engine.

**M21 still does not promote, and the blocker is now one thing.** The dead-ability
scan is clean for M21 — the only entry left is Capture Sphere, whose "When this
Aura enters, tap enchanted creature" is carried out by the Aura entry path
exactly as its shipped LEA twin Paralyze is, and both were driven to confirm it.
What remains is a **printed restriction nobody enforces**: "Activate only if a
creature died this turn" (Caged Zombie), "…only if you control a creature with
flying" (Celestial Enforcer), "…only if you have at least 7 life more than your
starting life total and only as a sorcery" (Speaker of the Heavens). Driving
Caged Zombie with no creature dead activates the ability and drains two life.

That is not a dead ability — it is an ability that works *more often than the
card allows* — and it wants the twin of `engine/cast_restrictions.py`: a
text-keyed activation-restriction table, read by `mixins/stack/activation.py`,
which today hard-codes two LEA phrases. Thirteen further parse-coverage
sentences are attribution gaps rather than behaviour gaps (delayed triggers,
modal trigger heads, equip, Nine Lives' replacement, three statics) and want
channels, not code.

## Round 138: the restriction nobody enforced, and M21 ships

*(2026-08-18.)* The last blocker, and the promotion. **M21 moves from `measured`
to `sets`: 668 cards, all supported.**

`mixins/stack/activation.py` gated activations with a hand-written if-chain,
each branch a substring test against the ability line. Eight LEA phrases were
listed. Everything else printed with the words was **unenforced** — Caged
Zombie's "Activate only if a creature died this turn" drained two life on an
empty graveyard, and the card reported supported the whole time, because an
unenforced restriction is not a dead ability. It is an ability that works more
often than the card allows: nothing crashes, nothing is missing, the game is
just wrong in the player's favour. That is the harder failure to see, and the
reason this one survived five sets.

`engine/activation_restrictions.py` is the twin of `cast_restrictions.py`: one
declaration per printed clause, matched **whole** so a rule for a shorter phrase
cannot satisfy a longer one, read by the activation path *and* by the support
gate. The eight existing phrases moved into it, so the chain is gone rather than
joined. Twelve clauses, one reader.

Two details the pool insisted on. Armageddon Clock prints its clause as the tail
of a conjunction ("Any player may activate this ability **but** only during any
upkeep step"), so the sentence splitter reads the tail and leaves the permission
to the rule that owns it. Rocket Launcher's "controlled continuously since the
beginning of your most recent turn" already had a route through the compiled
payload, so its entry calls the same `_controlled_since_turn_start` rather than
inventing a second answer.

**The promotion itself.** Every guard the wider catalog turns on is green; the
numbers moved the way a modern set should move them —

| | before | after |
| --- | --- | --- |
| grammar parses | 78.1% | **80.0%** |
| grammar executes | 42.2% | **46.4%** |
| hooked share of supported cards | 24.0% | **13.9%** |
| hook entries per 100 supported | 25.8 | **15.0** |

Hook reliance nearly halving is the headline: M21 is 285 cards the grammar reads
almost entirely, so the *marginal cost per card* — the number that decides
whether this reaches 26,113 — fell by a third of its value on one set.

Three lines are recorded in `parse_coverage.py`'s `ACKNOWLEDGED` as **not
implemented**, each with what it costs: Chromatic Orrery's "spend mana as though
it were mana of any color", Malefic Scythe's counter-accumulating trigger, and
Nine Lives' counter-placing prevention (open since round 127). All three fail in
the direction that makes the card *weaker* than printed, which is why they are
acknowledged rather than blocking — and they are named in the report so they
cannot be mistaken for coverage.

In-game verification is deliberately not a promotion gate (SET_PLAYBOOK.md
Phase 5): 369 of 668 cards pass, 10 more are `equivalent`, and the rest are
M21's, owed a Debug-Menu pass.

## Round 139: two of the four acknowledged gaps, closed

*(2026-08-18.)* `parse_coverage.py`'s `ACKNOWLEDGED` held four lines marked
**NOT IMPLEMENTED** — visible rather than hidden, which is what that dict is
for, but still four cards doing less than they print. Two are fixed here.

**Chromatic Orrery** — "You may spend mana as though it were mana of any color."
The engine had one spend-as permission and it was one colour pair wide
(`can_spend_white_as_red`). With the general one, every unit in the pool pays a
coloured pip — the Orrery's own five {C} are the point of the card — while a
{C} in a *cost* still wants colourless, because colourless is not a colour
(CR 105.1). Handled before the per-colour cascade rather than threaded through
it: with the permission those five checks are one check about a total, and
threading is how the narrow permission ended up appearing in five places.

**Malefic Scythe** — three lines, and the middle one was quietly wrong.
"Equipped creature gets +1/+1 **for each** soul counter" was read by the flat
P/T-grant pattern, which matches this line's *prefix*, so the Scythe was a
permanent +1/+1 whose counters did nothing. It has its own reader now, declared
ahead of the flat one. "Whenever equipped creature dies" is a scope no seat
comparison can express — the observer is what the dead creature was carrying —
and it shares one condition kind with an Aura's "when enchanted creature dies",
because the two attach the same way here.

**One store for a CR 122.1 counter, not two.** `named_counters.py` (round 127)
kept a dict; Armageddon Clock's doom counters and Cyclone's wind counters had
been `metadata["<word>_counters"]` since long before. Two stores for one concept
is how a card puts counters somewhere nothing reads — which is exactly what
happened the moment the grammar learned this sentence: the placement went to one
store and the Scythe's own P/T grant looked in the other. The module now uses
the older spelling, and two entries that existed only to route around the gap
are gone: Armageddon Clock's card hook, and the `upkeep_put_counter_on_self`
registry handler. The Clock takes the ordinary on-the-stack route now.

Creature Bond's reader moved with it: `_trigger_aura_death_effects` matched the
generic `dies` condition because that was the only kind the table produced for
the phrase, and "when enchanted creature dies" was never the Aura's own death.

Whole-pool diff: **no card changed support status**; two changed what they do,
and Armageddon Clock changed how it gets there. Suite green, every `--check`
gate green, pool 668/668, AI simulation byte-identical at 443 interactions,
**one hook removed and none added** (14.8 entries per 100 supported, down from
15.0). Five new tests, three watched to fail on the round-138 engine; the other
two are the without-the-permission controls.

**Two gaps remain, both still acknowledged.** Mana Vault's "at the beginning of
your draw step, if this artifact is tapped, it deals 1 damage to you" needs a
draw-step trigger condition scoped to a single permanent — the table has only
`draw_step_each`. Nine Lives' "if a source would deal damage to you, prevent
that damage and put an incarnation counter on this enchantment" needs a CR 614
interceptor that *also places a counter*, which `engine/replacements.py` has no
shape for. Both fail in the direction that makes the card weaker than printed.
