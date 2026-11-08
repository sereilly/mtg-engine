"""The compiled pool on disk: compiled once per engine version, not once per process.

Compiling every card of both manifest roles takes ~17 s, and every process that
walks the compiled pool paid it again — each xdist worker of a large test run
(``tests/passes.py`` compiles the pool before the first test) and each run after
it. A program is a function of the card's printed fields (the arguments of
``oracle._compile_card_oracle``), the engine's source and the vocabulary
catalogs the grammar loads, so the pool compiled once can be read back by any
process running the same engine. Reading it back takes well under a second.

**What names a store is everything a program can depend on.**
:func:`fingerprint` hashes the content of every ``engine/**/*.py``, every file
under ``data/`` and every ``cards/*.json`` (the pool the store holds, so a
re-ingest rebuilds it rather than leaving the new cards to compile in every
process), with the Python version and :data:`FORMAT`. Any edit to engine code,
a comment included, names a different file, and a file is read only under the
name it was written under. That is the whole of the invalidation: by content,
never by modification time or commit, and with nothing to compare against a
stale file because a stale file is never opened.

**The store answers through the compiler's own cache, never beside it.**
:func:`seed` hands each stored program to ``_compile_card_oracle`` as its answer
for that argument tuple — :func:`seedable` sits under the ``lru_cache`` and
answers a miss from the store while seeding — so a program lands where
compiling it would have put it and leaves with the same ``cache_clear()``. A
test that swaps a piece of the compiler out and clears the caches
(``oracle_types.clear_compilation_caches``, or ``cache_clear`` alone) therefore
compiles under its stub: there is no second table for a stale answer to hide in.

**It is written only by :func:`build`, in a process that imported nothing but
the engine** (:func:`ensure` runs it as a subprocess), so nothing a test or a
script patched, at import or in a fixture, can be persisted: a poisoned answer
cannot outlive the process that computed it. The fingerprint is read before the
compile and again after it, and nothing is written if the two differ — an
engine file edited mid-build belongs to neither the code before nor the code
after.

**Three kinds of process read it, each at a moment nothing should have patched
the compiler yet.** A test process reads it at configure time
(``tests/passes.py``), and :func:`warm` there asks the test runner. A script
that walks the whole pool calls :func:`warm` before its first compile —
``scripts/integration/regen.sh`` runs five such scripts after every merge, and
they compiled the pool five times. And the web layer calls it as
``web/runtime.py`` loads the catalog, so the server starts in a couple of
seconds rather than eighteen. It is deliberately *not* read on a process's
first compile miss: a scratch probe that patches a production and then compiles
a card would be handed what the unpatched compiler wrote. A probe that patches
the compiler *before* importing the web layer sets :data:`NO_STORE_ENV`, or
clears the compile caches after the import.
"""

from __future__ import annotations

import functools
import hashlib
import os
import pickle
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

#: The store file's layout. Part of the fingerprint, so changing what a file
#: holds is a bump here and never a reader that has to tell two layouts apart.
FORMAT = 1
ROOT = Path(__file__).resolve().parent.parent
#: Where a checkout keeps its stores (gitignored). A worktree has its own.
DIRECTORY = ROOT / ".program_store"
#: What a program can depend on besides its arguments, as (folder, glob) under
#: :data:`ROOT`. ``engine/ARCHITECTURE.md`` is left out: prose compiles nothing.
INPUTS = (("engine", "**/*.py"), ("data", "**/*"), ("cards", "*.json"))
#: How many stores a directory keeps, newest first. Older engines' are deleted
#: as a new one is written, so switching branches back and forth stays warm.
KEEP = 3
#: Set to compile in every process rather than read a store, tests and scripts
#: alike (``tests/passes.py`` reads the same name before importing the engine).
NO_STORE_ENV = "MTG_NO_PROGRAM_STORE"
#: How long a build may run before the waiting processes give up on it.
BUILD_TIMEOUT_SECONDS = 600

#: In a test process, how the test runner reads the store
#: (:func:`leave_to_the_test_runner`); :func:`warm` hands over to it.
_test_runner_reader = None
#: How many programs :func:`warm` read into this process, once it has.
_warmed: int | None = None

#: While :func:`seed` runs: the stored programs not yet handed over.
_seeding: dict | None = None
#: While :func:`build` runs: every program the compiler computed.
_recording: dict | None = None


def fingerprint(root: Path = ROOT) -> str:
    """A digest of everything a compiled program depends on but its arguments."""
    digest = hashlib.sha256(f"{FORMAT}\0{sys.version}\0".encode())
    for folder, pattern in INPUTS:
        for path in sorted((root / folder).glob(pattern)):
            if "__pycache__" in path.parts or not path.is_file():
                continue
            data = path.read_bytes()
            digest.update(path.relative_to(root).as_posix().encode() + b"\0")
            digest.update(len(data).to_bytes(8, "little"))
            digest.update(data)
    return digest.hexdigest()


def store_path(directory, engine_print: str) -> Path:
    """Where the store for *engine_print* lives in *directory*."""
    return Path(directory) / f"programs-{engine_print[:24]}.pickle"


def failure_path(directory, engine_print: str) -> Path:
    """Where a builder records that the store for *engine_print* could not be
    built, so the processes waiting on it compile for themselves instead of
    each trying again in turn."""
    return store_path(directory, engine_print).with_suffix(".failed")


def seedable(func):
    """Let :func:`seed` answer for *func*, and :func:`build` record it.

    Applied *inside* ``functools.lru_cache`` (nearest the ``def``), so it runs
    only on a cache miss and costs nothing on a hit::

        @compilation_cache
        @lru_cache(maxsize=None)
        @seedable
        def _compile_card_oracle(...): ...

    Outside :func:`seed` and :func:`build` it is one call through.
    """
    @functools.wraps(func)
    def answer(*args, **kwargs):
        if _seeding is not None and not kwargs:
            program = _seeding.pop(args, None)
            if program is not None:
                return program
        program = func(*args, **kwargs)
        if _recording is not None and not kwargs:
            _recording[args] = program
        return program

    return answer


def seed(compiler, programs: dict) -> None:
    """Put each of *programs* (argument tuple to program) into *compiler*'s
    cache, as calling it with those arguments would have."""
    global _seeding
    _seeding = dict(programs)
    try:
        for args in programs:
            compiler(*args)
    finally:
        _seeding = None


def build(directory) -> Path | None:
    """Compile the pool, both manifest roles, and write it to *directory*.

    Returns the file written, or None when an engine file changed while the
    pool compiled. Meant for a fresh process: a program already in this one's
    cache is a hit, and a hit is not recorded.
    """
    global _recording
    from .card_loader import load_cards, manifest_set_paths
    from .oracle import compiled_units

    before = fingerprint()
    _recording = {}
    try:
        compiled_units(load_cards(manifest_set_paths(include_measured=True)))
        programs = _recording
    finally:
        _recording = None
    if fingerprint() != before:
        return None
    path = store_path(directory, before)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Written whole under another name and renamed into place, so a reader
    # finds either no file or all of one.
    partial = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with open(partial, "wb") as handle:
            pickle.dump(
                {"fingerprint": before, "programs": programs}, handle,
                protocol=pickle.HIGHEST_PROTOCOL,
            )
        os.replace(partial, path)
    finally:
        partial.unlink(missing_ok=True)
    _prune(path.parent)
    return path


def load(path: Path, engine_print: str) -> int:
    """Seed the compiler from the store at *path*; how many programs it held.

    0 when there is no file (another run may have pruned it) or it was written
    under another fingerprint than *engine_print*, the engine this process runs.
    """
    from .oracle import _compile_card_oracle

    try:
        with open(path, "rb") as handle:
            stored = pickle.load(handle)
    except FileNotFoundError:
        return 0
    if stored.get("fingerprint") != engine_print:
        return 0
    seed(_compile_card_oracle, stored["programs"])
    return len(stored["programs"])


def ensure(directory, engine_print: str, *, build: bool = True) -> Path:
    """The store for *engine_print* in *directory*, built first when *build*
    and nobody has built it.

    Of the processes that find no store, the first builds it while holding
    ``build.lock`` and the rest wait on the lock, then read what it wrote. A
    build that fails is recorded (:func:`failure_path`), so the waiting
    processes, and every later one for that engine, compile for themselves
    rather than each running the same failing build in turn. The path comes
    back whether or not a file is there: :func:`load` answers 0 for none.
    """
    directory = Path(directory)
    path = store_path(directory, engine_print)
    if build and not path.exists():
        directory.mkdir(parents=True, exist_ok=True)
        with _locked(directory / "build.lock"):
            failed = failure_path(directory, engine_print)
            if not path.exists() and not failed.exists():
                _build_in_subprocess(directory, path, failed)
    return path


def warm(*, build: bool = True) -> int:
    """Fill this process's compile cache from the store for the engine it
    runs, building the store first if *build* and none is there; how many
    programs it read.

    For a script about to walk the whole pool, and the web layer as it loads
    the catalog, called before anything else compiles a card (see the module
    docstring for why that moment and no other). A script that compiles a few
    dozen cards — one simulated game's decks — reads a fingerprint and 9,000
    programs to save less than that, so it does not call this. A process reads
    the store once: a script that warms and then imports the web layer pays
    for one read. In a test process the test runner decides (its reader is
    asked instead). 0, and the caller compiles as it always did, when
    :data:`NO_STORE_ENV` is set or the store cannot be built or read: the
    store is a shortcut, never a requirement.
    """
    global _warmed
    if os.environ.get(NO_STORE_ENV):
        return 0
    if _test_runner_reader is not None:
        return _test_runner_reader()
    if _warmed is not None:
        return _warmed
    try:
        engine_print = fingerprint()
        read = load(ensure(DIRECTORY, engine_print, build=build), engine_print)
    except Exception as error:  # noqa: BLE001 - see the docstring
        sys.stderr.write(f"program_store: unused ({error!r}); compiling in-process\n")
        return 0
    if read:
        _warmed = read
    return read


def leave_to_the_test_runner(reader) -> None:
    """In this process — a test process — :func:`warm` calls *reader*, a
    no-argument callable answering how many programs it read.

    ``tests/passes.py`` reads the store at configure time, before collection
    imports a test module or the web layer, and decides there whether the run
    may build one. What the web layer's import asks (it is about to compile the
    whole shipped pool) is the runner's to answer: a run naming files builds
    the store then, where its own compile would cost as much."""
    global _test_runner_reader
    _test_runner_reader = reader


_BUILD = "import sys; from engine.program_store import build; build(sys.argv[1])"


def _build_in_subprocess(directory: Path, store: Path, failed: Path) -> None:
    # A subprocess, not the caller: a test run has imported every test module
    # by now and a script may have patched what it likes, and nothing either
    # did to the engine may be written down for the next process to read.
    try:
        result = subprocess.run(
            [sys.executable, "-c", _BUILD, str(directory)],
            cwd=ROOT, capture_output=True, text=True, timeout=BUILD_TIMEOUT_SECONDS,
        )
        why = result.stderr[-4000:] or f"exit {result.returncode} and no store written"
    except subprocess.TimeoutExpired:
        why = f"the build ran past {BUILD_TIMEOUT_SECONDS} s"
    if not store.exists():
        failed.write_text(why, encoding="utf-8")
        sys.stderr.write(f"program_store: the compiled-program store was not built; see {failed}\n")


@contextmanager
def _locked(path: Path):
    """Hold *path* locked against every other process for the block. A
    process that dies holding it releases it with its handles.

    The same one-byte lock ``tests/memory_guard.py`` takes for a collection,
    kept apart on purpose: engine code cannot import the tests, and a waiting
    collection must not import the engine to wait."""
    handle = open(path, "a+b")
    try:
        while not _try_lock(handle):
            time.sleep(0.25)
    except BaseException:
        handle.close()
        raise
    try:
        yield
    finally:
        _unlock(handle)


def _try_lock(handle) -> bool:
    try:
        if sys.platform == "win32":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(handle) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    handle.close()  # on POSIX, closing releases the flock


def _prune(directory: Path) -> None:
    def written(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    for pattern in ("programs-*.pickle", "programs-*.failed"):
        for old in sorted(directory.glob(pattern), key=written, reverse=True)[KEEP:]:
            try:
                old.unlink()
            except OSError:  # open in another process, or already gone
                pass
