"""An offer is gated on its *action*, never on the "if you do" steps behind it.

"Whenever this creature deals combat damage to a player, you may draw a card.
If you do, discard a card." (Jeskai Elder, M21.) The offer's takeability gate
(``handlers/offers._narrow_to_takeable_actions``) was asked of the whole accept
branch — the draw *and* the discard — before the draw had happened, so a seat
with an empty hand was never offered the draw: the discard had nothing to
discard yet. The answer path re-asked the same question
(``_optional_action_still_takeable``) and turned an accepted offer into a
decline. CR 608.2c follows the instructions in order; the consequence is
measured after the action.

Found driving Mask of Memory (Mirrodin), whose sentence is the same with two
cards. A census over the pool (both manifest roles, 977 compiled ``may``
instructions) found four whose if-you-do branch holds a step the gate can
refuse: Jeskai Elder, Sanctum of Calm Waters, Mask of Memory (a discard each)
and Genesis (a targeted return, which the gate answers True for).
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import declare_attack, resolve_stack


def _table(set_pool, interactive: bool):
    island = set_pool("LEA")["Island"]
    game = Game(players=[
        PlayerState(name=f"P{seat}", life=20, library=[island] * 10)
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.start_turn(0)
    elder = Permanent(card=set_pool("M21")["Jeskai Elder"])
    game._put_permanent_onto_battlefield(0, elder, None)
    elder.metadata["summoning_sickness_turn"] = -99
    game._settle()
    game.players[0].hand = []
    return game


@pytest.mark.parametrize("interactive", [False, True])
def test_jeskai_elder_loots_from_an_empty_hand(set_pool, interactive):
    game = _table(set_pool, interactive)
    library = len(game.players[0].library)

    declare_attack(game, 0)
    game.advance_combat_phase()
    assert game.players[1].life == 19  # a 1/2
    if interactive:
        # At a table with a person the damage step gives the active player
        # priority over what the damage set off (CR 510.3, 117.4): the
        # trigger resolves once both have passed.
        assert [item.card.name for item in game.stack] == ["Jeskai Elder"], game.log[-4:]
        game.pass_priority(0)
        game.pass_priority(1)
    assert [c.kind for c in game.pending_choices] == ["optional_pay"], game.log[-4:]
    if interactive:
        assert game.resolve_pending_choice("optional_pay", 0, accept=True)
        assert [c.kind for c in game.pending_choices] == ["discard"]
        assert game.resolve_pending_choice(
            "discard", 0, hand_indices=[0], to_library=False
        )
    else:
        game.auto_resolve_pending_choices()
    resolve_stack(game)

    assert len(game.players[0].library) == library - 1, game.log[-6:]
    assert [card.name for card in game.players[0].graveyard] == ["Island"]
    assert game.players[0].hand == []
