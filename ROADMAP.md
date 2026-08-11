# Scaling Roadmap

Target: grow the card pool from 369 unique cards (LEA/LEB/2ED/ARN) to the full
release line — **137 sets, 33,594 printings, 26,113 unique cards** per
`set_progress.json`.

This document records the audit that motivated the work and the phased plan
that follows from it. Phases 1, 2, 3, 4, 7 and 8 are done; 5 and 6 are partly
done. **The parser migration is finished** — `engine/parsing/` is deleted and
`engine/grammar/` is the engine's only parser; see "`engine/parsing/` is
deleted" at the end.

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
  no sweep, and `ARCHITECTURE.md` claimed otherwise. **Closed in phase 8** —
  `tests/engine/test_catalog_sweep.py` parametrizes over `cards/manifest.json`,
  so a newly ingested set is swept the moment it is registered.

---

## Approach: a grammar front end, migrated strangler-fig ✅ arrived

The end state was a real parser: tokenizer → recursive-descent grammar over
Magic's card templating → typed AST → lowered to the existing
`OracleInstruction` IR, executed by the existing effect handlers, with the flat
`@parse_rule` registry deleted category by category as the grammar took over.
**That end state is reached** — `engine/parsing/` is gone, and the section
"`engine/parsing/` is deleted" near the bottom of this file records the last
wave. What follows is the plan as it was written, because the two properties
below are what made it work and they are still the contract for new productions.

Two properties made this tractable rather than a big-bang rewrite:

**Full token consumption.** A production that matches must account for every
token of its line; leftovers raise `GrammarError`. "Parsed" therefore means
"understood in full". A grammar gap is a *loud* failure (card unsupported, with
the offending clause named) and never a quiet mis-resolution. This is the
structural fix for the bug class the deletion probe detects empirically — and
the probe stays on anyway.

**Category gating.** The grammar ran on every line from day one, but its
output was only *used* when every category it lowered to was switched on in
`GRAMMAR_CATEGORIES`, everything else falling back to the legacy rules
untouched. So new grammar work was exercised against the whole pool while still
unused, enabling a category was a one-line change made after its differential
guard was green, and a category's legacy rules were deleted only once the
ratchet showed the grammar claimed every line they used to.

*(With the registry gone the gate means something else: a category left off no
longer routes its lines anywhere, it makes those cards unsupported. It is now
held equal to what `lower.py` can emit.)*

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
- **CI** (`.github/workflows/ci.yml`) runs the suite, a suite-time budget (20
  seconds then; 35 now, with the measured baseline recorded beside it), all four
  guard scripts in `--check` mode, and a staleness check that the generated
  trackers are committed. `requirements.txt` pins the versions.
- **Migration guard:** all 369 `OracleProgram`s verified byte-identical before
  and after conversion; `tests/engine/test_card_format.py` holds the format,
  layout, variable-P/T, and reprint-identity invariants going forward.

**Closed later:** the five stragglers this phase left naming
`cards/LEA_cards.json`. Two had already been fixed by the time anyone came back
to the entry — `support_report.py` while chasing the Revised experiment, and
`tests/helpers.py` when the per-set fixtures landed — so the paragraph claiming
five was two-fifths wrong, which is the ordinary decay rate of a backlog note
about code. The other three now take **`--set <CODE>` / `--all` / `--cards
<path>`** through `scripts/set_argument.py`, resolved against the manifest.

The interesting part was not the plumbing but what the default should be.
`run_duel.py` and `simulate_ai_games.py` really are single-set by design: each
plays one fixed decklist, so their default is the *code* `LEA` and a set that
cannot supply the list stops rather than quietly playing a shorter game.
`retrieve_oracle.py` was not — it was single-set by accident, and a lookup tool
that could not see four of the five sets answered "Library of Alexandria" with
Library of Leng's text. It defaults to the whole pool now, which is the same
call `support_report.py` had already made for the same reason: a report over a
silently smaller pool is a true answer to a question nobody asked.

Guarded by `tests/engine/test_script_set_argument.py`, which holds the loud
failure (an unknown code exits naming the codes that exist) and extends the
tests' no-spelled-out-filenames rule to `scripts/`.

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

Recorded as still open at the time: regeneration, life, draw/discard and zones
were parsed and lowered but not switched on — `zones` because "Draw a card"
mapped to two different handlers depending on who draws, and `mana` because
`add_mana_from_text` re-read clause text and Black Lotus bundled a sacrifice
cost into its instruction. **All four are switched on now** (`life`, `mana`,
`regeneration`, `zones` are in `GRAMMAR_CATEGORIES`); the handler rework each
was waiting on landed with the categories.
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

### Layer 4 finished: one answer to "what type is this?"

`land_type_override` had 17 sites. Nine are writes (recording the effect, which
is the point), one is the layer-4 builder that turns it into a CR 305.7 subtype
*replacement* — and **seven were readers going around the layer system**, each
with its own version of the rule. They did not agree with layer 4 or with each
other.

Two live bugs came out of it:

- **A land was two types at once.** `legality.py` matched *printed type OR
  override*, so a Mountain turned into an Island was a legal "target Mountain"
  **and** a legal "target Island". CR 305.7 says the printed type is gone.
- **Flashfires never destroyed Plains.** The handler stripped a trailing "s"
  from the named type, and Plains is spelled the same singular and plural — so
  it looked for "plain", a subtype no land has. The substring match hid it
  perfectly, because "plain" *is* a substring of "plains". `singular_land_type`
  checks the known types before guessing at the word's shape.

The second bug is the one worth remembering: **the loose match was not just
imprecise, it was concealing a second defect.** Tightening the reader is what
made it visible, which is the argument for having one accessor rather than
seven approximations.

A test was written around the bug, too. `test_tsunami_destroys_all_islands`
fabricated a type line of `"Basic Land - Islands"` — plural, a line no Magic
card has ever had — with a comment explaining it was shaped that way so the
substring check would match. It uses the printed cards now.

`tests/engine/test_layer_reads.py` holds the line: a raw `land_type_override`
read outside the layer-4 builder fails, with `card_hooks.py` acknowledged by
name (Gaea's Liege reverting the override it set itself is bookkeeping, not a
type question). A second test fails if that acknowledgement ever goes stale.
Verified by reintroducing the bypass. *(That acknowledgement is gone, and the
staleness test is what removed it — see "Layers 3 and 4 have write APIs" below.
It was not only bookkeeping: reading the type back to decide whether to clear it
was wrong on any land something newer had changed.)*

**Layers 4, 5, 6 and 7 are now all read through the layer system.** What remains
is layer 1 (copies), layer 2 (control, which the earlier audit established is
zone membership here rather than a stored flag) and layer 3 (text-changing).
*(Layer 2 is done — see "Layer 2: the readers first, then the storage" below.
Zone membership is the projection now, not the storage.)*

### Layer 3: apply the text change once, not at each reader

Sleight of Mind replaces a colour word in a permanent's rules text. CR 613.1c
puts that in layer 3 — *before* anything reads the text — and the engine applied
it at each reader that had been taught about it. Protection honoured the remap.
Magnetic Mountain went on blocking blue creatures and Gloom went on taxing white
spells, their text notwithstanding.

`Permanent.effective_card` applies it once, so the text-keyed tables (untap
restrictions, cost modifiers, draw-step bonuses) never learn that text can
change. The existing `_remap_color_filter` helper — a per-consumer patch applied
to compiled colour filters — is the shape this replaces, and is exactly why the
remap reached three readers and not the rest.

Two details the implementation has to get right, both pinned:

- **A swap must not collapse.** Remapping black→red *and* red→black by running
  the substitutions in sequence turns every black into red, then every red —
  including the ones just written — back into black. One pass over a single
  alternation.
- **Whole words only.** Without a word boundary, "red" rewrites the "red" inside
  "requi**red**" and "conside**red**", and reminder text is full of both.

*The first is superseded in part — see "Layers 3 and 4 have write APIs, and both
needed timestamps" below.* One pass over a single alternation is right for the
substitutions **within one effect**, and is still pinned there. Storing *two*
Sleights of Mind in one merged table was the mistake: CR 613.7 applies them in
timestamp order, and doing so gives neither of the answers a merged table can.

The no-remap path returns the card object itself, unchanged and unallocated,
because `effective_card` is read on nearly every rules query.

**Layers 3, 4, 5, 6 and 7 now all resolve through the layer system.** Remaining:
layer 1 (copies) and layer 2 (control, already established here as zone
membership rather than a stored flag). *(Both are done — see below. Layer 1 did
**not** retire `effective_card`, which this section predicted it would; it
retired the *other* half of it, and the measurement of what is left is in
"Layer 1: a copy is a value, not five stamps".)*

### The last card-rewriting effect: Animate Artifact

Animate Artifact was the remaining place where a *characteristic* change was
made by rebuilding the object. It spliced "Creature" into the artifact's type
line, baked P/T into `raw`, swapped the new `CardDefinition` onto the permanent,
and stashed the original to restore on removal — remember-and-undo applied to
the card's identity. It is now two derived effects from one line: layer 4 adds
the creature type, layer 7b sets P/T, both read from the attached Aura.

**Two rules bugs were inside that rewrite**, and they compounded:

- The P/T was clamped to a minimum of 1, so an artifact with mana value 0
  animated to 1/1 instead of 0/0.
- CR 704.5f's state-based action tested `card.primary_type == "creature"` — the
  *printed* type — so it would not have swept an animated permanent even at 0
  toughness.

Either alone would have been invisible. Together they meant Animate Artifact on
a Mox or a Black Lotus produced an immortal 1/1 where the rules give a 0/0 that
dies immediately. Both are fixed; the SBA reads `is_creature`.

Two tests were passing for the wrong reason, and both are the same shape:

- `test_601_2c_...` animated a Black Lotus and asserted the Aura was on the
  battlefield. Correct behaviour now kills the Lotus and takes the Aura with it
  (CR 704.5m), so the test needed an artifact with a nonzero mana value to be
  about CR 601.2c at all.
- The alpha sweep asserted "the cast permanent is on the battlefield" while an
  *identical stock card* sat on the same battlefield. Black Lotus sacrifices
  itself to its own mana ability, so the assertion had never once been
  satisfied by the card under test. Changing the stock artifact exposed it.

Also folded in: `permanent_state._eff_card` was a local re-implementation of
`Permanent.effective_card` covering only the copy half, so it silently skipped
the layer-3 text change added in the previous pass. A second opinion that was
correct when written and wrong a commit later — which is the argument for the
accessor, not for remembering to update both.

**Every layer that changes a characteristic now resolves through the layer
system.** What is left of layer 1 is copy *identity* (`copied_card`), which is
already metadata-driven and read through `effective_card`; and layer 2, which
this engine models as zone membership rather than a stored flag. *(Superseded:
layer 2 resolves through the layer system too — `engine/control.py` records the
contributions and the battlefield lists became its projection. See "Layer 2:
the readers first, then the storage".)*

### The grammar backlog was ranked by symptom, not by leverage

`GRAMMAR_COVERAGE.md` ordered its backlog by failing-line count and described
each row as "a production the grammar still needs, ordered by how many lines it
would unlock". Both halves of that were misleading, and acting on it would have
meant spending the migration's effort in the wrong place.

Counting distinct *sentences* per reason instead shows why:

| Reason | Lines | Distinct | What it really is |
| --- | ---: | ---: | --- |
| expected a subject | 199 | 78 | a long tail — Chaos Orb, Lich, Fastbond, one production each |
| unrecognized effect verb | 89 | 31 | also a tail |
| expected 'be' | 12 | **2** | **one production, twelve lines** |
| modal line | 10 | 2 | one production |
| expected a quantity | 6 | 2 | one production |

The top row is 78 different sentences wearing one error message. The rows worth
doing are near the bottom, where a handful of distinct texts account for many
lines. Reprints inflate the first column further — a card in four sets counts
four times — which is why the ranking flattered the tail.

The table now carries both columns and says to sort by the ratio. That is a
permanent change to the work queue, not a one-off observation.

**Acting on it:** `expected 'be'` turned out to be the combat-restriction
family — "can't attack unless defending player controls a <land>" and "can't
block creatures with power N or greater" — which the engine *already*
implements through `engine/combat_restrictions.py`. The grammar simply could
not read them. A production plus a lowering closes that, and the differential
holds the grammar's payloads to the legacy table's byte for byte, which is what
allowed the category to be switched on. Executed coverage 34.9% → 35.9%.

The two shapes the production does not claim ("attacks each combat if able",
"can't be blocked by Walls") still fail the parser *by name*. A test asserts
that specifically, because the failure mode to fear is not "unclaimed" — it is
a line that parses to zero instructions and looks handled.

### After the combat restrictions, this pool has no low-hanging fruit left

The re-ranked backlog made the next candidates obvious, and checking them
turned out to matter more than implementing them.

- **`modal line` (10 lines / 2 distinct)** is not a production. The failing
  "line" is the header `Choose one —`; the bullets are separate lines, and the
  grammar parses one line at a time. Lowering it needs multi-line context,
  which is a change to the pipeline's shape rather than a new rule.
- **`expected a quantity` (6 / 2)** is not about numbers — spelled-out numerals
  already parse. It is `discards their hand`, and both cards behind it
  (Wheel of Fortune, Contract from Below) currently compile to *card-named
  fused instruction kinds* (`wheel_of_fortune`,
  `discard_hand_ante_then_draw_seven`). Claiming them properly means
  decomposing into a sequence and adding the handlers that sequence needs —
  the conjunction-kind retirement, not a parser gap.
- **`expected a colour after 'becomes'` (6 / 2)** I actually implemented, and
  then reverted. The production worked on invented text and claimed **zero
  lines in the pool**, because both real cards carry a duration the grammar
  cannot read ("until this creature leaves the battlefield"). Coverage did not
  move. Code that passes its own examples and claims nothing real is worse than
  no code: it looks like progress in the diff.

That last one is the lesson worth keeping: **measure what a production claims
in the pool before keeping it**, not whether it parses the sentence you wrote to
test it. The check is one line — count the pool lines whose instructions the new
production produced.

`unconsumed text` (36 / 18) turns out to sit behind several of these, and is
itself 18 different trailing clauses. So after the combat restrictions, the
remaining backlog for *this* pool is tail all the way down. The leverage has
moved: further grammar work here optimises for 369 cards, while the open
question for the roadmap's goal is whether any of it generalises. Ingesting a
fifth set answers that empirically and would exercise every guard built in this
pass against text none of them has seen.

### Ingesting a fifth set: what it actually cost

Revised (3ED, 306 cards) was fetched, slimmed 64%, and registered. The pool went
from 369 unique cards to **388** — 296 of Revised's cards deduped onto existing
ones by `oracle_id`, which is the first real exercise `printings` has had.

**Eight guards fired.** That is the result, and it is a good one: every one was
either a real gap or a test with the four-set pool hardcoded into it.

Real gaps, all of them the "supported but does nothing" class:

- **Shatterstorm** and **Crumble** compiled to bare `spell_pattern` markers —
  supported, no handler, no-ops on resolution. Exactly Shahrazad.
- **Titania's Song** the same, as a permanent.
- Four more (Armageddon Clock, Mishra's War Machine, Rocket Launcher, Titania's
  Song) reported supported while carrying text nothing parses.

Tests with the pool baked in: an exact printings tuple, an exact set of
variable-P/T card names, an exact set list in the web API, and a
"nothing is ever unsupported" assertion that cannot survive any real ingest.

**The set data is reverted** — finishing the integration means implementing or
classifying six cards and generalising four tests, which is its own piece of
work, not a tail on this one. What is kept is everything the experiment
exposed:

- `test_no_hollow_support.py` asserted "no supported spell lacks a handler" as a
  property of the pool. It is now the **compiler's contract**: a one-shot spell
  whose instructions have no handler is reported unsupported, naming the
  reason. Cost to the existing pool: zero cards. Revised would have added two.
- `scripts/support_report.py` defaulted to `cards/LEA_cards.json`. It printed
  Alpha's 290 cards while the pool had four sets, so "no unsupported cards" was
  a true statement about a much smaller question than it appeared to answer. It
  reads the manifest now, like everything else.
- The pool-shaped tests are pool-relative, and the unsupported set is a named
  ratchet rather than an assertion that it is empty.

The honest summary: the engine's *guards* generalise — they caught every gap on
first contact with unseen text, loudly and by name. The engine's *coverage* does
not yet, and that is what the next set's worth of work buys.

### Starting the Revised backlog with the part that generalises

Of the six cards Revised could not compile, Shatterstorm ("Destroy all
artifacts. They can't be regenerated.") was the one whose gap was not about
Shatterstorm. The engine had four `destroy_all_*` handlers — creatures,
enchantments, lands, and the artifacts-creatures-enchantments triple — with
*identical three-line bodies*, differing only in which types qualify and
whether regeneration may replace the destruction. "Destroy all artifacts" would
have been a fifth copy, and every future noun another.

Both are parameters now. One sweep is registered under all five kinds; the
kinds stay distinct because the compiler, the grammar's lowering table and the
behaviour snapshots key on them, but there is one body. Adding artifacts was
then a single table row, and Shatterstorm compiles and resolves correctly
without Revised being in the pool.

A test asserts every kind in the table has a handler, because the registration
is a loop: a kind added to the table but not seen by that loop would be a
silent no-op, which is the failure this file spent the session removing.

### Three of Revised's six, and why the other three are one job

Implemented, each verified against the printed text with the set still out of
the manifest:

- **Millstone** — mill, as a template. The count is a parameter, spelled out or
  numeric, so this is the mechanic rather than the card. Milling into an empty
  library stops there and does **not** lose the game: CR 704.5b fires on an
  attempted *draw*, and conflating the two is the classic mill bug.
- **Hurkyl's Recall** — "all artifacts target player **owns**". Ownership, not
  control, so a stolen artifact returns to its owner's hand (CR 400.3); the
  engine already distinguishes the two and this asks `owner_index_of`.
- **Crumble** — destroy, then its controller gains life equal to its mana
  value. Deliberately one handler and not a `sequence`: the second clause is
  about *the object the first destroyed*, and by the time a second step ran that
  permanent is in a graveyard. `results` carries values, not objects. When it
  carries objects this becomes two steps and the fused kind goes away — the
  comment on the handler says so, so the debt is visible where it is owed.

**Energy Flux, Titania's Song and Primal Clay are blocked on one thing**, and it
is worth naming precisely rather than filing three card-shaped tickets. The
first two are *global* statics — "all artifacts have …", "each noncreature
artifact loses all abilities and becomes …" — and every `collect_*` function in
`layer_bridge` takes `(perm, oid)`. The bridge cannot see the board, so a global
effect has no way to reach the layers except by writing a flag onto each
affected permanent and cleaning it up later, which is precisely the pattern this
pass spent itself removing. `_recalculate_lord_buffs` is the existing
workaround.

So the work is not three cards; it is **one seam** — giving the layer bridge the
board so a static ability can contribute an effect to objects it does not own —
after which those two cards are table entries. Primal Clay wants the enter-time
choice machinery and is genuinely separate, but small.

### Revised: five of six, and the sixth is a rider

All six of Revised's new cards were implemented and verified against their
printed text. Re-ingesting the set then took the pool to 388 cards, **388
supported, 0 unsupported** — and the guards still found one thing, which is the
part worth recording.

**Titania's Song's real text has a second sentence** my fixture did not: "If
this enchantment leaves the battlefield, this effect continues until end of
turn." The implementation ends the effect the moment the source leaves the
battlefield, which is right for the first sentence and wrong for the second.
The template deliberately matches only the one-sentence form, so the real card
does not match it — and is therefore not claimed.

That is the correct outcome and it cost nothing to discover, because the rule
has been enforced all pass: **a production that matches a line must implement
all of it.** Had the template been written to match "whatever Titania's Song
prints", the card would report supported and quietly lose its effect a turn
early.

The remaining work on it is one rider — a delayed end-of-effect, which the
engine has no representation for yet (`until end of turn` durations exist for
one-shots; a *static* that outlives its source does not). That is a real
feature, not a card.

Everything else the re-ingest surfaced is mechanical and already named: the
`KNOWN_UNSUPPORTED` ratchet correctly reports the six as fixed, Primal Clay
needs an entry in the static-line guard and the variable-P/T property test
widened to accept "chosen on entry" alongside "computed by a
characteristic-defining rule", and the web API test still hardcodes three sets.

### A static that outlives its source, and what Revised still needs

Titania's Song's rider — "if this enchantment leaves the battlefield, this
effect continues until end of turn" — is now implemented, and it is the first
continuous effect in the engine that survives its own source. Detected in
`_refresh_global_statics` rather than on a leave-battlefield hook, because that
method already knows which sources were applying: one that was in the list and
is no longer on a battlefield has left, whichever way it went. The cleanup step
drops the lingering list (CR 514.2), and dropping it *is* the removal, because
the effect was only ever derived from that list.

**Revised still does not land, and the reason changed.** All six cards it was
blocked on are implemented; re-ingesting gives 388 cards, **388 supported, 0
unsupported**. But Revised also reprints Antiquities cards, and three of those —
Armageddon Clock, Mishra's War Machine, Rocket Launcher — report supported while
carrying text nothing parses. They are the same class the pass has been
clearing, found the same way, and acknowledging them to make the ingest green
would be the one thing this file argues against.

So the set is one more card-sized batch away, and the estimate is now grounded
rather than guessed: **six cards cost one seam** (board-wide statics reaching
the layer bridge), **one engine feature** (an effect outliving its source), and
**four test generalisations**. Three of those tests are now pool-relative; the
fourth — the static-line guard's acknowledgement for Primal Clay — is
deliberately withheld until the card is actually in the pool, because the
stale-entry guard is right that an acknowledgement for an absent card is a claim
nobody has checked.

### The last three Revised cards, analysed

Each was compiled and inspected rather than estimated, so the next pass starts
from the gap and not from the card name.

**Mishra's War Machine** — compiles to `deal_damage {amount: 3}` and reports
supported. It loses *both* riders: "unless you discard a card" (an alternative
cost, so the damage is not unconditional) and "if it deals damage to you this
way, tap it" (a consequence conditional on the first rider having applied).
Today it deals 3 to its controller every upkeep with no choice and no tap. The
pay-or-consequence upkeep table already models "deals N damage unless you pay
<mana>" (Force of Nature); this is the same shape with a *discard* as the
alternative, plus a tap conditional on the branch taken.

**Rocket Launcher** — the damage clause parses. Unclaimed: "destroy this
artifact at the beginning of the next end step" (a delayed one-shot the engine
has no representation for — distinct from the *continuous* effect that outlives
its source, which now exists) and "activate only if you've controlled this
artifact continuously since the beginning of your most recent turn", which is
CR 302.6's summoning-sickness clause applied to an artifact's activated
ability.

**Armageddon Clock** — three abilities, none claimed: an upkeep trigger adding
a counter, a *draw-step* trigger dealing damage equal to that counter count to
each player, and an activated ability that any player may use but only during
an upkeep step. The counter-accumulating upkeep trigger has a precedent
(Cyclone's wind counters); the draw-step trigger and the "any player, only
during any upkeep step" activation window do not.

Common thread: all three are **riders and timing windows**, not effects. The
effects themselves — damage, discard, destroy, counters — are all implemented.
What is missing is the vocabulary for *when* and *unless*: a delayed one-shot,
an activation window tied to a step, and an alternative-cost branch whose
outcome a later clause depends on.

That is one coherent piece of work, and it is worth more than these three cards:
delayed one-shots and step-scoped activation windows are two of the commonest
templates in every set after this one.

### Armageddon Clock's third ability, and what Revised still yields

The last named blocker is done. "{4}: Remove a doom counter from this artifact.
Any player may activate this ability but only during any upkeep step" needed two
things, and they are separate checks that both have to pass:

- **the permission** — "any player may activate", which already existed;
- **the window** — "only during any upkeep step", scoped to a *step* rather
  than to a player's own step. The engine had "activate only during **your**
  upkeep" (Cyclopean Tomb, the Clockwork creatures); this is the same step with
  the ownership dropped, which is precisely what lets an opponent wind the Clock
  down. That is the whole point of the card: it threatens everyone, so everyone
  may slow it.

The counter-removal effect is payload-keyed on the counter's name, matching the
accumulation side, so the pair is one template rather than one card.

**Revised still does not land, and the list keeps growing rather than shrinking
by the same amount each time.** Ingesting it now gives 388 cards, **388
supported, 0 unsupported** — and three more cards with unclaimed text: Ivory
Tower and Reverse Polarity ("you gain X life, where X is …" computed from board
state) and Reconstruction ("return target artifact card from your graveyard to
your hand", which has a creature-only sibling already).

That pattern is the honest finding of this whole exercise. Each pass through the
set implements what the last pass found and surfaces a new layer — six cards,
then three, now three more — because the guards only report what a card *claims*
and cannot report what it will claim once the blocking card compiles. **A set is
not a fixed amount of work discoverable up front; it converges.** The useful
number is not "how many cards are left" but "how much smaller is each round",
and it is: 6, 3, 3, with the last two rounds costing riders and windows rather
than architecture.

### Revised is in: 388 cards, 388 supported

The fifth set landed. 306 cards ingested, 296 deduping onto existing ones by
`oracle_id`; the pool went 369 → **388 unique, 388 supported, 0 unsupported**.

It cost, in rounds: **6 cards → 3 → 3 → 1 → 0**, plus one seam (board-wide
statics reaching the layer bridge), two engine features (a continuous effect
that outlives its source; a step-scoped activation window open to any player),
and four pool-shaped tests generalised. The later rounds bought riders and
timing vocabulary rather than architecture — which is the shape you want, since
delayed one-shots and step windows recur in every set after this one.

The last obstacle was not a card. Four new parse rules tripped the deletion
probe, and it took three turns to see why: **the probe's output and the
unclaimed-sentence output are both `(card, sentence)` pairs**, so a
payload-only reading of the failure pointed at the wrong assertion entirely.
The findings, once actually read, were benign — filler words in long phrases,
with the distinguishing words retained — and the baseline was re-accepted after
review, which is what the probe is for.

The durable fix is in the test: the four assertions are tagged `[UNCLAIMED]`,
`[STALE-ACK]`, `[PROBE]` and `[STALE-PROBE]`, so the failure names itself.

### Phase 7: moving cards off the shadow parser by instruction kind

`legality.py` answers "what does this spell target?" by re-reading the card's
text — a second parser every new card has to satisfy. `targeting.py` replaces it
card by card, and the useful measurement is not how many cards fall back (324)
but how many actually *need* to: only **84 supported cards mention "target" at
all**, and only **35** are spells or Auras that pick one as they are cast.

Some of those need no text at all. A lace always targets a spell or permanent;
a counterspell always targets the stack; a graveyard-return always targets a
card in a graveyard. **The instruction kind already says so**, so those cards
can be answered from the compiled program with a small kind→target table rather
than a text cascade. Derivable cards: **64 → 76**.

The existing agreement guard earned its keep immediately: it compares a derived
answer against the *raw* text cascade (not `cast_target_kind`, which now
prefers the derivation and would be comparing the thing to itself), and it
caught two wrong entries in the first table I wrote — a counterspell answered
"spell" where the cascade says "stack", and a text-changer "spell_or_permanent"
where it says "permanent". Both would have changed which prompt the UI raises,
for cards that work today.

I also wrote a second agreement test before noticing that one existed and was
stricter. Deleted; the lesson is to read the guard file before adding to it.

### Phase 7: the cast-target cascade is down to one card

Every supported spell or Aura that picks a target as it is cast now answers from
its **compiled program** — 64 → 76 → 97 → **98 derivable**, with the single
exception of Fireball.

Three levers, in order of how much each bought:

1. **The instruction kind often *is* the answer.** A lace targets a spell or
   permanent, a counterspell the stack, a bounce a creature. A kind→target table
   answered 33 cards with no text reading at all.
2. **One kind, two targets, decided by payload.** A graveyard return names the
   card type it may take — Reconstruction an artifact card, Raise Dead a
   creature card. Same instruction, different data, which is why the type is
   payload and not part of the kind.
3. **Recursing into `sequence`.** A spell written as two steps carries its
   targeting on the step that targets; stopping at the wrapper sent an
   otherwise fully-described spell to the shadow parser.

**Fireball is left deliberately.** Its program is `deal_damage {amount: "x"}`
and says nothing about division, so `None` — "ask the fallback" — is the honest
answer. It becomes derivable when the damage lowering records the divided-target
description, not by guessing in the table. A test names it, so the day that
lowering lands, the test fails and the exception gets deleted.

What remains of `legality.py` is not targeting: it is 970 lines of which the
cast-target cascade is one part, and `stack_casting.py` is still 2,277 lines.
Neither blocks anything; both are size rather than duplication now.

### What is actually left in `legality.py`, measured

Correcting an earlier claim of mine: I said the remainder of phase 7 was "size
rather than duplication". Measuring it says otherwise. `legality.py` has **49
module-level functions, 19 of which read raw oracle text** — every one a second
answer to a question the compiled program could give:

    _cast_requires_graveyard_creature   _cast_requires_graveyard_card
    _cast_requires_artifact             _cast_requires_land
    _cast_offers_copy_creature          _cast_offers_copy_artifact
    _cast_requires_sacrifice_creature   _cast_requires_creature
    _cast_requires_source_of_choice     _cast_requires_divided
    _reanimates_own_graveyard_only      … and the line splitters they share

So the cast-*target* cascade is done (98 of 99 cards derive), but the cast-
*requirement* predicates are the same duplication one layer over: they decide
whether a spell needs a graveyard creature, an artifact on the battlefield, a
sacrifice, and so on, by re-reading text the instruction kinds already encode.

The migration path is the one that just worked for targets, and in the same
order: a kind→requirement table for the cases the kind settles outright; payload
for the cases one kind serves two requirements; recursion into `sequence`. The
agreement guard generalises too — compare each derived requirement against the
existing predicate over the whole pool, and the table cannot drift.

`stack_casting.py` at 2,277 lines really is size, and is a separate job.

### Phase 7 finished: the cast cascade is gone, and it was hiding a bug

All four remaining items landed. `legality.py` is **970 → 775 lines, 49 → 29
module-level functions, and 19 → 0 cast-time text predicates**; the cast half of
the shadow parser no longer exists.

**Fireball first, exactly as predicted.** The AST had carried `divided=True`
since phase 1 and lowering dropped it, so the program said
`deal_damage {amount: x}` — byte-identical to Lightning Bolt. Recording the
division made the last holdout derivable and the test naming it failed on
purpose, which is what a well-written exception test is for.

**Then the flags, which were the actual remainder.** The kind was already
derived for 98 of 99 cards, but the flags beside it — whose graveyard, only the
caster's creatures, which colour on the stack — still came from text, so the
second parser stayed alive for the interesting half. Only 17 cards carry a flag
at all, and the evidence for nearly all of them was already in the program.

The rule that made it clean: **a flag is read off the handler it describes, not
off the card.** `reanimate_creature` calls
`_reanimate_creature_to_battlefield(caster, caster, …)` — always the caster's own
graveyard — so `own_graveyard_only` belongs to the kind, not to whether the words
"your graveyard" appear. Animate Dead is the counter-case that proves it: it
resolves through `_apply_aura_effect`, which pops the chosen index out of
*whichever* graveyard was pointed at, so it derives the same kind without the
flag. Two answers, both read from the code that runs.

**Widening the differential from the kind to the whole spec found a live bug.**
Reconstruction — "Return target artifact card from your graveyard to your hand",
the artifact sibling of Raise Dead — classified as a *battlefield* artifact
target. With no artifact in play the UI enumerated zero legal targets, so the
spell was uncastable, while the engine resolved it perfectly when driven
headlessly. That gap between "works in a test" and "works in the app" is the
whole reason the two-parser problem matters. Fixed by reading the instruction's
own `card_type` payload, and the graveyard picker now applies its handler's type
test, which also makes an artifact *creature* card a legal choice (CR 205.2).

Two gates were measured rather than assumed. Removing the instant/sorcery gate
derives a cast target for **27 permanents that have none** — their abilities'
instructions are hoisted into the card's instruction list — so the gate stays,
and the one real exception (a permanent whose enters-the-battlefield trigger
targets: Oubliette) is its own route rather than a loosening of it.

**What replaced the differential.** It compared two answers; there is one now.
In its place: a per-card table pinning the 26 specs that carry flags, and a
ratchet asserting every supported card naming a target outside an activated or
triggered ability derives its own prompt. Darkpact is the single
acknowledgement — nothing enumerates the ante zone — and a second test fails if
that acknowledgement goes stale.

Verified in the running app, not only in tests: with an Ornithopter in the
graveyard, Reconstruction's serialized `target_spec` goes from
`{kind: artifact, valid_targets: []}` to
`{kind: graveyard_creature, card_type: artifact, valid_targets: [Ornithopter]}`.

### Phase 7 finished: the stack module, split and slimmed

`stack_casting.py` held four jobs in 2,277 lines. It is `engine/mixins/stack/`
now, one mixin per stage of an object's life on the stack, composed onto `Game`
the way `engine/phases` composes one mixin per turn phase:

| Module | Mixin | Methods | Lines |
| --- | --- | ---: | ---: |
| `casting` | `SpellCastingMixin` | 7 | 679 |
| `activation` | `AbilityActivationMixin` | 4 | 557 |
| `resolution` | `StackResolutionMixin` | 9 | 375 |
| `choices` | `PendingChoicesMixin` | 33 | 680 |

`choices` is the fourth because the pending-decision code was the largest
cluster and belonged to no single stage. All 33 of its methods are the same
triple — something arms a pending choice, a `confirm_*` answers it for an
interactive seat, an `auto_resolve_pending_*` takes the default for the rest —
and that pattern is only visible once they sit together rather than interleaved
with the code that arms them.

The split was **verified rather than trusted**: all 51 methods appear exactly
once, and an AST comparison against the old module shows the only body changes
are six function-local relative imports that gained a dot. Two module-level
imports turned out to have been dead already.

**And the stack item stopped growing per card.** `StackItem` had a typed field
for every extra thing a caster could pick — a colour for the Lace cycle, a
second for a text change, a cross-seat list for divided damage, a source for
Jade Monolith — and each also became a field on `OracleExecutionContext`,
because the handler that reads it lives on the far side of resolution. Two
dataclass edits per card family, forever. They are one `choices` dict now:
**StackItem 20 → 16 fields, OracleExecutionContext 15 → 11**. The typed keyword
arguments on `cast_from_hand` stay — that is where a choice is *named* — so what
the fold removes is the transport growing with it. `target_stack_name` was
deleted outright rather than folded: it was the target's name, computed at
construction from the reference sitting next to it.

A dict trades field growth for a key that can be misspelled on one side and read
as absent on the other, so `CHOICE_KEYS` declares them and a guard holds the
engine to the declaration **in both directions** — a key in use but undeclared
fails, a declared key nothing uses fails. Both verified by injection.

The suite caught the exact failure that guard exists for, mid-change: after the
reads moved, `_stack_item_colors` still guarded on
`getattr(item, "new_color", None)` — now always None — so a Chaoslaced spell
silently kept its printed colour. `getattr` with a default does not fail when the
attribute goes away; it just starts answering "no".

### The shadow parser is gone: the ability cascade went the way of the cast one

*(The section that stood here described the `_activated_*` cascade as the last
piece left. This is what happened to it.)*

**19 text predicates → 1.** `legality.py` is **775 → 587 lines, 29 → 9
module-level functions**, and nothing in it classifies a target from text any
more except a single named residue (below). `derive_activation_spec` in
`engine/targeting.py` reads an *ability's* compiled instruction, using the same
tables the cast side already used — because what an instruction targets is a
property of the instruction, not of whether a spell or an ability produced it.
`grant_target_flying_until_eot` is Jump on the cast side and Flying Carpet's
ability on the other, and both want the same creature picker.

**Per ability, which is the whole difference from the cast side.** A spell picks
its targets once (CR 115.1a); an ability picks them each time it is activated
(CR 115.1c), and one permanent may carry several that pick differently. So the
function takes an ability, and `activation_target_spec` scans a permanent's
abilities in order for the first that chooses anything — which is also what
makes a land with a mana ability still raise its real prompt.

**The differential ran at two levels, and only the second is a behaviour
claim.** Level one compared specs for all 114 usable activated abilities in the
pool; level two put every supported permanent on a populated board and compared
the *targets each spec enumerates* — 222 serialized specs, each permanent's
default prompt plus each of its abilities. Level two is what mattered: a spec
difference is only a difference if it changes what the player is offered.

**One live bug, and it was in the half the cascade could see.** Ebony Horse —
"{2}, {T}: Untap target attacking creature **you control**" — classified as
`{kind: creature, attacking_only}`. The cascade read "target attacking creature"
and stopped, so the UI offered the *opponent's* attackers too. The handler does
not: it resolves through a predicate requiring the creature be attacking and on
the activating player's battlefield, and an explicit choice failing that fizzles
rather than falling back. Picking one of the offered targets spent the {2} and
the tap, logged "Ebony Horse ability resolved", and did nothing whatsoever.
`own_only` is read off that predicate, which is exactly why the derivation has
it and a reading of the words did not.

Two more abilities disagreed for the opposite reason: King Suleiman ("Destroy
target Djinn or Efreet") and Elephant Graveyard ("Regenerate target Elephant")
name no card type, so the cascade saw no target at all and
`activation_target_spec` needed a rescue clause that reached into the compiled
instruction *after* classifying. The derivation reads that instruction to begin
with, so the rescue is deleted.

**What was refused, and why that is the better answer.** Jandor's Saddlebags —
"{3}, {T}: Untap target creature." — lowers to `untap_target_permanent`, whose
handler untaps whatever it is handed (`predicate=lambda p: True`). The grammar
*already* refuses to lower a restricted untap onto that kind, in those words:
"no untap handler honors this restriction". So the program carries no evidence
of the restriction, and the only derivation the kind honestly supports is
"permanent" — which would offer lands for an ability that may only untap a
creature, and the handler would untap the land. Inventing the evidence in a
legacy rule to satisfy the picker would put the engine's two answers back out of
step, which is the defect this whole migration removes. So the derivation
refuses and one text pattern survives, in `_UNDERIVABLE_ABILITY_TARGETS`, with
a test asserting the grammar still refuses that line — the day the untap handler
honours its filter, that test fails and the pattern is deleted with it.

Rocket Launcher was the other refusal, and it was fixable rather than
structural: its rule's regex matched `damage to any target` and then threw the
match away, exactly the shape Fireball had on the cast side. Recording what the
regex proved made it derivable — `targets` is a description no handler reads, so
this cost no behaviour change.

**What replaced the differential.** A table pinning all 18 specs that carry a
flag plus a representative of each plain kind, a ratchet asserting every ability
whose line names a target derives its own prompt, and an exact two-directional
census of what still reaches the text fallback — a new card falling through
fails, and so does an acknowledgement whose card now derives. All fifteen of
those guards were verified by injecting the bug each exists to catch.

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

> **Revisited when `engine/parsing/` was deleted, and the argument holds —
> for `CHANNELS`, which is what it was ever about.** `_AURA_STATIC_PATTERNS`
> and its sibling channel tables are a hand-kept *inventory* of which engine
> code implements which sentence, and nothing derives them from the engine.
> They stayed.
>
> The `parse_primary_instruction` leg of `_rule_match` is a different thing
> wearing the same word. It was not an inventory but a second *parser*, and its
> independence was an artifact of two front ends existing rather than a property
> anything relied on — the grammar was already tried first, so the legacy leg
> only ever answered for text the grammar refused, which is text that now has no
> reader at all. Three things keep the guard from being an echo of the compiler,
> and none of them is that call: the **unit** (the compiler claims a line; this
> script splits it into sentences and makes each earn a claim, then searches for
> the shortest sentence prefix reproducing the parse so trailing sentences
> cannot ride along), the **deletion probe** (a property test over the parser,
> not a second opinion), and **`CHANNELS`** itself.
>
> The probe got *stronger* in the same pass, for a reason worth recording. It
> had been comparing `behavioural_payload(...)` — payloads with the `targets`
> description dropped — which existed so a grammar instruction could be compared
> against a legacy one. That subtraction was hiding real differences from the
> probe: "target **attacking** creature" and "target creature" differ only
> inside `targets`, so the probe reported "attacking" as a word the parser
> ignored. Comparing whole payloads took the accepted findings from **96 entries
> / 455 ignored words to 9 / 10**, with no entry anywhere gaining a word.

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

### The "phase 6" row was wrong, and none of it was blocked

*(Checked after phase 4; the table above is left as it stood.)*

The static row said 50 lines were waiting on the CR 613 layers engine. When
that claim was finally tested against the code, **not one of the 23 distinct
sentences behind it was blocked on layers at all** — and the row had been
growing for four phases while phase 6 landed the layers underneath it.

| What they really were | Distinct lines | Owner |
| --- | ---: | --- |
| Aura P/T, keyword, protection, restriction and animation grants | 12 | already derived at layers 6/7c by `engine/auras.py` (phase 6, slices 1–4) |
| Continuous anthems ("Black creatures get +1/+1") | 3 | already had a continuous consumer — `_recalculate_lord_buffs` |
| Conditional self-bonus ("as long as you control a Forest") | 3 | `engine/static_bonuses.py` |
| Lord buffs ("Other Goblins get +1/+1 and have mountainwalk") | 3 | `_recalculate_lord_buffs`, off a bare `static_line` |
| Anthems with a qualifier that consumer ignores | 2 | need their own instruction kinds |

The Aura lines are `RegistryLine`s now, claimed by the derivation functions
themselves rather than by a copy of their patterns — `aura_continuous_claim`
asks `aura_keyword_grants` / `aura_restrictions` / the P/T and protection
matchers, so a claim cannot outlive the code that carries it out. It stops
deliberately short of the Aura's *triggered and activated* abilities, which do
compile to instructions and which a claim would silently shadow.

The anthems now lower to `buff_creatures_global` — the same instruction the
legacy rule always emitted. That kind has two consumers, and the reason the
refusal looked right for so long is that only one of them is obvious: the spell
handler locks its set in at resolution (CR 611.2c), while on a *permanent*
`_recalculate_lord_buffs` re-derives it on every recompute. The second one is
the continuous reading, and it was there the whole time.

**The trap in doing it**, and why the lowering is narrow: that continuous
consumer reads the colour and the controller and *nothing else*. Lowering
Orcish Oriflamme's "Attacking creatures you control get +1/+0" onto the same
kind would buff every creature its controller has, permanently — and Castle
would buff tapped ones. The filter is compared for **equality** against the
shape the consumer implements rather than probed field by field, so a filter
field added later cannot slip past a check written before it existed.

**Coverage: 70.4 → 73.2% parsed, 63.9 → 69.9% lowered, 35.8 → 36.4% executed**,
and the backlog's phase-6 row is **gone** — no line is attributed to it. What
replaced it are reasons that name an owner: `static_bonuses.py`, a lord-buff
derivation table that does not exist yet, or the two anthem shapes that need
their own kinds.

Seven tests asserted the old refusal and each was re-pointed rather than
deleted, because most of them were guarding something still true. The
keyword-grant test's hazard is unchanged and is exactly why these must never be
*lowered* — every keyword-grant handler sets an until-end-of-turn flag the
cleanup step wipes, so lowering "Enchanted creature has flying" onto one would
grant flying for a single turn and then silently stop. Zero instructions is the
correct output, not a missing one. Paralyze's test is the sharpest case: its
premise — "claiming this would credit a card on the strength of code that never
looks at it" — was *true when written* and was made false by phase 6 moving the
restriction onto the Aura. It asserts the new reader by name now.

**The generalisable rule:** a backlog entry blaming a phase is a claim about
code, and it decays exactly like a stale comment — except that it decays into
work looking blocked that nobody is blocked on. Re-check them when the phase
they name lands, not when someone finally gets to them.

### The lord anthem gets its table, and two bugs come out with it

`engine/lord_buffs.py` is that missing derivation table. "Other Goblins get
+1/+1 and have mountainwalk", "Black creatures get +1/+1", "Attacking creatures
you control get +1/+0" and "Untapped creatures you control get +0/+2" are one
template with parameters — **who** (colour, creature subtype, "other",
controller scope, and a state qualifier) and **what** (a P/T delta, keyword
abilities, a granted activated ability) — and everything is derived from the
printed sentence. Nine cards now compile through it; the two backlog rows it
was blocking (20 lines, 5 distinct sentences) are gone.

Both halves of the two-lists defect were live here, in the same family:

- The support gate's entire test for a lord line was the prefix `"other "`, so
  "Other Goblins glimmer uncontrollably." compiled as supported and did
  nothing. The gate asks the table now.
- The qualified anthems could not be expressed at all, so each had its own
  instruction kind whose *parse rule spelled out one card's numbers*
  (`"attacking creatures you control get +1/+0"`,
  `"untapped creatures you control get +0/+2"`). A card printed +2/+0 was
  unsupported while the engine had every line of code it needed. Both rules are
  deleted; the qualifier is payload.

**Two real bugs, and both were in the qualifier the consumer ignored:**

1. **Castle buffed creatures that had stopped being untapped.** The bonus was
   contributed when the board was *recomputed*, and nothing recomputes when a
   creature taps — so a 2/2 attacking under Castle stayed a 2/4 for the whole
   declare-attackers step, which is where priority is held and blocks are
   decided. A state qualifier now goes into a derived channel that
   `layer_bridge` evaluates when P/T is *read*, which is what CR 611.3a's "at
   any given moment" actually says. `attacking_buff_*` — the one qualified
   channel that already worked, for exactly this reason — is generalised into
   it rather than sitting next to it.
2. **No anthem reached an animated land.** The consumer skipped a permanent on
   `card.primary_type != "creature"` — the printed type line, which layer 4 is
   precisely what overrides. Kormus Bell's Swamps are 1/1 *black* creatures and
   Bad Moon gives black creatures +1/+1, so CR 613.1 makes them 2/2; they were
   1/1. Types and subtypes are asked through `is_creature`/`has_type` now.
   `tests/rules/test_layers.py` had covered this interaction *in the abstract*
   since phase 6 — the layer engine was right and the code feeding it was not,
   which is the shape a bridge bug takes.

**CR 611.2c is the line that must not be crossed**, and it is now drawn by the
text rather than by which consumer happens to run. "Attacking creatures get
+2/+0 **until end of turn**" is Army of Allah: a one-shot effect that locks its
set in at resolution, and it keeps `buff_creatures_global` and its spell
handler, untouched. A static ability has no duration and is re-derived every
recompute. `lord_buff_for` refuses any clause carrying a duration, so the two
readings can no longer arrive at the same instruction by accident — where
before they shared a kind and were told apart only by whether the object was on
the battlefield.

The grammar lowers all of it now, and the safety property survives the move:
the filter is **rebuilt from what `LordBuffFilter` holds and compared for
equality** against the one the parser produced, so a restriction the table has
no field for refuses instead of being dropped, and a field added to
`ObjectFilter` later is refused by default rather than ignored by a check that
predates it. `_looks_static` also learned that a *conjunction* of durationless
effects is a static ability — judging one effect at a time is why "Other
Goblins get +1/+1 and have mountainwalk" was on a different lowering path from
the anthem that says the same kind of thing.

Two smaller things fell out. `behaviour_signature` sorted instruction triples
naturally, so two instructions sharing a kind and value fell through to
comparing their payload *dicts* and raised — Zombie Master is the first card in
the pool with two of one kind, and it crashed the whole signature rather than
merging anything. And Island Sanctuary asked for islandwalk by reading a
metadata flag *and* the printed keyword list, so it saw the routes to the
ability someone had told it about; it asks layer 6 now, which is what the lord's
grant has always been.

**Coverage: 69.9 → 71.1% lowered, 36.4 → 37.6% executed** (parsed unchanged at
73.2% — these lines already parsed). Every guard added was verified by
reintroducing the bug it exists to catch, including the `"other "` prefix, the
missing channel clear, the read-time qualifier, the printed-type-line read and
the vacuous filter comparison.

**The generalisable rule, again and from the other side:** the qualifier that
had no home in the table was also the qualifier the consumer got wrong. A
parameter a derivation cannot express does not stay unexpressed — it gets
approximated somewhere, and the approximation is invisible because no test
names it.

### The last three `TODO(card-hooks)` sites: none of them was one card

Three comments in the mixins said "single-card bespoke site; migrate if a second
card needs the shape". Tested by *behaviour* — give an invented card the same
printed text and see what happens — all three were already wrong, and each in a
different way. The count is 0 now.

- **Kormus Bell / Living Lands** were the combat-restriction bug exactly, with
  both failure modes live at once. The gate was two `in text` literals emitting
  instruction kinds that spelled the land type out (`animate_all_swamps` /
  `animate_all_forests`), so a card printed "All Mountains are …" compiled
  **unsupported**; the dispatch matched `perm.card.name == "Kormus Bell"`, so a
  differently-named card with Kormus Bell's *exact* text compiled **supported
  and animated nothing**. `engine/land_animation.py` derives the land type, the
  P/T and the colour into one `animate_all_lands` payload. The P/T and the
  colour were hardcoded 1/1 and black in the refresh, so those were two more
  parameters the template could not carry.
- **Fastbond** was the split at its widest. `_fastbond_count` counted permanents
  *named "Fastbond"* and was read from four places — cast validation, the
  land-drop damage, the AI's land policy, the web layer's playable list — while
  `scripts/parse_coverage.py` claimed the *sentence* "you may play any number of
  lands on each of your turns" for every card printing it. Claim pool-wide,
  behaviour one name: an invented card with Fastbond's exact text compiled
  supported, granted no extra land play and dealt no damage.
  `engine/land_play_allowance.py` derives CR 305.2's count, covering the
  "\[N] additional land(s)" forms the pool does not yet contain, and every gate
  asks the one table — including `_derived_static_claims`.
- **Basalt Monolith** was not a template at all; it was a *rule*. The branch
  hand-picked between the card's {T} mana ability and its {3} untap ability by
  tapped state, which is just CR 107.5 — an already-tapped permanent can't be
  tapped again to pay {T}, so a card with both abilities has exactly one payable
  ability in each state. The default selection asks that question now. An
  identically-worded card under any other name previously tapped for mana once
  and was then stuck tapped for good, its untap ability unreachable. A second
  Basalt Monolith branch further down was **dead code** — the {T} cost has
  already run `become_tapped` by then — confirmed by making it raise and running
  the suite.

Two things worth keeping from this. The first: "single card" is a claim about
the *pool*, not about the code, and it expires silently — Fastbond's comment was
true when written and the parse-coverage claim that contradicted it was added
later, by someone closing a different gap. The second: a name-keyed dispatch and
a CR rule implemented as a card special case look identical in a grep for card
names, and they have opposite fixes. Only running the invented card tells them
apart.

Every guard was verified by injecting the bug it catches and reverting: the
name-keyed animation dispatch, the hardcoded 1/1-black body, the animation gate
losing its right anchor, the name-keyed land-play count, the gate no longer
asking the allowance table, and both halves of the ability-selection default.

## Phase 4 — trigger event bus and a generic choice queue ✅ done

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
- The optional-action prompt still rode `pending_optional_pays`. It carried
  instruction branches rather than a fixed life/draw/damage vocabulary, so it
  was no longer a *limit* — but it was still one of the one-card fields.
  *(Folded into the choice queue below.)*
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

### Done — one queue, and the three cascades that hung off it

`Game.pending_choices` replaces the sixteen one-card `pending_*` fields. A
decision is a `PendingChoice` (kind, seat, payload) and a `ChoiceSpec`
registered in `engine/pending_choices.py`; `web/prompts.py` holds the renderers.
**19 kinds registered, 14 of which refuse other actions.** `web/app.py` lost
**603 lines** (5,506 → 4,948).

The fields were never the expensive part. Each prompt needed *five* things —
something to arm it, a resolver, a default for non-interactive seats, a
renderer, and an action that answers it — spread across five files with nothing
holding them together, and the failure modes are silent and asymmetric:

| Missing part | What happens |
| --- | --- |
| default | the AI seat never answers and **the game hangs forever** |
| gate | the player acts around their own prompt |
| renderer / action | the prompt is armed, never shown, never cleared |

All three shipped. `_auto_resolve_ai_pending` was twelve near-identical
functions and was **missing two** — Aladdin's Lamp and Ring of Ma'rûf had no
safety net, so a seat handed from a human to the AI would have stalled on them.
The blocking cascade was eighteen hand-written `if` statements. And **Primal
Clay's "choose your body" prompt had three of the five missing**: armed for a
human controller, then no renderer, no action, and no auto-answer — the
controller silently got the first printed body and the field was never cleared.
It is wired up now, with a board panel, and verified end to end in the running
app: the prompt renders, clicking *1/6 with defender* applies it, and the
`pass_priority` the prompt was refusing is accepted afterwards.

`tests/engine/test_pending_choices.py` makes that class mechanical rather than
a rule to remember. It reads the registry, so a kind registered with no
renderer, or given an action `web/app.py` never dispatches, or armed with no
spec at all, fails — each verified by injection, and each fired with exactly the
right name. A per-kind gating test also pins that a prompt never refuses the
action that answers it (a deadlock) and that a bystander seat is only held up by
the kinds that stop the whole game.

Four things the migration turned up, worth keeping:

- **A queue is not a field, and one distinction was hiding in that.** Balance
  owes *every* player their own removals; the single `pending_balance` field
  held one `{"plans": {...}}` table for all of them, and `pending_sacrifice`
  could only hold one seat's — a second seat's forced sacrifice resolved itself
  inline rather than waiting. Both are one choice per seat now, and the legacy
  view rebuilds the plan table from them.
- **Two seat fields, one authority.** Every prompt carried its seat inside its
  payload (`caster_index`, `chooser_index`, `controller_index`, …). The queued
  choice owns it now and the compatibility views derive their key from
  `choice.player_index`, so the two spellings cannot disagree.
- **Where the "is this seat interactive?" test belongs is per kind, not
  universal.** Most prompts gate at arm time — a non-interactive seat never
  queues one, because the resolution they interrupt has to finish. Kudzu does
  not: whether the controller is asked at all is the *caller's* `defer_choice`,
  since a tap that already names the land re-attaches inline. Making that a
  spec flag (`default_at_arm`) rather than a convention is what let the
  difference stay visible; treating it as universal broke Kudzu's regression
  test on the first run.
- **The AI simulator drains kinds by name, not queue order.** A library search
  shuffles, so *which* prompt is answered first is part of what a seed
  reproduces. `auto_resolve_pending_choices(kinds=…)` takes an ordered tuple for
  exactly that reason, and the seeded AI-behaviour tests are unchanged.

**Not done, deliberately:** the 23 existing trigger fire sites still stay put,
for the reasons above — they convert when they need new behavior. And a plain
"gain N life" consequence is still mirrored into the legacy `life` field so the
optional-pay prompt can describe what accepting does; that goes away when the
choice carries its own description, which is now a one-field change to a spec
rather than a change to a `Game` field.

3,992 tests, 14.3s.

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

**Done — CR 616.1's process, and the split that was blocking it.**
`engine/effect_ordering.py` implements the rule: gather every effect that
applies, choose one, apply it, then re-ask the rest against what is now true
(616.1f). `apply_prevention` runs through it.

The reason this was unimplementable before is worth stating, because it is a
shape that recurs: **an effect answered "do I apply?" by applying itself.** The
guard and the work were one function, so there was no way to ask how many
effects were in contention without running one of them — and running one is
precisely what 616.1 says you may not do until the player has chosen. Every
shield now carries an `applies` predicate, and the guard *moved* there rather
than being copied: the shield body starts after the decision, so the two cannot
drift into disagreeing. `test_616_1_applicability_is_asked_without_applying_anything`
pins the other half of that contract — the predicate must be pure, because a
predicate that consumed a charge would spend shields on effects the player was
only asked about.

616.1f is a real behaviour change and not just structure: applying one effect
can change which others apply, and the loop re-gathers instead of walking a list
decided up front. Forcefield capping 6 damage to 1 and then a 5-point pool
spending only 1 of itself is the case, and it is now arrived at by re-asking
rather than by the amount happening to be mutated in place.

**Done — replacements got the same split, and a damage event is now one
contention set.** `engine/replacements.py` was the other half: every interceptor
carries an `applies` predicate and an explicit order, and `apply_replacements`
runs through `effect_ordering` instead of walking its list. Registration order
no longer decides anything, which was the quiet hazard in the old registry — an
import moving would have changed which effect replaced an event first, silently.

The predicates were, as expected, entangled with the values they compute, and
each one was resolved by extracting the value rather than duplicating the test:
`_floored_amount` answers both "does Ali from Cairo apply?" and "what does it
floor to", `_jade_monolith_seat` answers both "does the redirect apply?" and
"to whom". Aladdin's Lamp is the interesting exception — its charge is spent
even when the library is too short to look at anything (CR 614.1), so its
predicate is "armed", not "will do something", and the short-library case stays
*inside* the effect. A predicate that declined there would leave the charge
unspent, which is a rules difference, not a refactor.

`engine/damage_events.py` is then the union: a damage event's shields and its
replacements are gathered into one candidate list, one is applied, and the rest
are re-asked — across both registries, which is what CR 616.1 actually says. Two
things that were structurally impossible before are now just true: the contender
count is right (counting from one registry could only undercount, and that count
is what the future prompt's choice is over), and 616.1f's re-check spans the
seam instead of stopping at the end of each pass.

The two registries share one order space for damage, so the defaults reproduce
the old two-pass result exactly — damage to a permanent is redirected before it
is shielded (a shield spent on damage that then leaves is wasted); damage to a
player is shielded before it is floored (the floor has to read the life total the
shields left). Both were already reasoned choices; they are now *the same kind of
thing* as every other order in the two tables, which is why a collision between
the registries had to become an import-time failure — neither table can see the
other's orders, so `_assert_one_order_space` is the check only the union can
make. The change is deliberately behaviour-preserving: 4,012 tests, 19.5s, no
existing assertion moved.

**Done — combat damage joins the rest, and the blocker was not what the last two
entries said it was.** Both of those entries claimed the combat damage step
needed a *resumable* damage event to stop applying its shields in one place and
its replacements in another. That was wrong, and the reason is worth writing
down because it is a diagnosis error, not a missing feature: the step was not
short a moment, it was short a **number**.

CR 120.4 sequences a damage event in parts. First the damage is **dealt**, as
modified by the effects that interact with damage (120.4b: shields, redirects).
Then what was dealt is **processed into its results**, as modified by the effects
that interact with those results (120.4c: life lost, damage marked). Ali from
Cairo — "damage that would reduce your life total to less than 1 reduces it to 1
instead" — is a 120.4c effect, so the damage is dealt *in full*: lifelink gains
the full amount (CR 120.3f), a "deals damage to a player" trigger sees the full
amount, and only the life loss is capped.

The engine had one number for both. That is precisely why the combat step had to
apply shields where the event was recorded (so lifelink read a number the floor
had not touched) and replacements where life was applied (so the floor read the
running life total). Two moments compensating for one missing number.

`deal_damage` now returns a `DamageOutcome` carrying `dealt` and `result`, the
registry has four damage kinds instead of two (`damage_to_player` /
`damage_to_creature`, then `life_loss` / `damage_marked`), and the combat step
records raw events and runs the whole sequence at one site with lifelink tallied
from `dealt`. `_prevent_damage` and `apply_prevention` are **gone** — with
nothing left holding half an event, a shields-only entry point is just the defect
this pipeline exists to remove, and `shield_candidates` hands the half over
instead of running it.

Three things fell out of rewriting that code, each verified against the rules
rather than assumed:

- **Veteran Bodyguard was absorbing trample damage.** It covers "damage dealt to
  you by unblocked creatures", and CR 509.1h is explicit that an attacker with a
  blocker declared for it *is* a blocked creature — and stays one even if every
  blocker leaves combat. As an inline check in the combat step it could only see
  "this damage arrived on the player's pile", which cannot tell a trampler's
  excess from an unblocked attacker. It is a registry interceptor now, reading
  the source permanent's own combat state, which also gets a case the inline
  version never could: the card says *all* damage, so an unblocked attacker's
  activated ability is redirected too.
- **Its redirect was ordered behind the shields**, so a prevention pool was spent
  on damage that then left for the creature anyway. Redirects now default ahead
  of shields for both recipients, one rule instead of two conventions.
- **Every combat event was attributed to whichever attacker was processed last.**
  The apply loop passed the leaked `attacker` from the earlier loop to
  `_on_player_dealt_damage` while using `source_attacker` two lines below.
  Invisible until a source's identity mattered — Reverse Polarity counts only
  what artifact sources dealt (CR 120.7), so a Clockwork attacking beside a
  Grizzly Bears tallied 0.

4,018 tests, 12.8s. The three fixes are mutation-checked: each new test fails
when the specific line it pins is reverted.

**Done — the choice is asked, and it cost far less than the last entry
predicted.** That entry said asking needed continuation-passing through the
whole effect layer. It was measuring the wrong thing: what a prompt needs is not
the ability to *resume* an event, it is the ability to *re-run* one — and the
`applies` split had already bought that without anyone noticing.

Every applicability predicate is pure. So at the moment `apply_in_order` reaches
a contended round, **nothing has been applied yet**. The process can be
abandoned there and the whole event re-run later: it reaches the same round
against the same state, finds the same contenders, and now has the recorded
answer. No continuation, no snapshot, no rollback, because there is nothing yet
to undo. (A snapshot would have been actively wrong here — the engine compares
damage sources and band members by identity, which a deep copy breaks.)

616.1e is an `effect_order` pending choice, registered like every other prompt,
so `tests/engine/test_pending_choices.py` covered the renderer, the action and
the gate by construction. The re-run is a `restart` thunk the caller passes to
`apply_replacements`; passing it *is* the caller declaring "this event can
suspend", and a suspended event reports `consumed` so the caller skips the
default action and the re-run does it properly. A non-interactive seat is never
asked, so AI and headless play stay synchronous.

The reachable contention is Ring of Ma'rûf and Aladdin's Lamp both armed over
one draw, and the choice is real: picking the Lamp leaves the Ring armed, which
is the opposite of the default order.

**Done — a damage event's consequences travel with it.** The blocker named
above was that a damage event's callers read the number back for lifelink,
"gain life equal to the damage dealt" and their own log lines, so deferring the
event means deferring all of that. That half is closed: every damage caller now
passes what it would do with the number as a `then` callback, so it runs inside
the event and re-runs with it. Thirty-odd call sites, behaviour-neutral, and
held in place by `tests/engine/test_damage_continuations.py`, a source guard —
because on a suite where nothing suspends, a caller that reads the return value
instead is invisible.

That also fixed a class of log bug on its own terms: the log line for a damage
event is now written from inside it, so it can no longer disagree with what
happened, in the same way the Veteran Bodyguard redirect used to log "took 8
combat damage" against a player whose life never moved.

`deal_damage` takes a `restart` and asks with it, proven by
`test_616_1e_a_damage_event_given_a_restart_asks_and_re_runs`: a Circle of
Protection and a prevention pool contend over one red source, the affected
player is asked, and picking the pool — the opposite of the default — spends the
pool and leaves the Circle.

**Done — the loops are the re-runnable unit, and spell damage asks.**
`engine/resumption.py` is a resume stack: a loop records the rest of itself
before each step and drops that record once the step gets through, so what is
left when something suspends is exactly the work still owed, innermost last.
Answering re-runs the suspended event and then unwinds, which is why a
suspension two loops deep resumes the divided damage first and the sequence
after — the innermost loop is the one whose next step comes soonest.

Three places convert: `control_flow._run` (every spell's instructions), the
divided-damage branch of `handlers/damage.deal_damage`, and the *tail* of spell
resolution. That last one was not on the original list and is the one that
would have been missed: CR 608.2m puts the card into the graveyard as the final
part of resolution, so finishing regardless would bin a spell whose damage was
still waiting on an answer. Word of Command already needed the same care for
its own reason, which is why the tail was separable at all.

A Lightning Bolt into a player holding a Circle of Protection and a prevention
pool now asks, leaves the spell on the stack while it waits, and finishes
properly when answered — including a Fireball divided over two players, where
the second target used to be the thing that would have been silently dropped.
Both are mutation-checked against the loop conversion they depend on.

The rule a loop has to follow — **it must be the last thing its function does**
— is written where the mechanism is, because work after the loop does not run
when a step suspends and nothing records it.

**Done — combat damage asks, and the restructure it needed was a seam, not a
rewrite.** This was the one damage path that passed neither `asks` nor a
`restart`, and the entry above called it a real restructure rather than a
two-line conversion. It was, but the shape it wanted turned out to be one the
function already had and did not name: **the step is in two halves, and only one
of them can be interrupted.** Assignment (CR 510.1) works out where every point
goes and can be *refused* — a negative amount, a trampler holding back lethal —
so it deals nothing while it can still say no. Dealing (CR 510.2) runs those
recorded events and can be *suspended*. Naming that seam is what made the
conversion mechanical: everything before it stays ordinary code that returns
`(False, reason)`, everything after it is a step of a resumable loop and can
return nothing at all.

`resolve_combat_damage` was 380 lines with five loops and a tail. It is now
guards, three extracted helpers (`_first_strike_pass_pending`,
`_validate_blocker_damage_split`, `_assign_attacker_combat_damage`) and one
`run_resumable` over four steps: blockers deal, attackers deal to blockers,
attackers deal to players, `finish`. The blocker step is itself two nested
resumable loops (by defender, by blocker) and a third inside the band-member
split, so a suspension four loops deep unwinds innermost-first back out through
them. `finish` — the lifelink gain, the state-based actions, the log lines and
the `combat_first_strike_done` / `combat_damage_resolved` flags — is a *step*,
not code after the loop, which is the whole rule restated: work written after a
resumable loop does not run when one of its steps suspends, and here that would
have been a combat that half-happened and then declared itself resolved.

The player-damage loop is the one place that writes its own `restart` rather
than passing `asks=True`, and the reason is CR 120.4's two numbers: the step
applies `outcome.result` to the life total and tallies lifelink from
`outcome.dealt`, so "re-run this call" is not enough — the re-run has to be the
whole `hit()`, consequences included. `asks=True`'s generated thunk closes over
one call; this one closes over both numbers' uses.

**The strike passes were the sharp edge, and the caller was where it cut.**
Every caller wrote "resolve, and resolve again if that was only the first-strike
pass", keyed on `combat_damage_resolved`. That is safe exactly while a pass
cannot be interrupted: a first-strike pass that suspends leaves the flag False,
so the second call would have re-run the *first* strike — the damage twice, the
question twice. The idiom is now `resolve_all_combat_damage`, a two-step
resumable loop, and the second pass is recorded *behind* the first instead of
racing it. `_advance_combat_step` got the same treatment one level up: leaving
the damage step (priority window, step end, entering end of combat) is the last
step of a loop whose first step is the damage, because otherwise answering a
prompt would have found the game already in end of combat.

**The bug it turned up: Merchant Ship gained 4 life.** "Whenever this creature
attacks and isn't blocked" is fired from `resolve_combat_damage`, guarded by a
comment claiming the method "runs once per combat (`combat_damage_resolved`)".
It does not — the first-strike pass deliberately leaves that flag False, which
is the entire point of it — so any first striker anywhere in the combat handed
the Ship's trigger to the stack twice. Invisible for the same reason the
attacker-attribution bug was: nothing in the pool had both an
"attacks and isn't blocked" trigger and a reason to share a combat with first
strike, so no test paired them. The guard is `combat_first_strike_done` now,
which is the flag that actually marks the re-entry.

Also found and corrected while citing it: **CR 510.5 does not exist.** The
first-strike step is CR 510.4. The step module had been citing 510.5 since it
was written.

Nothing was refused, but two things were deliberately left alone. The manual
assignment endpoint still calls `resolve_combat_damage` once rather than
`resolve_all_combat_damage`, because one action is one pass there and the UI
drives the second; a suspension in it is caught by the prompt gate, which
refuses every action until answered. And 616.1 is still asked *per event* rather
than once for the whole simultaneous step (CR 510.2) — two attackers into the
same shielded player ask twice. That is right for the engine as built, which
deals combat damage sequentially by documented design, but it is the place where
"simultaneous" and "one contention set" would eventually have to be reconciled.

Seven mutation checks, one per pinned line: drop the `restart`, flatten any of
the three converted loops, restore the double-call idiom, move `finish` back
after the loop, remove the trigger guard — each fails the test that pins it.
4,082 tests, 12.0s. The AI simulation log is byte-identical to its
pre-change baseline, which is the check that matters for the un-asked path:
nothing about combat changed for a seat nobody is sitting in.

**616.1a–d are deliberately not built.** They order *classes* of effect ahead of
the free choice: self-replacement effects first (614.15), then control-on-entry,
then copy-on-entry, then back-face-up. Not one of them has a member in this
pool's registries — entry replacements live in `enter_effects.py` and never
reach this process — so building the class machinery would be four empty
branches, which is the same call the roadmap already made about cost reduction.
`OrderingTrace.unasked` records the one situation that would need them sooner
(616.2 making a fresh effect applicable mid-event), so it surfaces rather than
passing silently.

**616.1g needs no code.** "The second effect can't be chosen until after the
first" falls out of a contained event happening *inside* the outer effect's
`apply` — Jade Monolith's redirect creates its damage event there, so the
destination's shields are only ever gathered once the redirect has been chosen.
Pinned by a test rather than left as a claim.

4,028 tests.

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

Lifetap stayed **name-keyed** at the time, honestly: the compiler parsed *zero*
triggered abilities for it, so there was no condition kind to emit. Mana Flare's
trigger did parse (`land_tapped_for_mana`) but lowered to nothing. Moving these
onto `engine/events.py` needed the parser to produce the conditions first —
that was the real remaining task, not the fire site. **Both are done; see "the
two land-tapping trigger templates" below.** The 605.1b divergence recorded here
is fixed there too.

Cast-trigger hooks (six cards name-keyed for conditions the parser already
understands) move onto the same bus.

Phase 4's `Game.pending_choices` was recorded here as still its own job, on the
grounds that what landed above covers only choices a *replacement effect*
raises, and that twenty `pending_*` fields remained for the choices raised by
resolving spells and turn-based actions. **Both halves are now out of date.**
The general queue landed as `engine/pending_choices.py` — one `PendingChoice`
list and one registered `ChoiceSpec` per kind, which is exactly the "answer
routed back into a partly-executed effect" this entry was waiting for, built on
`engine/resumption.py`.

Four `pending_*` fields survive on `Game`, and two of them *are* the generic
queues (`pending_choices`, `pending_replacement_choices`) — the destination, not
the backlog. The other two are not choices at all: `pending_end_step_tokens` and
`pending_draw_step_life_loss` are delayed *effects* scheduled for a later step
(Rukh Egg's token, Nafs Asp's life loss), where the thing deferred is the
effect's execution rather than a seat's decision. Generalizing those is the
delayed-trigger job, not this one.

**Done — a shield's state is generic too, and the old field names are views.**
The entry above deferred this: the `PlayerState` fields the shields read
(`forcefield_capped_sources`, `reverse_damage_charges`,
`color_prevention_shields`, …) were the *state* an interceptor reads, and
replacing them reaches the web payload and the AI simulator. It is done, by the
same route the interactive replacements took — a narrow generic mechanism with
the old names surviving as thin views — and neither of those layers changed.

`engine/shields.py` holds a `Shield`: what it answers to (`source`, `color`),
how much it absorbs (`amount` points, `leave` points let through), how many
`uses` remain, and its `lifetime`. One collection per recipient, on `Permanent`
as well as `PlayerState`, because CR 615.1's shield goes around "whatever
they're affecting". `kind` names the interceptor that consumes the shield, which
is the only link back to behaviour — and it is named for what the shield does,
never for the card that granted it.

**Six fields gone, six names kept.** `damage_prevention_pool`,
`damage_prevention_source`, `color_prevention_shields`,
`combat_damage_cap_one_charges`, `forcefield_capped_sources`,
`reverse_damage_charges` and `reverse_damage_sources` are properties now, read
*and* written — a test still says `p1.damage_prevention_pool = 3` and a
regression test still says `p2.reverse_damage_sources.append(barbs)`, which is
why the list views write through rather than returning a derived copy that
would swallow the append. Derived on every access, so a view and its shields
cannot disagree; the badge that outlived its pool is now impossible rather than
cleared by a line per card.

`damage_prevention_color` is the one that could not be a settable view, and the
reason is worth stating rather than working around: the colour is not
decoration, it is what the shield matches its source against (CR 615.9).
Assigning it would either invent a shield or silently widen an existing one to
match every source. It is read-only, and the cleanup line that used to null it
is gone with the rest of the sweep.

Three things fell out that the fields had been holding apart:

- **The turn-step sweeps are lifetime-driven.** Cleanup was eight assignments
  per player plus two per permanent; end of combat was two more, and they were
  the only place that knew Forcefield's shield expires a step earlier than
  everything else. Both are now `clear_shields(recipient[, lifetime])`, and a
  new shield joins them by recording its duration.
- **Two numeric shields are two shields.** "Prevent the next N damage" was a
  single running integer, so a second Healing Salve added to the first and its
  granting card overwrote the badge. They are separate shields now, each with
  its own source name, and the pool interceptor drains across them — which is
  CR 615.7's "such effects count only the amount of damage; the number of events
  or sources dealing it doesn't matter", and reproduces the old total exactly.
- **A colourless Circle of Protection shield is no longer armed at all.** The
  legacy parse rule can produce one from a card whose text names no colour word;
  it used to become a `None` in the colour list that could never match anything.
  Not arming it is the same behaviour said out loud, and it keeps the matcher
  free of a kind-specific branch.

**Deliberately unchanged: the registration set and every order.** The chosen-
source and any-source halves of Forcefield and Reverse Damage are still four
registrations at four orders rather than two, and the numeric pool is still one
contender rather than one per shield. Merging either would be tidier code and a
*rules-visible* change: CR 616.1's contention set is what the `effect_order`
prompt is over, so collapsing two candidates into one removes a question the
affected player is currently asked. That is a decision about the rules, not
about the state, and it does not belong in this commit.

**The Aladdin's Lamp shape is here, and it is Forcefield.** The Lamp's charge is
spent even when the library is too short to look at anything (CR 614.1), so its
predicate is "armed", not "will do something". A generic shield predicate wants
to be "there is a matching shield", and that would have quietly given Forcefield
the same shape: a chosen attacker dealing exactly 1 would spend the shield on
preventing nothing. The predicate is `would_prevent(amount) > 0` instead, which
is exactly what the old `amount > 1` guard meant.

Which reading is right is a live question and the rules do not settle it
directly. CR 615.12a — "a prevention effect is applied to any particular
unpreventable damage event just once" — says a one-shot shield *is* used up by
an event it prevents nothing of, and by analogy a cap facing 1 damage should be
too. That is an analogy, not the rule, and `MagicCompRules.txt` has nothing
closer. So it is measured rather than guessed: making the cap spend itself on a
0-point application is a two-line change, and the suite (4,210) and the AI
simulation (10/10 games, 443 interactions) are both green with it — *nothing
pins either reading*. It is left as it was, because a rules change with no test
either way should arrive as its own commit with the test that decides it, not
inside a refactor advertised as behaviour-preserving.

Two shields stayed out of the collection, and for one reason each. Fog's
"prevent all combat damage this turn" is a game flag — nothing is consumed, so
there is no charge, no lifetime and no remaining use for a `Shield` to carry.
Ebony Horse's is a per-creature marker that has to be readable off the damage's
*source* as well as its recipient ("dealt to and dealt by"), which a
recipient-keyed collection cannot express.

`tests/rules/test_prevention.py` proves the mechanism is open the way
`test_replacement_choices.py` does: it registers a shield no card in the pool
has — absorbs 2 points, twice — at runtime, arms it by putting a `Shield` on a
player, and drives it through `deal_damage`. The test body names no field,
because there is no longer a field to name. Five guards, each verified by
injecting the bug it catches: `shields_on` not persisting the collection, the
end-of-combat sweep ignoring `lifetime`, `_spend` stopping at the first pool,
`drop_spent` keeping a used-up shield, and the pool view storing instead of
deriving. The purity guard is the sharper one — it snapshots the shields
themselves rather than a total, and catches a predicate that mutates a shield's
`lifetime`, which the existing total-based purity test cannot see.

4,205 → 4,210 tests, 12.5s. The web payload, `web/static/`, the AI simulator and
every existing test are untouched; the AI simulation is unchanged at 10/10 games
and 443 interactions.

**Done — the two land-tapping trigger templates parse, and the last mana hooks
go.** The entry above named the blocker precisely and it was a *parser* one, so
that is where the work went. Two templates now compile, both parameterised
rather than spelled out per card:

- **"Whenever a `<type>` [an opponent controls] becomes tapped, …"** →
  a `permanent_becomes_tapped` condition carrying the type and the controller
  scope as payload. `Game.become_tapped` announces it on the bus and one
  `@event_filter` reads the restriction off the trigger's own condition, so no
  card name is involved. (Lifetap.)
- **"Whenever a `[<land type>]` is tapped for mana, `<player>` adds …"** →
  `land_tapped_for_mana`, now narrowable by land type, plus an
  `add_mana_for_tapped_land` instruction. `tap_land_for_mana` runs it inline.
  (Mana Flare, Gauntlet of Might.)

In the grammar both are one production, `_parse_quantified_tap_event`: the
subject is a *noun phrase* rather than one of the named subjects the literal
phrase table already covers ("enchanted land", "this land", "a player taps a
land"). It is tried strictly after that table, because `parse_target_spec` would
otherwise happily claim "enchanted land" and name a condition the legacy table
does not — the disagreement
`test_every_executed_trigger_agrees_with_the_legacy_condition_table` exists to
catch.

Three `card_hooks.py` entries and both registries they lived in
(`MANA_PRODUCTION_MODIFIERS`, `ON_BECOMES_TAPPED`) are gone; the file lost 54
lines. Coverage: **73.2% → 73.8% parsed, 37.6% → 38.3% executed**, and it is
real coverage — each new condition is dispatched, proven by tapping a board and
reading it, not by a payload golden.

**CR 605.1b, verified against `MagicCompRules.txt` rather than the summary
above.** 605.1b requires all three of: no target, *triggers from the activation
or resolution of an activated mana ability or from mana being added*, and could
add mana. Mana Flare and Gauntlet of Might meet all three, so 605.4a applies and
they may not use the stack — inline is what the rules require, not a shortcut,
and the fire site now says so. Lifetap fails 605.1b **twice**: it triggers on
*becoming tapped*, which is not a mana ability, and it could never add mana.
605.5a names that case explicitly ("a triggered ability that could produce mana
but triggers from an event other than activating a mana ability, or … triggers
from activating a mana ability but couldn't produce mana. These follow the
normal rules"). It now goes on the stack. That is the visible behaviour change
here: the life arrives when the trigger resolves, so two existing tests grew a
`resolve_stack()`.

Worth recording, from injecting the bug the pool-wide guard is supposed to
catch: renaming `add_mana_for_tapped_land` alone did **not** produce false
coverage, because an instruction kind absent from `INSTRUCTION_CATEGORIES` makes
the whole line ungated and the card falls back. The Mana Vault / Black Vise
shape needs *both* halves — a new kind and its category — which is exactly the
diff an author writing a new effect produces. The guard
(`test_every_land_tapped_for_mana_trigger_lands_on_a_kind_the_fire_site_runs`)
was re-verified against that two-part injection.

**A tightening in `parse_coverage.py` fell out of it.** Its trigger branch read
the effect clause *alone*, while the compiler hands the grammar the whole line.
Most clauses read the same either way, so the difference only showed up when a
clause is meaningless outside its trigger — "that player adds one mana of any
type that land produced" names a player and a land the *event* binds, so
lowering refuses it standalone and the script called it unclaimed. `_rule_match`
now falls back to re-reading the clause with its condition prefixed, and the
deletion probe re-parses through the same path, so every word of the clause
still has to matter. Lifetap's probe finding (six ignored words — its entire
trigger condition) disappeared, since the condition is now parsed instead of
being dropped by a rule that only saw "you gain 1 life".

**Not done, deliberately.** Wild Growth ("Whenever *enchanted land* is tapped
for mana, its controller adds an additional {G}") is the same effect clause but
a third subject, and the legacy table has no condition for it — its mana is
still added by an inline regex in `tap_land_for_mana`. Claiming it would need a
new condition kind *and* a fire-site branch that knows the Aura's attachment,
which is a different piece of work from the one this entry names; adding the
grammar phrase without them is the false coverage this task existed to avoid.

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

Seeding needed care *while copies were stamped*: `absolute_power`/
`absolute_toughness` apply in 7b, so the seed had to use the permanent's *own*
printed stats or the copy was counted twice; and colours had to seed from the
permanent's own card, because Vesuvan Doppelganger recorded no copied colours so
its printed blue would show through. Both were caught by existing tests rather
than by inspection — and **both are gone now that layer 1 is real**: every field
of the seed reads the same `effective_card`, and the exception lives in the copy
effect instead of in the seam. See "Layer 1: a copy is a value, not five
stamps" below.

| Layer | Status |
| --- | --- |
| 1 copy | **live** — `engine/copies.py` records the copiable values, `Permanent.effective_card` folds them |
| 2 control | **live** — `engine/control.py` records the contributions, `Game.controller_index_of` computes through them |
| 3 text | **live** — `engine/text_changes.py`, applied by `Permanent.effective_card` |
| 4 type | **live** — `engine/land_types.py` records the CR 305.7 replacements |
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

**Layer 2 was structurally different from the others, and that was the
finding.** Layers 4–7 were flags a reader consulted, so wiring them meant
changing the reader. Control was not stored at all — a control change *moved
the permanent between `player.battlefield` lists*, so "who controls this" was
answered by which list it was in. Making the controller a derived
characteristic meant every site that read zone membership had to stop doing so
first, and there were **172** of them — 165 in `engine/`, 7 in `web/`.

**Done, in that order.** See "Layer 2: the readers first, then the storage"
below for what the migration cost and what it found.

Layer 1 was the last one open — modelling copies as real copiable values
instead of stamped `absolute_power`/`copied_colors` overrides. It is done; see
"Layer 1: a copy is a value, not five stamps" below, including the measurement
that says `effective_card` **stays**, which is not what this paragraph used to
predict.

### Layer 1: a copy is a value, not five stamps

CR 613.2c is the whole design: after layer 1 has been applied, the object's
characteristics **are** its copiable values. So layer 1 is not an effect applied
over a seed — it is what produces the seed, which is why `engine/copies.py`
answers with a `CardDefinition` and not with a `ContinuousEffect`, and why
`apply_layers` now *refuses* a layer-1 effect rather than silently dropping it
(it starts at layer 2).

The stamped model kept a copy's answer in five places — `copied_card`,
`copied_colors`, `copied_keywords`, `may_recopy_each_upkeep`, and
`absolute_power`/`absolute_toughness` — and **CR 707.2's boundary was violated
by four of them.** That rule reads: the copiable values are the printed values
"as modified by other copy effects … Other effects (including type-changing and
text-changing effects), status, counters, and stickers are not copied." A stamp
records an *answer*; the rule asks where the answer came from, which a stamp
cannot say.

Four live bugs, all of that one shape:

- **`absolute_power` is layer 7b's channel.** A copy read its P/T out of it, so
  whatever a *non-copy* effect had set on the source came with it. A creature
  set to base 0/5 was copied as a 0/5.
- **`copied_card` was the source permanent's own `card`**, which is not its
  copiable values when the source is itself a copy (CR 707.3). A Clone of a
  Clone of a Craw Wurm came out a blue 0/0 Shapeshifter *named Clone* — its P/T
  right by luck, because that came from the stamp, and its name, types, colours
  and abilities all wrong.
- **Copy Artifact read the source's `effective_card`**, which already has layer 3
  folded into it — so a Sleight of Mind on the artifact was copied, which
  CR 707.2's last sentence forbids.
- **`copied_colors` was only written when there were colours to write.** So "this
  effect declines colour" (CR 707.9c) and "the copied object was colourless"
  were the same absent record, and **Copy Artifact copying a Sol Ring produced a
  blue Sol Ring.** This is the exact failure the "expressed by omitting a stamp"
  model guarantees.

`engine/copies.py` records one contribution instead: the copied object's
copiable values (`copiable_card(source)`, so CR 707.2's "as modified by other
copy effects" is one call), the set of characteristics this effect *takes*, the
CR 707.9 modifications it declares, a source and a CR 613.7 timestamp.
`become_copy` / `end_copy` / `copiable_card`, the same shape as
`engine/control.py` and `engine/land_types.py`; re-recording from the same
source replaces rather than appends, which is what Vesuvan's upkeep re-copy
(CR 707.4) needs and what stops a once-per-upkeep ability growing the fold by an
entry every turn.

**Vesuvan Doppelganger's exception is named positively.** `copies=EXCEPT_COLOR`
says the effect takes name, mana cost, types, text and P/T; CR 707.9c's "the
affected objects instead retain their original values" is then a *rule of the
fold*. The blue survives for a reason a test can read (`copy_effects(dop)[-1]
["copies"]`), and — the point — it is now distinguishable from copying something
colourless. Which exception applies is read off the copier's own printed text
(`copy_exceptions`), text-keyed like `cast_restrictions.py`, so all three
templates in the pool ("doesn't copy that creature's color", "it's an
enchantment in addition to its other types", "and it has …") work for a card
this engine has never seen.

**`effective_card` stays, and the measurement is why.** This roadmap predicted
layer 1 would let it disappear. It does not, and it was never going to: layer 1
is only *half* of what `effective_card` is. Of its **56** call sites in
`engine/` and `web/`, **38** want the compiled program — the copy's activated
and triggered abilities and static lines — and **8** want the rules text for a
text-keyed table; 4 more want the type line as text and 6 another printed field.
Not one of them is a characteristic the layer system can answer. Retiring it
needs two things layer 1 does not provide:

1. **Layer 3 rewrites text, and `Characteristics` has no text field.** A text
   change has to be folded into something card-shaped for the text-keyed tables
   to read.
2. **Layer 6 here carries keyword *strings*, not abilities.** `Characteristics.
   abilities` is a `set[str]` of keywords; a copy's `{T}: deal 1 damage` is not
   in it. **332 of the pool's 388 cards** carry at least one ability that is not
   a keyword string, so "get the copy's abilities from layer 6" would mean layer
   6 holding compiled `OracleProgram` fragments — a much larger change than
   layer 1, and the actual blocker.

What layer 1 *did* change is what `effective_card` computes: it is now exactly
"layer 1, then layer 3", stated in that order in its docstring, instead of
"whatever `copied_card` was stamped with, then layer 3". The fast path is
intact and measured — no copy and no text change returns `self.card` itself,
unallocated, at **0.52µs** (0.52µs before). A copy costs 1.19µs and returns a
*cached* card object, so `compile_card_oracle` still compiles it once.

Also gone with the stamps: `Permanent._base_stat` (its only readers were the
copy stamps), the `copied_colors` branch of layer 5, the `copied_keywords`
branch of layer 6 — a copy's keywords are printed abilities of the copied card
and belong in the seed, where a layer-6 *removal* can take them away rather than
being outranked by a grant stamped at timestamp 0 — and `copied_from`, which is
derived from the contribution now (`Permanent.copied_from`) rather than stamped
beside it.

One reader had to move for a reason worth recording: CR 704.5f's zero-toughness
sweep asked whether a creature's printed toughness was variable by reading
`perm.card.raw` — the *copier's* card. Under the stamped model a copy's P/T was
written at copy time, so a Clone of a Nightmare was never seen mid-flight; under
layer 1 the characteristic-defining ability supplies it on the next recompute,
and reading the copier's printed "0" would have swept the copy in between. It
reads `effective_card` now — the same printed-vs-effective correction the
animated-Mox sweep needed.

**The guard** is `tests/engine/test_copy_reads.py`, the layer-2 and layer-4
sibling: the storage key is touched only by the write API, `copiable_card` is
folded in exactly one place, `become_copy` is called from exactly one, the five
retired stamp keys are ratcheted out, and `engine/copies.py` may not name a
layer-7 channel — because a copy that writes `absolute_power` is a copy that
cannot tell a printed 2/2 from a 2/2 something else set, which is the first bug
above. Every part was verified by injecting the bug it catches (twelve
injections, twelve failures), including the two seeding subtleties: reverting
the colour seed to `perm.card` fails four tests, and making Vesuvan copy colour
after all fails two.

### Layer 2: the readers first, then the storage

**Step 1 — the readers.** `Game.all_permanents` /
`permanents_with_controller` / `permanents_matching` existed as a seam but only
25 call sites used it, because it could not answer the question most sites were
actually asking: *what does one seat control*. Four methods were added, and
they are now the whole of what may read zone membership:

| Seam method | The question |
| --- | --- |
| `all_permanents()` | every permanent on the battlefield |
| `permanents_with_controller()` | ditto, paired with the controlling seat |
| `controlled_by(seat)` | what one seat controls |
| `permanents_matching(pred)` | the filtered form |
| `controller_index_of(perm)` | who controls this — **CR 613 layer 2** |
| `controls(seat, perm)` | does this seat control it |
| `is_on_battlefield(perm)` | is it there at all |

172 open-coded iteration/membership sites (165 `engine/`, 7 `web/`) went down
to **8**: six in one AI-simulator snapshot comparison over detached
`PlayerState` clones, one positional target-resolver, and one inside the seam
itself. 23 more survive structurally as zone *writes* — the
`X.battlefield = [p for p in X.battlefield if p is not gone]` rebuild and the
`survivors` loop — which the guard exempts by *shape* rather than by name, so
the exemption cannot go stale.

**Two live bugs came out of the migration, and they are the same bug.**
`permanent in player.battlefield` compares `Permanent` **by value** — it is a
mutable dataclass with a generated `__eq__` — so it answers yes for an
opponent's identically-stated copy of the same card:

- CR 704.5m read that way, so an Aura whose enchanted creature had died stayed
  on the battlefield as long as *some* player had an identical creature in an
  identical state.
- The world rule (704.5k) and role rule (704.5y) then called `.remove()` on the
  same value match, which removes the look-alike rather than the permanent the
  sweep chose.

`controls` / `is_on_battlefield` compare by identity. This is the same class as
the Camel band-shield `list.index` bug from batch 22, which is the argument for
one accessor over eleven hand-written scans.

**Step 2 — the storage.** With the readers behind the seam, control became a
recorded contribution:

- **`engine/control.py`** — `change_control(permanent, seat, source=…)` records
  one with a CR 613.7 timestamp; `end_control_change(permanent, source=…)`
  drops that one and nothing else; `base_controller_index` holds the value
  layer 2 starts from (CR 613.1's copiable characteristic), written once when
  the permanent enters and never again.
- **`engine/layer_bridge.py`** — `collect_control_effects` turns each into a
  layer-2 `ContinuousEffect`; `computed_controller` applies them. A permanent
  with no control effect skips the layer engine entirely, which is what keeps
  `controller_index_of` at 0.79µs.
- **`Game.take_control` / `end_control_changes_from` / `_sync_control`** — the
  battlefield lists are the **projection** of the derived controller, not the
  storage for it. One synchronizer moves permanents to match, and it is also
  the single place CR 302.6 is stamped, so a permanent changing hands cannot be
  marked summoning-sick by one control path and not by another.

Gone: `_take_control_linked`, `_revert_stolen_permanent`,
`stolen_owner_index`. Control Magic, Steal Artifact, Aladdin, Old Man of the
Sea and Ghazbán Ogre are all one `take_control` call now, and their durations
end by dropping a contribution.

**The bug that justifies the storage change.** Steal Artifact and then Aladdin
on the same artifact, with the Aura destroyed first and Aladdin lost second,
handed the artifact to the Aura's controller — a player who by then controlled
nothing that gave it to them, and who did not own it either. Remember-and-undo
cannot express "two effects, ended out of order", exactly as the single stamped
land-type string could not express two land-type changes. Ending a contribution
is an *absence* now: whatever is left applies in timestamp order, and if
nothing is left the permanent returns to the seat it entered under. Pinned in
`tests/regressions/test_batch23.py` and, as a layer property, in
`tests/rules/test_layers.py`.

Ownership came free with it. CR 108.3 used to be read off the *thief*
(`stolen_owner_index`), so a second theft overwrote the first one's answer and
a twice-stolen permanent could die into the wrong graveyard. It reads
`base_controller_index` now, which no theft touches.

**The guard.** `tests/engine/test_control_reads.py` is the layer-4 sibling: a
raw `player.battlefield` iteration or `in` test outside `engine/mixins/helpers.py`
fails, with each genuine exception acknowledged by `path::function` (so it
survives line edits) and a second test that fails when an acknowledgement goes
stale. Verified by injecting each: reintroducing a raw read, migrating an
acknowledged function, and renaming a seam method.

**What is deliberately *not* done, measured.** 266 sites still address a
permanent **positionally** — `player.battlefield[i]`, `len(...)`,
`enumerate(...)` — concentrated in the combat steps (72), the web API (26) and
the AI policy (19). That is the wire protocol: the browser names a permanent by
its slot on a controller's battlefield, and the engine's declare-attackers /
declare-blockers maps are keyed by those indices. It is a separate axis from
control, and it stays correct only because `_sync_control` keeps the projection
honest — a permanent that changed hands changes slot. Replacing slots with
stable permanent ids is the follow-on, and it reaches the JSON contract and the
canvas renderer, not just the engine.

### Layers 3 and 4 have write APIs, and both needed timestamps

`land_type_override` was the last stamped characteristic: one string on the
land, written by six different effects and un-written by five of them. Each
writer had to remember what it stamped, and could only ever un-stamp
*everything* — so an Aura leaving took a mire counter's Swamp with it, and a
second effect on the same land silently overwrote the first with no way to get
it back.

It is two write APIs now, following `engine/pt.py` and `engine/keywords.py`:

- **`engine/land_types.py`** (layer 4). `change_land_type(land, type,
  source=…)` records a contribution; `end_land_type_change(land, source=…)`
  drops that one. `layer_bridge` turns each into its own CR 305.7 subtype
  replacement carrying its own timestamp, and a second *derived* channel holds
  Conversion's static — cleared and rebuilt each recompute, the split
  `engine/keywords.py` has for the same reason.
- **`engine/text_changes.py`** (layer 3). One entry per text-changing effect,
  applied oldest-first by `Permanent.effective_card` over the rules text, the
  type line and the parsed keywords.

**Both layers needed the timestamps to be real, and neither commutes** — which
is the opposite of what phase 6 found for Auras, where every effect sharing
`_DERIVED_TIMESTAMP = 0` was invisible only because addition commutes. CR 305.7
makes each land-type change a *replacement*, so the newest wins and the reverse
order gives the other answer; a text change rewrites the text the previous one
produced, so black→red then red→black leaves every one of those words reading
**black**, not swapped. `land_type_changes()` deliberately returns storage
order rather than sorting, so the layer engine's timestamps are what order them
and a wrong stamp is a failing test rather than a hidden no-op.

**Three bugs came out of it.**

- **Merging two Sleights of Mind into one substitution table produced an answer
  neither order gives.** `{"B": "R"}` plus `{"R": "B"}` in one dict, applied in
  a single pass, is a *swap*; CR 613.7 says apply them in order, which leaves
  both words black. The single-pass alternation is still exactly right for the
  substitutions *within* one effect — that is what stops a swap collapsing —
  and it is now the primitive (`one_pass`) that the per-effect fold sits on top
  of, rather than the whole model.
- **Layer 3 was being applied twice, in three places.** `_remap_color_filter`,
  `_protection_colors`' trailing remap and `_recalculate_lord_buffs`'
  `_remap_keywords` each patched a value that had *already* been read off
  `effective_card`. With one Sleight of Mind the second application had nothing
  left to match, so it was invisible; with two it compounded. All three are
  gone — the previous pass had named `_remap_color_filter` as the shape
  `effective_card` replaces and then left it in place.
- **Magical Hack was modelled in the wrong layer, and as two different
  effects.** "Replacing all instances of one basic land type with another" is a
  text change (CR 612.1 covers the type line), not a subtype replacement. It
  was a layer-4 stamp on a land and a separate word-remap plus a
  `has_<new>walk`/`lost_<old>walk` flag pair on a creature, so the two branches
  could disagree and the flags had to be kept in step by hand. It is one
  `change_land_word` call now; the keyword follows because the keyword is
  parsed off the changed text.

**The Gaea's Liege acknowledgement in `tests/engine/test_layer_reads.py` is
gone.** It existed because the revert read the stored type back and cleared it
if it still said "forest" — bookkeeping, but also wrong: on a land something
newer had changed, the Liege's effect went on applying invisibly, and on an
Evil Presence Swamp the clear reverted the land to its *printed* Mountain.
Dropping a contribution by source asks nothing about the current type, so the
exemption had nothing left to cover. The guard's staleness test is what caught
it, exactly as designed; the guard itself now pins the new invariant (nothing
outside the two write APIs touches the storage, and each channel has exactly
one consumer) and every part of it was verified by injecting the bug it catches.

One acknowledged limitation, pinned by a test: **"Plains" is spelled the same
singular and plural**, so a text change naming it is read as singular — the
reading a type line uses, and the one that changes what the land is. "All
Plains are …" would come out a letter short. No permanent in this pool writes
that phrase; `singular_land_type` guards the same trap from the other side.

## Phase 6 (original scope) — CR 613 layer system

`engine/continuous.py` with typed
`ContinuousEffect(layer, sublayer, timestamp, source, scope, apply_fn)`;
`effective_power`/`effective_toughness` recompute through it; `pt.py` stays the
write API. Destructive `power_bonus` accumulation and the ad-hoc layer 1–6
metadata (`land_animated`, `color_override`, `has_islandwalk`) migrate to typed
effects. **Unblocks static-ability lowering** — which is why statics migrate
last, and why the grammar currently parses them but declines to lower them.

## Phase 7 — delete the shadow parser, decompose the stack ✅ done

**Final state.** Every supported card answers "what does this spell target?"
from its compiled program — kind *and* flags. `legality.py`'s cast cascade is
deleted (970 → 775 lines, 49 → 29 functions, 19 → 0 cast-time text predicates),
`stack_casting.py` is four mixins in `engine/mixins/stack/`, and `StackItem` no
longer grows a field per card family (20 → 16, with `OracleExecutionContext`
15 → 11). Suite 3,941 → 3,963 tests, still under 20 seconds.

The narrative, including the live bug the full-spec differential found
(Reconstruction was uncastable through the UI), is in "Phase 7 finished" above.
The one piece deliberately left — the `_activated_*` cascade, the same
19-predicate shape for *ability* targets — was finished afterwards and is
recorded in "The shadow parser is gone" above: 19 text predicates → 1,
`legality.py` 775 → 587 lines, and one more live bug (Ebony Horse offered
targets its own handler refused).

The rest of this section is the record of how it got there.

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

**All four of what was open here is now done** — the remaining cards, the
per-kind flags, deleting the cascade, splitting `stack_casting.py`, and folding
`StackItem`'s per-choice fields into a dict. See "Phase 7 finished" above for
what each cost and what it turned up.

## Phase 8 — test restructuring for scale ✅ done

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

### Done — the convention, the factory, and the split

`tests/sets/README.md` is the convention, and
`tests/engine/test_set_test_convention.py` enforces the parts a test can check.

**The factory.** `conftest.py` grew a path fixture, a cards fixture and a
by-name fixture every time a set was ingested — three or four declarations
whose entire content was a set code. `set_pool("ARN")` / `set_cards("ARN")`
resolve any set through the manifest, so **a new set needs no change to
`conftest.py` at all**. `cards`/`all_cards` (LEA) and `arn_cards`/`arn_by_name`
are grandfathered — thousands of call sites between them — and the guard is an
exact expected-fixture set, so *any* addition fails and has to be argued for.

An unknown code raises and names the codes that exist. That is the whole reason
the factory is not a dict lookup: a missing set resolving to an empty pool makes
every test over it pass without testing anything.

**The split.** 9,402 lines → the largest per-set file is now 2,598, split by the
printed type of the card each test names (creatures 106 tests, enchantments 92,
instants 64, artifacts 60, sorceries 40, lands 19). 87% of the tests name their
card in the function name, which is what made the split mechanical rather than a
judgement call per test.

Done with a script, not by hand: every top-level node keeps its exact source
text and its preceding comment block, per-file imports are recomputed from what
each bucket actually uses, and the 908 collected node IDs were compared before
and after — 0 lost. 9,400 lines of hand-moved game tests is exactly where a
silently dropped test hides.

**The catalog sweep moved out of `tests/sets/` entirely.** It parametrizes over
the whole manifest, so it was never a LEA test — and it sat in
`test_lea_cards.py` reading `cards/LEA_cards.json` directly, which is precisely
why Arabian Nights, a set the tracker called complete, went unswept for as long
as it did. It lives in `tests/engine/test_catalog_sweep.py` now, and no test
anywhere spells out a `cards/*.json` filename; the guard scans for it.

Each of the four guards was verified by injecting the bug it exists to catch.
The first draft of the fixture guard **did not fire**: it flagged fixtures named
after a set already in the manifest, but a new set's fixture and its manifest
entry arrive together, so the check could never have fired on the case it
existed for. An exact expected set replaced it.

**Still open:** the suite is at ~17s. That is not from the split (measured
either side: unchanged) — it crept up over four phases, from the 9s the audit
recorded, with the 20s gate green the whole way.

The budget is 35s now, and raising it is the smaller half of the fix. The
useful half is that `ci.yml` records the *measured baseline* next to the budget
and prints the suite as a percentage of it on every run. A pass/fail gate can
only ever catch the cliff; what let 9s become 17s unnoticed is that nothing
reported the trend. The number to keep honest is the baseline, not the budget.

Making the suite faster is still worth doing — 132 sets are still to come, and
per-set tests are the part that grows with them.

## The name rule was never checked, and it had already decayed

Invariant 5 said card names live only in `card_hooks.py`. It was written down
here, repeated in `CLAUDE.md` and in `ARCHITECTURE.md`, and **nothing had ever
tested it**. `engine/ai_policy.py` carried eight name comparisons and
`engine/ai_simulator.py` five, none of them acknowledged anywhere.

The interesting question was whether they were in scope at all. They are not
rules code: an AI heuristic naming a card is tuning, and generalising tuning
sounds like building a card-valuation model. So the sites were classified by
what each name *stood in for*, and the answer settled it — **all eight in
`ai_policy` stood in for something already in the compiled program**, and the
decay was measurable in the current pool, not hypothetical:

| Site | The name stood for | Measured today |
| --- | --- | --- |
| `"Disenchant"` targeting | a targeted destroy, valued by the opponent's board | Shatter, Terror, Stone Rain and Desert Twister print the template, were not named, and the AI **aimed all four at its own permanents** — Shatter resolved onto its own Howling Mine |
| `"Ancestral Recall"` ×2 | drawing more cards than the library holds (CR 704.5b) | Braingeyser is the same sentence with X; with two cards left the AI cast it at itself for X=2 and emptied its own library |
| `"Jayemdae Tome"` | a draw ability with an empty library | Jandor's Ring draws the same card and had no guard |
| `"Lightning Bolt"` lethal | `damage >= opponent's life` — that card's damage spelled out | every other burn spell got nothing |
| `"Black Lotus"` | a permanent whose value *is* mana | every Mox, Sol Ring and Basalt Monolith got nothing |
| `"Unsummon"` | returning a creature to hand | one card in the pool, but the same shape |
| `"Counterspell"` | countering a spell | **dead**: Counterspell's oracle text *is* "counter target spell", so the text probe beside it already matched |

`engine/ai_valuation.py` derives all of it from `compile_card_oracle`, in the
style of `cost_modifiers.py` / `lord_buffs.py` / `land_play_allowance.py`, and
`tests/ai/test_ai_valuation.py` pins every property with an **invented** card
printing the template under a name the engine has never seen — a test naming
only the real card passes against the broken version, which is exactly how these
survived.

**The AI's decisions did not move where they were already right.** The 10-game
seeded simulation is byte-identical, 443 interactions, and the suite is
unchanged. Every decision that *did* change is one of the rows above.

Three findings beyond the brief, all the same decay one level down:

- **`{"add_mana", "black_lotus_add_mana"}`** gated "don't activate a mana ability
  for its own sake", and **neither instruction kind still existed** — both had
  been renamed out from under it. So the AI tapped its Moxen for mana that
  emptied unspent and *sacrificed Black Lotus* to do it. The replacement is a
  named constant held to registered `EFFECT_HANDLERS` entries by a test; putting
  the original set back makes that test fail naming both dead kinds.
- **`"disenchant" in text` / `"unsummon" in text`** — a card's *name* searched
  for inside its own oracle text. No card in the pool contains either, so both
  probes had never fired.
- `_can_cast_with_targets` still reads a permanent's activated ability out of
  `OracleProgram.instructions` (they are mirrored there), so the AI will not cast
  Royal Assassin or Northern Paladin unless the opponent already has something
  the *ability* could destroy. Left alone deliberately — it is the same trap,
  but no card name is involved and fixing it widens the behaviour delta.

### The simulator's assertions are a different case, and the difference is measurable

`ai_simulator._assert_expected` names five cards to assert what each did. It
looks like the same defect and is not: it is a **test oracle**, and a test oracle
derived from the system under test asserts nothing. Measured, not argued —
compile Lightning Bolt with its damage mis-parsed as 1, cast it, and the printed
expectation fires while the same check reading `deal_damage`'s payload expects 1,
sees 1, and passes. The numbers are read off the printed card by a human on
purpose.

It has a real decay mode all the same, just not this one: the decklist can move
out from under it, and an expectation for a card `_build_deck` no longer plays
stops firing with nothing failing. That now has a guard which reads the names
out of the source and checks them against the deck.

### The guard, and what it scans for

`tests/engine/test_card_name_reads.py` is the mechanism the invariant never had.
It scans `engine/` for a card name **deciding behaviour** — a comparison or
membership test against `<something>.name` — with `card_hooks.py` excluded, an
`ACKNOWLEDGED` dict keyed `path::function`, and a staleness test.

Scanning every string constant was tried first and is too blunt: `Sacrifice`,
`Channel` and `Lich` are all card names *and* all appear as ordinary log and
prompt labels. A name in a log line is data; a name in an `if` is dispatch. Basic
lands are exempt because a basic land's name is also a land subtype, and subtypes
are vocabulary data.

All four tests were verified by injecting the bug each exists to catch: putting
`card.name == "Disenchant"` back fails the scan (and three behaviour tests
alongside it), pointing `HOOKS` at another module fails the vacuity check,
renaming `_assert_expected` fails the staleness check, and restoring the dead
mana-kind set fails the handler check naming both kinds.

## The web layer, split on the same axis the stack was

`web/app.py` was 4,930 lines and 144 definitions — the largest file in the repo,
and the one place where serialization, the pregame state machine, turn driving,
the AI loop, the debug menu and the action dispatch all sat next to the routes.
It is the FastAPI app and **nothing else** now, at 567 lines, with thirteen
modules beside it:

| Module | Job | Defs | Lines |
| --- | --- | ---: | ---: |
| `runtime` | card pool, store instances, session lookup | 2 | 71 |
| `events` | server-sent events — the one thing the API pushes | 2 | 55 |
| `seats` | seat kind, who has lost, whether to hold priority | 11 | 155 |
| `serialization` | engine object → client JSON, one function per kind | 21 | 708 |
| `catalog` | the pool and decks as the client browses them | 6 | 173 |
| `verification_report` | the verification tracker's read side | 2 | 93 |
| `pregame` | coin flip and mulligans | 9 | 229 |
| `turn_steps` | the beginning phase and the turn's boundaries | 23 | 430 |
| `combat_prompts` | banding / multiblock / pile-division assignments | 14 | 362 |
| `game_flow` | priority, phase advancement, AI stepping | 7 | 435 |
| `state_view` | the whole-state payload a client polls | 5 | 386 |
| `debug_actions` | Debug-Menu board manipulation, raw-state injection | 6 | 202 |
| `actions` | the one dispatch over `ActionKind` | 5 | 1,451 |
| `app` | the FastAPI app: routes, middleware, join URLs | 31 | 567 |

**The axis is one module per stage of a session's life in the web layer**, which
is the same move `engine/mixins/stack/` made for an object's life on the stack —
before a session exists (`catalog`), the ground it lives in (`runtime`), who is
sitting at it (`seats`), before turn one (`pregame`), a turn's boundaries
(`turn_steps`), the game moving forward (`game_flow`), what the client sees
(`serialization` → `state_view`), what the client does (`actions`).

**The axis is also a *layering*, and that is the part with teeth.** `web.LAYERS`
declares the order and a module may import only from one earlier in it; nothing
imports upward, and the ordering constraint is checked mechanically as the split
runs, so a bucket that reached sideways failed the build rather than shipping.
Two facts fell out of enforcing it rather than asserting it. `_seat_deck_colors`
and `_seat_deck_display_name` *look* like seat questions and would have put
`seats` above `catalog`, closing a cycle back through `serialization`; their only
caller is `_serialize_state`, so they are view code and belong in `state_view`.
And the hold-priority predicates (`_ai_should_hold`, `_hold_priority_for_human`,
`_self_should_hold`) are what makes `turn_steps` and `game_flow` separable at
all: mutually recursive as written, they separate the moment the three
predicates — which need no card data and no turn state — drop to `seats`.

**Done with a script, phase 8's method, and the proof is two numbers.** Every
top-level node kept its exact source text and its attached comment block, and
per-module imports were recomputed from each bucket's actual free names. Then:
**169 top-level definitions before, 169 after, 0 lost and 0 gained**; and
**30 registered routes before, 30 after** — identical path, methods and name on
every one. A separate pass diffed each node's *slice including its comments*
straight off disk and found exactly one difference in 4,930 lines: `do_action`
lost the `@app.post` decorator, which became
`app.post(...)(do_action)` in `app.py`. Nothing else in the file changed by a
character. That last check matters because the obvious comparison —
`ast.get_source_segment` — does not see a decorator or a preceding comment, so
the thing most likely to be dropped by hand is the thing it cannot report.

**`web.app` stopped being the god-namespace.** 233 names were bound there; 101
are now, and the 132 that went are the module's own imports plus definitions
nothing outside `web/` ever read. Twenty-two are re-exported explicitly, with a
comment saying why: they are the names tests and scripts reach for
(`from web.app import _end_turn`, `web_app._advance_phase`), so the split needed
**no edit outside `web/`** — except one, below. Re-exporting all 132 was the safe
option and was rejected: a barrel that keeps every name importable from `app.py`
guarantees nothing ever migrates off it, which is the shape the split exists to
end.

**One thing could not move, and one had to change.** `ALLOW_SHARED_DECK_WRITES`
and the join-URL builders stay in `app.py` because tests monkeypatch them *on the
`web.app` module object* — `monkeypatch.setattr(web_app, "_detect_local_ip", …)`
only reaches a reader in the same namespace, so moving them would have left the
patch setting an attribute nothing reads, and the test would have passed for the
wrong reason on a real IP. They are route-shaped anyway (both read the incoming
`Request`). The one outside edit is
`tests/engine/test_pending_choices.py`, which greps the dispatch source for
`req.action == "<kind>"`; it now reads `web/actions.py`.

**The layering is guarded, and the guard was verified against the failure that
does *not* announce itself.** `tests/ui/test_web_layering.py` reads `web.LAYERS`
and rejects any intra-package import pointing at or above its own module, in all
three spellings (`from .x`, `from web.x`, `import web.x`). A module-level cycle
would fail at startup anyway; a *function-level* one would not, and that is what
was injected — `from .state_view import _serialize_state` inside `seats._seat_type`
leaves `import web.app` working perfectly and fails the guard on the line it sits
on. A second guard fails if a new `web/*.py` is not placed in `LAYERS` at all,
because a module the layering never mentions is a module the first guard never
reads; verified by dropping an unlisted file in.

**`actions.py` at 1,451 lines really is size, and is a separate job** — the same
thing the stack split said about `stack_casting.py`. `do_action` is a 70-branch
`if`/`elif` over `ActionKind` wrapped in a shared preamble (seat check, concede,
pending-prompt refusal, priority bookkeeping) and a shared tail (snapshot, AI
response, serialize) that apply to every branch. Splitting the branches out is a
restructure of control flow, not a move, and it does not belong inside a change
advertised as touching no behaviour. It stays one chain in one module, which is
also what keeps the dispatch reviewable against the literal it dispatches on.

Suite 4,292 → 4,297 (the five layering tests) in 14.1s, every guard green,
388/388 supported, AI simulation unchanged at 10/10 games and 443 interactions.
Verified in the running app as well as in tests: server starts clean, a
human-vs-AI game reaches its opening hand, keeps, plays a land and ends a turn
through `POST /action` while the AI takes its own, and the canvas board renders
with life totals, phase rail and hand — zero console errors.

**Found and deliberately left** (a behaviour change hidden in a 5,000-line move
is unreviewable): the `_no_cache_assets` middleware matches a hardcoded set of
asset paths, and three first-party scripts `index.html` actually loads —
`/sfx.js`, `/music.js`, `/legality.js` — are not in it, so they alone are
browser-cacheable while their siblings are not. The `?v=` query strings they
carry are the real cache-bust today (and the middleware matches on `path`, so it
never sees them), which is why nothing has noticed. Separately: `_serialize_state`
mutates the game — `_ai_resolve_raging_river` and `award_ante_to_winner` — so
`GET /state` is not a read. Both are documented idempotent and both predate this
change.

**Both are fixed, as their own change — see "The two the pure move left" below.**

---

## Deleting `engine/parsing/`: the "expected a subject" bucket, split two ways

The deletion criterion is mechanical: compile the whole manifest pool twice,
once with `parse_primary_instruction` / `parse_modal_options` /
`parse_static_coeffects` stubbed, and diff each card's program. It started this
pass at **110 cards changing, 69 losing support**, and the largest single reason
the grammar gave was "expected a subject" — 61 distinct lines.

**The triage was the work; writing the productions was not.** The bucket splits
cleanly once you ask the only question that matters: *could a second card, real
or plausibly printable, carry this sentence?*

**Six lines were templates and became productions.** Each reproduces the legacy
rule's payload byte for byte, and each carries the refusals that stop it
becoming the substring match it replaced:

| Production | Cards | What it refuses, and why |
| --- | --- | --- |
| `that player discards a card at random` on a damage trigger | Hypnotic Specter | any trigger that does not record a damaged player — the handler reads the victim out of the trigger's context, so elsewhere the sentence names nobody |
| `remove [a\|N] <kind> counter(s) from <subject>` as an effect | Armageddon Clock | more than one counter, and any subject but the source; also declines "remove target creature … from combat" so those keep their own failure |
| `change the text of <target> by replacing all instances of one <vocabulary> with another` | Magical Hack, Sleight of Mind | a vocabulary outside the two the substitution performs |
| `gain control of <target> for as long as you control this <permanent>` | Aladdin | an absent duration, and any filter but artifact — the handler looks for an artifact in its own source |
| `exile <target>. Its controller gains life equal to its power.` | Swords to Plowshares | a bare exile, naming the handler that does not exist yet |
| `destroy that creature at end of combat` | Thicket Basilisk, Cockatrice | any other trigger, and the end-*step* delay (Stone Giant, Nettling Imp), which is a different handler |

**Thirty-nine lines across 38 cards were one card's text, and went to
`card_hooks.CARD_LINE_INSTRUCTIONS`.** Chaos Orb's flip, Camouflage's blocker
piles, Shahrazad's subgame, Cyclopean Tomb's mire counters, the four coin-flip
and "next time … instead" fused kinds. A grammar production for any of them
would be the same whole-card substring match wearing a grammar hat — the defect
the audit measured (133 of 168 rules were literal substring matches, several
encoding whole card texts) and the thing the deletion exists to stop inheriting.
`card_hooks.py` is where a card's name is the point, so the reading moves there
unchanged and *honestly labelled*.

The registry is keyed by **(card name, normalized line)** — not by name alone,
which would claim lines a production already reads, and not by text alone, which
would make it a second `engine/parsing/`. `engine/oracle.py` consults it after
the grammar and before the legacy rules, so a line that later grows a production
makes its entry **dead rather than wrong**. Three guards
(`tests/engine/test_card_lines.py`), each fault-injected:

* a key must match a printed line of that card in the pool — a hand-typed key
  that drifts is a hook that can never fire, and a missing hook is
  indistinguishable from a card nobody hooked;
* every entry must still supply an instruction *with the legacy rules stubbed* —
  which is what makes a dead entry fail rather than linger as a card's apparent
  implementation while the real one is elsewhere;
* every entry must read its line the way the rule it replaced did. This one
  retires with `engine/parsing/`; the first two do not.

**Refusals, with the missing code named.** Not everything in the bucket was
implementable, and three cases were refused rather than papered over:

- **"When there are no creatures on the battlefield, sacrifice this
  enchantment."** (Drop of Honey.) The *effect* half already lowers. The
  condition is not in `WHEN_TRIGGER_PATTERNS` and nothing dispatches it, so
  adding a phrase would compile a trigger the game has never fired — coverage
  rising while nothing changes, which is worse than the gap.
- **"Remove this card from your deck before playing if you're not playing for
  ante."** (Contract from Below and three others.) Nothing implements it; it is
  a `spell_pattern` marker. Claiming it would report a rule the engine does not
  apply.
- **Metamorphosis.** It prints Sacrifice's additional-cost line and a different
  effect (X mana of any one colour), and the legacy rule hands it *Sacrifice's*
  black-mana instruction. Registering that would re-state a wrong reading as
  understood, so only Sacrifice is hooked and Metamorphosis keeps its gap: no
  handler adds any-colour mana sized by a sacrificed creature's mana value.

**Two card names left the engine on the way.** The Hypnotic Specter production
would have put `hypnotic_specter_deals_damage` into `engine/grammar/parser.py`,
and the Basilisk one `cockatrice_blocks_or_blocked` — both trigger-condition
kinds named after a card, in violation of standing invariant 5 and in a file
that is supposed to be about templating. They are now
`creature_deals_damage_to_opponent` and
`creature_blocks_or_blocked_by_nonwall`. The behaviour-class snapshot is a list
of card-name sets rather than signature hashes, so a pure rename left it
untouched.

**A near miss the guards caught.** `_line_instruction` composes the grammar and
the hooks, and the obvious place to put the hook lookup was inside
`_grammar_instruction` — where `tests/engine/test_grammar_fallback_safety.py`
stubs it to compile the pool without the grammar. That would have stubbed the
hooks too and made the guard report every hooked card as an instruction loss.
The two front ends stay separate functions for exactly that reason.

Result: **110 → 66 cards changing, 69 → 38 losing support.** Grammar coverage
73.2% → 75.6% parsed, 71.1% → 73.3% lowered, 37.6% → 39.9% executed; the probe
baseline tightened by one (the grammar now claims Living Artifact's optional
counter removal, so its dropped-rider finding stopped occurring). What remains
in this bucket is four cards whose "expected a subject" line is not their
blocker — Contract from Below, Drain Life, Gaea's Liege and Siren's Call each
fail on a line in a *different* backlog reason.


---

## Deleting `engine/parsing/`: the last bucket, and where a table already knew

Wave C opened at **66 cards changing, 38 losing support** and closed at **5 and
1**. Same criterion as before — compile the manifest pool twice, once with
`parse_primary_instruction` / `parse_static_coeffects` stubbed, and diff each
card's program — and the same triage question. What was new was a third answer
to it, sitting between "template" and "one card's text".

### The cheapest tool was the one that writes no grammar at all

Agent D's `RegistryLine` claims a line by asking the code that implements it,
never by copying its phrases into the parser. Four of this wave's lines had an
implementing table that produces an **instruction**, which `RegistryLine` cannot
carry — it lowers to nothing by contract. `engine/grammar/derived.py` is its
sibling for those: the table matches the line *and* computes the payload, and
the lowering hands that over unchanged.

| Table | Lines |
| --- | --- |
| `engine/land_animation.py` | Kormus Bell, Living Lands |
| `engine/land_types.py` | Conversion |
| `engine/lord_buffs.py` | Jihad's conditional anthem |

`static_land_type_change_for` is new; the rule it replaces spelled the five
basics into a regex of its own and matched with `.search` over the card's whole
collapsed text, so "All Deserts are Islands" was unsupported while the consumer
— which reads only the payload — had every line of code it needed. It is now
derived from `data/vocabulary/land_types.json` and anchored at both ends, and
`tests/rules/test_land_type_changes.py` pins it with invented cards.

**The ordering is the whole safety argument.** `parse_line` runs every
production first and consults the tables only after a `GrammarError`, so a table
can reach nothing a production could read. Left the other way round,
`lord_buff_for` claims six anthems the static-buff production already owns —
measured by injecting exactly that swap, which is what
`test_a_derived_claim_only_ever_reaches_a_line_no_production_reads` reports.

Jihad also showed why these are appended as **co-effects** rather than claimed as
line instructions. Claiming its anthem as a line makes the compiler's whole-text
fallback stop running, which silently drops the *other* sentences' reading and
trips the differential guard on instruction count. `parse_static_coeffects`
already existed for that exact shape — a continuous static coexisting with a
clause that claimed the card — so the grammar's derivations join it there, ahead
of it, with the same de-dupe by kind.

Fastbond needed no instruction at all: `land_play_line` already claims both
halves of its template, so both are `RegistryLine`s and the `deal_damage` the
whole-text fallback was inventing for the rider simply goes away.

### Three productions, and one compiler stage that was in the wrong package

- **`<player> mills <n> cards`** (Millstone). Refuses any miller but the target:
  `mill_target_player` mills `context.target` and reads no player from its
  payload, so "you mill three cards" would compile cleanly and mill whoever
  happened to be targeted.
- **`you may pay {N}. If you do, untap this <permanent>`** on an upkeep trigger
  (Mana Vault, Brass Man, Island Fish Jasconius). Fused, like every upkeep
  shape, because the dispatcher is keyed on the (condition, kind) pair.
  Recognised on the *node*, before `lower_statement` runs — the generic `may`
  lowering refuses a coloured optional cost, rightly, and Island Fish pays
  {U}{U}{U}. Paralyze stays a hook: its payer is the enchanted permanent's
  controller and its object is "the creature", a definite noun phrase with no
  antecedent in its own clause.
- **Modal spells moved into `engine/oracle.py`.** Splitting `Choose one —` into
  bullets is line classification, which the compiler owns; each bullet's effect
  already went through the grammar. `parse_modal_options` lived in
  `engine/parsing/__init__.py` purely by history, and with it there the deletion
  would have taken Blue Elemental Blast, Red Elemental Blast and Healing Salve
  with it. A modal spell's card-level instruction is its first mode's — the
  bullets are alternatives, and the whole-text reading of one is a spell that
  does every mode at once.

### Fifty-one lines went to `card_hooks.CARD_LINE_INSTRUCTIONS`

Generated from each line's own legacy reading rather than transcribed, so the
"same instruction, same effect_kind" guard was satisfied by construction rather
than by proofreading. Four of them are earlier refusals finally getting an
honest home instead of a widened production: Black Lotus's three-mana
any-colour, Rukh Egg's token name under CR 111.4, Twiddle's `may` on a spell
path, and Jandor's Saddlebags' filtered untap.

### What remains, and the ratchet that holds it there

`tests/engine/test_legacy_rule_removal.py` is the deletion criterion as a test:
compile the pool with the legacy rules stubbed, and assert the cards that change
are exactly two named lists, each entry naming the code involved. One card loses
support — **Metamorphosis**, refused twice now for the same reason: no handler
adds player-chosen-colour mana sized by a sacrificed creature's mana value, and
the legacy rule hands it *Sacrifice's* black-mana instruction.

Four more change shape without losing support, and all four are the same thing:
the whole-text fallback invented an instruction for a sentence the engine
implements somewhere else. Fastbond's `deal_damage` (the land-drop path derives
it), Island Sanctuary's `draw_controller_cards` (the card skips a draw, it does
not take one), Jihad's `sacrifice_self` (read only through a trigger condition
no table has), Lich's `player_loses_game` (an instruction on an enchantment's
mirror, which nothing resolves). Those disappear when the fallback does.

Grammar coverage 75.6% → **77.2% parsed**, 73.3% → **75.3% lowered**, 39.9% →
**41.4% executed**. 4,350 tests, 388/388 supported, AI simulation unchanged at
10/10 and 443 interactions.

---

## `engine/parsing/` is deleted

**2,303 lines across 18 modules, gone.** The compiler reads a line through
`engine/grammar/` and then through `card_hooks.CARD_LINE_INSTRUCTIONS`, and
there is no third front end: a line neither claims produces no instruction, and
its card is reported unsupported naming the clause. 388/388 supported before and
after; the AI simulation is byte-identical (10/10 games, 443 interactions); the
support report is byte-identical; every card's compiled program is identical
except the five below.

### Metamorphosis was not what the last ratchet said it was

`LOSES_SUPPORT` claimed no handler adds player-chosen-colour mana sized by a
sacrificed creature's mana value. **`sacrifice_creature_for_black_mana` does** —
it had been doing it since the batch-18 bug round, by running three `in` probes
against the resolving card's own oracle text: `"1 plus the sacrificed creature's
mana value"` bumped the amount, `"mana of any one color"` took the caster's
colour choice, `"spend this mana only to cast creature spells"` routed the mana
into the restricted bucket. So the card was already right, and what it lacked
was an *instruction of its own* — the legacy rule handed it Sacrifice's, and the
handler recovered the difference by re-reading the card. A second parser living
inside a handler, which is the shape this whole migration exists to remove.

It is now payload: `color` (a symbol, or None for "of any one color"), `bonus`
(0 for Sacrifice, 1 for Metamorphosis's "1 plus"), `spend_only` (None, or
`"creature"`). The kind is `sacrifice_creature_for_mana`, because the old name
was a lie for one of the two cards carrying it. Both are keyed in
`CARD_LINE_INSTRUCTIONS` on the additional-cost sentence they *share* — which is
what makes the name load-bearing rather than a shortcut here: the line alone
cannot say what the card does, and a production keyed on it would have to give
one answer for two cards.

Verified in a game: Metamorphosis sacrificing a Hill Giant (mana value 4) with
blue chosen gives 5 blue mana in the creature-only bucket and none in the pool;
Black Vise is refused for insufficient mana and Grizzly Bears is not. Sacrifice
on a Grizzly Bears still gives 2 unrestricted black.

### The four phantom instructions were phantom, checked in play

Each was the whole-text fallback inventing an instruction for a sentence
implemented elsewhere. All four were played out rather than reasoned about:

- **Fastbond** — three lands in one turn, life 20 → 19 → 18, logged as
  "Fastbond dealt 1 damage to P1". `engine/land_play_allowance.py` derives both
  halves; the `deal_damage` on the enchantment's mirror was dispatched by
  nobody.
- **Island Sanctuary** — the draw is skipped and the flag set; a ground Grizzly
  Bears is refused an attack and a flying Mahamoti Djinn is allowed.
  `card_hooks.DRAW_STEP_MODIFIERS`, read by three phase steps.
- **Lich** — enters and takes its controller to 0; the controller does not lose;
  gaining 3 life draws 3 cards instead; 2 damage sacrifices 2 nontoken
  permanents; putting the Lich into a graveyard loses the game. Four separate
  text-keyed sites, none of them an instruction.
- **Jihad** — Savannah Lions is 4/2 while the chosen player controls a black
  permanent, and when that permanent leaves, Jihad is sacrificed and the Lions
  are 2/1 again. The CR 603.8 state trigger in `game_ending.py`.

### The bug the deletion exposed: Mana Vault

**"At the beginning of your draw step, if this artifact is tapped, it deals 1
damage to you." is not implemented.** No trigger table has a per-permanent
draw-step condition, nothing scans for the phrase, and the card's program
carries no instruction for it. Verified in a game: a tapped Mana Vault costs its
controller nothing at their draw step.

It read as covered because `parse_coverage.py` asked the *legacy registry* about
the sentence in isolation, and a broad rule matched "deals 1 damage to you" —
an instruction the card's own program never carried and nothing ever dispatched.
The guard was reporting a claim the engine had never made. It is now an
`ACKNOWLEDGED` entry naming precisely what is missing; implementing it needs a
per-permanent draw-step trigger (the shape `phases/upkeep_effects.py` has for
the upkeep) and is a behaviour change, so it belongs in a pass of its own.

### The pool was not the whole gap

The deletion ratchet compiled the *pool*. It never compiled the **test
fixtures**, and 25 synthetic card texts lost support the moment the registry
went — templating no printed card in LEA/ARN/3ED carries, which the legacy rules
had rules for and the grammar had never been asked to read. Split two ways:

**Real templating with a real handler → productions.** "You win the game.",
"Target player loses the game.", "The game is a draw." (`ast.WinGame` and
`ast.LoseGame` had existed unreachable since phase 1; `DrawGame` is new, and the
sentence has no subject so it is a leaf beside the colour-shield production).
"Exile target creature until end of turn." — `ast.Exile` gained a duration,
because a bare exile and a temporary one are different handlers and dropping the
rider onto the permanent reading is the bug class. "Prevent the next N damage
that would be dealt to **target player**" — the lowering refused a `PlayerRef`
recipient although `apply_prevention_shield` shields a chosen player perfectly
well.

**Fixtures leaning on a refusal → fixtures fixed.** "Untap target creature." is
refused *on purpose* (`untap_target_permanent` untaps whatever it is handed), so
the fixture now says "target permanent", which is what the handler does.
"{T}: Add {G} for each creature you control." is CR 605.2's own example, and
`_add_mana_from_text` would add one {G} and drop the rest — so that test uses
605.2's other half, a mana ability on an already-tapped permanent, and says why.
Two fixtures named a card inside its own oracle text (pre-errata Black Lotus,
pre-errata Drain Life) and one ran a spell effect and a cycling trigger together
on one line; all three are now the printed text.

### Scaffolding: kept, re-pointed, retired

| Piece | Outcome |
| --- | --- |
| `tests/engine/test_grammar_differential.py` | **Retired.** Its subject was grammar-vs-legacy. Four survivors moved: the combat-restriction comparison (against a live derivation table) to `test_grammar_derived_lines.py`; determinism, the load-bearing check and pool-wide support to `test_front_end_safety.py`. `ACCEPTED_DIFFS` retired with it. |
| `tests/engine/test_grammar_fallback_safety.py` | **Re-pointed** to `test_front_end_safety.py`. Stubbing the grammar no longer leaves the legacy rules, it leaves the card hooks — and the hazard that survives is real: a production that takes a hooked line over and reads *less* of it. `ACCEPTED_REPLACEMENTS` emptied; all six entries were "a deleted category's leftover broad rule", which no longer exists. |
| `test_grammar_ratchet.py` + `grammar_ratchet.json` | **Kept, re-pointed.** "% of lines the grammar parses" stops being a migration measure and becomes a division-of-labour one: every line the grammar does not read is read by a name-keyed hook or a sidecar table, or leaves its card unsupported. A fall means the pool became more special-cased. Floors unchanged (77.2 / 75.3 / 41.4). |
| `GRAMMAR_CATEGORIES` | **Kept, meaning changed, and now pinned.** Nothing was off — every category with a lowering was already on — but the *reason* to keep it is different: with no fallback, a category left off makes cards unsupported rather than routing them elsewhere. `tests/engine/test_grammar_categories.py` holds it equal to what `lower.py` can emit, in both directions. |
| `behavioural_payload` / `GRAMMAR_ONLY_PAYLOAD_KEYS` | **Removed from `parse_coverage.py`, kept for the lowering goldens.** Its job was making two front ends comparable; dropping it from the probe made the probe stricter (96 → 9 findings). |
| `scripts/grammar_coverage.py`, `GRAMMAR_COVERAGE.md` | **Kept**, re-titled from migration tracker to parser reach. |
| `tests/engine/test_legacy_rule_removal.py` | **Retired.** It was the deletion criterion; the deletion happened. |
| `tests/engine/test_parsing_common.py` | **Retired** with its subject (`engine/parsing/common.py`). |
| `test_card_lines.py`'s third test | **Retired**, as its own docstring always said it would be — there is no legacy reading left to compare a hook against. |
| `test_grammar_differential`'s directional whole-program check | **Retired deliberately: it could no longer fail.** It was written when the compiler had a per-card whole-text fallback, so switching the grammar off could change the *number* of instructions. The list is per line now and each line yields exactly one instruction whichever front end claims it, so the hooks-only compile can only ever have fewer. Three injections were tried and it stayed green for all three. |
| The parse-coverage probe self-test | **Rewritten.** It appended nonsense to a clause and checked a substring rule swallowed it — a shape one full-consumption parser makes impossible, so the assertion could never fire again. It now uses a word the parser *consumes* but does not carry ("destroy **all** creatures"), with a second test asserting the probe is silent when every word is load-bearing. |
| `engine/effect_labels.py` | **New**, and the one thing carried rather than deleted. `effect_kind`'s vocabulary was the registry's own, and the compiler preferred the legacy label whenever a legacy rule matched a line the grammar had already read — so deleting the registry would have silently re-bucketed 57 cards and stripped the `triggered_` prefix `web/serialization.py` turns into a stack item's `is_triggered`. Both tables are held to the pool in both directions. |

### Odds and ends the deletion took with it

`_instruction`, `parse_number_token`, `_parse_number_token` and
`_extract_mana_cost_from_text` in `oracle_types.py` were the registry's toolkit
and had no other caller; `_NUMBER_WORDS` stays, because three text-keyed
derivation tables read it. `_prefer_line_reading` — which took the grammar's
instruction and the *legacy* label — is one line of widening now.
`ARCHITECTURE.md`'s nine `BAND_*` order bands are gone, and their absence is the
point: precedence was a property of a registry of substring predicates, and a
grammar has no such knob.

### Where the pool stands

4,326 tests, 388/388 supported, grammar coverage 77.2% parsed / 75.3% lowered /
41.4% executed, AI simulation unchanged at 10/10 and 443 interactions. Parse
coverage: every sentence claimed, one acknowledged simplification added (Mana
Vault), probe baseline 96 → 9 entries.

---

## Splitting the two files that grow with the pool

`lower.py` (2,428) and `parser.py` (2,306) were the largest files in the repo
and were parked as "size is a separate job". The M21 result retired that
reasoning: the cost that scales is **parser breadth**, and every new template
lands in exactly these two. They stopped being big files that happened to grow
and became the files that have to absorb 25,000 more cards' worth of templates.

### The equivalence harness came first

4,600 lines of parser moved. The only honest way to do that is to be able to
prove nothing changed, so before touching anything: compile every card in the
ingested pool — shipped *and* measured, because M21's 503 lines reach
productions the 1993 sets never do — and dump a canonical form of the result.
668 cards, 13,219 lines, at two levels that fail differently. Per **card**, the
`OracleProgram` the engine dispatches on, which catches a reordered instruction
or a dropped payload key. Per **line**, the raw `CompiledLine` including every
*failure message*, which catches a production that still refuses a line but for
a different reason — invisible in the program until a card's text changes.

Both splits were generated from the original file rather than edited into
shape, so the output is a function of one input, and both diffed **byte-identical**
against that baseline.

Two things about the harness itself are worth recording, because both were
wrong first. The verification was originally an inline `&&` chain, where a
failing snapshot step left the previous diff file untouched and `[ -s diff ]`
then reported IDENTICAL for a comparison that never ran — a check that passes
when it does not execute is worse than none, so it became a script with
`set -e`. And the injection test that proves the new guard bites wrote its
violation, crashed before restoring, and left a stray import in
`effects/damage.py` that the next run reported as a real finding. Restores go in
a `finally`.

### The partition was found, not chosen

Both files already carried banner comments marking their sections. Rather than
trust them, an AST pass mapped every top-level name to every other name it
references and reported the cross-section edges. That turned up the same class
of problem in both files, and it is the interesting part:

* **`parser.py` had a cycle.** Four *effect* productions — `_parse_become_color`,
  `_parse_prevent`, `_parse_prevent_all`, `_parse_colour_source_prevention` —
  had drifted to the bottom of the file under the "Line classification" banner.
  They were the only thing making the graph cyclic. Filed with the effects, the
  order is strict.
* **Both files had fragments filed as effects.** `_parse_zone` and
  `_parse_mana_payment` in the parser; `_full_mana_payload` (with `_MANA_KEYS`)
  and `_REST_OF_TURN` in the lowering. Each was wanted by two or three
  families — a zone by search and by bounce, an "unless they pay" cost by
  damage and the board — and they were the **only** references crossing between
  families. In `phrases`/`_common` the seven families are independent.

That independence is the property worth having, and it is why the fragments
moved rather than being tolerated. It is what makes "where does prowess go?" a
question with an answer instead of "wherever, then fix the imports".

### The shape, and the same names on both sides

```
phrases.py     word tables + fragment productions   |  lowering/_common.py
effects/       damage characteristics board cards   |  lowering/  (same seven)
               stack combat game                    |  lowering/categories.py
statements.py  one whole sentence                   |
parser.py      one printed line (parse_line)        |  lower.py (dispatch)
```

The families are deliberately named identically on the parsing and lowering
sides, so a template has one home per side: prowess parses in
`effects/characteristics.py` and lowers in `lowering/characteristics.py`. Both
packages re-export flat, so callers name a production and never its family, and
moving one between families is not a caller-visible change.

`INSTRUCTION_CATEGORIES`, `GRAMMAR_ONLY_PAYLOAD_KEYS` and `lower_statement` are
re-exported from `lower.py` because callers outside the package import them from
that address (`grammar/__init__.py`, two test modules). The table moved; its
address did not, which is what kept this a pure move rather than a rename with a
diff attached.

Largest module in `engine/grammar/` is now 626 lines, down from 2,428. Nothing
in the parser or lowering is over 450.

### The guard, and what it is for

`tests/engine/test_grammar_layering.py` holds both properties: the layers import
only downward, and the families do not import each other. A split that is not
tested is a split that lasts until the next hurried change.

It also carries a 1,000-line ceiling per module — not a style rule. These files
grow with the card pool, so a module drifting back over a thousand lines means
the families stopped absorbing new work and something is being appended to
whatever was easiest to find.

Every rule is injection-tested: five deliberate violations, five caught. A sixth
(`statements` importing `parser`) is deliberately *not* in that list, and the
reason is worth stating — injecting it makes the package circular, so `conftest`
fails to import and pytest never reaches the guard. That is a louder failure
than the guard's own, not a hole in it.

Suite 4,369 → 4,378.

---

## `ast.py` was the third file that grows with the pool

The layering guard put a 1,000-line ceiling on every module under
`engine/grammar/`. `ast.py` was at 981 — nineteen lines from tripping, and it
gains a node type with every new template. Split before the next feature rather
than during it.

Nine modules on the same seven families, `_core` at the bottom (quantities,
nouns, durations, zones, costs — the vocabulary every node is built from) and
`statements.py` as a **roof**: `Effect`, `Statement` and `AbilityNode` are unions
over every family, so they can only be written where every leaf is visible. That
is the one module in the three packages that imports a family, and the edge runs
one way — the families are held to `_core` by one test, and the roof is held to
`_core` + the families by another.

Unlike the parser and lowering splits, **no fragment had to be rescued**: every
node already referenced only the shared vocabulary or its own family.

What the dependency pass did turn up: **`CombatRestriction` was defined after
`__all__`**, at the very bottom of the file. The module never exported it, and
the `Effect` union still does not name it — while `lower.py` dispatches on it
like any other leaf effect. `__all__` had also silently dropped `BoardCount` and
`DamageUnlessPay`. Nothing imports `*` anywhere in the repo, so all of it was
inert at runtime; the regenerated front door now names all 89. **Adding
`CombatRestriction` to the `Effect` union is left open deliberately** — that is
a semantic change, not a move, and it belongs in whatever change decides what
the union is for.

Largest AST module is now 328 lines. Suite 4,378 → 4,382.

---

## Modal, and the substring that had been lying

`GRAMMAR_COVERAGE.md`'s backlog is sorted by lines ÷ distinct — how many printed
lines one production buys. `modal line` led it at 3.5 (21 lines, 6 sentences),
and it is worth far more than 21 lines suggests: "Choose one —" is on a large
fraction of every modern set printed since.

**The head carries no modes, on purpose.** CR 700.2 puts the modes in a
bulleted list *below* the head, and each bullet is an ordinary effect line the
parser already reads. A node holding copies of them would be a second reading of
the same text — the failure this engine is organised to avoid. So `ModalNode`
records the count and nothing else, and `engine/oracle.py` groups the head with
the bullets directly beneath it.

**It is a `Statement`, not an `AbilityNode`**, and that is what makes
`Choose one —`, `{2}: Choose one —` (Pyramids) and
`When this creature enters, choose one —` all read through line shapes that
already exist: the cost stays on `ActivatedAbilityNode`, the event on
`TriggeredAbilityNode`. As a line node it would have needed its own copy of
both, and a head parsed with its prefix dropped is exactly the silent-rider bug.

The compiler now has **one reader instead of two**. `_CHOOSE_ONE_RE`,
`_MODAL_ABILITY_HEAD_RE` and `_normalize_mode_clause` (defined, never called)
are gone; both paths ask the grammar.

### The bug the substring was hiding

`_CHOOSE_ONE_RE` matched `choose one` — which is a substring of
**"Choose one or more"**. So a spell whose controller picks *several* modes
compiled as one that picks the first, and reported itself supported. Sublime
Epiphany (M21) was doing exactly that. It now parses in full and refuses at
lowering, naming the limit: the engine's `StackItem.chosen_mode_index` is a
single index, so `choose two` / `choose one or more` have no representation yet.
Refusing loudly is the correct outcome; the card's support count went 105 → 104
and that number is now true.

`Battalion —` moved buckets too: it used to be swallowed by the blanket "any em
dash ⇒ modal line" rejection and now reports `expected a subject`, the trigger it
actually cannot read. An ability word (CR 207.2c) was never a modal line.

Coverage: ALL parsed **77.2 → 78.0%**, lowered **75.3 → 76.1%**. Executed is
deliberately flat — the head executes nothing, the bullets do, and they were
already counted as the separate lines they are. **Cards gaining support: zero,
and that is the correct number** — every modal card in the shipped pool was
already supported through the old reader.

`"modal line"` is retired from `_ROADMAPPED_REASONS` in the same change, as that
dict's own docstring requires. Suite 4,382 → 4,403; CR 700 goes 0/15 → 1/15.

### Quoted abilities were not worth it, and the ratio said so misleadingly

Second on the table at 2.1 — and that ratio is an artifact of one error message
covering unrelated work. The 13 distinct lines are 13 different templates
(`All artifacts have "…"`, `creates a token with "…" and "…"`,
`You get an emblem with "…"`), and one of them is not a granted ability at all:
Raging River's quotes are pile labels.

Decisive: **every one of those cards in the shipped pool is already supported**
through a channel that runs it. Granting a whole triggered or activated ability
to a set of objects is a CR 613 layer-6 capability the engine does not have —
`engine/auras.py` grants keywords and P/T, not abilities — so all 13 productions
would be `LoweringError`s. That buys parse coverage and nothing else, over 13
productions, against working code. Left, with its schedule entry intact, because
it is honestly still scheduled.

---

## Stable permanent IDs: the address exists, combat still doesn't use it

`player.battlefield[i]` was 137 sites. The reason is already in this document's
control-seam rule: **`Permanent` compares by value**, so `in` / `.remove()` /
`.index()` match an opponent's look-alike. Positional indices were the workaround
that grew *because* identity comparison is unsafe — and they are unstable, since
any permanent leaving renumbers every later slot.

`Permanent.permanent_id` is a monotonic counter, deliberately the same idiom as
`engine/continuous.py`'s `next_timestamp()`. Assigned at construction (so the AI
simulator's detached clones, the Debug Menu's raw-state injection and several
hundred test rigs are addressable with no call-site opt-in) and **re-stamped on
entering the battlefield**, because CR 400.7 makes a returning permanent a new
object. `_sync_control`'s list move deliberately does not re-stamp: a control
change is not a zone change.

`compare=False`, so `__eq__` is unchanged — folding identity into equality is a
separate behavioural change (the simulator compares detached clones by value)
and would have put the determinism gate at risk.

### Six live bugs, found by looking for the shape

`.battlefield.index()` and `.remove()` compare with `==`, so they find a
look-alike rather than the object. **Crumble** read its target's slot back with
`battlefield.index(artifact)` and destroyed the *first* of two equal Moxen.
Earthquake's Mountain sweep, Teferi-style phasing, Rag Man's bounce, the
sacrifice-for-mana path and Phantasmal Terrain's land index had the same shape.
All six fixed; **zero `.index()`/`.remove()` calls on a battlefield remain**, and
the guard bans them outright rather than ratcheting them.

### And one the renderer was doing

The canvas keyed cards by `seat-index`. One creature dying renumbered every
later slot, so the renderer pruned the whole right-hand side as departed and
re-added it as arrivals — replaying entrance animations and snapping anything
mid-flight. It re-keys by `pid` now, verified live: a permanent's item kept its
identity across a death, confirmed by a probe property surviving on the same JS
object.

### What is done, and what is explicitly not

Done: the ID and its seam (`permanent_by_id`, `find_permanent_by_id`,
`permanent_id_of`, and the two halves of the index bridge the wire still needs);
the cast→resolution holding, stamped at a new single choke point `_stack_push`
that the nine `stack.append(StackItem(...))` sites now route through; the
additive wire (`id` alongside `index`, resolved at **one** point at the top of
`do_action`, where **a stale id is a 404 rather than a fallback** — falling back
to the index would reintroduce the bug); seven client paths that hold an address
across an async gap.

**Not done: combat**, 51 sites across the four combat step modules plus
`ai_policy.py`, `web/combat_prompts.py` and `web/game_flow.py`. These are not
independent call sites — `combat_attackers`, `combat_blockers`, `combat_bands`,
`combat_band_blocks`, `combat_banding_damage`, `combat_multiblock_damage` and
the pile assignments are all **keyed** by battlefield index, as are the wire
fields carrying them and the canvas's arrows, and 115 test references read that
state directly. It converts as one unit or not at all, and re-keying those dicts
would change iteration order — the exact thing that would break the seeded
simulation. Left whole and ratcheted.

**The raw count barely moved: 139 by the new alias-aware measure.** That is the
honest number. What this change bought is that the stable address now *exists*,
is *reachable*, is *carried on the wire*, is *used by the client*, and is
*fenced* — plus seven real bugs. Converting combat is the rest of it.

The guard extends `tests/engine/test_control_reads.py` rather than duplicating
it, since that file already owns "the battlefield list has one reader". It
catches the aliased spelling (`bf = x.battlefield; bf[i]`) too — the majority
form in `mixins/stack/casting.py`, and without it the guard would have been one
line from bypassable.

Suite 4,403 → 4,437. AI simulation byte-identical at every stage.

---

## Combat: the maps follow the creatures now

The last piece of the index-instability thread. Combat is recorded as
battlefield **slots** — `combat_attackers` maps an attacker index to a defending
seat, `combat_blockers` a blocker index to the attackers it blocks — and a slot
is not a name. A creature dying in the first-strike damage step shifts every
later slot on its controller's battlefield down by one, so an attacker recorded
as index 3 silently becomes whatever index 3 is now.

### Which design, and why the other one was wrong

Two were on the table. Convert the eight maps to stable ids (with write-through
views, so the 73 test and 13 web references need not change), or remap the
indices when a permanent leaves.

The second was unavailable until the removal choke point existed — it would have
needed 41 hooks. With one transition it is one function, so it became the
cheaper option *and* had to be checked for correctness rather than chosen for
size.

The check that settled it: **every index has a resolvable seat.** An attacker
index is always the active player's — `declare_attackers` refuses any other
controller outright. A blocker index in `combat_blockers` comes from its own
outer key. The two damage-assignment maps (`combat_banding_damage`,
`combat_multiblock_damage`) record blocker slots with *no seat beside them*,
which is unambiguous in a duel and not in a CR 802 multi-defender combat — but it
is recoverable, because a blocker blocks an attacker and `combat_attackers` says
which player that attacker is attacking. `_combat_seat_of_blocker` does exactly
that, reading the pre-removal numbering before any map is rewritten.

Had that lookup not existed, ids would have been the only correct answer, since
a remap cannot shift an index whose battlefield it cannot name. Worth recording:
the under-specified seat in those two maps is a real latent gap, and the id
design would have removed it rather than recovering it.

### What the remap does

Two things happen to a recorded slot. If its own creature left, the entry is
**dropped** — a dead attacker is not attacking, and a blocker whose every
attacker has gone is not blocking. Otherwise it **shifts** down by the number of
departing creatures that sat ahead of it on the same battlefield. All eight maps,
including the Raging River pile labels.

### The AI simulation proved it safe and proved nothing else

Byte-identical before and after — which means the sim never reaches the case.
That is exactly the situation where a green suite is not evidence, so
`tests/regressions/test_combat_survives_renumbering.py` drives the renumbering
deliberately: two attackers where the lower-indexed one dies, a blocker dying
under a multi-block, an attacker dying under its blocker, and the pile labels.

**Verified by disabling the remap: five of the six fail.** The sixth is the
control — removal outside combat must not invent entries — and correctly passes
either way.

Suite 4,448 → 4,454.

### What is still index-keyed

The maps themselves, and the wire fields that carry them. This fixes the
*consistency* bug (a map pointing at the wrong creature) without making the
addresses stable, so an index held outside these maps across a removal is still
stale — the sites that mattered are already converted to ids. Moving combat onto
ids outright remains available and is now a smaller job than it was, because the
seat-resolution question above is answered and written down.

---

## Leaving the battlefield is one transition now

The battlefield list was rebuilt or shortened in **41 places**, in three
spellings: filter-by-identity, `pop` by index, and rebuild-from-a-survivors-list.

That is the shape `become_tapped` had at seventeen sites, and it has the same
consequence — anything that must happen when a permanent leaves has 41 places to
be wired into and 41 places to be forgotten. It is also the *root* of the
index-instability this document has been chasing: every combat map is keyed by
battlefield index, so a permanent leaving mid-combat renumbers every attacker
and blocker recorded after it, and there was nowhere to put the remap.

`Game.remove_from_battlefield(permanent)` and `remove_all_from_battlefield(perms)`
are that place. Where the permanent goes next stays the caller's business — a
graveyard, exile, a hand, a library, or the phased-out limbo an effect holds it
in have nothing in common; this does the one part they share. By **identity**,
never by value, for the reason `.remove()` is banned outright.

**41 → 3.** What is left is not removal:

* `_sync_control`'s pair of statements — the projection of a derived controller
  change (CR 613 layer 2). The permanent moves between two battlefields without
  leaving either zone, so firing the leave transition here would be wrong. It
  stays written open, with the reason on it.
* `remove_all_from_battlefield` itself.
* the Debug Menu's raw-state injection, which replaces a board wholesale.

### The sweeps said it backwards

Ten of the sites built a `survivors` list and assigned it. That names what
*stays*, when the interesting set is what *leaves* — and every one of them was
also open-coding the reverse-order walk (`for i in sorted(indices, reverse=True)`)
that kept indices valid while removing. Both go away together: collect the
departing, hand them over once. `_destroy_swept_permanents` lost its survivors
list entirely.

### Three things went wrong, and each is worth recording

**A scripted regex removed the `continue` statements that advanced a loop.**
Two state-based-action sweeps then called `_permanent_to_graveyard` without ever
removing the permanent, so `changed` stayed true and `check_state_based_actions`
span forever — the test suite hung rather than failed. Mechanical edits to
control flow need reading afterwards, not just testing.

**The seam guard caught reads that had been exempt "by shape."** Three
`for perm in player.battlefield` loops were tolerated because a rebuild-write
followed them, which the guard recognised as a zone write. With the rebuild gone
they were plain reads, and the guard said so. Correct on both counts, and a
nice demonstration that the exemption was keyed to the right thing.

**The new guard's first version flagged its own documentation** — a regex over
raw lines matched the seam docstring explaining why `.battlefield.remove()` is
banned. It walks the AST now. A guard that reports its own comments is one
people learn to skim.

Every rule is injection-tested with the restore in a `finally`: three spellings
of an open-coded rebuild and one stale exemption, four caught.

Suite 4,444 → 4,448. AI simulation byte-identical at every stage.

**This unblocks the combat conversion** rather than performing it. The combat
maps are still index-keyed; what changed is that there is now one function to
hang the remap on, instead of 41.

---

## The `Effect` union, and the target lookups outside combat

### A union member that was missing for its whole existence

`CombatRestriction` was defined *after* `__all__` at the bottom of the pre-split
`ast.py`, so the module never exported it and `ast.Effect` never named it —
while `lower_statement` dispatched on it like any other leaf. `BoardCount` and
`DamageUnlessPay` had been dropped from `__all__` the same way.

None of it broke anything, and that is the whole problem: the union is an
annotation, annotations are lazy, and nothing in the repo does `import *`. It
was a claim about the type system that was false with no consequence until
someone read it to answer "what is an `Effect`?".

Fixed, and `tests/engine/test_ast_effect_union.py` now checks membership **off
the dispatch** rather than off a second list — whatever `lower_statement`
matches with `isinstance` is by definition a statement, so the union has to name
it. `DamageRiders` is the one leaf deliberately excluded, and the test makes that
an entry with a reason rather than an omission: it is a *field* of `DealDamage`
("it can't be regenerated"), folded in by `_attach_riders`, never a step.

### Five Aura lookups and four damage lookups

`Game.chosen_permanent(seat, index, permanent_id)` is the read half of what
`_stack_push` writes: prefer the stable id, fall back to the index exactly as
before when the id no longer resolves. Additive, so it can only turn a wrong
answer into a right one.

Applied to the six sites in `engine/mixins/oracle_instructions.py` (the Aura
attachment paths and the shroud/protection legality check) and four in
`engine/handlers/damage.py`, including the multi-target list — where
`_stack_push` had already stamped a positionally-paired id list that nothing was
reading. **An Aura is the longest gap in the engine between choosing a target
and using it**: it waits for priority, for responses, and for everything above
it on the stack, which is exactly when a slot gets renumbered underneath the
index. `_apply_aura_effect` had to grow the parameter — it was the one path the
id was not threaded into.

`engine/mixins/oracle_instructions.py` is at zero positional reads;
`engine/handlers/damage.py` went 5 → 1 (the remaining one is Fireball's
cross-seat divided list, which needs ids in the `(seat, index)` tuple shape end
to end and belongs with the combat conversion).

### The regression test found the bug in the fix

`tests/regressions/test_target_survives_renumbering.py` drives the renumbering
deliberately — a distractor in a lower slot dies while the spell is on the stack
— and asserts the *right* permanent is hit. It caught the first version of the
damage fix: a `not 0 <= idx < len(battlefield)` bounds check sat in front of the
id lookup and returned "target is gone (CR 608.2b)" for a target that had merely
been **renumbered**, so the id resolution behind it could never run. Dead code
that looked like a fix.

Order matters and is now stated where it is easy to get wrong: resolve through
the seam *first*, refuse on `None`. A scan for the same shape across `engine/`
and `web/` found no other id lookup shadowed by a bounds check.

Suite 4,441 → 4,444, AI simulation identical.

---

## The two the pure move left

Both were found during the web-layer split and deferred on the grounds that a
behaviour change hidden inside a 5,000-line move is unreviewable. This is that
change, on its own, with a guard each.

### The no-cache list had fallen behind the page

`_no_cache_assets` matched a hand-written set of eight paths. `index.html` loads
ten first-party shell assets, so `/sfx.js`, `/music.js` and `/legality.js` were
browser-cacheable while their siblings were not — a stale-script bug waiting for
whoever edited one of the three without bumping its `?v=`.

**Adding the three names would have been the wrong fix**, because the hardcoded
list *is* the bug: it reproduces the same gap at the next script. The set is now
derived from `web/static/` — top-level `.html`/`.css`/`.js`, minus an explicit
`_VENDORED_ASSETS` exemption. Asking the filesystem cannot fall behind the
filesystem.

Two exclusions are deliberate rather than incidental, and both are asserted.
`anime.min.js` is third-party and version-pinned, so no-storing it would
re-download it for nothing. `images/`, `music/`, `sfx/` and `symbols/` are
megabytes that never change under an unchanged name — the no-store set is the
app *shell*, not the media, which is why the derivation is top-level only.

`tests/ui/test_static_assets.py` derives its expectation from `index.html` while
the middleware derives its set from the directory. The two are computed from
different places on purpose; the test is worth something only while that holds.
Checked against the old set: it fails on exactly the three names above.

### `_serialize_state` moved cards between players

Ante transfer (CR 407.2) and an AI's Raging River lock ran inside the function
that builds the JSON payload, so `GET /state` was not a read.

**Neither is deletable**, which is why this is a move. Both are lazy settlements
of a transition the game has already entered, and the human's next action is
gated on the result. Raging River's prompt sequencing runs defender-then-attacker,
so an AI on either side must lock its division *before* the prompt renders — settle
only on the action path and the prompt the human needs in order to act is waiting
on the human to act. The ante call covers the web layer's own (Lich-aware)
reading of who has lost, which the engine does not make: `_player_has_lost` falls
back to the 0-or-less-life rule, while `_maybe_award_ante` fires only from a
state-based action or a concession.

So the split is `build_state` (settle, then read) over `_serialize_state` (read).
The settling lives in `game_flow.settle_before_observation`, beside the rest of
the "game moving forward between HTTP requests" family. Every route calls
`build_state`, so behaviour is unchanged; what changed is that there is now a
function you can call to ask what the game looks like without altering the
answer.

**The invariant asserted is not "observation never mutates"** — that one is
false, and writing it down would have meant deleting a settle step the game
needs. It is *the function named for reading does not mutate*.

The session's own view fields (`cleanup_selected_indices`,
`untap_selected_indices`) are still normalized in the serializer, and that is the
boundary rather than an oversight: they belong to the `Session`, not the `Game`,
and clamping a viewer's pending selection to what is currently legal is part of
rendering the prompt. `_serialize_state` is a read *of the game*.

`tests/ui/test_state_is_a_read.py` drives the serializer against a game with
settling pending and asserts it comes back untouched, then asserts `build_state`
over the same state settles it. A test that only checked the payload would pass
either way — the way this split gets undone is not deleting `build_state`, it is
someone adding "just one more" settle to the serializer, exactly how the first
two got there. Verified by restoring the old behaviour: all three guards fail.

Suite 4,343 → 4,362.

---

## The aggregate nobody was measuring: hook reliance

Every entry in `engine/card_hooks.py` is individually defensible, and two guards
hold each one to its bar — `test_card_lines.py` checks a key names a real
printed line and still supplies a live instruction,
`test_front_end_safety.py` checks a production never quietly does less than the
hook it superseded. Neither looks at **how many there are**, and that is the
number the audit actually opened with. "Roughly one hand-written rule per two
cards" was item 1; the parser migration answered it for `@parse_rule` and then
put 89 cards' readings into a name-keyed registry, where the same arithmetic
applies and nothing counted it.

`scripts/hook_reliance.py` counts it. Three measures, per set and over the
deduped pool: **hooked cards** (at least one name-keyed entry, in any registry),
**hooked lines** (printed lines `CARD_LINE_INSTRUCTIONS` supplies rather than
the grammar — the same line denominator `GRAMMAR_COVERAGE.md` uses, so they read
together), and **entries per 100 supported cards**, the one that extrapolates.

### The denominator is supported cards, and that is not a detail

The first version counted every card in the pool, which is wrong in a way that
is *invisible today and only bites during the experiment the script exists for*.
All 388 cards are supported, so "cards" and "cards the engine plays" are the
same number and no reading of live data can tell them apart. They come apart the
moment a modern set lands at partial support: the denominator inflates with
cards no hook is carrying, the numerator does not follow, and reliance falls.

The arithmetic, for a 300-card set supported at 30% where 40 of those 90 needed
a hook to be supported at all:

| | Reading | Verdict |
| --- | --- | --- |
| Over supported cards | 135/478 = **28.2%** | rise — ceiling fails, correctly |
| Over all cards | 135/688 = **19.6%** | *fall* — ceiling passes |

A set that cost 40 new hand-written entries would have reported a five-point
architectural improvement, and the ratchet would have agreed. So every ratcheted
denominator is supported cards, and the measure *names* say so
(`hooked_cards_pct_of_supported`, `entries_per_100_supported_cards`) — an
implicit denominator is what went wrong, and a name is where that gets fixed.
Support rate is still reported beside them as pool reach: a real number, a
different question, never ratcheted.

Two asymmetries are deliberate. **Lines are restricted on both sides** — an
unsupported card's text is not text the engine reads. **Entries are not**: the
numerator counts every hand-written entry including those on cards that ended up
unsupported, because entries are what was written and supported cards are what
it bought, and a rule that bought nothing should still be charged for.

Pinning this needed a synthetic `Stats`, not a read of the pool, and the reason
is the point: with everything supported there is no live data that distinguishes
the two denominators, so a test over real cards would have passed either way.
`test_the_ratcheted_denominator_is_supported_cards` and
`test_unsupported_cards_stay_out_of_the_denominators` are the two halves — what
the arithmetic does, and what the counting does.

**Ceilings, not floors** — `scripts/hook_reliance_ratchet.json` is the mirror of
`grammar_ratchet.json`, and the direction is the whole point. There the hazard
is the general reader losing ground; here it is the special-case readers gaining
it. Adding a hook to a card whose text a production could have read fails
`tests/engine/test_hook_reliance.py`.

A ceiling has a failure mode a floor does not, and it is guarded explicitly. A
floor breaks loudly when its measurement breaks — a miscount reads as zero
coverage and fails. A ceiling breaks *silently*: a measurement that stops
finding registries reports 0% reliance and passes forever while the pile grows
underneath. So `test_the_measure_is_not_vacuous` asserts the machinery itself,
and registries are found by introspecting `engine.card_hooks` rather than from a
list — a registry added tomorrow is measured tomorrow, not when someone
remembers. The rule is "most keys name cards in the pool", which is also what
keeps `TRIGGER_HOOKS` (keyed by trigger condition) correctly out; a test pins
that too, because a threshold loose enough to sweep it in would inflate every
measure and the ceilings would be re-snapshotted around noise.

### What it says: 24.5%, and ARN is not the base sets

**95 of 388 cards carry a name-keyed entry, across 102 entries** — 91 of them
lines in `CARD_LINE_INSTRUCTIONS`, all live. Held at that rate the 26,113-card
release line needs about **6,900 hand-written entries**, which is item 1 of the
audit arriving at the same order of magnitude by a different route.

The per-set split is the more useful half, and it does not support reading 24.5%
as one number:

| Scope | Hooked cards | Hooked lines | Entries/100 supported |
| --- | ---: | ---: | ---: |
| LEA / LEB / 2ED / 3ED | 18.2–18.9% | 12.9–13.9% | 19.5–19.9 |
| ARN | **42.3%** | **29.9%** | **46.2** |
| ALL (deduped) | 24.5% | 17.5% | 26.3 |

(Every set is 100% supported today, so these read the same under either
denominator — which is exactly why the denominator had to be fixed before the
sixth set rather than after.)

The four base sets are near-identical reprint lists, so those rows are one data
point wearing four hats — and the ALL row, deduped, is that same point plus ARN.
**Arabian Nights is 2.3× the base rate.** That is consistent with the reading
the registry's own docstring gives (Shahrazad, Camouflage, Chaos Orb are one-offs
by design, not templates the engine failed to see), but two sets is not enough to
tell "designed-weird set" from "the rate rises as sets get stranger". Ingesting
one modern, heavily-templated set is the experiment that separates them, and it
now has an instrument to read: the numbers above are the control.

Measuring also turned up something no guard covered. `CARD_LINE_INSTRUCTIONS`
had a key-names-a-real-card check; the six smaller registries did not, and a
hook keyed on a misspelling is indistinguishable from a card nobody hooked — the
card silently loses the behaviour. `test_no_registry_key_names_a_card_outside_the_pool`
now covers all of them. (None were wrong; the check was.)

---

## The sixth set: what M21 answered

Core Set 2021, ingested to settle whether 24.5% is early-Magic weirdness or the
real rate. **A core set on purpose**: 3ED is a core set, so putting it next to a
modern *expansion* would confound era with product type — a difference could be
"cards got weirder" or "expansions are denser than base sets", with no way to
tell which. Core-to-core isolates the era.

### 285 cards, 105 supported, and zero of them needed a name

Not one M21 card required a `card_hooks.py` entry. Every card the engine plays
from a set printed 26 years after the pool is carried by a production that was
already there — zero new engine work, zero hooks. Pool reliance falls 24.5% →
19.5% when M21's supported cards are counted: the same 102 entries cover 488
playable cards instead of 388.

**That number is a lower bound, not a total.** The 180 unsupported M21 cards
have an unmeasured hook cost — nobody has tried to implement them, and what they
would need is exactly what this does not say. What it does say is that the
free-by-templating fraction of a modern set is real and large.

### The two sets fail differently, and that is the finding

| | Hooked cards | Lines parsed |
| --- | ---: | ---: |
| Base sets (LEA/LEB/2ED/3ED) | 18.2–18.9% | ~78% |
| ARN | **42.3%** | 63.9% |
| M21 | **0%** | **49.3%** |

M21 is the *hardest to parse* set in the pool and the *cheapest in hooks*. Those
are not in tension — they are different costs, and only one of them amortizes.
ARN's 42% is one-off cards: Shahrazad, Camouflage, Chaos Orb, each buying exactly
itself forever. M21's gap is missing *templates* — prowess, lifelink as a keyword
line, protection from a quality, hexproof, menace, flash, additional costs. One
production for prowess covers every prowess creature ever printed, in every set,
forever.

So the honest projection changed shape. The 26,113-card line does not need ~6,900
one-off entries at M21's rate; it needs productions for a bounded vocabulary of
templates, plus one-offs at whatever rate modern design actually prints them —
which M21 says is near zero. **The thing that stops this at 26,000 cards is
parser breadth, not hand-written rules per card**, and parser breadth is the cost
that gets cheaper per card as the pool grows. That is the opposite of what the
audit's item 1 feared, and it is the first evidence either way.

### The bug it found: one import, never once executed

`engine/mixins/stack/casting.py` reached for `from .oracle import
compile_card_oracle` — resolving to `engine.mixins.stack.oracle`, which does not
exist. A leftover from the stack decomposition, and `compile_card_oracle` was
already imported at module scope two lines of file away, so the statement was
both wrong and redundant.

It is reachable **only for an unsupported card**, and every card in the pool was
supported. So it had never run, in any test, ever — and the moment a set arrived
with 33 unsupported-triggered-ability cards it was 66 test failures from two
sweeps. One line. This is the class of bug a 388-card sample cannot expose at
any effort, which was the other half of what the ingest was for.

### `sets` and `measured`: what the manifest means

M21 is 37% supported, and two guards assert the manifest pool is 100% supported.
That is a real conflict and it forced a choice about what the registry means:
ship a set the app can play a third of, or do not measure a modern set at all.

Neither. `cards/manifest.json` now carries two lists. `sets` is the shipped pool
and keeps its guarantee — the web app offers those cards, and
`test_front_end_safety.py` / `test_card_format.py` still fail on a single
unsupported one. `measured` is a set ingested so its numbers can be read before
the support work is done: `manifest_set_paths(include_measured=True)` returns it,
`load_catalog` does not, and no player can put one of its cards in a deck. The
default on that flag is load-bearing — widening it is how an unsupported card
would reach a deck.

**Measured sets are reported and never ratcheted**, in both instruments, and the
reason differs by direction. `grammar_coverage`'s floors would have *failed*:
ingesting M21 drops ALL from 77.2% to 70.7% parsed without a production
changing, and a floor that fires on pool composition is a floor that gets
lowered without being read. `hook_reliance`'s ceilings would have *passed*
while measuring a set nobody has implemented. Both are the same mistake — a
ratchet answering a different question with the same number — so both aggregates
cover the shipped pool only, while the per-set rows show everything.

One casualty worth noting: `test_every_measured_set_is_in_the_baseline` in both
ratchet tests is now `test_every_ratcheted_scope_is_in_the_baseline`. "Measured"
had meant "measured by the script" and now names the unshipped sets, which are
precisely the scopes that test must *not* require.

Suite 4,362 → 4,369, every gate green.

---

## Standing invariants

Anything that weakens these is a regression regardless of what it enables:

1. **No silent wrongness.** A card may fail loudly as unsupported with a
   reason; it may never resolve as something other than what it says.
2. **The suite stays fast.** 4,341 tests in ~14s today, against a CI budget of
   35s. The budget catches a step change; the *baseline* recorded beside it in
   `ci.yml` is what catches creep, and it is the number to keep honest — it
   went 9s → 17s across four phases with the gate green the whole way. Raising
   the budget is a decision, not maintenance.

   **Open question, not yet a finding:** back-to-back runs on one clean local
   tree measured 43.98s and then 16.79s, and the first would have failed the
   35s budget on nothing but machine weather. The budget/baseline mechanism
   assumes a stable runner. Whether that assumption holds on the *CI* runner is
   unmeasured — read the percentages `ci.yml` prints across several runs before
   concluding anything, because "the budget is too tight" and "this dev box is
   noisy" have opposite fixes and the same symptom.
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
