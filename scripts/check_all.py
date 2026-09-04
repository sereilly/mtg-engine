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

``--caps`` reports how much room the size guards have left. It fails nothing:
the guard in ``tests/engine/test_grammar_layering.py`` is what fails, and it
fails only once a module is already over. The number worth knowing *before* a
set starts is how many modules are one round away from that, because a cap
crossed at integration is the expensive kind — it fires on nobody's branch,
with two groups' additions summed, and the integrator has to find the seam with
none of the work in hand. Mirage crossed five that way across two waves.
Derived on every run, so it cannot go stale the way a written-down list would.
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
#: The five tracker scripts are absent on purpose: their ``--check`` (run in
#: COMMANDS above) already fails on a stale report from the analysis in hand.
FRESHNESS_COMMANDS: list[tuple[str, list[str]]] = [
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


#: How close to a cap counts as "one round away". Not tuned: it is roughly what
#: a single group added to a single module in Mirage's waves, so a module inside
#: it is one group's work from breaching.
CAP_MARGIN = 30

#: The size guards, as (label, cap, root, glob). A cap written here and in the
#: guard is a second copy of one number, which is the failure class this repo
#: hunts — so ``tests/engine/test_check_all.py`` reads both and fails if they
#: disagree.
SIZE_GUARDS: list[tuple[str, int, str, str]] = [
    ("grammar modules", 1000, "engine/grammar", "**/*.py"),
    ("per-set test files", 2600, "tests/sets", "test_*.py"),
]


def report_caps() -> None:
    """Print every module within :data:`CAP_MARGIN` of its size guard."""
    print()
    print("Size-guard headroom (advisory — nothing here fails):")
    for label, cap, root, pattern in SIZE_GUARDS:
        base = REPO_ROOT / root
        rows = []
        for path in sorted(base.glob(pattern)):
            count = len(path.read_text(encoding="utf-8").splitlines())
            if count > cap - CAP_MARGIN:
                rows.append((count, path.relative_to(REPO_ROOT).as_posix()))
        rows.sort(reverse=True)
        over = [r for r in rows if r[0] > cap]
        print(f"  {label} (cap {cap:,}): {len(rows)} within {CAP_MARGIN}, "
              f"{len(over)} already over")
        for count, name in rows:
            flag = "OVER" if count > cap else f"{cap - count:>4} left"
            print(f"    {count:5,}  {flag}  {name}")


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
    parser.add_argument(
        "--caps",
        action="store_true",
        help=(
            "Also report which modules are within a round's work of a size "
            "guard. Advisory: it fails nothing, and it exists so a set can be "
            "briefed knowing where the next integration-time split will land."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.caps:
        report_caps()

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
