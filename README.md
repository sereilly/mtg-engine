# MTG Text Rules Engine (LEA)

This project provides a text-based MTG simulation engine focused on the Limited Edition Alpha dataset in `lea_cards.json`. All 290 LEA cards are classified as supported and covered by per-card simulation tests.

## Engine Architecture

The engine is registry-based so the card pool can scale to thousands of cards by adding small, isolated entries — never by editing core control flow:

- `engine/parsing/` — declarative oracle-text parse rules (`@parse_rule(order)`), organized by category (damage, zones, destruction, …). First match in ascending order wins; a duplicate order fails at import.
- `engine/handlers/` — effect executors (`@effect_handler(kind)`), dispatched per instruction with a single O(1) dict lookup.
- `engine/card_hooks.py` — name-keyed hooks for truly bespoke card behavior (e.g. Power Sink's rider, Verduran Enchantress's cast trigger). The only place the engine references cards by name.
- `engine/oracle.py` — the compiler: tokenizes oracle text, classifies lines (keyword / triggered / activated / static), and caches one compiled `OracleProgram` per card for the life of the process.
- `engine/mixins/` — game flow: turn structure, priority, combat, the stack, upkeep, and state-based actions.

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
pytest
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
The app's generated Join URL now uses your local IP when accessed via localhost.

## Run Scripted Duel

```powershell
c:/Users/qwv48_66yef5i/Desktop/Magic/.venv/Scripts/python.exe scripts/run_duel.py
```

## AI Simulation

AI-vs-AI games are fully deterministic for a given seed (the simulator seeds every RNG the engine uses):

```powershell
c:/Users/qwv48_66yef5i/Desktop/Magic/.venv/Scripts/python.exe scripts/simulate_ai_games.py
```

## Support Coverage Report

```powershell
c:/Users/qwv48_66yef5i/Desktop/Magic/.venv/Scripts/python.exe scripts/support_report.py
```

## Notes

This is intentionally a foundational engine. The registry architecture means new effect patterns, instruction kinds, and per-card hooks can be added incrementally while preserving full card coverage and deterministic tests.

See `engine/ARCHITECTURE.md` for details.
