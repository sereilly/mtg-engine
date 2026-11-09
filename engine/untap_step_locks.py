"""Untap restrictions that belong to a **player's step**, not to a permanent
(CR 502.3, CR 611.2c).

"Creatures don't untap during target player's next untap step." (Blinding
Beam.) A resolving spell's continuous effect, and one that modifies no
characteristic and changes no controller — so by CR 611.2c it "modifies the
rules of the game" and "can affect objects that weren't affected when that
continuous effect began". The card's ruling (2013-06-07) says the same of this
card in particular: "The second mode affects all creatures during the player's
next untap step, including creatures controlled by other players (who may have
untapped because of Seedborn Muse, for example) and creatures that weren't on
the battlefield when Blinding Beam resolved."

So it cannot be ``handlers/tapping.skip_next_untap``'s marker, which is stamped
on the permanents there as the spell resolves: a creature cast afterwards would
untap on schedule. It is a record on the game naming a seat, a noun phrase and
how many of that seat's untap steps it lasts, read by the untap step as one
more entry in its ``blocked`` aggregate (``phases/untap_step._untap_constraints``)
and spent when that seat's untap step actually happens — not by a skipped one
(CR 500.11: a skipped step is not the "next untap step" the card named), the
rule the per-permanent marker already follows.

The record is ``Game.untap_step_locks``: a list of :class:`UntapStepLock`. It
changes when such a spell resolves and when the named step is spent, and at no
other time, so a ``vars()`` walker that reads it (``ai_rehearsal.
position_digest``) sees a lasting change exactly when the board has one.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass
class UntapStepLock:
    """One "<phrase> don't untap during <seat>'s next untap step" in force.

    ``seat`` is whose untap step it names; ``described`` the printed noun
    phrase as a ``subject_matches`` payload; ``observer`` the seat that
    resolved the effect, which "you" in that phrase is relative to (CR 109.5);
    ``steps`` how many of ``seat``'s untap steps are still to be spent;
    ``source`` the card that made it, for the log.
    """

    seat: int
    described: dict = field(default_factory=dict)
    observer: int | None = None
    steps: int = 1
    source: str = ""


def lock_untap_step(
    game, seat: int, described: dict, *, observer: int | None,
    steps: int = 1, source: str = "",
) -> UntapStepLock:
    """Record that *described* permanents don't untap during *seat*'s next
    *steps* untap steps, and return the record."""
    lock = UntapStepLock(
        seat=seat, described=dict(described), observer=observer,
        steps=max(1, int(steps or 1)), source=source,
    )
    game.untap_step_locks = [*getattr(game, "untap_step_locks", ()), lock]
    return lock


def untap_step_locks_for(game, seat: int | None) -> list[UntapStepLock]:
    """Every lock naming *seat*'s untap step, in the order they were made."""
    if seat is None:
        return []
    return [lock for lock in getattr(game, "untap_step_locks", ()) if lock.seat == seat]


def spend_untap_step_locks(game, seat: int) -> None:
    """Spend one step of every lock naming *seat*'s untap step, dropping the
    ones with none left. Called once that step has run (CR 611.2a: the effect
    lasts the step it named)."""
    kept = []
    for lock in getattr(game, "untap_step_locks", ()):
        if lock.seat == seat:
            if lock.steps <= 1:
                continue
            # A new record rather than an edit of the old one, so a copy of
            # the game that shares the list's members (a rehearsal's scratch
            # table) is never changed through this one.
            lock = replace(lock, steps=lock.steps - 1)
        kept.append(lock)
    game.untap_step_locks = kept


__all__ = [
    "UntapStepLock",
    "lock_untap_step",
    "spend_untap_step_locks",
    "untap_step_locks_for",
]
