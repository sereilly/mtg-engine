"""Combat stops when the game ends (CR 104.1), and goes on when a multiplayer
game only loses a player (CR 800.4a).

Found in Legions' Phase 5, game 1: the human was killed by first-strike
damage, and the regular combat damage step was dealt afterwards (life -1 -> -4).
"Player ... lost the game" was also logged before the damage line that caused
it — the step's state-based check ran ahead of its summary.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from web.game_flow import _advance_ai_turn
from web.session_store import Session

_CATALOG = {card.name: card for card in load_catalog()}


def _permanent(name: str) -> Permanent:
    permanent = Permanent(card=_CATALOG[name])
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _table(seats: int) -> Game:
    """Seat 0's precombat main phase, with Elvish Archers (2/1 first strike)
    and Grizzly Bears (2/2), entered the turn's own way."""
    game = Game(players=[
        PlayerState(name=f"P{seat}", library=[_CATALOG["Forest"]] * 10)
        for seat in range(seats)
    ])
    game.enforce_mana_costs = False
    game.players[0].battlefield = [_permanent("Elvish Archers"), _permanent("Grizzly Bears")]
    game._sync_control()
    game.begin_turn_bookkeeping(0)
    game._set_phase_and_step("beginning", "draw")
    game.enter_next_turn_phase("beginning")
    game._close_current_priority_step()
    game.enter_next_turn_phase("precombat_main")
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.current_step == "declare_attackers"
    return game


def _damage_lines(game: Game, name: str) -> list[int]:
    return [i for i, line in enumerate(game.log) if line.startswith(f"{name} took ")]


@pytest.mark.cr("104.1", "510.4")
def test_a_first_strike_kill_ends_the_game_before_the_regular_step():
    game = _table(2)
    game.players[1].life = 2
    assert game.declare_attackers(0, [0, 1], 1)[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {})[0]
    game.advance_combat_phase()

    assert game.is_game_over()
    # The Archers' 2, and not the Bears' 2 after it.
    assert game.players[1].life == 0, game.log[-6:]
    assert len(_damage_lines(game, "P1")) == 1
    assert "Resolved combat damage" not in game.log
    # Nothing further happens: the rail does not leave the step.
    step = (game.current_turn_phase, game.current_step)
    game.advance_combat_phase()
    assert (game.current_turn_phase, game.current_step) == step == ("combat", "combat_damage")
    assert game.players[1].life == 0


@pytest.mark.cr("704.5a")
def test_the_damage_is_logged_before_the_loss_it_causes():
    game = _table(2)
    game.players[1].life = 2
    game.declare_attackers(0, [0], 1)
    game.advance_combat_phase()
    game.declare_blockers(1, {})
    game.advance_combat_phase()

    took = _damage_lines(game, "P1")
    lost = [i for i, line in enumerate(game.log) if line.startswith("P1 lost the game")]
    assert took and lost and took[0] < lost[0], game.log[-6:]


@pytest.mark.cr("800.4a", "510.4")
def test_in_multiplayer_the_regular_step_goes_on_without_the_player_who_left():
    game = _table(3)
    game.players[1].life = 2
    game.players[1].battlefield = [_permanent("Llanowar Elves")]
    game._sync_control()
    assert game.declare_attackers(0, [0, 1], attacker_targets={0: 1, 1: 2})[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {})[0]
    assert game.declare_blockers(2, {})[0]
    game.advance_combat_phase()

    assert game.players[1].lost and not game.is_game_over()
    # P1's permanents left with P1 (CR 800.4a)…
    assert not game.players[1].battlefield
    # …and the Bears' regular-step damage still reached P2.
    assert game.players[2].life == 18
    assert game.current_step == "end_of_combat"


@pytest.mark.cr("104.1")
def test_the_web_layer_does_not_walk_an_ended_game_on():
    """An AI's first striker kills the human on the AI's turn: the human's life
    stops at 0 and the AI's turn does not go on to its end step."""
    game = Game(players=[
        PlayerState(name="Human", library=[_CATALOG["Forest"]] * 10),
        PlayerState(name="AI", library=[_CATALOG["Forest"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game.players[1].battlefield = [_permanent("Elvish Archers"), _permanent("Grizzly Bears")]
    game.players[0].life = 2
    game._sync_control()
    session = Session(
        id="c1-game-over", mode="human_vs_ai", host_name="Human", guest_name="AI",
        game=game, seat_types={0: "human", 1: "ai"},
    )
    session.current_turn = 1
    game.active_player_index = 1
    game.begin_turn_bookkeeping(1)
    game._set_phase_and_step("beginning", "draw")
    game.enter_next_turn_phase("beginning")
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(1, [0, 1], 0)[0]
    game.advance_combat_phase()
    assert game.declare_blockers(0, {})[0]

    _advance_ai_turn(session)

    assert game.is_game_over()
    assert game.players[0].life == 0, game.log[-6:]
    assert game.current_turn_phase == "combat"
