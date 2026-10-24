"""An immediate "exile it" naming a permanent an earlier step recorded refuses.

``exile_bound_permanent`` is a **delayed** ability's kind — "Return the top
creature card of your graveyard to the battlefield. … **Exile it at the
beginning of the next end step.**" (Shallow Grave, Zirilan of the Claw) — and
its handler reads the id the creating effect froze into the delayed trigger's
context (CR 603.7c). Judgment's W1G4 found that the lowering reached the same
kind for the *immediate* sentence, where nothing freezes an id: "Return target
creature card from your graveyard to the battlefield. Exile it." compiled,
reported supported, and exiled nothing. No card prints that today, so it is
refused by name rather than read (the reading would be the recorded-permanent
exile Cannibalize uses), and the delayed sentences are pinned unchanged.
"""

from __future__ import annotations

import pytest

from engine.grammar import compile_line
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card

_REFUSED = "an immediate \"exile it\" naming a permanent an earlier step recorded"


def _program(type_line: str, text: str):
    return compile_card_oracle(_mk_card("Probe Card", "{1}{B}", type_line, text, colors=("B",)))


def _kinds(value) -> list[str]:
    found = []
    stack = [value]
    while stack:
        node = stack.pop()
        kind = getattr(node, "kind", None)
        if kind is not None and hasattr(node, "payload"):
            found.append(kind)
            stack.extend((node.payload or {}).values())
        elif isinstance(node, (list, tuple)):
            stack.extend(node)
        elif isinstance(node, dict):
            stack.extend(node.values())
    return found


@pytest.mark.parametrize("type_line, text", [
    ("Sorcery", "Return target creature card from your graveyard to the battlefield. Exile it."),
    ("Sorcery", "Return the top creature card of your graveyard to the battlefield. Exile it."),
    ("Sorcery", "Put target creature card from a graveyard onto the battlefield under your control. Exile it."),
    ("Creature — Spirit", "When this creature enters, return target creature card from your graveyard to the battlefield. Exile it."),
])
def test_an_immediate_exile_of_a_recorded_permanent_is_refused_by_name(type_line, text):
    program = _program(type_line, text)
    assert "exile_bound_permanent" not in _kinds(
        [program.instructions] + [t.instruction for t in program.triggered_abilities]
    )
    if "Creature" in type_line:
        assert not any(t.supported for t in program.triggered_abilities)
    else:
        assert not program.supported
    # The grammar read every word and the lowering refused the reference by
    # name — not a parse failure and not a generic one.
    compiled = compile_line(text)
    assert compiled.parsed and not compiled.lowered
    assert _REFUSED in compiled.lowering_error, compiled.lowering_error


@pytest.mark.parametrize("text", [
    "Return target creature card from your graveyard to the battlefield. Exile it at the beginning of the next end step.",
    "Return the top creature card of your graveyard to the battlefield. That creature gains haste until end of turn. Exile it at the beginning of the next end step.",
])
def test_the_delayed_exile_still_reads_the_permanent_it_froze(text):
    """Shallow Grave's shape: the exile is the delayed ability's, and the
    creating effect binds the recorded permanent to it."""
    program = _program("Sorcery", text)
    assert program.supported, program.reason
    (sequence,) = program.instructions
    delayed = [
        step for step in sequence.payload["steps"]
        if step.kind == "create_delayed_trigger"
    ]
    assert len(delayed) == 1
    assert delayed[0].payload["instruction"].kind == "exile_bound_permanent"
    assert delayed[0].payload["binds_recorded"] == "reanimated_permanents"
