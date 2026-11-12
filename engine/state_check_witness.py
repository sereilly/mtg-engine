"""Whether the last thing done to a table was a state-based check of it.

CR 704.3 checks state-based actions whenever a player would receive
priority, and the engine makes the check at each such moment: after an
object resolves (``resolve_next_object``), after an answer, and as a
priority window closes on an empty stack (CR 117.5,
``PhaseStepsMixin._window_may_close``). Some of those moments follow one
another with nothing done in between. A resolution's check is followed by
the window's closing check, with nothing on the stack and nothing answered.
A rehearsal settling a scratch copy (``ai_rehearsal._settle_scratch``) then
made a third check after both. The check runs to a fixed point
(``_check_state_based_actions``' ``while changed``), so a second check of
the table the first one left performs nothing. In the simulated games that
was about a sixth of the time: nearly every settle check, and over a third
of the window-close checks, found the table the previous check had left.

A **witness** is how a loop knows it stands at such a moment. It does not
guess from the stack. The priority window holds the witness for its game
(:func:`watching`), and every completed check of that game marks it
(:func:`saw`, called by ``check_state_based_actions``). The loop clears the
mark before each call of its own that could change the table: a
resolution, a prompt answered, priority offered. So "marked" means the
table is the one a check left, and nothing the loop did since has touched
it. A skip asks for that and nothing weaker. Whatever happened to the
table before the loop began is unseen, so every watch starts unmarked. The
window returns the mark it closed with (``_resolve_priority_window``),
which is what the rehearsal's settle reads.

**Nothing is remembered on the game.** The mark lives in a context
variable, one frame per watch, and it goes when the watch ends. A deep
copy (a rehearsal's scratch table) carries no mark of its original. A
digest that reads every field of ``vars(game)``
(``ai_rehearsal.position_digest``, the mode census's ``table_state``)
sees nothing new. Frames are matched by identity (``is``) on a reference
held for the length of the watch, never by ``id()``. A watch opened inside
another one (a window run inside a resolution, or a rehearsal's copy asked
about inside a priority offer) pushes a frame of its own and pops it. The
outer frame is left as it was, and the outer loop reads only the checks it
saw itself.

One thing is taken on trust, and it is the trust the window already
gives: a priority driver that answers False has passed (CR 117.3d), which
changes nothing. The window closes on that answer with no check after it.
A driver that tries something and reports False marks the table changed
(:func:`changed`), as the rehearsal's fight driver does around an
activation it tries.

Under ``fast_paths.CHECKING`` a skipped check is made anyway
(:func:`skipped`), and it must perform nothing: the same table before and
after, to the last field and log line. A check that would have acted
raises.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

from . import fast_paths


class Witness:
    """One watched game, and whether a check of it is the last thing that
    happened to it (``checked``)."""

    __slots__ = ("game", "checked", "parent")

    def __init__(self, game, parent: "Witness | None") -> None:
        self.game = game
        self.checked = False
        self.parent = parent


_CURRENT: ContextVar["Witness | None"] = ContextVar("state_check_witness", default=None)


@contextmanager
def watching(game):
    """Watch *game* for the length of the block, starting unmarked. Each
    watch is a frame of its own, even inside another watch of *game*: a
    window run inside a resolution marks its own frame, and the loop that
    called the resolution reads the check made after it."""
    witness = Witness(game, _CURRENT.get())
    token = _CURRENT.set(witness)
    try:
        yield witness
    finally:
        _CURRENT.reset(token)


def saw(game) -> None:
    """A state-based check of *game* has just completed. Only the innermost
    watch counts it, and only if that watch is of *game*. A check made while
    another table is watched leaves every outer watch unmarked, which is the
    safe way to be wrong."""
    current = _CURRENT.get()
    if current is not None and current.game is game:
        current.checked = True


def changed(game) -> None:
    """Something may have changed *game* without a check after it. Every open
    watch of *game* is unmarked."""
    witness = _CURRENT.get()
    while witness is not None:
        if witness.game is game:
            witness.checked = False
        witness = witness.parent


def skipped(game, label: str) -> None:
    """A check *game* does not need, because its witness is marked. Under
    ``fast_paths.CHECKING`` the check is made anyway, and it must perform
    nothing (:func:`fast_paths.checked`, counted under *label*)."""
    if not fast_paths.CHECKING:
        return
    before = table_text(game)
    performed = game.check_state_based_actions()
    after = table_text(game)
    fast_paths.checked(
        label, not performed and before == after,
        lambda: _first_difference(game, performed, before, after),
    )


def table_text(game) -> list:
    """Everything a check could write, as comparable text: ``(where, field,
    text)`` for each seat's fields (a permanent's fields with its seat's
    battlefield), the game's own fields, and how long the log is. Cards are
    given by name and permanents by their fields, so a check that computes
    the same values reads the same."""
    rows = [
        (f"seat {seat}", key, _value_text(value))
        for seat, player in enumerate(game.players)
        for key, value in sorted(vars(player).items())
    ]
    rows.extend(
        ("game", key, _value_text(value))
        for key, value in sorted(vars(game).items())
        if key not in ("players", "log")
    )
    rows.append(("game", "log", str(len(game.log))))
    return rows


def _value_text(value) -> str:
    if isinstance(value, list):
        return repr([_item_text(item) for item in value])
    return repr(value)


def _item_text(item):
    if hasattr(item, "permanent_id") and hasattr(item, "card"):
        return (
            item.permanent_id, item.card.name,
            sorted((key, repr(value)) for key, value in vars(item).items() if key != "card"),
        )
    if type(item).__name__ == "CardDefinition":
        return item.name
    return repr(item)


def _first_difference(game, performed: bool, before: list, after: list) -> str:
    """The first field the check moved, for the mismatch message."""
    where = f"turn {game.turn}, {game.current_turn_phase} / {game.current_step}"
    if performed:
        return f"the check performed an action ({where})"
    for was, now in zip(before, after):
        if was != now:
            return f"{was[0]}'s {was[1]} moved ({where}): {was[2]:.300} -> {now[2]:.300}"
    if len(before) != len(after):
        return f"a field came or went ({where}): {len(before)} -> {len(after)}"
    return "it moved nothing that was read"


__all__ = ["Witness", "changed", "saw", "skipped", "table_text", "watching"]
