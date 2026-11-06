"""The reporting label an ability's compiled instruction carries.

``effect_kind`` is a *label*, never dispatch. It reaches ``SimulationResult.effect_kind``
(the string the duel scripts and the per-card tests report a cast by),
``StackItem.ability_effect_kind`` (the stack object's own copy of the same
report) and ``scripts/oracle_diff.py``'s stored programs. Nothing else reads
it: ``scripts/support_report.py`` buckets by card type and refusal, never by
label, and whether a delayed trigger is one is the enqueue's ``delayed`` flag.

**Its prefix says nothing about the ability's kind**, and nothing may read it as
if it did: ``add_counter_to_target`` is ``triggered_counter`` in the activated
table, and hundreds of triggers are ``upkeep_effect`` or ``spell_pattern``.
Whether a stack object is an activated or a triggered ability is
``StackItem.ability_kind`` — how it was put on the stack. Until the kg round
three readers took the ``triggered_`` / ``activated_`` prefix for that answer
(the client's ``is_triggered``, ``stack_targets``' CR 115.7 lists and "counter
target activated ability"), which is why several notes in the tables justify a
row by the prefix it gave ``is_triggered``: they record why the row was added,
not what reads it now.

Its vocabulary was ``engine/parsing/``'s. Each string was named after the rule
that produced it (``activated_deny_regeneration`` because there was a rule
called that), and the compiler preferred the legacy label whenever a legacy rule
matched the same line the grammar had already read. Deleting the registry
without carrying the vocabulary would therefore have silently re-bucketed 57
cards — an activated regeneration reported ``activated_regeneration`` where it
had always said ``activated_regenerate``, and every trigger the grammar reads
losing the ``triggered_`` prefix the client's flag then depended on.

So the vocabulary moved into these tables, which is the move
``card_hooks.CardLine.effect_kind`` already made for the lines that became
name-keyed hooks: *"carried here so deleting the rule that produced it does not
silently re-bucket the card."* A hook supplies its own label and never consults
these tables; what they cover is the grammar's output.

**Where a row lives.** The rows are two families, a module each, and this
module is the reader both import into: ``engine/activated_labels.py`` holds
``ACTIVATED_LABELS`` (the activated position) and ``engine/triggered_labels.py``
holds ``TRIGGERED_LABELS`` with its by-condition rows,
``TRIGGERED_LABELS_BY_CONDITION`` (a wrapper whose label the trigger's
moment names). A new row goes in its position's module; this one changes only
when the way a label is looked up does.

**Both tables are held to the pool**, by ``tests/engine/test_effect_labels.py``:
every entry must still be reached by a card that compiles through the grammar,
and every such ability must take its label from an entry rather than the
fallback. A frozen list of strings nothing checks would rot into a description
of a pool that has moved on; this one fails when it stops describing the pool,
so it can be pruned and extended for cause rather than by guesswork.

The fallbacks in the two readers below are what a *new* card gets: an activated
ability is labelled by the grammar category its instruction lowered to, and a
trigger keeps the ``spell_pattern`` marker the compiler has always used when
nothing claimed the clause. A new entry is only needed when a card must keep a
label the category cannot produce.
"""

from __future__ import annotations

from .activated_labels import ACTIVATED_LABELS
from .triggered_labels import TRIGGERED_LABELS, TRIGGERED_LABELS_BY_CONDITION


def activated_label(instruction_kind: str, category: str) -> str:
    """The label for *instruction_kind* read as an activated ability."""
    return ACTIVATED_LABELS.get(instruction_kind, f"activated_{category}")


def triggered_label(instruction_kind: str, condition_kind: str | None) -> str:
    """The label for *instruction_kind* read as a trigger's effect."""
    if condition_kind is not None:
        by_condition = TRIGGERED_LABELS_BY_CONDITION.get((condition_kind, instruction_kind))
        if by_condition is not None:
            return by_condition
    return TRIGGERED_LABELS.get(instruction_kind, "spell_pattern")


__all__ = [
    "activated_label",
    "triggered_label",
]
