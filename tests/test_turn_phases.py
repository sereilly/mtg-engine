from engine import Game
from engine.models import PlayerState


def test_start_turn_runs_beginning_phase_and_enters_precombat_main():
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.start_turn(0)

    assert game.current_turn_phase == "precombat_main"
    assert game.current_step == "precombat_main"
    assert game.current_phase == "main"


def test_advance_combat_moves_to_postcombat_main():
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    assert game.current_turn_phase == "combat"
    assert game.current_step == "beginning_of_combat"

    game.advance_combat_phase()
    assert game.current_step == "declare_attackers"

    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"

    game.advance_combat_phase()
    assert game.current_step == "combat_damage"

    game.advance_combat_phase()
    assert game.current_step == "end_of_combat"

    game.advance_combat_phase()
    assert game.current_turn_phase == "postcombat_main"
    assert game.current_step == "postcombat_main"
    assert game.current_phase == "main"


def test_extra_turn_queue_is_lifo():
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.active_player_index = 0

    game.add_extra_turn(0)
    game.add_extra_turn(1)

    assert game.start_next_turn() == 1
    assert game.start_next_turn() == 0


def test_skip_turn_is_applied():
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.active_player_index = 0

    game.skip_next_turn(1)
    assert game.start_next_turn() == 0


def test_additional_step_after_phase_creates_single_step_phase():
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    ok = game.add_additional_step_after_phase("combat", "upkeep", controller_index=0, only_on_controllers_turn=False)

    assert ok
    inserted_phase = game.next_unskipped_phase_after("combat")
    assert inserted_phase is not None
    assert game._phase_steps(inserted_phase) == ("upkeep",)
