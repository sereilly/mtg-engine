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

#: The whole-line phrases this module implements, mapped to **whose** hand each
#: one opens, anchored end to end by normalization: a sentence saying more than
#: the phrase stays unclaimed.
#:
#: "everyone" is Revelation's — every hand at the table. "controller" is
#: Enduring Renewal's "Play with your hand revealed", where "your" is CR 109.5's
#: answer: the controller of the static ability, which is the permanent's
#: controller. The pair the module's docstring said the seam was shaped for.
_HANDS_LINES: dict[str, str] = {
    "players play with their hands revealed": "everyone",
    "play with your hand revealed": "controller",
}


#: Where a *granted* reveal is recorded, on the permanent that granted it:
#: the seats whose hands it opens, as a list of indices.
#:
#: "…have defending player play with their hand revealed **for as long as this
#: creature remains on the battlefield**." (Stromgald Spy.) The table above is
#: keyed to a printed *line*, which is the whole of a static ability; this one
#: is created by a resolution and names a seat the combat froze, so no line can
#: say it.
#:
#: On the permanent rather than on a player, and that is what implements the
#: duration: this module's scan is over the battlefield, so a source that leaves
#: stops contributing with nothing to sweep (CR 611.2b), and a returning one is
#: a new object with no record (CR 400.7). A per-seat flag would need a watcher
#: to clear it, and the watcher is what the module's docstring says it does not
#: want.
HAND_REVEALED_SEATS = "hand_revealed_to_seats"


def reveal_hand_while_present(source, owner_seat: int) -> None:
    """Record that *source* opens *owner_seat*'s hand while it is on the
    battlefield. Idempotent — a second attack re-reveals a hand already
    revealed, which is not two effects."""
    seats = source.metadata.setdefault(HAND_REVEALED_SEATS, [])
    if owner_seat not in seats:
        seats.append(owner_seat)


def _normalized(line: str) -> str:
    return " ".join(_REMINDER.sub("", line).strip().lower().split()).rstrip(".")


def revealed_hands_line(line: str) -> bool:
    """Whether *line* is one of the hands-revealed statics, in full.

    The grammar's registry claim and the support gate both ask this, so what
    the scan below enforces and what the compiler admits cannot drift.
    """
    return _normalized(line) in _HANDS_LINES


def _line_scope(line: str) -> str | None:
    """Whose hand *line* opens, or None when it is not one of these lines."""
    return _HANDS_LINES.get(_normalized(line))


def hand_revealed_to(game, owner_seat: int, viewer_seat: int | None) -> bool:
    """Whether a standing effect reveals *owner_seat*'s hand to *viewer_seat*.

    Only the effect: a player seeing their own hand is the game's baseline,
    answered by the caller, not by this table.

    **Whose** hand each line opens is the scope the phrase carries, and reading
    it is what keeps Enduring Renewal from revealing the opponent's hand too:
    "play with **your** hand revealed" is one seat's, and a scan that answered
    True for any matching line would turn a one-sided drawback into a
    two-sided one.
    """
    for controller_index, perm in game.permanents_with_controller():
        # The granted record first: it is the cheaper question and it is not a
        # property of the text at all (Stromgald Spy's own printed line says
        # nothing about a hand while the creature is merely sitting there —
        # the reveal exists because an attack resolved).
        if owner_seat in (perm.metadata.get(HAND_REVEALED_SEATS) or ()):
            return True
        text = perm.effective_card.oracle_text or ""
        for raw in text.splitlines():
            scope = _line_scope(raw)
            if scope == "everyone":
                return True
            if scope == "controller" and owner_seat == controller_index:
                return True
    return False


__all__ = [
    "HAND_REVEALED_SEATS",
    "hand_revealed_to",
    "reveal_hand_while_present",
    "revealed_hands_line",
]
