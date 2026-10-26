"""Future Sight on the wire: the revealed top card and the cast it opens.

"Play with the top card of your library revealed. You may play lands and cast
spells from the top of your library." The first sentence puts the card face on
``players[seat].library_top`` for **every** viewer (CR 400.2: revealed is
public); the second puts the top card on its controller's
``castable_from_zones`` with its ways — a spell at its mana cost, a land as
the land drop — and nobody else's. ONS is measured, not shipped, so the card is
placed into the session directly, as ``test_revealed_zones_ui_api.py`` does.

The client half (drawing the revealed card on the library pile, offering the
cast from it) is the wave-2 client group's: today the canvas draws a library
pile with no face and the zone-cast filter names graveyard, exile and command.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from engine import load_cards
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from web.app import app, store

client = TestClient(app)

_ONS = {c.name: c for c in load_cards(manifest_set_path("ONS", include_measured=True))}


def _session():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 4111,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    return sid, store.get(sid).game


def _state(sid: str, seat: int) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def test_future_sight_shows_its_controllers_top_card_to_both_seats():
    sid, game = _session()
    owner = game.active_player_index or 0
    other = 1 - owner
    game.players[owner].library.insert(0, _ONS["Shock"])
    game._put_permanent_onto_battlefield(owner, Permanent(card=_ONS["Future Sight"]), None)
    game._sync_control()

    for viewer in (owner, other):
        state = _state(sid, viewer)
        assert state["players"][owner]["library_top"]["name"] == "Shock"
        assert state["players"][other]["library_top"] is None


def test_future_sight_offers_the_top_card_to_its_controller_alone():
    sid, game = _session()
    owner = game.active_player_index or 0
    other = 1 - owner
    game.players[owner].library.insert(0, _ONS["Shock"])
    game._put_permanent_onto_battlefield(owner, Permanent(card=_ONS["Future Sight"]), None)
    game._sync_control()

    mine = [
        entry for entry in _state(sid, owner).get("castable_from_zones") or ()
        if entry["zone"] == "library"
    ]
    assert [(entry["index"], entry["name"]) for entry in mine] == [(0, "Shock")]
    assert mine[0]["ways"], "the cast is offered with its price"
    theirs = [
        entry for entry in _state(sid, other).get("castable_from_zones") or ()
        if entry["zone"] == "library"
    ]
    assert theirs == []
