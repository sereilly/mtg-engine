"""Which permanent, and which kind of counter, a remove-a-counter cost is paid with.

"{1}{R}, Remove a +1/+1 counter or a charge counter from a permanent you
control: This enchantment deals 2 damage to any target." (Ion Storm.) "{T},
Remove a counter from a permanent you control: …" (Power Conduit.) "{2},
Remove a +1/+1 counter from a creature you control: Put a +1/+1 counter on
this creature." (Spike Rogue's second ability.) The activation chooser
declined every such cost (``ai_abilities._activation_candidate``), because
its flat score reads the effect alone and a counter moved off one permanent
read as free. SET_PLAYBOOK's Known gaps named the parts: the sacrifice
weighing's twin, an ``ActivationAction.cost_counter_kind`` the announcement
forwards, and a price on the counters the standing does not read.

* **The choices** (:func:`counter_cost_choices`): each permanent the
  engine's own list admits (``Game._remove_counter_cost_candidates``) with
  each kind the cost lets it give up, at most :data:`COUNTER_CHOICES_WEIGHED`,
  the cheapest first — each one a cast of the ability the chooser rehearses
  with the whole cost paid (``ai_activation_rehearsal.
  _counter_priced_activation``).
* **The price the standing cannot see** (:func:`spent_counter_worth`). A
  +1/+1 counter taken off a creature is a smaller body, which
  ``ai_standing.permanent_worth`` reads through the layers, so it is priced
  by the rehearsal itself. A charge counter is read by nothing in the
  standing: what it is worth is what its permanent spends it on — Pentad
  Prism's mana, Clearwater Goblet's life, the mana value Engineered
  Explosives destroys — so a counter the permanent's own abilities spend or
  count is priced at :data:`SPENT_COUNTER_WORTH`, one mana's worth, and one
  nothing on it reads at nothing. An age counter is the price of keeping a
  cumulative-upkeep permanent (CR 702.24a): taking one off is a relief, at
  minus that. Priced here, at the one choice that spends it, rather than in
  ``ai_standing``: a standing term would reach every rehearsal of every
  permanent that ever holds a counter.
"""

from __future__ import annotations

from .named_counters import (
    ANY_COUNTER_KIND,
    counter_kinds_on,
    counters_on,
    listed_counter_kinds,
)
from .oracle import compile_card_oracle

#: What one counter a permanent's own abilities spend or count is worth to
#: the seat giving it up, where the standing reads nothing for it: one mana,
#: the unit ``ai_standing.permanent_worth`` prices a permanent's cost in.
#: Tuning.
SPENT_COUNTER_WORTH = 1.0

#: The counter cumulative upkeep adds (CR 702.24a), whose loss lowers every
#: payment after it.
AGE_COUNTER = "age"

#: How many ways of paying one remove-a-counter cost are rehearsed, the
#: cheapest first. Tuning: each is a rehearsal of the turn.
COUNTER_CHOICES_WEIGHED = 4

#: The counters CR 613.4c applies to power and toughness, which the standing
#: reads through the layers.
_PT_COUNTER_KINDS = frozenset({"+1/+1", "-1/-1", "+1/+0", "+0/+1", "-1/-0", "-0/-1"})


def _names_the_kind(value, kind: str) -> bool:
    """Whether *value* (a payload, or anything in one) names *kind*."""
    if isinstance(value, str):
        return value == kind
    if isinstance(value, dict):
        return any(_names_the_kind(each, kind) for each in value.values())
    if isinstance(value, (list, tuple)):
        return any(_names_the_kind(each, kind) for each in value)
    return False


def reads_its_counters(permanent, kind: str) -> bool:
    """Whether *permanent*'s own abilities spend or count its *kind*
    counters: a cost removing that kind from itself ("Remove a charge counter
    from this artifact: Add one mana of any color", Pentad Prism), or a step
    whose payload names it (Engineered Explosives' "the number of charge
    counters on this artifact"). Read off its compiled program."""
    program = compile_card_oracle(permanent.effective_card)
    for ability in program.activated_abilities:
        cost = ability.cost
        if getattr(cost, "remove_counter", None) == kind and (
            getattr(cost, "remove_counter_filter", None) is None
        ):
            return True
        if ability.instruction is not None and _names_the_kind(ability.instruction.payload, kind):
            return True
    for each in (*program.instructions, *program.triggered_abilities):
        instruction = getattr(each, "instruction", each)
        if instruction is not None and _names_the_kind(
            getattr(instruction, "payload", None), kind,
        ):
            return True
    return False


def spent_counter_worth(permanent, kind: str) -> float:
    """What giving up one *kind* counter off *permanent* costs its
    controller beyond what ``ai_standing`` reads: nothing for a counter the
    layers turn into power and toughness (the rehearsal prices the smaller
    body), minus :data:`SPENT_COUNTER_WORTH` for an age counter, that much
    for a counter the permanent's own abilities spend or count
    (:func:`reads_its_counters`), and nothing for one nothing on it reads."""
    if permanent is None or kind in _PT_COUNTER_KINDS:
        return 0.0
    if kind == AGE_COUNTER:
        return -SPENT_COUNTER_WORTH
    return SPENT_COUNTER_WORTH if reads_its_counters(permanent, kind) else 0.0


def _kinds_it_may_give(permanent, printed: str, needed: int) -> "list[str]":
    """The kinds of counter *permanent* could pay a cost printing *printed*
    with, *needed* of one kind at a time: every kind it holds for "a counter"
    (``ANY_COUNTER_KIND``), the listed ones it holds for "a +1/+1 counter or a
    charge counter", and the printed kind otherwise. Sorted, so a seeded game
    weighs them in one order."""
    if printed == ANY_COUNTER_KIND:
        held = counter_kinds_on(permanent)
        return sorted(kind for kind, count in held.items() if count >= needed)
    listed = listed_counter_kinds(printed)
    kinds = listed if listed is not None else (printed,)
    return [kind for kind in kinds if counters_on(permanent, kind) >= needed]


def counter_cost_choices(
    game, seat: int, source, ability, *, spare=None,
) -> "list[tuple[int, str]]":
    """The ways *seat* could pay *ability*'s "Remove <a counter> from <a
    permanent you control>" cost (CR 602.2b through 601.2b), as
    ``(permanent_id, kind)`` pairs — the activation path's
    ``cost_permanent_ids`` and ``cost_counter_kind`` — cheapest first and at
    most :data:`COUNTER_CHOICES_WEIGHED` of them; ``[]`` when the board
    cannot pay.

    The candidates are the engine's own (``Game._remove_counter_cost_
    candidates``), ordered by what the counter costs before any rehearsal:
    :func:`spent_counter_worth`, then for a counter the layers read the
    standing's price of the body it shrinks (``ai_standing.permanent_worth``),
    then the engine's own order. *spare* — the permanent the ability is
    aimed at — is not offered while any other will do: a counter moved off
    the creature it is put back on is a cost paid for nothing.
    """
    from .ai_standing import permanent_worth

    cost = ability.cost
    printed = str(cost.remove_counter)
    wanted = cost.remove_counter_count
    needed = int(wanted) if isinstance(wanted, int) else 1
    candidates = game._remove_counter_cost_candidates(cost, seat, source)
    if spare is not None and any(permanent is not spare for permanent in candidates):
        candidates = [permanent for permanent in candidates if permanent is not spare]
    choices = [
        (permanent, kind)
        for permanent in candidates
        for kind in _kinds_it_may_give(permanent, printed, needed)
    ]

    def order(choice) -> tuple:
        permanent, kind = choice
        body = permanent_worth(permanent, now=False) if kind in _PT_COUNTER_KINDS else 0.0
        return (
            spent_counter_worth(permanent, kind), body,
            game.sacrifice_preference_key(permanent, source), kind,
        )

    ranked = sorted(choices, key=order)[:COUNTER_CHOICES_WEIGHED]
    return [(permanent.permanent_id, kind) for permanent, kind in ranked]


__all__ = [
    "AGE_COUNTER",
    "COUNTER_CHOICES_WEIGHED",
    "SPENT_COUNTER_WORTH",
    "counter_cost_choices",
    "reads_its_counters",
    "spent_counter_worth",
]
