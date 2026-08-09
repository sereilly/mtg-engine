"""Fetch the Magic vocabulary catalogs the oracle grammar parses against.

The grammar in ``engine/grammar/`` classifies nouns (creature types, land
types, supertypes) and keywords from *data*, not from hardcoded tuples — a
4-entry ``KNOWN_CREATURE_SUBTYPES`` cannot describe a 30,000-card pool. The
catalogs come from Scryfall and are committed under ``data/vocabulary/`` so the
engine never touches the network at import time.

Re-run after a set release introduces new types::

    python scripts/fetch_vocabulary.py

``data/vocabulary/manifest.json`` records the source endpoint, fetch date, and
per-catalog counts so a stale vocabulary is visible in a diff.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "data" / "vocabulary"

SCRYFALL_API = "https://api.scryfall.com"
USER_AGENT = "MTGSimulacrum-Vocabulary/1.0"
REQUEST_DELAY_SECONDS = 0.11  # Scryfall asks for 50-100ms between requests

# Scryfall catalog endpoint -> output filename (without .json).
CATALOGS: dict[str, str] = {
    "creature-types": "creature_types",
    "land-types": "land_types",
    "artifact-types": "artifact_types",
    "enchantment-types": "enchantment_types",
    "planeswalker-types": "planeswalker_types",
    "spell-types": "spell_types",
    "supertypes": "supertypes",
    "keyword-abilities": "keyword_abilities",
    "keyword-actions": "keyword_actions",
    "ability-words": "ability_words",
}

# Card types are a closed set the API does not expose as a catalog.
CARD_TYPES: tuple[str, ...] = (
    "artifact", "battle", "creature", "enchantment", "instant", "kindred",
    "land", "planeswalker", "sorcery", "tribal",
)


def _get_json(url: str) -> dict:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _write(name: str, values: list[str]) -> int:
    """Write one catalog as a sorted, lowercased JSON list. Sorting keeps the
    committed file diff-stable across fetches."""
    cleaned = sorted({value.lower() for value in values})
    path = OUTPUT_DIR / f"{name}.json"
    path.write_text(json.dumps(cleaned, indent=2) + "\n", encoding="utf-8")
    return len(cleaned)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true",
        help="verify the committed catalogs load and are non-empty (no network)",
    )
    args = parser.parse_args()

    if args.check:
        missing = [
            name for name in (*CATALOGS.values(), "card_types")
            if not (OUTPUT_DIR / f"{name}.json").exists()
        ]
        if missing:
            print(f"FAIL: missing vocabulary catalogs: {', '.join(missing)}")
            return 1
        print(f"OK: {len(CATALOGS) + 1} vocabulary catalogs present")
        return 0

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}

    for endpoint, name in CATALOGS.items():
        time.sleep(REQUEST_DELAY_SECONDS)
        payload = _get_json(f"{SCRYFALL_API}/catalog/{endpoint}")
        counts[name] = _write(name, payload["data"])
        print(f"{name}: {counts[name]}")

    counts["card_types"] = _write("card_types", list(CARD_TYPES))
    print(f"card_types: {counts['card_types']}")

    manifest = {
        "source": f"{SCRYFALL_API}/catalog/<name>",
        "fetched_at": date.today().isoformat(),
        "counts": dict(sorted(counts.items())),
    }
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\nWrote {len(counts)} catalogs to {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
