"""Tests for Magic: The Gathering Comprehensive Rules 601.2f.

Covers:
  601.2f — The total cost is the mana cost plus all cost increases; increases
           from several sources all apply

These pin the *derivation* of cost taxes from oracle text
(engine/cost_modifiers.py), which replaced two hand-written functions keyed by
card name. The point of the change is that a card the engine has never seen is
taxed correctly as long as it uses a printed template, so most of these use
invented wordings — a test naming Gloom could pass against a lookup keyed by
"Gloom". Gloom itself is covered by the set suite.
"""

import pytest

from engine.cost_modifiers import CostModifier, cost_modifiers_for


def _only(text: str) -> CostModifier:
    modifiers = cost_modifiers_for(text)
    assert len(modifiers) == 1, modifiers
    return modifiers[0]


@pytest.mark.cr("601.2f")
def test_601_2f_colour_scoped_spell_tax_is_read_from_the_text():
    """"White spells cost {3} more to cast." (Gloom's wording.)"""
    modifier = _only("White spells cost {3} more to cast.")

    assert (modifier.applies_to, modifier.colour, modifier.amount) == ("cast", "W", 3)
    assert modifier.card_type is None


@pytest.mark.cr("601.2f")
def test_601_2f_the_colour_and_amount_come_from_the_wording():
    """A card printed in another colour or at another amount needs no
    registration — both are read from the text."""
    modifier = _only("Green spells cost {1} more to cast.")

    assert (modifier.colour, modifier.amount) == ("G", 1)


@pytest.mark.cr("601.2f")
def test_601_2f_an_unscoped_tax_applies_to_every_spell():
    """"Spells cost {1} more to cast." (Sphere of Resistance's template.) No
    colour and no type means no filter."""
    modifier = _only("Spells cost {1} more to cast.")

    assert modifier.colour is None
    assert modifier.card_type is None
    assert modifier.amount == 1


@pytest.mark.cr("601.2f")
def test_601_2f_a_type_scoped_tax_is_recognized():
    """"Creature spells cost {2} more to cast." — the type is a filter in its
    own right, with or without a colour."""
    typed = _only("Creature spells cost {2} more to cast.")
    both = _only("Blue creature spells cost {2} more to cast.")

    assert (typed.card_type, typed.colour) == ("creature", None)
    assert (both.card_type, both.colour) == ("creature", "U")


@pytest.mark.cr("601.2f")
def test_601_2f_activated_ability_taxes_are_separate_from_cast_taxes():
    """"Activated abilities of white enchantments cost {3} more to activate."
    Casting and activating are different events, so the modifier records which
    one it applies to."""
    modifier = _only("Activated abilities of white enchantments cost {3} more to activate.")

    assert modifier.applies_to == "activate"
    assert (modifier.colour, modifier.card_type, modifier.amount) == ("W", "enchantment", 3)


@pytest.mark.cr("601.2f")
def test_601_2f_a_card_may_carry_both_kinds():
    """Gloom's shape: one clause taxes casting, the other activating."""
    modifiers = cost_modifiers_for(
        "White spells cost {3} more to cast.\n"
        "Activated abilities of white enchantments cost {3} more to activate."
    )

    assert {m.applies_to for m in modifiers} == {"cast", "activate"}


@pytest.mark.cr("601.2f")
def test_601_2f_unrelated_text_imposes_no_tax():
    """Cost *reduction* is deliberately not implemented — there is no card in
    the pool to verify it against, and reading "less" as "more" would be worse
    than not reading it. These must all yield nothing rather than a wrong tax."""
    for text in (
        "White spells cost {1} less to cast.",
        "This spell costs {1} more to cast for each target beyond the first.",
        "Creature spells you cast cost {1} less to cast.",
        "{T}: Add {W}.",
        "",
    ):
        assert cost_modifiers_for(text) == (), text
