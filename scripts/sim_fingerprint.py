"""Seeded-simulation differential — "did this refactor change what the engine does?"

`oracle_diff.py`'s twin one layer down. That script stores every card's
compiled program, so it answers for the compiler and is blind to everything
the program is *run* by: the handlers, the mixins, the AI, the turn. A change
that is meant to move code without changing behaviour (a module split, a
helper extracted, an import rerouted) owes a reading of that half too, and the
test suite is the wrong instrument for it — it says whether the behaviours it
names still hold, not whether anything else moved.

A seeded AI-vs-AI run is deterministic to the byte (CLAUDE.md, "Determinism"),
so its interaction log is a fingerprint of everything a game exercised: every
cast, target, prompt answer, combat assignment and AI decision in a few
thousand lines. This script records the log and the summary of a fixed list of
seeded runs across the pool, and compares a later tree's against them.

Usage::

    python scripts/sim_fingerprint.py snapshot    # before the change
    ... edit ...
    python scripts/sim_fingerprint.py compare     # exit 1 if any run moved

The run list is fixed and spans the pool by era, so the two readings are of
the same games; there is no ``--set`` for the reason `oracle_diff` has none.
A compare that differs prints the first lines where each moved run diverges.
**A diff is not always a defect** — a change that is meant to alter play
(a new AI weight, a rules fix) moves the runs it reaches, and the reading is
then "these games, at this line", which is what the reviewer needs. For a
change meant to move nothing, the answer must be 0 moved.
"""

from __future__ import annotations

import argparse
import difflib
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SNAPSHOT = REPO_ROOT / ".sim_fingerprint"

#: (set code, seed, games). One set per era of the pool, so the handlers a
#: refactor can reach are reached by some run: the base sets, the first
#: expansions, the Ice Age and Mirage blocks, Tempest, Urza's, Masques,
#: Invasion, Odyssey and the core set.
RUNS = (
    ("LEA", 7, 3),
    ("ARN", 7, 3),
    ("LEG", 7, 3),
    ("ICE", 7, 3),
    ("MIR", 7, 3),
    ("TMP", 7, 3),
    ("USG", 7, 3),
    ("MMQ", 7, 3),
    ("INV", 7, 3),
    ("ODY", 7, 3),
    ("TOR", 7, 3),
    ("M21", 7, 3),
)

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover - non-tty streams
        pass


def run_name(code: str, seed: int, games: int) -> str:
    return f"{code}_s{seed}_g{games}"


def run_one(code: str, seed: int, games: int, out_dir: Path) -> dict:
    """One seeded run, its log written beside the summary it printed.

    The printed summary carries the log's path, which is the one line that
    differs between two identical runs, so it is dropped.
    """
    name = run_name(code, seed, games)
    log_path = out_dir / f"{name}.log"
    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "simulate_ai_games.py"),
            "--set", code,
            "--seed", str(seed),
            "--games", str(games),
            "--log-file", str(log_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    summary = [
        line
        for line in completed.stdout.splitlines()
        if not line.startswith("Log file:")
    ]
    (out_dir / f"{name}.summary").write_text(
        "\n".join([f"exit={completed.returncode}", *summary]) + "\n",
        encoding="utf-8",
    )
    if not log_path.exists():
        log_path.write_text(completed.stderr, encoding="utf-8")
    return {"name": name, "exit": completed.returncode}


def run_all(out_dir: Path, workers: int) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda run: run_one(*run, out_dir), RUNS))


def _read(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def compare_dirs(old: Path, new: Path) -> list[tuple[str, list[str]]]:
    """Each run whose summary or log moved, with the first lines of its diff."""
    moved = []
    for code, seed, games in RUNS:
        name = run_name(code, seed, games)
        diff: list[str] = []
        for suffix in ("summary", "log"):
            before = _read(old / f"{name}.{suffix}")
            after = _read(new / f"{name}.{suffix}")
            if before != after:
                diff.extend(
                    difflib.unified_diff(
                        before, after,
                        f"before/{name}.{suffix}", f"after/{name}.{suffix}",
                        n=2, lineterm="",
                    )
                )
        if diff:
            moved.append((name, diff[:40]))
    return moved


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("snapshot", "compare"))
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=DEFAULT_SNAPSHOT,
        help=f"snapshot directory (default {DEFAULT_SNAPSHOT.relative_to(REPO_ROOT)})",
    )
    parser.add_argument(
        "--workers", type=int, default=4, help="runs at once (default 4)"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "snapshot":
        results = run_all(args.snapshot, args.workers)
        failed = [r["name"] for r in results if r["exit"] != 0]
        print(f"snapshot: {len(results)} seeded runs -> {args.snapshot}")
        if failed:
            print(f"note: {len(failed)} run(s) exited non-zero: {failed}")
        return 0
    if not args.snapshot.exists():
        print(f"no snapshot at {args.snapshot}; run `snapshot` first")
        return 2
    with tempfile.TemporaryDirectory(prefix="sim_fingerprint_") as scratch:
        run_all(Path(scratch), args.workers)
        moved = compare_dirs(args.snapshot, Path(scratch))
    print(f"compare: {len(moved)} moved of {len(RUNS)} seeded runs")
    for name, diff in moved:
        print(f"\n== {name}")
        print("\n".join(diff))
    return 1 if moved else 0


if __name__ == "__main__":
    sys.exit(main())
