"""Splice onto Arcane (CR 702.47) over HTTP: what the client is sent and what
the cast action carries.

The engine half is ``tests/rules/test_chk_w1g5_splice.py``. This asks the
wire: an Arcane hand card lists what may be spliced onto it
(``splice_offers``: each candidate's hand place, printed cost and the target
spec of the text it would add, judged as the host spell's); one cast request
naming ``splice_cards`` performs the main text and the gained ones; the stack
item says what was spliced and draws every target; the auto-tap's preview
prices the splice cost; a stale id and the spell named as its own splice are
refused with nothing spent.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine import load_cards
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from tests.helpers import settle
from web.app import app, store

client = TestClient(app)

_CHK = {c.name: c for c in load_cards(manifest_set_path("CHK", include_measured=True))}
_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _make_session(*, mana: bool = False, lands=()):
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 4747,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = mana
    game.players[0].hand = [
        _CHK["Reach Through Mists"], _CHK["Glacial Ray"], _CHK["Kodama's Might"],
    ]
    bears = Permanent(card=_LEA["Grizzly Bears"])
    giant = Permanent(card=_LEA["Hill Giant"])
    game.players[0].battlefield = [bears, *(Permanent(card=_LEA[name]) for name in lands)]
    game.players[1].battlefield = [giant]
    game.players[1].hand = []
    for player in game.players:
        for key in player.mana_pool:
            player.mana_pool[key] = 0
    session.current_turn = 0
    game.active_player_index = 0
    game.priority_player_index = 0
    game._sync_control()
    return sid, game, bears, giant


def _hand_card(state, name):
    return next(c for c in state["players"][0]["hand"] if c["name"] == name)


def test_an_arcane_hand_card_lists_what_may_be_spliced_onto_it():
    sid, _game, bears, giant = _make_session()
    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    offers = _hand_card(state, "Reach Through Mists")["splice_offers"]
    assert [(o["hand_index"], o["name"], o["cost"]) for o in offers] == [
        (1, "Glacial Ray", "{1}{R}"), (2, "Kodama's Might", "{G}"),
    ]
    ray_spec = offers[0]["target_spec"]
    assert ray_spec["requires_target"] and ray_spec["valid_targets"], ray_spec
    might_targets = {
        (t.get("seat"), t.get("index")) for t in offers[1]["target_spec"]["valid_targets"]
    }
    assert {(0, 0), (1, 0)} <= might_targets, might_targets  # the Bears, the Giant
    # Glacial Ray is an Arcane spell too: Kodama's Might may be spliced onto
    # it, and it is never offered onto itself (CR 702.47a).
    ray_offers = _hand_card(state, "Glacial Ray")["splice_offers"]
    assert [o["name"] for o in ray_offers] == ["Kodama's Might"]


def test_a_cast_naming_splice_cards_performs_the_gained_text_over_http():
    sid, game, bears, giant = _make_session()
    resp = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "cast", "card_name": "Reach Through Mists",
        "splice_cards": [
            {"hand_index": 1, "target_seat": 1, "permanent_id": giant.permanent_id},
            {"hand_index": 2, "target_seat": 0, "permanent_ids": [bears.permanent_id]},
        ],
    })
    assert resp.status_code == 200, resp.text
    settle(game)
    assert giant.damage_marked == 2 and bears.effective_power == 4, game.log
    assert [c.name for c in game.players[0].hand][:2] == ["Glacial Ray", "Kodama's Might"]


def test_the_stack_item_names_what_was_spliced_and_draws_its_targets():
    sid, game, _bears, giant = _make_session()
    game.queue_from_hand(0, "Reach Through Mists", splice_cards=[
        {"hand_index": 1, "target_permanent_ids": [giant.permanent_id]},
    ])
    state = client.get(f"/api/sessions/{sid}/state?seat=1").json()
    (item,) = state["stack"]
    assert item["spliced"] == [{
        "name": "Glacial Ray",
        "text": "Reach Through Mists deals 2 damage to any target.",
        "targets": [{"kind": "permanent", "seat": 1, "index": 0}],
    }]
    assert {"kind": "permanent", "seat": 1, "index": 0} in item["targets"]


def test_the_auto_tap_preview_prices_the_splice_cost():
    sid, game, _bears, giant = _make_session(
        mana=True, lands=["Island", "Mountain", "Mountain"],
    )
    body = {
        "seat": 0, "action": "cast", "card_name": "Reach Through Mists",
        "splice_cards": [{"hand_index": 1, "permanent_id": giant.permanent_id}],
    }
    plan = client.post(f"/api/sessions/{sid}/payment_plan", json=body)
    assert plan.status_code == 200, plan.text
    plan = plan.json()
    assert plan["payable"] is True, plan
    assert sorted(tap["name"] for tap in plan["taps"]) == ["Island", "Mountain", "Mountain"]
    resp = client.post(f"/api/sessions/{sid}/action", json={**body, "auto_tap": True})
    assert resp.status_code == 200, resp.text
    settle(game)
    assert giant.damage_marked == 2


def test_a_stale_id_and_a_self_splice_are_refused_with_nothing_spent():
    sid, game, _bears, giant = _make_session()
    stale = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "cast", "card_name": "Reach Through Mists",
        "splice_cards": [{"hand_index": 1, "permanent_id": 999_999}],
    })
    assert stale.status_code == 404, stale.text
    itself = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "cast", "card_name": "Glacial Ray",
        "target_seat": 1,
        "splice_cards": [{"hand_index": 1, "target_seat": 1}],
    })
    assert itself.status_code != 200 or "onto itself" in itself.text, itself.text
    assert [c.name for c in game.players[0].hand] == [
        "Reach Through Mists", "Glacial Ray", "Kodama's Might",
    ]
    assert not game.stack and giant.damage_marked == 0
