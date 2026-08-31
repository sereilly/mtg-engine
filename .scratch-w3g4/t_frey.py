import sys
sys.path.insert(0, ".")
from engine import Game
from engine.models import Permanent, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.named_counters import counters_on
from engine.pt import add_pt_modifier

cards = load_cards(manifest_set_paths(include_measured=True))
pool = {c.name: c for c in cards}
print([c.name for c in cards if c.name in ("Balduvian Bears",)])

def board(fodder_name, boost=0):
    supp = Permanent(card=pool["Freyalise Supplicant"])
    supp.metadata["summoning_sickness_turn"] = -99
    fodder = Permanent(card=pool[fodder_name])
    fodder.metadata["summoning_sickness_turn"] = -99
    p0 = PlayerState(name="P0", battlefield=[supp, fodder], life=20)
    p1 = PlayerState(name="P1", life=20)
    g = Game(players=[p0, p1])
    g.enforce_mana_costs = False
    g.active_player_index = 0
    g.current_turn_phase, g.current_step = "precombat_main", "precombat_main"
    if boost:
        add_pt_modifier(fodder, boost, 0, source="test")
        g._settle()
    return g, p0, p1, supp, fodder

# find a red or white creature in ICE
reds = [c.name for c in cards if 'creature' in c.type_line.lower() and set(c.colors or ())&{'R','W'} and (c.power or '').isdigit()]
print(reds[:12])
for name in ("Brothers of Fire",):
    pass

g, p0, p1, supp, fodder = board("Goblin Mutant")
print("fodder power", fodder.effective_power)
r = g.queue_permanent_ability(0, "Freyalise Supplicant", target_player_index=1, permanent_index=0,
                              cost_permanent_index=1)
g._settle()
print(r)
print("P1", p1.life, "log", g.log[-5:])
