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
"""

from __future__ import annotations

import ast
from pathlib import Path

import engine.mixins.stack.activation as activation_module

#: Calls that move game state as a cost is paid. A call to one of these above
#: the mana payment is a cost paid before the activation is known to be legal.
_PAYMENTS = frozenset({
    "become_tapped", "become_untapped", "remove_counters", "add_counters",
    "place_pt_counters", "sacrifice_permanent", "_pay_sacrifice_tax",
    "take_card_from_hand", "_discard_card", "remove_from_battlefield",
    "put_card_into_hand", "put_card_into_library", "_pay_exile_cost",
})


def _method():
    tree = ast.parse(Path(activation_module.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_activate_onto_stack":
            return node
    raise AssertionError("_activate_onto_stack not found")


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


def _hinge_line(method) -> int:
    lines = [
        node.lineno for node in ast.walk(method)
        if isinstance(node, ast.Call) and _called_name(node) == "_pay_mana_cost"
    ]
    assert len(lines) == 1, f"expected one mana payment in the method, found {lines}"
    return lines[0]


def _hinge_end(method) -> int:
    """The last line of the ``if not self._pay_mana_cost(...)`` block: its own
    refusal — the payment failing — is the one refusal allowed at the hinge."""
    for node in ast.walk(method):
        if isinstance(node, ast.If) and any(
            isinstance(inner, ast.Call) and _called_name(inner) == "_pay_mana_cost"
            for inner in ast.walk(node.test)
        ):
            return node.end_lineno
    raise AssertionError("the mana payment is not the test of an if-block")


def test_no_refusal_is_written_below_the_mana_payment():
    method = _method()
    hinge = _hinge_end(method)
    late = [
        node.lineno for node in ast.walk(method)
        if _is_refusal(node) and node.lineno > hinge
    ]
    assert not late, (
        f"refusal(s) at line(s) {late} come after the mana payment at line "
        f"{hinge}: an activation refused there has already paid"
    )
    # Floor: the method refuses in dozens of places; a reader that finds none
    # has stopped reading the method rather than found it clean.
    early = [node for node in ast.walk(method) if _is_refusal(node)]
    assert len(early) >= 40, len(early)


def test_no_cost_is_paid_above_the_mana_payment():
    method = _method()
    hinge = _hinge_line(method)
    early = sorted(
        (node.lineno, _called_name(node)) for node in ast.walk(method)
        if isinstance(node, ast.Call)
        and _called_name(node) in _PAYMENTS
        and node.lineno < hinge
    )
    assert not early, (
        f"payment(s) {early} come before the mana payment at line {hinge}: "
        "a refusal between them would leave the cost paid"
    )
    # Floor: the payments do exist below the hinge.
    late = {
        _called_name(node) for node in ast.walk(method)
        if isinstance(node, ast.Call) and _called_name(node) in _PAYMENTS
    }
    assert {"become_tapped", "_pay_exile_cost", "sacrifice_permanent"} <= late, late
