"""Web of Inertia's "you" is the trigger's controller, even after the Web
changes hands.

"At the beginning of combat on each opponent's turn, that player may exile a
card from their graveyard. If the player doesn't, creatures they control
can't attack **you** this turn." CR 109.5: "you" on a triggered ability is
"the controller of the object when the ability triggered"; CR 603.3a puts the
ability on the stack under that player. Judgment's W1G5 measured the read as
the Web's controller *when the branch runs* — the same seat unless control
of the Web changes while its trigger waits — because the offer to the event's
seat moves ``caster`` onto that seat for its branches, and nothing on the
context kept the seat it moved off. The stack item does keep it
(``caster_index``), so the offer's rebind now carries it forward
(``OracleExecutionContext.ability_controller``).

Driven both ways an offer can end in the restriction: no card to exile (no
offer made, CR 608.2d) and an offer declined by an interactive seat.
"""

from __future__ import annotations

import pytest

from engine.control import change_control
from tests.sets import jud_w1g5_helpers as _helpers


def _web_changes_hands(set_pool, *, graveyard):
    """Seat 0's Web at the beginning of seat 1's combat, its trigger on the
    stack — and then seat 1 takes control of the Web."""
    game = _helpers.table(set_pool, hands=([], [], []), interactive=(0, 1))
    game.players[1].graveyard.extend([_helpers.card(set_pool, "Forest")] * graveyard)
    web = _helpers.put(game, set_pool, 0, "Web of Inertia")
    giant = _helpers.put(game, set_pool, 1, "Hill Giant")
    game.start_turn(1)
    game._close_current_priority_step()
    game.advance_combat_phase()
    assert [item.card.name for item in game.stack] == ["Web of Inertia"]
    assert game.stack[-1].caster_index == 0, "CR 603.3a: the Web's controller then"

    change_control(web, 1, source="a test's theft")
    game._sync_control()
    assert game.controller_index_of(web) == 1
    return game, giant


@pytest.mark.parametrize("graveyard", [0, 2], ids=["nothing to exile", "declined"])
def test_the_web_protects_the_player_who_controlled_it_as_it_triggered(set_pool, graveyard):
    game, giant = _web_changes_hands(set_pool, graveyard=graveyard)
    game.resolve_top_of_stack(pause_for_choices=True)
    if graveyard:
        assert _helpers.owed(game) == [1]
        assert game.confirm_optional_pay(1, accept=False)
    _helpers.settle(game)

    # "Creatures they control" are seat 1's, and "you" is seat 0.
    assert not game.can_attack(giant, 0), "the trigger's controller is protected"
    assert game.can_attack(giant, 2), "and nobody else"
