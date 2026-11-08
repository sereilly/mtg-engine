"""Every departure made in a loop is made inside one departure event
(CR 603.10a, 704.3).

CR 603.10a: a leaves-the-battlefield ability — and one that triggers when a
player sacrifices a permanent, or when an object all players can see is put
into a hand or library — looks back in time, "using the existence of those
abilities and the appearance of objects immediately prior to the event": every
permanent one event takes off the battlefield is an observer of everything
else it takes. The engine performs such an event as several removals, one
after another: once per seat (Shatterstorm, Jokulhaups), once per permanent
("destroy all creatures", Upheaval's "return all permanents", a cost of
"sacrifice all permanents you control"), once per rule of one state-based
check. An observer the first removal took was off the battlefield for the
rest: Massacre Wurm destroyed by Wrath of God before the opponent's creatures
saw none of them die (``tests/regressions/test_kg4_together_one_departure_event.py``),
and Warped Devotion returned by Upheaval ahead of the creatures saw none of them
go (``tests/rules/test_kg4_departures_look_back.py``).

The census reads the source. Which functions take a permanent off the
battlefield is derived, not listed: the one transition
(``remove_from_battlefield`` / ``remove_all_from_battlefield``) and every
function that calls it, or calls one that does — two calls deep, by name. Every
call of one of them made **in a loop** (the body of a ``for`` / ``while``, or a
comprehension's element — not the iterable, which is evaluated once) must sit
inside a ``with ….leaving_together():`` block, or be in ``_REVIEWED`` with the
reason its loop is not one event. The state-based check wraps each pass in one
(``_check_state_based_actions`` around ``_state_based_pass``).

Backwards: on kg4/together's base it named the 10 destruction loops that round
wrapped; on 4c3d6e34 (that round merged) it names the 26 sacrifice, exile,
bounce, tuck and cost loops kg4/departures wrapped.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from tests.source_index import source_tree

ENGINE = Path(__file__).resolve().parents[2] / "engine"

_TRANSITION = frozenset({"remove_from_battlefield", "remove_all_from_battlefield"})

#: Functions that reach the transition but are not a departure of their own.
_NOT_DEPARTURES = {
    "phase_out_permanent": (
        "phasing out is not a zone change (CR 702.26d): it calls the "
        "transition with ``zone_change=False``, which records nothing and "
        "announces no leaves-the-battlefield ability; the only phase-out "
        "triggers the pool prints are the phasing permanent's own (CR 603.10b)."
    ),
    "_remove_aura_effects": (
        "an attachment's teardown (CR 611.3); its one removal, Animate Dead's "
        "sacrifice, is a leaves-the-battlefield trigger performed inline, and "
        "it waits for the departure event to close "
        "(``Game.after_this_departure``)."
    ),
}

#: ``(module, function, called) -> why that loop is not one departure event``.
_REVIEWED = {
    ("phases/end_step.py", "_begin_end_step", "_destroy_swept_permanents"): (
        "each \"destroy it at the beginning of the next end step\" mark is its "
        "own delayed triggered ability (CR 603.7), so each destruction is its "
        "own event; the engine performs them in one sweep rather than one "
        "stack object each, which is a shortcut of its own."
    ),
    ("phases/end_step.py", "_begin_end_step", "sacrifice_permanent"): (
        "each \"sacrifice it at the beginning of the next end step\" mark is "
        "its own delayed triggered ability (CR 603.7), so each sacrifice is "
        "its own event, as the cleanup step's flash-Aura sacrifices are."
    ),
    ("phases/end_step.py", "_begin_end_step", "remove_from_battlefield"): (
        "Rakalite's \"return this artifact to its owner's hand at the beginning "
        "of the next end step\": each is its own delayed triggered ability "
        "(CR 603.7), as the destructions above."
    ),
    ("phases/end_of_combat_step.py", "_resolve_end_of_combat_destruction",
     "_destroy_swept_permanents"): (
        "the same, at end of combat: each \"destroy that creature at end of "
        "combat\" (Infinite Authority) is its own delayed triggered ability."
    ),
    ("phases/cleanup_step.py", "_sacrifice_permanents_cast_at_instant_speed",
     "sacrifice_permanent"): (
        "each \"sacrifice it at the beginning of the next cleanup step\" mark is "
        "its own delayed triggered ability (CR 603.7)."
    ),
    ("mixins/stack/cast_additional_costs.py", "_pay_sacrifice_tax",
     "sacrifice_permanent"): (
        "Drought's tax is one additional \"Sacrifice a Swamp\" per black mana "
        "symbol — several costs, each paid in its turn (CR 601.2h: \"in any "
        "order\")."
    ),
    ("mixins/stack/cast_additional_costs.py", "_pay_additional_costs",
     "remove_from_battlefield"): (
        "the loop is over the spell's additional costs, each its own payment "
        "(CR 601.2h); this one exiles one permanent. A cost that moves several "
        "is wrapped where it loops."
    ),
    ("phases/declare_attackers_step.py", "_pay_declaration_sacrifices",
     "sacrifice_permanent"): (
        "one attack cost per creature, each its own cost paid in its turn "
        "(CR 508.1j, as 601.2h)."
    ),
    ("mixins/stack/choices/sacrifice.py", "_open_balance_round",
     "_finish_balance_round"): (
        "Balance's three rounds are three events (its ruling: lands, then cards "
        "in hand, then creatures); each round's sacrifices are one "
        "``sacrifice_permanents``."
    ),
    ("mixins/land_tapped_for_mana.py", "_land_tapped_for_mana",
     "_resolve_tapped_land_trigger_step"): (
        "the steps of one triggered ability, performed in the order written "
        "(CR 608.2c) — a sequence, not one action."
    ),
    ("mixins/effects.py", "_destroy_target_permanent", "_do_destroy"): (
        "a fallback scan for the first legal permanent; it returns after one."
    ),
    ("phases/upkeep_step.py", "_force_sacrifice_first_land",
     "sacrifice_permanent"): (
        "a scan for the one land to sacrifice; it returns after one."
    ),
}


def _trees():
    # The shared cache's trees (`tests/source_index.py`): every other engine
    # sweep in the worker reads the same ones, where a parse of its own held a
    # second copy of the engine's trees (~400 MB) while the test ran.
    return {path: source_tree(path) for path in sorted(ENGINE.rglob("*.py"))}


def _called_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    if isinstance(call.func, ast.Name):
        return call.func.id
    return None


@lru_cache(maxsize=1)
def _departing_functions() -> frozenset[str]:
    """The transition and every function calling it, two calls deep, by name —
    less the ones in ``_NOT_DEPARTURES``."""
    calls_of: dict[str, set[str]] = defaultdict(set)
    for tree in _trees().values():
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call):
                        name = _called_name(sub)
                        if name:
                            calls_of[node.name].add(name)
    reaching = set(_TRANSITION)
    for _ in range(2):
        reaching |= {
            function for function, called in calls_of.items()
            if called & reaching and function not in _NOT_DEPARTURES
        }
    return frozenset(reaching - set(_NOT_DEPARTURES))


def _in_a_loop(node, parent) -> bool:
    """Whether *node* runs once per repetition of a loop around it in its own
    function: in a ``for`` / ``while`` body (or a ``while`` test), or in a
    comprehension's element, conditions or a later generator — never the
    iterable a loop is handed, which is evaluated once."""
    child = node
    while child in parent:
        holder = parent[child]
        if isinstance(holder, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            return False
        if isinstance(holder, (ast.For, ast.AsyncFor)) and child is not holder.iter:
            return True
        if isinstance(holder, ast.While):
            return True
        if isinstance(holder, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            first = holder.generators[0]
            if child is not first:
                return True
        if isinstance(holder, ast.comprehension) and child is not holder.iter:
            return True
        child = holder
    return False


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


def _enclosing_function(node, parent):
    while node in parent:
        node = parent[node]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node
    return None


@lru_cache(maxsize=1)
def _census():
    departing = _departing_functions()
    unwrapped, wrapped, reviewed = [], [], []
    for path, tree in _trees().items():
        parent = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parent[child] = node
        module = path.relative_to(ENGINE).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = _called_name(node)
            if called not in departing or not _in_a_loop(node, parent):
                continue
            func = _enclosing_function(node, parent)
            if func is None:
                continue
            row = (module, func.name, called)
            if _in_block(node, parent, "leaving_together"):
                wrapped.append(row)
            elif row in _REVIEWED:
                reviewed.append(row)
            elif module == "mixins/game_ending.py" and func.name == "_state_based_pass":
                # One pass of the check, wrapped by its one caller (below).
                wrapped.append(row)
            else:
                unwrapped.append(f"{module}:{node.lineno} {func.name} -> {called}")
    return tuple(unwrapped), tuple(wrapped), tuple(reviewed)


def test_the_census_knows_the_departure_roads():
    departing = _departing_functions()
    assert {
        "sacrifice_permanent", "sacrifice_permanents", "_destroy_swept_permanents",
        "return_permanent_to_owners_hand", "remove_from_battlefield",
    } <= departing, sorted(departing)
    assert not set(_NOT_DEPARTURES) & departing


def test_every_departure_made_in_a_loop_is_one_event():
    unwrapped, wrapped, reviewed = _census()
    assert not unwrapped, (
        "permanents taken off the battlefield in a loop outside `with "
        "game.leaving_together():` (CR 603.10a) — wrap the loop, or review it "
        "in _REVIEWED:\n" + "\n".join(unwrapped)
    )
    # Measured at kg4/departures: 31 calls in handlers, choices and costs
    # wrapped, the state-based pass's 19 sweeps, and the players a check
    # eliminates.
    assert len(wrapped) >= 50, wrapped
    destructions = [row for row in wrapped if row[2] == "_destroy_swept_permanents"]
    # kg4/together's ten destruction loops, and the pass's five sweeps.
    assert len(destructions) >= 14, destructions


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


def test_the_sacrifice_transitions_open_the_event_they_announce_in():
    """"Whenever you sacrifice a permanent" is announced once the permanent has
    gone, and looks back in time (CR 603.10a): both sacrifice transitions make
    their removal and their announcement inside one departure event, so the
    permanent sacrificed is an observer of its own sacrifice."""
    tree = ast.parse((ENGINE / "mixins" / "deaths.py").read_text(encoding="utf-8"))
    for name in ("sacrifice_permanent", "sacrifice_permanents"):
        function = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == name
        )
        parent = {}
        for node in ast.walk(function):
            for child in ast.iter_child_nodes(node):
                parent[child] = node
        emits = [
            node for node in ast.walk(function)
            if isinstance(node, ast.Call) and _called_name(node) == "emit"
        ]
        assert emits, name
        assert all(_in_block(node, parent, "leaving_together") for node in emits), name
