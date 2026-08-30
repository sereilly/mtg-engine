import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from engine.card_loader import load_cards, manifest_set_path
from engine.oracle import (compile_card_oracle, expand_ability_lines,
                           normalize_creature_line, keyword_line_triggers)
from engine.grammar import compile_line
cards = load_cards(manifest_set_path('ICE', include_measured=True))
by = {c.name: c for c in cards}
for n in sys.argv[1:]:
    c = by[n]
    p = compile_card_oracle(c)
    print('====', n, '|', c.type_line, '| supported:', p.supported, '|', p.reason)
    text = expand_ability_lines(c.oracle_text, card_name=c.name)
    for raw in text.splitlines():
        line = raw.strip()
        if not line: continue
        norm = normalize_creature_line(line)
        kw = keyword_line_triggers(norm)
        cl = compile_line(norm, card_name=c.name)
        print('  LINE:', repr(line))
        print('    norm:', repr(norm))
        print('    kwtrig:', len(kw), '| parsed:', cl.parsed, '| lowered:', cl.lowered,
              '| usable:', cl.usable, '| err:', cl.failure_reason)
        if cl.parsed:
            print('    node:', cl.node)
        for i in cl.instructions:
            print('    instr:', i)
    print('  PROGRAM instructions:', p.instructions)
    print('  PROGRAM activated:')
    for a in p.activated_abilities: print('    ', a)
    print('  PROGRAM triggered:')
    for t in p.triggered_abilities: print('    ', t)
    print('  PROGRAM statics:', p.static_lines)
    print()
