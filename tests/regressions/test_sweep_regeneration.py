"""A "destroy all <type>" sweep honours a regeneration shield unless the card
says otherwise — for lands and enchantments as for creatures and artifacts.

Found by driving Apocalypse's Desolation Angel ("destroy all lands you control.
If it was kicked, destroy all lands instead."): its two arms lowered to two
handlers, and the by-type land sweep behind the kicked one skipped regeneration
shields while the filtered sweep behind the unkicked one honoured them. The
by-type table read "regeneration allowed: False" for lands and enchantments —
inherited from two Alpha-era handlers written when "regenerate" was a thing
creatures did — so four shipped cards that say nothing about regeneration
destroyed a permanent through its shield.

CR 701.19a makes regeneration a replacement of *a permanent's* destruction, and
a land or an enchantment is often a creature too: a Spawning Pool animated in
response to Armageddon, an enchantment under Opalescence wearing a
Regeneration. "It can't be regenerated" is the card's to say (Catastrophe).
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.oracle_types import OracleInstruction
from tests.helpers import resolve_stack


def _duel(catalog_by_name, hand):
    forest = catalog_by_name["Forest"]
    game = Game(players=[
        PlayerState(
            "Caster", library=[forest] * 10,
            hand=[catalog_by_name[name] for name in hand],
        ),
        PlayerState("Bystander", library=[forest] * 10),
    ])
    game.enforce_mana_costs = False
    return game


def _put(game, seat, card):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    permanent.tapped = False
    return permanent


def _names(game, seat):
    return sorted(perm.card.name for perm in game.controlled_by(seat))


def test_armageddon_does_not_destroy_a_land_with_a_regeneration_shield(catalog_by_name):
    """Spawning Pool, animated and regenerated in response: "Destroy all
    lands." destroys every other land and the Pool is still there, tapped."""
    game = _duel(catalog_by_name, ["Armageddon"])
    pool = _put(game, 0, catalog_by_name["Spawning Pool"])
    _put(game, 0, catalog_by_name["Forest"])
    _put(game, 1, catalog_by_name["Forest"])
    animated = game.activate_permanent_ability(0, "Spawning Pool", ability_index=1)
    assert animated.supported and pool.is_creature, animated.details
    shielded = game.activate_permanent_ability(0, "Spawning Pool", ability_index=2)
    assert shielded.supported, shielded.details

    cast = game.cast_from_hand(0, "Armageddon")
    assert cast.supported, cast.details
    resolve_stack(game)

    assert _names(game, 0) == ["Spawning Pool"]
    assert _names(game, 1) == []
    assert pool.tapped
    assert "Spawning Pool regenerated" in game.log


def test_tranquility_does_not_destroy_an_enchantment_with_a_regeneration_shield(
    catalog_by_name,
):
    """Under Opalescence a Crusade is a creature and can wear a Regeneration.
    "Destroy all enchantments." takes Opalescence, the Aura and the opponent's
    Crusade, and the shielded one regenerates."""
    game = _duel(catalog_by_name, ["Tranquility", "Regeneration"])
    _put(game, 0, catalog_by_name["Opalescence"])
    crusade = _put(game, 0, catalog_by_name["Crusade"])
    _put(game, 1, catalog_by_name["Crusade"])
    assert crusade.is_creature
    enchanted = game.cast_from_hand(
        0, "Regeneration", target_player_index=0,
        target_permanent_ids=[crusade.permanent_id],
    )
    assert enchanted.supported, enchanted.details
    resolve_stack(game)
    shielded = game.activate_permanent_ability(0, "Regeneration", ability_index=0)
    assert shielded.supported, shielded.details

    cast = game.cast_from_hand(0, "Tranquility")
    assert cast.supported, cast.details
    resolve_stack(game)

    assert _names(game, 0) == ["Crusade"]
    assert _names(game, 1) == []
    assert "Crusade regenerated" in game.log


def test_a_sweep_that_says_so_still_bypasses_the_shield(catalog_by_name):
    """Wrath of God prints "They can't be regenerated.", and that is what
    skips a shield — the card's sentence, not the sweep's type."""
    game = _duel(catalog_by_name, ["Wrath of God"])
    pool = _put(game, 0, catalog_by_name["Spawning Pool"])
    assert game.activate_permanent_ability(0, "Spawning Pool", ability_index=1).supported
    assert game.activate_permanent_ability(0, "Spawning Pool", ability_index=2).supported
    assert pool.is_creature

    cast = game.cast_from_hand(0, "Wrath of God")
    assert cast.supported, cast.details
    resolve_stack(game)

    assert _names(game, 0) == []


def _lead(steps):
    (step,) = steps
    return step


@pytest.mark.parametrize("text,kinds", [
    # one arm narrowed, one bare: both become the filtered sweep
    (
        "When this creature enters, destroy all lands you control. If it was "
        "kicked, destroy all lands instead.",
        ("destroy_all_matching", "destroy_all_matching"),
    ),
    (
        "When this creature enters, destroy all creatures you control. If it "
        "was kicked, destroy all creatures instead.",
        ("destroy_all_matching", "destroy_all_matching"),
    ),
])
def test_two_sweep_arms_of_one_conditional_go_through_one_kind(text, kinds):
    """``_destroy_sweeps.one_sweep_kind``: inside an if/instead pair a by-type
    sweep is respelt as the filtered sweep its sibling arm already is, with the
    same types and nothing else added — so the two arms of one printed verb
    cannot disagree about anything the card did not print."""
    from tests.helpers import _mk_card

    card = _mk_card(
        name="Invented Desolator", type_line="Creature — Giant",
        oracle_text="Kicker {W}{W}\n" + text, power="3", toughness="3",
    )
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    (trigger,) = program.triggered_abilities
    then = _lead(trigger.instruction.payload["then"])
    otherwise = _lead(trigger.instruction.payload["else"])
    assert (then.kind, otherwise.kind) == kinds
    assert "controller" not in then.payload
    assert otherwise.payload["controller"] == "you"
    assert then.payload["type_filter"] == otherwise.payload["type_filter"]


def test_a_lone_by_type_sweep_keeps_its_kind():
    """Outside a pair nothing moves: Armageddon's "Destroy all lands." is still
    ``destroy_all_lands``, the kind the behaviour snapshots key on."""
    from engine.grammar.lowering._destroy_sweeps import one_sweep_kind

    lands = (OracleInstruction("destroy_all_lands", "", {}),)
    creatures = (OracleInstruction("destroy_all_creatures", "", {}),)
    gain = (OracleInstruction("gain_life", "", {"amount": 3}),)
    narrowed = (
        OracleInstruction(
            "destroy_all_matching", "", {"type_filter": "land", "controller": "you"}
        ),
    )

    # two by-type arms, an arm that is no sweep, an arm of two steps: untouched
    assert one_sweep_kind(lands, creatures) == (lands, creatures)
    assert one_sweep_kind(lands, gain) == (lands, gain)
    assert one_sweep_kind(narrowed, gain) == (narrowed, gain)
    assert one_sweep_kind(lands + lands, narrowed) == (lands + lands, narrowed)
    # the pair this exists for, either way round, keeping a printed rider
    assert one_sweep_kind(lands, narrowed) == (
        (OracleInstruction("destroy_all_matching", "", {"type_filter": "land"}),),
        narrowed,
    )
    no_regen = (OracleInstruction("destroy_all_lands", "", {"bypass_regeneration": True}),)
    (respelt,), _ = one_sweep_kind(no_regen, narrowed)
    assert respelt.payload == {"type_filter": "land", "bypass_regeneration": True}
