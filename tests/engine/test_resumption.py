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




# ---------------------------------------------------------------------------
# The loops in engine/handlers/control_flow.py
# ---------------------------------------------------------------------------


def _r33_board(names: list[str]) -> Game:
    """Seat 0 holding one 1/1 creature per name, and a seat 1 with nothing."""
    from engine.models import Permanent
    from tests.helpers import _mk_creature_card

    seat0 = PlayerState(
        name="P1", battlefield=[Permanent(card=_mk_creature_card(n, 1, 1)) for n in names]
    )
    return Game(players=[seat0, PlayerState(name="P2")])


def _r33_for_each(game: Game, steps: tuple) -> None:
    """Run ``for_each`` over every creature on the board with *steps* as its body."""
    from engine.game_types import OracleExecutionContext
    from engine.handlers.registry import EFFECT_HANDLERS
    from engine.oracle_types import OracleInstruction
    from tests.helpers import _mk_card

    card = _mk_card("Iterator", "Sorcery")
    context = OracleExecutionContext(
        caster=game.players[0], target=game.players[1], card=card
    )
    EFFECT_HANDLERS["for_each"](
        game,
        OracleInstruction(
            "for_each", "", {"iterator": {"type_filter": "creature"}, "effect": steps}
        ),
        context,
    )


def test_for_each_walks_the_board_and_restores_the_iteration_target():
    """The plain case: every match is visited, and the loop leaves nothing owed.

    It also pins the arity of the matcher call — this handler passed the game to
    a two-argument function until round 33, which no card ever reached, so the
    loop was a ``TypeError`` waiting for its first card.
    """
    game = _r33_board(["A", "B", "C"])
    seen: list[str] = []

    from engine.handlers.registry import effect_handler

    @effect_handler("_r33_note")
    def _note(game, instruction, context):
        seen.append(context.iteration_target.card.name)
        return True, "resolved"

    try:
        from engine.oracle_types import OracleInstruction

        _r33_for_each(game, (OracleInstruction("_r33_note", "", {}),))
    finally:
        from engine.handlers.registry import EFFECT_HANDLERS

        EFFECT_HANDLERS.pop("_r33_note", None)

    assert seen == ["A", "B", "C"]
    assert game.resume_stack == []


def test_for_each_resumes_the_iterations_behind_the_one_that_asked():
    """A step that stops to ask must not cost the iterations behind it.

    This was a bare ``for`` loop: the suspending step returned, the handler
    reported "resolved", and every later object was silently skipped — the
    outcome engine/resumption.py calls worse than never asking.
    """
    game = _r33_board(["A", "B", "C"])
    seen: list[str] = []

    from engine.handlers.registry import EFFECT_HANDLERS, effect_handler

    @effect_handler("_r33_ask")
    def _ask(game, instruction, context):
        seen.append(context.iteration_target.card.name)
        if context.iteration_target.card.name == "B":
            _r31_suspend(game)
        return True, "resolved"

    try:
        from engine.oracle_types import OracleInstruction

        _r33_for_each(game, (OracleInstruction("_r33_ask", "", {}),))
        assert seen == ["A", "B"]
        assert game.resume_stack, "the rest of the loop must be recorded"

        _r31_unsuspend(game)
        while game.resume_stack:
            game.resume_stack.pop()()
    finally:
        EFFECT_HANDLERS.pop("_r33_ask", None)

    assert seen == ["A", "B", "C"], "C was dropped when B asked a question"
