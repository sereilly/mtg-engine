"""The wire of an each-player sacrifice: one seat's prompt at a time, the
active player's first (CR 101.4), each entry carrying its permanent ``id`` and
the answer accepted by id (``sacrifice_permanent_ids``) as well as by slot.

Known gap "Five prompts answer a permanent by index" named
``sacrifice_confirm`` as one with no id form; this is that form.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from web.app import app, store

from tests.helpers import _mk_creature_card

client = TestClient(app)

_W2G3_CARDS = {
    c.name: c
    for path in manifest_set_paths(include_measured=True)
    for c in load_cards(path)
}


def _w2g3_session():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
            "host_colors": 2, "guest_colors": 2, "seed": 23,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    game.players[0].hand = [_W2G3_CARDS["Innocent Blood"]]
    game.players[0].battlefield = [
        Permanent(card=_mk_creature_card("Elves", 1, 1)),
        Permanent(card=_mk_creature_card("Giant", 3, 3)),
    ]
    game.players[1].battlefield = [
        Permanent(card=_mk_creature_card("Bear", 2, 2)),
        Permanent(card=_mk_creature_card("Wurm", 6, 4)),
    ]
    game._sync_control()
    session.current_turn = 0
    game.active_player_index = 0
    game.cast_from_hand(0, "Innocent Blood")
    return sid, game


def _prompt(sid: str, seat: int):
    return client.get(
        f"/api/sessions/{sid}/state", params={"seat": seat}
    ).json()["sacrifice_select"]


def test_one_seat_at_a_time_and_the_answer_by_id():
    sid, game = _w2g3_session()

    mine = _prompt(sid, 0)
    assert mine is not None and mine["count"] == 1
    assert {entry["name"] for entry in mine["permanents"]} == {"Elves", "Giant"}
    assert all(isinstance(entry["id"], int) for entry in mine["permanents"])
    assert _prompt(sid, 1) is None, "the other seat is asked only after this answer"
    refused = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 1, "action": "sacrifice_confirm", "sacrifice_indices": [0]},
    )
    assert refused.status_code == 400

    giant = next(e for e in mine["permanents"] if e["name"] == "Giant")
    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "sacrifice_confirm",
              "sacrifice_permanent_ids": [giant["id"]]},
    )
    assert resp.status_code == 200, resp.text

    theirs = _prompt(sid, 1)
    assert theirs is not None
    assert {entry["name"] for entry in theirs["permanents"]} == {"Bear", "Wurm"}
    board0 = [p["name"] for p in client.get(
        f"/api/sessions/{sid}/state", params={"seat": 1}
    ).json()["players"][0]["battlefield"]]
    assert "Giant" in board0, "chosen, not yet sacrificed (CR 101.4)"

    bear = next(e for e in theirs["permanents"] if e["name"] == "Bear")
    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 1, "action": "sacrifice_confirm",
              "sacrifice_indices": [bear["index"]]},
    )
    assert resp.status_code == 200, resp.text

    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    assert state["sacrifice_select"] is None
    assert [p["name"] for p in state["players"][0]["battlefield"]] == ["Elves"]
    assert [p["name"] for p in state["players"][1]["battlefield"]] == ["Wurm"]


def test_a_stale_id_is_a_refusal():
    sid, _game = _w2g3_session()
    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "sacrifice_confirm",
              "sacrifice_permanent_ids": [987654]},
    )
    assert resp.status_code == 400
    assert _prompt(sid, 0) is not None
