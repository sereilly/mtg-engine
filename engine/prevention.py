"""Damage-prevention registry (CR 615).

A prevention effect is a shield sitting on a player or a permanent that removes
points from a damage event before the damage is dealt (CR 615.1). Like
replacement effects (CR 614, ``engine/replacements.py``) each shield is a
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
them runs, and the orders below are the *default* choice a non-interactive seat
makes rather than a fixed cascade. Any single order is a legal set of choices;
only the aggregate outcome can differ, and only when one recipient holds two
applicable shields at once — a Circle of Protection and a prevention pool, say,
which this card pool reaches easily.

The shields are only *half* of a damage event's contenders: CR 616.1 does not
separate prevention from replacement, so the orders below share one space with
the damage entries in ``engine/replacements.py`` and the union is what actually
runs. ``engine/damage_events.py`` is where the two are put together, and it
raises at import if the union ever collides. There is deliberately no
shields-only entry point here — a caller holding half a contention set is the
shape this pipeline exists to remove, and ``shield_candidates`` hands the halves
over rather than running them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from .effect_ordering import Candidate
from .models import PlayerState
from .shields import (
    PREVENT_ALL_BUT,
    PREVENT_AND_GAIN_LIFE,
    PREVENT_FROM_COLOR,
    PREVENT_NEXT_N,
    Shield,
    drop_spent,
    shields_on,
)

# Order bands. Blanket combat shields run first: they are flags rather than
# charges, so applying one costs the recipient nothing, and letting it go first
# keeps a consumable shield from being spent on damage that was never going to
# be dealt. Caps run before whole-event shields so a capped event can still be
# shielded outright; the numeric pool runs last so an all-or-nothing shield is
# spent before points are drawn from a pool that could cover later damage.
COMBAT_BLANKET = 10  # "Prevent all combat damage that would be dealt this turn"
# The same blanket narrowed to a printed noun phrase (Pack Leader). Beside the
# unscoped one and before every consumable shield, for the same reason: it has
# no charges, so applying it costs its recipient nothing.
COMBAT_BLANKET_SCOPED = 11
COMBAT_SHIELD = 20  # "…dealt to and dealt by that creature this turn"
SOURCE_CAP = 100  # Forcefield against a chosen attacker
GENERIC_CAP = 200  # Forcefield with no chosen attacker
SOURCE_SHIELD = 300  # Reverse Damage against a chosen source
GENERIC_SHIELD = 400  # Reverse Damage with no chosen source
COLOR_SHIELD = 500  # Circle of Protection
POOL = 600  # "Prevent the next N damage" (CR 615.7)


@dataclass
class PreventionOutcome:
    """Points this shield removes from the event. 0 means the shield looked but
    did not apply, which is indistinguishable from passing."""

    prevented: int = 0


Preventer = Callable[[Any, dict], Optional[PreventionOutcome]]
Applicability = Callable[[Any, dict], bool]

PREVENTION_EFFECTS: list[Candidate] = []


def prevention_effect(order: int, *, applies: Applicability) -> Callable[[Preventer], Preventer]:
    """Register a prevention interceptor at *order* (ascending).

    ``applies`` is the shield's guard — "would this shield apply to this
    event?" — and it is **required**, because CR 616.1 has to count the effects
    in contention before running any of them. It must be pure: a predicate that
    consumed a charge would spend shields the player never chose.

    A duplicate order raises at import time, matching ``@parse_rule``: with the
    default choice being the lowest order, a collision is a real ambiguity about
    which shield is consumed first, so it should surface at startup rather than
    as a rare misplay.
    """

    def decorator(fn: Preventer) -> Preventer:
        for existing in PREVENTION_EFFECTS:
            if existing.order == order:
                raise ValueError(
                    f"prevention_effect order {order} already used by "
                    f"{existing.key}; pick a free slot"
                )
        PREVENTION_EFFECTS.append(
            Candidate(key=fn.__name__, order=order, applies=applies, apply=fn,
                      label=(fn.__doc__ or fn.__name__).split(":")[0].strip())
        )
        PREVENTION_EFFECTS.sort(key=lambda candidate: candidate.order)
        return fn

    return decorator


def spent(game, event: dict) -> bool:
    """Nothing left to prevent, so nothing more can apply (CR 615.7's "any
    remaining damage is dealt normally")."""
    return event["amount"] <= 0


def _consume(game, event: dict, preventer: Preventer) -> None:
    """Apply one shield and keep ``event["amount"]`` in step, so the next round
    of CR 616.1f asks the remaining shields about what is actually left."""
    outcome = preventer(game, event)
    if outcome is not None and outcome.prevented > 0:
        event["amount"] = max(0, event["amount"] - outcome.prevented)


def shield_candidates() -> list[Candidate]:
    """Every shield as a CR 616.1 candidate, with the amount bookkeeping already
    wired into ``apply``.

    Exposed rather than kept private because a damage event's contenders are the
    shields *and* the replacements, and whoever unions the two must not have to
    re-implement what applying a shield does to the event.
    """
    return [
        Candidate(
            key=c.key, order=c.order, applies=c.applies, label=c.label,
            apply=lambda g, e, fn=c.apply: _consume(g, e, fn),
        )
        for c in PREVENTION_EFFECTS
    ]


# ---------------------------------------------------------------------------
# Source matching
# ---------------------------------------------------------------------------

def source_colors(source) -> tuple[str, ...]:
    """Color symbols of a damage source — a Permanent (honoring a color
    override), a CardDefinition (spell), or None."""
    if source is None:
        return ()
    meta = getattr(source, "metadata", None)
    if isinstance(meta, dict) and meta.get("color_override"):
        return (str(meta["color_override"]),)
    card = getattr(source, "card", source)
    return tuple(getattr(card, "colors", ()) or ())


# Ebony Horse: "Prevent all combat damage that would be dealt to and dealt by
# that creature this turn." — a per-creature marker set by the
# untap_attacker_and_prevent_combat_damage handler, cleared in cleanup.
_COMBAT_SHIELD_KEY = "prevent_combat_damage_to_and_by_until_eot"


def combat_shielded(perm) -> bool:
    """Whether *perm* carries a "prevent all combat damage to and by this
    creature" shield. Accepts None and non-permanent damage sources (a spell's
    CardDefinition), which never carry one."""
    metadata = getattr(perm, "metadata", None)
    return bool(metadata) and bool(metadata.get(_COMBAT_SHIELD_KEY))


# ---------------------------------------------------------------------------
# Reading the collection (CR 616.1's pure half)
# ---------------------------------------------------------------------------
#
# "Does this shield apply?" is separated from "apply it", because 616.1 has to
# know how many effects are in contention *before* any of them runs. The guard
# each shield used to open with *moved* here rather than being copied, so the
# shield body starts after the decision and the two cannot drift. Predicates are
# pure: none of them spends a charge, since a shield that is asked about may
# then not be chosen — ``Shield.would_prevent`` computes, ``Shield.spend``
# mutates, and only the second is reachable from an ``apply``.


def _source_matches(game, shield: Shield, source) -> bool:
    """Whether *shield* answers damage from *source*.

    Two independent narrowings, both rechecked at damage time rather than
    locked in when the shield was armed (CR 615.9): the chosen source of
    CR 615.8, matched the way every other chosen-source effect in the engine
    matches one, and the source *property* a Circle of Protection names. A
    shield recording neither answers to any source.
    """
    if shield.source is not None:
        if game._match_chosen_damage_source([shield.source], source) is None:
            return False
    if shield.color is not None and shield.color not in source_colors(source):
        return False
    return True


def _live(game, event: dict, kind: str, *, chosen: bool | None = None):
    """Shields of *kind* on the event's recipient that could modify this event.

    *chosen* selects one half of the order space: True for shields naming a
    source, False for the "any source" fallback an AI or headless activation
    arms. They are separate registrations because they take separate default
    orders, and CR 616.1e's default is rules-visible.
    """
    recipient = event["recipient"]
    amount = event["amount"]
    for shield in shields_on(recipient):
        if shield.kind != kind or shield.spent:
            continue
        if chosen is not None and (shield.source is not None) != chosen:
            continue
        if not _source_matches(game, shield, event.get("source")):
            continue
        if shield.would_prevent(amount) <= 0:
            continue
        yield shield


def _arms(kind: str, *, chosen: bool | None = None, player_only: bool = False) -> Applicability:
    """The applicability predicate for a shield of *kind*: is one armed that
    would remove at least a point from this event?

    "Would remove a point" rather than merely "is armed" is the deliberate
    reading, and it is the one place this differs from Aladdin's Lamp — see
    ``_forcefield_chosen_attacker``, which is the shield it could bite.
    """

    def applies(game, event: dict) -> bool:
        if player_only and not isinstance(event["recipient"], PlayerState):
            return False
        return next(_live(game, event, kind, chosen=chosen), None) is not None

    return applies


def _spend(game, event: dict, kind: str, *, chosen: bool | None = None, rider=None):
    """Apply the recipient's shields of *kind* to this event.

    Draining every matching shield rather than one is what keeps CR 615.7's
    "such effects count only the amount of damage" true when a recipient holds
    two numeric pools: the pair behaves as the single total the old integer
    field held. A whole-instance shield takes the event to 0 on its first
    application and the loop stops there, so exactly one is consumed.

    *rider* is CR 615.5's "additional effect, which may refer to the amount of
    damage that was prevented" — run after the prevention, with the shields that
    did it, never before.
    """
    remaining = event["amount"]
    prevented = 0
    used: list[Shield] = []
    for shield in list(_live(game, event, kind, chosen=chosen)):
        take = shield.would_prevent(remaining)
        if take <= 0:
            continue
        shield.spend(take)
        used.append(shield)
        prevented += take
        remaining -= take
        if remaining <= 0:
            break
    drop_spent(event["recipient"])
    if rider is not None and prevented > 0:
        rider(game, event, used, prevented)
    return PreventionOutcome(prevented=prevented)


def _applies_all_combat(game, event: dict) -> bool:
    return bool(event.get("combat")) and game.combat_damage_prevented_until_eot


def _applies_scoped_combat(game, event: dict) -> bool:
    """Whether an armed "…to <noun phrase>" prevention covers this event.

    The noun phrase is matched **now**, not when the effect resolved (CR 611.2c
    fixes a set only where the effect says so, and "Dogs you control" does not):
    a Dog that entered after Pack Leader attacked is still a Dog its controller
    controls when the damage would be dealt.
    """
    if not event.get("combat"):
        return False
    recipient = event.get("recipient")
    if recipient is None or not hasattr(recipient, "card"):
        # A player is not a "Dog you control". Only permanents are scoped.
        return False
    from .subject_filters import subject_matches

    for entry in getattr(game, "combat_damage_prevented_for", ()) or ():
        seat = entry.get("seat")
        if subject_matches(game, recipient, entry.get("filter") or {}, observer=seat):
            return True
    return False


def _applies_combat_to_and_by(game, event: dict) -> bool:
    return bool(event.get("combat")) and (
        combat_shielded(event["recipient"]) or combat_shielded(event.get("source"))
    )


# ---------------------------------------------------------------------------
# Shields
# ---------------------------------------------------------------------------
#
# The first two are turn-wide flags rather than shields a recipient holds, which
# is why they read a game flag and a permanent's marker instead of the
# collection: nothing is consumed, so there is no charge, no lifetime and no
# remaining-uses bookkeeping for a Shield to carry. Ebony Horse's also has to be
# readable off the damage's *source* ("dealt to and dealt by"), which a
# recipient-keyed collection cannot express.

@prevention_effect(COMBAT_BLANKET, applies=_applies_all_combat)
def _prevent_all_combat_damage(game, event: dict) -> PreventionOutcome | None:
    """Fog / Holy Day: "Prevent all combat damage that would be dealt this
    turn." A turn-wide flag rather than a shield, so it is never used up — and
    it applies only to combat damage, leaving spell and ability damage alone."""
    return PreventionOutcome(prevented=event["amount"])


@prevention_effect(COMBAT_BLANKET_SCOPED, applies=_applies_scoped_combat)
def _prevent_scoped_combat_damage(game, event: dict) -> PreventionOutcome | None:
    """Pack Leader: "Prevent all combat damage that would be dealt this turn to
    Dogs you control." A turn-wide record like the blanket above rather than a
    shield each Dog holds, so it is never used up and it covers Dogs that were
    not on the battlefield when it resolved."""
    return PreventionOutcome(prevented=event["amount"])


@prevention_effect(COMBAT_SHIELD, applies=_applies_combat_to_and_by)
def _prevent_combat_damage_to_and_by(game, event: dict) -> PreventionOutcome | None:
    """Ebony Horse: "Prevent all combat damage that would be dealt to and dealt
    by that creature this turn." Both directions are one check here — the
    shielded creature may be either end of the event."""
    return PreventionOutcome(prevented=event["amount"])


@prevention_effect(SOURCE_CAP, applies=_arms(PREVENT_ALL_BUT, chosen=True))
def _forcefield_chosen_attacker(game, event: dict) -> PreventionOutcome | None:
    """Forcefield: "The next time an unblocked creature of your choice would
    deal combat damage to you this turn, prevent all but 1 of that damage."
    The chosen attacker is consumed by the damage it caps.

    A shield that would prevent nothing does not apply, so a chosen attacker
    dealing exactly 1 leaves it armed. That is the one place this pool's shields
    could have taken Aladdin's Lamp's shape instead — a charge spent even when
    it does nothing (CR 614.1) — and CR 615.8 arguably says they should. It is
    left as it was rather than changed under cover of a refactor; see
    ROADMAP.md's phase 5 entry."""
    return _spend(game, event, PREVENT_ALL_BUT, chosen=True)


@prevention_effect(GENERIC_CAP, applies=_arms(PREVENT_ALL_BUT, chosen=False))
def _forcefield_generic(game, event: dict) -> PreventionOutcome | None:
    """Forcefield activated without recording a chosen attacker (AI / headless):
    the next damage event from any source is capped to 1."""
    return _spend(game, event, PREVENT_ALL_BUT, chosen=False)


def _gain_prevented_life(game, event: dict, used: list[Shield], prevented: int) -> None:
    # CR 615.5: the prevention happens first, then the rest of the effect —
    # here a life gain referring to the amount prevented.
    recipient = event["recipient"]
    game.log.append(f"Reverse Damage prevented {prevented} damage to {recipient.name}")
    game._gain_life(recipient, prevented, source_name="Reverse Damage")


@prevention_effect(
    SOURCE_SHIELD, applies=_arms(PREVENT_AND_GAIN_LIFE, chosen=True, player_only=True)
)
def _reverse_damage_chosen_source(game, event: dict) -> PreventionOutcome | None:
    """Reverse Damage: "The next time a source of your choice would deal damage
    to you this turn, prevent that damage. You gain life equal to the damage
    prevented this way." The whole instance is prevented regardless of its size
    (CR 615.8)."""
    return _spend(game, event, PREVENT_AND_GAIN_LIFE, chosen=True, rider=_gain_prevented_life)


@prevention_effect(
    GENERIC_SHIELD, applies=_arms(PREVENT_AND_GAIN_LIFE, chosen=False, player_only=True)
)
def _reverse_damage_generic(game, event: dict) -> PreventionOutcome | None:
    """Reverse Damage cast without recording a chosen source (AI / headless):
    the next damage event from any source is prevented and gained as life."""
    return _spend(game, event, PREVENT_AND_GAIN_LIFE, chosen=False, rider=_gain_prevented_life)


def _log_color_prevention(game, event: dict, used: list[Shield], prevented: int) -> None:
    game.log.append(
        f"Circle of Protection prevented {prevented} damage to "
        f"{event['recipient'].name} from a {used[0].color} source"
    )


@prevention_effect(COLOR_SHIELD, applies=_arms(PREVENT_FROM_COLOR, player_only=True))
def _circle_of_protection(game, event: dict) -> PreventionOutcome | None:
    """Circle of Protection: "The next time a <color> source of your choice
    would deal damage to you this turn, prevent that damage." One shield per
    activation, matched against the source's colors at damage time (CR 615.9)
    and prevented in full."""
    return _spend(game, event, PREVENT_FROM_COLOR, rider=_log_color_prevention)


def _log_pool_prevention(game, event: dict, used: list[Shield], prevented: int) -> None:
    recipient = event["recipient"]
    if not isinstance(recipient, PlayerState):
        game.log.append(f"Prevented {prevented} damage to {recipient.card.name}")


@prevention_effect(POOL, applies=_arms(PREVENT_NEXT_N))
def _prevention_pool(game, event: dict) -> PreventionOutcome | None:
    """"Prevent the next N damage that would be dealt to <recipient> this turn"
    (Healing Salve's prevention mode, Samite Healer, Rock Hydra, …). Each point
    prevented reduces the shield by 1; the remainder is dealt normally
    (CR 615.7). The one shield that protects creatures as well as players."""
    return _spend(game, event, PREVENT_NEXT_N, rider=_log_pool_prevention)
