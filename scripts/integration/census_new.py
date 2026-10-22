"""A just-ingested set against the shipped pool (SET_PLAYBOOK Phase 1).

    census_new.py CODE        run from the root of a tree with CODE ingested

Prints which of its cards are **new to this pool** (every one goes to a
group, supported or not — "arrived supported" has not been driven), which
share a name but not an oracle_id, which are unsupported, and **the origin
trap**: reprints whose only other printings here are *later* than the set,
so the set's insert position decides their `original_printing`. Stronghold's
Shock, Urza's Saga's three and Planeshift's Quirion Dryad were each one card
the prefix guard could not see. Then each new or unsupported card's text, and
the layouts the set uses (a new layout makes guards blind, not red).
"""
import os
import sys
from collections import Counter

sys.path.insert(0, os.getcwd())

from engine.card_loader import (load_cards, manifest_measured_sets,  # noqa: E402
                                manifest_set_path, manifest_sets)
from engine.oracle import compile_card_oracle  # noqa: E402

code = sys.argv[1].upper()
shipped = manifest_sets()
released = {s["code"].upper(): s["released"] for s in shipped}
entry = next((s for s in manifest_measured_sets() + shipped if s["code"].upper() == code), None)
assert entry, f"{code} is in neither manifest role"
set_date = entry["released"]

by_oracle: dict = {}
by_name: dict = {}
for s in shipped:
    if s["code"].upper() == code:
        continue
    for card in load_cards([manifest_set_path(s["code"])]):
        by_oracle.setdefault(card.oracle_id, []).append(s["code"].upper())
        by_name.setdefault(card.name, []).append(s["code"].upper())

cards = load_cards([manifest_set_path(code, include_measured=True)])
new, later_only, name_only = [], [], []
seen = set()
for card in cards:
    if card.oracle_id in seen:
        continue
    seen.add(card.oracle_id)
    printed_in = by_oracle.get(card.oracle_id, [])
    if not printed_in:
        new.append(card.name)
        if card.name in by_name:
            name_only.append((card.name, by_name[card.name]))
        continue
    if all(released[c] > set_date for c in printed_in):
        later_only.append((card.name, sorted(set(printed_in))))

print(f"{code} unique cards: {len(seen)}; released {set_date}")
print(f"new to the pool ({len(new)}): {sorted(new)}")
print(f"same name, different oracle_id: {name_only}")
print(f"reprints whose only other printings are LATER than {code} ({len(later_only)}): {later_only}")
unsupported = [c.name for c in cards if not compile_card_oracle(c).supported]
print(f"unsupported ({len(unsupported)}): {unsupported}")
for c in cards:
    if c.name in new or c.name in unsupported:
        print(f"--- {c.name} [{c.type_line}] {c.mana_cost}\n    " + (c.oracle_text or "").replace("\n", "\n    "))
print("layouts:", dict(Counter(c.layout for c in cards)))
