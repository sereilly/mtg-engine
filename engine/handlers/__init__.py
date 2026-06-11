"""Effect handler registry.

Each module in this package registers executors for oracle-instruction kinds
via the @effect_handler decorator. The game dispatches instructions with a
single dict lookup, so adding new effects never touches existing code paths —
drop a new handler function in the matching category module (or a new module
imported here) and it is live.
"""

from .registry import EFFECT_HANDLERS, EffectHandler, effect_handler

# Importing the category modules populates EFFECT_HANDLERS.
from . import (  # noqa: E402,F401
    board_misc,
    combat,
    damage,
    destruction,
    life_and_game,
    mana,
    prevention,
    pump,
    regeneration,
    stack,
    tapping,
    zones,
)

__all__ = ["EFFECT_HANDLERS", "EffectHandler", "effect_handler"]
