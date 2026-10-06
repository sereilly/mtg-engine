"""Regression: "one additional mana of any type **that land produced**" adds
what the land made, not what its tapper asked for.

Mana Flare, Overabundance and Winter's Night each print that clause. The tap
seam (``Game.tap_land_for_mana``) carried one symbol to their inline
resolution: the colour the seat *asked* the land for, which is what a land
that offers a choice then makes. For a land whose mana ability compiles to
something else it is not — and the request defaults to green. A Mishra's
Factory asked for {G} made its {C}, and the Flare added a {G}: a mana of any
colour its tapper cared to name, from every land in the pool whose ability
makes colourless (Ancient Tomb, the painlands' first ability, every utility
land) and from every land asked for a colour it does not make.

Found while extending the castable highlight to count these triggers
(``tests/engine/test_castable_highlight_counts_every_tap.py``), whose truth is
found by tapping.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent

_CARDS = {card.name: card for card in load_catalog()}


def _board(*names):
    game = Game(players=[
        PlayerState(name=f"P{seat}", library=[_CARDS["Island"]] * 12)
        for seat in range(2)
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = "precombat_main"
    game.current_step = "precombat_main"
    permanents = []
    for name in names:
        permanent = Permanent(card=_CARDS[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        permanent.tapped = False
        permanents.append(permanent)
    game._recompute_continuous_effects()
    return game, permanents


def _pool(game) -> dict:
    return {symbol: amount for symbol, amount in game.players[0].mana_pool.items() if amount}


@pytest.mark.parametrize("adder", ["Mana Flare", "Overabundance"])
@pytest.mark.parametrize("land,asked,made", [
    # A land that makes colourless, asked (by default) for green.
    ("Mishra's Factory", "G", {"C": 2}),
    ("Ancient Tomb", "G", {"C": 3}),
    # A painland's first ability, asked for the colour of its second.
    ("Karplusan Forest", "R", {"C": 2}),
    # Lands that make what they are asked for are as they were.
    ("Forest", "G", {"G": 2}),
    ("Tropical Island", "U", {"U": 2}),
    ("City of Brass", "W", {"W": 2}),
])
def test_the_extra_mana_is_of_a_type_the_land_made(adder, land, asked, made):
    game, (_adder, permanent) = _board(adder, land)

    assert game.tap_land_for_mana(0, land, asked, permanent_id=permanent.permanent_id)
    assert _pool(game) == made


def test_a_fixed_adder_is_not_touched():
    """"…adds an additional {R}" names its symbol and never read the land's."""
    game, (_gauntlet, mountain) = _board("Gauntlet of Might", "Mountain")
    assert game.tap_land_for_mana(0, "Mountain", "R", permanent_id=mountain.permanent_id)
    assert _pool(game) == {"R": 2}
