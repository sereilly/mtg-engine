"""A trigger set off as a triggered ability is put on the stack goes on in
the next round, above it (CR 603.3b) — Scourge's post-promotion session.

When Bladewing the Risen entered with Grip of Chaos out, Grip's trigger was
offered in the same "order your triggered abilities" prompt as Bladewing's
entry trigger, so it could be put underneath the ability it was meant to
re-aim. The census over every watcher is
``tests/engine/test_scg_p5_trigger_round_census.py``.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from tests.engine.test_scg_p5_trigger_round_census import _pool, _round


def test_bladewing_and_grip_of_chaos():
    """The report: Bladewing the Risen enters with Grip of Chaos out. Grip's
    trigger is above Bladewing's, is offered in no ordering prompt beside it,
    and triggered because Bladewing's trigger had its one target (CR 603.4)."""
    by_name = {card.name: card for card in _pool()}
    game = Game(players=[
        PlayerState(name="P1", library=[by_name["Mountain"]] * 10,
                    graveyard=[by_name["Shivan Dragon"]]),
        PlayerState(name="P2", library=[by_name["Mountain"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    game._put_permanent_onto_battlefield(0, Permanent(card=by_name["Grip of Chaos"]), None)
    game.stack.clear()
    game.interactive_seats = {0}
    game._put_permanent_onto_battlefield(0, Permanent(card=by_name["Bladewing the Risen"]), None)
    choice = game.pending_choice_of("trigger_target", 0)
    if choice is not None:
        game.auto_resolve_pending_choices()
    names = [(item.card.name, _round(item)) for item in game.stack]
    blade = next(i for i, item in enumerate(game.stack) if item.card.name == "Bladewing the Risen")
    grip = next(i for i, item in enumerate(game.stack) if item.card.name == "Grip of Chaos")
    assert grip > blade, names
    assert _round(game.stack[grip]) == _round(game.stack[blade]) + 1
    assert not any(choice.kind == "order_triggers" for choice in game.pending_choices), names
