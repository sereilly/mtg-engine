"""Basic MTG text rules engine package."""

from .card_loader import load_cards
from .classifier import CardClassification, classify_card
from .game import Game, SimulationResult
from .models import CardDefinition, PlayerState
from .reporting import SupportReport, build_support_report

__all__ = [
    "CardClassification",
    "CardDefinition",
    "Game",
    "PlayerState",
    "SimulationResult",
    "SupportReport",
    "build_support_report",
    "classify_card",
    "load_cards",
]
