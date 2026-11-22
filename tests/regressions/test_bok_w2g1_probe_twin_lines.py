"""``scripts/probe_line.py`` on a card whose rewrite reads two identical lines.

"Soulshift 4, soulshift 4" (Forked-Branch Garami) is rewritten to one rules
line per instance (CR 702.46b; ``soulshift.expand_soulshift_line``), so the
compiler reads the same sentence twice. The probe attributed every reader's
call to the first of the two by text, and reported the second "not reached:
the compiler refused the card before reading it" on a card the compiler
supports — the promotion rehearsal's sampled pass found it
(``tests/engine/test_probe_line.py::test_the_probe_agrees_with_the_compiler_across_the_pool``
under ``MTG_FULL_CENSUS=1``, ``MTG_PROMOTE=BOK``). Each reader's n-th call
about the text is now the n-th line of it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import probe_line  # noqa: E402

_TWICE = (
    "Soulshift 4, soulshift 4 (When this creature dies, you may return up to "
    "two target Spirit cards with mana value 4 or less from your graveyard to "
    "your hand.)"
)


def test_both_twin_lines_are_judged_accepted():
    card = probe_line.invented_card([_TWICE], "Creature — Spirit", "Probe Twin Shift")
    (unit,) = probe_line.probe_card(card)
    assert unit.supported
    assert len(unit.lines) == 2
    assert unit.lines[0].text == unit.lines[1].text
    assert [line.verdict.accepted for line in unit.lines] == [True, True], [
        str(line.verdict) for line in unit.lines
    ]
