"""Paying a cost from the board — engine/mana_payment.py (CR 601.2h, CR 602.2b).

Two questions, and the engine long answered only one of them well. Casting and
activating spend the **pool**, because producing the mana is the player's own
separate action; an effect that says "you may pay {1}{B}. If you do, …" gives its
player no priority window at all, so it must look at the untapped lands too.

That second answer used to count to a number, which is why every optional cost
with a coloured pip in it refused at compile time. These tests are about the
answer that replaced it: what it can pay, what it correctly cannot, and that it
never *under*-reports a board that could pay — which is the failure a greedy
land-picker would have.
"""

from __future__ import annotations

import pytest

from engine.card_loader import load_cards, manifest_set_paths
from engine.mana_payment import (
    generic_cost, mana_cost_label, plan_payment, total_pips, untapped_mana_lands,
)
from engine.models import Permanent


@pytest.fixture(scope="module")
def pool():
    return {c.name: c for c in load_cards(manifest_set_paths(include_measured=True))}


def _lands(pool, *names):
    return [Permanent(card=pool[name]) for name in names]


EMPTY = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}


@pytest.mark.cr("601.2h")
def test_a_coloured_pip_is_paid_by_a_land_that_makes_that_colour(pool):
    lands = _lands(pool, "Swamp", "Forest")

    plan = plan_payment(EMPTY, lands, {"B": 1, "generic": 1})

    assert plan is not None
    assert {land.card.name for land in plan.tapped} == {"Swamp", "Forest"}


@pytest.mark.cr("601.2h")
def test_a_board_with_no_source_of_the_colour_cannot_pay(pool):
    lands = _lands(pool, "Forest", "Forest", "Forest")

    assert plan_payment(EMPTY, lands, {"B": 1, "generic": 1}) is None


@pytest.mark.cr("601.2h")
def test_floating_mana_is_spent_before_a_land_is_tapped(pool):
    """A land kept untapped is worth more than one that is not, and the floating
    mana is already spent-in-advance."""
    lands = _lands(pool, "Swamp", "Swamp")

    plan = plan_payment({**EMPTY, "B": 1}, lands, {"B": 1})

    assert plan is not None
    assert plan.from_pool == {"B": 1}
    assert plan.tapped == ()


@pytest.mark.cr("601.2h")
def test_the_matching_is_exact_rather_than_greedy(pool):
    """The case a one-pass picker gets wrong. A dual is the only source of one
    colour and *also* a source of the other; spending it on the wrong pip
    strands the cost on a board that can pay it.

    Under-reporting is the harm here — CR 601.2h asks what the player is *able*
    to do, and a payment nobody was offered is not the same as one refused.
    """
    lands = _lands(pool, "Swamp", "Underground Sea")  # {B} and {U}{B}

    plan = plan_payment(EMPTY, lands, {"U": 1, "B": 1})

    assert plan is not None, "the Sea pays the {U} and the Swamp the {B}"
    assert len(plan.tapped) == 2


@pytest.mark.cr("601.2h")
def test_a_land_cannot_pay_two_pips_at_once(pool):
    lands = _lands(pool, "Underground Sea")

    assert plan_payment(EMPTY, lands, {"U": 1, "B": 1}) is None


@pytest.mark.cr("601.2h")
def test_a_tapped_land_is_not_a_source(pool):
    tapped = _lands(pool, "Swamp")[0]
    tapped.tapped = True

    assert untapped_mana_lands([tapped]) == []


@pytest.mark.cr("107.4")
def test_the_cost_reads_the_way_the_card_prints_it():
    """The prompt a player answers should look like the line they read it on —
    the numerical symbol first, then the coloured ones, which is the notation
    the rules themselves use."""
    assert mana_cost_label({"generic": 1, "B": 1}) == "{1}{B}"
    assert mana_cost_label(generic_cost(2)) == "{2}"
    assert total_pips({"generic": 1, "B": 1}) == 2
