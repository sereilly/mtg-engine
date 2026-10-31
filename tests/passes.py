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

The hooks are imported into ``tests/conftest.py``, which is what registers them.
"""

from __future__ import annotations

import os
from pathlib import Path

FULL_MARK = "full"
#: Set by the full pass; read by ``tests.helpers.full_census``.
FULL_CENSUS_ENV = "MTG_FULL_CENSUS"
#: What earns the mark, measured on a quiet machine.
FULL_THRESHOLD_SECONDS = 10.0
#: An unmarked quick-pass test whose call took this long is named at the end of the run.
REPORT_THRESHOLD_SECONDS = 2 * FULL_THRESHOLD_SECONDS

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
    where the tests are."""
    global _warmed
    if session.config.option.collectonly or len(session.items) < WARM_FROM_ITEMS:
        return
    _compile_the_pool()
    _warmed = True


_warmed = False


def _compile_the_pool() -> None:
    from engine.card_loader import load_cards, manifest_set_paths
    from engine.oracle import compiled_units

    compiled_units(load_cards(manifest_set_paths(include_measured=True)))


def rewarm_compile_cache() -> None:
    """Refill the compile cache a test just emptied, if this run warmed it.

    A test that patches the compiler clears the caches on both sides of the
    patch, and the next test in that process to walk the pool would pay the
    recompile — a stranger's bill, and a timing that names the wrong test.
    Called after the patch is undone, it charges the test that cleared.
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
