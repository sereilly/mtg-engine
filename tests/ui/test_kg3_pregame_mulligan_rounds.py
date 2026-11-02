"""The web table takes its mulligans by CR 103.5's rounds.

"First, the starting player declares whether they will take a mulligan. Then
each other player in turn order does the same. Once each player has made a
declaration, all players who decided to take mulligans do so at the same time
… This process is then repeated until no player takes a mulligan."

Until the kg3 round the sequential table let each seat mulligan until it kept
before the next seat declared — a seat declared having seen the earlier seats'
whole mulligan runs in the shared log — and the simultaneous table let a seat
run through its rounds while another was still making its first declaration.

Each test drives sessions through ``TestClient`` and reads what every seat is
served after every step. The AI seats' declarations are scripted (a stand-in
for ``ai_mulligan.keeps_opening_hand`` that records each call), so the rounds,
not the AI's judgement, are the subject. **The invariant**, asserted at every
step through :func:`_served_everyone`: a seat asked to declare after *m*
mulligans is served a log in which no seat has taken more than *m* — while
round *k* is open nobody has taken a *k*-th — so no seat declares having seen
another's next hand. Validated backwards against ``web/pregame.py`` and
``web/action_pregame.py`` as they were (each seat redrawing as it declared):
every test here fails, the invariant first wherever a mulligan was declared
ahead of another seat's declaration.
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest import mock

import pytest

from fastapi.testclient import TestClient

import web.pregame as pregame
from web.app import app, store

client = TestClient(app)


def _post(sid: str, seat: int, action: str, **extra):
    return client.post(
        f"/api/sessions/{sid}/action", json={"seat": seat, "action": action, **extra}
    )


def _action(sid: str, seat: int, action: str, **extra) -> dict:
    resp = _post(sid, seat, action, **extra)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _state(sid: str, seat: int) -> dict:
    resp = client.get(f"/api/sessions/{sid}/state", params={"seat": seat})
    assert resp.status_code == 200, resp.text
    return resp.json()


@contextmanager
def _scripted_ai(answers: dict[int, list[bool]], declared: list[tuple[int, int]]):
    """AI seats answer keep (True) / mulligan (False) from *answers*, in
    order; each call is recorded as (seat, mulligans taken so far)."""
    def decide(game, seat):
        declared.append((seat, game.players[seat].mulligans_taken))
        return answers[seat].pop(0)

    with mock.patch.object(pregame, "keeps_opening_hand", decide):
        yield


def _seed_for(body: dict, flip_winner: int) -> int:
    """A seed whose coin flip goes to *flip_winner* (the flip is the session
    seed's, ``Random(seed + 2)``), found with throwaway sessions before any
    script is in place — an AI seat that wins a flip declares at once."""
    for seed in range(5000, 5400):
        created = client.post("/api/sessions", json={**body, "seed": seed})
        assert created.status_code == 200, created.text
        if store.get(created.json()["session_id"]).coin_flip_winner == flip_winner:
            return seed
    pytest.fail(f"no seed gave seat {flip_winner} the flip")


def _open(body: dict, seed: int) -> str:
    created = client.post("/api/sessions", json={**body, "seed": seed})
    assert created.status_code == 200, created.text
    return created.json()["session_id"]


def _served_everyone(sid: str) -> list[dict]:
    """Every seat's payload, with the round invariant asserted of each.

    Read off the payload a deciding seat is served: a seat asked to declare,
    having taken *m* mulligans, is in round *m + 1*, so no seat's served log
    may show it more than *m* mulligans taken — a seat that kept earlier
    took fewer, and a seat of the round has taken *m*, its next one waiting
    on the round. And, read off the session, every seat of the open round has
    taken exactly *k − 1*."""
    session = store.get(sid)
    game = session.game
    names = [player.name for player in game.players]
    served = [_state(sid, seat) for seat in range(len(game.players))]
    for seat, payload in enumerate(served):
        info = payload.get("pregame") or {}
        if info.get("phase") != "mulligan" or not info.get("is_my_turn"):
            continue
        mine = info["mulligans_taken"]
        for other, name in enumerate(names):
            taken = sum(1 for line in payload["log"] if line.startswith(f"{name} took mulligan #"))
            assert taken <= mine, (
                f"{names[seat]} declares after {mine} mulligan(s), having seen "
                f"{name} take {taken}",
                [line for line in payload["log"] if "mulligan" in line],
            )
    if session.pregame_phase in ("mulligan", "bottom_select") and session.mulligan_round_seats:
        k = session.mulligan_round
        for seat in session.mulligan_round_seats:
            assert game.players[seat].mulligans_taken == k - 1, (seat, k)
    return served


def _mulligan_log(sid: str) -> list[str]:
    return [line for line in store.get(sid).game.log if "mulligan" in line or "keeps" in line]


# --- two seats: human vs AI, sequential -------------------------------------


def test_the_ai_starts_and_its_mulligan_waits_for_the_human_s_declaration():
    body = {"mode": "human_vs_ai", "host_name": "Host", "enable_pregame": True}
    seed = _seed_for(body, 1)
    declared: list = []
    with _scripted_ai({1: [False, True]}, declared):
        sid = _open(body, seed)
        session = store.get(sid)
        game = session.game
        ai_seven = list(game.players[1].hand)

        # Round 1: the AI (the starting player) declared a mulligan; the human
        # is offered its declaration with the AI's mulligan not yet taken.
        host, ai = _served_everyone(sid)
        assert declared == [(1, 0)]
        assert host["pregame"]["phase"] == "mulligan"
        assert host["pregame"]["is_my_turn"] is True
        assert host["pregame"]["mulligans_taken"] == 0
        assert ai["pregame"]["is_my_turn"] is False
        assert "AI will take a mulligan" in host["log"]
        assert game.players[1].hand == ai_seven
        assert host["players"][1]["hand_count"] == 7

        # The human declares a mulligan too: the round is complete, and both
        # mulligans are taken together, the starting player's shuffle first.
        _action(sid, 0, "mulligan_take")
        host, ai = _served_everyone(sid)
        log = _mulligan_log(sid)
        assert log.index("AI took mulligan #1, redrew 7 cards") < log.index(
            "Host took mulligan #1, redrew 7 cards"
        )
        assert session.mulligan_round == 2

        # Round 2: the AI declares first again — keep, bottoming its one card
        # — and only then is the human asked, with one mulligan taken.
        assert declared == [(1, 0), (1, 1)]
        assert host["pregame"]["is_my_turn"] is True
        assert host["pregame"]["mulligans_taken"] == 1
        assert len(game.players[1].hand) == 6

        _action(sid, 0, "mulligan_keep")
        host, _ = _served_everyone(sid)
        assert host["pregame"]["phase"] == "bottom_select"
        assert host["pregame"]["required_count"] == 1
        _action(sid, 0, "mulligan_bottom_select", hand_index=0)
        _action(sid, 0, "mulligan_bottom_confirm")

    host, _ = _served_everyone(sid)
    assert host["pregame"] is None
    assert host["current_turn"] == 1
    assert [len(p.hand) for p in game.players] == [6, 6]


def test_a_seat_that_keeps_is_not_asked_again():
    body = {"mode": "human_vs_ai", "host_name": "Host", "enable_pregame": True}
    seed = _seed_for(body, 0)
    declared: list = []
    with _scripted_ai({1: [True]}, declared):
        sid = _open(body, seed)
        _action(sid, 0, "coin_flip_choose", hand_index=0)
        # The human declares first (the starting player) and mulligans; the
        # AI keeps; the round ends and only the human declares in round 2.
        host, _ = _served_everyone(sid)
        assert host["pregame"]["is_my_turn"] is True
        assert declared == []
        _action(sid, 0, "mulligan_take")
        assert declared == [(1, 0)]
        host, _ = _served_everyone(sid)
        assert store.get(sid).mulligan_round_seats == [0]
        assert host["pregame"]["is_my_turn"] is True
        assert host["pregame"]["mulligans_taken"] == 1
        _action(sid, 0, "mulligan_take")
        _action(sid, 0, "mulligan_keep")
        assert declared == [(1, 0)]
        _action(sid, 0, "mulligan_bottom_select", hand_index=0)
        _action(sid, 0, "mulligan_bottom_select", hand_index=1)
        _action(sid, 0, "mulligan_bottom_confirm")
    game = store.get(sid).game
    assert store.get(sid).pregame_phase is None
    assert [len(p.hand) for p in game.players] == [5, 7]


def test_no_mulligan_past_a_hand_of_zero_cards():
    body = {"mode": "human_vs_ai", "host_name": "Host", "enable_pregame": True}
    seed = _seed_for(body, 0)
    with _scripted_ai({1: [True]}, []):
        sid = _open(body, seed)
        _action(sid, 0, "coin_flip_choose", hand_index=0)
        for _ in range(7):
            _action(sid, 0, "mulligan_take")
        refused = _post(sid, 0, "mulligan_take")
        assert refused.status_code == 400
        assert "0 cards" in refused.json()["detail"]
        assert store.get(sid).game.players[0].mulligans_taken == 7


# --- four seats: free-for-all, sequential -------------------------------------


def test_a_four_seat_table_declares_in_turn_order_and_mulligans_together():
    seats = [
        {"name": "Host", "is_ai": False, "colors": 2},
        {"name": "Bot1", "is_ai": True, "colors": 2},
        {"name": "Bot2", "is_ai": True, "colors": 2},
        {"name": "Bot3", "is_ai": True, "colors": 2},
    ]
    body = {"mode": "free_for_all", "seats": seats, "enable_pregame": True}
    seed = _seed_for(body, 2)
    declared: list = []
    answers = {2: [False, True], 3: [True], 1: [False, False, True]}
    with _scripted_ai(answers, declared):
        sid = _open(body, seed)
        session = store.get(sid)
        game = session.game

        # Round 1 in turn order from Bot2: Bot2 mulligans, Bot3 keeps, and the
        # host is asked before Bot1 has declared — with Bot2's mulligan not
        # yet taken.
        served = _served_everyone(sid)
        assert declared == [(2, 0), (3, 0)]
        assert served[0]["pregame"]["is_my_turn"] is True
        assert "Bot2 will take a mulligan" in served[0]["log"]
        assert all(not p["pregame"]["is_my_turn"] for p in served[1:])

        _action(sid, 0, "mulligan_take")
        # Bot1 declared after the host; the round's three mulligans were taken
        # together, in turn order from the starting player.
        served = _served_everyone(sid)
        assert declared[:3] == [(2, 0), (3, 0), (1, 0)]
        log = _mulligan_log(sid)
        took = [line.split(" took")[0] for line in log if "took mulligan #1" in line]
        assert took == ["Bot2", "Host", "Bot1"]
        assert log.index("Bot1 will take a mulligan") < log.index("Bot2 took mulligan #1, redrew 7 cards")

        # Round 2 among Bot2, the host and Bot1: Bot2 keeps (CR 103.5c: its
        # first mulligan was free, so it bottoms nothing), then the host.
        assert session.mulligan_round_seats == [2, 0, 1]
        assert declared[3] == (2, 1)
        assert served[0]["pregame"]["is_my_turn"] is True
        assert served[0]["pregame"]["mulligans_taken"] == 1
        assert len(game.players[2].hand) == 7

        _action(sid, 0, "mulligan_keep")  # free first mulligan: nothing owed
        # Bot1 mulligans again, alone in round 3, then keeps owing one card.
    served = _served_everyone(sid)
    assert declared == [(2, 0), (3, 0), (1, 0), (2, 1), (1, 1), (1, 2)]
    assert served[0]["pregame"] is None
    assert served[0]["current_turn"] == 2
    assert [len(p.hand) for p in game.players] == [7, 6, 7, 7]
    assert [p.mulligans_taken for p in game.players] == [1, 2, 1, 0]


# --- simultaneous declarations -------------------------------------------------


def _two_humans_simultaneous() -> str:
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human", "host_name": "Alice", "guest_name": "Bob",
            "seed": 99, "enable_pregame": True, "simultaneous_mulligan": True,
        },
    )
    assert created.status_code == 200, created.text
    sid = created.json()["session_id"]
    assert client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Bob"}).status_code == 200
    assert client.post(f"/api/sessions/{sid}/start", json={"seat": 0}).status_code == 200
    _action(sid, store.get(sid).coin_flip_winner, "coin_flip_choose", hand_index=0)
    return sid


def test_a_simultaneous_mulligan_waits_for_every_declaration_of_its_round():
    sid = _two_humans_simultaneous()
    game = store.get(sid).game
    bob_seven = list(game.players[1].hand)

    _action(sid, 1, "mulligan_take")
    alice, bob = _served_everyone(sid)
    # Bob's mulligan is declared, not taken: his hand is the seven he
    # declared over, and he waits on Alice's declaration.
    assert game.players[1].hand == bob_seven
    assert bob["pregame"]["is_my_turn"] is False
    assert bob["pregame"]["waiting_for"] == "Alice"
    assert alice["pregame"]["is_my_turn"] is True
    assert "Bob will take a mulligan" in alice["log"]
    # He may not keep or mulligan again before the round is over.
    for action in ("mulligan_keep", "mulligan_take"):
        refused = _post(sid, 1, action)
        assert refused.status_code == 400
        assert "every player has declared" in refused.json()["detail"]

    _action(sid, 0, "mulligan_keep")
    alice, bob = _served_everyone(sid)
    assert game.players[1].mulligans_taken == 1
    assert bob["pregame"]["is_my_turn"] is True
    assert bob["pregame"]["mulligans_taken"] == 1
    assert alice["pregame"]["is_my_turn"] is False
    assert alice["pregame"]["waiting_for"] == "Bob"

    _action(sid, 1, "mulligan_keep")
    _, bob = _served_everyone(sid)
    assert bob["pregame"]["phase"] == "bottom_select"
    _action(sid, 1, "mulligan_bottom_select", hand_index=3)
    _action(sid, 1, "mulligan_bottom_confirm")
    assert store.get(sid).pregame_phase is None
    assert [len(p.hand) for p in game.players] == [7, 6]


def test_a_simultaneous_table_s_ai_seats_declare_each_round_at_once():
    seats = [
        {"name": "Host", "is_ai": False, "colors": 2},
        {"name": "Bot1", "is_ai": True, "colors": 2},
        {"name": "Bot2", "is_ai": True, "colors": 2},
    ]
    body = {"mode": "free_for_all", "seats": seats, "enable_pregame": True,
            "simultaneous_mulligan": True}
    seed = _seed_for(body, 0)
    declared: list = []
    with _scripted_ai({1: [False, True], 2: [True]}, declared):
        sid = _open(body, seed)
        _action(sid, 0, "coin_flip_choose", hand_index=0)
        # Both AI seats declared at once; Bot1's mulligan waits on the host.
        served = _served_everyone(sid)
        assert sorted(declared) == [(1, 0), (2, 0)]
        assert served[0]["pregame"]["is_my_turn"] is True
        assert store.get(sid).game.players[1].mulligans_taken == 0
        _action(sid, 0, "mulligan_take")
        # The round's two mulligans were taken together; round 2 asks the host
        # and Bot1, and Bot1 declared at once again.
        served = _served_everyone(sid)
        assert declared[2:] == [(1, 1)]
        assert served[0]["pregame"]["is_my_turn"] is True
        _action(sid, 0, "mulligan_keep")
    game = store.get(sid).game
    assert store.get(sid).pregame_phase is None
    assert [p.mulligans_taken for p in game.players] == [1, 1, 0]
    assert [len(p.hand) for p in game.players] == [7, 7, 7]
