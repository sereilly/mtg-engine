"""Quick Sliver through the web's timing gate (LGN, W1G3).

"Any player may cast Sliver spells as though they had flash." The engine's
cast path takes no timing decision of its own; the gate a person meets is
``web/actions.py``'s, which asks ``cast_timing.casts_at_instant_speed``. So
the permission is driven here, where it is enforced: the *opponent* of Quick
Sliver's controller casts a Sliver during the controller's turn, and the same
request without Quick Sliver on the battlefield — or for a non-Sliver — is
refused with the gate's own words.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.models import Permanent
from web.app import app, store

client = TestClient(app)


def _session(set_pool, battlefield, hand):
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 818,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    lgn, lea = set_pool("LGN"), set_pool("LEA")
    pool = {**lea, **lgn}
    game.players[0].battlefield = [Permanent(card=pool[name]) for name in battlefield]
    game.players[1].battlefield = []
    game.players[1].hand = [pool[name] for name in hand]
    session.current_turn = 0
    game.active_player_index = 0
    # Seat 0's turn, and seat 0 has passed: the opponent holds priority
    # (CR 117.3d), which is the moment flash is for.
    game.priority_player_index = 1
    game._recompute_continuous_effects()
    return sid, game


def _cast(sid, name):
    return client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 1, "action": "cast", "card_name": name},
    )


def test_the_opponent_casts_a_sliver_on_quick_slivers_controllers_turn(set_pool):
    sid, game = _session(set_pool, ["Quick Sliver"], ["Plated Sliver"])
    response = _cast(sid, "Plated Sliver")
    assert response.status_code == 200, response.text
    assert "Plated Sliver" in [item.card.name for item in game.stack] or any(
        permanent.card.name == "Plated Sliver"
        for permanent in game.players[1].battlefield
    )
    assert game.players[1].hand == []


def test_without_quick_sliver_the_gate_still_refuses(set_pool):
    sid, game = _session(set_pool, [], ["Plated Sliver"])
    response = _cast(sid, "Plated Sliver")
    assert response.status_code == 400
    assert "only be cast on your turn" in response.text
    assert [card.name for card in game.players[1].hand] == ["Plated Sliver"]


def test_quick_sliver_does_not_flash_a_non_sliver(set_pool):
    sid, game = _session(set_pool, ["Quick Sliver"], ["Grizzly Bears"])
    response = _cast(sid, "Grizzly Bears")
    assert response.status_code == 400
    assert [card.name for card in game.players[1].hand] == ["Grizzly Bears"]
