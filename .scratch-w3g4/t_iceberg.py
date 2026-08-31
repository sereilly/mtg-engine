import sys
sys.path.insert(0, ".")
from engine import Game
from engine.models import Permanent, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.named_counters import counters_on

cards = load_cards(manifest_set_paths(include_measured=True))
pool = {c.name: c for c in cards}

p0 = PlayerState(name="P0", hand=[pool["Iceberg"]], life=20)
g = Game(players=[p0, PlayerState(name="P1", life=20)])
g.enforce_mana_costs = False
g.active_player_index = 0
g.current_turn_phase, g.current_step = "precombat_main", "precombat_main"
g.cast_from_hand(0, "Iceberg", x_value=3)
g._settle()
berg = p0.battlefield[0]
print("counters:", counters_on(berg, "ice"))
berg.metadata["summoning_sickness_turn"] = -99
g.activate_permanent_ability(0, "Iceberg", permanent_index=0, ability_index=1)
g._settle()
print("after tapping for mana:", counters_on(berg, "ice"), p0.mana_pool)
print(g.log[-4:])

# X=0 enters with nothing
p0b = PlayerState(name="P0", hand=[pool["Iceberg"]], life=20)
g2 = Game(players=[p0b, PlayerState(name="P1", life=20)])
g2.enforce_mana_costs = False
g2.active_player_index = 0
g2.current_turn_phase, g2.current_step = "precombat_main", "precombat_main"
g2.cast_from_hand(0, "Iceberg", x_value=0)
g2._settle()
print("x=0 counters:", counters_on(p0b.battlefield[0], "ice"))
