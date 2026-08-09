"""Guard: a supported spell must actually do something when it resolves.

``supported`` is set by the oracle compiler as soon as *any* instruction was
produced — including a ``spell_pattern`` marker, which carries no behavior and
exists only to record that a whitelist substring matched. A card can therefore
report support, pass the parse-coverage guard (its text is "claimed"), be marked
verified in CARD_VERIFICATION.md, and still resolve as a complete no-op.

That is exactly what Shahrazad did: its text contains the word "loses", the
whitelist has a bare ``"loses"`` entry, and casting it logged "Resolved
supported pattern ... without state mutation" while nothing changed. The
acknowledgement in parse_coverage.py even described life-halving behavior that
did not exist.

This checks the property directly — for every supported instant and sorcery,
at least one compiled instruction must have a registered handler. Permanents
are excluded: they legitimately do their work through statics, auras, layers and
the text-keyed step tables rather than through a resolution instruction.
"""

import pytest

from engine.card_loader import load_catalog
from engine.handlers import EFFECT_HANDLERS
from engine.oracle import compile_card_oracle


def _hollow_spells() -> list[tuple[str, list[str]]]:
    hollow: list[tuple[str, list[str]]] = []
    for card in load_catalog():
        type_line = card.type_line.lower()
        if "instant" not in type_line and "sorcery" not in type_line:
            continue
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        if program.modes:
            # A modal spell selects its instruction at resolution from the
            # chosen mode, so the top-level instruction list is not the whole
            # story.
            continue
        if any(instr.kind in EFFECT_HANDLERS for instr in program.instructions):
            continue
        hollow.append((card.name, [f"{i.kind}:{i.value}" for i in program.instructions]))
    return hollow


def test_no_supported_spell_resolves_without_an_effect():
    """A supported instant or sorcery whose every instruction lacks a handler
    resolves to nothing at all. Either give it an effect or classify it
    unsupported with a reason — silent no-op support is the failure mode the
    whole parse-coverage apparatus exists to prevent."""
    hollow = _hollow_spells()

    assert not hollow, (
        "supported spells that resolve with no registered handler (they do "
        f"nothing when cast): {hollow}"
    )


@pytest.mark.parametrize("bare_pattern", ["loses", "deals", "gain"])
def test_broad_whitelist_patterns_never_carry_a_card_alone(bare_pattern):
    """The spell-pattern whitelist holds bare substrings like "loses" that
    match far more text than they describe. None of them may be the only thing
    making a spell supported — that is how a card ends up claiming support for
    text nothing implements."""
    from engine.oracle import SUPPORTED_SPELL_PATTERNS

    assert bare_pattern in SUPPORTED_SPELL_PATTERNS, (
        f"{bare_pattern!r} left the whitelist; drop it from this test too"
    )
    carried = [
        name
        for name, instrs in _hollow_spells()
        if instrs == [f"spell_pattern:{bare_pattern}"]
    ]

    assert not carried, f"spells supported only by the bare {bare_pattern!r} pattern: {carried}"
