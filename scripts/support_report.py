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
    return parser


def main() -> int:
    parser = build_parser()
    selection = resolve_set(parser, parser.parse_args())
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
