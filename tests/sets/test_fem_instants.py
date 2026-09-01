"""Per-card tests for Fallen Empires' instants.

See tests/sets/README.md for the convention: get cards through
``set_pool("FEM")`` / ``set_cards("FEM")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** The wave that implemented FEM
split by grammar family rather than by printed type, so several groups land
tests in this one file. Each group appends a single delimited block:

    # --- G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared
header loses it in exactly that move -- a ``NameError`` at collection, found
only after the merge is committed. A self-contained block cannot lose one.
"""

from __future__ import annotations


# --- G5: prices offered to a player, prevention and control ---
from engine import Game, PlayerState
from engine.models import Permanent


def _g5_ready(perm: Permanent) -> Permanent:
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _g5_combat(set_pool):
    """P2 attacks with a bear, P1 blocks with one — the board Spore Cloud is
    printed to be cast on."""
    attacker = _g5_ready(Permanent(card=set_pool("LEA")["Grizzly Bears"]))
    blocker = _g5_ready(Permanent(card=set_pool("LEA")["Grizzly Bears"]))
    idle = _g5_ready(Permanent(card=set_pool("LEA")["Grizzly Bears"]))
    p1 = PlayerState(name="P1", battlefield=[blocker, idle],
                     hand=[set_pool("FEM")["Spore Cloud"]])
    p2 = PlayerState(name="P2", battlefield=[attacker])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(1)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(1, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(0, {0: 0})[0]
    return game, attacker, blocker, idle


def test_spore_cloud_taps_the_blockers_fogs_the_combat_and_holds_both_sides_down(set_pool):
    """"Tap all blocking creatures. Prevent all combat damage that would be
    dealt this turn. Each attacking creature and each blocking creature doesn't
    untap during its controller's next untap step."

    Three sentences, three mechanisms, and the third is a *sweep* — it names no
    target and restates nothing an earlier step chose, so the set is whatever
    is in combat when the spell resolves.
    """
    game, attacker, blocker, idle = _g5_combat(set_pool)

    assert game.cast_from_hand(0, "Spore Cloud").supported, game.log

    assert blocker.tapped, "sentence one"
    assert not idle.tapped, "a creature outside combat is not blocking"
    assert attacker.metadata.get("skip_next_untap") == 1
    assert blocker.metadata.get("skip_next_untap") == 1
    assert idle.metadata.get("skip_next_untap") is None, (
        "the third sentence names attackers and blockers, not every creature"
    )

    game.advance_combat_phase()   # combat damage
    assert game.players[0].life == 20
    assert attacker.damage_marked == 0 and blocker.damage_marked == 0, game.log


def test_spore_clouds_untap_marker_survives_one_untap_step(set_pool):
    """The marker is what CR 502.3 reads, and the untap step both honours and
    clears it — so the creatures are still down for exactly one turn."""
    game, attacker, blocker, _idle = _g5_combat(set_pool)
    game.cast_from_hand(0, "Spore Cloud")
    assert blocker.tapped

    game.start_turn(0)

    assert blocker.tapped, "P1's untap step skipped it"
    assert blocker.metadata.get("skip_next_untap") in (None, 0), game.log
# --- end G5 ---
