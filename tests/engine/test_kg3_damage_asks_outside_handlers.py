"""Every damage call in ``engine/`` outside ``engine/handlers`` can ask CR
616.1e's question, and none runs past the question in a loop that does not
record itself.

``tests/engine/test_kg_damage_handler_asks.py`` holds the handlers to this;
this is the same census over everything else that deals damage: the upkeep
effects resolved inline (``phases/upkeep_effects.py``), the prompt answers
(``mixins/effects.py``, ``mixins/stack/choices/``), the land riders, the
Aura entry branch, Eye for an Eye's mirror, the CR 614.9 redirects
(``replacements/redirects.py``), a shield's rider (``prevention/``) and the
combat damage step.

A damage event asks the affected player — or the affected object's
controller — which of several applicable prevention or replacement effects
applies first (CR 616.1, 616.1e) only when its caller hands it a way to
re-run the event (``asks=True``, or a ``restart``). Three shapes are wrong,
the same three the handler census names:

* a call with neither: the seat is never asked and gets the default — twenty
  one such calls at Legions (``SET_PLAYBOOK.md``'s Known-gaps entry), and one
  more the entry did not count;
* an asking call inside a plain ``for`` or ``while``: the recipients behind
  the one that asked are dealt to before the answer (Cyclone's two sweeps);
* an asking call followed by another damage call in the same block.

The behaviour is driven board by board in
``tests/regressions/test_kg3_damage_outside_handlers_ask.py``; this is the
static half, so a new damage call cannot reintroduce a shape the boards have
no card for.
"""

from __future__ import annotations

import ast
from pathlib import Path

_ENTRY_POINTS = {
    "apply_damage_to_creature", "_mark_damage_on_permanent",
    "_deal_damage_to_player", "deal_damage",
}
_ENGINE = Path(__file__).resolve().parents[2] / "engine"
_HANDLERS = _ENGINE / "handlers"


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


def _sources():
    for path in sorted(_ENGINE.rglob("*.py")):
        if _HANDLERS in path.parents:
            continue
        yield path


def _census():
    calls, unasked, in_loop, back_to_back = [], [], [], []
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        where_file = path.relative_to(_ENGINE).as_posix()
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for node in ast.walk(tree):
            if not _is_entry(node):
                continue
            # The effect handler named ``deal_damage`` is a definition, never
            # called by that name outside the handlers; a bare ``deal_damage``
            # here is ``damage_events.deal_damage``.
            where = f"{where_file}:{node.lineno} {_name(node)}"
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
                        back_to_back.append(f"{where_file}:{statement.lineno}")
    return calls, unasked, in_loop, back_to_back


def test_every_damage_call_outside_the_handlers_can_ask_and_none_runs_past_the_question():
    calls, unasked, in_loop, back_to_back = _census()
    # A floor on what was examined: a census that found no calls has measured
    # nothing, and would pass. 31 calls at Legions, the seam's own included;
    # 25 once the eight redirect hand-offs became one helper.
    assert len(calls) >= 20, calls
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
