import sys
sys.path.insert(0, ".")
from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_path, manifest_set_paths
from engine.models import Permanent
usg = {c.name: c for c in load_cards(manifest_set_path("USG", include_measured=True))}
pool = {}
for p in manifest_set_paths():
    for c in load_cards(p):
        pool.setdefault(c.name, c)

alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
game = Game(players=[alice, bob]); game.enforce_mana_costs = False
g = Permanent(card=usg["Opal Gargoyle"])
game._put_permanent_onto_battlefield(0, g, None)
print("before:", g.is_creature, g.has_type("enchantment"), g.effective_power, g.effective_toughness, g.has_keyword("flying"))
bob.hand[:] = [pool["Grizzly Bears"], pool["Lightning Bolt"]]
game.cast_from_hand(1, "Grizzly Bears")
while game.stack and not game.waiting_prompt():
    game.resolve_top_of_stack()
print("after:", g.is_creature, g.has_type("enchantment"), g.effective_power, g.effective_toughness, g.has_keyword("flying"))
print("subtypes:", g.effective_card.type_line, [t for t in dir(g) if 'subtype' in t])
from engine.layer_bridge import displayed_type_line

print("log:", game.log[-4:])
print("type line:", displayed_type_line(g))
print("gargoyle?", g.has_type("gargoyle"))
n = len(game.log)
game.cast_from_hand(1, "Lightning Bolt", target_player_index=0)
while game.stack and not game.waiting_prompt():
    game.resolve_top_of_stack()
print("after bolt:", g.is_creature, g.effective_power)
print("stack size:", len(game.stack))
print("log tail:", game.log[n:])
