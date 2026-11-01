"""The quick pass and the full pass.

**`pytest` runs the quick pass; `pytest --full` runs the full pass**, and the
full pass is the promotion gate's (SET_PLAYBOOK Phase 4), run once a set is
otherwise ready to ship. Measured on 2026-10-31 with every test timed warm
(below), 163 test functions (234 of 34,762 tests) — the seeded AI-game
batches and the whole-pool censuses that drive the engine card by card —
took 9,274 of the full pass's 10,487 test-seconds; at `-n 12` the full pass
ran in 1,412 s and the quick pass in under 180. So:

- **A test marked `@pytest.mark.full` runs only in the full pass.** The mark
  is for a test that takes ten seconds or more on this machine — below that
  sit the structural guards and source scans the quick pass is for, and a
  guard a convention depends on stays here a little over the line — and
  it goes on every test that reads a heavy module fixture, since the
  fixture's cost lands on whichever of them runs first. The quick pass
  names, at the end of the run, any unmarked test whose call took twice the
  line (a busy machine, and a worker's first compile of the pool, ~20 s,
  inflate one reading), so the list does not rot by addition.
- **The full pass also runs the sampled censuses whole**: it sets
  ``MTG_FULL_CENSUS`` (:data:`FULL_CENSUS_ENV`), which ``tests.helpers.
  stable_sample`` reads. The quick pass runs each census's stable sample.
- **A file or test named on the command line runs whole** — `pytest
  tests/ai/test_ai_simulator.py` runs its full-marked tests too — because
  naming a file is asking about it. A folder, or no argument, is the quick
  pass. An IDE running one test passes its node id, so it runs.
- **A large run compiles the pool once per engine, not once per process.**
  Before collection (which compiles the pool, below) each process fills its
  compile cache from the store ``engine/program_store.py`` writes to
  ``.program_store/``, named by a hash of the engine's source, the vocabulary
  and the card files: a fraction of a second, where compiling took ~17 s in
  every worker. The first worker of a folder or whole-suite run to find no
  store for its engine builds it in a subprocess that imports nothing but the
  engine, and the others wait for it; a run naming files reads one only if it
  is there. ``MTG_NO_PROGRAM_STORE=1`` turns it off.

The hooks are imported into ``tests/conftest.py``, which is what registers them.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

FULL_MARK = "full"
#: Set by the full pass; read by ``tests.helpers.full_census``.
FULL_CENSUS_ENV = "MTG_FULL_CENSUS"
#: What earns the mark, measured on a quiet machine.
FULL_THRESHOLD_SECONDS = 10.0
#: An unmarked quick-pass test whose call took this long is named at the end of the run.
REPORT_THRESHOLD_SECONDS = 2 * FULL_THRESHOLD_SECONDS
#: Set to compile the pool in every process rather than read it from the store.
NO_STORE_ENV = "MTG_NO_PROGRAM_STORE"

_slow_unmarked: list[tuple[float, str]] = []


def pytest_addoption(parser):
    parser.addoption(
        "--full", action="store_true", default=False,
        help="the full pass: also run tests marked `full` (seeded AI games, "
             "whole-pool censuses) and every sampled census whole — the "
             "promotion gate's run (tests/passes.py)",
    )


def is_full_pass(config) -> bool:
    return bool(config.getoption("full", default=False))


def pytest_configure(config):
    if is_full_pass(config):
        # Before xdist starts its workers, so they inherit it.
        os.environ[FULL_CENSUS_ENV] = "1"
    _note_the_engine(config)


def _named_files(config) -> set[Path]:
    """The test files the command line names, alone or by a node id in them."""
    base = Path(config.invocation_params.dir)
    named = set()
    for arg in config.args:
        path = Path(str(arg).split("::", 1)[0])
        if not path.is_absolute():
            path = base / path
        if path.is_file():
            named.add(path.resolve())
    return named


def pytest_collection_modifyitems(config, items):
    # A collect-only session lists every test: an IDE's test tree is one, and
    # a full-pass test it cannot show is one nobody can click to run.
    if is_full_pass(config) or config.option.collectonly:
        return
    named = _named_files(config)
    left = [
        item for item in items
        if item.get_closest_marker(FULL_MARK) is not None
        and Path(item.path).resolve() not in named
    ]
    if not left:
        return
    config.hook.pytest_deselected(items=left)
    leaving = set(map(id, left))
    items[:] = [item for item in items if id(item) not in leaving]


#: A run selecting at least this many tests compiles the pool before its first.
WARM_FROM_ITEMS = 2000


def pytest_collection_finish(session):
    """Compile the pool once, before the first test, in a large run.

    Otherwise whichever test first walks the compiled pool in a process pays
    for compiling all of it — ~20 s, more on a busy machine — and which test
    that is changes from run to run: a 0.2 s sweep read 30 s, and the slow-test
    report above named it. Paid here, the cost is the run's and every test's
    reading is its own. A small run (one file, one folder of guards) skips it,
    since it may need none of the pool. Runs in each xdist worker, which is
    where the tests are — and where the store, when there is one for this
    engine, filled the cache at configure time (``_note_the_engine``)."""
    global _warmed
    if session.config.option.collectonly or len(session.items) < WARM_FROM_ITEMS:
        return
    _compile_the_pool()
    _warmed = True


_warmed = False


def _compile_the_pool() -> None:
    from engine.card_loader import load_cards, manifest_set_paths
    from engine.oracle import compiled_units

    _seed_from_the_store()
    compiled_units(load_cards(manifest_set_paths(include_measured=True)))


#: The store's folder, when this process may use the store; None when it may not.
_store_dir: Path | None = None
#: The engine this process imported, as ``program_store.fingerprint`` read it
#: at configure time — the programs a store may hand it are that engine's.
_engine_print: str | None = None


def _note_the_engine(config) -> None:
    """Record which engine this process runs, and seed it from the store.

    At configure time, before collection, because collection compiles the
    pool: ``tests/helpers.py`` imports ``web.app``, whose ``runtime`` sorts the
    shipped pool into behaviour classes as it loads, and three test files in
    four import the helpers. Seeded any later, the store would arrive after
    the compile it is for. A run that names files only reads a store that is
    there — it may need none of the pool, and building one costs ~18 s — while
    a folder or the whole suite builds one first if none is.

    The fingerprint read here is compared with one read again at warm-up
    (:func:`_seed_from_the_store`). The store is its own folder rather than
    pytest's cache: the gate's runs turn that plugin off
    (``scripts/integration/gate.sh``), and the full pass is one of them."""
    global _store_dir, _engine_print
    if os.environ.get(NO_STORE_ENV):
        return
    if not hasattr(config, "workerinput") and getattr(config.option, "numprocesses", None):
        return  # the xdist controller: its workers collect and run the tests
    from engine import program_store

    _engine_print = program_store.fingerprint()
    _store_dir = program_store.DIRECTORY
    _seed_from_the_store(build=not (config.option.collectonly or _named_files(config)))


def _seed_from_the_store(*, build: bool = False) -> None:
    """Fill the compile cache from the store — first building it, if *build*
    and no process has. On any failure the caller's compile does the work, as
    it did before the store: the store is a shortcut, never a requirement."""
    if _store_dir is None:
        return
    from engine import program_store

    try:
        if program_store.fingerprint() != _engine_print:
            sys.stderr.write(
                "passes: engine sources changed since this run started; "
                "compiling the pool in-process\n"
            )
            return
        _store_dir.mkdir(parents=True, exist_ok=True)
        store = program_store.store_path(_store_dir, _engine_print)
        if build and not store.exists():
            from tests.memory_guard import exclusive

            with exclusive(_store_dir / "build.lock"):
                failed = program_store.failure_path(_store_dir, _engine_print)
                if not store.exists() and not failed.exists():
                    _build_the_store(_store_dir, store, failed)
        program_store.load(store, _engine_print)
    except Exception as error:  # noqa: BLE001 - see the docstring
        sys.stderr.write(f"passes: compiled-program store unused ({error!r})\n")


_BUILD = "import sys; from engine.program_store import build; build(sys.argv[1])"


def _build_the_store(directory: Path, store: Path, failed: Path) -> None:
    # A subprocess, not this process: by now collection has imported every
    # test module, and nothing a test module did to the engine may be written
    # down for the next run to read.
    try:
        result = subprocess.run(
            [sys.executable, "-c", _BUILD, str(directory)],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, timeout=600,
        )
        why = result.stderr[-4000:] or f"exit {result.returncode} and no store written"
    except subprocess.TimeoutExpired:
        why = "the build ran past 600 s"
    if not store.exists():
        # Recorded, so the workers waiting on the lock compile for themselves
        # rather than each running the same failing build in turn.
        failed.write_text(why, encoding="utf-8")
        sys.stderr.write(f"passes: the compiled-program store was not built; see {failed}\n")


def rewarm_compile_cache() -> None:
    """Refill the compile cache a test just emptied, if this run warmed it.

    A test that patches the compiler clears the caches on both sides of the
    patch, and the next test in that process to walk the pool would pay the
    recompile — a stranger's bill, and a timing that names the wrong test.
    Called after the patch is undone, it charges the test that cleared — a
    read of the store now, rather than a compile.
    `tests/engine/test_passes.py` holds every clearing function to calling it."""
    if _warmed:
        _compile_the_pool()


def pytest_runtest_logreport(report):
    # On the xdist controller every worker's reports arrive here, durations
    # and keywords included.
    if report.when != "call" or FULL_MARK in report.keywords:
        return
    if report.duration >= REPORT_THRESHOLD_SECONDS:
        _slow_unmarked.append((report.duration, report.nodeid))


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    if is_full_pass(config) or hasattr(config, "workerinput"):
        return
    terminalreporter.write_line(
        "quick pass: tests marked `full` and the censuses' unsampled rows were "
        "left for `pytest --full` (tests/passes.py)"
    )
    if _slow_unmarked:
        terminalreporter.write_line(
            f"quick pass: {len(_slow_unmarked)} unmarked test(s) took "
            f"{REPORT_THRESHOLD_SECONDS:.0f}s or more — make each faster or mark it "
            "@pytest.mark.full (a cold worker's first pool compile, ~20 s, can land "
            "on one test once):"
        )
        for seconds, nodeid in sorted(_slow_unmarked, reverse=True)[:15]:
            terminalreporter.write_line(f"  {seconds:6.1f}s  {nodeid}")
