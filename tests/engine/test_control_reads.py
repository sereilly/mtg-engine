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

--------------------------------------------------------------------------

**Addressing one permanent lives here too**, because it is the same mistake
one step further in. ``player.battlefield[i]`` is not a name for a permanent,
it is a name for a *slot*, and a slot is only true until something leaves the
battlefield and renumbers everything after it. That instability is why the
engine grew positional indices in the first place: identity comparison was
unsafe (``Permanent`` has value equality, so ``in`` / ``.index()`` /
``.remove()`` match an opponent's look-alike), so a position was the only
address left. ``Permanent.permanent_id`` removes the reason, and the seam
resolves it — ``permanent_by_id`` / ``find_permanent_by_id`` /
``permanent_id_of`` / ``permanent_at`` / ``battlefield_index_of``.

Two guards below, of different strengths:

  * ``.battlefield.index(x)`` and ``.battlefield.remove(x)`` are **banned**.
    They are the value-comparison bug in its purest form and there are none
    left, so there is no baseline to hold — only a zero.
  * ``player.battlefield[i]`` — and the aliased ``bf = x.battlefield; bf[i]``,
    which is the same read one name later — is **ratcheted**, per module, by
    ``POSITIONAL_BASELINE``. It cannot go up. It is not zero because the
    combat state (``combat_attackers``, ``combat_blockers``, the banding and
    pile maps) is keyed by index end to end, and so is the wire protocol that
    carries it; converting those is its own migration, and pretending it is
    done by exempting the files would leave nothing guarding the rest.
"""

import ast
import functools
import re
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


# ---------------------------------------------------------------------------
# Addressing one permanent: identity, not position
# ---------------------------------------------------------------------------

# Per-module count of surviving ``X.battlefield[i]`` reads. A ratchet, not an
# allowance: it may fall (lower the number in the same commit) and it may never
# rise. A module that reaches zero is deleted from the dict, so the dict itself
# shrinks as the migration lands and the guard becomes a ban by attrition.
#
# What is still here is one thing wearing many names: **combat**. The engine's
# combat state — who is attacking, who blocks whom, the banding assignments, the
# Raging River piles, Camouflage's piles — is a set of dicts keyed by battlefield
# index, and the wire protocol and the canvas's arrows are keyed the same way.
# Every count below is a read of one of those maps or of an index that arrived
# from a client. They convert together or not at all.
POSITIONAL_BASELINE: dict[str, int] = {
    "engine/ai_policy.py": 11,
    "engine/ai_simulator.py": 2,
    "engine/card_hooks.py": 2,
    "engine/handlers/_common.py": 2,
    "engine/handlers/board_misc.py": 2,
    "engine/handlers/combat.py": 2,
    "engine/handlers/damage.py": 1,
    "engine/handlers/destruction.py": 3,
    "engine/handlers/prevention.py": 2,
    "engine/handlers/zones.py": 2,
    "engine/legality.py": 2,
    "engine/mixins/effects.py": 2,
    "engine/mixins/permanent_state.py": 1,
    "engine/mixins/stack/activation.py": 2,
    "engine/mixins/stack/casting.py": 5,
    "engine/mixins/stack/choices.py": 4,
    "engine/phases/combat_damage_step.py": 17,
    "engine/phases/combat_phase.py": 11,
    "engine/phases/declare_attackers_step.py": 4,
    "engine/phases/declare_blockers_step.py": 16,
    "engine/phases/untap_step.py": 1,
    "engine/phases/upkeep_step.py": 3,
    "engine/replacements.py": 1,
    # web/actions.py's four sites moved with their handlers when the dispatch
    # became a registry: the cast plumbing's one and the turn handlers' three.
    "web/action_helpers.py": 1,
    "web/action_turn.py": 2,
    "web/combat_prompts.py": 3,
    "web/debug_actions.py": 3,
    "web/game_flow.py": 4,
    "web/prompts.py": 1,
    "web/serialization.py": 1,
    "web/state_view.py": 2,
}


def _battlefield_owner(node: ast.AST) -> ast.Attribute | None:
    """*node* as an ``<expr>.battlefield`` attribute access, or None."""
    return _battlefield_attr(node)


def _battlefield_aliases(tree: ast.Module) -> set[str]:
    """Local names bound to a battlefield list — ``battlefield = target.battlefield``.

    Counted because otherwise the guard is one line away from being bypassed:
    aliasing the list and subscripting the alias is the same positional read,
    and it is already the majority spelling in ``mixins/stack/casting.py``.
    Names are collected module-wide rather than per function; a name that means
    "a battlefield" in one function and something else in another is a naming
    problem of its own."""
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or _battlefield_attr(node.value) is None:
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                aliases.add(target.id)
    return aliases


@functools.lru_cache(maxsize=None)
def _positional_reads(path: pathlib.Path) -> tuple[tuple[int, str], ...]:
    """``(line, source)`` for each positional battlefield read in *path* —
    ``<expr>.battlefield[...]`` and the aliased ``bf = x.battlefield; bf[...]``."""
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source)
    aliases = _battlefield_aliases(tree)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Subscript):
            continue
        subject = node.value
        if _battlefield_owner(subject) is None and not (
            isinstance(subject, ast.Name) and subject.id in aliases
        ):
            continue
        found.append((node.lineno, lines[node.lineno - 1].strip()))
    return tuple(found)


@functools.lru_cache(maxsize=None)
def _value_comparison_calls(path: pathlib.Path) -> tuple[tuple[int, str], ...]:
    """``(line, source)`` for each ``.battlefield.index(...)`` / ``.remove(...)``."""
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in {"index", "remove"}:
            continue
        if _battlefield_owner(node.func.value) is None:
            continue
        found.append((node.lineno, lines[node.lineno - 1].strip()))
    return tuple(found)


def test_a_permanent_is_never_located_by_value():
    """``list.index`` and ``list.remove`` compare with ``==``, and
    :class:`Permanent` is a dataclass whose ``__eq__`` is generated field by
    field — so both find an opponent's identically-stated copy of the same card
    in preference to the object they were handed.

    This is not theoretical: Crumble read its target's slot back with
    ``battlefield.index(artifact)`` and would have destroyed the *first* of two
    equal Moxen, and four "remove this permanent" sites had the same shape.
    Identity is ``[p for p in X.battlefield if p is not perm]``, and the slot of
    a known permanent is ``game.battlefield_index_of(perm)``."""
    offenders = []
    for path in _scanned_files():
        module = _module_name(path)
        for line, text in _value_comparison_calls(path):
            offenders.append(f"  {module}:{line}: {text}")
    assert not offenders, (
        "a battlefield permanent located by value — Permanent compares field by "
        "field, so this matches a look-alike. Use identity (`p is not perm`) or "
        "the seam's game.battlefield_index_of(perm):\n" + "\n".join(offenders)
    )


def test_positional_battlefield_indexing_does_not_grow():
    """``player.battlefield[i]`` names a slot, and a slot stops meaning the same
    permanent the moment anything ahead of it leaves the battlefield. The stable
    address is ``Permanent.permanent_id``, resolved through the seam.

    A ratchet rather than a ban, because the remaining reads are all combat
    state whose *keys* are indices — they cannot be migrated one call site at a
    time. What the ratchet buys is that no new one can appear while that is
    true."""
    measured: dict[str, int] = {}
    samples: dict[str, list[str]] = {}
    for path in _scanned_files():
        module = _module_name(path)
        if module == SEAM:
            # The seam is where a positional lookup legitimately lives: it is
            # the module that turns an index from the wire into a permanent
            # (``permanent_at``) and back (``battlefield_index_of``).
            continue
        reads = _positional_reads(path)
        if reads:
            measured[module] = len(reads)
            samples[module] = [f"  {module}:{line}: {text}" for line, text in reads]

    grew = [
        f"{module}: {count} (baseline {POSITIONAL_BASELINE.get(module, 0)})"
        for module, count in sorted(measured.items())
        if count > POSITIONAL_BASELINE.get(module, 0)
    ]
    assert not grew, (
        "new positional battlefield indexing. Address the permanent by its "
        "stable id instead — game.permanent_by_id(pid) / find_permanent_by_id / "
        "permanent_at(seat, index) at a wire boundary:\n"
        + "\n".join(grew)
        + "\n"
        + "\n".join(line for module in sorted(measured) for line in samples[module]
                    if measured[module] > POSITIONAL_BASELINE.get(module, 0))
    )


def test_the_positional_baseline_is_not_stale():
    """A baseline higher than the truth is a standing allowance to put the reads
    back. Lower the number (or delete the entry) in the commit that removes
    them, which is what makes the ratchet ratchet."""
    measured = {
        _module_name(path): len(_positional_reads(path))
        for path in _scanned_files()
        if _module_name(path) != SEAM and _positional_reads(path)
    }
    stale = [
        f"{module}: baseline {expected}, actually {measured.get(module, 0)}"
        for module, expected in sorted(POSITIONAL_BASELINE.items())
        if measured.get(module, 0) < expected
    ]
    assert not stale, (
        "POSITIONAL_BASELINE is above the real count — lower these entries "
        "(delete the ones now at zero):\n  " + "\n  ".join(stale)
    )


# ---------------------------------------------------------------------------
# Leaving the battlefield is one transition
# ---------------------------------------------------------------------------

# The writes that are legitimately not removals, each with the reason it cannot
# go through the choke point. Keyed by ``path::function`` so they survive line
# edits, and checked for staleness below like every other acknowledgement here.
_BATTLEFIELD_WRITE_EXEMPTIONS = {
    # The projection of a derived controller change (CR 613 layer 2). The
    # permanent moves between two battlefields without leaving either zone, so
    # firing the leave transition here would be wrong.
    "engine/mixins/helpers.py::_sync_control": "control change is a move, not a removal",
    # The choke point itself.
    "engine/mixins/helpers.py::remove_all_from_battlefield": "this is the transition",
    # Debug-menu raw-state injection replaces a whole battlefield wholesale;
    # nothing "leaves", the board is being rebuilt from a supplied payload.
    "web/debug_actions.py::_apply_raw_state": "wholesale board replacement",
}

_MUTATORS = {"pop", "remove", "clear"}


def _battlefield_writes(path: pathlib.Path):
    """(function, line, text) for every statement that shortens or replaces a
    battlefield list.

    Walked with ``ast`` rather than matched with a regex: the first version of
    this scanned raw lines and flagged a *docstring* in the seam that mentions
    ``.battlefield.remove()`` while explaining why it is banned. A guard that
    reports its own documentation is a guard people learn to skim.
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines()
    spans = [
        (node.lineno, node.end_lineno, node.name)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]

    def enclosing(lineno: int) -> str:
        name = ""
        for start, end, candidate in spans:
            if start <= lineno <= end:
                name = candidate
        return name

    def is_battlefield(node) -> bool:
        return isinstance(node, ast.Attribute) and node.attr == "battlefield"

    hits: list[tuple[str, int, str]] = []
    for node in ast.walk(tree):
        # `x.battlefield = ...` — a wholesale replacement.
        if isinstance(node, ast.Assign) and any(is_battlefield(t) for t in node.targets):
            hits.append((enclosing(node.lineno), node.lineno, lines[node.lineno - 1].strip()))
        # `x.battlefield.pop(...)` / `.remove(...)` / `.clear()`
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _MUTATORS
            and is_battlefield(node.func.value)
        ):
            hits.append((enclosing(node.lineno), node.lineno, lines[node.lineno - 1].strip()))
    return sorted(set(hits), key=lambda entry: entry[1])


def test_leaving_the_battlefield_goes_through_one_transition():
    """The battlefield list was rebuilt or shortened in **41 places**, in three
    spellings — filter-by-identity, ``pop`` by index, and rebuild-from-survivors.

    That is the same shape ``become_tapped`` had at seventeen sites, and it has
    the same consequence: anything that must happen when a permanent leaves has
    41 places to be wired into and 41 places to be forgotten. The live example
    is the combat maps, every one of which is keyed by battlefield index, so a
    permanent leaving mid-combat renumbers every attacker and blocker recorded
    after it — and there was nowhere to put the remap.

    ``Game.remove_from_battlefield`` / ``remove_all_from_battlefield`` is that
    place. A new open-coded rebuild is not a style problem; it is a site the
    next thing hung off the transition will silently miss.
    """
    offenders = []
    for path in _scanned_files():
        module = _module_name(path)
        for function, line, text in _battlefield_writes(path):
            if _BATTLEFIELD_WRITE_EXEMPTIONS.get(f"{module}::{function}"):
                continue
            offenders.append(f"  {module}:{line} in {function}(): {text}")
    assert not offenders, (
        "a battlefield list rebuilt outside the seam — call "
        "game.remove_from_battlefield(perm) or remove_all_from_battlefield(perms) "
        "so the leave transition has one place to happen:\n" + "\n".join(offenders)
    )


@pytest.mark.parametrize("key", sorted(_BATTLEFIELD_WRITE_EXEMPTIONS))
def test_no_battlefield_write_exemption_has_gone_stale(key):
    """An exemption naming a function that no longer writes a battlefield is a
    comment nobody will re-check — and it silently widens to whatever else that
    name comes to mean."""
    module, function = key.split("::")
    path = ROOT / module
    assert path.exists(), f"{module} no longer exists"
    writes = [entry for entry in _battlefield_writes(path) if entry[0] == function]
    assert writes, (
        f"{key} is exempted from the battlefield-write rule but no longer "
        "writes one — delete the exemption"
    )
