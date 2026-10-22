"""One line per card of a set: status, type, cost and text — the grouping sheet.

    card_table.py CODE <census-dir>     run from the root of a tree with CODE ingested

<census-dir> holds `<code>_parse.log` (`parse_coverage.py --set CODE`). Flags:
U = unsupported, P = supported with an unclaimed sentence, . = supported and
quiet (which is not the same as working: Phase 1 drives those).
"""
import os
import re
import sys

sys.path.insert(0, os.getcwd())

from engine.card_loader import load_cards, manifest_set_path  # noqa: E402
from engine.oracle import compile_card_oracle  # noqa: E402

code, census = sys.argv[1].upper(), sys.argv[2]
with open(os.path.join(census, f"{code.lower()}_parse.log"), encoding="utf-8") as fh:
    parse_log = fh.read().splitlines()
unclaimed = {line.strip() for line in parse_log[2:] if line and not line.startswith(" ")}

cards = sorted(load_cards([manifest_set_path(code, include_measured=True)]),
               key=lambda c: (c.type_line, c.name))
for card in cards:
    program = compile_card_oracle(card)
    flag = "U" if not program.supported else ("P" if card.name in unclaimed else ".")
    text = re.sub(r"\([^)]*\)", "", card.oracle_text or "").replace("\n", " / ")
    print(f"{flag} {card.name} | {card.type_line} | {card.mana_cost} | {text}")
