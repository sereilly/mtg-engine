"""Loops that survive one of their steps stopping to ask a question.

A decision can interrupt an event part-way. Two things do it today:

* CR 616.1e's "which of these effects applies first". Answering re-runs that
  event, which is exact, because nothing had been applied when it stopped (see
  ``engine/effect_ordering.py``).
* any pending choice whose spec is registered ``suspends`` — a scry, a search, a
  library reorder. There the answer *is* the effect, so there is nothing to
  re-run; the loop simply carries on from where it stopped.

Both arrive through ``arm_pending_choice`` and leave through the one completion
path in ``engine/mixins/stack/choices.py``, so what sets and clears
``game.effect_suspended`` is the spec, not the caller.

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


class _RestOfLoop:
    """One loop's record on ``game.resume_stack``: the steps it has not run.

    ``live`` is whether the step in front of that remainder is **still
    executing** — the loop is on the Python call stack right now, not waiting
    for anybody. The difference did not exist while every answer arrived from
    outside the engine (a player's confirm, a test's drain): by then every loop
    on the stack had returned, so "on the stack" and "waiting" were one fact.

    A table whose prompts a driver answers (`Game.prompt_driver`) breaks that.
    The combat damage step's last step drains its priority window; a trigger
    resolving in that window runs a loop of its own, which stops to ask; the
    driver answers at once — *inside* the window, with the outer loop's step
    still running. Unwinding everything then re-runs the outer loop's remainder
    from underneath it, and the outer step returns to pop a record that is
    already gone. So the unwinding stops at a live record: that loop will carry
    on by itself the moment its step returns.
    """

    __slots__ = ("resume", "live")

    def __init__(self, resume: Callable[[], None]) -> None:
        self.resume = resume
        self.live = True

    def __call__(self) -> None:
        self.resume()


def run_resumable(game, items: Iterable[Any], step: Callable[[Any], None]) -> None:
    """Run *step* over *items*, stopping if one of them suspends.

    The rest of the loop is recorded on ``game.resume_stack`` while each step
    runs and removed again once it returns without suspending, so the stack only
    ever holds work that is genuinely still owed.
    """
    items = list(items)

    def run_from(index: int) -> None:
        for position in range(index, len(items)):
            rest = _RestOfLoop(lambda position=position: run_from(position + 1))
            game.resume_stack.append(rest)
            try:
                step(items[position])
            finally:
                rest.live = False
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
    unwinding, so the next answer picks up from there. So does a record whose
    step is still running (`_RestOfLoop.live`): that loop is not waiting.
    """
    while game.resume_stack and not game.effect_suspended:
        if getattr(game.resume_stack[-1], "live", False):
            return
        game.resume_stack.pop()()
