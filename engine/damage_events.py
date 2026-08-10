"""One damage event, one contention set (CR 616.1).

CR 616.1 does not distinguish replacement effects from prevention effects when
it decides what happens to an event. It says: gather every replacement *and*
prevention effect that would apply, let the affected player choose one, apply
it, and repeat over what is still applicable. Two registries implement those
effects here — ``engine/replacements.py`` and ``engine/prevention.py`` — and
this module is the one place a damage event's members of both are put together
into the single list the rule describes.

Before this existed they were two passes with a fixed order between them, which
had two consequences worth naming, because they are the bugs this module
removes rather than merely tidies:

- **616.1f only re-checked within a pass.** A shield applying could not make a
  replacement stop applying, or the reverse, because by the time the second pass
  ran the first had already finished. The re-ask now spans both.
- **The contender count was wrong.** "How many effects are attempting to modify
  this event" is the question the eventual prompt hangs off, and answering it
  from one registry at a time can only ever undercount.

**Order.** The two registries share one order space for damage, so the default
choice is still a total order and still exactly reproduces what the two passes
used to do. Which side goes first genuinely differs by recipient, and both
answers are reasoned (see the order block in ``replacements.py``): damage to a
permanent is redirected before it is shielded, damage to a player is shielded
before it is floored. ``_assert_one_order_space`` below makes a collision
between the registries an import-time failure rather than a silent tie broken by
list order.

**What still runs half an event.** Combat damage to a player applies its shields
when the event is *recorded*, so that lifelink and the recorded amount agree on
the number, and its replacements when life is actually applied, so that a second
attacker's floor sees what the first one left. Those are two different moments,
so that path calls ``apply_prevention`` and ``apply_replacements`` separately and
says so at both sites. Making it one contention set means making a damage event
suspendable, which is the same missing piece that stops the 616.1 choice from
being *asked* at all (see ``effect_ordering.choose_effect``).
"""

from __future__ import annotations

from .effect_ordering import Candidate, affected_seat, apply_in_order
from .models import PlayerState
from .prevention import shield_candidates, spent
from .replacements import replacement_candidates, take_replaced, was_replaced

# The replacement kinds keyed by what the damage is being dealt to. Prevention
# has no such split — one shield registry covers both recipients — so this is
# the only place the two halves need lining up.
DAMAGE_KINDS = ("damage_to_player", "damage_to_creature")


def damage_kind(recipient) -> str:
    """Which replacement kind an event with this recipient belongs to."""
    return "damage_to_player" if isinstance(recipient, PlayerState) else "damage_to_creature"


def damage_candidates(recipient) -> list[Candidate]:
    """Every effect attempting to modify a damage event with this recipient —
    shields and replacements together, in default order."""
    return sorted(
        shield_candidates() + replacement_candidates(damage_kind(recipient)),
        key=lambda candidate: candidate.order,
    )


def _settled(game, event: dict) -> bool:
    """The event has been consumed, or has nothing left to modify. Either way
    no further effect can apply to it (CR 615.7, CR 614.6)."""
    return was_replaced(game, event) or spent(game, event)


def modify_damage(game, event: dict) -> tuple[bool, int]:
    """Run CR 616.1 over a damage event.

    *event* is ``{recipient, amount, source, combat}``. Returns
    ``(consumed, amount)``: ``consumed`` means a replacement took the event
    entirely and the damage must not be dealt at all; otherwise ``amount`` is
    what is left after every effect that applied.

    A 0-or-less event modifies nothing and consumes nothing (CR 614.7a), and its
    amount comes back unchanged rather than clamped — combat passes raw power
    here, which can be negative for a creature shrunk below 0.
    """
    if event["amount"] <= 0:
        return False, event["amount"]
    apply_in_order(
        game,
        event,
        damage_candidates(event["recipient"]),
        chooser_index=affected_seat(game, event["recipient"]),
        stop=_settled,
    )
    return take_replaced(event), event["amount"]


def _assert_one_order_space() -> None:
    """A shield and a replacement sharing an order is an ambiguity about which
    modifies a damage event first, which is rules-visible. Both registries
    already reject a duplicate within themselves; this is the check neither can
    make alone, and it runs at import for the same reason theirs do.
    """
    for kind in DAMAGE_KINDS:
        seen: dict[int, str] = {}
        for candidate in shield_candidates() + replacement_candidates(kind):
            clash = seen.get(candidate.order)
            if clash is not None:
                raise ValueError(
                    f"{kind} order {candidate.order} is used by both {clash} and "
                    f"{candidate.key}; a damage event's shields and replacements "
                    f"share one order space (see engine/damage_events.py)"
                )
            seen[candidate.order] = candidate.key


_assert_one_order_space()
