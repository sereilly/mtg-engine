"""Helper script to find LEA cards with no dedicated functional tests."""
import re
from engine import load_cards

with open("tests/test_lea_cards.py", "r", encoding="utf-8") as f:
    lea_content = f.read()
with open("tests/test_alpha_individual_cards.py", "r", encoding="utf-8") as f:
    alpha_content = f.read()

combined = lea_content + alpha_content

# _get(all_cards, 'Card Name')
tested = set(re.findall(r'_get\(all_cards,\s*["\']([^"\']+)["\']', combined))
# next(c for c in all_cards if c.name == 'Card Name')
tested |= set(re.findall(r'c\.name == ["\']([^"\']+)["\']', combined))
# explicit name strings in names = [ ... ]
tested |= set(re.findall(r'"([^"]+)"', combined))

from pathlib import Path
all_cards = load_cards(Path("lea_cards.json"))

untested = [c for c in all_cards if c.name not in tested]
print(f"Tested: {len(tested)}, Total LEA: {len(all_cards)}, Untested: {len(untested)}")
print()
print("First 10 untested cards:")
for c in untested[:10]:
    print(f"  {c.name!r} | {c.type_line} | {c.oracle_text[:80] if c.oracle_text else ''}")
