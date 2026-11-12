"""Which permanent a seat sacrifices when the effect reads what it ate.

"As an additional cost to cast this spell, sacrifice an artifact. Put X +1/+1
counters on target creature, where X is the sacrificed artifact's mana value."
(Forge Armor.) A seat that names no victim pays with the engine's
deterministic pick (``Game.default_sacrifice_pick``: the smallest power
first), which is right for a cost that is only a price and wrong for one the
effect is measured by — Forge Armor gave up a Great Furnace and put no counter
anywhere, beside a four-mana artifact that would have made it four. Six cast
cards read the cost this way (Burnt Offering, Carrion, Fling, Forge Armor,
Metamorphosis, Worthy Cause), all through one payload key
(``x_from_count.cost_sacrifice_characteristic``), so the reading is the key's
and names no card.

What the victim is *worth* is not decided here: the candidates are the
distinct readings the board offers — one permanent per value of the
characteristic, the cheapest to lose among equals — and the cast chooser
rehearses each (``ai_casts._cast_naming_its_sacrifice``). A tie keeps the
cheaper permanent, so a board where the reading cannot matter pays as the
default always paid.

**How many**, where the effect counts what the sacrifice ate: "As an
additional cost to cast this spell, sacrifice any number of creatures. Target
creature gets +2/+2 until end of turn for each creature sacrificed this way"
(Vicious Betrayal). Named nothing, the engine sacrifices nothing and pumps
+0/+0, so every rehearsal read nothing and the spell was never cast. The
target choosers rehearse each target with one provisional victim
(``ai_actions._SACRIFICES_ANNOUNCED``, set by
:func:`sacrifices_weighed_provisionally`), and then
:func:`cast_naming_its_sacrifices` rehearses one set per size, the cheapest to
lose first: a creature is given up only where what it buys outweighs it.
"""

from __future__ import annotations

from contextlib import contextmanager

from .ai_standing import permanent_worth
from .ai_weighed_cast import _effect_steps
from .models import Permanent

#: The payload key a count spec reads the sacrificed permanent through
#: (``handlers/_amounts.py``), and the characteristics it names.
SACRIFICE_READ_KEY = "cost_sacrifice_characteristic"

#: How many distinct readings a cast is rehearsed at, the largest first.
#: Tuning: each is a rehearsal of the whole turn, and a limited board rarely
#: offers more distinct values than this.
VICTIM_READINGS_WEIGHED = 4

#: The payload key a count spec reads how many permanents an "any number of"
#: sacrifice ate through (``handlers/_amounts.py``): "+2/+2 … for each
#: creature sacrificed this way".
SACRIFICE_COUNT_KEY = "cost_sacrificed_count"

#: How many sizes of an "any number of" sacrifice a cast is rehearsed at, one
#: set per size, the cheapest to lose first. Tuning: each is a rehearsal of
#: the whole turn through its fight.
SACRIFICE_SETS_WEIGHED = 4


def characteristic_read_off_the_sacrifice(instructions) -> str | None:
    """The characteristic ("mana_value", "power", "toughness") *instructions*
    read off the permanent their sacrifice cost ate, or None when no step
    does. Wrappers opened, so "you may …" and a sequence read the same."""
    for instruction in instructions or ():
        if instruction is None:
            continue
        for step in (instruction, *_effect_steps(instruction)):
            for value in (step.payload or {}).values():
                if isinstance(value, dict) and value.get(SACRIFICE_READ_KEY):
                    return str(value[SACRIFICE_READ_KEY])
    return None


def sacrificed_reading(permanent: Permanent, characteristic: str) -> int:
    """What *characteristic* reads off *permanent* if it is sacrificed now: a
    mana value off its effective card (CR 707.2 copies it), power and
    toughness off the permanent as layer 7 has them. Only a grouping key —
    what the sacrifice actually buys is the rehearsal's to measure."""
    if characteristic == "mana_value":
        return int(getattr(permanent.effective_card, "cmc", 0) or 0)
    return int(getattr(permanent, f"effective_{characteristic}", 0) or 0)


def victims_to_weigh(
    candidates: "list[Permanent]", characteristic: str, sacrifice_key,
) -> "list[Permanent]":
    """One permanent per distinct reading of *characteristic* among
    *candidates*: the one cheapest to lose (its lasting worth, then
    *sacrifice_key* — ``Game.sacrifice_preference_key``), at most
    :data:`VICTIM_READINGS_WEIGHED` readings, the largest kept. Returned
    cheapest first, so a caller keeping the first of equal results keeps the
    cheaper permanent."""
    cheapest: dict[int, Permanent] = {}

    def cost(permanent) -> tuple:
        return (permanent_worth(permanent, now=False), sacrifice_key(permanent))

    for permanent in candidates:
        reading = sacrificed_reading(permanent, characteristic)
        held = cheapest.get(reading)
        if held is None or cost(permanent) < cost(held):
            cheapest[reading] = permanent
    kept = [cheapest[reading] for reading in sorted(cheapest, reverse=True)]
    return sorted(kept[:VICTIM_READINGS_WEIGHED], key=cost)


def counts_its_sacrifices(instructions) -> bool:
    """Whether a step of *instructions* counts the permanents its "any number
    of" sacrifice ate (:data:`SACRIFICE_COUNT_KEY`). Wrappers opened."""
    for instruction in instructions or ():
        if instruction is None:
            continue
        for step in (instruction, *_effect_steps(instruction)):
            for value in (step.payload or {}).values():
                if isinstance(value, dict) and value.get(SACRIFICE_COUNT_KEY):
                    return True
    return False


def any_number_sacrifice(game, card, from_zone: str, offers):
    """The "sacrifice any number of <noun phrase>" price (CR 601.2b) a cast of
    *card* out of *from_zone* would pay with *offers* taken, where its effect
    counts what that sacrifice ate — or None. Only where that price is the
    cast's one chosen-permanent demand (``Game._chosen_cast_cost_demands``,
    whose count is None for "any number"): one list of ids names it whole."""
    from .ai_actions import _announced_steps
    from .cast_costs import additional_costs
    from .oracle import compile_card_oracle

    costs = tuple(
        cost for cost in additional_costs(card)
        if cost.from_zone is None or cost.from_zone == from_zone
    )
    if not any(getattr(cost, "sacrifice_any_number", False) for cost in costs):
        return None
    if not counts_its_sacrifices(_announced_steps(card, compile_card_oracle(card))):
        return None
    demands = game._chosen_cast_cost_demands(costs, x_value=None, taken=offers)
    if len(demands) != 1 or demands[0][0] != "sacrifice" or demands[0][2] is not None:
        return None
    return demands[0][1]


def cheapest_to_lose(game, seat: int, candidates) -> list:
    """*candidates* in the order *seat* would give them up: the least lost
    first (``ai_standing.permanent_loss``), the engine's own order
    (``Game.sacrifice_preference_key``) on a tie."""
    from .ai_standing import permanent_loss

    return sorted(
        candidates,
        key=lambda permanent: (
            permanent_loss(game, seat, permanent), game.sacrifice_preference_key(permanent),
        ),
    )


@contextmanager
def sacrifices_weighed_provisionally(game, seat: int, card, from_zone: str, offers):
    """Around the build of a candidate cast of *card*: where it pays an "any
    number of" sacrifice its effect counts (:func:`any_number_sacrifice`), the
    permanents that could pay, cheapest first, as the provisional victims the
    target choosers rehearse with (``ai_actions._SACRIFICES_ANNOUNCED``).
    Nothing for every other card."""
    from .ai_actions import _SACRIFICES_ANNOUNCED

    cost = any_number_sacrifice(game, card, from_zone, offers)
    if cost is None:
        yield
        return
    victims = tuple(
        permanent.permanent_id
        for permanent in cheapest_to_lose(
            game, seat, game._additional_cost_candidates(seat, cost),
        )
    )
    token = _SACRIFICES_ANNOUNCED.set(victims)
    try:
        yield
    finally:
        _SACRIFICES_ANNOUNCED.reset(token)


def cast_naming_its_sacrifices(game, seat: int, card, action, offers):
    """*action* naming the permanents its "any number of" sacrifice is paid
    with — or *action* as it is, naming none, which the engine pays with
    nothing at all.

    One set per size up to :data:`SACRIFICE_SETS_WEIGHED`, the cheapest to
    lose first (:func:`cheapest_to_lose`), each rehearsed as a cast of its own
    with the turn's fight read through it, and the one that moves the seat
    furthest named — the smaller on a tie. A set that leaves its caster worse
    off is not named, so a creature is sacrificed only where the pump it buys
    is worth more than it is. Never a permanent the cast names as a target: a
    pump paid for with its own target is a pump on nothing.
    """
    from dataclasses import replace

    from . import ai_cast_trace as cast_trace
    from .ai_actions import cast_announcement
    from .ai_payment import _bind_action_slots
    from .ai_scoring import (
        _rehearse_announcement,
        _weighed_through_the_fight,
        _worth_proposing,
    )

    cost = any_number_sacrifice(game, card, action.from_zone, offers)
    if cost is None:
        return action
    bound = _bind_action_slots(game, seat, action)
    named = [bound.get("target"), *bound.get("targets", ()), *bound.get("divided", ())]
    named += [
        game.permanent_by_id(permanent_id)
        for permanent_id in (action.target_permanent_ids or ())
        if isinstance(permanent_id, int)
    ]
    victims = [
        permanent
        for permanent in cheapest_to_lose(game, seat, game._additional_cost_candidates(seat, cost))
        if not any(permanent is other for other in named if other is not None)
    ]
    best, best_swing = action, None
    for count in range(1, min(len(victims), SACRIFICE_SETS_WEIGHED) + 1):
        eaten = victims[:count]
        variant = replace(action, cost_permanent_ids=[each.permanent_id for each in eaten])
        rehearsal = _rehearse_announcement(
            game, seat, card, cast_announcement(variant), planned=variant,
        )
        rehearsal = _weighed_through_the_fight(
            game, seat, card, cast_announcement(variant), rehearsal, planned=variant,
        )
        names = ", ".join(each.card.name for each in eaten)
        if rehearsal is None or not _worth_proposing(rehearsal):
            cast_trace.note(f"sacrifice {names}: not worth proposing")
            continue
        cast_trace.note(f"sacrifice {names}: swing {rehearsal.swing:+.2f}")
        if best_swing is None or rehearsal.swing > best_swing:
            best, best_swing = variant, rehearsal.swing
    return best


def activation_sacrifice_choices(
    game, seat: int, source: Permanent, ability, *, spare: "Permanent | None" = None,
) -> "list[tuple[int, ...] | None]":
    """The ways *seat* could pay *ability*'s "Sacrifice <a printed number of>
    <noun phrase>" cost (CR 602.2b through 601.2b), cheapest first, as the
    ``permanent_id`` tuples the activation path's ``cost_permanent_ids``
    takes — for the activation chooser to rehearse
    (``ai_activation_rehearsal._sacrifice_priced_activation``).

    * Where the effect reads what the sacrifice ate ("Bosh deals damage
      equal to the sacrificed artifact's mana value"), one victim per
      distinct reading (:func:`victims_to_weigh`) — the activated twins of
      the six cast cards this module was written for.
    * Otherwise the one choice of the printed number of permanents that are
      cheapest to lose (``ai_standing.permanent_loss``: a land beyond the
      ones a seat needs is a spare), the engine's own order
      (``Game.sacrifice_preference_key``: the source kept for last) on a tie.

    The candidates are the engine's own (``Game._sacrifice_cost_candidates``).
    *spare* — the permanent the ability is aimed at — is not offered while
    any other will do: a pump paid for with its own target is a pump on
    nothing. ``[None]`` (the engine's default) for a conjoined second
    sacrifice ("a creature and a Swamp"), which one list of ids does not
    say; ``[]`` when the board cannot pay.
    """
    from .ai_standing import permanent_loss

    cost = ability.cost
    count = cost.sacrifice_count if isinstance(cost.sacrifice_count, int) else 1
    candidates = game._sacrifice_cost_candidates(cost, seat, source)
    if spare is not None and len([p for p in candidates if p is not spare]) >= count:
        candidates = [p for p in candidates if p is not spare]
    if len(candidates) < count:
        return []
    if cost.sacrifice_also_filter is not None:
        return [None]

    def order(permanent):
        return game.sacrifice_preference_key(permanent, source)

    characteristic = characteristic_read_off_the_sacrifice([ability.instruction])
    if characteristic is not None and count == 1:
        return [
            (victim.permanent_id,)
            for victim in victims_to_weigh(candidates, characteristic, order)
        ]
    cheapest = sorted(
        candidates,
        key=lambda permanent: (permanent_loss(game, seat, permanent), order(permanent)),
    )
    return [tuple(permanent.permanent_id for permanent in cheapest[:count])]


def eats_a_land_it_needs(game, seat: int, permanent_ids) -> bool:
    """Whether sacrificing the permanents *permanent_ids* name leaves *seat*
    controlling fewer lands than ``ai_standing.LANDS_WORTH_KEEPING`` — a land
    out of the ones a limited deck needs to cast what it holds, which the
    standing prices at a card and a land drop whatever the seat's hand asks
    of it. False for no named permanents (the engine's default pick, which
    this reader cannot see)."""
    from .ai_standing import LANDS_WORTH_KEEPING

    named = set(permanent_ids or ())
    if not named:
        return False
    lands = [permanent for permanent in game.controlled_by(seat) if permanent.has_type("land")]
    eaten = sum(1 for permanent in lands if permanent.permanent_id in named)
    return bool(eaten) and len(lands) - eaten < LANDS_WORTH_KEEPING


__all__ = [
    "SACRIFICE_COUNT_KEY",
    "SACRIFICE_READ_KEY",
    "SACRIFICE_SETS_WEIGHED",
    "VICTIM_READINGS_WEIGHED",
    "activation_sacrifice_choices",
    "any_number_sacrifice",
    "cast_naming_its_sacrifices",
    "cheapest_to_lose",
    "counts_its_sacrifices",
    "eats_a_land_it_needs",
    "characteristic_read_off_the_sacrifice",
    "sacrifices_weighed_provisionally",
    "sacrificed_reading",
    "victims_to_weigh",
]
