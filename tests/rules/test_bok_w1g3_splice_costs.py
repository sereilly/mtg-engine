"""A splice cost that is not mana (CR 702.47a): ``engine/splice.py``.

"Splice onto [quality] [cost]" pays [cost] "as an additional cost to cast that
spell", following "the rules for paying additional costs in rules 601.2b and
601.2f–h". Betrayers of Kamigawa prints five such costs behind a dash; the
per-card tests are ``tests/sets/test_bok_instants.py``. These hold the rules of
the payment itself, each through a real cast:

* 601.2b — what pays the cost is chosen as the spell is announced, and named
  objects are held to (``cost_permanent_ids``, ``cost_graveyard_indices``);
* 601.2h — the total cost is paid whole: two splice costs cannot both be paid
  with one creature, and the spell's own cost must still be payable beside
  its splice costs; nothing is spent by a refused cast;
* 119.7 — a cost that has an opponent gain life cannot be paid when no
  opponent may gain life.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import settle

_SETS = ("BOK", "CHK", "LEA", "MIR")


def _card(set_pool, name):
    for code in _SETS:
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _table(set_pool, *, hand=(), mine=(), theirs=(), graveyard=()):
    cards = lambda names: [_card(set_pool, n) for n in names]  # noqa: E731
    island = _card(set_pool, "Island")
    game = Game(players=[
        PlayerState("A", hand=cards(hand), library=[island] * 10,
                    graveyard=cards(graveyard)),
        PlayerState("B", library=[island] * 10),
    ])
    game.enforce_mana_costs = False
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = Permanent(card=_card(set_pool, name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    game._sync_control()
    game.start_turn(0)
    settle(game)
    return game, placed[0], placed[1]


def _hand(game, seat=0):
    return [card.name for card in game.players[seat].hand]


@pytest.mark.cr("702.47a", "601.2h")
def test_two_tap_costs_want_two_creatures_never_one_tapped_twice(set_pool):
    game, (lions, bears), (giant,) = _table(
        set_pool,
        hand=["Glacial Ray", "Hundred-Talon Strike", "Hundred-Talon Strike"],
        mine=["Savannah Lions", "Grizzly Bears"], theirs=["Hill Giant"],
    )
    both = [
        {"hand_index": 1, "target_permanent_ids": [bears.permanent_id]},
        {"hand_index": 2, "target_permanent_ids": [bears.permanent_id]},
    ]
    refused = game.cast_from_hand(
        0, "Glacial Ray", target_permanent_ids=[giant.permanent_id], splice_cards=both,
    )
    assert not refused.supported
    assert "once the other splice costs are paid" in refused.details
    assert not lions.tapped and len(_hand(game)) == 3
    # One of them alone is a payment.
    paid = game.cast_from_hand(
        0, "Glacial Ray", target_permanent_ids=[giant.permanent_id], splice_cards=both[:1],
    )
    assert paid.supported, paid.details
    settle(game)
    assert lions.tapped and bears.effective_power == 3


@pytest.mark.cr("702.47a", "601.2h")
def test_two_tap_costs_paid_by_two_white_creatures_tap_both(set_pool):
    game, (lions, knight), (giant,) = _table(
        set_pool,
        hand=["Glacial Ray", "Hundred-Talon Strike", "Hundred-Talon Strike"],
        mine=["Savannah Lions", "White Knight"], theirs=["Hill Giant"],
    )
    result = game.cast_from_hand(
        0, "Glacial Ray", target_permanent_ids=[giant.permanent_id], splice_cards=[
            {"hand_index": 1, "target_permanent_ids": [lions.permanent_id]},
            {"hand_index": 2, "target_permanent_ids": [lions.permanent_id]},
        ],
    )
    assert result.supported, result.details
    settle(game)
    assert lions.tapped and knight.tapped
    assert lions.effective_power == 4  # +1/+0 twice


@pytest.mark.cr("601.2b", "601.2h")
def test_one_permanent_named_for_two_splice_costs_is_refused(set_pool):
    game, (knight, _lions), (giant,) = _table(
        set_pool,
        hand=["Glacial Ray", "Hundred-Talon Strike", "Hundred-Talon Strike"],
        mine=["White Knight", "Savannah Lions"], theirs=["Hill Giant"],
    )
    result = game.cast_from_hand(
        0, "Glacial Ray", target_permanent_ids=[giant.permanent_id], splice_cards=[
            {"hand_index": 1, "target_permanent_ids": [knight.permanent_id],
             "cost_permanent_ids": [knight.permanent_id]},
            {"hand_index": 2, "target_permanent_ids": [knight.permanent_id],
             "cost_permanent_ids": [knight.permanent_id]},
        ],
    )
    assert not result.supported
    assert "already pays another splice cost" in result.details
    assert not knight.tapped


@pytest.mark.cr("601.2b")
def test_a_permanent_named_that_cannot_pay_is_refused_never_slid_onto_a_neighbour(set_pool):
    game, (bears, lions), (giant,) = _table(
        set_pool, hand=["Glacial Ray", "Hundred-Talon Strike"],
        mine=["Grizzly Bears", "Savannah Lions"], theirs=["Hill Giant"],
    )
    result = game.cast_from_hand(
        0, "Glacial Ray", target_permanent_ids=[giant.permanent_id], splice_cards=[{
            "hand_index": 1, "target_permanent_ids": [lions.permanent_id],
            "cost_permanent_ids": [bears.permanent_id],
        }],
    )
    assert not result.supported
    assert not bears.tapped and not lions.tapped and giant.damage_marked == 0


@pytest.mark.cr("601.2b")
def test_a_mana_splice_names_nothing_to_pay_with(set_pool):
    game, (bears,), (giant,) = _table(
        set_pool, hand=["Glacial Ray", "Kodama's Might"],
        mine=["Grizzly Bears"], theirs=["Hill Giant"],
    )
    result = game.cast_from_hand(
        0, "Glacial Ray", target_permanent_ids=[giant.permanent_id], splice_cards=[{
            "hand_index": 1, "target_permanent_ids": [bears.permanent_id],
            "cost_permanent_ids": [bears.permanent_id],
        }],
    )
    assert not result.supported and "its splice cost is mana" in result.details


@pytest.mark.cr("601.2h")
def test_the_spells_own_sacrifice_must_still_be_payable_beside_a_splice_return(set_pool):
    """Call for Blood's "As an additional cost to cast this spell, sacrifice a
    creature" and Veil of Secrecy's "Return a blue creature you control to its
    owner's hand": each gate alone says yes on a board of one blue creature,
    and together they cannot both be paid."""
    game, (merfolk,), (giant,) = _table(
        set_pool, hand=["Call for Blood", "Veil of Secrecy"],
        mine=["Merfolk of the Pearl Trident"], theirs=["Hill Giant"],
    )
    refused = game.cast_from_hand(
        0, "Call for Blood", target_permanent_ids=[giant.permanent_id],
        splice_cards=[{"hand_index": 1, "target_permanent_ids": [giant.permanent_id]}],
    )
    assert not refused.supported
    assert "once the splice costs are paid" in refused.details
    assert game.is_on_battlefield(merfolk) and _hand(game) == ["Call for Blood", "Veil of Secrecy"]


@pytest.mark.cr("601.2h")
def test_the_spells_own_sacrifice_takes_what_the_splice_cost_leaves(set_pool):
    game, (merfolk, giant_mine), (bears,) = _table(
        set_pool, hand=["Call for Blood", "Veil of Secrecy"],
        mine=["Merfolk of the Pearl Trident", "Hill Giant"], theirs=["Grizzly Bears"],
    )
    result = game.cast_from_hand(
        0, "Call for Blood", target_permanent_ids=[bears.permanent_id],
        splice_cards=[{"hand_index": 1, "target_permanent_ids": [bears.permanent_id]}],
    )
    assert result.supported, result.details
    settle(game)
    # The Merfolk paid the splice; the Giant paid the spell's own cost.
    assert not game.is_on_battlefield(merfolk) and not game.is_on_battlefield(giant_mine)
    assert "Merfolk of the Pearl Trident" in _hand(game)
    assert "Hill Giant" in [card.name for card in game.players[0].graveyard]
    # -3/-3 off the Giant's power: the Bears are gone.
    assert not game.is_on_battlefield(bears)


@pytest.mark.cr("119.7", "702.47a")
def test_an_opponent_who_cannot_gain_life_cannot_pay_roar_of_jukais_splice(set_pool):
    game, _mine, (giant, _wastes) = _table(
        set_pool, hand=["Glacial Ray", "Roar of Jukai"], mine=["Forest"],
        theirs=["Hill Giant", "Forsaken Wastes"],
    )
    result = game.cast_from_hand(
        0, "Glacial Ray", target_permanent_ids=[giant.permanent_id],
        splice_cards=[{"hand_index": 1}],
    )
    assert not result.supported and "CR 119.7" in result.details
    assert game.players[1].life == 20 and giant.damage_marked == 0
