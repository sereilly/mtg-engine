"""Guard: every card put into a graveyard goes through one seam.

``Game.put_card_into_graveyard`` is where a graveyard arrival becomes a CR 614
*event*. Forbidden Crypt is the card that needs it — "if a card would be put
into your graveyard **from anywhere**, exile that card instead" — and "from
anywhere" is the whole difficulty: a creature dying, a card discarded, a card
milled, a spell finishing on the stack, a permanent sacrificed and a land
buried by a search are all one event with twenty-six different spellings.

This is the third zone seam, and it exists for the reason CR 903.9b gave the
first two (``put_card_into_hand`` / ``put_card_into_library``): a rule with no
single fire site has as many places to be forgotten as it has call sites, and
the way it is forgotten is silent — the card reaches the graveyard, nothing
raises, and the replacement simply does not happen.

The mirror of ``test_draw_seam.py`` one file over, and the same shape of debt:
the appends were all already there, spelled six different ways
(``player.graveyard.append``, ``victim.graveyard.append(victim.library.pop(0))``,
``game.players[seat].graveyard.append``), and none of them could see an
interceptor.
"""

from __future__ import annotations

import ast
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[2] / "engine"

#: The list methods that *put a card into* a graveyard. A read of the pile is
#: not an arrival and is not guarded — ``pop``, ``index``, ``remove`` and the
#: comprehensions over it are how every "return a card from your graveyard"
#: effect works.
WRITES = {"append", "insert", "extend"}

#: ``file:function`` for the one place a graveyard may still be written
#: directly: the seam itself, which is what runs the replacements.
ALLOWED = {
    "mixins/helpers.py:put_card_into_graveyard",
}


def _graveyard_writes(path: Path) -> list[tuple[str, int]]:
    """``(enclosing function, line)`` for each ``<...>.graveyard.<write>(...)``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call):
                continue
            method = inner.func
            if not isinstance(method, ast.Attribute) or method.attr not in WRITES:
                continue
            pile = method.value
            if isinstance(pile, ast.Attribute) and pile.attr == "graveyard":
                found.append((node.name, inner.lineno))
    return found


def test_only_the_seam_puts_a_card_into_a_graveyard():
    offenders = []
    for path in sorted(ENGINE.rglob("*.py")):
        relative = path.relative_to(ENGINE).as_posix()
        for function, line in _graveyard_writes(path):
            if f"{relative}:{function}" in ALLOWED:
                continue
            offenders.append(f"{relative}:{line} (in {function})")
    assert not offenders, (
        "a graveyard written outside Game.put_card_into_graveyard — a card put "
        "there this way skips every CR 614 replacement over the event:\n  "
        + "\n  ".join(offenders)
    )


def test_the_allowed_list_names_places_that_exist():
    """A stale exemption is an unguarded write that looks guarded."""
    present = {
        f"{path.relative_to(ENGINE).as_posix()}:{function}"
        for path in ENGINE.rglob("*.py")
        for function, _ in _graveyard_writes(path)
    }
    assert ALLOWED <= present, sorted(ALLOWED - present)
