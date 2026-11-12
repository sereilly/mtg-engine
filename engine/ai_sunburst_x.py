"""The X a sunburst card is cast for, where its counters will name a mana value.

"{X}. Sunburst. {2}, Sacrifice this artifact: Destroy each nonland permanent
with mana value equal to the number of charge counters on this artifact."
(Engineered Explosives.) The counters are the colours spent on the cast (CR
702.44a), and the AI announced the largest X its lands could pay
(``ai_payment._max_affordable_x``) — every colour in reach, whatever the
board held at that mana value, and mana beyond the colours for nothing
(5DN W1G1). Two parts, as W1G1 named them:

* **the want — a target mana value** (:func:`aimed_sunburst_x`): each count
  the board allows is the mana value the sweep would then take, priced as
  what it destroys of the other seats' less what it destroys of the
  caster's (``ai_standing.permanent_worth``, read through the same filter
  the resolved sweep asks, ``subject_filters.subject_matches``); the count
  taking most is aimed at, and none where no count takes more than it
  costs (the largest X stands, as before);
* **a colour count the payment would hit** — the X is that count: a payment
  of N generic spreads over as many colours as its N units can be
  (``sunburst.color_spreading_costs``), so X = N spends N colours exactly
  where the planner says N are in reach at that X
  (``ai_payment.colors_in_reach``), and no mana beyond them.

Read off the card's compiled ability (:data:`MANA_VALUE_FROM_COUNTERS` on a
sweep) and its sunburst line (``sunburst.counts_colors_spent``), so it names
no card. An X of 0 is the aim where the board's mana value 0 is the one worth
taking (tokens), which the cast chooser otherwise never announces
(:func:`aims_at_mana_value_zero`).
"""

from __future__ import annotations

from .ai_payment import colors_in_reach
from .ai_standing import permanent_worth
from .oracle import compile_card_oracle
from .subject_filters import SOURCE_COUNTED_MANA_VALUE, subject_matches
from .sunburst import counts_colors_spent
from .targeting import usable_activated_abilities

#: The payload key a step compares mana values against its source's counters
#: through: "…with mana value equal to the number of charge counters on this
#: artifact".
MANA_VALUE_FROM_COUNTERS = SOURCE_COUNTED_MANA_VALUE

#: The sweeps whose mana value this aims: each one removes what it matches
#: from every seat alike, so what it takes is a loss to whoever controls it.
_SWEEP_KINDS = frozenset({"destroy_all_matching"})

#: CR 105.1: five colours, so a sunburst count never passes five (CR 702.44a).
MOST_COLORS = 5


def counted_sweep_filter(card) -> "dict | None":
    """The filter of *card*'s own sweep keyed to its counters ("Destroy each
    nonland permanent with mana value equal to the number of charge counters
    on this artifact"), without the counted key — or None."""
    for ability in usable_activated_abilities(compile_card_oracle(card)):
        instruction = ability.instruction
        if instruction is None or instruction.kind not in _SWEEP_KINDS:
            continue
        payload = instruction.payload or {}
        if payload.get(MANA_VALUE_FROM_COUNTERS):
            return {
                key: value for key, value in payload.items()
                if key not in (MANA_VALUE_FROM_COUNTERS, "targets")
            }
    return None


def _sweep_worth(game, seat: int, swept: dict, mana_value: int) -> float:
    """What the counted sweep would take at *mana_value*: the other seats'
    permanents it matches, less the caster's own, each at its lasting worth."""
    wanted = {**swept, "mana_value": {"op": "eq", "value": mana_value}}
    net = 0.0
    for permanent in game.all_permanents():
        if not subject_matches(game, permanent, wanted, observer=seat):
            continue
        worth = permanent_worth(permanent, now=False)
        net += -worth if game.controls(seat, permanent) else worth
    return net


def aimed_sunburst_x(game, seat: int, card, max_x: "int | None") -> "int | None":
    """The X to announce for *card* — the mana value its counters will name —
    or None where its X is not aimed this way (no sunburst, no counted sweep,
    no count the board pays that takes more than it costs).

    Each count from 0 up to *max_x* (and :data:`MOST_COLORS`) that the
    payment would hit at that X is priced by :func:`_sweep_worth`, and the
    best is announced — the smaller on a tie, the less mana spent.
    """
    if max_x is None or not counts_colors_spent(card):
        return None
    swept = counted_sweep_filter(card)
    if swept is None:
        return None
    best, best_worth = None, 0.0
    for count in range(0, min(max_x, MOST_COLORS) + 1):
        if count and colors_in_reach(game, seat, card, x_value=count) != count:
            continue
        worth = _sweep_worth(game, seat, swept, count)
        if worth > best_worth + 1e-9:
            best, best_worth = count, worth
    return best


def aims_at_mana_value_zero(game, seat: int, card) -> bool:
    """Whether an X of 0 is *card*'s aim (:func:`aimed_sunburst_x`): its
    counted sweep takes more at mana value 0 than it costs."""
    return aimed_sunburst_x(game, seat, card, 0) == 0


__all__ = [
    "MANA_VALUE_FROM_COUNTERS",
    "MOST_COLORS",
    "aimed_sunburst_x",
    "aims_at_mana_value_zero",
    "counted_sweep_filter",
]
