"""Conditional static power/toughness bonuses (CR 613 layer 7c).

"This creature gets +N/+N as long as <condition>" — Sedge Troll, Kird Ape,
Giant Tortoise. The bonus size and the condition's subject are both data, and
the clause is printed in **two word orders**:

    This creature gets +1/+1 as long as you control a Swamp.
    As long as you control a Swamp, this creature gets +1/+1.

Only the first was ever dispatched. The second was admitted by a whitelist
literal in the compiler's support gate that spelled out *Swamp*, so a card
printed that way reported `supported` and then never got the bonus — while the
identical sentence naming any other land type was reported unsupported. Gate
and dispatch derive from this one table now, so both orders work for every
type and an unrecognized wording fails loud.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Desert is included alongside the five basics: Arabian Nights prints
# "as long as you control a Desert", and the check this feeds
# (_refresh_dynamic_creatures) matches by type, not by basic-ness.
BASIC_LAND_WORDS = ("plains", "island", "swamp", "mountain", "forest", "desert")
_LAND_ALTERNATION = "|".join(BASIC_LAND_WORDS)

_BONUS = r"gets \+(?P<power>\d+)/\+(?P<toughness>\d+)"


@dataclass(frozen=True)
class StaticBonus:
    """An instruction kind the P/T refresh dispatches on, plus its data."""

    kind: str
    payload: dict[str, object] = field(default_factory=dict)


# (pattern, kind). Each condition appears twice — trailing and leading — because
# both are printed. Writing them as one table is what keeps the two orders from
# drifting into "one is implemented, the other is whitelisted".
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(rf"{_BONUS} as long as you control an? (?P<land_type>{_LAND_ALTERNATION})\b"),
        "conditional_land_bonus",
    ),
    (
        re.compile(
            rf"^as long as you control an? (?P<land_type>{_LAND_ALTERNATION}), "
            rf".*?{_BONUS}$"
        ),
        "conditional_land_bonus",
    ),
    (
        re.compile(rf"{_BONUS} as long as (?:it's|this creature is) untapped\b"),
        "conditional_untapped_bonus",
    ),
    (
        re.compile(rf"^as long as (?:it's|this creature is) untapped, .*?{_BONUS}$"),
        "conditional_untapped_bonus",
    ),
)


def static_bonus_for(normalized_line: str) -> StaticBonus | None:
    """The conditional P/T bonus *normalized_line* grants, or None.

    Takes an already-normalized line (``oracle.normalize_creature_line``).
    """
    for pattern, kind in _PATTERNS:
        match = pattern.search(normalized_line)
        if match is None:
            continue
        groups = match.groupdict()
        payload: dict[str, object] = {
            "power": int(groups["power"]),
            "toughness": int(groups["toughness"]),
        }
        if groups.get("land_type"):
            payload["land_type"] = groups["land_type"]
        return StaticBonus(kind, payload)
    return None
