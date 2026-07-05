# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A text-based **Magic: The Gathering rules engine** for the Limited Edition Alpha
(LEA) card set (290 cards in `lea_cards.json`), served behind a FastAPI web app
with a browser game UI. The engine is **registry-based**: card support grows by
adding small isolated entries, never by editing core control flow.

## Commands

All Python runs through the workspace venv (Windows / PowerShell):
`.\.venv\Scripts\python.exe` (referred to below as `python`).

```powershell
# Tests (pytest.ini sets testpaths=tests, addopts=-q)
python -m pytest                                  # full suite
python -m pytest -m "not slow"                    # skip the AI-simulation batch tests
python -m pytest tests/test_web_api.py -q         # one file
python -m pytest tests/test_lea_cards.py::test_name -q   # one test
python -m pytest tests/regressions -q             # in-game bug regressions (batched by fix round)

# Web server (browser game UI)
python -m uvicorn web.app:app --host 127.0.0.1 --port 8010   # then open http://127.0.0.1:8010/

# Engine scripts
python scripts/run_duel.py            # scripted deterministic duel, no server
python scripts/simulate_ai_games.py   # AI-vs-AI batch; deterministic per seed
python scripts/support_report.py      # per-category card-support coverage
```

To **launch and drive the running web app** (screenshots, scripted UI flow), use
the `/run-magic` skill at `.claude/skills/run-magic/` — it drives the browser
with `playwright-cli` (see the `playwright-cli` skill for the general command
reference). The board is canvas-rendered, so DOM selectors won't find cards; that
skill documents the working harness.

## Engine architecture

Full details in `engine/ARCHITECTURE.md`. The compile-and-dispatch pipeline:

```
lea_cards.json → card_loader.load_cards → CardDefinition (immutable)
  → oracle.compile_card_oracle (cached once per card per process) → OracleProgram
      { instructions, activated_abilities, triggered_abilities, static_lines }
  → Game mixins → EFFECT_HANDLERS[instruction.kind](game, instruction, context)  # O(1) dict dispatch
```

Extension points, each a small registered function — **adding a card means
adding entries, not editing dispatch**:

- `engine/parsing/` — `@parse_rule(order)` functions map a normalized oracle-text
  clause to `(OracleInstruction, effect_kind)`. Organized by category
  (damage, zones, destruction, combat, …). `engine/parsing/common.py` holds
  shared helpers (number words, color-word scans, duration parsing, the
  `parse_target_filter` noun-phrase parser) — reuse before writing a new regex.
- `engine/handlers/` — `@effect_handler(kind)` functions mutate game state for one
  instruction kind. Registered into `EFFECT_HANDLERS`, dispatched by dict lookup.
  `engine/handlers/_common.py` holds shared helpers (target resolution, filter
  matching, damage application).
- `engine/pt.py` — the single write API for power/toughness (`set_base_pt`,
  `add_pt_modifier`, `switch_pt`). All P/T mutation goes through here, never
  direct metadata pokes; see "P/T channels" in `engine/ARCHITECTURE.md`.
- `engine/replacements.py` — CR 614 "if X would happen, Y instead" interceptors,
  registered by event kind (`life_gain`, `damage_to_creature`, `would_die`).
- `engine/tokens.py` — `make_token_card(...)`, paired with the generic
  `create_token` instruction kind. A token-making card is one parse rule, never
  a bespoke handler.
- `engine/cast_restrictions.py` — text-keyed "cast this spell only during..."
  timing gates (an ordered predicate table; genuinely textual, not per-card).
- `engine/card_hooks.py` — name-keyed registries for truly bespoke behavior
  (spell-cast triggers, leave-battlefield effects, untap-step restrictions,
  draw-step modifiers, mana-production modifiers, cost-tax modifiers).
  **This is the only sanctioned place to reference a card by name**; do not put
  card names anywhere else in the engine (a few single-card exceptions are
  marked `# TODO(card-hooks)` — migrate them if a second card needs the shape).
- `engine/phases/` — one mixin per turn phase and per step within a phase
  (CR 500–514): beginning phase (untap/upkeep/draw steps), the two main phases,
  combat phase (its five steps), and the ending phase (end/cleanup steps). Each is
  composed onto `Game`; see `engine/phases/__init__.py` for the taxonomy. Put
  phase/step turn-based logic here.
- `engine/mixins/` — cross-cutting game flow *not* tied to a single phase:
  turn-structure navigation and priority (`phase_steps`), per-turn/pregame
  management (`turn_management`), stack/casting, state-based actions, effects,
  helpers. Consumes compiled programs; must never parse oracle text.

`engine/oracle.py` is the compiler (tokenize → classify lines as
keyword/triggered/activated/static → delegate effect clauses to `engine.parsing`).
`engine/oracle_types.py` holds shared dataclasses and imports nothing from the
engine, so it's safe to import anywhere.

### Parse-rule ordering (critical, non-obvious)

`@parse_rule` order determines precedence: **first match in ascending order
wins, so more specific patterns must use lower orders than generic ones**
(`"destroy all creatures"` before `"destroy target"`). All orders share one
global space; write new rules as `BAND_X + offset` using the named constants in
`engine/parsing/base.py`. A **duplicate order raises at import time**, so
collisions surface immediately. The current order bands (×100 of the historic
LEA numbering, opening ~99 free slots between former neighbors) are documented
in `engine/ARCHITECTURE.md` (1,000–6,500 upkeep … 113,000–117,000 global/static
buffs, lowest precedence).

### Adding support for a new card

Work top-down, stop at the first step that covers it (recipe in
`engine/ARCHITECTURE.md`):
1. Already covered? (`compile_card_oracle(card).supported`) → done.
   `python scripts/support_report.py --cards <set.json>` reports coverage for
   a whole set; unsupported creatures now name the specific unrecognized line.
2. New text, existing effect → add one `@parse_rule` returning an existing kind
   (reuse `engine/parsing/common.py` helpers where they fit).
3. New effect → invent an instruction kind (verb_object naming) + add a
   `@effect_handler`. Token creation → emit `create_token`. P/T changes → go
   through `engine/pt.py`. "Would happen, instead" effects → register in
   `engine/replacements.py`.
4. Bespoke behavior → register a hook in `card_hooks.py` keyed by name (or a
   `cast_restrictions.py` entry for a textual timing gate).
5. Add a focused test (see `tests/test_lea_cards.py` for per-card patterns).
   The comprehensive-cast sweep (`test_all_lea_cards_resolve_without_exception`)
   parametrizes dynamically over the live catalog, so new cards are swept
   automatically.

Cards whose text falls outside recognized patterns degrade gracefully: classified
unsupported with an explicit reason, never crashing simulation.

### Determinism

`run_ai_simulation` seeds the module-level RNG, so a given seed reproduces a run
exactly — required for the AI-behavior regression tests. Preserve this when
touching anything that consumes randomness.

## Web layer

`web/app.py` is the FastAPI app (`/api/...` routes + static UI in `web/static/`).
The card pool is `CARD_PATHS` (a list of set JSONs, today just `lea_cards.json`)
loaded once into `CARD_CATALOG` at process startup — adding a set means
appending its JSON path there. State lives in in-memory stores: `session_store.py`
(games; takes the loaded catalog, not a path — never re-reads the JSON per
session), `deck_store.py` (decks, incl. Moxfield import), `verification_store.py`.
Game actions funnel through one endpoint, `POST /api/sessions/{id}/action`,
dispatched by the `ActionKind` literal in `web/schemas.py`. Session `mode` must
be one of the literals `human_vs_ai`, `ai_vs_ai`, `human_vs_human`.

The board UI is **canvas-rendered** (`web/static/battlefield-canvas.js`).

## Card verification tracker

`CARD_VERIFICATION.md` / `card_verification.json` track which of the 290 cards
have been manually validated in-game. **Generated automatically** — results are
edited via the in-game Debug Menu, not by hand.
`tests/test_card_verification_regressions.py` guards against regressions in
verified cards.

## MTG rules questions

For rules/timing/layers/interaction questions, the `mtg-rules` skill
(`.agents/skills/mtg-rules/`) is authoritative; it consults `MagicCompRules.txt`
(the full Comprehensive Rules, in the repo root). Don't answer non-trivial
rulings from memory — cite that file.
