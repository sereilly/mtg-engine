"""Guard: every category the grammar can lower to is switched on.

``GRAMMAR_CATEGORIES`` used to be the migration's valve. A category left out of
it meant "parse this in shadow and let ``engine/parsing/`` execute the line",
which is why landing a lowering and switching it on could be two separate,
reviewed steps.

With the legacy registry deleted there is nothing underneath. A category left
out no longer routes its lines anywhere — ``CompiledLine.usable`` goes False,
``engine/oracle.py`` falls through to the card hooks and then to nothing, and
the cards holding those lines are reported **unsupported**. The omission still
fails loudly (that is invariant 1 working), but it fails at the far end, in a
support report, rather than where the mistake was made.

So the set is pinned to what ``lower.py`` can emit, in both directions:

* a lowering added without its category costs cards their support;
* a category listed that nothing emits is a line of dead configuration that
  reads like a feature switch.

A category that genuinely should not execute has no business having a lowering:
the refusal belongs in ``lower_statement``, where it carries a reason
(``LoweringError``) that the coverage report can group and act on, instead of
being an unexplained absence from a frozenset.
"""

from __future__ import annotations

from engine.grammar import GRAMMAR_CATEGORIES
from engine.grammar.lower import INSTRUCTION_CATEGORIES


def _emittable() -> set[str]:
    return set(INSTRUCTION_CATEGORIES.values())


def test_every_emittable_category_is_switched_on():
    missing = sorted(_emittable() - GRAMMAR_CATEGORIES)
    assert not missing, (
        "engine/grammar/lower.py can lower instructions into these categories "
        "but GRAMMAR_CATEGORIES does not list them, so every card whose line "
        "lowers there is reported unsupported: "
        f"{missing}"
    )


def test_no_switched_on_category_is_unreachable():
    dead = sorted(GRAMMAR_CATEGORIES - _emittable())
    assert not dead, (
        "GRAMMAR_CATEGORIES lists categories no instruction lowers into — dead "
        f"configuration that reads like a feature switch: {dead}"
    )


def test_the_gate_is_not_empty():
    """Both assertions above pass on two empty sets. This is what stops the
    invariant being satisfied by deleting the tables."""
    assert len(GRAMMAR_CATEGORIES) > 15
