"""No Python source under ``engine/``, ``web/``, ``scripts/`` or ``tests/``
holds a control character other than tab, newline and carriage return.

The class this guards: an edit made through a shell heredoc loses one layer
of backslashes on this machine, so ``r"\\band\\b"`` arrives as ``r"<BS>and<BS>"``
— a literal U+0008 BACKSPACE where a regex word boundary was meant. It
compiles, it imports, every test of the line passes, and the alternative it
spells can never match anything. ``engine/static_bonuses._protection_list``
carried four of them from Stronghold to Mirrodin, so "has protection from
green **and from** white" never split on "and from" (ROADMAP recorded it; MRD
W2G3 removed it), and ``engine/text_changes.py`` carried a fifth in a comment.
A kindred census test carried three more until W1G2 found them.

No source line has a reason to hold one: a control character a test needs is
written as an escape (``chr(8)``, ``"\\x08"``), which is two or more printable
characters in the file.
"""

from __future__ import annotations

from tests.source_index import REPO_ROOT, python_files, source_text

AREAS = ("engine", "web", "scripts", "tests")

#: Tab, newline, carriage return — the three a Python source may carry.
_ALLOWED = {"\t", "\n", "\r"}


def control_characters(text: str) -> list[tuple[int, int, str]]:
    """``(line, column, U+XXXX)`` for every disallowed control character."""
    found = []
    # ``split("\n")``, not ``splitlines()``: the latter treats a form feed,
    # a vertical tab and U+001C–U+001E as line ends and would swallow them.
    for number, line in enumerate(text.split("\n"), start=1):
        for column, char in enumerate(line, start=1):
            if (ord(char) < 0x20 or ord(char) == 0x7F) and char not in _ALLOWED:
                found.append((number, column, f"U+{ord(char):04X}"))
    return found


def test_the_census_finds_the_shape_it_guards():
    """Backwards: the line ``_protection_list`` held reads as four hits, and
    its repaired spelling as none."""
    eaten = 'words = re.split(r",|' + chr(8) + "and from" + chr(8) + "|" + chr(8) + "and" + chr(8) + '", text)'
    assert [hit[2] for hit in control_characters(eaten)] == ["U+0008"] * 4
    assert control_characters('words = re.split(r",|\\band from\\b|\\band\\b", text)') == []


def test_no_python_source_holds_a_control_character():
    files = python_files(*AREAS)
    # A floor on what was examined: an empty sweep would pass vacuously.
    assert len(files) > 1500, len(files)
    offenders = {
        str(path.relative_to(REPO_ROOT)): hits
        for path in files
        if (hits := control_characters(source_text(path)))
    }
    assert offenders == {}, offenders
