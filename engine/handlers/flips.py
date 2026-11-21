"""A permanent flipped by an effect (CR 710): "flip this creature", "flip it".

The status and what it does to the permanent are ``engine/flip_cards.py``'s —
a flipped flip card's ``Permanent.card`` *is* its bottom half, with the top
half's cost and colours (CR 710.1c) — and so is the one seam called here,
:func:`~engine.flip_cards.flip_permanent`. What is here is the effect half:
which permanent the sentence names. Every card printing the verb flips the
ability's own source, and only while it is still the object the ability came
from (CR 400.7).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .registry import effect_handler

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("flip_self")
def flip_self(game: "Game", instruction: "OracleInstruction",
              context: "OracleExecutionContext") -> tuple[bool, str]:
    """"…flip this creature." (Jushi Apprentice, Nezumi Graverobber, ….)
    "…, flip it." (Student of Elements, Akki Lavarunner, Kitsune Mystic.)

    The ability's own source, if it is still on the battlefield as the
    permanent the ability came from: one that left and came back is a new
    object the ability knows nothing of (CR 400.7), and a card in a graveyard
    has no status to set (CR 110.5d). Already flipped, nothing happens
    (CR 710.4: "Flipping a permanent is a one-way process").
    """
    from ..flip_cards import flip_permanent

    permanent = context.source_permanent
    name = context.card.name if context.card is not None else "It"
    if permanent is None or not game.is_on_battlefield(permanent):
        game.log.append(f"{name}: it is no longer on the battlefield, so it does not flip")
        return True, "resolved"
    if not flip_permanent(game, permanent):
        game.log.append(f"{name}: it is already flipped")
    return True, "resolved"
