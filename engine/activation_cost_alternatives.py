"""Which of an ability's printed activation costs is paid (CR 602.2b, 601.2b).

"{3}, {T} **or** {U}, {T}: Return target creature to its owner's hand unless
its controller pays {1}." (Crystal Shard.) One ability, two printed costs, and
the 2004-10-04 ruling on all five Mirrodin Shards: "You can pay either of the
two costs (but not both at the same time) to activate the ability." The
activator announces which as the ability is activated — CR 602.2b sends the
activation through CR 601.2b, which announces alternative and additional costs
before targets are chosen — and CR 601.2f then totals *that* cost.

The compiler carries the printed costs as ``ActivatedAbilityCost.mana`` (the
first) and ``mana_alternatives`` (the rest), each a symbol dict; the halves
share every non-mana cost (``activation_costs._split_cost_alternatives``), so
the choice is a choice of mana alone. This module is the one reader of that
pair: the list of prices in printed order (:func:`printed_mana_costs`), the
announced index checked against it (:func:`alternative_cost_refusal`), and the
choice made for a seat that announced none (:func:`default_alternative_index`).

The announcement is ``alternative_cost_index`` — the name the cast path gives
CR 118.9a's choice between a spell's alternative costs, so one idea has one
name on both paths, on the wire (``GameActionRequest.alternative_cost_index``)
and on the AI's actions. Here index 0 is the first printed cost.

Imports nothing from the engine at module level (the board question is asked
lazily), so the activation mixins, the AI and the web layer may all read it.
"""

from __future__ import annotations

#: The pool's symbols, in the order every payment path spends them.
_POOL_SYMBOLS = ("W", "U", "B", "R", "G", "C")


def printed_mana_costs(cost) -> tuple[dict[str, int], ...]:
    """Every printed activation cost's mana, in printed order: ``cost.mana``
    first, then each alternative. One entry for every ability that prints no
    "or" between costs, which is all but five cards in the pool."""
    return (
        dict(cost.mana or {}),
        *(dict(found) for found in (getattr(cost, "mana_alternatives", ()) or ())),
    )


def has_alternative_costs(cost) -> bool:
    """Whether *cost* prints more than one activation cost to choose from."""
    return bool(getattr(cost, "mana_alternatives", ()) or ())


def alternative_cost_refusal(cost, index) -> str | None:
    """Why *index* names no printed cost of *cost*, or None.

    An index on an ability that prints one cost names nothing either, unless it
    is 0 — the one cost there is. A refusal rather than a quiet fallback: an
    announcement that cannot be carried out makes the activation illegal
    (CR 602.2, CR 733.1), and paying a different cost than the one announced
    is a different activation.
    """
    if index is None:
        return None
    count = len(printed_mana_costs(cost))
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < count:
        return (
            f"no printed activation cost {index!r}: the ability prints "
            f"{count} to choose from"
        )
    return None


def _pool_covers(pool: dict, required: dict) -> bool:
    """Whether *pool* alone pays *required*, coloured pips first — the reading
    ``activation_payment._pool_covers`` makes for "Pay 2 life or {2}", and
    deliberately as narrow: it is only ever a *default*, and a false negative
    picks another printed cost the card allows just as much."""
    left = {symbol: int(pool.get(symbol, 0) or 0) for symbol in _POOL_SYMBOLS}
    for symbol in _POOL_SYMBOLS:
        need = int(required.get(symbol, 0) or 0)
        if left[symbol] < need:
            return False
        left[symbol] -= need
    return sum(left.values()) >= int(required.get("generic", 0) or 0)


def default_alternative_index(game, seat: int, cost, *, source=None) -> int:
    """The printed cost a seat that announced none pays.

    The rule ``activation_cost_choice`` states for Tidal Control, one payment
    wider: an activation spends the pool, so the costs the floating mana
    covers are the ones this activation can pay, and of those the smallest —
    {U} rather than {3} when the pool holds both, which leaves the most mana
    behind. With nothing covered, the smallest the seat's **board** could pay
    (``board_payment.board_can_pay``, as a player is asked it), which is the
    one a payment that taps for the activation (the web's auto-tap, which asks
    the engine what it is short of) should tap for. Ties go to the printed
    order; with nothing payable at all the first printed cost is announced,
    and the payment refuses it as it refuses any cost the pool cannot pay.
    A seat that cares names its cost; this is what every headless caller, and
    a client that sends no index, gets.
    """
    costs = printed_mana_costs(cost)
    if len(costs) == 1:
        return 0

    def cheapest(indices):
        return min(indices, key=lambda index: (sum(costs[index].values()), index))

    controller = game.players[seat]
    pool = dict(getattr(controller, "mana_pool", {}) or {})
    covered = [index for index, mana in enumerate(costs) if _pool_covers(pool, mana)]
    if covered:
        return cheapest(covered)
    if getattr(game, "enforce_mana_costs", False):
        from .board_payment import board_can_pay
        from .restricted_mana import ACTIVATE, PaymentPurpose

        payable = [
            index for index, mana in enumerate(costs)
            if board_can_pay(
                game, seat, mana, nonland_sources=True,
                purpose=PaymentPurpose(ACTIVATE, source=source),
            )
        ]
        if payable:
            return cheapest(payable)
    return 0


def mana_cost_text(mana: dict) -> str:
    """*mana* as printed symbols, generic first — "{3}", "{U}", "{0}" — for a
    log line and for the wire's list of prices."""
    parts: list[str] = []
    generic = int(mana.get("generic", 0) or 0)
    if generic:
        parts.append(f"{{{generic}}}")
    for symbol in _POOL_SYMBOLS:
        parts.extend(f"{{{symbol}}}" for _ in range(int(mana.get(symbol, 0) or 0)))
    return "".join(parts) or "{0}"
