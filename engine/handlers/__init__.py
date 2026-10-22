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
    animation,
    attachments,
    base_pt,
    bites,
    cards,
    colors,
    combat,
    control_changes,
    control_flow,
    counter_removal,
    counters,
    damage,
    damage_sweeps,
    delayed,
    destruction,
    discards,
    exile,
    fighting,
    hand,
    keyword_removal,
    keywords,
    library,
    life_and_game,
    linked_exile,
    mana,
    naming,
    offers,
    ownership,
    permanent_choices,
    permissions,
    phasing,
    piles,
    player_choices,
    prevention,
    pump,
    pt_switch,
    reanimation,
    redirection,
    regeneration,
    repeats,
    returns,
    reveal,
    sacrifices,
    search,
    shuffles,
    stack,
    tapping,
    tokens,
    types,
    value_choices,
    zones,
)

__all__ = ["EFFECT_HANDLERS", "EffectHandler", "effect_handler"]
