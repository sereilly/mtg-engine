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

    python scripts/sim_fingerprint.py snapshot --rev main   # after the fact

**A snapshot can be of another commit** (``--rev``). Three Darksteel groups
had edited before they snapshotted and rebuilt their base by hand from a
``git archive`` export. ``snapshot --rev <commit>`` plays the same twelve runs
in a throwaway detached worktree of that commit inside ``.worktrees/`` —
its own engine and its own ``simulate_ai_games.py`` — writes them into the
snapshot directory named, and removes the worktree; ``compare`` then reads
that base against the working tree as usual. The commit a snapshot was taken
of is recorded beside it (``SOURCE``) and printed by ``compare``.

The run list is fixed and spans the pool by era, so the two readings are of
the same games; there is no ``--set`` for the reason `oracle_diff` has none.
A compare that differs prints the first lines where each moved run diverges,
how many places it diverged in, and writes each moved run's whole diff and its
new log under ``<snapshot>/compare/`` (``<run>.diff``, ``<run>.after.log``):
the first hunk is rarely the decision that moved, and reading the rest used to
mean re-running the game.
**A diff is not always a defect** — a change that is meant to alter play
(a new AI weight, a rules fix) moves the runs it reaches, and the reading is
then "these games, at this line", which is what the reviewer needs. For a
change meant to move nothing, the answer must be 0 moved.
"""

from __future__ import annotations

import argparse
import difflib
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SNAPSHOT = REPO_ROOT / ".sim_fingerprint"
#: The file beside a snapshot's runs naming what they were played on.
SOURCE_FILE = "SOURCE"

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


def run_one(code: str, seed: int, games: int, out_dir: Path, root: Path = REPO_ROOT) -> dict:
    """One seeded run, its log written beside the summary it printed.

    The printed summary carries the log's path, which is the one line that
    differs between two identical runs, so it is dropped. *root* is the
    checkout whose simulator (and so whose engine) plays the run.
    """
    name = run_name(code, seed, games)
    log_path = out_dir / f"{name}.log"
    completed = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "simulate_ai_games.py"),
            "--set", code,
            "--seed", str(seed),
            "--games", str(games),
            "--log-file", str(log_path),
        ],
        cwd=root,
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


def run_all(out_dir: Path, workers: int, root: Path = REPO_ROOT) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda run: run_one(*run, out_dir, root), RUNS))


def _git(*args: str, cwd: Path = REPO_ROOT) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()


def resolve_rev(rev: str) -> str:
    """The full commit hash *rev* names, or ``ValueError``."""
    try:
        return _git("rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    except subprocess.CalledProcessError:
        raise ValueError(f"{rev!r} names no commit") from None


@contextmanager
def rev_worktree(commit: str):
    """A detached worktree of *commit*, removed on the way out.

    Inside the main checkout's ``.worktrees/`` (gitignored, and the one place
    an agent can write), whichever worktree this runs from."""
    common = Path(_git("rev-parse", "--path-format=absolute", "--git-common-dir"))
    path = common.parent / ".worktrees" / f"sim_fingerprint-{commit[:10]}-{os.getpid()}"
    _git("worktree", "add", "--detach", str(path), commit)
    try:
        yield path
    finally:
        try:
            _git("worktree", "remove", "--force", str(path))
        except subprocess.CalledProcessError:
            shutil.rmtree(path, ignore_errors=True)
            _git("worktree", "prune")


def snapshot_source(rev: str | None, commit: str | None) -> str:
    """What a snapshot was played on, as ``SOURCE`` records it."""
    if commit is not None:
        return f"commit {commit} (--rev {rev})"
    try:
        head = _git("rev-parse", "HEAD")
        dirty = bool(_git("status", "--porcelain", "--untracked-files=no"))
    except (OSError, subprocess.CalledProcessError):
        return "working tree"
    return f"working tree at {head}" + (" with uncommitted changes" if dirty else "")


def _read(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


#: How many lines of each moved run's diff the compare prints; the rest is in
#: ``<snapshot>/compare/<run>.diff``.
PRINTED_LINES = 40


def compare_dirs(old: Path, new: Path) -> list[tuple[str, list[str]]]:
    """Each run whose summary or log moved, with the whole of its diff."""
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
            moved.append((name, diff))
    return moved


def keep_compare(snapshot: Path, scratch: Path, moved: list[tuple[str, list[str]]]) -> Path:
    """Write each moved run's whole diff and its new log beside the snapshot."""
    out = snapshot / "compare"
    out.mkdir(parents=True, exist_ok=True)
    for stale in out.iterdir():
        stale.unlink()
    for name, diff in moved:
        (out / f"{name}.diff").write_text("\n".join(diff) + "\n", encoding="utf-8")
        after = scratch / f"{name}.log"
        if after.exists():
            (out / f"{name}.after.log").write_text(after.read_text(encoding="utf-8"), encoding="utf-8")
    return out


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
    parser.add_argument(
        "--rev",
        metavar="COMMIT",
        help="snapshot: play the runs on this commit instead of the working "
             "tree, in a throwaway detached worktree removed after",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.rev is not None and args.command != "snapshot":
        parser.error("--rev is a snapshot option: compare always plays the working tree")
    if args.command == "snapshot":
        commit = None
        if args.rev is not None:
            try:
                commit = resolve_rev(args.rev)
            except ValueError as error:
                parser.error(str(error))
            with rev_worktree(commit) as root:
                results = run_all(args.snapshot, args.workers, root)
        else:
            results = run_all(args.snapshot, args.workers)
        source = snapshot_source(args.rev, commit)
        (args.snapshot / SOURCE_FILE).write_text(source + "\n", encoding="utf-8")
        failed = [r["name"] for r in results if r["exit"] != 0]
        print(f"snapshot: {len(results)} seeded runs of the {source} -> {args.snapshot}")
        if failed:
            print(f"note: {len(failed)} run(s) exited non-zero: {failed}")
        return 0
    if not args.snapshot.exists():
        print(f"no snapshot at {args.snapshot}; run `snapshot` first")
        return 2
    source = args.snapshot / SOURCE_FILE
    if source.exists():
        print(f"snapshot of the {source.read_text(encoding='utf-8').strip()}")
    with tempfile.TemporaryDirectory(prefix="sim_fingerprint_") as scratch:
        run_all(Path(scratch), args.workers)
        moved = compare_dirs(args.snapshot, Path(scratch))
        kept = keep_compare(args.snapshot, Path(scratch), moved)
    print(f"compare: {len(moved)} moved of {len(RUNS)} seeded runs")
    for name, diff in moved:
        hunks = sum(line.startswith("@@") for line in diff)
        print(f"\n== {name}: diverges in {hunks} place(s); whole diff {kept / (name + '.diff')}")
        print("\n".join(diff[:PRINTED_LINES]))
        if len(diff) > PRINTED_LINES:
            print(f"... {len(diff) - PRINTED_LINES} more line(s) in the .diff")
    return 1 if moved else 0


if __name__ == "__main__":
    sys.exit(main())
