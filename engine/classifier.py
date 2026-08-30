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
    """The compiler's verdict on *card*, unchanged.

    A pass-through, and it has to be one. This function used to widen the
    compiler's answer: a card refused for ``"unsupported triggered ability"``
    was reported **supported** as long as any *other* triggered ability of it
    compiled. That is the widened-gate shape — the gate stands in for "is every
    line of this card read?" and answers "does some line of it work?" — and it
    reached further than a census, because `mixins/stack/casting.py`,
    `web/catalog.py` and `engine/ai_policy.py` all ask this question rather than
    the compiler's: the card was castable, browsable and playable with a printed
    trigger silently doing nothing.

    It also made one script disagree with itself. `scripts/support_report.py`'s
    census counts through here and its ``--refusals`` list counts through
    `compile_card_oracle`, so the two halves of one report gave two totals for
    one set.

    Measured over the whole shipped-plus-measured pool before removing it:
    **one** card moved, Illusionary Presence (ICE), whose second upkeep trigger
    the compiler cannot read. No shipped card was affected, which is what makes
    this a removal rather than a migration — and the card it was hiding landed
    in the same round.
    """
    program = compile_card_oracle(card)
    return CardClassification(program.supported, program.effect_kind, program.reason)
