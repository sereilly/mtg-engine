"""A web AI that is not the active player answers priority as often as the
simulator's seat does on the same board — no fewer, and no more.

wave 1 (kg5 ``webturn``) left: "``_ai_respond_to_priority`` has no per-step
cap, unlike ``_ai_answers_priority``'s ``MAX_PRIORITY_ACTIONS``. A non-active
AI with a free, repeatable ability could answer every hold." Measured: no
pool ability is free and repeatable at instant speed (every cost with no
mana symbol and no {T} is a loyalty ability, a tap of the enchanted
permanent, or life), and the life-paid ones stop where the seat's own
valuation stops them. Yawgmoth's Bargain ("Pay 1 life: Draw a card") in the
person's end step is answered once a pass — ten times, from 20 life to 10 —
which is exactly the simulator's answer in the engine's own window
(``Game.offer_priority``, ``MAX_PRIORITY_ACTIONS`` a round). A per-step cap
would make the web seat answer *less* than the simulator; there is none, and
this holds the two together.
"""

from __future__ import annotations

import pytest

from engine.ai_simulator import (
    SimulationReport,
    _priority_answerer,
    _resolve_pending_choices,
    _SimulatedGame,
)
from engine.card_loader import load_catalog
from engine.game import PlayerState
from engine.models import Permanent
from tests.helpers import client, seat_plays_first

_CARDS = {card.name: card for card in load_catalog()}
_BARGAIN = "Yawgmoth's Bargain"


def _web_answers() -> tuple[int, int]:
    """The person's turn, walked to their flagged end step; they pass
    whenever they hold priority there. The AI's activations, its life."""
    created = client.post("/api/sessions", json={"mode": "human_vs_ai", "seed": 5}).json()
    sid = created["session_id"]
    session = seat_plays_first(sid, 0)
    game = session.game
    for player in game.players:
        player.battlefield = []
        player.graveyard = []
        player.hand = []
        player.library = [_CARDS["Plains"]] * 60
    game._put_permanent_onto_battlefield(1, Permanent(card=_CARDS[_BARGAIN]), None)
    start = len(game.log)
    for _ in range(200):
        state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
        if state["current_turn"] != 0:
            break
        action = "pass_priority" if state["priority_player"] == 0 else "next_phase"
        response = client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0, "action": action, "stop_steps": ["end"]},
        )
        assert response.status_code == 200, response.json()
    else:
        raise AssertionError(f"the person's turn never ended: {game.log[-12:]}")
    paid = sum(1 for line in game.log[start:] if line == f"AI paid 1 life to activate {_BARGAIN}")
    return paid, game.players[1].life


def _simulator_answers() -> tuple[int, int]:
    """The same board in the simulator's table: seat 0's end step, the
    engine's window with the simulator's priority driver."""
    players = [PlayerState(name, library=[_CARDS["Plains"]] * 60) for name in ("P1", "P2")]
    game = _SimulatedGame(players=players, enforce_mana_costs=True, prompt_driver=_resolve_pending_choices)
    report = SimulationReport(games_requested=1, games_completed=0, interaction_count=0)
    game.priority_driver = _priority_answerer(game, report, 0, [1])
    game._put_permanent_onto_battlefield(1, Permanent(card=_CARDS[_BARGAIN]), None)
    game.turn = 1
    game.active_player_index = 0
    game.begin_turn_bookkeeping(0)
    game.enter_next_turn_phase("beginning")
    start = len(game.log)
    game.resolve_end_step(0)
    game._resolve_priority_window()
    paid = sum(1 for line in game.log[start:] if line.endswith(f"paid 1 life to activate {_BARGAIN}"))
    return paid, game.players[1].life


@pytest.mark.cr("117.3c", "117.3d")
def test_the_off_turn_ai_answers_as_often_as_the_simulators_seat():
    web = _web_answers()
    simulated = _simulator_answers()
    assert web[0] >= 2, web          # answered more than once: repeated holds
    assert web == simulated, (web, simulated)
