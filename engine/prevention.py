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
which to apply, and re-ask after each one (616.1f). That process lives in
``engine/effect_ordering.py`` and this registry runs through it: every shield
carries an ``applies`` predicate so the contenders can be counted before any of
them runs, and the orders below are the *default* choice a non-interactive seat
makes rather than a fixed cascade. Any single order is a legal set of choices;
only the aggregate outcome can differ, and only when one recipient holds two
applicable shields at once — a Circle of Protection and a prevention pool, say,
which this card pool reaches easily.

Two things are deliberately not done here. The choice is not *asked*: a damage
event cannot currently suspend (see ``effect_ordering.choose_effect``). And
replacement effects are still a separate pass, so a damage event's replacements
and its shields are two contention sets rather than the one CR 616.1 describes —
closing that needs the same ``applies`` split on ``engine/replacements.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from .effect_ordering import Candidate, apply_in_order
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


def _spent(game, event: dict) -> bool:
    """Nothing left to prevent, so nothing more can apply (CR 615.7's "any
    remaining damage is dealt normally")."""
    return event["amount"] <= 0


def _consume(game, event: dict, preventer: Preventer) -> None:
    """Apply one shield and keep ``event["amount"]`` in step, so the next round
    of CR 616.1f asks the remaining shields about what is actually left."""
    outcome = preventer(game, event)
    if outcome is not None and outcome.prevented > 0:
        event["amount"] = max(0, event["amount"] - outcome.prevented)


def apply_prevention(game, event: dict) -> int:
    """Run the prevention shields over *event*; return the unprevented damage.

    Shields are applied in CR 616.1 order — every applicable one is gathered,
    one is chosen (the affected player's choice; the default is the documented
    order above), it is applied, and the rest are re-asked against the reduced
    amount. That last step is 616.1f, and it is why this is a loop rather than
    a single pass: a shield that applied to 5 damage may not apply to the 1
    left after another shield ran.
    """
    if event["amount"] <= 0:
        # No damage event, so no shield is consumed (CR 614.7a). Returned
        # unchanged rather than clamped: combat passes raw power here, which can
        # be negative for a creature shrunk below 0.
        return event["amount"]
    recipient = event["recipient"]
    apply_in_order(
        game,
        event,
        [
            Candidate(
                key=c.key, order=c.order, applies=c.applies, label=c.label,
                apply=lambda g, e, fn=c.apply: _consume(g, e, fn),
            )
            for c in PREVENTION_EFFECTS
        ],
        chooser_index=_recipient_seat(game, recipient),
        stop=_spent,
    )
    return event["amount"]


def _recipient_seat(game, recipient) -> int | None:
    """The seat CR 616.1 gives the choice to: the affected player, or the
    affected permanent's controller."""
    if isinstance(recipient, PlayerState):
        return next((i for i, p in enumerate(game.players) if p is recipient), None)
    return next(
        (i for i, p in enumerate(game.players)
         if any(perm is recipient for perm in p.battlefield)),
        None,
    )


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
# Applicability (CR 616.1)
# ---------------------------------------------------------------------------
#
# "Does this shield apply?" separated from "apply it", because 616.1 has to know
# how many effects are in contention *before* any of them runs. Each predicate
# below is the guard its shield used to open with — moved, not copied, so the
# shield body starts after the decision and the two cannot drift. Predicates are
# pure: none of them consumes a charge, since a shield that is asked about may
# then not be chosen.


def _player_event(event: dict) -> bool:
    """Shields that exist only for players. A creature is covered by the
    numeric pool and the blanket combat shields, nothing else here."""
    return event["amount"] > 0 and isinstance(event["recipient"], PlayerState)


def _applies_all_combat(game, event: dict) -> bool:
    return bool(event.get("combat")) and game.combat_damage_prevented_until_eot


def _applies_combat_to_and_by(game, event: dict) -> bool:
    return bool(event.get("combat")) and (
        combat_shielded(event["recipient"]) or combat_shielded(event.get("source"))
    )


def _applies_forcefield_chosen(game, event: dict) -> bool:
    source = event.get("source")
    return (
        event["amount"] > 1
        and source is not None
        and isinstance(event["recipient"], PlayerState)
        and source in event["recipient"].forcefield_capped_sources
    )


def _applies_forcefield_generic(game, event: dict) -> bool:
    return (
        event["amount"] > 1
        and isinstance(event["recipient"], PlayerState)
        and event["recipient"].combat_damage_cap_one_charges > 0
    )


def _applies_reverse_chosen(game, event: dict) -> bool:
    if not _player_event(event):
        return False
    return game._match_chosen_damage_source(
        event["recipient"].reverse_damage_sources, event.get("source")
    ) is not None


def _applies_reverse_generic(game, event: dict) -> bool:
    return _player_event(event) and event["recipient"].reverse_damage_charges > 0


def _matching_cop_color(event: dict) -> str | None:
    """The colour shield this source trips, if any — shared by the predicate
    and the shield so "which colour applies" has one answer."""
    recipient = event["recipient"]
    if not recipient.color_prevention_shields:
        return None
    return next(
        (c for c in source_colors(event.get("source")) if c in recipient.color_prevention_shields),
        None,
    )


def _applies_circle_of_protection(game, event: dict) -> bool:
    return _player_event(event) and _matching_cop_color(event) is not None


def _applies_pool(game, event: dict) -> bool:
    return event["amount"] > 0 and event["recipient"].damage_prevention_pool > 0


# ---------------------------------------------------------------------------
# Shields
# ---------------------------------------------------------------------------

@prevention_effect(COMBAT_BLANKET, applies=_applies_all_combat)
def _prevent_all_combat_damage(game, event: dict) -> PreventionOutcome | None:
    """Fog / Holy Day: "Prevent all combat damage that would be dealt this
    turn." A turn-wide flag rather than a shield, so it is never used up — and
    it applies only to combat damage, leaving spell and ability damage alone."""
    return PreventionOutcome(prevented=event["amount"])


@prevention_effect(COMBAT_SHIELD, applies=_applies_combat_to_and_by)
def _prevent_combat_damage_to_and_by(game, event: dict) -> PreventionOutcome | None:
    """Ebony Horse: "Prevent all combat damage that would be dealt to and dealt
    by that creature this turn." Both directions are one check here — the
    shielded creature may be either end of the event."""
    return PreventionOutcome(prevented=event["amount"])


@prevention_effect(SOURCE_CAP, applies=_applies_forcefield_chosen)
def _forcefield_chosen_attacker(game, event: dict) -> PreventionOutcome | None:
    """Forcefield: "The next time an unblocked creature of your choice would
    deal combat damage to you this turn, prevent all but 1 of that damage."
    The chosen attacker is consumed by the damage it caps."""
    recipient = event["recipient"]
    amount = event["amount"]
    recipient.forcefield_capped_sources.remove(event["source"])
    return PreventionOutcome(prevented=amount - 1)


@prevention_effect(GENERIC_CAP, applies=_applies_forcefield_generic)
def _forcefield_generic(game, event: dict) -> PreventionOutcome | None:
    """Forcefield activated without recording a chosen attacker (AI / headless):
    the next damage event from any source is capped to 1."""
    recipient = event["recipient"]
    amount = event["amount"]
    recipient.combat_damage_cap_one_charges -= 1
    return PreventionOutcome(prevented=amount - 1)


def _reverse_damage(game, recipient: PlayerState, amount: int) -> PreventionOutcome:
    # CR 615.5: the prevention happens first, then the rest of the effect —
    # here a life gain referring to the amount prevented.
    game.log.append(f"Reverse Damage prevented {amount} damage to {recipient.name}")
    game._gain_life(recipient, amount, source_name="Reverse Damage")
    return PreventionOutcome(prevented=amount)


@prevention_effect(SOURCE_SHIELD, applies=_applies_reverse_chosen)
def _reverse_damage_chosen_source(game, event: dict) -> PreventionOutcome | None:
    """Reverse Damage: "The next time a source of your choice would deal damage
    to you this turn, prevent that damage. You gain life equal to the damage
    prevented this way." The whole instance is prevented regardless of its size
    (CR 615.8)."""
    recipient = event["recipient"]
    amount = event["amount"]
    matched = game._match_chosen_damage_source(
        recipient.reverse_damage_sources, event.get("source")
    )
    recipient.reverse_damage_sources.remove(matched)
    _clear_reverse_damage_badge(recipient)
    return _reverse_damage(game, recipient, amount)


@prevention_effect(GENERIC_SHIELD, applies=_applies_reverse_generic)
def _reverse_damage_generic(game, event: dict) -> PreventionOutcome | None:
    """Reverse Damage cast without recording a chosen source (AI / headless):
    the next damage event from any source is prevented and gained as life."""
    recipient = event["recipient"]
    amount = event["amount"]
    recipient.reverse_damage_charges -= 1
    _clear_reverse_damage_badge(recipient)
    return _reverse_damage(game, recipient, amount)


@prevention_effect(COLOR_SHIELD, applies=_applies_circle_of_protection)
def _circle_of_protection(game, event: dict) -> PreventionOutcome | None:
    """Circle of Protection: "The next time a <color> source of your choice
    would deal damage to you this turn, prevent that damage." One shield per
    activation, matched against the source's colors at damage time (CR 615.9)
    and prevented in full."""
    recipient = event["recipient"]
    amount = event["amount"]
    color = _matching_cop_color(event)
    recipient.color_prevention_shields.remove(color)
    if not recipient.color_prevention_shields:
        recipient.damage_prevention_color = None
        recipient.damage_prevention_source = None
    game.log.append(
        f"Circle of Protection prevented {amount} damage to {recipient.name} "
        f"from a {color} source"
    )
    return PreventionOutcome(prevented=amount)


@prevention_effect(POOL, applies=_applies_pool)
def _prevention_pool(game, event: dict) -> PreventionOutcome | None:
    """"Prevent the next N damage that would be dealt to <recipient> this turn"
    (Healing Salve's prevention mode, Samite Healer, Rock Hydra, …). Each point
    prevented reduces the shield by 1; the remainder is dealt normally
    (CR 615.7). The one shield that protects creatures as well as players."""
    recipient = event["recipient"]
    amount = event["amount"]
    prevented = min(amount, recipient.damage_prevention_pool)
    recipient.damage_prevention_pool -= prevented
    if recipient.damage_prevention_pool <= 0:
        recipient.damage_prevention_source = None
    if not isinstance(recipient, PlayerState):
        game.log.append(f"Prevented {prevented} damage to {recipient.card.name}")
    return PreventionOutcome(prevented=prevented)
