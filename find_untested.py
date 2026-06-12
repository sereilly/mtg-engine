"""Helper script to find LEA cards with no dedicated functional tests."""
import re
from engine import load_cards

with open("tests/test_lea_cards.py", "r", encoding="utf-8") as f:
    lea_content = f.read()
with open("tests/test_alpha_individual_cards.py", "r", encoding="utf-8") as f:
    alpha_content = f.read()

combined = lea_content + alpha_content

from pathlib import Path
all_cards = load_cards(Path("lea_cards.json"))

# Substring search per card name. (Extracting quoted strings with a regex is
# unreliable: a single unpaired quote anywhere flips the pairing for the rest
# of the file, and names containing apostrophes break ["'] character classes.)
untested = [c for c in all_cards if c.name not in combined]
print(f"Total LEA: {len(all_cards)}, Untested: {len(untested)}")
print()
print("First 10 untested cards:")
for c in untested[:10]:
    print(f"  {c.name!r} | {c.type_line} | {c.oracle_text[:80] if c.oracle_text else ''}")
