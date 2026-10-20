"""Modules a hot accessor reads that the package loads *after* the accessor's own.

``Permanent.effective_card`` and the CR 613 accessors beside it live in
``engine/models.py``, the second module ``engine/__init__.py`` loads, and they
read functions out of ``keywords``, ``global_statics``, ``auras`` and
``layer_bridge``, which load dozens of modules later. So those reads were
function-level imports — correct, and paid on **every call**: a
``from .keywords import abilities_lost_at`` inside a function runs the import
machinery each time it executes (CPython resolves the relative name through the
module spec's ``parent`` property, a Python-level frame per statement).
``effective_card`` ran five such statements per read and was read 4.5 million
times in two simulated Mirage games, which made import resolution — 31 million
of them — one of the simulator's largest single costs.

A module-level import would cost nothing per call, but here it would also
**change the order the package loads its modules in**, because the target is
imported earlier than it was. Several modules register into shared tables as
they load (``auras`` registers a special action, the ``compilation_cache``
decorator appends to the list ``clear_compilation_caches`` walks), so a load
order change is a behaviour change that nothing would point at. This keeps the
order exactly what it was:

    _late = LateModules(__package__)
    ...
    _late.keywords.abilities_lost_at(perm)

The first ``_late.keywords`` imports ``engine.keywords`` (by then long loaded,
so it is a dictionary lookup) and stores the module on the instance; every read
after that is an ordinary attribute lookup, with no import machinery at all.
Nothing is imported when the owning module loads.

Imports nothing from the engine, so any module may import it at its top.
"""

from __future__ import annotations

import importlib
from types import ModuleType


class LateModules:
    """Attribute access to the submodules of *package*, each imported on first
    use and then held as an ordinary attribute."""

    def __init__(self, package: str) -> None:
        self._package = package

    def __getattr__(self, name: str) -> ModuleType:
        # Only reached when *name* is not yet an attribute: the first read.
        if name.startswith("__"):
            raise AttributeError(name)
        module = importlib.import_module(f"{self._package}.{name}")
        setattr(self, name, module)
        return module


__all__ = ["LateModules"]
