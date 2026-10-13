"""The web's beginning phase: what an upkeep trigger set off resolves before
the draw (CR 500.2, CR 117.5).

Phase 5's log, on a human's own turn: "Hill Giant each got 1 fuse counter(s)",
then "drew 1 card(s) in draw step", and only then Bomb Squad's destruction and
the 4 damage. The step's window closed on an empty stack, and the state
trigger the last resolution made true was announced by the draw step's own
check. The rule and the three-path census are
``tests/rules/test_step_ends_after_what_triggered.py``; this is the same turn
through the functions the web layer runs it with.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.models import Permanent
from engine.named_counters import add_counters
from web.app import app, store
from web.runtime import CARD_BY_NAME
from web.turn_steps import _finish_beginning_phase, _resolve_upkeep_step

client = TestClient(app)


def test_bomb_squads_fuse_goes_off_before_the_draw_step():
    created = client.post(
        "/api/sessions", json={"mode": "human_vs_human", "seed": 808},
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    session.current_turn = 0
    game.active_player_index = 0
    game.interactive_seats = {0, 1}
    me, you = game.players
    squad = Permanent(card=CARD_BY_NAME["bomb squad"])
    giant = Permanent(card=CARD_BY_NAME["hill giant"])
    me.battlefield = [squad]
    you.battlefield = [giant]
    game._settle()
    add_counters(giant, "fuse", 3)
    life = you.life
    hand = len(me.hand)
    start = len(game.log)

    assert _resolve_upkeep_step(session, 0) is True
    # The upkeep is over and the fuse has gone off in it — nothing was left
    # on the stack for the draw step to find, and nothing has been drawn.
    assert not game.stack
    assert not game.is_on_battlefield(giant), game.log[start:]
    assert you.life == life - 4
    assert len(me.hand) == hand
    in_the_upkeep = game.log[start:]
    assert any("destroyed Hill Giant" in line for line in in_the_upkeep)
    assert any("dealt 4 damage" in line for line in in_the_upkeep)

    assert _finish_beginning_phase(session, 0) is True
    assert game.current_phase != "beginning"

    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    assert state["stack"] == []
