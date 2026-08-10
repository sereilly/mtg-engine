from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import Game, PlayerState, load_cards
from set_argument import add_set_argument, resolve_set

# The duel is a fixed script, so it names the cards it plays. Which set supplies
# them is the argument.
SAMPLE_DECK = (
    "Island",
    "Island",
    "Island",
    "Counterspell",
    "Ancestral Recall",
    "Lightning Bolt",
    "Serra Angel",
)


def _card_lookup(cards):
    return {card.name: card for card in cards}


def _sample_library(lookup, seed: int):
    cards = [lookup[name] for name in SAMPLE_DECK if name in lookup]
    random.Random(seed).shuffle(cards)
    return cards


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a short scripted duel simulation")
    add_set_argument(parser, default="LEA")
    parser.add_argument("--seed", default=7, type=int, help="Deterministic shuffle seed")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    selection = resolve_set(parser, args)

    lookup = _card_lookup(load_cards(selection.paths))
    missing = [name for name in dict.fromkeys(SAMPLE_DECK) if name not in lookup]
    if len(missing) == len(dict.fromkeys(SAMPLE_DECK)):
        # Every scripted card absent means empty libraries, and an empty duel
        # prints a log of nothing and a pair of untouched life totals — a run
        # that looks like a pass. Say so instead.
        parser.error(
            f"{selection.label} has none of the scripted duel's cards "
            f"({', '.join(missing)}), so there is no duel to run"
        )

    p1 = PlayerState(name="Alice", library=_sample_library(lookup, args.seed))
    p2 = PlayerState(name="Bob", library=_sample_library(lookup, args.seed + 1))

    game = Game(players=[p1, p2])
    starting_player = game.select_starting_player()
    game.deal_opening_hands(starting_player)
    game.keep_hand(0)
    game.keep_hand(1)

    if any(card.name == "Ancestral Recall" for card in p1.hand):
        game.queue_from_hand(0, "Ancestral Recall", target_player_index=0)
        if any(card.name == "Counterspell" for card in p2.hand):
            game.queue_from_hand(1, "Counterspell", target_player_index=0)
        game.resolve_stack()

    if any(card.name == "Lightning Bolt" for card in p1.hand):
        game.cast_from_hand(0, "Lightning Bolt", target_player_index=1)

    print(f"Set: {selection.label}")
    if missing:
        print(f"Not in this set, skipped: {', '.join(missing)}")
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
