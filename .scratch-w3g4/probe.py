import sys, json
sys.path.insert(0, ".")
from engine.card_loader import load_cards, manifest_set_path
from engine.oracle import compile_card_oracle

names = ["Goblin Lyre","Game of Chaos","Amulet of Quoz","Ice Cauldron","Freyalise Supplicant","Iceberg","Drought"]
cards = load_cards([manifest_set_path("ICE", include_measured=True)])
by = {c.name: c for c in cards}
for n in names:
    c = by.get(n)
    if c is None:
        print("MISSING", n); continue
    prog = compile_card_oracle(c)
    print("="*70)
    print(n, "|", c.type_line, "|", c.mana_cost)
    print("TEXT:", repr(c.oracle_text))
    print("supported:", prog.supported, "reason:", getattr(prog, "unsupported_reason", None))
    print("instructions:", [getattr(i,'kind',i) for i in prog.instructions])
    print("activated:", len(prog.activated_abilities))
    for a in prog.activated_abilities:
        print("   ACT:", a)
    print("triggered:", len(prog.triggered_abilities))
    for t in prog.triggered_abilities:
        print("   TRG:", t)
    print("static:", prog.static_lines)
