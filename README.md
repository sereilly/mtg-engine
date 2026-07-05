# MTG Simulacrum

A text-based Magic: The Gathering rules engine with a browser game UI (FastAPI + canvas board). The card pool lives in `cards/`, one JSON per set:

- **Limited Edition Alpha** (`cards/LEA_cards.json`) — all 290 cards supported and covered by per-card simulation tests
- **Arabian Nights** (`cards/ARN_cards.json`) — all 78 cards supported

Games can be played human vs AI, AI vs AI, human vs human over LAN, or 3–4 player free-for-all.

## Engine Architecture

The engine is registry-based so the card pool can scale to thousands of cards by adding small, isolated entries — never by editing core control flow:

- `engine/parsing/` — declarative oracle-text parse rules (`@parse_rule(order)`), organized by category (damage, zones, destruction, …). First match in ascending order wins; a duplicate order fails at import.
- `engine/handlers/` — effect executors (`@effect_handler(kind)`), dispatched per instruction with a single O(1) dict lookup.
- `engine/card_hooks.py` — name-keyed hooks for truly bespoke card behavior (e.g. Power Sink's rider, Verduran Enchantress's cast trigger). The only place the engine references cards by name.
- `engine/oracle.py` — the compiler: tokenizes oracle text, classifies lines (keyword / triggered / activated / static), and caches one compiled `OracleProgram` per card for the life of the process.
- `engine/phases/` — one mixin per turn phase and step (CR 500–514).
- `engine/mixins/` — cross-cutting game flow: turn-structure navigation, priority, the stack, and state-based actions.

To add support for a new card: add a parse rule that emits an instruction kind, add an effect handler for that kind if it is new, and add a test. See `engine/ARCHITECTURE.md` for the full pipeline, the rule-ordering conventions, and the step-by-step recipe.

## Rules Support

Supported patterns include:
- Land plays, mana production, and cost enforcement (optional)
- Creatures: keywords (flying, trample, first strike, banding, landwalk, protection, …), static buffs, dynamic power/toughness
- Activated and triggered abilities (costs, upkeep pay-or-else effects, enter/dies/attack triggers)
- Spells: damage (fixed, X, mass), draw/discard, destruction (targeted and mass), counterspells, bounce, exile, reanimation, auras, pumps, prevention shields, extra turns, ante effects, and game-ending effects

Cards whose text falls outside the recognized patterns degrade gracefully: they are classified unsupported with an explicit reason and never crash simulation.

## Run Tests

With the workspace virtual environment activated:

```powershell
pytest                    # full suite
pytest -m "not slow"      # skip the AI-simulation batch tests
```

## Start the Server

From the workspace root, start the web app with the project virtual environment:

```powershell
.\.venv\Scripts\python.exe -m uvicorn web.app:app --host 0.0.0.0 --port 8010
```

Or to host on ipv6 run:

```powershell
.\.venv\Scripts\python.exe -m uvicorn web.app:app --host :: --port 8010
```

Then open `http://127.0.0.1:8010/` on the host machine.

To join from another computer on the same network, open `http://<your-local-ip>:8010/`.
The app's generated Join URL uses your local IP when accessed via localhost.

## Run Scripted Duel

```powershell
.\.venv\Scripts\python.exe scripts/run_duel.py
```

## AI Simulation

AI-vs-AI games are fully deterministic for a given seed (the simulator seeds every RNG the engine uses):

```powershell
.\.venv\Scripts\python.exe scripts/simulate_ai_games.py
```

## Support Coverage Report

```powershell
.\.venv\Scripts\python.exe scripts/support_report.py                                # LEA (default)
.\.venv\Scripts\python.exe scripts/support_report.py --cards cards/ARN_cards.json   # any set JSON
```

## Card Verification

`CARD_VERIFICATION.md` tracks which cards have been manually validated in the running game (currently all 290 LEA cards, all passing). Results are recorded via the in-game Debug Menu, and `tests/test_card_verification_regressions.py` guards verified cards against regressions.

## Notes

This is intentionally a foundational engine. The registry architecture means new effect patterns, instruction kinds, and per-card hooks can be added incrementally while preserving full card coverage and deterministic tests — adding a set is one JSON file in `cards/` plus registry entries for any new text patterns.

See `engine/ARCHITECTURE.md` for details.
