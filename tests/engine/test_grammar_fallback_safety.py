"""Guard: enabling the grammar must not silently delete a card's instructions.

`engine/oracle.py`'s noncreature path reads:

    if grammar_instructions:
        instructions.extend(grammar_instructions)
    else:
        parse_primary_instruction(normalized_text)      # the whole card's text

The fallback is all-or-nothing **per card**, not per line. So on a multi-line
card, a grammar production that claims one line suppresses the legacy reading of
*every* line — and the card can quietly lose an effect while still compiling,
still reporting `supported`, and still passing a payload differential (which
only compares lines the grammar claimed).

Nothing in the parser prevents that; it has been avoided so far only by authors
being careful, which is not a mechanism. This compiles the whole pool twice —
once with the grammar disabled — and fails on any *new* card that loses an
instruction kind.
"""

import pytest

import engine.oracle as oracle
from engine.card_loader import load_catalog


# Cards where the grammar deliberately replaces a legacy kind with a better one.
# Each entry is a real improvement, not a loss — verify before extending.
ACCEPTED_REPLACEMENTS: dict[str, str] = {
    # A generic sweep becomes the specific handler that honours the "except
    # creatures with flying" half of the clause.
    "Earthquake": "deal_damage",
    "Hurricane": "deal_damage",
    "Sandstorm": "deal_damage",
    # untap_target_permanent ignores its filter entirely, so the legacy kind can
    # untap a creature; the grammar routes to the land-specific handler.
    "Ley Druid": "untap_target_permanent",
    # Fused conjunction kinds decompose into a `sequence` of ordinary steps —
    # the whole point of the migration.
    "Orcish Artillery": "deal_damage",
    "Psionic Blast": "deal_damage",
    "Cuombajj Witches": "deal_damage",
    # "You may draw a card" was unconditional in the legacy rule.
    "Verduran Enchantress": "draw_controller_cards",
}


def _kinds(program) -> set[str]:
    """Executable instruction kinds — `spell_pattern` is a whitelist marker, not
    behaviour, so it is excluded."""
    return {i.kind for i in program.instructions if i.kind != "spell_pattern"}


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
