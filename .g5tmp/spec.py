import sys
from engine.card_loader import load_cards, manifest_set_paths
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec, derive_cast_spec
cards = {}
for p in manifest_set_paths(include_measured=True):
    for c in load_cards(p):
        cards.setdefault(c.name, c)
for name in sys.argv[1:]:
    c = cards[name]
    prog = compile_card_oracle(c)
    print(name, "cast:", derive_cast_spec(c, prog))
    for i, a in enumerate(prog.activated_abilities):
        print("   act", i, derive_activation_spec(a))
