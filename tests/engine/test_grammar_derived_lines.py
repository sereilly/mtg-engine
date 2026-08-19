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


def test_combat_restrictions_match_the_derivation_table_exactly():
    """The grammar's combat restrictions must equal engine/combat_restrictions.py.

    This is what let the category be switched on: not "the grammar produced
    something", but "it produced the same instruction kind and the same payload
    the table the consumer dispatches on produces", on every such line in the
    pool. The land type and the power threshold are payload data on both sides,
    so a card naming Mountain or a threshold of 4 is compared the same way.

    (Inherited from `test_grammar_differential.py`. Its subject was never the
    legacy rule registry: `combat_restriction_for` is a live derivation table,
    read by `phases/declare_attackers_step.py` and by the compiler's support
    gate, so the comparison outlives the deletion.)
    """
    from engine.combat_restrictions import combat_restriction_for
    from engine.oracle import normalize_creature_line

    # Shapes the grammar deliberately does not claim yet. They must keep
    # *failing the parser*, not lowering to an empty instruction list — a line
    # that parses to nothing is the silent drop this whole invariant exists to
    # prevent.
    unclaimed_kinds = {
        "must_attack_each_combat", "cant_be_blocked_by_walls", "cant_attack", "cant_block",
        # "This creature can block only creatures with flying." (Shacklegeist,
        # M21's first printing of the shape.) The derivation table implements it
        # and the declare-blockers step dispatches on it; the grammar has no
        # production, so the line fails the parser — which is what the assertion
        # below checks, and is the safe direction.
        "can_block_only_with_keyword",
        # "This creature must be blocked if able." (Canopy Stalker.) Same
        # position: the table implements it, the grammar does not read it.
        "must_be_blocked",
    }

    compared = 0
    for card in load_catalog():
        for raw_line in card.oracle_text.split("\n"):
            line = raw_line.strip()
            if not line:
                continue
            derived = combat_restriction_for(normalize_creature_line(line))
            if derived is None:
                continue
            result = compile_line(line, card_name=card.name)
            if derived.kind in unclaimed_kinds:
                assert not result.parsed, (
                    f"{card.name}: {line!r} is not claimed by the grammar yet, so "
                    "it must fail the parser rather than parse to nothing"
                )
                continue
            got = [(i.kind, i.payload) for i in result.instructions]
            assert got == [(derived.kind, derived.payload)], f"{card.name}: {line!r}"
            compared += 1

    assert compared, "no combat-restriction lines were compared"


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
