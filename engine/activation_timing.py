"""Printed permissions that widen *when* a class of abilities may be activated.

"You may activate equip abilities any time you could cast an instant."
(Leonin Shikari.) The activation twin of ``engine/cast_timing.py``'s static
flash permission, and kept beside it rather than inside it because the two
gates it answers are different: that file is asked by the cast path, this one
by ``engine/activation_restrictions.py``'s "Activate only as a sorcery" row —
the clause CR 702.6a writes into every equip ability, and the only thing the
permission lifts.

CR 304.5 says what the permission means: "any time they could cast an
instant" is that the player has priority, so a permitted ability is held to
that and nothing less. The 2004-12-01 ruling says what it does not reach:
"You're still subject to any other restrictions on activating equip
abilities" — a second clause on the line (a use budget, a condition) is still
asked by its own row.

**Whose** abilities: "you" is the permission's controller (CR 109.5), and the
activator is the one the sorcery row asks about — so a seat's Shikari moves
that seat's Equipment and nobody else's. **Which** abilities: the printed class
word, answered by the class's one reader (an equip ability is
``equipment.is_equip_ability_text``: the rewrite run backwards, never "attaches
this permanent"). A class with no reader leaves the line unclaimed, so its card
is unsupported rather than permitted to activate a class nothing narrows.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .game import Game

_ACTIVATION_TIMING_PERMISSION = re.compile(
    r"^you may activate (?P<klass>[a-z]+) abilities "
    r"any time you could cast an instant$"
)


def _equip(card, ability_text: str) -> bool:
    from .equipment import is_equip_ability_text

    return is_equip_ability_text(card, ability_text)


#: The ability classes a permission may name, each with the one reader that
#: says whether a line of a card is one.
_ABILITY_CLASSES: dict[str, Callable[[object, str], bool]] = {"equip": _equip}


def _normalize(text: str) -> str:
    return " ".join((text or "").replace("’", "'").split()).lower().rstrip(".")


def activation_timing_permission(line: str) -> str | None:
    """The ability class one printed *line* lets its controller activate at
    instant speed, or None.

    Read by the support gate (``derived_static_claims``, ``static_line_support``,
    the parse-coverage census) **and** by :func:`instant_timing_permits`, so
    what is claimed and what is enforced are one table.
    """
    match = _ACTIVATION_TIMING_PERMISSION.match(_normalize(line))
    if match is None or match.group("klass") not in _ABILITY_CLASSES:
        return None
    return match.group("klass")


def activation_timing_permissions_on(permanent) -> tuple[str, ...]:
    """Every ability class *permanent* currently permits, off its effective
    card (a text change or a copy rewrites what it says, CR 612.1 / 707.2)."""
    card = getattr(permanent, "effective_card", None) or getattr(permanent, "card", None)
    text = getattr(card, "oracle_text", "") or ""
    if "any time you could cast an instant" not in text.lower():
        return ()
    return tuple(
        found for line in text.splitlines()
        if (found := activation_timing_permission(line)) is not None
    )


def instant_timing_permits(game: "Game", seat: int, source, ability_text: str) -> bool:
    """Whether a permanent *seat* controls lets them activate *source*'s
    ability *ability_text* any time they could cast an instant.

    Asked by the "Activate only as a sorcery" row only, which then holds the
    activation to CR 304.5's priority instead of CR 307.1's timing.
    """
    card = getattr(source, "effective_card", None) or getattr(source, "card", None)
    if card is None:
        return False
    for permanent in game.controlled_by(seat):
        for klass in activation_timing_permissions_on(permanent):
            if _ABILITY_CLASSES[klass](card, ability_text):
                return True
    return False


__all__ = [
    "activation_timing_permission",
    "activation_timing_permissions_on",
    "instant_timing_permits",
]
