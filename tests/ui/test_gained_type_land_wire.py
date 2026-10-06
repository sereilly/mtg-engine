"""The wire for a land a *gained* land type gave a free mana ability.

A Hickory Woodlot under Blanket of Night prints "{T}, Remove a depletion
counter from this land: Add {G}{G}" and has the Swamp's "{T}: Add {B}"
(CR 305.7's last sentence, CR 305.6). The engine's tap seam made the {B}; the
payload said ``taps_for_mana: false`` and offered {B} and {G}, so the client
never auto-tapped it, and a click with no ability named went to the activation
path and spent a depletion counter for {G}{G} — the land could not be tapped
for its free mana by a person at all.

The engine half is ``tests/rules/test_gained_land_type_mana.py``.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from web.app import app, store

client = TestClient(app)
_CARDS = {card.name: card for card in load_catalog()}


def _session(*names):
    response = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "Host",
        "host_colors": 2, "guest_colors": 2, "seed": 4107,
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
    permanents = []
    for name in names:
        permanent = Permanent(card=_CARDS[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        permanent.tapped = False
        permanents.append(permanent)
    game._recompute_continuous_effects()
    game.start_priority_window(0)
    return sid, game, permanents


def _payload(sid, permanent) -> dict:
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    for entry in state["players"][0]["battlefield"]:
        if entry["id"] == permanent.permanent_id:
            return entry
    raise AssertionError(f"{permanent.card.name} is not on the payload")


def test_the_payload_offers_the_gained_types_mana_and_a_click_makes_it():
    sid, game, (woodlot, _blanket) = _session("Hickory Woodlot", "Blanket of Night")
    payload = _payload(sid, woodlot)

    assert payload["taps_for_mana"] is True
    assert payload["produced_mana"] == ["B"]

    # The click as the client sends it for a land it may tap: no ability named.
    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "activate", "permanent_name": "Hickory Woodlot",
        "permanent_id": woodlot.permanent_id, "mana_color": "B",
    })
    assert response.status_code == 200, response.text
    assert game.players[0].mana_pool.get("B", 0) == 1
    assert game.players[0].mana_pool.get("G", 0) == 0
    assert woodlot.tapped
    assert int(woodlot.metadata.get("depletion_counters", 0)) == 2


def test_the_printed_ability_is_still_there_to_be_named():
    """By its index, through the activation path, for the counter it costs."""
    sid, game, (woodlot, _blanket) = _session("Hickory Woodlot", "Blanket of Night")

    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "activate", "permanent_name": "Hickory Woodlot",
        "permanent_id": woodlot.permanent_id, "ability_index": 0,
    })
    assert response.status_code == 200, response.text
    assert game.players[0].mana_pool.get("G", 0) == 2
    assert int(woodlot.metadata.get("depletion_counters", 0)) == 1


def test_without_the_blanket_the_land_is_not_one_the_client_taps():
    sid, _game, (woodlot,) = _session("Hickory Woodlot")
    payload = _payload(sid, woodlot)

    assert payload["taps_for_mana"] is False
