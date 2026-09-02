"""No module under ``engine/`` imports a name it neither uses nor re-exports.

This is the **silent** half of the moved-block hazard SET_PLAYBOOK.md names.
The loud half — a function moved between modules leaving a *needed* import
behind — fails as mass collection errors, so it gets fixed the same hour. The
other half is a function moved out leaving its now-unneeded import behind, and
nothing ever fails: every family split since the grammar layering began
deposited some, and by Homelands' promotion there were **305** across 36
modules, `sentence_clauses.py` carrying 89 and `statements.py` 69.

It is not a runtime bug, and that is exactly why it needs a guard rather than a
cleanup. What it costs is the signal: the layering guards next door exist to say
which families a module really depends on, and a module importing half the
package makes that answer meaningless. A defect whose failure mode is silence
comes back the moment somebody splits a module again.

**Re-exporting is a real use and is not flagged.** ``engine/grammar``'s packages
re-export flat by design, and two modules act as façades over the effect
productions — ``statements`` and ``sentence_clauses`` — so a name another module
pulls back out through them counts as used *there*. Relative imports are
resolved to real module paths before that question is asked, because a check
keyed on the bare module name would let ``lowering/board`` launder
``effects/board``'s re-exports.

``__init__.py`` is skipped entirely: a package's flat re-export is the
convention, and CLAUDE.md's grammar layering depends on it.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from tests.source_index import source_text, source_tree

ENGINE = Path(__file__).resolve().parents[2] / "engine"


def _module_path(path: Path) -> str:
    """``engine/grammar/nouns.py`` -> ``engine.grammar.nouns``."""
    return ".".join(path.relative_to(ENGINE.parent).with_suffix("").parts)


def _resolve(node: ast.ImportFrom, importer: str) -> str | None:
    """The absolute dotted module *node* imports from, or None."""
    if node.level == 0:
        return node.module
    parts = importer.split(".")[: -node.level]
    if node.module:
        parts.append(node.module)
    return ".".join(parts) if parts else None


def _sources() -> list[Path]:
    return sorted(ENGINE.rglob("*.py"))


def _names_pulled_from_each_module() -> dict[str, set[str]]:
    """For every module, the names some *other* module imports out of it."""
    pulled: dict[str, set[str]] = {}
    for path in _sources():
        try:
            tree = source_tree(path)
        except SyntaxError:  # pragma: no cover - a syntax error fails elsewhere
            continue
        importer = _module_path(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                target = _resolve(node, importer)
                if target:
                    pulled.setdefault(target, set()).update(a.name for a in node.names)
    return pulled


PULLED = _names_pulled_from_each_module()
MODULES = [p for p in _sources() if p.name != "__init__.py"]


def _unused_imports(path: Path) -> list[str]:
    """Bindings *path* imports, never mentions again, and nobody pulls out.

    "Mentions" is deliberately **textual**: a name that appears only inside a
    string annotation, a docstring or a comment is treated as used. A false
    negative here costs nothing — one stale import survives — while a false
    positive would delete a `TYPE_CHECKING` import and break a signature.
    """
    src = source_text(path)
    tree = ast.parse(src)
    exported = PULLED.get(_module_path(path), set())
    dead: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            continue
        for alias in node.names:
            if alias.name == "*":
                continue
            bound = alias.asname or alias.name.split(".")[0]
            if alias.name in exported or bound in exported:
                continue
            if len(re.findall(rf"\b{re.escape(bound)}\b", src)) <= 1:
                dead.append(bound)
    return sorted(dead)


@pytest.mark.parametrize(
    "path", MODULES, ids=lambda p: str(p.relative_to(ENGINE.parent))
)
def test_no_module_imports_a_name_it_neither_uses_nor_re_exports(path: Path):
    dead = _unused_imports(path)
    assert not dead, (
        f"{path.relative_to(ENGINE.parent)} imports {dead} and neither uses them "
        "nor re-exports them. A function moved between modules leaves its import "
        "behind, and this half of that hazard fails nothing — delete the binding, "
        "or, if another module is meant to pull it back out, let it import from "
        "where the name actually lives."
    )


def test_the_guard_walks_every_engine_module():
    """The parametrization is the guard, so an empty one would pass silently.

    The same assertion `test_grammar_layering` makes about its own module list,
    for the same reason: a guard that iterates a collection nobody checks is a
    guard a new file escapes by existing.
    """
    assert len(MODULES) > 150, len(MODULES)
    walked = {p.name for p in MODULES}
    for expected in ("oracle.py", "card_hooks.py", "nouns.py", "statements.py"):
        assert expected in walked, expected
    assert "__init__.py" not in walked
