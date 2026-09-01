"""Lowering counter **removal** (CR 121.3).

Split out of ``lowering/counters.py`` when Fallen Empires took that module
through the 1,000-line cap — and by three groups at once, none of which
crossed it alone: a bound subject for the placement (Soul Exchange), a
chosen one (the two Chants), and "remove **all** counters" (Homarid, Tidal
Influence). The cap fired at integration, which is the guard working: the
family boundary was already there and the collision is what surfaced it.

Putting and removing are different actions with different payload
vocabularies — a placement asks *which object and how many*, a removal asks
*which kind and whether the number is known yet* — so this is the boundary
that was there to find rather than a cut at a convenient line number.

**No parse-side mirror, deliberately.** ``effects/counters.py`` reads both
halves in 321 lines and has no reason to split; the lowering side carries
families the parse side does not for exactly this reason, and
``tests/engine/test_grammar_layering.py`` documents every one with its
reason.
"""

from __future__ import annotations

from ..phrases import is_pt_counter
from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ._common import _amount_payload, _is_source


def _lower_remove_counter(
    node: ast.RemoveCounter, event: str | None = None
) -> tuple[OracleInstruction, ...]:
    """``Remove a <kind> counter from this <permanent>`` (Armageddon Clock).

    The counter's name is payload — it is the accumulating side's payload too
    (``upkeep_put_counter_on_self``), so the pair is one template rather than a
    card. What is *not* payload is the subject or the number:
    ``remove_counter_from_self`` reads the ability's own source and decrements by
    one, so anything else refuses rather than compiling onto a handler that
    would quietly do that instead.
    """
    # "Remove two loyalty counters from each planeswalker." (Pestilent Haze's
    # second mode.) A sweep, not a choice: every planeswalker on every
    # battlefield loses that many, and CR 704.5i collects the ones that hit
    # zero. Only the loyalty/planeswalker pairing has a handler — loyalty is
    # the one counter kind whose storage the handler knows how to reach.
    if (
        isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier == "each"
        and node.counter == "loyalty"
    ):
        if node.subject.filter.card_types != ("planeswalker",):
            raise LoweringError(
                "the loyalty sweep removes from planeswalkers alone", node=node
            )
        amount = _amount_payload(node.count)
        if not isinstance(amount, int) or amount <= 0:
            raise LoweringError("the loyalty sweep takes a fixed count", node=node)
        return (
            OracleInstruction(
                "remove_loyalty_from_each_planeswalker", "", {"amount": amount}
            ),
        )
    # "…remove a sleep counter from **that creature**." (Venarian Gold.) "That
    # creature" restates an object something earlier bound, and the only
    # trigger head that binds one is `upkeep_enchanted_controller` — its
    # sentence is *about* the enchanted creature, which is what the handler
    # reads off the source's own attachment. Under any other event the words
    # name a creature nobody recorded, so the line keeps refusing; and the
    # dispatch registry keys on the ability's whole instruction, so a nested
    # occurrence (event is None here) refuses the same way.
    if (
        isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier == "that"
        and event == "upkeep_enchanted_controller"
    ):
        if node.subject.filter != ast.ObjectFilter(card_types=("creature",)):
            raise LoweringError(
                "the attached counter removal reads the enchanted creature alone",
                node=node,
            )
        if is_pt_counter(node.counter):
            raise LoweringError(
                "a P/T counter removal needs the counter seam, which this "
                "handler does not reach",
                node=node,
            )
        if _amount_payload(node.count) != 1:
            raise LoweringError(
                "no handler removes more than one counter at a time", node=node
            )
        return (
            OracleInstruction(
                "remove_counter_from_attached", "", {"counter": node.counter}
            ),
        )
    if not _is_source(node.subject):
        raise LoweringError(
            "the only counter-removal handler reads the ability's own source", node=node
        )
    if isinstance(node.count, ast.AllOf):
        # "…remove **all** tide counters from it." (Homarid, Tidal Influence.)
        # Its own kind rather than a count on the one below: that handler
        # decrements by a number the instruction already carries, and "all" is
        # a number nobody knows until the permanent is looked at — compiling it
        # onto a fixed removal would take exactly one counter off a permanent
        # the card says to empty.
        return (
            OracleInstruction(
                "remove_all_counters_from_self", "", {"counter": node.counter}
            ),
        )
    if isinstance(node.count, ast.AnyNumber):
        # "Remove **any number of** +1/+1 counters from this creature."
        # (Tetravus.) Its own kind rather than a count on the one above: that
        # handler decrements by a number it already knows, and this one has to
        # ask its controller for the number first. What it removes is recorded,
        # because the sentence after it ("create **that many** … tokens") reads
        # it back.
        return (
            OracleInstruction(
                "remove_any_number_of_counters_from_self", "", {"counter": node.counter}
            ),
        )
    if _amount_payload(node.count) != 1:
        raise LoweringError("no handler removes more than one counter at a time", node=node)
    return (
        OracleInstruction("remove_counter_from_self", "", {"counter": node.counter}),
    )
