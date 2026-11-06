"""Guard: arriving in exile is one transition, and it is ``put_card_into_exile``.

The departure side has had its seam since the exile register
(``tests/engine/test_exile_removal_seam.py``); the arrival side had 79 sites
appending to ``player.exile`` directly, and that was safe only while nothing
could tell two exiled copies of one card apart. A deck repeats one immutable
``CardDefinition`` per copy, so an exile could hold the same Python object
twice — a Dimensional Breach's face-up Temple and a Parallel Thoughts pile's
face-down Temple — while every record about an exiled card names its object
and every reader maps the object back to the first position holding it. The
Breach's card showed as a card back and the pile's by name, and the pile's
draw took the Breach's card (Scourge's post-promotion browser session).

``Game.put_card_into_exile`` returns the object the pile now holds, a new one
when some exile already held that object (CR 400.7, 406.7), so **no exile ever
holds one object twice** and every record names one card. That holds only
while every arrival goes through it, which is what this file scans for:
``.exile.append`` / ``.extend`` / ``.insert`` / ``+=`` anywhere in ``engine/``
or ``web/`` outside the seam, and an assignment of a whole pile
(``player.exile = cards``) other than emptying it — the Debug Menu's raw-state
paste built one from names, so two copies named were one object. A write
through a computed attribute name
(``getattr(player, zone).append``) is the removal guard's completeness table's
to enumerate, and it already says, for each, whether ``exile`` can reach it.
"""

from __future__ import annotations

import ast
import pathlib

from tests.source_index import source_tree

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCANNED = ("engine", "web")
SEAM = "engine/mixins/zone_funnels.py"
#: The one function allowed to add to an exile pile: it *is* the transition.
#: Not the module — ``exile_hand_slots`` beside it appended for itself, and
#: the census found it (Memory Jar, Suppress, Hypnox, Decree of Annihilation).
SEAM_FUNCTION = "put_card_into_exile"
_ADDERS = frozenset({"append", "extend", "insert"})


def _is_exile_attribute(node) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "exile"


def _seam_lines(tree) -> set[int]:
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == SEAM_FUNCTION:
            lines.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    return lines


def _arrivals(path: pathlib.Path, *, inside_the_seam: bool = False) -> list[tuple[int, str]]:
    tree = source_tree(path)
    seam = _seam_lines(tree) if path.relative_to(ROOT).as_posix() == SEAM else set()
    hits = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _ADDERS
            and _is_exile_attribute(node.func.value)
        ):
            hits.append((node.lineno, f".exile.{node.func.attr}(...)"))
        elif isinstance(node, ast.AugAssign) and _is_exile_attribute(node.target):
            hits.append((node.lineno, ".exile += ..."))
        elif isinstance(node, ast.Assign) and any(_is_exile_attribute(t) for t in node.targets):
            emptied = isinstance(node.value, ast.List) and not node.value.elts
            if not emptied:
                hits.append((node.lineno, ".exile = ..."))
    return [hit for hit in hits if (hit[0] in seam) is inside_the_seam]


def _scanned_files():
    for top in SCANNED:
        yield from sorted((ROOT / top).rglob("*.py"))


def test_every_arrival_in_exile_goes_through_the_seam():
    offenders = []
    examined = 0
    for path in _scanned_files():
        module = path.relative_to(ROOT).as_posix()
        examined += 1
        for line, what in _arrivals(path):
            offenders.append(f"  {module}:{line}: {what}")
    assert examined > 100
    assert not offenders, (
        "a card put into exile outside the seam — call "
        "game.put_card_into_exile(owner, card) and write down the object it "
        "returns, so no exile holds one object twice (CR 400.7):\n"
        + "\n".join(offenders)
    )


def test_the_seam_is_the_one_place_that_appends():
    """The scan is not vacuous: the seam's own append is what it would flag."""
    assert _arrivals(ROOT / SEAM, inside_the_seam=True), (
        "the seam no longer appends to an exile pile"
    )
