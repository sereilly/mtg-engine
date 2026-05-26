from __future__ import annotations

from engine.ai_policy import (
    choose_activation_action,
    choose_cast_action,
    choose_combat_blockers,
    choose_combat_instant_cast_action,
)
from engine.game import Game
from engine.models import Permanent, PlayerState


def _get(all_cards, name: str):
    return next(card for card in all_cards if card.name == name)














