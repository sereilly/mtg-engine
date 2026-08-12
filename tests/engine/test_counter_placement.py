"""Guard: +1/+1 counters are placed through one seam.

``Game.place_plus1_counters`` is where a counter placement becomes an *event*:
CR 614 lets a replacement change how many arrive (Conclave Mentor's "that many
plus one") and CR 603 lets a trigger fire on their arrival (Wildwood Scourge).
``engine/pt.py``'s ``add_plus1_counters`` is the library operation underneath —
it writes the P/T channel and the counter record and knows nothing about the
game.

Reaching for the library operation directly is how a replacement gets skipped,
and it is not a hypothetical: the draw seam has exactly that shape, and three
handlers still call ``player.draw`` around ``_draw_with_replacements`` (noted
in ROADMAP round 28). This test keeps the counter seam from acquiring the same
debt while the debt is still cheap to prevent.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from engine import Game
from engine.card_loader import load_cards, manifest_set_path
from engine.models import Permanent, PlayerState

ENGINE = Path(__file__).resolve().parents[2] / "engine"

# The two modules that may name the library operation: the one that defines it,
# and the one seam that wraps it. Anything else must go through the seam.
ALLOWED = {"pt.py", "effects.py"}


def _calls_in(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "add_plus1_counters"
    ]


def test_only_the_seam_calls_the_library_operation():
    offenders = [
        f"{path.relative_to(ENGINE)}:{line}"
        for path in ENGINE.rglob("*.py")
        if path.name not in ALLOWED
        for line in _calls_in(path)
    ]
    assert not offenders, (
        "add_plus1_counters called outside engine/pt.py and the "
        "place_plus1_counters seam — a counter placed this way skips CR 614 "
        "replacements and fires no trigger:\n  " + "\n  ".join(offenders)
    )


def _mentor_game():
    pool = {c.name: c for c in load_cards(manifest_set_path("M21", include_measured=True))}
    mentor = Permanent(card=pool["Conclave Mentor"])
    target = Permanent(card=pool["Concordia Pegasus"])
    p1 = PlayerState(name="P1", battlefield=[mentor, target])
    return Game(players=[p1, PlayerState(name="P2")]), mentor, target


@pytest.mark.cr("614.1", "121.1")
def test_the_replacement_raises_a_placement_made_anywhere():
    """The point of the seam: a card that never heard of Conclave Mentor still
    places its counters through the replacement."""
    game, _mentor, target = _mentor_game()
    placed = game.place_plus1_counters(target, 1)
    assert placed == 2
    assert target.metadata["plus_counters"] == 2
    assert (target.effective_power, target.effective_toughness) == (3, 5)


@pytest.mark.cr("614.1")
def test_the_replacement_reaches_only_its_controllers_creatures():
    game, _mentor, _target = _mentor_game()
    pool = {c.name: c for c in load_cards(manifest_set_path("M21", include_measured=True))}
    theirs = Permanent(card=pool["Concordia Pegasus"])
    game.players[1].battlefield.append(theirs)

    assert game.place_plus1_counters(theirs, 1) == 1
    assert theirs.metadata["plus_counters"] == 1
