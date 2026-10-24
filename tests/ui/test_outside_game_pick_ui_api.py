"""Web-API tests for the Wishes' pick from outside the game (Judgment W1G6).

"You may reveal a sorcery card you own from outside the game and put it into
your hand." The server half of the wire, end to end over the HTTP routes: the
cast, the "you may" (the ordinary ``optional_pay`` offer the client already
answers), the ``outside_game_pick`` payload a person is shown — only to the
seat whose sideboard it is — and ``outside_game_pick_confirm``, which re-checks
the pick against the printed type. The browser half is ``app.js``'s
``renderOutsideGamePickModal``, run against this payload in
``tests/ui/test_jud_w2g1_client_ui_api.py``.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from web.app import app, store

client = TestClient(app)


def _session(set_pool):
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
            "host_colors": 2, "guest_colors": 2, "seed": 6066,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    lea = set_pool("LEA")
    game.enforce_mana_costs = False
    game.players[0].hand = [set_pool("JUD")["Burning Wish"]]
    game.players[0].sideboard = [lea["Lightning Bolt"], lea["Stone Rain"], lea["Stone Rain"]]
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    return sid, session, game


def _state(sid: str, seat: int = 0) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _act(sid: str, **payload):
    return client.post(f"/api/sessions/{sid}/action", json=payload)


def _cast_and_accept(sid: str):
    assert _act(sid, seat=0, action="cast", card_name="Burning Wish").status_code == 200
    for seat in (0, 1):
        assert _act(sid, seat=seat, action="pass_priority").status_code == 200
    assert _state(sid)["optional_pay"] is not None, "the 'you may' is asked first"
    accepted = _act(sid, seat=0, action="resolve_optional_pay",
                    card_name="Burning Wish", accept=True)
    assert accepted.status_code == 200, accepted.json()


def test_the_pick_offers_its_owner_the_sorceries_and_no_one_else_anything(set_pool):
    sid, _session_, _game = _session(set_pool)
    _cast_and_accept(sid)

    prompt = _state(sid)["outside_game_pick"]
    assert prompt["player_seat"] == 0 and prompt["card_name"] == "Burning Wish"
    assert prompt["reveal"] is True and prompt["optional"] is False
    assert [(c["sideboard_index"], c["name"]) for c in prompt["choices"]] == [
        (1, "Stone Rain"), (2, "Stone Rain"),
    ]
    assert prompt["choices"][0]["card"]["name"] == "Stone Rain"
    assert _state(sid, seat=1)["outside_game_pick"] is None


def test_confirming_a_sorcery_brings_it_in_and_a_bolt_is_refused(set_pool):
    sid, _session_, game = _session(set_pool)
    _cast_and_accept(sid)

    assert _act(sid, seat=0, action="outside_game_pick_confirm",
                sideboard_index=0).status_code == 400
    assert _act(sid, seat=1, action="outside_game_pick_confirm",
                sideboard_index=1).status_code == 400
    assert _act(sid, seat=0, action="outside_game_pick_confirm",
                accept=False).status_code == 400, "a pick the offer made mandatory"
    done = _act(sid, seat=0, action="outside_game_pick_confirm", sideboard_index=2)
    assert done.status_code == 200, done.json()

    assert [card.name for card in game.players[0].hand] == ["Stone Rain"]
    assert [card.name for card in game.players[0].sideboard] == ["Lightning Bolt", "Stone Rain"]
    assert [card.name for card in game.players[0].exile] == ["Burning Wish"]
    assert _state(sid)["outside_game_pick"] is None
