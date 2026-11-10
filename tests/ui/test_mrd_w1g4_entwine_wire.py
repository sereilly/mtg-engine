"""An entwined cast (CR 702.42a), over HTTP: what the client is sent and what
the action carries.

The engine half is ``tests/rules/test_mrd_w1g4_entwine.py``. This asks the
wire: the hand card's modal spec carries the entwine offer (asked before a
mode, because taking it is choosing every mode), and one cast request — the
offer taken plus every mode with its own targets, a mode naming two
permanents by id — performs every mode.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine import load_cards
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from tests.helpers import resolve_stack
from web.app import app, store

client = TestClient(app)

_MRD = {c.name: c for c in load_cards(manifest_set_path("MRD", include_measured=True))}
_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _make_session():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 424,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    game.players[0].hand = [_MRD["Blinding Beam"]]
    mine = Permanent(card=_LEA["Grizzly Bears"])
    theirs = [Permanent(card=_LEA["Hill Giant"]), Permanent(card=_LEA["Craw Wurm"])]
    game.players[0].battlefield = [mine]
    game.players[1].battlefield = list(theirs)
    game.players[1].hand = []
    session.current_turn = 0
    game.active_player_index = 0
    game._sync_control()
    return sid, game, mine, theirs


def test_the_hand_card_offers_the_entwine_before_its_modes():
    sid, _game, _mine, _theirs = _make_session()
    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    card = next(c for c in state["players"][0]["hand"] if c["name"] == "Blinding Beam")
    spec = card["target_spec"]
    assert spec["kind"] == "modal" and spec["entwine"] == "{1}", spec
    assert [offer["label"] for offer in spec["cost_offers"]] == ["entwine"]
    assert len(card["modes"]) == 2


def test_an_entwined_cast_performs_every_mode_over_http():
    """One request: the entwine offer, mode 0 naming two creatures by id on
    one board, mode 1 naming a seat."""
    sid, game, _mine, theirs = _make_session()
    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "cast",
            "card_name": "Blinding Beam",
            "optional_cost_payments": {"{1}": 1},
            "mode_choices": [
                {"index": 0, "target_seat": 1,
                 "permanent_ids": [p.permanent_id for p in theirs]},
                {"index": 1, "target_seat": 1},
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    game._settle()
    resolve_stack(game)
    assert all(p.tapped for p in theirs), game.log
    assert [lock.seat for lock in game.untap_step_locks] == [1]


def test_a_modes_permanents_may_sit_on_two_boards():
    """"Tap two target creatures" names any two creatures (CR 115.1), on two
    battlefields as readily as on one: the mode's ids say which board each is
    on (``ModeChoice.permanent_ids`` → ``ChosenMode.target_permanent_id``),
    as the cast's own ``target_permanent_ids`` do. This was a 422 until
    MRD W2G6b; a name the mode cannot take is still refused."""
    sid, game, mine, theirs = _make_session()
    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "cast",
            "card_name": "Blinding Beam",
            "optional_cost_payments": {"{1}": 1},
            "mode_choices": [
                {"index": 0, "target_seat": 1,
                 "permanent_ids": [theirs[0].permanent_id, mine.permanent_id]},
                {"index": 1, "target_seat": 1},
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    game._settle()
    resolve_stack(game)
    assert theirs[0].tapped and mine.tapped and not theirs[1].tapped, game.log
    assert [lock.seat for lock in game.untap_step_locks] == [1]


def test_a_mode_naming_a_noncreature_across_boards_is_refused():
    sid, game, mine, theirs = _make_session()
    land = Permanent(card=_LEA["Forest"])
    game.players[0].battlefield.append(land)
    game._sync_control()
    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "cast",
            "card_name": "Blinding Beam",
            "optional_cost_payments": {"{1}": 1},
            "mode_choices": [
                {"index": 0, "target_seat": 1,
                 "permanent_ids": [theirs[0].permanent_id, land.permanent_id]},
                {"index": 1, "target_seat": 1},
            ],
        },
    )
    assert resp.status_code == 400, resp.text
    assert not game.stack and not any(p.tapped for p in (mine, land, *theirs))
