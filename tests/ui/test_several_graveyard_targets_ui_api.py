"""Web-API tests for a spell naming several target *cards* in a graveyard.

The multi-permanent round trip (`test_several_targets_ui_api.py`) sends
`target_permanent_ids`, because a permanent has a stable id. A card in a
graveyard has none — the wire carries `target_permanent_indices`, which the
engine reads as slots in the caster's graveyard — so this pins the other shape.

Sanguine Indulgence because it is the card the several-cards round bought. The
set is measured rather than shipped, which is exactly the point of a measured
set: a card's focused test is written while the work is being done.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine import load_cards
from engine.card_loader import manifest_set_path
from web.app import app, store

client = TestClient(app)

_M21 = {c.name: c for c in load_cards(manifest_set_path("M21", include_measured=True))}


def _make_session(graveyard=("Alpine Watchdog", "Shock", "Garruk's Warsteed")):
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 4242,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    game.players[0].hand = [_M21["Sanguine Indulgence"]]
    game.players[0].graveyard = [_M21[name] for name in graveyard]
    session.current_turn = 0
    game.active_player_index = 0
    return sid, session, game


def _spec(sid: str) -> dict:
    """The target spec as the client reads it — off the serialized hand card,
    which is the path a real cast takes for a measured set's card."""
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    hand = state["players"][0]["hand"]
    return next(c for c in hand if c["name"] == "Sanguine Indulgence")["target_spec"]


def test_the_spec_tells_the_client_to_collect_two_graveyard_cards():
    sid, _session_obj, _game = _make_session()

    spec = _spec(sid)

    assert spec["kind"] == "graveyard_creature"
    assert spec["max_targets"] == 2
    assert spec["own_graveyard_only"] is True
    # The instant in the pile is not offered: the picker shows what resolution
    # would honour, never more.
    assert [t["name"] for t in spec["valid_targets"]] == [
        "Alpine Watchdog",
        "Garruk's Warsteed",
    ]


def test_a_cast_naming_two_graveyard_slots_returns_exactly_those_two():
    sid, _session_obj, game = _make_session()

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "cast",
            "card_name": "Sanguine Indulgence",
            "target_seat": 0,
            "target_permanent_indices": [0, 2],
        },
    )
    assert resp.status_code == 200, resp.text
    game.resolve_stack()

    assert sorted(c.name for c in game.players[0].hand) == [
        "Alpine Watchdog",
        "Garruk's Warsteed",
    ]
    assert [c.name for c in game.players[0].graveyard] == [
        "Shock",
        "Sanguine Indulgence",
    ]


def test_choosing_no_graveyard_cards_is_a_legal_cast():
    """"Up to two" may name none (CR 601.2c), so the confirm has to be reachable
    with nothing selected — including with nothing in the graveyard to select."""
    sid, _session_obj, game = _make_session(graveyard=())

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "cast",
            "card_name": "Sanguine Indulgence",
            "target_seat": 0,
        },
    )

    assert resp.status_code == 200, resp.text
    game.resolve_stack()
    assert game.players[0].hand == []
    assert [c.name for c in game.players[0].graveyard] == ["Sanguine Indulgence"]


def test_a_slot_the_effect_would_decline_is_refused_rather_than_skipped():
    """The enumeration above never offers the instant; a request naming it
    anyway is a 400 from the cast path, not a spell that returns one card and
    keeps quiet about the other."""
    sid, _session_obj, game = _make_session()

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "cast",
            "card_name": "Sanguine Indulgence",
            "target_seat": 0,
            "target_permanent_indices": [0, 1],
        },
    )

    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == "no valid target for Sanguine Indulgence"
    assert any(c.name == "Sanguine Indulgence" for c in game.players[0].hand), (
        "the spell was not cast"
    )
