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

## Round 113: three Auras that reported supported and did nothing

*(2026-08-18.)* M21 **262 → 263** — Faith's Fetters.

> Enchant permanent
> When this Aura enters, you gain 4 life.
> Enchanted permanent can't attack or block, and its activated abilities can't
> be activated unless they're mana abilities.

One card, and it needed four things — three of which were defects it merely
walked into.

**The restriction table and the support gate were two copies of one list.**
Every pattern in `_RESTRICTIONS` was also written out in `_TEMPLATES`: one
deciding what an Aura *does*, one deciding whether the card is supported. Adding
Faith's Fetters to the first made the restriction derive perfectly, apply
perfectly, and the card still reported unsupported — the exact failure this
file's other comments keep describing. `aura_effect_claim` now falls through to
`aura_continuous_claim`, which asks the derivation tables, and the six duplicated
entries are gone.

**The attach path was a cascade of per-noun branches** — creature, land, Wall,
artifact, enchantment — each re-deriving "does this permanent answer the enchant
clause?" from the noun it was written for. A sixth noun needed a sixth branch, so
"Enchant **permanent**" attached to nothing and the Aura went to the graveyard as
though its target had left. The general branch asks
`permanent_matches_enchant_noun`, which is the question the *cast* already
answered; a seventh noun needs no code.

Its entry guard was a third reading of the same thing, and a worse one: it
searched for a `spell_pattern` instruction whose value begins "enchant", which
depends on the rest of the card. Faith's Fetters compiles a life-gain trigger, so
its spell patterns are about life, and the function returned before the cascade
could run.

**An Aura's ordinary entry trigger fired nowhere.** The resolution path skipped
the generic enters-the-battlefield trigger for *every* Aura, on the strength of
the two whose entry text `_apply_aura_effect` performs itself (Animate Dead's
reanimation, Earthbind's conditional damage). So an Aura whose entry trigger
compiled to a perfectly ordinary instruction did nothing at all — **Rousing Read
drew no cards, Setessan Training drew none**, both reporting supported, both
shipped in the measured set. `_apply_aura_effect` now *returns* whether it ran
the entry text and the caller does the general thing otherwise, after the attach
rather than before it.

**And "This creature can't block." was enforced nowhere at all.** It compiles to
a `cant_block` instruction and reports the card supported;
`engine/combat_restrictions.py`'s comment named `phases/declare_blockers_step` as
the enforcement site and that file had never mentioned the kind. Every question
in `_can_block_attacker` is about the *attacker*, which is how a restriction on
the blocker came to have no home. No card in the pool prints the bare line today,
which is why it went unnoticed — it is one of the commonest templates in Magic,
and Pursued Whale's token prints it.

CR 605.1a's mana exception is part of the restriction's *name*, because the
clause without it is strictly harsher: an Aura that stopped a land tapping for
mana would lock its controller out of the game rather than shut off one ability.
`is_mana_ability` is one predicate asked by the one caller that needs it.

Whole-pool diff: **one card**. Suite green, every `--check` gate green, shipped
pool 388/388, AI simulation byte-identical at 443 interactions, **zero hooks
added**. Eleven new tests, nine watched to fail on the round-112 engine; the two
that pass there carry an in-test control, because "the ability still worked" is
also what an unattached Aura looks like.

## Round 114: one card, two prices

*(2026-08-18.)* M21 **263 → 264** — Demonic Embrace.

> Enchant creature
> Enchanted creature gets +3/+1, has flying, and is a Demon in addition to its
> other types.
> You may cast this card from your graveyard by paying 3 life and discarding a
> card in addition to paying its other costs.

The first two lines were already claimed; the card was that third sentence, and
it is **two different things said once**: a permission to cast from a zone the
rules close, and the costs of doing so.

**A permission the card grants itself.** Every grant `cast_permissions.py` held
was a `CastPermission` some effect put on `game.cast_permissions` and something
later took away. This one is a static ability of the card while it sits in the
graveyard (CR 113.6d) — nothing grants it, nothing expires it, and there is no
state at all — so it is derived from the text on demand, the shape
`cast_restrictions.py` already uses for a printed timing gate. Asked *after* the
stored grants, because a granted permission may waive a cost or open a wider
zone and answering with this first would hide it.

**The cost belongs to the zone, not to the card.** Demonic Embrace costs
{1}{B}{B} from the hand and {1}{B}{B} plus 3 life plus a card from the
graveyard — the same card, so `AdditionalCost` grew a `from_zone`, and an
unmarked cost ("as an additional cost to cast this spell") still applies
wherever the spell is cast from. It also grew `pay_life`: CR 118.4 lets a player
pay life down to 0 and no further, and CR 601.2h then makes an unpayable cost an
uncastable spell rather than a free one, so exactly 3 life pays and 2 refuses.

**Two readers of one sentence, which is normally the bug.** The zone half is
read by `cast_permissions.self_permission_zone` and the cost half by
`cast_costs._self_permission_cost`. They are allowed to share a line because
they answer different questions of it — *is the zone open?*, which the cast path
needs before it will look outside the hand, and *what must be paid?*, which it
needs after — and a test holds both to the same line, so there can be no
permission with no costs attached nor costs with no permission behind them.

Every clause of the cost list must be read or the whole line is refused. A
sentence naming something the table cannot charge ("…and sacrificing a Zombie")
leaves the card unsupported rather than castable from the graveyard for less
than it prints.

Whole-pool diff: **one card**. Suite green, every `--check` gate green, shipped
pool 388/388, AI simulation byte-identical at 443 interactions, **zero hooks
added**. Eight new tests, all watched to fail on the round-113 engine.

## Round 115: a trigger that fired from one place only

*(2026-08-18.)* M21 **264 → 265** — Archfiend's Vessel.

> Lifelink
> When this creature enters, if it entered from your graveyard or you cast it
> from your graveyard, exile it. If you do, create a 5/5 black Demon creature
> token with flying.

Four pieces, and the fourth is a defect the card merely walked into.

**"Exile it" is not a target.** Every exile the engine had resolved a *chosen*
permanent, so an ability exiling its own source had no lowering at all. It gets
its own instruction kind rather than a flag on the targeted exile — a handler
that resolves a target and one that reads `context.source_permanent` share
nothing beyond the move — and a source already gone exiles nothing rather than
falling back to a scan, which would exile whichever look-alike it reached first.

**"If you do" after an action that was not optional.** The fold existed only for
a `May`, where the branch is a consequence of the player's decision. Here the
exile is compulsory and the branch asks whether it *took place* (CR 608.2b's "as
much as possible"), so it lowers to an ordinary `if_then` whose condition reads
the record the exile wrote. The pairing with "the step before it" is made in
`_lower_steps`, the one place that knows both which step that was and what it
records — a field on the node would have been a second copy of `_PRODUCES`.

**"Entered from" and "you cast it from" are two events, not one.** A permanent
put onto the battlefield from a graveyard and a permanent spell cast from a
graveyard leave the same card in the same place by different routes, and the
card names both. So the entry seam stamps where the permanent came from, the
cast stamps the zone the spell was cast from, and the condition asks each. `None`
means the caller did not say — the same defaulting as round 111's `was_cast`,
and one more fact about an entry that two different rules now ask.

**And a permanent's own entry trigger fired from exactly one place: the
resolution of a permanent *spell*.** Every other route onto the battlefield — a
reanimation, a token, an effect putting a card into play — never fired it. So a
reanimated Archfiend's Vessel made no Demon, and a Niambi put into play returned
nothing; both compile the ability perfectly and nothing ran it. The seam now
fires it, with the cast path keeping its own call because it has the caster's
cast-time target choice to thread through (CR 601.2c) and an entry from a
graveyard has no equivalent. `was_cast` is what keeps the two from both firing —
the same flag CR 701.5a needed for Containment Priest, one fact about an entry
asked by two rules.

The suite passed that change unmodified and the AI simulation stayed
byte-identical, which is the measurement that made it a fix rather than a
gamble.

Whole-pool diff: **one card**. Suite green, every `--check` gate green, shipped
pool 388/388, AI simulation byte-identical at 443 interactions, **zero hooks
added**. Seven new tests, all watched to fail on the round-114 engine.
