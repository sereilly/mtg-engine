"""The two literal amounts every other node is allowed to contain.

The bottom of the bottom. ``_references`` needs :class:`Fixed` to read a
comparison's constant, and ``_core`` needs both for the counts that default to
one — so a node **both** halves need cannot live in either of them without one
importing the other. That is the same rule CLAUDE.md states for the parse side
("a fragment two families need goes in ``phrases``/``_common``/``_core``, never
in one of them"), applied one level further down when ``_core`` itself split.

Nothing here imports anything. If a third node ever turns out to be needed by
both halves, it belongs here rather than in whichever half was written first.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Fixed:
    """A literal count: "3 damage", "two cards"."""
    value: int


@dataclass(frozen=True)
class AnyNumber:
    """"remove **any number of** +1/+1 counters" (Tetravus) — a count its
    controller chooses on resolution, bounded by what is there to take.

    Distinct from :class:`AllOf`, which is "all of them" and is not a choice,
    and from :class:`Fixed`, which is a number the card printed. Keeping the
    three apart is what stops "any number" being lowered as "one" or as "all",
    either of which is a different card.
    """
