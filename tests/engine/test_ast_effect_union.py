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
`lower_statement` lowers is by definition a statement, so the union has to name
it. A new leaf that someone wires into the dispatch and forgets to add here
fails on the same day rather than years later.

**This guard went blind twice, and both times by keeping a copy.** It read the
dispatch as `isinstance(statement, ast.X)` in `lower.py`, which was the whole
dispatch when it was written; the chain then moved to `statement_dispatch.py`
and most of it became the four type-keyed tables in `by_node.py`, so by
Planeshift it was examining **nine** of about 210 dispatched nodes. And it read
the families off a hand-written list of module names that five splits never
updated (`tapping`, `control_changes`, `mana`, `library`, `exile`, then
`separations`), so six of fourteen families were outside it. Both were found by
a Phase 0 split moving five nodes out of a listed module - a split must not
shrink what a guard reads, and this one would have. Widened, it named two
leaves on the day: `BinRevealedCard` and `GraveyardTopToLibrary`, each built
by a production and lowered through `by_node`, and in neither union.

So the families are the layering guard's own `AST_FAMILIES` now, the dispatch
is read off the tables' keys and off both modules that still match by
`isinstance`, and each population carries a floor - a guard over nine nodes
passed for as long as it did because nothing asked how many it had looked at.
"""

from __future__ import annotations

import ast as pyast
import re
import typing
from pathlib import Path

import pytest

from engine.grammar import ast, by_node

from .test_grammar_layering import AST_FAMILIES

REPO = Path(__file__).resolve().parent.parent.parent
GRAMMAR_DIR = REPO / "engine" / "grammar"
AST_DIR = GRAMMAR_DIR / "ast"
#: The layering guard's list, not a second one: it is the list a new `ast/`
#: family has to join to import anything, so a family cannot exist without
#: being read here.
FAMILIES = AST_FAMILIES

#: The modules that still dispatch by `isinstance`. `lower.py` is the entry
#: point and keeps a handful; the chain itself is `statement_dispatch.py`.
_ISINSTANCE_DISPATCHERS = ("lower.py", "statement_dispatch.py")
#: The four type-keyed registries `lower_statement` consults before the chain.
_TABLES = (
    "_BY_NODE_TYPE",
    "_BY_NODE_TYPE_WITH_EVENT",
    "_BY_NODE_TYPE_WITH_PRODUCED",
    "_BY_NODE_TYPE_WITH_EVENT_AND_PRODUCED",
)
#: Floors, each well under today's count (226 leaves, about 210 dispatched,
#: 169 of them through the tables) and far over what the guard read while it
#: was blind (nine).
#: Where a dispatched node may live besides a family: the roof's control-flow
#: nodes (`Sequence`, `May`, `Conditional`, ...), the line layer's ability
#: lines, and two names the `isinstance` scan picks up from the vocabulary
#: floors (`RawEffect`, and `TargetSpec` in a subject test). None of these is a
#: leaf effect, which is why the union is not asked about them.
_NON_FAMILY_HOMES = {"statements", "lines", "_core", "_targets"}
_LEAF_FLOOR = 200
_DISPATCHED_FLOOR = 180
_TABLE_KEY_FLOOR = 150

# Leaf nodes that are deliberately not statements. Each needs a reason, because
# the whole failure this guards is a name going missing without one.
_NOT_STATEMENTS = {
    # A field of DealDamage ("it can't be regenerated", "exile it instead"),
    # folded into the effect it modifies by `_attach_riders`. Nothing dispatches
    # on it and it never stands alone as a step.
    "DamageRiders",
    # A term of GainLife's "…but not more than A, B, or C" cap (Drain Life,
    # Soul Burn). Part of how much life the gain is, not a step of its own:
    # `_lower_gain_life` folds the whole tuple into the gain's payload and
    # nothing dispatches on it.
    "LifeGainCap",
    # A field of PreventDamage — CR 615.5's sentence *after* the prevention
    # ("you gain life equal to the damage prevented this way"). Not a step of
    # its own and deliberately so: its quantity does not exist until the shield
    # has absorbed something, so it runs from the interceptor rather than as a
    # lowered instruction. `_lower_prevent_damage` folds it into which shield is
    # armed and nothing dispatches on it.
    "PreventedRider",
    # One keep of a KeepChosenSacrificeRest - how many permanents may fill it
    # and what they must be (Cataclysm's "an artifact", Limited Resources' "five
    # lands"). A term of the sentence's payload rather than a step: the
    # lowering expands the whole tuple into the instruction's `slots` key and
    # nothing dispatches on it.
    "KeepSlot",
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


def _table_keys() -> set[str]:
    """Node names the four `by_node` registries are keyed by.

    Read off the live dicts rather than out of the source: the keys are the
    classes `lower_statement` looks `type(statement)` up by, so this is the
    dispatch itself and cannot disagree with it.
    """
    return {
        node.__name__ for table in _TABLES for node in getattr(by_node, table)
    }


def _dispatched_by_lowering() -> set[str]:
    """Node names `lower_statement` lowers: a table key, or an `isinstance` arm."""
    names = _table_keys()
    for module in _ISINSTANCE_DISPATCHERS:
        source = (GRAMMAR_DIR / module).read_text(encoding="utf-8")
        names |= set(re.findall(r"isinstance\([a-z_]+, *ast\.([A-Z]\w+)\)", source))
        for group in re.findall(r"isinstance\([a-z_]+, *\(([^)]*)\)\)", source):
            names |= set(re.findall(r"ast\.([A-Z]\w+)", group))
    return names


def test_the_guard_reads_the_whole_dispatch_and_every_family():
    """A guard over an empty - or a ninth of a - population passes. These
    floors are what would have said so."""
    for table in _TABLES:
        assert isinstance(getattr(by_node, table, None), dict), (
            f"`by_node.{table}` is gone or renamed: this guard reads the "
            "dispatch through it"
        )
    assert len(_table_keys()) >= _TABLE_KEY_FLOOR, len(_table_keys())
    dispatched = {n for n in _dispatched_by_lowering() if hasattr(ast, n)}
    assert len(dispatched) >= _DISPATCHED_FLOOR, len(dispatched)
    leaves = _family_leaves()
    assert len(leaves) >= _LEAF_FLOOR, len(leaves)
    # Every dispatched node is defined in a module this guard reads. Asked of
    # the nodes rather than of the directory listing: a new `ast/` module that
    # holds something `lower_statement` lowers fails here until it is a family
    # the layering guard lists, which is the list `FAMILIES` is.
    homes = {getattr(ast, name).__module__.rsplit(".", 1)[-1] for name in dispatched}
    assert homes <= set(FAMILIES) | _NON_FAMILY_HOMES, sorted(
        homes - set(FAMILIES) - _NON_FAMILY_HOMES
    )


def test_every_dispatched_node_is_in_the_effect_union():
    dispatched = {n for n in _dispatched_by_lowering() if hasattr(ast, n)}
    assert dispatched, "found no dispatch at all — the guard is vacuous"
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
