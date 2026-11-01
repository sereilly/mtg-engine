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
from functools import lru_cache
from pathlib import Path

import pytest

from engine import program_store
from engine.oracle import compile_card_oracle
from engine.oracle_types import (_COMPILATION_CACHES, OracleProgram,
                                 clear_compilation_caches)
from tests.passes import _build_the_store, rewarm_compile_cache
from tests.source_index import source_text


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
    _build_the_store(tmp_path, store, program_store.failure_path(tmp_path, engine_print))
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
