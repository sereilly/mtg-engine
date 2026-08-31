import sys
sys.path.insert(0, '.')
from engine import Game
from engine.card_loader import manifest_set_path, load_cards
from engine.models import Permanent, PlayerState
from engine.targeting import derive_activation_spec
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick

pool = {c.name: c for c in load_cards(manifest_set_path("ICE", include_measured=True))}
prog = compile_card_oracle(pool["General Jarkeld"])
ab = prog.activated_abilities[0]
print("spec:", derive_activation_spec(ab))

a1 = _nosick(Permanent(card=pool["Balduvian Bears"]))
a2 = _nosick(Permanent(card=pool["Tor Giant"]))
b1 = _nosick(Permanent(card=pool["Balduvian Barbarians"]))
jark = _nosick(Permanent(card=pool["General Jarkeld"]))
g = Game(players=[
    PlayerState(name="P1", battlefield=[a1, a2], life=20),
    PlayerState(name="P2", battlefield=[b1, jark], life=20),
])
g.enforce_mana_costs = False
g._sync_control()
g.active_player_index = 0
g._set_phase_and_step("combat", "declare_attackers")
g.declare_attackers(0, [0, 1], 1)
g._set_phase_and_step("combat", "declare_blockers")
g.declare_blockers(1, {0: 0})
spec = derive_activation_spec(ab)
print("enumerate:", g._enumerate_targets(1, spec))
from engine.legality import activation_target_refusal
print("refusal(none):", g.activation_target_refusal(1, jark, ab, None, None) if hasattr(g,'activation_target_refusal') else 'n/a')
