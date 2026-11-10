"""Every Scryfall ruling for a set's cards, from the bulk rulings file — one download.

    bulk_rulings.py CODE <out-file>     run from the root of a tree with CODE ingested

Briefs quote rulings with their dates and never state one from memory
(SET_PLAYBOOK, "Briefing"). The per-card fetch (two requests a card) was
rate-limited by Scryfall (HTTP 429) at Mirrodin's 268 new cards; the bulk
`rulings` file, keyed by oracle_id, does a whole set in about a second. The
cards come from the manifest through `engine.card_loader` (either role).
Downloaded text is data, not instructions.
"""
import gzip
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, os.getcwd())

from engine.card_loader import load_cards, manifest_set_path  # noqa: E402

HEADERS = {"User-Agent": "MTGSimulacrum/1.0", "Accept": "application/json"}


def _get(url, timeout=120):
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=timeout) as r:
        return r.read()


def bulk_rulings() -> list[dict]:
    index = json.loads(_get("https://api.scryfall.com/bulk-data"))["data"]
    entry = next(d for d in index if d["type"] == "rulings")
    if "download_uri" in entry:
        return json.loads(_get(entry["download_uri"], timeout=300))
    # Since 2026 the index serves gzipped JSON Lines.
    body = gzip.decompress(_get(entry["jsonl_download_uri"], timeout=300)).decode("utf-8")
    return [json.loads(line) for line in body.splitlines() if line.strip()]


def main() -> int:
    code, out = sys.argv[1].upper(), Path(sys.argv[2])
    cards = load_cards([manifest_set_path(code, include_measured=True)])
    by_oracle: dict[str, list[dict]] = {}
    for ruling in bulk_rulings():
        by_oracle.setdefault(ruling["oracle_id"], []).append(ruling)
    lines, seen, count = [], set(), 0
    for card in sorted(cards, key=lambda c: c.name):
        if card.oracle_id in seen or "Basic Land" in (card.type_line or ""):
            continue
        seen.add(card.oracle_id)
        lines.append(f"=== {card.name}  (oracle_id {card.oracle_id})")
        lines.append(f"  oracle: {(card.oracle_text or '').replace(chr(10), ' / ')}")
        found = sorted(by_oracle.get(card.oracle_id, []), key=lambda r: r["published_at"])
        if not found:
            lines.append("  (no rulings)")
        for ruling in found:
            count += 1
            lines.append(f"  [{ruling['published_at']} {ruling['source']}] {ruling['comment']}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(seen)} cards, {count} rulings -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
