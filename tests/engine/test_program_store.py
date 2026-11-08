"""The compiled-program store (``engine/program_store.py``).

A store that hands a process programs some other engine compiled is a wrong
answer nothing would point at: every card still compiles, just not to what this
code says. So what is pinned here is the invalidation — a store is named by
everything a program can depend on, and the engine reads nothing the name does
not cover — and that the store answers through the compile cache rather than
beside it, so clearing the cache clears it.
"""

from __future__ import annotations

import ast
import os
import pickle
import re
import sys
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import pytest

from engine import program_store
from engine.oracle import compile_card_oracle
from engine.oracle_types import (_COMPILATION_CACHES, OracleProgram,
                                 clear_compilation_caches)
from tests.passes import NO_STORE_ENV as PASSES_NO_STORE_ENV
from tests.passes import rewarm_compile_cache
from tests.source_index import source_text, source_tree

REPO = Path(__file__).resolve().parents[2]


def _stand_in_repo(root: Path) -> None:
    for relative, text in (
        ("engine/oracle.py", "x = 1\n"),
        ("engine/grammar/parser.py", "y = 2\n"),
        ("data/vocabulary/keyword_abilities.json", '["Flying"]'),
        ("cards/lea.json", "[]"),
        ("cards/manifest.json", '{"sets": []}'),
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def test_any_edit_to_what_a_program_depends_on_names_another_store(tmp_path):
    _stand_in_repo(tmp_path)
    first = program_store.fingerprint(tmp_path)
    for relative, text in (
        ("engine/grammar/parser.py", "y = 2  # a comment is an edit too\n"),
        ("engine/grammar/new_family.py", ""),
        ("data/vocabulary/keyword_abilities.json", '["Flying", "Reach"]'),
        ("cards/lea.json", "[{}]"),
    ):
        path = tmp_path / relative
        before = path.read_bytes() if path.exists() else None
        path.write_text(text, encoding="utf-8")
        assert program_store.fingerprint(tmp_path) != first, relative
        if before is None:
            path.unlink()
        else:
            path.write_bytes(before)
    assert program_store.fingerprint(tmp_path) == first, "and undoing each one names it again"


def test_what_compiles_nothing_names_the_same_store(tmp_path):
    _stand_in_repo(tmp_path)
    first = program_store.fingerprint(tmp_path)
    for relative in (
        "engine/ARCHITECTURE.md",
        "engine/__pycache__/oracle.cpython-313.pyc",
        "tests/test_anything.py",
        "web/app.py",
        "cards/notes.txt",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("anything", encoding="utf-8")
    assert program_store.fingerprint(tmp_path) == first


#: Every engine module that reads a file, and the input folder that covers what
#: it reads. A module joining this table names its folder in
#: ``program_store.INPUTS`` first, or a store would outlive an edit to that file.
_FILE_READERS = {
    "engine/card_loader.py": "cards",
    "engine/grammar/vocabulary.py": "data",
    "engine/program_store.py": None,  # the store itself
}


def test_the_engine_reads_no_file_the_fingerprint_does_not_cover():
    """The fingerprint is safe only while it hashes every file a program can
    depend on. The engine's source is all of ``engine/``; its data is whatever
    a module opens — so every call that opens or reads a file is found, and
    each module making one must be in the table above, its folder an input."""
    root = program_store.ROOT
    readers = set()
    for path in sorted((root / "engine").rglob("*.py")):
        for node in ast.walk(ast.parse(source_text(path))):
            func = getattr(node, "func", None) if isinstance(node, ast.Call) else None
            if (isinstance(func, ast.Name) and func.id == "open") or (
                isinstance(func, ast.Attribute)
                and func.attr in {"open", "read_text", "read_bytes"}
            ):
                readers.add(path.relative_to(root).as_posix())
    assert readers == set(_FILE_READERS), (
        "an engine module reads a file the table here does not know about, or "
        "stopped reading one: add its folder to program_store.INPUTS and the "
        f"module to _FILE_READERS — {sorted(readers ^ set(_FILE_READERS))}"
    )
    inputs = {folder for folder, _ in program_store.INPUTS}
    assert {folder for folder in _FILE_READERS.values() if folder} <= inputs

    from engine.card_loader import MANIFEST_PATH
    from engine.grammar.vocabulary import DATA_DIR

    assert DATA_DIR.resolve().is_relative_to(root / "data")
    assert Path(MANIFEST_PATH).resolve().is_relative_to(root / "cards")


def test_a_seeded_answer_is_spent_by_the_cache_clear():
    """What :func:`program_store.seed` hands over lives in the ``lru_cache``
    and nowhere else, so one ``cache_clear()`` and the next call computes."""
    computed = []

    @lru_cache(maxsize=None)
    @program_store.seedable
    def double(n):
        computed.append(n)
        return n * 2

    assert double(3) == 6
    program_store.seed(double, {(1,): "stored", (3,): "stored"})
    assert double(1) == "stored", "a miss is answered from the store"
    assert double(3) == 6, "and an answer already computed is kept"
    assert double(2) == 4 and computed == [3, 2]
    double.cache_clear()
    assert double(1) == 2 and computed == [3, 2, 1], "cleared means computed"


def test_the_compiler_is_seeded_through_its_own_cache(set_pool):
    """The property that keeps a stubbed compile honest: a test that swaps a
    piece of the compiler out clears the caches (``test_front_end_safety``,
    ``test_no_hollow_support``), and a store that survived the clear would
    answer for the stub with the live compile. So the seedable wrapper sits
    directly under ``_compile_card_oracle``'s ``lru_cache`` — what the test
    above shows a clear spends — and seeding fills that cache.

    Shown on a card nobody printed, so no cache is cleared and the pool this
    run compiled stays where it is."""
    from engine import oracle

    wrapper = oracle._compile_card_oracle.__wrapped__
    assert wrapper.__code__ is program_store.seedable(len).__code__
    assert oracle._compile_card_oracle in _COMPILATION_CACHES

    args = ("Program Store Probe", "Instant", "Seeded, never compiled.", (),
            "normal", False)
    stand_in = OracleProgram(False, "unsupported", "a seeded stand-in", "")
    program_store.seed(oracle._compile_card_oracle, {args: stand_in})
    assert oracle._compile_card_oracle(*args) is stand_in

    bolt = set_pool("LEA")["Lightning Bolt"]
    compiled = compile_card_oracle(bolt)
    program_store.seed(oracle._compile_card_oracle, {
        (bolt.name, bolt.primary_type, bolt.oracle_text, bolt.keywords,
         bolt.layout, bolt.is_legendary): stand_in,
    })
    assert compile_card_oracle(bolt) is compiled, (
        "a seed replaced a program this process had already compiled"
    )


def test_a_store_is_read_only_under_the_fingerprint_it_was_written_under(tmp_path):
    path = tmp_path / "programs-written-elsewhere.pickle"
    path.write_bytes(pickle.dumps({"fingerprint": "another engine", "programs": {("X",): 1}}))
    assert program_store.load(path, "this engine") == 0
    assert program_store.load(tmp_path / "pruned.pickle", "this engine") == 0


def test_a_directory_keeps_only_the_newest_stores(tmp_path):
    for age, name in enumerate(["a", "b", "c", "d", "e"]):
        for suffix in (".pickle", ".failed"):
            path = tmp_path / f"programs-{name}{suffix}"
            path.write_bytes(b"")
            os.utime(path, (age, age))
    (tmp_path / "build.lock").write_bytes(b"")

    program_store._prune(tmp_path)

    kept = sorted(path.name for path in tmp_path.iterdir())
    assert kept == [
        "build.lock",
        "programs-c.failed", "programs-c.pickle",
        "programs-d.failed", "programs-d.pickle",
        "programs-e.failed", "programs-e.pickle",
    ]


@pytest.mark.full
def test_the_store_holds_what_this_process_compiles(tmp_path):
    """End to end, the way a large run makes one: built in a subprocess, read
    back here, and compared program by program with this process's own compile
    — which has every test module imported, so a module that changed the
    engine at import would show up here as a difference."""
    from engine import oracle

    engine_print = program_store.fingerprint()
    store = program_store.store_path(tmp_path, engine_print)
    program_store._build_in_subprocess(
        tmp_path, store, program_store.failure_path(tmp_path, engine_print)
    )
    stored = pickle.loads(store.read_bytes())
    assert stored["fingerprint"] == engine_print
    programs = stored["programs"]
    assert len(programs) > 5000, "the store holds the pool, both manifest roles"

    clear_compilation_caches()
    try:
        compiled = {args: oracle._compile_card_oracle(*args) for args in programs}
    finally:
        clear_compilation_caches()
        rewarm_compile_cache()
    differ = sorted(args[0] for args in programs if programs[args] != compiled[args])
    assert not differ, f"the store and this process compile these differently: {differ[:20]}"


# ---------------------------------------------------------------------------
# A script's read: `program_store.warm`
# ---------------------------------------------------------------------------

@pytest.fixture
def script_world(tmp_path, monkeypatch):
    """A script's process allowed the store, with the build and the read
    recorded rather than run: what is pinned is who builds and who reads."""
    directory = tmp_path / "store"
    engine_print = "e" * 64
    monkeypatch.setattr(program_store, "DIRECTORY", directory)
    monkeypatch.setattr(program_store, "fingerprint", lambda root=None: engine_print)
    monkeypatch.delenv(program_store.NO_STORE_ENV, raising=False)
    # A script's process, not this test process: nothing read yet, and no
    # test runner that reads the store for it.
    monkeypatch.setattr(program_store, "_test_runner_reads", False)
    monkeypatch.setattr(program_store, "_warmed", None)
    world = SimpleNamespace(
        built=[], loaded=[],
        store=program_store.store_path(directory, engine_print),
        failed=program_store.failure_path(directory, engine_print),
    )

    def build(directory, store, failed):
        world.built.append(store)
        store.write_bytes(b"")

    def load(path, read_under):
        assert read_under == engine_print, "a store is read under the engine this process runs"
        world.loaded.append(path)
        return 7

    monkeypatch.setattr(program_store, "_build_in_subprocess", build)
    monkeypatch.setattr(program_store, "load", load)
    return world


def test_the_first_script_without_a_store_builds_it_and_every_one_reads_it(script_world, monkeypatch):
    assert program_store.warm() == 7
    monkeypatch.setattr(program_store, "_warmed", None)  # the next script's process
    assert program_store.warm() == 7
    assert script_world.built == [script_world.store]
    assert script_world.loaded == [script_world.store, script_world.store]


def test_a_process_reads_the_store_once_however_many_callers_ask(script_world):
    """A script that warms and then imports the web layer, which warms as it
    loads the catalog, reads the store one time."""
    assert program_store.warm() == 7
    assert program_store.warm() == 7
    assert script_world.loaded == [script_world.store]


def test_a_test_process_leaves_the_store_to_the_test_runner(script_world, monkeypatch):
    monkeypatch.setattr(program_store, "_test_runner_reads", True)
    assert program_store.warm() == 0
    assert script_world.built == [] and script_world.loaded == []


def test_this_test_process_is_the_test_runners():
    """`tests/passes.py` marks every test process it seeds, so the web layer's
    import (collection imports it through `tests/helpers.py`) reads nothing a
    second time and builds nothing for a run that named a file."""
    if os.environ.get(program_store.NO_STORE_ENV):
        pytest.skip("the store is turned off for this run")
    assert program_store._test_runner_reads


def test_the_web_layer_reads_the_store_before_it_compiles_the_pool():
    """`web/runtime.py` sorts the shipped pool into behaviour classes as it
    loads, which compiled every card on each server start (~18 s)."""
    runtime = source_tree(REPO / "web" / "runtime.py")
    warm_line = compile_line = None
    for statement in runtime.body:
        for node in ast.walk(statement):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name == "warm" and warm_line is None:
                warm_line = statement.lineno
            if name == "peers_by_card" and compile_line is None:
                compile_line = statement.lineno
    assert compile_line is not None, "web/runtime.py no longer compiles at import — drop this test"
    assert warm_line is not None and warm_line < compile_line, (
        "web/runtime.py compiles the pool before reading the compiled-program store"
    )


def test_a_script_not_asked_to_build_only_reads(script_world):
    program_store.warm(build=False)
    assert script_world.built == [] and script_world.loaded == [script_world.store]


def test_a_failed_build_is_not_retried_by_each_script_after_it(script_world):
    script_world.failed.parent.mkdir(parents=True)
    script_world.failed.write_text("the first builder's stderr", encoding="utf-8")
    program_store.warm()
    assert script_world.built == [], "every later script would run the failing build in turn"


def test_the_store_turned_off_is_neither_built_nor_read(script_world, monkeypatch):
    monkeypatch.setenv(program_store.NO_STORE_ENV, "1")
    assert program_store.warm() == 0
    assert script_world.built == [] and script_world.loaded == []


def test_a_store_that_cannot_be_read_leaves_the_script_compiling(script_world, monkeypatch, capsys):
    """The store is a shortcut, never a requirement: whatever goes wrong
    reading it, the script compiles as it did before there was one."""
    def unreadable(path, read_under):
        raise pickle.UnpicklingError("a truncated file")

    monkeypatch.setattr(program_store, "load", unreadable)
    assert program_store.warm() == 0
    assert "compiling in-process" in capsys.readouterr().err


def test_tests_and_scripts_turn_the_store_off_by_one_name():
    assert PASSES_NO_STORE_ENV == program_store.NO_STORE_ENV


#: Scripts the merge path runs that walk no compiled pool, and why. Reading the
#: store would cost each a fingerprint, and with none built yet a build, for
#: nothing (measured 2026-11-08 by the compile cache's misses after a run).
_WALKS_NO_POOL = {
    "check_all.py": "runs each check in a process of its own",
    "grammar_coverage.py": "parses each line through the grammar; compiles 83 cards",
    "rules_progress.py": "reads the tests' `cr` markers",
    "fetch_vocabulary.py": "checks that the vocabulary catalogs are present",
}


def _merge_path_scripts() -> set[str]:
    """Every script the integrator's per-merge regeneration, its gate and
    `check_all` run, read off the runners themselves rather than listed."""
    regen = source_text(REPO / "scripts" / "integration" / "regen.sh")
    loop = re.search(r"for s in ([a-z_ ]+); do", regen)
    assert loop, "regen.sh's tracker loop moved — update this extraction"
    named = {f"{name}.py" for name in loop.group(1).split()}
    for runner in ("regen.sh", "gate.sh"):
        text = source_text(REPO / "scripts" / "integration" / runner)
        named |= set(re.findall(r'"\$PY" scripts/([a-z_]+\.py)', text))
    sys.path.insert(0, str(REPO / "scripts"))
    try:
        import check_all
    finally:
        sys.path.remove(str(REPO / "scripts"))
    for _, argv in (*check_all.COMMANDS, *check_all.FRESHNESS_COMMANDS):
        assert argv[0].startswith("scripts/"), f"check_all runs {argv} — not a script this census can read"
        named.add(Path(argv[0]).name)
    assert {"parse_coverage.py", "set_progress.py", "oracle_diff.py"} <= named, named
    return named


def _reads_the_store(script: Path) -> bool:
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "warm"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "program_store"
        for node in ast.walk(source_tree(script))
    )


def test_every_merge_path_script_that_walks_the_pool_reads_the_store():
    """`regen.sh` runs after every merge, and five of its seven processes each
    compiled the whole pool (~18 s apiece) before they read the store."""
    named = _merge_path_scripts()
    stale = sorted(set(_WALKS_NO_POOL) - named)
    assert not stale, f"exempted scripts the merge path no longer runs: {stale}"
    unread = sorted(
        name for name in named - set(_WALKS_NO_POOL)
        if not _reads_the_store(REPO / "scripts" / name)
    )
    assert not unread, (
        f"merge-path scripts that compile the pool without reading the store: {unread}. "
        "Call `program_store.warm()` before the first compile, or exempt the script "
        "in _WALKS_NO_POOL with the reason it walks no pool."
    )
