"""The resumable-loop mechanism itself (engine/resumption.py).

A decision can interrupt an event part-way. Answering re-runs that event — but
an event is usually one step of a loop, and re-running the step alone would
leave everything behind it undone. These tests are about the bookkeeping that
prevents that: what is still owed gets recorded, and answering works through it
innermost-first.

The rules these serve are exercised end to end in tests/rules/test_resumption.py;
this file is the mechanism, which is engine internals rather than a CR
semantics question.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.resumption import run_resumable


def _r31_suspend(game: Game) -> None:
    """Make the game suspended the way the engine does: owe somebody a decision
    of a kind registered ``suspends``. ``effect_suspended`` is derived from the
    queue, so there is no flag to poke."""
    game.arm_pending_choice("number_choice", 0, minimum=0, maximum=0)


def _r31_unsuspend(game: Game) -> None:
    game.clear_pending_choices("number_choice")

def test_a_loop_records_only_what_is_still_owed():
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    seen: list[int] = []

    run_resumable(game, [1, 2, 3], seen.append)

    assert seen == [1, 2, 3]
    assert game.resume_stack == [], (
        "a loop that got through must leave nothing behind; a leftover entry is "
        "work nobody will come back for"
    )


def test_a_suspended_step_stops_the_loop_and_records_the_rest():
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    seen: list[int] = []

    def step(item: int) -> None:
        seen.append(item)
        if item == 2:
            _r31_suspend(game)

    run_resumable(game, [1, 2, 3], step)

    assert seen == [1, 2], "step 3 did not run against a step 2 that has not happened"
    assert len(game.resume_stack) == 1

    _r31_unsuspend(game)
    game.resume_stack.pop()()
    assert seen == [1, 2, 3]


def test_nested_loops_resume_innermost_first():
    """The deepest loop is the one whose next step comes soonest, so unwinding
    runs it first. An outer-first order would finish the enclosing work before
    the inner work it contains."""
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    seen: list[str] = []

    def outer(item: str) -> None:
        if item == "b":
            run_resumable(game, ["b1", "b2"], inner)
        else:
            seen.append(item)

    def inner(item: str) -> None:
        seen.append(item)
        if item == "b1":
            _r31_suspend(game)

    run_resumable(game, ["a", "b", "c"], outer)
    assert seen == ["a", "b1"]

    _r31_unsuspend(game)
    while game.resume_stack:
        game.resume_stack.pop()()

    assert seen == ["a", "b1", "b2", "c"], "the inner loop finished before the outer one"


