"""Separating objects into two piles: CR 700.3.

One node, because CR 700.3 describes one procedure and every card that prints
it prints the same three facts about it: **what** is separated, **who**
separates it and **who chooses** a pile — and then what becomes of the chosen
pile and of the other. Invasion prints it six times over three kinds of object
(cards revealed from a library, cards in a graveyard, permanents on a
battlefield), and the three differ in nothing the procedure cares about: a pile
is not a zone and its objects stay put (CR 700.3c), so nothing moves until a pile is acted on.

A family of its own rather than a node in ``library`` beside
:class:`~.library.SeparateLibraryTopIntoPiles`, which is Phyrexian Portal's
face-down procedure and names a pile *being looked through*. Four of the six
sentences here never touch a library; what they share is the split and the
choice, and that is this module's line on all three sides of the grammar
(``effects/separations.py``, ``lowering/separations.py``).
"""

from __future__ import annotations

from dataclasses import dataclass

from ._core import Amount, ObjectFilter


@dataclass(frozen=True)
class SeparateIntoPiles:
    """"Separate <objects> into two piles. <What happens to each pile.>"

    Every field is a printed word, read off the sentence and carried into the
    payload:

    ``what``
        ``"library_top"`` (the top ``count`` cards of the controller's library,
        revealed — Fact or Fiction), ``"graveyard"`` (the cards ``filter``
        names in the controller's graveyard — Death or Glory) or
        ``"battlefield"`` (the permanents ``filter`` names).

    ``whose``
        Whose objects, for the battlefield: ``"target_player"`` (Do or Die),
        ``"that_player"`` (Fight or Flight — the seat the trigger's event
        names), ``"each_defending_player"`` (Stand or Fall) or ``"each_player"``
        (Bend or Break). ``"you"`` for the library and the graveyard. A word
        naming several seats makes one pair of piles **per seat**.

    ``separator``
        ``"you"``, ``"an_opponent"`` (of the controller's choice — CR 608.2d)
        or ``"owner"``, the player whose objects they are ("**each player
        separates** all nontoken lands they control").

    ``chooser``
        ``"you"``, ``"an_opponent"``, ``"owner"`` ("the pile of **that
        player's** choice") or ``"owner_opponent"`` ("chosen by **one of their
        opponents of their choice**").

    ``chosen_fate`` / ``other_fate``
        What becomes of each pile — a closed vocabulary the handler's table
        performs (``engine/piles.py``): ``hand``, ``graveyard``, ``exile``,
        ``battlefield``, ``destroy``, ``tap``, ``only_attackers``,
        ``only_blockers``. ``other_fate`` is None where the sentence leaves the
        other pile alone.

    ``no_regeneration`` is "They can't be regenerated." behind a destroy.
    """

    what: str
    whose: str
    separator: str
    chooser: str
    chosen_fate: str
    other_fate: str | None = None
    count: Amount | None = None
    filter: ObjectFilter | None = None
    no_regeneration: bool = False
