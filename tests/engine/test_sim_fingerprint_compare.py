"""`sim_fingerprint compare` keeps the whole of a moved run, not its first hunk.

It printed the first 40 lines of each moved run's diff and dropped the rest, so
reading which decision moved — rarely the first divergence — meant re-running
the game. The whole diff and the new log now land under ``<snapshot>/compare/``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

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


def test_snapshot_rev_plays_the_runs_on_the_commit_s_own_checkout(tmp_path, monkeypatch, capsys):
    """``snapshot --rev`` hands every run the throwaway worktree as its root —
    that checkout's simulator, so that checkout's engine — writes them into the
    snapshot directory named, and records the commit beside them, which
    ``compare`` prints. The worktree itself is ``rev_worktree``'s (git); here it
    is a folder, so the test is about the plumbing."""
    commit = sim_fingerprint.resolve_rev("HEAD")
    assert len(commit) == 40
    roots, made = [], []

    class FakeWorktree:
        def __init__(self, sha):
            made.append(sha)

        def __enter__(self):
            return tmp_path / "throwaway"

        def __exit__(self, *exc):
            made.append("removed")

    def fake_run_one(code, seed, games, out_dir, root=sim_fingerprint.REPO_ROOT):
        roots.append(root)
        _write_run(out_dir, sim_fingerprint.run_name(code, seed, games), [code])
        return {"name": sim_fingerprint.run_name(code, seed, games), "exit": 0}

    monkeypatch.setattr(sim_fingerprint, "rev_worktree", FakeWorktree)
    monkeypatch.setattr(sim_fingerprint, "run_one", fake_run_one)
    snapshot = tmp_path / "snapshot"
    assert sim_fingerprint.main(["snapshot", "--rev", "HEAD", "--snapshot", str(snapshot)]) == 0
    assert made == [commit, "removed"]
    assert roots == [tmp_path / "throwaway"] * len(sim_fingerprint.RUNS)
    assert (snapshot / "SOURCE").read_text(encoding="utf-8") == f"commit {commit} (--rev HEAD)\n"
    assert f"of the commit {commit}" in capsys.readouterr().out

    # compare plays the working tree (the script's own checkout) and names the base.
    roots.clear()
    assert sim_fingerprint.main(["compare", "--snapshot", str(snapshot), "--workers", "1"]) == 0
    assert roots == [sim_fingerprint.REPO_ROOT] * len(sim_fingerprint.RUNS)
    out = capsys.readouterr().out
    assert out.startswith(f"snapshot of the commit {commit} (--rev HEAD)\ncompare: 0 moved of ")


def test_rev_names_a_commit_and_only_snapshot_takes_it(tmp_path):
    with pytest.raises(ValueError):
        sim_fingerprint.resolve_rev("no-such-ref-anywhere")
    with pytest.raises(SystemExit):
        sim_fingerprint.main(["compare", "--rev", "HEAD", "--snapshot", str(tmp_path)])
    with pytest.raises(SystemExit):
        sim_fingerprint.main(["snapshot", "--rev", "no-such-ref-anywhere", "--snapshot", str(tmp_path)])
