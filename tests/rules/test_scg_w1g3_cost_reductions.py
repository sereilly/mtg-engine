"""Cost reductions keyed by what the spell is (CR 601.2f), read off invented
sentences — Scourge's W1G3.

The per-card drives are in ``tests/sets/test_scg_creatures.py`` (W1G3). This
file holds the readings themselves, because each is a template a second card
could print: the creature-type slot (the Warchiefs), the mana-value bound
(Krosan Drover), the shared-type relation (Mistform Warchief), the colored-only
rider (Edgewalker), and Rock Jockey's two prohibitions — and the refusals that
keep each from being read wider than it prints.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from engine import Game, PlayerState
from engine.cast_restrictions import cast_timing_claims_line, self_cast_ban_line
from engine.cost_modifier_lines import CostReduction, cost_modifiers_for
from engine.cost_modifiers import (cost_modifier_claims_line,
                                   cost_reduction_for_cast, reduce_cost,
                                   spell_mana_value)
from engine.land_play_allowance import land_play_line, land_play_prohibition
from engine.models import Permanent


def _read(sentence: str):
    return cost_modifiers_for(sentence.lower().rstrip("."))


@pytest.mark.cr("205.3m", "601.2f")
def test_a_creature_type_in_the_subject_slot_narrows_and_a_non_type_refuses(catalog_by_name):
    """"Goblin spells you cast cost {1} less to cast." reads the creature type
    (CR 205.3m) as a narrowing — the sentence used to be read from "spells",
    which is every spell — and a word in that slot the vocabulary does not hold
    ("legendary", "kicked") refuses the whole sentence: unread, unclaimed,
    charged by nothing."""
    (goblin,) = _read("Goblin spells you cast cost {1} less to cast.")
    assert goblin.creature_type == "goblin" and goblin.reduces and goblin.amount == 1
    for sentence in (
        "Legendary spells you cast cost {1} less to cast.",
        "Kicked spells you cast cost {1} less to cast.",
        "Nonartifact spells you cast cost {1} less to cast.",
    ):
        assert _read(sentence) == (), sentence
        assert not cost_modifier_claims_line(sentence), sentence
    # The card types, colours and "face-down" keep their own slots.
    (instants,) = _read("Instant spells you cast cost {1} less to cast.")
    assert instants.card_types == ("instant",) and instants.creature_type is None
    (blue,) = _read("Blue creature spells cost {1} more to cast.")
    assert blue.colour == "U" and blue.creature_type is None
    assert _read("Face-down Goblin spells you cast cost {1} less to cast.") == ()


@pytest.mark.cr("205.3m", "601.2f")
def test_a_kindred_spell_of_the_type_is_discounted(set_pool, catalog_by_name):
    """CR 205.3m: "Creatures and kindreds share their lists of subtypes" — so
    a Kindred instant that is a Goblin is a Goblin spell, and the same instant
    without the subtype is not."""
    game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
    game.players[0].battlefield.append(Permanent(card=set_pool("SCG")["Goblin Warchief"]))
    game._sync_control()
    bolt = catalog_by_name["Lightning Bolt"]
    kindred = replace(bolt, name="Goblin Bolt", type_line="Kindred Instant — Goblin")
    assert cost_reduction_for_cast(game, 0, kindred)[0].generic == 1
    assert cost_reduction_for_cast(game, 0, bolt)[0].generic == 0


@pytest.mark.cr("601.2f")
def test_a_template_read_from_the_middle_of_a_sentence_charges_nothing():
    """``cost_modifiers_for`` searches a card's whole text, so a match can
    begin inside a longer sentence — and then whatever came first is a
    narrowing dropped: a condition ("If you control a Wizard, …") or a quote
    granting the ability to something else. Each now reads as nothing; a match
    at a sentence's start (after a full stop, a line break or an ability
    word's dash) still reads."""
    assert _read("If you control a Wizard, Wizard spells you cast cost {1} less to cast.") == ()
    assert _read(
        'Creatures you control have "Spells you cast cost {1} less to cast."'
    ) == ()
    assert len(_read("Flying. Spells you cast cost {1} less to cast.")) == 1
    assert len(cost_modifiers_for(
        "flying\nwizard spells you cast cost {1} less to cast"
    )) == 1


@pytest.mark.cr("202.3e", "601.2f")
def test_a_mana_value_bound_is_read_on_the_stack_and_only_downwards():
    """"Creature spells you cast with mana value 6 or greater cost {2} less to
    cast." The bound is the ``{op, value}`` every mana-value narrowing rides,
    and the spell's mana value counts X as announced (CR 202.3e). Admitted on a
    reduction bounded below only — the cast path restates a reduction once X
    is a number, and only a monotone bound makes that restatement final — so
    "or less" and a tax narrowed this way are refused."""
    (drover,) = _read(
        "Creature spells you cast with mana value 6 or greater cost {2} less to cast."
    )
    assert drover.mana_value == {"op": "ge", "value": 6}
    assert drover.card_types == ("creature",)
    for sentence in (
        "Creature spells you cast with mana value 2 or less cost {1} less to cast.",
        "Creature spells you cast with mana value 6 or greater cost {2} more to cast.",
    ):
        assert _read(sentence) == (), sentence

    class _Card:
        cmc, mana_cost = 2.0, "{X}{G}{G}"

    assert spell_mana_value(_Card()) == 2
    assert spell_mana_value(_Card(), 4) == 6


@pytest.mark.cr("205.3m", "601.2f")
def test_a_shared_creature_type_is_a_creature_spells_relation():
    """"Creature spells you cast that share a creature type with this creature
    cost {1} less to cast." Read only after a subject that names a creature
    spell (CR 205.3d: only a creature or a kindred has creature types)."""
    (mistform,) = _read(
        "Creature spells you cast that share a creature type with this creature "
        "cost {1} less to cast."
    )
    assert mistform.shares_creature_type_with_source
    assert _read(
        "Artifact spells you cast that share a creature type with this creature "
        "cost {1} less to cast."
    ) == ()


@pytest.mark.cr("118.7b", "118.7c")
def test_a_colored_only_reduction_never_spills_onto_generic():
    """Edgewalker: "Cleric spells you cast cost {W}{B} less to cast. This
    effect reduces only the amount of colored mana you pay. (For example, if
    you cast a Cleric spell with mana cost {1}{W}, it costs {1} to cast.)"
    CR 118.7b and 118.7c are what the rider switches off: a {1}{W} costs {1}
    (not {0}), a {5} costs {5} (not {3}). The ordinary coloured reduction still
    spills, and applied beside the colored-only one it is applied second —
    never worse for the payer (CR 601.2f leaves the order to them)."""
    walker = CostReduction(colored_only=(("B", 1), ("W", 1)))
    assert reduce_cost({"generic": 1, "W": 1}, walker) == {"generic": 1, "W": 0}
    assert reduce_cost({"generic": 5}, walker) == {"generic": 5}
    assert reduce_cost({"generic": 1, "W": 2, "B": 1}, walker) == {
        "generic": 1, "W": 1, "B": 0,
    }
    spilling = CostReduction(colored=(("W", 1),))
    assert reduce_cost({"generic": 1}, spilling) == {"generic": 0, "W": 0}
    both = CostReduction(colored=(("W", 1),), colored_only=(("W", 1),))
    assert reduce_cost({"generic": 1, "W": 1}, both) == {"generic": 0, "W": 0}
    # Read off the printed line, rider and all; without the rider a coloured
    # reduction from a permanent is refused (no card prints one), and the
    # rider beside a generic amount says two contradictory things.
    line = (
        "Cleric spells you cast cost {W}{B} less to cast. This effect reduces "
        "only the amount of colored mana you pay."
    )
    (edgewalker,) = _read(line)
    assert edgewalker.colored_only and edgewalker.creature_type == "cleric"
    assert dict(edgewalker.symbols) == {"W": 1, "B": 1}
    assert cost_modifier_claims_line(line)
    assert _read("Cleric spells you cast cost {W}{B} less to cast.") == ()
    assert _read(
        "Cleric spells you cast cost {1}{W} less to cast. This effect reduces only "
        "the amount of colored mana you pay."
    ) == ()
    assert walker and CostReduction().plus_generic(0) == CostReduction()
    assert walker.plus_generic(2) == CostReduction(2, (), walker.colored_only)


@pytest.mark.cr("601.2f", "118.7")
def test_a_colored_only_reduction_reaches_the_pips_of_an_additional_cost(
    set_pool, catalog_by_name,
):
    """Edgewalker's ruling (2008-08-01): "You apply cost reduction effects
    after other cost modifiers, so it can reduce additional costs or
    alternative costs if they include {W} and/or {B}." No Cleric in the pool
    prints such a cost, so an invented one does: {1}{W} with Kicker {W}, kicked,
    totals {1}{W}{W} (CR 601.2f) and Edgewalker takes one {W} off — a {W} and a
    {1} pay for it, and the kicked entry trigger gains its life."""
    from tests.helpers import resolve_stack

    acolyte = replace(
        catalog_by_name["Samite Healer"], name="Kicked Acolyte",
        mana_cost="{1}{W}", cmc=2.0,
        oracle_text=(
            "Kicker {W}\nWhen this creature enters, if it was kicked, you gain 2 life."
        ),
    )
    game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
    game.enforce_mana_costs = True
    game.turn, game.active_player_index, game.current_phase = 3, 0, "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    game._put_permanent_onto_battlefield(
        0, Permanent(card=set_pool("SCG")["Edgewalker"]), None,
    )
    game._sync_control()
    game.players[0].hand.append(acolyte)
    game.players[0].mana_pool.update({"W": 1, "C": 1})
    result = game.cast_from_hand(0, "Kicked Acolyte", optional_cost_payments={"{W}": 1})
    assert result.supported, result.details
    resolve_stack(game)
    assert not any(game.players[0].mana_pool.values())
    assert game.players[0].life == 22


@pytest.mark.cr("601.3")
def test_a_card_that_forbids_its_own_cast_names_itself_or_this_spell():
    """"You can't cast Rock Jockey if you've played a land this turn." The
    negative spelling of "Cast this spell only if …", printed with the card's
    own name (CR 201.5): one reader for both spellings, with the condition as
    payload — and a condition nothing answers leaves the line unread."""
    printed = "You can't cast Rock Jockey if you've played a land this turn."
    assert self_cast_ban_line(printed, "Rock Jockey") == "you've played a land this turn"
    assert self_cast_ban_line(printed, "Stone Jockey") is None, "another card's name"
    assert self_cast_ban_line(
        "You can't cast this spell if you have played a land this turn.", None,
    ) == "you have played a land this turn"
    assert self_cast_ban_line(
        "You can't cast this spell if you've cast a spell this turn.", None,
    ) is None
    assert cast_timing_claims_line(printed, "Rock Jockey")
    assert not cast_timing_claims_line(printed)


@pytest.mark.cr("305.1")
def test_a_land_ban_scoped_to_you_and_to_this_creatures_cast():
    """"You can't play lands if this creature was cast this turn." Read as a
    prohibition the land-drop gate asks with the permanent and the seat in
    hand; any other condition on the same words is not this row."""
    line = "You can't play lands if this creature was cast this turn."
    assert land_play_line(line) == "prohibition"
    found = land_play_prohibition(line)
    assert found.controller_only and found.while_cast_this_turn
    assert land_play_line("You can't play lands if this creature attacked this turn.") is None
    assert land_play_prohibition("You can't play lands if this creature attacked this turn.") is None
