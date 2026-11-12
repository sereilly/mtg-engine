"""Engineered Explosives' X: the colour count aimed at the mana value the board wants swept.

"{X}. Sunburst. {2}, Sacrifice this artifact: Destroy each nonland permanent
with mana value equal to the number of charge counters on this artifact." The
AI announced the largest X its lands paid — every colour in reach, whatever
the board held at that mana value (5DN W1G1). ``ai_sunburst_x.aimed_sunburst_x``
prices each count the payment would hit as what the sweep would then take of
the other seat's less the caster's own, and the X is that count: N generic
spread over N colours, no mana beyond them.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_actions import cast_announcement
from engine.ai_payment import tap_planned_lands
from engine.ai_policy import choose_cast_action
from engine.models import Permanent
from engine.named_counters import counters_on
from tests.helpers import settle

_LANDS = ["Plains", "Island", "Swamp", "Mountain", "Forest"]


def _table(set_pool, *, mine=(), theirs=(), lands=_LANDS) -> Game:
    pool = {**set_pool("LEA"), **set_pool("ATQ"), **set_pool("5DN")}
    game = Game(players=[
        PlayerState(name="AI", hand=[pool["Engineered Explosives"]], library=[pool["Forest"]] * 8),
        PlayerState(name="Opp", library=[pool["Forest"]] * 8),
    ])
    game.interactive_seats = set()
    for seat, names in ((0, [*lands, *mine]), (1, list(theirs))):
        for name in names:
            permanent = Permanent(card=pool[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    game.start_turn(0)
    settle(game)
    game.enforce_mana_costs = True
    return game


def _cast_counters(game, action) -> int:
    action = tap_planned_lands(game, 0, action)
    result = game.cast_from_hand(0, action.card_name, **cast_announcement(action))
    assert result.supported, result
    settle(game)
    explosives = next(
        p for p in game.controlled_by(0) if p.card.name == "Engineered Explosives"
    )
    return counters_on(explosives, "charge")


def test_the_count_is_the_mana_value_worth_most_to_sweep(set_pool):
    """Five lands of five colours; the opponent holds a Grizzly Bears (2) and
    a Hill Giant (4). The X is 4, paid in four colours, and the Explosives
    enter with four charge counters — the Giant's mana value."""
    game = _table(set_pool, theirs=["Grizzly Bears", "Hill Giant"])
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Engineered Explosives"
    assert action.x_value == 4 and len(action.land_tap_indices) == 4
    assert _cast_counters(game, action) == 4


def test_two_cheap_creatures_outweigh_one_dear_one(set_pool):
    """Two Grizzly Bears beside the Hill Giant: two for one is the better
    sweep, so the X is 2 and only two lands are tapped."""
    game = _table(set_pool, theirs=["Grizzly Bears", "Grizzly Bears", "Hill Giant"])
    action = choose_cast_action(game, 0)
    assert action is not None and action.x_value == 2
    assert len(action.land_tap_indices) == 2
    assert _cast_counters(game, action) == 2


def test_the_casters_own_board_is_not_aimed_at(set_pool):
    """Two of the seat's own Bears against the opponent's one: mana value 2
    costs more than it takes, so it is never the count."""
    game = _table(set_pool, mine=["Grizzly Bears", "Grizzly Bears"], theirs=["Grizzly Bears"])
    action = choose_cast_action(game, 0)
    assert action is None or action.x_value != 2


def test_mana_value_zero_is_an_x_of_zero(set_pool):
    """Two opposing Ornithopters (mana value 0) and nothing else: X = 0 is
    the aim, so the Explosives are cast for nothing, tap no land, and enter
    with no counters — the count that sweeps the Ornithopters."""
    game = _table(set_pool, theirs=["Ornithopter", "Ornithopter"])
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Engineered Explosives"
    assert action.x_value == 0 and not action.land_tap_indices
    assert _cast_counters(game, action) == 0
