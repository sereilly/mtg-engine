"""A turn the seat will skip is priced in its standing (kg5 aiact).

``ai_standing.seat_standing`` read life, cards and permanents and nothing
else a seat owes, so "You skip your next turn" (``Game.skip_turn_counts``,
CR 614.10) was free: Chronatog's "{0}: +3/+3 until end of turn. You skip your
next turn." was activated for three points of damage at 20 life, Meditate
drew four for nothing, and the first of Lethal Vapors' three missing readers
(Known gaps, "AI leftovers") was this one. Each pending skip now costs
``SKIPPED_TURN_WORTH`` (two cards: the draw, the land drop, the untap and
the attack the turn would have made).

Validated backwards: with the base standing, Chronatog pumps at 20 and at 8
life, where the three damage decide nothing.
"""

from __future__ import annotations

from engine.ai_abilities import choose_activation_action
from engine.ai_simulator import SimulationReport, _play_activations
from engine.ai_standing import SKIPPED_TURN_WORTH, seat_standing
from engine.game import Game
from engine.models import Permanent, PlayerState
from tests.helpers import declare_attack, drive_combat, stock_libraries


def _board(mine=(), *, their_life: int = 20):
    """The AI's precombat main phase, costs enforced, nothing summoning sick."""
    game = Game(players=[PlayerState(name="AI"), PlayerState(name="Opp")])
    stock_libraries(game)
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.turn = 5
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    for card in mine:
        game._put_permanent_onto_battlefield(0, Permanent(card=card), None)
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    game.players[1].life = their_life
    return game


def test_a_pending_skip_costs_the_seat_two_cards_a_turn():
    game = _board()
    before = seat_standing(game, 0)
    game.skip_turn_counts[0] = 2
    assert seat_standing(game, 0) == before - 2 * SKIPPED_TURN_WORTH
    assert seat_standing(game, 1) == seat_standing(_board(), 1)


def test_chronatog_skips_no_turn_for_damage_that_decides_nothing(set_pool):
    """A lone Chronatog (1/2) against an empty board: three more damage at 20
    or at 8 life is not worth a turn."""
    chronatog = set_pool("VIS")["Chronatog"]
    for life in (20, 8):
        assert choose_activation_action(_board([chronatog], their_life=life), 0) is None, life


def test_chronatog_skips_a_turn_to_win(set_pool):
    """At 4 life the +3/+3 makes the 1/2's attack lethal: the turn skipped is
    never taken. Driven through the simulator's executor and the fight."""
    game = _board([set_pool("VIS")["Chronatog"]], their_life=4)
    report = SimulationReport(games_requested=1, games_completed=0, interaction_count=0)
    _play_activations(game, 0, report, 1, 1)
    assert not report.refused_activations, report.refused_activations
    assert game.skip_turn_counts.get(0) == 1
    declare_attack(game, 0)
    drive_combat(game)
    assert game.players[1].life <= 0
