"""Guard: a trigger condition a card compiles to must have something that fires it.

**A condition can parse on both sides of the pipeline and have no dispatcher at
all.** Four were found that way one card at a time —
``creature_attacks_or_blocks`` (round 28), ``creature_you_control_dies`` (30),
``you_gain_life`` (33), ``creature_becomes_blocked`` (34) — and a fifth,
``draws_card``, survived until round 58 with **two supported cards behind it**:
Lorescale Coatl and Burlfist Oak compiled a real instruction under a condition
nothing announced, entered play, and did nothing. The support report counted
them as working the whole time, because the compiler can see that a condition
parsed and cannot see whether the game ever says it happened.

Every earlier find was a person noticing. This is the check, and the shape it
has to take follows from how many ways a trigger can be dispatched: the event
bus (``emit``), the hand-placed scans that predate it
(``iter_triggered_abilities(condition_kinds=…)``), the upkeep registry's
``@upkeep_effect(condition, kind)`` pairs, and a plain comparison against
``trig.condition.kind`` in a phase step. Enumerating those is a list of
mechanisms, and a list of mechanisms goes stale exactly like a list of fire
sites.

So the question asked is the weaker one that cannot: **does this kind's name
appear anywhere in the engine at all, other than in the tables that declare
it?** A kind that appears only in the two parse tables has nothing that could
possibly dispatch it, whatever the mechanism. Docstrings are excluded, because
``engine/events.py``'s own docstring names ``draws_card`` — as an example of
this very failure — and a guard that a comment can satisfy is not one.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from engine.card_loader import load_cards, manifest_set_paths
from engine.oracle import compile_card_oracle

ENGINE = pathlib.Path(__file__).resolve().parents[2] / "engine"

# The tables that *declare* the vocabulary rather than acting on it: the two
# parse tables, one per side of the pipeline, and the event-filter rows that say
# which announcement a trigger belongs to. A kind named only in these is a kind
# the compiler can produce and nothing can act on — the filter tables are
# excluded for exactly the same reason as the parse tables, since a filter with
# no announcement behind it narrows an event that never happens.
DECLARATION_TABLES = frozenset({
    "WHENEVER_TRIGGER_PATTERNS", "WHEN_TRIGGER_PATTERNS", "AT_TRIGGER_PATTERNS",
    "_WHENEVER_EVENTS", "_FILTERED_EVENTS", "_SUBJECT_LED_EVENTS", "_AT_EVENTS",
    "_SEAT_SCOPED_EVENTS", "_SUBJECT_LED_FILTER_KEYS",
})


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """The ``ast.Constant`` nodes that are docstrings, by identity."""
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
            found.add(id(first.value))
    return found


def _mentioned_kinds() -> set[str]:
    mentioned: set[str] = set()
    for path in sorted(ENGINE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        skip = _docstring_nodes(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) in DECLARATION_TABLES for t in node.targets
            ):
                skip |= {id(c) for c in ast.walk(node)}
            elif isinstance(node, ast.AnnAssign) and (
                getattr(node.target, "id", None) in DECLARATION_TABLES
            ):
                skip |= {id(c) for c in ast.walk(node)}
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in skip
            ):
                mentioned.add(node.value)
    return mentioned


@pytest.fixture(scope="module")
def announced() -> set[str]:
    found = _mentioned_kinds()
    assert "draws_card" in found, (
        "the reader is broken, not the engine — this kind is announced by the "
        "draw sweep in mixins/game_ending.py"
    )
    assert "you_gain_life" in found and "upkeep_enchanted_controller" in found
    return found


def _live_conditions() -> list[tuple[str, str]]:
    """(card name, condition kind) for every trigger a *supported* card
    compiles with a real instruction behind it.

    Supported, because an unsupported card is already refusing loudly; and with
    an instruction, because a trigger whose behaviour lives in a card hook has
    no instruction here and is fired by the hook's own site.
    """
    found = []
    for card in load_cards(manifest_set_paths(include_measured=True)):
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for trig in program.triggered_abilities:
            if not trig.supported or trig.instruction is None or trig.condition is None:
                continue
            found.append((card.name, trig.condition.kind))
    return found


def test_every_live_trigger_condition_has_a_fire_site(announced):
    orphans = sorted(
        {(kind, name) for name, kind in _live_conditions() if kind not in announced}
    )
    assert not orphans, (
        "trigger condition(s) with no dispatcher — these cards compile "
        "supported and do nothing:\n"
        + "\n".join(f"  {kind}: {name}" for kind, name in orphans)
    )


def test_the_pool_produces_conditions_to_check():
    """The guard is vacuous if the enumeration comes back empty, and it reads
    the pool rather than a list — so a compiler change that stopped producing
    conditions at all would fail here rather than pass quietly."""
    assert len({kind for _, kind in _live_conditions()}) > 15
