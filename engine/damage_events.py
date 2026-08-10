"""One damage event, start to finish (CR 120.4, CR 616.1).

A damage event is not one decision, it is two, and the engine spent a long time
treating it as one number. CR 120.4 sets out the sequence:

- **120.4b — the damage is dealt**, as modified by the replacement and prevention
  effects that interact with *damage*: shields absorb points, redirects send the
  event somewhere else. Abilities that trigger on damage being dealt trigger on
  what comes out of this half.
- **120.4c — the damage that was dealt is processed into its results**, as
  modified by the replacement effects that interact with *those results*: life
  lost for a player, damage marked for a creature.

Within each half, CR 616.1 chooses: gather every applicable effect, apply one,
re-ask the rest (616.1f). ``engine/effect_ordering.py`` is that process; this
module supplies each half's candidates and runs them in order.

**Why the split earns its keep.** Ali from Cairo ("damage that would reduce your
life total to less than 1 reduces it to 1 instead") is a 120.4c effect, so the
damage is *dealt* in full — lifelink gains the full amount (CR 120.3f) and a
"whenever ~ deals damage to a player" trigger sees the full amount — and only
the life loss is capped. One number cannot carry both answers. That is why the
combat damage step used to apply its shields where the event was recorded (so
lifelink saw the right number) and its replacements where life was applied (so
the floor read the right life total): not two moments by necessity, but one
moment missing a second number. With :class:`DamageOutcome` carrying both, every
damage path runs the whole event in one place.

**Order.** In the 120.4b half the two registries share one order space, so the
default choice is a total order across shields and replacements alike;
``_assert_one_order_space`` makes a collision between them an import-time
failure rather than a tie broken by list order. The 120.4c half has a space of
its own — no shield lives there, because prevention stops damage being dealt and
by 120.4c it already has been.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .effect_ordering import Candidate, affected_seat, apply_in_order
from .models import PlayerState
from .prevention import shield_candidates, spent
from .replacements import (
    apply_replacements,
    order_prompt_asker,
    replacement_candidates,
    take_replaced,
    was_replaced,
)


@dataclass(frozen=True)
class DamageOutcome:
    """What one damage event did, in CR 120.4's two parts.

    consumed -- a replacement took the event whole; no damage was dealt at all
                and nothing downstream should treat this as a damage event
                (CR 120.8)
    dealt    -- damage actually dealt (CR 120.4b). What lifelink (CR 120.3f),
                "whenever ~ deals damage" triggers, and every caller asking "how
                much did that do" should read.
    result   -- how much of it lands as its result (CR 120.4c): life lost for a
                player, damage marked for a creature. Equal to ``dealt`` unless a
                result-replacement capped it — Ali from Cairo is the one card in
                this pool that separates the two.
    """

    consumed: bool
    dealt: int
    result: int
    #: The event stopped to ask the affected player which effect applies first
    #: (CR 616.1e). **Nothing happened** — no shield spent, no damage dealt, no
    #: trigger fired. The caller must do nothing at all with this outcome; the
    #: answer re-runs the whole event, consequences included.
    suspended: bool = False


# The replacement kinds a damage event passes through, by what it is dealt to.
# Prevention has no such split — one shield registry covers both recipients —
# so this is the only place the halves need lining up.
DAMAGE_KINDS = ("damage_to_player", "damage_to_creature")
RESULT_KINDS = {"damage_to_player": "life_loss", "damage_to_creature": "damage_marked"}


def damage_kind(recipient) -> str:
    """Which CR 120.4b kind an event with this recipient belongs to."""
    return "damage_to_player" if isinstance(recipient, PlayerState) else "damage_to_creature"


def damage_candidates(recipient) -> list[Candidate]:
    """Every effect attempting to modify a damage event with this recipient
    before it is dealt (CR 120.4b) — shields and replacements together, in
    default order."""
    return sorted(
        shield_candidates() + replacement_candidates(damage_kind(recipient)),
        key=lambda candidate: candidate.order,
    )


def _settled(game, event: dict) -> bool:
    """The event has been consumed, or has nothing left to modify. Either way
    no further effect can apply to it (CR 615.7, CR 614.6)."""
    return was_replaced(game, event) or spent(game, event)


def deal_damage(game, event: dict, *, restart: Callable[[], Any] | None = None) -> DamageOutcome:
    """Run a damage event through CR 120.4 and report what it did.

    *event* is ``{recipient, amount, source, combat}``. A 0-or-less event
    modifies nothing and consumes nothing (CR 120.8, CR 614.7a): no shield is
    spent and no trigger fires, which is why the amount is checked before any
    effect is asked rather than after.

    This does not apply the result — the caller does that, because what "apply"
    means differs by recipient (life loss, damage marked) and by caller (combat
    accumulates a per-defender tally the log reconstructs from).

    *restart* re-runs the event **and everything the caller does with it**, which
    is what lets CR 616.1e's choice be asked here. Damage differs from a draw in
    exactly that respect: a draw's caller can be told "0 drawn, they arrive
    later", while a damage event's caller gains life equal to it, tallies
    lifelink from it and logs it. So the thunk has to close over the caller's
    own consequences — see ``Game._deal_damage_to_player``'s ``then``, which is
    how every damage caller now passes them in.

    Re-running a single damage event is only enough when the work behind it is
    recorded, because damage is rarely the only thing in flight: a divided
    Fireball deals to each target in turn, a ``sequence`` has instructions
    queued behind the one that stopped, a spell still has CR 608.2m's graveyard
    move to make, and the combat damage step has the rest of its blockers, its
    attackers and its own completion flags. ``engine/resumption.py`` is what
    records that, and the callers that pass ``asks=True`` (or their own
    ``restart``, as the combat step's player-damage loop does) are the ones
    running inside it. Every damage path now asks.
    """
    if event["amount"] <= 0:
        return DamageOutcome(consumed=False, dealt=0, result=0)
    kind = damage_kind(event["recipient"])
    trace = apply_in_order(
        game,
        event,
        damage_candidates(event["recipient"]),
        chooser_index=affected_seat(game, event["recipient"]),
        stop=_settled,
        ask=None if restart is None else order_prompt_asker(kind, restart),
    )
    if trace.suspended:
        take_replaced(event)
        return DamageOutcome(consumed=False, dealt=0, result=0, suspended=True)
    if trace.applied:
        game.effect_order_answers.pop((kind, affected_seat(game, event["recipient"])), None)
    consumed = take_replaced(event)
    dealt = max(0, event["amount"])
    if consumed or dealt <= 0:
        return DamageOutcome(consumed=consumed, dealt=0, result=0)
    return DamageOutcome(consumed=False, dealt=dealt, result=_process_results(game, event, dealt))


def _process_results(game, event: dict, dealt: int) -> int:
    """CR 120.4c: how much of the damage that was dealt lands as its result.

    Carries ``dealt`` alongside the running ``amount`` so an effect that caps the
    result can still see the damage it is not changing.

    Runs without a ``restart``, so this half never asks CR 616.1e's question —
    and never has one to ask, because each results kind holds at most one effect
    and a contention needs two. That is not a coincidence to rely on quietly:
    ``test_a_results_half_contention_would_need_asking`` fails the day a second
    one is registered, because by then the first half has applied real effects
    and re-running would need the replay reasoning this deliberately avoids.
    """
    results = {
        "recipient": event["recipient"],
        "amount": dealt,
        "dealt": dealt,
        "source": event.get("source"),
        "combat": bool(event.get("combat")),
    }
    consumed, _ = apply_replacements(game, RESULT_KINDS[damage_kind(event["recipient"])], results)
    return 0 if consumed else max(0, results["amount"])


def _assert_one_order_space() -> None:
    """A shield and a replacement sharing an order is an ambiguity about which
    modifies a damage event first, which is rules-visible. Both registries
    already reject a duplicate within themselves; this is the check neither can
    make alone, and it runs at import for the same reason theirs do.

    Only the 120.4b half needs it — the results kinds contend with replacements
    alone, so their own per-kind check already covers them.
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
