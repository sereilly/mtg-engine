"""The stack (CR 405) — putting things on it, and taking them off.

One 2,277-line ``stack_casting`` module held four distinct jobs. They are now a
mixin each, composed onto :class:`~engine.game.Game` the same way
``engine.phases`` composes one mixin per turn phase:

    casting      SpellCastingMixin       CR 601 — cast a spell from hand
    activation   AbilityActivationMixin  CR 602 — activate a permanent's ability
    resolution   StackResolutionMixin    CR 603/608 — trigger, resolve, clean up
    choices      PendingChoicesMixin     the arm / confirm / auto-resolve queue

The split is along "what stage of the object's life is this?", which is why
``choices`` exists as its own module rather than staying inside the two that arm
its prompts: a pending choice belongs to no single stage, and the arm/confirm/
auto-resolve triple is only recognisable as one pattern when its 33 members sit
together.

The four are disjoint — no method moved between them and none is overridden, so
composition order carries no meaning.
"""

from .activation import AbilityActivationMixin
from .casting import (
    SpellCastingMixin,
    aura_enchant_noun,
    permanent_matches_enchant_noun,
)
from .choices import PendingChoicesMixin
from .resolution import StackResolutionMixin

__all__ = [
    "AbilityActivationMixin",
    "PendingChoicesMixin",
    "SpellCastingMixin",
    "StackResolutionMixin",
    "aura_enchant_noun",
    "permanent_matches_enchant_noun",
]
