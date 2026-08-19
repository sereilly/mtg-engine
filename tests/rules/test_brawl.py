"""Tests for Magic: The Gathering Comprehensive Rules 903.12 — the Brawl option.

CR 903.12a: "Brawl games use the normal rules for the Commander variant with the
following modifications." So this file tests the **modifications** — the eight
sentences of 903.12 — plus, once, that the unmodified half really is shared. The
rest of CR 903 is ``test_commander.py``; testing it again here would be testing
one implementation twice and would hide which of the two a change broke.

The modifications, in the rule's own order:

* 903.12b — decks are usually built from Standard, which is the format's own
  legality list;
* 903.12c — a planeswalker may be a commander;
* 903.12d — exactly 60 cards;
* 903.12e — a colourless commander admits basics of one chosen type;
* 903.12f — 25 life two-player, 30 multiplayer;
* 903.12g — the first mulligan is free in *any* Brawl game;
* 903.12h — no 21-damage commander loss.
"""

from __future__ import annotations

import random
from unittest.mock import patch

import pytest

from engine import Game, PlayerState
from engine.commander import (
    BRAWL,
    COMMANDER,
    LETHAL_COMMANDER_DAMAGE,
    can_be_commander,
    deck_card_problem,
    deck_size,
    free_first_mulligan,
    starting_life,
    uses_commander_damage,
)
from engine.models import Permanent
from web.deck_legality import FORMATS_BY_KEY, validate_deck


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _brawl_game(pool, *, seats: int = 2, commander: str = "Kaervek, the Spiteful",
                deal: bool = True) -> Game:
    filler = [pool["Mountain"]] * 30
    players = [PlayerState(name=f"P{i + 1}", library=list(filler)) for i in range(seats)]
    game = Game(players=players, commander_variant=BRAWL)
    for seat in range(seats):
        game.designate_commander(seat, pool[commander] if seat == 0 else pool["Azusa, Lost but Seeking"])
    if deal:
        game.deal_opening_hands(0)
    return game


def _catalog_entry(name, *, type_line="Creature — Test", mana_cost="", oracle_text="",
                   produced_mana=(), key="brawl"):
    return {
        "name": name, "type_line": type_line, "mana_cost": mana_cost,
        "oracle_text": oracle_text, "produced_mana": list(produced_mana),
        "legalities": {key: "legal"},
    }


def _catalog(*entries):
    return {entry["name"].casefold(): entry for entry in entries}


def _deck(*pairs):
    return [{"name": name, "count": count} for name, count in pairs]


# ---------------------------------------------------------------------------
# 903.12a — Brawl is Commander plus modifications
# ---------------------------------------------------------------------------

@pytest.mark.cr("903.12a")
def test_brawl_is_a_commander_game(set_pool):
    """"Brawl is an option for a different style of Commander game." Everything
    CR 903 gives a Commander game, a Brawl game has: the command zone (903.6),
    casting from it (903.8), and the tax (903.8)."""
    pool = set_pool("M21")
    game = _brawl_game(pool)
    kaervek = pool["Kaervek, the Spiteful"]

    assert game.is_commander_game is True
    assert [c.name for c in game.players[0].command_zone] == [kaervek.name]

    assert game.cast_from_hand(0, kaervek.name, from_zone="command").supported is True
    assert [p.card.name for p in game.controlled_by(0)] == [kaervek.name]
    assert game.commander_tax(0, kaervek) == 2


@pytest.mark.cr("903.12a", "903.9a")
def test_brawl_returns_a_dead_commander_to_the_command_zone(set_pool):
    """903.9a is not one of 903.12's modifications, so it applies unchanged."""
    pool = set_pool("M21")
    game = _brawl_game(pool)
    kaervek = pool["Kaervek, the Spiteful"]
    game.players[0].command_zone.clear()
    game.players[0].graveyard.append(kaervek)

    game.check_state_based_actions()

    assert [c.name for c in game.players[0].command_zone] == [kaervek.name]


# ---------------------------------------------------------------------------
# 903.12b — Standard-ish card pool
# ---------------------------------------------------------------------------

@pytest.mark.cr("903.12b")
def test_brawl_has_its_own_legality_list():
    """"Brawl decks are usually constructed using cards from the Standard
    format." The engine reads per-card legality from the card's own list rather
    than deriving it from Standard, so the format carries its own key — a card
    legal in Standard but banned in Brawl is banned in Brawl."""
    fmt = FORMATS_BY_KEY["brawl"]
    assert fmt["scryfall_key"] == "brawl"

    catalog = _catalog(
        _catalog_entry("Test Legend", type_line="Legendary Creature — Test", mana_cost="{R}"),
        _catalog_entry("Mountain", type_line="Basic Land — Mountain", produced_mana=("R",)),
        {"name": "Test Banned", "type_line": "Instant", "mana_cost": "{R}",
         "oracle_text": "", "produced_mana": [],
         "legalities": {"brawl": "banned", "standard": "legal"}},
    )
    res = validate_deck(
        _deck(("Test Banned", 1), ("Mountain", 58)), "brawl", catalog,
        commander=_deck(("Test Legend", 1)),
    )
    assert any("Test Banned" in p and "banned" in p for p in res["problems"])


# ---------------------------------------------------------------------------
# 903.12c — a planeswalker may be a commander
# ---------------------------------------------------------------------------

@pytest.mark.cr("903.12c")
def test_a_planeswalker_may_be_a_brawl_commander(set_pool):
    """"That card must be either (a) a creature card, (b) a planeswalker card,
    (c) a Vehicle card, or (d) a Spacecraft card…" — (b) is what 903.3 lacks."""
    pool = set_pool("M21")
    garruk = pool["Garruk, Unleashed"]

    assert can_be_commander(garruk, BRAWL) is True
    assert can_be_commander(garruk, COMMANDER) is False


@pytest.mark.cr("903.12c")
def test_a_planeswalker_commander_starts_in_the_command_zone(set_pool):
    pool = set_pool("M21")
    game = _brawl_game(pool, commander="Garruk, Unleashed")

    assert [c.name for c in game.players[0].command_zone] == ["Garruk, Unleashed"]


@pytest.mark.cr("903.12c")
def test_a_planeswalker_commander_may_be_cast_from_the_command_zone(set_pool):
    pool = set_pool("M21")
    game = _brawl_game(pool, commander="Garruk, Unleashed")

    result = game.cast_from_hand(0, "Garruk, Unleashed", from_zone="command")

    assert result.supported is True
    assert [p.card.name for p in game.controlled_by(0)] == ["Garruk, Unleashed"]


@pytest.mark.cr("903.12c")
def test_the_deck_validator_admits_a_planeswalker_commander_only_in_brawl():
    walker = _catalog_entry(
        "Test Walker", type_line="Legendary Planeswalker — Test", mana_cost="{2}{G}",
        key="brawl",
    )
    walker["legalities"]["commander"] = "legal"
    catalog = _catalog(
        walker,
        _catalog_entry("Forest", type_line="Basic Land — Forest", produced_mana=("G",),
                       key="brawl"),
    )
    catalog["forest"]["legalities"]["commander"] = "legal"

    brawl = validate_deck(
        _deck(("Forest", 59)), "brawl", catalog, commander=_deck(("Test Walker", 1))
    )
    assert brawl["legal"] is True, brawl["problems"]

    commander = validate_deck(
        _deck(("Forest", 99)), "commander", catalog, commander=_deck(("Test Walker", 1))
    )
    assert any("not a legendary creature" in p for p in commander["problems"])


# ---------------------------------------------------------------------------
# 903.12d — exactly 60 cards
# ---------------------------------------------------------------------------

@pytest.mark.cr("903.12d")
def test_a_brawl_deck_is_exactly_sixty_cards():
    """"A player's deck must contain exactly 60 cards, including its commander.
    In other words, the minimum deck size and the maximum deck size are both
    60.\""""
    assert deck_size(BRAWL) == 60

    catalog = _catalog(
        _catalog_entry("Test Legend", type_line="Legendary Creature — Test", mana_cost="{R}"),
        _catalog_entry("Mountain", type_line="Basic Land — Mountain", produced_mana=("R",)),
    )
    commander = _deck(("Test Legend", 1))

    short = validate_deck(_deck(("Mountain", 58)), "brawl", catalog, commander=commander)
    assert any("requires at least 59" in p for p in short["problems"])

    long = validate_deck(_deck(("Mountain", 60)), "brawl", catalog, commander=commander)
    assert any("at most 59" in p for p in long["problems"])

    exact = validate_deck(_deck(("Mountain", 59)), "brawl", catalog, commander=commander)
    assert exact["legal"] is True, exact["problems"]


@pytest.mark.cr("903.12d", "903.5a")
def test_brawl_and_commander_deck_sizes_differ():
    assert deck_size(BRAWL) == 60
    assert deck_size(COMMANDER) == 100


# ---------------------------------------------------------------------------
# 903.12e — a colourless commander's basic lands
# ---------------------------------------------------------------------------

@pytest.mark.cr("903.12e")
def test_a_colourless_brawl_commander_admits_one_basic_land_type():
    """"If a player's commander has no colors in its color identity, that
    player's deck may contain any number of basic lands of one basic land type
    of their choice. This is an exception to rule 903.5d.\""""
    forest = _catalog_entry("Forest", type_line="Basic Land — Forest", produced_mana=("G",))

    assert deck_card_problem(forest, frozenset(), BRAWL, brawl_basic_type="forest") is None
    # …and the exception is Brawl's alone.
    assert deck_card_problem(forest, frozenset(), COMMANDER, brawl_basic_type="forest") is not None


@pytest.mark.cr("903.12e")
def test_the_chosen_basic_land_type_is_only_one():
    """"…of **one** basic land type of their choice." A second type is not
    covered by the exception, so 903.5d refuses it."""
    island = _catalog_entry("Island", type_line="Basic Land — Island", produced_mana=("U",))

    assert deck_card_problem(island, frozenset(), BRAWL, brawl_basic_type="forest") is not None


@pytest.mark.cr("903.12e")
def test_a_colourless_brawl_deck_with_one_basic_type_is_legal():
    catalog = _catalog(
        _catalog_entry("Test Colossus", type_line="Legendary Creature — Golem", mana_cost="{6}"),
        _catalog_entry("Forest", type_line="Basic Land — Forest", produced_mana=("G",)),
    )
    res = validate_deck(
        _deck(("Forest", 59)), "brawl", catalog,
        commander=_deck(("Test Colossus", 1)),
    )
    assert res["legal"] is True, res["problems"]
    assert res["commander_identity"] == ""


@pytest.mark.cr("903.12e")
def test_a_colourless_brawl_deck_with_two_basic_types_is_illegal():
    """With two basic types in the deck the "one basic land type of their
    choice" has not been exercised, and 903.5d applies to both."""
    catalog = _catalog(
        _catalog_entry("Test Colossus", type_line="Legendary Creature — Golem", mana_cost="{6}"),
        _catalog_entry("Forest", type_line="Basic Land — Forest", produced_mana=("G",)),
        _catalog_entry("Island", type_line="Basic Land — Island", produced_mana=("U",)),
    )
    res = validate_deck(
        _deck(("Forest", 30), ("Island", 29)), "brawl", catalog,
        commander=_deck(("Test Colossus", 1)),
    )
    assert res["legal"] is False
    assert any("903.5d" in p for p in res["problems"])


@pytest.mark.cr("903.12e", "903.5c")
def test_the_exception_does_not_reach_a_coloured_brawl_commander():
    """The exception is for a commander with *no* colours; a green commander's
    deck is judged by 903.5c/d as any Commander deck is."""
    island = _catalog_entry("Island", type_line="Basic Land — Island", produced_mana=("U",))
    problem = deck_card_problem(island, frozenset("G"), BRAWL, brawl_basic_type="island")
    assert problem is not None and "903.5d" in problem


# ---------------------------------------------------------------------------
# 903.12f — starting life
# ---------------------------------------------------------------------------

@pytest.mark.cr("903.12f")
def test_two_player_brawl_starts_at_twenty_five_life(set_pool):
    """"In a two-player Brawl game, each player's starting life total is 25.\""""
    game = _brawl_game(set_pool("M21"), seats=2)
    assert [p.life for p in game.players] == [25, 25]


@pytest.mark.cr("903.12f")
def test_multiplayer_brawl_starts_at_thirty_life(set_pool):
    """"In a multiplayer Brawl game, each player's starting life total is 30.\""""
    game = _brawl_game(set_pool("M21"), seats=3)
    assert [p.life for p in game.players] == [30, 30, 30]


@pytest.mark.cr("903.12f", "903.7")
def test_brawl_life_totals_differ_from_commanders():
    assert starting_life(BRAWL, 2) == 25
    assert starting_life(BRAWL, 3) == 30
    assert starting_life(BRAWL, 4) == 30
    assert starting_life(COMMANDER, 2) == 40
    assert starting_life(COMMANDER, 4) == 40


# ---------------------------------------------------------------------------
# 903.12g — the free first mulligan
# ---------------------------------------------------------------------------

@pytest.mark.cr("903.12g")
def test_the_first_brawl_mulligan_is_free_in_a_two_player_game(set_pool):
    """"In any Brawl game, the first mulligan a player takes doesn't count
    toward the number of cards that player will put on the bottom of their
    library or the number of mulligans that player may take.\""""
    game = _brawl_game(set_pool("M21"), seats=2)

    with patch.object(random, "shuffle", lambda seq: None):
        assert game.take_mulligan(0) is True
    assert len(game.players[0].hand) == 7        # nothing bottomed
    assert game.mulligan_effective_count(0) == 0

    with patch.object(random, "shuffle", lambda seq: None):
        assert game.take_mulligan(0) is True
    assert len(game.players[0].hand) == 6        # the second costs one
    assert game.mulligan_effective_count(0) == 1


@pytest.mark.cr("903.12g", "103.5c")
def test_a_two_player_commander_game_has_no_free_mulligan(set_pool):
    """The contrast that makes 903.12g a modification: CR 103.5c gives the free
    first mulligan to a multiplayer game *and* to any Brawl game, so a
    two-player Commander game does not get one."""
    pool = set_pool("M21")
    players = [PlayerState(name=f"P{i + 1}", library=[pool["Mountain"]] * 30) for i in range(2)]
    game = Game(players=players, commander_variant=COMMANDER)
    game.designate_commander(0, pool["Kaervek, the Spiteful"])
    game.deal_opening_hands(0)

    with patch.object(random, "shuffle", lambda seq: None):
        game.take_mulligan(0)
    assert len(game.players[0].hand) == 6
    assert game.mulligan_effective_count(0) == 1


@pytest.mark.cr("903.12g", "800.6")
def test_the_brawl_and_multiplayer_discounts_do_not_stack(set_pool):
    """Both rules describe the same one mulligan, so a multiplayer Brawl game
    still discounts exactly one — not two."""
    game = _brawl_game(set_pool("M21"), seats=3)

    with patch.object(random, "shuffle", lambda seq: None):
        game.take_mulligan(0)
        game.take_mulligan(0)

    assert game.mulligan_effective_count(0) == 1
    assert len(game.players[0].hand) == 6


@pytest.mark.cr("903.12g")
def test_free_first_mulligan_is_a_brawl_property():
    assert free_first_mulligan(BRAWL) is True
    assert free_first_mulligan(COMMANDER) is False
    assert free_first_mulligan(None) is False


# ---------------------------------------------------------------------------
# 903.12h — no commander damage
# ---------------------------------------------------------------------------

@pytest.mark.cr("903.12h", "704.6c")
def test_brawl_does_not_use_the_twenty_one_damage_loss(set_pool):
    """"Brawl games do not use the state-based action described in rule 704.6c,
    which causes a player to lose the game if they've been dealt 21 or more
    combat damage by a commander.\""""
    pool = set_pool("M21")
    game = _brawl_game(pool)
    commander = Permanent(card=pool["Kaervek, the Spiteful"])
    game.players[0].battlefield.append(commander)
    game._sync_control()

    for _ in range(10):
        game.record_commander_combat_damage(game.players[1], commander, 5)
    game.check_state_based_actions()

    assert game.players[1].lost is False


@pytest.mark.cr("903.12h")
def test_brawl_does_not_even_tally_commander_damage(set_pool):
    """Nothing reads the tally in a Brawl game, so nothing keeps it — a number
    kept but never consulted is a claim that the rule is only half off."""
    pool = set_pool("M21")
    game = _brawl_game(pool)
    commander = Permanent(card=pool["Kaervek, the Spiteful"])
    game.players[0].battlefield.append(commander)
    game._sync_control()

    game.record_commander_combat_damage(game.players[1], commander, 21)

    assert game.players[1].commander_damage_taken == {}
    assert game.commander_damage_dealt(1, 0, commander.card.name) == 0


@pytest.mark.cr("903.12h", "903.10a")
def test_commander_damage_is_a_commander_only_rule():
    assert uses_commander_damage(COMMANDER) is True
    assert uses_commander_damage(BRAWL) is False


@pytest.mark.cr("903.12h")
def test_a_brawl_player_still_loses_to_zero_life(set_pool):
    """903.12h switches off one state-based action, not the ordinary ones: 21
    combat damage from a commander is survivable in Brawl only because the life
    total (CR 704.5a) is what ends the game."""
    pool = set_pool("M21")
    game = _brawl_game(pool)
    commander = Permanent(card=pool["Kaervek, the Spiteful"])
    game.players[0].battlefield.append(commander)
    game._sync_control()

    game.record_commander_combat_damage(game.players[1], commander, LETHAL_COMMANDER_DAMAGE)
    game.players[1].life = 0
    game.check_state_based_actions()

    assert game.players[1].lost is True
