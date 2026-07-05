# Engine Architecture

The engine is built so that card support grows by **adding registry entries**,
never by editing core control flow. Every extension point is a small function
in a category module; dispatch is data-driven.

## Pipeline

```
cards/LEA_cards.json (+ any further set JSONs — web/app.py:CARD_PATHS)
   │  card_loader.load_cards
   ▼
CardDefinition (immutable)
   │  oracle.compile_card_oracle        ← cached: each card compiles once per process
   ▼
OracleProgram
   ├─ instructions          (primary effects, e.g. deal_damage)
   ├─ activated_abilities   (cost + instruction)
   ├─ triggered_abilities   (TriggerCondition + instruction)
   └─ static_lines          (keywords, static buffs)
   │  Game mixins (stack_casting → oracle_instructions)
   ▼
EFFECT_HANDLERS[instruction.kind](game, instruction, context)   ← O(1) dict dispatch
```

## Packages

| Package / module | Role |
| --- | --- |
| `engine/oracle_types.py` | Shared dataclasses (`OracleInstruction`, `OracleProgram`, …) and text helpers. No engine imports — safe to import from anywhere. |
| `engine/parsing/` | Declarative parse rules. Each `@parse_rule(order)` function maps a normalized oracle-text clause to `(OracleInstruction, effect_kind)`. First match in ascending order wins. `engine/parsing/common.py` hosts helpers shared across rules (number words, color-word scans, duration parsing, `parse_target_filter` for "target <noun phrase>" restrictions) — check there before adding a new one-off regex. |
| `engine/oracle.py` | The compiler: tokenizes oracle text, classifies lines (keyword / triggered / activated / static), delegates effect clauses to `engine.parsing`, and caches one `OracleProgram` per card. |
| `engine/handlers/` | Effect executors. Each `@effect_handler(kind)` function mutates game state for one instruction kind. Registered into `EFFECT_HANDLERS` and dispatched with a single dict lookup. `engine/handlers/_common.py` hosts shared helpers (`resolve_target_permanent`/`pick_target_permanent`, `permanent_matches_filter`, damage application). |
| `engine/pt.py` | The single write API for power/toughness channels (`set_base_pt`, `add_pt_modifier`, `switch_pt`, `clear_base_pt`) — see "P/T channels" below. All P/T mutation should go through here, never direct metadata pokes. |
| `engine/replacements.py` | CR 614 replacement-effect registry (`life_gain`, `damage_to_creature`, `would_die`, …). An interceptor may consume an event or adjust its amount before the default action runs; see "Replacement effects" below. |
| `engine/tokens.py` | `make_token_card(...)` — the one place that builds a token's `CardDefinition`. A token-creating card is a parse rule emitting a generic `create_token` instruction, never a bespoke handler. |
| `engine/cast_restrictions.py` | Text-keyed "Cast this spell only during..." timing gates — an ordered predicate table, since the restriction is the same for any card printed with that phrase (not name-specific). |
| `engine/card_hooks.py` | Name-keyed registries for truly bespoke card behavior: spell-cast triggers, spell-resolved triggers, counterspell riders, leave-battlefield effects, untap-step restrictions, draw-step modifiers, mana-production modifiers, cost-tax modifiers. The only sanctioned place to reference a card by name — a short list of `# TODO(card-hooks)` markers in the mixins flags the handful of remaining single-card bespoke sites not yet worth generalizing. |
| `engine/phases/` | One mixin per turn phase and per step within a phase (CR 500–514): `beginning_phase` + `untap_step`/`upkeep_step`/`draw_step`, `precombat_main_phase`, `combat_phase` + its five step modules, `postcombat_main_phase`, `ending_phase` + `end_step`/`cleanup_step`. Each is composed onto `Game`. See `engine/phases/__init__.py` for the full taxonomy. |
| `engine/mixins/` | Cross-cutting game flow not tied to a single phase: turn-structure navigation and priority (`phase_steps`), per-turn/pregame management (`turn_management`), stack and casting, state-based actions, effects, helpers. Consumes compiled programs; should never parse oracle text itself. |

## Adding support for a new card

Work top-down; stop at the first step that covers the card.

1. **Already covered?** If the card's oracle text matches existing parse rules
   (run `compile_card_oracle(card)` and check `supported`), nothing to do.
   `python scripts/support_report.py --cards <set.json>` reports coverage for
   an entire set at once, and the "creature text too complex" reason now
   names the specific unrecognized line.
2. **New text pattern, existing effect.** Add one `@parse_rule` to the matching
   category module in `engine/parsing/` that returns an existing instruction
   kind. Reuse `engine/parsing/common.py` helpers (number words, color words,
   durations, target-noun-phrase filters) instead of re-deriving them. Pick an
   `order` using the `BAND_*` constants in `engine/parsing/base.py` — more
   specific patterns must use lower orders than generic ones (e.g. `"destroy
   all creatures"` runs before `"destroy target"`).
3. **New effect.** Invent a new instruction kind (verb_object naming, e.g.
   `exile_target_creature_until_eot`), add the parse rule, then add one
   `@effect_handler` function in the matching `engine/handlers/` module.
   Creating tokens: emit `create_token` (payload: name/power/toughness/
   type_line/colors/keywords/count) — never write a bespoke token handler.
   Setting/modifying power or toughness: go through `engine/pt.py`, never
   metadata directly. "If X would happen, Y instead": register an interceptor
   in `engine/replacements.py` instead of an inline metadata check.
4. **Card-specific behavior.** If the behavior can't be expressed generically,
   register a hook in `engine/card_hooks.py` keyed by card name (or, for a
   genuinely textual timing restriction, an entry in
   `engine/cast_restrictions.py`). Don't put card names anywhere else in the
   engine.
5. **Tests.** Add a focused test per new rule/handler (see
   `tests/test_lea_cards.py` for per-card patterns). The comprehensive-cast
   sweep (`test_all_lea_cards_resolve_without_exception`) is driven by
   `pytest_generate_tests` over the live catalog, so a new set's cards are
   swept automatically — only add to that file's `SWEEP_EXCLUSIONS` if a card
   needs setup the generic body can't provide.

## P/T channels (scoped CR 613)

Power/toughness is computed by `Permanent.effective_power`/`effective_toughness`
(engine/models.py) from a fixed set of metadata channels, applied in CR-613
sublayer order: 7d switch (`pt_switched`) → 7b set (`absolute_power[_until_eot]`,
until-eot wins) → 7c additive (`power_bonus`, `static_buff_power`,
`attacking_buff_power`). There is no general timestamp/dependency-ordered
layer system — last-write-wins on a 7b metadata key already gives the correct
order for stack-resolved effects, and 7c is commutative addition, which covers
every LEA/Arabian-Nights-era interaction. All writes go through `engine/pt.py`;
characteristic-defining P/T (layer 7a) is registry-driven via
`engine.mixins.permanent_state.DYNAMIC_PT` (instruction kind → count
function) — a new CDA card is one table entry, not a new branch.

## Replacement effects

"If X would happen, Y instead" effects (Lich, Disintegrate's exile-instead,
Jade Monolith's redirect, …) are interceptors registered in
`engine/replacements.py` by event kind (`life_gain`, `damage_to_creature`,
`would_die`). `apply_replacements(game, kind, payload)` runs the kind's
interceptors in registration order; one may consume the event (skip the
default action) or adjust `payload["amount"]` and let the chain continue.
Interceptors self-select from game/permanent state, so the registry stays
name-free.

## Ordering conventions for parse rules

All orders share one global space (cross-category precedence is intentional:
"destroy all creatures" must beat "destroy target" regardless of which file
each lives in). Historic orders were multiplied by 100, opening ~99 free slots
between former neighbors; new rules should be written as `BAND_X + offset`
using the named band constants in `engine/parsing/base.py`. Current bands
(ascending):

- 1,000–6,500: upkeep pay-or-else effects (`BAND_UPKEEP`)
- 7,000–13,000: named triggered-ability effects (`BAND_NAMED_TRIGGERS`)
- 14,000–50,000: spells — zone changes, combat tricks, damage, library effects (`BAND_SPELLS`)
- 51,000–63,000: recolor, mass/targeted destruction, pumps, discard (`BAND_DESTRUCTION`)
- 64,000–80,000: game-ending, life totals, tap/untap, prevention, regeneration (`BAND_LIFE_TAP_PREVENT`)
- 81,000–100,000: activated abilities (pump, counters, tokens, misc) (`BAND_ACTIVATED`)
- 101,000–105,000: mana production, counterspells (`BAND_MANA_COUNTER`)
- 106,000–112,000: triggered-effect shorthands ("draw a card", "you lose the game") (`BAND_TRIGGER_SHORTHANDS`)
- 113,000–117,000: global/static buffs (lowest precedence — most generic patterns) (`BAND_GLOBAL_STATIC`)

A duplicate order raises at import time, so collisions surface immediately;
`tests/test_parsing_common.py` additionally asserts the registry is strictly
ordered.

## Scale properties

- **Compile once:** `compile_card_oracle` is cached unbounded; parsing cost is
  paid once per distinct card per process, regardless of how many games run.
- **O(1) execution:** instruction dispatch is a dict lookup. Adding the
  1000th effect kind does not slow down the 1st.
- **Precompiled regexes:** trigger tables and parse rules compile their
  patterns at import. Python's internal regex cache (512 entries) is never
  relied on.
- **Deterministic simulations:** `run_ai_simulation` seeds the module-level
  RNG, so a given seed reproduces a run exactly — required for regression
  tests over AI behavior.
