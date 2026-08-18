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

from engine.cost_modifiers import (
    CostModifier, CostReduction, cost_modifiers_for, reduce_cost, self_cost_reduction,
)


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
    """A wording outside the templates yields nothing rather than a wrong tax.

    This used to include "costs {1} less", pinning the absence of reductions
    while that was the honest state. They are implemented now (below), so what
    is left here is the text these templates genuinely do not read: Fireball's
    per-target surcharge, which mixins/stack applies, and a mana ability."""
    for text in (
        "This spell costs {1} more to cast for each target beyond the first.",
        "{T}: Add {W}.",
        "",
    ):
        assert cost_modifiers_for(text) == (), text


# ---------------------------------------------------------------------------
# 601.2f / 118.7 — reductions
# ---------------------------------------------------------------------------


@pytest.mark.cr("601.2f")
def test_601_2f_a_reduction_is_read_from_the_same_template():
    """"Creature spells with flying you cast cost {1} less to cast." (Watcher of
    the Spheres.) One template reads both directions, so the only difference
    between a tax and a discount is the word the card prints."""
    modifier = _only("Creature spells with flying you cast cost {1} less to cast.")

    assert modifier.reduces
    assert (modifier.card_type, modifier.keyword, modifier.controller) == (
        "creature", "flying", "you",
    )
    assert modifier.amount == 1


@pytest.mark.cr("601.2f")
def test_601_2f_a_non_type_is_the_printed_negation_of_the_same_word():
    """"Noncreature spells cost {1} more to cast." (Vryn Wingmare) — the type
    line is asked the same question and the answer inverted, rather than "non"
    becoming a card type of its own."""
    modifier = _only("Noncreature spells cost {1} more to cast.")

    assert (modifier.card_type, modifier.reduces) == ("noncreature", False)


@pytest.mark.cr("118.7a")
def test_118_7a_a_generic_reduction_touches_only_the_generic_component():
    """"Effects that reduce a cost by an amount of generic mana affect only the
    generic mana component of that cost.\""""
    cost = {"W": 0, "U": 2, "B": 0, "R": 0, "G": 0, "C": 0, "generic": 3}

    reduced = reduce_cost(cost, CostReduction(generic=2))

    assert reduced["generic"] == 1
    assert reduced["U"] == 2, "the coloured pips are untouched"


@pytest.mark.cr("118.7b")
def test_118_7b_a_coloured_reduction_falls_back_to_generic():
    """"If a cost is reduced by an amount of colored mana, but the cost doesn't
    require mana of that type, the cost is reduced by that amount of generic
    mana.\""""
    cost = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "generic": 3}

    reduced = reduce_cost(cost, CostReduction(colored=(("U", 1),)))

    assert reduced["generic"] == 2


@pytest.mark.cr("118.7c")
def test_118_7c_an_excess_coloured_reduction_spills_onto_generic():
    """"…the cost's mana component of that color is reduced to nothing and the
    cost's generic mana component is reduced by the difference.\""""
    cost = {"W": 0, "U": 1, "B": 0, "R": 0, "G": 0, "C": 0, "generic": 3}

    reduced = reduce_cost(cost, CostReduction(colored=(("U", 3),)))

    assert (reduced["U"], reduced["generic"]) == (0, 1)


@pytest.mark.cr("601.2f")
def test_601_2f_a_cost_is_never_reduced_below_nothing():
    """"It can't be reduced to less than {0}.\""""
    cost = {"W": 0, "U": 1, "B": 0, "R": 0, "G": 0, "C": 0, "generic": 1}

    reduced = reduce_cost(cost, CostReduction(generic=9, colored=(("U", 9),)))

    assert all(amount == 0 for amount in reduced.values())


@pytest.mark.cr("601.2f")
def test_601_2f_a_self_reduction_refuses_a_condition_it_cannot_answer():
    """A wording outside the condition table refuses the whole line. Reading an
    unrecognized condition as satisfied would make the spell cheaper than it is
    — the one direction a cost error must never go."""
    assert self_cost_reduction(
        "This spell costs {2} less to cast if you've juggled three chainsaws."
    ) is None
    # A {X} reduction *with* a "where X is …" clause the table knows is read
    # since round 120 — the amount is a question, asked of the caster at
    # CR 601.2f. A clause it does not know still refuses, for the reason above:
    # an amount this cannot compute is not an amount of zero.
    assert self_cost_reduction(
        "This spell costs {X} less to cast, where X is the total power of creatures you control."
    ) is not None
    assert self_cost_reduction(
        "This spell costs {X} less to cast, where X is the number of chainsaws you have juggled."
    ) is None
    # And a bare {X} with no clause at all names no amount, so it refuses as it
    # always did.
    assert self_cost_reduction("This spell costs {X} less to cast.") is None
