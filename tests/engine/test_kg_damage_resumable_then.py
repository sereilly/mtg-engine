"""``run_resumable``'s ``then``: the loop's own last step.

Work written after a resumable loop does not run when one of its steps
suspends (``engine/resumption.py``), so a loop's summary — a sweep's log line,
a record about the whole loop — has to be a step of the loop. ``then`` is that
step: run once, after the last item, whether the loop went straight through or
was brought back by an answer.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.resumption import resume_after_answer, run_resumable


def _game() -> Game:
    return Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])


def test_then_runs_once_after_every_item_when_nothing_suspends():
    game = _game()
    seen: list = []
    run_resumable(game, [1, 2, 3], seen.append, then=lambda: seen.append("done"))
    assert seen == [1, 2, 3, "done"]
    assert game.resume_stack == []


def test_then_runs_with_an_empty_loop():
    game = _game()
    seen: list = []
    run_resumable(game, [], seen.append, then=lambda: seen.append("done"))
    assert seen == ["done"]
    assert game.resume_stack == []


def test_then_waits_for_the_answer_when_an_item_suspends():
    game = _game()
    seen: list = []

    def step(item) -> None:
        seen.append(item)
        if item == 2:
            game.arm_pending_choice("number_choice", 0, minimum=0, maximum=0)

    run_resumable(game, [1, 2, 3], step, then=lambda: seen.append("done"))
    assert seen == [1, 2], "the item behind the one that asked, and the summary, wait"

    game.clear_pending_choices("number_choice")
    resume_after_answer(game)
    assert seen == [1, 2, 3, "done"]
    assert game.resume_stack == []
