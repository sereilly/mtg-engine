from __future__ import annotations

import random
from pathlib import Path

from engine import load_cards
from engine.models import CardDefinition


COLOR_SYMBOLS = ["W", "U", "B", "R", "G"]
BASIC_LANDS = {
    "W": "Plains",
    "U": "Island",
    "B": "Swamp",
    "R": "Mountain",
    "G": "Forest",
}


def _card_map(cards_path: Path) -> dict[str, CardDefinition]:
    cards = load_cards(cards_path)
    return {card.name: card for card in cards}


def _pick_colors(rng: random.Random, color_count: int) -> list[str]:
    return rng.sample(COLOR_SYMBOLS, color_count)


def _build_lands(rng: random.Random, cards: dict[str, CardDefinition], colors: list[str]) -> list[CardDefinition]:
    if not colors:
        raise ValueError("At least one color must be selected")

    base = 24 // len(colors)
    remainder = 24 % len(colors)
    symbols = list(colors)
    rng.shuffle(symbols)

    lands: list[CardDefinition] = []
    for idx, symbol in enumerate(symbols):
        count = base + (1 if idx < remainder else 0)
        land_name = BASIC_LANDS[symbol]
        for _ in range(count):
            lands.append(cards[land_name])
    return lands


def _eligible_nonlands(cards: dict[str, CardDefinition], colors: set[str]) -> list[CardDefinition]:
    eligible: list[CardDefinition] = []
    for card in cards.values():
        if card.primary_type == "land":
            continue
        # Allow colorless cards and cards fully within selected colors.
        identity = set(card.color_identity)
        if not identity or identity.issubset(colors):
            eligible.append(card)
    return eligible


def build_random_deck(cards_path: Path, color_count: int, seed: int) -> tuple[list[CardDefinition], list[str]]:
    if not (1 <= color_count <= 5):
        raise ValueError("color_count must be between 1 and 5")

    rng = random.Random(seed)
    cards = _card_map(cards_path)
    selected_colors = _pick_colors(rng, color_count)

    lands = _build_lands(rng, cards, selected_colors)
    pool = _eligible_nonlands(cards, set(selected_colors))
    if not pool:
        raise ValueError("No nonland cards available for selected colors")

    nonlands = [rng.choice(pool) for _ in range(36)]
    deck = lands + nonlands
    rng.shuffle(deck)
    return deck, selected_colors
