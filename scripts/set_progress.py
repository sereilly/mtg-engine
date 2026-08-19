"""Generate SET_PROGRESS.md — per-set card implementation tracker.

Lists Magic sets in chronological release order with total card counts,
new-card counts (first printings, i.e. cards not released in any earlier
set), and this engine's implementation state for each set:

- Not Implemented: the set holds no role in ``cards/manifest.json``.
- Measured: ingested under the manifest's ``measured`` role — its numbers
  are readable by the coverage instruments, but it is not shipped and no
  player can deck its cards.
- Partial: shipped, but not every card in the set is present and supported
  by the oracle compiler.
- Complete: every card in the set is present and supported.

Set metadata and counts come from the Scryfall API and are cached in
``set_progress.json`` at the repo root so re-renders work offline. Use
``--refresh`` to re-fetch from Scryfall (needed when a new set releases).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.card_loader import (
    load_cards,
    manifest_measured_codes,
    manifest_set_codes,
    manifest_set_path,
)
from engine.reporting import build_support_report

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = REPO_ROOT / "set_progress.json"
OUTPUT_PATH = REPO_ROOT / "SET_PROGRESS.md"

SCRYFALL_API = "https://api.scryfall.com"
USER_AGENT = "MTGSimulacrum-SetProgress/1.0"
REQUEST_DELAY_SECONDS = 0.11  # Scryfall asks for 50-100ms between requests

# The main chronological release line the engine implements set by set.
# Supplemental products (Commander decks, masters reprints, etc.) can be
# added here later if the engine ever targets them.
SET_TYPES = ("core", "expansion")

# Foreign-language and misprint reruns of existing editions — Scryfall types
# them as core sets, but they add nothing to implement.
EXCLUDED_CODES = {"fbb", "4bb", "sum"}


def _get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _search_count(query: str) -> int:
    """Return the number of unique cards matching a Scryfall search query."""
    params = urllib.parse.urlencode({"q": query, "unique": "cards"})
    time.sleep(REQUEST_DELAY_SECONDS)
    try:
        payload = _get_json(f"{SCRYFALL_API}/cards/search?{params}")
    except urllib.error.HTTPError as error:
        if error.code == 404:  # Scryfall returns 404 for zero-result searches
            return 0
        raise
    return int(payload["total_cards"])


def fetch_sets() -> list[dict]:
    """Fetch released paper core/expansion sets from Scryfall, oldest first."""
    payload = _get_json(f"{SCRYFALL_API}/sets")
    today = date.today().isoformat()
    sets = [
        entry
        for entry in payload["data"]
        if entry["set_type"] in SET_TYPES
        and entry["code"] not in EXCLUDED_CODES
        and not entry["digital"]
        and entry.get("released_at", "9999") <= today
        and entry.get("card_count", 0) > 0
    ]
    sets.sort(key=lambda entry: entry["released_at"])

    result = []
    for index, entry in enumerate(sets, start=1):
        code = entry["code"]
        total = _search_count(f"e:{code}")
        new = _search_count(f"e:{code} -is:reprint")
        result.append(
            {
                "code": code,
                "name": entry["name"],
                "released_at": entry["released_at"],
                "set_type": entry["set_type"],
                "total_cards": total,
                "new_cards": new,
            }
        )
        print(f"  [{index}/{len(sets)}] {entry['name']} ({code.upper()}): {total} cards, {new} new", flush=True)
    return result


def implementation_state(set_entry: dict) -> tuple[str, str]:
    """Return (state, detail) for one set, from the manifest role it holds.

    The role is read through ``engine.card_loader`` (the manifest's one
    reader), never from whether a card file sits on disk: an unregistered
    file is invisible to the web app and every coverage script, and a
    ``measured`` set is ingested but unshipped — its numbers must say so
    rather than read as shipped-pool ones.
    """
    code = set_entry["code"].upper()
    shipped = {c.upper() for c in manifest_set_codes()}
    measured = {c.upper() for c in manifest_measured_codes()}
    if code not in shipped and code not in measured:
        return "Not Implemented", ""

    cards = load_cards(manifest_set_path(code, include_measured=True))
    report = build_support_report(cards)
    total_in_set = set_entry["total_cards"]
    detail = f"{report.supported_cards}/{total_in_set} supported"
    if code in measured:
        return "Measured", f"{detail}, not shipped"
    if report.supported_cards >= total_in_set and report.unsupported_cards == 0:
        return "Complete", detail
    return "Partial", detail


def render_markdown(sets: list[dict], fetched_at: str) -> str:
    states = [implementation_state(entry) for entry in sets]
    complete = sum(1 for state, _ in states if state == "Complete")
    measured = sum(1 for state, _ in states if state == "Measured")
    partial = sum(1 for state, _ in states if state == "Partial")

    lines = [
        "# Set Implementation Progress",
        "",
        "Tracks card implementation across Magic sets in chronological release",
        "order. **New Cards** counts first printings — unique cards not released",
        "in any earlier set. Covers the main release line (core sets and",
        "expansions); supplemental products are out of scope.",
        "",
        f"Generated by `scripts/set_progress.py` (Scryfall data fetched {fetched_at}).",
        "Do not edit by hand — re-run the script instead.",
        "",
        f"**Progress: {complete} complete, {measured} measured, {partial} partial, "
        f"{len(sets) - complete - measured - partial} not implemented ({len(sets)} sets)**",
        "",
        "| # | Set | Code | Released | Cards | New Cards | Status |",
        "|--:|-----|------|----------|------:|----------:|--------|",
    ]
    for index, (entry, (state, detail)) in enumerate(zip(sets, states), start=1):
        status = state if not detail else f"{state} ({detail})"
        lines.append(
            f"| {index} | {entry['name']} | {entry['code'].upper()} | {entry['released_at']} "
            f"| {entry['total_cards']} | {entry['new_cards']} | {status} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="Re-fetch set data from Scryfall")
    args = parser.parse_args()

    if args.refresh or not CACHE_PATH.exists():
        print("Fetching set data from Scryfall...", flush=True)
        cache = {"fetched_at": date.today().isoformat(), "sets": fetch_sets()}
        CACHE_PATH.write_text(json.dumps(cache, indent=2) + "\n", encoding="utf-8")
        print(f"Cached set data to {CACHE_PATH.name}")
    else:
        cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))

    sets = [entry for entry in cache["sets"] if entry["code"] not in EXCLUDED_CODES]
    markdown = render_markdown(sets, cache["fetched_at"])
    OUTPUT_PATH.write_text(markdown, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH.name} ({len(sets)} sets)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
