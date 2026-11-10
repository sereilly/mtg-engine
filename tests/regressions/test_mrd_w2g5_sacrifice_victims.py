"""The victim of a sacrifice cost the effect reads (Mirrodin wave 2, W2G5).

"As an additional cost to cast this spell, sacrifice a creature. Fling deals
damage equal to the sacrificed creature's power to any target." A seat naming
no victim pays with the engine's deterministic pick, the smallest power first
(``Game.default_sacrifice_pick``) — right for a cost that is only a price,
wrong for one the effect is measured by. Six cast cards read the cost this
way (``x_from_count.cost_sacrifice_characteristic``); the cast chooser now
rehearses each distinct reading the board offers and names the best
(``ai_casts._cast_naming_its_sacrifice``, ``ai_sacrifice_victims``).
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_actions import CastAction, cast_announcement
from engine.ai_payment import tap_planned_lands
from engine.ai_policy import choose_cast_action
from engine.ai_sacrifice_victims import (characteristic_read_off_the_sacrifice,
                                         victims_to_weigh)
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick, resolve_stack


def _card(set_pool, name):
    for code in ("STH", "TMP", "MIR", "LEA"):
        if name in set_pool(code):
            return set_pool(code)[name]
    raise KeyError(name)


def _table(set_pool, mine, theirs, hand):
    game = Game(players=[
        PlayerState("A", hand=[_card(set_pool, n) for n in hand],
                    library=[_card(set_pool, "Plains")] * 10),
        PlayerState("B", library=[_card(set_pool, "Plains")] * 10),
    ])
    game.enforce_mana_costs = False
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _nosick(Permanent(card=_card(set_pool, name)))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            placed[seat].append(permanent)
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    game.start_turn(0)
    game._settle()
    game.enforce_mana_costs = True
    return game, placed[0], placed[1]


def test_a_lethal_fling_is_paid_with_the_creature_that_makes_it_lethal(set_pool):
    game, (elves, giant, *_lands), _ = _table(
        set_pool, ["Llanowar Elves", "Hill Giant", "Mountain", "Mountain"],
        ["Serra Angel"], ["Fling"],
    )
    game.players[1].life = 3
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Fling"
    assert action.cost_permanent_ids == [giant.permanent_id]
    tap_planned_lands(game, 0, action)
    assert game.cast_from_hand(0, "Fling", **cast_announcement(action)).supported
    resolve_stack(game)
    assert game.players[1].life <= 0
    assert game.is_on_battlefield(elves)


def test_the_cast_readers_name_their_characteristic(set_pool):
    for name, set_code, characteristic in (
        ("Fling", "STH", "power"), ("Carrion", "MIR", "power"),
        ("Worthy Cause", "TMP", "toughness"), ("Forge Armor", "MRD", "mana_value"),
    ):
        program = compile_card_oracle(set_pool(set_code)[name])
        assert characteristic_read_off_the_sacrifice(program.instructions) == characteristic, name
    plain = compile_card_oracle(_card(set_pool, "Lightning Bolt"))
    assert characteristic_read_off_the_sacrifice(plain.instructions) is None


def test_one_victim_per_reading_the_cheapest_kept_and_cheapest_first(set_pool):
    game, (bears_a, bears_b, giant, elves), _ = _table(
        set_pool, ["Grizzly Bears", "Grizzly Bears", "Hill Giant", "Llanowar Elves"],
        [], [],
    )
    weighed = victims_to_weigh(
        [bears_a, bears_b, giant, elves], "power", game.sacrifice_preference_key,
    )
    # Three readings (3, 2, 1), one of the two equal Bears, cheapest first.
    assert sorted(p.effective_power for p in weighed) == [1, 2, 3]
    assert sum(p.card.name == "Grizzly Bears" for p in weighed) == 1
    assert weighed[0] is elves and weighed[-1] is giant


def test_the_announcement_carries_the_named_victim():
    action = CastAction(
        card_name="Fling", target_player_index=1, x_value=None,
        land_tap_indices=(), score=1.0, hand_index=0, cost_permanent_ids=[42],
    )
    assert cast_announcement(action)["cost_permanent_ids"] == [42]
