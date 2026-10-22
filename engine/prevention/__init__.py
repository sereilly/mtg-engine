"""Damage-prevention registry (CR 615).

A prevention effect is a shield sitting on a player or a permanent that removes
points from a damage event before the damage is dealt (CR 615.1). Like
replacement effects (CR 614, ``engine/replacements/``) each shield is a
registered interceptor that self-selects from game state, so supporting a new
kind of shield means registering a function — never editing a cascade.

**The state is generic too.** This registry's shields once read a
``PlayerState`` field named after the card that granted them
(``forcefield_capped_sources``, ``reverse_damage_charges``,
``color_prevention_shields``), so "register a function" was only half true: the
other half was a new field on a model the web payload, the AI simulator and
forty tests read. A shield is now a :class:`~engine.shields.Shield` in one
collection on its recipient — what it answers to, how much it absorbs, how many
uses remain, how long it lasts — and the old names survive as views over that
collection. Adding a shield is one registration plus a ``Shield``; see
``engine/shields.py``.

Preventers run in ascending ``order`` over one event payload::

    {"recipient": PlayerState | Permanent, "amount": int, "source": Any | None,
     "combat": bool}

``combat`` marks the event as combat damage, which is the only thing a
"prevent all combat damage" shield may touch; every other shield ignores it.

Each returns the number of points it removes, or ``None`` to pass. The event
stops as soon as nothing is left to prevent, so a shield later in the order is
never consumed by damage an earlier one already absorbed — and a 0-damage event
consumes no shield at all (CR 614.7a).

Recipients are deliberately not split by type: ``Permanent`` and ``PlayerState``
both carry the shield collection, so the numeric shield of CR 615.7 is one
interceptor covering creatures and players alike. A shield whose additional
effect needs a player (Reverse Damage's life gain) guards on the recipient type
itself.

**Ordering (CR 616.1).** When several prevention and/or replacement effects
could apply to one event, the rules give the *affected* player the choice of
which to apply, and re-ask after each one (616.1f). That process lives in
``engine/effect_ordering.py`` and this registry runs through it: every shield
carries an ``applies`` predicate so the contenders can be counted before any of
them runs, and the orders in ``registry.py`` are the *default* choice a
non-interactive seat makes rather than a fixed cascade. Any single order is a
legal set of choices; only the aggregate outcome can differ, and only when one
recipient holds two applicable shields at once — a Circle of Protection and a
prevention pool, say, which this card pool reaches easily.

The shields are only *half* of a damage event's contenders: CR 616.1 does not
separate prevention from replacement, so the orders in ``registry.py`` share
one space with the damage entries in ``engine/replacements/`` and the union is
what actually runs. ``engine/damage_events.py`` is where the two are put
together, and it raises at import if the union ever collides. There is
deliberately no shields-only entry point here — a caller holding half a
contention set is the shape this pipeline exists to remove, and
``shield_candidates`` hands the halves over rather than running them.

This package was one 2,974-line module, ``prevention.py``, until the 2,000-line
cap's split round cut it on the line its own last section drew:

    registry   the order bands, ``@prevention_effect``, the candidates, and
               ``source_has_type`` (the floor both halves read)
    shields    the shields a recipient was **given** — armed by something that
               resolved, and spent: the directional marker, the collection read
               as CR 616.1's pure half, and every collection shield
    static     a permanent's **own** static prevention, read off its text at
               damage time, and ``prevention_claims_line``

Both interceptor modules register at import, so both are imported here: a name
pulled from any module of the package first runs this file, which is what keeps
the registry whole whichever module a caller reaches for.
"""

from .registry import (PREVENTION_EFFECTS, PreventionOutcome,
                       prevention_effect, shield_candidates, source_has_type,
                       spent)
from . import shields  # noqa: F401  (registers its shields)
from .static import prevention_claims_line

__all__ = [
    "PREVENTION_EFFECTS",
    "PreventionOutcome",
    "prevention_claims_line",
    "prevention_effect",
    "shield_candidates",
    "source_has_type",
    "spent",
]
