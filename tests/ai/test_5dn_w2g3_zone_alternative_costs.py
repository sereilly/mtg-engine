"""A printed non-mana alternative cost, taken for a cast out of an opened graveyard.

"If you control a Swamp, you may pay 4 life rather than pay this spell's mana
cost." (Snuff Out.) From the hand, a seat whose lands cannot pay {3}{B} pays
the 4 life (CR 118.9). From a graveyard Yawgmoth's Agenda opens, the cast
chooser stopped at the unpayable mana cost — "the planned price was already
the permission's" — though the Agenda charges the card's own cost and leaves
the printed alternative open (``ai_cast_gates.permission_leaves_the_price``;
5DN W1G2 measured it). A permission with a cost of its own (flashback, CR
118.9a) still allows no second one.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_actions import cast_announcement, spell_being_cast, zone_being_cast_from
from engine.ai_payment import tap_planned_lands
from engine.ai_policy import choose_cast_action
from engine.models import Permanent
from tests.helpers import settle


def _table(set_pool, *, graveyard=(), hand=()) -> Game:
    pool = {**set_pool("LEA"), **set_pool("MMQ"), **set_pool("INV")}
    game = Game(players=[
        PlayerState(
            name="AI", hand=[pool[n] for n in hand], graveyard=[pool[n] for n in graveyard],
            library=[pool["Swamp"]] * 8,
        ),
        PlayerState(name="Opp", library=[pool["Forest"]] * 8),
    ])
    game.interactive_seats = set()
    for seat, names in ((0, ["Swamp", "Yawgmoth's Agenda"]), (1, ["Grizzly Bears"])):
        for name in names:
            permanent = Permanent(card=pool[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    game.start_turn(0)
    settle(game)
    game.enforce_mana_costs = True
    return game


def test_snuff_out_is_cast_out_of_the_opened_graveyard_for_its_life(set_pool):
    """One Swamp, Snuff Out in the graveyard under Yawgmoth's Agenda: cast
    from the graveyard for 4 life, and the opposing Grizzly Bears die."""
    game = _table(set_pool, graveyard=["Snuff Out"])
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Snuff Out"
    assert action.from_zone == "graveyard" and action.alternative_cost
    action = tap_planned_lands(game, 0, action)
    spell = spell_being_cast(zone_being_cast_from(game, 0, action), action)
    result = game.cast_from_hand(0, spell.name, **cast_announcement(action))
    assert result.supported, result
    settle(game)
    assert game.players[0].life == 16
    assert any(card.name == "Grizzly Bears" for card in game.players[1].graveyard)


def test_the_hand_cast_pays_the_same_price(set_pool):
    """The same board with Snuff Out in hand: the alternative cost, as before."""
    game = _table(set_pool, hand=["Snuff Out"])
    action = choose_cast_action(game, 0)
    assert action is not None and action.from_zone == "hand" and action.alternative_cost
