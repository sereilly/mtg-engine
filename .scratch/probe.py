import sys
from engine.card_loader import load_cards, manifest_set_path
cards = load_cards(manifest_set_path('ICE', include_measured=True))
by = {c.name: c for c in cards}
from engine.oracle import compile_card_oracle, expand_ability_lines
for n in sys.argv[1:]:
    c = by[n]
    p = compile_card_oracle(c)
    print('====', n, '| supported:', p.supported, '|', p.reason)
    print(' lines:')
    for l in expand_ability_lines(c.oracle_text):
        print('   -', repr(l))
    print(' instructions:', p.instructions)
    print(' activated:')
    for a in p.activated_abilities:
        print('   -', a)
    print(' triggered:')
    for t in p.triggered_abilities:
        print('   -', t)
    print(' statics:', p.static_lines)
