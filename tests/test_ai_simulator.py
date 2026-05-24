from pathlib import Path

from engine.ai_simulator import run_ai_simulation


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