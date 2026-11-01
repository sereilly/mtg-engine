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
the engine** (``tests/passes.py`` runs it as a subprocess), so nothing a test
patched, at import or in a fixture, can be persisted: a poisoned answer cannot
outlive the process that computed it. The fingerprint is read before the
compile and again after it, and nothing is written if the two differ — an
engine file edited mid-build belongs to neither the code before nor the code
after.
"""

from __future__ import annotations

import functools
import hashlib
import os
import pickle
import sys
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
