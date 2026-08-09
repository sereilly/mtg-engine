"""Damage-prevention registry (CR 615).

A prevention effect is a shield sitting on a player or a permanent that removes
points from a damage event before the damage is dealt (CR 615.1). Like
replacement effects (CR 614, ``engine/replacements.py``) each shield is a
registered interceptor that self-selects from game state, so supporting a new
kind of shield means registering a function — never editing a cascade.

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
both carry ``damage_prevention_pool``, so the numeric shield of CR 615.7 is one
interceptor covering creatures and players alike. Shields that only exist for
players guard on the recipient type themselves.

**Ordering (CR 616.1).** When several prevention and/or replacement effects
could apply to one event, the rules give the *affected* player the choice of
which to apply. This engine applies the fixed order below instead. Any single
order is a legal set of choices; only the aggregate outcome can differ, and only
when one recipient holds two applicable shields at once. The numbers reproduce
the order these shields were historically checked in, so the ordering question
is isolated here rather than spread across a cascade.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from .models import PlayerState

# Order bands. Blanket combat shields run first: they are flags rather than
# charges, so applying one costs the recipient nothing, and letting it go first
# keeps a consumable shield from being spent on damage that was never going to
# be dealt. Caps run before whole-event shields so a capped event can still be
# shielded outright; the numeric pool runs last so an all-or-nothing shield is
# spent before points are drawn from a pool that could cover later damage.
COMBAT_BLANKET = 10  # "Prevent all combat damage that would be dealt this turn"
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

PREVENTION_EFFECTS: list[tuple[int, Preventer]] = []


def prevention_effect(order: int) -> Callable[[Preventer], Preventer]:
    """Register a prevention interceptor at *order* (ascending).

    A duplicate order raises at import time, matching ``@parse_rule``: an
    ordering collision is a real ambiguity about which shield is consumed
    first, so it should surface at startup rather than as a rare misplay.
    """

    def decorator(fn: Preventer) -> Preventer:
        for existing_order, existing in PREVENTION_EFFECTS:
            if existing_order == order:
                raise ValueError(
                    f"prevention_effect order {order} already used by "
                    f"{existing.__name__}; pick a free slot"
                )
        PREVENTION_EFFECTS.append((order, fn))
        PREVENTION_EFFECTS.sort(key=lambda entry: entry[0])
        return fn

    return decorator


def apply_prevention(game, event: dict) -> int:
    """Run every prevention shield over *event*; return the unprevented damage.

    ``event["amount"]`` is kept in step as shields apply, so a later preventer
    sees what is actually left to prevent (CR 615.7's "any remaining damage is
    dealt normally").
    """
    amount = event["amount"]
    if amount <= 0:
        # No damage event, so no shield is consumed (CR 614.7a). Returned
        # unchanged rather than clamped: combat passes raw power here, which can
        # be negative for a creature shrunk below 0.
        return amount
    for _order, preventer in PREVENTION_EFFECTS:
        outcome = preventer(game, event)
        if outcome is None or outcome.prevented <= 0:
            continue
        amount = max(0, amount - outcome.prevented)
        event["amount"] = amount
        if amount <= 0:
            break
    return amount


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


def _clear_reverse_damage_badge(target: PlayerState) -> None:
    # Drop the life-pill shield badge once no Reverse Damage shield remains.
    if not target.reverse_damage_sources and target.reverse_damage_charges <= 0:
        target.damage_prevention_source = None


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
# Shields
# ---------------------------------------------------------------------------

@prevention_effect(COMBAT_BLANKET)
def _prevent_all_combat_damage(game, event: dict) -> PreventionOutcome | None:
    """Fog / Holy Day: "Prevent all combat damage that would be dealt this
    turn." A turn-wide flag rather than a shield, so it is never used up — and
    it applies only to combat damage, leaving spell and ability damage alone."""
    if not event.get("combat") or not game.combat_damage_prevented_until_eot:
        return None
    return PreventionOutcome(prevented=event["amount"])


@prevention_effect(COMBAT_SHIELD)
def _prevent_combat_damage_to_and_by(game, event: dict) -> PreventionOutcome | None:
    """Ebony Horse: "Prevent all combat damage that would be dealt to and dealt
    by that creature this turn." Both directions are one check here — the
    shielded creature may be either end of the event."""
    if not event.get("combat"):
        return None
    if not (combat_shielded(event["recipient"]) or combat_shielded(event.get("source"))):
        return None
    return PreventionOutcome(prevented=event["amount"])


@prevention_effect(SOURCE_CAP)
def _forcefield_chosen_attacker(game, event: dict) -> PreventionOutcome | None:
    """Forcefield: "The next time an unblocked creature of your choice would
    deal combat damage to you this turn, prevent all but 1 of that damage."
    The chosen attacker is consumed by the damage it caps."""
    recipient = event["recipient"]
    amount = event["amount"]
    source = event.get("source")
    if amount <= 1 or source is None or not isinstance(recipient, PlayerState):
        return None
    if source not in recipient.forcefield_capped_sources:
        return None
    recipient.forcefield_capped_sources.remove(source)
    return PreventionOutcome(prevented=amount - 1)


@prevention_effect(GENERIC_CAP)
def _forcefield_generic(game, event: dict) -> PreventionOutcome | None:
    """Forcefield activated without recording a chosen attacker (AI / headless):
    the next damage event from any source is capped to 1."""
    recipient = event["recipient"]
    amount = event["amount"]
    if amount <= 1 or not isinstance(recipient, PlayerState):
        return None
    if recipient.combat_damage_cap_one_charges <= 0:
        return None
    recipient.combat_damage_cap_one_charges -= 1
    return PreventionOutcome(prevented=amount - 1)


def _reverse_damage(game, recipient: PlayerState, amount: int) -> PreventionOutcome:
    # CR 615.5: the prevention happens first, then the rest of the effect —
    # here a life gain referring to the amount prevented.
    game.log.append(f"Reverse Damage prevented {amount} damage to {recipient.name}")
    game._gain_life(recipient, amount, source_name="Reverse Damage")
    return PreventionOutcome(prevented=amount)


@prevention_effect(SOURCE_SHIELD)
def _reverse_damage_chosen_source(game, event: dict) -> PreventionOutcome | None:
    """Reverse Damage: "The next time a source of your choice would deal damage
    to you this turn, prevent that damage. You gain life equal to the damage
    prevented this way." The whole instance is prevented regardless of its size
    (CR 615.8)."""
    recipient = event["recipient"]
    amount = event["amount"]
    if amount <= 0 or not isinstance(recipient, PlayerState):
        return None
    matched = game._match_chosen_damage_source(
        recipient.reverse_damage_sources, event.get("source")
    )
    if matched is None:
        return None
    recipient.reverse_damage_sources.remove(matched)
    _clear_reverse_damage_badge(recipient)
    return _reverse_damage(game, recipient, amount)


@prevention_effect(GENERIC_SHIELD)
def _reverse_damage_generic(game, event: dict) -> PreventionOutcome | None:
    """Reverse Damage cast without recording a chosen source (AI / headless):
    the next damage event from any source is prevented and gained as life."""
    recipient = event["recipient"]
    amount = event["amount"]
    if amount <= 0 or not isinstance(recipient, PlayerState):
        return None
    if recipient.reverse_damage_charges <= 0:
        return None
    recipient.reverse_damage_charges -= 1
    _clear_reverse_damage_badge(recipient)
    return _reverse_damage(game, recipient, amount)


@prevention_effect(COLOR_SHIELD)
def _circle_of_protection(game, event: dict) -> PreventionOutcome | None:
    """Circle of Protection: "The next time a <color> source of your choice
    would deal damage to you this turn, prevent that damage." One shield per
    activation, matched against the source's colors at damage time (CR 615.9)
    and prevented in full."""
    recipient = event["recipient"]
    amount = event["amount"]
    if amount <= 0 or not isinstance(recipient, PlayerState):
        return None
    if not recipient.color_prevention_shields:
        return None
    for color in source_colors(event.get("source")):
        if color not in recipient.color_prevention_shields:
            continue
        recipient.color_prevention_shields.remove(color)
        if not recipient.color_prevention_shields:
            recipient.damage_prevention_color = None
            recipient.damage_prevention_source = None
        game.log.append(
            f"Circle of Protection prevented {amount} damage to {recipient.name} "
            f"from a {color} source"
        )
        return PreventionOutcome(prevented=amount)
    return None


@prevention_effect(POOL)
def _prevention_pool(game, event: dict) -> PreventionOutcome | None:
    """"Prevent the next N damage that would be dealt to <recipient> this turn"
    (Healing Salve's prevention mode, Samite Healer, Rock Hydra, …). Each point
    prevented reduces the shield by 1; the remainder is dealt normally
    (CR 615.7). The one shield that protects creatures as well as players."""
    recipient = event["recipient"]
    amount = event["amount"]
    if amount <= 0 or recipient.damage_prevention_pool <= 0:
        return None
    prevented = min(amount, recipient.damage_prevention_pool)
    recipient.damage_prevention_pool -= prevented
    if recipient.damage_prevention_pool <= 0:
        recipient.damage_prevention_source = None
    if not isinstance(recipient, PlayerState):
        game.log.append(f"Prevented {prevented} damage to {recipient.card.name}")
    return PreventionOutcome(prevented=prevented)
