"""Guard: an activation checks everything before it pays anything.

``_activate_onto_stack`` is arranged as CR 601.2h (through CR 602.2b) asks and
as CR 733.1 makes cheap: every refusal first, then every payment, so a refused
activation has nothing to give back. The **mana payment is the hinge** — it is
the last gate (``_pay_mana_cost`` is all-or-nothing) and the first payment.

Two breaches of that shape shipped for a long time, and neither crashed:
the {T} symbol's refusals sat *below* the mana payment (535 abilities spent
mana into a refusal), and a chosen exile cost was paid as it was chosen, above
five refusals (City of Shadows exiled a creature while already tapped). The
behavioural sweep in ``tests/regressions/test_refused_activation_spends_nothing.py``
runs three engineered refusals over the shipped pool; this guard is the
structural half, which also covers refusals no sweep board engineers (a Drought
tax, an attached host's mana cost, a card-defined X): it reads the method and
fails on a refusal written below the hinge, or a payment written above it.

Validated backwards: against the pre-fix method it fails on both halves — two
refusals below the hinge (summoning sickness, already tapped) and
``_pay_exile_cost`` above it.

**The method is read with its steps in place.** At the 2,000-line cap the
method's CR steps moved out of it whole into ``activation_checks`` and
``activation_charges``, and it calls them in order (``_STEPS``); the hinge
stayed in the method. A step's body is read *where the method calls it*, so
the order checked is the activation's — a refusal in a step called below the
hinge is a refusal below the hinge — where reading the method alone would see
seven refusals and no payment at all.
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
from pathlib import Path

import engine.mixins.stack as stack_package
import engine.mixins.stack.activation as activation_module
import engine.mixins.stack.activation_payment as payment_module

#: Calls that move game state as a cost is paid. A call to one of these above
#: the mana payment is a cost paid before the activation is known to be legal.
_PAYMENTS = frozenset({
    "become_tapped", "become_untapped", "remove_counters", "add_counters",
    "place_pt_counters", "sacrifice_permanent", "_pay_sacrifice_tax",
    "take_card_from_hand", "_discard_card", "remove_from_battlefield",
    "put_card_into_hand", "put_card_into_library", "_pay_exile_cost",
})


#: The steps ``_activate_onto_stack`` calls, in its order: each was moved out
#: of the method whole and is read where the method calls it.
_STEPS = (
    "_activation_source", "_chosen_activated_ability",
    "_settled_activation_division", "_activation_window",
    "_choose_activation_cost_payers", "_pay_activation_costs",
)


def _definitions() -> dict:
    """Every function defined in ``engine.mixins.stack``'s modules, by name —
    walked as a package, so a step that moves to a new module is still found."""
    found: dict = {}
    modules = 0
    for info in pkgutil.iter_modules(stack_package.__path__):
        if info.ispkg:
            continue
        module = importlib.import_module(f"{stack_package.__name__}.{info.name}")
        modules += 1
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                found.setdefault(node.name, []).append(node)
    assert modules >= 10, modules
    return found


def _method():
    """The method as the activation runs it: ``[(position, node)]`` for every
    node of ``_activate_onto_stack`` and of each step it calls, a step's nodes
    positioned at the line of its call."""
    tree = ast.parse(Path(activation_module.__file__).read_text(encoding="utf-8"))
    method = next(
        (node for node in ast.walk(tree)
         if isinstance(node, ast.FunctionDef) and node.name == "_activate_onto_stack"),
        None,
    )
    assert method is not None, "_activate_onto_stack not found"
    definitions = _definitions()
    flat = [((node.lineno, 0), node) for node in ast.walk(method) if hasattr(node, "lineno")]
    called = []
    for node in ast.walk(method):
        if isinstance(node, ast.Call) and _called_name(node) in _STEPS:
            step = definitions.get(_called_name(node), [])
            assert len(step) == 1, (_called_name(node), len(step))
            called.append((node.lineno, _called_name(node)))
            flat += [
                ((node.lineno, inner.lineno), inner)
                for inner in ast.walk(step[0]) if hasattr(inner, "lineno")
            ]
    # Every step is called, once each and in its order: a step the method
    # stopped calling would take its refusals and payments out of the reading.
    assert [name for _line, name in sorted(called)] == list(_STEPS), called
    return flat


def _called_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _is_refusal(node: ast.AST) -> bool:
    """``return SimulationResult(<name>, False, ...)``."""
    if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Call):
        return False
    call = node.value
    if _called_name(call) != "SimulationResult" or len(call.args) < 2:
        return False
    flag = call.args[1]
    return isinstance(flag, ast.Constant) and flag.value is False


def _hinge_line(method) -> tuple:
    lines = [
        position for position, node in method
        if isinstance(node, ast.Call) and _called_name(node) == "_pay_mana_cost"
    ]
    assert len(lines) == 1, f"expected one mana payment in the method, found {lines}"
    return lines[0]


def _hinge_end(method) -> tuple:
    """Where the ``if not self._pay_mana_cost(...)`` block ends: its own
    refusal — the payment failing — is the one refusal allowed at the hinge."""
    for (line, inner_line), node in method:
        if isinstance(node, ast.If) and any(
            isinstance(inner, ast.Call) and _called_name(inner) == "_pay_mana_cost"
            for inner in ast.walk(node.test)
        ):
            return (node.end_lineno, 0) if not inner_line else (line, node.end_lineno)
    raise AssertionError("the mana payment is not the test of an if-block")


def test_no_refusal_is_written_below_the_mana_payment():
    method = _method()
    hinge = _hinge_end(method)
    late = [
        position for position, node in method
        if _is_refusal(node) and position > hinge
    ]
    assert not late, (
        f"refusal(s) at line(s) {late} come after the mana payment at line "
        f"{hinge}: an activation refused there has already paid"
    )
    # Floor: the method refuses in dozens of places; a reader that finds none
    # has stopped reading the method rather than found it clean. Forty-odd
    # until Torment's W2G3 moved every "the board cannot pay this" refusal
    # into one gate (``unpayable_activation_cost``) — which the method calls
    # once, **above the hinge**, and which says why in each of its returns.
    early = [node for _position, node in method if _is_refusal(node)]
    assert len(early) >= 25, len(early)
    gate_calls = [
        position for position, node in method
        if isinstance(node, ast.Call)
        and _called_name(node) == "unpayable_activation_cost"
    ]
    assert gate_calls and max(gate_calls) < _hinge_line(method), gate_calls
    # The gate went to ``activation_payment.py`` when ``activation.py`` split
    # at the 2,000-line cap; it is read where it is defined.
    gate = next(
        node for node in ast.walk(
            ast.parse(Path(payment_module.__file__).read_text(encoding="utf-8"))
        )
        if isinstance(node, ast.FunctionDef) and node.name == "unpayable_activation_cost"
    )
    reasons = [
        node for node in ast.walk(gate)
        if isinstance(node, ast.Return) and node.value is not None
        and not (isinstance(node.value, ast.Constant) and node.value.value is None)
    ]
    assert len(reasons) >= 18, len(reasons)


def test_no_cost_is_paid_above_the_mana_payment():
    method = _method()
    hinge = _hinge_line(method)
    early = sorted(
        (position, _called_name(node)) for position, node in method
        if isinstance(node, ast.Call)
        and _called_name(node) in _PAYMENTS
        and position < hinge
    )
    assert not early, (
        f"payment(s) {early} come before the mana payment at line {hinge}: "
        "a refusal between them would leave the cost paid"
    )
    # Floor: the payments do exist below the hinge.
    late = {
        _called_name(node) for _position, node in method
        if isinstance(node, ast.Call) and _called_name(node) in _PAYMENTS
    }
    assert {"become_tapped", "_pay_exile_cost", "sacrifice_permanent"} <= late, late
