"""One shared, cached read of the repo's source tree for the guard tests.

Around twenty-five files in ``tests/engine/`` are convention guards that sweep
``engine/`` (some also ``web/`` or ``scripts/``) with ``rglob`` + ``read_text``
+ ``ast.parse``. Each did its own sweep, so one suite run parsed the same ~200
files dozens of times — 35-45 seconds of pure repetition. These helpers are
that sweep, done once per process (``lru_cache``; per-worker under xdist,
which is the same safety story every module-level cache in the engine has).

Read-only by contract: callers walk the returned trees and slice the returned
text, never mutate them — a guard that edited a shared AST would corrupt every
guard after it. Nothing here changes what any guard checks; the file lists,
exemption tables and analyses all stay in their guard files.
"""

from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


@lru_cache(maxsize=None)
def python_files(*roots: str) -> tuple[Path, ...]:
    """Every ``*.py`` under the named repo-relative roots, sorted per root.

    ``python_files("engine", "web")`` matches the common guard sweep; a root
    may also be a subpackage path like ``"engine/grammar"``.
    """
    found: list[Path] = []
    for root in roots:
        found.extend(sorted((REPO_ROOT / root).rglob("*.py")))
    return tuple(found)


@lru_cache(maxsize=None)
def source_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=None)
def source_tree(path: Path) -> ast.Module:
    """The parsed module. Walk it, never mutate it — the tree is shared."""
    return ast.parse(source_text(path))
