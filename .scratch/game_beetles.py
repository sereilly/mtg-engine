import sys
sys.path.append("tests")
from engine import Game, PlayerState
from engine.models import Permanent
from engine.card_loader import load_cards, manifest_set_paths
from helpers import resolve_stack, _mk_creature_card

cards = {c.name: c for c in load_cards(manifest_set_paths(include_measured=True))}
p1, p2 = PlayerState(name="A"), PlayerState(name="B")
game = Game(players=[p1, p2])
game.enforce_mana_costs = False
beetles = Permanent(card=cards["Carrion Beetles"])
beetles.summoning_sick = False
p1.battlefield.append(beetles)
game._sync_control()
for i in range(4):
    p2.graveyard.append(_mk_creature_card(f"Corpse{i}", 1, 1))
print("p2 gy before:", [c.name for c in p2.graveyard])
res = game.activate_permanent_ability(0, "Carrion Beetles")
print("activate:", res.supported)
resolve_stack(game)
print("pending choices:", [(c.kind, getattr(c,'seat',None)) for c in game.pending_choices])
print("waiting_prompt:", game.waiting_prompt)
print("p2 gy after:", [c.name for c in p2.graveyard])
print("exiled:", [c.name for c in getattr(p2, 'exile', [])])
print("log:", game.log[-6:])
