"""A person's refused cast says what taxed it, on the wire.

The engine half is ``tests/engine/test_kg3_payment_tax_reason.py``. This is
the route: the cast the client sends from a pool one tax short comes back 400,
and its ``detail`` — the actor's own answer, which the auto-tap dialog shows
(``isManaRefusal`` reads its first words) — names the taxing card. The other
seat's state carries nothing of the reversed attempt (CR 733.1).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from web.app import app, store

client = TestClient(app)
_CARDS = {card.name: card for card in load_catalog()}


def _session(mine, theirs, hand):
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 4245,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    session.pregame_phase = None
    game.enforce_mana_costs = True
    game.players[0].battlefield = []
    game.players[1].battlefield = []
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = Permanent(card=_CARDS[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            permanent.tapped = False
    game._recompute_continuous_effects()
    game.players[0].hand = [_CARDS[name] for name in hand]
    game.stack.clear()
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, game


def test_the_actor_reads_the_tax_in_the_refusal_and_the_table_reads_nothing():
    sid, game = _session([], ["Gloom"], ["Savannah Lions"])
    game.players[0].mana_pool["W"] = 1
    log_before = list(game.log)

    refused = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "cast", "card_name": "Savannah Lions",
    })

    assert refused.status_code == 400
    detail = refused.json()["detail"]
    assert detail == "insufficient mana for Savannah Lions (costs {3} more: Gloom)", detail
    assert game.log == log_before
    other = client.get(f"/api/sessions/{sid}/state?seat=1").json()
    assert "log" in other
    assert not any("Savannah Lions" in str(line) for line in other.get("log", [])), other.get("log")


def test_an_untaxed_refusal_reads_as_it_always_did():
    """No tax, no note: the client's exact-match readers see the old words."""
    sid, game = _session([], [], ["Savannah Lions"])

    refused = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "cast", "card_name": "Savannah Lions",
    })

    assert refused.status_code == 400
    assert refused.json()["detail"] == "insufficient mana for Savannah Lions"
