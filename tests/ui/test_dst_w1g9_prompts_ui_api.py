"""DST W1G9: what the wire carries for the two prompts this group's cards arm
in a new shape, each answered through the action endpoint a browser uses.

* **Scrounge's pick** is the graveyard pick prompt (``graveyard_exile_pick``)
  owed by the *opponent*, over their own pile, with ``destination: "chosen"`` —
  a pick that moves nothing and is read by the sentence behind it. The client
  must word it as a choice ("choose an artifact card"), not as an exile.
* **Sundering Titan's choice** is the keep prompt (``keep_permanents``) with
  ``fate: "destroy_chosen"`` and ``every_battlefield``: its candidates sit on
  *both* battlefields, each with its own ``seat``. The client must draw them
  wherever they are and word the fate as a destruction.

The running app cannot hold a measured set's card, so the cards are put into a
session by hand; the route the answer travels is the real one.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.models import Permanent
from web.app import app, store

client = TestClient(app)


def _session(*, hand0=(), bf0=(), bf1=(), gy1=()):
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
            "host_colors": 2, "guest_colors": 2, "seed": 4242,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    for seat, hand in enumerate((hand0, ())):
        game.players[seat].hand = list(hand)
        game.players[seat].library = []
        game.players[seat].graveyard = []
    game.players[1].graveyard = list(gy1)
    for player in game.players:
        for permanent in list(game.controlled_by(player)):
            game.remove_from_battlefield(permanent)
    for seat, cards in enumerate((bf0, bf1)):
        for card in cards:
            game._put_permanent_onto_battlefield(seat, Permanent(card=card), None)
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    return sid, game


def _act(sid: str, **body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def _state(sid: str, seat: int = 0) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _cast_and_pass(sid: str, name: str, **extra):
    cast = _act(sid, seat=0, action="cast", card_name=name, **extra)
    assert cast.status_code == 200, cast.json()
    for seat in (0, 1):
        passed = _act(sid, seat=seat, action="pass_priority")
        assert passed.status_code == 200, passed.json()


def test_scrounge_asks_the_opponent_over_the_wire_and_moves_their_answer(set_pool):
    dst, lea = set_pool("DST"), set_pool("LEA")
    sid, game = _session(
        hand0=[dst["Scrounge"]],
        gy1=[lea["Juggernaut"], lea["Grizzly Bears"], lea["Sol Ring"]],
    )
    _cast_and_pass(sid, "Scrounge", target_player_index=1)

    prompt = _state(sid, seat=1)["graveyard_exile_pick"]
    assert prompt is not None, "the opponent owes the pick"
    assert prompt["player_seat"] == 1 and prompt["owner_seat"] == 1
    assert prompt["destination"] == "chosen"
    assert prompt["count"] == 1 and prompt["up_to"] is False
    assert prompt["legal_indices"] == [0, 2]

    refused = _act(sid, seat=0, action="graveyard_exile_confirm", graveyard_indices=[0])
    assert refused.status_code == 400, "not the caster's choice"
    answered = _act(sid, seat=1, action="graveyard_exile_confirm", graveyard_indices=[2])
    assert answered.status_code == 200, answered.json()
    assert [p.card.name for p in game.controlled_by(0)] == ["Sol Ring"]
    assert [card.name for card in game.players[1].graveyard] == ["Juggernaut", "Grizzly Bears"]


def test_sundering_titan_offers_lands_on_both_battlefields_over_the_wire(set_pool):
    dst, lea = set_pool("DST"), set_pool("LEA")
    sid, game = _session(
        hand0=[dst["Sundering Titan"]],
        bf0=[lea["Plains"], lea["Island"]],
        bf1=[lea["Plains"], lea["Swamp"], lea["Mountain"], lea["Forest"]],
    )
    _cast_and_pass(sid, "Sundering Titan")
    # The Titan resolved; its entry trigger is on the stack.
    for seat in (0, 1):
        _act(sid, seat=seat, action="pass_priority")

    prompt = _state(sid)["keep_permanents"]
    assert prompt is not None
    assert prompt["fate"] == "destroy_chosen" and prompt["every_battlefield"] is True
    seats = sorted({candidate["seat"] for candidate in prompt["candidates"]})
    assert seats == [0, 1]
    by_name_seat = {(c["name"], c["seat"]): c["id"] for c in prompt["candidates"]}
    # Bob's Plains, not Alice's; Alice's Island is the only Island.
    answer = [
        by_name_seat[("Plains", 1)], by_name_seat[("Island", 0)],
        by_name_seat[("Swamp", 1)], by_name_seat[("Mountain", 1)],
        by_name_seat[("Forest", 1)],
    ]
    short = _act(sid, seat=0, action="keep_permanents_confirm",
                 target_permanent_ids=answer[1:])
    assert short.status_code == 400, "a Plains is on the battlefield and must be chosen"
    answered = _act(sid, seat=0, action="keep_permanents_confirm",
                    target_permanent_ids=answer)
    assert answered.status_code == 200, answered.json()
    assert [p.card.name for p in game.controlled_by(0)] == ["Plains", "Sundering Titan"]
    assert [p.card.name for p in game.controlled_by(1)] == []
