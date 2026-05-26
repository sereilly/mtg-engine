"""Retrieve oracle text for a Magic card from lea_cards.json.

Usage:
    python scripts/retrieve_oracle.py "Black Lotus"
    python scripts/retrieve_oracle.py "lotus" --mode substring
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
from typing import Dict, List, Optional, Tuple, Any


def _load_cards(path: str = "lea_cards.json") -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    # Accept either a list at top-level, or a dict containing common keys
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # common variants: {"cards": [...]} or {"data": [...]}
        for key in ("cards", "data", "cards_list"):
            if key in data and isinstance(data[key], list):
                return data[key]
        # fallback: try to collect list-like values
        for v in data.values():
            if isinstance(v, list):
                return v
    raise ValueError("Unrecognized JSON structure for card data")


def retrieve_oracle_text(
    name: str,
    cards: List[Dict[str, Any]],
    mode: Optional[str] = None,
    max_candidates: int = 5,
    fuzzy_cutoff: float = 0.6,
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    norm = name.strip()
    # 1. exact
    if mode in (None, "exact"):
        for c in cards:
            if c.get("name") == norm:
                return c, []
    # 2. case-insensitive exact
    if mode in (None, "ci", "case_insensitive"):
        for c in cards:
            if c.get("name", "").lower() == norm.lower():
                return c, []
    # 3. substring
    if mode in (None, "substring"):
        candidates = [c for c in cards if norm.lower() in c.get("name", "").lower()]
        if len(candidates) == 1:
            return candidates[0], []
        if candidates:
            return None, [c.get("name") for c in candidates[:max_candidates]]
    # 4. fuzzy
    if mode in (None, "fuzzy"):
        names = [c.get("name") for c in cards]
        close = difflib.get_close_matches(norm, names, n=max_candidates, cutoff=fuzzy_cutoff)
        if len(close) == 1:
            # return the card dict for the single close match
            match_name = close[0]
            for c in cards:
                if c.get("name") == match_name:
                    return c, []
        return None, close

    return None, []


def _print_card(card: Dict[str, Any]) -> None:
    print(f"Name: {card.get('name')}")
    print(f"Type: {card.get('type_line')}")
    mc = card.get('mana_cost')
    if mc:
        print(f"Mana cost: {mc}")
    print("Oracle text:")
    print(card.get("oracle_text", ""))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Retrieve oracle text from lea_cards.json by card name")
    parser.add_argument("name", help="Card name to search for")
    parser.add_argument("--mode", choices=["exact", "ci", "substring", "fuzzy"], help="Match mode to use")
    parser.add_argument("--file", default="lea_cards.json", help="Path to the card JSON file")
    parser.add_argument("--max-candidates", type=int, default=8, help="Maximum candidates to show for non-unique matches")
    args = parser.parse_args(argv)

    try:
        cards = _load_cards(args.file)
    except Exception as e:
        print(f"Error loading cards from {args.file}: {e}", file=sys.stderr)
        return 2

    card, candidates = retrieve_oracle_text(args.name, cards, mode=args.mode, max_candidates=args.max_candidates)

    if card:
        _print_card(card)
        return 0

    if candidates:
        print("Multiple or close matches found:")
        for i, n in enumerate(candidates, start=1):
            print(f"  {i}. {n}")
        print("Use a more specific name or --mode to change matching strategy.")
        return 3

    print("No matches found.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
