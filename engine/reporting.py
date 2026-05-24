from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .classifier import classify_card
from .models import CardDefinition


@dataclass(frozen=True)
class SupportReport:
    total_cards: int
    supported_cards: int
    unsupported_cards: int
    by_type: dict[str, int]
    supported_by_type: dict[str, int]
    unsupported_reasons: dict[str, int]


def build_support_report(cards: list[CardDefinition]) -> SupportReport:
    by_type = Counter()
    supported_by_type = Counter()
    unsupported_reasons = Counter()

    supported = 0
    for card in cards:
        by_type[card.primary_type] += 1
        classification = classify_card(card)
        if classification.supported:
            supported += 1
            supported_by_type[card.primary_type] += 1
        else:
            unsupported_reasons[classification.reason] += 1

    total = len(cards)
    return SupportReport(
        total_cards=total,
        supported_cards=supported,
        unsupported_cards=total - supported,
        by_type=dict(sorted(by_type.items())),
        supported_by_type=dict(sorted(supported_by_type.items())),
        unsupported_reasons=dict(sorted(unsupported_reasons.items())),
    )
