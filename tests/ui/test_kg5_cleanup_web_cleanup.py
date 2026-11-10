"""The web's End Turn carries a flashed-in Aura's cleanup sacrifice out in the
cleanup step it names (CR 603.7g, 514.3a).

Since kg5/cleanup the sacrifice is a delayed triggered ability put on the stack
in the cleanup step rather than a sweep. The web layer holds no cleanup window
for a person (``web/turn_steps._end_turn`` calls ``resolve_cleanup_step`` and
begins the next turn on True), so at a table with a person the engine resolves
it inside the step — the window collapsed to its outcome. Driven here through
the web's own turn flow: the stack is empty when the next turn begins, the Aura
is in its owner's graveyard, and both seats are served the log line.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from web.session_store import Session
from web.state_view import build_state
from web.turn_steps import _end_turn

from tests.helpers import settle


def test_end_turn_sacrifices_a_flashed_in_aura_in_that_turns_cleanup(set_pool):
    pool = set_pool("MIR")
    island = pool["Island"]
    game = Game(players=[
        PlayerState(name="P1", hand=[pool["Soar"]], library=[island] * 10),
        PlayerState(name="P2", library=[island] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game.begin_turn_bookkeeping(0)
    game._set_phase_and_step("beginning", "untap")
    game.enter_next_turn_phase("beginning")
    host = Permanent(card=pool["Femeref Knight"])
    game._put_permanent_onto_battlefield(0, host, None)
    session = Session(
        id="s", mode="human_vs_ai", host_name="P1", guest_name="P2", game=game,
        seat_types={0: "human", 1: "ai"},
    )
    game._close_current_priority_step()
    game.advance_combat_phase()
    assert game.current_turn_phase == "combat"
    result = game.cast_from_hand(
        0, "Soar", target_player_index=0,
        target_permanent_index=game.players[0].battlefield.index(host),
    )
    assert result.supported, result.details
    settle(game)
    aura = next(p for p in game.players[0].battlefield if p.card.name == "Soar")

    _end_turn(session)

    assert session.current_turn == 1, game.log[-10:]
    assert not game.stack
    assert not game.is_on_battlefield(aura)
    assert any(card.name == "Soar" for card in game.players[0].graveyard)
    for seat in (0, 1):
        served = build_state(session, seat)
        assert any("P1 sacrificed Soar at cleanup" in str(line) for line in served["log"]), seat
