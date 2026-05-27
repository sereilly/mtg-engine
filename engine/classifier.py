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
    # If the only reason for unsupported is 'unsupported triggered ability', but there is at least one supported triggered ability, mark as supported
    if not program.supported and program.reason == "unsupported triggered ability":
        if hasattr(program, "triggered_abilities") and any(getattr(program, "triggered_abilities", ())):
            if any(t.supported for t in program.triggered_abilities):
                return CardClassification(True, program.effect_kind, "supported triggered ability")
    return CardClassification(program.supported, program.effect_kind, program.reason)
