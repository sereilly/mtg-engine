"""A leading "Until end of turn," over a control change (Mirrodin's ingest).

Grab the Reins' first mode — "Until end of turn, you gain control of target
creature and it gains haste." — crashed the compiler: the leading-duration
distributor reached ``existing.kind`` on ``GainControl.duration``, which is a
name (``"indefinite"``) rather than a ``Duration`` node, and the
``AttributeError`` escaped the parser instead of refusing the line. Every
census that compiles the measured set died on it.
"""

from __future__ import annotations

from engine.grammar import ast, compile_line


def _steps(line: str):
    compiled = compile_line(line)
    assert compiled.node is not None, compiled.parse_error
    statement = compiled.node.statement
    return statement.steps if isinstance(statement, ast.Sequence) else (statement,)


def test_the_leading_duration_reaches_the_control_change_and_the_grant():
    steps = _steps(
        "Until end of turn, you gain control of target creature and it gains haste."
    )
    controls = [step for step in steps if isinstance(step, ast.GainControl)]
    assert [step.duration for step in controls] == ["until_end_of_turn"]
    assert len(steps) == 2


def test_the_trailing_spelling_reads_the_same_duration():
    steps = _steps("Gain control of target creature until end of turn.")
    assert [step.duration for step in steps] == ["until_end_of_turn"]


def test_a_control_change_printing_two_durations_refuses_rather_than_raising():
    compiled = compile_line(
        "Until end of turn, gain control of target creature for as long as "
        "you control this creature."
    )
    assert compiled.node is None
    assert compiled.parse_error
