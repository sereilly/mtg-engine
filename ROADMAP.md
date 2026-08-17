# Scaling Roadmap

Target: grow the card pool from 388 unique cards (LEA/LEB/2ED/ARN/3ED shipped,
M21 measured at 220/285) to the full release line - **137 sets, 33,594
printings, 26,113 unique cards** per `set_progress.json`.

A chronological engineering journal, kept to the last three rounds. Everything
before them — the founding audit, the parser migration (finished:
`engine/parsing/` is deleted and `engine/grammar/` is the only parser), the
per-set narratives, and M21 rounds 1–62 — lives in git history at and before
commit `0801c4c`. What those rounds established that outlives their narrative is
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

## Round 63: the prompt that did not need building

*(2026-08-16.)* M21 **218 → 219** — Alchemist's Gift. The round is mostly about
what it did **not** add.

**"Gains your choice of deathtouch or lifelink" reads as a choice at
resolution** (CR 609.3), and the obvious shape for it is a new pending-choice
kind: offer the keywords, take a default for a seat that is not asked, grant the
answer. That is one registry entry, one resolver, one web renderer and one AI
default — and every line of it already exists. **A choice between two effects is
`choose_one`**, the composition seam in `engine/handlers/control_flow.py` that a
modal triggered ability uses, and the two grants are just its two modes. The
card needed no prompt, no handler and no `Game` field; it needed a lowering that
says the keywords are *alternatives*.

That distinction is the whole of the parse work, and it has to be recorded where
the words still are. "Gains deathtouch **and** lifelink" and "gains your choice
of deathtouch **or** lifelink" reach the keyword reader as the same tuple —
`_parse_keyword_list` treats the conjunctions alike, correctly, because for a
list they mean the same thing. One flag on the AST node is what stops the card
granting both.

Lowering each alternative back through the same function is the other half:
a keyword the engine cannot grant refuses the whole line rather than being
offered as an option that would do nothing. And the non-interactive default is
*inherited* rather than invented — `choose_one` already states it as the first
printed option, a policy and not a valuation.

**Two things were checked and turned out not to be affordable**, which is worth
recording so the next round does not re-derive them:

- **Carrion Grub** looked like a small aggregate — "+X/+0, where X is the
  **greatest power** among creature cards in your graveyard" is a maximum where
  the where-clause admits only a count. It is not: the pump has no duration, so
  the card wants a *static* layer-7 P/T contribution with a computed X, and the
  aggregate is the small half.
- **Sanctum of Fruitful Harvest** still wants more than the colour choice this
  round could have given it. "Add X mana of any one color" reaches a legacy
  text-keyed handler that adds exactly one mana and picks its colour from a
  `preferred_color` the *activation* path injects; a counted, chosen-colour add
  is a rewrite of that path rather than a prompt.

`choose_one` also had to become a *wrapper* for the categories reader: its
options are `{label, instruction}` pairs rather than a bare tuple, so the
migration category of a choice is its options' — giving it one of its own would
say the choosing is the effect.

Suite **5,123** at 23.0s, every `--check` green, shipped pool 388/388, AI
simulation byte-identical at 443 interactions. Three of the four new tests were
watched to fail on the round-62 engine; the fourth is the control that "your
choice of" with one keyword refuses.

**Next:**

- **The Shrine cycle**, with Fruitful Harvest's real cost now measured (above):
  Shattered Heights' discard cost (whose "a land card or **Shrine** card" is a
  noun-phrase *union* the parser has no production for), Tranquil Light's
  per-Shrine cost reduction, Sanctum of All's two-zone search and
  trigger-doubling static.
- **A static P/T contribution with a computed X** — Carrion Grub, Kinetic
  Augur's characteristic-defining power, and Jolrael's team base-P/T are three
  readings of the same missing shape.
- **A reflexive trigger** — "you may pay {1}. **When you do**, …" (Tolarian
  Kraken), deliberately refused in round 60.
- The legend rule from round 49.

## Round 64: one evaluator for a computed amount

*(2026-08-16.)* M21 **219 → 220** — Carrion Grub, whose one line needed two
things the engine had no shape for and one it had two of.

**A maximum is not a count.** "…where X is the **greatest power among** creature
cards in your graveyard" reads the same objects as "the number of" and asks a
different question, so it gets its own definition node beside `CountOf` — the
distinction round 55 drew for the death count, for the same reason: a lowering
that saw only a filter would have to guess.

**A layer-7c contribution whose size is computed.** A pump with no duration is a
continuous effect, which is why the general case refuses; but one on the
ability's own source *is* the CR 613 layer 7c contribution the P/T refresh
already rebuilds on every recompute. What made it unreachable was not the layer,
it was having no way to say how big it is —
`engine/static_bonuses.py`'s table can carry a bonus's condition and its size,
and here the size is the whole variable part. The refusal now routes: a durationless
self-pump *with* an `x_definition` lowers to `dynamic_pt_bonus` and the refresh
resolves it.

**And the thing there were two of.** The pump handler carried its own graveyard
counter, hardcoded to that zone, reading `card_types` where every other reader
of a computed amount says `filter` — so "the number of creature cards in your
graveyard" meant two things depending on which sentence it was printed in. Both
sides go through `evaluate_count` now, and the split that made that possible is
the honest one: **a resolution knows whose zone to read and a continuous
recompute does not**, so the context-aware wrapper is one line on top of an
evaluator that takes an owner. The graveyard-only restriction on the pump was
its own counter talking; with the shared evaluator behind it the zone is data
like everything else.

Two smaller decisions worth their lines. A **negated** computed bonus refuses:
the refresh resolves the amount and nothing carries a sign for it, so "-X/-0"
would make a creature bigger where the card shrinks it. And the creature
compiler's static gate asks the grammar for a **short list** of kinds rather
than for anything it can read — a creature's static lines have been gated by
that whitelist since the compiler was written, and opening it to every
production at once is a change with its own blast radius.

Suite **5,127** at 23.1s, every `--check` green, shipped pool 388/388, AI
simulation byte-identical at 443 interactions. Three of the four new tests were
watched to fail on the round-63 engine; the fourth is the control that a
graveyard of noncreature cards leaves the printed 0/5 body alone. One older test
had to drop an assertion rather than change it — it pinned Carrion Grub as
unsupported *while* its mill line worked, which was true and is not.

**Next:**

- **The other two readings of the same shape.** Kinetic Augur's power "is equal
  to the number of instant and sorcery cards in your graveyard" is layer 7a
  (characteristic-defining) where this was 7c, and `dynamic_pt_count`'s payload
  vocabulary — battlefield-only, both stats — is what stands between them; the
  card is also held up by its second line. Jolrael's "creatures you control have
  base power and toughness X/X until end of turn" is layer 7b over a *team*,
  which has no handler at all.
- **The Shrine cycle**: Shattered Heights' discard cost (a noun-phrase *union*),
  Tranquil Light's per-Shrine cost reduction, Sanctum of All's two-zone search
  and trigger-doubling static, and Fruitful Harvest's counted any-colour mana
  (round 63 measured it: a legacy text-keyed handler that adds exactly one).
- **A reflexive trigger** (Tolarian Kraken), then the legend rule from round 49.

## Round 65: the duration in front, and a word that was being dropped

*(2026-08-16.)* M21 **220 â†’ 220** â€” Rookie Mistake in, Selfless Savior out. The
flat number is the round, in the sense rounds 12â€“14 and 16 established: a card
left because it was playing wider than it prints.

**The card was scheduled for the wrong reason, and the fix was one probe away.**
"Until end of turn, target creature gets +0/+2 and **another target** creature
gets -2/-0" was ranked as a multi-targeting gap. It is not: the second target has
parsed since round 40 (`TargetSpec.distinct_from_prior`), and the sentence join
already builds two statements. The actual first refusal is the **leading duration
adverbial** â€” `Until end of turn, target creature gets +0/+2.` refuses on its own
with the identical message, and it is card-independent. Sorting the backlog by
the *reason string* would have had the fuser written first and the real blocker
discovered underneath it.

**A leading duration is distributed, not stored.** The trailing spelling attaches
to the clause it follows, so the front-position one has to reach every effect
behind it; a wrapper node holding it would be a second place to ask what a
statement's duration is. It refuses rather than dropping in three shapes â€” a
statement with no duration field, a statement already printing a different one,
and any sequence containing either â€” because a dropped "until end of turn" is a
permanent effect the card never printed. The production is placed **after**
`_parse_cast_permission`, which prints the same prefix and reads it itself:
ahead of it, both Chandras go unsupported. That ordering has its own test.

**Two chosen creatures in one sentence cannot be two steps.** Every single-target
handler resolves through `_one_choice`, which reads the first entry of the target
list â€” so lowered as a `sequence` the card would compile supported and put both
boosts on one creature. It fuses to one `pump_targets_until_eot` carrying a slot
per clause, the third member of the family `target_bites_target` and
`prepare_then_interact` opened. The printed "another" rides as `distinct` beside
per-slot `filters`, not folded into a filter: it is a relation between two slots,
and `permanent_matches_filter` tests one permanent, so it could never answer.

**The slots are resolved positionally, and that needed a third resolver.**
`resolve_target_permanents` *compacts* â€” it drops a decayed slot without padding
â€” so `chosen[1]` becomes `chosen[0]` the moment the first target leaves. Primal
Might and Hunter's Edge survive that only because their slot filters are
disjoint and the impostor is rejected; Rookie Mistake's two slots are both a bare
"target creature", where the surviving creature would take the other slot's
effect. `resolve_target_slots` pads instead. (`prepare_then_interact` still reads
the compacting one. It is correct today by that accident of the pool and wants
moving over with a regression test of its own.)

**And the word that was being dropped.** `parse_coverage.py`'s deletion probe
reports `('another',)` on Selfless Savior â€” the emitted filter excluded nothing,
so the picker offered the Savior as the target of "another target creature you
control", an illegal choice a player could announce, whose cost then sacrificed
it and whose ability then fizzled. CR 601.2c is why the word has to be said at
all: two instances of "target" may otherwise name the same object. A
one-recipient description has nowhere to record which *other* choice this one
must differ from, so it now refuses. The alternative â€” reading a sole target's
"another" as CR's source exclusion â€” is a larger change that conflates two
meanings the AST deliberately separates, and it is the next round's, written up
in the spec.

Landed in dependency order with the grammar **last**, so at no intermediate point
was the card castable with half its targets collected. That order was load-
bearing twice: without the AI's per-slot side the AI put both targets on its own
board (measured `[0, 1]`, seat 0 â€” it shrank its own creature), and the browser
picker reset the selection on a click on the second board, so a human could never
pump one of theirs and shrink one of the opponent's. Which slot wants which board
is *derived* â€” the sign of the slot's P/T delta â€” never a name.

One finding taken from the same measurement and fixed here, because it is
unambiguous where the above is not: **`exclude_self` was honoured at resolution
and ignored by every picker.** Basri's Acolyte's "up to two **other** target
creatures you control" offered the Acolyte; so did Barrin and Brash Taunter. All
three handlers already refuse the source. `legality.py` has honoured
`exclude_source` all along â€” nothing read the filter key into it. One line.

Suite **5,138** green, every `--check` gate green, shipped pool 388/388, AI
simulation byte-identical at 443 interactions. Ten of the eleven new tests were
watched to fail on the round-64 engine; the eleventh is the control that both
Chandras keep their cast permissions.

**Next:**

- **"Another" as a source exclusion**, the alternative above: translate
  `distinct_from_prior` on a sole target to `exclude_self` rather than refusing,
  which returns Selfless Savior and covers Subira's and Niambi's same drop. It
  needs a guard separating it from the two-slot meaning first.
- **The headless AI simulator throws its chosen permanent target away.**
  `grep target_permanent engine/ai_simulator.py` returns nothing, so every
  targeted-permanent spell in a seeded run resolves through a handler fallback,
  and a several-target spell resolves to *nothing at all*. Latent for the shipped
  pool, live for M21, and live for the shipped pool the day M21 promotes. Fixing
  it moves the 443-interaction baseline, which is why it is recorded rather than
  folded in here.
- The Shrine cycle, a static P/T contribution with a computed X (Kinetic Augur,
  Jolrael), a reflexive trigger (Tolarian Kraken), then the legend rule.
