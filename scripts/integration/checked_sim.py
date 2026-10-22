"""Run scripts/simulate_ai_games.py with engine.fast_paths.CHECKING on (cwd = tree).

python checked_sim.py <counts.json> <simulate_ai_games args...>
Writes the CHECKED counts to <counts.json> when the run ends (exit code kept).
"""
import json
import os
import runpy
import sys

sys.path.insert(0, os.getcwd())
from engine import fast_paths  # noqa: E402

out = sys.argv[1]
sys.argv = ["scripts/simulate_ai_games.py", *sys.argv[2:]]
fast_paths.CHECKING = True
code = 0
try:
    runpy.run_path("scripts/simulate_ai_games.py", run_name="__main__")
except SystemExit as exc:
    code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
finally:
    with open(out, "w", encoding="utf-8") as handle:
        json.dump({"checked": fast_paths.CHECKED, "exit": code}, handle, indent=1)
sys.exit(code)
