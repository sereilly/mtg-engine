"""Text-keyed draw-step bonus draws (CR 504).

"At the beginning of each player's draw step, [if this artifact is untapped,]
that player draws an additional card." — Howling Mine's wording, and the
template a long line of cards reprints. The bonus is derived from oracle text
here rather than registered per card name, so a card printed with the template
needs no registration.

Only the symmetric bonus-draw template lives here. Island Sanctuary's
"instead you may skip that draw" remains a name-keyed hook: what it grants is
a specific protection quality ("except by creatures with flying and/or
islandwalk"), and until a second card grants a *different* quality there is
nothing to generalize over — deriving the trigger from text while the effect
stays hardcoded would only move the card-specificity out of sight.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from .oracle_types import _NUMBER_WORDS


@dataclass(frozen=True)
class DrawStepBonus:
    """Extra cards drawn in EVERY player's draw step.

    count             -- how many additional cards each player draws
    requires_untapped -- the bonus applies only while the source is untapped
    """

    count: int
    requires_untapped: bool = False


# "draws an additional card" is the printed wording; the shared number-word map
# carries "a" but not "an", so extend it here rather than mutating a table the
# rest of the parser reads.
_COUNT_WORDS: dict[str, int] = {**_NUMBER_WORDS, "an": 1}
_COUNT_WORD = "|".join(sorted(_COUNT_WORDS, key=len, reverse=True))

_EXTRA_DRAW = re.compile(
    r"^at the beginning of each player's draw step, "
    r"(?P<untapped>if this [a-z ]*?is untapped, )?"
    rf"that player draws (?P<count>{_COUNT_WORD}) additional cards?$"
)


@lru_cache(maxsize=None)
def draw_step_bonus_for(oracle_text: str) -> DrawStepBonus | None:
    """The per-draw-step bonus *oracle_text* grants every player, or None.

    Cached on the text itself, which is immutable on a ``CardDefinition``, so
    the draw step's per-permanent scan stays as cheap as the name-keyed lookup
    it replaced.
    """
    if "draw step" not in oracle_text.lower():
        return None
    for raw_line in oracle_text.lower().split("\n"):
        match = _EXTRA_DRAW.match(raw_line.strip().rstrip("."))
        if match is not None:
            return DrawStepBonus(
                count=_COUNT_WORDS[match.group("count")],
                requires_untapped=match.group("untapped") is not None,
            )
    return None
