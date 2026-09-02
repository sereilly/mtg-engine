"""Guard: every "put this card into a hand / a library" goes through one seam.

``Game.put_card_into_hand`` / ``put_card_into_library`` are where those moves
become CR 903.9b events: a commander headed to either zone may go to the
command zone instead, and the rule has no single fire site — a bounce, a tuck,
a regrowth and a Ring of Ma'rûf import are all "would be put into its owner's
hand or library from anywhere". A raw ``hand.append`` is a fire site the rule
never reaches; the funnels shipped with the Commander variant after fourteen
such sites were rerouted, and this guard is what keeps site fifteen from
growing back (``_finish_outside_game_draw`` was it, found the week the funnels
landed).

The scan reads receivers spelled ``<expr>.hand`` / ``<expr>.library`` and bare
``hand`` / ``library`` locals — the aliasing ``put_card_into_library`` itself
uses. Like the draw-seam guard beside this one, it cannot see through every
rename; it holds the spellings the engine actually writes.
"""

from __future__ import annotations

import ast
from pathlib import Path
from tests.source_index import source_tree

ENGINE = Path(__file__).resolve().parents[2] / "engine"

#: ``file:function`` for every place the zone lists may still be written.
#: The two funnels themselves; ``commander_declines_zone_change``, the funnel's
#: decline completion (the card goes where it was headed — re-entering the
#: funnel would ask again); ``_divert_drawn_commanders``, the draw half of
#: CR 903.9b, whose insert puts a card back where it was popped from when the
#: zone change is suspended; and ``PlayerState.draw``, the library operation
#: below the draw seam (``test_draw_seam.py`` owns who may call it, and the
#: diversion above runs over its result).
ALLOWED = {
    "mixins/helpers.py:put_card_into_hand",
    "mixins/helpers.py:put_card_into_library",
    "commander.py:commander_declines_zone_change",
    "mixins/effects.py:_divert_drawn_commanders",
    "models.py:draw",
}


def _zone_writes(path: Path) -> list[tuple[str, int]]:
    """``(enclosing function, line)`` for each append/insert onto a hand or
    library receiver."""
    tree = source_tree(path)
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if not (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr in ("append", "insert")
            ):
                continue
            receiver = inner.func.value
            if (
                isinstance(receiver, ast.Attribute)
                and receiver.attr in ("hand", "library")
            ) or (
                isinstance(receiver, ast.Name)
                and receiver.id in ("hand", "library")
            ):
                found.append((node.name, inner.lineno))
    return found


def test_only_the_funnels_write_the_hand_and_library():
    offenders = []
    for path in sorted(ENGINE.rglob("*.py")):
        relative = path.relative_to(ENGINE).as_posix()
        for function, line in _zone_writes(path):
            if f"{relative}:{function}" in ALLOWED:
                continue
            offenders.append(f"{relative}:{line} (in {function})")
    assert not offenders, (
        "hand/library written outside Game.put_card_into_hand / "
        "put_card_into_library — a card put this way skips CR 903.9b:\n  "
        + "\n  ".join(offenders)
    )


def test_the_allowed_list_names_places_that_exist():
    """A stale exemption is an unguarded write site that looks guarded."""
    present = {
        f"{path.relative_to(ENGINE).as_posix()}:{function}"
        for path in ENGINE.rglob("*.py")
        for function, _ in _zone_writes(path)
    }
    assert ALLOWED <= present, sorted(ALLOWED - present)
