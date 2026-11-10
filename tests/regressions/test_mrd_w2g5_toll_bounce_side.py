"""A toll's effect, aimed by the seat that pays for it (Mirrodin wave 2, W2G5).

"{1}, {T}: Return target creature to its owner's hand unless its controller
pays {1}." (Erratic Portal; Mirrodin's Crystal Shard prints the same.) The
ability compiles to an offer to the target's controller whose unpaid branch
is the bounce, and that bounce carries no ``targets`` payload — so no step
reader had a side to give, and the activation chooser aimed at the largest
creature on either board: an AI seat bounced its own creature and then paid
its own toll. ``ai_target_sides.toll_effect_side`` reads the unpaid branch's
family instead.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_abilities import choose_activation_action
from engine.ai_actions import activation_announcement
from engine.ai_payment import tap_planned_lands
from engine.ai_target_sides import toll_effect_side
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick, resolve_stack


def _card(set_pool, name):
    exo = set_pool("EXO")
    return exo[name] if name in exo else set_pool("LEA")[name]


def _table(set_pool, mine, theirs=()):
    game = Game(players=[
        PlayerState("A", library=[_card(set_pool, "Island")] * 10),
        PlayerState("B", library=[_card(set_pool, "Island")] * 10),
    ])
    game.enforce_mana_costs = False
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _nosick(Permanent(card=_card(set_pool, name)))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            placed[seat].append(permanent)
    game.start_turn(0)
    game._settle()
    game.enforce_mana_costs = True
    return game, placed[0], placed[1]


def test_the_portal_is_not_activated_at_its_own_creature(set_pool):
    game, (_portal, bears, *lands), _ = _table(
        set_pool, ["Erratic Portal", "Grizzly Bears", "Island", "Island"],
    )
    assert choose_activation_action(game, 0) is None
    assert game.is_on_battlefield(bears)
    assert not any(land.tapped for land in lands)


def test_the_portal_bounces_the_opponents_creature(set_pool):
    game, (_portal, bears, *_lands), (giant,) = _table(
        set_pool, ["Erratic Portal", "Grizzly Bears", "Island", "Island"], ["Hill Giant"],
    )
    action = choose_activation_action(game, 0)
    assert action is not None and action.target_player_index == 1
    tap_planned_lands(game, 0, action)
    assert game.activate_permanent_ability(
        0, "Erratic Portal", **activation_announcement(action),
    ).supported
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    # Seat 1 has no land to pay with, so the toll's other half happens.
    assert [card.name for card in game.players[1].hand] == ["Hill Giant"]
    assert game.is_on_battlefield(bears)


def test_the_toll_reader_answers_only_the_toll_shape(set_pool):
    (portal,) = compile_card_oracle(_card(set_pool, "Erratic Portal")).activated_abilities
    assert toll_effect_side(portal.instruction) == "opponent"
    # A plain "you may" offer to the activator is not a toll on a target.
    lea = set_pool("LEA")
    for name in ("Prodigal Sorcerer", "Royal Assassin"):
        (ability,) = compile_card_oracle(lea[name]).activated_abilities
        assert toll_effect_side(ability.instruction) is None
