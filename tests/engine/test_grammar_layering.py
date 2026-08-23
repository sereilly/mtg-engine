"""Guard: `engine/grammar/` stays layered, and its families stay independent.

`parser.py`, `lower.py` and `ast.py` were 2,306, 2,428 and 981 lines. They are
the three files that grow with the card pool — every new template lands in all
three — so their size is not cosmetic, it is the cost of the next 25,000 cards.
Splitting them only helps while the split holds, and a split holds by test or
not at all.

Two properties, and they fail differently.

**The layers are ordered.** `phrases -> effects -> conditions -> statements ->
costs -> parser` on the parsing side, `_common/categories -> the families -> statics -> lower` on the
lowering side, `_core -> the families -> statements` inside the AST. An import that
reaches back up would compile fine and would make the three files three files
again with extra steps.

**The families are independent.** `effects/damage.py` must not import
`effects/board.py`. This is the property that makes "where does prowess go?"
answerable: if the families reference each other, the answer becomes "wherever,
then fix the imports", and the grouping stops being information.

Independence is what the original files did *not* have, and each split started
by finding the exceptions rather than assuming there were none:
`_parse_zone` / `_parse_mana_payment` on the parsing side and
`_full_mana_payload` / `_REST_OF_TURN` on the lowering side were fragments
several families wanted. They live in `phrases` and `_common` for that reason,
not by taxonomy — so the rule below is "families do not import each other",
with no exception list to grow. (The AST needed no such correction: its nodes
only ever reference the shared vocabulary or their own family.)
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

GRAMMAR = Path(__file__).resolve().parent.parent.parent / "engine" / "grammar"

# Bottom to top. A module may import from any layer *below* it and none above.
# `conditions` sits below `statements` because that is where its dependencies
# put it: a condition describes an event and is built from nouns, amounts and
# durations alone, so nothing in it can reach a statement production. The
# order is therefore an assertion about the split, not a convention — a
# condition that grew a need for an effect would fail here.
PARSE_LAYERS = [
    # What a noun phrase *describes* (`nouns`) sits under what it *points at*
    # (`references`): CR 109's "what is this object" against CR 115's "how many
    # does the spell choose, and is a player one of them". They were one module
    # until Antiquities' token phrases pushed it past the guard below, and the
    # order is what keeps the split from folding back — the filter parser must
    # never need the quantifier one.
    "nouns",
    "references",
    # Whole printed *paragraphs* that are one effect (Necromentia, Idol of
    # Endurance, Tawnos's Coffin, Transmute Artifact). Below `statements`
    # because none of them calls back into the sentence parser — each reads its
    # own words to the end — and split out of it when Antiquities' four-sentence
    # cards pushed that file past the guard below.
    "paragraphs",
    "phrases",
    # The trigger tables and the productions that read them. Split out of
    # `phrases` when Antiquities' trigger work pushed that module past the
    # thousand-line guard below — above `phrases`, whose shared fragments it
    # reads, and below everything that reads a whole line.
    "triggers",
    "effects", "conditions", "statements", "costs", "parser",
]
LOWER_LAYERS = ["lowering", "statics", "lower"]

EFFECT_FAMILIES = ["damage", "characteristics", "board", "cards", "stack", "combat", "game"]
# The lowering side carries families the parsing side does not. Zone movement
# is one `return`/`exile`/`put` production each on the way in and a decision
# about *which handler moves the object* on the way out, so `lowering/board.py`
# outgrew the 1,000-line cap while `effects/board.py` stayed small. A near-empty
# `effects/zones.py` would buy back the symmetry and cost the thing symmetry is
# for — one home per template per side, findable from the family name.
# `library` and `mana` split out of `lowering/cards.py` the same way when it
# reached 959 of the 1,000 lines: the hidden-zone flows and mana production
# each lower to far more than their parse halves read. If `effects/cards.py`
# ever splits, reuse these names so the mirror re-forms instead of forking.
# `counters` split out of `lowering/characteristics.py` at 975 lines, the day
# before a set ingest: a counter (CR 122) is a marker on an object, not a
# characteristic of it, and the two halves shared no imports.
LOWERING_FAMILIES = EFFECT_FAMILIES + ["zones", "library", "mana", "counters"]
AST_FAMILIES = EFFECT_FAMILIES


def _imports(path: Path) -> list[tuple[int, str, bool]]:
    """(line, target, is_sibling) for every relative import in *path*.

    *target* is the grammar-level module name, so `from ..phrases import` in
    `effects/damage.py` and `from .phrases import` in `parser.py` both read as
    `phrases` — the layer list uses one spelling regardless of which directory
    the importer sits in.

    *is_sibling* marks an import within the importer's own subpackage
    (`effects/cards.py` importing `effects/board.py`). Those are the
    subpackage's internal business, checked by the family tests below rather
    than by the layer order — conflating the two is what made the first version
    of this guard fail on every legitimate `from ._common import`.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    inside_package = path.parent != GRAMMAR
    out: list[tuple[int, str, bool]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.level:
            continue
        module = (node.module or "").split(".")[0]
        if inside_package and node.level == 1:
            out.append((node.lineno, module, True))
        elif node.level == 1 + (1 if inside_package else 0):
            out.append((node.lineno, module, False))
    return out


def _layer_modules(name: str) -> list[Path]:
    module = GRAMMAR / f"{name}.py"
    if module.exists():
        return [module]
    return sorted((GRAMMAR / name).rglob("*.py"))


@pytest.mark.parametrize(
    "layers", [PARSE_LAYERS, LOWER_LAYERS], ids=["parsing", "lowering"]
)
def test_layers_only_import_downward(layers):
    rank = {name: i for i, name in enumerate(layers)}
    violations = []
    for name in layers:
        paths = _layer_modules(name)
        assert paths, f"layer {name!r} has no modules — the guard would pass vacuously"
        for path in paths:
            for line, target, is_sibling in _imports(path):
                if is_sibling:
                    continue
                if target in rank and rank[target] >= rank[name]:
                    violations.append(
                        f"{path.relative_to(GRAMMAR)}:{line} imports {target}"
                    )
    assert not violations, (
        "engine/grammar/ layering broken — a module imported from its own layer "
        "or above:\n  " + "\n  ".join(violations)
    )


@pytest.mark.parametrize(
    "package,shared,roof",
    [
        ("effects", (), ()),
        ("lowering", ("_common", "categories"), ()),
        ("ast", ("_core",), ("statements",)),
    ],
    ids=["effects", "lowering", "ast"],
)
def test_families_import_only_their_package_shared_module(package, shared, roof):
    """Inside a subpackage, a family may reach the shared module and nothing else.

    `effects/` has no shared module of its own — its shared fragments are one
    level up in `phrases`, which is why its tuple is empty. `lowering/` keeps
    `_common` and `categories` beside the families because both are lowering
    concerns with no reader outside the package. `ast/` keeps `_core`, the
    vocabulary its nodes are built from.

    `roof` names the modules that sit *above* the families rather than below
    them; they are exempted here and checked by their own test. Only `ast/` has
    one, because `Effect`, `Statement` and `AbilityNode` are unions over every
    family and so cannot live beside any single one.
    """
    violations = []
    for path in sorted((GRAMMAR / package).glob("*.py")):
        if path.stem in ("__init__", *shared, *roof):
            continue
        for line, target, is_sibling in _imports(path):
            if is_sibling and target not in shared:
                violations.append(f"{package}/{path.name}:{line} imports {target}")
    assert not violations, (
        f"a {package}/ family reached sideways instead of down:\n  "
        + "\n  ".join(violations)
    )


def test_the_ast_roof_only_reaches_downward():
    """`ast/statements.py` may name the families; nothing may name it back.

    It is the one module in the three packages that imports a family, and it
    has to be: a union over every leaf node can only be written where every
    leaf node is visible. What keeps that from being a hole is that the edge
    runs one way — the families are held to `_core` by the test above, so a
    family importing `statements` fails there, and `statements` importing the
    package's own `__init__` (the way to smuggle in a cycle) fails here.
    """
    allowed = {"_core", *AST_FAMILIES}
    violations = [
        f"ast/statements.py:{line} imports {target or '__init__'}"
        for line, target, _is_sibling in _imports(GRAMMAR / "ast" / "statements.py")
        if target not in allowed
    ]
    assert not violations, (
        "ast/statements.py is the roof of the package — it may import `_core` "
        "and the families and nothing else:\n  " + "\n  ".join(violations)
    )


@pytest.mark.parametrize(
    "package,families",
    [
        ("effects", EFFECT_FAMILIES),
        ("lowering", LOWERING_FAMILIES),
        ("ast", AST_FAMILIES),
    ],
)
def test_families_do_not_import_each_other(package, families):
    """The property that makes the grouping mean something."""
    violations = []
    for family in families:
        path = GRAMMAR / package / f"{family}.py"
        assert path.exists(), f"{package}/{family}.py is missing"
        for line, target, _is_sibling in _imports(path):
            if target in families and target != family:
                violations.append(f"{package}/{family}.py:{line} imports {target}")
    shared = {"effects": "phrases", "lowering": "_common", "ast": "_core"}[package]
    assert not violations, (
        f"{package}/ families are supposed to be independent — a fragment two "
        f"families need belongs in the shared module below them ({shared}), "
        "not in one of them:\n  " + "\n  ".join(violations)
    )


@pytest.mark.parametrize("package", ["effects", "lowering", "ast"])
def test_the_front_door_exports_every_family_name(package):
    """`__init__` re-exports flat, so callers never name a family.

    That is what makes moving a production between families a non-event. A name
    that stops being re-exported is an ImportError at startup rather than a
    silent loss, but only if `__all__` and the imports agree — this checks they
    do.

    It bites hardest in `ast/`, where every caller says `ast.DealDamage` through
    `from . import ast`: a node the front door forgets is not a missing export
    but a missing *attribute*, which surfaces card by card at parse time rather
    than once at import. The pre-split `ast.py` had drifted that way already —
    `__all__` had stopped naming three of its own node types.
    """
    init = GRAMMAR / package / "__init__.py"
    tree = ast.parse(init.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported |= {a.asname or a.name for a in node.names}
    declared: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "__all__":
            declared = {
                el.value for el in node.value.elts if isinstance(el, ast.Constant)
            }
    assert declared, f"{package}/__init__.py has no __all__"
    assert declared <= imported, (
        f"{package}/__init__.py declares names it does not import: "
        f"{sorted(declared - imported)}"
    )
    assert imported <= declared, (
        f"{package}/__init__.py imports names it does not export: "
        f"{sorted(imported - declared)}"
    )


def test_no_module_is_back_to_its_old_size():
    """The point of the split, stated as a number.

    Not a style rule — these three files grow with the card pool, and the reason
    the split was worth doing is that every new template lands in them. A
    module drifting back past a thousand lines means the families stopped
    absorbing new work and something is being appended to whatever was easiest.
    """
    oversized = {
        str(path.relative_to(GRAMMAR)): len(path.read_text(encoding="utf-8").splitlines())
        for path in GRAMMAR.rglob("*.py")
        if len(path.read_text(encoding="utf-8").splitlines()) > 1000
    }
    assert not oversized, (
        f"grammar modules back over 1,000 lines: {oversized}. Split along the "
        "family the new work belongs to rather than raising this number."
    )
