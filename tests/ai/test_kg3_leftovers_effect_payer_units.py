"""The effect payer credits a land what one tap of it really adds.

"Counter target spell unless its controller pays {3}." (Mana Leak.) The
payer has no priority window, so the engine taps lands for it
(``Game._pay_planned_cost``) and chooses which with the payer's other wants in
view (``mana_payment._sparing_choice``). It planned every land as **one**
mana, so Ancient Tomb's {C}{C} was one unit: on a Tomb, two Plains and a
Mountain, with White Knight ({W}{W}) in hand, no set of three "units" kept the
Knight payable, the price decided, and the Plains paid beside the Mountain —
leaving a Tomb that cannot cast a Knight. The Tomb and the Mountain pay {3}
and leave both Plains.

The census is ``tests/ai/test_kg3_payment_drawback_census.py`` (its
``multi_mana`` rows, now counted); this drives the board through a real Mana
Leak, for a seat nobody asks and for a seat that answers "pay".
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest import mock

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import settle

_CARDS = {card.name: card for card in load_catalog()}


def _ready(name: str) -> Permanent:
    permanent = Permanent(card=_CARDS[name])
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _leaked(interactive: bool) -> Game:
    """Seat 1's Lightning Bolt on the stack at seat 0, Mana Leak cast at it:
    seat 1 owes Mana Leak's {3} on a Tomb, two Plains and a Mountain."""
    payer = PlayerState(
        name="P0", hand=[_CARDS["Mana Leak"]], library=[_CARDS["Island"]] * 5,
    )
    victim = PlayerState(
        name="P1", hand=[_CARDS["Lightning Bolt"], _CARDS["White Knight"]],
        library=[_CARDS["Plains"]] * 5,
        battlefield=[_ready(name) for name in ("Ancient Tomb", "Plains", "Plains", "Mountain")],
    )
    game = Game(players=[payer, victim])
    game.enforce_mana_costs = False
    game.interactive_seats = {1} if interactive else set()
    game.active_player_index = 1
    game._set_phase_and_step("precombat_main", "precombat_main")
    game._recompute_continuous_effects()
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    game.cast_from_hand(0, "Mana Leak", target_stack_index=0)
    return game


def _tapped(game: Game) -> list[str]:
    return sorted(p.card.name for p in game.controlled_by(1) if p.tapped)


@contextmanager
def _one_mana_per_land():
    from engine import board_payment

    with mock.patch.object(board_payment, "land_payment_units", lambda game, land: None):
        yield


def _paid_by_a_seat_nobody_asks() -> Game:
    game = _leaked(interactive=False)
    settle(game)
    return game


def _paid_by_an_asked_seat() -> Game:
    game = _leaked(interactive=True)
    assert game.pending_choice_of("mana_payment", 1) is not None, game.log
    assert game.confirm_mana_payment(1, True)
    settle(game)
    return game


@pytest.mark.parametrize("pay", [_paid_by_a_seat_nobody_asks, _paid_by_an_asked_seat])
def test_the_tomb_and_the_mountain_pay_and_the_knight_stays_castable(pay):
    game = pay()
    victim = game.players[1]
    assert any("is not countered" in line for line in game.log), game.log
    # The Bolt was not countered: it resolved at seat 0.
    assert game.players[0].life == 17, game.log
    assert _tapped(game) == ["Ancient Tomb", "Mountain"], game.log
    # The Tomb's own price is paid: it deals 2 damage to its controller.
    assert victim.life == 18, game.log
    # …and both Plains are left for White Knight's {W}{W}.
    untapped = sorted(p.card.name for p in game.controlled_by(1) if not p.tapped)
    assert untapped == ["Plains", "Plains"]


@pytest.mark.parametrize("pay", [_paid_by_a_seat_nobody_asks, _paid_by_an_asked_seat])
def test_backwards_one_mana_per_land_strands_the_knight(pay):
    with _one_mana_per_land():
        game = pay()
    assert any("is not countered" in line for line in game.log), game.log
    assert "Ancient Tomb" not in _tapped(game), game.log
