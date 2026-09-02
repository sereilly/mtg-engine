"""Guard: a *dispatch* on a permanent's name asks the effective name.

``perm.card.name`` is the printed face, which no effect can change. What a
permanent is actually *named* is a layer question — CR 707.2 lists name first
among the copiable values (layer 1), and a text-changing effect may in
principle rewrite it (layer 3) — so a decision keyed on the name has to read
``perm.effective_card.name``, exactly as ``tests/engine/test_layer_reads.py``
already holds for ``type_line``, ``colors``, ``oracle_text`` and ``keywords``.

``card.name`` could not join that regex ratchet, because hundreds of its reads
are legitimate: log lines, prompt labels, serialization display fields, the
AI-batch tally. The distinction that separates those from the defect is the
one ``test_card_name_reads.py`` draws for name *literals* — **dispatch versus
mention** — applied here to the field. A name deciding behaviour is, in
Python, one of three shapes:

  * an operand of a comparison or membership test (``==``, ``in``);
  * the key of a subscript *read* (``hooks[perm.card.name]`` — writing under
    the key, ``counter[perm.card.name] += 1``, records rather than decides);
  * the argument of a ``.get(...)`` lookup.

Everything else — an f-string, a label argument, a dict value, a bare
assignment — is a mention and stays out of scope. (The classification is
syntactic: a name stored first and compared later, or a lookup spelled through
a helper, is invisible to it. The layer_reads regexes accept the same limit.)

The census that built this guard found 45 dispatch-shaped reads. Four sites
were live bugs a shipped card demonstrates, fixed in the same commit and held
by ``tests/rules/test_copy_effects.py``'s "copied name" section:

  * the ``same_name`` P/T count (a Clone of Plague Rats neither was one nor
    counted, ``mixins/permanent_state.py``);
  * the Guardian Beast untapped-protector check (``mixins/effects.py``);
  * the ``ON_LEAVE_BATTLEFIELD`` hook lookup (a Clone of Gaea's Liege left
    its Forests standing, ``mixins/helpers.py``);
  * Goblin Artisans' "another creature named ~" rival scan
    (``handlers/stack.py``).

The rest are ratcheted below rather than fixed, because no card in the pool
can demonstrate a wrong answer for them — this repo's rule is that a fix with
no card to verify it is a guess. They fall into three families:

  * **The interactive upkeep prompt protocol** (``phases/upkeep_step.py``,
    ``phases/upkeep_effects.py``): ``human_choices`` / ``trigger_targets`` /
    ``optional_choices`` dicts keyed by card name on *both* the arming side
    and the reading side, in the same files. Printed-name keys are consistent
    with the printed-name labels beside them; converting one side alone
    desyncs the wire, so they convert together (to permanent ids) or not at
    all — the combat-map story in ``test_control_reads.py``.
  * **Wire/test addressing** (``mixins/helpers.py``'s
    ``_find_controlled_permanent``, ``phases/beginning_phase.py``,
    ``web/action_helpers.py``): a client or a test names a permanent by the
    printed name serialization gave it. Same protocol both ways.
  * **Uncopyable name-keyed statics** (``phases/draw_step.py`` and
    ``web/turn_steps.py`` on Island Sanctuary; ``web/state_view.py`` and
    ``web/serialization.py`` on Gloom): both are enchantments, and the pool
    has no way to copy an enchantment or change any permanent's name — so the
    effective-name spelling would be a fix nothing can exercise.
"""

from __future__ import annotations

import ast
import functools
import pathlib

from tests.source_index import python_files, source_text, source_tree

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _module_name(path: pathlib.Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def _scanned_files() -> tuple[pathlib.Path, ...]:
    return python_files("engine", "web")


def _is_printed_name_read(node: ast.AST) -> bool:
    """``<something>.card.name`` — the possessive, a permanent (or stack item,
    or execution context) reached *through* for its printed face. A bare
    ``card.name`` is a local that already is a CardDefinition, which is the
    same carve-out ``test_layer_reads.py`` documents for its patterns."""
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "name"
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "card"
    )


def _is_dispatch(node: ast.AST, parents: dict[int, ast.AST]) -> bool:
    """Whether the read at *node* decides behaviour, by its syntactic seat."""
    prev: ast.AST = node
    cur = parents.get(id(node))
    while cur is not None:
        if isinstance(cur, ast.Compare):
            return True
        if isinstance(cur, ast.Subscript) and prev is not cur.value:
            # The key of a lookup decides; the key of a write records.
            return isinstance(cur.ctx, ast.Load)
        if isinstance(cur, ast.Call):
            if prev is cur.func:
                return False
            return (
                isinstance(cur.func, ast.Attribute)
                and cur.func.attr == "get"
                and any(prev is arg for arg in cur.args)
            )
        if isinstance(cur, ast.JoinedStr):
            return False
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
            return False
        prev, cur = cur, parents.get(id(cur))
    return False


@functools.lru_cache(maxsize=None)
def _dispatch_reads(path: pathlib.Path) -> tuple[tuple[int, str], ...]:
    """``(line, source)`` for every dispatch-shaped printed-name read."""
    tree = source_tree(path)
    lines = source_text(path).splitlines()
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    return tuple(
        (node.lineno, lines[node.lineno - 1].strip())
        for node in ast.walk(tree)
        if _is_printed_name_read(node) and _is_dispatch(node, parents)
    )


# Per-module count of surviving dispatch-shaped ``.card.name`` reads. A
# ratchet, not an allowance: it may fall (lower the number in the same commit)
# and it may never rise. A module that reaches zero is deleted from the dict.
# Which family each module belongs to — and why it is ratcheted rather than
# fixed — is in the module docstring above.
PRINTED_NAME_DISPATCH_BASELINE: dict[str, int] = {
    # The interactive upkeep prompt protocol: name-keyed on both sides.
    "engine/phases/upkeep_effects.py": 18,
    "engine/phases/upkeep_step.py": 7,
    # Wire/test addressing by the printed name serialization handed out.
    "engine/mixins/helpers.py": 2,
    "engine/phases/beginning_phase.py": 2,
    "web/action_helpers.py": 2,
    # Island Sanctuary (an enchantment nothing in the pool can copy/rename).
    "engine/phases/draw_step.py": 1,
    "web/turn_steps.py": 1,
    # Gloom (the same, through the client-hint payloads).
    "web/serialization.py": 1,
    "web/state_view.py": 1,
}


def test_no_new_dispatch_on_a_printed_name():
    """A new comparison/lookup on ``.card.name`` is the legend-rule bug over
    again: it reads the printed face and misses every copy (CR 707.2) and
    every text change (CR 612.1). Ask ``perm.effective_card.name`` — or, if
    the read really is protocol keyed printed on both sides, raise the
    module's number here with the reason written into the docstring."""
    measured: dict[str, int] = {}
    samples: dict[str, list[str]] = {}
    for path in _scanned_files():
        module = _module_name(path)
        reads = _dispatch_reads(path)
        if reads:
            measured[module] = len(reads)
            samples[module] = [f"  {module}:{line}: {text}" for line, text in reads]

    grew = [
        f"{module}: {count} (baseline {PRINTED_NAME_DISPATCH_BASELINE.get(module, 0)})"
        for module, count in sorted(measured.items())
        if count > PRINTED_NAME_DISPATCH_BASELINE.get(module, 0)
    ]
    assert not grew, (
        "new dispatch-shaped read of a printed name. What a permanent is named "
        "is a layer-1/-3 answer — read perm.effective_card.name:\n"
        + "\n".join(grew)
        + "\n"
        + "\n".join(
            line
            for module in sorted(measured)
            for line in samples[module]
            if measured[module] > PRINTED_NAME_DISPATCH_BASELINE.get(module, 0)
        )
    )


def test_the_printed_name_baseline_is_not_stale():
    """A baseline higher than the truth is a standing allowance to put the
    reads back. Lower the number (or delete the entry) in the commit that
    removes them, which is what makes the ratchet ratchet. This is also the
    guard's vacuity check: if the classifier stopped seeing the reads that are
    known to exist, every count would read as zero and fail here."""
    measured = {
        _module_name(path): len(_dispatch_reads(path))
        for path in _scanned_files()
        if _dispatch_reads(path)
    }
    stale = [
        f"{module}: baseline {expected}, actually {measured.get(module, 0)}"
        for module, expected in sorted(PRINTED_NAME_DISPATCH_BASELINE.items())
        if measured.get(module, 0) < expected
    ]
    assert not stale, (
        "the printed-name dispatch baseline is stale — lower it to match:\n"
        + "\n".join(stale)
    )


def test_the_fixed_sites_stay_fixed():
    """The four modules whose dispatch reads were live bugs (see the module
    docstring) are not in the baseline at all, so any dispatch-shaped read
    reappearing there fails the growth test above. This pins the stronger
    claim while they are at zero: the fix was to *leave* the printed face,
    not to move the read around inside the file."""
    for module in (
        "engine/mixins/permanent_state.py",
        "engine/mixins/effects.py",
        "engine/handlers/stack.py",
    ):
        path = ROOT / module
        assert path.exists(), f"{module} moved — update this list"
        assert not _dispatch_reads(path), (
            f"{module} dispatches on a printed name again: {_dispatch_reads(path)}"
        )
