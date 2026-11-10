"""`sim_fingerprint compare` keeps the whole of a moved run, not its first hunk.

It printed the first 40 lines of each moved run's diff and dropped the rest, so
reading which decision moved — rarely the first divergence — meant re-running
the game. The whole diff and the new log now land under ``<snapshot>/compare/``.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import sim_fingerprint  # noqa: E402


def _write_run(directory: Path, name: str, lines: list[str]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (directory / f"{name}.summary").write_text("same\n", encoding="utf-8")


def test_a_moved_run_keeps_every_divergence_and_its_new_log(tmp_path):
    name = sim_fingerprint.run_name(*sim_fingerprint.RUNS[0])
    before = [f"turn {i}: pass" for i in range(400)]
    after = list(before)
    for far_apart in (10, 200, 390):
        after[far_apart] = f"turn {far_apart}: cast Shock"
    _write_run(tmp_path / "snapshot", name, before)
    _write_run(tmp_path / "scratch", name, after)

    moved = sim_fingerprint.compare_dirs(tmp_path / "snapshot", tmp_path / "scratch")
    assert [moved_name for moved_name, _ in moved] == [name]
    diff = moved[0][1]
    assert sum(line.startswith("@@") for line in diff) == 3
    assert "+turn 390: cast Shock" in diff

    kept = sim_fingerprint.keep_compare(tmp_path / "snapshot", tmp_path / "scratch", moved)
    assert "+turn 390: cast Shock" in (kept / f"{name}.diff").read_text(encoding="utf-8")
    assert (kept / f"{name}.after.log").read_text(encoding="utf-8").splitlines() == after


def test_a_compare_that_moves_nothing_leaves_no_stale_diffs(tmp_path):
    stale = tmp_path / "snapshot" / "compare" / "old_run.diff"
    stale.parent.mkdir(parents=True)
    stale.write_text("from an earlier compare\n", encoding="utf-8")
    sim_fingerprint.keep_compare(tmp_path / "snapshot", tmp_path / "scratch", [])
    assert not stale.exists()
