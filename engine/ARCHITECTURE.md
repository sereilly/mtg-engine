# Engine Architecture

The engine is built so that card support grows by **adding registry entries**,
never by editing core control flow. Every extension point is a small function
in a category module; dispatch is data-driven.

## Pipeline

```
lea_cards.json
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
| `engine/parsing/` | Declarative parse rules. Each `@parse_rule(order)` function maps a normalized oracle-text clause to `(OracleInstruction, effect_kind)`. First match in ascending order wins. |
| `engine/oracle.py` | The compiler: tokenizes oracle text, classifies lines (keyword / triggered / activated / static), delegates effect clauses to `engine.parsing`, and caches one `OracleProgram` per card. |
| `engine/handlers/` | Effect executors. Each `@effect_handler(kind)` function mutates game state for one instruction kind. Registered into `EFFECT_HANDLERS` and dispatched with a single dict lookup. |
| `engine/card_hooks.py` | Name-keyed registries for truly bespoke card behavior (cast triggers, spell-resolved triggers, counterspell riders). The only sanctioned place to reference a card by name. |
| `engine/phases/` | One mixin per turn phase and per step within a phase (CR 500–514): `beginning_phase` + `untap_step`/`upkeep_step`/`draw_step`, `precombat_main_phase`, `combat_phase` + its five step modules, `postcombat_main_phase`, `ending_phase` + `end_step`/`cleanup_step`. Each is composed onto `Game`. See `engine/phases/__init__.py` for the full taxonomy. |
| `engine/mixins/` | Cross-cutting game flow not tied to a single phase: turn-structure navigation and priority (`phase_steps`), per-turn/pregame management (`turn_management`), stack and casting, state-based actions, effects, helpers. Consumes compiled programs; should never parse oracle text itself. |

## Adding support for a new card

Work top-down; stop at the first step that covers the card.

1. **Already covered?** If the card's oracle text matches existing parse rules
   (run `compile_card_oracle(card)` and check `supported`), nothing to do.
2. **New text pattern, existing effect.** Add one `@parse_rule` to the matching
   category module in `engine/parsing/` that returns an existing instruction
   kind. Pick an `order` that places it correctly relative to overlapping
   patterns — more specific patterns must use lower orders than generic ones
   (e.g. `"destroy all creatures"` runs before `"destroy target"`).
3. **New effect.** Invent a new instruction kind (verb_object naming, e.g.
   `exile_target_creature_until_eot`), add the parse rule, then add one
   `@effect_handler` function in the matching `engine/handlers/` module.
4. **Card-specific behavior.** If the behavior can't be expressed generically,
   register a hook in `engine/card_hooks.py` keyed by card name. Don't put
   card names anywhere else in the engine.
5. **Tests.** Add a focused test per new rule/handler (see
   `tests/test_lea_cards.py` for per-card patterns).

## Ordering conventions for parse rules

Orders are spaced by 10 so new rules can slot between existing ones. Current
bands (ascending):

- 10–60: upkeep pay-or-else effects
- 70–130: named triggered-ability effects (Raging River … Dragon Whelp)
- 140–500: spells — zone changes, combat tricks, damage, library effects
- 510–630: recolor, mass/targeted destruction, pumps, discard
- 640–800: game-ending, life totals, tap/untap, prevention, regeneration
- 810–1000: activated abilities (pump, counters, tokens, misc)
- 1010–1050: mana production, counterspells
- 1060–1120: triggered-effect shorthands ("draw a card", "you lose the game")
- 1130–1170: global/static buffs (lowest precedence — most generic patterns)

A duplicate order raises at import time, so collisions surface immediately.

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
