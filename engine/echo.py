"""Echo (CR 702.30), the keyword and the triggered ability it *is*.

CR 702.30a does not describe echo, it **defines** it: "Echo [cost]" means "At
the beginning of your upkeep, if this permanent came under your control since
the beginning of your last upkeep, sacrifice it unless you pay [cost]." So this
module is the rewrite ``engine/equipment.py`` established for equip — the
printed keyword line becomes the sentence the rules say it already is, applied
by ``oracle.expand_ability_lines`` before any line is classified, and from
there nothing downstream knows the word: the grammar reads the trigger, the
intervening-if and the pay-or-sacrifice offer, ``lowering/upkeep.py`` produces
the ``upkeep_pay_or_sacrifice_self`` kind the pool has printed since Alpha, and
``phases/upkeep_effects.py``'s registered handler charges it.

**Why a rewrite into a sentence rather than a rewrite into a trigger.**
``engine/cumulative_upkeep.py`` and ``engine/flanking.py`` skip the grammar and
build a :class:`ParsedTriggeredAbility` outright, because the sentences CR
702.24a and CR 702.25a define have no production behind them — an escalating
cost keyed off a counter, and a clause ("for each creature blocking it beyond
the first") no card outside a reminder prints. Echo's sentence is not in that
position. Every word of it but one already parses: "At the beginning of your
upkeep, sacrifice it unless you pay {1}{G}" is Veiled Apparition's granted
ability and lowers today. What was missing was CR 702.30a's intervening-if, and
that is a *condition* — a thing the grammar has forty-nine of and a table to put
the fiftieth in. Building the trigger by hand here would have bought the same
fourteen cards while leaving the condition unreadable, so the next card to print
it in longhand would need the work done again.

**CR 702.30b needs no code.** Urza-block cards were printed with a bare "Echo"
and have Oracle errata giving each one a cost equal to its mana cost; the
ingested text already carries the errata'd cost, so the cost is *read* here and
never re-derived from ``CardDefinition.mana_cost``. A line that still prints the
bare word is refused by name (:func:`is_echo_line` is wider than
:func:`echo_cost`, exactly as equip's shape test is wider than its reader), so
such a card is reported unsupported rather than shipping a permanent whose echo
is never charged.

**The state behind the condition is not this module's.** "Came under your
control since the beginning of your last upkeep" is a general question about a
window that spans the opponents' turns, so it lives where the pool's other
question about that window lives — ``engine/turn_state.py``, beside Wiitigo's
"has blocked or been blocked since your last upkeep". It is *not* recorded the
same way, and that module says why: the record here is which upkeep of yours
this permanent first saw, written by the upkeep step, rather than a
moment-of-arrival stamp compared against a seat-turn ordinal.
"""

from __future__ import annotations

import re

#: The rules text CR 702.30a gives the keyword, quoted word for word. "This
#: permanent" rather than the reminder text's bare "this": both parse, and the
#: rule's own wording is the one to carry, because the printed reminder also
#: says "its echo cost" where the sentence needs the cost itself.
ECHO_RULES_TEXT = (
    "At the beginning of your upkeep, if this permanent came under your "
    "control since the beginning of your last upkeep, sacrifice it unless "
    "you pay {cost}."
)

#: "echo {1}{g}" as the printed line survives reminder-text removal. The cost is
#: taken from the printed line so a coloured pip keeps its letter, exactly as
#: ``equipment._EQUIP_LINE`` does.
_ECHO_LINE = re.compile(r"^echo\s+(?P<cost>(?:\{[^{}]+\})+)$", re.IGNORECASE)

#: Any line that *is* an echo keyword line, readable or not — a pre-errata bare
#: "Echo" included. The wider shape is what a caller asking "is this an echo
#: line?" wants: a variant the expansion refuses must stay refused *as an echo
#: line* rather than fall through to a classifier that has never heard of the
#: word and reports it as some other keyword.
_ECHO_SHAPE = re.compile(r"^echo\b", re.IGNORECASE)

_REMINDER = re.compile(r"\([^)]*\)")


def echo_cost(line: str) -> str | None:
    """The printed echo cost of one line, or None when *line* is not an echo
    line this module can read.

    The admission test as well as the reader, exactly as
    ``cumulative_upkeep.cumulative_upkeep_cost`` is: the function that
    *implements* the keyword is the one that admits it, so a spelling it cannot
    express keeps the line refused rather than shipping a creature that never
    pays.
    """
    stripped = " ".join(_REMINDER.sub("", line or "").split()).strip().rstrip(".")
    match = _ECHO_LINE.match(stripped)
    if match is None:
        return None
    return match.group("cost")


def is_echo_line(line: str) -> bool:
    """Whether *line* is a printed echo keyword line, whether or not
    :func:`expand_echo_line` can read it."""
    stripped = _REMINDER.sub("", line or "").strip()
    return _ECHO_SHAPE.match(stripped) is not None


def expand_echo_line(line: str) -> str | None:
    """The CR 702.30a rules text for one printed echo line, or None."""
    cost = echo_cost(line)
    if cost is None:
        return None
    return ECHO_RULES_TEXT.format(cost=cost)


def expand_echo_lines(oracle_text: str) -> str:
    """*oracle_text* with every echo keyword line rewritten to its rules text.

    Text without an echo line is returned unchanged, so applying this to every
    card costs nothing but a scan. Applied by the compiler before any line is
    classified — beside ``expand_equip_lines`` and for the same reason: what the
    compiler reads and what every other reader of a card's lines (targeting,
    parse coverage, hook reliance) reads must be one text.
    """
    # The case-insensitive substring both spellings share, which is
    # ``expand_equip_lines``'s ``"quip"`` test one module over. It is a fast
    # path and nothing else: a card whose text merely says "choose" pays one
    # split and every line then refuses on its own.
    if not oracle_text or "cho" not in oracle_text:
        return oracle_text
    lines = oracle_text.split("\n")
    rewritten = [expand_echo_line(line) or line for line in lines]
    return "\n".join(rewritten)


__all__ = [
    "ECHO_RULES_TEXT",
    "echo_cost",
    "expand_echo_line",
    "expand_echo_lines",
    "is_echo_line",
]
