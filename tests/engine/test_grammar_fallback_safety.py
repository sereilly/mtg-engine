"""Guard: enabling the grammar must not silently delete a card's instructions.

`engine/oracle.py`'s noncreature path used to read:

    if grammar_instructions:          # any one line claimed...
        instructions.extend(grammar_instructions)
    else:
        parse_primary_instruction(normalized_text)      # ...the whole card's text

The fallback was all-or-nothing **per card**, not per line. So on a multi-line
card, a grammar production that claimed one line suppressed the legacy reading of
*every* line — and the card could quietly lose an effect while still compiling,
still reporting `supported`, and still passing a payload differential (which
only compares lines the grammar claimed).

`_noncreature_line_instructions` assembles that list per line now: each line
contributes the reading the compiler already produced for it (the grammar's, or
the legacy rules' for the one clause the grammar refused), and the whole-text
parse runs only when no line contributed anything at all. The hazard is
therefore narrower than it was — but it is not gone, because that last fallback
is still per card, and because a line can still lower to less than it says.

Nothing in the parser prevents either; it has been avoided so far only by
authors being careful, which is not a mechanism. This compiles the whole pool
twice — once with the grammar disabled — and fails on any *new* card that loses
an instruction kind.
"""

import pytest

import engine.oracle as oracle
from engine.card_loader import load_catalog


# Cards where the grammar deliberately replaces a legacy kind with a better one.
# Each entry is a real improvement, not a loss — verify before extending.
#
# Every survivor here is the same shape: a legacy *category whose rules were
# deleted* (`damage`, `tapping`) leaves behind a broad rule that still claims the
# line and drops most of its meaning, and the grammar routes it to the handler
# that implements the whole sentence. `tests/engine/test_grammar_differential.py`
# names that shelf life explicitly in MIGRATED_CATEGORIES and stops comparing;
# here the replacement is recorded per card instead, because this guard's subject
# is the assembly rather than the reading.
ACCEPTED_REPLACEMENTS: dict[str, str] = {
    # A generic sweep becomes the specific handler that honours the whole clause
    # — the "except creatures without flying" half, the "each attacking creature"
    # half, the "each creature *and* each player" half. `deal_damage` alone
    # damages one recipient.
    "Earthquake": "deal_damage",
    "Hurricane": "deal_damage",
    "Sandstorm": "deal_damage",
    "Pestilence": "deal_damage",
    "Cuombajj Witches": "deal_damage",
    # untap_target_permanent ignores its filter entirely, so the legacy kind can
    # untap a creature; the grammar routes to the land-specific handler.
    "Ley Druid": "untap_target_permanent",
    # Retired when `_kinds` began counting nested steps: Orcish Artillery,
    # Psionic Blast and Verduran Enchantress were never losing an instruction.
    # A fused conjunction decomposing into a `sequence`, and an unconditional
    # draw becoming a `may`, *keep* the original kind — one level down. The
    # top-level-only comparison scored the migration's own composition mechanism
    # as deletion, which is why those three read as deliberate divergences for
    # as long as they did.
}


# Payload keys under which engine/handlers/control_flow.py carries nested steps.
# A composed effect keeps its parts here, so a comparison that reads only the
# top level sees composition as deletion.
_NESTED_STEP_KEYS = ("steps", "then", "else", "action", "otherwise", "effect")


def _flatten(instructions):
    for instruction in instructions:
        yield instruction
        for key in _NESTED_STEP_KEYS:
            yield from _flatten(instruction.payload.get(key) or ())


def _kinds(program) -> set[str]:
    """Executable instruction kinds — `spell_pattern` is a whitelist marker, not
    behaviour, so it is excluded.

    Nested steps count. The grammar's whole point is that effects *compose*
    (ROADMAP "Effects could not compose"), so "you may pay {1}. If you do, you
    gain 1 life" lowers to `may` wrapping the `target_gains_life` the legacy rule
    emitted bare and unconditional. Reading only the top level would score that
    wrapping as a deleted life gain — the guard reporting the migration's
    central mechanism as the bug class it exists to catch.
    """
    return {i.kind for i in _flatten(program.instructions) if i.kind != "spell_pattern"}


@pytest.fixture(scope="module")
def with_and_without_grammar():
    cards = load_catalog()
    live = {c.name: _kinds(oracle.compile_card_oracle(c)) for c in cards}
    original = oracle._grammar_instruction
    oracle._grammar_instruction = lambda *args, **kwargs: None
    oracle._compile_card_oracle.cache_clear()
    try:
        legacy = {c.name: _kinds(oracle.compile_card_oracle(c)) for c in cards}
    finally:
        oracle._grammar_instruction = original
        oracle._compile_card_oracle.cache_clear()
    return live, legacy


def test_no_card_silently_loses_an_instruction_to_the_grammar(with_and_without_grammar):
    """A card that compiles to fewer effects with the grammar on has lost one.
    It still reports supported, so only this catches it."""
    live, legacy = with_and_without_grammar
    unexpected = []
    for name, legacy_kinds in legacy.items():
        missing = legacy_kinds - live[name]
        if not missing:
            continue
        accepted = ACCEPTED_REPLACEMENTS.get(name)
        if accepted is not None and missing == {accepted}:
            continue
        unexpected.append((name, sorted(missing), sorted(live[name])))

    assert not unexpected, (
        "enabling the grammar dropped instructions these cards had. If the "
        "replacement is a deliberate improvement, add it to "
        f"ACCEPTED_REPLACEMENTS with the reason: {unexpected}"
    )


def test_accepted_replacements_are_all_still_happening(with_and_without_grammar):
    """A stale entry hides a card that has quietly stopped being improved."""
    live, legacy = with_and_without_grammar
    stale = [
        name for name, kind in ACCEPTED_REPLACEMENTS.items()
        if kind not in legacy.get(name, set()) - live.get(name, set())
    ]

    assert not stale, f"ACCEPTED_REPLACEMENTS entries that no longer occur: {stale}"
