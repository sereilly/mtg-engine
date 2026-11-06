"""The effect-label rows live in their family modules, and the reader reads them.

``engine/effect_labels.py`` was one module of three tables and two lookups,
nineteen lines short of the 200-line band at Scourge. It was split by label
family: ``engine/activated_labels.py`` holds ``ACTIVATED_LABELS`` and
``engine/triggered_labels.py`` holds ``TRIGGERED_LABELS`` with its by-condition
rows, and ``effect_labels`` keeps the two readers, which import them.

The guards that hold the rows to the pool (``test_effect_labels``,
``test_kg_kinds_wrapper_labels``, ``test_kg3_chores_moment_labels``) import the
tables from the family modules, while the compiler asks the readers. Those two
are one table only while the reader's name and the family module's name are
bound to one object: a table copied rather than moved — a merge that brings
the old rows back into ``effect_labels.py`` beside the import, say — would
leave the guards examining one dict and every card labelled from another, and
``scripts/integration/dups.py`` reads ``def``/``class`` names only, so it would
not see it. These two checks do.
"""
from __future__ import annotations

import ast

from engine import activated_labels, effect_labels, triggered_labels
from tests.source_index import REPO_ROOT, python_files, source_tree

ENGINE = REPO_ROOT / "engine"

#: Each table and the one module that may define it.
HOMES = {
    "ACTIVATED_LABELS": "activated_labels.py",
    "TRIGGERED_LABELS": "triggered_labels.py",
    "TRIGGERED_LABELS_BY_CONDITION": "triggered_labels.py",
}


def test_the_readers_look_labels_up_in_the_family_modules_tables():
    assert effect_labels.ACTIVATED_LABELS is activated_labels.ACTIVATED_LABELS
    assert effect_labels.TRIGGERED_LABELS is triggered_labels.TRIGGERED_LABELS
    assert (
        effect_labels.TRIGGERED_LABELS_BY_CONDITION
        is triggered_labels.TRIGGERED_LABELS_BY_CONDITION
    )
    # And a row is answered from there: one known row each, through the reader.
    kind, label = next(iter(activated_labels.ACTIVATED_LABELS.items()))
    assert effect_labels.activated_label(kind, "no_such_category") == label
    (condition, kind), label = next(
        iter(triggered_labels.TRIGGERED_LABELS_BY_CONDITION.items())
    )
    assert effect_labels.triggered_label(kind, condition) == label


def _table_definitions() -> list[tuple[str, str]]:
    """``(module file, table name)`` for every assignment to a table name, at
    any depth, in any module under ``engine/``."""
    found: list[tuple[str, str]] = []
    for path in python_files("engine"):
        if "__pycache__" in path.parts:
            continue
        for node in ast.walk(source_tree(path)):
            if isinstance(node, ast.AnnAssign):
                targets = [node.target]
            elif isinstance(node, ast.Assign):
                targets = node.targets
            else:
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id in HOMES:
                    found.append((path.relative_to(ENGINE).as_posix(), target.id))
    return found


def test_each_table_is_defined_once_in_its_family_module():
    found = _table_definitions()
    # A floor on what the scan saw: all three tables, each somewhere.
    assert {name for _module, name in found} == set(HOMES), found
    assert sorted(found) == sorted((home, name) for name, home in HOMES.items()), (
        "an effect-label table is assigned outside its family module, or twice "
        f"— its rows belong in that module alone: {sorted(found)}"
    )
