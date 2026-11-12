"""`scripts/tests_for_diff.py` names the censuses a registry's new member owes.

Mirrodin's wave-close gate found eight reds no meeting list named, each a census
"every member of registry R is classified" in a file no branch had edited. The
picker compares the registries of two trees and lists the test files that
*enumerate* a moved one; a file that looks one entry up is not owed a run (in
a replay over Mirrodin's wave-1 merges, lookups of ``EFFECT_HANDLERS`` were 314
of the 520 rows a plain read listed). Replayed over those twelve merges, it
named five of the seven red files at the merge that caused them; the other two
enumerate the AI policy's source and the compiled pool, not a registry.

Its defaults, from Darksteel's reports: the diff is read from where the branch
started, not the merge-base with ``main`` (W2G3, cut from a chain link, listed
512 files); a list is LF (W2G2's shell loop handed pytest a path ending in a
carriage return); and while a set is measured an engine diff owes the tests
that walk it, by node id (`scripts/measured_censuses.py`) — the class W1G3's
graveyard-denial census and the conditional-grants and upkeep-window censuses
were, each red on the branch that caused it and named by no other reason.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import tests_for_diff  # noqa: E402

HERE = REPO / "tests" / "engine" / "test_example.py"


def _imports(text: str) -> "tests_for_diff._Imports":
    return tests_for_diff._Imports(HERE, text)


def test_a_census_enumerates_and_a_lookup_does_not():
    census = _imports(
        "from engine.handlers.registry import EFFECT_HANDLERS\n"
        "def test_every_kind():\n"
        "    for kind in sorted(EFFECT_HANDLERS):\n"
        "        assert kind\n"
    )
    lookup = _imports(
        "from engine.handlers.registry import EFFECT_HANDLERS\n"
        "def test_one():\n"
        "    EFFECT_HANDLERS['deal_damage'](None, None, None)\n"
    )
    assert census.enumerates("engine.handlers.registry", "EFFECT_HANDLERS")
    assert not lookup.enumerates("engine.handlers.registry", "EFFECT_HANDLERS")


def test_every_way_a_census_walks_a_registry_is_seen():
    shapes = [
        "x = [k for k in R]",
        "x = R.items()",
        "x = len(R)",
        "x = set(R) - {'a'}",
        "x = R - OTHER",
        "x = [*R]",
        "x = 'k' not in R",           # a census over the pool's keys
        "for k, v in R.items(): pass",
    ]
    for shape in shapes:
        imports = _imports(f"from engine.m import R, OTHER\n{shape}\n")
        assert imports.enumerates("engine.m", "R"), shape


def test_a_registry_read_through_a_module_alias_is_resolved():
    imports = _imports(
        "from engine import oracle\n"
        "import engine.handlers.registry as registry\n"
        "a = sorted(oracle.INSTRUCTION_CATEGORIES)\n"
        "b = list(registry.EFFECT_HANDLERS)\n"
    )
    assert imports.enumerates("engine.oracle", "INSTRUCTION_CATEGORIES")
    assert imports.enumerates("engine.handlers.registry", "EFFECT_HANDLERS")


def test_a_relative_import_inside_tests_resolves_to_the_helper():
    path = REPO / "tests" / "sets" / "test_example.py"
    imports = tests_for_diff._Imports(path, "from .jud_w1g5_helpers import settle\n")
    assert imports.imports_module("tests.sets.jud_w1g5_helpers")


def test_a_registry_moves_when_its_members_do_and_follows_a_split():
    before = {
        "engine.a:R": {"aliases": [["engine.a", "R"]], "members": ["'x'"]},
        "engine.a:SAME": {"aliases": [["engine.a", "SAME"]], "members": ["'y'"]},
        "engine.a:MOVED_HOME": {"aliases": [["engine.a", "MOVED_HOME"]], "members": ["'z'"]},
    }
    after = {
        "engine.a:R": {"aliases": [["engine.a", "R"]], "members": ["'x'", "'new'"]},
        "engine.a:SAME": {"aliases": [["engine.a", "SAME"]], "members": ["'y'"]},
        # A module split moved it; it is matched by name and compared.
        "engine.b:MOVED_HOME": {"aliases": [["engine.b", "MOVED_HOME"]], "members": []},
        "engine.b:BRAND_NEW": {"aliases": [["engine.b", "BRAND_NEW"]], "members": ["'n'"]},
    }
    moved = tests_for_diff.moved_registries(before, after)
    assert sorted(moved) == ["engine.a:R", "engine.b:MOVED_HOME"]
    assert moved["engine.a:R"]["added"] == ["'new'"]
    assert moved["engine.b:MOVED_HOME"]["removed"] == ["'z'"]


def test_members_are_keys_and_hashable_values_only():
    assert tests_for_diff._members({"a": object(), "b": 1}) == ["'a'", "'b'"]
    assert tests_for_diff._members(frozenset({"x", ("y", 1)})) == ["'x'", "('y', 1)"]
    assert tests_for_diff._members([object()]) is None
    assert tests_for_diff._members("not a container") is None


def test_the_times_split_quick_from_full_by_file():
    times = {
        "tests/a.py::q": [2.0, False], "tests/a.py::f": [30.0, True],
        "tests/b.py::q": [1.5, False],
    }
    assert tests_for_diff.file_times(times) == {"tests/a.py": (2.0, 30.0), "tests/b.py": (1.5, 0.0)}


# ---------------------------------------------------------------------------
# the base: where the branch started, not the merge-base with main
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=repo, check=True, capture_output=True, text=True,
    ).stdout.strip()


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", name)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def chain(tmp_path, monkeypatch):
    """main, a chain link cut from it with two merges' worth of commits, and a
    branch cut from the link with one of its own — Darksteel's W2G3 on
    ``dst/int-w1g9``, whose list read every link's files against ``main``."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    root = _commit(repo, "a.py")
    _git(repo, "checkout", "-q", "-b", "link")
    _commit(repo, "link1.py")
    link = _commit(repo, "link2.py")
    _git(repo, "checkout", "-q", "-b", "w2g3")
    _commit(repo, "own.py")
    monkeypatch.setattr(tests_for_diff, "ROOT", repo)
    monkeypatch.delenv(tests_for_diff.BASE_ENV, raising=False)
    return {"repo": repo, "main": root, "link": link}


def test_the_base_is_where_the_branch_started(chain):
    base, source = tests_for_diff.resolve_base(None)
    assert base == chain["link"]
    assert source.startswith("where w2g3 started")
    assert tests_for_diff.changed_files(base) == ["own.py"]
    # The merge-base with main, the old default, is the whole chain.
    merge_base = _git(chain["repo"], "merge-base", "HEAD", "main")
    assert tests_for_diff.changed_files(merge_base) == ["link1.py", "link2.py", "own.py"]


def test_the_brief_s_variable_and_the_flag_outrank_the_branch_start(chain, monkeypatch):
    monkeypatch.setenv(tests_for_diff.BASE_ENV, "main")
    assert tests_for_diff.resolve_base(None) == (chain["main"], f"${tests_for_diff.BASE_ENV}")
    assert tests_for_diff.resolve_base("link") == (chain["link"], "--base")


def test_a_detached_head_falls_back_to_the_merge_base_with_main(chain):
    _git(chain["repo"], "checkout", "-q", "--detach", "HEAD")
    assert tests_for_diff.resolve_base(None) == (chain["main"], "the merge-base with main")


# ---------------------------------------------------------------------------
# the measured reason: node ids, grouped by file, timed
# ---------------------------------------------------------------------------


def test_the_measured_tests_are_one_row_a_file_and_run_longest_first():
    nodes = {
        "tests/a.py::test_census": (3, "DST: walks"),
        "tests/a.py::test_other": (9, "DST: counts"),
        "tests/b.py::test_big": (4, "DST: walks"),
    }
    times = {
        "tests/a.py::test_census[x]": [1.0, False], "tests/a.py::test_census[y]": [2.0, False],
        "tests/a.py::test_unlisted": [50.0, True],
        "tests/b.py::test_big": [40.0, True],
    }
    rows = {row["file"]: row for row in tests_for_diff.rows_of({}, nodes, times)}
    assert rows["tests/a.py"]["targets"] == ["tests/a.py::test_census", "tests/a.py::test_other"]
    assert rows["tests/a.py"]["times"] == (3.0, 0.0)   # the unlisted test is not its cost
    assert rows["tests/b.py"]["times"] == (0.0, 40.0)
    assert tests_for_diff.targets_longest_first(list(rows.values())) == [
        "tests/b.py::test_big", "tests/a.py::test_census", "tests/a.py::test_other",
    ]


def _stub_pick(monkeypatch, changed_paths):
    monkeypatch.setattr(tests_for_diff, "changed_files", lambda base: [])
    monkeypatch.setattr(tests_for_diff, "changed_paths", lambda base: changed_paths)
    empty = {"registries": {}, "failed": []}
    monkeypatch.setattr(tests_for_diff, "registries_of", lambda tree: empty)
    monkeypatch.setattr(tests_for_diff, "base_registries", lambda sha: empty)
    monkeypatch.setattr(tests_for_diff, "measured_codes", lambda: ["DST"])
    monkeypatch.setattr(tests_for_diff, "measured_rows",
                        lambda codes: {"tests/ai/test_x.py::test_census": (1, "DST: walks")})


def test_an_engine_diff_owes_the_tests_that_walk_the_measured_set(monkeypatch):
    _stub_pick(monkeypatch, ["engine/ai_abilities.py"])
    result = tests_for_diff.pick("base", hub=60)
    assert result["measured"] == ["DST"]
    assert list(result["nodes"]) == ["tests/ai/test_x.py::test_census"]
    assert not tests_for_diff.pick("base", hub=60, measured=False)["nodes"]
    assert not tests_for_diff.pick("base", hub=60, censuses_only=True)["nodes"]


def test_a_diff_outside_the_engine_owes_none_of_them(monkeypatch):
    _stub_pick(monkeypatch, ["tests/engine/test_x.py", "scripts/x.py", "SET_PLAYBOOK.md"])
    assert not tests_for_diff.pick("base", hub=60)["nodes"]


def test_a_list_is_lf_on_every_platform():
    """W2G2: ``--list`` wrote CRLF on Windows, and a shell loop handed pytest a
    path ending in a carriage return."""
    script = (
        "import sys; sys.path.insert(0, sys.argv[1]); import tests_for_diff as t; "
        "t._ingest = lambda code: {'tests/a.py::test_x': (1, 'w'), 'tests/b.py::test_y': (2, 'w')}; "
        "t.recorded_times = lambda: {}; t.main(['--ingest', 'DST', '--list'])"
    )
    out = subprocess.run(
        [sys.executable, "-c", script, str(REPO / "scripts")], capture_output=True, check=True,
    ).stdout
    assert b"\r" not in out
    assert sorted(out.decode().split("\n")) == ["", "tests/a.py::test_x", "tests/b.py::test_y"]
