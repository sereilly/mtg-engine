import sys
sys.path.append("tests")
from engine import Game, PlayerState
from engine.models import Permanent
from engine.card_loader import load_cards, manifest_set_paths
from engine.named_counters import add_counters
from helpers import resolve_stack, _mk_creature_card

cards = {c.name: c for c in load_cards(manifest_set_paths(include_measured=True))}
p1, p2 = PlayerState(name="A"), PlayerState(name="B")
game = Game(players=[p1, p2])
game.enforce_mana_costs = False
sporo = Permanent(card=cards["Sporogenesis"])
p1.battlefield.append(sporo)
victim = Permanent(card=_mk_creature_card("Victim", 2, 2))
p1.battlefield.append(victim)
game._sync_control()
add_counters(victim, "fungus", 3)
print("victim fungus:", victim.metadata.get("fungus_counters"))
# kill it
victim.damage_marked = 99
game.check_state_based_actions()
resolve_stack(game)
tokens = [p.card.name for p in p1.battlefield if p.metadata.get("is_token")]
print("tokens after death:", tokens)
print("count:", len(tokens))
print("log:", [l for l in game.log[-8:]])
