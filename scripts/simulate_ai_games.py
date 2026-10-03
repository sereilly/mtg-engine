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
    # Land drops are a special action, not an interaction (CR 116.2a), so they
    # are counted apart — and they are what every cast above was paid from.
    # Until PCY's wave 3 nothing was: the simulator's games ignored mana costs
    # and a land was the turn's one cast. Zero here is that coming back.
    print(f"Lands played: {report.lands_played}")
    print(f"Log file: {log_path}")

    # What combat did. Reported beside the interaction count and for the same
    # reason: before this simulator had a combat phase, every run in its history
    # reported "no illegal interactions" over games in which nobody had ever
    # attacked — a true statement about nothing. A zero here now means either a
    # pool that cannot attack or a regression, and either is worth seeing.
    print(
        f"Combat: {report.attacks_declared} declaration(s), "
        f"{report.attackers_declared} attacker(s), "
        f"{report.blockers_declared} blocker(s), "
        f"{report.manual_damage_splits} manual damage split(s)"
    )

    # And how many turns actually *ended*, for the same reason. The loop had
    # no ending phase until PCY's wave 2, so every "until end of turn" effect
    # in every run this script ever printed lasted the whole game — and the
    # output read exactly as it does now. A zero here is that coming back.
    print(
        f"Ending phase: {report.end_steps} end step(s), "
        f"{report.cleanup_steps} cleanup step(s), "
        f"{report.cleanup_discards} card(s) discarded to hand size"
    )

    # CR 602.1b: abilities activated on a permanent another seat controls
    # ("Any player may activate this ability"). Only a pool printing one can
    # move it, so it is shown when it did.
    if report.foreign_activations:
        print(
            f"Activations on another seat's permanent: {report.foreign_activations}"
        )

    if report.refused_attacks:
        total = sum(report.refused_attacks.values())
        print(f"Attack declarations the engine declined: {total} (the AI proposed an illegal set)")
        for reason, count in report.refused_attacks.most_common(5):
            print(f"  {count}x {reason}")

    # The block-side twin, and it reads zero for two different reasons that no
    # other number here tells apart: a defender that chose not to block, and a
    # defender whose whole declaration was refused. This is the second.
    if report.refused_blocks:
        total = sum(report.refused_blocks.values())
        print(f"Block declarations the engine declined: {total} (the AI proposed an illegal map)")
        for reason, count in report.refused_blocks.most_common(5):
            print(f"  {count}x {reason}")

    if report.refused_casts:
        total = sum(report.refused_casts.values())
        print(f"Casts the engine declined: {total} (the cast gate working, not a failure)")
        for reason, count in report.refused_casts.most_common(5):
            print(f"  {count}x {reason}")

    # The activation-side twin, which this report had no line for: a refused
    # activation spends nothing and the AI proposes it again next turn.
    if report.refused_activations:
        total = sum(report.refused_activations.values())
        print(f"Activations the engine declined: {total} (the AI proposed one it cannot make)")
        for reason, count in report.refused_activations.most_common(5):
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
