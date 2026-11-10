"""Every printed "whenever" line the trigger table's reverse retry reaches.

``trigger_conditions._parse_trigger_condition`` asks the "when" table about a
"whenever" line the "whenever" table misses (CR 603.1: one kind of ability),
and only about the source's own events. On 59f133e63 no shipped card is read
that way — the retry moved no card's program — so the census here is the one
a set printing "Whenever this creature dies" meets first: whatever line the
retry reads must be the source's own event, ended at its comma, and the card
must compile. The behaviour is driven in
``tests/rules/test_kg5_grammar_whenever_dies.py``.
"""

from __future__ import annotations

from engine.card_loader import load_catalog
from engine.faces import compilation_units
from engine.line_normalization import normalize_creature_line
from engine.trigger_conditions import trigger_condition_of_line


def test_every_whenever_line_the_reverse_retry_reads_is_the_sources_own_event():
    examined = 0
    retried = []
    for unit in compilation_units(load_catalog()):
        for line in (unit.oracle_text or "").split("\n"):
            if not normalize_creature_line(line).startswith("whenever "):
                continue
            examined += 1
            condition, _ = trigger_condition_of_line(line, unit.name)
            # The forward retry reports the rewritten "whenever …" clause, so
            # a "whenever" line whose clause reads "when …" is the reverse's.
            if condition is not None and condition.raw_text.startswith("when "):
                retried.append((unit.name, condition.raw_text))
    assert examined >= 600, f"only {examined} printed whenever lines examined"
    wrong = [
        (name, clause) for name, clause in retried
        if not clause.startswith("when this ") or "," in clause
    ]
    assert wrong == [], wrong
