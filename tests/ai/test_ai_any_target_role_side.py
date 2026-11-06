"""An "any target" role is aimed at its step's side from either chair.

"{T}: Return target card from an opponent's graveyard to their hand. Prevent
all damage that would be dealt to **any target** this turn by a source of your
choice." (Shieldmage Advocate.) CR 115.4's union is a role whose options are
players *and* permanents, and the activation chooser held only the permanent
options to the side the role's own step wants — so a seat option passed
through, and the first option is the first seat in order. Driven in a seeded
game the AI in chair 1 shielded its opponent (W1G3, Judgment). The shield is
the activator's own side, from either chair.
"""
from __future__ import annotations

from unittest import mock

import pytest

from engine import Game, PlayerState, ai_abilities
from engine.ai_abilities import choose_activation_action
from engine.models import Permanent


def _table(set_pool, seat: int) -> Game:
    jud, lea = set_pool("JUD"), set_pool("LEA")
    other = 1 - seat
    game = Game(players=[PlayerState(f"P{i}", library=[lea["Forest"]] * 5) for i in range(2)])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = seat
    game._set_phase_and_step("precombat_main", "precombat_main")
    advocate = Permanent(card=jud["Shieldmage Advocate"])
    game._put_permanent_onto_battlefield(seat, advocate, None)
    advocate.metadata["summoning_sickness_turn"] = -99
    game._put_permanent_onto_battlefield(other, Permanent(card=lea["Hill Giant"]), None)
    game.players[other].graveyard.extend([lea["Swamp"], lea["Island"]])
    return game


@pytest.mark.parametrize("seat", [0, 1])
def test_the_shield_goes_on_the_activators_side_from_either_chair(set_pool, seat):
    """Which side the shield's role is aimed at — asked on an idle board,
    so with the rehearsed "moves nothing" gate (kg4,
    ``ai_abilities._moves_something``) off: a shield with nothing coming is
    not proposed at all."""
    game = _table(set_pool, seat)
    with mock.patch.object(ai_abilities, "_moves_something", lambda *args, **kwargs: True):
        action = choose_activation_action(game, seat)

    assert action is not None and action.permanent_name == "Shieldmage Advocate"
    card_ref, shielded = action.target_role_refs
    assert card_ref["graveyard_seat"] == 1 - seat           # an opponent's pile
    if "seat" in shielded:
        assert shielded["seat"] == seat
    else:
        assert game.controller_index_of(game.permanent_by_id(shielded["permanent_id"])) == seat
