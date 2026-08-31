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


# --- W4G3: X spent by colour, and the life-gain cap ---
def _soul_burn_seat(pool, mana, *, victim_life=20, battlefield=()):
    """Soul Burn in hand, *mana* in the pool, costs enforced."""
    from engine.game import Game
    from engine.models import PlayerState

    p0 = PlayerState(name="P0", hand=[pool["Soul Burn"]], life=20)
    p1 = PlayerState(name="P1", life=victim_life, battlefield=list(battlefield))
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = True
    game._sync_control()
    p0.mana_pool = dict(mana)
    return game, p0, p1


@pytest.mark.cr("601.2h", "107.3a")
def test_601_2h_a_restricted_x_is_paid_by_whichever_split_the_pool_can_cover(pool):
    """"Spend only black and/or red mana on X." on a {X}{2}{B} spell.

    CR 107.3a: the caster announces X. CR 601.2h: they then pay the total cost,
    and which unit of mana covers which part of it is theirs to decide. The two
    interact here: the printed {B} pip and X compete for the same black mana, so
    a payment that spent black on X first would leave the pip unpayable and
    report a castable spell as uncastable.

    Two black and three red against X=3: the pip takes one black, X takes the
    other plus two red, and the {2} comes out of what is left.
    """
    game, p0, _p1 = _soul_burn_seat(pool, {"B": 2, "R": 3, "C": 2})

    result = game.cast_from_hand(0, "Soul Burn", x_value=3, target_player_index=1)

    assert result.supported, result.details
    assert sum(p0.mana_pool.values()) == 1, "six of the seven units paid {3}{2}{B}"


@pytest.mark.cr("601.2h")
def test_601_2h_an_unpayable_restricted_x_costs_the_caster_nothing(pool):
    """"Unpayable costs can't be paid." Green pays the generic {2} and nothing
    else on this card, so X=3 is unreachable — and the refusal happens before
    any mana leaves the pool, under **every** split rather than the first one
    tried."""
    game, p0, _p1 = _soul_burn_seat(pool, {"B": 1, "G": 6})

    result = game.cast_from_hand(0, "Soul Burn", x_value=3, target_player_index=1)

    assert not result.supported
    assert p0.mana_pool == {"B": 1, "G": 6}


@pytest.mark.cr("107.3a", "601.2h")
def test_107_3a_x_is_inferred_from_every_colour_the_card_allows(pool):
    """With no announced X the engine works out the largest affordable one, and
    that has to pool *both* allowed colours: asking about black alone
    under-reported the affordable X by every red mana on the board.

    {B} pip + {2} generic leaves five of the seven units for X.
    """
    game, p0, p1 = _soul_burn_seat(pool, {"B": 4, "R": 4})

    result = game.cast_from_hand(0, "Soul Burn", target_player_index=1)

    assert result.supported, result.details
    assert p1.life == 15, "X inferred as 5"


@pytest.mark.cr("120.3c", "306.5c")
def test_120_3c_the_life_gain_is_capped_by_the_planeswalkers_loyalty(pool):
    """"…but not more than … the planeswalker's loyalty before the damage was
    dealt…"

    The third of the cap's three recipient kinds, and the one no card in the
    pool can be pointed at without inventing a planeswalker: damage to a
    planeswalker removes that many loyalty counters (CR 120.3c), so the number
    the card measures against is the loyalty *before* the removal (CR 306.5c:
    a planeswalker's loyalty on the battlefield is its counters).
    """
    from engine.models import Permanent
    from tests.rules.test_planeswalkers import _mk_walker

    walker = Permanent(card=_mk_walker(), metadata={"loyalty_counters": 2})
    game, p0, _p1 = _soul_burn_seat(pool, {"B": 8}, battlefield=[walker])

    result = game.cast_from_hand(
        0, "Soul Burn", x_value=4,
        target_player_index=1, target_permanent_index=0,
    )

    assert result.supported, result.details
    game._settle()
    assert p0.life == 22, "four damage at two loyalty gains two"
# --- end W4G3 ---
