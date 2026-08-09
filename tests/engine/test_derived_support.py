"""Guard: support is derived from the tables that do the work.

Several noncreature behaviours are implemented by text-keyed rule tables that
read a permanent's oracle text directly at the step that needs them —
``untap_restrictions``, ``draw_step_modifiers``, ``cost_modifiers``,
``enter_effects``. They need no instruction to *work*.

They were nonetheless absent from the support gate, which listed the same
behaviours as whitelist literals with the table's parameters baked in:
"creatures with power **3** or greater don't untap", "players can't untap more
than **one** creature". So a card printed "power 4 or greater" was enforced
correctly by the table and reported **unsupported** — the false-negative half
of the gate/dispatch split that produced the combat-restriction and
characteristic-defining bugs in their supported-but-wrong form.

The gate now asks the tables. These tests use parameter values no card in the
pool prints, because a test built from Meekstone and Smoke passes against the
version that hardcoded exactly their numbers.
"""

import dataclasses

import pytest

from engine.card_loader import load_catalog
from engine.oracle import compile_card_oracle
from engine.untap_restrictions import untap_restriction_for


@pytest.fixture(scope="module")
def artifact_card():
    return {c.name: c for c in load_catalog()}["Meekstone"]


def _probe(artifact_card, text):
    return compile_card_oracle(
        dataclasses.replace(artifact_card, name="Probe Artifact", oracle_text=text)
    )


@pytest.mark.parametrize(
    "text",
    [
        # The threshold is data to the table; it was a literal to the gate.
        "Creatures with power 1 or greater don't untap during their controllers' untap steps.",
        "Creatures with power 4 or greater don't untap during their controllers' untap steps.",
        "Creatures with power 9 or greater don't untap during their controllers' untap steps.",
        # So is the count, and the permanent type it counts.
        "Players can't untap more than two creatures during their untap steps.",
        "Players can't untap more than one land during their untap steps.",
        "Players can't untap more than three lands during their untap steps.",
    ],
)
def test_a_parameterized_untap_restriction_is_supported(artifact_card, text):
    """Implemented-but-unsupported is still a bug: the card would be excluded
    from decks and coverage reports while the engine enforced it correctly."""
    assert untap_restriction_for(text) is not None, "table should claim it"
    assert _probe(artifact_card, text).supported, text


@pytest.mark.parametrize(
    "text",
    [
        "Blue spells cost {2} more to cast.",
        "Green spells cost {1} more to cast.",
        "Black spells cost {4} more to cast.",
    ],
)
def test_a_parameterized_cost_tax_is_supported(artifact_card, text):
    """Gloom's literal named white and {3}; the table has always taken both as
    parameters."""
    assert _probe(artifact_card, text).supported, text


def test_the_derived_marker_names_the_table_that_claims_it(artifact_card):
    """The marker records *which* table carries the behaviour, so a card whose
    support comes from a table can be traced to it without re-reading text."""
    program = _probe(
        artifact_card,
        "Creatures with power 4 or greater don't untap during their controllers' untap steps.",
    )
    derived = [i for i in program.instructions if i.kind == "derived_static_rule"]
    assert [i.value for i in derived] == ["untap_restrictions"]


def test_real_cards_keep_their_support(artifact_card):
    catalog = {c.name: c for c in load_catalog()}
    expected = {
        "Meekstone": "untap_restrictions",
        "Smoke": "untap_restrictions",
        "Winter Orb": "untap_restrictions",
        "Howling Mine": "draw_step_modifiers",
        "Gloom": "cost_modifiers",
        "Library of Leng": "enter_effects.no_maximum_hand_size",
        "Sunglasses of Urza": "enter_effects.spend_white_as_red",
    }
    for name, table in expected.items():
        program = compile_card_oracle(catalog[name])
        assert program.supported, name
        values = [i.value for i in program.instructions if i.kind == "derived_static_rule"]
        assert table in values, f"{name}: {values}"


def test_text_no_table_claims_is_still_unsupported(artifact_card):
    """The gate must not have become permissive. A restriction none of the
    tables understands stays unsupported."""
    assert not _probe(
        artifact_card,
        "Creatures with toughness 4 or greater don't untap during their controllers' untap steps.",
    ).supported
