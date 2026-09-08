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

def drain(game):
    while game.stack and not game.waiting_prompt():
        game.resolve_top_of_stack()

alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
game = Game(players=[alice, bob]); game.enforce_mana_costs = False
a = Permanent(card=usg["Opal Acrolith"])
game._put_permanent_onto_battlefield(0, a, None)
a.metadata["summoning_sickness_turn"] = -99
bob.hand[:] = [pool["Grizzly Bears"], pool["Hill Giant"]]
print("start:", a.is_creature, a.has_type("enchantment"), a.effective_power, a.effective_toughness)
game.cast_from_hand(1, "Grizzly Bears"); drain(game)
print("animated:", a.is_creature, a.has_type("enchantment"), a.effective_power, a.effective_toughness)
# {0}: becomes an enchantment
abilities = [ab.cost_text if hasattr(ab,'cost_text') else ab for ab in __import__("engine.oracle", fromlist=["x"]).compile_card_oracle(a.card).activated_abilities]
print("abilities:", abilities)
ok = game.activate_permanent_ability(0, "Opal Acrolith")
print("activate:", ok)
drain(game)
print("back:", a.is_creature, a.has_type("enchantment"), a.effective_power, a.effective_toughness)
game.cast_from_hand(1, "Hill Giant"); drain(game)
print("re-animated:", a.is_creature, a.has_type("enchantment"), a.effective_power, a.effective_toughness)
print(game.log[-8:])
