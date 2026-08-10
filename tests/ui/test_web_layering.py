"""The web package's layering, held to what ``web.LAYERS`` declares.

``web/app.py`` was one ~4,950-line module, so nothing could be circular: there
was only one thing. Split into modules the shape becomes losable, and it is
losable *quietly* — Python resolves a function-level import fine, so a leaf that
starts reaching back up to the state assembler produces working code and a
tangle nobody chose. The failure it eventually causes is an ImportError at
process start, which arrives long after the edit that caused it.

So the direction is declared once, in ``web/__init__.py``, and checked here:
every intra-package import must point *earlier* in ``LAYERS``. That is also what
lets ``app.py`` be nothing but the route table — it is last, so everything is
importable from it and it is importable from nothing.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from web import LAYERS

WEB = Path(__file__).resolve().parents[2] / "web"
RANK = {name: i for i, name in enumerate(LAYERS)}


def _intra_package_imports(source: str) -> list[tuple[str, int]]:
    """Every ``web`` module *source* imports, with the line it does it on.

    Covers all three spellings: ``from .catalog import x``, ``from web.catalog
    import x`` and ``import web.catalog`` — a guard that only knew the relative
    form would be silent about the one an author reaching for a new dependency
    is most likely to write."""
    found: list[tuple[str, int]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            if node.level == 1 and node.module in RANK:
                found.append((node.module, node.lineno))
            elif node.level == 0 and (node.module or "").startswith("web."):
                found.append((node.module.split(".")[1], node.lineno))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("web."):
                    found.append((alias.name.split(".")[1], node.lineno))
    return found


def _violations(module: str, source: str) -> list[str]:
    """Imports in *module* that do not point earlier in LAYERS. Shared by the
    test below and the fault-injection test that proves it fires."""
    out = []
    for target, lineno in _intra_package_imports(source):
        if RANK[target] >= RANK[module]:
            direction = "itself" if target == module else f"{target}, at or above it"
            out.append(f"web/{module}.py:{lineno} imports {direction}")
    return out


def test_every_web_module_is_placed_in_the_layering():
    """A module missing from LAYERS is a module the guard below never reads."""
    on_disk = {p.stem for p in WEB.glob("*.py")} - {"__init__"}
    assert on_disk == set(LAYERS), (
        f"not in web.LAYERS: {sorted(on_disk - set(LAYERS))}; "
        f"in LAYERS but not on disk: {sorted(set(LAYERS) - on_disk)}"
    )


def test_no_web_module_imports_one_at_or_above_it():
    """The layering is a layering: imports only ever point down."""
    problems: list[str] = []
    for name in LAYERS:
        problems += _violations(name, (WEB / f"{name}.py").read_text(encoding="utf-8"))
    assert not problems, "web package layering broken:\n  " + "\n  ".join(problems)


@pytest.mark.parametrize(
    "module, injected",
    [
        # The cycle this shape actually grows: a leaf reaching up to the
        # assembler that is built out of it.
        ("serialization", "from .state_view import _serialize_state"),
        # The same thing written absolutely, which a relative-only check misses.
        ("seats", "from web.catalog import CATALOG_BY_NAME"),
        ("runtime", "import web.app"),
    ],
)
def test_the_layering_guard_fires(module, injected):
    """Verified by injection: each import above is one the real check must
    reject. A guard nobody has watched fail is a guard nobody has tested."""
    source = (WEB / f"{module}.py").read_text(encoding="utf-8") + "\n" + injected
    assert _violations(module, source), f"{injected!r} was not rejected"
