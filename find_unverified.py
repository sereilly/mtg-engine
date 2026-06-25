"""List LEA cards that are untested or failing per card_verification.json.

"Untested" = no pass/fail entry recorded; "fail" = manually marked failing
in-game. (The verification JSON only stores pass/fail; everything else is
untested.) See CARD_VERIFICATION.md for the human-readable tracker.
"""
import json
from pathlib import Path

from engine import load_cards

all_cards = load_cards(Path("lea_cards.json"))

with open("card_verification.json", "r", encoding="utf-8") as f:
    results = json.load(f).get("results", {})

untested, failed = [], []
for card in all_cards:
    entry = results.get(card.name)
    status = entry.get("status") if entry else None
    if status == "fail":
        failed.append((card.name, entry.get("reason", "")))
    elif status != "pass":
        untested.append(card.name)

print(f"Total LEA: {len(all_cards)}, Failed: {len(failed)}, Untested: {len(untested)}")
print()
print(f"Failed ({len(failed)}):")
for name, reason in sorted(failed):
    print(f"  {name}" + (f" | {reason}" if reason else ""))
print()
print(f"Untested ({len(untested)}):")
for name in sorted(untested):
    print(f"  {name}")
