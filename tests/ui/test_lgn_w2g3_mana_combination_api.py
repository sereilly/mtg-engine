"""The wire of "Add three mana in any combination of {R} and/or {G}".

``ability_mana`` names the split an ability makes (``combination``: symbols
and count), and ``activate`` takes the answer as ``mana_combination``
({symbol: count}); a split the ability does not offer is a 400 with nothing
paid. The client half (a split chooser that sends it) is a client group's.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from web.app import app, store

client = TestClient(app)
_W2G3_CARDS = {
    c.name: c
    for path in manifest_set_paths(include_measured=True)
    for c in load_cards(path)
}


def _w2g3_session():
    response = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "Host",
        "host_colors": 2, "guest_colors": 2, "seed": 2303,
        "host_deck_cards": [{"name": "Forest", "count": 40}],
        "guest_deck_cards": [{"name": "Forest", "count": 40}],
    })
    assert response.status_code == 200, response.text
    sid = response.json()["session_id"]
    session = store.get(sid)
    game = session.game
    session.pregame_phase = None
    session.current_turn = 0
    game.active_player_index = 0
    game.enforce_mana_costs = False
    placed = []
    for name in ("Goblin Clearcutter", "Forest"):
        permanent = Permanent(card=_W2G3_CARDS[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        placed.append(permanent)
    game.start_priority_window(0)
    return sid, game, placed


def test_the_state_names_the_split_and_the_activation_takes_it():
    sid, game, (cutter, forest) = _w2g3_session()
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    entry = next(p for p in state["players"][0]["battlefield"] if p["id"] == cutter.permanent_id)
    (mana,) = entry["ability_mana"]
    assert mana["combination"] == {"symbols": ["R", "G"], "count": 3}

    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "activate", "permanent_id": cutter.permanent_id,
        "mana_combination": {"R": 1, "G": 2},
    })
    assert response.status_code == 200, response.text
    pool = game.players[0].mana_pool
    assert (pool["R"], pool["G"]) == (1, 2)
    assert not game.is_on_battlefield(forest)


def test_a_split_the_ability_does_not_offer_is_refused_with_nothing_paid():
    sid, game, (cutter, forest) = _w2g3_session()
    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "activate", "permanent_id": cutter.permanent_id,
        "mana_combination": {"R": 1, "G": 1},
    })
    assert response.status_code == 400
    assert "add up to 3" in response.json()["detail"]
    assert game.is_on_battlefield(forest) and not cutter.tapped
