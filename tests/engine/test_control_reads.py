"""Guard: "who controls this?" has one answer, and it is the control seam.

CR 613 layer 2 is control-changing, and this engine models control as **which
``player.battlefield`` list a permanent sits in**. That makes every open-coded
``for perm in player.battlefield`` a control read: it is not a zone question
with an incidental control answer, it *is* the answer. Layers 4-7 could be
wired by changing one accessor because they were flags a reader consulted;
layer 2 cannot, because there are no readers to change until the zone reads
stop — which is what this guard holds.

The seam lives on ``Game`` (``engine/mixins/helpers.py``):

  * ``all_permanents()``           - every permanent on the battlefield
  * ``permanents_with_controller()`` - ditto, paired with the controlling seat
  * ``controlled_by(seat)``       - what one seat controls
  * ``permanents_matching(pred)`` - the filtered form
  * ``controller_index_of(perm)`` / ``controls(seat, perm)`` / ``is_on_battlefield(perm)``

Two live bugs came out of the migration, both of the same shape:
``permanent in player.battlefield`` compares :class:`Permanent` **by value**
(it is a mutable dataclass with generated ``__eq__``), so it answers yes for an
opponent's identically-stated copy of the same card. CR 704.5m read that way
would keep an Aura alive after its enchanted creature died, and the world-rule
and role-rule sweeps would ``remove()`` the look-alike instead of the permanent
they meant. ``controls`` / ``is_on_battlefield`` compare by identity.

**Writing the zone is not reading it.** A loop that rebuilds
``X.battlefield`` — either the ``X.battlefield = [p for p in X.battlefield if
...]`` comprehension or a ``survivors`` loop whose block assigns the list back
— is exempt structurally rather than by name, because the exemption is a
property of the code shape and cannot go stale.
"""

import ast
import functools
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCANNED = (ROOT / "engine", ROOT / "web")

# The one module allowed to read zone membership: it *is* the seam. Wiring
# layer 2 means changing these methods and nothing else.
SEAM = "engine/mixins/helpers.py"

# Genuine exceptions, by ``path::function`` so they survive line edits, each
# with the reason it cannot ask the seam. Kept small on purpose: every entry is
# a site that would have to be revisited to finish layer 2.
ACKNOWLEDGED: dict[str, str] = {
    "engine/handlers/_common.py::pick_target_permanent": (
        "Positional. The web protocol addresses a permanent by its *slot* on a "
        "controller's battlefield, and this is the function that honours that "
        "index; it takes a PlayerState and no Game, so there is no seam to ask."
    ),
    "engine/ai_simulator.py::_assert_expected": (
        "Reads detached PlayerState clones taken before and after a spell, not "
        "the live board. A clone belongs to no Game, and comparing snapshots is "
        "the whole point of the check."
    ),
}


def _module_name(path: pathlib.Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def _scanned_files() -> list[pathlib.Path]:
    found: list[pathlib.Path] = []
    for base in SCANNED:
        found.extend(sorted(base.rglob("*.py")))
    return found


def _battlefield_attr(node: ast.AST) -> ast.Attribute | None:
    """*node* as a ``<expr>.battlefield`` attribute access, or None."""
    if isinstance(node, ast.Attribute) and node.attr == "battlefield":
        return node
    return None


def _same_target(first: ast.AST, second: ast.AST) -> bool:
    """Whether two ``<expr>.battlefield`` expressions name the same list."""
    return ast.dump(first) == ast.dump(second)


def _rebuild_assign_targets(body: list[ast.stmt]) -> list[ast.Attribute]:
    """The ``X.battlefield`` lists assigned to anywhere in this statement list."""
    targets = []
    for statement in body:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                attr = _battlefield_attr(target)
                if attr is not None:
                    targets.append(attr)
    return targets


def _exempt_reads(tree: ast.Module) -> set[int]:
    """Node ids of ``.battlefield`` reads that are part of a zone *write*.

    Two shapes, both of them "rebuild this list without the permanents that
    left": the comprehension (``X.battlefield = [p for p in X.battlefield if p
    is not gone]``) and the survivors loop (``for p in X.battlefield: ...`` with
    ``X.battlefield = survivors`` as a sibling statement).
    """
    exempt: set[int] = set()
    for node in ast.walk(tree):
        # Shape 1: assignment whose value re-reads the list being assigned.
        if isinstance(node, ast.Assign):
            for target in node.targets:
                attr = _battlefield_attr(target)
                if attr is None:
                    continue
                for inner in ast.walk(node.value):
                    read = _battlefield_attr(inner)
                    if read is not None and _same_target(read.value, attr.value):
                        exempt.add(id(read))
        # Shape 2: a loop over the list, in a block that assigns the list back.
        for field in ("body", "orelse", "finalbody"):
            body = getattr(node, field, None)
            if not isinstance(body, list):
                continue
            rebuilt = _rebuild_assign_targets(body)
            if not rebuilt:
                continue
            for statement in body:
                if not isinstance(statement, ast.For):
                    continue
                read = _battlefield_attr(statement.iter)
                if read is None:
                    continue
                if any(_same_target(read.value, done.value) for done in rebuilt):
                    exempt.add(id(read))
    return exempt


def _enclosing_functions(tree: ast.Module) -> dict[int, str]:
    """Every node id mapped to the name of the function it sits in."""
    owner: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                owner.setdefault(id(child), node.name)
    return owner


@functools.lru_cache(maxsize=None)
def _raw_control_reads(path: pathlib.Path) -> tuple[tuple[int, str, str], ...]:
    """``(line, function, source)`` for each zone-membership read in *path*.

    Cached: three tests sweep the same tree, and this scan is the whole cost of
    the guard."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines()
    exempt = _exempt_reads(tree)
    owners = _enclosing_functions(tree)
    found: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        reads: list[ast.AST] = []
        if isinstance(node, ast.For):
            reads = [node.iter]
        elif isinstance(node, ast.comprehension):
            reads = [node.iter]
        elif isinstance(node, ast.Compare):
            # ``perm in player.battlefield`` / ``perm not in player.battlefield``
            if any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
                reads = list(node.comparators)
        for candidate in reads:
            attr = _battlefield_attr(candidate)
            if attr is None or id(attr) in exempt:
                continue
            found.append((attr.lineno, owners.get(id(node), "<module>"), lines[attr.lineno - 1].strip()))
    return tuple(found)


def _offenders() -> list[tuple[str, int, str, str]]:
    offenders = []
    for path in _scanned_files():
        module = _module_name(path)
        if module == SEAM:
            continue
        for line, function, text in _raw_control_reads(path):
            if f"{module}::{function}" in ACKNOWLEDGED:
                continue
            offenders.append((module, line, function, text))
    return offenders


def test_zone_membership_is_read_only_through_the_control_seam():
    """A raw ``player.battlefield`` iteration or ``in`` test outside the seam is
    a second opinion about who controls what — and the day control becomes a
    derived characteristic, it is the opinion that will be wrong."""
    offenders = _offenders()
    assert not offenders, (
        "raw battlefield membership read outside " + SEAM + " — ask "
        "game.all_permanents() / permanents_with_controller() / controlled_by(seat) / "
        "controls(seat, perm) / is_on_battlefield(perm) so CR 613 layer 2 has one "
        "answer to change:\n"
        + "\n".join(f"  {f}:{n} in {fn}(): {t}" for f, n, fn, t in offenders)
    )


def test_the_seam_still_owns_the_reads_it_claims():
    """The guard above is only worth anything while the seam actually reads the
    zone. If ``helpers.py`` stopped touching ``player.battlefield``, the
    exemption would be protecting nothing and every other file's compliance
    would be accidental."""
    seam = ROOT / SEAM
    tree = ast.parse(seam.read_text(encoding="utf-8"))
    methods = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }
    required = {
        "all_permanents", "permanents_with_controller", "controlled_by",
        "permanents_matching", "controller_index_of", "controls", "is_on_battlefield",
    }
    missing = sorted(required - methods)
    assert not missing, f"{SEAM} no longer defines the control seam: {missing}"
    assert _raw_control_reads(seam), (
        f"{SEAM} no longer reads player.battlefield — the seam has moved, so "
        "SEAM here points at the wrong module and the guard is vacuous"
    )


@pytest.mark.parametrize("entry", sorted(ACKNOWLEDGED))
def test_no_acknowledgement_has_gone_stale(entry):
    """An acknowledgement whose function has been migrated (or renamed away) is
    a standing exemption for whatever takes its place. Same failure mode the
    layer-4 guard's staleness test caught: the exemption outlived its reason."""
    module, _, function = entry.partition("::")
    path = ROOT / module
    assert path.exists(), f"{entry} names a file that no longer exists"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert function in names, f"{entry}: {function}() is gone — drop the acknowledgement"
    owners = _enclosing_functions(tree)
    still_raw = any(
        owners.get(id(node)) == function
        for node in ast.walk(tree)
        for _ in [0]
        if isinstance(node, (ast.For, ast.comprehension, ast.Compare))
        and any(
            _battlefield_attr(candidate) is not None
            for candidate in (
                [node.iter] if isinstance(node, (ast.For, ast.comprehension))
                else list(node.comparators)
            )
        )
    )
    assert still_raw, (
        f"{entry} no longer reads the battlefield directly — drop the "
        f"acknowledgement ({ACKNOWLEDGED[entry]})"
    )
