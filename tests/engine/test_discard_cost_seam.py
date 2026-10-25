"""Guard: every discard paid **as a cost** tells the discard seam so.

A discard is one event (CR 701.9a), raised by ``Game._discard_card`` whether a
spell's effect or a cost caused it, and nearly everything that watches a
discard watches both: madness, Megrim, "whenever you discard a card". One
printed replacement does not: Library of Leng's "If **an effect** causes you
to discard a card" — and its 2004-10-04 ruling: "You can't use the Library of
Leng ability to place a discarded card on top of your library when you discard
a card as a cost, because costs aren't effects."

So the seam takes ``as_cost`` and the Library's ``applies`` predicate refuses
an event carrying it. A cost site that forgets it puts a cycled card back on
top of its library — where the cycling ability draws it again, and an
Onslaught card's "when you cycle this card" trigger makes that a loop (Renewed
Faith: {1}{W}, gain 2 life, keep the card). Found by ONS W1G3, when no site
passed it.

The cost-paying modules are the four the stack's cost steps live in (CR
601.2h, 602.2b): the activation charges, the cast's additional and
alternative costs, and a card's own hand activation (cycling). A discard
anywhere else in them is a cost by construction, so every one is checked.
"""

from __future__ import annotations

import ast

from tests.source_index import REPO_ROOT, source_tree

_COST_MODULES = (
    "engine/mixins/stack/activation_charges.py",
    "engine/mixins/stack/cast_additional_costs.py",
    "engine/mixins/stack/cast_alternative_costs.py",
    "engine/mixins/stack/card_activation.py",
)


def _discard_calls(tree: ast.AST):
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_discard_card"
        ):
            yield node


def _passes_as_cost(call: ast.Call) -> bool:
    return any(
        keyword.arg == "as_cost"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is True
        for keyword in call.keywords
    )


def test_every_discard_a_cost_step_makes_says_it_is_a_cost():
    examined = 0
    missing = []
    for relative in _COST_MODULES:
        tree = source_tree(REPO_ROOT / relative)
        calls = list(_discard_calls(tree))
        assert calls, f"{relative} pays no discard cost any more — update this guard"
        for call in calls:
            examined += 1
            if not _passes_as_cost(call):
                missing.append(f"{relative}:{call.lineno}")
    # A floor on what was examined: eight cost discards across the four
    # modules when this guard was written.
    assert examined >= 8, examined
    assert not missing, (
        "a discard paid as a cost must pass as_cost=True to Game._discard_card, "
        f"or Library of Leng redirects it: {missing}"
    )
