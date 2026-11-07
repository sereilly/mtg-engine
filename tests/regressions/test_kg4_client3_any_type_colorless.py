"""{C} named for an "any type" mana ability is the type made, beside others.

"{T}: Add one mana of any **type** that a land you control could produce."
(Reflecting Pool.) "Sacrifice a land: Add one mana of any type the sacrificed
land could produce." (Squandered Resources.) {C} is one of CR 106.1b's six
types, and the handler reads a named {C} apart from a colour — but both sites
that run a mana ability inline read the wire's symbol through
``_chosen_mana_color``, which drops {C} (CR 105.1: colourless is not a
colour). So a {C} was "nothing named", and a board offering {C} and {G} made
{G}: the earlier regression (``test_any_type_mana_named_colorless``) passed
only because {C} was the board's *one* type. The type now rides its own key
(``mana_could_produce.NAMED_MANA_TYPE``).

Backwards on the base: both boards make {G} / {U}, never {C}.
"""
from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent

_CARDS = {card.name: card for card in load_catalog()}


def _board(*names):
    game = Game(players=[
        PlayerState("A", library=[_CARDS["Forest"]] * 10),
        PlayerState("B", library=[_CARDS["Forest"]] * 10),
    ])
    placed = {}
    for name in names:
        permanent = Permanent(card=_CARDS[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        placed[name] = permanent
    return game, placed


def _floating(game) -> dict:
    return {symbol: n for symbol, n in game.players[0].mana_pool.items() if n}


def test_reflecting_pool_asked_for_colorless_beside_a_forest_and_a_colorless_land():
    game, placed = _board("Reflecting Pool", "Mishra's Factory", "Forest")
    pool = placed["Reflecting Pool"]
    assert set(game.narrowed_land_mana_colors(pool)) == {"C", "G"}
    assert game.tap_land_for_mana(0, "Reflecting Pool", chosen_color="C", permanent_id=pool.permanent_id)
    assert _floating(game) == {"C": 1}


def test_reflecting_pool_asked_for_green_there_still_makes_green():
    game, placed = _board("Reflecting Pool", "Mishra's Factory", "Forest")
    pool = placed["Reflecting Pool"]
    assert game.tap_land_for_mana(0, "Reflecting Pool", chosen_color="G", permanent_id=pool.permanent_id)
    assert _floating(game) == {"G": 1}


def test_squandered_resources_sacrificing_a_painland_for_colorless():
    game, placed = _board("Squandered Resources", "Underground River")
    river = placed["Underground River"]
    result = game.activate_permanent_ability(
        0, "Squandered Resources", cost_permanent_ids=[river.permanent_id], mana_color="C",
    )
    assert result.supported, result.details
    assert not game.is_on_battlefield(river)
    assert _floating(game) == {"C": 1}
