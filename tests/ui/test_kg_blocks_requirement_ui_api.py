"""Web-API test: a block declaration CR 509.1c refuses says why, on the wire.

The engine's refusal is the 400's ``detail``, which is the only thing a person
declaring blocks in the browser is shown. Three Watchdogs under Caverns of
Despair is the board that had **no** legal declaration — every one the client
could send came back 400 and the human defender was stuck at the
declare-blockers step for good — so this asserts both halves: the illegal
declaration names the requirement and the count, and a maximal one is taken.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import _mk_creature_card
from web.app import app, store
from tests.helpers import combat_ids

client = TestClient(app)

_CARDS = {card.name: card for card in load_catalog()}


def _session():
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_human", "host_name": "H", "host_colors": 2,
              "guest_colors": 2, "seed": 5},
    ).json()
    sid = created["session_id"]
    session = store.get(sid)
    session.joined_seats.add(1)
    return sid, session, session.game


def _three_watchdogs_under_caverns(game):
    raider = Permanent(card=_mk_creature_card("Raider", 2, 2))
    raider.metadata["summoning_sickness_turn"] = -99
    dogs = [Permanent(card=_CARDS["Watchdog"]) for _ in range(3)]
    for dog in dogs:
        dog.metadata["summoning_sickness_turn"] = -99
    game.players[0].battlefield = [raider, Permanent(card=_CARDS["Caverns of Despair"])]
    game.players[1].battlefield = dogs
    game._sync_control()
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    game.combat_defending_player_index = 1
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"
    return dogs


def test_the_refusal_names_the_requirement_and_how_many_can_be_obeyed():
    sid, session, game = _session()
    session.current_turn = 0
    _three_watchdogs_under_caverns(game)

    refused = client.post(
        f"/api/sessions/{sid}/action",
        json=combat_ids(store.get(sid).game, {"seat": 1, "action": "declare_blockers", "blocker_pairs": {"0": 0}}),
    )
    assert refused.status_code == 400
    assert refused.json()["detail"] == (
        "Watchdog blocks each combat if able (this declaration obeys 1 of the 2 "
        "blocking requirements that can be obeyed together)"
    )
    assert not game.combat_blockers_locked

    over_cap = client.post(
        f"/api/sessions/{sid}/action",
        json=combat_ids(store.get(sid).game, {"seat": 1, "action": "declare_blockers",
              "blocker_pairs": {"0": 0, "1": 0, "2": 0}}),
    )
    assert over_cap.status_code == 400
    assert "no more than 2" in over_cap.json()["detail"]

    accepted = client.post(
        f"/api/sessions/{sid}/action",
        json=combat_ids(store.get(sid).game, {"seat": 1, "action": "declare_blockers",
              "blocker_pairs": {"0": 0, "2": 0}}),
    )
    assert accepted.status_code == 200, accepted.json()
    assert game.combat_blockers == {1: {0: [0], 2: [0]}}
    assert game.combat_blockers_locked
