"""ci.yml's test shards cover every test, once.

The test job runs the suite as a matrix of shards, each a list of tests/
folders handed to pytest on the command line, optionally with a marker
expression. Naming paths overrides pytest.ini's ``testpaths``, so a folder no
shard names is a folder CI never runs — and that failure is silent: every
shard is green, the guards job is green, and the new tests simply do not
exist as far as CI is concerned. A folder run twice is the opposite cost (run
twice, budgeted twice) and is as much a sign the list was edited by hand
without looking.

A folder may be split between two shards by a marker, and then only by an
expression and its negation (``slow`` / ``not slow``), which partition its
tests by construction. Any other pair could leave a test in neither shard or
in both, and which would depend on how each test is marked.

Read with a regex for the reason test_check_all.py gives: the repo carries no
yaml dependency, and the shape read here is the shape the workflow uses.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TESTS = REPO / "tests"
CI_YML = REPO / ".github" / "workflows" / "ci.yml"

_SHARD = re.compile(r"^\s+- shard: (\S+)$", re.M)
_PATHS = re.compile(r"^\s+paths: (tests/.+)$", re.M)
_MARKERS = re.compile(r"^\s+markers: (.*)$", re.M)
#: pytest's default ``python_files``; pytest.ini does not override it.
_TEST_FILE_GLOBS = ("test_*.py", "*_test.py")


def _shards(workflow: str) -> list[tuple[str, list[str], str]]:
    """``(name, paths, markers)`` per matrix entry, markers ``""`` for none."""
    starts = [match.start() for match in _SHARD.finditer(workflow)]
    assert len(starts) >= 2, (
        "ci.yml's test matrix stopped matching '- shard: <name>' — update the "
        "extraction here together with the workflow"
    )
    shards = []
    for start, end in zip(starts, starts[1:] + [None]):
        block = workflow[start:end]
        name = _SHARD.search(block).group(1)
        paths = _PATHS.search(block)
        markers = _MARKERS.search(block)
        assert paths and markers, (
            f"shard {name!r} lacks a 'paths:' or a 'markers:' line (write "
            "markers: '' for none, so the step's env always has the key)"
        )
        shards.append(
            (name, paths.group(1).split(), markers.group(1).strip().strip("'\""))
        )
    return shards


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


def _coverage_refusal(shards) -> str | None:
    """Why *shards* do not run every test folder exactly once, or None."""
    by_folder: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for name, paths, markers in shards:
        for path in paths:
            by_folder[path].append((name, markers))
    missing = sorted(_folders_holding_tests() - set(by_folder))
    if missing:
        return f"CI runs no shard over {missing}: add each to a shard's paths in ci.yml"
    stale = sorted(path for path in by_folder if not (REPO / path).is_dir())
    if stale:
        return f"ci.yml shards name folders that do not exist: {stale}"
    for folder, named in sorted(by_folder.items()):
        expressions = [markers for _, markers in named]
        if expressions == [""]:
            continue
        if len(expressions) == 2 and all(expressions) and (
            expressions[1] == f"not {expressions[0]}"
            or expressions[0] == f"not {expressions[1]}"
        ):
            continue
        return (
            f"{folder} is covered by {named}: a folder is one shard with no "
            "markers, or two whose markers are an expression and its negation"
        )
    return None


def test_every_folder_holding_tests_is_covered_exactly_once():
    refusal = _coverage_refusal(_shards(CI_YML.read_text(encoding="utf-8")))
    assert refusal is None, refusal


def test_the_coverage_rule_refuses_what_it_should():
    """The rule's own cases, so a loosened check fails here rather than
    reading green over a matrix that drops tests."""
    whole = [("rest", sorted(_folders_holding_tests()), "")]
    assert _coverage_refusal(whole) is None
    folder = whole[0][1][0]
    others = whole[0][1][1:]
    split = [("a", [folder], "slow"), ("b", [folder], "not slow"), ("r", others, "")]
    assert _coverage_refusal(split) is None
    for broken in (
        [("r", others, "")],                                      # dropped
        [("a", [folder], ""), ("b", [folder], ""), ("r", others, "")],  # twice
        [("a", [folder], "slow"), ("r", others, "")],            # half only
        [("a", [folder], "slow"), ("b", [folder], "not fast"), ("r", others, "")],
        [("a", [folder], "slow"), ("b", [folder], ""), ("r", others, "")],
        [("r", whole[0][1] + ["tests/nowhere"], "")],            # stale
    ):
        assert _coverage_refusal(broken) is not None, broken


def test_no_test_file_sits_at_the_root_of_tests():
    """A shard is a folder, so a test file directly under tests/ is in none."""
    loose = sorted(
        path.name for glob in _TEST_FILE_GLOBS for path in TESTS.glob(glob)
    )
    assert not loose, (
        f"{loose} would be collected by no CI shard: move each into the "
        "tests/ subfolder for its subject"
    )


def test_the_timed_step_runs_the_shards_paths_and_markers():
    """Without the paths on its command line a shard runs the whole suite,
    and without the markers both halves of a split folder run all of it."""
    workflow = CI_YML.read_text(encoding="utf-8")
    assert "SHARD_PATHS: ${{ matrix.paths }}" in workflow
    assert "SHARD_MARKERS: ${{ matrix.markers }}" in workflow
    assert re.search(
        r'python -m pytest .*\$\{SHARD_MARKERS:\+-m "\$SHARD_MARKERS"\} \$SHARD_PATHS',
        workflow,
    ), "the timed step no longer passes the shard's markers and paths to pytest"
