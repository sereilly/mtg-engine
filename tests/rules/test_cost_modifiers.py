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
    assert modifier.card_types == ()


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
    assert modifier.card_types == ()
    assert modifier.amount == 1


@pytest.mark.cr("601.2f")
def test_601_2f_a_type_scoped_tax_is_recognized():
    """"Creature spells cost {2} more to cast." — the type is a filter in its
    own right, with or without a colour."""
    typed = _only("Creature spells cost {2} more to cast.")
    both = _only("Blue creature spells cost {2} more to cast.")

    assert (typed.card_types, typed.colour) == (("creature",), None)
    assert (both.card_types, both.colour) == (("creature",), "U")


@pytest.mark.cr("601.2f")
def test_601_2f_activated_ability_taxes_are_separate_from_cast_taxes():
    """"Activated abilities of white enchantments cost {3} more to activate."
    Casting and activating are different events, so the modifier records which
    one it applies to."""
    modifier = _only("Activated abilities of white enchantments cost {3} more to activate.")

    assert modifier.applies_to == "activate"
    assert (modifier.colour, modifier.card_types, modifier.amount) == (
        "W", ("enchantment",), 3,
    )


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
    assert (modifier.card_types, modifier.keyword, modifier.controller) == (
        ("creature",), "flying", "you",
    )
    assert modifier.amount == 1


@pytest.mark.cr("601.2f")
def test_601_2f_a_non_type_is_the_printed_negation_of_the_same_word():
    """"Noncreature spells cost {1} more to cast." (Vryn Wingmare) — the type
    line is asked the same question and the answer inverted, rather than "non"
    becoming a card type of its own."""
    modifier = _only("Noncreature spells cost {1} more to cast.")

    assert (modifier.card_types, modifier.reduces) == (("noncreature",), False)


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


@pytest.mark.cr("601.2f")
def test_601_2f_a_printed_type_list_is_read_as_an_alternation():
    """"Instant and enchantment spells you cast cost {2} less to cast." (Mana
    Matrix.) The number of types is a fact about one card, so it is payload —
    a template that read one type would silently drop the other, taxing or
    discounting half of what the card says."""
    modifier = _only("Instant and enchantment spells you cast cost {2} less to cast.")

    assert modifier.card_types == ("instant", "enchantment")
    assert (modifier.reduces, modifier.amount, modifier.controller) == (True, 2, "you")


@pytest.mark.cr("601.2f")
def test_601_2f_a_type_list_is_not_limited_to_two():
    """Nothing in the template counts to two: a comma-separated list of three
    reads as three, because the count is not in the pattern."""
    modifier = _only(
        "Artifact, creature, and land spells cost {1} more to cast."
    )

    assert modifier.card_types == ("artifact", "creature", "land")


@pytest.mark.cr("118.7a", "601.2f")
def test_118_7a_a_generic_reduction_clamps_at_zero_without_touching_pips():
    """Mana Matrix offers {2} against a cost holding {1} of generic: the
    generic goes to nothing and the coloured pip is untouched, rather than the
    surplus spilling onto it."""
    assert reduce_cost({"generic": 1, "W": 1}, CostReduction(2)) == {
        "generic": 0, "W": 1,
    }


# --- W2G5: one sentence, several printed subjects ---


@pytest.mark.cr("601.2f")
def test_601_2f_a_tax_sentence_may_name_several_subjects():
    """"Green enchantment spells **and** white enchantment spells cost {2} more
    to cast." (Irini Sengir's wording.)

    Idiom 38: a restriction printed as one sentence is a conjunction, and each
    conjunct has to be read. Read as one subject the pattern matched from the
    *second* one onwards, which is a tax on half the card.
    """
    modifier = _only(
        "Green enchantment spells and white enchantment spells cost {2} more to cast."
    )

    assert (modifier.colour, modifier.card_types) == ("G", ("enchantment",))
    assert modifier.alternative_subjects == (("W", ("enchantment",)),)
    assert modifier.amount == 2


@pytest.mark.cr("601.2f")
def test_601_2f_several_subjects_are_still_one_cost_increase():
    """CR 601.2f applies each increase once. Two printed noun phrases describe
    one set of spells, so a spell answering to both is taxed once — which is
    what keeps the conjuncts from being emitted as two modifiers."""
    class _Card:
        colors = ("G", "W")
        type_line = "Enchantment"
        keywords = ()

    modifiers = cost_modifiers_for(
        "green enchantment spells and white enchantment spells cost {2} more to cast"
    )

    assert len(modifiers) == 1
    assert sum(m.amount for m in modifiers) == 2
    from engine.cost_modifiers import _matches

    assert _matches(modifiers[0], _Card())


@pytest.mark.cr("601.2f")
def test_601_2f_the_subjects_may_differ_on_both_axes():
    """Nothing in the template pairs the conjuncts on one characteristic: a
    sentence naming a colour in one and a card type in the other is the same
    shape, which is why the alternatives are whole noun phrases rather than a
    list of colours."""
    modifier = _only("Red spells and artifact spells cost {1} more to cast.")

    assert (modifier.colour, modifier.card_types) == ("R", ())
    assert modifier.alternative_subjects == ((None, ("artifact",)),)


@pytest.mark.cr("601.2f")
def test_601_2f_a_printed_type_list_is_still_one_subject():
    """"Instant and enchantment spells" (Mana Matrix) uses the same word inside
    a *type list*. Splitting on every "and" would leave "instant" reading as
    nothing and take the whole clause with it, so the split is guarded on the
    word a subject ends with."""
    modifier = _only("Instant and enchantment spells cost {1} less to cast.")

    assert modifier.card_types == ("instant", "enchantment")
    assert modifier.alternative_subjects == ()


@pytest.mark.cr("601.2f")
def test_601_2f_a_conjunct_that_cannot_be_read_refuses_the_whole_clause():
    """A conjunct nothing reads makes the whole sentence unreadable — which is
    what stops a card being admitted with half its subject enforced. The claim
    and the charge are one reader, so an unreadable clause is neither."""
    from engine.cost_modifiers import cost_modifier_claims_line

    text = "Green enchantment spells and every second spell cost {2} more to cast."

    assert cost_modifiers_for(text.lower().rstrip(".")) == ()
    assert not cost_modifier_claims_line(text)


# --- W4G1: a spell's own per-target increase, and when a life cost is paid ---

from engine import Game as _w4g1c_Game, PlayerState as _w4g1c_PlayerState  # noqa: E402
from engine.card_loader import load_catalog as _w4g1c_load  # noqa: E402
from engine.cost_modifiers import (  # noqa: E402
    cost_modifier_claims_line as _w4g1c_claims,
    self_per_target_tax as _w4g1c_tax,
)
from engine.models import Permanent as _w4g1c_Permanent  # noqa: E402

_W4G1C_CATALOG = {card.name: card for card in _w4g1c_load()}


@pytest.mark.cr("601.2f")
def test_601_2f_a_spells_own_increase_is_sized_by_its_chosen_targets():
    """"This spell costs {2} more to cast for each target." — an invented
    wording, for this file's stated reason: a test naming Phyrexian Purge would
    pass against a lookup keyed by "Phyrexian Purge", and the point of a
    template is that a card the engine has never seen is charged correctly.

    CR 601.2c chooses the targets before CR 601.2f calculates the cost, which is
    what makes "for each target" answerable at all.
    """
    tax = _w4g1c_tax("This spell costs {2} more to cast for each target.")

    assert tax is not None
    assert (tax.amount, tax.life, tax.beyond_first) == (2, False, False)
    assert [tax.owed(n) for n in range(4)] == [0, 2, 4, 6]


@pytest.mark.cr("601.2f", "118.3b")
def test_601_2f_the_resource_and_the_exemption_are_both_payload():
    """The pool prints the template twice and differs on both axes: Fireball
    pays mana and exempts the first target, Phyrexian Purge pays life and
    exempts none. Reading either as the other is a cost error — and the life one
    matters most, because generic mana may be paid with anything (CR 118.3b) and
    life may not."""
    mana = _w4g1c_tax("This spell costs {1} more to cast for each target beyond the first.")
    life = _w4g1c_tax("This spell costs 3 life more to cast for each target.")

    assert (mana.life, mana.beyond_first) == (False, True)
    assert [mana.owed(n) for n in range(4)] == [0, 0, 1, 2]
    assert (life.life, life.beyond_first) == (True, False)
    assert [life.owed(n) for n in range(4)] == [0, 3, 6, 9]


@pytest.mark.cr("601.2f")
def test_601_2f_the_per_target_increase_is_claimed_by_the_table_that_charges_it():
    """One reader for the claim and the charge, which is what stops a card
    reporting supported with its cost sentence dropped. A sentence about
    *other* spells is not this template and stays unclaimed here."""
    assert _w4g1c_claims("This spell costs 3 life more to cast for each target.")
    assert _w4g1c_claims(
        "This spell costs {1} more to cast for each target beyond the first."
    )
    assert not _w4g1c_claims("Spells cost 3 life more to cast for each target.")


@pytest.mark.cr("601.2e", "601.2h")
def test_601_2e_a_life_tax_is_not_paid_by_a_cast_that_is_then_refused():
    """CR 601.2 makes an illegal proposal a **rewind**, not a purchase.

    "Spells your opponents cast that target this creature cost an additional 3
    life to cast." (Terror of the Peaks.) The life used to come off the moment
    the tax was measured — above the support gate, the timing gate, the target
    gates, the printed additional costs and the mana — so every refusal below
    that point left the caster three life poorer for a spell that was never
    cast. Nothing crashed and nothing was missing; the player simply paid for
    nothing, which is why it wanted a test rather than a look.
    """
    terror = _w4g1c_Permanent(card=_W4G1C_CATALOG["Terror of the Peaks"])
    game = _w4g1c_Game(players=[
        _w4g1c_PlayerState(name="P1", hand=[_W4G1C_CATALOG["Lightning Bolt"]]),
        _w4g1c_PlayerState(name="P2", battlefield=[terror]),
    ])
    game._sync_control()
    game.start_turn(0)
    game.enforce_mana_costs = True  # and P1 controls no land at all

    result = game.cast_from_hand(
        0, "Lightning Bolt",
        target_player_index=1, target_permanent_index=0,
        target_permanent_ids=[terror.permanent_id],
    )

    assert result.supported is False, result.details
    assert "insufficient mana" in result.details, result.details
    assert game.players[0].life == 20, game.log
    assert any(card.name == "Lightning Bolt" for card in game.players[0].hand)


@pytest.mark.cr("601.2f", "119.4")
def test_601_2f_a_life_tax_is_still_paid_by_a_cast_that_goes_through():
    """The other half of the move, because a payment deferred to a site nothing
    reaches is a tax deleted."""
    terror = _w4g1c_Permanent(card=_W4G1C_CATALOG["Terror of the Peaks"])
    game = _w4g1c_Game(players=[
        _w4g1c_PlayerState(name="P1", hand=[_W4G1C_CATALOG["Lightning Bolt"]]),
        _w4g1c_PlayerState(name="P2", battlefield=[terror]),
    ])
    game._sync_control()
    game.start_turn(0)
    game.enforce_mana_costs = False

    result = game.cast_from_hand(
        0, "Lightning Bolt",
        target_player_index=1, target_permanent_index=0,
        target_permanent_ids=[terror.permanent_id],
    )

    assert result.supported is True, result.details
    assert game.players[0].life == 17, game.log
