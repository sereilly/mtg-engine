"""Census: a road's "put X onto the battlefield" line is written only for an
entry that happened — and a state-based sweep's "put into graveyard" only for
a permanent that went there.

``game.log`` is every seat's interface (round rule 8). The battlefield funnel
runs a caller's ``then`` for an entry a replacement took away too (CR 614.6:
the event never happens; the replacement writes where the card went), so on
round kg5's chain (e245e624c) 26 of the 27 arrival lines the funnel's callers
write claimed an entry whatever happened to it: Show and Tell "put" a Lake of
the Dead it had sent to the graveyard, a search "put" a land Worms of the
Earth kept out. The funnel now records what became of each entry
(``entry_awaiting.entry_happened`` / ``entry_replaced``), and every such line
asks it — in the ``then`` it runs in, or once the event that put it has
closed.

The census reads every caller of ``_put_permanent_onto_battlefield`` out of
``engine/`` (an AST walk) and each arrival line in it — a literal saying
"onto the battlefield", "to the battlefield" or "enters/entered the
battlefield" — and holds the function the line is written in to asking.
Validated backwards: over the chain's sources it names 26 lines (all but
the acknowledged one).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[2] / "engine"
FUNNEL = "_put_permanent_onto_battlefield"
GATES = frozenset({"entry_happened", "entry_replaced"})
CLAIM = re.compile(r"(onto|to) (the )?battlefield|enter(s|ed) the battlefield")
#: Literal parts that make a line something other than a claim of arrival.
NOT_A_CLAIM = re.compile(
    r"can't enter|instead of entering|nothing was put|no cards? |has no card"
    r"|no revealed|no recorded|may discard a card to put"
)

#: Lines that claim an entry and are written for a stated reason.
ACKNOWLEDGED = {
    "replacements/permanents.py:_resolve_entry_discard_toll":
        "Mox Diamond's toll paid, named for what it buys; the re-entry it "
        "makes is asked every entry question again and says its own outcome",
}


def _units(tree: ast.Module):
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node
        elif isinstance(node, ast.ClassDef):
            for inner in node.body:
                if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield inner


def _calls(node) -> set[str]:
    return {
        getattr(n.func, "attr", None) or getattr(n.func, "id", None)
        for n in ast.walk(node) if isinstance(n, ast.Call)
    }


def _literal(node) -> str:
    return "".join(
        part.value for part in ast.walk(node)
        if isinstance(part, ast.Constant) and isinstance(part.value, str)
    )


def _arrival_lines():
    """(caller key, line number, asks?) for every arrival line in a caller."""
    rows = []
    for path in sorted(ENGINE.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        rel = path.relative_to(ENGINE).as_posix()
        for unit in _units(tree):
            if FUNNEL not in _calls(unit):
                continue

            def visit(node, enclosing):
                if (
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
                    and node is not unit
                ):
                    enclosing = node
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "append"
                    and isinstance(node.func.value, ast.Attribute)
                    and node.func.value.attr == "log"
                    and node.args
                ):
                    text = _literal(node.args[0])
                    if CLAIM.search(text) and not NOT_A_CLAIM.search(text):
                        rows.append((
                            f"{rel}:{unit.name}", node.lineno,
                            bool(_calls(enclosing) & GATES),
                        ))
                for child in ast.iter_child_nodes(node):
                    visit(child, enclosing)

            visit(unit, unit)
    return rows


def test_every_arrival_line_asks_whether_the_entry_happened():
    rows = _arrival_lines()
    assert len(rows) >= 20, rows
    unasked = [
        f"{key}:{line}" for key, line, asks in rows
        if not asks and key not in ACKNOWLEDGED
    ]
    assert not unasked, (
        "a line saying a card was put onto the battlefield, written whether or "
        "not its entry happened — ask entry_awaiting.entry_happened in the "
        "entry's ``then``, or entry_replaced once the event has closed:\n  "
        + "\n  ".join(unasked)
    )


def test_the_acknowledged_lines_are_still_written_unasked():
    rows = _arrival_lines()
    stale = [
        key for key in ACKNOWLEDGED
        if not any(row_key == key and not asks for row_key, _line, asks in rows)
    ]
    assert not stale, stale


def test_the_sweeps_say_where_a_permanent_went():
    """The state-based sweeps' "put into graveyard" is written from what
    ``_permanent_to_graveyard`` answered (True: it died; False: a replacement
    sent it elsewhere), never as a constant."""
    source = (ENGINE / "mixins" / "game_ending.py").read_text(encoding="utf-8")
    constant = [
        number for number, line in enumerate(source.splitlines(), start=1)
        if "put into graveyard (" in line
    ]
    assert not constant, constant
    assert source.count("'put into graveyard' if died else 'left the battlefield'") >= 7
