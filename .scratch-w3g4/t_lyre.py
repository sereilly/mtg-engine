import sys
sys.path.insert(0, ".")
from unittest.mock import patch
from engine import Game
from engine.models import Permanent, PlayerState
from engine.card_loader import load_cards, manifest_set_paths

cards = load_cards(manifest_set_paths(include_measured=True))
pool = {c.name: c for c in cards}

def board():
    lyre = Permanent(card=pool["Goblin Lyre"])
    lyre.metadata["summoning_sickness_turn"] = -99
    mine = [Permanent(card=pool["Balduvian Bears"]) for _ in range(2)]
    theirs = [Permanent(card=pool["Balduvian Bears"]) for _ in range(3)]
    p0 = PlayerState(name="P0", battlefield=[lyre, *mine], life=20)
    p1 = PlayerState(name="P1", battlefield=list(theirs), life=20)
    g = Game(players=[p0, p1])
    g.enforce_mana_costs = False
    g.active_player_index = 0
    g.current_turn_phase, g.current_step = "precombat_main", "precombat_main"
    return g, p0, p1

for label, roll in (("win", 0.0), ("lose", 0.99)):
    g, p0, p1 = board()
    with patch("engine.handlers._common.random.random", return_value=roll):
        r = g.queue_permanent_ability(0, "Goblin Lyre", target_player_index=1, permanent_index=0)
        g._settle()
    print(label, "result=", r)
    print("  P0", p0.life, "P1", p1.life)
    print("  log:", g.log[-6:])
