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


# ---------------------------------------------------------------------------
# CR 616.1's last sentence: several seats asked about one effect's damage are
# asked in APNAP order
# ---------------------------------------------------------------------------

#: Loops that deal damage and are *not* walked through
#: ``effect_ordering.in_apnap_order``, by (module, enclosing function), each
#: with the reason its order is not a CR 616.1 question — or the round that
#: owes it. A loop missing from here and not ordered fails; an entry naming no
#: such loop fails too, so the table cannot outlive what it excuses.
_NOT_APNAP = {
    ("handlers/damage.py", "deal_damage_and_opponent_choice"):
        "a loop over the sentence's two halves, not its recipients: the "
        "second half's is the opponent's pick, made as that half is reached; "
        "both halves' chunks are collected and dealt in APNAP order by "
        "simultaneous_damage.deal_sentence once it is made (kg4 `dealings`)",
    ("phases/combat_damage_step.py", "resolve_all_combat_damage"):
        "first-strike and regular passes, not recipients (CR 510.4)",
}


def _enclosing(parents, node):
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current
    return None


def _defs(tree):
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found.setdefault(node.name, node)
    return found


def _deals(node, defs, seen) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            if _is_entry(sub):
                return True
            called = _name(sub)
            if called in defs and called not in seen:
                seen.add(called)
                if _deals(defs[called], defs, seen):
                    return True
        if isinstance(sub, ast.Name) and sub.id in defs and sub.id not in seen:
            seen.add(sub.id)
            if _deals(defs[sub.id], defs, seen):
                return True
    return False


def _ordered(items, function) -> bool:
    """*items* is ``in_apnap_order(...)``, or a name the enclosing function
    assigned from it."""
    if isinstance(items, ast.Call) and _name(items) == "in_apnap_order":
        return True
    if isinstance(items, ast.Name) and function is not None:
        for node in ast.walk(function):
            if (
                isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == items.id for t in node.targets)
                and isinstance(node.value, ast.Call)
                and _name(node.value) == "in_apnap_order"
            ):
                return True
    return False


#: ``simultaneous_damage.deal_at_once``: the one loop every effect dealing
#: damage to several recipients at once runs (kg3 `dealings`). A call to it is
#: a damage loop by construction, and walks its items through
#: ``in_apnap_order`` itself.
_AT_ONCE = "deal_at_once"


def _damage_loops():
    loops = []
    for path in sorted(_ENGINE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        defs = _defs(tree)
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        where_file = path.relative_to(_ENGINE).as_posix()
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and _name(node) in ("run_resumable", _AT_ONCE)
            ):
                continue
            if len(node.args) < 3:
                continue
            items, step = node.args[1], node.args[2]
            at_once = _name(node) == _AT_ONCE
            if not at_once and not (
                _deals(step, defs, set()) or _deals(items, defs, set())
            ):
                continue
            function = _enclosing(parents, node)
            outer = function
            while outer is not None and _enclosing(parents, outer) is not None:
                outer = _enclosing(parents, outer)
            loops.append((
                where_file, node.lineno, outer.name if outer is not None else "",
                at_once or _ordered(items, function),
            ))
    return loops


def test_every_loop_dealing_damage_asks_its_seats_in_apnap_order():
    loops = _damage_loops()
    # A floor on what was examined: 24 loops when this was written, 19 once
    # kg3 `events` made the combat damage step's six nested loops one loop
    # over its APNAP-ordered chunks.
    assert len(loops) >= 15, loops
    unordered = [
        f"{where}:{line} ({function})" for where, line, function, ordered in loops
        if not ordered and (where, function) not in _NOT_APNAP
    ]
    assert not unordered, (
        "a loop dealing damage to several recipients at once asks their seats "
        "in its own order; walk it through effect_ordering.in_apnap_order "
        f"(CR 616.1's last sentence): {unordered}"
    )
    excused = {(where, function) for where, _, function, _ in loops}
    stale = [key for key in _NOT_APNAP if key not in excused]
    assert not stale, f"exemptions naming no damage loop: {stale}"
