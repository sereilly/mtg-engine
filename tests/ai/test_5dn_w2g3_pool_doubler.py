"""A mana ability that doubles the pool, counted by the AI's payment plan.

"{3}, {T}: Double the amount of each type of unspent mana you have."
(Doubling Cube.) Its yield is no amount a payload states, so no planner
counted it and the AI never activated one (5DN W1G7). It is now the plan's
last resort (``ai_payment._plan_through_a_pool_doubler``): the free sources
float half of the cost plus the Cube's price, the Cube is activated last, and
the plan is kept only where a scratch copy's pool then pays the cost — the
engine's own arithmetic for which units pay the price. The ability is a mana
ability (the card's 2004-12-01 ruling), so it never uses the stack.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_actions import cast_announcement
from engine.ai_payment import _plan_land_taps, tap_planned_lands
from engine.ai_policy import choose_cast_action
from engine.models import Permanent
from tests.helpers import settle


def _table(set_pool, *, lands, land="Forest", hand=()) -> tuple[Game, Permanent]:
    lea, fdn, atq = set_pool("LEA"), set_pool("5DN"), set_pool("ATQ")
    pool = {**lea, **atq}
    game = Game(players=[
        PlayerState(name="AI", hand=[pool[name] for name in hand], library=[lea["Forest"]] * 8),
        PlayerState(name="Opp", library=[lea["Forest"]] * 8),
    ])
    game.interactive_seats = set()
    cube = None
    for card in [lea[land]] * lands + [fdn["Doubling Cube"]]:
        permanent = Permanent(card=card)
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        if card.name == "Doubling Cube":
            cube = permanent
    game._sync_control()
    game.start_turn(0)
    settle(game)
    game.enforce_mana_costs = True
    return game, cube


def test_eight_forests_and_the_cube_cast_a_nine_mana_spell(set_pool):
    """Eight Forests make eight; the Cube's {3} comes out of them and the
    five left double to ten, which pays Colossus of Sardia's {9}. The plan
    taps the Cube last, and the cast resolves."""
    game, cube = _table(set_pool, lands=8, hand=["Colossus of Sardia"])
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Colossus of Sardia"
    assert game.permanent_at(0, action.land_tap_indices[-1]) is cube
    action = tap_planned_lands(game, 0, action)
    assert cube.tapped
    assert any("Doubling Cube doubled" in line for line in game.log)
    result = game.cast_from_hand(0, action.card_name, **cast_announcement(action))
    assert result.supported, result
    settle(game)
    assert any(p.card.name == "Colossus of Sardia" for p in game.controlled_by(0))


def test_seven_forests_are_not_enough_and_nothing_is_tapped(set_pool):
    """Seven Forests: 7 - 3 = 4, doubled to 8, short of {9}. No plan, no
    cast, and the Cube stays untapped."""
    game, cube = _table(set_pool, lands=7, hand=["Colossus of Sardia"])
    assert choose_cast_action(game, 0) is None
    assert not cube.tapped and not any(p.tapped for p in game.controlled_by(0))


def test_a_cost_the_lands_pay_leaves_the_cube_alone(set_pool):
    """Craw Wurm's {4}{G}{G} off eight Forests: the free plan pays it and the
    doubler is never reached."""
    game, cube = _table(set_pool, lands=8, hand=["Craw Wurm"])
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Craw Wurm"
    assert cube not in [game.permanent_at(0, slot) for slot in action.land_tap_indices]


def test_coloured_pips_are_floated_half_and_doubled_whole(set_pool):
    """{5}{U}{U}{U}{U} off eight Islands: two blue for the four pips, three
    more for half the whole, three for the price — eight floated, five left,
    ten blue. The plan the planner returns pays it when carried out."""
    game, cube = _table(set_pool, lands=8, land="Island")
    required = {"U": 4, "generic": 5}
    plan = _plan_land_taps(game, game.players[0], required)
    assert plan is not None and game.permanent_at(0, plan[0][-1]) is cube
    assert len(plan[0]) == 9

    class _Plan:
        land_tap_indices, land_tap_colors = plan

    tap_planned_lands(game, 0, _Plan)
    assert game.players[0].mana_pool.get("U", 0) == 10
