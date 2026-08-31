import sys
sys.path.insert(0, ".")
from engine import Game
from engine.models import Permanent, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.pt import add_pt_modifier

cards = load_cards(manifest_set_paths(include_measured=True))
pool = {c.name: c for c in cards}

def run(boost=0, fodder_name="Balduvian Barbarians"):
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
        add_pt_modifier(fodder, boost, 0)
    g._settle()
    print("power", fodder.effective_power)
    g.queue_permanent_ability(0, "Freyalise Supplicant", target_player_index=1, permanent_index=0, cost_permanent_index=1)
    g._settle()
    print("boost", boost, "-> P1 life", p1.life, "| tapped", supp.tapped, "| graveyard", [c.name for c in p0.graveyard])

run(0)
run(1)
# a green creature must not be eatable
supp = Permanent(card=pool["Freyalise Supplicant"]); supp.metadata["summoning_sickness_turn"]=-99
bears = Permanent(card=pool["Balduvian Bears"]); bears.metadata["summoning_sickness_turn"]=-99
p0 = PlayerState(name="P0", battlefield=[supp, bears], life=20)
g = Game(players=[p0, PlayerState(name="P1", life=20)])
g.enforce_mana_costs = False
g.active_player_index = 0
g.current_turn_phase, g.current_step = "precombat_main", "precombat_main"
r = g.queue_permanent_ability(0, "Freyalise Supplicant", target_player_index=1, permanent_index=0, cost_permanent_index=1)
g._settle()
print("green fodder ->", r, g.players[1].life, [c.name for c in p0.graveyard])
