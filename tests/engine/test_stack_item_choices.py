"""The stack item's ``choices`` dict is declared, not ad hoc.

``StackItem`` used to grow a typed field for every extra thing a caster could
pick — a colour for the Lace cycle, a second colour for a text change, a
cross-seat list for divided damage, a source for Jade Monolith — and each one
also became a field on ``OracleExecutionContext``, because the handler that
reads it lives on the other side of resolution. Two dataclass edits per card
family, forever.

They are one ``choices`` dict now, which trades that growth for the usual cost
of a dict: a key can be misspelled on one side and silently read as absent on
the other. ``CHOICE_KEYS`` is the declaration that closes it, and this file is
what makes the declaration load-bearing rather than a comment — every key the
engine actually reads or writes must appear in it, and every key it names must
be used by something.
"""

import ast
import re
from pathlib import Path

import pytest

from engine.game_types import CHOICE_KEYS
from tests.source_index import source_text

_ROOT = Path(__file__).resolve().parents[2]
_SOURCES = sorted(
    p for d in ("engine", "web") for p in (_ROOT / d).rglob("*.py")
)

# `choices["x"]`, `choices.get("x")`, and the literal dicts assigned to the
# field. The first two are the reads; the third is caught by walking the AST
# below, because a dict literal has no `choices` token next to its keys.
_SUBSCRIPT = re.compile(r"""choices(?:\.get\(|\[)\s*["']([a-z_]+)["']""")

#: The same three shapes written with a **named constant** instead of a literal:
#: ``choices[CAST_AT_INSTANT_SPEED]``, ``choices.get(KEY)``, ``{KEY: value}``.
#: A key whose string lives in one module and is imported by the three files
#: that use it is strictly better than four copies of a literal — it is the
#: arrangement `engine/enter_effects.py` exists to enforce for its own phrases —
#: and this guard used to be blind to it, reporting the key as declared and
#: unused while three files read and wrote it. So the constant is resolved:
#: every module-level ``NAME = "literal"`` in the scanned tree, collected once.
_CONSTANT_SUBSCRIPT = re.compile(r"""choices(?:\.get\(|\[)\s*([A-Z][A-Z0-9_]*)""")


def _string_constants() -> dict[str, str]:
    """Every module-level ``NAME = "value"`` in engine/ and web/."""
    constants: dict[str, str] = {}
    for path in _SOURCES:
        for node in ast.parse(source_text(path)).body:
            targets = (
                node.targets if isinstance(node, ast.Assign)
                else [node.target] if isinstance(node, ast.AnnAssign) and node.value
                else []
            )
            value = getattr(node, "value", None)
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    constants[target.id] = value.value
    return constants


def _keys_in_use() -> dict[str, set[str]]:
    """Every ``choices`` key each source file reads or writes."""
    constants = _string_constants()
    found: dict[str, set[str]] = {}
    for path in _SOURCES:
        text = source_text(path)
        if "choices" not in text:
            continue
        keys = set(_SUBSCRIPT.findall(text))
        keys |= {
            constants[name]
            for name in _CONSTANT_SUBSCRIPT.findall(text)
            if name in constants
        }
        # `choices={...}` and `choices=dict(...)` keyword arguments.
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, ast.keyword) or node.arg != "choices":
                continue
            if isinstance(node.value, ast.Dict):
                for key in node.value.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        keys.add(key.value)
                    elif isinstance(key, ast.Name) and key.id in constants:
                        keys.add(constants[key.id])
        if keys:
            found[str(path.relative_to(_ROOT))] = keys
    return found


def test_every_choice_key_in_use_is_declared():
    """A key written on one side and misread on the other is invisible: the
    read returns None and the effect quietly does nothing. Declaring them is
    only worth anything if the declaration is checked."""
    undeclared = {
        path: sorted(keys - set(CHOICE_KEYS))
        for path, keys in _keys_in_use().items()
        if keys - set(CHOICE_KEYS)
    }

    assert not undeclared, (
        "these choices keys are not in game_types.CHOICE_KEYS — add them there "
        f"with a line saying what they carry: {undeclared}"
    )


@pytest.mark.parametrize("key", CHOICE_KEYS)
def test_every_declared_choice_key_is_used(key):
    """The other direction. A declared key nothing reads is a choice the engine
    stopped honouring, and leaving it listed makes the dict look richer than it
    is."""
    users = [path for path, keys in _keys_in_use().items() if key in keys]

    assert users, f"{key!r} is declared in CHOICE_KEYS but nothing reads or writes it"
