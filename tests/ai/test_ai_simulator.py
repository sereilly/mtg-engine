import ast
import pathlib

import pytest

from engine import Game, PlayerState
from engine.ai_simulator import _build_deck, run_ai_simulation
from engine.models import Permanent
from tests.helpers import LEA_PATH

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _expected_card_names() -> set[str]:
    """The card names ``_assert_expected`` branches on, read from the source.

    An AST read rather than a hand-kept list: a list would be the third place
    these names live, and it would go stale the same way the thing it guards
    would."""
    tree = ast.parse((ROOT / "engine" / "ai_simulator.py").read_text(encoding="utf-8"))
    function = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_assert_expected"
    )
    found: set[str] = set()
    for node in ast.walk(function):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left, *node.comparators]
        if not any(isinstance(item, ast.Attribute) and item.attr == "name" for item in operands):
            continue
        found.update(
            item.value for item in operands
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        )
    return found


def test_every_simulator_expectation_names_a_card_the_deck_plays(all_cards):
    """``_assert_expected`` is allowed its card names — it is a test oracle, and
    one derived from the compiled program would be a tautology (a Lightning Bolt
    mis-parsed to 1 damage deals 1 and matches its own derived expectation).

    What it is *not* immune to is the decklist drifting: an expectation for a
    card ``_build_deck`` stopped playing never fires again, and nothing fails.
    That is the same "the comment expired without anyone editing it" decay the
    name rule exists for, so it gets a guard rather than a promise."""
    deck = {card.name for card in _build_deck({c.name: c for c in all_cards}, seed=1)}
    expected = _expected_card_names()

    assert expected, "no card-name expectations found — did _assert_expected move?"
    orphaned = sorted(expected - deck)
    assert not orphaned, (
        "engine/ai_simulator.py::_assert_expected checks cards the simulator's "
        f"decklist no longer plays, so the checks never run: {orphaned}"
    )


def test_the_simulator_drains_every_prompt_that_suspends_a_resolution():
    """A kind registered ``suspends`` holds ``game.effect_suspended`` until it is
    answered, so a headless run that leaves one owed does not merely skip that
    prompt — it stops the *next* resumable loop anywhere in the game after one
    step, with nothing pointing back at what caused it. Derived from the
    registry, because a hand-kept list is what would go stale.

    Two exemptions, both by construction rather than by opinion. A kind
    registered ``default_at_arm`` is never *queued* for a non-interactive seat —
    ``arm_pending_choice`` takes its default before the flag is set — so a
    headless run cannot owe one. ``effect_order`` is the same rule written a
    layer up: ``engine/replacements.py`` answers a non-interactive seat with the
    default before queueing.
    """
    from engine.ai_simulator import _SIMULATED_CHOICES
    from engine.pending_choices import CHOICE_SPECS

    suspending = {kind for kind, spec in CHOICE_SPECS.items() if spec.suspends}
    answered_at_arm = {
        kind for kind, spec in CHOICE_SPECS.items() if spec.default_at_arm
    }
    undrained = (
        suspending - set(_SIMULATED_CHOICES) - answered_at_arm - {"effect_order"}
    )

    assert not undrained, (
        "suspending prompt(s) a headless simulation would leave owed, wedging "
        f"every later resumable loop: {sorted(undrained)}"
    )


@pytest.mark.slow
def test_ai_simulator_runs_without_issues_for_two_games():
    report = run_ai_simulation(
        cards_path=LEA_PATH,
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


@pytest.mark.slow
def test_prodigal_sorcerer_deals_damage_in_simulation():
    """Regression: Prodigal Sorcerer must deal damage once summoning sickness clears."""
    report = run_ai_simulation(
        cards_path=LEA_PATH,
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


@pytest.mark.slow
def test_simulation_stops_when_player_loses_via_empty_library():
    """Regression: game loop must exit when player.lost is set, not only on life loss.

    Before the fix, the loop only checked life <= 0. A player who drew from an
    empty library had player.lost set to True by check_state_based_actions, but
    the game continued for many more turns.
    """
    report = run_ai_simulation(
        cards_path=LEA_PATH,
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


@pytest.mark.slow
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
        cards_path=LEA_PATH,
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
