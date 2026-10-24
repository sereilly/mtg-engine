"""What a static functioning from a graveyard looks like on the wire.

Judgment's Incarnations and Riftstone Portal change the board while their card
is not on it (CR 113.6b). The engine's answer is the CR 613 accessors; the
client draws what the state payload says, so the payload has to carry it:

* Wonder in its owner's graveyard with an Island — the owner's creature's
  ``keywords`` badge list shows Flying (``serialization._effective_keywords``
  asks ``game._has_keyword``, the layered reader);
* Riftstone Portal in its owner's graveyard — a Swamp's ``ability_mana`` lists
  the granted "{T}: Add {G} or {W}" as a choice, and its ``produced_mana``
  offers {B} beside {G} and {W} (the Swamp's own CR 305.6 ability is no text,
  and a picker built from the grant alone would ask for colours without it).

Nothing here is a new prompt: both are read off an existing payload the
client already renders.
"""
from __future__ import annotations

import functools

from fastapi.testclient import TestClient

from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from web.app import app, store

client = TestClient(app)


@functools.lru_cache(maxsize=1)
def _w1g1_cards() -> dict:
    cards: dict = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            cards.setdefault(card.name, card)
    return cards


def _w1g1_session():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
            "host_colors": 2, "guest_colors": 2, "seed": 3131,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    session.current_turn = 0
    game.active_player_index = 0
    for player in game.players:
        player.hand.clear()
        player.graveyard.clear()
    game.remove_all_from_battlefield(list(game.all_permanents()))
    return sid, game


def _w1g1_put(game, seat: int, card) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    permanent.tapped = False
    return permanent


def _w1g1_mine(sid: str, name: str, seat: int = 0) -> dict:
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()
    return next(
        permanent for permanent in state["players"][seat]["battlefield"]
        if permanent["name"] == name
    )


def test_w1g1_a_keyword_granted_from_a_graveyard_is_badged():
    cards = _w1g1_cards()
    sid, game = _w1g1_session()
    _w1g1_put(game, 0, cards["Island"])
    _w1g1_put(game, 0, cards["Grizzly Bears"])
    game._settle()
    assert "Flying" not in _w1g1_mine(sid, "Grizzly Bears")["keywords"]

    assert game.put_card_into_graveyard(0, cards["Wonder"])
    game._settle()

    assert "Flying" in _w1g1_mine(sid, "Grizzly Bears")["keywords"]


def test_w1g1_a_mana_ability_granted_from_a_graveyard_is_on_the_wire():
    """The Swamp offers {B}, {G} and {W} (``produced_mana``, the colour list
    the client prompts from), and a click naming each makes it through the
    ``tap`` action. ``ability_mana`` is left off here by design
    (``serialization._ability_mana_payload``: when the board has changed what a
    land offers, the summary is the answer) — the granted ability is one row
    and the Swamp's own {B} is none, so a per-ability list would hide it."""
    cards = _w1g1_cards()
    for colour in ("B", "G", "W"):
        sid, game = _w1g1_session()
        _w1g1_put(game, 0, cards["Swamp"])
        game.players[0].mana_pool = {s: 0 for s in ("W", "U", "B", "R", "G", "C")}
        game._settle()
        assert _w1g1_mine(sid, "Swamp")["produced_mana"] == ["B"]

        assert game.put_card_into_graveyard(0, cards["Riftstone Portal"])
        game._settle()

        swamp = _w1g1_mine(sid, "Swamp")
        assert sorted(swamp["produced_mana"]) == ["B", "G", "W"], swamp["produced_mana"]
        resp = client.post(f"/api/sessions/{sid}/action", json={
            "seat": 0, "action": "tap", "permanent_name": "Swamp", "mana_color": colour,
        })
        assert resp.status_code == 200, resp.json()
        assert {s: n for s, n in game.players[0].mana_pool.items() if n} == {colour: 1}
