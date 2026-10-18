"""Every land in the pool, asked to pay {1} for an effect: a plan that says
"can pay" pays.

An effect's price is collected with no priority window behind it, so the
engine taps for its payer (CR 605.3a) — over a plan, asked first as "can they
pay?" and then carried out one land at a time (``Game._pay_planned_cost``).
The two must be one answer. The plan was made over every untapped land with a
free mana ability, and five of the pool's lands do not pay when tapped that
way: Mishra's Workshop (its mana may be spent only on artifact spells,
CR 106.6) and City of Shadows, Gaea's Cradle, Serra's Sanctum and Tolarian
Academy (an amount the board decides, at nothing on a bare one). "Can pay"
said yes, the land was tapped, and the payment failed part-way — which each
payer then survived in its own way: a counter-unless countered the spell, an
"unless you pay" was forgiven, an upkeep price and an attack toll were logged
as paid.

``Game.payment_lands`` is the list every such plan is made over now: the
pure list narrowed by the tap seam's own refusal and by the predicate the AI's
cast plan already asked. Validated backwards below.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_paths
from engine.mana_payment import untapped_mana_lands
from engine.models import Permanent
from engine.search_filters import card_has_type

#: Floors, because a sweep that reaches nothing passes. 223 lands on the day,
#: 171 of which a plan says pay {1} from a bare board.
_MIN_LANDS = 200
_MIN_PLANNED = 150

_PRICE = {"cost": {"generic": 1}}


@pytest.fixture(scope="module")
def lands():
    pool = load_cards(manifest_set_paths(include_measured=True))
    return [card for card in pool if card_has_type(card, "land")]


def _alone(card) -> tuple[Game, PlayerState]:
    land = Permanent(card=card)
    land.metadata["summoning_sickness_turn"] = -99
    me = PlayerState(name="P0", battlefield=[land], life=20)
    return Game(players=[me, PlayerState(name="P1", life=20)]), me


def _census(lands) -> dict:
    planned, lies = [], []
    for card in lands:
        game, me = _alone(card)
        if game._optional_pay_plan(me, _PRICE) is None:
            continue
        planned.append(card.name)
        if not game._pay_planned_cost(
            me, lambda: game._optional_pay_plan(me, _PRICE)
        ):
            lies.append(card.name)
    return {"planned": planned, "lies": lies}


def test_a_plan_that_says_a_land_pays_is_a_payment_that_succeeds(lands):
    census = _census(lands)

    assert len(lands) >= _MIN_LANDS, len(lands)
    assert len(census["planned"]) >= _MIN_PLANNED, len(census["planned"])
    assert not census["lies"], census["lies"]


def test_the_census_names_the_five_with_the_narrowing_switched_off(
    lands, monkeypatch,
):
    """Backwards: planned over the pure list. The five used to be counted
    again and the payment failed on each; they are still not planned, because
    a second layer now answers for them — the planner's hook reads what a tap
    *alone* makes of each land (``board_payment.tap_alone_symbols``, R3 K3),
    and a Gaea's Cradle on a bare board or a Workshop's restricted mana offers
    a payment with no purpose nothing."""
    monkeypatch.setattr(
        Game, "payment_lands",
        lambda self, seat: untapped_mana_lands(self.controlled_by(seat)),
    )

    census = _census(lands)

    assert census["lies"] == [], census["lies"]
    five = {
        "Mishra's Workshop", "City of Shadows", "Gaea's Cradle",
        "Serra's Sanctum", "Tolarian Academy",
    }
    assert not five & set(census["planned"]), sorted(five & set(census["planned"]))
    assert len(census["planned"]) >= _MIN_PLANNED


def test_a_land_the_plan_leaves_out_is_still_a_person_s_to_tap(lands):
    """Left out of the plan is not lost: it is mana beyond the plan, which is
    what makes an offer worth putting to a person who holds it
    (``Game.payment_may_be_offered``)."""
    by_name = {card.name: card for card in lands}
    game, me = _alone(by_name["Mishra's Workshop"])
    game.interactive_seats = {0}

    assert game.payment_lands(0) == []
    assert game.mana_beyond_the_plan(0)
    assert not game._player_can_pay_optional(me, _PRICE)
    assert game.payment_may_be_offered(me, _PRICE)

    game.interactive_seats = set()
    assert not game.payment_may_be_offered(me, _PRICE)
