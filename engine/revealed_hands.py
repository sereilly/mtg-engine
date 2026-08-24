"""Playing with hands revealed (CR 701.20a).

"Players play with their hands revealed." (Revelation.) Revealing shows the
card to *all* players (CR 701.20a); the hand stays a hidden zone by
classification (CR 400.2 — "even if all the cards in one such zone happen to
be revealed"), so nothing here moves a card or changes what the zone is. The
whole effect is who may see what, which makes the *viewer* — the web layer's
per-seat serialization — the consumer, not the rules engine's own steps.

The library-top twin ("Players play with the top card of their libraries
revealed.", Field of Dreams) lives with the other top-of-library permissions
in ``engine/library_top.py`` — one home per zone, because that module already
answers every "who may see or play the top card?" question and a second copy
of the reveal half is how the two would drift.

The answer here is **derived, never stored**: a static ability's effect exists
while its source is on the battlefield, so the predicate scans the board
through the control seam and reads each permanent's :attr:`effective_card` (a
layer-3 text change edits this line like any other). A source leaving ends
the effect by no longer being in the scan — there is no flag to go stale.

The predicate takes an ``(owner_seat, viewer_seat)`` pair even though this
card reveals every hand to everyone: "whose hand" and "who is looking" is the
real shape of the question — Telepathy's "**Your opponents** play with their
hands revealed" scopes the owner by the source's controller — so the seam
takes the pair now rather than teaching every consumer a second calling
convention later.
"""

from __future__ import annotations

import re

_REMINDER = re.compile(r"\([^)]*\)")

#: The whole-line phrase this module implements, anchored end to end by
#: normalization: a sentence saying more than the phrase stays unclaimed.
_HANDS_LINE = "players play with their hands revealed"


def _normalized(line: str) -> str:
    return " ".join(_REMINDER.sub("", line).strip().lower().split()).rstrip(".")


def revealed_hands_line(line: str) -> bool:
    """Whether *line* is the hands-revealed static, in full.

    The grammar's registry claim and the support gate both ask this, so what
    the scan below enforces and what the compiler admits cannot drift.
    """
    return _normalized(line) == _HANDS_LINE


def hand_revealed_to(game, owner_seat: int, viewer_seat: int | None) -> bool:
    """Whether a standing effect reveals *owner_seat*'s hand to *viewer_seat*.

    Only the effect: a player seeing their own hand is the game's baseline,
    answered by the caller, not by this table.
    """
    for perm in game.all_permanents():
        text = perm.effective_card.oracle_text or ""
        if any(revealed_hands_line(raw) for raw in text.splitlines()):
            return True
    return False


__all__ = ["hand_revealed_to", "revealed_hands_line"]
