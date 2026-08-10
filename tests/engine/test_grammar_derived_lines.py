"""Guard: ``engine/grammar/derived.py`` stays a delegation, not a second parser.

A derivation table matching on raw text is exactly the shape this migration is
deleting. Three properties are what make these entries something other than
``engine/parsing/`` relocated into the grammar, and none of them holds by
inspection:

* **a table may only reach text no production can read.** ``parse_line`` runs
  every production first and consults the tables only after a ``GrammarError``.
  Reorder that and ``engine/lord_buffs.py`` starts claiming every anthem in the
  pool, silently taking those lines off the production that reads them.
* **the lowered instruction is the table's own output**, not a rebuilt copy of
  it — so a payload the grammar emits and a payload the consumer dispatches on
  cannot describe different effects.
* **every entry is reachable.** A table nothing in the pool routes to is either
  dead weight or, worse, a claim that has quietly stopped matching the line it
  was written for.
"""

from __future__ import annotations

import pytest

from engine import oracle
from engine.card_loader import load_catalog
from engine.grammar import ast as grammar_ast, compile_line
from engine.grammar.derived import TABLES, derived_instruction_for_line
from engine.grammar.errors import GrammarError
from engine.grammar.parser import _parse_line


@pytest.fixture(scope="module")
def pool_lines():
    """Every printed line of every card, with the card that printed it."""
    lines = []
    for card in load_catalog():
        text = oracle.expand_modal_activated_lines(card.oracle_text or "")
        for raw in text.splitlines():
            line = raw.strip()
            if line:
                lines.append((card.name, line))
    return lines


def _derived_lines(pool_lines):
    for card_name, line in pool_lines:
        compiled = compile_line(line, card_name=card_name)
        if isinstance(compiled.node, grammar_ast.DerivedLine):
            yield card_name, line, compiled


def test_a_derived_claim_only_ever_reaches_a_line_no_production_reads(pool_lines):
    """The ordering property, asserted rather than assumed.

    Every line a table claims must be one the ordinary parser refuses in full.
    If a production later learns to read one of these, this fails and the entry
    has to move — which is the outcome that keeps the grammar authoritative.
    """
    shadowed = []
    for card_name, line, _compiled in _derived_lines(pool_lines):
        try:
            node = _parse_line(line, card_name=card_name)
        except GrammarError:
            continue
        shadowed.append((card_name, line, type(node).__name__))

    assert not shadowed, (
        "a derivation table claimed a line the grammar can parse, shadowing the "
        f"production that reads it: {shadowed}"
    )


def test_a_derived_line_lowers_to_exactly_what_its_table_derives(pool_lines):
    """The claim and the payload are one function call, in both directions."""
    for card_name, line, compiled in _derived_lines(pool_lines):
        derived = derived_instruction_for_line(line)
        assert derived is not None, (card_name, line)
        table, instruction = derived
        assert compiled.node.table == table
        assert compiled.instructions == (instruction,), (card_name, line)


def test_every_derivation_table_is_reachable_from_the_pool(pool_lines):
    """A table nothing routes to is a claim that has stopped matching."""
    reached = {compiled.node.table for _n, _l, compiled in _derived_lines(pool_lines)}
    unreachable = [table.name for table in TABLES if table.name not in reached]

    assert not unreachable, (
        "derivation tables no pool line reaches — either the entry is dead or "
        f"its matcher no longer claims the line it was written for: {unreachable}"
    )


def test_a_derived_line_is_a_whole_line_or_nothing():
    """Every matcher is anchored at both ends, so a rider refuses the sentence.

    The near miss that matters is the one between the two land tables: an
    animation clause is a type change *plus* a body the type-change consumer
    would never apply, and admitting it would drop the animation silently.
    """
    animation = "All Swamps are 1/1 black creatures that are still lands."
    assert derived_instruction_for_line(animation)[0] == "land_animation"

    assert derived_instruction_for_line("All Mountains are Plains.")[0] == "land_types"
    assert derived_instruction_for_line("All Mountains are Plains and you gain 2 life") is None
    assert derived_instruction_for_line("All Wombats are Plains") is None
