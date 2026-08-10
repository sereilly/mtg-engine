"""Retrieve oracle text for a Magic card from the engine's card pool.

Usage:
    python scripts/retrieve_oracle.py "Black Lotus"
    python scripts/retrieve_oracle.py "lotus" --mode substring
    python scripts/retrieve_oracle.py "Library of Alexandria" --set ARN

The pool is ``cards/manifest.json`` — every set the engine ships. This used to
read Alpha's file and nothing else, which is a bad default for a *lookup*: it
answered "no such card" for anything printed later, and answering a rules
question with the wrong card's wording is worse than not answering. ``--set``
narrows it back to one set when that is what you want.
"""
from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.card_loader import load_cards
from engine.models import CardDefinition
from set_argument import add_set_argument, resolve_set


def retrieve_oracle_text(
    name: str,
    cards: Sequence[CardDefinition],
    mode: Optional[str] = None,
    max_candidates: int = 5,
    fuzzy_cutoff: float = 0.6,
) -> Tuple[Optional[CardDefinition], List[str]]:
    norm = name.strip()
    # 1. exact
    if mode in (None, "exact"):
        for c in cards:
            if c.name == norm:
                return c, []
    # 2. case-insensitive exact
    if mode in (None, "ci", "case_insensitive"):
        for c in cards:
            if c.name.lower() == norm.lower():
                return c, []
    # 3. substring
    if mode in (None, "substring"):
        candidates = [c for c in cards if norm.lower() in c.name.lower()]
        if len(candidates) == 1:
            return candidates[0], []
        if candidates:
            return None, [c.name for c in candidates[:max_candidates]]
    # 4. fuzzy
    if mode in (None, "fuzzy"):
        names = [c.name for c in cards]
        close = difflib.get_close_matches(norm, names, n=max_candidates, cutoff=fuzzy_cutoff)
        if len(close) == 1:
            match_name = close[0]
            for c in cards:
                if c.name == match_name:
                    return c, []
        return None, close

    return None, []


def _print_card(card: CardDefinition) -> None:
    print(f"Name: {card.name}")
    print(f"Type: {card.type_line}")
    if card.mana_cost:
        print(f"Mana cost: {card.mana_cost}")
    if card.printings:
        # Reprints dedupe to one card, so say which sets it is in rather than
        # leaving the reader to guess which printing they are looking at.
        print(f"Printings: {', '.join(p.upper() for p in card.printings)}")
    print("Oracle text:")
    print(card.oracle_text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Retrieve oracle text by card name from the engine's card pool"
    )
    parser.add_argument("name", help="Card name to search for")
    parser.add_argument("--mode", choices=["exact", "ci", "substring", "fuzzy"], help="Match mode to use")
    # --file is the flag this script shipped with; kept so an invocation in
    # someone's muscle memory still works.
    add_set_argument(parser, default=None, path_flags=("--cards", "--file"))
    parser.add_argument("--max-candidates", type=int, default=8, help="Maximum candidates to show for non-unique matches")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    selection = resolve_set(parser, args)

    try:
        cards = load_cards(selection.paths)
    except Exception as e:  # unreadable or malformed card JSON
        print(f"Error loading cards from {selection.label}: {e}", file=sys.stderr)
        return 2

    card, candidates = retrieve_oracle_text(
        args.name, cards, mode=args.mode, max_candidates=args.max_candidates
    )

    if card:
        _print_card(card)
        return 0

    if candidates:
        print("Multiple or close matches found:")
        for i, n in enumerate(candidates, start=1):
            print(f"  {i}. {n}")
        print("Use a more specific name or --mode to change matching strategy.")
        return 3

    print(f"No matches found in {selection.label}.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
