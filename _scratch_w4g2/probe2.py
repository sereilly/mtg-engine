import sys
sys.path.insert(0, '.')
from engine.card_loader import load_cards
from engine.oracle import compile_card_oracle
import json
cards = load_cards(['cards/ICE_cards.json'])
by = {c.name: c for c in cards}
for n in ('Gaze of Pain',):
    p = compile_card_oracle(by[n])
    print('===', n, p.supported)
    for i in p.instructions:
        print('  ', i.kind, i.value, json.dumps(i.payload, default=str)[:1200])
