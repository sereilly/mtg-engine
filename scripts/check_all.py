"""Run every CI guard check locally, in CI's order, with one command.

The canonical list of gates lived only in ``.github/workflows/ci.yml``, and
SET_PLAYBOOK.md's promotion phase literally instructed the reader to open the
YAML to reconstruct it — so every round retyped the invocations, and the
integration loop (which runs them between every merge of a wave) retyped them
twelve times per wave. This script is those steps; the guard test
(``tests/engine/test_check_all.py``) extracts the ``--check`` run lines from
ci.yml and fails if the two lists drift, so the YAML stays authoritative.

``--freshness`` additionally regenerates the trackers whose staleness the
``--check`` guards do not see and fails if that dirties the tree — off by
default because a mid-round tree is legitimately dirty.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The guard checks, in ci.yml's order. The guard test holds this equal to the
#: workflow's ``--check`` run lines — edit ci.yml first, then mirror it here.
COMMANDS: list[tuple[str, list[str]]] = [
    ("Parse coverage", ["scripts/parse_coverage.py", "--check"]),
    ("Grammar coverage ratchet", ["scripts/grammar_coverage.py", "--check"]),
    ("Hook reliance ratchet", ["scripts/hook_reliance.py", "--check"]),
    ("Rules-citation coverage", ["scripts/rules_progress.py", "--check"]),
    ("Behaviour classes", ["scripts/behaviour_classes.py", "--check"]),
    ("Vocabulary catalogs", ["scripts/fetch_vocabulary.py", "--check"]),
]

#: What ``--freshness`` regenerates before asking git whether anything moved —
#: the trackers whose staleness no ``--check`` sees (ci.yml's freshness step).
FRESHNESS_COMMANDS: list[tuple[str, list[str]]] = [
    ("Grammar coverage report", ["scripts/grammar_coverage.py"]),
    ("Rules progress report", ["scripts/rules_progress.py"]),
    ("Behaviour classes report", ["scripts/behaviour_classes.py"]),
    ("Parse coverage report", ["scripts/parse_coverage.py"]),
    ("Hook reliance report", ["scripts/hook_reliance.py"]),
    ("Set progress report", ["scripts/set_progress.py"]),
    (
        "Verification markdown",
        ["-c", "from web.verification_report import write_verification_markdown as w; w()"],
    ),
]


def _run(name: str, argv: list[str]) -> tuple[str, float, subprocess.CompletedProcess]:
    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, *argv],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return name, time.monotonic() - started, result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run every CI guard check (the --check scripts, in ci.yml's "
            "order) and summarize. Exit 1 if any fails."
        )
    )
    parser.add_argument(
        "--freshness",
        action="store_true",
        help=(
            "Also regenerate the committed trackers and fail if that dirties "
            "the tree (ci.yml's freshness step). Off by default: a mid-round "
            "tree is legitimately dirty, and this half only means anything "
            "on a tree you are about to commit or merge."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    rows: list[tuple[str, float, subprocess.CompletedProcess]] = []
    for name, cmd in COMMANDS:
        rows.append(_run(name, cmd))
    if args.freshness:
        for name, cmd in FRESHNESS_COMMANDS:
            rows.append(_run(name, cmd))

    failed = []
    for name, elapsed, result in rows:
        status = "ok" if result.returncode == 0 else f"FAIL ({result.returncode})"
        print(f"  {status:>9}  {elapsed:6.1f}s  {name}")
        if result.returncode != 0:
            failed.append((name, result))

    if args.freshness and not failed:
        diff = subprocess.run(
            ["git", "diff", "--quiet"], cwd=REPO_ROOT, capture_output=True
        )
        if diff.returncode != 0:
            stat = subprocess.run(
                ["git", "--no-pager", "diff", "--stat"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )
            print()
            print("FAIL: regenerating the trackers dirtied the tree — commit the result:")
            print(stat.stdout)
            return 1
        print(f"  {'ok':>9}          generated trackers are up to date")

    if failed:
        for name, result in failed:
            print()
            print(f"--- {name} ---")
            output = (result.stdout or "") + (result.stderr or "")
            print(output.strip()[-4000:])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
