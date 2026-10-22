"""A land's own tap door asks an Aura's "its activated abilities can't be
activated" (CR 602.5) — found by Torment's Stupefying Touch, whose ruling
(2016-06-08) reads: "Unlike many similar abilities, Stupefying Touch's last
ability stops mana abilities from being activated."

``Game.land_mana_tap_refusal`` is the second door to a land's mana ability
(CR 106.12: tapping a land for mana *is* activating it). It asked Interdict's
turn-long ban and nothing else, so a land that an effect has made a creature —
a Forest under Living Lands — tapped for mana under an Aura printing the
restriction with no CR 605.1a exception. Volrath's Curse (Stronghold) prints
the same restriction as its second clause and shipped with the same hole.

What this does **not** fix, measured and left in the report: the rest of
``activation_prohibitions.ACTIVATION_PROHIBITIONS`` is not asked at that door
either — City of Solitude ("This stops players from activating mana
abilities.", 2009-10-01) does not stop a Forest tapping on another player's
turn, and Cursed Totem ("…stops players from activating mana abilities of
creatures.", 2021-06-18) does not stop a Living Lands Forest. A basic land has
no compiled ability object for the table's rows to read, which is why it is
not a one-line change.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.aura_attachment import attach_aura
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from tests.helpers import _nosick


def _pool() -> dict:
    found: dict = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            found.setdefault(card.name, card)
    return found


@pytest.mark.parametrize("aura", ["Volrath's Curse", "Stupefying Touch"])
def test_an_aura_that_shuts_off_every_activated_ability_stops_a_land_creature_s_mana(aura):
    pool = _pool()
    forest, other = (_nosick(Permanent(card=pool["Forest"])) for _ in range(2))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[_nosick(Permanent(card=pool["Living Lands"])), forest, other]),
        PlayerState(name="P2"),
    ])
    game._recompute_continuous_effects()
    assert forest.is_creature
    enchantment = Permanent(card=pool[aura])
    game.players[1].battlefield.append(enchantment)
    attach_aura(enchantment, forest)
    game._recompute_continuous_effects()

    assert game.land_mana_tap_refusal(forest) == "aura_activations_forbidden"
    assert not game.tap_land_for_mana(0, "Forest", permanent_id=forest.permanent_id)
    assert not forest.tapped and game.players[0].mana_pool["G"] == 0
    assert game.tap_land_for_mana(0, "Forest", permanent_id=other.permanent_id)
    assert game.players[0].mana_pool["G"] == 1
