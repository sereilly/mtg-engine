"""Every entry made in a loop is made inside one event (CR 603.6a).

CR 603.6a: "Each time an event puts one or more permanents onto the
battlefield, all permanents on the battlefield (including the newcomers) are
checked for any enters-the-battlefield triggers that match the event." An
engine loop that calls the entry seam once per permanent puts them there one
at a time unless it opens the event around them
(``Game.entering_together``): then each entry's state is performed as its call
is made and every newcomer is announced with all of them present. Outside the
block, an observer among the newcomers sees only those that entered after it
— Goblin Assassin returned by Planar Guide after a Goblin Clearcutter
triggered once (``tests/regressions/test_kg3_batch_enter_together_census.py``
is the board).

The census reads the source. Which functions put a permanent onto the
battlefield is derived, not listed: the entry seam, and every function that
calls one that does, three calls deep, through names defined at most twice
(a name as common as ``resolve`` would reach everything). Every call of one of
them inside a ``for`` / ``while`` / comprehension must sit inside a ``with
….entering_together():`` block, or be in ``_REVIEWED`` with the reason its
loop is not one event. Backwards: on the base, before the roads were
converted, it names the 33 calls that were.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[2] / "engine"

_SEAM = "_put_permanent_onto_battlefield"

#: The seam's own machinery, which is not a road.
_INTERNAL = frozenset({
    _SEAM, "_enter_battlefield", "_finish_or_await", "_complete_entries",
    "_announce_entry", "entering_together", "_finish_answered_entries",
})

#: ``(module, function, called) -> why that loop is not one event``.
_REVIEWED = {
    ("phases/upkeep_step.py", "_resolve_upkeep_actions", _SEAM): (
        "Nether Shadow's return: each copy's \"at the beginning of your "
        "upkeep … you may put this card onto the battlefield\" is its own "
        "triggered ability, so each return is its own event (CR 603.2)."
    ),
    ("handlers/reveal.py", "put_revealed_card_onto_battlefield", _SEAM): (
        "the loop finds the one revealed card and returns after entering it."
    ),
    ("mixins/effects.py", "_reanimate_creature_to_battlefield", "arrive"): (
        "a fallback scan for the first eligible card; it returns after one."
    ),
    ("mixins/stack/choices/search.py", "_default_search_library",
     "_resolve_search_library"): (
        "a fallback that tries findable cards until one is taken, then returns."
    ),
    ("handlers/phasing.py", "phase_out_target_creature_until_source_leaves",
     "remove_all_from_battlefield"): (
        "phasing out (``zone_change=False``) gives back no linked exile."
    ),
    ("mixins/game_ending.py", "_check_state_based_actions",
     "remove_all_from_battlefield"): (
        "each sweep's linked returns are one event inside "
        "``remove_all_from_battlefield``; the sweeps of one pass are separate "
        "calls — CR 704.3 makes one pass one event, a known gap (the pass "
        "would have to be extracted to be wrapped)."
    ),
    ("mixins/stack/resolution.py", "resolve_stack", "resolve_top_of_stack"): (
        "each stack object resolves as its own event."
    ),
    ("ai_compelled_blocks.py", "_shed_for_the_block", "resolve_top_of_stack"): (
        "each stack object resolves as its own event."
    ),
    ("ai_simulator.py", "run_ai_simulation", "_play_rest_of_turn"): (
        "one turn after another."
    ),
}


def _trees():
    return {
        path: ast.parse(path.read_text(encoding="utf-8"))
        for path in sorted(ENGINE.rglob("*.py"))
    }


def _called(func) -> set[str]:
    names = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                names.add(node.func.attr)
            elif isinstance(node.func, ast.Name):
                names.add(node.func.id)
    return names


def _entering_functions(trees) -> set[str]:
    defined = defaultdict(list)
    for tree in trees.values():
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defined[node.name].append(node)
    reaching = {_SEAM}
    for _level in range(3):
        frontier = set()
        for name, funcs in defined.items():
            if name in reaching or len(funcs) > 2:
                continue
            if any(_called(func) & reaching for func in funcs):
                frontier.add(name)
        reaching |= frontier
    return reaching


def _in_together_block(node, parent) -> bool:
    while node in parent:
        node = parent[node]
        if isinstance(node, ast.With) and any(
            isinstance(item.context_expr, ast.Call)
            and isinstance(item.context_expr.func, ast.Attribute)
            and item.context_expr.func.attr == "entering_together"
            for item in node.items
        ):
            return True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return False
    return False


def _census():
    trees = _trees()
    entering = _entering_functions(trees)
    unbatched, batched, reviewed = [], [], []
    for path, tree in trees.items():
        parent = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parent[child] = node
        module = path.relative_to(ENGINE).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = (
                node.func.attr if isinstance(node.func, ast.Attribute)
                else node.func.id if isinstance(node.func, ast.Name) else None
            )
            if called not in entering or (called in _INTERNAL and called != _SEAM):
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
            if loop is None or func is None or func.name in _INTERNAL:
                continue
            row = (module, func.name, called)
            if _in_together_block(node, parent):
                batched.append(row)
            elif row in _REVIEWED:
                reviewed.append(row)
            else:
                unbatched.append(f"{module}:{node.lineno} {func.name} calls {called}")
    return entering, unbatched, batched, reviewed


def test_every_entry_made_in_a_loop_is_one_event():
    entering, unbatched, batched, reviewed = _census()
    assert not unbatched, (
        "entries made in a loop outside `with game.entering_together():` "
        "(CR 603.6a) — wrap the loop, or review it in _REVIEWED:\n"
        + "\n".join(unbatched)
    )
    # Measured at kg3/batch: 87 functions reach the seam, 33 calls in loops
    # are inside the block and 12 (nine rows) are reviewed.
    assert len(entering) >= 60, len(entering)
    assert len(batched) >= 28, len(batched)


def test_every_reviewed_loop_is_still_a_loop():
    """A reviewed row whose loop went away is a reason nobody reads."""
    _entering, _unbatched, _batched, reviewed = _census()
    assert set(_REVIEWED) <= set(reviewed), sorted(set(_REVIEWED) - set(reviewed))
