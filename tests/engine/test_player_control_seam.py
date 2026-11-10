"""The one question about a seat's decisions (CR 723, ``engine/player_control.py``).

"Is this seat interactive?" used to be ``seat in game.interactive_seats`` at
every site that asked it — twenty-eight of them across the engine. Once a
player can control another (Mindslaver), the answer is about the seat that
*decides* for it (CR 723.5), and a site still asking the set directly would
ask the person sitting there a decision their controller makes, or default a
decision the person controlling them is owed. So the membership spelling is
held to ``player_control.asks_a_person``; asking whether a person sits at the
table at all (``bool(game.interactive_seats)``) is a different question and
stays free.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALLOWED = {Path("engine/player_control.py")}


def _membership_reads(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        for op, right in zip(node.ops, node.comparators):
            if (
                isinstance(op, (ast.In, ast.NotIn))
                and isinstance(right, ast.Attribute)
                and right.attr == "interactive_seats"
            ):
                lines.append(node.lineno)
    return lines


def test_seat_membership_in_interactive_seats_is_asked_through_the_seam():
    offenders = []
    scanned = 0
    for folder in ("engine", "web"):
        for path in sorted((ROOT / folder).rglob("*.py")):
            relative = path.relative_to(ROOT)
            if relative in ALLOWED:
                continue
            scanned += 1
            for line in _membership_reads(path):
                offenders.append(f"{relative}:{line}")
    assert scanned > 300
    assert not offenders, (
        "ask Game.asks_a_person(seat) — the seat that decides for it may not be "
        f"the one sitting there (CR 723.5): {offenders}"
    )


def test_the_guard_sees_the_spelling_it_forbids(tmp_path):
    """Validated backwards: the scan names the spelling every site used."""
    probe = tmp_path / "probe.py"
    probe.write_text(
        "def f(game, seat):\n"
        "    return seat not in game.interactive_seats or seat in self.interactive_seats\n",
        encoding="utf-8",
    )
    assert _membership_reads(probe) == [2, 2]
    assert _membership_reads(ROOT / "engine/player_control.py")
