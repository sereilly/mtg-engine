"""A roles announcement whose "target player **or planeswalker**" role names a
planeswalker.

Lunge: "Lunge deals 2 damage to target creature and 2 damage to target player
or planeswalker." The picker offered the planeswalker for the second role and
the cast gate then refused the announcement ("no valid target for Lunge"):
``_named_role_targets`` filled every seat-kind slot from the seat channels, so
the planeswalker named by id was read as a missing player. The resolution's
role scoping had the same reading (``control_flow._role_scoped``). Found
building Kaboom!, whose every role is that union.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from engine.named_counters import add_counters, counters_on
from tests.helpers import _mk_card, resolve_stack


def test_lunge_deals_its_second_two_to_a_planeswalker(set_pool):
    mmq = set_pool("MMQ")
    bear = Permanent(card=_mk_card(
        name="Bear", mana_cost="{1}{G}", type_line="Creature - Bear",
        colors=("G",), power=3, toughness=3,
    ))
    walker = Permanent(card=_mk_card(
        name="Walker", mana_cost="{3}{R}",
        type_line="Legendary Planeswalker - Chandra", colors=("R",),
    ))
    add_counters(walker, "loyalty", 5)
    game = Game(players=[
        PlayerState(name="A", hand=[mmq["Lunge"]], library=[mmq["Island"]] * 5),
        PlayerState(name="B", battlefield=[bear, walker], library=[mmq["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()

    spec = game.cast_target_spec(0, mmq["Lunge"])
    (creature,) = spec["valid_targets"]
    assert ("permanent", "Walker") in {(o["kind"], o.get("name")) for o in creature["next"]}

    result = game.queue_from_hand(0, "Lunge", target_role_refs=[
        {"permanent_id": bear.permanent_id}, {"permanent_id": walker.permanent_id},
    ])
    assert result.supported, result.details
    resolve_stack(game)
    assert counters_on(walker, "loyalty") == 3
    assert game.players[1].life == 20
    assert "Lunge dealt 2 damage to Bear" in game.log
