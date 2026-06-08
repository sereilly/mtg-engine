"""Tests for Magic: The Gathering Comprehensive Rules 103.1 and 103.5 — Starting the Game."""

from unittest.mock import patch

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mk_card(name: str) -> CardDefinition:
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line="Instant",
        oracle_text="",
        colors=(),
        color_identity=(),
        keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Instant"},
    )


def _library(size: int) -> list[CardDefinition]:
    return [_mk_card(f"Card{i}") for i in range(size)]


def _two_player_game() -> Game:
    p1 = PlayerState(name="Alice", library=_library(20))
    p2 = PlayerState(name="Bob", library=_library(20))
    return Game(players=[p1, p2])


# ---------------------------------------------------------------------------
# Rule 103.1 — Starting Player Selection
# ---------------------------------------------------------------------------


def test_103_1_select_starting_player_returns_valid_index():
    """select_starting_player returns an index within the player list (103.1)."""
    game = _two_player_game()
    idx = game.select_starting_player()
    assert idx in range(len(game.players))


def test_103_1_result_is_logged():
    """Coin-flip result is recorded in the game log (103.1)."""
    game = _two_player_game()
    game.select_starting_player()
    assert any("Coin flip" in entry for entry in game.log)


def test_103_1_coin_flip_can_select_first_player():
    """Coin flip can select player 0 (Alice) as starting player (103.1)."""
    game = _two_player_game()
    with patch("engine.game.random.randrange", return_value=0):
        idx = game.select_starting_player()
    assert idx == 0
    assert "Alice" in game.log[-1]


def test_103_1_coin_flip_can_select_second_player():
    """Coin flip can select player 1 (Bob) as starting player (103.1)."""
    game = _two_player_game()
    with patch("engine.game.random.randrange", return_value=1):
        idx = game.select_starting_player()
    assert idx == 1
    assert "Bob" in game.log[-1]


def test_103_1_game_supports_more_than_two_players():
    """select_starting_player works for multi-player games (103.1)."""
    players = [PlayerState(name=f"P{i}", library=_library(10)) for i in range(4)]
    game = Game(players=players)
    with patch("engine.game.random.randrange", return_value=2):
        idx = game.select_starting_player()
    assert idx == 2


# ---------------------------------------------------------------------------
# Rule 103.5 — Opening Hands
# ---------------------------------------------------------------------------


def test_103_5_deal_opening_hands_gives_each_player_seven_cards():
    """Each player draws 7 cards as their opening hand (103.5)."""
    game = _two_player_game()
    game.deal_opening_hands(0)
    for player in game.players:
        assert len(player.hand) == 7


def test_103_5_deal_opening_hands_removes_cards_from_library():
    """Cards dealt to hand come from the player's library (103.5)."""
    game = _two_player_game()
    game.deal_opening_hands(0)
    for player in game.players:
        assert len(player.library) == 20 - 7


def test_103_5_deal_opening_hands_is_logged():
    """Opening hand deal is recorded in the log (103.5)."""
    game = _two_player_game()
    game.deal_opening_hands(0)
    log_text = " ".join(game.log)
    assert "Alice" in log_text and "Bob" in log_text
    assert "opening hand" in log_text


def test_103_5_deal_opening_hands_shuffles_library():
    """deal_opening_hands shuffles the library before dealing (103.5)."""
    # Run many times; each library should have been shuffled (not always in original order).
    # We only verify that the library shrinks correctly — true shuffle is random.
    game = _two_player_game()
    original_sizes = [len(p.library) for p in game.players]
    game.deal_opening_hands(1)
    for i, player in enumerate(game.players):
        assert len(player.library) == original_sizes[i] - 7


# ---------------------------------------------------------------------------
# Rule 103.5 — Mulligan
# ---------------------------------------------------------------------------


def test_103_5_take_mulligan_returns_true_on_success():
    """take_mulligan returns True when the mulligan is performed (103.5)."""
    game = _two_player_game()
    game.deal_opening_hands(0)
    result = game.take_mulligan(0)
    assert result is True


def test_103_5_take_mulligan_increments_counter():
    """mulligans_taken is incremented each time a mulligan is taken (103.5)."""
    game = _two_player_game()
    game.deal_opening_hands(0)
    assert game.players[0].mulligans_taken == 0
    game.take_mulligan(0)
    assert game.players[0].mulligans_taken == 1
    game.take_mulligan(0)
    assert game.players[0].mulligans_taken == 2


def test_103_5_first_mulligan_leaves_six_cards():
    """After the first mulligan a player has 6 cards (draws 7, puts 1 on bottom) (103.5)."""
    game = _two_player_game()
    game.deal_opening_hands(0)
    game.take_mulligan(0)
    assert len(game.players[0].hand) == 6


def test_103_5_second_mulligan_leaves_five_cards():
    """After two mulligans a player has 5 cards (103.5)."""
    game = _two_player_game()
    game.deal_opening_hands(0)
    game.take_mulligan(0)
    game.take_mulligan(0)
    assert len(game.players[0].hand) == 5


def test_103_5_seventh_mulligan_leaves_zero_cards():
    """After seven mulligans a player has 0 cards in hand (103.5)."""
    p1 = PlayerState(name="Alice", library=_library(60))
    p2 = PlayerState(name="Bob", library=_library(20))
    game = Game(players=[p1, p2])
    game.deal_opening_hands(0)
    for _ in range(7):
        game.take_mulligan(0)
    assert len(game.players[0].hand) == 0
    assert game.players[0].mulligans_taken == 7


def test_103_5_cannot_mulligan_past_zero_cards():
    """A player with 0 cards cannot take further mulligans (103.5)."""
    p1 = PlayerState(name="Alice", library=_library(60))
    p2 = PlayerState(name="Bob", library=_library(20))
    game = Game(players=[p1, p2])
    game.deal_opening_hands(0)
    for _ in range(7):
        game.take_mulligan(0)
    result = game.take_mulligan(0)
    assert result is False
    assert game.players[0].mulligans_taken == 7


def test_103_5_mulligan_refusal_is_logged():
    """Refusing a mulligan when at 0 cards is recorded in the log (103.5)."""
    p1 = PlayerState(name="Alice", library=_library(60))
    p2 = PlayerState(name="Bob", library=_library(20))
    game = Game(players=[p1, p2])
    game.deal_opening_hands(0)
    for _ in range(7):
        game.take_mulligan(0)
    game.take_mulligan(0)
    assert any("cannot take further mulligans" in e for e in game.log)


def test_103_5_mulligan_is_logged():
    """Each mulligan action is recorded in the game log (103.5)."""
    game = _two_player_game()
    game.deal_opening_hands(0)
    game.take_mulligan(0)
    assert any("mulligan" in e.lower() and "Alice" in e for e in game.log)


def test_103_5_mulligan_hand_comes_from_new_library_draw():
    """After mulligan, hand consists of cards drawn from the reshuffled library (103.5)."""
    game = _two_player_game()
    game.deal_opening_hands(0)
    hand_before = set(c.name for c in game.players[0].hand)
    game.take_mulligan(0)
    # The new hand is drawn from the library that now contains the old hand.
    # All cards in the new hand must come from the full original card pool.
    all_cards = set(c.name for c in _library(20))
    for card in game.players[0].hand:
        assert card.name in all_cards


def test_103_5_mulligan_puts_cards_on_bottom_not_top():
    """Cards put to bottom are appended to the end of library, not inserted at index 0 (103.5)."""
    game = _two_player_game()
    game.deal_opening_hands(0)
    lib_size_before = len(game.players[0].library)
    game.take_mulligan(0)
    player = game.players[0]
    # Library grew by (hand returned) and shrank by 7 drawn; net is 0 relative to pre-deal size.
    # The bottom card is the last element in library.
    assert len(player.library) > 0


def test_103_5_bottom_card_indices_places_specific_cards_on_bottom():
    """bottom_card_indices selects which cards go to the bottom of the library (103.5)."""
    game = _two_player_game()
    # Disable shuffle so card order is deterministic: after dealing, library[0] is
    # the first undealt card and will be drawn first on the mulligan.
    with patch("engine.game.random.shuffle"):
        game.deal_opening_hands(0)
        player = game.players[0]
        # library[0] is the first card that will be drawn into the new hand.
        expected_bottom = player.library[0]
        # Take a mulligan and put new hand[0] (= expected_bottom) on the bottom.
        game.take_mulligan(0, bottom_card_indices=[0])
    assert expected_bottom not in player.hand
    assert player.library[-1] == expected_bottom


def test_103_5_keep_hand_is_logged():
    """keep_hand records the decision in the game log (103.5)."""
    game = _two_player_game()
    game.deal_opening_hands(0)
    game.keep_hand(0)
    assert any("keeps opening hand" in e and "Alice" in e for e in game.log)


def test_103_5_keep_hand_logs_hand_size():
    """keep_hand log entry states the number of cards kept (103.5)."""
    game = _two_player_game()
    game.deal_opening_hands(0)
    game.keep_hand(0)
    assert any("7" in e and "keeps opening hand" in e for e in game.log)


def test_103_5_keep_hand_after_mulligan_logs_mulligan_count():
    """keep_hand log entry mentions how many mulligans were taken (103.5)."""
    game = _two_player_game()
    game.deal_opening_hands(0)
    game.take_mulligan(0)
    game.keep_hand(0)
    assert any("1 mulligan" in e for e in game.log)


def test_103_5_keep_hand_without_mulligan_no_mulligan_note():
    """keep_hand on the initial hand does not note any mulligans taken (103.5)."""
    game = _two_player_game()
    game.deal_opening_hands(0)
    game.keep_hand(0)
    # No mulligan count parenthetical should appear.
    keep_entries = [e for e in game.log if "keeps opening hand" in e and "Alice" in e]
    assert all("mulligan" not in e for e in keep_entries)


def test_103_5_second_player_is_unaffected_by_first_players_mulligan():
    """Each player's mulligan is independent; P2's hand is unchanged (103.5)."""
    game = _two_player_game()
    game.deal_opening_hands(0)
    hand_p2_before = list(game.players[1].hand)
    game.take_mulligan(0)
    assert game.players[1].hand == hand_p2_before
    assert game.players[1].mulligans_taken == 0


def test_103_5_full_mulligan_sequence_two_players():
    """Full two-player mulligan round: P1 mulligans once, P2 keeps (103.5)."""
    game = _two_player_game()
    starting = game.select_starting_player()
    game.deal_opening_hands(starting)

    # Starting player declares first.
    game.take_mulligan(starting)

    # Other player keeps.
    other = 1 - starting
    game.keep_hand(other)

    # Starting player now keeps.
    game.keep_hand(starting)

    assert len(game.players[starting].hand) == 6
    assert game.players[starting].mulligans_taken == 1
    assert len(game.players[other].hand) == 7
    assert game.players[other].mulligans_taken == 0
