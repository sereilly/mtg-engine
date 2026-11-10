"""A land play whose entry is replaced spends the land drop, through the web
layer (CR 305.2a; ``tests/regressions/test_kg5_entry2_land_drop.py`` is the
engine's test).

A person plays Lake of the Dead with no Swamp: it goes to their graveyard
instead of entering, and the Forest beside it is no longer offered — and is
refused if sent anyway.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from web.app import app, store

client = TestClient(app)

_SHIPPED = {card.name: card for card in load_catalog()}


def _session():
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 4247,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = True
    for player in game.players:
        player.battlefield = []
    session.current_turn = 0
    game.active_player_index = 0
    game.lands_played_this_turn = {}
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, game


def _state(sid: str, seat: int = 0) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _act(sid: str, **body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def test_a_replaced_land_play_spends_the_drop_over_the_wire():
    sid, game = _session()
    island = Permanent(card=_SHIPPED["Island"])
    game._put_permanent_onto_battlefield(0, island, None)
    game.players[0].hand = [_SHIPPED["Lake of the Dead"], _SHIPPED["Forest"]]
    before = _state(sid)
    assert 1 in before["players"][0]["playable_hand_indices"], before["players"][0]

    played = _act(sid, seat=0, action="cast", card_name="Lake of the Dead")
    assert played.status_code == 200, played.text
    assert [c.name for c in game.players[0].graveyard] == ["Lake of the Dead"]
    assert [c.name for c in game.players[0].hand] == ["Forest"]

    after = _state(sid)
    assert after["players"][0]["playable_hand_indices"] == [], after["players"][0]
    refused = _act(sid, seat=0, action="cast", card_name="Forest")
    assert refused.status_code == 400, refused.text
    assert "already played a land this turn" in refused.text
    assert [c.name for c in game.players[0].hand] == ["Forest"]
