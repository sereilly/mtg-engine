"""Cards a player holds but may not play, and holds face up (CR 614 riders).

Firestorm Phoenix: "If this creature would die, return it to its owner's hand
instead. **Until that player's next turn, that player plays with that card
revealed in their hand and can't play it.**" The first sentence is the
replacement (``engine/replacements.py``); this module is the second, which is
not a replacement at all but a lasting restriction on one card in one hand.

**Why it is not stamped on the card.** Every other "this object is under an
effect" record in the engine lives on the object — ``Permanent.metadata``, the
Wall of Dust stamp, the linked exile. A card in a hand has no such place: a
:class:`~engine.models.CardDefinition` is the card *as printed*, immutable and
**shared** — a deck with two Firestorm Phoenixes holds the same object twice
(``web/deck_builder.build_deck_from_entries``), and a stamp on it would be a
stamp on both. So the record lives here, on the game, keyed by seat and card.

**And why that is exactly right rather than a compromise.** Two copies of one
card in a hand are indistinguishable — the hand is a hidden zone with no
order anyone may rely on (CR 400.2) — so "which copy is locked" is not a
question the game can ask. What is observable is *how many*: with two copies
in hand and one locked, the player may play one. The record is therefore a
**count** per (seat, card), and the readers below take the first that many
occurrences. A caller looking for a copy to play asks for the first *unlocked*
one, the same way ``_cast_onto_stack`` already prefers the occurrence that
carries a casting permission.

**Expiry is derived, not swept.** "Until that player's next turn" is an ordinal
against ``Game.seat_turn_counts`` — the same reading Wall of Dust's "can't
attack during its controller's next turn" takes
(``engine/phases/declare_attackers_step.py``). A lock records the seat ordinal
it expires *on*, so a turn that walks past it needs nothing swept and a lock
can never outlive its sentence because someone forgot a clearing line.
:func:`expire_hand_locks` only keeps the list from growing.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HandLock:
    """One card in one hand, revealed and unplayable until a stated turn.

    ``card`` is held by identity, and ``expires_on_seat_turn`` is the value
    ``Game.seat_turn_counts[seat]`` reaches when the restriction ends — the
    seat's *next* turn, counted at the moment the lock is made.
    """

    seat: int
    card: Any
    expires_on_seat_turn: int
    source_name: str


def lock_card_in_hand(game, seat: int, card, source_name: str) -> None:
    """Record that one copy of *card* in *seat*'s hand is revealed and
    unplayable until that seat's next turn."""
    game.hand_locks.append(
        HandLock(
            seat=seat,
            card=card,
            expires_on_seat_turn=game.seat_turn_counts.get(seat, 0) + 1,
            source_name=source_name,
        )
    )


def live_hand_locks(game, seat: int) -> list[HandLock]:
    """*seat*'s locks that have not yet expired.

    A lock made during the seat's own turn survives the rest of it and ends
    when their *next* turn begins; one made during an opponent's turn ends at
    the very next turn of this seat. Both fall out of the one comparison,
    which is why "that player's next turn" is stored as an ordinal rather than
    as "one turn from now".
    """
    current = game.seat_turn_counts.get(seat, 0)
    return [
        lock
        for lock in getattr(game, "hand_locks", ())
        if lock.seat == seat and current < lock.expires_on_seat_turn
    ]


def locked_hand_indices(game, seat: int) -> frozenset[int]:
    """The positions in *seat*'s hand that are revealed and can't be played.

    The first N occurrences of each locked card, N being how many locks that
    card has. A lock whose card is no longer in the hand matches nothing and
    quietly does nothing, which is the honest answer: the sentence is about a
    card in a hand.
    """
    owed: Counter = Counter()
    for lock in live_hand_locks(game, seat):
        owed[id(lock.card)] += 1
    if not owed:
        return frozenset()
    locked: set[int] = set()
    for index, card in enumerate(game.players[seat].hand):
        if owed[id(card)] > 0:
            owed[id(card)] -= 1
            locked.add(index)
    return frozenset(locked)


def playable_hand_index(game, seat: int, card_name: str) -> int | None:
    """The position of a copy of *card_name* in *seat*'s hand that may be
    played, or None when every copy there is locked.

    None and "no copy at all" are deliberately the same answer to the caller
    that asks — both mean this seat cannot play that card right now — and the
    caller distinguishes them for its error message.
    """
    locked = locked_hand_indices(game, seat)
    for index, card in enumerate(game.players[seat].hand):
        if card.name == card_name and index not in locked:
            return index
    return None


def hand_lock_reason(game, seat: int, card_name: str) -> str | None:
    """Why *seat* may not play *card_name*, or None. The message names the
    source, because "you can't play that" with no reason is indistinguishable
    from a bug to the player reading the log."""
    for lock in live_hand_locks(game, seat):
        if getattr(lock.card, "name", None) == card_name:
            return (
                f"{card_name} can't be played until "
                f"{game.players[seat].name}'s next turn ({lock.source_name})"
            )
    return None


def expire_hand_locks(game) -> None:
    """Drop locks whose turn has passed.

    Housekeeping only — :func:`live_hand_locks` already ignores them, so
    nothing behaves differently for having run this. It exists so a long game
    does not carry every lock it ever made.
    """
    game.hand_locks = [
        lock
        for lock in getattr(game, "hand_locks", ())
        if game.seat_turn_counts.get(lock.seat, 0) < lock.expires_on_seat_turn
    ]


__all__ = [
    "HandLock",
    "expire_hand_locks",
    "hand_lock_reason",
    "live_hand_locks",
    "lock_card_in_hand",
    "locked_hand_indices",
    "playable_hand_index",
]
