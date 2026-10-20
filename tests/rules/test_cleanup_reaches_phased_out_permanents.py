"""CR 514.2 reaches phased-out permanents, and CR 702.26f is what that means.

"All damage marked on permanents (including phased-out permanents) is removed
and all 'until end of turn' and 'this turn' effects end" — and an effect that
expires while its permanent is phased out "will no longer affect that
permanent once it's phased in". The cleanup sweep walked the battlefield
alone, so a phased-out creature kept its turn's pump and its damage across the
turn boundary. Found by the AI simulator once its seats had priority on the
opponent's turn: a Seedling Charm's trample, granted in response to a Reality
Ripple, rehearsed as lasting — correctly, for an engine that let it last.
"""
import pytest

from engine import Game, PlayerState
from engine.models import Permanent


def _board(set_pool, *, hand):
    lea, mir = set_pool("LEA"), set_pool("MIR")
    cards = {**lea, **mir}
    game = Game(players=[
        PlayerState(name="P0", hand=[cards[name] for name in hand], library=[cards["Forest"]] * 6),
        PlayerState(name="P1", hand=[cards["Reality Ripple"]], library=[cards["Forest"]] * 6),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    bears = Permanent(card=cards["Grizzly Bears"])
    game._put_permanent_onto_battlefield(0, bears, None)
    return game, bears


def _phase_out_and_end_the_turn(game, bears):
    game.active_player_index = 1
    assert game.cast_from_hand(1, "Reality Ripple", target_permanent_ids=[bears.permanent_id]).supported
    assert any(p is bears for p in game.players[0].phased_out)
    game._set_phase_and_step("ending", "end")
    game.resolve_cleanup_step(1)
    game.start_turn(0)
    assert game.is_on_battlefield(bears)


@pytest.mark.cr("514.2", "702.26f")
def test_an_until_end_of_turn_pump_ends_while_its_creature_is_phased_out(set_pool):
    game, bears = _board(set_pool, hand=["Giant Growth"])
    assert game.cast_from_hand(0, "Giant Growth", target_permanent_ids=[bears.permanent_id]).supported
    assert (bears.effective_power, bears.effective_toughness) == (5, 5)

    _phase_out_and_end_the_turn(game, bears)

    assert (bears.effective_power, bears.effective_toughness) == (2, 2)


@pytest.mark.cr("514.2")
def test_damage_marked_on_a_phased_out_creature_is_removed(set_pool):
    game, bears = _board(set_pool, hand=[])
    bears.damage_marked = 1

    _phase_out_and_end_the_turn(game, bears)

    assert bears.damage_marked == 0
