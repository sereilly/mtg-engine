"""Every library an effect shuffles goes through ``Game.shuffle_library_of``.

"Whenever a spell or ability causes a player to shuffle their library, this
artifact deals 2 damage to that player." (Psychogenic Probe.) The trigger
hears the seam's announcement (``library_shuffled``) and nothing else, so a
``random.shuffle(player.library)`` written anywhere but the seam is a shuffle
the Probe never hears — the failure ``become_untapped`` was built to end one
event over, which is why this is a census rather than a test of one road.

The two places a library is shuffled by no spell or ability are allowed by
name: the seam itself, and the pregame (CR 103.3's opening shuffle and the
mulligans, ``mixins/turn_management.py``).
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCANNED = ("engine", "web")
ALLOWED = {
    Path("engine/mixins/helpers.py"),          # the seam
    Path("engine/mixins/turn_management.py"),  # CR 103.3 and the mulligans
}


def _library_shuffles(source: str) -> list[int]:
    """Line numbers of every ``random.shuffle(<x>.library)`` in *source*."""
    lines: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "shuffle"):
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Attribute) and arg.attr == "library":
            lines.append(node.lineno)
    return lines


def test_the_census_finds_a_raw_library_shuffle():
    """Validated backwards: the reader names the spelling it exists to forbid
    (every one of the twenty-seven sites the seam replaced was this), and
    passes over a shuffle of something that is not a library."""
    assert _library_shuffles("import random\nrandom.shuffle(player.library)\n") == [2]
    assert _library_shuffles("random.shuffle(target.library)") == [1]
    assert _library_shuffles("random.shuffle(rest)\nrandom.shuffle(pile)") == []


def test_every_effect_shuffle_goes_through_the_seam():
    offenders: list[str] = []
    examined = 0
    for folder in SCANNED:
        for path in sorted((ROOT / folder).rglob("*.py")):
            relative = path.relative_to(ROOT)
            examined += 1
            if relative in ALLOWED:
                continue
            for line in _library_shuffles(path.read_text(encoding="utf-8")):
                offenders.append(f"{relative.as_posix()}:{line}")
    assert examined > 300, f"the census read only {examined} modules"
    assert not offenders, (
        "a library shuffled outside Game.shuffle_library_of, which "
        "Psychogenic Probe cannot hear: " + ", ".join(offenders)
    )


def test_the_allowed_modules_still_hold_their_shuffles():
    """The allowance is not dead weight: the seam and the pregame each still
    shuffle a library directly. If either stops, its line here should go."""
    for relative in ALLOWED:
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert _library_shuffles(source), relative
