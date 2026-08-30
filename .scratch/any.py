import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from engine.card_loader import load_cards, manifest_set_paths
from engine.oracle import compile_card_oracle, expand_ability_lines, normalize_creature_line, keyword_line_triggers
from engine.grammar import compile_line
cards = []
for p in manifest_set_paths(include_measured=True):
    cards.extend(load_cards(p))
by = {}
for c in cards: by.setdefault(c.name, c)
for n in sys.argv[1:]:
    c = by[n]
    p = compile_card_oracle(c)
    print('====', n, '|', c.type_line, '| supported:', p.supported, '|', p.reason)
    for raw in expand_ability_lines(c.oracle_text, card_name=c.name).splitlines():
        line = raw.strip()
        if not line: continue
        norm = normalize_creature_line(line)
        cl = compile_line(norm, card_name=c.name)
        print('  LINE:', repr(norm))
        print('    parsed:', cl.parsed, '| lowered:', cl.lowered, '| usable:', cl.usable, '| err:', cl.failure_reason)
        for i in cl.instructions: print('    instr:', i)
    print('  instructions:', p.instructions)
    for a in p.activated_abilities: print('  ACT:', a)
    for t in p.triggered_abilities: print('  TRIG:', t)
    print('  statics:', p.static_lines)
