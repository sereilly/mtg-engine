"""Tapped creatures that can block as though they were untapped (CR 509.1a).

"Tapped creatures you control can block as though they were untapped."
(Masako the Humorless.) CR 509.1a lets the defending player declare blockers
from among their **untapped** creatures; this static relaxes that one word for
the creatures its controller controls, and nothing else — the ruling
(2004-12-01): "Masako allows tapped creatures to block only if they could
otherwise block. It doesn't allow creatures that 'can't block' to block,
nonflying creatures to block fliers, etc." So it is asked exactly where the
engine asks "is this creature untapped?" of a would-be blocker, and every
other block gate (``_can_block_attacker``, the requirements) still runs.

A static of the permanent, so like every derivation table here it is read off
the board's own text when asked (``effective_card``: a Masako that has lost
its abilities stops granting it, a copy of one grants it) and there is nothing
to arm or clear. One reader — :func:`tapped_blockers_line` — for the support
gate, the grammar's registry claim and the blocker gates, so the claim cannot
outlive the enforcement.

Blocking does not untap the creature: CR 509.1a's untapped requirement is the
only thing waived, and a tapped blocker still deals and is dealt combat damage
(CR 510.1 says nothing of tapped blockers, unlike CR 506.4's attackers).
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .game import Game
    from .models import Permanent

#: The label the grammar's registry claim gives the line.
CLAIM = "tapped_blockers"

#: "Tapped creatures you control can block as though they were untapped." The
#: scope word is the controller's ("you control", CR 109.5): a wider printing
#: ("Tapped creatures can block …") would be a different card and refuses.
_TAPPED_BLOCKERS = re.compile(
    r"^tapped creatures you control can block as though they were untapped$"
)


@lru_cache(maxsize=None)
def tapped_blockers_line(line: str) -> bool:
    """Whether *line* is, in full, Masako's static."""
    normalized = " ".join((line or "").strip().lower().rstrip(".").split())
    return _TAPPED_BLOCKERS.match(normalized) is not None


def may_block_while_tapped(game: "Game", permanent: "Permanent") -> bool:
    """Whether a permanent on the battlefield controlled by *permanent*'s
    controller prints Masako's static. Pure."""
    seat = game.controller_index_of(permanent)
    if seat is None:
        return False
    for source_seat, source in game.permanents_with_controller():
        if source_seat != seat:
            continue
        text = source.effective_card.oracle_text or ""
        if "as though they were untapped" not in text.lower():
            continue
        if any(tapped_blockers_line(line) for line in text.splitlines()):
            return True
    return False


def tapped_out_of_blocking(game: "Game", permanent: "Permanent") -> bool:
    """Whether CR 509.1a's untapped requirement keeps *permanent* from
    blocking: it is tapped and nothing lets it block as though it were not.
    The one question every blocker gate and the AI's blocker lists ask in
    place of ``permanent.tapped``."""
    return bool(permanent.tapped) and not may_block_while_tapped(game, permanent)


__all__ = [
    "CLAIM", "may_block_while_tapped", "tapped_blockers_line",
    "tapped_out_of_blocking",
]
