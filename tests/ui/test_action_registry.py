"""Guards on the action-handler registry (web/action_registry.py).

``do_action`` used to be one ~1,540-line if/elif chain over every
``ActionKind`` — the hand-ordered-dispatch shape ``engine/parsing/`` was
deleted for, living in the web layer where no ratchet watched it. It is a
registry now, and these tests are what keep it one:

- every ``ActionKind`` literal has a handler (a literal without one costs that
  action its endpoint), with ``concede`` the single named exception — CR
  104.3a makes it available at any time, so it runs in the preamble before
  the pregame gate and the snapshot;
- nothing registers a kind the wire cannot send (a dead registration is a
  handler nobody can reach);
- ``do_action`` itself compares ``req.action`` only against the preamble's
  known gate kinds — a new ``elif req.action == ...`` arm growing back inside
  it fails here by naming a kind this list does not.
"""

from __future__ import annotations

import ast
import inspect
from typing import Literal, get_args

import web.actions as actions_module
from web.action_registry import ACTION_HANDLERS
from web.schemas import ActionKind

ACTION_KINDS = set(get_args(ActionKind))


def test_every_action_kind_has_a_handler_except_concede():
    missing = ACTION_KINDS - ACTION_HANDLERS.keys()
    assert missing == {"concede"}, (
        f"ActionKind literals without a registered handler: {sorted(missing - {'concede'})}"
        if missing - {"concede"}
        else "concede must stay a preamble special case (CR 104.3a), not a handler"
    )


def test_no_handler_is_registered_for_an_unsendable_kind():
    dead = ACTION_HANDLERS.keys() - ACTION_KINDS
    assert not dead, f"handlers registered for kinds the wire cannot send: {sorted(dead)}"


def test_the_registry_is_not_vacuously_small():
    """The two set comparisons above would both pass on an empty Literal and an
    empty registry; this is the same non-vacuity pin test_grammar_categories
    keeps on its table."""
    assert len(ACTION_HANDLERS) > 70


#: The kinds the dispatch preamble may legitimately name: the CR 104.3a early
#: return, the cleanup rewrite pair, and the step gates that refuse most
#: actions while a selection is owed. Adding a kind here is a decision about
#: the *preamble*; a returning dispatch arm fails by naming its kind.
_PREAMBLE_KINDS = {
    "concede",
    "cast",
    "cleanup_select",
    "untap_select",
    "untap_confirm",
    "optional_untap_confirm",
    "pay_upkeep",
    "sacrifice_upkeep",
    "resolve_optional_trigger",
    "pay_upkeep_prevention",
    "tap",
    "activate",
    "island_sanctuary_skip",
    "island_sanctuary_draw",
}


def _req_action_comparisons(func) -> set[str]:
    """Every string constant ``do_action`` compares ``req.action`` against."""
    tree = ast.parse(inspect.getsource(func))
    found: set[str] = set()

    def is_req_action(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Attribute)
            and node.attr == "action"
            and isinstance(node.value, ast.Name)
            and node.value.id == "req"
        )

    def constants(node: ast.AST) -> set[str]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return {node.value}
        if isinstance(node, (ast.Set, ast.Tuple, ast.List)):
            out: set[str] = set()
            for el in node.elts:
                out |= constants(el)
            return out
        if isinstance(node, ast.BinOp):
            return constants(node.left) | constants(node.right)
        return set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        sides = [node.left, *node.comparators]
        if any(is_req_action(side) for side in sides):
            for side in sides:
                found |= constants(side)
    return found


def test_do_action_dispatches_through_the_registry_not_a_chain():
    named = _req_action_comparisons(actions_module.do_action)
    regrown = named - _PREAMBLE_KINDS
    assert not regrown, (
        "do_action compares req.action against kinds outside the preamble's "
        f"gates — a dispatch arm is growing back: {sorted(regrown)}. Register "
        "a handler in web/action_registry.py instead."
    )
