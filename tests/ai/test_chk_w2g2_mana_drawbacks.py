"""Forbidden Orchard's tap is priced (``engine/mana_drawbacks.py``).

"{T}: Add one mana of any color. Whenever you tap this land for mana, target
opponent creates a 1/1 colorless Spirit creature token." Nothing in the price
read a token made for another seat, so the AI tapped the Orchard as freely as
a Forest (CHK W1G9) and handed the opponent a Spirit for every mana. A token
given to another seat is priced at its power and toughness — a 1/1 at two —
and the sparing choice spends a free source of the colour first.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_payment import _plan_land_taps
from engine.mana_drawbacks import tap_prices
from engine.models import Permanent


def _w2g2_lands(set_pool, names) -> Game:
    chk = set_pool("CHK")
    game = Game(players=[
        PlayerState(name="P1", battlefield=[Permanent(card=chk[name]) for name in names],
                    library=[chk["Forest"]] * 5),
        PlayerState(name="P2", library=[chk["Forest"]] * 5),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game._sync_control()
    game.start_turn(0)
    game._settle()
    return game


def test_forbidden_orchard_is_priced_at_the_spirit_it_hands_over(set_pool):
    game = _w2g2_lands(set_pool, ["Forbidden Orchard", "Forest"])
    orchard, forest = game.players[0].battlefield
    assert tap_prices(game, orchard, ("G",)) == {"G": 2}
    assert tap_prices(game, forest, ("G",)) == {"G": 0}


def test_the_plan_spends_a_city_of_brass_point_before_an_orchard_spirit(set_pool):
    """Two sources of any colour, each with a price: City of Brass's one
    damage against the Orchard's 1/1 for the opponent. {G} is paid with the
    City; on the base the Orchard read as free and paid it."""
    game = _w2g2_lands(set_pool, ["Forbidden Orchard"])
    city = Permanent(card=set_pool("ARN")["City of Brass"])
    game._put_permanent_onto_battlefield(0, city, None)
    game._sync_control()
    player = game.players[0]

    taps, _colours = _plan_land_taps(game, player, {"G": 1})
    assert [player.battlefield[slot].card.name for slot in taps] == ["City of Brass"]
