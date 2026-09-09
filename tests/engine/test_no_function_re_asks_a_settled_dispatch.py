"""Guard: merge shadowing *inside* one function.

``tests/engine/test_no_module_defines_the_same_name_twice.py`` catches the
parallel-round hazard MEMORY records — two branches each add a definition and
git unions them, so the second silently wins. It looks for a repeated
**top-level name**, which means it is blind to the same accident one level
down: two branches each rewrote the same *function*, the union kept both
bodies, and the second copy sits after a ``return`` that always fires.

``engine/handlers/zones.discard_hand`` was carrying one. It had **two**
``if instruction.payload.get("who") == "each_player":`` blocks, and the first
returned unconditionally. Nothing could see it: the module defines the name
once, the function compiles, every test passes, and the dead half was a near
copy of the live one — so even reading it, the eye slides over the second
block as the first. The two differed in exactly one line, and the difference
mattered: only the live block wrote ``DISCARDED_BY_SEAT``, which is what the
sentence *behind* Windfall's ("the greatest number of cards a player discarded
this way") reads. Had the merge gone the other way, that sentence would have
read a zero with nothing failing.

**The test has to be invariant, or this is noise.** A first pass over the same
shape found 54 sites and 53 were parser productions asking
``stream.accept_punct(".")`` twice — which consumes a token, so the second ask
is a different question and re-asking it is the whole idiom. So the scan keeps
only a *dispatch* test: a mapping read (``payload.get("k") == "v"``, or a
subscript) compared to a literal, with nothing between the two asks that
assigns the name it reads. Under that rule the pool holds exactly one, and it
is the bug — which is the number a guard wants: one that fires on the defect
and on nothing else.
"""

from __future__ import annotations

import ast
import pathlib

_ROOTS = ("engine", "web", "scripts")
_REPO = pathlib.Path(__file__).resolve().parents[2]


def _always_leaves(stmt: ast.stmt) -> bool:
    """Whether *stmt* always leaves the enclosing function.

    ``return`` and ``raise`` only. ``break``/``continue`` leave a *loop*, so a
    later branch in the same body is reachable on the next pass around it.
    """
    return isinstance(stmt, (ast.Return, ast.Raise))


def _root_name(node: ast.expr) -> str | None:
    """The bare name a read chain hangs off: ``instruction`` for
    ``instruction.payload.get("who")``."""
    while isinstance(node, (ast.Attribute, ast.Subscript, ast.Call)):
        node = node.func if isinstance(node, ast.Call) else node.value
    return node.id if isinstance(node, ast.Name) else None


def _dispatch_root(test: ast.expr) -> str | None:
    """The root name of *test* when it is an invariant dispatch, else None.

    An invariant dispatch is a mapping read compared to a literal — the shape
    a handler branches on. Deliberately narrow: anything that could *do*
    something when asked (a parser's ``accept_*``, a generator's ``next``) is
    not one, because asking it twice is not asking the same question.
    """
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return None
    if not isinstance(test.ops[0], (ast.Eq, ast.NotEq, ast.In, ast.NotIn)):
        return None
    if not all(isinstance(c, ast.Constant) for c in test.comparators):
        return None
    left = test.left
    if isinstance(left, ast.Call):
        if not (isinstance(left.func, ast.Attribute) and left.func.attr == "get"):
            return None
        if left.keywords or not all(isinstance(a, ast.Constant) for a in left.args):
            return None
    elif not isinstance(left, ast.Subscript):
        return None
    return _root_name(left)


def _names_assigned(statements: list[ast.stmt]) -> set[str]:
    return {
        node.id
        for statement in statements
        for node in ast.walk(statement)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    }


def _statement_lists(function: ast.AST):
    """Every straight-line statement list inside *function*."""
    yield function.body
    for child in ast.walk(function):
        for field in ("body", "orelse", "finalbody"):
            value = getattr(child, field, None)
            if isinstance(value, list) and value and child is not function:
                yield value


def _shadowed_branches(path: pathlib.Path) -> list[str]:
    findings: list[str] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return findings
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for body in _statement_lists(function):
            settled: dict[str, tuple[int, int]] = {}
            for index, statement in enumerate(body):
                if not isinstance(statement, ast.If):
                    continue
                key = ast.unparse(statement.test)
                root = _dispatch_root(statement.test)
                if root is None:
                    # Not an invariant dispatch: whatever it asks, a previous
                    # answer to the same words says nothing about it.
                    settled.pop(key, None)
                    continue
                if key in settled:
                    first_index, first_line = settled[key]
                    if root in _names_assigned(body[first_index + 1:index]):
                        # Re-bound in between, so it really is a new question.
                        settled[key] = (index, statement.lineno)
                        continue
                    findings.append(
                        f"{path.relative_to(_REPO).as_posix()}:{statement.lineno} "
                        f"in {function.name}(): `if {key}:` is unreachable — "
                        f"line {first_line} already answered it and returned"
                    )
                    continue
                if statement.body and _always_leaves(statement.body[-1]) and not statement.orelse:
                    settled[key] = (index, statement.lineno)
    return findings


def test_no_function_re_asks_a_dispatch_it_already_returned_on():
    findings: list[str] = []
    scanned = 0
    for root in _ROOTS:
        for path in sorted((_REPO / root).rglob("*.py")):
            scanned += 1
            findings.extend(_shadowed_branches(path))
    # The vacuity check the classifier needs: a scan that stopped finding files
    # would report a clean pool it never looked at.
    assert scanned > 200, f"the scan only reached {scanned} files"
    assert findings == [], (
        "unreachable duplicate dispatch branches — the merge-shadowing shape "
        "that lives inside one function, where a repeated top-level name "
        "cannot be seen:\n  " + "\n  ".join(findings)
    )
