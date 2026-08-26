"""Physical-dexterity actions (CR 104.1), simulated.

A handful of very early cards ask a player to *physically manipulate the
cards*: Chaos Orb and Falling Star are both flipped onto the table from a
height of at least one foot, and what they hit is decided by where they land.
CR 104.1 puts that outside the game's own rules — there is no playing area
here, no geometry for "lands on", and no honest reading of "doesn't turn
completely over".

So the engine **substitutes** a random selection, and this module is the one
place that substitution is made. That matters for two reasons:

* It is a house rule, not a reading of the card. Keeping it in a module of its
  own, named for what it is, stops it from looking like rules text somebody
  merely implemented badly — anyone reading a flip handler is sent here and
  told plainly that the card's real instruction cannot be carried out.
* Both cards must substitute the *same* way. Chaos Orb grew its own inline
  ``random.sample`` first; when Falling Star arrived it would have grown a
  second, and two independently-drifting house rules for one printed idiom is
  the failure this engine keeps finding in its own tables.

The parameters stay with the caller, because they are the cards' own numbers
rather than the substitution's: Chaos Orb touches up to two permanents,
Falling Star lands on one to three creatures.

**The flip always turns over.** Both cards make their effect conditional on
that ("if this artifact turns over completely at least once", "if Falling Star
doesn't turn completely over ... it has no effect"), and the engine treats the
condition as met. A random chance of nothing happening would be a second
invented number on top of the first, and it would make the cards untestable
without pinning the seed of every test that touches them.
"""

from __future__ import annotations

import random
from typing import Sequence, TypeVar

T = TypeVar("T")

#: Whether a simulated flip turns completely over (see the module docstring).
#: A named constant rather than a bare ``True`` at each site, so the two cards
#: cannot disagree and so the assumption is greppable.
FLIP_TURNS_OVER = True


def flip_lands_on(
    candidates: Sequence[T], *, maximum: int, minimum: int = 0
) -> list[T]:
    """Return the objects a simulated flip lands on.

    A uniformly random subset of *candidates*, of a uniformly random size
    between *minimum* and *maximum* (both inclusive, and both clamped to what
    is actually on the board — a flip cannot land on more permanents than
    exist, and asking for a minimum of one on an empty board yields nothing
    rather than raising).

    Drawn from the module-level ``random``, deliberately: ``run_ai_simulation``
    seeds that module, so a given seed reproduces a run exactly, and a private
    ``Random`` instance here would silently break that guarantee for every
    simulation involving one of these cards.
    """
    if not candidates:
        return []
    top = min(maximum, len(candidates))
    bottom = max(0, min(minimum, top))
    count = random.randint(bottom, top)
    if count <= 0:
        return []
    return random.sample(list(candidates), count)
