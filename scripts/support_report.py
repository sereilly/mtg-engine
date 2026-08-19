from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.card_loader import load_cards
from engine.reporting import build_support_report
from set_argument import add_set_argument, resolve_set


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Show card support coverage for the whole manifest pool, or one set"
    )
    # Defaulting to one hardcoded set made this report answer a much narrower
    # question than it appeared to: it printed LEA's 290 cards while the pool
    # had grown to several sets, so "no unsupported cards" was true of Alpha
    # and said nothing about the rest. The manifest is the single registry of
    # the pool; this reads it like everything else does, and prints which pool
    # the numbers below describe.
    add_set_argument(parser, default=None)
    parser.add_argument(
        "--hollow-lines",
        action="store_true",
        help=(
            "Census the Nine Lives class: supported cards carrying an ability "
            "part that compiled to no instruction. A card is supported when "
            "any line is, so these are the lines support can hide — each "
            "needs a registry (aura death effects, draw-step modifiers, enter "
            "effects, …) verified to actually implement it, or it is a card "
            "that works less than it reports."
        ),
    )
    return parser


def hollow_lines_report(cards) -> list[tuple[str, str, str]]:
    """``(card, part kind, source line)`` for every supported card whose
    compiled program carries an ability with no instruction behind it."""
    from engine.oracle import compile_card_oracle

    findings: list[tuple[str, str, str]] = []
    for card in cards:
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for ability in program.activated_abilities:
            if not ability.supported or ability.instruction is None:
                findings.append((card.name, "activated", ability.source_line))
        for trigger in program.triggered_abilities:
            if not trigger.supported or trigger.instruction is None:
                findings.append((card.name, "triggered", trigger.source_line))
        for mode in program.modes:
            if mode.instruction is None:
                findings.append((card.name, "mode", mode.label))
    return findings


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    selection = resolve_set(parser, args)

    if args.hollow_lines:
        findings = hollow_lines_report(load_cards(selection.paths))
        print(f"Pool: {selection.label}")
        print(f"Supported cards with an instruction-less ability part: "
              f"{len({name for name, _, _ in findings})} ({len(findings)} part(s))")
        for name, kind, line in findings:
            print(f"  {name} [{kind}]: {line}")
        if findings:
            print()
            print("Each line above leans on a registry the compiler cannot see —")
            print("verify the registry actually implements it (the Rock Hydra test:")
            print("give the behaviour a game and watch it happen, not the claim).")
        return 0

    report = build_support_report(load_cards(selection.paths))

    print(f"Pool: {selection.label}")
    print(f"Total cards: {report.total_cards}")
    print(f"Supported cards: {report.supported_cards}")
    print(f"Unsupported cards: {report.unsupported_cards}")
    print()
    print("By type:")
    for card_type, count in report.by_type.items():
        supported = report.supported_by_type.get(card_type, 0)
        print(f"  {card_type}: {supported}/{count} supported")

    print()
    print("Unsupported reason breakdown:")
    if not report.unsupported_reasons:
        print("  none")
    else:
        for reason, count in report.unsupported_reasons.items():
            print(f"  {reason}: {count}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
