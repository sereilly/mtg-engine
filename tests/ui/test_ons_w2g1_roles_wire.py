"""Blatant Thievery and Kaboom! through the wire: two roles announcements a
client walks and sends as ``target_role_refs``.

* **Blatant Thievery** ("For each opponent, gain control of target permanent
  that player controls"): the hand card's ``target_spec`` is a ``roles`` spec
  with **one owed role per opponent at this table** (no ``optional_role``),
  role *n* offering only the *n*-th opponent's permanents in turn order from
  the caster — so the ``valid_targets`` tree is walked to its end and every
  level answered.
* **Kaboom!** ("Choose any number of target players or planeswalkers. For
  each of them, …"): twelve ``optional_role`` roles of kind
  ``player_or_planeswalker``; each level's options are players (``kind:
  "player"``, a ``seat``) and planeswalkers (``kind: "permanent"``), later in
  turn order than the one before — the client may stop at any level.

The engine's own reads of both shapes are in ``tests/sets/test_ons_sorceries.py``
(W2G1's section); this pins what the wire carries and accepts. A measured
set's card is dealt here by putting it in the hand of a session made for the
test, which is what a card in hand looks like to the client.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from engine.models import Permanent
from engine.named_counters import add_counters, counters_on
from tests.helpers import _mk_card
from web.app import app, store

client = TestClient(app)


def _table(set_pool, spell, seats=3):
    created = client.post("/api/sessions", json={
        "mode": "free_for_all", "seed": 7,
        "seats": [
            {"name": f"P{i + 1}", "is_ai": False, "colors": 2} for i in range(seats)
        ],
    })
    assert created.status_code == 200, created.text
    sid = created.json()["session_id"]
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    session.current_turn = 0
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game.priority_player_index = 0
    for player in game.players:
        player.battlefield[:] = []
    game.players[0].hand[:] = [set_pool("ONS")[spell]]
    game._sync_control()
    return sid, game


def _put(game, seat, name, type_line="Creature - Bear"):
    permanent = Permanent(card=_mk_card(
        name=name, mana_cost="{1}{G}", type_line=type_line, colors=("G",),
    ))
    permanent.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(permanent)
    game._sync_control()
    return permanent


def _hand_spec(sid, name):
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    (card,) = [c for c in state["players"][0]["hand"] if c["name"] == name]
    return card["target_spec"]


def test_blatant_thievery_spec_owes_one_role_per_opponent(set_pool):
    sid, game = _table(set_pool, "Blatant Thievery")
    _put(game, 1, "B Bear")
    _put(game, 2, "C Bear")
    spec = _hand_spec(sid, "Blatant Thievery")
    assert spec["kind"] == "roles"
    assert [role["role"] for role in spec["roles"]] == [
        "opponent 1's target", "opponent 2's target",
    ]
    assert not any(role.get("optional_role") for role in spec["roles"])
    (first,) = spec["valid_targets"]
    assert (first["seat"], first["name"]) == (1, "B Bear")
    assert [(n["seat"], n["name"]) for n in first["next"]] == [(2, "C Bear")]


def test_blatant_thievery_cast_through_the_action_endpoint(set_pool):
    sid, game = _table(set_pool, "Blatant Thievery")
    b_bear = _put(game, 1, "B Bear")
    c_bear = _put(game, 2, "C Bear")
    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "cast", "card_name": "Blatant Thievery",
        "target_role_refs": [
            {"permanent_id": b_bear.permanent_id},
            {"permanent_id": c_bear.permanent_id},
        ],
    })
    assert response.status_code == 200, response.text
    game.resolve_stack()
    assert sorted(p.card.name for p in game.controlled_by(0)) == ["B Bear", "C Bear"]


def test_kaboom_spec_is_an_optional_chain_of_players_and_planeswalkers(set_pool):
    sid, game = _table(set_pool, "Kaboom!")
    walker = _put(game, 1, "B Walker", "Legendary Planeswalker - Chandra")
    add_counters(walker, "loyalty", 5)
    spec = _hand_spec(sid, "Kaboom!")
    assert spec["kind"] == "roles" and len(spec["roles"]) == 12
    assert all(role.get("optional_role") for role in spec["roles"])
    assert sorted((o["kind"], o["seat"]) for o in spec["valid_targets"]) == [
        ("permanent", 1), ("player", 0), ("player", 1), ("player", 2),
    ]


def test_kaboom_cast_through_the_action_endpoint(set_pool):
    sid, game = _table(set_pool, "Kaboom!")
    ons = set_pool("ONS")
    game.players[0].library[:] = [ons["Shock"], ons["Clone"], ons["Swat"]]
    walker = _put(game, 1, "B Walker", "Legendary Planeswalker - Chandra")
    add_counters(walker, "loyalty", 5)
    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "cast", "card_name": "Kaboom!",
        "target_role_refs": [
            {"seat": 1}, {"permanent_id": walker.permanent_id}, {"seat": 2},
        ],
    })
    assert response.status_code == 200, response.text
    game.resolve_stack()
    assert [p.life for p in game.players] == [20, 19, 17]
    assert counters_on(walker, "loyalty") == 1
