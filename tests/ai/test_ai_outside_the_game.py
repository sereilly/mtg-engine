"""The AI and cards from outside the game (the Judgment Wishes, CR 400.11).

Every simulated seat is dealt a sideboard (``ai_simulator.limited_sideboard``):
CR 100.4b — "In limited play involving individual players, all cards in a
player's card pool not included in their deck are in that player's
sideboard" — over the pool the deck was built from, the whole set but its
basic lands. Before JUD's wave 2 no seat had one, so a Wish had nothing to
bring in, the rehearsal read its cast as moving nothing, and no simulated game
ever cast one.

What this file holds: the deal (the leftovers of the deck, with no randomness
spent, so every deck is the one it was); the zone-conservation invariant
counting a sideboard as the reservoir a card comes in from (CR 400.11b); the
policy casting a Wish when there is something outside the game for it and not
when there is nothing; and a seeded run in which a Wish brings a card in.
"""

from __future__ import annotations

import random

import pytest

from engine import Game, PlayerState
from engine.ai_policy import choose_cast_action
from engine.ai_simulator import (
    _basic_land_pool,
    _zone_counter,
    build_limited_deck,
    limited_sideboard,
    run_ai_simulation,
)
from engine.card_loader import load_cards, manifest_set_path
from engine.models import Permanent
from tests.helpers import CARDS_BY_NAME as _C

_WISHES = ("Burning Wish", "Cunning Wish", "Death Wish", "Golden Wish", "Living Wish")


def _jud_pool() -> dict:
    return {
        card.name: card
        for card in load_cards(manifest_set_path("JUD", include_measured=True))
    }


def test_a_card_brought_in_from_outside_the_game_is_not_a_card_starting_to_exist():
    """CR 400.11b: the card moved from the sideboard into the game. Counted
    from the game's zones alone it was an "extra" card — fourteen false
    zone-conservation issues in four Judgment games once seats were given a
    sideboard by hand. The sideboard is the reservoir, so the count before and
    after the move is the same count."""
    game = Game(players=[
        PlayerState(name="A", library=[_C["Island"]] * 2,
                    sideboard=[_C["Lightning Bolt"], _C["Stone Rain"]]),
        PlayerState(name="B", library=[_C["Island"]] * 2),
    ])
    before = _zone_counter(game)
    assert game.bring_card_from_outside_game(0, 1, source_name="a test") is not None
    assert [card.name for card in game.players[0].hand] == ["Stone Rain"]
    assert _zone_counter(game) == before


def test_a_dealt_deck_s_sideboard_is_the_rest_of_its_pool():
    """CR 100.4b over the pool the deck was built from: every card of the set
    but the basic lands (CR 100.2b: "this product and basic land cards") is in
    the deck or in the sideboard, never both and never twice — and dealing it
    draws nothing from either random sequence, so the deck dealt is the deck
    the same seed always dealt."""
    pool = _jud_pool()
    basics = set(_basic_land_pool(pool))
    deck = build_limited_deck(pool, 4242, required=["Burning Wish"])
    state = random.getstate()
    sideboard = limited_sideboard(pool, deck)
    assert random.getstate() == state
    assert build_limited_deck(pool, 4242, required=["Burning Wish"]) == deck

    held = {card.name for card in sideboard}
    played = {card.name for card in deck} - basics
    assert len(held) == len(sideboard), "one copy of each"
    assert not held & played
    assert not held & basics
    assert held | played == set(pool) - basics
    assert "Burning Wish" in played and "Burning Wish" not in held
    # In the order the pool was loaded, so a seed reproduces the positions.
    assert [card.name for card in sideboard] == [
        name for name in pool if name in held
    ]


def _wish_table(sideboard) -> Game:
    """Seat 0 in its precombat main phase with Burning Wish in hand, three
    untapped Mountains and *sideboard* outside the game."""
    game = Game(players=[
        PlayerState(name="A", library=[_C["Mountain"]] * 10,
                    hand=[_jud_pool()["Burning Wish"]], sideboard=list(sideboard)),
        PlayerState(name="B", library=[_C["Mountain"]] * 10),
    ], enforce_mana_costs=True)
    for _ in range(3):
        game._put_permanent_onto_battlefield(0, Permanent(card=_C["Mountain"]), None)
    game.start_turn(0)
    return game


def test_a_wish_is_cast_for_a_card_outside_the_game_and_not_into_nothing():
    """"You may reveal a sorcery card you own from outside the game and put it
    into your hand. Exile Burning Wish." With a Stone Rain in the sideboard the
    cast brings in a card and is proposed; with nothing outside the game it
    only exiles itself — a card traded for nothing, which the rehearsal does
    not propose."""
    empty = _wish_table(())
    chosen = choose_cast_action(empty, 0)
    assert chosen is None or chosen.card_name != "Burning Wish"

    stocked = _wish_table([_C["Stone Rain"], _C["Lightning Bolt"]])
    chosen = choose_cast_action(stocked, 0)
    assert chosen is not None and chosen.card_name == "Burning Wish"


@pytest.mark.full
def test_a_seeded_run_brings_a_card_in_with_a_wish():
    """Every Wish pinned into both decks of a seeded Judgment run, each seat
    with its pool's leftovers outside the game: a Wish is cast and brings a
    card in at least once (a floor of one — that the path was reached), the
    report counts it, no cast is refused and the zone count holds with the
    sideboards in it."""
    report = run_ai_simulation(
        manifest_set_path("JUD", include_measured=True), games=2, seed=606,
        max_turns=12, required_cards=list(_WISHES),
    )
    assert report.games_completed == 2
    assert not report.issues, report.issues
    assert not any(
        name in reason for reason in report.refused_casts for name in _WISHES
    ), report.refused_casts
    assert report.cards_from_outside_game >= 1
    assert any(
        "from outside the game and put it into their hand" in line
        for line in report.log_lines
    )
