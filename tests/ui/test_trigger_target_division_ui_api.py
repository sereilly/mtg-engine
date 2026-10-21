"""Web-API round trip for a triggered ability that **divides** among its targets.

"When this creature dies, distribute three -1/-1 counters among one, two, or
three target creatures." (Shambling Swarm, Torment — the pool's first divided
trigger.) CR 603.3d chooses the targets as the ability goes on the stack, and
CR 601.2d's division is chosen with them. The ``trigger_target`` prompt carries
the total (``division_total``) and who divides it (``division``) beside the
ceiling it already carried for a several-target trigger, and the answer comes
back the way a divided *spell's* announcement does: ``divided_targets``, one
entry per creature with its ``amount``.

The engine half is in ``tests/sets/test_tor_creatures.py`` (W1G8). The browser
has no branch that answers a division on this prompt yet — wave 2's client
group's brief. What the client must send is pinned here.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.models import Permanent
from web.app import app, store

client = TestClient(app)


def _w1g8_session():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 601,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    game = store.get(sid).game
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_phase = "main"
    game.interactive_seats = {0, 1}
    for player in game.players:
        player.battlefield.clear()
    return sid, game


def _w1g8_state(sid: str, seat: int = 0) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _w1g8_act(sid: str, **body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def _w1g8_dying_swarm(set_pool, catalog_by_name):
    sid, game = _w1g8_session()
    swarm = Permanent(card=set_pool("TOR")["Shambling Swarm"])
    game._put_permanent_onto_battlefield(0, swarm, None)
    bears = Permanent(card=catalog_by_name["Grizzly Bears"])
    giant = Permanent(card=catalog_by_name["Hill Giant"])
    game._put_permanent_onto_battlefield(1, bears, None)
    game._put_permanent_onto_battlefield(1, giant, None)
    game.place_pt_counters(swarm, "-1/-1", 3)
    game.check_state_based_actions()
    return sid, game, bears, giant


def test_w1g8_a_divided_trigger_prompt_says_what_to_divide(set_pool, catalog_by_name):
    sid, game, bears, giant = _w1g8_dying_swarm(set_pool, catalog_by_name)

    prompt = _w1g8_state(sid)["trigger_target"]
    assert prompt["card_name"] == "Shambling Swarm"
    assert (prompt["max_targets"], prompt["division_total"]) == (2, 3)
    assert prompt["division"] == "chosen"
    assert sorted(c["id"] for c in prompt["candidates"]) == sorted(
        [bears.permanent_id, giant.permanent_id]
    ), "the dying Swarm is not on offer"


def test_w1g8_a_division_round_trips_as_divided_targets(set_pool, catalog_by_name):
    sid, game, bears, giant = _w1g8_dying_swarm(set_pool, catalog_by_name)

    undivided = _w1g8_act(
        sid, seat=0, action="trigger_target_confirm",
        target_permanent_ids=[bears.permanent_id, giant.permanent_id],
    )
    assert undivided.status_code == 400, "2+1 or 1+2 is the announcer's to say"
    short = _w1g8_act(
        sid, seat=0, action="trigger_target_confirm",
        divided_targets=[
            {"seat": 1, "id": bears.permanent_id, "amount": 1},
            {"seat": 1, "id": giant.permanent_id, "amount": 1},
        ],
    )
    assert short.status_code == 400, "the division must total three"
    assert _w1g8_state(sid)["trigger_target"] is not None, "still owed"

    answered = _w1g8_act(
        sid, seat=0, action="trigger_target_confirm",
        divided_targets=[
            {"seat": 1, "id": bears.permanent_id, "amount": 1},
            {"seat": 1, "id": giant.permanent_id, "amount": 2},
        ],
    )
    assert answered.status_code == 200, answered.json()
    assert _w1g8_state(sid)["trigger_target"] is None

    game.resolve_top_of_stack()
    assert (bears.metadata.get("minus_counters"), giant.metadata.get("minus_counters")) == (1, 2)


def test_w1g8_a_forced_division_may_be_sent_as_ids(set_pool, catalog_by_name):
    """One creature takes all three: nothing to divide, so the plain id list a
    several-target trigger sends is an answer here too."""
    sid, game, bears, giant = _w1g8_dying_swarm(set_pool, catalog_by_name)
    answered = _w1g8_act(
        sid, seat=0, action="trigger_target_confirm",
        target_permanent_ids=[giant.permanent_id],
    )
    assert answered.status_code == 200, answered.json()
    game.resolve_top_of_stack()
    assert giant.metadata.get("minus_counters") == 3
    assert bears.metadata.get("minus_counters") is None
