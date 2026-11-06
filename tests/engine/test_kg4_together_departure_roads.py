"""Every destruction made in a loop is made inside one departure event
(CR 603.10a, 704.3).

CR 603.10a: a leaves-the-battlefield ability looks back in time, "using the
existence of those abilities and the appearance of objects immediately prior
to the event" — every permanent one event takes off the battlefield is an
observer of every other death in it. The engine performs such an event as
several removals, one after another: ``_destroy_swept_permanents`` once per
seat (Shatterstorm, Jokulhaups), once per permanent ("destroy all creatures",
"destroy two target creatures"), once per rule of one state-based check. A
dying observer the first removal took was off the battlefield for the rest:
Massacre Wurm destroyed by Wrath of God before the opponent's creatures saw
none of them die (``tests/regressions/test_kg4_together_one_departure_event.py``
is the board).

The census reads the source: every call of ``_destroy_swept_permanents``
inside a ``for`` / ``while`` / comprehension must sit inside a ``with
….leaving_together():`` block, or be in ``_REVIEWED`` with the reason its
loop is not one event. And the state-based check wraps each pass in one
(``_check_state_based_actions`` around ``_state_based_pass``). Backwards: on
the base it names the 10 calls this round wrapped, and the pass.

Only the destruction road. A loop of sacrifices, exiles or bounces over
several permanents is the same shape, and is not yet held here.
"""
from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[2] / "engine"

_DESTRUCTION = "_destroy_swept_permanents"

#: ``(module, function) -> why its loop is not one departure event``.
_REVIEWED = {
    ("phases/end_step.py", "_begin_end_step"): (
        "each \"destroy it at the beginning of the next end step\" mark is its "
        "own delayed triggered ability (CR 603.7), so each destruction is its "
        "own event; the engine performs them in one sweep rather than one "
        "stack object each, which is a shortcut of its own."
    ),
    ("phases/end_of_combat_step.py", "_resolve_end_of_combat_destruction"): (
        "the same, at end of combat: each \"destroy that creature at end of "
        "combat\" (Infinite Authority) is its own delayed triggered ability."
    ),
}


def _trees():
    return {
        path: ast.parse(path.read_text(encoding="utf-8"))
        for path in sorted(ENGINE.rglob("*.py"))
    }


def _in_block(node, parent, attr: str) -> bool:
    while node in parent:
        node = parent[node]
        if isinstance(node, ast.With) and any(
            isinstance(item.context_expr, ast.Call)
            and isinstance(item.context_expr.func, ast.Attribute)
            and item.context_expr.func.attr == attr
            for item in node.items
        ):
            return True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return False
    return False


@lru_cache(maxsize=1)
def _census():
    unwrapped, wrapped, reviewed = [], [], []
    for path, tree in _trees().items():
        parent = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parent[child] = node
        module = path.relative_to(ENGINE).as_posix()
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == _DESTRUCTION
            ):
                continue
            cur, loop, func = node, None, None
            while cur in parent:
                cur = parent[cur]
                if loop is None and isinstance(
                    cur, (ast.For, ast.While, ast.comprehension)
                ):
                    loop = cur
                if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    func = cur
                    break
            if loop is None or func is None:
                continue
            row = (module, func.name)
            if _in_block(node, parent, "leaving_together"):
                wrapped.append(row)
            elif row in _REVIEWED:
                reviewed.append(row)
            elif module == "mixins/game_ending.py" and func.name == "_state_based_pass":
                # One pass of the check, wrapped by its one caller (below).
                wrapped.append(row)
            else:
                unwrapped.append(f"{module}:{node.lineno} {func.name}")
    return tuple(unwrapped), tuple(wrapped), tuple(reviewed)


def test_every_destruction_made_in_a_loop_is_one_event():
    unwrapped, wrapped, reviewed = _census()
    assert not unwrapped, (
        "destructions made in a loop outside `with game.leaving_together():` "
        "(CR 603.10a) — wrap the loop, or review it in _REVIEWED:\n"
        + "\n".join(unwrapped)
    )
    # Measured at kg4/together: 10 calls wrapped in handlers, and the five
    # sweeps of one state-based pass.
    assert len(wrapped) >= 14, wrapped


def test_every_reviewed_loop_is_still_a_loop():
    _unwrapped, _wrapped, reviewed = _census()
    assert set(_REVIEWED) <= set(reviewed), sorted(set(_REVIEWED) - set(reviewed))


def test_one_state_based_pass_is_one_event():
    """``_check_state_based_actions`` runs each pass inside one departure
    event and one entry event (CR 704.3, 610.3d)."""
    tree = ast.parse((ENGINE / "mixins" / "game_ending.py").read_text(encoding="utf-8"))
    check = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_check_state_based_actions"
    )
    blocks = [
        node for node in ast.walk(check)
        if isinstance(node, ast.With)
        and any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "_state_based_pass"
            for n in ast.walk(node)
        )
    ]
    assert blocks, "the pass is not called inside a with block"
    entered = {
        item.context_expr.func.attr
        for block in blocks for item in block.items
        if isinstance(item.context_expr, ast.Call)
        and isinstance(item.context_expr.func, ast.Attribute)
    }
    assert {"leaving_together", "entering_together"} <= entered, entered
