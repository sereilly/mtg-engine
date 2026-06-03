import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from engine import load_cards
from engine.oracle import compile_card_oracle

from pathlib import Path
root = Path(__file__).resolve().parent.parent
lea_path = root / "lea_cards.json"
cards = load_cards(lea_path)
fire = next(c for c in cards if c.name=='Fireball')
prog = compile_card_oracle(fire)
print('oracle_text:', fire.oracle_text)
print('instructions:')
for instr in prog.instructions:
    print(instr)
print('activated:', prog.activated_abilities)
print('triggered:', prog.triggered_abilities)
