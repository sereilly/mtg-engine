"""Text-keyed extra triggers (CR 603.2d).

"If a triggered ability of another Shrine you control triggers while you control
six or more Shrines, that ability triggers an additional time." (Sanctum of All.)

CR 603.2d: "rather than simply determining that such an ability *has* triggered,
determine how many times it should trigger, then that ability triggers that many
times." So this is not a replacement effect and not a copy — the ability
genuinely triggers more than once, each instance choosing its own targets, and
the seam is the moment an ability is put onto the stack.

Everything below is derived from the printed sentence, so a differently-named
card with the same template needs no code at all. The **support gate reads this
same table** (``oracle._derived_static_claims``), so a wording it does not
understand cannot be admitted as supported and then silently unenforced — the
lesson `land_play_allowance.py` records at length.

Two restrictions the rule states and this file enforces, because both are ways a
naive reading gets more triggers than the card grants:

* "a triggered ability **of** an object refers only to triggered abilities that
  object has, not to any delayed or reflexive triggered abilities" — so a
  delayed trigger with no source permanent is never doubled;
* "doesn't invoke itself repeatedly" — the extra instance is not itself put
  through the count again, which falls out of counting once at the fire site
  rather than recursing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from .oracle_types import _NUMBER_WORDS

_COUNT_WORD = "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True))

_PATTERN = re.compile(
    r"^if a triggered ability of another (?P<subtype>[a-z][a-z' -]*?) you control "
    r"triggers while you control (?P<threshold>\d+|" + _COUNT_WORD + r") or more "
    r"(?P<plural>[a-z][a-z' -]*?)s, that ability triggers an additional time\.?$"
)


@dataclass(frozen=True)
class ExtraTriggers:
    """One permanent's CR 603.2d contribution.

    subtype   -- the printed noun the doubled permanents share ("shrine")
    threshold -- how many of them the controller must have for it to apply
    extra     -- additional times the ability triggers ("an additional time" = 1)
    """

    subtype: str
    threshold: int
    extra: int = 1


def _count(word: str) -> int:
    return int(word) if word.isdigit() else int(_NUMBER_WORDS[word])


@lru_cache(maxsize=None)
def extra_triggers_for(oracle_text: str) -> ExtraTriggers | None:
    """The contribution *oracle_text* states, or None when it states none.

    Read line by line, because this sentence shares a card with the ability it
    is about (Sanctum of All prints an upkeep trigger above it).
    """
    for line in (oracle_text or "").splitlines():
        match = _PATTERN.match(line.strip().lower())
        if match is None:
            continue
        # The noun is printed twice — singular in the subject, plural in the
        # condition. They have to be the same noun: a sentence naming two would
        # be a different card, and reading only the first would apply a Shrine's
        # doubling on a count of something else.
        if match.group("plural") != match.group("subtype"):
            return None
        return ExtraTriggers(
            subtype=match.group("subtype"),
            threshold=_count(match.group("threshold")),
        )
    return None


def extra_trigger_line(line: str) -> bool:
    """Whether one printed *line* is a sentence this module implements in full.

    The claim the support gate and the grammar's parse claim both read, so what
    is implemented and what is admitted cannot drift.
    """
    return _PATTERN.match((line or "").strip().lower()) is not None


def additional_triggers(game, source_permanent, controller_index: int) -> int:
    """How many **extra** times an ability of *source_permanent* triggers.

    Zero for a delayed or reflexive trigger, which has no source permanent —
    CR 603.2d says such an ability is not one the object "has".
    """
    if source_permanent is None:
        return 0
    extra = 0
    for seat, permanent in game.permanents_with_controller():
        if seat != controller_index or permanent is source_permanent:
            continue
        contribution = extra_triggers_for(permanent.effective_card.oracle_text)
        if contribution is None:
            continue
        # "another <Shrine> you control" — the triggering permanent has to be
        # one, asked through the layer bridge rather than off the printed line,
        # because a permanent's subtypes are a computed characteristic (CR 613
        # layer 4) and a Shrine that became one is still one.
        if not source_permanent.has_type(contribution.subtype):
            continue
        held = sum(
            1 for held_seat, other in game.permanents_with_controller()
            if held_seat == controller_index and other.has_type(contribution.subtype)
        )
        if held >= contribution.threshold:
            extra += contribution.extra
    return extra


__all__ = [
    "ExtraTriggers",
    "additional_triggers",
    "extra_trigger_line",
    "extra_triggers_for",
]
