import sys
sys.path.insert(0, ".")
from engine.card_loader import load_cards, manifest_set_path
from engine.oracle import compile_card_oracle
NAMES = ["Hidden Ancients","Hidden Guerrillas","Hidden Herd","Hidden Predators","Hidden Spider","Hidden Stag","Opal Acrolith","Opal Archangel","Opal Caryatid","Opal Gargoyle","Opal Titan","Veil of Birds","Veiled Apparition","Veiled Crocodile","Veiled Sentry","Veiled Serpent","Soul Sculptor","Chimeric Staff","Lurking Evil","Karn, Silver Golem"]
pool = {c.name: c for c in load_cards(manifest_set_path("USG", include_measured=True))}
for n in NAMES:
    p = compile_card_oracle(pool[n])
    print(f"{'SUP ' if p.supported else 'UNS '} {n:22s} {p.reason or ''}")
