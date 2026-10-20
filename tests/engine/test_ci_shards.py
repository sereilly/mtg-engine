"""ci.yml's test shards cover every test, once.

The test job runs the suite as a matrix of shards, each a list of tests/
folders handed to pytest on the command line. Naming paths overrides
pytest.ini's ``testpaths``, so a folder no shard names is a folder CI never
runs — and that failure is silent: every shard is green, the guards job is
green, and the new tests simply do not exist as far as CI is concerned. A
folder named by two shards is the opposite cost (run twice, budgeted twice)
and is as much a sign the list was edited by hand without looking.

Read with a regex for the reason test_check_all.py gives: the repo carries no
yaml dependency, and the shape read here is the shape the workflow uses.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TESTS = REPO / "tests"
CI_YML = REPO / ".github" / "workflows" / "ci.yml"

_SHARD_PATHS = re.compile(r"^\s+paths: (tests/.+)$", re.M)
#: pytest's default ``python_files``; pytest.ini does not override it.
_TEST_FILE_GLOBS = ("test_*.py", "*_test.py")


def _shard_paths() -> list[str]:
    shards = _SHARD_PATHS.findall(CI_YML.read_text(encoding="utf-8"))
    assert len(shards) >= 2, (
        "ci.yml's test matrix stopped matching '  paths: tests/...' — update "
        "the extraction here together with the workflow"
    )
    return [path for shard in shards for path in shard.split()]


def _folders_holding_tests() -> set[str]:
    return {
        f"tests/{folder.name}"
        for folder in TESTS.iterdir()
        if folder.is_dir()
        and any(
            next(folder.rglob(glob), None) is not None
            for glob in _TEST_FILE_GLOBS
        )
    }


def test_every_folder_holding_tests_is_in_exactly_one_shard():
    named = Counter(_shard_paths())
    twice = sorted(path for path, count in named.items() if count > 1)
    assert not twice, f"named by more than one shard: {twice}"
    missing = sorted(_folders_holding_tests() - set(named))
    assert not missing, (
        f"CI runs no shard over {missing}: add each to a shard's paths in ci.yml"
    )
    stale = sorted(path for path in named if not (REPO / path).is_dir())
    assert not stale, f"ci.yml shards name folders that do not exist: {stale}"


def test_no_test_file_sits_at_the_root_of_tests():
    """A shard is a folder, so a test file directly under tests/ is in none."""
    loose = sorted(
        path.name for glob in _TEST_FILE_GLOBS for path in TESTS.glob(glob)
    )
    assert not loose, (
        f"{loose} would be collected by no CI shard: move each into the "
        "tests/ subfolder for its subject"
    )


def test_the_timed_step_runs_the_shards_paths():
    """Without the paths on its command line a shard runs the whole suite."""
    workflow = CI_YML.read_text(encoding="utf-8")
    assert "SHARD_PATHS: ${{ matrix.paths }}" in workflow
    assert re.search(r"python -m pytest .*\$SHARD_PATHS", workflow), (
        "the timed step no longer passes $SHARD_PATHS to pytest"
    )
