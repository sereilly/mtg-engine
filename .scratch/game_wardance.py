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
dance = Permanent(card=cards["War Dance"])
p1.battlefield.append(dance)
game.register_permanent(dance) if hasattr(game, "register_permanent") else None
bear = Permanent(card=_mk_creature_card("Bear", 2, 2))
p1.battlefield.append(bear)
game._sync_control()
for p in p1.battlefield:
    print(" perm", p.card.name, "id", getattr(p, "permanent_id", None))
add_counters(dance, "verse", 3)
print("verse counters:", dance.metadata.get("verse_counters"))
print("bear P/T before:", bear.effective_power, bear.effective_toughness)
res = game.activate_permanent_ability(0, "War Dance", target_permanent_ids=[bear.permanent_id])
print("activate supported:", res.supported, res.description if hasattr(res,'description') else '')
resolve_stack(game)
print("bear P/T after:", bear.effective_power, bear.effective_toughness)
print("dance on bf:", dance in p1.battlefield, "graveyard:", [c.name for c in p1.graveyard])
