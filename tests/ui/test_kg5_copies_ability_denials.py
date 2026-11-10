"""The wire's ``ability_denials`` name a copy by what it copies (CR 707.2).

``ability_denials`` is the activation path's own refusal for each usable
ability, sent so the client greys out what a click would be refused for
(``web/offers._ability_denial``). It is the engine's sentence, and the engine
named the permanent by its printed card: a summoning-sick Clone copying
Prodigal Sorcerer — "Prodigal Sorcerer" on its name plate since kg5's
``client`` group — was denied as "Clone has summoning sickness". The engine
names it by its name now (kg5 ``copies``), and this is the board the
Known-gaps item names, served to the seat that owns it.

Backwards: on the round's base the denial read "Clone has summoning
sickness".
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.models import Permanent
from tests.helpers import settle
from web.app import app, store

client = TestClient(app)


def _session():
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 7072,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    session.pregame_phase = None
    game = session.game
    for player in game.players:
        player.battlefield = []
        player.hand = []
        player.graveyard = []
        player.exile = []
    game.interactive_seats = set(range(len(game.players)))
    game.enforce_mana_costs = False
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, game


def test_a_summoning_sick_copy_is_denied_by_its_name(set_pool):
    lea = set_pool("LEA")
    sid, game = _session()
    sorcerer = Permanent(card=lea["Prodigal Sorcerer"])
    game._put_permanent_onto_battlefield(0, sorcerer, None)
    sorcerer.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    game.players[0].hand = [lea["Clone"]]
    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "cast", "card_name": "Clone",
        "target_seat": 0, "target_permanent_id": sorcerer.permanent_id,
    })
    assert response.status_code == 200, response.text
    settle(game)
    (clone,) = [p for p in game.players[0].battlefield if p.card.name == "Clone"]
    assert clone.effective_card.name == "Prodigal Sorcerer", game.log[-5:]
    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    entry = next(e for e in state["players"][0]["battlefield"] if e["id"] == clone.permanent_id)
    assert entry["name"] == "Prodigal Sorcerer"
    assert entry["ability_denials"] == ["Prodigal Sorcerer has summoning sickness"]
    # The Sorcerer that has been here since the turn began is denied nothing.
    real = next(e for e in state["players"][0]["battlefield"] if e["id"] == sorcerer.permanent_id)
    assert "ability_denials" not in real
