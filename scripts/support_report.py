from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.card_loader import load_cards
from engine.reporting import build_support_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Show card support coverage for LEA cards")
    parser.add_argument(
        "--cards",
        default="lea_cards.json",
        help="Path to card JSON data (default: lea_cards.json)",
    )
    args = parser.parse_args()

    cards_path = Path(args.cards)
    cards = load_cards(cards_path)
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
