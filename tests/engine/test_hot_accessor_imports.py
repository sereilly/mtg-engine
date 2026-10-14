"""No accessor on ``Permanent`` executes an import statement.

``Permanent.effective_card`` is the one answer to "what does this permanent
say?" (CLAUDE.md, the layer system), and ``has_type`` / ``is_creature`` /
``effective_power`` and their siblings are the one answer to what it *is* — so
every rules query reads them, most of them several times. A function-local
import inside one is not free: Python runs the import machinery on every call,
finds the module already loaded and binds the name again.

Measured on the tree before this guard (October 2026), over a 216-cast sample
of ``test_player_target_census.py``:

* ``effective_card`` on a vanilla creature cost 6.9 microseconds, 3.8 of them
  its import statements, to return ``perm.card``; 2.8 afterwards.
* the sample executed 5.93 million import statements, 5.16 million of them in
  ``effective_card`` and ``_abilities_stripped``; 0.66 million afterwards.
* the sample itself took 12.2 seconds and takes 7.5.

``engine/models.py`` already said this in its header for three modules
("effective_card is read on nearly every rules query, so this is not a
function-local import"), and ten accessors grew local imports afterwards, one
grant channel at a time. A comment is a claim with no test behind it.

**The fix is a module-level import, and it is safe only for a module that does
not import ``engine.models`` back at module level.** ``_without_keyword_parts``
keeps its local import of ``engine.oracle`` for exactly that reason, and it is
memoised, so it is not on the path this guard is about. A new accessor that
needs a module with a real cycle should bind it once, not per read.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.source_index import source_tree

MODELS = Path(__file__).resolve().parents[2] / "engine" / "models.py"

#: Module-level functions the accessors call on every read.
HOT_FUNCTIONS = ("_abilities_stripped",)

#: Accessors a rename must not silently drop out of the walk.
EXPECTED_ACCESSORS = (
    "effective_card", "has_type", "is_creature", "has_supertype",
    "effective_colors", "has_keyword", "effective_power", "effective_toughness",
)


def _importing(functions) -> list[str]:
    return sorted(
        function.name for function in functions
        if any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(function))
    )


def _permanent_members(tree: ast.Module) -> list[ast.FunctionDef]:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Permanent":
            return [member for member in node.body if isinstance(member, ast.FunctionDef)]
    return []


def test_no_permanent_accessor_executes_an_import_statement():
    members = _permanent_members(source_tree(MODELS))
    names = {member.name for member in members}
    # The walk is the guard, so an empty or shrunken one would pass silently.
    assert len(members) >= 15, len(members)
    for expected in EXPECTED_ACCESSORS:
        assert expected in names, expected

    importing = _importing(members)
    assert not importing, (
        f"Permanent.{importing} execute an import statement on every read. These "
        "accessors are read by nearly every rules query: import the name at the "
        "top of engine/models.py (safe when the module does not import "
        "engine.models back at module level), or bind it once."
    )


def test_no_function_an_accessor_calls_per_read_executes_an_import_statement():
    functions = [
        node for node in source_tree(MODELS).body
        if isinstance(node, ast.FunctionDef) and node.name in HOT_FUNCTIONS
    ]
    assert len(functions) == len(HOT_FUNCTIONS), [f.name for f in functions]
    importing = _importing(functions)
    assert not importing, (
        f"{importing} in engine/models.py run once per `effective_card` read and "
        "execute an import statement each time."
    )
