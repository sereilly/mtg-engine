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

---

## Antiquities: ingest and census (Phase 1)

*(2026-08-21.)* The set journal for ATQ, opened per `SET_PLAYBOOK.md`. Ingested
at 85 unique cards (100 printings), registered under `measured`.

**Phase 0 was a no-op except for one stale tracker** — `RULES_PROGRESS.md` sat
one test behind (1357 → 1358, rule coverage unchanged at 302/611). Committed on
its own so it could not be read as an ATQ diff.

**The ingest broke nothing.** M21's ingest surfaced 66 failures from a
never-run import; ATQ's surfaced zero, and nine previously-skipped tests began
running. That is a real difference between the two sets rather than luck: ATQ
introduces no card type, no layout, no keyword and no vocabulary the engine has
not already met.

**Census.** 48/85 supported (56.5%); 120 rules lines, 46.7% parsed, 45.0%
lowered, 27.5% executed, against a shipped-pool 80.7/79.5/46.7. The shipped
floors and ceilings did not move, which is the `measured` role working as
designed.

**The three big rocks are all absent.** Every card is `layout: normal`; the
types are Artifact / Artifact Creature / Creature / Enchantment / Aura /
Instant / Sorcery / Land. The keyword lines are banding, defender, first strike,
flying, trample and vigilance — every one already in
`vocabulary.IMPLEMENTED_KEYWORDS`. `data/vocabulary/` already carries `urza's`,
`mine`, `power-plant` and `tower` as land types and `book` as an artifact type.
So there is no subsystem project gating Phase 4, which is what makes this set
cheap at the top and long in the tail: the work is almost entirely grammar
productions over one recurring theme.

**19 of the 85 are already shipped through Revised** (Atog, Ornithopter, The
Rack, Millstone, Crumble, Shatterstorm, Ivory Tower, Primal Clay, Energy Flux,
Titania's Song, Hurkyl's Recall, Reverse Polarity, Reconstruction, Armageddon
Clock, Dragon Engine, Dwarven Weaponsmith, Mishra's War Machine, Onulet, Rocket
Launcher). Net new cards: **66**.

### The census overstates support, and the guards cannot see it

`support_report.py --set ATQ` reports `land: 6/6 supported`. All six are wrong
in the same direction, and two more cards join them:

| Card | Reported as | Actually does |
| --- | --- | --- |
| Urza's Mine / Power Plant / Tower | `basic land support` | taps for `{C}` off `produced_mana`; **never assembles** |
| Mishra's Workshop | `basic land support` | taps for **one** `{C}` instead of three, restriction unenforced |
| Mishra's Factory | `basic land support` | mana and pump real; **cannot animate** |
| Artifact Possession | `pattern-supported effect` | zero abilities compiled — enchants an artifact and does nothing |

(Bronze Tablet was listed here on first reading and does not belong: it prints
a third line, "This artifact enters tapped", which `enter_effects` implements.
Its ante exchange is unreadable, so it is a *degraded* card like Mishra's
Factory and Battering Ram, not a hollow one. Round 1 records the correction.)

Two separate blind spots, and the point is that they are separate — this is
not one guard with one hole:

1. `engine/oracle.py`'s land gate passes **every** land. The comment there
   states the intended rule correctly ("an unparsed *bonus* ability degrades
   just that ability, never the land's own castability") and the code does not
   implement the distinction, so a land whose unreadable line *is* its mana
   ability is indistinguishable from Desert.
2. `test_no_hollow_support.py::_hollow_permanents` filters to
   `primary_type in ("artifact", "enchantment")` — lands were never in scope.
3. `engine/auras.py`'s effect table claimed **any** `when(ever)
   enchanted|equipped …` line with a `.+` wildcard, naming "trigger_utils /
   upkeep_effects" as the implementer without asking either of them.

This is the M21 lesson — the census counts cards, not sentences — arriving one
layer further down: not "a supported card has an unsupported line" but "the
gate that decides support cannot ask the question". Round 1 therefore fixes the
**gates** before any card work, and is expected to *lower* the supported count.

### Round plan

Ranked by cards-per-change, generalise-first:

1. **Honesty** — close the three hollow-support blind spots above.
2. **Artifact-matter noun phrases** — `artifact creature(s)`, `artifact
   source(s)`, `an artifact spell`, `noncreature artifact`, `nonartifact
   creature`, `artifacts your opponents control`. The set's spine; ~15 cards.
3. **`enters with <N> <kind> counters`** — collapse two literal strings in
   `enter_effects.py` into one pattern (Triskelion, Tetravus, Clockwork Avian).
4. **Assembly mana + restricted mana** — the Urza's cycle as one production;
   Mishra's Workshop is one row in `restricted_mana.py`.
5. **Prevention keyed on a source class** — colour-keyed shields generalised
   (6 cards).
6. **"for as long as this permanent remains tapped"** — promotes Old Man of the
   Sea's hook to a production; 3 cards and hook reliance falls.
7. **Becomes an artifact creature with CDA P/T** — 4 cards.
8. **Artifact-spell-cast / artifact-dies triggers** — narrowings of two existing
   rows; 4 cards.
9. **The ability-activated trigger** — the one genuinely new dispatcher.
10. Counting and chosen numbers; cost *reduction* (Power Artifact); ante
    exchange (Bronze Tablet); exile-with-noted-counters (Tawnos's Coffin, to be
    landed against the standing exiled-with linkage block); then the long tail.

**Placement decision, recorded now because it is load-bearing at promotion.**
ATQ's entry goes into `sets` at **index 4, between ARN and 3ED** — not appended.
The manifest describes itself as printing-ordered, `SET_PROGRESS.md` already
credits ATQ with 85 new cards and 3ED with 0, and Golgothian Sylex *requires*
it: it sacrifices "each nontoken permanent with a name originally printed in
the Antiquities expansion", read through `CardDefinition.original_printing` —
the seam City in a Bottle already uses. Appending after M21 would leave those 19
shared cards reading `3ed` and the Sylex would miss every one of them. Expect
19 cards to flip `set_code`, `printings[0]`, art and Scryfall link at promotion;
`test_appending_a_set_never_changes_an_existing_original_printing` compares
prefixes of the new ordering and stays green.

## ATQ round 1: the gates that could not ask the question

*(2026-08-21.)* No card gained support this round. **48 → 43**, and the five
that left are the round's whole point: each reported supported while nothing in
the engine carried out a word of what it prints.

**The land gate.** `engine/oracle.py` passed every land, with a comment
explaining a distinction the code did not draw — "an unparsed *bonus* ability
degrades just that ability, never the land's own castability". That is exactly
right about Desert's damage ping, and it had never been separated from the case
where the unreadable line *is* the whole card. Antiquities is where the two came
apart: Urza's Mine, Power Plant and Tower each print one line, none of them
parsed, and all three reported supported while tapping for the flat `{C}` that
`produced_mana` records — the assembly they exist for could never happen.
Mishra's Workshop is the one that hides best, because nothing about it looks
broken: it taps for one `{C}` where the card prints three, and spends it on
anything.

The gate now asks the same question the artifact half already asked — a
permanent that prints abilities and can read *none* of them is unsupported,
naming the clause. **Mishra's Factory deliberately keeps its support**: it taps
for mana and pumps an Assembly-Worker, and only its self-animation is unread.
That is a card doing less than it prints, which the coverage instruments report
and this gate is not for. It is the control in
`test_a_land_with_one_readable_ability_is_not_hollow`, chosen over a
comfortably-passing card precisely because it sits on the boundary.

**The Aura wildcard, which is round 140's shape again.** `engine/auras.py`'s
effect table claimed any `when(ever) enchanted|equipped …` line with `.+`, and
its claim string named "trigger_utils / upkeep_effects" without asking either.
Matching the shape of a trigger is not evidence that one fires. Artifact
Possession is what it cost: its entire effect is one trigger nothing reads, the
wildcard claimed the line, the gate found nothing unclaimed, and the Aura
entered play and did nothing.

The fix is an *asked* claim (`attached_trigger_claim`), and the three shipped
cards resting on the wildcard are why it could not simply be deleted — all
three work, by three different mechanisms. It asks for a compiled trigger
(Psychic Venom, Malefic Scythe), for a `card_hooks` entry (Kudzu), and for the
additional-mana-on-tap clause (Wild Growth). Deliberately **not** "…and the
trigger produced an instruction": Creature Bond compiles its condition with no
instruction at all, because `mixins/effects.py` builds the effect from the dead
creature's toughness at trigger time, and requiring one would have withdrawn a
card that works.

**Wild Growth's pattern moved to where both readers can see it.** It was a
regex inside `tap_land_for_mana` alone, so the support gate had no way to ask
whether the line was implemented — which is *why* the wildcard existed. It is
`auras.aura_additional_mana_on_tap` now, one pattern with two readers: the
dispatcher that adds the mana and the claim that decides the card is supported.

**Two test fixtures were asserting the bug.** An invented "Land Aura" printed
"…its controller adds {G}" — a wording no card uses and the dispatcher's regex
never matched. Both tests passed on the wildcard while the Aura added no mana.
They print Wild Growth's real wording now. This is the M21 round-16 lesson
arriving from the other direction: there a spec's diagnosis was a hypothesis
until measured, here a *fixture's* text was.

**What did not move.** The shipped pool is 668/668, the suite is green (6579
passed), and every `--check` gate passes untouched — no floor lowered, no
ceiling raised. One line moved in `PARSE_COVERAGE.md` from "auras.py (attached
effect)" to "card_hooks bespoke (name-keyed)": that is Kudzu, always carried by
a name-keyed hook and until now credited to the general reader. The number got
worse and the accounting got true, which is the right direction for a ratchet
that exists to measure honesty.

**One correction to the census above**, recorded rather than quietly edited:
Bronze Tablet was listed as a third blind spot and is not one. It prints a
third line — "This artifact enters tapped" — that `enter_effects` implements,
so it is degraded (its ante exchange is unreadable, round 12's job) rather than
hollow. Found by reading the card's lines instead of the two the census report
happened to quote, which is the same failure mode Phase 1 warns about for
reason strings.

## ATQ round 2: the Urza's cycle, and the land mana path that never ran

*(2026-08-21.)* **43 → 47.** The four cards round 1 withdrew are back, this
time doing what they print. Five changes, in dependency order with the grammar
last, so the cards stayed honestly unsupported at every intermediate commit.

**A conjunction of subtypes is not a union of them.** "Urza's Mine" is two land
types, not a name (CR 205.3i): `urza's` and `mine`. The noun parser collected
subtypes into one list with OR semantics — right for "Djinn or Efreet", and it
would have let a single Urza's Mine satisfy "an Urza's Power-Plant **and** an
Urza's Tower", assembling the whole cycle off one land. `ObjectFilter` already
drew exactly this distinction for card types (`type_match`), so subtypes got
the symmetric `subtype_match` and a `subtype_filter_all` payload key AND'd by
both matchers. The demonstrating row in `test_subject_filters.py` is Grizzly
Bears against `["bear", "wall"]` — a card an OR would *accept* on the first
alternative, which is what makes the row a demonstration rather than a second
copy of the `subtype_filter` row above it.

**A latent mis-parse found on the way.** The lexer splits a possessive, so
"Urza's" arrives as `urza` + `'s` and the land type `urza's` could never match.
That was not a silent miss but a silent *wrong* match: `Urza` alone is a
**planeswalker** type, so "an Urza's Mine" was reading as "an Urza planeswalker"
and leaving `'s mine` behind. `_match_subtype` re-joins the possessive, and only
when the joined form is itself in the vocabulary — so "that artifact's
controller" is untouched, `artifact's` being no subtype. It is in the parser
and not the lexer on purpose: the lexer is vocabulary-free by design, and
"is this word a subtype" only has an answer in the noun position.

**Two shapes of "and", one node.** "If you control an Urza's Mine and an Urza's
Tower" shares one player and one verb and repeats only the noun, so the
shared-verb form is desugared into the same conjunction the clause-level "and"
builds. It refuses to widen a negated, counted or shared-name clause, where the
qualifier would have to be distributed over each conjunct and no card in the
pool says which reading was meant. The node is `EveryOf`, not `AllOf` — that
name is taken by the *quantity* meaning "all damage", and two senses of "all"
in a flat re-export is how a conjunction of conditions ends up standing in for
an unbounded amount. (Found by 104 collection errors, which is the flat
re-export doing its job.)

**The rider was one type wide.** `_parse_conditional_instead_rider` folded
"…, X instead" into a `Conditional` only for `GainLife`. `AddMana` joins it, and
the same-kind check tightened from "is a GainLife" to "is the same type as what
it replaces", so widening the set cannot let one kind stand in for another.

**And the finding that was not on the plan: the land mana path never ran a
land's compiled ability.** `tap_land_for_mana` added exactly one symbol chosen
from `produced_mana` — Scryfall's summary of *which* symbols a land can make,
which says nothing about how many or under what condition. For every land in
the pool until now that was indistinguishable from correct: the base sets, the
duals, the Temples and the gain-lands all produce exactly one mana. Antiquities
brought the first four that do not, and the compiled ability was right while
the dispatcher ignored it. So Mishra's Workshop would have paid one {C} even
after `restricted_mana.py` learned its clause — the round would have reported a
card supported and still had it playing wrong, which is round 1's lesson
arriving on the dispatch side.

The land path now runs the compiled ability when there is one and keeps
`produced_mana` as the fallback for a basic, whose whole ability line is CR
305.6 reminder text and compiles to nothing. The colour is injected the way the
activation path delivers it, so "tap Badlands for {R}" means what it did.
`_is_free_beyond_tapping` compares the cost against a default rather than
listing the fields that must be empty — a list would silently start ignoring
any cost component added later, and ignoring a cost component here means
activating an ability without paying for it.

**Numbers.** ATQ 43 → 47 supported; grammar parses 46.7% → 50.0% of its lines,
executes 27.5% → 30.8%, cards executing 29 → 33. Shipped pool 668/668 and every
shipped floor and ceiling unmoved; suite green at 6587 passed. No hook added.

## ATQ round 3: two artifact triggers, and a narrowing nothing produced

*(2026-08-21.)* **47 → 50.** Citanul Druid, Urza's Chalice and Tablet of
Epityr. Every *effect* half already worked — "you may pay {1}. If you do, you
gain 1 life." compiles today — so all three were blocked purely on their
trigger conditions, which is the cheapest shape a card can be blocked in.

**"Casts an artifact spell" was two table rows and a dead branch.**
`events._spell_cast_filter` already read a `card_type` narrowing off the
condition payload — and **no pattern in the compiler ever emitted that key**. A
dispatcher reading a narrowing nothing produces is round 1's shape with the
halves swapped: harmless while dead, and a second opinion about what "an
artifact spell" means the moment it is not. The new rows emit `cast_type`, the
name `you_cast_spell`'s rows already used, and all three cast kinds now ask one
helper (`_cast_narrowing_admits`) instead of each growing its own type test.
`_opponent_cast_filter` had no type narrowing at all and now asks the same one.

**A general "put into a graveyard" trigger, announced at the one seam.**
`land_dies` was the only death condition with a printed-noun form, and it is
specific — Dingus Egg's own event with its own damage shape. `permanent_dies`
is the general reading, its subject a filter payload like every other narrowed
condition, and it is ordered *after* the land row in both front ends so the
specific reading keeps its line. Its dispatcher hangs off
`_permanent_to_graveyard`, the seam every path to a graveyard already goes
through, rather than off the several places a permanent can die — the rule
CLAUDE.md states for a draw, a life gain or a sacrifice, applied to a death.
The narrowing is asked with the **observer's** seat, so "an artifact **you
control**" means the controller of the triggered ability (CR 109.5) and not the
controller of the dying permanent; that is the assertion
`test_tablet_of_epityr_ignores_an_opponents_artifact` exists for.

**What the grammar side cost, and the lesson in it.** Adding the oracle row
alone left both cards compiling a condition with `instruction=None` — the
condition was recognised and the *effect* never lowered, because the grammar is
a second front end and had not been taught the phrase. Twice in this round the
first placement was wrong: the subject-led death production went before the
phrase table and had to move after it, which is the file's own documented
ordering (the table holds the specific readings). Placed first it would have
claimed Dingus Egg's line as a generic death and quietly stopped that card
working — a widened gate taking a working card with it, which is exactly what
Phase 3's "grep for readers keyed on the old classification" is about.

**Urza's Miter did not land, and is not a near miss.** Its clause is "…**if it
wasn't sacrificed**, you may pay {3}" — a CR 603.4 intervening-if about *how*
the permanent died, which needs a record no path keeps today. Left unsupported
naming the clause rather than admitted with the qualifier dropped: an artifact
sacrificed to its own cost would otherwise draw a card the printed card
refuses.

**Numbers.** ATQ 47 → 50; grammar parses 50.0% → 52.5% of its lines, executes
30.8% → 33.3%, cards executing 33 → 36. Shipped pool 668/668, every floor and
ceiling unmoved, suite green at 6597. No hook added. One guard fired and was
right: `test_every_pattern_has_an_example` wanted a canonical text for the new
kind.

## ATQ round 4: three ways to say "artifact", and one filter key that was owed

*(2026-08-21.)* **50 → 53.** Argivian Blacksmith, Argothian Treefolk and
Argothian Pixies. The round is really one observation: Antiquities keeps naming
a *class of object* where the engine had only ever been asked about a single
type, and the answer is the same each time — make the noun phrase payload, and
ask the one matcher.

**`type_filter_all` was a debt from round 2 and cost one card.** The grammar has
drawn "artifact **creature**" apart from "artifact, creature, **or** land"
since `ObjectFilter` had a `type_match` field: it emitted `type_filter_all` and
lowering refused the line, because nothing answered it. Round 2 added the
symmetric key for subtypes and left this one; Argivian Blacksmith needed
nothing else. Both matchers answer it now and `test_subject_filters.py`
demonstrates it in both directions — the rejection row is Grizzly Bears, which a
union would *accept* on the "creature" alternative.

**A source class is a shield narrowing.** `_source_matches` already narrowed by
the chosen source (CR 615.8) and by colour (the Circles); "by artifact sources"
is the same question with a different property, so it is one text table, one
predicate and one interceptor in the `SOURCE_TYPE_BLANKET` band — beside the
other blankets, because it has no charges and applying it costs its recipient
nothing. `source_has_type` asks a Permanent through the layer system, so an
*animated* artifact land is an artifact source; reading its printed line would
have said otherwise.

**One block restriction became one rule.** `combat_restrictions.py` held
`cant_be_blocked_by_walls` — a whole kind for one noun — and the blockers step
tested it with a literal `has_type("wall")`. The noun is payload now, so
Argothian Pixies and Artifact Ward's blocking line cost a table row rather than
a branch, and the enforcement site asks `subject_matches` (which reads layer 4,
so Primal Clay's Wall body and an animated artifact both answer correctly).

Two things this widening had to get right, and one of them was caught by a
guard rather than by me. The bare-plural pattern reads any noun ("by walls"),
which is what keeps it from needing a 350-entry alternation — but a word the
vocabulary has never heard of would build a filter matching nothing, the
restriction would go **inert**, and the creature would be blockable by anything.
That is the widening direction, so the line refuses and its card is reported
unsupported. And `test_grammar_derived_lines` failed on the rename, naming
`cant_be_blocked_by_walls` in its unclaimed-kinds set — Phase 3's "grep for
readers keyed on the old classification", working as a guard instead of as a
grep.

**Numbers.** ATQ 50 → 53. Shipped pool 668/668, every floor and ceiling
unmoved, suite green at 6603. No hook added. Circle of Protection: Artifacts and
Rakalite are still out — both are *activated* prevention with riders (a chosen
source of a class; a delayed self-return), not the static shield this round
built.
