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

_CREATURE_TARGET = 15
_NONCREATURE_TARGET = 21


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
        identity = set(card.color_identity)
        if not identity or identity.issubset(colors):
            eligible.append(card)
    return eligible


def _cmc_weight(cmc: float) -> int:
    """Curve weights: peak at CMC 2-3, taper toward extremes."""
    c = int(cmc)
    if c <= 1:
        return 3
    if c == 2:
        return 5
    if c == 3:
        return 4
    if c == 4:
        return 3
    if c == 5:
        return 2
    return 1


def _pick_cards(
    rng: random.Random,
    pool: list[CardDefinition],
    target: int,
    colors: list[str],
) -> list[CardDefinition]:
    """Pick unique cards with 2-4 copies each to fill exactly `target` slots.

    Rotates through `colors` so each gets roughly equal representation and
    weights card selection by CMC for a playable mana curve.
    """
    by_color: dict[str, list[CardDefinition]] = {c: [] for c in colors}
    neutral: list[CardDefinition] = []
    for card in pool:
        identity = set(card.color_identity)
        if not identity:
            neutral.append(card)
        else:
            for c in colors:
                if c in identity:
                    by_color[c].append(card)

    used: set[str] = set()
    chosen: list[list] = []  # [card, copies]
    picks_per_color: dict[str, int] = {c: 0 for c in colors}
    total = 0

    while total < target:
        remaining = target - total
        if remaining < 2:
            break

        max_copies = min(4, remaining)
        # Avoid leaving exactly 1 slot, which can't be filled with 2-4 copies.
        forbidden = remaining - 1
        valid_copies = [n for n in range(2, max_copies + 1) if n != forbidden]
        if not valid_copies:
            break

        # Pick from the most underrepresented color for even distribution.
        color = min(colors, key=lambda c: picks_per_color[c])
        candidates = [c for c in by_color[color] if c.name not in used]
        if not candidates:
            candidates = [c for c in neutral if c.name not in used]
        if not candidates:
            for c in colors:
                candidates = [card for card in by_color[c] if card.name not in used]
                if candidates:
                    break
        if not candidates:
            break

        weights = [_cmc_weight(c.cmc) for c in candidates]
        card = rng.choices(candidates, weights=weights, k=1)[0]
        copies = rng.choice(valid_copies)

        chosen.append([card, copies])
        used.add(card.name)
        total += copies
        picks_per_color[color] += 1

    # Fallback: if unique cards ran out before target, add copies to existing picks.
    if total < target and chosen:
        i = 0
        while total < target:
            chosen[i % len(chosen)][1] += 1
            total += 1
            i += 1

    result: list[CardDefinition] = []
    for card, copies in chosen:
        result.extend([card] * copies)
    return result


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

    creatures = [c for c in pool if c.primary_type == "creature"]
    noncreatures = [c for c in pool if c.primary_type != "creature"]

    creature_cards = _pick_cards(rng, creatures, _CREATURE_TARGET, selected_colors)
    noncreature_cards = _pick_cards(rng, noncreatures, _NONCREATURE_TARGET, selected_colors)

    deck = lands + creature_cards + noncreature_cards
    rng.shuffle(deck)
    return deck, selected_colors
