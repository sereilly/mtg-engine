"""Guard: `ast.Effect` names every leaf node the lowering dispatches on.

The union is an annotation, and annotations are lazy under
`from __future__ import annotations` — so a leaf missing from it costs nothing
at runtime and produces no error anywhere. `CombatRestriction` was absent for
its entire existence: defined after `__all__` at the bottom of the pre-split
`ast.py`, so the module never exported it, while `lower_statement` dispatched on
it like any other effect. Two names (`BoardCount`, `DamageUnlessPay`) had been
dropped from `__all__` the same way.

That is a claim about the type system being false with no consequence until
someone reads it to answer "what is an Effect?" — at which point they get a
wrong answer and write code around it. Nothing but a test can hold this,
because nothing else ever evaluates it.

The check runs off the *dispatch*, not off a second list: whatever
`lower_statement` matches with `isinstance(statement, ast.X)` is by definition a
statement, so the union has to name it. A new leaf that someone wires into the
dispatch and forgets to add here fails on the same day rather than years later.
"""

from __future__ import annotations

import ast as pyast
import re
import typing
from pathlib import Path

import pytest

from engine.grammar import ast

REPO = Path(__file__).resolve().parent.parent.parent
AST_DIR = REPO / "engine" / "grammar" / "ast"
FAMILIES = ["damage", "characteristics", "board", "cards", "stack", "combat", "game"]

# Leaf nodes that are deliberately not statements. Each needs a reason, because
# the whole failure this guards is a name going missing without one.
_NOT_STATEMENTS = {
    # A field of DealDamage ("it can't be regenerated", "exile it instead"),
    # folded into the effect it modifies by `_attach_riders`. Nothing dispatches
    # on it and it never stands alone as a step.
    "DamageRiders",
}


def _union_members() -> set[str]:
    return {t.__name__ for t in typing.get_args(ast.Effect)}


def _family_leaves() -> dict[str, str]:
    """Every dataclass defined in an `ast/` family module -> its family."""
    leaves: dict[str, str] = {}
    for family in FAMILIES:
        tree = pyast.parse((AST_DIR / f"{family}.py").read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, pyast.ClassDef):
                leaves[node.name] = family
    return leaves


def _dispatched_by_lowering() -> set[str]:
    """Node names `lower_statement` matches with isinstance."""
    source = (REPO / "engine" / "grammar" / "lower.py").read_text(encoding="utf-8")
    return set(re.findall(r"isinstance\([a-z_]+, *ast\.([A-Z]\w+)\)", source)) | set(
        re.findall(r"isinstance\([a-z_]+, *\(([^)]*)\)\)", source)
    ).union(
        name
        for group in re.findall(r"isinstance\([a-z_]+, *\(([^)]*)\)\)", source)
        for name in re.findall(r"ast\.([A-Z]\w+)", group)
    )


def test_every_dispatched_node_is_in_the_effect_union():
    dispatched = {n for n in _dispatched_by_lowering() if hasattr(ast, n)}
    assert dispatched, "found no isinstance dispatch in lower.py — the guard is vacuous"
    leaves = _family_leaves()
    missing = sorted(
        name for name in dispatched if name in leaves and name not in _union_members()
    )
    assert not missing, (
        f"`lower_statement` dispatches on {missing}, so they are statements, but "
        "`ast.Effect` does not name them. The union is lazy, so this costs "
        "nothing at runtime and is wrong to anyone who reads it."
    )


def test_every_family_leaf_is_a_statement_or_has_a_reason():
    leaves = _family_leaves()
    members = _union_members()
    unexplained = sorted(
        name for name in leaves if name not in members and name not in _NOT_STATEMENTS
    )
    assert not unexplained, (
        f"{unexplained} are leaf nodes in an `ast/` family but are neither in "
        "`ast.Effect` nor listed in this test's `_NOT_STATEMENTS` with a "
        "reason. One of those two is the fix; deciding which is the point."
    )


@pytest.mark.parametrize("name", sorted(_NOT_STATEMENTS))
def test_the_not_a_statement_list_has_not_gone_stale(name):
    """An exemption for a node that no longer exists, or that has since become a
    statement, is a comment nobody will re-check."""
    assert hasattr(ast, name), f"{name} is exempted but no longer exists"
    assert name not in _union_members(), (
        f"{name} is in `ast.Effect` now — remove it from _NOT_STATEMENTS"
    )
    assert name not in _dispatched_by_lowering(), (
        f"`lower_statement` dispatches on {name} — it is a statement, so the "
        "exemption is wrong"
    )


def test_the_union_only_names_real_nodes():
    """A union member that is not a node at all would make the two tests above
    pass while describing something that cannot be lowered."""
    for name in _union_members():
        assert hasattr(ast, name), f"`ast.Effect` names {name}, which does not exist"
