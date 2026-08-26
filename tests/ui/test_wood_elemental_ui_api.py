"""Web-API tests for Wood Elemental's "sacrifice any number" entry prompt.

Two things about this card only show up through the app rather than at the
compiler.

The first is that the prompt is a **ceiling**: "As this creature enters,
sacrifice any number of untapped Forests." None is a legal answer, and a picker
that could only confirm at exactly the offered count would turn the offer into a
demand. The wire carries ``up_to`` beside ``count`` for that reason, and
``web/static/app.js`` reads it.

The second is that the creature is a 0/0 until the answer lands — its P/T is
*defined* by how many Forests were sacrificed as it entered (CR 604.3). It must
still be on the battlefield when the player is looking at the prompt, or they
are being asked about a permanent already in the graveyard. CR 614.1c: the
sacrifice is part of entering, so entering is not finished and CR 704.5f has
nothing settled to test yet.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_cards, manifest_set_paths
from engine.models import CardDefinition, Permanent
from web.app import app, store

client = TestClient(app)

# ``include_measured``: Legends is a measured set, so its cards are not in the
# pool a player may deck. Putting one in a hand by hand is what these tests do
# to every card they are about.
_R31_CARDS = {
    c.name: c
    for path in manifest_set_paths(include_measured=True)
    for c in load_cards(path)
}


def _r31_forest() -> CardDefinition:
    return CardDefinition(
        name="Forest", mana_cost="", cmc=0.0, type_line="Basic Land - Forest",
        oracle_text="", colors=(), color_identity=("G",), keywords=(),
        produced_mana=("G",),
        raw={"name": "Forest", "type_line": "Basic Land - Forest"},
    )


def _r31_session(forests: int = 3):
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 31,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    game.players[0].hand = [_R31_CARDS["Wood Elemental"]]
    game.players[0].battlefield = [
        Permanent(card=_r31_forest()) for _ in range(forests)
    ]
    session.current_turn = 0
    game.active_player_index = 0
    game.cast_from_hand(0, "Wood Elemental")
    return sid, session, game


def test_the_offer_reaches_its_controller_as_a_ceiling():
    sid, _session, game = _r31_session()

    info = client.get(
        f"/api/sessions/{sid}/state", params={"seat": 0}
    ).json()["sacrifice_select"]
    assert info is not None
    assert info["count"] == 3 and info["up_to"] is True
    assert len(info["permanents"]) == 3
    assert "Wood Elemental" in info["reason"]

    # It belongs to its controller alone.
    other = client.get(f"/api/sessions/{sid}/state", params={"seat": 1}).json()
    assert other["sacrifice_select"] is None


def test_the_creature_is_still_there_to_be_asked_about():
    """CR 614.1c: entering is not finished while the choice is owed, so the
    state-based check has no settled toughness to sweep."""
    sid, _session, game = _r31_session()

    names = [p.card.name for p in game.players[0].battlefield]
    assert "Wood Elemental" in names
    assert game.players[0].graveyard == []


def test_sacrificing_two_forests_makes_it_a_two_two():
    sid, _session, game = _r31_session()
    info = client.get(
        f"/api/sessions/{sid}/state", params={"seat": 0}
    ).json()["sacrifice_select"]

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "sacrifice_confirm",
            "sacrifice_indices": [p["index"] for p in info["permanents"]][:2],
        },
    )
    assert resp.status_code == 200, resp.text

    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    assert state["sacrifice_select"] is None
    elemental = next(
        p for p in state["players"][0]["battlefield"] if p["name"] == "Wood Elemental"
    )
    assert (elemental["power"], elemental["toughness"]) == (2, 2)


def test_sacrificing_none_is_accepted_and_the_creature_dies():
    """The empty answer is the one a ceiling has to accept. It is also the one
    that kills the creature, which is what the card does when its controller
    keeps their lands."""
    sid, _session, game = _r31_session()

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "sacrifice_confirm", "sacrifice_indices": []},
    )
    assert resp.status_code == 200, resp.text

    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    assert state["sacrifice_select"] is None
    assert [p["name"] for p in state["players"][0]["battlefield"]] == ["Forest"] * 3
    assert [c["name"] for c in state["players"][0]["graveyard"]] == ["Wood Elemental"]


def test_the_prompt_refuses_everything_else_until_it_is_answered():
    """CR 117.3b / CR 608.2: the resolution is not over, so its controller does
    not get to do something else first."""
    sid, _session, game = _r31_session()

    resp = client.post(
        f"/api/sessions/{sid}/action", json={"seat": 0, "action": "pass_priority"}
    )
    assert resp.status_code == 400
    assert "sacrifice" in resp.json()["detail"].lower()
