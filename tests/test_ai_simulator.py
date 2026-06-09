from pathlib import Path

import pytest

from engine import Game, PlayerState
from engine.ai_simulator import run_ai_simulation
from engine.models import Permanent


def test_ai_simulator_runs_without_issues_for_two_games():
    report = run_ai_simulation(
        cards_path=Path("lea_cards.json"),
        games=2,
        seed=77,
        max_turns=10,
    )

    assert report.games_completed == 2
    assert report.interaction_count > 0
    assert report.issues == []


def test_prodigal_sorcerer_summoning_sickness_clears_after_turn(all_cards):
    """Regression: game.turn must increment each half-turn so summoning sickness clears.

    Before the fix, game.turn was never incremented in the simulation loop, so
    every creature retained its summoning_sickness_turn == game.turn == 1 forever
    and could never use a tap ability.
    """
    cards = {c.name: c for c in all_cards}
    prodigal = cards["Prodigal Sorcerer"]

    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # P1's first turn: creature enters; game.turn is 1
    game.turn = 1
    perm = Permanent(card=prodigal)
    p1.battlefield.append(perm)
    game._initialize_permanent_state(perm, 0, None)

    # Creature is summoning sick on the turn it entered
    assert game._is_summoning_sick(perm)

    # P1's second turn: each player half-turn advances game.turn by 1, so
    # P1's second turn is game.turn == 3 (P1=1, P2=2, P1=3)
    game.turn = 3
    assert not game._is_summoning_sick(perm), "sickness must clear by P1's second turn"

    # The tap ability should now succeed and deal 1 damage to P2
    result = game.activate_permanent_ability(0, "Prodigal Sorcerer", target_player_index=1)
    assert result.supported
    assert p2.life == 19


def test_prodigal_sorcerer_deals_damage_in_simulation():
    """Regression: Prodigal Sorcerer must deal damage once summoning sickness clears."""
    report = run_ai_simulation(
        cards_path=Path("lea_cards.json"),
        games=5,
        seed=42,
        max_turns=18,
    )

    prodigal_damage_lines = [
        line for line in report.log_lines
        if "Prodigal Sorcerer dealt" in line
    ]
    assert prodigal_damage_lines, (
        "Prodigal Sorcerer never dealt damage across 5 games; "
        "summoning sickness may not be clearing between turns"
    )


def test_simulation_stops_when_player_loses_via_empty_library():
    """Regression: game loop must exit when player.lost is set, not only on life loss.

    Before the fix, the loop only checked life <= 0. A player who drew from an
    empty library had player.lost set to True by check_state_based_actions, but
    the game continued for many more turns.
    """
    report = run_ai_simulation(
        cards_path=Path("lea_cards.json"),
        games=5,
        seed=42,
        max_turns=18,
    )

    found_loss_in_game = False
    for line in report.log_lines:
        if line.startswith("=== Game"):
            found_loss_in_game = False
            continue

        if "lost the game (704.5b" in line:
            found_loss_in_game = True
            continue

        if found_loss_in_game:
            # Only the RESULT line or blank lines should follow within the same game.
            # A "Gx Ty ... cast/activate" line means the game kept running after the loss.
            assert not (" cast " in line and line.startswith("G")), (
                f"Cast action found after player lost via empty library: {line!r}"
            )
            assert not (" activate " in line and line.startswith("G")), (
                f"Activation found after player lost via empty library: {line!r}"
            )


def test_ancestral_recall_never_self_causes_library_loss():
    """Regression: AI must not self-cast Ancestral Recall when library has < 3 cards.

    Before the fix, the AI's score for Ancestral Recall did not account for library
    depth, causing it to self-target the spell when nearly out of cards and lose the
    game immediately via rule 704.5b.  The fix returns -100 in that scenario.

    We verify this by scanning the log for the distinctive pattern:
      'cast Ancestral Recall' followed by 'lost the game (704.5b' in the *same turn block*
    which is the footprint of an AI-caused library self-kill from Ancestral Recall.
    """
    report = run_ai_simulation(
        cards_path=Path("lea_cards.json"),
        games=10,
        seed=1337,
        max_turns=25,
    )

    prev_was_ancestral_cast = False
    for line in report.log_lines:
        stripped = line.strip()
        if "cast Ancestral Recall" in stripped:
            prev_was_ancestral_cast = True
            continue
        if prev_was_ancestral_cast:
            assert "lost the game (704.5b" not in stripped, (
                f"Ancestral Recall self-cast triggered a library-death loss: {stripped!r}"
            )
            # Reset once we move past the immediate follow-up lines
            if stripped.startswith("G") or stripped.startswith("RESULT") or stripped == "":
                prev_was_ancestral_cast = False
