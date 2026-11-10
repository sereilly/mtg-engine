"""Camouflage in the simulator's combat walker, when the defender has no
untapped creature to divide.

"This turn, instead of declaring blockers, each defending player chooses any
number of creatures they control and divides them into a number of piles…"
With nothing to divide, ``advance_combat_phase``'s Camouflage branch resolves
the empty piles itself (``resolve_camouflage_blocking``) — and then returned
at every table. A person's table gives the active player the declare blockers
step's priority there (CR 509.2) and the next advance leaves the step; the
simulator's walker (``ai_combat.run_ai_combat_phase``) saw nothing move and
nothing owed and gave the phase up, so the turn was left in declare blockers
with the attack's combat damage never dealt — and the rehearsal stalled the
same way. Now the branch returns only at a table with an interactive seat.
"""

from __future__ import annotations

import pytest

from engine import PlayerState
from engine.ai_combat import run_ai_combat_phase
from engine.models import Permanent
from tests.helpers import _game, _nosick, settle, stock_libraries


def _camouflaged_attack(by_name, *, defenders=(), interactive=()):
    """Seat 0 attacks with Murk Dwellers ("Whenever this creature attacks and
    isn't blocked, it gets +2/+0 until end of combat") and casts Camouflage in
    its declare attackers step; seat 1 controls *defenders*, all tapped."""
    game = _game(PlayerState(name="A", hand=[by_name["Camouflage"]]), PlayerState(name="D"))
    stock_libraries(game)
    game.interactive_seats = set(interactive)
    dwellers = Permanent(card=by_name["Murk Dwellers"])
    game._put_permanent_onto_battlefield(0, dwellers, None)
    _nosick(dwellers)
    for name in defenders:
        defender = Permanent(card=by_name[name])
        game._put_permanent_onto_battlefield(1, defender, None)
        _nosick(defender).tapped = True
    game._sync_control()
    game._settle()
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok, why
    result = game.queue_from_hand(0, "Camouflage")
    assert result.supported, result.details
    settle(game)
    assert game.is_camouflage_active()
    return game, dwellers


@pytest.mark.parametrize("defenders", [(), ("Grizzly Bears",)], ids=["no creature", "all tapped"])
def test_the_walker_finishes_a_camouflaged_combat_with_nothing_to_divide(catalog_by_name, defenders):
    game, _ = _camouflaged_attack(catalog_by_name, defenders=defenders)

    run_ai_combat_phase(game, 0)

    assert game.current_turn_phase != "combat", game.current_step
    assert game.players[1].life == 16, "Murk Dwellers, unblocked and pumped, deals 4"
    log = game.log
    assert log.index("D declared 0 blocker(s)") < log.index(
        "Murk Dwellers gets +2/+0 until end of turn"
    ) < log.index("D took 4 combat damage (life: 20 → 16)")


def test_a_table_with_a_person_keeps_the_declare_blockers_window(catalog_by_name):
    """Interactive: the empty piles are the declaration, the step stays for
    its priority exchange, and the next advance leaves it."""
    game, _ = _camouflaged_attack(catalog_by_name, interactive={0})

    game.advance_combat_phase()  # into declare blockers
    assert game.current_step == "declare_blockers" and not game.combat_blockers_locked
    game.advance_combat_phase()  # the empty piles resolve

    assert game.current_step == "declare_blockers"
    assert game.combat_blockers_locked
    assert "D declared 0 blocker(s)" in game.log
    assert game.players[1].life == 20

    settle(game)
    game.advance_combat_phase(allow_damage_skip=False)
    assert game.current_step == "combat_damage"
    assert game.players[1].life == 16
