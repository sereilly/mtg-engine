"""The copy-as-it-enters "may" declined, over HTTP (``decline_copy``).

The engine half is ``tests/regressions/test_mrd_w2g4_copy_declined.py``.
This asks the wire: the hand card's ``target_spec`` says the copy target is
optional, and a ``cast`` carrying ``decline_copy: true`` and no target enters
the permanent as itself — where the same cast without the field copies the
first permanent of the type, as every client that does not know the field
always has. The browser's gesture (a "Don't copy" answer to the optional
picker) is the client group's; this is the field it sends.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine import load_cards
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from tests.helpers import resolve_stack
from web.app import app, store

client = TestClient(app)

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
    game.players[0].hand = [_LEA["Clone"]]
    game.players[0].battlefield = []
    game.players[1].battlefield = [Permanent(card=_LEA["Craw Wurm"])]
    game.players[1].hand = []
    session.current_turn = 0
    game.active_player_index = 0
    game._sync_control()
    return sid, game


def test_the_hand_card_says_its_copy_target_is_optional():
    sid, _game = _make_session()
    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    card = next(c for c in state["players"][0]["hand"] if c["name"] == "Clone")
    spec = card["target_spec"]
    assert spec["kind"] == "creature" and spec["optional"] is True, spec
    # What the client's "Don't copy" answers instead of: the Wurm, offered.
    assert [t["kind"] for t in spec["valid_targets"]] == ["permanent"], spec


def test_a_cast_declining_the_copy_enters_the_clone_as_itself():
    sid, game = _make_session()
    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Clone", "decline_copy": True},
    )
    assert resp.status_code == 200, resp.text
    game._settle()
    resolve_stack(game)
    game.check_state_based_actions()
    assert "Clone entered as itself, copying nothing" in game.log
    assert [c.name for c in game.players[0].graveyard] == ["Clone"]


def test_a_cast_without_the_field_still_copies():
    sid, game = _make_session()
    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Clone"},
    )
    assert resp.status_code == 200, resp.text
    game._settle()
    resolve_stack(game)
    assert [p.effective_card.name for p in game.controlled_by(0)] == ["Craw Wurm"]
