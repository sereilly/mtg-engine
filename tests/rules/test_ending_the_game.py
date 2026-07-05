"""Tests for Magic: The Gathering Comprehensive Rules Section 104 — Ending the Game."""

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mk_card(name: str, type_line: str, oracle_text: str = "", colors: tuple[str, ...] = ()) -> CardDefinition:
    raw: dict = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw["power"] = "2"
        raw["toughness"] = "2"
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line=type_line,
        oracle_text=oracle_text,
        colors=colors,
        color_identity=colors,
        keywords=(),
        produced_mana=(),
        raw=raw,
    )


def _two_player_game(**kwargs) -> tuple[Game, PlayerState, PlayerState]:
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2], **kwargs)
    return game, p1, p2


# ---------------------------------------------------------------------------
# Rule 104.1 – A game ends immediately when a player wins, when the game is
# a draw, or when the game is restarted.
# ---------------------------------------------------------------------------

def test_104_1_fresh_game_is_not_over():
    """104.1: A newly created game has not ended."""
    game, p1, p2 = _two_player_game()
    assert not game.is_game_over()


def test_104_1_game_over_when_player_wins():
    """104.1: The game is over once a player has won."""
    game, p1, p2 = _two_player_game()
    p2.lost = True
    assert game.is_game_over()


def test_104_1_game_over_when_draw():
    """104.1: The game is over when it is a draw."""
    game, p1, p2 = _two_player_game()
    game.is_draw = True
    assert game.is_game_over()


# ---------------------------------------------------------------------------
# Rule 104.2a – A player wins if all opponents have left the game.
# ---------------------------------------------------------------------------

def test_104_2a_last_player_standing_wins():
    """104.2a: When all opponents have lost, the remaining player wins."""
    game, p1, p2 = _two_player_game()
    p2.lost = True
    winner = game.get_winner()
    assert winner is p1


def test_104_2a_no_winner_while_both_active():
    """104.2a: No winner while both players are still in the game."""
    game, p1, p2 = _two_player_game()
    assert game.get_winner() is None


def test_104_2a_no_winner_while_one_active_one_lost_draw():
    """104.2a: is_draw overrides last-standing win."""
    game, p1, p2 = _two_player_game()
    p2.lost = True
    game.is_draw = True
    assert game.get_winner() is None


def test_104_2a_three_players_two_lose_winner_identified():
    """104.2a: In a multiplayer game, the last player with opponents all lost wins."""
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    p3 = PlayerState(name="P3")
    game = Game(players=[p1, p2, p3])
    p2.lost = True
    p3.lost = True
    assert game.get_winner() is p1


# ---------------------------------------------------------------------------
# Rule 104.2b – An effect may state that a player wins the game.
# ---------------------------------------------------------------------------

def test_104_2b_spell_causes_caster_to_win():
    """104.2b: Resolving a spell with 'you win the game' marks the caster as winner."""
    win_spell = _mk_card("Final Gambit", "Sorcery", "You win the game.")
    p1 = PlayerState(name="P1", hand=[win_spell])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Final Gambit", target_player_index=1)

    assert result.supported
    game.check_state_based_actions()
    assert game.get_winner() is p1
    assert game.is_game_over()


def test_104_2b_win_spell_marks_opponent_as_lost():
    """104.2b: When caster wins, all opponents are marked as lost."""
    win_spell = _mk_card("Win Card", "Sorcery", "You win the game.")
    p1 = PlayerState(name="P1", hand=[win_spell])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Win Card", target_player_index=1)
    game.check_state_based_actions()

    assert p2.lost


# ---------------------------------------------------------------------------
# Rule 104.3a – A player can concede the game at any time.
# ---------------------------------------------------------------------------

def test_104_3a_concede_marks_player_as_lost():
    """104.3a: A conceding player immediately loses the game."""
    game, p1, p2 = _two_player_game()
    game.concede(0)
    assert p1.lost


def test_104_3a_concede_leaves_game_immediately():
    """104.3a: After conceding, the game is over because the opponent wins."""
    game, p1, p2 = _two_player_game()
    game.concede(0)
    assert game.is_game_over()
    assert game.get_winner() is p2


def test_104_3a_concede_is_logged():
    """104.3a: Concession is logged."""
    game, p1, p2 = _two_player_game()
    game.concede(1)
    assert any("concede" in entry.lower() or "lost" in entry.lower() for entry in game.log)


def test_104_3a_double_concede_is_idempotent():
    """104.3a: Conceding twice does not change the lost flag or produce duplicate effects."""
    game, p1, p2 = _two_player_game()
    game.concede(0)
    log_len = len(game.log)
    game.concede(0)
    assert p1.lost
    assert len(game.log) == log_len  # second concede is a no-op


# ---------------------------------------------------------------------------
# Rule 104.3b – If a player's life total is 0 or less, that player loses the
# game the next time a player would receive priority. (State-based action.)
# ---------------------------------------------------------------------------

def test_104_3b_zero_life_causes_loss():
    """104.3b: A player reduced to 0 life loses the game via state-based actions."""
    drain = _mk_card("Drain Life", "Sorcery", "Target player loses 20 life.")
    p1 = PlayerState(name="P1", hand=[drain])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Drain Life", target_player_index=1)

    assert p2.life <= 0
    assert p2.lost


def test_104_3b_negative_life_causes_loss():
    """104.3b: A player with negative life also loses the game."""
    drain = _mk_card("Big Drain", "Sorcery", "Target player loses 5 life.")
    p1 = PlayerState(name="P1", hand=[drain])
    p2 = PlayerState(name="P2", life=3)
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Big Drain", target_player_index=1)

    assert p2.life < 0
    assert p2.lost


def test_104_3b_positive_life_does_not_cause_loss():
    """104.3b: A player with positive life does not lose."""
    game, p1, p2 = _two_player_game()
    p1.life = 1
    game.check_state_based_actions()
    assert not p1.lost


# ---------------------------------------------------------------------------
# Rule 104.3c – If a player is required to draw more cards than are left in
# their library, they draw the remaining cards and then lose the game.
# ---------------------------------------------------------------------------

def test_104_3c_draw_from_empty_library_causes_loss():
    """104.3c: Drawing from an empty library causes the player to lose."""
    draw_spell = _mk_card("Draw Spell", "Sorcery", "Target player draws a card.")
    p1 = PlayerState(name="P1", hand=[draw_spell])
    p2 = PlayerState(name="P2", library=[])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Draw Spell", target_player_index=1)

    assert p2.lost


def test_104_3c_winning_player_identified_after_opponent_decks():
    """104.3c: After the opponent loses to decking, the remaining player wins."""
    draw_spell = _mk_card("Draw Spell", "Sorcery", "Target player draws a card.")
    p1 = PlayerState(name="P1", hand=[draw_spell])
    p2 = PlayerState(name="P2", library=[])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Draw Spell", target_player_index=1)

    assert game.get_winner() is p1


# ---------------------------------------------------------------------------
# Rule 104.3d – If a player has ten or more poison counters, that player
# loses the game. (State-based action.)
# ---------------------------------------------------------------------------

def test_104_3d_poison_counters_field_exists():
    """104.3d: PlayerState tracks poison_counters."""
    p = PlayerState(name="P1")
    assert hasattr(p, "poison_counters")
    assert p.poison_counters == 0


def test_104_3d_nine_poison_counters_does_not_cause_loss():
    """104.3d: Nine poison counters is not enough to lose."""
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    p2.poison_counters = 9
    game = Game(players=[p1, p2])
    game.check_state_based_actions()
    assert not p2.lost


def test_104_3d_ten_poison_counters_causes_loss():
    """104.3d: Exactly 10 poison counters causes the player to lose."""
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    p2.poison_counters = 10
    game = Game(players=[p1, p2])
    game.check_state_based_actions()
    assert p2.lost


def test_104_3d_more_than_ten_poison_counters_causes_loss():
    """104.3d: More than 10 poison counters also causes the player to lose."""
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    p2.poison_counters = 15
    game = Game(players=[p1, p2])
    game.check_state_based_actions()
    assert p2.lost


def test_104_3d_poison_loss_is_logged():
    """104.3d: Losing to poison is recorded in the game log."""
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    p2.poison_counters = 10
    game = Game(players=[p1, p2])
    game.check_state_based_actions()
    assert any("poison" in entry.lower() for entry in game.log)


def test_104_3d_winner_determined_after_poison_death():
    """104.3d: The surviving player wins after opponent accumulates 10 poison counters."""
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    p2.poison_counters = 10
    game = Game(players=[p1, p2])
    game.check_state_based_actions()
    assert game.get_winner() is p1


# ---------------------------------------------------------------------------
# Rule 104.3e – An effect may state that a player loses the game.
# ---------------------------------------------------------------------------

def test_104_3e_spell_causes_target_to_lose():
    """104.3e: A spell with 'target player loses the game' makes the target lose."""
    lose_spell = _mk_card("Death Sentence", "Sorcery", "Target player loses the game.")
    p1 = PlayerState(name="P1", hand=[lose_spell])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Death Sentence", target_player_index=1)

    assert result.supported
    assert p2.lost


def test_104_3e_caster_wins_after_opponent_spell_loss():
    """104.3e: After the target loses via effect, the caster wins."""
    lose_spell = _mk_card("Death Sentence", "Sorcery", "Target player loses the game.")
    p1 = PlayerState(name="P1", hand=[lose_spell])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Death Sentence", target_player_index=1)
    game.check_state_based_actions()

    assert game.get_winner() is p1


def test_104_3e_effect_on_already_lost_player_is_safe():
    """104.3e: Applying a 'loses the game' effect to an already-lost player is a no-op."""
    lose_spell = _mk_card("Overkill", "Sorcery", "Target player loses the game.")
    p1 = PlayerState(name="P1", hand=[lose_spell])
    p2 = PlayerState(name="P2")
    p2.lost = True
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Overkill", target_player_index=1)

    assert result.supported
    assert p2.lost  # still lost, unchanged


# ---------------------------------------------------------------------------
# Rule 104.3f – If a player would both win and lose simultaneously, that
# player loses the game.
# ---------------------------------------------------------------------------

def test_104_3f_win_condition_does_not_save_player_who_has_lost():
    """104.3f: A player who has already lost cannot win even if a win effect fires."""
    p1 = PlayerState(name="P1")
    p1.lost = True  # already lost
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    # Even though p2 is alive, p1 is lost — p1 cannot be the winner
    assert game.get_winner() is p2
    assert game.get_winner() is not p1


def test_104_3f_player_with_zero_life_casting_win_spell_still_loses():
    """104.3f: Casting 'you win the game' while at 0 life — player still loses (SBAs apply)."""
    win_spell = _mk_card("Last Gambit", "Sorcery", "You win the game.")
    p1 = PlayerState(name="P1", hand=[win_spell], life=0)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    # SBAs already run at game start and after each action; p1 has 0 life so should already be lost
    assert p1.lost  # SBAs fire at game init
    assert game.get_winner() is p2


# ---------------------------------------------------------------------------
# Rule 104.4a – If all the players remaining in a game lose simultaneously,
# the game is a draw.
# ---------------------------------------------------------------------------

def test_104_4a_both_players_lose_simultaneously_is_draw():
    """104.4a: Both players losing at the same time results in a draw."""
    p1 = PlayerState(name="P1", life=0)
    p2 = PlayerState(name="P2", life=0)
    game = Game(players=[p1, p2])  # SBAs fire during __post_init__
    assert p1.lost
    assert p2.lost
    assert game.is_draw


def test_104_4a_draw_means_no_winner():
    """104.4a: A draw means there is no winner."""
    p1 = PlayerState(name="P1", life=0)
    p2 = PlayerState(name="P2", life=0)
    game = Game(players=[p1, p2])
    assert game.get_winner() is None


def test_104_4a_draw_is_game_over():
    """104.4a: A draw counts as the game being over (rule 104.1)."""
    p1 = PlayerState(name="P1", life=0)
    p2 = PlayerState(name="P2", life=0)
    game = Game(players=[p1, p2])
    assert game.is_game_over()


def test_104_4a_manual_draw_flag():
    """104.4a: Setting is_draw directly on the game object is respected."""
    game, p1, p2 = _two_player_game()
    game.is_draw = True
    assert game.is_draw
    assert game.get_winner() is None
    assert game.is_game_over()


# ---------------------------------------------------------------------------
# Rule 104.4c – An effect may state that the game is a draw.
# ---------------------------------------------------------------------------

def test_104_4c_spell_causes_game_to_be_draw():
    """104.4c: A spell with 'the game is a draw' ends the game as a draw."""
    draw_spell = _mk_card("Mutual Destruction", "Sorcery", "The game is a draw.")
    p1 = PlayerState(name="P1", hand=[draw_spell])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Mutual Destruction", target_player_index=1)

    assert result.supported
    assert game.is_draw


def test_104_4c_draw_spell_no_winner():
    """104.4c: After a 'game is a draw' effect, there is no winner."""
    draw_spell = _mk_card("Stalemate", "Sorcery", "The game is a draw.")
    p1 = PlayerState(name="P1", hand=[draw_spell])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Stalemate", target_player_index=1)

    assert game.get_winner() is None
    assert game.is_game_over()


# ---------------------------------------------------------------------------
# Rule 104.5 – If a player loses the game, that player leaves the game.
# ---------------------------------------------------------------------------

def test_104_5_lost_player_has_lost_flag_set():
    """104.5: A player who loses has their lost flag set to True."""
    game, p1, p2 = _two_player_game()
    game.concede(1)
    assert p2.lost


def test_104_5_game_over_after_player_leaves():
    """104.5: Once a player loses and leaves, the remaining player wins."""
    game, p1, p2 = _two_player_game()
    game.concede(1)
    assert game.is_game_over()
    assert game.get_winner() is p1


# ---------------------------------------------------------------------------
# Rule 104.3j – Commander damage: 21 or more combat damage by the same
# commander over the course of the game causes that player to lose.
# (State-based action, see rule 704 and 903.10.)
# ---------------------------------------------------------------------------

@pytest.mark.xfail(
    strict=False,
    reason=(
        "Rule 104.3j not implemented: the engine does not track per-commander combat "
        "damage dealt to each player. No commander_damage field exists on PlayerState."
    ),
)
def test_104_3j_twenty_one_commander_damage_causes_loss():
    """104.3j: A player dealt 21+ combat damage by the same commander over the game loses."""
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    assert hasattr(p2, "commander_damage")  # type: ignore[attr-defined]
    # Simulate receiving 21 combat damage from a commander named "Rafiq of the Many"
    p2.commander_damage["Rafiq of the Many"] = 21  # type: ignore[attr-defined]
    game = Game(players=[p1, p2])
    game.check_state_based_actions()
    assert p2.lost


# ---------------------------------------------------------------------------
# Additional edge-case tests
# ---------------------------------------------------------------------------

def test_game_not_over_with_all_players_alive():
    """No game-ending condition met when all players are alive and healthy."""
    game, p1, p2 = _two_player_game()
    assert not p1.lost
    assert not p2.lost
    assert not game.is_draw
    assert not game.is_game_over()


def test_get_winner_returns_none_when_no_game_over():
    """get_winner() returns None while the game is ongoing."""
    game, p1, p2 = _two_player_game()
    assert game.get_winner() is None


def test_is_game_over_false_on_new_game():
    """is_game_over() returns False immediately after game creation."""
    game, p1, p2 = _two_player_game()
    assert not game.is_game_over()


def test_poison_counters_start_at_zero():
    """Players start with zero poison counters."""
    p = PlayerState(name="P1")
    assert p.poison_counters == 0


def test_is_draw_starts_false():
    """Games start with is_draw = False."""
    game, _, _ = _two_player_game()
    assert not game.is_draw
