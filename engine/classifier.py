from __future__ import annotations

from dataclasses import dataclass

from .models import CardDefinition
from .oracle import compile_card_oracle


@dataclass(frozen=True)
class CardClassification:
    supported: bool
    effect_kind: str
    reason: str


def classify_card(card: CardDefinition) -> CardClassification:
    program = compile_card_oracle(card)
    return CardClassification(program.supported, program.effect_kind, program.reason)
