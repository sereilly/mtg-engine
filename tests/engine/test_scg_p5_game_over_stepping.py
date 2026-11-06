"""CR 104.1: once the game has ended, the engine's stepping goes no further
(SCG Phase 5, W2).

Smoke game 2, turn 18: Sulfuric Vortex took the person to 0 in their upkeep,
the log read "Player 1 lost the game (704.5a)" and then "Player 1 drew 1
card(s) in draw step", and the game's final state was a precombat main phase.
The web layer's beginning phase ran the draw step and entered the main phase
without asking ``is_game_over()``; so did the headless ``Game.start_turn``.

The guard is the engine's (``engine/game_over_guard.py``): every entry point a
driver steps a turn through, and the one unit of play every window resolves
with (``resolve_next_object``). This census asks every one of them, on a game
that has ended with a spell still on the stack, whether calling it changes
anything — the log, the phase or step, the turn, a hand, a library, the stack,
who is active — and holds the list to every method of ``Game`` its names
match, so a new stepping entry point arrives with its row.
"""

from __future__ import annotations

import re

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog

_CARDS = {card.name: card for card in load_catalog()}

#: Every stepping entry point, with the arguments a driver calls it with.
_ENTRY_POINTS = {
    "begin_turn_bookkeeping": ((1,), {}),
    "start_turn": ((1,), {}),
    "start_next_turn": ((), {}),
    "resolve_untap_step": ((1,), {}),
    "resolve_upkeep": ((1,), {}),
    "resolve_draw_step": ((1,), {}),
    "close_beginning_step": ((), {}),
    "enter_turn_phase": (("precombat_main",), {}),
    "enter_next_turn_phase": (("beginning",), {}),
    "_close_current_priority_step": ((), {}),
    "advance_combat_phase": ((), {}),
    "end_combat": ((), {}),
    "resolve_end_step": ((1,), {}),
    "close_end_step": ((), {}),
    "resolve_cleanup_step": ((1,), {}),
    "_resolve_priority_window": ((), {}),
    "pass_priority": ((0,), {}),
    "resolve_next_object": ((), {"pause_for_choices": False}),
}

#: What a stepping entry point is called — the names the census holds the
#: table to.
_STEPPING = re.compile(
    r"^(resolve_\w+_step|resolve_upkeep|close_\w+_step|_close_current_priority_step"
    r"|enter_(next_)?turn_phase|start_(next_)?turn|end_combat|advance_combat_phase"
    r"|begin_turn_bookkeeping|_resolve_priority_window|pass_priority|resolve_next_object)$"
)


def _ended_game() -> Game:
    """Seat 1 lost to Lightning Bolt's predecessor (0 life, CR 704.5a) in
    seat 0's precombat main phase, with seat 0's Lightning Bolt still on the
    stack aimed at it and both libraries stocked."""
    library = [_CARDS["Island"]] * 10
    game = Game(players=[
        PlayerState(name="P0", life=20, library=list(library), hand=[_CARDS["Lightning Bolt"]]),
        PlayerState(name="P1", life=20, library=list(library), hand=[_CARDS["Island"]] * 3),
    ])
    game.turn = 4
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    game.start_priority_window(0)
    result = game.queue_from_hand(0, "Lightning Bolt", target_player_index=1)
    assert result.supported and game.stack, result.details
    game.players[1].life = 0
    game.check_state_based_actions()
    assert game.is_game_over()
    return game


def _picture(game: Game) -> tuple:
    return (
        len(game.log),
        game.current_turn_phase,
        game.current_step,
        game.turn,
        game.active_player_index,
        [len(player.hand) for player in game.players],
        [len(player.library) for player in game.players],
        [item.card.name for item in game.stack],
        [player.life for player in game.players],
    )


@pytest.mark.parametrize("name", sorted(_ENTRY_POINTS))
def test_a_stepping_entry_point_does_nothing_once_the_game_is_over(name):
    game = _ended_game()
    before = _picture(game)
    args, kwargs = _ENTRY_POINTS[name]
    getattr(game, name)(*args, **kwargs)
    assert _picture(game) == before, (name, game.log[before[0]:])


def test_every_stepping_entry_point_is_in_the_census_and_guarded():
    from engine.game_over_guard import GUARDED

    stepping = {name for name in dir(Game) if _STEPPING.match(name)}
    assert len(stepping) >= 15, sorted(stepping)
    assert stepping == set(_ENTRY_POINTS), sorted(stepping ^ set(_ENTRY_POINTS))
    unguarded = sorted(name for name in stepping if not getattr(getattr(Game, name), GUARDED, False))
    assert not unguarded, unguarded


def test_a_multiplayer_game_one_player_left_still_steps():
    """CR 800.4a: in a game of three, one player leaving does not end it —
    the guard asks ``is_game_over``, which is False, so the turn goes on."""
    library = [_CARDS["Island"]] * 10
    game = Game(players=[
        PlayerState(name=f"P{seat}", life=20, library=list(library)) for seat in range(3)
    ])
    game.turn = 4
    game.active_player_index = 0
    game.players[2].life = 0
    game.check_state_based_actions()
    assert game.players[2].lost and not game.is_game_over()
    drawn = game.resolve_draw_step(0)
    assert drawn == 1 and len(game.players[0].library) == 9, game.log[-4:]
