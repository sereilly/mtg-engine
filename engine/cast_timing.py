"""Printed permissions that widen *when* a card may be cast (CR 113.6b).

Two neighbours, and this file is neither of them. ``engine/cast_restrictions.py``
is the mirror: that table holds "Cast this spell only during …", a gate that
*narrows* legal timing, and its failure mode is a card cast too often. This one
holds the sentences that widen it, whose failure mode is the opposite — a card
that could have been cast and was refused, which breaks no rule and fails no
test, because a spell nobody can cast simply never appears.
``engine/cast_permissions.py`` is a different axis again: *where* a spell may be
cast **from** (CR 601.3's zones), which is state on the game rather than text on
the card.

**Mirage's five-card cycle is what this file is for.** Armor of Thorns, Grave
Servitude, Lightning Reflexes, Soar and Ward of Lights each print exactly:

    You may cast this spell as though it had flash. If you cast it any time a
    sorcery couldn't have been cast, the controller of the permanent it becomes
    sacrifices it at the beginning of the next cleanup step.

Two effects in one sentence, and the second is why the first cannot be
implemented alone. A permission dropped costs a card its trick; a **penalty**
dropped makes the card strictly better than the one printed, which is the
silent-wrongness this repo does not ship. So both halves are read here, off the
same line, and a card printing the permission without the rider it cannot
implement leaves the line unclaimed rather than half-claimed.

``CardDefinition.has_flash`` is the printed keyword and stays what it is. This
is the granted form its docstring predicted: "a permission about a card outside
the battlefield, so it will arrive as its own seam". :func:`casts_at_instant_speed`
is that seam, and it is the **one** question the timing gates ask — the web
layer had the printed half written out twice (``web/actions.py`` and
``web/state_view.py``), and a third spelling for the granted half would have
been the second copy this codebase keeps finding on the wrong side of.

The rider is enforced across three places, none of which knows the sentence:
the cast path records whether a sorcery could have been cast
(:data:`CAST_AT_INSTANT_SPEED`, a ``StackItem.choices`` key), the permanent
spell's resolution copies that answer onto the permanent, and the cleanup step
sacrifices what is marked. CR 514.1's cleanup step is where the rule puts it,
and a sweep there rather than a delayed trigger for the reason every other
sweep in this engine exists: there is no single fire site, and a permanent can
reach the battlefield marked by more than one route.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .game import Game

#: The metadata / ``StackItem.choices`` key recording that a spell was cast at a
#: time a sorcery could not have been. Stamped only for a card whose text asks —
#: a flag every cast wrote would be a record nothing reads on 1,868 cards.
CAST_AT_INSTANT_SPEED = "cast_at_instant_speed"

#: "You may cast this spell as though it had flash."
_FLASH_PERMISSION = re.compile(
    r"you may cast this spell as though it had flash"
)

#: The rider that always accompanies it in this cycle. Matched as its own
#: pattern rather than as a tail of the one above because the two are separate
#: effects with separate enforcement — but see :func:`cast_permission_line`,
#: which refuses to claim the permission without it.
_CLEANUP_SACRIFICE_RIDER = re.compile(
    r"if you cast it any time a sorcery couldn't have been cast, the "
    r"controller of the permanent it becomes sacrifices it at the beginning "
    r"of the next cleanup step"
)


def a_sorcery_could_be_cast(game: "Game", seat: int) -> bool:
    """CR 601.3d's timing: *seat*'s own main phase, with an empty stack.

    One rule, two readers. ``activation_restrictions`` asks it of "Activate only
    as a sorcery" and the cast path asks it of "any time a sorcery couldn't have
    been cast" — the same sentence in the CR, so the same function, because two
    spellings of one timing rule is how the two come to disagree about a turn.

    Asked of the state *before* the spell being announced reaches the stack,
    which is the only moment it can be asked: by resolution the stack has emptied
    down to this spell and the step may have moved on.
    """
    return (
        game.active_player_index == seat
        and game.current_turn_phase in ("precombat_main", "postcombat_main")
        and not game.stack
    )


def _normalize(text: str) -> str:
    return " ".join((text or "").replace("’", "'").split()).lower()


def grants_flash(oracle_text: str) -> bool:
    """Whether *oracle_text* gives its own spell flash timing (CR 702.8b)."""
    return _FLASH_PERMISSION.search(_normalize(oracle_text)) is not None


def sacrifices_at_cleanup_if_cast_at_instant_speed(oracle_text: str) -> bool:
    """Whether the permanent this spell becomes is sacrificed at the next
    cleanup step when the spell was cast at instant speed."""
    return _CLEANUP_SACRIFICE_RIDER.search(_normalize(oracle_text)) is not None


def casts_at_instant_speed(card) -> bool:
    """Whether *card* may be cast whenever an instant could be (CR 601.3d).

    The one question both timing gates ask. An instant by type, a card with
    printed flash, or a card whose own text grants it — three sources, one
    answer, so a card cannot be castable in the picker and refused by the
    action or the other way round.
    """
    return (
        card.primary_type == "instant"
        or card.has_flash
        or grants_flash(card.oracle_text or "")
    )


def cast_permission_line(line: str) -> bool:
    """Whether one printed line is a casting permission this file implements.

    The support gate's reader, and it is deliberately **all or nothing**: the
    permission is claimed only when the rider printed beside it is also one the
    engine enforces. A line claimed for its first sentence alone would ship
    five Auras that can be flashed in and never sacrificed — a strictly better
    card than the one printed, which is exactly the failure the whole-line rule
    in this repo exists to prevent.
    """
    normalized = _normalize(line).rstrip(".")
    if not grants_flash(normalized):
        return False
    return sacrifices_at_cleanup_if_cast_at_instant_speed(normalized)


__all__ = [
    "CAST_AT_INSTANT_SPEED",
    "a_sorcery_could_be_cast",
    "cast_permission_line",
    "casts_at_instant_speed",
    "grants_flash",
    "sacrifices_at_cleanup_if_cast_at_instant_speed",
]
