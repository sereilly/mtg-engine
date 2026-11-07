"""Undiscovered Paradise returns at its controller's next untap step whether
or not it untaps.

"During your next untap step, as you untap your permanents, return this land
to its owner's hand." Its rulings (2004-10-04): "It will return even if some
effect prevents you from untapping it. The ability is not replacing the
untapping of the land in any way." and "Only returns to owner's hand if it is
still on the battlefield at the beginning of its controller's next untap."

The engine registered it as a ``would_untap`` replacement, reached only by a
permanent about to untap — so a Paradise kept tapped stayed on the
battlefield, marked for a step the ability never named; and beside Freyalise's
Winds (which puts a wind counter on every permanent that becomes tapped, the
Paradise tapped for its mana included) the two read as CR 616.1 contenders for
one untap, and Winds' default took the return away. Round kg4 `asks` found it
classifying the untap step's replacement site.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.named_counters import counters_on
from tests.helpers import resolve_stack

_POOL = {card.name: card for card in load_catalog()}


def _table(interactive: bool) -> Game:
    game = Game(players=[
        PlayerState(f"P{index}", library=[_POOL["Island"]] * 8) for index in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.begin_turn_bookkeeping(0)
    game.resolve_untap_step(0)
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game


def _put(game: Game, seat: int, name: str) -> Permanent:
    permanent = Permanent(card=_POOL[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    resolve_stack(game)
    game.pending_choices.clear()
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _tap_paradise_for_mana(game: Game) -> Permanent:
    paradise = _put(game, 0, "Undiscovered Paradise")
    result = game.activate_permanent_ability(0, "Undiscovered Paradise", mana_color="U")
    assert result.supported, result.details
    assert paradise.tapped and game.players[0].mana_pool["U"] == 1
    return paradise


def _hand(game: Game, seat: int = 0) -> list[str]:
    return [card.name for card in game.players[seat].hand]


@pytest.mark.parametrize("interactive", [False, True])
def test_a_wind_counter_does_not_keep_paradise_on_the_battlefield(interactive):
    """Freyalise's Winds puts a counter on the Paradise as it is tapped for
    mana; at the next untap step the land returns all the same, and nobody is
    asked to choose between the two — there is only one replacement."""
    game = _table(interactive)
    _put(game, 1, "Freyalise's Winds")
    forest = _put(game, 0, "Forest")
    game.become_tapped(forest)
    paradise = _tap_paradise_for_mana(game)
    resolve_stack(game)  # Winds' "whenever a permanent becomes tapped"
    assert counters_on(paradise, "wind") == 1 and counters_on(forest, "wind") == 1

    game.begin_turn_bookkeeping(0)
    game.resolve_untap_step(0)

    assert not game.is_on_battlefield(paradise)
    assert _hand(game) == ["Undiscovered Paradise"]
    assert not game.pending_choices
    # The Forest's own wind counter still replaced its untap.
    assert forest.tapped and counters_on(forest, "wind") == 0


def test_a_paradise_its_untap_is_prevented_for_returns_all_the_same():
    """Mana Vapors keeps the seat's lands tapped through its next untap step;
    the Paradise goes back to its owner's hand as that step begins."""
    game = _table(False)
    paradise = _tap_paradise_for_mana(game)
    game.players[1].hand.append(_POOL["Mana Vapors"])
    assert game.queue_from_hand(1, "Mana Vapors", target_player_index=0).supported
    resolve_stack(game)

    game.begin_turn_bookkeeping(0)
    game.resolve_untap_step(0)

    assert not game.is_on_battlefield(paradise)
    assert _hand(game) == ["Undiscovered Paradise"]


def test_a_paradise_another_player_took_still_returns_at_the_step_named():
    """"During **your** next untap step": the ability's controller's step,
    whoever controls the land by then — and "its owner's hand"."""
    from engine.control import change_control

    game = _table(False)
    paradise = _tap_paradise_for_mana(game)
    change_control(paradise, 1, source="test")
    game._sync_control()
    assert any(permanent is paradise for permanent in game.controlled_by(1))

    game.begin_turn_bookkeeping(1)
    game.resolve_untap_step(1)
    assert game.is_on_battlefield(paradise), "not the step the ability named"
    assert not paradise.tapped, "its new controller's step untaps it"

    game.begin_turn_bookkeeping(0)
    game.resolve_untap_step(0)
    assert not game.is_on_battlefield(paradise)
    assert _hand(game, 0) == ["Undiscovered Paradise"] and _hand(game, 1) == []
