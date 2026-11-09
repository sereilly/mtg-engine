"""Every loss the engine performs goes through ``Game.lose_the_game``.

The funnel is where a printed "can't lose the game" ban (Platinum Angel,
``engine/game_result_bans.py``) is asked, so a site that wrote
``player.lost = True`` itself would be a way to lose the Angel does not answer
— the shape every one of the six sites routed through it at Mirrodin had. The
three writes left are the funnel's own, a concession (CR 104.3a: the Angel's
2004-12-01 ruling says a concession still loses) and a draw (CR 104.4: "effects
that say the game is a draw … will still work").
"""

from __future__ import annotations

import re
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[2] / "engine"

_WRITE = re.compile(r"\.lost\s*=\s*True")

#: (module, the function the write sits in) — the three that are not losses
#: the ban answers.
_ALLOWED = {
    ("mixins/game_ending.py", "lose_the_game"),
    ("mixins/game_ending.py", "concede"),
    ("handlers/life_and_game.py", "game_is_draw"),
}


def _enclosing_function(lines: list[str], index: int) -> str:
    for line in reversed(lines[: index + 1]):
        match = re.match(r"\s*def (\w+)\(", line)
        if match:
            return match.group(1)
    return ""


def test_only_the_funnel_a_concession_and_a_draw_write_a_loss():
    found = set()
    examined = 0
    for path in ENGINE.rglob("*.py"):
        examined += 1
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if line.lstrip().startswith("#") or not _WRITE.search(line):
                continue
            found.add((path.relative_to(ENGINE).as_posix(), _enclosing_function(lines, index)))
    assert examined > 300
    assert found - _ALLOWED == set()
    # Backwards: the scan does find the funnel's own write.
    assert ("mixins/game_ending.py", "lose_the_game") in found
