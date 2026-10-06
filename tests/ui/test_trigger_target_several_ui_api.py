"""Web-API round trip for a triggered ability that prints several targets.

"Put a +1/+1 counter on each of up to two other target creatures you control"
(Basri's Acolyte), put onto the battlefield by something other than a cast, so
CR 603.3d chooses its targets as the trigger goes on the stack. The prompt's
payload says how many may be named (``max_targets``) and the answer carries
them as one list of stable ids — CR 601.2c makes the targets of one ability one
announcement.

The engine half is ``tests/regressions/test_trigger_target_several.py``; this
pins the wire. The browser client still sends one id per click — a legal
answer to "up to two", and the part still to do: a multi-pick for this prompt
in ``app.js``, the shape ``renderModalModeTargetsModal`` already has for
``modal_mode_targets``.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.models import Permanent
from web.app import app, store

client = TestClient(app)


def _w2g6_session():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 603,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    # What the action preamble sets before every action; the trigger below is
    # put on the stack on the engine directly, before any action has run.
    game.interactive_seats = {0, 1}
    for player in game.players:
        player.battlefield.clear()
    return sid, game


def _w2g6_state(sid: str, seat: int = 0) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _w2g6_act(sid: str, **body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def _w2g6_enter(game, catalog_by_name, seat, name) -> Permanent:
    permanent = Permanent(card=catalog_by_name[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return permanent


def test_w2g6_a_several_target_trigger_round_trips_a_list(catalog_by_name):
    sid, game = _w2g6_session()
    bears = _w2g6_enter(game, catalog_by_name, 0, "Grizzly Bears")
    giant = _w2g6_enter(game, catalog_by_name, 0, "Hill Giant")
    lions = _w2g6_enter(game, catalog_by_name, 0, "Savannah Lions")
    _w2g6_enter(game, catalog_by_name, 0, "Basri's Acolyte")

    prompt = _w2g6_state(sid)["trigger_target"]
    assert prompt["player_seat"] == 0 and prompt["card_name"] == "Basri's Acolyte"
    assert prompt["max_targets"] == 2
    assert sorted(c["id"] for c in prompt["candidates"]) == sorted(
        [bears.permanent_id, giant.permanent_id, lions.permanent_id]
    )
    assert _w2g6_state(sid, seat=1)["trigger_target"] is None

    too_many = _w2g6_act(
        sid, seat=0, action="trigger_target_confirm",
        target_permanent_ids=[bears.permanent_id, giant.permanent_id, lions.permanent_id],
    )
    assert too_many.status_code == 400, too_many.json()
    assert _w2g6_state(sid)["trigger_target"] is not None, "still owed"

    answered = _w2g6_act(
        sid, seat=0, action="trigger_target_confirm",
        target_permanent_ids=[bears.permanent_id, lions.permanent_id],
    )
    assert answered.status_code == 200, answered.json()
    assert _w2g6_state(sid)["trigger_target"] is None

    game.resolve_top_of_stack()
    counters = [p.metadata.get("plus_counters", 0) for p in (bears, giant, lions)]
    assert counters == [1, 0, 1]


def test_w2g6_a_one_target_trigger_prompt_carries_no_ceiling(catalog_by_name):
    """Every ability that prints one target raises the payload it always did."""
    sid, game = _w2g6_session()
    bears = _w2g6_enter(game, catalog_by_name, 1, "Grizzly Bears")
    _w2g6_enter(game, catalog_by_name, 0, "Man-o'-War")

    prompt = _w2g6_state(sid)["trigger_target"]
    assert "max_targets" not in prompt
    answered = _w2g6_act(
        sid, seat=0, action="trigger_target_confirm",
        target_permanent_id=bears.permanent_id,
    )
    assert answered.status_code == 200, answered.json()
