"""Per-card tests for Limited Edition Beta (cards/LEB_cards.json) and
Unlimited Edition (cards/2ED_cards.json).

Beta is Alpha's card list plus the two cards accidentally omitted from the
Alpha print run — Circle of Protection: Black and Volcanic Island — and
Unlimited reprints Beta's list unchanged. Everything except those two cards
is already exercised by the LEA suite, so this file covers set composition,
whole-set support, and the two new cards.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.classifier import classify_card
from engine.models import Permanent


# ===========================================================================
# Set composition
# ===========================================================================

def test_beta_is_alpha_plus_its_two_missing_cards(set_cards):
    leb_cards = set_cards("LEB")
    lea_names = {c.name for c in set_cards("LEA")}
    leb_names = {c.name for c in leb_cards}

    assert len(leb_cards) == 292
    assert leb_names - lea_names == {"Circle of Protection: Black", "Volcanic Island"}
    assert lea_names - leb_names == set()


def test_unlimited_matches_beta_card_list(set_cards):
    leb_cards, unlimited_cards = set_cards("LEB"), set_cards("2ED")
    assert len(unlimited_cards) == 292
    assert {c.name for c in unlimited_cards} == {c.name for c in leb_cards}


def test_all_beta_and_unlimited_cards_are_supported(set_cards):
    leb_cards, unlimited_cards = set_cards("LEB"), set_cards("2ED")
    for card in (*leb_cards, *unlimited_cards):
        program = classify_card(card)
        assert program.supported, f"{card.name}: {program.reason}"


# ===========================================================================
# Circle of Protection: Black
# ===========================================================================

def test_circle_of_protection_black_activation_sets_prevention(set_pool):
    cop = set_pool("LEB")["Circle of Protection: Black"]
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=cop)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Circle of Protection: Black", target_player_index=0)

    assert result.supported
    assert p1.color_prevention_shields == ["B"]


# ===========================================================================
# Volcanic Island
# ===========================================================================

def test_volcanic_island_taps_for_blue_mana(set_pool):
    volcanic = set_pool("LEB")["Volcanic Island"]
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=volcanic)])
    game = Game(players=[p1, PlayerState(name="P2")])

    ok = game.tap_land_for_mana(0, "Volcanic Island", "U")

    assert ok
    assert p1.mana_pool.get("U", 0) == 1


def test_volcanic_island_taps_for_red_mana(set_pool):
    volcanic = set_pool("LEB")["Volcanic Island"]
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=volcanic)])
    game = Game(players=[p1, PlayerState(name="P2")])

    ok = game.tap_land_for_mana(0, "Volcanic Island", "R")

    assert ok
    assert p1.mana_pool.get("R", 0) == 1
