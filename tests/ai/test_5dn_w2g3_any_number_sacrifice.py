"""How many creatures an "any number of" sacrifice eats, and which body it pumps.

"As an additional cost to cast this spell, sacrifice any number of creatures.
Target creature gets +2/+2 until end of turn for each creature sacrificed this
way." (Vicious Betrayal.) Named nothing, the engine sacrifices nothing and
pumps +0/+0, so every target the chooser rehearsed read as nothing and the
spell was dropped for "no legal target on the side the effect wants" — the AI
never cast it (5DN W1G7). The target choosers now rehearse each target with
one provisional victim (``ai_actions._SACRIFICES_ANNOUNCED``), and
``ai_sacrifice_victims.cast_naming_its_sacrifices`` rehearses one set per
size, the cheapest to lose first: a creature is given up only where the pump
it buys is worth more than it is.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_actions import cast_announcement
from engine.ai_payment import tap_planned_lands
from engine.ai_policy import choose_cast_action
from engine.models import Permanent
from tests.helpers import declare_attack, drive_combat, settle


def _table(set_pool, *, mine, theirs=(), opponent_life=20) -> tuple[Game, dict]:
    lea, fdn = set_pool("LEA"), set_pool("5DN")
    game = Game(players=[
        PlayerState(name="AI", hand=[fdn["Vicious Betrayal"]], library=[lea["Swamp"]] * 8),
        PlayerState(name="Opp", library=[lea["Forest"]] * 8),
    ])
    game.interactive_seats = set()
    placed: dict = {}
    for seat, names in ((0, ["Swamp"] * 5 + list(mine)), (1, list(theirs))):
        for name in names:
            permanent = Permanent(card=lea[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed.setdefault(name, permanent)
    game._sync_control()
    game.players[1].life = opponent_life
    game.start_turn(0)
    settle(game)
    game.enforce_mana_costs = True
    return game, placed


def _cast(game, action) -> None:
    action = tap_planned_lands(game, 0, action)
    result = game.cast_from_hand(0, action.card_name, **cast_announcement(action))
    assert result.supported, result
    settle(game)


def test_one_sacrifice_that_makes_the_attack_lethal_is_made(set_pool):
    """The opponent at 4, the seat holding Grizzly Bears and Llanowar Elves:
    3 damage unpumped, and the Elves given up make the Bears a 4/4 that ends
    the game. The cast names the Bears and pays with the Elves, and the fight
    the rehearsal counted on is the one the turn then has."""
    game, placed = _table(set_pool, mine=["Llanowar Elves", "Grizzly Bears"], opponent_life=4)
    elves, bears = placed["Llanowar Elves"], placed["Grizzly Bears"]
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Vicious Betrayal"
    assert action.target_permanent_ids == [bears.permanent_id]
    assert action.cost_permanent_ids == [elves.permanent_id]
    _cast(game, action)
    assert any(card.name == "Llanowar Elves" for card in game.players[0].graveyard)
    assert (bears.effective_power, bears.effective_toughness) == (4, 4)
    declare_attack(game, 0)
    drive_combat(game)
    assert game.players[1].life <= 0


def test_no_creature_is_given_up_for_a_pump_worth_less(set_pool):
    """The opponent at 20 with nothing to block: the Elves' +2/+2 on the
    Bears is one more damage than the Elves would deal themselves, a lasting
    creature spent on a turn's pump. Nothing is cast."""
    game, _placed = _table(set_pool, mine=["Llanowar Elves", "Grizzly Bears"])
    assert choose_cast_action(game, 0) is None


def test_the_pump_goes_on_the_casters_own_creature(set_pool):
    """An opposing Hill Giant, tapped so it blocks nothing, is a legal target,
    and +2/+2 on it is a gift: the cast names the seat's own Bears."""
    game, placed = _table(
        set_pool, mine=["Llanowar Elves", "Grizzly Bears"], theirs=["Hill Giant"],
        opponent_life=4,
    )
    placed["Hill Giant"].tapped = True
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Vicious Betrayal"
    assert action.target_permanent_ids == [placed["Grizzly Bears"].permanent_id]
    assert action.cost_permanent_ids == [placed["Llanowar Elves"].permanent_id]


def test_a_lone_creature_is_no_cast(set_pool):
    """One creature: it is the only target and the only victim, and a pump
    paid for with its own target is a pump on nothing. Not cast."""
    game, _placed = _table(set_pool, mine=["Grizzly Bears"], opponent_life=2)
    assert choose_cast_action(game, 0) is None
