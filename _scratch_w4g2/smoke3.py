import sys
sys.path.insert(0, '.')
from engine import Game
from engine.card_loader import manifest_set_path, load_cards
from engine.models import Permanent, PlayerState
from tests.helpers import _nosick

pool = {c.name: c for c in load_cards(manifest_set_path("ICE", include_measured=True))}
print("Silver Erne:", pool["Silver Erne"].oracle_text, "|", pool["Silver Erne"].type_line)


def setup(attacker2, blocker2, blocks):
    a1 = _nosick(Permanent(card=pool["Balduvian Bears"]))
    a2 = _nosick(Permanent(card=pool[attacker2]))
    b1 = _nosick(Permanent(card=pool["Balduvian Barbarians"]))
    b2 = _nosick(Permanent(card=pool[blocker2]))
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
    ok, msg = g.declare_blockers(1, blocks)
    assert ok, msg
    return g, a1, a2, b1, b2, jark


# --- illegal: the flier's blocker could not block the ground creature's ---
g, a1, a2, b1, b2, jark = setup("Silver Erne", "Silver Erne", {0: 0, 1: 1})
print("before:", g.combat_blockers)
res = g.activate_permanent_ability(
    1, "General Jarkeld", permanent_index=2, target_player_index=0,
    target_permanent_index=[0, 1],
    target_permanent_ids=[a1.permanent_id, a2.permanent_id],
)
print("activate:", res)
print("after (should be unchanged):", g.combat_blockers)
print(" log:", g.log[-2])

# --- the activation restriction ---
g2, *_ = setup("Tor Giant", "Balduvian Bears", {0: 0, 1: 1})
g2._set_phase_and_step("combat", "combat_damage")
res2 = g2.activate_permanent_ability(
    1, "General Jarkeld", permanent_index=2, target_player_index=0,
    target_permanent_index=[0, 1],
)
print("activate outside step:", res2)

# --- a blocker blocking BOTH stays put ---
g3, a1, a2, b1, b2, jark = setup("Tor Giant", "Balduvian Bears", {0: 0, 1: 1})
# make b1 block both by hand-editing? use a creature that can block additional.
print("both-blocker case skipped (needs a can-block-additional creature)")

# --- targeting an unblocked attacker is refused ---
g4, a1, a2, b1, b2, jark = setup("Tor Giant", "Balduvian Bears", {0: 0})
print("blockers:", g4.combat_blockers, "a2.blocked:", a2.blocked)
res4 = g4.activate_permanent_ability(
    1, "General Jarkeld", permanent_index=2, target_player_index=0,
    target_permanent_index=[0, 1],
    target_permanent_ids=[a1.permanent_id, a2.permanent_id],
)
print("activate with unblocked target:", res4)
print("blockers after:", g4.combat_blockers)
