"""Guard: the engine decides what to do by what a card *says*, not what it is called.

``ROADMAP.md``'s standing invariant 5 — card names live only in
``card_hooks.py`` — was written down, repeated in ``CLAUDE.md`` and
``engine/ARCHITECTURE.md``, and had never once been checked by anything. It had
decayed: ``engine/ai_policy.py`` carried eight name comparisons the invariant
did not acknowledge, and every one of them was standing in for something
derivable from the compiled program. The audit that found them measured what
the decay costs — Shatter, Terror, Stone Rain and Desert Twister print
Disenchant's template, were not in the whitelist, and the AI aimed all four at
its own permanents.

**The shape this scans for is dispatch, not mention.** A card name in a log
line, a prompt label or a fixture decklist is data; the defect is a name
deciding behaviour, which in Python is a comparison or a membership test against
``<something>.name``. Scanning every string constant instead was tried and is
too blunt: ``Sacrifice``, ``Channel`` and ``Lich`` are all card names *and* all
appear as ordinary labels.

Basic-land names are exempt because a basic land's name is also a land subtype,
and the subtype vocabulary is data (``data/vocabulary/``) that legitimately
appears in type reasoning.

The sanctioned home is ``engine/card_hooks.py``. Everything else needs an entry
below, keyed ``path::function`` so it survives line edits, with the *measured*
reason it cannot be derived — and a staleness test, because an acknowledgement
that outlives its code is a standing exemption for whatever takes its place.
"""

from __future__ import annotations

import ast
import functools
import pathlib

import pytest

from engine.card_loader import load_cards, manifest_set_paths

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCANNED = (ROOT / "engine",)

# The one module allowed to key behaviour on a card name.
HOOKS = "engine/card_hooks.py"

# A basic land's name is also its subtype. "Island" in a landwalk check is type
# vocabulary, not a card reference.
BASIC_LANDS = frozenset({"Plains", "Island", "Swamp", "Mountain", "Forest"})

ACKNOWLEDGED: dict[str, str] = {
    "engine/ai_simulator.py::_assert_expected": (
        "A test oracle, not a heuristic and not dispatch: it asserts that the "
        "card the simulator just cast did what the *printed* card says. "
        "Deriving the expectation from the compiled program makes it a "
        "tautology — measured by compiling Lightning Bolt with its damage "
        "mis-parsed as 1: the printed expectation fires, the derived one "
        "expects 1, sees 1 and passes. Its real decay mode is the decklist "
        "drifting away from the names it checks, which "
        "tests/ai/test_ai_simulator.py holds."
    ),
}


def _module_name(path: pathlib.Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


@functools.lru_cache(maxsize=1)
def _card_names() -> frozenset[str]:
    return frozenset(card.name for card in load_cards(manifest_set_paths())) - BASIC_LANDS


def _is_name_read(node: ast.AST) -> bool:
    """``card.name`` / ``permanent.card.name`` / ``perm.effective_card.name``."""
    return isinstance(node, ast.Attribute) and node.attr == "name"


def _string_constants(node: ast.AST) -> list[str]:
    """Every string literal *node* is, or directly contains as a container."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.Set, ast.Tuple, ast.List)):
        return [
            item.value for item in node.elts
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        ]
    return []


def _enclosing_functions(tree: ast.Module) -> dict[int, str]:
    owner: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                owner.setdefault(id(child), node.name)
    return owner


@functools.lru_cache(maxsize=None)
def _name_dispatch_sites(path: pathlib.Path) -> tuple[tuple[int, str, str, str], ...]:
    """``(line, function, card name, source)`` for each name-keyed decision."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines()
    owners = _enclosing_functions(tree)
    names = _card_names()

    found: list[tuple[int, str, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left, *node.comparators]
        if not any(_is_name_read(item) for item in operands):
            continue
        for operand in operands:
            for literal in _string_constants(operand):
                if literal in names:
                    found.append((
                        node.lineno,
                        owners.get(id(node), "<module>"),
                        literal,
                        lines[node.lineno - 1].strip(),
                    ))
    return tuple(found)


def _scanned_files() -> list[pathlib.Path]:
    found: list[pathlib.Path] = []
    for base in SCANNED:
        found.extend(sorted(base.rglob("*.py")))
    return found


def _offenders() -> list[tuple[str, int, str, str, str]]:
    offenders = []
    for path in _scanned_files():
        module = _module_name(path)
        if module == HOOKS:
            continue
        for line, function, card, text in _name_dispatch_sites(path):
            if f"{module}::{function}" in ACKNOWLEDGED:
                continue
            offenders.append((module, line, function, card, text))
    return offenders


def test_no_card_name_decides_behaviour_outside_card_hooks():
    """"Only one card does this" is a claim about the *pool*, and it expires
    with nobody editing the comment. A name comparison is how the claim is
    written down, so this is where it has to be re-made."""
    offenders = _offenders()
    assert not offenders, (
        f"card name keying behaviour outside {HOOKS} — derive it from the "
        "compiled program (see engine/ai_valuation.py, engine/lord_buffs.py, "
        f"engine/cost_modifiers.py) or register a hook in {HOOKS}:\n"
        + "\n".join(f"  {f}:{n} in {fn}(): {card!r} — {t}" for f, n, fn, card, t in offenders)
    )


def test_card_hooks_still_keys_on_names():
    """The exemption above is only worth anything while ``card_hooks.py`` is
    really the name-keyed module. If it stopped comparing names, the exclusion
    would be protecting nothing and every other file's compliance would be
    accidental."""
    hooks = ROOT / HOOKS
    tree = ast.parse(hooks.read_text(encoding="utf-8"))
    keys = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert keys & _card_names(), (
        f"{HOOKS} no longer names a card in the pool — the sanctioned home has "
        "moved, so HOOKS points at the wrong module and this guard is vacuous"
    )


@pytest.mark.parametrize("entry", sorted(ACKNOWLEDGED))
def test_no_acknowledgement_has_gone_stale(entry):
    """An acknowledgement whose function has been derived away (or renamed) is a
    free pass for whatever lands in its place."""
    module, _, function = entry.partition("::")
    path = ROOT / module
    assert path.exists(), f"{entry} names a file that no longer exists"
    sites = _name_dispatch_sites(path)
    assert any(owner == function for _line, owner, _card, _text in sites), (
        f"{entry} no longer keys on a card name — drop the acknowledgement "
        f"({ACKNOWLEDGED[entry]})"
    )
