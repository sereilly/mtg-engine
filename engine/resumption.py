"""Loops that survive one of their steps stopping to ask a question.

A decision can interrupt an event part-way — CR 616.1e's "which of these
effects applies first" is the one that does it today. Answering re-runs that
event, which is exact, because nothing had been applied when it stopped (see
``engine/effect_ordering.py``).

Re-running the *event* is not enough when the event was one step of a loop. A
divided Fireball deals to each target in turn; a ``sequence`` has instructions
queued behind the one that stopped; the combat damage step walks a list of
recorded events. Re-run step k on its own and steps k+1 onwards are silently
lost, which is a worse outcome than never asking.

So a loop that can be interrupted records **the rest of itself** before each
step and drops that record once the step gets through. What is left on
``game.resume_stack`` when something suspends is exactly the work still owed,
innermost last. Answering the prompt re-runs the suspended event and then
unwinds the stack, so a suspension three loops deep resumes the divided damage,
then the sequence, then whatever held that — in that order, because the
innermost loop is the one whose next step comes soonest.

**A loop using this must be the last thing its function does.** Work written
after it does not run when a step suspends, and nothing records it — put it in
the loop's own final step, or in a continuation, rather than after the call.
``tests/rules/test_resumption.py`` pins the unwinding order and the balance of
the stack; an unbalanced stack means a loop leaked a continuation nobody will
run.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable


def run_resumable(game, items: Iterable[Any], step: Callable[[Any], None]) -> None:
    """Run *step* over *items*, stopping if one of them suspends.

    The rest of the loop is recorded on ``game.resume_stack`` while each step
    runs and removed again once it returns without suspending, so the stack only
    ever holds work that is genuinely still owed.
    """
    items = list(items)

    def run_from(index: int) -> None:
        for position in range(index, len(items)):
            game.resume_stack.append(lambda position=position: run_from(position + 1))
            step(items[position])
            if game.effect_suspended:
                # Leave the continuation: it is the rest of this loop, and
                # answering the prompt is what will come back for it.
                return
            game.resume_stack.pop()

    run_from(0)


def resume_after_answer(game) -> None:
    """Continue every loop that was waiting on the answer just applied.

    Innermost first — the deepest loop is the one whose next step comes soonest.
    A continuation that suspends again leaves its own record and stops the
    unwinding, so the next answer picks up from there.
    """
    while game.resume_stack and not game.effect_suspended:
        game.resume_stack.pop()()
