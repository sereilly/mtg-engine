"""Whether an AI seat takes an offering (CR 702.48), and which permanent it
offers.

CR 702.48a: "'[Quality] offering' means 'As an additional cost to cast this
spell, you may sacrifice a [quality] permanent. If you chose to pay the
additional cost, this spell's total cost is reduced by the sacrificed
permanent's mana cost, and you may cast this spell any time you could cast an
instant.'" The seat never took one: the offer buys nothing the program reads,
so ``ai_valuation._what_an_offer_buys`` called it a different spell
(``OFFER_ALTERS``) and ``ai_casts._times_worth_taking`` declined it — every
Patron was hard-cast or held, and none was ever flashed in. It is its own
class now (``ai_valuation.OFFER_REDUCES``), read off ``offering.offering_costs``.

**What the offering buys** is one of two things, and the seat takes it for
either and for nothing else:

* **the moment** — CR 601.3c lets a cast begin "as though it had flash" only
  if the cost will be paid, so at a time a sorcery could not be cast the
  cast exists *only* with the offering (``offering.offering_timing_refusal``
  names it): a Patron at another seat's end step, or flashed in to block;
* **the mana** — the total reduced by the offered permanent's mana cost
  (CR 702.48c, ``offering.offering_reduction``) is one the seat's sources can
  pay and the printed total is not.

A seat that can pay the printed cost at a time a sorcery could be cast keeps
its permanent: what it would save is mana it has, and what it would give up
is a body on the board.

**Which permanent** (CR 702.48b: chosen as the spell's other choices are,
CR 601.2b) is the one cheapest to lose
(``ai_sacrifice_victims.cheapest_to_lose`` — ``ai_standing.permanent_loss``,
the engine's own order on a tie) whose reduction lets the sources pay; for
the moment alone, the cheapest. It is named on the cast's cost channel
(``CastAction.cost_permanent_ids``), which is what the cast path sizes the
reduction by (``offering.offering_announcement``), and while the candidate
is built every price the builder reads is the reduced one
(``ai_weighed_cast.offering_victim_weighed``, read by ``ai_payment._cost_for``).

**What it costs** — the permanent — is the rehearsal's to weigh: a cast that
takes an offering is rehearsed even when it is a permanent
(``ai_casts._announced_candidate``), so the standing reads the Patron
arriving and the Fox gone, and a cast that leaves its seat worse off is not
proposed (``ai_scoring.not_worth_proposing``).
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from .offering import (offering_candidates, offering_costs, offering_taken,
                       offering_timing_refusal)

if TYPE_CHECKING:
    from .game import Game
    from .models import CardDefinition, Permanent


def offering_opens_the_moment(game: "Game", seat: int, card: "CardDefinition") -> bool:
    """Whether a cast of *card* by *seat* is possible right now **only** with
    its offering paid (CR 601.3c, 601.2e): the engine's own refusal of the
    announcement that declines it."""
    return offering_timing_refusal(game, seat, card, None) is not None


def offering_worth_taking(
    game: "Game", seat: int, card: "CardDefinition", from_zone: str,
) -> bool:
    """Whether *seat* takes *card*'s offering on this cast (the module
    docstring): it opens the moment, or its reduction pays for a cast the
    sources cannot pay for without it."""
    if not offering_costs(card) or not any(
        offering_candidates(game, seat, cost) for cost in offering_costs(card)
    ):
        return False
    if offering_opens_the_moment(game, seat, card):
        return True
    if not game.enforce_mana_costs:
        # Free mana: the reduction buys nothing.
        return False
    from .ai_payment import _cost_for, _plan_land_taps

    player = game.players[seat]
    if _plan_land_taps(game, player, _cost_for(game, player, card, None)) is not None:
        return False
    return offering_pays_for_it(game, seat, card)


def offering_pays_for_it(game: "Game", seat: int, card: "CardDefinition") -> bool:
    """Whether *seat*'s sources pay *card*'s total with some permanent it
    could offer given up (CR 702.48c) — the cheap question
    ``ai_policy.holds_an_instant_it_could_pay_for`` asks before the
    instant-speed chooser is: a Patron with four lands and a Fox is a cast
    that chooser builds although the printed cost is not paid."""
    if not game.enforce_mana_costs:
        return False
    return any(
        _offered_and_payable(game, seat, card, victim)
        for cost in offering_costs(card)
        for victim in offering_candidates(game, seat, cost)
    )


def _offered_and_payable(
    game: "Game", seat: int, card: "CardDefinition", victim: "Permanent",
) -> bool:
    """Whether *seat*'s sources pay *card*'s total with *victim* offered."""
    from .ai_payment import _cost_for, _plan_land_taps
    from .ai_weighed_cast import weighing_an_offering

    player = game.players[seat]
    with weighing_an_offering(card, victim):
        return _plan_land_taps(game, player, _cost_for(game, player, card, None)) is not None


def offering_victim(
    game: "Game", seat: int, card: "CardDefinition", offers: "dict | None",
) -> "Permanent | None":
    """The permanent *seat* offers on a cast of *card* announcing *offers*,
    or None for an announcement that takes no offering (or has nothing to
    offer — the CR 601.2h gate says so, in one place).

    The cheapest to lose (``ai_sacrifice_victims.cheapest_to_lose``) whose
    reduction lets the sources pay — the cheapest of all where the mana is
    free, where none does (the builder's own gate then says the cast is
    unaffordable), and at a moment the offering alone opens with the printed
    cost payable."""
    from .ai_sacrifice_victims import cheapest_to_lose

    for cost in offering_costs(card):
        if not offering_taken(cost, offers):
            continue
        ranked = cheapest_to_lose(game, seat, offering_candidates(game, seat, cost))
        if not ranked:
            return None
        if game.enforce_mana_costs:
            for victim in ranked:
                if _offered_and_payable(game, seat, card, victim):
                    return victim
        return ranked[0]
    return None


@contextmanager
def offering_weighed(game: "Game", seat: int, card: "CardDefinition", offers: "dict | None"):
    """Around the build of one candidate cast of *card* announcing *offers*:
    the permanent it offers (:func:`offering_victim`) is the one every price
    read in the block is reduced by (``ai_weighed_cast.weighing_an_offering``).
    Nothing for an announcement that takes no offering."""
    from .ai_weighed_cast import weighing_an_offering

    victim = offering_victim(game, seat, card, offers) if offers else None
    if victim is None:
        yield
        return
    with weighing_an_offering(card, victim):
        yield


__all__ = [
    "offering_opens_the_moment",
    "offering_pays_for_it",
    "offering_victim",
    "offering_weighed",
    "offering_worth_taking",
]
