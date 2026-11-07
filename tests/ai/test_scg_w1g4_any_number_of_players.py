"""How an AI seat aims "any number of target **players** each …" (Scourge's
Reward the Faithful and Cabal Conditioning).

The chain is Wheel and Deal's optional seat roles with the caster admitted
(``target_roles.any_number_of_players_roles``). Read as sideless, the roles
walk took the caster's own seat first — first in seat order at seat 0, and the
only seat a later role could follow at the last seat — so Cabal Conditioning
named its own caster at seat 0 and was never cast at seat 1. The side is now
the seat reading of the loop's body (``ai_slot_sides.announced_roles_loop_side``):
a life gain is a gift and names the caster, a discard a denial and names the
opponents, and the prefix walk then weighs how many of them.
"""

from __future__ import annotations

import pytest

from engine.ai_actions import cast_announcement
from engine.ai_payment import tap_planned_lands
from engine.ai_policy import choose_cast_action
from engine.game import Game
from engine.models import Permanent, PlayerState
from tests.helpers import _nosick, resolve_stack


def _table(set_pool, spell, lands, *, caster, seats=2):
    lea = set_pool("LEA")
    players = [
        PlayerState(
            name="ABC"[seat],
            hand=[set_pool("SCG")[spell]] if seat == caster else [lea["Island"]] * 6,
            library=[lea["Island"]] * 20,
        )
        for seat in range(seats)
    ]
    game = Game(players=players)
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.turn = 4
    game.active_player_index = caster
    for name in [*lands, "Hill Giant"]:
        permanent = Permanent(card=lea[name])
        game._put_permanent_onto_battlefield(caster, permanent, None)
        _nosick(permanent)
    game.current_turn_phase = game.current_step = "precombat_main"
    return game


def _cast(game, seat, action):
    action = tap_planned_lands(game, seat, action)
    result = game.cast_from_hand(seat, action.card_name, **cast_announcement(action))
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    return result


@pytest.mark.parametrize("caster", [0, 1])
def test_reward_the_faithful_heals_only_its_caster(set_pool, caster):
    game = _table(set_pool, "Reward the Faithful", ["Plains"], caster=caster)

    action = choose_cast_action(game, caster)

    assert action is not None and action.card_name == "Reward the Faithful"
    assert action.target_role_refs == [{"seat": caster}]
    assert _cast(game, caster, action).supported
    # Hill Giant (4) is the caster's greatest mana value.
    assert [player.life for player in game.players] == [
        24 if seat == caster else 20 for seat in range(2)
    ], game.log


@pytest.mark.parametrize("caster", [0, 1])
def test_cabal_conditioning_names_the_opponent_and_never_its_caster(set_pool, caster):
    game = _table(set_pool, "Cabal Conditioning", ["Swamp"] * 7, caster=caster)

    action = choose_cast_action(game, caster)

    assert action is not None and action.card_name == "Cabal Conditioning"
    assert action.target_role_refs == [{"seat": 1 - caster}]
    assert _cast(game, caster, action).supported
    assert len(game.players[1 - caster].hand) == 6 - 4, game.log


def test_cabal_conditioning_names_every_opponent_at_a_three_seat_table(set_pool):
    game = _table(set_pool, "Cabal Conditioning", ["Swamp"] * 7, caster=0, seats=3)

    action = choose_cast_action(game, 0)

    assert action is not None and action.target_role_refs == [{"seat": 1}, {"seat": 2}]
    assert _cast(game, 0, action).supported
    assert [len(player.hand) for player in game.players] == [0, 2, 2], game.log
