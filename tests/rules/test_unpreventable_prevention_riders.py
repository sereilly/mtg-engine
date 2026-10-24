"""CR 615.12: damage that can't be prevented still meets the prevention effects
that would apply to it.

    "If unpreventable damage would be dealt, any applicable prevention effects
    are still applied to it. Those effects won't prevent any damage, but any
    additional effects they have will take place. Existing damage prevention
    shields won't be reduced by damage that can't be prevented."
    "615.12a A prevention effect is applied to any particular unpreventable
    damage event just once."

The engine dropped every prevention contender from a locked event, which is
the right answer for a shield with nothing after its prevention and the wrong
one for the three whose additional effect does not depend on how much was
prevented: Nine Lives ("If damage that a source would deal to you can't be
prevented, you still put an incarnation counter on Nine Lives", 2020-06-23),
Rock Hydra ("…you still remove a +1/+1 counter from it for each 1 damage
dealt", 2008-08-01) and the Phantoms ("…the damage is dealt and a +1/+1 counter
is removed from this creature", 2022-12-08). Each lock is driven by a real
card: Flaring Pain's turn-wide "Damage can't be prevented this turn" and
Lightning Surge's per-spell "and the damage can't be prevented" reach the same
mark.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.pt import add_plus1_counters
from engine.shields import add_shield, make_numeric_pool, shields_on
from tests.helpers import resolve_stack


def _table(catalog_by_name):
    island = catalog_by_name["Island"]
    game = Game(players=[
        PlayerState(name="Alice", library=[island] * 5),
        PlayerState(name="Bob", library=[island] * 5),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 1
    game.current_turn_phase = "main1"
    return game


def _put(game, seat, card):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    resolve_stack(game)
    return permanent


def _cast(game, seat, card, **announcement):
    game.players[seat].hand.append(card)
    result = game.cast_from_hand(seat, card.name, **announcement)
    assert result.supported, result.details
    resolve_stack(game)


def _flaring_pain(game, set_pool):
    _cast(game, 1, set_pool("JUD")["Flaring Pain"])


@pytest.mark.cr("615.12")
def test_nine_lives_still_takes_its_counter_from_damage_that_cannot_be_prevented(
    set_pool, catalog_by_name,
):
    """Flaring Pain, then a bolt at Nine Lives' controller: the 3 is dealt and
    the enchantment still gets its incarnation counter."""
    game = _table(catalog_by_name)
    nine_lives = _put(game, 0, catalog_by_name["Nine Lives"])
    _flaring_pain(game, set_pool)
    _cast(game, 1, catalog_by_name["Lightning Bolt"], target_player_index=0)

    assert game.players[0].life == 17
    assert nine_lives.metadata.get("incarnation_counters") == 1


@pytest.mark.cr("615.12")
def test_rock_hydra_still_pays_a_counter_for_each_point_dealt(
    set_pool, catalog_by_name,
):
    """Rock Hydra with five counters takes an unpreventable Shock: both points
    are dealt (2 damage marked) and two counters come off for them."""
    game = _table(catalog_by_name)
    hydra = _put(game, 0, catalog_by_name["Rock Hydra"])
    add_plus1_counters(hydra, 5)
    _flaring_pain(game, set_pool)
    _cast(
        game, 1, catalog_by_name["Shock"], target_player_index=0,
        target_permanent_ids=[hydra.permanent_id],
    )

    assert hydra.damage_marked == 2
    assert int(hydra.metadata.get("plus_counters", 0)) == 3
    assert game.is_on_battlefield(hydra)


@pytest.mark.cr("615.12")
def test_a_shield_with_nothing_after_it_is_neither_applied_nor_spent(
    set_pool, catalog_by_name,
):
    """"Existing damage prevention shields won't be reduced by damage that
    can't be prevented." A five-point pool on the player is still five points
    after an unpreventable bolt is dealt in full."""
    game = _table(catalog_by_name)
    pool = add_shield(game.players[0], make_numeric_pool(5, source_name="Healing Salve"))
    _flaring_pain(game, set_pool)
    _cast(game, 1, catalog_by_name["Lightning Bolt"], target_player_index=0)

    assert game.players[0].life == 17
    assert pool in shields_on(game.players[0]) and pool.amount == 5


@pytest.mark.cr("615.12a")
def test_a_phantom_rider_is_applied_once_to_one_unpreventable_event(
    set_pool, catalog_by_name,
):
    """The rider prevents nothing, so the event it leaves behind is the event
    it was applied to — and CR 615.12a applies it to that event once. Phantom
    Tiger (two counters) under Lightning Surge's threshold loses exactly one
    counter, not one per round of CR 616.1f's re-asking."""
    jud = set_pool("JUD")
    game = _table(catalog_by_name)
    game.players[1].graveyard = [catalog_by_name["Island"]] * 7
    tiger = _put(game, 0, jud["Phantom Tiger"])
    add_plus1_counters(tiger, 6)  # eight counters: a 9/8
    _cast(
        game, 1, jud["Lightning Surge"], target_player_index=0,
        target_permanent_ids=[tiger.permanent_id],
    )
    game._settle()

    assert tiger.damage_marked == 6
    assert int(tiger.metadata.get("plus_counters", 0)) == 7
    assert game.is_on_battlefield(tiger), "an 8/7 with 6 damage marked"
