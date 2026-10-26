"""The AI's announcement for "for each opponent, … target permanent that player
controls" (Blatant Thievery, ``target_roles.PER_OPPONENT_ROLE``).

The roles walk offers each role only the permanents of the opponent it is for,
so which one is the whole decision: the enumeration's order is the
battlefield's, and the seat took a Swamp from a table of creatures until each
such level was ordered by ``ai_rehearsal.permanent_worth``.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_targets import _choose_role_targets
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
    _seat, _indices, ids, _stack = chosen
    named = [game.permanent_by_id(pid).card.name for pid in ids]
    assert named == ["B Giant", "C Elf"]

    assert game.queue_from_hand(0, "Blatant Thievery", target_permanent_ids=ids).supported
    resolve_stack(game)
    assert sorted(p.card.name for p in game.controlled_by(0)) == ["B Giant", "C Elf"]
