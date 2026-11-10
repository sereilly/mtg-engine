"""The quick pass and the full pass select what tests/passes.py says they do.

A selection hook that drops too much reads green — the tests it dropped report
nothing — so its rules are pinned here on stand-in items rather than trusted.
So is who builds the compiled-program store and who reads it: a worker that
read a store for another engine, or every worker rebuilding a failed one in
turn, would also read green.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

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
    # Configuring also notes this process's engine for the store; not this test's business.
    monkeypatch.setattr(passes, "_note_the_engine", lambda config: None)
    passes.pytest_configure(_config()[0])
    import os

    assert os.environ.get(passes.FULL_CENSUS_ENV) is None
    passes.pytest_configure(_config(full=True)[0])
    assert os.environ.get(passes.FULL_CENSUS_ENV) == "1"


@pytest.fixture
def store_world(tmp_path, monkeypatch):
    """A process allowed the store, with the build and the read recorded
    rather than run: what is pinned is who builds and who reads."""
    from engine import program_store

    engine_print = program_store.fingerprint()
    directory = tmp_path / "store"
    monkeypatch.setattr(passes, "_store_dir", directory)
    monkeypatch.setattr(passes, "_engine_print", engine_print)
    world = SimpleNamespace(
        directory=directory, built=[], loaded=[],
        store=program_store.store_path(directory, engine_print),
        failed=program_store.failure_path(directory, engine_print),
    )

    def build(directory, store, failed):
        world.built.append(store)
        store.write_bytes(b"")

    monkeypatch.setattr(program_store, "_build_in_subprocess", build)
    monkeypatch.setattr(program_store, "load", lambda path, _: world.loaded.append(path) or 0)
    return world


def test_the_first_process_without_a_store_builds_it_and_every_one_reads_it(store_world):
    passes._seed_from_the_store(build=True)
    passes._seed_from_the_store(build=True)
    assert store_world.built == [store_world.store]
    assert store_world.loaded == [store_world.store, store_world.store]


def test_a_process_not_asked_to_build_only_reads(store_world):
    passes._seed_from_the_store()
    assert store_world.built == [] and store_world.loaded == [store_world.store]


def test_a_failed_build_is_not_retried_by_each_process_waiting_on_it(store_world):
    store_world.directory.mkdir()
    store_world.failed.write_text("the first builder's stderr", encoding="utf-8")
    passes._seed_from_the_store(build=True)
    assert store_world.built == [], "every waiting worker would run the failing build in turn"


def test_an_engine_edited_since_the_run_started_reads_no_store(store_world, monkeypatch):
    """The store read must be the one for the code this process imported."""
    monkeypatch.setattr(passes, "_engine_print", "the engine before the edit")
    passes._seed_from_the_store(build=True)
    assert store_world.built == [] and store_world.loaded == []


@pytest.fixture
def before_the_web_layer(store_world, monkeypatch):
    """A test process whose collection is importing the web layer, which asks
    `program_store.warm` before compiling the shipped pool."""
    from engine import program_store

    monkeypatch.delenv(passes.NO_STORE_ENV, raising=False)
    monkeypatch.setattr(program_store, "_test_runner_reader", passes._read_before_the_pool_compiles)
    return store_world


def test_a_named_file_run_builds_the_store_as_the_pool_is_about_to_compile(before_the_web_layer, monkeypatch):
    """After an engine edit no store is there, and a run naming one per-set
    file compiled the pool in every worker: 22 s, where reading a store takes
    4 (2026-11-08). The compile was coming either way, so the build costs
    nothing extra and the next run reads it."""
    from engine import program_store

    monkeypatch.setattr(passes, "_seeded_at_configure", False)
    monkeypatch.setattr(passes, "_builds_before_the_compile", True)
    program_store.warm()
    assert before_the_web_layer.built == [before_the_web_layer.store]
    assert before_the_web_layer.loaded == [before_the_web_layer.store]


def test_a_run_whose_configure_read_filled_the_cache_reads_nothing_more(before_the_web_layer, monkeypatch):
    from engine import program_store

    monkeypatch.setattr(passes, "_seeded_at_configure", True)
    monkeypatch.setattr(passes, "_builds_before_the_compile", True)
    assert program_store.warm() == 0
    assert before_the_web_layer.built == [] and before_the_web_layer.loaded == []


def test_an_ide_discovery_reads_a_store_but_never_builds_one(before_the_web_layer, monkeypatch):
    from engine import program_store

    monkeypatch.setattr(passes, "_seeded_at_configure", False)
    monkeypatch.setattr(passes, "_builds_before_the_compile", False)
    program_store.warm()
    assert before_the_web_layer.built == []
    assert before_the_web_layer.loaded == [before_the_web_layer.store]


def test_the_store_is_read_before_collection_and_built_only_for_a_large_run(monkeypatch):
    """Collection compiles the pool (``tests/helpers.py`` imports ``web.app``),
    so configure time is the last moment the store can save that compile. A
    run naming files may need none of the pool and does not pay for a build;
    an IDE's discovery reads a store but never builds one."""
    monkeypatch.setattr(passes, "_store_dir", None)
    monkeypatch.setattr(passes, "_engine_print", None)
    monkeypatch.setattr(passes, "_seeded_at_configure", passes._seeded_at_configure)
    monkeypatch.setattr(passes, "_builds_before_the_compile", passes._builds_before_the_compile)
    monkeypatch.delenv(passes.NO_STORE_ENV, raising=False)
    seeded = []
    monkeypatch.setattr(
        passes, "_seed_from_the_store", lambda *, build: seeded.append(build) or 0
    )

    def note(*, collectonly=False, numprocesses=None, worker=False, args=("tests",)):
        config, _ = _config(collectonly=collectonly, args=args)
        config.option.numprocesses = numprocesses
        if worker:
            config.workerinput = {}
        seeded.clear()
        passes._note_the_engine(config)
        monkeypatch.setattr(passes, "_store_dir", None)
        return seeded[0] if seeded else None

    assert note() is True and note(numprocesses=4, worker=True) is True
    assert note(args=(str(HERE.relative_to(REPO)),)) is False, "a named file only reads"
    assert note(collectonly=True) is False, "an IDE's discovery only reads"
    assert note(numprocesses=4) is None, "the xdist controller collects nothing"
    monkeypatch.setenv(passes.NO_STORE_ENV, "1")
    assert note() is None


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


def test_quick_keeps_the_quick_pass_in_the_files_named():
    """`--quick`: a picker's list of files is a question about their quick
    tests, not an hour of AI censuses inside them."""
    config, _ = _config(args=(str(HERE.relative_to(REPO)),))
    config.getoption = lambda name, default=None: name == "quick" or default
    assert _run(config) == ["quick_here", "quick_there"]


@pytest.mark.parametrize("expression, selects", [
    ("full", True),
    ("full and not ui", True),
    ("not full", False),
    ("not cr", False),          # picks an unmarked test too
    ("full or not full", False),
    ("cr", False),
    ("", False),
])
def test_a_marker_expression_that_picks_the_full_tests_is_the_full_pass(expression, selects):
    assert passes.selects_full_tests(expression) is selects


def test_minus_m_full_turns_the_full_pass_on(monkeypatch):
    """`pytest -m full` collected nothing (exit 5): the quick pass dropped the
    full tests before the expression ran."""
    monkeypatch.setenv(passes.FULL_CENSUS_ENV, "0")
    monkeypatch.delenv(passes.FULL_CENSUS_ENV)
    monkeypatch.setattr(passes, "_note_the_engine", lambda config: None)
    option = SimpleNamespace(markexpr="full", full=False, collectonly=False)
    config = SimpleNamespace(option=option, getoption=lambda name, default=None: getattr(option, name, default))
    passes.pytest_configure(config)
    assert option.full is True and passes.is_full_pass(config)
    import os

    assert os.environ.get(passes.FULL_CENSUS_ENV) == "1"


def test_a_run_merges_its_times_by_node_id(tmp_path, monkeypatch):
    """A run of a few files refreshes their rows and keeps the rest — the last
    full pass's times stand until something re-runs them."""
    passes.timings_path(tmp_path).write_text(
        '{"a.py::kept": [9.0, true], "a.py::rerun": [1.0, false]}', encoding="utf-8"
    )
    monkeypatch.setattr(passes, "_timings", {})
    for when, seconds in (("setup", 0.5), ("call", 2.0), ("teardown", 0.25)):
        passes.pytest_runtest_logreport(SimpleNamespace(
            nodeid="a.py::rerun", when=when, duration=seconds, keywords={},
        ))
    config = SimpleNamespace(option=SimpleNamespace(collectonly=False), rootpath=tmp_path)
    passes.pytest_sessionfinish(SimpleNamespace(config=config), 0)
    assert passes.read_timings(tmp_path) == {
        "a.py::kept": [9.0, True], "a.py::rerun": [2.75, False],
    }


def test_a_promoted_run_says_so_in_its_header(monkeypatch):
    monkeypatch.setenv(passes.PROMOTE_ENV, "DST")
    assert "rehearsal" in " ".join(passes.pytest_report_header(None))
    monkeypatch.delenv(passes.PROMOTE_ENV)
    assert passes.pytest_report_header(None) == []


def test_the_header_names_the_engines_promote_variable():
    from engine.card_loader import PROMOTE_ENV

    assert passes.PROMOTE_ENV == PROMOTE_ENV
