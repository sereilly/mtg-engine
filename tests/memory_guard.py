"""Keep a pytest run inside the machine's memory.

Two limits, enforced by the runner rather than remembered by whoever launches
it. CLAUDE.md's "-n 4 while agents are running" is advice, and on 2026-10-31
nineteen IDE test discoveries ran at once, about 4 GB each, and took a 64 GB
machine to zero free commit — nothing anyone typed asked for parallelism.

- **One collection at a time per checkout.** A collect-only session waits for
  the one before it in the same rootdir to finish. An IDE's test discovery is
  a collect-only session, and VS Code's Python extension starts a new one on
  every ``pytest.ini`` change in the workspace without cancelling the one
  running — each ``git worktree add`` / ``remove`` is such a change. A waiting
  process holds about 60 MB; a collecting one about 0.8 GB.
- **No more xdist workers than free memory holds.** ``-n N`` and ``-n auto``
  are capped through xdist's own ``maxprocesses`` at what is free now —
  available commit on Windows (the limit an allocation fails against, whatever
  RAM shows), ``MemAvailable`` on Linux — at ``WORKER_PEAK_GB`` a worker,
  keeping ``RESERVE_GB`` for everything else on the machine. The cap is
  printed when it bites; ``MTG_PYTEST_NO_MEMORY_CAP=1`` turns it off.

The hooks are imported into ``tests/conftest.py``, which is what registers them.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

# The largest private commit one xdist worker reached over a full `-n 4` run
# of the suite (2026-10-31, measured after `load_cards` was cached), rounded
# up. Re-measure when a worker's footprint changes shape.
WORKER_PEAK_GB = 2.5
# Left free for the controller, the IDE, a browser, and whatever else the
# machine's owner has open.
RESERVE_GB = 4.0

_collection_lock = None  # the open lock file; closing it releases the lock


def available_memory_gb() -> float | None:
    """What can still be allocated on this machine, or None where unknown."""
    if sys.platform == "win32":
        class _MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = _MemoryStatus(dwLength=ctypes.sizeof(_MemoryStatus))
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(_MemoryStatus)]
        if not kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return status.ullAvailPageFile / 2**30
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 2**20
    except OSError:
        pass
    return None


def worker_cap(available_gb: float) -> int:
    """How many workers *available_gb* holds, never fewer than one."""
    return max(1, int((available_gb - RESERVE_GB) // WORKER_PEAK_GB))


@pytest.hookimpl(tryfirst=True)
def pytest_cmdline_main(config):
    # Ahead of xdist's own tryfirst hook (a conftest registers after the
    # plugin, and pluggy calls the later registration first), which reads
    # `maxprocesses` as it turns `-n` into workers.
    if hasattr(config, "workerinput") or os.environ.get("MTG_PYTEST_NO_MEMORY_CAP"):
        return None
    requested = getattr(config.option, "numprocesses", None)
    if not requested:
        return None
    available = available_memory_gb()
    if available is None:
        return None
    cap = worker_cap(available)
    current = getattr(config.option, "maxprocesses", None)
    if current is not None and current <= cap:
        return None
    config.option.maxprocesses = cap
    if requested == "auto" or (isinstance(requested, int) and requested > cap):
        sys.stderr.write(
            f"memory_guard: {available:.1f} GB free holds {cap} worker(s) at "
            f"{WORKER_PEAK_GB} GB each with {RESERVE_GB} GB kept free; -n {requested} "
            f"runs as -n {cap} (MTG_PYTEST_NO_MEMORY_CAP=1 to override)\n"
        )
    return None


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


@contextmanager
def exclusive(path: Path):
    """Hold *path* locked against every other process for the block.

    The lock the collection wait below takes, as a block: ``tests/passes.py``
    builds the compiled-program store under one, so of the workers that find
    no store the first builds it and the rest wait for it. A process that
    dies holding it releases it with its handles."""
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


def pytest_configure(config):
    global _collection_lock
    if hasattr(config, "workerinput") or not config.option.collectonly:
        return
    digest = hashlib.sha1(str(config.rootpath).lower().encode()).hexdigest()[:12]
    handle = open(Path(tempfile.gettempdir()) / f"mtg-simulacrum-collect-{digest}.lock", "a+b")
    waiting = False
    while not _try_lock(handle):
        if not waiting:
            sys.stderr.write(f"memory_guard: waiting for another collection in {config.rootpath}\n")
            waiting = True
        time.sleep(0.5)
    _collection_lock = handle


def pytest_unconfigure(config):
    global _collection_lock
    if _collection_lock is None:
        return
    _unlock(_collection_lock)
    _collection_lock = None
