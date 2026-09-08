import sys, json
sys.path.insert(0, ".")
from engine.card_loader import load_cards, manifest_set_paths
from engine.oracle import compile_card_oracle
paths = manifest_set_paths(include_measured=True)
cards = load_cards(paths)
seen = []
def walk(p, out):
    if not isinstance(p, dict): return
    if "intervening_if" in p: out.append(p["intervening_if"])
    for v in p.values():
        if isinstance(v, dict): walk(v, out)
        elif isinstance(v, (list, tuple)):
            for x in v:
                if isinstance(x, dict): walk(x, out)
                elif hasattr(x, "payload"): walk(x.payload, out)
for c in cards:
    prog = compile_card_oracle(c)
    for t in prog.triggered_abilities:
        if t.instruction is None: continue
        out = []
        walk(t.instruction.payload, out)
        if out:
            seen.append((c.name, t.source_line, out[0].get("kind")))
print(len(seen))
for n, l, k in seen:
    print(f"{n} | {k} | {l[:90]}")
