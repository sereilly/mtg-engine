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
2. **The suite stays fast.** ~6,360 tests at a steady 35s, against a CI budget
   of 60s. The budget catches a step change; the *baseline* recorded beside it
   in `ci.yml` is what catches creep, and it is the number to keep honest — it
   went 9s → 17s across four phases with the gate green the whole way. Raising
   the budget is a decision, not maintenance.

   The baseline has moved twice as a *record* of growth rather than permission
   for it: 17 → 23 when ~130 tests landed in one session (permanent ids, the
   grammar layering guards, two renumbering regression suites), and 23 → 35
   when the Commander/Brawl variant and the pre-set cleanup round took the
   suite from 4,454 tests to ~6,360 — proportional growth, no step change.
   The second move put the suite *at* the old 35s budget, so the budget was
   raised 35 → 60 as a decision (2026-08-19, ahead of the next set ingestion):
   the next set's tests need somewhere to land, and the cliff detector stays
   well above honest growth.

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
- **An AI seat never casts its commander** (the Commander variant's known
  deferral). `ai_policy.py` and `ai_valuation.py` read the hand and the
  battlefield; nothing reads `command_zone`, so an AI commander sits there for
  the whole game and Commander-vs-AI is a handicap match. The CR 903.9 zone
  prompt already defaults safely for AI seats — this is a missing *policy*, not
  a rules gap. Wants the same shape as every other AI read: derived from the
  compiled program in `ai_valuation.py`, weight tuning in `ai_policy.py`.

### Recorded, measured, and not yet fixed

- **The Nine Lives class — partial implementation reported as full.** A card is
  supported when **any** line is, so a card can report supported while other
  lines produce nothing. The census this bullet asked for exists now:
  `scripts/support_report.py --hollow-lines` names every supported card whose
  compiled program carries an ability with no instruction behind it. Its first
  run held **four cards** (Creature Bond, Howling Mine, Paralyze, Capture
  Sphere), each leaning on a registry the compiler cannot see — and each
  verified *live* by a per-card test in `tests/sets/`, so the pool's known
  members are all honest today. Rock Hydra's automatic counter shield — the
  one the bullet below used to call "the Nine Lives class hiding behind a
  verified-sounding acknowledgement" — is implemented
  (`prevention.py:_remove_counter_per_damage`) rather than acknowledged, and
  its `IMPLEMENTED_ELSEWHERE` entry is gone. What the census cannot see is a
  *registry that claims a line and does less than it says*: that class is only
  findable the Rock Hydra way, by giving the behaviour a game. Run the census
  in every Phase 2, on the measured set.
- **Fabled Passage** is hollow and stays supported: a land with no mana ability
  whose only ability is unreadable, kept by the separate "a land is always at
  least playable" rule in the compiler. That rule is right for a land that taps
  for mana and wrong for one that does not, and overturning it is a decision
  with its own reasoning to write down.
- **The verification tracker holds 299 unrecorded cards** — 280 of M21,
  promoted before its in-game pass (SET_PLAYBOOK Phase 5 owns that delta and
  promotion deliberately did not gate on it), plus the 19 Revised added; ten of
  the 299 read `equivalent` off a passing peer. Rounds 46–47 checked the
  Revised nineteen behaviour by behaviour and fixed three real bugs in them,
  but a headless sweep is not a manual in-game pass and
  `card_verification.json` records what a human checked. A generated artifact
  that is stale does not read as stale; it reads as an answer. (This bullet
  itself said "19 untested" for a week after M21 shipped — the same failure one
  layer up.)

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

## Round 140: the last two acknowledged gaps, and the trigger nobody could fire

*(2026-08-18.)* `parse_coverage.py`'s `ACKNOWLEDGED` is **empty of NOT
IMPLEMENTED entries**. Round 139 closed two of four; these are the other two,
and closing them surfaced a third gap that neither of them named.

**Mana Vault** — "At the beginning of your draw step, if this artifact is
tapped, it deals 1 damage to you." Two halves were missing and each was silent
in its own way. The draw step had *no trigger dispatch at all*: it drew a card
and opened priority, so any draw-step trigger the compiler produced sat in the
program unfired. And "if this artifact is tapped" had no production — the
condition parser held `it is untapped` / `this is untapped` as two written-out
phrases, so the *negated* reading worked and the plain one did not. A gate
nothing can fail is the same silence as no gate at all, which is why both
directions are now one production over the two axes the pool varies: how the
card names itself (`accept_source_reference`) and which way round the state is
asked.

`draw_step_self` joins `draw_step_each` in both trigger tables, the same pair
the upkeep and end steps carry, and `phases/draw_step.py` gained the scan those
two steps already had — keyed on the *condition*, not on a list of instruction
kinds, and checking CR 603.4's intervening-if as the trigger would fire.

**Armageddon Clock came with it, whether or not it was asked.** Its draw-step
damage was a regex over the permanent's oracle text living inside
`phases/draw_step.py`, dealt inline before the turn-based draw — so the moment
`draw_step_self` existed, the Clock's line compiled as a trigger too and the
choice was a second reader or a migration. It is a trigger now: "damage equal to
the number of doom counters on it" is `ast.CountersOnSource`, lowered to one
payload key the way "equal to its power" already is, and read at *resolution*
through `named_counters.py` — the store round 139 unified. The regex is gone,
and with it the last oracle-text scan in a turn step.

The migration found a hole underneath. "…to each player" was listed among the
damage recipients the handler takes off the resolution context, where for "each
player" there is no seat — the damage went to whatever `context.target` held.
No card in the pool printed the phrase until this one, so it had never been
dealt through. It is a recipient of its own now, the same shape `each_opponent`
takes and differing only in who is in the list.

**Nine Lives** — "If a source would deal damage to you, prevent that damage and
put an incarnation counter on this enchantment." Recorded as needing a CR 614
interceptor that also places a counter; it is a CR 615 *prevention* instead, and
that is the whole reason the shape was missing. Every shield in
`engine/prevention.py` was one a recipient had been **given** — something
resolved, armed it, and it is spent. This is the other kind: a static ability
that applies while its source is on the battlefield, with no charges, no
lifetime and nothing for the sweeps to clear. One registration, read off the
card's own text at damage time, with the counter's word as payload so a second
card printing it needs no code.

It runs **last** in the shared CR 616.1 order, after the consumable shields.
Any order is legal (616.1e) and this is the default a non-interactive seat
takes: reaching nine counters loses the game, so the counter should only be
spent on damage nothing else stopped — and a shield that covers the event
outright leaves this one unasked.

`prevention_claims_line` joins `replacement_claims_line` at both readers, the
grammar's parse claim and the support gate. Nine Lives printed three other
lines so it reported supported anyway; a card whose whole text is one prevention
would have reported unsupported while working perfectly, which is the same hole
round 113 closed one table over.

**The third gap, which neither entry named.** `leaves_battlefield` had **no fire
site anywhere in the engine**. It parsed on both sides of the pipeline, Nine
Lives compiled a real `player_loses_game` under it, and nothing announced it.
Nothing reached the gap while the prevention was unimplemented — the enchantment
never left the battlefield — so closing one acknowledged gap turned a card that
did nothing into a card that was *stronger than printed*: nine free preventions
with the downside missing. That is the direction the M21 promotion note calls
the harder failure to see, arrived at by fixing something.

It is announced from `remove_from_battlefield`, the one transition out, for the
reason the exile-return beside it is: the other forty callers would forget it.

`tests/engine/test_trigger_dispatchers.py` should have caught it and did not.
The guard asks whether a condition's name appears anywhere in `engine/` outside
the tables that *declare* it, and `leaves_battlefield`'s only other mention was
`return ast.TriggerEvent("leaves_battlefield", "when")` in the grammar — a
declaration written as code rather than as a table row, so the condition
satisfied the guard with its own parser. Those calls are excluded now; with the
tightening and without the fire site, the guard names Nine Lives.

Whole-pool diff: **no card changed support status**, three changed what they do.
Suite green, every `--check` gate green, pool 668/668, AI simulation
byte-identical at 443 interactions, **no hook added and none removed** (13.9% of
supported cards name-keyed, 14.8 entries per 100). Grammar parses 80.0% → 80.3%
of lines and executes 46.4% → 46.7%. Fourteen new tests, eight of them watched
to fail on the round-139 engine; the other six are the controls that must pass
on both. The tightened dispatcher guard is the ninth, and it names Nine Lives.

**`ACKNOWLEDGED` still holds two entries, and both are simplifications rather
than gaps**: Shahrazad's subgame (the life clause *is* implemented) and Word of
Command's control-of-player (modelled as forcing the chosen card to be played).
Neither is a card doing less than it prints without saying so.
