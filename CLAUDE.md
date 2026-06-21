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
python -m pytest tests/test_web_api.py -q         # one file
python -m pytest tests/test_lea_cards.py::test_name -q   # one test
python find_untested.py                           # LEA cards lacking a dedicated functional test

# Web server (browser game UI)
python -m uvicorn web.app:app --host 127.0.0.1 --port 8010   # then open http://127.0.0.1:8010/

# Engine scripts
python scripts/run_duel.py            # scripted deterministic duel, no server
python scripts/simulate_ai_games.py   # AI-vs-AI batch; deterministic per seed
python scripts/support_report.py      # per-category card-support coverage
```

To **launch and drive the running web app** (screenshots, scripted UI flow via a
headless Playwright browser driver), use the `/run-magic` skill at
`.claude/skills/run-magic/` — the board is canvas-rendered, so DOM selectors
won't find cards; that skill documents the working harness.

## Engine architecture

Full details in `engine/ARCHITECTURE.md`. The compile-and-dispatch pipeline:

```
lea_cards.json → card_loader.load_cards → CardDefinition (immutable)
  → oracle.compile_card_oracle (cached once per card per process) → OracleProgram
      { instructions, activated_abilities, triggered_abilities, static_lines }
  → Game mixins → EFFECT_HANDLERS[instruction.kind](game, instruction, context)  # O(1) dict dispatch
```

Four extension points, each a small registered function — **adding a card means
adding entries, not editing dispatch**:

- `engine/parsing/` — `@parse_rule(order)` functions map a normalized oracle-text
  clause to `(OracleInstruction, effect_kind)`. Organized by category
  (damage, zones, destruction, combat, …).
- `engine/handlers/` — `@effect_handler(kind)` functions mutate game state for one
  instruction kind. Registered into `EFFECT_HANDLERS`, dispatched by dict lookup.
- `engine/card_hooks.py` — name-keyed registries for truly bespoke behavior.
  **This is the only sanctioned place to reference a card by name**; do not put
  card names anywhere else in the engine.
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
(`"destroy all creatures"` before `"destroy target"`). Orders are spaced by 10 to
slot new rules between existing ones. A **duplicate order raises at import time**,
so collisions surface immediately. The current order bands are documented in
`engine/ARCHITECTURE.md` (10–60 upkeep … 1130–1170 global/static buffs, lowest
precedence).

### Adding support for a new card

Work top-down, stop at the first step that covers it (recipe in
`engine/ARCHITECTURE.md`):
1. Already covered? (`compile_card_oracle(card).supported`) → done.
2. New text, existing effect → add one `@parse_rule` returning an existing kind.
3. New effect → invent an instruction kind (verb_object naming) + add a
   `@effect_handler`.
4. Bespoke behavior → register a hook in `card_hooks.py` keyed by name.
5. Add a focused test (see `tests/test_lea_cards.py` for per-card patterns).

Cards whose text falls outside recognized patterns degrade gracefully: classified
unsupported with an explicit reason, never crashing simulation.

### Determinism

`run_ai_simulation` seeds the module-level RNG, so a given seed reproduces a run
exactly — required for the AI-behavior regression tests. Preserve this when
touching anything that consumes randomness.

## Web layer

`web/app.py` is the FastAPI app (`/api/...` routes + static UI in `web/static/`).
State lives in in-memory stores: `session_store.py` (games), `deck_store.py`
(decks, incl. Moxfield import), `verification_store.py`. Game actions funnel
through one endpoint, `POST /api/sessions/{id}/action`, dispatched by the
`ActionKind` literal in `web/schemas.py`. Session `mode` must be one of the
literals `human_vs_ai`, `ai_vs_ai`, `human_vs_human`.

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
