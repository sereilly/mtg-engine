"""CR 305.7 over Quicksilver Fountain's flood (Mirrodin; W2G0).

    305.7. If an effect sets a land's subtype to one or more of the basic
           land types, the land no longer has its old land type. It loses all
           abilities generated from its rules text, its old land types, and
           any copiable effects affecting that land, and it gains the
           appropriate mana ability for each new basic land type. …

"At the beginning of each player's upkeep, that player puts a flood counter
on target non-Island land they control of their choice. That land is an
Island for as long as it has a flood counter on it." The handler behind the
second sentence (``set_land_type_while_counter``) writes the same layer-4
contribution every other setter writes (``land_types.change_land_type``),
keyed on the counter, so the readers CR 305.7 was taught one at a time read
it too. ``test_land_type_set_loses_abilities``'s census of setter kinds now
lists it; this drives it through the real upkeep: a flooded Forest makes only
{U}, a flooded City of Brass neither taps for another colour nor deals its
damage, a flooded Strip Mine cannot be activated — and with the counter gone
each is the land it was (CR 611.2b: the effect is over).
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.named_counters import counters_on, remove_counters
from tests.helpers import resolve_stack


def _flooded(set_pool, land_card):
    """Quicksilver Fountain and *land_card* on seat 0's side, the land its
    only one; seat 0's upkeep floods it (nobody is asked: the only
    candidate)."""
    lea = set_pool("LEA")
    game = Game(players=[
        PlayerState(name="A", library=[lea["Plains"]] * 8),
        PlayerState(name="B", library=[lea["Plains"]] * 8),
    ])
    game.enforce_mana_costs = False
    placed = []
    for card in (set_pool("MRD")["Quicksilver Fountain"], land_card):
        permanent = Permanent(card=card)
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        placed.append(permanent)
    game.start_turn(0)
    game._settle()
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    _fountain, land = placed
    assert counters_on(land, "flood") == 1, game.log[-6:]
    return game, land


def _tap(game, land, colour) -> dict:
    """Tap *land* for *colour* from an empty pool; the pool it leaves, after
    whatever the tap triggered has resolved."""
    pool = game.players[0].mana_pool
    for symbol in list(pool):
        pool[symbol] = 0
    land.tapped = False
    game.tap_land_for_mana(
        0, land.card.name, chosen_color=colour, permanent_id=land.permanent_id,
    )
    resolve_stack(game)
    return {symbol: count for symbol, count in pool.items() if count}


@pytest.mark.cr("305.7")
def test_a_flooded_forest_makes_only_blue(set_pool):
    game, forest = _flooded(set_pool, set_pool("LEA")["Forest"])

    assert forest.basic_land_types == ("island",)
    assert forest.effective_produced_mana == ("U",)
    assert _tap(game, forest, "G") == {"U": 1}
    assert _tap(game, forest, "U") == {"U": 1}


@pytest.mark.cr("305.7", "611.2b")
def test_a_flooded_city_of_brass_loses_its_trigger_and_its_any_colour(set_pool):
    """Its printed "Whenever this land becomes tapped, it deals 1 damage to
    you." and "{T}: Add one mana of any color." are gone: tapped, it makes
    {U} and deals nothing. The counter removed, both are back."""
    game, city = _flooded(set_pool, set_pool("ARN")["City of Brass"])

    assert city.effective_card.oracle_text == ""
    assert city.effective_produced_mana == ("U",)
    assert game.usable_abilities_of(city) == []
    assert _tap(game, city, "R") == {"U": 1}
    assert game.players[0].life == 20

    remove_counters(city, "flood", 1)
    game._recompute_continuous_effects()

    assert city.basic_land_types == ()
    assert "U" in city.effective_produced_mana and "R" in city.effective_produced_mana
    assert _tap(game, city, "R") == {"R": 1}
    assert game.players[0].life == 19


@pytest.mark.cr("305.7")
def test_a_flooded_strip_mine_cannot_be_activated(set_pool):
    """"{T}, Sacrifice this land: Destroy target land." is a printed ability
    the flooded land no longer has: the activation is refused, the land stays
    and the target is untouched."""
    game, mine = _flooded(set_pool, set_pool("ATQ")["Strip Mine"])
    target = Permanent(card=set_pool("LEA")["Plains"])
    game._put_permanent_onto_battlefield(1, target, None)

    refused = game.activate_permanent_ability(
        0, "Strip Mine", permanent_index=game.battlefield_index_of(mine),
        ability_index=1, target_permanent_ids=[target.permanent_id],
    )

    assert not refused.supported
    assert "CR 305.7" in refused.details
    assert game.is_on_battlefield(mine) and game.is_on_battlefield(target)
    assert _tap(game, mine, "C") == {"U": 1}
