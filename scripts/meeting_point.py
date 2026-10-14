"""Run the meeting-point tests for a merged tree: what stands in for the suite
between full gates.

A full suite is half an hour of this machine and only one fits at a time, so a
wave's merges are staged on a link and gated in batches (SET_PLAYBOOK.md,
"Integration"). What each merge gets instead is this list, on the merged tree:

* **changed** — every test file the tree adds or edits against its base (the
  merge-base with ``--base``, so the base moving ahead adds nothing), plus
  anything uncommitted or untracked;
* **set** — the per-set test files of ``--set <CODE>``;
* **guard** — the structural guards: every test file that reads source rather
  than running a card (it imports ``ast`` or ``tests.source_index``). Derived on
  each run, because a guard sits far from the code it guards and a hand list of
  them is what an integrator thought of;
* **surprise** — every file a full gate has turned red behind a green
  meeting-point run, from ``scripts/meeting_point_surprises.txt``. Add a line
  the day it happens, with the reason.

It existed for two sets as a scratch file rewritten per wave, and once, to save
ten minutes, as six paths typed by hand — a per-set file went over its cap and a
census tripped the face-blind guard, and both sat red on the link for a merge.
Two refusals come from that:

* **a path that does not exist is an error**, here, before pytest starts. xdist
  reports a mistyped path as "no tests ran", exit 5, which reads as green in a
  tail.
* **exit 5 is a failure.** A list that collected nothing proved nothing.

A guard's or a surprise's `slow`-marked tests are left to the full gate; a
changed, set or named file runs whole. Anything after a bare `--` is pytest's.

**The list is not the suite.** Odyssey's full gates found six reds behind
seventeen green meeting-point runs, each in a file this list did not hold. A
link is not green on the list; the surprises file is how the list learns.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SURPRISES = Path(__file__).resolve().parent / "meeting_point_surprises.txt"

_READS_SOURCE = re.compile(
    r"^(import ast\b|from tests\.source_index import|from tests import source_index)",
    re.MULTILINE,
)


#: Why a file's `slow` tests run too: the tree changed it, or somebody asked.
FULL_REASONS = frozenset({"changed", "set", "named"})


class ListError(Exception):
    """The list names something that is not there."""


def _git(*argv: str) -> list[str]:
    result = subprocess.run(
        ["git", *argv], cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def changed_test_paths(base: str) -> list[str]:
    """Every path under ``tests/`` the tree adds or edits against *base*,
    committed or not. Deletions are not on the list: there is nothing to run."""
    fork = _git("merge-base", base, "HEAD")[0]
    committed_or_dirty = _git("diff", "--name-only", "--diff-filter=d", fork, "--", "tests")
    untracked = _git("ls-files", "--others", "--exclude-standard", "--", "tests")
    return sorted(set(committed_or_dirty) | set(untracked))


def is_test_file(path: str) -> bool:
    return path.endswith(".py") and Path(path).name.startswith("test_")


def structural_guards(root: Path = REPO_ROOT) -> list[str]:
    """Test files that read source: the guards a card's own tests never touch."""
    guards = []
    for path in sorted((root / "tests").rglob("test_*.py")):
        if _READS_SOURCE.search(path.read_text(encoding="utf-8")):
            guards.append(path.relative_to(root).as_posix())
    return guards


def set_test_files(code: str, root: Path = REPO_ROOT) -> list[str]:
    files = sorted(
        path.relative_to(root).as_posix()
        for path in (root / "tests" / "sets").glob(f"test_{code.lower()}_*.py")
    )
    if not files:
        raise ListError(
            f"--set {code}: no tests/sets/test_{code.lower()}_*.py. A set whose "
            "files are named for the set rather than its code (legends, "
            "antiquities) is passed as paths."
        )
    return files


def read_surprises(path: Path = SURPRISES) -> list[tuple[str, str]]:
    """``(test file, reason)`` for every line of the surprises file."""
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        name, _, reason = line.partition("#")
        if not reason.strip():
            raise ListError(f"{path.name}:{number}: a surprise carries its reason after '#'")
        rows.append((name.strip(), reason.strip()))
    return rows


def build_list(
    *,
    changed: list[str],
    set_files: list[str],
    guards: list[str],
    surprises: list[tuple[str, str]],
    extra: list[str],
    root: Path = REPO_ROOT,
) -> tuple[dict[str, list[str]], list[str]]:
    """``{test file: [why it is on the list]}`` and the changed paths under
    ``tests/`` that are not test files (a helper's readers are not listed).

    Raises :class:`ListError` on any named path that does not exist.
    """
    reasons: dict[str, list[str]] = {}

    def add(path: str, why: str) -> None:
        path = Path(path).as_posix()
        if not (root / path).is_file():
            raise ListError(f"{path} ({why}) does not exist")
        reasons.setdefault(path, []).append(why)

    helpers = [path for path in changed if path.endswith(".py") and not is_test_file(path)]
    for path in changed:
        if is_test_file(path):
            add(path, "changed")
    for path in set_files:
        add(path, "set")
    for path in guards:
        add(path, "guard")
    for path, _reason in surprises:
        add(path, "surprise")
    for path in extra:
        add(path, "named")
    return dict(sorted(reasons.items())), helpers


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the meeting-point tests on this tree: changed test files, the "
            "set's own, the structural guards and every file a gate has "
            "surprised. Exit non-zero on a failure, on a missing path, and on "
            "a run that collected nothing."
        )
    )
    parser.add_argument(
        "--base", default="main",
        help="The tree this one is measured against (default: main). Its merge-base with HEAD is used.",
    )
    parser.add_argument("--set", dest="set_code", help="Also run tests/sets/test_<code>_*.py.")
    parser.add_argument("--list", action="store_true", help="Print the list with each file's reason and run nothing.")
    parser.add_argument("-n", dest="workers", default="2", help="xdist workers (default 2; a gate may be running beside this).")
    parser.add_argument("paths", nargs="*", help="Further test files to run; each must exist.")
    parser.epilog = "Anything after a bare `--` is passed to pytest."
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Everything after a bare `--` is pytest's. Not `parse_known_args`: an
    # unknown option's value would be read as one more path to run.
    passthrough: list[str] = []
    if "--" in argv:
        split = argv.index("--")
        argv, passthrough = argv[:split], argv[split + 1:]
    args = build_parser().parse_args(argv)
    try:
        reasons, helpers = build_list(
            changed=changed_test_paths(args.base),
            set_files=set_test_files(args.set_code) if args.set_code else [],
            guards=structural_guards(),
            surprises=read_surprises(),
            extra=args.paths,
        )
    except ListError as error:
        print(f"meeting_point: {error}", file=sys.stderr)
        return 2

    counts: dict[str, int] = {}
    for whys in reasons.values():
        for why in whys:
            counts[why] = counts.get(why, 0) + 1
    summary = ", ".join(f"{count} {why}" for why, count in sorted(counts.items()))
    print(f"meeting point: {len(reasons)} files against {args.base} ({summary})")
    for path in helpers:
        print(f"  note: {path} changed and is not a test file - its readers are not on this list")
    if args.list:
        for path, whys in reasons.items():
            print(f"  {'+'.join(whys):<22} {path}")
        return 0
    if not reasons:
        print("meeting_point: nothing on the list", file=sys.stderr)
        return 2

    # Two runs. A file on the list as a guard or a surprise is there for the
    # fact it states about the pool, and several of them keep one AST guard
    # beside whole-game simulations marked `slow` — five of this list's
    # thirty-odd minutes of worker time. Those simulations are the full gate's.
    # A file the tree *changed* is a meeting point in full, slow tests included.
    #
    # `worksteal`: the default scheduler deals each worker its share up front,
    # and this list is a few long files among many short ones.
    def run(files: list[str], marker: str) -> int:
        return subprocess.run(
            [
                sys.executable, "-m", "pytest", *files, "-m", marker,
                "-n", args.workers, "--dist", "worksteal", *passthrough,
            ],
            cwd=REPO_ROOT,
        ).returncode

    code = run(list(reasons), "not slow")
    if code == 5:
        print("meeting_point: pytest collected nothing (exit 5) - that is not a green run", file=sys.stderr)
        return 1
    if code != 0:
        return code
    in_full = [path for path, whys in reasons.items() if FULL_REASONS & set(whys)]
    if in_full:
        slow = run(in_full, "slow")
        # Exit 5 here only means none of those files has a slow test.
        if slow not in (0, 5):
            return slow
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
