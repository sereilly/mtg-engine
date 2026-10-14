"""The meeting-point list (scripts/meeting_point.py) refuses what would read as
green, and names real files.

The script stands in for the suite between full gates, so its failure mode is
the one that matters: a list that silently ran less than it appeared to. xdist
reports a mistyped path as "no tests ran", which reads as green in a tail, and
a surprises file naming a test somebody later renamed would drop that test from
every merge without a word. Both are held here, where the suite fails, rather
than on the day of a gate.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import meeting_point  # noqa: E402


def _list(**overrides):
    arguments = dict(changed=[], set_files=[], guards=[], surprises=[], extra=[])
    arguments.update(overrides)
    return meeting_point.build_list(**arguments)


def test_every_recorded_surprise_names_a_test_file_that_exists():
    surprises = meeting_point.read_surprises()
    assert len(surprises) >= 11, len(surprises)
    for path, reason in surprises:
        assert (REPO / path).is_file(), path
        assert meeting_point.is_test_file(path), path
        assert reason


def test_a_surprise_without_a_reason_is_refused(tmp_path):
    bare = tmp_path / "surprises.txt"
    bare.write_text("tests/rules/test_echo.py\n", encoding="utf-8")
    with pytest.raises(meeting_point.ListError):
        meeting_point.read_surprises(bare)


@pytest.mark.parametrize("channel", ["set_files", "guards", "extra"])
def test_a_path_that_does_not_exist_is_refused_on_every_channel(channel):
    with pytest.raises(meeting_point.ListError):
        _list(**{channel: ["tests/engine/test_no_such_file.py"]})
    with pytest.raises(meeting_point.ListError):
        _list(surprises=[("tests/engine/test_no_such_file.py", "a reason")])


def test_an_unknown_set_code_is_refused_rather_than_run_as_nothing():
    with pytest.raises(meeting_point.ListError):
        meeting_point.set_test_files("ZZZ")
    assert len(meeting_point.set_test_files("ODY")) >= 5


def test_the_structural_guards_are_derived_and_include_the_ones_a_merge_trips():
    guards = meeting_point.structural_guards()
    assert len(guards) >= 30, len(guards)
    for expected in (
        "tests/engine/test_grammar_layering.py",
        "tests/engine/test_face_blind_guards.py",
        "tests/engine/test_set_test_convention.py",
        "tests/engine/test_import_hygiene.py",
    ):
        assert expected in guards, expected


def test_a_file_on_two_channels_runs_once_and_says_why_twice():
    reasons, helpers = _list(
        changed=["tests/rules/test_echo.py", "tests/helpers.py"],
        surprises=[("tests/rules/test_echo.py", "a reason")],
    )
    assert reasons == {"tests/rules/test_echo.py": ["changed", "surprise"]}
    # A changed helper is reported, not run: it is not a test file, and pytest
    # handed one collects nothing from it.
    assert helpers == ["tests/helpers.py"]


def test_a_named_path_that_does_not_exist_exits_before_pytest(monkeypatch, capsys):
    monkeypatch.setattr(meeting_point, "changed_test_paths", lambda base: [])
    monkeypatch.setattr(meeting_point.subprocess, "run", lambda *a, **k: pytest.fail("pytest was started"))
    assert meeting_point.main(["tests/engine/test_no_such_file.py"]) == 2
    assert "does not exist" in capsys.readouterr().err


def test_an_option_meant_for_pytest_is_not_read_as_a_path(monkeypatch):
    """`--dist worksteal` typed without the separator used to hand the script
    a path called "worksteal". Unknown options are an error; pytest's own go
    after a bare `--` and arrive untouched."""
    seen = {}

    class Ran:
        returncode = 0

    def run(command, **_):
        seen["command"] = command
        return Ran()

    monkeypatch.setattr(meeting_point, "changed_test_paths", lambda base: [])
    monkeypatch.setattr(meeting_point.subprocess, "run", run)
    with pytest.raises(SystemExit):
        meeting_point.main(["--maxfail", "1"])
    assert meeting_point.main(["--", "--maxfail", "1"]) == 0
    assert seen["command"][-2:] == ["--maxfail", "1"]
    assert "worksteal" in seen["command"]


def test_a_changed_files_slow_tests_run_and_a_guards_do_not(monkeypatch):
    """A guard or a surprise is on the list for the fact it states about the
    pool, not for the whole-game simulations that share its file; a file the
    tree changed is a meeting point in full."""
    commands = []

    class Ran:
        def __init__(self, returncode):
            self.returncode = returncode

    def run(command, **_):
        commands.append(command)
        # The second run finding no slow test in the changed files is exit 5.
        return Ran(0 if len(commands) == 1 else 5)

    monkeypatch.setattr(meeting_point, "changed_test_paths", lambda base: ["tests/rules/test_echo.py"])
    monkeypatch.setattr(meeting_point.subprocess, "run", run)
    assert meeting_point.main([]) == 0

    everything, changed_only = commands
    marker = lambda command: command[command.index("-m", 2) + 1]  # noqa: E731
    assert marker(everything) == "not slow" and marker(changed_only) == "slow"
    assert "tests/engine/test_grammar_layering.py" in everything
    assert [part for part in changed_only if part.startswith("tests/")] == ["tests/rules/test_echo.py"]


def test_a_run_that_collected_nothing_is_a_failure(monkeypatch, capsys):
    class Collected:
        returncode = 5

    monkeypatch.setattr(meeting_point, "changed_test_paths", lambda base: [])
    monkeypatch.setattr(meeting_point.subprocess, "run", lambda *a, **k: Collected())
    assert meeting_point.main([]) == 1
    assert "collected nothing" in capsys.readouterr().err
