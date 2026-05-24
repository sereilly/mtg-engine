# MTG Basic Text Rules Engine (LEA)

This project provides a basic text-based MTG simulation engine focused on the Limited Edition Alpha dataset in `lea_cards.json`.

## Scope

- Loads and normalizes all cards from `lea_cards.json`
- Classifies every card as either:
  - supported in MVP simulation, or
  - unsupported with an explicit reason
- Runs one simulation-oriented unit test case for every LEA card

## MVP Rules Support

Supported examples:
- Land plays (battlefield placement)
- Simple creatures and keyword-only creatures
- Basic spell patterns:
  - draw cards (for fixed numeric counts)
  - fixed direct damage
  - counter target spell (with basic stack handling)
  - destroy target permanent (simple type/color matching)
  - destroy all lands
  - simple life gain patterns
  - static creature buffs like "Black creatures get +1/+1"

Unsupported examples (graceful fallback):
- Banding and similarly complex legacy mechanics
- Complex replacement/timing chains
- Ante/copy/exchange style effects

Unsupported cards are still fully covered in tests and never crash simulation.

## Run Tests

With the workspace virtual environment activated:

```powershell
pytest
```

## Run Scripted Duel

```powershell
c:/Users/qwv48_66yef5i/Desktop/Magic/.venv/Scripts/python.exe scripts/run_duel.py
```

## Support Coverage Report

```powershell
c:/Users/qwv48_66yef5i/Desktop/Magic/.venv/Scripts/python.exe scripts/support_report.py
```

## Notes

This is intentionally a foundational engine. It is designed so additional effect handlers can be added incrementally while preserving full card coverage and deterministic tests.
