"""Whose creature an AI seat puts a *named* counter on.

A named counter has no meaning of its own (CR 122.1): what it does is whatever
the card's other lines say. The activation chooser read "{T}: Put a fuse
counter on target creature" (Bomb Squad) by its category — ``counters``, an
own-side category because a +1/+1 counter is a gift — so a seat holding the
card lit its own creature, watched it destroyed, took the 4 damage, and then
started on Bomb Squad itself. ODY W2G7 found it by dealing the card into six
simulated games.

``ai_target_sides.named_counter_marks_for_harm`` derives the answer from the
compiled program: the same card carries a state trigger over that counter kind
whose effect the engine already files as hostile.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_abilities import choose_activation_action
from engine.ai_target_sides import named_counter_marks_for_harm
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _table(set_pool):
    lea = set_pool("LEA")
    game = Game(players=[
        PlayerState("AI", library=[lea["Mountain"]] * 10),
        PlayerState("Opponent", library=[lea["Mountain"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game


def _put(game, seat, card):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.tapped = False
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _invented(name, text):
    return CardDefinition(
        name=name, mana_cost="{2}", cmc=2.0, type_line="Creature — Probe",
        oracle_text=text, colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": name, "type_line": "Creature — Probe",
                               "power": "1", "toughness": "1"},
    )


def test_bomb_squads_fuse_is_read_as_harm(set_pool):
    squad = set_pool("ODY")["Bomb Squad"]
    (ability,) = compile_card_oracle(squad).activated_abilities
    assert named_counter_marks_for_harm(squad, ability.instruction)


def test_an_ai_seat_lights_an_opponents_creature(set_pool):
    lea = set_pool("LEA")
    game = _table(set_pool)
    _put(game, 0, set_pool("ODY")["Bomb Squad"])
    _put(game, 0, lea["Craw Wurm"])  # the biggest creature on either board
    theirs = _put(game, 1, lea["Grizzly Bears"])

    action = choose_activation_action(game, 0)

    assert action is not None and action.permanent_name == "Bomb Squad"
    assert action.target_player_index == 1
    assert game.players[1].battlefield[action.target_permanent_index] is theirs


def test_an_ai_seat_with_only_its_own_creatures_keeps_the_fuse_dry(set_pool):
    lea = set_pool("LEA")
    game = _table(set_pool)
    _put(game, 0, set_pool("ODY")["Bomb Squad"])
    _put(game, 0, lea["Craw Wurm"])

    action = choose_activation_action(game, 0)

    assert action is None or action.permanent_name != "Bomb Squad"


def test_a_named_counter_nothing_punishes_is_not_read_as_harm(set_pool):
    """The derivation is about the card's own other lines, not about named
    counters: one no state trigger watches keeps the reading it had."""
    marker = _invented(
        "W2G7 Marker", "{T}: Put a charge counter on target creature.",
    )
    program = compile_card_oracle(marker)
    assert program.supported, program.reason
    (ability,) = program.activated_abilities
    assert not named_counter_marks_for_harm(marker, ability.instruction)
    # …and another kind of counter than the one the trigger watches is not it.
    mixed = _invented(
        "W2G7 Mixed",
        "{T}: Put a charge counter on target creature.\n"
        "Whenever a creature has two or more doom counters on it, destroy it.",
    )
    program = compile_card_oracle(mixed)
    assert program.supported, program.reason
    assert not named_counter_marks_for_harm(
        mixed, program.activated_abilities[0].instruction
    )
