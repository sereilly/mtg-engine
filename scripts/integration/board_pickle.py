"""A live web session, pickled and read back: the board ``serve_board.py --reload`` keeps.

What is kept is **the whole session** — ``web.session_store.Session``: the
game (every zone and its order, the stack, permanents with their ids,
counters, attachments, continuous effects and every record), the pending
prompts, the session's own pregame/upkeep/cleanup state, the undo history
and the log. Measured before building (pre5dn T4): 113 of 113 sessions read
back to the byte-identical state payload for every seat in a fresh process
(ai_vs_ai games pickled after every turn, a human_vs_ai one mid-pregame).
The Debug Menu's raw-state paste (``web/debug_actions._apply_raw_state``) was
the alternative; it renumbers every permanent id and drops the log, the
library and the attachments' ids in every trial.

Plain pickle refuses one thing a live game holds: a resolution suspended
part-way for an answer keeps the rest of its loop as a closure on
``game.resume_stack`` (``engine/resumption.py``). :class:`BoardPickler`
carries a function that is not importable by name as its code and closure
(its globals are the reading process's module — the new code — and its
bytecode the old), and the engine's **identity sentinels** (``_THEN =
object()``, ``ENTRY_SUSPENDED``) by name, so an ``is`` against one still
answers yes. A dataclass field the new code added is filled from its default
on the way back in (:func:`fill_new_fields`); an attribute a new ``__init__``
sets on a plain class (``Game``) is not, and a class or module the new code
moved or deleted makes that session unreadable — reported and skipped.

A module of its own so the board's pickles name ``board_pickle.<helper>``
whether ``serve_board.py`` runs as a script (``__main__``) or is imported.
"""

from __future__ import annotations

import builtins
import dataclasses
import importlib
import io
import marshal
import os
import pickle
import sys
import time
import types
from pathlib import Path

BOARD_FORMAT = 1

_OWN_PACKAGES = ("engine", "web")


def _own_module(name: str | None) -> bool:
    return bool(name) and any(name == root or name.startswith(root + ".") for root in _OWN_PACKAGES)


def identity_globals() -> dict[int, tuple[tuple[str, str], ...]]:
    """``id(value) -> ((module, name), …)`` for every module-level identity
    object in ``engine``/``web``: a bare ``object()`` sentinel, or a stateless
    instance of a class those packages define. Code compares them with
    ``is``, so a copy would answer no; they are pickled by name and read back
    as the reading process's own. Stateful globals pickle by value — a loop
    variable left at module level names one card of the catalog, not *the*
    card a game holds."""
    table: dict[int, list[tuple[str, str]]] = {}
    for module_name, module in list(sys.modules.items()):
        if module is None or not _own_module(module_name):
            continue
        for name, value in list(vars(module).items()):
            kind = type(value)
            if kind is not object and (
                isinstance(value, (type, types.ModuleType, types.FunctionType))
                or not _own_module(getattr(kind, "__module__", None))
                or getattr(value, "__dict__", None)
                or any(hasattr(value, slot) for slot in getattr(kind, "__slots__", ()))
            ):
                continue
            table.setdefault(id(value), []).append((module_name, name))
    return {key: tuple(places[:6]) for key, places in table.items()}


def _importable(fn: types.FunctionType) -> bool:
    target = sys.modules.get(fn.__module__ or "")
    for part in fn.__qualname__.split("."):
        target = getattr(target, part, None)
        if target is None:
            return False
    return target is fn


class _EmptyCell:
    """What an empty closure cell's contents pickle as."""

    def __reduce__(self):
        return "EMPTY_CELL"


EMPTY_CELL = _EmptyCell()


def make_cell():
    return types.CellType()


def fill_cell(cell, state) -> None:
    (contents,) = state
    if contents is not EMPTY_CELL:
        cell.cell_contents = contents


def make_function(code: bytes, module: str | None, name: str, closure: tuple):
    owner = sys.modules.get(module or "")
    if owner is None and module:
        try:
            owner = importlib.import_module(module)
        except ImportError:
            owner = None
    namespace = vars(owner) if owner is not None else {"__builtins__": builtins}
    return types.FunctionType(marshal.loads(code), namespace, name, None, closure or None)


def fill_function(fn, state) -> None:
    defaults, kwdefaults, qualname, attributes = state
    fn.__defaults__ = defaults
    fn.__kwdefaults__ = kwdefaults
    fn.__qualname__ = qualname
    fn.__dict__.update(attributes)


class BoardPickler(pickle.Pickler):
    """Pickle, plus a function that is not importable by name (a lambda, a
    nested function — the rest of a suspended loop) as its code and closure,
    and the identity sentinels by name (:func:`identity_globals`). A cell is
    made empty and filled after it is memoized, so a closure that refers to
    itself (``run_from`` in ``engine/resumption.py``) pickles once."""

    def __init__(self, file, identities: dict):
        super().__init__(file, protocol=pickle.HIGHEST_PROTOCOL)
        self._identities = identities

    def persistent_id(self, obj):
        places = self._identities.get(id(obj))
        return ("identity", places) if places else None

    def reducer_override(self, obj):
        kind = type(obj)
        if kind is types.CellType:
            try:
                contents = obj.cell_contents
            except ValueError:
                contents = EMPTY_CELL
            # In a 1-tuple: a reduce's state of None means "no state", and a
            # cell holding None would come back empty.
            return (make_cell, (), (contents,), None, None, fill_cell)
        if kind is types.FunctionType and not _importable(obj):
            state = (obj.__defaults__, obj.__kwdefaults__, obj.__qualname__, dict(obj.__dict__))
            return (
                make_function,
                (marshal.dumps(obj.__code__), obj.__module__, obj.__name__, obj.__closure__ or ()),
                state, None, None, fill_function,
            )
        return NotImplemented


class BoardUnpickler(pickle.Unpickler):
    def persistent_load(self, pid):
        tag, places = pid
        if tag != "identity":
            raise pickle.UnpicklingError(f"unknown persistent id {tag!r}")
        for module_name, name in places:
            try:
                return getattr(importlib.import_module(module_name), name)
            except (ImportError, AttributeError):
                continue
        raise pickle.UnpicklingError(f"no identity object at any of {places}")


def dumps(obj, identities: dict | None = None) -> bytes:
    buffer = io.BytesIO()
    BoardPickler(buffer, identity_globals() if identities is None else identities).dump(obj)
    return buffer.getvalue()


def loads(blob: bytes):
    return BoardUnpickler(io.BytesIO(blob)).load()


_ATOMS = (
    str, bytes, int, float, complex, bool, type(None), type, types.ModuleType,
    types.FunctionType, types.BuiltinFunctionType, types.CodeType,
)


def fill_new_fields(root) -> int:
    """Give every dataclass instance reachable from *root* each field its
    class declares and the instance lacks — a field the new code added —
    from the field's default; returns how many were filled."""
    filled = 0
    seen: set[int] = set()
    pending = [root]
    while pending:
        obj = pending.pop()
        if isinstance(obj, _ATOMS) or id(obj) in seen:
            continue
        seen.add(id(obj))
        if dataclasses.is_dataclass(obj):
            for field in dataclasses.fields(obj):
                if hasattr(obj, field.name):
                    continue
                if field.default_factory is not dataclasses.MISSING:
                    value = field.default_factory()
                elif field.default is not dataclasses.MISSING:
                    value = field.default
                else:
                    continue
                object.__setattr__(obj, field.name, value)
                filled += 1
        if isinstance(obj, dict):
            pending.extend(obj.keys())
            pending.extend(obj.values())
        elif isinstance(obj, (list, tuple, set, frozenset)):
            pending.extend(obj)
        else:
            pending.extend(getattr(obj, "__dict__", {}).values())
            for slot in getattr(type(obj), "__slots__", ()):
                if isinstance(slot, str) and hasattr(obj, slot):
                    pending.append(getattr(obj, slot))
    return filled


def save_board(store, session_lock, revisions, board: Path) -> tuple[bool, str]:
    """Pickle every session of *store* to *board*, each under its session's
    lock; return (saved, message). On success the locks are **kept**: the
    caller exits holding them, so no request moves a game after the moment
    saved. On failure they are released and nothing is written."""
    sessions = list(getattr(store, "_sessions", {}).items())
    held = []
    for sid, _ in sessions:
        lock = session_lock(sid)
        if not lock.acquire(timeout=30):
            for each in held:
                each.release()
            return False, f"session {sid} stayed busy for 30 s"
        held.append(lock)
    identities = identity_globals()
    blobs = []
    for sid, session in sessions:
        try:
            blobs.append((sid, dumps(session, identities)))
        except Exception as exc:  # noqa: BLE001 — named in the message; the old process keeps serving
            for each in held:
                each.release()
            return False, f"session {sid} could not be pickled: {exc!r}"
    record = {
        "format": BOARD_FORMAT,
        "saved_at": time.time(),
        "sessions": blobs,
        "revisions": {sid: revisions.get(sid, 0) for sid, _ in sessions},
    }
    temporary = board.with_suffix(".tmp")
    temporary.write_bytes(pickle.dumps(record, protocol=pickle.HIGHEST_PROTOCOL))
    os.replace(temporary, board)
    total = sum(len(blob) for _, blob in blobs)
    return True, f"saved {len(blobs)} session(s), {total // 1024} KiB, to {board}"


def restore_board(store, revisions, board: Path) -> str:
    """Load *board*'s sessions into *store* (before anything is served); a
    session that no longer reads is reported and skipped."""
    record = pickle.loads(board.read_bytes())
    if record.get("format") != BOARD_FORMAT:
        return f"{board} is board format {record.get('format')!r}, not {BOARD_FORMAT}: nothing restored"
    restored, failed, filled = [], [], 0
    for sid, blob in record["sessions"]:
        try:
            session = loads(blob)
            filled += fill_new_fields(session)
        except Exception as exc:  # noqa: BLE001 — reported; the rest still load
            failed.append(f"{sid}: {exc!r}")
            continue
        store._sessions[sid] = session
        # One more than the old process announced: the page keeps the state
        # with the highest revision, so a restored one must not read older
        # than the one it is showing.
        revisions[sid] = record["revisions"].get(sid, 0) + 1
        restored.append(sid)
    age = time.time() - record.get("saved_at", time.time())
    message = f"restored {len(restored)} of {len(record['sessions'])} session(s) saved {age:.0f} s ago"
    if filled:
        message += f"; {filled} dataclass field(s) the new code added filled from their defaults"
    for line in failed:
        message += f"\n[serve_board]   not restored: {line}"
    return message
