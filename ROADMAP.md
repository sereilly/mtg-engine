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
  members are all honest today. LEG round 9 makes it **five**: Kudzu's "when
  enchanted land becomes tapped" reached no trigger table before that round, so
  the ability was instruction-less and invisible to the census at the same time.
  Its registry (`ENCHANTED_LAND_TAPPED_FOR_MANA`) does implement the line — but
  only from the mana-tap path, which is the half of that round's finding it did
  not close. Rock Hydra's automatic counter shield — the
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

- ~~**El-Hajjâj's "you gain that much life"**~~ — *retired, LEG 10.* It was
  recorded here as "its fire site records the amount under a different key",
  which was a fact about a fire site and never about the rule. There is one
  announcement for every damage event now, so there is one key, and the words
  lower for El-Hajjâj, Spirit Link and Backfire alike. A refusal resting on
  where an event happens to be announced from expires the moment the
  announcement moves — which is the reason this list says to re-verify an
  entry against `compile_line` before citing it.
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
19. **A condition kind is a dispatcher's address, so spelling the subject into
    the kind gives one card its own fire site.** `enchanted_land_tapped` and
    `self_becomes_tapped` were CR 701.26a asked about two named subjects; each
    got a kind, and each kind then got a hand-written pass inside
    `tap_land_for_mana` instead of riding the tap seam beside the quantified
    spelling (LEG 9). One event is one kind and the subject is *payload* — the
    arrangement `permanent_becomes_tapped` already used for
    `tapped_subtype`/`tapped_controller`. The symptom is silent in the way this
    engine's worst bugs are: the seam emits, nothing listens for that name, and
    an emit nobody listens for reads exactly like an event that never happened.
20. **A pronoun names the object the sentence already named** — the same rule
    as idiom 7, one word smaller. "It" is the source only where the trigger's
    condition names nothing else, so it is resolved where both halves of the
    line are in hand rather than at the noun (LEG 9). It needs its own AST
    quantifier: a card naming *itself* mid-sentence parses to the same filter
    and means the opposite thing, and rewriting that would aim an Aura's effect
    at the permanent it enchants.
21. **A comment recording a gap is not a fire site that fires.**
    `_fire_combat_damage_to_player_triggers` said in its own docstring that
    El-Hajjâj should also fire on damage dealt to a creature and that "that path
    isn't wired up (a documented gap, not silent)" — and being documented is
    what kept it there for four sets (LEG 10). The distinction the note draws is
    real and the note is still not a dispatcher. When the gap is "this event has
    more than one announcement", the fix is the seam every one of them already
    passes through, and the tell is a *condition kind per fire site*: five kinds
    naming one event is five places to be announced from and five to be
    forgotten.

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

## LEG round 3: one sentence, five cards, and a second colour channel

**136 → 141 supported.** "One or more target creatures become <colour> until
end of turn" — Dwarven Song, Heaven's Gate, Sea Kings' Blessing, Sylvan
Paradise, Touch of Darkness, one per colour, one production.

Landed bottom-up with the grammar last, as M21 round 17's lesson says: the
until-end-of-turn colour channel, then the handler, then the targeting spec,
then the lowering, then the production that makes the five cards reachable. At
every intermediate point the cards stayed honestly unsupported rather than
becoming castable with half the effect wired.

**Three gaps, not one**, which the compile-not-read census is what surfaced —
the reason string named only the first.

- **"until end of turn" on a colour change.** `BecomeColor` carried no
  duration, because the Lace cycle prints none. Adding the field is what stops
  the parser from either refusing the line or — worse — consuming those four
  words and making Sylvan Paradise a permanent lace.
- **A second colour channel.** `color_override` is indefinite and must survive
  the turn (CR 105 and the Lace cycle print no duration). So layer 5 now reads
  two keys in timestamp order, exactly as layer 7b does, and only the newer one
  is in the cleanup sweep. A test casts Heaven's Gate at an already-Chaoslaced
  creature and checks the red is still there after cleanup.
- **"One or more target" is a quantifier the parser did not have.** Not
  "any number of" with a floor bolted on: the two differ in precisely the thing
  a picker enforces — "any number" may legally name none (CR 601.2c) and this
  may not — and in nothing else. It is unbounded above, so it reaches the
  picker through the same `unbounded_targets` route Drafna's Restoration's "any
  number of" takes, and `legality.py` fills in the cap once it knows how many
  legal targets exist.

## LEG round 4: "attacking or blocking" is one restriction, not two

**141 → 145 supported.** Crimson Manticore, D'Avenant Archer, Lady Caleria and
Tor Wauki all print the same pinger: "deals N damage to target attacking or
blocking creature". The parser read either adjective on its own and stopped at
the "or", which ended the noun phrase mid-sentence.

The field is `attacking_or_blocking`, and it is a **third** field rather than
both booleans set at once. Every matcher ANDs the payload keys, so
`attacking_only` and `blocking_only` together describe a creature doing both —
a set that is always empty, and a card that would refuse every target while
reporting itself supported.

It is answerable by the **pure** matcher, which is what keeps it out of
`subject_filters`: "attacking" is a field, and CR 509.1a makes "blocking" one
too — a creature is blocking once it has been *declared*, which is exactly what
`blocking_attacker_index` records. That is the same test
`layer_bridge._QUALIFIER_HOLDS` already uses for a conditional buff, so a
narrowing and a buff cannot come to different conclusions about what "blocking"
means.

Enforced in **both** places, deliberately. At resolution the filter narrows the
target; at activation `legality.py`'s enumerator narrows the picker, which is
what makes CR 602.2b's refusal fire — a pinger with nothing in combat to shoot
is refused with nothing paid rather than activated and pointed at whatever the
picker offered. The test asserts the *reason* string, because a refusal for any
other cause would pass while leaving the restriction unenforced.

## LEG round 5: a combat shield has a direction, and it was a boolean

**145 → 149 supported.** Horn of Deafening, Lady Evangela, Gaseous Form,
Demonic Torment — the first four of the census's nineteen prevention cards, and
the four that share one mechanism.

The engine had exactly one combat shield: Ebony Horse's
`prevent_combat_damage_to_and_by_until_eot`, a boolean read at both ends of the
event. Legends prints the halves. **Gaseous Form and Demonic Torment differ by
one word** — "dealt to and dealt by enchanted creature" against "dealt by
enchanted creature" — and reading them as the same shield makes Demonic
Torment's host unkillable in combat, which is a strictly better card than the
one printed. So a shield now answers `shields_combat_damage(perm,
dealt_to=…)`: the old boolean still means both ends and nothing that reads it
changed, and two new sources carry a direction beside it.

The two sources have different lifetimes, which is why both exist. The
**activated** form (Horn of Deafening, Lady Evangela) is a turn-long marker the
cleanup sweep clears — that is what "this turn" means. The **Aura** form
(Gaseous Form, Demonic Torment) is read off the attached Aura's own text at the
moment damage would be dealt, so it ends when the Aura does with nothing having
to clear it — the shape `_source_type_shielded_by` one screen up already used.

Two smaller findings. The `by` half of the prevention production had to be
*parsed*, not skipped: "to" and "by" are the whole difference between a
creature that cannot be hurt and one that cannot hurt anything. And Demonic
Torment's second line, "Enchanted creature can't attack", was unclaimed —
the Aura restriction table carried only the compound "can't attack or block",
beneath a comment saying in so many words that a card printing one half is a
different card. It is now that card, with its own row.

## LEG round 6: a source class stopped being a card type

**149 → 153 supported.** Enchanted Being, Marble Priest, Wall of Putrid Flesh,
Wall of Vapor — the other end of round 5's shield. "Prevent all damage that
would be dealt to this creature by <something>" already existed for Artifact
Ward, and the something was one of four card types.

Legends prints three narrowings that are not card types at all, and each is a
**different kind** of thing:

- **"Walls"** is a subtype (CR 205.3) — Marble Priest.
- **"enchanted creatures"** is a *state of the source object* — Wall of Putrid
  Flesh, Enchanted Being. (Not the Aura's "enchanted creature": these are
  creatures that happen to have an Aura on them.)
- **"creatures it's blocking"** is a *relationship* between the source and the
  recipient, which neither object carries on its own — Wall of Vapor. It is
  directional, and the test says so: a creature blocking the Wall is not a
  creature the Wall is blocking, and reading the combat map either way round
  would shield both.

So the reader returns a **dict of fields** rather than a type string, and
`_SOURCE_CLASSES` maps each printed phrase to the fields that test it. The
"combat" narrowing joins them as a flag on the same dict: Enchanted Being's
line is Wall of Putrid Flesh's with the word "combat" in it, and a shield that
dropped it would stop a ping the card does not stop.

Marble Priest's other line came along for the ride: "All Walls able to block
this creature do so" is Lure's requirement (CR 509.1c) narrowed to a printed
noun and printed on the creature rather than on an Aura. It is a
`combat_restrictions.py` row, and the blockers step reads it beside the Aura
form — one loop, two sources. The narrowing is translated into the
subject-filter vocabulary the same way `cant_be_blocked_by` is four screens
down; left untranslated it would have compelled the whole board, which is Lure
rather than Marble Priest.

## LEG round 7: a whitelist is not a negated blacklist

**153 → 156 supported.** Amrou Kithkin, Elven Riders, Seeker — the evasion
family. Two of the three narrowings were payload the table did not carry
(a colour, a power threshold); the third is a different *kind* of restriction
and got its own instruction kind.

**"Can't be blocked except by X" is `cant_be_blocked_except_by`, not
`cant_be_blocked_by` with a `not`.** The two differ in what they say about
everything the sentence does *not* name: "can't be blocked by Walls" lets the
rest of the board through, "except by Walls" lets none of it through. Written
as one kind with a flag, an unreadable member of the union would flip a card
from unblockable-by-almost-everything to blockable-by-everything.

Two things the round is worth recording for:

**The regex ends in a catch-all, so the union is parsed where the restriction
is built.** "Walls and/or creatures with flying" cannot be delimited by an
alternation without the noun parser this file deliberately does not have, so
`_blocker_union` reads it and a phrase it cannot read **refuses the whole
line**. Admitting the match and leaving the tail to the enforcement site is the
shape this file's own comments keep describing.

**And the test written for that found the hole in it.** The first version
accepted "creatures with three heads" as a keyword filter — which, in a
whitelist, is a creature that cannot be blocked *at all*. The keyword is
checked against `IMPLEMENTED_KEYWORDS` now, the same way the subtype is checked
against `CREATURE_TYPES` five lines up.

Invisibility's hardcoded `only_blockable_by_walls` Aura restriction and its own
check in the blockers step are **gone**: the general template reads its line
through the same subject rewrite every other attached restriction uses, so
Invisibility, Seeker and Elven Riders are one rule printed on three kinds of
card.

## LEG round 8: two where-clause parsers, and a spell a trigger already named

**156 → 160 supported.** Nether Void, Presence of the Master, In the Eye of
Chaos, Great Defender — two families that turned out to share a sentence
fragment.

**The parser had two where-clauses and they accepted different things.**
`statements._parse_where_x` read the sentence-level clause and
`effects/characteristics._parse_gets` read the pump's own. Only the pump knew
"the greatest power among"; only the sentence knew "that died under your
control". So *which definitions a card could use depended on which sentence it
printed them in*, which is not a rule Magic has — and adding "its mana value"
to one of them would have made a third such difference. The fork is closed:
one `phrases.parse_where_x_definition`, called by both, and the pump's
type-test on `CountOf` is gone in favour of the spec builder that already
refuses what it cannot build.

**"Where X is its mana value" is a different kind of definition.** Every
existing one aggregates over a *set* of objects; this reads a characteristic off
the single object the sentence already named. It needs no filter at all, which
is why it is its own node — and CR 202.3 makes it a characteristic of the
**card**, so the resolution reads the printed cost rather than anything on the
battlefield.

**And "it" is not "that spell".** "Whenever a player casts a spell, counter
**it**" binds its object through the trigger's own condition — nothing is
chosen, so no picker is described and the handler finds the spell on the stack
**by identity**, not at the top: CR 603.3 puts the trigger above the spell, and
anything cast in response sits between them. `cast_card` rides the `spell_cast`
event for that, the way it already rode the first-spell one.

Which of the two objects "its" names is decided **at lowering**, by looking at
the sentence being stamped: an instruction bound to a trigger names the spell,
anything else names the target. A resolution-time fallback order would have had
to guess for a sentence carrying both.

## Legends: where rounds 1–8 leave it

**121 → 160 of 310 supported (39.0% → 51.6%).** The set stays `measured`; the
promotion gate is Phase 4 and 150 cards are still unsupported. Every gate is
green, the trackers are current, and the suite is 6,845 → 6,993 tests at 42.5s
against a 40s baseline — proportional growth, no budget change.

**No name-keyed hook was added at any point.** LEG's hook reliance is 0.0% and
the ALL ceilings are untouched; the grammar floors are unchanged too, because
these eight rounds bought *Legends'* sentences and the shipped pool does not
print them. That is the honest reading of the ratchets rather than a
disappointment: a set this old shares less of its templating with the rest of
the pool than Antiquities did.

**What the rounds bought, in order:** rampage (7), landwalk negation (8),
colour change (5), the pinger target filter (4), directional combat shields (4),
described prevention sources (4), the evasion whitelist (3), the mana-value
where-clause and the trigger-bound counter (4).

**Where the next round starts.** The generalise-first ranking has flattened:
**113 of the 135 cards that still refuse a line refuse exactly one**, and the
largest group among them shares only an opening phrase. The families with more
than one card left, best first:

| Cards | Family | What it needs |
| ---: | --- | --- |
| 4 | attached triggers | "Whenever enchanted creature deals damage / becomes tapped" — two trigger conditions, both with a dispatcher already in place (`become_tapped`, `deal_damage`), plus a `-0/-2` counter kind and a damage-amount back-reference |
| 4 | named-card lords | "Creatures you control named X get +2/+2" — a lord buff whose filter is a card name |
| 4 | base P/T rewrites | "Change this creature's base power and toughness to …" against another permanent's current values |
| 3 | linked control changes | "Gain control of target creature for as long as you control this and it remains tapped" — `engine/control.py` has the contribution model; the linked duration is what is missing |
| 2 | poison counters | CR 122.1's counter plus the CR 704.5c state-based action — a subsystem, two cards |
| 2 | hidden information | "Players play with their hands / the top card of their libraries revealed" |
| 2 | ante | `engine/ante.py` exists; both cards print the CR 407 opt-out line as well |

Everything past that is one card at a time, which is what Legends is.

## LEG round 9: three conditions for one event, two of them dispatched by one tapper

**160 → 162 supported.** Blight and Spirit Shackle, the two Auras whose whole
effect is a trigger on the permanent they enchant becoming tapped. What the
round actually found is underneath them: `become_tapped` has been the single
CR 701.26a transition since Lifetap's hook was deleted, and **two conditions
were still being dispatched by a hand-written pass inside
`tap_land_for_mana`** — so each fired on that one tapper and on none of the
other ways a permanent taps.

**One event, one condition kind, the subject as payload.** `engine/oracle.py`'s
table spelled the subject into the *kind*: `enchanted_land_tapped` for Psychic
Venom, `self_becomes_tapped` for City of Brass, `permanent_becomes_tapped` for
Lifetap's quantified class. A kind of its own is exactly what let the first two
be dispatched somewhere else — the emit was there, nothing listened for those
two names, and an emit nobody listens for is indistinguishable from an event
that never happened. All three are `permanent_becomes_tapped` now, narrowed by
`tapped_attached` / `tapped_self` / `tapped_subtype`, and `_becomes_tapped_filter`
reads whichever is present. Both new narrowings are **identity** checks, not
characteristic ones: two Cities of Brass on one battlefield compare equal by
value, and so do two Forests under one Aura.

Two shipped cards changed behaviour, both in the direction the card prints.
Psychic Venom and City of Brass fire when the land is tapped by an Icy
Manipulator, by a cost, or by anything else — and they use the stack, because
CR 605.1b makes a trigger a mana ability only if it *could add mana*, which
these cannot. Their tests now resolve the ability rather than reading the life
total straight after the tap.

**"It" names the object the condition was about.** Blight says "destroy **it**",
and `parse_recipient` read a bare "it" as the ability's own source — correct on
every line in the pool until now, because every trigger printing the word had
the source as its subject. Read that way, Blight destroys Blight. The pronoun
has its own quantifier now and `parser.py` rebinds it once the whole line is in
hand, which is round 8's decision about "its" made at the same moment for the
same reason.

The rebinding is *only* the bare pronoun, and that is the whole reason the
quantifier exists: a card naming itself mid-sentence ("**Psychic Venom** deals 2
damage to that land's controller") parses to the same `is_source` filter and
means the opposite thing — rewriting it would aim an Aura's own effect at the
permanent it enchants. The walk over the statement is structural rather than a
list of the productions that admit a pronoun, because such a list goes stale the
way every fire-site list in this engine has.

### A P/T counter is named by the P/T it carries

Spirit Shackle's "-0/-2 counter" was refused as an *unsupported counter kind* by
a four-entry tuple that admitted "-1/-1" beside it. CR 122.1a does not have a
list — "a +X/+Y counter … similarly, -X/-Y counters subtract" — so the numbers
are the counter's name, and `engine/pt.py` derives the pair from it. Takklemaggot
and Lesser Werewolf's "-0/-1" come for free when their other lines land.

Three things fell out of writing the channel:

- **Unstable Mutation was not placing counters at all.** Its upkeep pass wrote
  `power_bonus -= 1; toughness_bonus -= 1` under a comment saying "the counters
  are real -1/-1 counters … 704.5f/704.5q apply" — which 704.5q could not,
  because the sweep cancels by reading `minus_counters` and nothing had ever
  written one. A claim in a comment falsified by the code two lines below it.
- **Clockwork Beast's cap was counting a different pile from the one it fills.**
  `+1/+0` counters had their own metadata key and their own direct
  `power_bonus` poke; they go through the seam now, so "can't cause the total
  number of +1/+0 counters to be greater than seven" reads the pile the
  placement fills.
- **The counter record is keyed by the counter's *name*** (CR 122.1: counters
  with the same name are interchangeable), through `named_counters.counters_key`
  rather than a second spelling of it. A -0/-2 counter is not a -1/-1 counter,
  so it must not join the pile CR 704.5q cancels — the test says so directly.

`Game.place_pt_counters` is the seam, handing "+1/+1" to `place_plus1_counters`
because that kind is the one with an *event*: the CR 614 replacements the pool
prints (Conclave Mentor) and the trigger watching for them (Wildwood Scourge)
name +1/+1 counters specifically. The day a card prints either for another kind
the event moves up; until then, routing a -0/-2 counter through that event would
ask a replacement about a counter its card does not mention. The placement guard
now bans both library operations, not just the +1/+1 one.

### What this round did not close, and why it is now visible

**Kudzu's hook still fires on the mana path alone.** Its first sentence *is*
Blight's, but the second — "That land's controller may attach this Aura to a
land of their choice" — is a paragraph the grammar does not read, so the whole
line still refuses and `ENCHANTED_LAND_TAPPED_FOR_MANA` still carries it. The
hook is unchanged and so is its behaviour; what changed is that the compiler now
recognises the *condition*, so the shipped pool's hollow-line census went **4 →
5** and names Kudzu. That is the census gaining sight of a card, not a card
getting worse: the ability produced no instruction before too, and the census
could not see it because "**When** enchanted land becomes tapped" reached no
table. Closing it is one production plus an attach instruction, over machinery
that already exists (`kudzu_reattach` is a registered pending choice, not a
`Game` field).

**Numbers.** LEG 160 → 162 of 310 (51.6% → 52.3%); the set's grammar reads
52.2% → 52.9% of its lines and executes 23.2% → 23.7%. Shipped pool 734/734
supported with every floor and ceiling unmoved — these productions read lines
the older sets already had claimed, so the movement is all in Legends. No hook
added; one bespoke fire site and two condition kinds deleted. Suite 6,993 →
7,009 at ~44s against the 40s baseline — proportional growth, no budget change.

**Where round 10 starts.** The other half of the attached-trigger family:
Spirit Link's "whenever enchanted creature deals damage, you gain that much
life" and Backfire's "…deals damage **to you**". Their condition has no seam
yet — `_fire_combat_damage_to_player_triggers` fires "this creature deals
damage" from the combat-damage-to-a-player path alone, which its own docstring
has recorded as a gap since El-Hajjâj was written. `damage_events.deal_damage`
is the one place every damage event passes through, and that is where the
announcement belongs.

## LEG round 10: "deals damage" was five conditions and three fire sites

**162 → 164 supported.** Spirit Link and Backfire, the other half of the
attached-trigger family — and the same finding as round 9 one seam over.
`damage_events.deal_damage` has been the single place a damage event happens
since it was written, and its own opening docstring says so: "abilities that
trigger on damage being dealt trigger on what comes out of this half". Nothing
was announced from there. The triggers were fired from wherever each card
happened to be played out.

**Every printed narrowing is one row now.** The pool spells the same event nine
ways —

```
whenever <this creature | enchanted creature | a source you control | <noun phrase>>
         deals [combat|noncombat] damage
         [to <a player | an opponent | you | a planeswalker | a player or planeswalker>]
```

— and that was five kinds in the condition table plus two more further down,
each with a dispatcher of its own. One kind (`damage_dealt`), one announcement,
one `@event_filter`, and both halves read off the trigger's own parsed
condition.

**Three cards changed behaviour, all of them towards what they print.**

- **El-Hajjâj** ("whenever this creature deals damage, you gain that much
  life") gained nothing for damage dealt to a blocker, to a planeswalker, or by
  any ability — its only announcement was inside the combat damage step's
  *player* loop. That gap was written down in the fire site's own docstring for
  as long as the site existed, which is what a fire site that is not a seam
  looks like: the comment was accurate, and being accurate did not make it fire.
- **Hypnotic Specter** prints "deals damage to an opponent" and was combat-only
  for six shipped sets, for the same reason.
- **Garruk's Harbinger** needed *two* fire sites so that "a player or
  planeswalker" would see both halves. It needs none: a planeswalker takes
  damage through the same event a player does, and which of them was hit is a
  question the filter asks.

**A hook retired itself.** El-Hajjâj's "you gain that much life" was a
name-keyed entry *and* a **deliberate refusal** recorded in this file: the words
could not be lowered because "its fire site records the amount under a different
key". That was true of a fire site and never of the rule. With one announcement
there is one key, `_EVENT_QUANTITIES` gains a single row for the whole family,
and the grammar reads the line — so the entry died and
`test_card_lines.py` said so on the first run. Spirit Link's "that much life"
and Backfire's "that much damage" arrive on the same row.

**Two smaller things the collapse forced, both worth keeping.**

*The bound object is promoted once, not stamped twice.* "Destroy that
planeswalker" (Hooded Blightfang) needs the damaged permanent on the **stack
item**, not in the trigger context, and the two fire sites that used to supply
it wrote it out by hand. `collect` lifts `target_permanent_id` and
`target_player_index` from any event's payload, so a third announcement cannot
forget.

*A noun phrase describes permanents, and a damage source need not be one.* For a
spell the source is the printed card (CR 109.5) — no controller, no computed
types, nothing the matcher can ask. The old planeswalker site avoided this by
refusing to announce at all; the filter answers it instead, which is where the
phrase is. Without the guard, a Shock aimed at a planeswalker with a Hooded
Blightfang on the board crashed mid-damage-event.

**And one name that was two.** The two announcements called the damaged player's
seat `damaged_seat` and `defending_player_index`, which is why a handler could
only be written against one of them. One announcement, one key.

**What stayed where it was, with its reason.** Feline Sovereign's "whenever
**one or more** … deal combat damage to a player" is one trigger however many
creatures dealt it, so it is not a per-event announcement and keeps the combat
step's batching. Subira's delayed trigger (CR 603.7) belongs to no permanent, so
no battlefield scan can find it. And Chandra's Incinerator's per-turn tally
stays on the noncombat player-damage path — it is the one site that knows both
halves of what it counts — while the *announcement* beside it is gone.

**Numbers.** LEG 162 → 164 of 310 (52.3% → 52.9%). Shipped pool 734/734, and
this time the ratchets moved: ALL executes 48.0% → 48.1% and ARN 41.7% → 42.6%
(El-Hajjâj's line is the grammar's now), while the ALL hook ceiling falls 11.4%
→ 11.3% of supported cards and 12.4 → 12.3 entries per 100 — one hook retired,
counted in both the sets that print the card. Suite 7,009 → 7,023 at ~41s;
three fire sites and seven condition kinds deleted, one added, and the handler
the retired hook was the only producer of deleted with it.

## LEG round 11: four families in four worktrees, merged one at a time

*(2026-08-23.)* The first round executed in the playbook's worktree shape —
re-opened this same day after re-testing the stale "repo refuses worktrees"
note — and the first to land four one-family branches in one round:
base-P/T rewrites (Sentinel, Wall of Tombstones, Halfdane, Brine Hag), linked
control changes (Willow Satyr, Rubinia Soulsinger, The Wretched, Disharmony),
the "named <card name>" filter (Ivory Guardians, Rohgahh of Kher Keep, Akron
Legionnaire), and poison counters plus standing reveals (Pit Scorpion, Serpent
Generator, Revelation, Field of Dreams). Fifteen cards, every one through the
grammar except one recorded hook (below).

**The parallel shape works, with two amendments the round itself wrote.** All
four agents launched at once and all four died on a shared session limit —
"two that finish beat four that die" holds even with a large budget, because
the budget is shared with the main loop. Restarted sequentially, every agent
resumed from its own partial worktree and finished. And integration is where
parallel grammar edits collide: both the P/T and control branches extended the
noun postmodifier scan at the word "blocking", each green alone, and the
merge ordered them so the one-word branch probed, failed on "or" and broke
the scan before the two-word branch was asked — Sentinel stopped compiling
with both branches' suites passing. The per-card test caught it at merge,
which is the serial-integration rule doing its job; the fix is a one-line
lookahead and a comment naming the collision.

**Four supported cards were silently doing less, and one was doing more.**
The census questions keep paying: Conspicuous Snoop's `top_is_public` was
computed, tested and read by nobody — his revealed top card never reached the
client until the reveal work needed the same seam. Sengir Vampire's kill
record was combat-fed and value-matched, so a ping kill earned no counter and
a look-alike deduped wrongly — fixed, a verified card CR-corrected. Aladdin's
"for as long as you control" ended only through the leave hook, so stealing
Aladdin left the artifact stolen forever — the linked-condition sweep now
ends it. And the conditional-lord reader granted protection without asking
the condition — latent (no conditional lord grants protection today), fixed.

**The first LEG hook, with its reason.** Rohgahh's pay-or-cede upkeep line —
tap a named tribe and cede it to an opponent — is `CARD_LINE_INSTRUCTIONS` +
an upkeep handler: no second card, real or plausibly printable, shares the
shape. LEG's 0.0% streak ends at one hook in 179 supported (0.6%); the
ceilings are untouched because a measured set never ratchets.

**Numbers.** LEG 164 → 179 of 310 (52.9% → 57.7%); `--refusals` drops from
176 refused lines over 146 cards to 131 cards. LEG parse 53.4% → 56.8%. The
shipped ratchets moved up as by-catch: ALL parses 81.8% → 82.0% (ARN 67.6% →
69.4% — Aladdin's family; 3ED 81.2% → 81.5%). Suite 7,023 → 7,085. Merge
order info → named → pt → control, full suite and every `--check` green
between merges; one union-merge rule held throughout (every branch's test
block was a pure insertion at the same anchor).

## LEG round 12: "can't attack" is one table with history behind it

*(2026-08-24.)* The first sequential worktree round: one branch from current
HEAD, one agent, a fast-forward merge — no cross-branch conflicts by
construction, which is the shape's dividend when nothing else is in flight.
Five cards, all landed: Moat, Evil Eye of Orms-by-Gore, Giant Turtle, Wall of
Dust, and Arboria — the stretch card came home rather than being deferred.

**A restriction's subject is payload, and its history is a record.** Moat and
Evil Eye are one `creatures_cant_attack` row whose filter carries
`without_keywords` (a layer-6 ask — a bear granted flying escapes the Moat)
and a negated subtype; the noncreature static path now consults the same
table the creature path always had, so an enchantment's restriction is gated
and dispatched by one table. The other three hang on per-turn history rather
than on the board: an `attacked_on_seat_turn` stamp against per-seat turn
ordinals (Giant Turtle — the stamp dies with the object, CR 400.7, so a
returned Turtle attacks freely), the same ordinal stamped onto a blocked
creature by Wall of Dust's trigger, and `last_own_turn_activity` folded at
the turn boundary for Arboria, which also taught `can_attack` that a
planeswalker attack is not an attack on a player (CR 508.5).

**The census misreads a table-claimed line, and now says so.** Evil Eye's
"can't be blocked except by Walls" showed as *refused: unconsumed text* — but
the round-7 whitelist row had read it perfectly all along. `--refusals`
probes lines through the grammar only, and a text-keyed table's claim is
invisible to that probe, so a card unsupported for one line shows every
table-claimed sibling as refused too. The report now carries the caveat in
its header; the deeper fix (a per-line claim seam the gate and the report
both read) is noted for whenever a second misread bites.

**Recorded approximations, named in the code:** a skipped turn still
increments its seat's ordinal (Giant Turtle wakes a turn early through Time
Walk-class effects; Arboria reads a skipped turn as quiet), and Arboria
credits an entered permanent to the seat it enters under. Wall of Dust's
trigger label is promotion debt (`TRIGGERED_LABELS` is guard-held to the
shipped pool).

**Numbers.** LEG 179 → 184 of 310 (57.7% → 59.4%); LEG parse 56.8% → 57.1%.
Suite 7,085 → 7,105, full run green with every `--check`. No hooks added —
the one LEG hook remains Rohgahh's.

## LEG round 13: an Aura's enter-tap was a substring, and X was always zero

*(2026-08-24.)* Sequential worktree round two: Reset, Venarian Gold, Cocoon,
Arena of the Ancients — enter-taps, counter-conditioned untap restrictions,
and upkeep counter removal, all four landed.

**The census said one handler; the work was three kinds and two seams.** The
"no handler for non-targeted tap/untap" bucket split into an
enchanted-creature tap (source-relative, twin of the existing untap) and a
described-set sweep pair, both resolving through `subject_matches` under the
double gate. Behind them sat two gaps no census line named: an ETB trigger's
X had always resolved to zero (the fire site never threaded the cast's
value), and "put X sleep counters on **it**" parsed the pronoun as the
*Aura*, so a generic lowering would have put the counters on the wrong
object. The fused recognizer pairs the tap with its counters and the fire
site now carries `cast_x_value`.

**Two shipped-pool defects, one deleted and one disarmed.** Paralyze and
Capture Sphere's enter-taps were a substring pair in `_apply_aura_effect`
that also matched Venarian Gold — it would have tapped the creature and
silently dropped the sleep counters. The pair is deleted; both cards'
enter-taps are real triggers now. And `sacrifice_self` executed with no
handler at all — "supported pattern without state mutation", one card away
from firing in the wild.

**Where a spelling lands is a fact about scope, not about words.** The two
Aura untap conditions ("if it has a sleep counter" / "if this Aura has a
pupa counter") do not join `untap_restrictions.py` — that is the board-wide
table, where Arena's plural-possessive legendary row belongs — they are aura
derivations beside Paralyze's unconditional form, answered live at the untap
step. Cocoon's hatch reads `last_attached_to` (CR 603.10) so the +1/+1
counter and the permanent flying land after the same resolution sacrificed
the Aura, and "Enchant creature you control" is enforced at the cast gate,
the picker, the AI and a new CR 704.5m sweep.

**Flagged for a future round, deliberately not taken here:** the `_TEMPLATES`
ETB wildcard in `engine/auras.py` still claims every "when this aura enters"
line for the substring chain's remaining users (Animate Dead, Earthbind);
removing it flips an unknown set of cards and wants its own differential.

**Numbers.** LEG 184 → 188 of 310 (59.4% → 60.6%); LEG parse 57.1% → 58.5%,
executes 27.1% → 28.5%. Shipped by-catch: ALL lowers 80.8% → 81.1%, executes
48.1% → 48.3% — the sweeps and the enchanted-tap claim shipped sentences.
Suite 7,105 → 7,134, full run green with every `--check`; zero hooks added.

## LEG round 14: a threshold that was a number in a phrase, and a pronoun with no referent

*(2026-08-25.)* Two cards — Spiritual Sanctuary and Storm World — chosen
because neither gap was about the card. Both print "at the beginning of each
player's upkeep, … that player …", and what stopped them was shared with a
card that already ships.

**The Rack was a card hook because its number was 3.** Black Vise's "the
number of cards in their hand minus 4" was a `_BOARD_COUNTS` phrase with the
`4` spelled into the token list, so the threshold was part of the *match*
rather than data. The Rack prints the same arithmetic in the mirror order with
a different number, matched nothing, and had been carried by a name-keyed
entry in `card_hooks.py` — which is `land_animation.py`'s false-negative
failure in a second place, and exactly the entry bar that file states: a
second card shared the shape. The phrase now carries a `NUMBER_SLOT` that
captures the constant into `BoardCount.base`, both printed orders are rows,
and the hook is **deleted**. The deficit branch behind it had been live in
`upkeep_effects.py` since Black Vise landed with nothing in the grammar able
to reach it.

**"That player" was resolvable in the recipient and silently wrong in the
condition.** Spiritual Sanctuary compiled the moment "they" became a player
pronoun (`nouns.py` had read "they control" as `that_player` since Antiquities;
`references.py` had never heard the bare word). It then did the wrong thing
twice, and each half looked right while the other was being read. The gain
went through `context.target`, which on the controller's *own* upkeep is the
opponent — right on every other seat's upkeep, so a two-player test that
starts with the opponent's passes. And `who: "that_player"` reached
`evaluate_condition`'s fallback, which scans **every** player: the card asked
"does anybody control a Plains", found its controller's, and paid life on an
upkeep whose player controlled none.

Both halves are one seam now. `_EVENT_SUBJECT_PLAYERS` is the table of trigger
conditions whose subject *is* a player — a sibling of
`_EVENT_SUBJECT_CONTROLLERS` rather than more entries in it, because that one
answers "the controller of the object the event was about" and no upkeep fire
site stamps its key. The ordinary (non-registry) upkeep path freezes the seat
(CR 603.10) and both readers take it from there. A "that player" under a
trigger *not* in the table now refuses the line instead of resolving against
whatever is nearest, which is what the round was really buying: only Spiritual
Sanctuary produced that condition in the whole pool, so the fallback was a
loaded gun with nothing yet pointed at it.

**The size guard fired, and the cut was already drawn.** `lowering/_common.py`
crossed 1,000 lines on this round's comments. `_events.py` splits out the
tables keyed by **trigger-condition kind** — what the firing event froze, for a
back-reference the sentence cannot resolve on its own — leaving `_common` as
what it says it is, the shape a payload takes. Six families read something
there, so it is named beside `_common` in the layering guard's `shared` tuple
rather than being a family.

**Flagged, not taken.** Storm Seeker ("deals damage to target player equal to
the number of cards in that player's hand") gets past the self-reference and
dies on "unconsumed text": an `equal to <count>` tail after a damage clause is
a different production from the `where X is` trailer, and wants its own round.

**Numbers.** LEG 188 → 190 of 310 (60.6% → 61.3%); LEG parse 58.5% → 58.9%,
lowers 53.8% → 54.3%, executes 28.5% → 29.0%. Shipped by-catch is the hook
deletion showing up as grammar credit: ATQ 87.5% → 88.3% parsed *and* lowered,
3ED 81.5% → 81.7%, ALL 82.0% → 82.1% parsed and 48.3% → 48.4% executed. Hook
reliance **falls**: 83 → 82 of 734 supported cards (11.3% → 11.2%), 90 → 89
entries, 12.3 → 12.1 per 100 — a ceiling lowered rather than raised. Suite
7,134 → 7,145, full run green with every `--check`.

**A note on the ratchet diff.** `scripts/grammar_ratchet.json` moved more than
this round earned: its floors were behind the committed
`GRAMMAR_COVERAGE.md` at HEAD (ARN parse read 67.6 against the tracker's 69.4),
so round 13's gains were re-accepted alongside these. Regenerating the tracker
and accepting the ratchet are two steps, and only the first is in CI's
freshness check — worth doing both at a round's end.

## LEG round 15: a kind that spelled its own narrowing, and the fire site it needed

*(2026-08-25.)* Abomination and Aisling Leprechaun, and the round is mostly a
deletion: one fused instruction kind, one bespoke ~90-line fire site, and a
positional-read allowance.

**`creature_blocks_or_blocked_by_nonwall` had the narrowing in its name.** The
Basilisk cycle prints "Whenever this creature blocks or becomes blocked by a
non-Wall creature, destroy that creature at end of combat", and the engine met
it with a kind naming *non-Wall* and a fire site in
`declare_blockers_step.py` that tested `victim.has_type("wall")` by hand.
Abomination prints the identical sentence with "a green or white creature" and
matched nothing; Aisling Leprechaun's says "a creature" and matched nothing.
Same lesson as the land type in `combat_restrictions.py`, the P/T in
`land_animation.py` and round 14's threshold, and by now the tell is the kind
name itself.

The condition is `creature_blocks_or_blocked_by`, and its noun phrase is
delimited once by a new `_pair_subject` group that fans out into **both**
halves' existing filter keys. That is the whole trick: English distributes the
phrase over both verbs, the engine already had `blocked_filter` and
`blocker_filter`, and the two general dispatchers already read them — Infernal
Medusa prints the two halves as separate sentences and has always gone through
them. So the joined sentence needed no new dispatcher at all, only its kind
added to the two that exist, and `_fire_block_triggers` deleted. Positional
battlefield reads in that module fall 18 → 16.

**The delayed destroy was reading the wrong binding, and would have taken the
recolour with it.** The two fire sites bind "that creature" differently: the
becomes-blocked half makes it the stack item's target, the blocks half targets
the *blocking creature itself* (Ydwen Efreet needs to find itself there) and
puts the blocked attackers in `blocked_permanent_ids`. The old fire site hid
this by pushing the victim as the target on both. `block_pair_permanents` is
now the one reader of the difference, and both handlers go through it —
otherwise Abomination destroys itself on the half where it blocks.

**Aisling Leprechaun needed the fire site to stop being a destroy site.** Its
effect is a recolour, so the binding travels as payload
(`subject_from_trigger: "block_pair"`, beside `x_from_count` in
`oracle_types.py`) rather than as a second instruction kind — which object an
effect acts on is not a different effect, and fusing that in is what gave the
old kind its name.

**A dropped rider found on the way.** `ObjectFilter.to_payload` wrote
`payload["color_filter"] = self.colors[0]` — every colour after the first
silently discarded. Nothing exercised it because no noun phrase could produce
two, so it sat waiting for exactly the parser change this round made. Colour
disjunctions now read as a union (`any_colors`, demonstrated in
`test_subject_filters.py` in both directions, because a matcher reading the
list as AND passes the rejection row).

**Flagged, not taken.** Infernal Medusa is *supported* with a hollow half: its
"Whenever this creature blocks a creature" line lowers to nothing, because
`_BLOCK_PAIR_EVENTS` is keyed on the event kind alone and cannot tell the
narrowed spelling from the bare one — and the bare one binds no single creature
(CR 509.3c/509.3d), so admitting the kind would destroy every attacker it
blocked. Fixing it means threading the condition's *narrowing* into lowering,
not just its kind. `--hollow-lines` already reports it; LEG carries 19.

**Numbers.** LEG 190 → 192 of 310 (61.3% → 61.9%); LEG parse 58.9% → 59.4%,
lowers 54.3% → 54.8%, executes 29.0% → 29.5%. Shipped pool unchanged at 734/734
and its coverage flat — this round bought a measured set's cards and deleted
shipped code rather than adding any. Suite 7,145 → 7,151, full run green with
every `--check`; no hooks added, none removed.

## LEG round 16: the narrowing was the whole difference, and the gate could not see it

*(2026-08-25.)* No new card is supported by this round. It closes the gap
round 15 flagged, and the flag understated it: the gate was wrong in **both**
directions at once.

**One kind, two spellings, opposite meanings.** CR 509.3c/509.3d: "whenever
this creature becomes blocked" fires *once* however many creatures block it,
while "…becomes blocked **by a creature**" fires once for each creature the
phrase admits. Same trigger kind — the narrowing is the entire difference — and
it decides whether a following "that creature" names one object or several.
`_BLOCK_PAIR_EVENTS` was keyed on the kind alone, so it had to give both
spellings one answer, and either answer is wrong for the other:

* `creature_becomes_blocked` was in the set, so the **bare** form compiled.
  "Whenever this creature becomes blocked, destroy that creature at end of
  combat" was admitted, and the fire site hands an unnarrowed firing
  `blockers[:1]` — an arbitrary one of several. Not a crash and not a missing
  ability: a card that looks as though it resolved.
* `creature_blocks` was out of it, so the **narrowed** form refused. That is
  Infernal Medusa, which prints the two halves as separate sentences: it was
  reported supported with its first line lowering to nothing.

`binds_block_pair(event, event_subject)` replaces the set membership, and both
readers of it — the delayed destroy and round 15's recolour — ask it instead.

**Threading the narrowing is the actual work.** `event` has travelled down the
lowering chain since Gloom Sower, alongside `whole_effect`; `event_subject` now
travels with it, for the reason the docstring already gave for `event` — it is
simply true of every nested statement. Six helpers (`_lower_may`,
`_lower_steps`, the three where-clause lowerings, `_lower_one_of`) carry it
through, and it passes the same `whole_effect` gate the kind does: a nested
occurrence is not the ability's whole instruction, so a registry keyed on it
must see neither half.

**What it cost and what it bought.** No card moved from unsupported to
supported — LEG stays at 192 of 310 — because Medusa was already counted.
What moved is the honest measure: LEG hollow lines 19 → 18, LEG lowers 54.8% →
55.0% and executes 29.5% → 29.7%. A round whose whole yield is a supported card
starting to do what it prints, plus a shape that can no longer be printed and
silently mis-resolved. The parametrized table in `test_grammar_lowering.py`
holds all five spellings, because a gate that reads the kind alone passes any
test written about only one side of it.

**Numbers.** LEG 192 of 310 unchanged (61.9%); LEG lowers 54.8% → 55.0%,
executes 29.5% → 29.7%, hollow lines 19 → 18. Shipped pool unchanged at 734/734
and its coverage flat. Suite 7,151 → 7,158, full run green with every
`--check`; no hooks added or removed.

## LEG round 17: an ability is an object, and a cost is a symbol dict

*(2026-08-25.)* Rust and Ayesha Tanaka. Both print "Counter target activated
ability from an artifact source", and the machinery for the verb was already
there — `counter target activated ability` has compiled since Sublime
Epiphany. What was missing was everything the *narrowing* needed.

**An ability on the stack has one adjective, and it is not its own.** An
ability has no card and no type line (CR 113.7a), so "from an artifact source"
describes the permanent it came from. `ability_source_types` sits beside
`ability_kinds` on the filter and the handler tests it through `card_has_type`
— the reader that knows a card has *every* type its line names, so an artifact
creature's ability is caught by both spellings rather than by whichever
`primary_type` happens to return.

**The cost was the last bare number in the engine.** `engine/mana_payment.py`
says a cost is a symbol dict everywhere; the `mana_payment` prompt held an
`int`, which is why the counter lowering refused anything but generic with "no
counter flow offers this cost" and Ayesha's `{W}` had no way to arrive. The
prompt now carries a symbol dict and answers through `plan_payment`, the same
matcher casting uses.

The case that proves it is the one that looks redundant: **{R} in the pool must
not pay {W}**. One red mana is one mana, so the old count-based check would have
let the ability through and the white pip would have meant nothing — a card
working more often than it says, in the direction nothing crashes. The
empty-pool case passes against both representations, so it proves nothing on its
own.

**Two things the round found rather than built.** The `CounterAbility` docstring
asserted that an ability takes no "unless its controller pays" flow, "which is
offered to a spell's controller while the *spell* waits" — Ayesha Tanaka
disproves it, and what waits is a stack object either way. And the arming site
needs a `_new=True` marker for the headless path to drain the prompt; without it
the prompt armed, nobody answered, and the ability it was meant to gate resolved
anyway — the counter silently never happening, which is exactly what the first
run of the behavioural probe showed and no compile-time check could have.

`_parse_unless_pays` is now one reader for both clauses, since it is one clause:
the cost is offered to the countered *object's* controller while that object
waits (CR 118.3c).

**Flagged, not taken.** The non-interactive default spends only floating mana.
CR 605.3b would let a player tap lands to answer during resolution, and an
interactive seat already can — the prompt lists `tap` and `activate` among the
actions that answer it. Closing that for the auto path changes what every seeded
AI simulation does, so it is its own round with its own differential rather than
a rider on this one.

**Numbers.** LEG 192 → 194 of 310 (61.9% → 62.6%); LEG parse 59.4% → 59.9%,
lowers 55.0% → 55.5%, executes 29.7% → 30.2%. Shipped pool unchanged at 734/734.
Suite 7,158 → 7,163, full run green with every `--check`; no hooks added.

## LEG round 18: a narrowed shroud, and two clauses that had to stay two

*(2026-08-25.)* Bartel Runeaxe and Anti-Magic Aura. Both print "can't be the
target of …", and the class of spell is payload — Bartel names Aura spells,
Anti-Magic Aura names every spell, and the difference is one printed word.

**Not shroud with a filter bolted on.** Shroud (CR 702.18) stops every spell
*and* every ability; these stop one class of spell. `auras.py` already had the
sibling for the other half — Artifact Ward's "can't be the target of abilities
from artifact sources" — and CR 115.6 lets a card print either without the
other, so neither may answer for both. `engine/target_immunity.py` is the new
table, read by `Game._can_be_targeted`, which is the one predicate the cast
gate, the picker and the AI all reach.

**It is the mirror of a file that already existed, and I nearly lost that file
to find out.** `engine/target_restrictions.py` is what a *spell* prints about
its own targeting ("You can't choose an untapped creature as this spell's
target"); this is what a *permanent* prints about being aimed at. I wrote the
new module straight over it before checking the name was free, and only an
`ImportError` from `casting.py` — which imports `forbidden_target` — surfaced
it. Restored from git, renamed, and the two modules now open by naming each
other, because the pair is genuinely confusable.

**The two clauses on Anti-Magic Aura had to stay two rules.** "…can't be the
target of spells **and** can't be enchanted by other Auras" is one line, and the
second half prints no subject of its own. An Aura *spell* targets, so the first
clause already stops one being cast — but CR 303.4c makes an Aura already
attached illegal "as defined by its enchant ability **and other applicable
effects**", and 704.5m bins it. Only the second clause reaches that, and only a
sweep enforces it: Holy Strength on the creature was never targeted by anything.
So the reader splits the conjunction, carries the subject forward, and claims a
line only when it implements *every* clause — a card pairing one of these with a
sentence nothing reads stays unsupported rather than losing half its text.

The printed word "other" is load-bearing in the same place: without it
Anti-Magic Aura makes its own attachment illegal and the sweep bins it the turn
it lands, which is why the predicate takes the Aura asking.

**A gate and a runtime reader can normalize differently.** Bartel's line names
the card rather than saying "this creature", and the support gate collapses that
through `oracle._restriction_line` while the first runtime reader did not — so
the card compiled supported and protected nobody. Both go through the one
collapser now. The probe caught it; nothing else could have.

**Flagged, not taken.** Tetsuo Umezawa prints the same protection and is still
unsupported: its ability says "destroy target **tapped or blocking** creature",
and the noun parser's state-adjective union is hardcoded to the
attacking-or-blocking pair (a fused `attacking_or_blocking` payload key). That
is round 15's colour lesson again — a printed *or* is a union — and wants the
same treatment across four consumers. Wall of Shadows needs a spell to be asked
what it *can* target, which nothing models.

**Numbers.** LEG 194 → 196 of 310 (62.6% → 63.2%); LEG parse 59.9% → 60.1%,
lowers 55.5% → 55.7%, executes flat at 30.2% — both cards are enforced by
derivation rather than by an instruction, which is what "executes" counts.
Shipped pool unchanged at 734/734. Suite 7,163 → 7,169, full run green with
every `--check`; no hooks added.

## LEG round 19: a printed "or" is a union, and the pair was spelled in

*(2026-08-25.)* Tetsuo Umezawa, and the fused key that was keeping it out.

**The parser knew one pair.** "Target attacking **or** blocking creature" — the
four Legends pingers — was read by a branch that checked for exactly those two
words and set a boolean called `attacking_or_blocking`. Tetsuo prints "target
**tapped or blocking** creature": the same sentence with one word changed, and
it refused with "expected something to destroy" for a template the engine
implements. Round 15's colour union and round 14's threshold are the same
finding in the same place; by now the tell is a payload key whose *name* spells
out its own parameters.

`any_states` carries the printed words, and one `state_holds` table says what
each one asks of a permanent — shared with the singular narrowings beside it, so
a target restriction and a conditional buff cannot come to disagree about what
"blocking" means. Four consumers moved over: the payload, the matcher, the cast
gate and the picker.

**The picker had to carry it by value.** `_narrowing_flags` forwards its keys as
bare `True`, which is right for `attacking_only` and wrong the moment the key
has words in it — the first run flattened `["tapped","blocking"]` to `True` and
`legality.py` tried to iterate a boolean. Worth stating because the failure was
loud: a flag that quietly stayed True would have offered every creature as a
target and looked fine.

**Invented words in the test on purpose.** The parametrized table includes
"untapped or attacking" and a three-way union no card prints. A test naming only
the two real printings passes against the version that matched those two
literally — which is the false-negative shape `engine/land_animation.py`
documents, and the reason this round exists at all.

**Numbers.** LEG 196 → 197 of 310 (63.2% → 63.5%); LEG parse 60.1% → 60.3%,
lowers 55.7% → 55.9%, executes 30.2% → 30.4%. Shipped pool unchanged at 734/734.
Suite 7,169 → 7,177, full run green with every `--check`; no hooks added.

**Where the flags stand.** Wall of Shadows still needs a spell to be asked what
it *can* target, which nothing models. Round 17's CR 605.3b item is untouched:
the non-interactive payment default spends only floating mana, and closing that
changes every seeded AI simulation.

## LEG round 20: three worktrees at once, and two shipped cards that were lying

*(2026-08-25.)* The first genuinely parallel round: three agents in three
`git worktree` checkouts, one card group each, merged one branch at a time with
the full suite and every `--check` between merges. **Eleven cards**, the largest
round this set has had — and the two most valuable findings were not cards.

**The groups were chosen to touch different grammar families**, which is what
made the merges tractable: damage arithmetic, power/toughness and
characteristics, triggered abilities. Three conflicts total, and every one of
them was `tests/sets/test_legends_creatures.py`, exactly where SET_PLAYBOOK.md
says to expect them. Both engine conflicts (`ast/statements.py`'s union,
`lowering/characteristics.py`) were *additive* — each side had added something
the other could not have known about — so both sides survived. The test-file
conflict interleaved badly enough that hand-stitching was the wrong tool; the
three merge stages settle it exactly (theirs was a pure append over the base,
so the result is ours plus their new section).

### Cards
**Damage:** Psionic Entity, Syphon Soul, Jovial Evil, Hellfire.
**P/T:** Transmutation, Divine Offering, Wall of Wonder.
**Triggers:** Underworld Dreams, Mold Demon, Cosmic Horror, Elder Land Wurm.

Blood Lust was correctly declined: four pieces, none of them a P/T effect.

### Two shipped cards that reported supported and did the wrong thing
**Cleanse** — "Destroy all black creatures" compiled onto `destroy_all_creatures`,
whose payload is empty and whose scope is its own kind. The colour was dropped
and the card **wiped the entire board**, in a set the tracker calls 100%
supported. Hellfire's "nonblack" was heading into the same hole, which is the
only reason it surfaced. Narrowed sweeps now route to the filtered handler.

**Crumble's fused kind retired.** `destroy_artifact_controller_gains_mana_value`
existed only because "results carries values, not objects", and its own
docstring predicted its removal. The moment a general record of the destroyed
permanent's mana value existed, the grammar read Crumble's whole line and
`test_card_lines` failed — which is precisely what the grammar-before-hooks
ordering is built to do. One hook fewer, one positional read fewer.

### Three more "the narrowing was dropped" findings
* `_SEAT_SCOPED_EVENTS` narrows a `draws_card` trigger by the single word "you",
  so Underworld Dreams' "an **opponent** draws" would have fired on the wrong
  half of the table. The seat is payload now, and "that player" is frozen at the
  emit site — verified on a **three-player** board, because a targetless
  resolution's default seat is right with two players and wrong with three.
* `categories._PRODUCES` calls `deal_damage` a producer of `damage_dealt`, but
  the `each_opponent` / `each_player` loops never wrote the key. Syphon Soul's
  "life equal to the damage dealt this way" would have read zero.
* A durationless keyword loss was refused wholesale as "a static ability" —
  true of a printed static line, false of a trigger's one-shot effect
  (Elder Land Wurm).

### Numbers
LEG 197 → **208** of 310 (63.5% → 67.1%); LEG parse 60.3% → 62.9%, lowers 55.9%
→ 58.5%, executes 30.4% → 32.9%. Shipped by-catch from the two fixes above: ATQ
88.3% → 89.2%, 3ED 81.7% → 82.0%, ALL 82.1% → 82.2% parsed and 48.4% → 48.5%
executed. Hook reliance **falls** again: 82 → 81 of 734 cards, 89 → 88 entries.
Suite 7,177 → **7,217**. Shipped pool unchanged at 734/734, every `--check`
green.

### Promotion debt, recorded deliberately
`engine/effect_labels.py` carries **no** entries for this round's new kinds
(`remove_self_keyword`, `upkeep_pay_or_destroy_self`). `TRIGGERED_LABELS` is
guard-held to the *shipped* pool (`test_effect_labels.py` reads
`load_catalog()`), so an entry for a LEG-only kind fails while LEG is
`measured`. Same precedent as ATQ and M21, and the same as round 12's Wall of
Dust: the labels belong in the promotion commit.

### On running it this way
Three agents finished where an earlier attempt at four returned nothing. The
briefs mattered more than the count: each named the files the *other* agents
would touch, forbade `--accept` and tracker regeneration (three-way collisions
that buy nothing), and demanded a card be verified **in a game** rather than at
the compiler. That last rule is what produced Cleanse, the `_PRODUCES` gap and
the three-player seat check — none of which a compile-time gate would have said
a word about.

## LEG round 21: three more worktrees, and a sweep that would have taken the board

*(2026-08-25.)* The second parallel round, same shape: three agents, three
worktrees, merged one branch at a time with the full suite and every `--check`
between. **Twelve cards**, LEG 208 → 220.

**Groups:** static/continuous effects, counterspells narrowed by spell class,
library and hand manipulation. Three conflicts, every one of them a per-set test
file and every one a pure append over the merge base — the three-stage
reconstruction (`git show :1:/:2:/:3:`) settles those exactly, and hand-stitching
is the wrong tool for them.

### Cards
**Statics:** Living Plane, Dakkon Blackblade, Arcades Sabboth, Rabid Wombat, Kismet.
**Counters:** Avoid Fate, Ring of Immortals, Invoke Prejudice.
**Library:** Storm Seeker, Winds of Change, Visions, Land Tax.

Declined, correctly: **Mana Drain** (its second sentence is a delayed triggered
ability, CR 603.7 — the grammar has no production for "at the beginning of your
next \<step\>" at all) and **Recall** (a variable-count discard *plus* a
resolution-time repeated graveyard pick whose count is unknown until the discard
happens).

### A union across two axes
Avoid Fate and Ring of Immortals print "counter target **instant or Aura**
spell". "Instant" is a card type (CR 205.2) and "Aura" a subtype (CR 205.3), and
every matcher here ANDs `card_types` against `subtypes` — so recording the
phrase in both fields describes an instant that is *also* an Aura, a set nothing
is in. The card would have countered nothing while reporting supported. Each
alternative now carries the axis it was read on. The four tests that matter are
the discriminating ones: instant countered, Aura countered, a spell aimed at
someone else's permanent left alone, a sorcery left alone.

### Three pre-existing bugs
* **`destroy_all_matching` would have swept the board.** It resolved only the
  `"target"` attachment referent and fell through with `host = None` on anything
  else — which drops the relation and destroys *every* matching permanent.
  Latent while one referent existed; armed the moment a second was added. It now
  answers every referent the noun parser can produce and **returns** rather than
  widening. Same shape as round 20's Cleanse, one layer down.
* **`opponent_casts_spell` emitted no `cast_card`**, unlike its `spell_cast`
  sibling, so any opponent-scoped trigger whose effect is *about* the spell
  resolved with nothing to find and let it through. Nothing had asked until
  Invoke Prejudice did.
* **A counted search was two by construction.** `_parse_two_card_search` had
  "up to **two**" as a literal and required a destination per find, though the
  lowering already built one entry per find and the confirm flow answered them
  whole. Cultivate's payload is byte-identical after the generalisation.

### Two narrowings that could not be said
`LordBuffFilter` carried a *single* state qualifier, so Arcades Sabboth's "each
**untapped** creature you control … as long as it's **not attacking**" was
unsayable; it carries a tuple now, and the trailing clause folds into the
subject filter rather than being read as a condition — read as a condition, "it"
binds to the source and Arcades buffs its whole team whenever Arcades stays
home. And both `land_animation.py` and `characteristic_defining.py` read their
head noun through the land-*subtype* catalog, where the word "lands" does not
appear: Living Plane and Dakkon Blackblade were refused by a lookup table that
had no row for the general case.

### One guard deliberately widened
`test_grammar_derived_lines.py::pool_lines` read `load_catalog()` — the shipped
pool — so a derivation table written for a *measured* set's card was called dead
on the round that added it. It reads `include_measured=True` now. This is a
reachability question, not a coverage floor: the guard still fails on a table
that matches no card anywhere, and the alternative was writing every table after
promotion rather than with the card that needs it.

### Numbers
LEG 208 → **220** of 310 (67.1% → 71.0%); LEG parse 62.9% → 65.4%, lowers 58.5%
→ 61.0%, executes 32.9% → 35.5%. Shipped pool unchanged at 734/734 and its
coverage flat — this round bought a measured set's cards and fixed shipped
*latent* defects rather than adding shipped text. Suite 7,217 → **7,273**, every
`--check` green, no hooks added.

### Standing debt
`engine/effect_labels.py` still carries no entries for the LEG-only kinds
(`remove_self_keyword`, `upkeep_pay_or_destroy_self`, and this round's
`others_enter_tapped`): `TRIGGERED_LABELS` is guard-held to the shipped pool.
They belong in the promotion commit, with round 12's Wall of Dust.

New this round: `reorder_target_library_top`'s handler derives `may_shuffle` by
**substring-matching oracle text inside a handler**, which CLAUDE.md forbids
outright. Left alone deliberately — fixing it changes Natural Selection's
payload, and Natural Selection is *shipped*, so `behaviour_classes --check`
would drift with no `--accept` available mid-round. Promotion-time cleanup.

`engine/grammar/nouns.py` (998) and `engine/grammar/lowering/characteristics.py`
(997) are both within three lines of the 1,000-line guard. The next work landing
in either should split it, not shave comments — `names.py` split out of `nouns`
this round and absorbed exactly the growth that would otherwise have tripped the
guard one merge later.

## LEG debt round: two handlers stopped reading oracle text, two modules split

*(2026-08-25.)* No cards. Rounds 20 and 21 recorded four pieces of debt; this
pays the three that could be paid and establishes that the fourth cannot.

**Two handlers were re-reading printed text.** `reorder_target_library_top`
derived Natural Selection's optional shuffle by substring-matching the card's
own sentence at resolution, and the damage handler decided whether a target had
to be a creature by looking for the words "any target". Both facts are already
in the compiled program — the hook line can carry `may_shuffle`, and
`_describe_targets` has always recorded `quantifier: "any_target"` — so both
handlers now read the instruction. A handler that re-reads oracle text is a
second reading of a sentence the compiler already read, and the two drift.

`tests/engine/test_layer_reads.py`'s `PRINTED_TEXT_EXEMPTIONS` is a shrink-only
ratchet and it caught the leftover immediately: with the read gone the exemption
went stale, and the list is down to one entry (`global_statics.py`, which is a
genuine cycle — the text that defines a static cannot be read through it).

**`engine/effect_labels.py` is not debt, and the round proved it.** Rounds 20
and 21 both recorded the missing labels for LEG-only kinds as promotion debt.
Trying to pay it early — widening the guard's fixture to the measured sets, the
way `test_grammar_derived_lines` was widened in round 21 — caught 17 unlabelled
abilities and was the **wrong** move, so it was reverted. The two guards ask
different questions. The derived-lines one asks *is this table reachable*, which
is about the card that needed it. This one carries the vocabulary
`engine/parsing/` produced, so a card is not silently re-bucketed when the
grammar learns its line — and a card that never had a legacy rule has nothing to
carry. Seventeen entries restating the category default is what the sibling
guard calls "a special case pretending to be one". It stays a promotion task
because the promotion is when those cards acquire a bucket anyone reads.

**Two modules split, both at the guard.** `lowering/characteristics.py` (997)
lost its keyword half to `lowering/keywords.py`: CR 208 is what a creature's
power and toughness *are* (layer 7), CR 702 is an ability it *has* (layer 6),
and the two families shared no helper — only the module. It is now 793.

`nouns.py` (998) lost the ability-on-the-stack vocabulary to
`engine/grammar/abilities.py`. That cut needed one thing first: the new module
sits *below* `nouns` in the layer order, so it cannot reach `_singular` there.
`singular` and `GENERIC_NOUNS` moved down into `vocabulary`, which is where they
belonged — both are word lookup rather than parsing, and `nouns` re-exports them
under their old private names so its own body and `references` are untouched.
`nouns.py` is now 925.

**What is still near the guard**, recorded so the next round does not discover
it mid-merge: `lower.py` (982), `ast/_core.py` (976), `effects/cards.py` (959),
`lowering/board.py` (941), `lowering/_common.py` (902). `lower.py` is the
dispatch roof and will trip first.

**Numbers.** No card moved: LEG stays at 220 of 310 and the shipped pool at
734/734. Suite 7,273, unchanged — the two handler fixes are behaviour-preserving
by construction, and the splits move code without changing it. Every `--check`
green.

## LEG debt round 2: the last two outstanding items

*(2026-08-25.)* No cards. Both items rounds 13 and 17 deferred, and both turned
out smaller than the deferral assumed.

**CR 605.3b: the payment default now taps lands.** A counterspell's "unless its
controller pays" resolved by spending *floating mana only*, so a player holding
two untapped Mountains declined a `{2}` they could afford and lost the spell.
CR 605.3b lets a player activate a mana ability while paying a cost, and this
payment happens inside the counterspell's resolution with no priority window in
which to do it any other way — which is exactly the justification the sibling
`_optional_pay_plan` already carried for "you may pay". The counter payment was
the odd one out; both now ask one `_counter_payment_plan`, and the plan's lands
are tapped as well as its pips spent.

Round 17 deferred this as "a change to what every seeded AI simulation does".
**It changes none of them** — the LEA batch logs the same 443 interactions
before and after. The deferral was right to want a differential and wrong about
what it would show.

One regression test asserted the old behaviour outright: with two untapped
Mountains and `{2}` owed, "no mana available → the headless path counters". Its
comment said "no mana available" and it meant *no floating mana*. It now asserts
the payment, and a second case pins the genuinely-unable path with the lands
removed, so the two readings cannot be confused again.

**The Aura ETB row stopped being a wildcard.** `_TEMPLATES` claimed
`^when this (?:aura|enchantment) enters(?:,| ).+$` for
`_apply_aura_effect` — a method that performs exactly **two** entry texts by
bespoke matching. So "when this Aura enters, frobnicate the widget" was claimed
by code implementing nothing of the sort, and any Aura printing an entry effect
the engine cannot carry out reported supported and did nothing.

The comment beside the row said "never a wildcard" and meant the *subject*; the
effect half was open. The two rows that replace it are keyed to the substrings
`_apply_aura_effect` itself tests, so the gate and the dispatch read one rule.
Everything else falls through to `aura_compiled_trigger_claim`, which asks the
compiler whether the effect lowers — and refuses when it does not.

Measured before changing anything: of the nine Auras in the pool whose entry
line the wildcard matched, **seven were already claimed by the compiled path**
and only Animate Dead and Earthbind depended on it — precisely the two the
method implements. The differential was zero cards.

Getting the two patterns right took three attempts, and the failures were
informative: `_apply_aura_effect` tests its substrings against the **whole
card**, while a claim is asked per *line*, and Animate Dead's other half
("creature card in a graveyard") lives on the enchant line — already required by
the `aura_enchants` gate in front of that branch. The pattern carries the half a
line can answer for.

The guard is written with invented sentences, deliberately: every real printing
either lowers or is one of the two bespoke texts, so a test written from the
pool alone passes against the wildcard.

**Numbers.** No card moved: LEG 220 of 310, shipped pool 734/734. Suite 7,273 →
**7,276** (three new tests: one corrected regression, two new guards). Every
`--check` green. AI simulation identical.

## LEG round 22: a subsystem, five mechanisms for six cards, and a stale veto

*(2026-08-25.)* Third parallel round, and the first where a group's honest
deliverable was **machinery** rather than cards. Eleven cards, LEG 220 → 232.

**Delayed triggered abilities (CR 603.7) exist now.** There was no general
mechanism — only a list of bare dicts on `Game` with two hard-coded events read
by `entry.get(...)` in three places, plus a `destroy_at_end_of_combat` metadata
flag and a card hook. `engine/delayed_triggers.py` holds the entry as an object,
one fire routine, one expiry routine, and `DELAYED_EVENTS`: every event with a
fire site, guarded by a test that fails if a listed event is named nowhere else
in `engine/`. The three ad-hoc sites migrated onto it and four new fire sites
joined. CR 603.7b's "only once unless it has a stated duration" is a *field*,
not something a fire site decides.

`Choose target <noun>.` — the opener three of those cards share — parses only
when the sentence binding what it chose follows. A spell whose one instruction
chose a target and did nothing would otherwise report itself supported.

**"Prevent" was a verb again.** The playbook records that Legends' prevention
bucket needed four mechanisms across two rounds; this round's six cards needed
**five**. The generalisations are the value: a colour shield records a *set* of
colours (one shield either colour spends, not one per colour, and `Shield.color`
survives as a read-only property returning None for a multi-colour shield —
there is no one colour it is "the" shield of); the directional turn-long
shield's *width* is payload, so Horn of Deafening and Kry Shield are one
instruction one word apart; a `Shield` can carry a printed noun phrase matched
through `subject_matches` at damage time.

### Three pre-existing defects

* **A stale blanket veto.** `oracle.UNSUPPORTED_PATTERNS` refused any card whose
  text contained `"exchange control"`, naming no clause — and kept refusing
  *after* the clause was implemented. Gauntlets of Chaos compiled cleanly and
  was still rejected by that line. The tuple is empty now; every "exchange" card
  in the pool was audited and only Gauntlets flipped, with Juxtapose and Tempest
  Efreet still refusing and now naming their actual clause.
* **A declared producer that never wrote.** `_PRODUCES` lists
  `tap_target_permanent` as producing `tapped_permanents`, but only its
  several-target branch wrote the key. Frost Breath prints "up to two" and takes
  that branch, so nothing had ever exercised the singular one — Telekinesis's
  third sentence marked nothing while the card compiled clean. The `untap` twin
  had the identical hole.
* **A resolving spell carries no targets by the time it deals damage** — the
  stack object is popped before its instructions run. `Game.resolving_targets`
  is the seam, beside `resolving_seats`, for the same reason.

### Where the riders went

Two riders were folded into the production that holds their subject rather than
parsed as their own step, and both would otherwise have been board-wide sweeps:
Gauntlets' "destroy all Auras attached to them" (an Aura on a third permanent
must survive — asserted) and Glyph of Doom's blocked-set. That is the third
round running in which the dangerous shape was a narrowing that reads as
guarded because something *adjacent* to it is.

### Integration

Two conflicts, both additive AST unions or pure-append test files. One genuine
cross-branch collision: `_parse_bound_subject` moved from `statements` to
`phrases` and lost its underscore in one worktree while another wrote a call
against the old name — invisible to both agents, caught by the suite the moment
the branches met. That is what the serial merge is for.

`lowering/board.py` reached 1,007 lines when two branches' additions met, and
split along tap/untap (CR 701.20/701.21 — a permanent's *status*, orthogonal to
its existence and controller, which is what `board` otherwise covers). 711 now.

**`engine/grammar/lower.py` is at 995 and cannot be split the usual way.** Its
`_lower_where_x` family recurses into `lower_statement`, so moving it into
`lowering/` would import upward, which the layering guard forbids — and
shuffling helpers to shave lines is what that guard's own comment warns against.
What actually grows is `lower_statement`'s 374-line if-chain over node types,
one line per type. The shape that fixes it permanently is a **dict dispatch
keyed by node type**, which is the engine's own idiom everywhere else
(`EFFECT_HANDLERS[instruction.kind]`, "O(1) dict dispatch"). That is a
deliberate refactor of the hottest file and wants its own round, not an
integration afterthought.

**Numbers.** LEG 220 → **232** of 310 (71.0% → 74.8%); LEG parse 65.4% → 68.0%,
lowers 61.0% → 63.8%, executes 35.5% → 38.1%. ARN parse 69.4% → 71.3% by-catch.
Shipped pool unchanged at 734/734. Suite 7,276 → **7,351**, every `--check`
green, no hooks added.

**Not reached, and why:** Feint (a noun phrase narrowed by a relation to a
target chosen in the same sentence — a nested `TargetSpec` inside a filter);
Enchantment Alteration and Juxtapose (a permanent chosen on *resolution* with no
"target" printed, needing a new `PendingChoice` kind and its web plumbing — the
nearest prompt, `kudzu_reattach`, is index-keyed and Kudzu-named through to the
JS); Glyph of Delusion and Glyph of Reincarnation (the block record this round
added is there for them now, but each needs machinery beyond it).

## LEG round 23: a prompt is a value, and four dispatchers were narrower than their conditions

*(2026-08-25.)* Fourth parallel round. Eight cards, LEG 232 → 240, and two
structural splits done serially around the batch rather than inside it.

### Before the batch: lower.py
`lower.py` was at 995 and the previous round's journal proposed a dict dispatch.
On inspection that was the wrong fix — 82 of its 94 branches are table-able but
across **nine call signatures**, so a table would need an arg-spec vocabulary
and read worse than the if-chain. The real cut was the `where_x` family, which
that journal had ruled out because it recurses into `lower_statement`.

The recursion inverts. All four productions began with the *identical* call, and
each then does the same two things to an already-lowered sentence: check it
reads an X at all, then stamp the definition onto it. None of them cares how the
sentence was lowered — what differs is only what is counted. So the caller
lowers it and passes `inner` in, and the family drops a layer legitimately.
995 → 825, no behaviour change.

### The round
**Choices:** Enchantment Alteration, on a new general prompt.
**Triggers:** Whirling Dervish, Axelrod Gunnarson, Ichneumon Druid, Nicol Bolas.
**Templates:** Teleport, Energy Tap, Winter Blast.

**A permanent chosen at resolution is a *value*.** The new `permanent_choice`
prompt writes the answer's `permanent_id` into `context.results` under a key the
payload names — the channel `gain_control_until_eot` already reads a bound
permanent through. Everything after the choice is ordinary instructions in a
`sequence` reading that key, so a card that chooses a permanent and then
destroys it needs no new prompt, handler or `Game` field.
`permanent_choice_candidates` is one rule with three callers (arming, liveness
re-check, renderer), so the offered list and the checked list cannot drift.

### Five pre-existing defects
* **A dispatcher narrowed to the first card that reached it.**
  `creature_dealt_damage_by_self_dies` was dispatched only for
  `add_counter_to_self`, so Axelrod Gunnarson's sequence fired nowhere.
* **The cast record was written between the two cast announcements**, so every
  opponent-scoped ordinal counted a list missing the spell that fired it —
  Ichneumon Druid was exempting the *second* instant, not the first.
* **A false CR 603.4 gate still reached the stack:** `end_step.py` checked the
  intervening-if, then its catch-all scan enqueued the trigger anyway.
* **The single-target tap dropped "you control"** — it tested its noun phrase
  with the *pure* matcher behind a hand-written probe for three type-ish keys,
  so `controller` rode the payload and was ignored. Energy Tap would have tapped
  an opponent's creature and made its mana.
* **`X target creatures` never reached the several-targets branch** — the count
  was tested with `isinstance(int) and > 1`, but it is the string `"x"` until
  the spell is cast, so it tapped the first slot and dropped the rest. The
  `untap` twin beside it reads the same key correctly and never had the hole.

Two hooks also retired themselves: Pyramids' existed only because the filter
lacked a list-valued field, and once it had one `test_card_lines` failed on the
dead entry. 88 → 87 entries.

### A card declined for a reason that did not hold
Shelkin Brownie was left because my brief said "do not touch `effect_labels.py`"
and the agent read that as "a new activated kind is impossible". It is not: a
LEG activated card with an unlabelled kind compiles supported and passes every
guard, because the labels guard reads the **shipped** pool. Ayesha Tanaka landed
in round 17 as exactly that shape. The wording cost a card; a brief that states
a constraint should state its scope.

### And one an agent declined correctly, after building it
Floral Spuzzem was implemented, seen to compile "supported" while the destroy
found no target and the rider set its flag *after* damage, and then **reverted**.
Its rider needs the trigger to resolve before the combat damage step's
turn-based action, and `advance_combat_phase` does not wait on an owed prompt.
Reverting a working-looking card is the right call and the hardest one to make.

### After the batch: ast/_core.py
Three branches met at 1,007 lines, and both agents that hit it named it the
binding constraint — `ObjectFilter` and the `Condition` union both lived there,
so any new filter field *or* condition node needed the split first, and
Juxtapose was declined for exactly that.

The cut is the one question `_core` asks that nothing else in `_core` needs the
answer to. The rest is the vocabulary every node is built *from*; a condition is
built from all of it while none of it is built from a condition. Verified rather
than assumed: nothing defined above `Controls` references any of the 18
condition classes. Amounts would have been the other candidate and **cannot**
move — `Comparison` takes an `Amount` and `ObjectFilter` takes a `Comparison`,
so amounts and nouns reference each other. 1,007 → 775.

### Numbers
LEG 232 → **240** of 310 (74.8% → 77.4%); shipped pool 734/734 and ALL parse
82.2% → 82.5%. Hook entries 88 → 87. Suite 7,351 → **7,383**, every `--check`
green.

### Standing debt
The support gate **admits a card whose trigger is dead** when another trigger on
it is supported (`if triggered and not any_supported_trigger`). That is how
Nicol Bolas became "supported" with a trigger that did nothing; the agent made
the trigger work rather than fix the gate. Worth its own round — it is the same
shape as `--hollow-lines`, one level down.

`derive_cast_spec` emits no `max_targets` for an X-counted target description,
so the picker offers one target for "X target creatures". Shared with shipped,
verified Candelabra of Tawnos, so not a regression — but the web picker
under-delivers Winter Blast.
