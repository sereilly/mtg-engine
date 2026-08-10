from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.card_loader import load_catalog, load_cards
from engine.reporting import build_support_report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Show card support coverage for the whole manifest pool"
    )
    parser.add_argument(
        "--cards",
        default=None,
        help=(
            "Path to a single set's card JSON. Omit to report on the whole "
            "manifest pool (cards/manifest.json), which is what 'is this "
            "engine's card pool supported?' means."
        ),
    )
    args = parser.parse_args()

    # Defaulting to one hardcoded set made this report answer a much narrower
    # question than it appeared to: it printed LEA's 290 cards while the pool
    # had grown to several sets, so "no unsupported cards" was true of Alpha
    # and said nothing about the rest. The manifest is the single registry of
    # the pool; this reads it like everything else does.
    if args.cards:
        cards = load_cards(Path(args.cards))
    else:
        cards = load_catalog()
    report = build_support_report(cards)

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
