import sys
sys.path.insert(0, '.')
from engine import Game
from engine.card_loader import manifest_set_path, load_cards
from engine.models import Permanent, PlayerState
from tests.helpers import _nosick

pool = {c.name: c for c in load_cards(manifest_set_path("ICE", include_measured=True))}


def board(hand=()):
    a1 = _nosick(Permanent(card=pool["Balduvian Bears"]))
    a2 = _nosick(Permanent(card=pool["Tor Giant"]))
    b1 = _nosick(Permanent(card=pool["Brown Ouphe"]))
    g = Game(players=[
        PlayerState(name="P1", battlefield=[a1, a2], life=20,
                    hand=[pool[n] for n in hand]),
        PlayerState(name="P2", battlefield=[b1], life=20),
    ])
    g.enforce_mana_costs = False
    g._sync_control()
    g.active_player_index = 0
    return g, a1, a2, b1


g, a1, a2, b1 = board(hand=("Melee",))
g._set_phase_and_step("combat", "beginning_of_combat")
print("cast Melee:", g.cast_from_hand(0, "Melee"))
g.resolve_stack()
print("chooser:", g.combat_block_chooser)
g._set_phase_and_step("combat", "declare_attackers")
print("attack:", g.declare_attackers(0, [0, 1], 1))
g._set_phase_and_step("combat", "declare_blockers")
print("defender declares:", g.declare_blockers(1, {0: 0}))
print("melee caster declares:", g.declare_blockers(1, {0: 0}, acting_index=0))
print("blockers:", g.combat_blockers, "locked:", g.combat_blockers_locked)
g.advance_combat_phase()
print("after advance: step", g.current_step, "| stack", [(s.card.name, s.ability_text) for s in g.stack])
g.resolve_stack()
print("a2 tapped:", a2.tapped, "attacking:", a2.attacking, "| combat_attackers:", g.combat_attackers)
print("a1 tapped:", a1.tapped, "attacking:", a1.attacking, "blocked:", a1.blocked)
for line in g.log[-10:]:
    print("  log:", line)
