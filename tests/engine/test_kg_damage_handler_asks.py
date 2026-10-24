"""Every damage call in ``engine/handlers`` can ask CR 616.1e's question, and
none of them runs past the question in a loop that does not record itself.

A damage event asks the affected player — or the affected object's controller
— which of several applicable prevention or replacement effects applies first
(CR 616.1, 616.1e) only when its caller hands it a way to re-run the event
(``asks=True``, or a ``restart``). The answer re-runs that one event; whatever
the caller had still to do behind it is brought back only if a resumable loop
recorded it (``engine/resumption.py``). So three shapes are wrong:

* a call with neither ``asks`` nor ``restart``: the seat is never asked and
  gets the default (sixteen calls at Judgment, ``SET_PLAYBOOK.md``'s
  Known-gaps entry);
* an asking call inside a plain ``for`` or ``while``: the loop runs on past
  the question, so the recipients behind the one that asked are dealt to
  before the answer (the bite-backs, The Fallen's opponents, Mana Clash);
* an asking call followed by another damage call in the same block: the
  second event lands before the first one's answer (the two halves of a
  fight).

The behaviour is held card by card in
``tests/regressions/test_kg_damage_loop_order_census.py``; this is the static
half, so a new handler cannot reintroduce a shape the census has no card for.
"""

from __future__ import annotations

import ast
from pathlib import Path

_ENTRY_POINTS = {"apply_damage_to_creature", "_mark_damage_on_permanent", "_deal_damage_to_player"}
_HANDLERS = Path(__file__).resolve().parents[2] / "engine" / "handlers"


def _name(call: ast.Call) -> str:
    return getattr(call.func, "attr", getattr(call.func, "id", ""))


def _is_entry(node) -> bool:
    return isinstance(node, ast.Call) and _name(node) in _ENTRY_POINTS


def _contains_entry(node) -> bool:
    """A damage call in *node*, not counting one inside a nested function —
    that runs when the function is called, not here."""
    stack = [node]
    while stack:
        current = stack.pop()
        if _is_entry(current):
            return True
        for child in ast.iter_child_nodes(current):
            if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                stack.append(child)
    return False


def _census():
    calls, unasked, in_loop, back_to_back = [], [], [], []
    for path in sorted(_HANDLERS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for node in ast.walk(tree):
            if not _is_entry(node):
                continue
            where = f"{path.name}:{node.lineno} {_name(node)}"
            calls.append(where)
            keywords = {keyword.arg for keyword in node.keywords}
            if not keywords & {"asks", "restart"}:
                unasked.append(where)
            current = node
            while current in parents:
                current = parents[current]
                if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                    break
                if isinstance(current, (ast.For, ast.While, ast.comprehension)):
                    in_loop.append(where)
                    break
        for node in ast.walk(tree):
            for field in ("body", "orelse", "finalbody"):
                block = getattr(node, field, None)
                if not isinstance(block, list):
                    continue
                for index, statement in enumerate(block):
                    if not (isinstance(statement, ast.Expr) and _is_entry(statement.value)):
                        continue
                    if any(_contains_entry(later) for later in block[index + 1:]):
                        back_to_back.append(f"{path.name}:{statement.lineno}")
    return calls, unasked, in_loop, back_to_back


def test_every_damage_call_in_the_handlers_can_ask_and_none_runs_past_the_question():
    calls, unasked, in_loop, back_to_back = _census()
    # A floor on what was examined: a census that found no calls has measured
    # nothing, and would pass.
    assert len(calls) >= 40, calls
    assert not unasked, (
        "a damage call that passes neither asks nor restart never asks CR "
        f"616.1e's question: {unasked}"
    )
    assert not in_loop, (
        "an asking damage call inside a plain loop runs the loop on past the "
        "question; use engine/resumption.run_resumable: " f"{in_loop}"
    )
    assert not back_to_back, (
        "a damage call followed by another in the same block deals the second "
        "before the first one's answer; make them one run_resumable loop: "
        f"{back_to_back}"
    )
