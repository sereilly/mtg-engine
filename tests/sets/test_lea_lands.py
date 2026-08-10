"""Per-card tests for Limited Edition Alpha's land cards.

Split out of the 9,400-line test_lea_cards.py by the type of the
card each test names. See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState, classify_card, load_cards
from engine.models import CardDefinition, Permanent
from tests.helpers import (
    _mk_card,
    _mk_creature_card,
    _pass_priority,
    _resolve_top_stack,
    client,
    _get,
)
from tests.sets.lea_helpers import (
    _forest,
    _grizzly,
    _island,
    _mountain,
    _plains,
    _start_session_with_p0_graveyard,
    _swamp,
)


def test_gaeas_liege_activation_turns_land_into_forest(all_cards):
    liege = _get(all_cards, "Gaea's Liege")
    plains = _get(all_cards, "Plains")
    forest = _get(all_cards, "Forest")

    # Gaea's Liege's P/T equals the Forests its controller controls, so give P1 a
    # Forest — otherwise it is 0/0 and dies as a state-based action (and its land
    # effect would end with it).
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=liege), Permanent(card=forest)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=plains)])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Gaea's Liege", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].changed_land_types == ("forest",)


def test_badlands_produces_black_or_red_mana(all_cards):
    # Badlands oracle text: ({T}: Add {B} or {R}.)
    # It is a dual land — Swamp Mountain that can produce either B or R.
    badlands = _get(all_cards, "Badlands")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=badlands)])
    game = Game(players=[p1])

    ok = game.tap_land_for_mana(0, "Badlands", chosen_color="B")
    assert ok
    assert p1.mana_pool["B"] == 1
    assert p1.mana_pool["R"] == 0

    # Reset for second tap test
    p1.battlefield[0].tapped = False
    p1.mana_pool["B"] = 0

    ok = game.tap_land_for_mana(0, "Badlands", chosen_color="R")
    assert ok
    assert p1.mana_pool["R"] == 1
    assert p1.mana_pool["B"] == 0


def test_bayou_taps_for_black_mana(all_cards):
    bayou = _get(all_cards, "Bayou")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=bayou)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    ok = game.tap_land_for_mana(0, "Bayou", chosen_color="B")

    assert ok
    assert p1.mana_pool["B"] == 1
    assert p1.battlefield[0].tapped is True


def test_bayou_taps_for_green_mana(all_cards):
    bayou = _get(all_cards, "Bayou")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=bayou)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    ok = game.tap_land_for_mana(0, "Bayou", chosen_color="G")

    assert ok
    assert p1.mana_pool["G"] == 1


def test_plateau_taps_for_red_or_white(all_cards):
    plateau = _get(all_cards, "Plateau")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=plateau)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    ok_r = game.tap_land_for_mana(0, "Plateau", "R")
    assert ok_r
    assert p1.mana_pool["R"] == 1

    p1.battlefield[0].tapped = False
    ok_w = game.tap_land_for_mana(0, "Plateau", "W")
    assert ok_w
    assert p1.mana_pool["W"] == 1


def test_savannah_taps_for_green_mana(all_cards):
    savannah = _get(all_cards, "Savannah")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=savannah)])
    game = Game(players=[p1, PlayerState(name="P2")])

    ok = game.tap_land_for_mana(0, "Savannah")

    assert ok
    assert p1.mana_pool["G"] == 1


def test_scrubland_taps_for_white_mana(all_cards):
    scrubland = _get(all_cards, "Scrubland")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=scrubland)])
    game = Game(players=[p1, PlayerState(name="P2")])

    ok = game.tap_land_for_mana(0, "Scrubland", "W")

    assert ok
    assert p1.mana_pool.get("W", 0) == 1


def test_scrubland_taps_for_black_mana(all_cards):
    scrubland = _get(all_cards, "Scrubland")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=scrubland)])
    game = Game(players=[p1, PlayerState(name="P2")])

    ok = game.tap_land_for_mana(0, "Scrubland", "B")

    assert ok
    assert p1.mana_pool.get("B", 0) == 1


def test_taiga_taps_for_red_mana(all_cards):
    taiga = _get(all_cards, "Taiga")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=taiga)])
    game = Game(players=[p1, PlayerState(name="P2")])

    ok = game.tap_land_for_mana(0, "Taiga", "R")

    assert ok
    assert p1.mana_pool.get("R", 0) == 1


def test_taiga_taps_for_green_mana(all_cards):
    taiga = _get(all_cards, "Taiga")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=taiga)])
    game = Game(players=[p1, PlayerState(name="P2")])

    ok = game.tap_land_for_mana(0, "Taiga", "G")

    assert ok
    assert p1.mana_pool.get("G", 0) == 1


def test_tropical_island_taps_for_green_mana(all_cards):
    tropical = _get(all_cards, "Tropical Island")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=tropical)])
    game = Game(players=[p1, PlayerState(name="P2")])

    ok = game.tap_land_for_mana(0, "Tropical Island", "G")

    assert ok
    assert p1.mana_pool.get("G", 0) == 1


def test_tropical_island_taps_for_blue_mana(all_cards):
    tropical = _get(all_cards, "Tropical Island")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=tropical)])
    game = Game(players=[p1, PlayerState(name="P2")])

    ok = game.tap_land_for_mana(0, "Tropical Island", "U")

    assert ok
    assert p1.mana_pool.get("U", 0) == 1


def test_tundra_taps_for_white_mana(all_cards):
    tundra = _get(all_cards, "Tundra")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=tundra)])
    game = Game(players=[p1, PlayerState(name="P2")])

    ok = game.tap_land_for_mana(0, "Tundra", "W")

    assert ok
    assert p1.mana_pool.get("W", 0) == 1


def test_tundra_taps_for_blue_mana(all_cards):
    tundra = _get(all_cards, "Tundra")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=tundra)])
    game = Game(players=[p1, PlayerState(name="P2")])

    ok = game.tap_land_for_mana(0, "Tundra", "U")

    assert ok
    assert p1.mana_pool.get("U", 0) == 1


def test_underground_sea_taps_for_blue_mana(all_cards):
    underground_sea = _get(all_cards, "Underground Sea")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=underground_sea)])
    game = Game(players=[p1, PlayerState(name="P2")])

    ok = game.tap_land_for_mana(0, "Underground Sea", "U")

    assert ok
    assert p1.mana_pool.get("U", 0) == 1


def test_underground_sea_taps_for_black_mana(all_cards):
    underground_sea = _get(all_cards, "Underground Sea")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=underground_sea)])
    game = Game(players=[p1, PlayerState(name="P2")])

    ok = game.tap_land_for_mana(0, "Underground Sea", "B")

    assert ok
    assert p1.mana_pool.get("B", 0) == 1


def test_gaeas_liege_pt_equals_forests_controlled_when_not_attacking(all_cards):
    liege = _get(all_cards, "Gaea's Liege")
    forest = _get(all_cards, "Forest")
    liege_perm = Permanent(card=liege)
    p1 = PlayerState(
        name="P1",
        battlefield=[liege_perm, Permanent(card=forest), Permanent(card=forest)],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game._refresh_dynamic_creatures()

    assert liege_perm.effective_power == 2
    assert liege_perm.effective_toughness == 2


def test_gaeas_liege_pt_equals_defenders_forests_when_attacking(all_cards):
    liege = _get(all_cards, "Gaea's Liege")
    forest = _get(all_cards, "Forest")
    liege_perm = Permanent(card=liege)
    p1 = PlayerState(name="P1", battlefield=[liege_perm, Permanent(card=forest)])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=forest), Permanent(card=forest), Permanent(card=forest)],
    )
    game = Game(players=[p1, p2])

    liege_perm.attacking = True
    liege_perm.defending_player_index = 1
    game._refresh_dynamic_creatures()

    assert liege_perm.effective_power == 3
    assert liege_perm.effective_toughness == 3


def test_gaeas_liege_dies_with_zero_forests(all_cards):
    # Regression: with 0 Forests its toughness is 0, so it dies as a state-based action.
    liege = _get(all_cards, "Gaea's Liege")
    plains = _get(all_cards, "Plains")
    p1 = PlayerState(name="P1", hand=[liege])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=plains)])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.cast_from_hand(0, "Gaea's Liege")
    game.check_state_based_actions()

    assert not any(p.card.name == "Gaea's Liege" for p in p1.battlefield)
    assert any(c.name == "Gaea's Liege" for c in p1.graveyard)
