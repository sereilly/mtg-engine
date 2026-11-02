"""The combat damage step asks its affected players CR 616.1e's question in
APNAP order.

CR 616.1's last sentence: "If two or more players have to make these choices
at the same time, choices are made in APNAP order (see rule 101.4)." Combat
damage is dealt simultaneously (CR 510.2), so every affected player's choices
about it are made at the same time: the active player's (their attackers
dealt damage by blockers), then each other player's in turn order. The step
walked blockers, then the attackers' damage to blockers, then to players —
each in slot order — so at three seats with the active player in seat 1 it
asked seat 0 before seat 2 whenever seat 0's attacker sat in the lower slot.

Validated backwards: on 753c241a the order is [1, 0, 2].
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import CardDefinition, Permanent
from engine.named_counters import counters_on
from engine.shields import add_shield, make_counting_pool, make_numeric_pool

_POOL = {card.name: card for card in load_catalog()}


def _creature(name: str, power: int, toughness: int) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature — Test",
        oracle_text="", colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Creature — Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _put(game: Game, seat: int, card: CardDefinition) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _arm_two(recipient) -> None:
    """Two applicable prevention effects, either of which may apply first."""
    add_shield(recipient, make_numeric_pool(10, source_name="Plain Pool"))
    add_shield(recipient, make_counting_pool(10, "+1/+1", source_name="Counting Pool"))


def _fight(interactive: set[int]):
    """Seat 1 is active. "At Zero" (lowest slot) attacks seat 0, "At Two"
    attacks seat 2, and "Third" attacks seat 2 and is blocked by seat 2's
    1/1. Seat 0, seat 2 and Third each hold two shields."""
    game = Game(players=[
        PlayerState(f"P{seat}", library=[_POOL["Island"]] * 10) for seat in range(3)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    at_zero = _put(game, 1, _creature("At Zero", 2, 2))
    at_two = _put(game, 1, _creature("At Two", 2, 2))
    third = _put(game, 1, _creature("Third", 3, 3))
    blocker = _put(game, 2, _creature("Blocker", 1, 1))
    for recipient in (game.players[0], game.players[2], third):
        _arm_two(recipient)
    game._sync_control()
    game.active_player_index = 1
    game._set_phase_and_step("combat", "declare_attackers")
    zero_slot, two_slot, third_slot = (
        game.battlefield_index_of(creature) for creature in (at_zero, at_two, third)
    )
    assert zero_slot < two_slot
    assert game.declare_attackers(
        1, [zero_slot, two_slot, third_slot],
        attacker_targets={zero_slot: 0, two_slot: 2, third_slot: 2},
        defending_player_index=0,
    )[0]
    game._set_phase_and_step("combat", "declare_blockers")
    assert game.declare_blockers(0, {})[0]
    assert game.declare_blockers(2, {game.battlefield_index_of(blocker): [third_slot]})[0]
    game._set_phase_and_step("combat", "combat_damage")
    assert game.resolve_all_combat_damage(1)[0]
    return game, third, blocker


def _board(game, third, blocker) -> tuple:
    return (
        tuple(player.life for player in game.players),
        third.damage_marked, counters_on(third, "+1/+1"),
        game.is_on_battlefield(blocker),
    )


@pytest.mark.cr("616.1", "101.4", "510.2")
def test_combat_damage_asks_the_active_player_then_each_defender_in_turn_order():
    reference = _fight(set())
    assert not reference[0].pending_choices, "a default seat was asked"
    assert "Resolved combat damage" in reference[0].log

    game, third, blocker = _fight({0, 1, 2})
    order = []
    while (choice := game.pending_choice_of("effect_order")) is not None:
        order.append(choice.player_index)
        assert game.resolve_pending_choice("effect_order", choice.player_index, option_index=0)
    assert order == [1, 2, 0]
    assert "Resolved combat damage" in game.log
    assert not game.resume_stack
    assert _board(game, third, blocker) == _board(*reference)
