"""The quick pass and the full pass select what tests/passes.py says they do.

A selection hook that drops too much reads green — the tests it dropped report
nothing — so its rules are pinned here on stand-in items rather than trusted.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

from tests import passes
from tests.source_index import source_text

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve()
OTHER = REPO / "tests" / "engine" / "test_ci_shards.py"


class _Item:
    def __init__(self, name: str, path: Path, full: bool):
        self.name, self.path, self._full = name, path, full

    def get_closest_marker(self, name):
        return object() if name == passes.FULL_MARK and self._full else None


def _config(*, full=False, collectonly=False, args=("tests",)):
    deselected = []
    config = SimpleNamespace(
        getoption=lambda name, default=None: full if name == "full" else default,
        option=SimpleNamespace(collectonly=collectonly),
        args=list(args),
        invocation_params=SimpleNamespace(dir=REPO),
        hook=SimpleNamespace(pytest_deselected=lambda items: deselected.extend(items)),
    )
    return config, deselected


def _run(config):
    items = [
        _Item("quick_here", HERE, False), _Item("full_here", HERE, True),
        _Item("quick_there", OTHER, False), _Item("full_there", OTHER, True),
    ]
    passes.pytest_collection_modifyitems(config, items)
    return [item.name for item in items]


def test_the_quick_pass_leaves_out_the_tests_marked_full():
    config, deselected = _config()
    assert _run(config) == ["quick_here", "quick_there"]
    assert sorted(item.name for item in deselected) == ["full_here", "full_there"]


def test_the_full_pass_runs_everything():
    config, deselected = _config(full=True)
    assert _run(config) == ["quick_here", "full_here", "quick_there", "full_there"]
    assert deselected == []


def test_a_file_named_on_the_command_line_runs_whole():
    for named in (str(HERE.relative_to(REPO)), f"{HERE.relative_to(REPO)}::full_here"):
        config, _ = _config(args=(named, "tests/ui"))
        assert _run(config) == ["quick_here", "full_here", "quick_there"], named


def test_a_folder_named_on_the_command_line_is_the_quick_pass():
    config, _ = _config(args=("tests/engine",))
    assert _run(config) == ["quick_here", "quick_there"]


def test_a_collection_lists_every_test():
    """An IDE's test tree is a collect-only session; a test it cannot show is
    one nobody can click to run."""
    config, deselected = _config(collectonly=True)
    assert len(_run(config)) == 4 and deselected == []


def test_the_full_pass_runs_the_censuses_whole(monkeypatch):
    # setenv first, so the variable's absence is what monkeypatch restores:
    # a delenv of an unset name records nothing, and the "1" set below would
    # outlive this test and run every later census in this worker whole.
    monkeypatch.setenv(passes.FULL_CENSUS_ENV, "0")
    monkeypatch.delenv(passes.FULL_CENSUS_ENV)
    passes.pytest_configure(_config()[0])
    import os

    assert os.environ.get(passes.FULL_CENSUS_ENV) is None
    passes.pytest_configure(_config(full=True)[0])
    assert os.environ.get(passes.FULL_CENSUS_ENV) == "1"


_CLEARS = re.compile(r"\bclear_compilation_caches\(\)|_compile_card_oracle\.cache_clear\(\)")


def test_a_test_that_empties_the_compile_cache_refills_it():
    """A run compiles the pool once before its first test (`pytest_collection_
    finish`), so every test's time is its own. A test that clears the compile
    caches undoes that for every test after it in its process: the next one to
    walk the pool pays a recompile, ~20 s billed to a stranger. Each function
    that clears must call `rewarm_compile_cache()` once its patch is undone."""
    import ast

    def calls(node, test) -> bool:
        return any(isinstance(n, ast.Call) and test(n.func) for n in ast.walk(node))

    def clears(func) -> bool:
        return (isinstance(func, ast.Name) and func.id == "clear_compilation_caches") or (
            isinstance(func, ast.Attribute) and func.attr == "cache_clear"
            and isinstance(func.value, ast.Attribute) and func.value.attr == "_compile_card_oracle"
        )

    def rewarms(func) -> bool:
        return getattr(func, "id", getattr(func, "attr", None)) == "rewarm_compile_cache"

    offenders = []
    for path in (REPO / "tests").rglob("test_*.py"):
        text = source_text(path)
        if not _CLEARS.search(text):
            continue
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if calls(node, clears) and not calls(node, rewarms):
                    offenders.append(f"{path.relative_to(REPO)}::{node.name}")
    assert not offenders, (
        f"{offenders} clear the compile caches without refilling them: call "
        "tests.passes.rewarm_compile_cache() after the patch is undone"
    )


def test_no_test_is_marked_slow():
    """`slow` was the quick pass's predecessor and is no longer registered: a
    test marked with it would only warn, and run in the quick pass."""
    marked = [
        str(path.relative_to(REPO))
        for path in (REPO / "tests").rglob("*.py")
        if re.search(r"\bpytest\.mark\.slow\b", source_text(path))
    ]
    assert not marked, f"{marked} use the retired `slow` mark: mark them `full`"
