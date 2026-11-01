"""Floating mana pays generic with what the payer's other costs need least.

Round kg2 made the *lands* a payment taps spare the payer's other wants
(``mana_payment._sparing_choice``). The mana already floating was still spent
on generic in a fixed order, a different one in each of three places:

* ``mana_payment.plan_payment``'s pool walked the pool dict's own order (W, U,
  B, R, G, C — colourless last): turning Liege of the Axe face up for {1}{W}
  from {W:3, G:4, C:7} spent {W}{W} and left Defender of the Order's {W}{W}
  unpayable with seven colourless floating (LGN Phase 5);
* the cast path's spend (``pool_payment._pay_mana_cost_directly``, and the
  permission paths beside it) took C, W, U, B, R, G — SET_PLAYBOOK's Known gap,
  whose repro (``scratch/kg2/payment/pool_order.py``) stranded 470 of 1,344;
* the AI planner's floating units (``plan_payment``'s *spent_first*) paid
  "what the order gave them".

``mana_payment.floating_units_for_generic`` is the one answer all three now
ask: the floating units that pay the generic are the ones the payer's wants
(``mana_wants``) need least, colourless first where nothing is wanted.

**The census.** Every pool of zero to two units of each of W, U, B, R, G and C,
against seventeen costs and eighteen wants, where the pool pays the cost and
the want together — so some spend of the cost leaves the want payable. A
**strand** is a shape where ``plan_payment``'s spend, told the want, does not.
Measured on 8f22d265's own files: 23,106 of 77,796 strand (told or not — the
want never reached the pool); after it, none. Told nothing, the spend is
colourless first and 22,845 strand: a want nobody names is not one a payment
can keep. (The first count of this, 36,010 of 111,685, listed each
colourless-only cost five times and asked no {C} want.)
"""
from __future__ import annotations

import itertools
from unittest import mock

from engine import Game, PlayerState, mana_payment
from engine.card_loader import load_catalog
from engine.face_down import face_down_card, is_face_down
from engine.mana_payment import plan_payment
from engine.models import Permanent
from engine.special_actions import take_permanent_special_action
from tests.helpers import _nosick, resolve_stack

_CARDS = {card.name: card for card in load_catalog()}
SYMBOLS = ("W", "U", "B", "R", "G", "C")


def _pool(counts) -> dict:
    pool = {symbol: 0 for symbol in SYMBOLS}
    pool.update(counts)
    return pool


def _pays(pool, cost) -> bool:
    left = dict(pool)
    for symbol in SYMBOLS:
        if left.get(symbol, 0) < cost.get(symbol, 0):
            return False
        left[symbol] -= cost.get(symbol, 0)
    return sum(left.values()) >= cost.get("generic", 0)


def _minus(pool, spent) -> dict:
    return {symbol: pool.get(symbol, 0) - spent.get(symbol, 0) for symbol in pool}


def _together(first, second) -> dict:
    total = dict(first)
    for symbol, amount in second.items():
        total[symbol] = total.get(symbol, 0) + amount
    return total


COSTS = [
    *({"generic": generic, colour: 1} for colour in SYMBOLS[:5] for generic in (1, 2, 3)),
    {"generic": 1}, {"generic": 2},
]
WANTS = [
    *({symbol: 1} for symbol in SYMBOLS),
    *({symbol: 2} for symbol in SYMBOLS),
    *({"generic": 1, symbol: 1} for symbol in SYMBOLS),
]


def _census(*, told: bool = True) -> dict:
    found = {"shapes": 0, "strands": []}
    for counts in itertools.product(range(3), repeat=len(SYMBOLS)):
        if not any(counts):
            continue
        pool = _pool(dict(zip(SYMBOLS, counts)))
        for cost in COSTS:
            for want in WANTS:
                if not _pays(pool, _together(cost, want)):
                    continue
                found["shapes"] += 1
                payment = plan_payment(pool, [], cost, wants=[want] if told else None)
                if payment is None or not _pays(_minus(pool, payment.from_pool), want):
                    found["strands"].append((counts, cost, want))
    return found


def _in_dict_order(pool, amount, wants, **_kwargs):
    """The pool's spend as it was on 8f22d265: the pool dict's own order."""
    spent: dict = {}
    for symbol, units in pool.items():
        paid = min(amount, max(0, int(units)))
        if paid:
            spent[symbol] = paid
            amount -= paid
    return spent


def test_floating_mana_leaves_every_want_it_could_have_left():
    found = _census()
    assert found["strands"] == [], found["strands"][:10]
    assert found["shapes"] >= 75_000, found["shapes"]


def test_the_census_names_the_spend_in_the_pools_own_order():
    """Backwards: the spend as it was, which the want did not reach."""
    with mock.patch.object(mana_payment, "pool_spent_on_generic", _in_dict_order):
        found = _census()
    assert len(found["strands"]) >= 20_000, len(found["strands"])


def test_told_nothing_the_floating_mana_spends_colourless_first():
    """A payer with no want spends a {C} before a {W} on a {1}."""
    payment = plan_payment(_pool({"W": 1, "C": 1}), [], {"generic": 1})
    assert payment.from_pool == {"C": 1}


def test_a_wanted_colourless_is_kept():
    """The Known gap's first row: {C} and {W} floating, a {1} paid, a {C}
    still wanted — the {W} pays."""
    payment = plan_payment(_pool({"W": 1, "C": 1}), [], {"generic": 1}, wants=[{"C": 1}])
    assert payment.from_pool == {"W": 1}


def test_the_ai_planners_floating_units_spare_the_want_too():
    """``ai_payment._PaymentPlanner`` hands its floating mana to `plan_payment`
    as the first units (*spent_first*): {W} and {C} floating, a Mountain, a
    {1}{R} — the {C} is the floating unit that pays the {1}, the {W} is kept
    for the {W} still wanted. They paid "what the order gave them", the {W}."""
    pays = [frozenset({"W"}), frozenset({"C"}), frozenset({"R"})]
    payment = plan_payment(
        {}, range(len(pays)), {"generic": 1, "R": 1}, produces=pays.__getitem__,
        wants=[{"W": 1}], spent_first=2,
    )
    assert sorted(payment.tapped) == [1, 2], payment.tapped
    with mock.patch.object(
        mana_payment, "floating_units_for_generic",
        lambda candidates, amount, wants, **_kwargs: [index for index, _ in candidates][:amount],
    ):
        blind = plan_payment(
            {}, range(len(pays)), {"generic": 1, "R": 1}, produces=pays.__getitem__,
            wants=[{"W": 1}], spent_first=2,
        )
    assert sorted(blind.tapped) == [0, 2], blind.tapped


def _duel():
    me = PlayerState(name="A", library=[_CARDS["Plains"]] * 10)
    you = PlayerState(name="B", library=[_CARDS["Plains"]] * 10)
    game = Game(players=[me, you])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    return game, me


def test_liege_turned_up_from_the_pool_leaves_defenders_turn_up_payable():
    """LGN Phase 5's board: Liege of the Axe and Defender of the Order face
    down, {W:3, G:4, C:7} floating. Liege's {1}{W} is paid with a {W} and a
    {C}, and Defender turns up for {W}{W} after it."""
    game, me = _duel()
    liege = _nosick(Permanent(card=face_down_card(_CARDS["Liege of the Axe"])))
    defender = _nosick(Permanent(card=face_down_card(_CARDS["Defender of the Order"])))
    me.battlefield.extend([liege, defender])
    game._sync_control()
    me.mana_pool.update({"W": 3, "G": 4, "C": 7})
    game.priority_player_index = 0

    assert take_permanent_special_action(game, 0, liege, "turn_face_up") is None
    resolve_stack(game)
    assert not is_face_down(liege)
    assert me.mana_pool["W"] == 2, dict(me.mana_pool)

    game.priority_player_index = 0
    assert take_permanent_special_action(game, 0, defender, "turn_face_up") is None
    assert not is_face_down(defender)


def test_the_cast_path_spends_what_the_hand_does_not_need():
    """The Known gap's shape on the cast path: {W} and {R} floating, a {1}
    paid, and Savannah Lions ({W}) held — the payer's own want, read off its
    hand (`mana_wants`). The {R} pays the {1} and the {W} is left; in the
    fixed order (C, W, U, B, R, G) the {W} paid and the Lions were stranded."""
    game, me = _duel()
    me.hand = [_CARDS["Savannah Lions"]]
    me.mana_pool.update({"W": 1, "R": 1})
    paid = game._pay_mana_cost(me, {**{symbol: 0 for symbol in SYMBOLS}, "generic": 1})
    assert paid
    assert me.mana_pool["W"] == 1 and me.mana_pool["R"] == 0, dict(me.mana_pool)


def test_the_cast_path_told_nothing_spends_colourless_first_as_it_did():
    game, me = _duel()
    me.mana_pool.update({"W": 1, "C": 1})
    assert game._pay_mana_cost(me, {**{symbol: 0 for symbol in SYMBOLS}, "generic": 1})
    assert me.mana_pool["W"] == 1 and me.mana_pool["C"] == 0, dict(me.mana_pool)
