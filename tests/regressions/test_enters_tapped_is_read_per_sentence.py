""""This land enters tapped." is one sentence, and the "unless" was another's.

The entry state performs an unconditional "enters tapped" and leaves the
conditional one ("…enters tapped **unless** you control two or fewer other
lands") to whoever reads its condition. Which of the two a card prints was
decided by looking for the word "unless" anywhere in its text — so a card
whose *next* sentence said "unless" never entered tapped:

    This land enters tapped.
    When this land enters, sacrifice it unless you return an untapped Plains
    you control to its owner's hand.

Karoo, Coral Atoll, Dormant Volcano, Everglades and Jungle Basin — the whole
Visions cycle — came into play untapped. Found by the CR 305.7 census, which
used Karoo as its control for "a land that enters tapped" and watched it not.

The sweep is every land in the pool that prints an unconditional "enters
tapped" sentence; measured on the tree before this file, 5 of 73 entered
untapped.
"""

from __future__ import annotations

import re

import pytest

from engine import Game, PlayerState
from engine.models import Permanent

_KAROO_CYCLE = ("Coral Atoll", "Dormant Volcano", "Everglades", "Jungle Basin", "Karoo")


def _enters_tapped_unconditionally(card) -> bool:
    return any(
        "enters tapped" in sentence.lower() and "unless" not in sentence.lower()
        for sentence in re.split(r"[.\n]", card.oracle_text or "")
    )


def _enter(catalog_by_name, name: str):
    game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    # One of each basic, so a land that is sacrificed "unless you return" one
    # has one to return and stays to be looked at.
    for basic in ("Plains", "Island", "Swamp", "Mountain", "Forest"):
        game._put_permanent_onto_battlefield(
            0, Permanent(card=catalog_by_name[basic]), None
        )
    land = Permanent(card=catalog_by_name[name])
    game._put_permanent_onto_battlefield(0, land, None)
    return game, land


def test_every_land_that_says_it_enters_tapped_does(catalog, catalog_by_name):
    lands = [
        card for card in catalog
        if card.primary_type == "land" and _enters_tapped_unconditionally(card)
    ]
    untapped = []
    for card in lands:
        _game, land = _enter(catalog_by_name, card.name)
        if not land.tapped:
            untapped.append(card.name)

    assert len(lands) >= 70, f"only {len(lands)} lands examined"
    assert set(_KAROO_CYCLE) <= {card.name for card in lands}
    assert untapped == []


@pytest.mark.parametrize("name", _KAROO_CYCLE)
def test_a_karoo_land_enters_tapped_and_still_asks_for_its_basic(
    catalog_by_name, name
):
    from tests.helpers import resolve_stack

    game, land = _enter(catalog_by_name, name)

    assert land.tapped, "This land enters tapped."
    # The other sentence is its own: the trigger is on the stack, and the land
    # stays because an untapped basic of the right type went back to hand.
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    assert game.is_on_battlefield(land)
    assert len(game.players[0].hand) == 1
    assert len(list(game.controlled_by(0))) == 5
