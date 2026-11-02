"""The web app's AI seat activates its graveyard's abilities too.

``web/game_flow._ai_step`` is the second executor of an AI seat's choices
(the simulator's is ``tests/ai/test_kg3_ai_graveyard_activations.py``). It had
a pass for the battlefield, the hand and another seat's board, and none for
the graveyard, so a Gangrenous Goliath or a Whiteout in an AI opponent's
graveyard stayed there for the game. The pass is the simulator's chooser and
executor (``engine.ai_graveyard_activations``).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from web.app import app, store
from web.game_flow import _ai_step

from tests.helpers import resolve_stack

client = TestClient(app)

_POOL: dict = {}
for _card in load_cards(manifest_set_paths()):
    _POOL.setdefault(_card.name, _card)


def _ai_main_phase(battlefield, *, graveyard=()):
    """An all-AI session in seat 1's precombat main phase, costs enforced."""
    created = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "Host", "guest_name": "AI",
        "host_colors": 2, "guest_colors": 2, "seed": 90210,
    }).json()
    session = store.get(created["session_id"])
    session.seat_types = {0: "ai", 1: "ai"}
    game = session.game
    game.enforce_mana_costs = True
    session.current_turn = 1
    game.active_player_index = 1
    seat = game.players[1]
    seat.battlefield = []
    game.players[0].battlefield = []
    for name in battlefield:
        permanent = Permanent(card=_POOL[name])
        game._put_permanent_onto_battlefield(1, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        permanent.tapped = False
    seat.hand = []
    seat.graveyard = [_POOL[name] for name in graveyard]
    game.players[0].hand = []
    game._set_phase_and_step("precombat_main", "precombat_main")
    game.start_priority_window(1)
    return session, game


def test_the_web_ai_returns_gangrenous_goliath_from_its_graveyard():
    session, game = _ai_main_phase(["Daru Healer"] * 3, graveyard=["Gangrenous Goliath"])

    _ai_step(session)
    resolve_stack(game)

    assert [card.name for card in game.players[1].hand] == ["Gangrenous Goliath"], game.log[-6:]
    assert game.players[1].graveyard == []
    assert all(permanent.tapped for permanent in game.controlled_by(1))
    assert "Gangrenous Goliath ability added to stack from the graveyard" in game.log
