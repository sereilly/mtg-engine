"""Rampage (CR 702.23), the keyword and the triggered ability it *is*.

CR 702.23a does not describe rampage, it **defines** it: "Rampage N" means
"Whenever this creature becomes blocked, it gets +N/+N until end of turn for
each creature blocking it beyond the first." So this module is a rewrite in
the shape ``engine/equipment.py`` established for equip — the printed keyword
line becomes the ability the rules say it already is, and from there the
existing "becomes blocked" dispatcher in
``engine/phases/declare_blockers_step.py`` fires it, the stack carries it, and
one handler resolves it. Nothing downstream of the compiler knows the word.

Writing it as a real trigger rather than as a pump applied at declaration is
what buys CR 702.23b: the bonus is calculated **when the ability resolves**,
so blockers added or removed after the declaration do not change it. A pump
applied inside the declare-blockers step would read the count at the wrong
moment and could never be responded to.

CR 702.23c — several instances of rampage each trigger separately — is why
:func:`rampage_amounts` returns every instance rather than their sum. The
arithmetic happens to agree, but the log lines and the stack do not: two
abilities go on the stack, and each may be responded to on its own.
"""

from __future__ import annotations

import re

from .oracle_types import (OracleInstruction, ParsedTriggeredAbility,
                           TriggerCondition)

#: The instruction one instance of rampage lowers to. Its payload is the N.
RAMPAGE_KIND = "rampage_pump"

#: The bucket the support report puts it in. Carried here rather than added to
#: ``effect_labels.TRIGGERED_LABELS`` for the reason a ``card_hooks.CardLine``
#: carries its own: those tables describe the abilities the **grammar** reads,
#: and this one is derived from a keyword line the grammar never sees. An entry
#: there would read as dead to the guard that holds the tables to the pool.
#: ``triggered_pump`` is the existing word for a triggered P/T change — the
#: report asks what the ability is for, and the answer is not "rampage".
RAMPAGE_LABEL = "triggered_pump"

#: "rampage 2" as it survives ``normalize_creature_line`` — lowercased, with
#: the reminder text already stripped. The number is the whole parameter.
_RAMPAGE_PART = re.compile(r"^rampage (\d+)$")


def rampage_amount(part: str) -> int | None:
    """The N of one normalized keyword-line part, or None if it isn't rampage.

    This is also the gate's admission test: a "rampage" with no number, or one
    the engine cannot read, is not a line this file implements, and the keyword
    classifier refuses the card rather than shipping it with the ability
    dropped.
    """
    match = _RAMPAGE_PART.match(part.strip())
    return int(match.group(1)) if match else None


def rampage_amounts(keyword_line: str) -> tuple[int, ...]:
    """Every instance of rampage on one comma-joined keyword line (CR 702.23c).

    "Trample, rampage 1" is one instance; a line naming rampage twice is two,
    and each gets its own ability.
    """
    amounts = []
    for part in keyword_line.split(","):
        amount = rampage_amount(part)
        if amount is not None:
            amounts.append(amount)
    return tuple(amounts)


def rampage_triggers(keyword_line: str) -> tuple[ParsedTriggeredAbility, ...]:
    """The triggered abilities CR 702.23a says *are* the rampage on this line.

    The condition kind is the same ``creature_becomes_blocked`` every printed
    "whenever this creature becomes blocked" produces, with no blocker filter —
    which is what makes it fire once per creature rather than once per blocker
    (CR 509.3c/509.3d, and the dispatcher reads exactly that distinction).
    """
    return tuple(
        ParsedTriggeredAbility(
            source_line=f"rampage {amount}",
            condition=TriggerCondition(
                kind="creature_becomes_blocked",
                trigger="whenever",
                raw_text="whenever this creature becomes blocked",
            ),
            instruction=OracleInstruction(RAMPAGE_KIND, f"rampage {amount}", {"amount": amount}),
            supported=True,
            effect_kind=RAMPAGE_LABEL,
        )
        for amount in rampage_amounts(keyword_line)
    )


def rampage_bonus(amount: int, blocker_count: int) -> int:
    """+N/+N "for each creature blocking it beyond the first" (CR 702.23a).

    Zero when the creature is blocked by one creature, which is the ordinary
    case — the ability still triggers and still resolves, it just grants
    nothing. An unblocked creature never triggers at all.
    """
    return amount * max(0, blocker_count - 1)


__all__ = [
    "RAMPAGE_KIND",
    "RAMPAGE_LABEL",
    "rampage_amount",
    "rampage_amounts",
    "rampage_bonus",
    "rampage_triggers",
]
