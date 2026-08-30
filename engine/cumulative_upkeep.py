"""Cumulative upkeep (CR 702.24), the keyword and the triggered ability it *is*.

CR 702.24a does not describe cumulative upkeep, it **defines** it: "Cumulative
upkeep [cost]" means "At the beginning of your upkeep, if this permanent is on
the battlefield, put an age counter on this permanent. Then you may pay [cost]
for each age counter on it. If you don't, sacrifice it." So this module is the
rewrite ``engine/rampage.py`` and ``engine/equipment.py`` established — the
printed keyword line becomes the ability the rules say it already is, and from
there the upkeep step's ordinary ``upkeep_self`` dispatch fires it and one
registered handler resolves it. Nothing downstream of the compiler knows the
word.

**[cost] is a cost, not a mana cost.** What one is lives in
``engine/upkeep_costs.py`` — mana, life and a sacrifice, in whatever
combination the card printed, read by a phrase reader that consumes the whole
phrase or refuses it. That module says why the strictness matters; the short
version is that Infernal Darkness's "Pay {B} and 1 life" used to come back
``{B}``.

**The cost escalates, and the escalation is payload rather than a kind.**
``per_counter`` on the instruction says which counter multiplies the printed
cost, and :func:`scaled_cost` is the one place that arithmetic happens — asked
by the prompt that quotes the cost and by the handler that charges it, so what a
player is shown and what they are charged cannot disagree. **Every part
scales**: CR 702.24a's "for each age counter on it" is about the whole cost, so
Glacial Chasm's third upkeep asks for 6 life and Polar Kraken's asks for three
lands. Cyclone (Arabian Nights) prints CR 702.24a's sentence longhand with
"wind" in place of "age" and is on that same payload key for that reason: the
counter word is a parameter of one sentence, not two mechanics.

The two callers sit on **opposite sides of the counter being placed**, which is
why the count is a parameter rather than something the reader looks up:
:func:`upcoming_cost` answers the prompt's question ("what will this ask for?",
before the trigger resolves) by adding the counter this resolution will place,
while the handler already holds the new total. One reader for both would have to
guess which caller it had and would be wrong for the other — which is not
hypothetical: Cyclone charged double the moment the two shared one function.

CR 702.24b — several instances each trigger separately, and each counts *all*
the age counters — is why :func:`cumulative_upkeep_costs` returns every instance
rather than their sum, and why the counter is read at resolution rather than
carried on the ability.
"""

from __future__ import annotations

import re

from .named_counters import counters_on
from .oracle_types import (OracleInstruction, ParsedTriggeredAbility,
                           TriggerCondition)
from .upkeep_costs import UpkeepCost, cost_from_payload, upkeep_cost_from_phrase

#: The instruction one instance of cumulative upkeep lowers to.
CUMULATIVE_UPKEEP_KIND = "cumulative_upkeep"

#: The counter CR 702.24a names.
AGE_COUNTER = "age"

#: The bucket the support report puts it in. Carried here rather than added to
#: ``effect_labels.TRIGGERED_LABELS`` for the reason ``rampage.RAMPAGE_LABEL``
#: is: that table describes the abilities the **grammar** reads, and this one is
#: derived from a keyword line the grammar never sees, so an entry there would
#: read as dead to the guard that holds the table to the pool.
CUMULATIVE_UPKEEP_LABEL = "upkeep_effect"

#: "cumulative upkeep {1}{u}" as it survives ``normalize_creature_line`` —
#: lowercased, with the reminder text already stripped. CR 702.24's non-mana
#: form puts an em dash before the cost ("cumulative upkeep—pay 2 life"), which
#: this deliberately also captures: it must reach ``upkeep_cost_from_phrase``
#: and be read — or refused — *there* by name, not fail to match and be read as
#: some other keyword.
_CUMULATIVE_UPKEEP_PART = re.compile(r"^cumulative upkeep[\s—-]+(?P<cost>.+)$")


def cumulative_upkeep_cost(part: str) -> UpkeepCost | None:
    """The cost of one normalized keyword-line part, or None if the part isn't a
    cumulative upkeep this engine can charge.

    This is also the gate's admission test, exactly as ``rampage_amount`` is:
    the reader that *implements* the keyword is the one that admits it, so a
    cost it cannot express keeps the line refused rather than shipping a
    permanent whose upkeep is never charged.
    """
    match = _CUMULATIVE_UPKEEP_PART.match(part.strip())
    if match is None:
        return None
    return upkeep_cost_from_phrase(match.group("cost"))


def cumulative_upkeep_costs(keyword_line: str) -> tuple[UpkeepCost, ...]:
    """Every instance of cumulative upkeep on one comma-joined keyword line.

    CR 702.24b: each instance triggers separately, so each gets its own ability.
    """
    costs = []
    for part in keyword_line.split(","):
        cost = cumulative_upkeep_cost(part)
        if cost is not None:
            costs.append(cost)
    return tuple(costs)


def cumulative_upkeep_triggers(keyword_line: str) -> tuple[ParsedTriggeredAbility, ...]:
    """The triggered abilities CR 702.24a says *are* the cumulative upkeep on
    this line.

    The condition kind is the same ``upkeep_self`` every printed "at the
    beginning of your upkeep" produces, so the upkeep step needs no new seat
    rule and the prompt loop needs no new condition.
    """
    return tuple(
        ParsedTriggeredAbility(
            source_line="cumulative upkeep",
            condition=TriggerCondition(
                kind="upkeep_self",
                trigger="at",
                raw_text="at the beginning of your upkeep",
            ),
            instruction=OracleInstruction(
                CUMULATIVE_UPKEEP_KIND,
                "",
                cost.payload() | {"per_counter": AGE_COUNTER},
            ),
            supported=True,
            effect_kind=CUMULATIVE_UPKEEP_LABEL,
        )
        for cost in cumulative_upkeep_costs(keyword_line)
    )


def scaled_cost(instruction, counters: int) -> UpkeepCost:
    """*instruction*'s printed upkeep cost charged *counters* times over.

    The printed cost unchanged for an ordinary pay-or-else upkeep, which
    declares no ``per_counter`` and is therefore charged once however many
    counters happen to be on the permanent.

    *counters* is the caller's to supply because the two callers stand on either
    side of this resolution's counter being placed — see the module docstring.
    """
    printed = cost_from_payload(instruction.payload)
    if not instruction.payload.get("per_counter"):
        return printed
    return UpkeepCost(
        mana={
            symbol: amount * counters
            for symbol, amount in printed.mana.items()
            if amount
        },
        life=printed.life * counters,
        sacrifice=printed.sacrifice,
        sacrifices=printed.sacrifices * counters,
    )


def upcoming_cost(permanent, instruction) -> UpkeepCost:
    """What *instruction* will ask for when it next resolves — the prompt's
    question, asked *before* the counter for this upkeep is placed.

    So the count is what is on the permanent now plus the one CR 702.24a puts
    there as the ability resolves.
    """
    counter = instruction.payload.get("per_counter")
    placed = counters_on(permanent, str(counter)) + 1 if counter else 1
    return scaled_cost(instruction, placed)


__all__ = [
    "AGE_COUNTER",
    "CUMULATIVE_UPKEEP_KIND",
    "CUMULATIVE_UPKEEP_LABEL",
    "cumulative_upkeep_cost",
    "cumulative_upkeep_costs",
    "cumulative_upkeep_triggers",
    "scaled_cost",
    "upcoming_cost",
]
