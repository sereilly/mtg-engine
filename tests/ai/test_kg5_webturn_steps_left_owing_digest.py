"""The simulator's step-leaving instrument is not part of a position.

``ai_simulator._SimulatedGame`` counts what each step leaves owed as the next
one begins (``SimulationReport.steps_left_owing``) in its instance
``__dict__`` (``_steps_left_owing``), so ``ai_rehearsal.position_digest`` —
which reads every field of ``vars(game)`` its bookkeeping list does not name
— read it in simulator games and in no web game: a rehearsal's "did the cast
change anything" asked one more question at the simulator's table than at the
web's, and two scratch copies whose run-out had left a step around something
differently read as different positions by the count alone.
"""

from __future__ import annotations

import copy

from engine.ai_rehearsal import _GAME_BOOKKEEPING, position_digest, same_position
from engine.ai_simulator import _SimulatedGame
from engine.models import PlayerState


def _counted_table(catalog_by_name) -> _SimulatedGame:
    named = catalog_by_name
    game = _SimulatedGame(players=[
        PlayerState(name="A", library=[named["Forest"]] * 10),
        PlayerState(name="B", library=[named["Forest"]] * 10),
    ])
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    game._set_phase_and_step("combat", "beginning_of_combat")
    return game


def test_the_step_counter_is_bookkeeping_to_the_digest(catalog_by_name):
    """A simulated table that has left a step: the instrument has counted
    (the floor), the field it counts in is one ``vars(game)`` carries, and
    the digest reads the table as a web game's table — without it."""
    game = _counted_table(catalog_by_name)
    assert game._steps_left_owing["_examined"] >= 1
    slots = [key for key, value in vars(game).items() if value is game._steps_left_owing]
    assert slots, "the instrument no longer lives in the instance dict: re-read this test"
    assert set(slots) <= _GAME_BOOKKEEPING

    as_the_web_reads_it = copy.deepcopy(game)
    for slot in slots:
        del as_the_web_reads_it.__dict__[slot]
    assert position_digest(game)["game"] == position_digest(as_the_web_reads_it)["game"]


def test_two_copies_counted_differently_are_one_position(catalog_by_name):
    """Two scratch copies of one simulated table, one of which has counted a
    step left around an owed prompt: nothing a player could point at
    differs, so they are the same position."""
    game = _counted_table(catalog_by_name)
    untouched, counted = copy.deepcopy(game), copy.deepcopy(game)
    counted._steps_left_owing["beginning_of_combat -> declare_attackers: choose_mode"] += 1
    assert same_position(position_digest(untouched), position_digest(counted))
