import sys
sys.path.insert(0, '.')
from engine import Game
from engine.card_loader import manifest_set_path, load_cards
from engine.models import Permanent, PlayerState
from tests.helpers import _nosick

pool = {c.name: c for c in load_cards(manifest_set_path("ICE", include_measured=True))}
print([n for n in pool if 'Jarkeld' in n])


def jarkeld_board(second_attacker="Tor Giant"):
    """P0 attacks with two creatures; P1 blocks each with one creature and
    controls General Jarkeld."""
    a1 = _nosick(Permanent(card=pool["Balduvian Bears"]))
    a2 = _nosick(Permanent(card=pool[second_attacker]))
    b1 = _nosick(Permanent(card=pool["Brown Ouphe"]))
    b2 = _nosick(Permanent(card=pool["Icatian Scout"] if "Icatian Scout" in pool else pool["Brown Ouphe"]))
    jark = _nosick(Permanent(card=pool["General Jarkeld"]))
    g = Game(players=[
        PlayerState(name="P1", battlefield=[a1, a2], life=20),
        PlayerState(name="P2", battlefield=[b1, b2, jark], life=20),
    ])
    g.enforce_mana_costs = False
    g._sync_control()
    g.active_player_index = 0
    g._set_phase_and_step("combat", "declare_attackers")
    assert g.declare_attackers(0, [0, 1], 1)[0]
    g._set_phase_and_step("combat", "declare_blockers")
    ok, msg = g.declare_blockers(1, {0: 0, 1: 1})
    assert ok, msg
    return g, a1, a2, b1, b2, jark


g, a1, a2, b1, b2, jark = jarkeld_board()
print("before:", g.combat_blockers)
print("b1 blocking:", b1.blocking_attacker_index, "b2 blocking:", b2.blocking_attacker_index)
res = g.activate_permanent_ability(
    1, "General Jarkeld", permanent_index=2,
    target_player_index=0,
    target_permanent_index=[0, 1],
    target_permanent_ids=[a1.permanent_id, a2.permanent_id],
)
print("activate:", res)
print("stack:", [(s.card.name, s.target_permanent_index, s.target_permanent_id) for s in g.stack])
g.resolve_stack()
print("after:", g.combat_blockers)
print("b1 blocking:", b1.blocking_attacker_index, "b2 blocking:", b2.blocking_attacker_index)
print("a1 blocked:", a1.blocked, "a2 blocked:", a2.blocked)
for line in g.log[-6:]:
    print("  log:", line)
