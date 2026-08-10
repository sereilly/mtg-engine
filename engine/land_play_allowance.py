"""Text-keyed extra land plays (CR 305.2, 505.5b).

"You may play any number of lands on each of your turns" (Fastbond), "You may
play an additional land on each of your turns", "You may play two additional
lands on each of your turns" — one printed template with one parameter, how many
extra land plays the permanent grants. The optional rider that comes with the
unlimited form ("Whenever you play a land, if it wasn't the first land you played
this turn, ~ deals N damage to you") is the second parameter.

This replaced ``Game._fastbond_count``, which counted battlefield permanents
**named "Fastbond"** and was consulted from four places (cast validation, the
land-drop damage, the AI's land policy and the web layer's playable-card list).
The gate and the dispatch were written with different literals, which is the
split this codebase keeps finding: ``scripts/parse_coverage.py`` claimed the
*sentence* "you may play any number of lands on each of your turns", so any card
printed with it counted as covered, while the code behind that claim only ever
fired for one name. Measured before this table was written: an invented card with
Fastbond's exact text compiled **supported**, granted no extra land play, and
dealt no damage.

Everything below is derived from the printed sentence, so a differently-named
card with the same template needs no code at all —
``tests/rules/test_land_play_allowance.py`` pins that with invented cards.

The **support gate reads this same table** (``oracle._derived_static_claims``),
so a wording it does not understand cannot be admitted as supported and then
silently unenforced.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from .oracle_types import _NUMBER_WORDS

_COUNT_WORD = "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True))

# Nouns a card uses to refer to itself in these lines. "~" is the placeholder
# some normalizations leave behind when the card's own name is stripped.
_SELF_NOUN = r"(?:this (?:artifact|creature|enchantment|land|permanent)|~)"


@dataclass(frozen=True)
class LandPlayAllowance:
    """Extra land plays one permanent grants its controller.

    extra                 -- additional land plays beyond the one CR 305.2
                             allows; ``None`` means any number
    damage_per_extra_land -- damage the source deals its controller when a land
                             is played that wasn't the first this turn (0 when
                             the card prints no such rider)
    """

    extra: int | None
    damage_per_extra_land: int = 0


_ANY_NUMBER = re.compile(r"^you may play any number of lands on each of your turns$")

_ADDITIONAL = re.compile(
    rf"^you may play (?:an|(?P<count>{_COUNT_WORD})) additional lands? "
    r"on each of your turns$"
)

# Fastbond's rider. Anchored at both ends for the usual reason: a line saying
# more than this carries something the land-drop path would not perform.
_DAMAGE_RIDER = re.compile(
    rf"^whenever you play a land, if it wasn't the first land you played this turn, "
    rf"{_SELF_NOUN} deals (?P<amount>\d+) damage to you$"
)


def land_play_line(normalized_line: str) -> str | None:
    """Name the part of the template *normalized_line* states, or None.

    ``"allowance"`` for the permission clause, ``"damage_rider"`` for the
    self-damage trigger that may accompany it. Its callers are
    ``scripts/parse_coverage.py`` (which needs to know each sentence is claimed
    by code that really runs) and the grammar's refusal registry — nothing
    dispatches on the returned name.
    """
    line = normalized_line.strip().lower().rstrip(".")
    if _ANY_NUMBER.match(line) or _ADDITIONAL.match(line):
        return "allowance"
    if _DAMAGE_RIDER.match(line):
        return "damage_rider"
    return None


@lru_cache(maxsize=None)
def land_play_allowance_for(oracle_text: str) -> LandPlayAllowance | None:
    """The extra land plays *oracle_text* grants, or None.

    Cached on the text itself, which is immutable on a ``CardDefinition``, so
    the per-permanent scan in the land-drop path stays as cheap as the name
    comparison it replaced. The permission clause is what makes an allowance:
    the damage rider alone is a trigger this module does not own, so a card
    printing only the rider returns None rather than silently granting a land.
    """
    lowered = oracle_text.lower()
    if "on each of your turns" not in lowered:
        return None
    extra: int | None = 0
    found = False
    damage = 0
    for raw_line in lowered.split("\n"):
        line = raw_line.strip().rstrip(".")
        if not line:
            continue
        if _ANY_NUMBER.match(line):
            extra, found = None, True
            continue
        additional = _ADDITIONAL.match(line)
        if additional is not None:
            count = additional.group("count")
            if extra is not None:
                extra += _NUMBER_WORDS[count] if count else 1
            found = True
            continue
        rider = _DAMAGE_RIDER.match(line)
        if rider is not None:
            damage += int(rider.group("amount"))
    if not found:
        return None
    return LandPlayAllowance(extra=extra, damage_per_extra_land=damage)


__all__ = [
    "LandPlayAllowance",
    "land_play_allowance_for",
    "land_play_line",
]
