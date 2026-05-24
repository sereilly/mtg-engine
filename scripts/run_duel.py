from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import Game, PlayerState, load_cards


def _card_lookup(cards):
    return {card.name: card for card in cards}


def _sample_library(lookup, seed: int):
    names = [
        "Island",
        "Island",
        "Island",
        "Counterspell",
        "Ancestral Recall",
        "Lightning Bolt",
        "Serra Angel",
    ]
    cards = [lookup[name] for name in names if name in lookup]
    random.Random(seed).shuffle(cards)
    return cards


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a short scripted duel simulation")
    parser.add_argument("--cards", default="lea_cards.json", help="Path to LEA cards JSON")
    parser.add_argument("--seed", default=7, type=int, help="Deterministic shuffle seed")
    args = parser.parse_args()

    cards = load_cards(Path(args.cards))
    lookup = _card_lookup(cards)

    p1 = PlayerState(name="Alice", library=_sample_library(lookup, args.seed))
    p2 = PlayerState(name="Bob", library=_sample_library(lookup, args.seed + 1))

    p1.draw(5)
    p2.draw(5)

    game = Game(players=[p1, p2])

    if any(card.name == "Ancestral Recall" for card in p1.hand):
        game.queue_from_hand(0, "Ancestral Recall", target_player_index=0)
        if any(card.name == "Counterspell" for card in p2.hand):
            game.queue_from_hand(1, "Counterspell", target_player_index=0)
        game.resolve_stack()

    if any(card.name == "Lightning Bolt" for card in p1.hand):
        game.cast_from_hand(0, "Lightning Bolt", target_player_index=1)

    print("Simulation log:")
    for line in game.log:
        print(f"- {line}")

    print()
    print("Final state:")
    print(f"Alice life: {p1.life}, hand: {len(p1.hand)}, graveyard: {len(p1.graveyard)}")
    print(f"Bob life: {p2.life}, hand: {len(p2.hand)}, graveyard: {len(p2.graveyard)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
