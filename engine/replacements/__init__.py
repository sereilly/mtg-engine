"""Replacement-effect registry (CR 614).

"If X would happen, do Y instead" effects intercept an event before the
default action applies. Each event kind has an ordered interceptor list; an
interceptor inspects the game/payload and either passes (returns None),
modifies the event amount, or consumes the event entirely (the default action
does not happen).

Interceptors self-select from game state (metadata flags, oracle-text
probes), so the registry stays name-free — bespoke per-card registration
belongs in engine/card_hooks.py.

Event kinds and their payload keys:

- ``life_gain``:          {player, amount, source_name}
- ``damage_to_creature``: {recipient, amount, source, combat}
- ``damage_to_player``:   {recipient, amount, source, combat}
- ``damage_marked``:      {recipient, amount, dealt, source, combat}
- ``life_loss``:          {recipient, amount, dealt, source, combat}
- ``would_die``:          {player, permanent}
- ``would_leave_battlefield``: {player, permanent, destination}
- ``discard``:            {player, card}
- ``draw``:               {player, count, drawn}

``discard`` and ``draw`` are *interactive*: their interceptors offer a
:class:`~engine.replacement_choices.ReplacementChoice` rather than applying
the effect outright, and report what they did through ``payload["drawn"]``.

The four damage kinds spell their subject ``recipient`` rather than
``permanent``/``player`` because a damage event is *one* event shared with
engine/prevention/ — see the ordering note below.

**A damage event has two halves, and they are different kinds** (CR 120.4).
First damage is *dealt*, as modified by the effects that interact with damage
— shields and redirects (120.4b). Then the damage that was dealt is *processed
into its results*, as modified by the effects that interact with those results
(120.4c): life lost for a player, damage marked for a creature. So
``damage_to_player`` and ``damage_to_creature`` are the first half, ``life_loss``
and ``damage_marked`` the second.

That is not a distinction for its own sake. Ali from Cairo — "damage that would
reduce your life total to less than 1 reduces it to 1 instead" — modifies the
*result*, so the damage is still dealt in full: lifelink gains the full amount
(CR 120.3f) and a "whenever ~ deals damage to a player" trigger sees the full
amount, while only the life loss is capped. Collapsing the two halves into one
number is what forced the combat damage step to run its shields and its
replacements at two different moments for years.

**Ordering (CR 616.1).** Interceptors do not run as a fixed chain. Each carries
an ``applies`` predicate and an ``order``, and ``engine/effect_ordering.py``
gathers everything applicable, applies one, then re-asks the rest against what
is now true (616.1f). The predicate is the guard the interceptor used to open
with, *moved* rather than copied, so the body starts after the decision and the
two cannot drift; and it must be pure, because an effect that is asked about may
then not be chosen.

Order is a per-kind space — two kinds are never in contention — with one
exception that matters. CR 616.1 does not separate replacement from prevention:
a damage event's replacements and its shields are *one* contention set. So the
two damage kinds share an order space with ``engine/prevention/``, and
``engine/damage_events.py`` is where the union is formed and where a collision
between the two registries raises at import.

This package was one 5,549-line module, ``replacements.py``, until the
2,000-line cap's split round cut it by what the event is:

    registry              the interceptor lists, the order space and its bands,
                          ``@replacement_effect``, and the CR 616.1 loop
    damage                damage as it is dealt, and the life it costs: caps,
                          shifts, multipliers, doublers, the life floor
    redirects             damage moved to another recipient (CR 614.9)
    damage_substitutions  damage replaced by an event that is not damage
    draws                 a draw replaced, the queue a suspended one holds, and
                          Lich's life gain drawn as cards
    revealed_draws        a draw replaced by a look at or a reveal of the top
    permanents            a permanent entering, untapping, getting +1/+1
                          counters, or tapped for mana — replaced
    zone_changes          dying, leaving, discarding, or going to a graveyard
                          — somewhere else instead
    lines                 ``REPLACEMENT_LINES`` and ``replacement_claims_line``:
                          which printed lines the package implements

Every interceptor module registers at import, so every one is imported here: a
name pulled from any of them first runs this file, which is what keeps each
kind's list whole whichever module a caller reaches for. ``order`` is the
behaviour, and every list is kept sorted by it, so the order those modules
import in decides nothing.
"""

from .registry import (REPLACEMENTS, ReplacementOutcome, apply_replacements,
                       order_prompt_asker, replacement_candidates,
                       replacement_effect, take_replaced, was_replaced)
from . import (  # noqa: F401  (each registers its interceptors)
    damage,
    redirects,
    damage_substitutions,
    draws,
    revealed_draws,
    permanents,
    zone_changes,
)
from .lines import REPLACEMENT_LINES, replacement_claims_line

# Temporary re-exports, not an API: each is pulled from the package by a module
# another group of the 2,000-line cap's split round is cutting in parallel
# (``engine/handlers/damage.py``, ``engine/mixins/effects.py``,
# ``engine/mixins/helpers.py``). Each goes when its importer is repointed at
# the module named here.
from .damage_substitutions import DAMAGE_TO_COUNTER_REMOVAL_RECORD
from .permanents import apply_entry_riders
from .zone_changes import TOP_OF_LIBRARY_DISCARD_TEXT

__all__ = [
    "REPLACEMENTS",
    "REPLACEMENT_LINES",
    "ReplacementOutcome",
    "apply_replacements",
    "order_prompt_asker",
    "replacement_candidates",
    "replacement_claims_line",
    "replacement_effect",
    "take_replaced",
    "was_replaced",
]
