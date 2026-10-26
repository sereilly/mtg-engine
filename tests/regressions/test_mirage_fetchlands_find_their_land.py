"""Mirage's five fetchlands find the land they name.

"{T}, Sacrifice this land: Search your library for an Island or Swamp card,
put it onto the battlefield, then shuffle." (Bad River; Flood Plain,
Grasslands, Mountain Valley and Rocky Tar Pit print the other four pairs.) The
union of two land types was AND'd by the search predicate — a card that is
both, which no basic is — so each sacrificed itself and found nothing while
reporting supported. See ``tests/engine/test_search_subtype_unions.py``.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from tests.helpers import resolve_stack

_FETCHES = {
    "Bad River": ("Island", "Swamp"),
    "Flood Plain": ("Plains", "Island"),
    "Grasslands": ("Forest", "Plains"),
    "Mountain Valley": ("Mountain", "Forest"),
    "Rocky Tar Pit": ("Swamp", "Mountain"),
}


@pytest.fixture(scope="module")
def mirage():
    return {card.name: card for card in load_cards(manifest_set_path("MIR"))}


@pytest.mark.parametrize("fetch", sorted(_FETCHES))
def test_a_mirage_fetchland_puts_the_second_named_type_onto_the_battlefield(mirage, fetch):
    wanted = _FETCHES[fetch][1]
    others = [
        name for name in ("Plains", "Island", "Swamp", "Mountain", "Forest")
        if name not in _FETCHES[fetch]
    ]
    me = PlayerState(name="P1", library=[mirage[name] for name in (*others, wanted)])
    game = Game(players=[me, PlayerState(name="P2", library=[mirage["Island"]] * 3)])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    land = Permanent(card=mirage[fetch])
    game._put_permanent_onto_battlefield(0, land, None)
    game._sync_control()
    assert land.tapped, "this land enters tapped"
    land.tapped = False  # a later turn's untap step

    assert game.activate_permanent_ability(0, fetch).supported
    resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert [p.card.name for p in game.controlled_by(0)] == [wanted]
    assert [card.name for card in me.graveyard] == [fetch]
    assert sorted(card.name for card in me.library) == sorted(others)
