import sys
sys.path.insert(0, ".")
from engine.card_loader import load_cards, manifest_set_paths
from engine.oracle import compile_card_oracle
import pprint

cards = load_cards(manifest_set_paths(include_measured=True))
by = {c.name: c for c in cards}
for n in sys.argv[1:]:
    c = by.get(n)
    if c is None:
        print("MISSING", n); continue
    prog = compile_card_oracle(c)
    print("="*70)
    print(n, "|", c.type_line, "|", c.mana_cost)
    print("TEXT:", c.oracle_text)
    print("supported:", prog.supported)
    for i in prog.instructions:
        pprint.pprint(i)
    for a in prog.activated_abilities:
        print("  ACT cost:", a.cost)
        pprint.pprint(a.instruction)
    for t in prog.triggered_abilities:
        print("  TRG:", t.condition)
        pprint.pprint(t.instruction)
    print("static:", prog.static_lines)
