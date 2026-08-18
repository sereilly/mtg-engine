"""Text-keyed combat restrictions on a creature (CR 506, 509).

"This creature can't attack unless defending player controls an Island",
"attacks each combat if able", "can't be blocked by Walls" — printed templates,
not card quirks. They are derived from oracle text here rather than listed, so a
card printed with one of these wordings needs no registration.

These used to be an ``elif`` chain of **exact string equality** inside
``engine/oracle.py``. That chain hardcoded *Island*, so a creature printed
"unless defending player controls a Mountain" fell through to a bare
``static_line``: the card reported `supported` and then attacked freely, with
the restriction silently absent. The land type is data, and is carried in the
payload.

Each entry names the code that enforces it, because a restriction recognized
here but dispatched nowhere is worse than one that fails to parse.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Basic land types a "controls a <type>" clause can name. Restricted to the five
# basics deliberately: the enforcing check in declare_attackers_step scopes its
# search to lands, and a nonbasic type would need the same scoping decided
# per card.
_LAND_TYPES = ("plains", "island", "swamp", "mountain", "forest")


@dataclass(frozen=True)
class CombatRestriction:
    """An instruction kind the combat steps dispatch on, plus its data."""

    kind: str
    payload: dict[str, object] = field(default_factory=dict)


# (pattern, kind) — enforced by:
#   cant_attack_without_land_type   phases/declare_attackers_step.can_attack
#   cant_attack                     phases/declare_attackers_step.can_attack
#   cant_block                      phases/declare_blockers_step
#   must_attack_each_combat         phases/declare_attackers_step._must_attack_if_able
#   cant_be_blocked_by_walls        phases/declare_blockers_step
#   cant_block_power_n_or_greater   phases/declare_blockers_step
#   must_be_blocked                 phases/declare_blockers_step
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            rf"^this creature can't attack unless defending player controls "
            rf"an? (?P<land_type>{'|'.join(_LAND_TYPES)})$"
        ),
        "cant_attack_without_land_type",
    ),
    (re.compile(r"^this creature can't attack$"), "cant_attack"),
    (re.compile(r"^this creature can't block$"), "cant_block"),
    (re.compile(r"^this creature attacks each combat if able$"), "must_attack_each_combat"),
    (re.compile(r"^this creature can't be blocked by walls$"), "cant_be_blocked_by_walls"),
    # A blocking *requirement* rather than a restriction (CR 509.1c), and
    # weaker than Lure's: **one** able creature must block it, not every
    # able creature. The two are enforced a dozen lines apart in the
    # blockers step and must not be folded together — "all able" on a card
    # printed "must be blocked" would forbid the defender keeping a blocker
    # back, which is a legal declaration.
    (re.compile(r"^this creature must be blocked if able$"), "must_be_blocked"),
    (
        # The threshold is data for the same reason the land type is: "power 4 or
        # greater" is the same restriction Ironclaw Orcs has, and baking 2 into
        # the instruction kind made every other number a new kind, a new handler
        # branch, and a new gate entry.
        re.compile(
            r"^this creature can't block creatures with power (?P<power>\d+) or greater$"
        ),
        "cant_block_power_n_or_greater",
    ),
)


def combat_restriction_for(normalized_line: str) -> CombatRestriction | None:
    """The combat restriction *normalized_line* imposes, or None.

    Takes an already-normalized line (``oracle.normalize_creature_line``), which
    is what the compiler holds at the point it needs this.
    """
    for pattern, kind in _PATTERNS:
        match = pattern.match(normalized_line)
        if match is None:
            continue
        # Numeric captures reach handlers as ints: a payload whose type depends
        # on which regex matched is how a comparison silently becomes a string
        # compare.
        payload = {
            key: int(value) if value is not None and value.isdigit() else value
            for key, value in match.groupdict().items()
        }
        return CombatRestriction(kind, payload)
    return None
