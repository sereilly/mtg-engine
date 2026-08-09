# Scaling Roadmap

Target: grow the card pool from 369 unique cards (LEA/LEB/2ED/ARN) to the full
release line — **137 sets, 33,594 printings, 26,113 unique cards** per
`set_progress.json`.

This document records the audit that motivated the work and the phased plan
that follows from it. Phase 1 is done; phases 2–8 are not yet started.

---

## Why: what the audit found

The engine's registry architecture is real and disciplined — 168 parse rules,
121 effect handlers, a "no card names outside `card_hooks.py`" rule that holds
to within five sites, a 3,100-test suite that runs in under ten seconds, and a
set of guard tests (parse coverage with a deletion probe, CR-citation checking,
trigger-table shadowing) that are unusually strong for a project this size.
None of that is what limits scale. Three things do.

### 1. The parser needed roughly one hand-written rule per two cards

168 `@parse_rule` functions covered 369 cards, and 133 of them were literal
substring matches — several encoding whole card texts. Extrapolated naively,
30,000 cards implies well over ten thousand rules, each with a hand-picked
global precedence integer in one shared ordering space. *(143 remain as of
phase 3; the count now falls as categories migrate.)*

Worse than the volume was the failure mode. Rules matched a *substring* and
discarded the rest:

- A non-creature card's entire text was collapsed to one string and given to
  the first matching rule, so `"Draw a card. Each player discards a card."`
  compiled to just the draw.
- `parse_target_filter` knew four creature subtypes (`wall`, `elephant`,
  `djinn`, `efreet`) and dropped every other restriction, so "destroy target
  creature with flying" and "destroy target creature" produced identical
  instructions — while the card still reported as **supported**.
- CR 603.4 intervening-if conditions were dropped entirely, so conditional
  triggers always fired.
- "You may pay {2}" became unconditional.

Silent wrongness, not errors. The parse-coverage deletion probe was built to
catch this class empirically, and it works — but it is a detector for a
structural problem, not a fix.

### 2. Effects could not compose, so instruction kinds grew combinatorially

`OracleProgram` delivered exactly one instruction per spell and
`_apply_spell_text` executed exactly one. Any card doing two things therefore
needed a *fused kind*: `deal_damage_and_gain_life`,
`deal_damage_and_self_damage`, `grant_islandwalk_and_linked_destroy`, and 25
more. **28 of 120 instruction kinds were conjunctions** — N effects × M riders
produces N×M kinds, which is the dominant cost at scale.

### 3. Several correctness mechanisms were per-call-site rather than central

- **CR 704.5g lethal damage was not a state-based action.** Destruction
  happened only when an effect called `_destroy_marked_creatures()` by hand —
  nine call sites, and any tenth that forgot left a lethally damaged creature
  alive.
- **Three parsers of the same oracle text**: `engine/parsing/`, the 937-line
  `engine/legality.py` (re-classifying targets from raw text for the UI), and
  ~251 inline `.lower()` probes scattered through the engine. They must agree
  forever, per card.
- **No trigger event bus** — 23 hand-placed fire sites; seven parsed trigger
  kinds (`spell_cast`, `creature_enters`, …) had no dispatcher at all, so those
  cards were routed through name-keyed hooks instead.
- **No CR 613 layer system** — `pt.py` covers layer 7 with last-write-wins
  semantics and destructive accumulation; layers 1–6 are ad-hoc metadata flags.
- **Twenty one-card `pending_*` fields** on `Game` with 22 bespoke `confirm_*`
  methods and 25 web endpoints.

### 4. Data and process constraints outside the engine

*(All but the last resolved in phase 2 — kept here as the record of what the
audit found.)*

- `cards/*.json` were raw Scryfall dumps: 57+ fields of which ~63% were never
  read (including stale `prices`), retained whole in `CardDefinition.raw` at
  **29 KB resident per card** — roughly 780 MB at 26k unique cards.
- **Zero layout support.** Split/flip/DFC/adventure cards would load as
  blank-text vanillas and be classified *supported*. `*` power/toughness parsed
  to `0`, so Nightmare would die to state-based actions.
- Reprints deduped by name, first-path-wins, and `card.raw["set"]` was whichever
  set loaded first — City in a Bottle keyed off exactly that and would break on
  the first reprint set (3ED is next in line).
- The set list was duplicated in six-plus places.
- **No CI.** Every guard above ran only when a human remembered.
- The comprehensive-cast sweep is hardcoded to `cards/LEA_cards.json`; ARN has
  no sweep, and `ARCHITECTURE.md` claimed otherwise. **Still open — phase 8.**

---

## Approach: a grammar front end, migrated strangler-fig

The end state is a real parser: tokenizer → recursive-descent grammar over
Magic's card templating → typed AST → lowered to the existing
`OracleInstruction` IR, executed by the existing effect handlers. The flat
`@parse_rule` registry is deleted category by category as the grammar takes
over.

Two properties make this tractable rather than a big-bang rewrite:

**Full token consumption.** A production that matches must account for every
token of its line; leftovers raise `GrammarError`. "Parsed" therefore means
"understood in full". A grammar gap is a *loud* failure (card unsupported, with
the offending clause named) and never a quiet mis-resolution. This is the
structural fix for the bug class the deletion probe detects empirically — and
the probe stays on anyway.

**Category gating.** The grammar runs on every line from day one, but its
output is only *used* when every category it lowered to is switched on in
`GRAMMAR_CATEGORIES`. Everything else falls back to the legacy rules untouched.
So new grammar work is exercised against the whole pool while still unused,
enabling a category is a one-line change made after its differential guard is
already green, and the legacy rules for a category are deleted only once the
ratchet shows the grammar claims every line they used to.

Progress is tracked in `GRAMMAR_COVERAGE.md` with floors in
`scripts/grammar_ratchet.json`, guarded by
`tests/engine/test_grammar_ratchet.py`.

---

## Phase 1 — grammar foundation ✅ done

- **`engine/grammar/`** — `lexer` (P/T as one token, source spans, card
  self-reference collapsed to a `SELF` token), `vocabulary` (350 creature types
  and 220 keywords loaded from `data/vocabulary/`, fetched by
  `scripts/fetch_vocabulary.py` — replacing the 4-entry subtype tuple), `ast`
  (full node inventory, append-only), `amounts`, `nouns`, `parser`, `lower`.
- **Composition in the IR** — a new `sequence` instruction plus `if_then`,
  `may`, and `for_each` in `engine/handlers/control_flow.py`. A resolution
  scratchpad (`OracleExecutionContext.results`) lets one instruction read what
  an earlier one did, which is what makes "deals X damage… you gain that much
  life" two composable instructions instead of a fused kind.
- **Damage and pump migrated** — 46 cards now execute through the grammar,
  including the decomposition of `deal_damage_and_self_damage`.
- **CR 704.5g/h moved into the state-based-action loop**, with regeneration
  correctly replacing the destruction and clearing marked damage. The nine
  manual `_destroy_marked_creatures()` calls remain (idempotent) and are
  removed in phase 4.
- **Guards** — grammar-vs-legacy differential over the whole pool with
  documented `ACCEPTED_DIFFS`, AST deletion-probe property test, lexer/parser/
  lowering goldens, coverage ratchet, and CR-cited SBA regressions.

Baseline: 25.3% of lines parsed, 19.0% lowered, 8.3% executed.

---

## Phase 2 — card data, ingestion, and CI ✅ done

- **`scripts/ingest_set.py`** projects a set onto the ~23 fields the engine and
  web layer actually read. `--from-existing` (default) prunes the committed
  snapshot with no network, so oracle text cannot drift; `--fetch` downloads a
  set the repo doesn't have yet. All four sets converted: **66% smaller on
  disk**, and **29.1 → 4.8 KB resident per card** (projected 122 MB at 26k
  unique cards, down from ~780 MB).
- **`cards/manifest.json`** is the single ordered set registry. `web/app.py`,
  `tests/conftest.py`, `scripts/parse_coverage.py`, and
  `scripts/grammar_coverage.py` all read it via
  `engine.card_loader.manifest_set_paths()`.
- **Typed `CardDefinition` fields** — `power`/`toughness`/`loyalty` (kept as
  printed strings), `layout`, `faces`, `oracle_id`, `set_code`,
  `collector_number`, `printings`. `base_power`/`base_toughness` return `None`
  for a variable stat rather than 0, so Nightmare and friends are recognized as
  characteristic-defining rather than 0/0.
- **Layout gate** — any non-single-face layout compiles as explicitly
  unsupported, naming the layout. Split/transform/adventure cards can no longer
  load as blank-text vanillas.
- **Reprint identity** — dedupe by `oracle_id`, with every printing recorded in
  order. City in a Bottle reads `original_printing`, so appending a reprint set
  cannot change which cards it bans.
- **CI** (`.github/workflows/ci.yml`) runs the suite, a 20-second suite-time
  budget, all four guard scripts in `--check` mode, and a staleness check that
  the generated trackers are committed. `requirements.txt` pins the versions.
- **Migration guard:** all 369 `OracleProgram`s verified byte-identical before
  and after conversion; `tests/engine/test_card_format.py` holds the format,
  layout, variable-P/T, and reprint-identity invariants going forward.

Still open from this phase's original scope: `scripts/retrieve_oracle.py`,
`run_duel.py`, `simulate_ai_games.py`, `support_report.py`, and
`tests/helpers.py` still default to LEA-only paths. That is deliberate — they
are single-set tools by design — but they should take a `--set` argument
resolved through the manifest rather than a hardcoded filename.

## Phase 3 — grammar wave 2, first legacy deletions ✅ done

**25 legacy parse rules deleted** (168 → 143). Coverage went from 25.3% / 19.0%
/ 8.3% (parsed / lowered / executed) to **46.1% / 29.1% / 14.0%**.

New productions: destroy, tap/untap, regenerate, counter, draw, discard, add
mana, `Enchant <noun>`, multi-type noun phrases ("artifact or enchantment",
"artifact, creature, or land"), comma-separated adjectives, pluralized
subtypes, and single modal bullets — `parse_modal_options` now tries the
grammar per mode.

Categories switched on: **destruction** and **tapping**. Destruction is the
clearest illustration of the whole exercise: five rules whose relative
precedence had to be hand-numbered so the sweeps outranked the targeted form
collapsed into one production, and every destroy card in the pool lowered to
byte-identical instructions.

Deleted rule families: the whole generic destroy set, the generic pump set
(including three rules that existed one-per-P/T-value — `pump_self_1_0`,
`pump_self_0_1`, `pump_self_1_1`), both base-P/T setters, the flying and
banding grants, the Earthquake/Hurricane/Sandstorm sweeps, the Disintegrate
riders, `tap_target`, `untap_target_land`, and the two fused damage
conjunctions.

Divergences accepted during migration, all since retired along with the rules
they were measured against:

| Card(s) | What changed |
| --- | --- |
| Orcish Artillery, Psionic Blast | `deal_damage_and_self_damage` decomposed into two ordinary damage instructions |
| Serendib Efreet, Juzám Djinn, City of Brass | recipient stated explicitly rather than relying on the resolution context's default target |
| Icy Manipulator | type union kept as a filter where the legacy rule special-cased the wording and emitted none |

Three bugs the guards caught during this phase, each a case where the grammar
was quietly wrong and something failed loudly:

1. **Back-references need a producer.** "You gain that much life" on a
   *triggered* ability reads the trigger's captured event, not the resolution
   scratchpad; lowering it as a scratchpad read would have gained zero life.
   Lowering now refuses a back-reference with no producer in the same effect.
2. **Restricted untap has its own handler.** `untap_target_permanent` ignores
   filters entirely, so lowering "untap target land" to it would have let Ley
   Druid untap a creature.
3. **Type unions versus stacked types.** "artifact or enchantment" is either;
   "artifact creature" is both. Collapsing them would have made "destroy target
   artifact creature" hit every artifact and every creature.

The deletion probe also found two real loosenesses and both were fixed rather
than accepted: a counter with no written kind defaulted to +1/+1, and the noun
after "other than this" was optional.

Still open from this phase's scope: regeneration, life, draw/discard and zones
are parsed and lowered but **not** switched on — `zones` because "Draw a card"
maps to two different handlers depending on who draws, and `mana` because
`add_mana_from_text` re-reads clause text and Black Lotus bundles a sacrifice
cost into its instruction. Both need their handlers reworked first.
`parse_target_filter`/`TargetFilter` still exist for the rules that remain.

## Grammar: the backlog is now measured, and the first item is cleared

With targeting riding on lowering, `GRAMMAR_COVERAGE.md`'s backlog table is the
work queue for almost everything left. Its largest entry was **"expected a
subject", 364 lines** — three times the next item, and it turned out not to be
one gap at all. 149 distinct lines, mostly triggered abilities whose *trigger*
already parsed while the effect after the comma did not.

The clearest of them: **"When you control no Islands, sacrifice this creature"**
— Dandân, Sea Serpent, Pirate Ship and Island Fish Jasconius. The `no_islands`
trigger event was already in the parser's table and `sacrifice_self` already had
a handler and an upkeep-registry entry; the only missing piece was a production
for *sacrifice as an effect*. The grammar had `SacrificeCost` (an activation
cost) but nothing for the verb.

One production plus one lowering: 48.1% → **48.9% parsed**, 30.0% → **30.8%
lowered**, 18.9% → **19.7% executed**, 241 → **248 cards**.

The lowering deliberately refuses "sacrifice **a** creature". That makes a
*player* choose which permanent, so it needs the pending-choice machinery;
lowering it alongside "sacrifice this creature" would sacrifice the source
instead — the wrong permanent, silently. It is a `LoweringError` with that
reason, so the card stays on the legacy path and the backlog table names it.

### Backlog worked, and what it turned out to be

Productions added this pass, each differentially checked against the legacy
rules over the whole pool before its category was switched on:

| Production | Cards unlocked |
| --- | --- |
| `sacrifice this <permanent>` | Dandân, Sea Serpent, Pirate Ship, Island Fish Jasconius |
| `regenerate` (target / self / enchanted) | Regeneration family, incl. Elephant Graveyard |
| `counter target <colour> spell` | Counterspell, the Elemental Blasts, Lifeforce |
| `target player discards N cards` | Mind Twist family |
| `untap this <permanent>` / `untap enchanted creature` | Basalt Monolith, Mana Vault, Instill Energy |

Two new categories (`regeneration`, `counterspells`) are switched on. Grammar
coverage over the pass: **18.9% → 23.3% executed**, **30.0% → 34.4% lowered**,
**241 → 284 cards**, and cards deriving their own cast target 50 → 61.

Three guards caught real defects mid-flight, which is the whole reason the
migration is gated this way:

- The **grammar-vs-legacy differential** caught Elephant Graveyard: "Regenerate
  target Elephant" lowered without its `subtype_filter`, which would have
  regenerated any creature. The lowering now carries the one restriction the
  handler honours and refuses the rest.
- The **targeting guard** caught Counterspell: its target description defaulted
  to "permanent", so the UI would have offered battlefield permanents for a
  spell that targets the stack. Spell targets are now described as such.
- The **regression suite** caught Mana Vault. Adding `untap_self` let the
  *enclosing* `may` lower, so the upkeep trigger became `("upkeep_self", "may")`
  — a pair no upkeep handler is keyed to. The card would have compiled cleanly
  and done nothing. Upkeep triggers that decompose into a wrapper are now
  refused with that reason, until phase 4 can execute decomposed instructions.

### Backlog analysed in parallel — the worklist is now specified

Four subagents analysed the ~215 non-blocked lines read-only, in disjoint
clusters, each classifying every line as *implementable now* (naming the
existing handler and the exact legacy payload to match), *needs a new handler*,
or *blocked*. That analysis is the expensive part; writing a production once you
know the target is not. Worktree isolation was unavailable — the session's work
is uncommitted, so a worktree lands on a HEAD without `engine/grammar/` — and
concurrent edits to `parser.py`/`lower.py` would have made the differential
meaningless, so implementation stays serial.

**Landed from the analysis: trailing activation restrictions.**
`ast.ActivationRestriction` had existed since phase 1 and was never once
constructed, so every "Activate only during your upkeep." sentence broke the
full-consumption invariant and sent its whole ability back to the legacy rules.
The parser now consumes it. Enforcement does not move — `stack_casting.py` reads
`ability.source_line`, so nothing is dropped — and a test pins that the
restriction never leaks into the effect's instructions. Six abilities became
usable (Disrupting Scepter, Instill Energy, Rock Hydra, Desert, Ifh-Bíff Efreet,
Library of Alexandria) and ten cards pool-wide carry the wording.

**An agent finding that was wrong, and why testing behaviour caught it.** One
agent reported that Cursed Land compiles with zero triggered abilities — true —
and concluded its upkeep damage never fires. It does: the enchant-land upkeep
pass in `phases/upkeep_step.py` handles it. Adding `land` to the trigger regex
made the card deal its damage *twice*, which
`test_cursed_land_deals_upkeep_damage_to_land_controller` caught immediately.
The regex now carries a comment saying why the omission is deliberate. A
compile-level observation is not a behaviour claim.

**The highest-value structural finding** came from the residual bucket: 18 lines
are declarative text whose behaviour lives in a text-keyed sidecar registry —
`cast_restrictions.py`, `untap_restrictions.py`, `cost_modifiers.py`, the Aura
`Enchant` line, three `replacements.py` interceptors — and which therefore can
*never* become `usable` through instructions, because `compile_line.usable`
requires a non-empty category set. They need a no-instruction AST node, the
`KeywordLine` pattern, with `ActivationRestriction` as the precedent just proven.
Those interceptors match on exact normalized text, so such a node must preserve
it verbatim.

**Landed next: damage prevention (CR 615).** The `ast.PreventDamage` node had
also existed unused since phase 1. Two productions now populate it — the numeric
shield ("Prevent the next N damage that would be dealt to <recipient> this
turn") and the Circle-of-Protection shield ("The next time a <colour> source of
your choice would deal damage to you this turn, prevent that damage"). Ten lines
lower, zero divergences against the legacy rules, and the `prevention` category
is switched on.

The recipient is what decides the payload, and the three shapes are not
interchangeable: `to_self` shields the ability's controller, `to_source` the
permanent the ability sits on, and neither shields a chosen target. Oasis
narrows to "target creature" — the handler takes no filter, so that restriction
survives in the grammar-only `targets` description rather than being dropped.
Reverse Damage's uncoloured "source of your choice" is **refused**: it is a
different handler that also gains life, so lowering it as a colourless Circle of
Protection would silently lose that.

Coverage across this pass: **23.3% → 26.4% executed**, **30.8% → 37.4%
lowered**, **48.9% → 52.0% parsed**, **284 → 315 cards**.

A note on the declarative-node idea the analysis ranked first (18 lines): it
buys *parse* credit only. `CompiledLine.usable` requires a non-empty category
set and `KeywordLine` short-circuits before lowering, so a no-instruction node
cannot make a line execute through the grammar and does not suppress the legacy
fallback. Worth doing to make the backlog honest, but it moves no behaviour —
which is why the prevention shields were done first.

**Landed next: the Lace cycle (colour replacement).** Two changes — generic
head nouns now union ("target spell **or permanent**", which previously stranded
"or permanent" and failed the whole line), and a `becomes <colour>` production
over a new `BecomeColor` node. Five cards, payloads identical to legacy, and the
`recolor` category is on.

The targeting guard earned its keep a second time here. Describing the Lace
target with the generic object shape derives "permanent", which would have
dropped **spells on the stack** from the picker for a card that explicitly
targets either. `test_batch08.TestLaceTargetsSpellOrPermanent` and
`test_derivation_never_disagrees_with_the_text_cascade` both failed within
seconds of switching the category on. The `targets` vocabulary has no way to
express a stack/battlefield union, so the lowering now describes *nothing* and
`legality.py` keeps answering `spell_or_permanent` — refusing to describe rather
than describing wrongly, the same rule that governs refusing to lower.

Coverage across this pass: **26.4% → 27.6% executed**, **37.4% → 38.6%
lowered**, **52.0% → 53.1% parsed**, **315 → 330 cards**.

**Landed next: pay-or-else upkeep triggers, and a trigger-table entry.**

Sengir Vampire needed one tuple — `creature_dealt_damage_by_self_dies` — and
became usable outright, its effect half already lowering to the legacy payload.
The table is matched in order, so the entry sits ahead of the shorter
`creature_dies` phrase that would otherwise claim its prefix.

"Sacrifice this <permanent> unless you pay <cost>" (Conversion, Stasis,
Phantasmal Forces, Junún Efreet) lowers to a new `SacrificeUnlessPay` node and
then to the **fused** kinds `upkeep_pay_or_sacrifice_enchantment` /
`upkeep_pay_or_sacrifice_self`. Fused deliberately: the upkeep dispatcher is
keyed on (trigger condition, instruction kind) and its handlers implement the
whole prompt, so a decomposed `May(pay) else Sacrifice` would produce a pair no
handler is keyed to — exactly the Mana Vault failure from the previous pass, and
the reason `lower_ability` refuses decomposed wrappers on upkeep triggers. The
noun picks the handler (an enchantment's prompt is a different registry entry),
and the mana payload names every colour because the handlers index it directly.
Verified end-to-end: Junún Efreet is sacrificed with no black mana and survives
with {B}{B}. The `upkeep` category is on.

Coverage across this pass: **27.6% → 28.6% executed**, **38.6% → 39.6%
lowered**, **53.1% → 54.2% parsed**, **330 → 343 cards**.

### Parallel implementation pass — four agents, four productions

Worktree isolation is unavailable (the session's work is uncommitted, so a
worktree lands on a HEAD without `engine/grammar/`), and every production edits
the same two files. The workable answer was a plain filesystem copy of the repo
per agent, minus `.venv`/`.git`, run against the shared venv by absolute path —
verified first: the full suite and every guard script run correctly in a copy.
So each agent implemented *and* verified its own work, and the diffs were merged
serially with the full gate re-run after each.

| Agent | Production | Cards |
| --- | --- | --- |
| A | `return <object> [from <zone>] to <zone>` | Raise Dead, Regrowth, Resurrection, Unsummon |
| B | counterspell riders + tap/untap disjunction | Spell Blast, Power Sink, Twiddle |
| C | single-clause imperatives | Time Walk, Glasses of Urza, Hurr Jackal, Dwarven Warriors |
| D | `RegistryLine` — lines implemented by a text-keyed sidecar registry | 16 lines |

**60.3% parsed / 45.5% lowered / 31.0% executed / 374 cards**, from 54.2 / 39.6 /
28.6 / 343.

Three designs came back better than specified:

- **A** added `is_card` and `zone_owner` to the filter rather than pattern-matching
  the sentence, because the legacy rules told Raise Dead from Regrowth by probing
  `"creature card" not in text` — so "return target *artifact* card from your
  graveyard" would have returned a creature. It also guards `_filter_payload` so a
  graveyard-scoped filter can never reach a battlefield handler.
- **C** checked the whole filter for *equality* against the shape each handler
  implements, rather than probing known fields, so a filter field added later
  cannot slip past a lowering written before it existed.
- **D** delegates every claim to the registry's own matcher instead of copying
  phrases into the grammar, and promoted two inline literals in `replacements.py`
  to named constants so the two readers cannot drift. It declined lines whose
  behaviour is a bare substring probe with no registry function to delegate to —
  claiming those would have required exactly the copied table its design forbids.

**B's most valuable output was a refusal.** Twiddle's printed line is "You may tap
or untap target …", which lowers to `may` — and `may` parks the effect in
`pending_optional_pays`, a queue only the triggered-ability resolution path
drains. A spell pops off the stack immediately, so the effect would never happen.
B measured this (three pinned regression tests fail with the permanent untouched)
and left the card on the legacy path rather than shipping a green-looking
no-op. It also refused to lower a filtered tap-or-untap at all, since that
handler honours no filter and falls back to *the first permanent*.

Merge notes worth keeping: `patch` failed on every shared file with CRLF/LF
mismatches (`--binary` fixes it); two hunks collided where agents edited the same
category map and `__all__` list; and one half-applied hunk left `mana_value`
parsed but never passed to the constructed filter, so Spell Blast silently lost
`mv_equals_x` — caught by `test_spell_blast_does_not_counter_spell_with_wrong_x`,
which is exactly why each agent's claims were re-verified in the live tree rather
than taken from its report.

### Second parallel pass — and a guard against false coverage

Three agents on the remaining backlog, partitioned by ability type (spells 82,
activated 29, triggers 55). Coverage **60.3% → 64.9% parsed, 45.5% → 58.2%
lowered, 31.0% → 33.0% executed, 374 → 399 cards.**

The lowered figure moving four times as far as the executed figure is the
interesting part, and it is honest: most of what agent E cleared is text the
engine implements *outside* the instruction pipeline. `_parse_enchant` produced
`RawEffect`, which never lowers — that one gap was ~125 of the 128 "no lowering
for RawEffect" backlog lines. An Aura's `Enchant <subject>` line is not an
effect and never will be; it now routes through `RegistryLine`, with
`enchant_line_subject()` added to `targeting.py` sharing the subject tuple so
the two readers cannot drift. E also moved two inline substring literals out of
`untap_step.py` into named constants, so the enforcing scan and the whole-line
matcher are built from one string each.

**Agent G refused 15 of its 55 lines on a principle worth recording.** For those
lines the legacy condition table matches nothing, so `_parse_triggered_ability`
returns `None` and the whole ability is discarded. Adding a grammar phrase would
have raised the coverage number while changing nothing about the game —
*false coverage is worse than none*. Cursed Land is in that set, which is the
same card whose regex the first analysis round wrongly wanted to "fix".

Better still, G made that failure mode **mechanical** rather than a rule people
have to remember. Two pool-wide tests now assert that every trigger the grammar
executes names the same condition the legacy table does (a legacy kind of `None`
being the sharp case), and that every executed upkeep `(condition, kind)` pair
is one something actually dispatches. I verified the guard fires by injecting
the Cursed Land row: it fails with `legacy: None grammar: upkeep_enchanted_controller`,
exactly the shape that shipped twice before (Mana Vault, Black Vise).

G also threaded the trigger kind into lowering so "damage unless you pay" can
reach two different fused kinds depending on its trigger — and deliberately did
*not* thread it into nested statements, so a nested occurrence refuses rather
than assuming the enclosing trigger's dispatch reaches it.

**Agent F's refusals are the model for this work.** It declined Black Lotus's
"Add three mana of any one color": `_add_mana_from_text`'s any-colour path probes
for *one* mana and recognizes no other number, so lowering three would have added
**zero** mana while reporting success. It declined Rukh Egg's token because
CR 111.4 names an unnamed token after its subtypes while `arm_end_step_token`
names it after the subtype alone — and a token's name is what every "creatures
named …" effect reads, so either convention makes one family wrong.

Best of the three: it required the token's colour word rather than defaulting an
absent one to colourless. An empty `colors` tuple already means colourless, so
allowing the word to be *absent* also allows it to be *deleted* with no payload
change — which the parse-coverage deletion probe duly flagged as a dropped
rider. F tightened the production so the finding disappeared, instead of
baselining it. That is the difference between fixing a bug and recording one.

It also found two cards beyond its worklist by sweeping the pool for the shapes
it had just implemented (City of Brass, Scavenging Ghoul), and declined 18
single-card fused kinds with the right reason: a production for those would be
the same whole-card substring match wearing a grammar hat, and they need the
*handler* decomposed first.

**A stale tracker, and the CI gap behind it.** E noticed `PARSE_COVERAGE.md` was
stale in the base tree; it was, by exactly the two lines it predicted, left by an
earlier `HANDLER_CLAIMS` addition. The cause is that `parse_coverage.py --check`
guards *unclaimed text*, not report freshness, and the CI staleness step
regenerated the other three trackers but not this one. Now added, with a comment
explaining the distinction.

### Third parallel pass — and the fallback hazard, now ratcheted

Two more agents over the 140 workable lines. **65.5 → 69.2% parsed, 59.3 →
63.0% lowered, 34.1 → 34.9% executed, 412 → 420 cards**, 3,724 → 3,776 tests.

Landed: per-death counter scaling (Scavenging Ghoul, Khabál Ghoul), fused
draw-then-discard (Bazaar of Baghdad), `search_library` (Demonic Tutor), random
discard routed to the handler that actually randomises (Mind Twist), an
`as long as <condition>` static node, `;` as a keyword separator, and
`engine/enter_effects.py` — ten CR 614.1c entry-state phrases that were string
literals inside `permanent_state`, now one leaf module with two readers.

Both agents added pool-wide guards of their own: an end-step dispatch guard
(the twin of the upkeep one) and a test that the entry phrases have exactly one
spelling. Both fault-injected them to prove they fire.

**The hazard worth recording.** Agent H noticed that `engine/oracle.py`'s
noncreature path is all-or-nothing *per card*:

    if grammar_instructions:      # any one line claimed...
        instructions.extend(grammar_instructions)
    else:
        parse_primary_instruction(normalized_text)   # ...suppresses the whole card

So a production claiming one line of a multi-line card deletes the legacy
reading of *every* line. The card still compiles, still reports `supported`, and
still passes a payload differential — which only compares lines the grammar
claimed. Nothing prevented it; it had been avoided only by authors being
careful, which is not a mechanism.

`tests/engine/test_grammar_fallback_safety.py` compiles the whole pool twice,
once with `_grammar_instruction` stubbed out, and fails on any card that loses an
instruction kind. It is currently biting nothing: all 8 differences are
deliberate improvements — Ley Druid getting `untap_target_land` instead of the
filter-ignoring `untap_target_permanent`, three fused conjunction kinds
decomposing into `sequence`, Verduran Enchantress becoming properly optional —
each listed with its reason and staleness-checked. Removing the Ley Druid entry
makes the guard fail with exactly that card, which is how I verified it.

### Combat restrictions: a template trapped in a literal whitelist

Chasing why the grammar cannot claim "This creature can't attack unless
defending player controls an Island" turned up a live scaling bug rather than a
parser gap. `engine/oracle.py` mapped static creature lines to instruction kinds
with an `elif` chain of **exact string equality**, and the Island wording was
one of its literals. A creature printed "unless defending player controls a
**Mountain**" therefore fell through to a bare `static_line` — and because
`_is_supported_static_creature_line` still returned True for it, the card
reported `supported` and then **attacked freely with the restriction silently
absent.**

`engine/combat_restrictions.py` derives the family from text instead, with the
land type carried as payload data rather than baked into the instruction's name
(`cant_attack_without_island` → `cant_attack_without_land_type` +
`{"land_type": …}`). `can_attack` reads the payload, so all five basic types
work and the Magical Hack / Phantasmal Terrain type-change handling is
unchanged. Six literals leave the compiler's whitelist, which is the audit's
named "card whitelists embedded in the compiler" in miniature.

The test deliberately uses an invented Mountain card: a test naming only Dandân
would have passed against the broken version, which is exactly how the bug
survived.

### The sibling: a whitelist keyed on the card's own name

The combat-restriction bug was one instance of a pattern, so I checked its
neighbours in the same chain. The land-count CDA — "*<name>*'s power and
toughness are each equal to the number of Swamps you control" (Nightmare) — had
the same shape with a different failure mode, and the distinction is worth
keeping straight.

Its whitelist entry embeds the **card's own name**, because
`normalize_creature_line` does not replace it. The `elif` that emits the
instruction matched name-agnostically, so this was not silent wrongness: a
functionally identical card with another name simply compiled as
**unsupported**. A false negative rather than a false positive — safe, but it
means every reprint and every same-template card needs its own whitelist line,
and adding one costs three edits (whitelist entry, `elif` branch, `DYNAMIC_PT`
row) because the land type was baked into the instruction *kind*.

Now one template, one kind (`dynamic_pt_land_count`), one counter reading
`{"land_type": …}`. Nightmare is unchanged at 3/3 with three Swamps; a
differently-named card counting Mountains works with no new code at all.

Both fixes are the same lesson: when a whitelist entry contains a card name or a
specific noun, the thing it is hiding is a template — and which way it fails
(supported-but-wrong vs unsupported) depends only on whether the *gate* and the
*dispatch* were written with the same literal.

### Finishing the chain: the gate and the dispatch must read one table

Auditing the rest of that `elif` chain turned up a third failure mode, and it
is the one that generalises.

`_is_supported_static_creature_line` matches its ~30 whitelist literals with
`startswith`, while the dispatch tables (`combat_restriction_for`) are
**anchored**. Nine lines pool-wide were admitted by a literal shorter than the
line itself. Most are benign, but the shape is not: "this creature can't block
creatures with flying" was gated in by the prefix `"this creature can't
block"`, matched no anchored pattern, and fell through to a bare `static_line`
— **supported, restriction absent**. Ironclaw Orcs escaped only because someone
had already written its exact rider into the dispatch table.

Loose gate + strict dispatch = supported-but-wrong. Strict gate + loose
dispatch = unsupported. Both are the same defect: two places deciding what the
engine understands. The gate now calls the dispatch table, so an unrecognised
rider is reported unsupported — loud — instead of silently unenforced. Fixing
it also showed `cant_block_power_2_or_greater` baked its threshold into the
instruction *kind*, so the identical restriction printed with any other number
produced nothing; the number is payload data now.

### One kind for every characteristic-defining P/T

The four CDA templates — Nightmare, Keldon Warlord, Plague Rats, Gaea's Liege —
were each a whitelist literal containing the card's **own name** plus an `elif`
emitting a per-card instruction kind plus a row in a counter registry. Three
edits per card, and a functionally identical card under any other name compiled
as unsupported. All four are one template with a parameter.
`engine/characteristic_defining.py` derives them name-agnostically into a single
`dynamic_pt_count` instruction whose payload says what to count (`land` /
`creature` / `same_name`) and whose battlefield to count it on; one counter
reads it, and the `DYNAMIC_PT` registry is gone. Relentless Rats and a
Mountain-counting Nightmare now work with no code at all.

Two behaviour bugs surfaced while consolidating, both from reading printed text
where the layer system is the authority:

- **The shared filter matcher bypassed layer 4.** `permanent_matches_filter` is
  documented as the one matcher so destroy-target resolution, cast validation
  and the legality enumerator "can never disagree about what a filter means" —
  but its subtype test read `card.type_line` while `has_type` computes through
  CR 613 layer 4. A land turned into a Swamp by Magical Hack was a Swamp to the
  rules engine and an Island to every filter. Unreachable in the current pool
  (no card here filters on a basic land subtype) and live the moment one ships.
- **Layer 4 was applied after layer 7a.** Land animation (Kormus Bell, Living
  Lands) ran inside the same per-permanent loop as characteristic-defining P/T,
  so a CDA counting creatures saw the *previous* pass's animation state — a
  land animated this pass counted only from the next one. CR 613.1 applies the
  layers in order within one application, not across successive ones. Animation
  is now its own pass ahead of the loop.

### Closing the class instead of the instances

Three bugs of the same shape is a pattern, so the last pass turned the fix into
a guard rather than hunting a fourth.

A fourth existed. The conditional P/T bonus is printed in two word orders —
"gets +1/+1 as long as you control a Swamp" and "As long as you control a
Swamp, this creature gets +1/+1". Only the trailing order was dispatched; the
leading order was a gate literal *spelling out Swamp*. So that sentence naming
Swamp reported supported and never applied the bonus, while the identical
sentence naming Mountain reported unsupported — the two failure modes of this
bug class, in one clause, separated only by which noun was typed into the
whitelist. `engine/static_bonuses.py` derives both orders for every land type.

`tests/engine/test_static_line_support.py` is the structural guard. It is the
permanent-shaped sibling of `test_no_hollow_support.py`: every static line the
gate admits must be claimed by a derivation table, or listed in
`IMPLEMENTED_ELSEWHERE` **naming the code that carries it out** (all 16 entries
were verified against that code, not assumed). A second test fails on stale
acknowledgements, because an entry matching no card is how the next card
inheriting that prefix gets a free pass nobody re-checked.

The guard was verified by reintroducing the original bug — one prefix literal
added back to the gate — confirming it fails, and reverting. A guard that has
never failed is a guard nobody has tested.

**The generalisable rule:** a whitelist entry containing a card name or a
specific noun is a template in disguise. Whether it fails as supported-but-wrong
or as unsupported depends only on whether the gate and the dispatch were written
with the same literal — which is why they must not be two lists.

### The same hole, one card type wider: Auras

The static-line gate is closed, but it had a bigger sibling. A single whitelist
substring — `"enchant creature"` — was the *entire* support test for an Aura.
Nothing ever looked past the enchant clause, so an Aura reading "Enchanted
creature glimmers uncontrollably" compiled as supported, and so did one whose
only line was the enchant clause itself. Forty-four Auras in the pool, none of
whose support status had ever actually been checked.

`engine/auras.py` names the effect lines the engine carries out, and the
compiler now requires every effect line of an Aura to match one, reporting the
offending line by name when it does not. All 369 cards remain supported; the
pool was already correct, but nothing had verified that.

Enumerating it produced the number the phase-6 work needs: **52 distinct effect
lines across 44 Auras, every one appearing exactly once.** That is the
signature of a mechanism that grows one branch per card, and it is why
`_apply_aura_effect` is a 270-line text-reading if-chain. Roughly a third of
those lines collapse into templates (the P/T modifications, the keyword grants,
the protection cycle, the upkeep-damage family); the rest are genuinely
single-card and are what the layer-owned rewrite has to absorb.

Two things surfaced while building it, both worth keeping:

- A test fixture asserted support it never had. `test_303_4j` used an invented
  wording ("Enchanted land produces an additional {G} when tapped") where the
  engine implements Wild Growth's real one. It passed only because "enchant
  land" was sufficient on its own. The test's subject is attachment, so it now
  uses the printed text and still tests what it meant to.
- My first draft of the table claimed `protection from [a-z]+`, which matched
  "protection from everything" — an over-broad entry of exactly the kind that
  made "enchant creature" sufficient in the first place. Protection is
  restricted to the five colours, because that is what the check behind it
  implements.

**Classification, not dispatch.** The behaviour still lives in the if-chain;
this only makes the engine honest about what it can do. That distinction is the
reason this was safe to land alongside parser work while the Aura rewrite
itself stays a phase of its own.

### The false-negative half, in the tables built this same session

The noncreature gate had the mirror of the combat-restriction bug, and it was
sitting inside work from earlier in this pass. `untap_restrictions.py`,
`draw_step_modifiers.py` and `cost_modifiers.py` derive their behaviours
generically — that was the entire point of extracting them. But the *support
gate* still listed the same behaviours as whitelist literals with the tables'
parameters baked in: "creatures with power **3** or greater don't untap",
"players can't untap more than **one** creature", "**white** spells cost
**{3}** more to cast".

So a card printed "power 4 or greater" was enforced correctly by the table and
reported **unsupported**. Implemented-but-unsupported is still a bug: the card
is excluded from decks and from every coverage report while the engine plays it
perfectly.

The gate asks the tables now, through a `derived_static_rule` instruction that
records *which* table claims the card — so support can be traced to the code
carrying it without re-reading text. Eight whitelist literals deleted; 88 → 80.

Worth stating plainly: extracting a derivation table does not finish the job.
The table removed the duplication in the *dispatch* and left it in the *gate*,
which is the same two-lists defect in a new place. When a behaviour moves to a
table, the support check has to move with it.

### Where the whitelist stands, and the ratchet holding it there

Sweeping the same question across noncreature permanents took the count of
cards "supported by a string comparison and nothing else" from **38 to 0**, and
`SUPPORTED_SPELL_PATTERNS` from **88 literals to 75**.

The last two removals were instructive in opposite directions:

- Four literals (Castle, Kormus Bell, Living Lands, Orcish Oriflamme) merely
  *restated* a parse rule that already produced a real instruction. Pure
  redundancy — but redundancy in a support gate reads as coverage, so it hides
  how much of the whitelist is actually load-bearing.
- My own `_derived_static_claims` named **two constants** out of
  `engine/enter_effects.py` rather than calling its `enter_effect_line`
  registry. Every phrase in that module is implemented, so listing a subset was
  the same partial-list mistake one level down — committed while fixing that
  exact mistake a level up. Copy Artifact was the card it left behind.

Three guards now cover the three shapes, and each was verified by reintroducing
the bug it exists to catch:

| Card kind | Guard | Requirement |
|---|---|---|
| Instant / sorcery | `test_no_hollow_support.py` | a registered `EFFECT_HANDLERS` entry |
| Aura | `tests/rules/test_aura_support.py` | every effect line claimed by `engine/auras.py` |
| Other permanents | `test_derived_support.py` | an instruction, an ability, or a rule table |
| Creature static line | `test_static_line_support.py` | a derivation table or a named acknowledgement |

A new card that fails one of these needs its behaviour claimed by the code that
implements it — never a new whitelist literal. That is the rule the remaining
~26k cards have to be onboarded under, and it is now enforced rather than
described.

### Phase 6, first slice: an Aura owns its P/T effect

The Aura's static P/T grant is now *derived from the Aura's own text* on every
recompute and collected at layer 7c with the timestamp of the moment it became
attached, instead of being added once into the enchanted creature's
`power_bonus` with the delta recorded and subtracted back on removal.

Four things follow, and only the first was the stated goal:

1. **Removal is dropping a contribution.** No remembered delta, so nothing can
   fall out of step with what was added — the Aspect of Wolf compounding shape
   is structurally gone for Auras, not just fixed once.
2. **Each Aura gets a real timestamp** (CR 613.7b). Every Aura previously
   shared `_DERIVED_TIMESTAMP = 0`, so two Auras had no order relative to each
   other. Addition commutes, which is why that was invisible — and why it would
   have stayed invisible right up until a layer-7c effect that does not commute
   met it.
3. **Counters and Aura grants are finally separable.** `power_bonus` holds
   things that belong to the *creature*; an Aura no longer writes there at all.
4. **Attachment is a list.** `attached_aura` was a single slot that a second
   Aura silently overwrote. `attached_auras` is the authority now, and
   `attach_aura`/`detach_aura` keep both directions in step so no caller has to
   remember to.

The bug this uncovered is the one worth remembering. `aura_granted_meta` is
captured as "every key that appeared on the target while this Aura was
attaching" — so it swept up the new `attached_auras` key, and removing one Aura
popped the list, **detaching every other Aura on the creature**. A
capture-anything heuristic will keep finding new things to eat; excluding the
attachment keys is a patch, and the real fix is the rest of phase 6 turning
those metadata flags into owned effects too.

Still to do in this phase: keyword grants, `only_blockable_by_walls`,
`lure_active` and the rest of the flags `_apply_aura_effect` stamps directly;
then layers 1 (copies), 2 (control) and 3 (text-changing).

### Phase 6, second slice: keyword grants, and one reader that had to move

Aura keyword grants now follow the P/T grant — derived from the Aura's text,
stamped when it attached, collected at layer 6, gone when it leaves. Six Auras
(Flight, Fear, Lance, Web, Burrowing, Fishliver Oil); the Wards and Consecrate
Land are deliberately *not* claimed, because protection and
can't-be-enchanted are metadata channels with their own checks and a
`grant_abilities` entry would say layer 6 carries them when it does not.

Landwalk is the interesting one. It was written as a `has_<walk>` flag straight
onto the creature, and `_attacker_has_active_landwalk` read that flag — so the
grant lived *outside* the layer system, and expressing removal needed a
matching `lost_<walk>` flag. The combat check now asks for computed abilities
and never learns an Aura exists.

That is the shape of the remaining phase-6 work in miniature: moving an effect
into the layers is easy, and the cost is finding every reader that was reaching
around them. Two small lessons banked:

- **Reminder text nearly hid the whole thing.** The first keyword pattern was
  anchored and matched only Flight and Lance, because every other printing
  carries "(It can't be blocked as long as…)". `oracle.normalize_creature_line`
  strips reminders, but importing the compiler into `auras.py` is a cycle, so
  the module needs its own one-line equivalent. An anchored pattern that
  silently stops matching most cards is the same failure as a whitelist that
  silently matches all of them.
- **A test asserted the mechanism, not the behaviour.** Burrowing's test
  checked `metadata["has_mountainwalk"] is True` and that the log said
  "landwalk". Both were implementation detail, and both broke on a change that
  kept the card working perfectly. It now asks whether the creature *has*
  mountainwalk.

Remaining: `only_blockable_by_walls`, `lure_active`, `aura_prevents_untap`,
protection, and the linked one-shots (control theft, animation) — then layers 1
(copies), 2 (control) and 3 (text-changing).

### Phase 6, third slice: the restriction flags, and a rules bug behind one

The remaining flags an Aura stamped on its target are gone. These are not
characteristics — they change how the game is played, so CR 613's layers do not
apply — but the ownership does: the reader asks which Auras are attached now,
instead of the Aura writing a flag someone must remember to clear.

`only_blockable_by_walls`, `lure_active`, `aura_prevents_untap`,
`can_attack_as_though_no_defender` and the Ward cycle's `protection_from_<colour>`
all derive from the Aura. **Auras that still stamp anything on their target:
5 of 44**, and the survivors are the genuinely layer-shaped ones
(`land_type_override` for Evil Presence and Phantasmal Terrain, Consecrate
Land's two flags) plus Animate Dead's linked one-shots.

Protection needed a correction mid-way. Deleting the `protection_from_<colour>`
metadata channel outright was too aggressive: an Aura's protection lasts while
it is attached, but protection granted *with a lifetime of its own* (a spell,
until end of turn) has nowhere else to live, and CR 702.16c does not care where
the protection came from. Both sources are read; the Aura path is simply no
longer the one that needs cleaning up.

**A rules bug fell out of the audit.** Instill Energy reads "Enchanted creature
can attack as though it had haste", and the engine granted the *haste keyword*.
CR 302.6 has two clauses — a summoning-sick creature can't attack, and can't
activate a `{T}` ability — and CR 702.10b says haste lifts the attack clause.
This wording lifts that same one clause. Granting haste lifted both, so a
summoning-sick Llanowar Elves under Instill Energy **tapped for mana a turn
early**. It is a restriction now, not a keyword grant.

That bug is the argument for this whole phase in one card: it was invisible
while the effect was "a flag that means roughly haste", and obvious the moment
the question became "what exactly does this Aura permit?".

### Phase 6, fourth slice: Consecrate Land — and where the thread stops

Consecrate Land prints one line carrying two effects: "Enchanted land has
indestructible **and** can't be enchanted by other Auras." The indestructible
half is a layer-6 keyword grant, the trailing clause a restriction. Both are
claimed explicitly rather than by loosening the keyword pattern to tolerate a
trailing "and …" — a pattern that matches half a line and ignores the rest is
the dropped-rider bug, and this table exists to prevent it.

**Auras that stamp metadata on their target: 2 of 44** (44 at the start of the
phase). The two survivors are Evil Presence and Phantasmal Terrain, and they
are where this thread deliberately stops.

`land_type_override` is not an Aura problem. It has **17 readers** across the
engine, several of which read it *instead of* `has_type` — the same layer-bypass
class already fixed in the shared filter matcher — and it is written by
non-Aura sources too (Magical Hack through `board_misc`, the upkeep step). It
is layer 3 and layer 4 work with its own blast radius, not the tail of this
one. Doing it here would mean touching seventeen call sites under the heading
of an Aura change.

Both remaining accessors (`_is_indestructible`, `_cant_be_enchanted`) keep
their metadata channel alongside the derived source, for the same reason
protection did: a grant with a lifetime of its own has nowhere else to live,
and the rules do not care where the quality came from.

### The static-ability cluster, and why it is a phase-6 job

20 of the remaining lines fail with "static abilities need the CR 613 layers
engine" — the Aura P/T and keyword grants (Holy Strength, Flight, Web, Fear) and
the lord anthems (Crusade, Bad Moon, Lord of Atlantis, Goblin King). They are the
largest coherent cluster left, and they are not long-tail vocabulary: they are
one structural problem.

The engine already runs them, but not the way the layer work intends. An Aura's
grant is applied by **mutating** `target_creature.power_bonus` and recording the
delta on the Aura (`aura_granted_power`) so `_remove_aura_effects` can subtract
it when the Aura leaves. That is precisely the destructive accumulation phase 6
set out to remove, and the shape Aspect of Wolf's bug came from — each effect
keeping its own record of what it contributed, with a mismatch compounding on
every refresh. The value is read through `layer_bridge.collect_pt_effects`, so
the *number* is layered; the *ownership* is not.

Making these lines lower means giving an Aura's static a real
`ContinuousEffect` owned by the Aura, so removal is "drop the effect" rather
than "subtract what I remember adding". That is a behaviour-affecting refactor
of the attach/detach path (Animate Dead, Unstable Mutation, Instill Energy all
ride it), and it belongs in a pass of its own rather than alongside parser work.

**A dedup that would be a mistake.** `scripts/parse_coverage.py` carries a
21-regex `_AURA_STATIC_PATTERNS` table mirroring the interpreter's scattered
`in text` probes, which looks like exactly the duplication this session has been
removing. It is not. `registries.py` delegates to each registry's own matcher
because its question is "does this code implement this line?" — a copy there
could claim text nothing runs. The coverage script asks the opposite question,
"is this text claimed by something?", and its value comes from being an
*independent* second opinion. Making it delegate to the engine would render the
guard tautological. The two tables should stay separate.

### What is left, and what actually blocks it

274 unique lines remain unsupported. Classifying them by what stands in the way:

| Lines | Blocked on |
| ---: | --- |
| 154 | plain effect vocabulary — now specified per line by the agent analysis |
| 64 | trigger lines: effect vocabulary *and* phase-4 dispatch |
| 50 | static/continuous abilities — phase 6 CR 613 layers |
| 4 | scheduled phase-3 productions (quoted abilities, modal) |
| 2 | upkeep dispatch needs fused kinds — phase 4 |

So **56 lines (20%) are blocked on other phases**, not on the grammar. The
other 218 are a genuine long tail: Magic's effect vocabulary, one production
each, with no remaining cluster large enough to move the number in a single
step. That is the shape of the rest of phase 3 — steady, verifiable,
production-by-production work of the kind above, not a few big wins.

## Phase 4 — trigger event bus and a generic choice queue 🟡 partly done

**Done:**

- **`engine/events.py`** — `emit(game, kind, **payload)` announces an event and
  puts every matching trigger on the stack in APNAP order. Applicability
  filters register per condition kind (`@event_filter`), so "whenever a player
  casts a *blue* spell" narrows from the trigger's own parsed payload instead of
  a per-card hook.
- **CR 603.3 fixed** — `iter_triggered_abilities` no longer stops at one trigger
  per permanent. A permanent with two upkeep triggers fired only one; no card in
  the current pool has that shape, which is why it needed a synthetic test
  rather than waiting to be discovered.
- **Manual destruction fully retired** — all nine `_destroy_marked_creatures()`
  call sites *and* the 39-line method are gone; CR 704.5g/h lives only in the
  state-based-action loop. `resolve_upkeep` gained the CR 704.3 check before it
  hands out priority, which is what the inline sweeps had been standing in for.
  The deathtouch marker is cleared per SBA pass, matching 704.5h's "since the
  last time state-based actions were checked".

- **Optional actions are now a grammar production.** "You may pay {N}. If you
  do, …" parses into a `May` node whose consequence is an ordinary instruction
  sequence, and "If you do," / "If you don't," fold into it as branches rather
  than becoming separate sentences (which would make the consequence
  unconditional). `_pay_optional` runs those branches when present. The old
  `optional_pay` hook shape could only express *gain N life*, *draw N cards* or
  *take N damage*, so any card outside that vocabulary needed a name-keyed
  entry; now any effect can sit behind an optional cost.
- **Colour-narrowed cast triggers parse as data.** "Whenever a player casts a
  *blue* spell" captures the colour into the trigger condition's payload — in
  both front ends — so one dispatcher covers the whole Rod/Cup/Sphere cycle
  instead of five hook entries. Trigger-table regexes now feed named groups into
  the condition payload generally.

- **Six name-keyed cast hooks deleted.** `ON_SPELL_CAST`, `ON_SPELL_CAST_ANY`
  and `COLOR_ROD_TRIGGERS` are gone: Verduran Enchantress and the five
  Rod/Cup/Sphere artifacts now run off their own compiled text. The cast site
  announces `spell_cast` / `you_cast_spell` / `enchantment_cast` /
  `opponent_casts_spell` on the bus and each trigger's parsed condition decides
  whether it applies. `optional` is switched on.
- **The "whenever a creature dies" fire site is generic.** It used to check
  `instr.kind == "target_gains_life"` and re-scan the observer's oracle text
  with a regex for "you may pay {N}", dropping any other instruction shape
  entirely — so a better-parsed instruction was silently ignored. It now
  enqueues whatever the trigger compiled to.

- **`zones` and `mana` switched on**, closing the two categories phase 3 left
  open. Both blockers turned out to be bugs rather than gaps: the draw handlers
  (above), and `add_mana_from_text` re-reading its clause text — it now takes
  structured pips, removing one of the engine's inline oracle-text probes. The
  player-chosen "add N mana of any one color" form is refused at lowering, so
  Black Lotus and Birds of Paradise stay on their own handlers until that
  choice has a general representation.

Coverage after this phase: **48.1% parsed, 30.0% lowered, 18.9% executed** —
and every category that has a lowering is now switched on. What is still
"parsed but not lowered" is effects the grammar can read but the engine has no
generic way to perform: static abilities (waiting on CR 613 layers),
player-chosen mana colour, and most zone movement.

Two bugs found while switching `optional` on, both of the kind that only
surface when something else starts depending on them:

1. **`draw_target_cards` ignores who is drawing.** Lowering "you may draw a
   card" to it drew for the *targeted* player. "You draw" and "target player
   draws" are separate handlers with different drawers, not one handler with a
   recipient flag; lowering now picks by the drawer.
2. **The dies-trigger fire site swallowed unknown instruction shapes** (above).

**Not done, and why:**

- The 23 existing fire sites stayed put. They are not generic scans — each is
  scoped to one permanent, filtered by instruction kind, or deliberately
  resolves inline (a land tapped for mana fires before the spell being paid for
  is even on the stack). Converting them mechanically would widen `emit` until
  it was the old API renamed. They convert when they need new behavior, as the
  dies-trigger site just did.
- The optional-action prompt still rides `pending_optional_pays`. It now
  carries instruction branches rather than a fixed life/draw/damage vocabulary,
  so it is no longer a *limit* — but it is still one of the twenty one-card
  fields. One shim remains: a plain "gain N life" consequence is mirrored into
  the legacy `life` field so the prompt UI keeps describing what accepting
  does. That goes away when the choice carries its own description.
**Done — `resolve_upkeep`'s if-chain is a registry.** It dispatched 20 card
shapes with hand-written `if cond == … and kind == …` branches, ~430 lines
inside a turn-structure method, so supporting an upkeep card meant editing
control flow and two matching branches were ordered by whichever came first in
the file. `engine/phases/upkeep_effects.py` keys them by the pair the compiler
already produces; `upkeep_step.py` went from 1,077 lines to 666, and a duplicate
pair now raises at import instead of being silently shadowed.

Everything a handler can read arrives on an `UpkeepContext`, including all five
prompt channels (`human_choices`, `mana_prevention`, `sacrifice_choices`,
`optional_choices`, `trigger_targets`), so a new effect joins the protocol
without touching the seam.

The extraction was done mechanically rather than by hand, with the script
asserting each body re-indents back to the original text byte-for-byte — 430
lines of hand-retyped game logic is exactly where a silent behavior change
hides. The five `break`s that were early exits from a branch became `return`
(the caller breaks unconditionally after the handler, so they are equivalent),
and the AI simulation is unchanged at 443 interactions.

These are the *interactive* upkeep triggers specifically — the pay-or-consequence
shapes whose prompt protocol the web layer drives, which is why they resolve
inline rather than on the stack. Folding them into a generic choice queue is
still phase 4's job; giving them a registry was not blocked on it.

`tests/engine/test_upkeep_effects_registry.py` guards the registry three ways:
no entry may be unreachable from the pool (a handler whose condition or kind
got renamed under it fails loudly rather than never running), duplicates raise,
and every `upkeep_*` kind the compiler emits must have a handler. That last one
immediately found `upkeep_return_self_from_graveyard`, which is genuinely
handled — by its own graveyard scan, since it fires from the graveyard rather
than the battlefield — so it is an explicit, reasoned exception with its own
staleness check rather than a hole in the guard.

- `Game.pending_choices` replacing the 20 `pending_*` fields remains the bulk of
  this phase.

## Phase 5 — unified replacement effects and hook generalization 🟡 started

**Done — prevention is a registry.** `engine/prevention.py` replaces the
hardcoded five-branch cascade in `mixins/effects.py`. Each shield is a
`@prevention_effect(order)` interceptor over one event payload
(`recipient`, `amount`, `source`, `combat`), and `apply_prevention` runs them in
ascending order, stopping as soon as nothing is left to prevent. A duplicate
order raises at import, matching `@parse_rule` — which shield is consumed first
is rules-visible, so a collision should surface at startup rather than as a rare
misplay.

Three things collapsed into that one pipeline:

- **Players and permanents.** There were two prevention functions, one per
  recipient kind, and the numeric-pool logic of CR 615.7 was written twice.
  Both `PlayerState` and `Permanent` carry `damage_prevention_pool`, so it is
  now one interceptor. Shields that only make sense for a player decline a
  permanent themselves.
- **The blanket combat shields.** Fog's `combat_damage_prevented_until_eot` and
  Ebony Horse's per-creature marker were checked inline at six sites in the
  combat damage step, each an early `continue` that skipped the whole damage
  event. They are interceptors now, and the six checks are gone. The `combat`
  flag on the event is what keeps a combat-only shield away from spell damage
  — the invariant that replaces "it is structurally unreachable from the spell
  path", so `tests/rules/test_prevention.py` pins it directly.
- **Deathtouch.** Removing those `continue`s exposed that the deathtouch mark
  was set even when the damage was fully prevented. CR 702.2b needs damage to
  have *been dealt* and CR 615.6 says prevented damage never happens, so the
  mark is now guarded on damage actually dealt. It was invisible before only
  because the SBA also requires `damage_marked > 0` — a second guard that
  happened to cover the first one's gap, and would have stopped covering it the
  moment a creature took damage from two sources in one combat.

**Done — combat damage now runs the damage-to-player replacements.** Chasing
the ordering question above turned up a live bug rather than a design wart:
combat damage never ran `damage_to_player` replacements at all. The combat
damage step applies life loss directly instead of routing through
`_deal_damage_to_player` — it has to, because prevention runs when the event is
recorded so lifelink and the recorded event agree on the amount — and the
replacement pass lived only on the path it skipped. Ali from Cairo floored a
Lightning Bolt at 1 life and let a 10/10 attacker take the same player to −7.

The pass now runs at the combat step's own life-application site. Putting it
there rather than where the event is recorded is what makes several attackers
work: each one applies its life loss in turn, so the floor sees the total the
previous attacker left behind and stops applying once it is already at 1 —
which is CR 616.1f's re-check, falling out of the placement instead of needing
a special case. Three 10/10s into a player at 3 life now leave them at 1.

The per-defender damage tally is now accumulated as events are applied rather
than summed from their recorded amounts, so damage that is redirected or
replaced away no longer shows up as life lost. Redirecting a whole combat to
Veteran Bodyguard used to log "took 8 combat damage (life: 28 → 20)" against a
player whose life never moved.

**Still open in this phase.** CR 616.1 gives the *affected player* the choice
of which applicable effect to apply; the engine applies a fixed order instead.
That is now a single documented table rather than a cascade spread across two
functions, so it is one place to change when there is a UI to ask through.

Prevention and replacement also remain separate pipelines, and the player and
permanent paths order them oppositely — but that is now a reasoned choice
rather than an accident, and 616.1e permits either. Damage to a *permanent*
replaces before it prevents, because the replacements there are redirects (Jade
Monolith, Personal Incarnation) and applying the shield first would spend it on
damage that then leaves for another recipient. Damage to a *player* prevents
before it replaces, because the replacement there is a floor that has to read
the life total it is flooring against, which means running immediately before
the life loss. Unifying them properly means implementing 616.1's choice, not
picking one fixed order — and the two constraints above are what that choice
would be selecting between.

**Done — the turn-step registries are text-keyed.** `UNTAP_RESTRICTIONS` and
the bonus-draw half of `DRAW_STEP_MODIFIERS` were name-keyed tables holding
data that is plainly readable off the card. They now derive from oracle text in
`engine/untap_restrictions.py` and `engine/draw_step_modifiers.py`, following
`cast_restrictions.py`. All five untap cards reproduce their old entries
field-for-field, no other card in the pool is newly claimed, and the templates
now cover cards the engine has never seen: a different power threshold, a
different color, a larger untap allowance, a bigger bonus draw, or the "as long
as this is untapped" qualifier on a restriction that never carried it.

Island Sanctuary stays name-keyed on purpose. What it grants is one specific
protection quality ("except by creatures with flying and/or islandwalk"), so
deriving its trigger from text while the effect stays hardcoded would move the
card-specificity out of sight rather than remove it. It generalizes when a
second card grants a *different* quality and the quality itself gets parsed.

Removing the untap entries also exposed something the guards had been hiding: a
name-keyed hook claims **every** sentence of its card in `parse_coverage.py`, so
Magnetic Mountain's upkeep clause had been riding along unexamined. It turned
out to be genuinely implemented and is now declared in `HANDLER_CLAIMS`. That
is a general property worth remembering — each name-keyed entry deleted turns a
wholesale claim into per-sentence claims, and the difference is text nothing
actually parses.

**Done — `draw` and `discard` are replacement events, and a replacement can
ask.** These were recorded as blocked on phase 4's pending-choice queue, on the
grounds that both replacements are optional ("you *may* put it on top of your
library") while `apply_replacements` returns synchronously. That framing was
wrong about what was needed: the general pending-choice queue is a much bigger
change than *these* effects require, because a replacement always knows the
question it is asking at the moment it intercepts.

`engine/replacement_choices.py` is that narrower thing. An interceptor that
needs a decision offers a `ReplacementChoice` — a seat, labelled options, a
default, and whatever the resolver will need. An interactive seat gets it queued
on `game.pending_replacement_choices` and the event is suspended; every other
seat takes the default immediately. Both paths finish through the same
registered resolver, which is the property that matters: there is no longer an
inline AI branch and a `confirm_` method that have to agree forever. They had
already drifted — the two paths logged different messages for the same outcome.

Three bespoke flows collapsed into it: Library of Leng's discard destination,
Aladdin's Lamp's look-at-the-top-X, and Ring of Ma'rûf's outside-the-game card.
Gone with them: three `pending_*` `Game` fields, the `TOP_OF_LIBRARY_DISCARD_SOURCES`
name frozenset (the interceptor reads the text), and `_discard_card`'s
`TODO(card-hooks)`. The three `confirm_*` methods and the `pending_*` shapes
survive as thin views over the queue so the web layer and its tests are
untouched, and `_draw_with_lamp` — a helper named after one card — is now
`_draw_with_replacements`.

Generalizing the queue also closed a latent gap for free: the web layer's
"seat is now AI-controlled" safety net only covered Library of Leng, so a lamp
or Ring prompt on a seat handed from a human to the AI would have stalled the
game. It is now generic over the queue and covers every interactive
replacement by construction.

Adding an interactive replacement is now two registrations and no new `Game`
field, confirm method, or prompt plumbing.
`tests/rules/test_replacement_choices.py` proves that by registering one at
runtime and driving it through the generic entry points.

**Done — cost taxes are text-keyed.** Gloom was two hand-written functions in
`card_hooks.py` keyed by its name. "<colour> spells cost {N} more to cast" is a
template Magic reprints constantly, so `engine/cost_modifiers.py` derives the
tax from oracle text: a filter (colour, card type, cast vs activate) plus an
amount, applied once per taxing permanent. The old and new tax agree on **2,214
comparisons** — every card in the pool as both a spell and an activation source,
against boards holding zero, one and two Glooms — so the swap is provably
behaviour-preserving. `card_hooks.py` lost another 198 lines.

Increases only. Cost *reduction* is at least as common in later sets, but it
clamps at zero and interacts with alternative costs, and there is no card in the
pool to verify an implementation against — so a negative test pins that "costs
{1} less" yields nothing rather than being misread as an increase.

**Done — a single "becomes tapped" choke point, and a bug it exposed.**
Chasing the last `MANA_PRODUCTION_MODIFIERS` entries turned up that **Lifetap
was filed under the wrong event**. Its text is "Whenever a Forest an opponent
controls *becomes tapped*, you gain 1 life", but it was registered on the
tapped-for-mana hook — so tapping an opponent's Forest with Icy Manipulator,
or any other way, granted nothing. Two existing tests covered it and both used
the mana path, so nothing caught it.

The engine set `perm.tapped = True` in **seventeen** places, which is why a
trigger could only ever see whichever one its implementer wired into.
`Game.become_tapped` is now the single transition, firing "becomes tapped"
triggers from one place, and fifteen of those sites route through it.

Two deliberately do not, and both are rules, not oversight: a permanent that
*enters* tapped was never untapped on the battlefield so it does not become
tapped, and re-tapping something already tapped is no state change at all
(CR 701.26a, "only untapped permanents can be tapped"). Both are pinned by
tests rather than left as comments.

Lifetap stays **name-keyed** for now, honestly: the compiler parses *zero*
triggered abilities for it, so there is no condition kind to emit. Mana Flare's
trigger does parse (`land_tapped_for_mana`) but lowers to nothing. Moving these
onto `engine/events.py` needs the parser to produce the conditions first — that
is the real remaining task, not the fire site.

Also worth recording: Mana Flare and Gauntlet of Might are triggered *mana*
abilities (CR 605.1b — they add mana, so they never use the stack) and are
correctly resolved inline. Lifetap is not one: it gains life, fails 605.1b's
"could add mana" criterion, and should use the stack. It still resolves inline.
That is a separate, smaller divergence from the missing-trigger bug fixed here.

Cast-trigger hooks (six cards name-keyed for conditions the parser already
understands) move onto the same bus.

Phase 4's `Game.pending_choices` is still its own job. What landed here covers
choices a *replacement effect* raises; the twenty remaining `pending_*` fields
are choices raised by resolving spells and turn-based actions, which need the
answer routed back into a partly-executed effect rather than into a resolver
that owns the whole event.

The per-card `PlayerState` fields the shields read (`forcefield_capped_sources`,
`reverse_damage_charges`, `color_prevention_shields`, …) are deliberately
untouched: they are the *state* an interceptor reads, and replacing them with a
generic shield list is a separate change that reaches the web payload and the
AI simulator. Splitting it kept this one behavior-preserving.

## Silent-support bug found and closed (Shahrazad)

Chasing per-card test coverage turned up 16 ARN cards named in no test at all,
and one of them was not merely untested but wrong. **Shahrazad reported
`supported=True` and resolved as a complete no-op** — "Resolved supported
pattern for Shahrazad without state mutation".

The cause is structural, not a typo. `SUPPORTED_SPELL_PATTERNS` is a whitelist
of bare substrings, one of which is `"loses"`; Shahrazad's text contains "loses
half their life", so the compiler emitted a `spell_pattern` marker, and
`supported` is set as soon as *any* instruction exists — even one that carries
no behavior. Three separate guards said the card was fine: parse-coverage
considered its text claimed, `CARD_VERIFICATION.md` marked it ✅ pass, and
`support_report.py` counted it among 369/369.

Worse, `parse_coverage.py`'s acknowledgement described behavior that did not
exist: "the card resolves with the life-halving only". Nobody had checked the
reason string against the code.

Fixed by implementing the simplification the acknowledgement already promised —
subgames stay out of scope, the caster is treated as the winner, and every other
player loses half their life rounded up. The log says the subgame was not
played, because a simplification a player can see is a different thing from a
card that quietly does nothing.

`tests/engine/test_no_hollow_support.py` checks the property directly: every
supported instant and sorcery must have at least one instruction with a
registered handler. Permanents are excluded — they legitimately work through
statics, auras, layers and the step tables. A second test pins that no spell is
carried by a bare whitelist pattern alone.

**The parse-coverage attribution had the same blind spot.** Its minimal-prefix
search assumed a rule's text anchor sits in the *leading* sentences, so a rule
anchored in a trailing sentence claimed everything before it for free. That is
the silent-rider bug the script exists to catch, in the script itself. It now
falls back to the smallest single sentence that reproduces the parse, which
immediately exposed three more cards (Farmstead, Living Artifact, Simulacrum)
whose leading sentence had been riding along unexamined. All three turned out to
be genuinely implemented by the same handler, and now say so in
`HANDLER_CLAIMS` with a pointer.

## Verification by behavioural equivalence

Manual verification does not reach 26,000 cards, so cards that run the same
engine paths are now grouped: `engine/behaviour_signature.py` builds a key from
everything the engine branches on (types, keywords, mana produced, compiled
instructions/triggers/activated abilities with payloads, static lines, and the
normalized text the text-keyed channels read), masking only what it handles
generically — numeric literals and which colour. An untested card whose class
contains a *passing* card is reported `equivalent` instead of `untested`.

On the current pool: **322 distinct behaviours across 369 cards, 65 cards in 18
classes**. It has nothing to do here yet — everything is already marked passing
— so its value is entirely for the sets to come. Of the 16 untested ARN cards,
6 would have been covered by a peer (Bird Maiden→Air Elemental, Aladdin's
Ring→Rod of Ruin, Dandân→Sea Serpent, Moorish Cavalry→War Mammoth, Flying
Men→Air Elemental, Stone-Throwing Devils→Elvish Archers); the other 10 are
behaviourally unique and need their own tests.

The status is **derived on read, never stored**. `card_verification.json` keeps
only what a person recorded, so a derived claim can never be mistaken for a
check, and it withdraws itself if its peer is later marked failing.

**The failure mode is the whole design problem.** A signature that stops
distinguishing two behaviours does not error — coverage *rises* and the output
looks better. The first version dropped `produced_mana`, activated-ability
payloads, and the oracle text the text-keyed channels read, and reported 74
covered cards instead of 38 by declaring Flight equivalent to **Control Magic**
(grant flying vs. steal the creature), Forest to Badlands, and Sol Ring to Mox
Emerald. Nothing about that output looked wrong.

So the classes are ratcheted through `scripts/behaviour_classes_snapshot.json`
and guarded in CI: any new or changed class must be reviewed and accepted. That
guard immediately earned itself — tightening colour masking merged four more
classes (Bad Moon/Crusade, the Elemental Blasts, the five Circles of Protection,
the four Laces), each of which had to be checked as genuinely colour-parameterised
before acceptance. `tests/engine/test_behaviour_classes.py` also pins named pairs
that must never merge, one per input a real signature bug dropped.

**What it does not claim.** Equivalence says "this card runs no engine path a
verified peer didn't" — not "this card is correct". It cannot catch a card whose
*data* breaks a generic path, and it inherits its peer's correctness. Shahrazad
is the cautionary case: a human marked it ✅ pass while it did nothing, and
anything derived from a card like that inherits the error. Whenever a new
text-keyed behaviour is added to the engine, check that the signature still
distinguishes the cards it applies to.

Incidental: `card_verification.json` held a stale lowercase `'gloom'` entry —
370 results for 369 cards.

## Phase 6 — CR 613 layer system 🟡 started

**Done — layer 7c is now non-destructive.** The audit's specific complaint was
that continuous effects accumulated into `power_bonus` and had to subtract
themselves on the next pass, with each effect keeping its own record of what it
had contributed; a mismatch compounded on every refresh, and CR 611.3a makes
that refresh constant. Aspect of Wolf shipped exactly that bug
(`tests/regressions/test_batch17.py`).

Layer 7c now splits by lifetime: `power_bonus` is persistent (counters,
one-shot boosts), while `static_buff_*` and `derived_buff_*` are *derived* —
cleared and rebuilt from the current board each recompute, so nothing records
what it contributed because nothing has to take it back. The conditional
"as long as …" bonuses and Aspect of Wolf moved onto the derived channel and
their bookkeeping keys are deleted. Each derived channel is cleared by the same
function that rebuilds it, which is the invariant that keeps the bug out.

`tests/rules/test_continuous_pt.py` pins the property rather than the cards:
recomputing twenty-five times equals recomputing once, a condition going false
removes its bonus with nothing to undo, and continuous effects never leak into
the counter channel.

**Done — the layer system itself.** `engine/continuous.py` implements CR 613
properly: layers 1–7, layer 7's sublayers 7a–7d, timestamp ordering (613.7),
and the dependency system (613.8) that overrides it. Dependency is detected
*generally* — by asking what an effect would do before and after applying
another — rather than by enumerating known card interactions, with the
loop fallback (613.8b) and re-evaluation after each application (613.8c) the
rule requires. Constructors exist for every layer: control (2), type (4),
colour (5), ability add/remove (6), and P/T set/modify/switch (7a–7d).

`tests/rules/test_layers.py` tests it against the rule text and CR 613.9's
worked examples, not against particular cards — sublayers outranking
timestamps, a colour change feeding a colour-keyed anthem, animating a land so
a creature anthem reaches it, control change before a controller-keyed effect,
a dependent effect waiting despite an earlier timestamp, and a dependency loop
terminating in timestamp order.

**Layer 7 is live.** `Permanent.effective_power`/`effective_toughness` now
compute through it via `engine/layer_bridge.py`, replacing the hand-ordered
property. The swap was gated on a differential (`tests/rules/test_layer_bridge.py`)
that checks the layer result against the old implementation — preserved
verbatim in the test file so the guard keeps meaning something — across every
combination of the channels and every creature in the pool.

That differential caught a real bug: the old path swapped which stat it read
for a P/T switch but dropped attacking-only buffs on that branch, so a switched
attacker under Orcish Oriflamme lost its bonus. 613.4d says the switch takes
the values as they stand after 7c, which includes it. The layer system gets it
right and the test pins the difference.

**Layer 6 is live.** `engine/keywords.py` is now the single write API for
keyword abilities: `grant_keyword` / `remove_keyword` record each one in order
with a timestamp, and `Permanent.has_keyword` resolves them through layer 6.
Printed keywords are seeded as copiable values, so a removal can take a printed
ability away and a later grant can restore it — CR 613.9's worked example.

What that replaced: one metadata flag per keyword per direction
(`gains_flying`, `gains_flying_until_eot`, `loses_flying`,
`gains_trample_until_eot`, …) read by an if-chain that checked removals first
and so made removal always win regardless of order — a rule the rules do not
have — and that needed a new flag, a new branch, and a new entry in the cleanup
key list for every keyword. Fourteen write sites and four readers moved over;
until-end-of-turn grants now expire in one place instead of per-keyword.

Two live readers were quietly wrong and are fixed by the move: the
Earthquake/Hurricane flier sweep and the banding check in declare-attackers
both read the grant flags directly, so they missed any ability granted by
another route.

**Layers 4 and 5 are live.** Type-changing and colour-changing effects are
collected into the system and drive the accessors:

- `Permanent.is_creature` and `has_type` compute through layer 4, so animation
  (Kormus Bell, Living Lands, Jade Statue) *adds* the creature type while a
  basic-land-type change (Evil Presence, Phantasmal Terrain) *replaces* the
  land's subtypes — a distinction one flag could not carry.
- `Permanent.effective_colors` computes through layer 5, replacing the
  hand-written precedence chain of colour override → copied colours → printed.

Seeding needed care: the engine models a copy by stamping
`absolute_power`/`absolute_toughness`, which apply in 7b, so the seed must use
the permanent's *own* printed stats or the copy is counted twice. Likewise
colours seed from the permanent's own card, because Vesuvan Doppelganger
deliberately records no copied colours so its printed blue shows through. Both
were caught by existing tests rather than by inspection.

| Layer | Status |
| --- | --- |
| 1 copy | constructors only — the engine models copies with metadata overrides |
| 2 control | constructors + tests; storage not wired |
| 3 text | constructors only |
| 4 type | **live** |
| 5 colour | **live** |
| 6 abilities | **live** |
| 7 P/T | **live** |

**Seventeen of the scattered subtype reads now go through layer 4.** They were
each re-deriving "is this a Swamp now?" from the printed type line *and* the
override separately, so every one had to remember both halves. Migrated: the
characteristic-defining Swamp and Forest counts, the no-Islands state trigger
and its two upkeep siblings, the Mountain and Swamp predicates, the Aspect of
Wolf Forest count, the conditional-land bonus, the islandwalk block check, and
the sacrificed-land type check.

Four of them mapped a land type to a *mana symbol* — the AI's land evaluation,
the mana-drain handler, and both halves of the tap-for-mana path — so they now
share `Permanent.basic_land_types` / `basic_land_mana` rather than each
carrying its own five-branch chain. `effective_produced_mana` derives from the
current types only when layer 4 has actually changed them, because a dual land's
printed production is read positionally and deriving it from types would reorder
the symbols.

**Performance.** Characteristics are computed rather than stored, and
`is_creature` is called in tight state-based-action and combat loops, so the
per-card text parsing behind seeding is cached on the same immutable fields
`compile_card_oracle` keys on. That took `is_creature` from 4.6µs to 2.8µs and
`effective_power` from 8.1µs to 6.1µs, and the suite back under nine seconds.

**Layer 2 is structurally different from the others, and that is the finding.**
Layers 4–7 were flags a reader consulted, so wiring them meant changing the
reader. Control is not stored at all — a control change *moves the permanent
between `player.battlefield` lists*, so "who controls this" is answered by which
list it is in. Making the controller a derived characteristic means every site
that reads zone membership has to stop doing so first, and there are **129** of
them.

`Game.all_permanents` / `permanents_with_controller` / `permanents_matching`
are that seam, and also close the audit's largest duplication hotspot (the
open-coded `for player: for perm in player.battlefield` double loop, 27
occurrences). `tests/rules/test_layers.py` pins the current
control-as-zone-membership model so the day it changes is deliberate rather
than incidental.

**Still open:** layer 2 storage (behind the 129 iteration sites above) and
layer 3 (text-changing) storage.
Twenty `land_type_override` references remain, but most are *writes* (the
storage layer 4 reads) or spots that need the override's raw value rather than a
yes/no answer — the UI payload, Magical Hack's text remap, Gaea's Liege's
revert. Those want layer 3 and a proper write API, not another `has_type` swap.

And layer 1, the deep one: modelling copies as real copiable values instead of
stamped `absolute_power`/`copied_colors` overrides. That is what would let
`effective_card` disappear, and it is the source of the two seeding subtleties
this phase already tripped over.

## Phase 6 (original scope) — CR 613 layer system

`engine/continuous.py` with typed
`ContinuousEffect(layer, sublayer, timestamp, source, scope, apply_fn)`;
`effective_power`/`effective_toughness` recompute through it; `pt.py` stays the
write API. Destructive `power_bonus` accumulation and the ad-hoc layer 1–6
metadata (`land_animated`, `color_override`, `has_islandwalk`) migrate to typed
effects. **Unblocks static-ability lowering** — which is why statics migrate
last, and why the grammar currently parses them but declines to lower them.

## Phase 7 — delete the shadow parser, decompose the stack 🟡 started

**Done — the seam exists and carries 50 cards.** `engine/targeting.py` answers
"what does this spell target?" from the compiled program instead of re-reading
oracle text. `legality.py` now consults it first and falls back to its cascade,
so the two can no longer drift apart on anything derivable.

A kind is derivable when the program carries the evidence: an Aura's
``Enchant <subject>`` line, or an instruction's ``type_filter`` payload. That is
**50 cards today**; the other 319 still need the cascade. The gap is concrete
rather than vague — Lightning Bolt and Fireball are both a bare ``deal_damage``
and differ only in text the instruction does not record, so `deal_damage` and
`target_gains_life` cannot be resolved until lowering emits target specs. That
is the precise ask on the grammar, and `test_shadow_parser_reliance_does_not_grow`
ratchets it so a parser change can't quietly take evidence away.

The derivation drives the **target picker**, not just serialization:
`cast_target_spec` takes its `kind` from the program and lets the cascade supply
the per-kind flags it doesn't model yet (`own_only`, stack filters,
`sacrifice_cost`). Verified against the live API — Shatter/Stone Rain/Disenchant/
Flight/Evil Presence/Steal Artifact derive, while Lightning Bolt (`any`),
Fireball (`divided`), Animate Dead (`graveyard_creature`) and Royal Assassin
(`none`) fall back correctly.

Writing it, the differential caught two bugs in the derivation before either
could ship:

- **Animate Dead** reads "Enchant creature card in a graveyard". Matching the
  leading words derived `creature`, which would have offered battlefield
  creatures for a reanimation spell whose target index means a graveyard slot.
- **Every permanent with a targeted activated ability** — Royal Assassin,
  Pyramids, King Suleiman, Dwarven Demolition Team — derived a cast-time target
  from its ability's filter. Only a spell picks targets as it is cast.

Both are now named tests rather than comments.

**Done — lowering now carries target specs, so the block is lifted.** The
grammar's AST always had a full `TargetSpec` (quantifier + `ObjectFilter`);
lowering validated it and threw it away, which is why Lightning Bolt and
Fireball both compiled to a bare `deal_damage`. Lowering now records a
`targets` description on damage, destroy, tap/untap, pump, gain-life and draw
instructions, and `targeting.py` reads it: **59 cards derive**, up from 50,
still with zero disagreements against the cascade.

The number matters less than what it means. Targeting coverage is now a
*by-product of parser migration* rather than a second body of text rules — every
category the grammar takes over brings its cards with it, automatically.

Making that safe needed one supporting change. `targets` is a key no handler
reads, but the grammar-vs-legacy differential and the parse-coverage deletion
probe both compared payloads with `==`, so a purely additive description read as
a divergence. Both now compare `behavioural_payload()` — the payload minus the
declared `GRAMMAR_ONLY_PAYLOAD_KEYS`. That is not a loosening: a key nothing
consumes cannot change behaviour, and without it every migrated card would have
needed an `ACCEPTED_DIFFS` entry, which would have gutted the ratchet.

It surfaced immediately in the probe: Desert's claimed clause silently widened
from one sentence to two, because its first sentence (grammar-lowered, with
`targets`) no longer compared equal to the whole clause (legacy-lowered,
without). That is the mixed-front-end hazard in miniature, and it is now handled
in one place instead of per tool.

The lowering goldens likewise compare the behavioural payload — folding
`targets` into all of them would bury the handler-compatibility contract they
exist to state — with the new key given its own section.

**Still open:** the remaining 310 cards (each arrives as its category migrates),
the per-kind flags (`own_only`, stack filters, `sacrifice_cost`), deleting the
cascade, splitting `stack_casting.py` (2,239 lines) into casting / resolution /
ability-activation, and folding `StackItem`'s single-card fields into a payload
dict.

## Phase 8 — test restructuring for scale 🟡 partly done

**Done:**

- **Both catalog sweeps now cover every set.** The comprehensive-cast sweep
  (renamed `test_every_catalog_card_resolves_without_exception`) and
  `test_each_card_simulates_without_crash` parametrize over
  `cards/manifest.json` instead of a hardcoded `cards/LEA_cards.json`. Arabian
  Nights — 78 cards, tracked as a complete set — had **never been swept**; all
  78 pass. A newly ingested set is now swept the moment it is added to the
  manifest. Suite: 3,247 → 3,405 tests, still under 9 seconds.
- **`catalog` / `catalog_by_name` fixtures** for pool-wide tests, alongside the
  per-set pools (which stay separate so name lookups remain unambiguous).
- **CWD-relative card paths removed** from the AI, trigger-table, deck-builder
  and web-API tests. The suite now runs from any directory; it previously
  failed collection anywhere but the repo root.

**Still open:** splitting the 9,370-line `tests/sets/test_lea_cards.py` by
category, a fixture factory to stop conftest growing per set, and a documented
per-set test convention for the 137-set march.

---

## Standing invariants

Anything that weakens these is a regression regardless of what it enables:

1. **No silent wrongness.** A card may fail loudly as unsupported with a
   reason; it may never resolve as something other than what it says.
2. **The suite stays fast.** Under ten seconds today; the CI budget fails over
   twenty.
3. **Determinism.** A given seed reproduces a run exactly. Parsing and lowering
   are pure functions of card text.
4. **Ratchets only tighten.** Coverage floors, probe baselines, and accepted-diff
   lists shrink or hold — never grow without review.
5. **Card names live only in `card_hooks.py`.**
