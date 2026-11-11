"""The AI's announcement for "for each opponent, … target permanent that player
controls" (Blatant Thievery, ``target_roles.PER_OPPONENT_ROLE``).

The roles walk offers each role only the permanents of the opponent it is for,
so which one is the whole decision: the enumeration's order is the
battlefield's, and the seat took a Swamp from a table of creatures until each
such level was ordered by ``ai_standing.permanent_worth``.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_slot_targets import _choose_role_targets
from engine.models import Permanent
from tests.helpers import _mk_card, resolve_stack


def _permanent(name, type_line, *, power=2):
    permanent = Permanent(card=_mk_card(
        name=name, mana_cost="{3}{G}" if "Creature" in type_line else "",
        type_line=type_line, colors=("G",) if "Creature" in type_line else (),
        power=power, toughness=power,
    ))
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _table(set_pool):
    ons = set_pool("ONS")
    players = [
        PlayerState(name="A", hand=[ons["Blatant Thievery"]],
                    library=[ons["Island"]] * 5),
        PlayerState(name="B", battlefield=[
            _permanent("B Forest", "Basic Land - Forest"),
            _permanent("B Giant", "Creature - Giant", power=5),
        ], library=[ons["Island"]] * 5),
        PlayerState(name="C", battlefield=[
            _permanent("C Forest", "Basic Land - Forest"),
            _permanent("C Elf", "Creature - Elf", power=1),
        ], library=[ons["Island"]] * 5),
    ]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    return game


def test_the_ai_names_each_opponents_most_valuable_permanent(set_pool):
    game = _table(set_pool)
    card = game.players[0].hand[0]
    chosen = _choose_role_targets(game, 0, card)
    assert chosen not in (None, ())
    _seat, _indices, ids, _stack, _refs = chosen
    named = [game.permanent_by_id(pid).card.name for pid in ids]
    assert named == ["B Giant", "C Elf"]

    assert game.queue_from_hand(0, "Blatant Thievery", target_permanent_ids=ids).supported
    resolve_stack(game)
    assert sorted(p.card.name for p in game.controlled_by(0)) == ["B Giant", "C Elf"]


# "Choose any number of target players or planeswalkers. For each of them, …
# Kaboom! deals damage … to that player or planeswalker" — every role a seat or
# a planeswalker, so the side the walk reads is the loop body's
# (``ai_slot_sides.announced_roles_loop_side``): sideless, the chain named the
# caster's own seat first and burned it.


def test_the_ai_aims_kaboom_at_the_opponent_and_their_planeswalker(set_pool):
    from engine.named_counters import add_counters, counters_on

    ons = set_pool("ONS")
    walker = _permanent("B Walker", "Legendary Planeswalker - Chandra")
    add_counters(walker, "loyalty", 5)
    mine = _permanent("A Walker", "Legendary Planeswalker - Chandra")
    add_counters(mine, "loyalty", 5)
    game = Game(players=[
        PlayerState(name="A", hand=[ons["Kaboom!"]], battlefield=[mine],
                    library=[ons["Island"], ons["Clone"], ons["Shock"]]),
        PlayerState(name="B", battlefield=[walker], library=[ons["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()

    chosen = _choose_role_targets(game, 0, game.players[0].hand[0])
    assert chosen not in (None, ())
    seat, indices, ids, _stack, _refs = chosen
    assert seat == 1
    assert ids == [None, walker.permanent_id]

    assert game.queue_from_hand(
        0, "Kaboom!", target_player_index=seat, target_permanent_index=indices,
        target_permanent_ids=ids,
    ).supported
    resolve_stack(game)
    assert game.players[0].life == 20 and counters_on(mine, "loyalty") == 5
    assert game.players[1].life == 16 and counters_on(walker, "loyalty") == 4
