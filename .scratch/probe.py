import sys
from engine.card_loader import load_cards, manifest_set_paths
from engine.oracle import compile_card_oracle, expand_ability_lines
from engine.grammar import parse_line
from engine.grammar.lower import lower_ability

paths = manifest_set_paths(include_measured=True)
cards = load_cards(paths)
by = {c.name: c for c in cards}
for n in sys.argv[1:]:
    c = by[n]
    print("="*70)
    print(n, "|", c.type_line)
    prog = compile_card_oracle(c)
    print("supported:", prog.supported, "reason:", prog.reason)
    for a in prog.activated_abilities:
        print("  ACT supported=%s kind=%s instr=%s" % (a.supported, a.effect_kind, a.instruction))
        print("      line:", a.source_line)
        print("      norm:", a.normalized_effect)
    for t in prog.triggered_abilities:
        print("  TRG supported=%s cond=%s instr=%s" % (t.supported, t.condition, t.instruction))
        print("      line:", t.source_line)
    print("  INSTR:", prog.instructions)
    print("  STATIC:", prog.static_lines)
    for line in expand_ability_lines(c.oracle_text or "", card_name=c.name).split("\n"):
        line = line.strip()
        if not line: continue
        print("--- LINE:", line)
        try:
            node = parse_line(line, card_name=c.name)
            print("    PARSED:", node)
            try:
                print("    LOWERED:", lower_ability(node))
            except Exception as e:
                print("    LOWER FAIL:", type(e).__name__, e)
        except Exception as e:
            print("    PARSE FAIL:", type(e).__name__, e)
