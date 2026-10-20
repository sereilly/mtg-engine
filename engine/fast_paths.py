"""The checking mode for the shortcuts the CR 613 accessors take.

``Permanent.effective_card`` (``engine/models.py``) and layer 4's
``computed_types`` / ``computed_supertypes`` (``engine/layer_bridge.py``) are
the most-read functions in the engine — 4.5 million and 0.7 million reads in
two simulated Mirage games — and nearly every read is of a permanent nothing
has touched: no copy, no text change, no grant, no type change. Each of them
answers that case **without running its fold**, by asking whether any of the
metadata channels the fold reads holds anything (``models.fold_channels``,
``layer_bridge.type_effect_channels``). Nothing is remembered between reads, so
there is nothing to go stale.

What can go wrong is the tuple: a channel the fold reads and the tuple does
not name is an effect applied on the reads that take the fold and dropped on
the rest. Each tuple is held by a test that runs its fold over a permanent
whose metadata records every key read. This module is the second line, the one
that covers whole games: while :data:`CHECKING` is true, every answer a
shortcut gives is computed again the long way, a different answer raises, and
:data:`CHECKED` counts the answers checked per accessor, so a run under the
flag can say how much it examined.

Set by a harness — a test, or a seeded simulator run wrapped to set it — and
never by the engine. Imports nothing from the engine.
"""

from __future__ import annotations

from typing import Callable

#: Whether every shortcut answer is checked against the full computation.
CHECKING = False

#: How many shortcut answers have been checked, per accessor.
CHECKED: dict[str, int] = {}


def checked(label: str, agrees: bool, describe: Callable[[], str]) -> None:
    """Count one checked answer of *label*'s shortcut, and raise if the full
    computation disagreed with it. *describe* is asked only on a mismatch."""
    CHECKED[label] = CHECKED.get(label, 0) + 1
    if not agrees:
        raise RuntimeError(
            f"{label}'s shortcut disagrees with its full computation: {describe()}"
        )


__all__ = ["CHECKED", "CHECKING", "checked"]
