"""`scripts/tests_for_diff.py` names the censuses a registry's new member owes.

Mirrodin's wave-close gate found eight reds no meeting list named, each a census
"every member of registry R is classified" in a file no branch had edited. The
picker compares the registries of two trees and lists the test files that
*enumerate* a moved one; a file that looks one entry up is not owed a run (in
a replay over Mirrodin's wave-1 merges, lookups of ``EFFECT_HANDLERS`` were 314
of the 520 rows a plain read listed). Replayed over those twelve merges, it
named five of the seven red files at the merge that caused them; the other two
enumerate the AI policy's source and the compiled pool, not a registry.
"""

from __future__ import annotations

import sys
from pathlib import Path

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
