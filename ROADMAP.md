# Scaling Roadmap

Target: grow the card pool from 734 unique cards (LEA/LEB/2ED/ARN/ATQ/3ED/M21,
all shipped and all supported) to the full release line - **137 sets, 33,594
printings, 26,113 unique cards** per `set_progress.json`.

A chronological engineering journal, kept to the last few rounds. Everything
before them — the founding audit, the parser migration (finished:
`engine/parsing/` is deleted and `engine/grammar/` is the only parser), the
per-set narratives, M21 rounds 1–140 and Antiquities rounds 1–27 — lives in git
history at and before commit `169be7e`. What those rounds established that
outlives their narrative is kept below under **Carried forward**. The process a
set follows is `SET_PLAYBOOK.md`.

---

## Standing invariants

Anything that weakens these is a regression regardless of what it enables:

1. **No silent wrongness.** A card may fail loudly as unsupported with a
   reason; it may never resolve as something other than what it says.
2. **The suite stays fast.** ~6,870 tests at a steady 40s locally, against a
   CI budget of 120s. The budget catches a step change; the *baseline* recorded beside it
   in `ci.yml` is what catches creep, and it is the number to keep honest — it
   went 9s → 17s across four phases with the gate green the whole way. Raising
   the budget is a decision, not maintenance.

   The baseline has moved three times as a *record* of growth rather than
   permission for it: 17 → 23 when ~130 tests landed in one session (permanent
   ids, the grammar layering guards, two renumbering regression suites), 23 → 35
   when the Commander/Brawl variant and the pre-set cleanup round took the
   suite from 4,454 tests to ~6,360, and 35 → 40 at Antiquities' promotion,
   which took it to ~6,845 — most of that not new tests at all but the
   pool-wide sweeps parametrizing over 85 more cards. Proportional growth every
   time, no step change.
   The second move put the suite *at* the old 35s budget, so the budget was
   raised 35 → 60 as a decision (2026-08-19, ahead of the next set ingestion):
   the next set's tests need somewhere to land, and the cliff detector stays
   well above honest growth. It went 60 → 120 two days later (2026-08-21) for
   a different reason — GitHub's runners take the same suite two to three
   times as long as a local run, so a budget tuned to local timings failed on
   the runner with nothing wrong; the local baseline of 40s is still the
   number that shows creep.

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

The parts of a round that are about the *next* card rather than about the round
that wrote them. Everything here was established by a round now in git history;
the round number is given so the reasoning can be read in full — plain numbers
are the M21-era rounds, `ATQ n` is Antiquities'.

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
  since, and still true at `game_ending.py:383`). CR 707.2 copies the name, so a
  Clone of Barrin is a second Barrin and CR 704.5j should bin one — it does not.
  Two reads are wrong, not one: `perm.card.name`, and the `Legendary` supertype,
  which `has_type` does not cover at all (round 48 exempted `game_ending.py` for
  exactly that). All eleven legendary creatures in the pool are M21, which
  ships — so this is reachable in a real game rather than hypothetical, and it
  is the oldest open block. A ratchet on `card.name` needs its own census first:
  hundreds of reads are log lines.
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
  findable the Rock Hydra way, by giving the behaviour a game. **The census is a
  Phase 3 exit criterion, not only a Phase 2 reading** — Antiquities read 85/85
  supported for thirty rounds with three cards in it (ATQ 30), and reaching zero
  took a round of its own.
- **The verification tracker holds ~335 unrecorded cards** of 734 — M21 and
  Antiquities, both promoted before their in-game pass (SET_PLAYBOOK Phase 5
  owns that delta and promotion deliberately does not gate on it); four read
  `equivalent` off a passing peer. A headless sweep is not a manual in-game
  pass, and `card_verification.json` records what a human checked — including
  a **failure**, which is a bug report with a card name on it. A generated
  artifact that is stale does not read as stale; it reads as an answer — this
  bullet itself said "19 untested" for a week after M21 shipped, which is why
  CI regenerates the tracker now, and why the count here is approximate on
  purpose: `CARD_VERIFICATION.md` is the number.

### Deliberate refusals, with their reasons

Not gaps to close on sight — each was measured and left refusing. This list
used to be three times as long; the pre-set cleanup round before the next
ingest found nine of its entries implemented (Pursued Whale's target
narrowing and the {X} self-reductions in `cost_modifiers.py`, Enthralling
Hold in `target_restrictions.py`, Runed Halo in `named_protection.py`, Feat of
Resistance as `PROTECTION_FROM_CHOSEN_COLOR`, Demonic Embrace in
`cast_costs.py`, Crypt Lurker as `may → choose_one`, Faith's Fetters and
Feline Sovereign in `auras.py` / `lord_buffs.py`) and still listed as
refusing. A refusal recorded here is a claim about the code; re-verify it
against `compile_line` before citing it.

- **El-Hajjâj's "you gain that much life"** is deliberately *not* a row in
  `_EVENT_QUANTITIES`: its fire site records the amount under a different key,
  so claiming its line would retire a hook onto a handler reading the wrong
  name.
- **Hexproof stays colour-only**, because its targeting branch reads colour
  words alone.
- **A durationless doubling** (a continuous effect the layers would have to own)
  and **doubling toughness** (a different effect — consuming the noun without
  checking it is how one card's production quietly claims another's).
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
   nothing off the battlefield touches, so it can be read at resolution. The
   longest gap between freezing and reading is Tawnos's Coffin's noted counters
   (ATQ 28) — a whole turn cycle, and what comes back is a new object (CR 400.7)
   with none of its own.
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
    the guard is the signal that a family stopped absorbing new work. Take the
    split *when it fires*: Antiquities' two (`nouns.py` → `references.py`,
    `statements.py` → `paragraphs.py`) each fell along a line the CR already
    draws — what a noun phrase describes against what it points at, a sentence
    against a paragraph — and that boundary is easiest to see while the work
    that crossed the line is still in hand.
14. **The same sentence about a different subject is the same table, asked with
    the subject rewritten.** Artifact Ward prints Argothian Pixies' combat
    restriction and Argothian Treefolk's damage shield about the creature it
    *enchants* (ATQ 22); Drafna's Restoration prints an ordinary graveyard
    return about a *chosen player's* pile (ATQ 27). Reuse costs a rewrite of the
    subject and nothing else — but it needs a gate naming the kinds a reader
    actually consults, or asking a table gets every row for free and claims
    lines nothing enforces.
15. **A card has every type its line names (CR 205.2).** `primary_type` picks
    one of them by the order of a list, and three readers asked it that way — a
    counter refused every artifact creature, a search could not find one, and
    only the graveyard reader was right (ATQ 25, 29). One
    `search_filters.card_has_type` now.
16. **A clause about a player says so in its payload.** The damage handler told
    a player from a permanent by looking for a permanent index on the resolution
    context — which in a `sequence` is the *previous* step's, so Detonate's
    "deals X damage to that artifact's controller" was aimed at the artifact it
    had just destroyed (ATQ 23). Inference from an absence is not a reading.
17. **A loop over a permanent's triggers must not stop at the first.** CR 603.3
    puts *every* ability that triggered on the stack; the upkeep step's `break`
    was correct until Tetravus printed two (ATQ 26). Same family as idiom 3, one
    control-flow keyword smaller.
18. **A guard whose control is a pool card stops controlling when the pool
    moves.** `test_no_hollow_support` proved "a land with *some* readable
    ability is not hollow" by asserting Mishra's Factory *had* an unread line —
    a fact about the pool, not about the guard, which would have started passing
    vacuously the day that line was implemented (ATQ 30). A fixture the test
    invents cannot go stale underneath it.

---

## ATQ round 28: the linked exile, and the second thing that ends one

*(2026-08-22.)* **83 → 84.** Tawnos's Coffin — four sentences that are one
effect:

```
{3}, {T}: Exile target creature and all Auras attached to it. Note the number
and kind of counters that were on that creature. When this artifact leaves the
battlefield or becomes untapped, return that exiled card to the battlefield
under its owner's control tapped with the noted number and kind of counters on
it. If you do, return the other exiled cards to the battlefield under their
owner's control attached to that permanent.
```

**The linked-exile seam was already built**, which the "open block" in *Carried
forward* undersells: `permanent.metadata["exiled_until_leaves"]` is the pile
Kitesail Freebooter and Idol of Endurance use, and `remove_from_battlefield` —
the one transition off the battlefield — is what empties it. What this card adds
is vocabulary the entries did not carry: a **destination** (the battlefield,
where the others go to a hand or a graveyard), a **state** to come back in
(tapped, with the noted counters) and a **relationship** between the returned
cards (the Auras go back onto the creature).

**And a second thing that ends a linked exile.** Every other card in the family
says "leaves the battlefield"; this one says "or becomes untapped", which is the
half it is actually played for. `become_untapped` is the one place a permanent
untaps — the round that wrote it says so, and that is exactly why the return
goes there rather than into the untap step: a return wired into one untapper
would be a return the other ten forgot.

**The counters are noted, not derived**, which is CR 608.2h's reason: by the
time the return runs the permanent has been gone for a turn cycle, and what
comes back is a new object (CR 400.7) with no counters at all. They go back
through `Game.place_plus1_counters` rather than the library operation under it —
a permanent that *enters with* counters has those counters put on it (CR 121.6),
so CR 614 may change how many arrive and CR 603 may fire on their arrival. The
counter-placement guard caught the shortcut before the test did.

**Four sentences, one production, one node.** The shape Necromentia and Idol of
Endurance already use, and for the same reason: none of the four is an effect on
its own. The note means nothing without the return that reads it, the return
means nothing without the exile that filled the pile, and the reattachment names
"that permanent" — the creature the sentence before it put back. A parse
producing four statements would produce three that do nothing. Every word is
required: without the Auras the creature comes back naked, without the counters
it comes back smaller, without "tapped" it comes back ready, and without either
half of the two-event return it never comes back at all.

**Numbers.** ATQ 83 → 84; grammar parses 83.3% → 84.2% of its lines, executes
55.8% → 56.7%. Shipped pool 668/668, floors and ceilings unmoved, suite green at
6700, no hook added.

## ATQ round 29: the last card, and one type question asked three ways

*(2026-08-22.)* **84 → 85. Every card in Antiquities is supported.** The last is
Transmute Artifact:

```
Sacrifice an artifact. If you do, search your library for an artifact card. If
that card's mana value is less than or equal to the sacrificed artifact's mana
value, put it onto the battlefield. If it's greater, you may pay {X}, where X is
the difference. If you do, put it onto the battlefield. If you don't, put it
into its owner's graveyard. Then shuffle.
```

**Three decisions in a row, each shaping the next** — what to give up, what to
look for, whether to pay the difference — and every one of them is machinery the
engine already had. The sacrifice is the standing forced-sacrifice prompt, the
search is the standing library search, and the payment is the ordinary
optional-pay entry whose accept and decline branches are the two placements the
card prints. Three things had to change for the chain to hold:

- **The sacrifice suspends.** "Sacrifice an artifact. **If you do**, search…" —
  what the player gives up decides what the rest of the resolution may find, so
  the rest waits. Only an interactive seat is affected: `default_at_arm` answers
  for everyone else *before* the flag is set, which is why headless and AI play
  are byte-identical.
- **The sacrifice records what it took.** By the time the comparison runs, the
  artifact is a card in a graveyard and a different object (CR 400.7), so its
  mana value is frozen as it happens — CR 608.2h's rule.
- **The search can *hold* its find.** Where the card goes is a later step's
  decision, so `destination: "held"` hands it over instead of placing it.

### Two bugs, and one of them was the same bug three times

**A declined optional payment dropped its branch.** The non-interactive default
applied a decline's consequence only when the entry carried the legacy `damage`
field, so a grammar-lowered "if you don't, …" branch never ran — Transmute
Artifact's found card vanished out of the game rather than going to a graveyard.
A decline is an answer, and an answer with a consequence has to have it applied.

**And CR 205.2 was being asked with `primary_type` in three places.** A card has
*every* type its line names, so Ornithopter is an artifact card and a creature
card; `primary_type` picks one of them by the order of a list, and it picks
"creature". Round 25 found the counter flow doing it (Goblin Artisans refused
every artifact creature in the set); this round found the *search* doing it
(Transmute Artifact could not find one either). The graveyard reader had it
right all along and said so in its docstring. There is one
`search_filters.card_has_type` now, and all three ask it.

### `statements.py` split: paragraphs.py

Antiquities' four-sentence cards took it past the thousand-line guard, and the
cut is the one the guard asks for: a **sentence** stays in `statements.py`, a
**paragraph** — several sentences that are only an effect together — moves to
`paragraphs.py`. Necromentia, Idol of Endurance, Tawnos's Coffin and Transmute
Artifact are the four, and none of them calls back into the sentence parser,
which is what lets the new module sit *below* `statements.py` in `PARSE_LAYERS`
rather than beside it.

**Numbers.** ATQ 84 → **85/85**; grammar parses 84.2% → 85.0% of its lines,
executes 56.7% → 57.5%. Shipped pool 668/668, floors and ceilings unmoved, suite
green at 6705, no hook added — **the whole set is implemented with zero
name-keyed entries added since the ingest**.

## ATQ round 30: three cards that reported supported and did less than they print

*(2026-08-22.)* **85 → 85, and the hollow-line census for ATQ goes to zero.**
No card gained support this round; three stopped lying. All three were on the
round-1 census as *degraded* — supported because some line of theirs was read,
with another line producing nothing — and `support_report.py --hollow-lines` has
named them ever since.

**Mishra's Factory could not animate.** `{1}: This land becomes a 2/2
Assembly-Worker **artifact** creature until end of turn. **It's still a land.**`
Two words the production had never met: a *card type* between the subtypes and
the head noun, and the second spelling of the addition clause. "It's still a
land" and "in addition to its other types" say the same rule — CR 205.1b, the
animation adds types rather than replacing them — in different places in the
sentence, so the production takes either and **requires one**: without it the
Factory would stop being a land, which is a permanent that no longer taps for
mana. The artifact type rides the same record the subtype does and is added by
the same layer-4 collector, because an animated Factory that is not an artifact
is a permanent Shatter cannot reach.

**Battering Ram's Wall lived.** `Whenever this creature becomes blocked by a
Wall, destroy that Wall at end of combat.` The trigger compiled, the fire site
existed and ran, and the effect clause lowered to nothing — "that **Wall**" is a
subtype, and the bound-object production read card types alone. Two changes and
one of them is the interesting one: the becomes-blocked fire site pushed the
**attacker** as the trigger's target, so a "destroy that Wall" rider would have
destroyed the Ram. The blocker is what the event bound, so the blocker is what
the stack item carries — by id as well as by slot, because a removal in between
renumbers every later one.

**Bronze Tablet's ante exchange was unread.** It gets a whole-paragraph
production in `paragraphs.py`, the family this set opened, and two small general
things fall out. `optional_pay` learned a **life** cost — "you may pay N life" is
a template with many printings and had none — and the prompt is armed on the
*victim's* seat rather than the activator's, which is the whole tension of the
card. CR 108.3 says ownership never changes; CR 407's ante rules are where the
exception lives, and this is one of the handful of cards that is it. The engine's
ownership is which player's zone a card sits in, so the exchange is the two exile
piles swapping — and paying moves **only** the Tablet, which is what makes 10
life a cost rather than a full undo.

**And a control that had quietly stopped controlling.** `test_no_hollow_support`
used Mishra's Factory to prove a land with *some* readable ability is not
reported hollow — an assertion that the card *had* an unread line, which is a
fact about the pool rather than about the guard. The day the animation landed it
would have started passing vacuously. The predicate is one function now, the
control is a land invented for the test, and a second test says where round 1
actually left the rule: a land whose only ability is unread never reaches this
guard, because the *support gate* refuses it first.

**Numbers.** ATQ 85/85 supported, **0 hollow lines**; grammar parses 85.0% →
87.5% of its lines, executes 57.5% → 60.0%. Shipped pool 668/668, floors and
ceilings unmoved, suite green at 6717, no hook added.

## Antiquities ships (Phase 4)

*(2026-08-22.)* The manifest entry moves from `measured` to `sets`, at **index
4, between Arabian Nights and Revised** — the placement this journal recorded at
the ingest, and it earned its keep: `original_printing` is the first entry in
`printings`, so appending would have left the 19 cards Antiquities shares with
Revised reading `3ed`, and Golgothian Sylex — "each nontoken permanent with a
name originally printed in the Antiquities expansion" — would have missed every
one of them. It reaches all three of Ornithopter, Atog and Su-Chi now, which is
the check that says the ordering is doing the work.

Shipped pool **668 → 734** cards, all supported. The suite grows 6717 → 6845
because the pool-wide sweeps now parametrize over 85 more cards.

### What promotion surfaced, which is the whole point of the rehearsal

Six guards fail the moment `load_catalog()` widens, and each named real work:

- **A printed timing clause nobody enforced.** Gate to Phyrexia says "Activate
  only during your upkeep **and only once each turn**", and the restriction
  table had the upkeep row without that tail — so the whole clause matched
  nothing and the *timing* went unenforced. It is the same optional tail the
  "your turn" row beside it already carried, for the same reason: the
  once-a-turn half is per-permanent state and stays where that state lives.
- **A conditional's targets had no prompt.** `derive_activation_spec` descended
  into `sequence` and `may` but not `if_then`, so Goblin Artisans — whose only
  targeting sits behind "if you lose the flip" — got the picker's silent
  auto-target. CR 601.2c/602.2b choose targets as the ability is activated,
  whichever way the coin lands, so both arms are read.
- **Fourteen activated and three triggered abilities** took the category
  fallback rather than a label; each is now in `effect_labels.py` in the bucket
  the *ability* belongs to.
- **Cursed Rack did nothing.** "The chosen player's maximum hand size is four"
  compiled, reported supported, and never took a card off anyone: the cleanup
  step had `max_hand_size = 7` as a literal. CR 402.2's seven and the two
  sentences the pool prints against it are `engine/hand_size.py` now, asked by
  the cleanup step that enforces it, the support gate that admits the line and
  the parse-coverage report that claims it.
- **Two more channels and one that needed the whole card.** "You may choose not
  to untap this artifact during your untap step" is a *permission* rather than a
  restriction and got its own reader beside them (folded into the existing
  `self_untap_line` three commits later, which already read the sentence with
  any noun — the reader was a duplicate); Power Artifact's reduction is
  two sentences that mean nothing apart, so `parse_coverage.py` grew a
  card-aware channel rather than a sentence-only predicate that could not
  recognise either half.
- **Three droppable words, found by the deletion probe and fixed rather than
  accepted.** The self-reference noun in `paragraphs.py`'s three productions
  ("when this **artifact** leaves the battlefield") was accepted-but-optional;
  so was the one in Phyrexian Gremlins' linked duration; and a *typed* counter
  did not require the printed word "spell", so "counter target artifact spell"
  and "counter target artifact" lowered identically. Two probe findings remain
  and both are genuinely redundant printed words — a subtype implying its type
  (CR 205.3) and an "or" in a list.

**Ratchets.** Every grammar floor rose: ALL 80.5% → 81.6% parsed and 46.7% →
47.8% executed, because the productions this set bought read lines the older
sets print too. Every hook ceiling fell: ALL 13.8% → 12.5% of supported cards
name-keyed, 14.7 → 13.4 entries per 100. Antiquities enters at 10.6% hooked —
all of it inherited from the 19 Revised reprints, because **no hook was added
for this set at any point**.

**Phase 5 is outstanding by design.** 388 of 734 cards are verified in-game;
Antiquities joins M21 in the untested remainder, which SET_PLAYBOOK.md Phase 5
owns and deliberately does not gate promotion on. A seeded AI batch over the
whole manifest pool runs clean.

---

## Legends: ingest and census (Phases 0–2)

*(2026-08-23.)* LEG joins `measured` at **310 cards, 121 supported (39.0%)** —
the largest set the engine has taken and the lowest starting coverage of any of
them. The manifest entry goes under `measured`; its eventual home in `sets` is
**index 6, between Revised and M21**, since Legends printed 1994-06-01 and every
one of its 310 cards is a first printing (no reprint's `original_printing`
moves either way, so the placement costs nothing here and keeps the invariant
honest for the sets that follow).

**Phase 1 surfaced nothing.** The suite is green on the ingest, which is worth
recording because it is not what M21 did (66 failures from a never-run import).
The difference is that LEG carries no new layout and no new card type: all 310
are `normal`, and the two supertypes it brings in bulk — **Legendary** (61) and
**World** (12) — already have their state-based actions (CR 704.5j/704.5k in
`mixins/game_ending.py`). Nothing in this set gates on a subsystem the way a
planeswalker or a split card would.

**Census (Phase 2), 189 unsupported cards.** Compiled rather than read: every
printed line of every unsupported card went through `parse_line`, which puts
280 lines on the board of which 205 refuse. Ranked by cards-per-change, the
families that pay:

| Cards | Family | Shape |
| ---: | --- | --- |
| 8 | landwalk negation | "Creatures with \<type\>walk can be blocked as though they didn't have \<type\>walk" |
| 7 | **rampage** (CR 702.23) | a keyword the vocabulary does not have |
| ~12 | prevention | "Prevent all combat damage that would be dealt by target creature this turn" and its statics |
| 5 | colour change | "One or more target creatures become \<colour\> until end of turn" |
| 5 | the Glyph cycle | effects keyed on "the creature that target Wall blocked this turn" |
| 4 | pinger targets | "deals N damage to target attacking or blocking creature" |
| 4 | tax counters | "Whenever a player casts \<a spell\>, counter it unless that player pays …" |
| 2 | poison counters | a subsystem this engine does not have (CR 122.1) |

The rest is a long tail of one-card sentences, which is what Legends is: a set
designed before templating existed, where the same idea is printed a different
way on every card that has it.

**Round plan:** keywords first (Phase 2's rule — highest cards-unlocked per
change), then the families above in the order of that table, with the long tail
last. Rounds are numbered from 1 and their narratives land below as they go.

## LEG round 1: rampage was already built, and a blocklist was hiding it

**121 → 128 supported.** The round was scheduled as "implement the keyword the
census ranks second", and the first thing it found was that the engine already
resolved rampage — `declare_blockers_step._apply_rampage_and_flanking`, with
three passing CR-cited tests over it — while every card that prints the keyword
compiled unsupported.

**The finding is a third table.** `engine/oracle.py`'s `UNSUPPORTED_KEYWORDS` is
a hand-written set of keyword *mechanics* the engine does not model, matched
against the ingested `keywords` field before any line is classified. It is not
the negation of `IMPLEMENTED_KEYWORDS` and cannot be derived from it — "Enchant"
and "Landwalk" are Scryfall tags whose behaviour lives in `auras.py` and the
evasion table — so it is a genuinely separate list, and it **outranks every
other gate**. "Rampage" sat in it, so the keyword registry, the line classifier
and the behaviour behind them agreed with each other and lost anyway. The
comment above that set now says so, and
`tests/engine/test_keyword_registry.py` compiles a card carrying each
implemented keyword *in its ingested field*, which is the direction that catches
it: the previous guards all built their probe cards from oracle text, which the
blocklist never reads.

**What replaced the inline implementation.** CR 702.23a does not describe
rampage, it defines it — "Rampage N" *means* "Whenever this creature becomes
blocked, it gets +N/+N until end of turn for each creature blocking it beyond
the first." So the keyword line now compiles to that triggered ability
(`engine/rampage.py`), the same rewrite `engine/equipment.py` gives equip, one
layer earlier because the grammar has no production for "for each creature
blocking it beyond the first". From there the becomes-blocked dispatcher fires
it, the stack carries it, and one handler resolves it — no combat step knows
the word.

That is not tidying: the inline version got three things wrong that the pool had
no card to expose.

- **CR 702.23b** — "the bonus is calculated only once per combat, when the
  triggered ability resolves". Applied at declaration, it was calculated a step
  early and could not be responded to at all.
- **CR 702.23c** — several instances each trigger separately. `_rampage_value`
  returned the *first* regex match, so a second instance was silently dropped.
- **Band-propagated blocks.** It counted `_combat_blockers_for_attacker` where
  the damage step counts `_attacker_all_blockers`, so a banded block gave the
  attacker a different blocker count depending on which code asked.

Flanking (CR 702.25) stays where it was, deliberately: it is a triggered ability
with no card in the pool — the keyword is not in `IMPLEMENTED_KEYWORDS` — so
moving it would be a card's worth of work with nothing to verify it against.

**Cost.** One new module, one handler, one line off the blocklist, one
`IMPLEMENTED_KEYWORDS` entry; a bespoke branch in the declare-blockers step
deleted. No hook. Three new CR tests (702.23a's stack, 702.23b's resolution
timing, 702.23c's second instance) and one new blocklist guard.

## LEG round 2: landwalk negation, and why it is not a keyword removal

**128 → 136 supported**, the census's largest family: five enchantments
(Crevasse, Deadfall, Great Wall, Quagmire, Undertow) and three creatures (Gosta
Dirk, Lord Magnus, Ur-Drago) printing one sentence per basic land type —
"Creatures with islandwalk can be blocked as though they didn't have
islandwalk."

`engine/evasion_negation.py` is the table, in the shape
`untap_restrictions.py` established: **no instruction kind at all.** The
enforcement site reads the permanent's own text at the moment it needs the
answer, so the gate's claim and the blockers step's check are the *same
function* rather than two tables held equal by hand — and a card printed with
this template in any other set needs no registration.

**The rule the shortcut would have got wrong.** The cheap implementation is a
layer-6 removal: take islandwalk off, blocks become legal, done in three lines.
It is a different card. CR 702.14b makes landwalk an *evasion ability* and
509.1b says an evasion ability creates a **blocking restriction**; this text
lifts the restriction and nothing else. The creature still has the keyword —
`has_keyword("islandwalk")` still answers True, a lord counting islandwalkers
still counts it, Magical Hack remapping the word still finds it. So the skip
lives in `_attacker_has_active_landwalk`, one line above the check it disables,
and a test asserts the keyword survives the block it allowed.

Two smaller decisions worth the words. The reader returns a **set**, because
Lord Magnus prints two of these lines and answering with the first would leave
the second silently unenforced — the same shape as round 1's rampage regex
returning one instance of two. And the template requires the keyword to match
**on both halves** of the sentence: it names the ability twice, and matching the
first half alone would let an invented "…as though they didn't have swampwalk"
negate islandwalk instead.
