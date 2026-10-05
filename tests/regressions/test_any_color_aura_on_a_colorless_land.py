"""An "additional one mana of any color" Aura on a land tapped for {C}.

"Whenever enchanted land is tapped for mana, its controller adds an additional
one mana of any color." (Fertile Ground, USG and INV.) The Aura's mana is
added inline, inside the payment that tapped the land (CR 605.4a gives a
triggered mana ability no window to ask in), so the colour it makes is the
colour that same call asked the land for — which was read through the colour
normalizer and **raised** when the land had been asked for ``{C}``:

    ValueError: Invalid mana color: C

A colourless land wearing the Aura is an ordinary board, and the AI's shared
tap executor (``ai_policy.tap_planned_lands``, the simulator's *and* the web
app's AI seat) asks a land for exactly the symbol its plan counted — so the
first AI seat to plan a ``{C}`` out of such a land took the whole game down.
Found by INV W3G1 on a seeded simulation (Archaeological Dig under a Fertile
Ground) while it was driving something else.

"Any color" is never colourless (CR 105.1: the five colours), so a caller that
asked the land for ``{C}`` has named no colour for the Aura, and that is the
case the tap seam already had an answer for: the same default as a call that
named none.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.models import Permanent


def _board(catalog_by_name, land_name):
    game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
    land = Permanent(card=catalog_by_name[land_name])
    aura = Permanent(card=catalog_by_name["Fertile Ground"])
    game.players[0].battlefield.extend([land, aura])
    game._sync_control()
    attach_aura(aura, land)
    return game, land


def _pool(game):
    return {symbol: n for symbol, n in game.players[0].mana_pool.items() if n}


@pytest.mark.parametrize("asked", ["C", "c"])
def test_a_colorless_land_under_fertile_ground_taps_for_colorless(catalog_by_name, asked):
    """Mishra's Factory makes {C}; the Aura adds one mana of a colour."""
    game, land = _board(catalog_by_name, "Mishra's Factory")

    assert game.tap_land_for_mana(0, "Mishra's Factory", chosen_color=asked)

    pool = _pool(game)
    assert pool.pop("C") == 1
    assert sum(pool.values()) == 1 and set(pool) <= {"W", "U", "B", "R", "G"}, pool
    assert land.tapped


def test_the_colour_asked_for_is_still_the_colour_the_aura_makes(catalog_by_name):
    """The fix widens nothing: a colour that *is* named is the Aura's."""
    game, _land = _board(catalog_by_name, "Forest")

    assert game.tap_land_for_mana(0, "Forest", chosen_color="U")

    assert _pool(game) == {"G": 1, "U": 1}


def test_a_word_that_is_no_mana_symbol_is_still_refused(catalog_by_name):
    """…and a value that is neither a colour nor {C} is still an error: the
    normalizer is there because the colour arrives off the wire."""
    game, _land = _board(catalog_by_name, "Forest")

    with pytest.raises(ValueError):
        game.tap_land_for_mana(0, "Forest", chosen_color="purple")
