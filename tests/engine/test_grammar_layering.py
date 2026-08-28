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
import collections
import pathlib
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
    # Small printed readers `nouns` shares *upward* — a comparison, a
    # self-reference. Below it because nothing about them is about a filter.
    "readers",
    # An ability on the stack (CR 113.7a) has no card and no type line, so it
    # shares no vocabulary with the filter parser that reads one. Below
    # `nouns`, which returns the moment one of these matches.
    "abilities",
    # A card **name** is a literal string, not a description of a set of
    # objects, so the scan that reads one shares no vocabulary with the filter
    # parser above it. Split out of `nouns` when the cross-axis class union
    # pushed that module past the guard below — the bottom of the parse side,
    # because it reads tokens and nothing else.
    "names",
    # What a noun phrase *describes* (`nouns`) sits under what it *points at*
    # (`references`): CR 109's "what is this object" against CR 115's "how many
    # does the spell choose, and is a player one of them". They were one module
    # until Antiquities' token phrases pushed it past the guard below, and the
    # order is what keeps the split from folding back — the filter parser must
    # never need the quantifier one.
    # The trailing half of a noun phrase. Below `nouns`, which hands it the
    # recursive parser rather than being imported back — "blocking target
    # attacking creature" nests a whole phrase.
    "postmodifiers",
    "nouns",
    "references",
    # Whole printed *paragraphs* that are one effect (Necromentia, Idol of
    # Endurance, Tawnos's Coffin, Transmute Artifact). Below `statements`
    # because none of them calls back into the sentence parser — each reads its
    # own words to the end — and split out of it when Antiquities' four-sentence
    # cards pushed that file past the guard below.
    "paragraphs",
    "phrases",
    # The "…, where X is …" clause. Above `phrases`, whose word tables and
    # literal reader it uses, and split out of it at the guard the round two
    # branches both added a definition. The name re-forms the mirror
    # `lowering/where_x.py` has had since round 23.
    "where_x",
    # Which object a bare "it" in an effect names. Under `triggers` because
    # only one of its two rebinders is about a trigger and neither needs a
    # production: the walk is about the shape of the AST, so it imports `ast`
    # and nothing else.
    "rebinding",
    # Trigger events whose subject the sentence *names* — the source, or the
    # permanent the source is attached to — rather than quantifying it. Split
    # out of `triggers` at the size guard below, along the boundary that module
    # already drew, and under it: these read tokens and build events, and none
    # of them reaches a table.
    "trigger_subjects",
    # The trigger tables and the productions that read them. Split out of
    # `phrases` when Antiquities' trigger work pushed that module past the
    # thousand-line guard below — above `phrases`, whose shared fragments it
    # reads, and below everything that reads a whole line.
    "triggers",
    "effects", "conditions",
    # Delayed triggered abilities, and the opener that binds one. Below
    # `statements`, which hands it `parse_statement` rather than being
    # imported back — a delayed trigger contains a whole statement.
    "delayed",
    # The `<subject> <verb> …` opening. Split out of `statements` at the guard
    # below, and under it: `statements` hands it `parse_optional_action` rather
    # than being imported back, the same inversion `delayed` makes.
    "subject_verb",
    "statements",
    # A sentence whose subject is a pronoun pointing at the sentence before it
    # ("It gains …", "Untap that creature", "It loses \"enchant creature\""). Split
    # out of `riders` at the guard below, along the boundary that module already
    # drew: these answer "what does this pronoun name?", the rest of `riders`
    # answers "which branch does this clause belong to". Below `riders`, which
    # imports the binding and is never imported back.
    "pronouns",
    # The trailing clauses that attach to a sentence already parsed ("if you
    # do", "…, then …"). Above `statements` because reading one means reading
    # the statement it modifies.
    "riders",
    "costs", "parser",
]
LOWER_LAYERS = ["lowering", "statics", "lower"]

# `library` joined on the parse side when The Dark pushed `effects/cards.py`
# past the size guard: search, look-at and the library's top split off, reusing
# `lowering/library.py`'s name so the two halves mirror rather than fork.
EFFECT_FAMILIES = ["damage", "characteristics", "board", "cards", "stack", "combat", "game", "mana", "library"]
# The lowering side carries families the parsing side does not. Zone movement
# is one `return`/`exile`/`put` production each on the way in and a decision
# about *which handler moves the object* on the way out, so `lowering/board.py`
# outgrew the 1,000-line cap while `effects/board.py` stayed small. A near-empty
# `effects/zones.py` would buy back the symmetry and cost the thing symmetry is
# for — one home per template per side, findable from the family name.
# `library` and `mana` split out of `lowering/cards.py` the same way when it
# reached 959 of the 1,000 lines: the hidden-zone flows and mana production
# each lower to far more than their parse halves read. `mana` is no longer one
# of the asymmetric ones — `effects/cards.py` and `ast/cards.py` reached the cap
# in their turn and split off the same family under the same name, which is the
# mirror re-forming exactly as this note asked for. `library` still has no parse
# half, and `effects/cards.py` keeps the search flows for that reason.
# `counters` split out of `lowering/characteristics.py` at 975 lines, the day
# before a set ingest: a counter (CR 122) is a marker on an object, not a
# characteristic of it, and the two halves shared no imports. `keywords` split
# out of the same module the second time it reached the guard, on the same
# reasoning: CR 208 is what a creature's P/T *is* (layer 7), CR 702 is an
# ability it *has* (layer 6), and the two families shared no helper.
# `prevention` split out of `lowering/damage.py` at 1,011 lines, the round a
# two-source shield landed. The parse side keeps prevention with damage because
# the two read the same recipient and duration vocabulary; the lowering halves
# share not one helper, which is the same asymmetry the families above record.
# `attachments` split out of `lowering/board.py` at 1,008 lines, the round
# Takklemaggot's reattachment landed. An attachment is a *relation between two
# permanents* — every production in it lowers a legality measured across a pair
# (CR 303.4j) — where the rest of `board.py` lowers effects on one permanent at
# a time; the two shared one name, and that already lived in `_events.py`.
# `redirection` split out of `lowering/damage.py` the round The Dark's halved
# damage landed, at the 1,000 lines that module had been sitting on. The line is
# the CR's own: CR 120 is a source dealing damage, CR 614.9 is a replacement
# that changes who it reaches — the damage is still dealt, in full, by the same
# source. The two halves shared no helper, the same asymmetry `prevention`
# recorded above when it left the same module. `fighting` left it the same
# round and on the CR's other line: CR 701.14 is a keyword action, an atomic
# exchange between two creatures (701.14b — if either has left, neither deals
# damage), where everything left behind is one source dealing to a recipient.
LOWERING_FAMILIES = EFFECT_FAMILIES + ["zones", "exile", "counters", "keywords", "tapping", "prevention", "redirection", "fighting", "where_x", "control_flow", "attachments"]
# The AST side has no `library`: what a search or a look-at *is* — the pile, the
# filter, the fate of what was found — is a handful of nodes that sit perfectly
# well beside the other card nodes, and the split that made `library` a family
# on the other two sides was a size guard firing on the productions and the
# lowerings, not on the inventory. A near-empty `ast/library.py` would buy back
# the symmetry and cost the thing symmetry is for: one home per node, findable
# from the family name. Same asymmetry, opposite direction, as `zones`/`exile`
# above — which the lowering side carries and the parse side does not.
AST_FAMILIES = [family for family in EFFECT_FAMILIES if family != "library"]


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
        ("lowering", ("_common", "_events", "categories", "conditions"), ()),
        # `costs` is shared beside `_core` rather than a family: a cost is
        # charged on the way to the stack and never lowered, so it has no
        # `effects/` or `lowering/` twin to be a family of — and both
        # `conditions` ("if you paid the cost") and the roof read one.
        ("ast", ("_core", "_primitives", "_references", "costs"), ("statements",)),
    ],
    ids=["effects", "lowering", "ast"],
)
def test_families_import_only_their_package_shared_module(package, shared, roof):
    """Inside a subpackage, a family may reach the shared module and nothing else.

    `effects/` has no shared module of its own — its shared fragments are one
    level up in `phrases`, which is why its tuple is empty. `lowering/` keeps
    `_common`, `_events` and `categories` beside the families because all three
    are lowering concerns with no reader outside the package. `_events` split
    out of `_common` when it crossed the size guard below, and is shared for the
    same reason `_common` is rather than by taxonomy: six families read a table
    keyed by trigger-condition kind, and a fragment several families need is not
    one family's property. `ast/` keeps `_core`, the vocabulary its nodes are
    built from, and `conditions` beside it for the reason above.

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
    # `conditions` is shared with `_core` rather than a family: a condition is
    # built from every part of `_core` while nothing in `_core` is built from a
    # condition, and every family that lowers a conditional reads one.
    allowed = {"_core", "conditions", "costs", *AST_FAMILIES}
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


# Modules deliberately outside the layer order, each with the reason it is not
# a layer. Named rather than skipped, because an *un-named* module is silently
# unguarded — which is how `amounts`, `riders` and `subject_verb` sat outside
# this test's reach, and how the next split would have too.
UNLAYERED = {
    # The AST is its own family with its own ordering guard below.
    "ast",
    # Infrastructure the whole parser sits on: the token stream, the token
    # kinds, the error type. Every layer may read them, so ranking them says
    # nothing.
    "errors", "lexer", "stream",
    # Word tables refreshed from Scryfall (`scripts/fetch_vocabulary.py`).
    # Data, not a production.
    "vocabulary",
    # `amounts` and `nouns` are mutually recursive and cannot be ranked against
    # each other: a `Comparison` takes an `Amount` and an `ObjectFilter` takes a
    # `Comparison`, so `nouns` imports this at module level and it breaks the
    # cycle with a call-time import back. Ranking it either way would make the
    # test above demand a split that the grammar itself forbids — which is what
    # the first attempt at placing it discovered.
    "amounts",
    # Bridges to `engine/` rather than parsers: they import the derivation
    # tables and the text-keyed registries and no grammar sibling at all, so
    # they have no position among productions.
    "derived", "registries",
}


def test_every_grammar_module_is_placed_or_exempt():
    """A module nobody listed is a module this file does not guard.

    The import-direction test above ranks only what `PARSE_LAYERS` and
    `LOWER_LAYERS` name, so a new module escapes it entirely by being
    forgotten — silently, with the suite green. This is the assertion that
    turns forgetting into a failure.
    """
    declared = set(PARSE_LAYERS) | set(LOWER_LAYERS) | UNLAYERED
    present = {p.stem for p in GRAMMAR.glob("*.py")} | {
        p.name for p in GRAMMAR.iterdir() if p.is_dir() and not p.name.startswith("__")
    }
    present.discard("__init__")
    missing = sorted(present - declared)
    assert not missing, (
        "grammar modules outside the layer order and not exempt: "
        f"{missing}. Place each in PARSE_LAYERS/LOWER_LAYERS, or add it to "
        "UNLAYERED with the reason it is not a layer."
    )


# The modules inside a family package that are *not* families: the floors every
# family may read (`_core`'s vocabulary, `_common`'s helpers, `_events`' tables,
# `conditions`' question — a condition is built from the vocabulary while none
# of the vocabulary is built from a condition, which is why both `ast/` and
# `lowering/` have one and why other families import it) and the roofs built
# from all of them (`statements`' unions, `categories`' dispatch table). Neither
# has an independence to check. Named rather than skipped, for the same reason
# `UNLAYERED` is — see the test below.
FAMILY_SHARED = {
    "_common", "_core", "_events", "conditions", "categories", "statements",
    # `_core` split twice in one round, when The Dark pushed it past the size
    # guard below. `_references` took the object/player/target nodes
    # (`ObjectFilter` alone was 428 lines), `_primitives` took the two literal
    # amounts both halves need — a node `_references` and `_core` both use
    # cannot live in either without one importing the other — and `costs` took
    # the cost nodes. All three are floors, not families: `_core` re-exports
    # what they define, so no family imports them directly.
    "_primitives", "_references", "costs",
}


@pytest.mark.parametrize(
    "package, families",
    [
        ("effects", EFFECT_FAMILIES),
        ("lowering", LOWERING_FAMILIES),
        ("ast", AST_FAMILIES),
    ],
)
def test_every_family_module_is_listed_or_shared(package, families):
    """A family nobody listed is a family `test_families_do_not_import_each_other`
    never looks at.

    The same hole as `test_every_grammar_module_is_placed_or_exempt`, one level
    down: that test iterates the *list*, so a new family module escapes it by
    being forgotten — silently, with the suite green. `lowering/exile.py` was
    written the day this assertion was added and would have been the first to
    slip through.
    """
    present = {p.stem for p in (GRAMMAR / package).glob("*.py")}
    present.discard("__init__")
    missing = sorted(present - set(families) - FAMILY_SHARED)
    assert not missing, (
        f"{package}/ modules that are neither a listed family nor a shared "
        f"floor: {missing}. Add each to the family list, or to FAMILY_SHARED "
        "with the reason every family may read it."
    )


def test_no_module_defines_the_same_name_twice():
    """A module may not bind one top-level name twice.

    Python takes the later definition silently, so a duplicate is not an error,
    it is a *shadow*: the first definition still reads correctly, is still
    imported by name, and never runs. The Dark's five-way parallel round landed
    four of them in one merge, because git resolves "both branches added a
    function" as two functions rather than as a conflict — a clean textual merge
    that is not a clean merge (SET_PLAYBOOK, "two merge hazards where taking
    either side passes the suite").

    Each of the four failed differently, which is why this asks the shape rather
    than any one symptom: two were harmless twins, one shadowed a *guard*
    (`_lower_reveal_hand`'s refusal of an unhandled player kind, so "each player
    reveals their hand" would have lowered to one player revealing), and one
    shadowed a production that returned ``Statement | None`` with one that
    raised instead, which the caller had just been taught to expect None from.
    """
    offenders = []
    for root in ("engine", "tests", "web", "scripts"):
        for path in sorted(pathlib.Path(root).rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # not ours to police here
                continue
            names = [
                node.name for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            ]
            for name, count in collections.Counter(names).items():
                if count > 1:
                    offenders.append(f"{path}: {name} defined {count}x")
    assert not offenders, (
        "a top-level name is bound twice in one module — the later definition "
        "silently wins and the earlier one never runs:\n  " + "\n  ".join(offenders)
    )
