import sys
from engine.card_loader import load_cards, manifest_set_paths
from engine.oracle import compile_card_oracle
cards = {}
for p in manifest_set_paths(include_measured=True):
    for c in load_cards(p):
        cards.setdefault(c.name, c)
for name in sys.argv[1:]:
    c = cards.get(name)
    if c is None:
        print("NOT FOUND", name); continue
    prog = compile_card_oracle(c)
    print("=== %s === supported=%s reason=%s" % (name, prog.supported, prog.reason))
    for i in prog.instructions:
        print("  instr", i.kind, i.payload)
    for a in prog.activated_abilities:
        print("  act cost=%r" % (a.cost,))
        if a.instruction is not None:
            print("      ->", a.instruction.kind, a.instruction.payload)
    for t in prog.triggered_abilities:
        print("  trig", getattr(t, 'condition', None))
        if getattr(t, 'instruction', None) is not None:
            print("      ->", t.instruction.kind, t.instruction.payload)
    for sl in prog.static_lines:
        print("  static:", sl)
