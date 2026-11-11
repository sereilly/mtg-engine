"""No caller in ``engine/`` or ``web/`` announces a target by the old slot
keyword (kg5 / ``ids``).

``target_permanent_index`` was the keyword every cast, activation and AI action
took: one slot whose zone the card's spec decided. Each zone has its own now
(``engine/target_keywords``): a permanent by id, a graveyard card by its place
in the pile, an ante card by its place there. The old keyword is still
accepted by the entry points, as the tests' adapter — and only the tests may
send it. This scan holds that: a call to an entry point anywhere in the engine
or the web layer naming ``target_permanent_index=`` is a slot announced where
an id (or a zone's own keyword) belongs, and the AI's actions carry no such
field for an executor to forward.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

from engine.ai_actions import (ActivationAction, CastAction,
                               activation_announcement, cast_announcement)
from tests.source_index import source_text

_ROOT = Path(__file__).resolve().parents[2]

#: Every API entry point a target is announced through.
ENTRY_POINTS = frozenset({
    "cast_from_hand", "queue_from_hand", "_cast_onto_stack",
    "activate_permanent_ability", "queue_permanent_ability", "_activate_onto_stack",
    "activate_from_graveyard", "_activate_from_graveyard",
})
OLD = "target_permanent_index"


def _calls():
    """Every call to an entry point in engine/, web/ and scripts/ — except an
    entry point forwarding its own parameters to the next (``cast_from_hand``
    to ``queue_from_hand``: the adapter passing the tests' keyword through)."""
    for top in ("engine", "web", "scripts"):
        for path in sorted((_ROOT / top).rglob("*.py")):
            tree = ast.parse(source_text(path))
            forwarding = {
                id(node)
                for function in ast.walk(tree)
                if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
                and function.name in ENTRY_POINTS
                for node in ast.walk(function)
            }
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or id(node) in forwarding:
                    continue
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
                if name in ENTRY_POINTS:
                    yield path.relative_to(_ROOT).as_posix(), node


def test_no_engine_or_web_caller_announces_a_target_by_slot():
    examined = 0
    offenders = []
    for where, call in _calls():
        examined += 1
        if any(keyword.arg == OLD for keyword in call.keywords):
            offenders.append(f"{where}:{call.lineno}")
    # A scan that found no entry point measured nothing.
    assert examined >= 25, examined
    assert not offenders, (
        "a target announced by slot — name a permanent by target_permanent_ids, "
        "a graveyard card by target_graveyard_indices: " + ", ".join(offenders)
    )


def test_the_ai_actions_carry_no_slot_to_forward():
    for action_type in (CastAction, ActivationAction):
        assert OLD not in {field.name for field in dataclasses.fields(action_type)}
    cast = CastAction(
        card_name="Probe", target_player_index=1, x_value=None,
        land_tap_indices=(), score=0.0, hand_index=0,
    )
    activation = ActivationAction(
        permanent_name="Probe", permanent_index=0, target_player_index=1,
        land_tap_indices=(), score=0.0,
    )
    for announcement in (cast_announcement(cast), activation_announcement(activation)):
        assert OLD not in announcement
        assert {"target_permanent_ids", "target_graveyard_indices"} <= set(announcement)
