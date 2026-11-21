"""A splice cost that is not mana (CR 702.47a) over HTTP: what the client is
sent and what the cast carries.

The engine half is ``tests/rules/test_bok_w1g3_splice_costs.py``. This asks the
wire: an Arcane hand card's ``splice_offers`` entry for a card whose splice
cost is not mana carries ``price`` — the morph cost's shape
(``special_actions.clause_choices``: ``cost_text``, ``cost_permanents``) plus
``cost_graveyard`` for a graveyard exile, and ``payable`` / ``refusal`` — and
the cast's splice choice names what pays it (``cost_permanent_ids``,
``cost_graveyard_indices``); a stale cost id is a 404 with nothing spent.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine import load_cards
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from tests.helpers import settle
from web.app import app, store

client = TestClient(app)

_BOK = {c.name: c for c in load_cards(manifest_set_path("BOK", include_measured=True))}
_CHK = {c.name: c for c in load_cards(manifest_set_path("CHK", include_measured=True))}
_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _make_session(*, graveyard=()):
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 4848,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    game.players[0].hand = [
        _CHK["Glacial Ray"], _BOK["Hundred-Talon Strike"], _BOK["Horobi's Whisper"],
    ]
    game.players[0].graveyard = [_LEA[name] for name in graveyard]
    lions = Permanent(card=_LEA["Savannah Lions"])
    knight = Permanent(card=_LEA["White Knight"])
    bears = Permanent(card=_LEA["Grizzly Bears"])
    giant = Permanent(card=_LEA["Hill Giant"])
    game.players[0].battlefield = [lions, knight, bears]
    game.players[1].battlefield = [giant]
    game.players[1].hand = []
    session.current_turn = 0
    game.active_player_index = 0
    game.priority_player_index = 0
    game._sync_control()
    return sid, game, (lions, knight, bears), giant


def _offers(state, name):
    card = next(c for c in state["players"][0]["hand"] if c["name"] == name)
    return {offer["name"]: offer for offer in card["splice_offers"]}


def test_a_non_mana_splice_offer_says_what_pays_it():
    sid, _game, (lions, knight, _bears), _giant = _make_session(
        graveyard=["Island", "Lightning Bolt", "Mountain"],
    )
    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    offers = _offers(state, "Glacial Ray")
    strike = offers["Hundred-Talon Strike"]
    assert strike["cost"] == ""
    price = strike["price"]
    assert price["cost_text"] == "tap an untapped white creature you control"
    assert price["cost_permanents"]["verb"] == "tap"
    assert price["cost_permanents"]["count"] == 1
    assert {c["permanent_id"] for c in price["cost_permanents"]["choices"]} == {
        lions.permanent_id, knight.permanent_id,
    }
    assert price["payable"] is True
    # Three cards in the pile cannot pay "Exile four cards from your
    # graveyard": listed, its choices shown, and said to be unpayable now.
    whisper = offers["Horobi's Whisper"]["price"]
    assert whisper["cost_graveyard"]["count"] == 4
    assert [c["graveyard_index"] for c in whisper["cost_graveyard"]["choices"]] == [0, 1, 2]
    assert whisper["payable"] is False and "Horobi's Whisper" in whisper["refusal"]


def test_a_cast_names_what_pays_the_splice_cost_over_http():
    sid, game, (lions, knight, bears), giant = _make_session()
    resp = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "cast", "card_name": "Glacial Ray",
        "target_seat": 1, "permanent_id": giant.permanent_id,
        "splice_cards": [{
            "hand_index": 1, "target_seat": 0, "permanent_ids": [bears.permanent_id],
            "cost_permanent_ids": [knight.permanent_id],
        }],
    })
    assert resp.status_code == 200, resp.text
    settle(game)
    assert knight.tapped and not lions.tapped
    assert giant.damage_marked == 2 and bears.effective_power == 3


def test_a_stale_cost_id_is_refused_with_nothing_spent():
    sid, game, (lions, knight, bears), giant = _make_session()
    resp = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "cast", "card_name": "Glacial Ray",
        "target_seat": 1, "permanent_id": giant.permanent_id,
        "splice_cards": [{
            "hand_index": 1, "target_seat": 0, "permanent_ids": [bears.permanent_id],
            "cost_permanent_ids": [987654],
        }],
    })
    assert resp.status_code == 404, resp.text
    assert not lions.tapped and not knight.tapped
    assert [c.name for c in game.players[0].hand][0] == "Glacial Ray"
