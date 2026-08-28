from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.ai_simulator import run_ai_simulation
from set_argument import add_set_argument, resolve_set


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run automated AI-vs-AI MTG simulations")
    add_set_argument(parser, default="LEA")
    parser.add_argument("--games", type=int, default=10, help="Number of games to simulate")
    parser.add_argument("--seed", type=int, default=1337, help="Deterministic seed")
    parser.add_argument("--max-turns", type=int, default=18, help="Turn cap per game")
    parser.add_argument(
        "--log-file",
        default="simulation_interactions.log",
        help="Path to write full interaction log",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    selection = resolve_set(parser, args)

    try:
        report = run_ai_simulation(
            cards_path=selection.paths,
            games=args.games,
            seed=args.seed,
            max_turns=args.max_turns,
        )
    except ValueError as exc:
        parser.error(f"{selection.label}: {exc}")

    log_path = Path(args.log_file)
    log_path.write_text("\n".join(report.log_lines), encoding="utf-8")

    print(f"Pool: {selection.label}")
    print(f"Games simulated: {report.games_completed}/{report.games_requested}")
    print(f"Interactions logged: {report.interaction_count}")
    print(f"Log file: {log_path}")

    if report.refused_casts:
        total = sum(report.refused_casts.values())
        print(f"Casts the engine declined: {total} (the cast gate working, not a failure)")
        for reason, count in report.refused_casts.most_common(5):
            print(f"  {count}x {reason}")

    # The guard the fixed decklist used to give for free. Building the deck out
    # of the set means no pool can fail to supply it, so nothing stops a run
    # over a set whose cards the AI can never pay for — and "no illegal
    # interactions detected" over games where nobody cast anything is exactly
    # the true-statement-about-nothing this script's --set handling exists to
    # prevent. Measure the thing itself: did anything happen?
    if report.interaction_count == 0:
        print(
            f"No spell was cast and no ability activated across "
            f"{report.games_completed} game(s). The run proves nothing — check "
            f"that {selection.label} can produce mana for its own spells."
        )
        return 1

    if report.issues:
        print("Issues found:")
        for issue in report.issues:
            print(f"- Game {issue.game_index}, Turn {issue.turn}: {issue.message}")
        return 1

    print("No illegal or unexpected interactions detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
