"""A seat that names {C} for an "any type" / "any color" mana ability.

"{T}: Add one mana of any **type** that a land you control could produce."
(Reflecting Pool.) Beside a Mishra's Factory the only type that board offers is
{C} (CR 106.1b: colourless is one of the six types of mana), and it is exactly
what `Game.narrowed_land_mana_colors` — the reader behind the client's colour
picker and the AI's tap plan — answers. The add-mana handler read the named
symbol through the *colour* normalizer, which raises on anything outside
WUBRG: tapping that Pool for the {C} its own picker offered ended the game with
``ValueError: Invalid mana color: C``.

Found by making the AI's plan count a Reflecting Pool (PLS W2G5): the first
simulated tap of one beside a colourless land crashed the run.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent


@pytest.fixture(scope="module")
def pool() -> dict:
    return {card.name: card for card in load_cards(manifest_set_paths())}


def _w2g5_board(pool, *names) -> tuple:
    game = Game(players=[
        PlayerState("A", library=[pool["Forest"]] * 10),
        PlayerState("B", library=[pool["Forest"]] * 10),
    ])
    permanents = []
    for name in names:
        permanent = Permanent(card=pool[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanents.append(permanent)
    return game, permanents


def _w2g5_floating(game) -> dict:
    return {symbol: n for symbol, n in game.players[0].mana_pool.items() if n}


def test_w2g5_reflecting_pool_asked_for_colorless_beside_a_colorless_land(pool):
    game, (reflecting, _factory) = _w2g5_board(pool, "Reflecting Pool", "Mishra's Factory")
    assert game.narrowed_land_mana_colors(reflecting) == ("C",)
    assert game.tap_land_for_mana(
        0, "Reflecting Pool", chosen_color="C", permanent_id=reflecting.permanent_id,
    )
    assert reflecting.tapped
    assert _w2g5_floating(game) == {"C": 1}


def test_w2g5_reflecting_pool_asked_for_colorless_it_cannot_make_takes_what_it_can(pool):
    """Beside a Swamp the board offers {B} alone: a {C} named there is outside
    the set (CR 608.2d) and the Pool makes what the board defines."""
    game, (reflecting, _swamp) = _w2g5_board(pool, "Reflecting Pool", "Swamp")
    assert game.tap_land_for_mana(
        0, "Reflecting Pool", chosen_color="C", permanent_id=reflecting.permanent_id,
    )
    assert _w2g5_floating(game) == {"B": 1}


def test_w2g5_any_color_asked_for_colorless_names_no_color(pool):
    """"Any color" is one of the five (CR 105.1), never colourless: a City of
    Brass asked for {C} has been named no colour and makes a colour, where it
    used to raise for the same reason the Pool did."""
    game, (city,) = _w2g5_board(pool, "City of Brass")
    assert game.tap_land_for_mana(
        0, "City of Brass", chosen_color="C", permanent_id=city.permanent_id,
    )
    floating = _w2g5_floating(game)
    assert sum(floating.values()) == 1 and "C" not in floating
