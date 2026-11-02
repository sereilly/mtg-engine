"""The web's no-pregame first deal plays first the seat that chose (CR 103.1, 103.8).

"103.1 … The player chosen to take the first turn is the starting player"; "103.8.
The starting player takes their first turn." A table created without the
pregame — an API client's or a test's; the browser always sends
``enable_pregame`` — asks nobody, so the flip's winner plays first
(``SessionStore._begin_pregame``).

Until the kg3 round a human_vs_ai or human_vs_human table dealt that way named
the flip's winner in ``Session.current_turn`` while the engine's active player
and priority stayed on seat 0, the ``Game`` constructor's default, and its turn
1 had no beginning phase (``Session.first_turn_owed`` was set only where the
seat already followed the chooser: ai_vs_ai, Free-For-All, a rematch). A seat-1
flip was a split seat: the payload said one player's turn while the engine let
the other act, and refused the player whose turn it said it was.

The census creates both two-seat modes over a run of seeds through the route a
client calls, and the Settings restart of each, and reads the session store and
every seat's payload: one seat holds the turn, the engine's active player and
priority, and its turn 1 has begun. It asserts a floor on what it examined —
every table, and a seat-0 and a seat-1 start in each mode.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import web.session_store as web_session_store
from web.app import app, store
from web.seats import _seat_type

client = TestClient(app)

_MODES = ("human_vs_ai", "human_vs_human")
_SEEDS = range(1, 13)


def _create(mode: str, seed: int) -> str:
    """A table created without the pregame: it is dealt, and turn 1 begun,
    by this request — a human_vs_human guest joins afterwards (`_join`)."""
    created = client.post("/api/sessions", json={"mode": mode, "seed": seed})
    assert created.status_code == 200, created.text
    return created.json()["session_id"]


def _join(sid: str) -> None:
    if store.get(sid).mode == "human_vs_human":
        joined = client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
        assert joined.status_code == 200, joined.text


def _refused_priority(response, label) -> None:
    """Refused for the priority the seat does not hold (the wording is the
    action's: "you do not currently have priority" or the engine's "player does
    not have priority")."""
    assert response.status_code == 400, (label, response.text)
    detail = response.json()["detail"]
    assert "not" in detail and "have priority" in detail, (label, detail)


def _state(sid: str, seat: int) -> dict:
    served = client.get(f"/api/sessions/{sid}/state", params={"seat": seat})
    assert served.status_code == 200, served.text
    return served.json()


def _act(sid: str, seat: int, action: str):
    return client.post(f"/api/sessions/{sid}/action", json={"seat": seat, "action": action})


def _assert_one_seat_first(sid: str, label) -> int:
    """The seat that plays first holds the session's turn, the engine's active
    player and priority, on the store and on every seat's payload, and its
    turn 1 began: the untap step ran and CR 103.8a skipped its draw. Returns
    that seat."""
    session = store.get(sid)
    game = session.game
    start = session.coin_flip_winner
    assert start in (0, 1), label
    assert session.pregame_phase is None, label
    assert (session.current_turn, game.active_player_index, game.priority_player_index) == (
        start, start, start,
    ), label
    assert session.first_turn_owed is False, label
    assert game.turn == 1 and game.seat_turn_counts == {start: 1}, (label, game.seat_turn_counts)
    name = game.players[start].name
    assert any(line.startswith(f"{name} untapped ") for line in game.log), (label, game.log[-6:])
    assert f"{name} skips the first turn's draw step (CR 103.8a)" in game.log, (label, game.log[-6:])
    for viewer in (0, 1):
        served = _state(sid, viewer)
        assert served["current_turn"] == start, label
        assert served["priority_player"] == start, label
        assert served["turn_number"] == 1, label
        assert served["current_step"] == "precombat_main", (label, served["current_step"])
    return start


def test_every_no_pregame_first_deal_puts_one_seat_first():
    seen: list[tuple[str, int]] = []
    for mode in _MODES:
        for seed in _SEEDS:
            label = (mode, seed)
            sid = _create(mode, seed)
            start = _assert_one_seat_first(sid, label)
            _join(sid)
            other = 1 - start
            # The seat whose turn the table names is the seat the engine lets
            # act, and the other is refused — never the reverse. (A
            # human_vs_ai AI seat sends nothing: the server acts for it.)
            if _seat_type(store.get(sid), other) == "human":
                _refused_priority(_act(sid, other, "pass_priority"), label)
            if _seat_type(store.get(sid), start) == "human":
                passed = _act(sid, start, "pass_priority")
                assert passed.status_code == 200, (label, passed.text)
                if _seat_type(store.get(sid), other) == "human":
                    assert store.get(sid).game.priority_player_index == other, label
            seen.append((mode, start))

    assert len(seen) == len(_MODES) * len(_SEEDS), seen
    for mode in _MODES:
        assert {start for m, start in seen if m == mode} == {0, 1}, (mode, seen)


def test_the_settings_restart_deals_the_same_way(monkeypatch):
    """``store.restart`` reshuffles off a new seed and deals through the same
    branch; pinned here so a run is the same run."""
    starts: set[tuple[str, int]] = set()
    for mode in _MODES:
        sid = _create(mode, 1)
        _join(sid)
        for bits in (101, 102, 103, 104):
            monkeypatch.setattr(web_session_store.secrets, "randbits", lambda _bits, b=bits: b)
            restarted = client.post(f"/api/sessions/{sid}/restart", json={"seat": 0})
            assert restarted.status_code == 200, restarted.text
            starts.add((mode, _assert_one_seat_first(sid, (mode, "restart", bits))))
    assert starts == {(mode, seat) for mode in _MODES for seat in (0, 1)}, starts


def test_an_ai_that_plays_first_takes_its_turn_and_hands_the_next_one_over():
    """The deadlock ai_vs_ai had before its seat was aligned, asked of a
    human_vs_ai table the AI's flip starts: driven as the browser drives it —
    ``ai_step`` while the AI holds priority, a pass while the human does — the
    AI's turn 1 is played out, and turn 2 is the human's, begun with its draw."""
    sid = next(
        sid for sid in (_create("human_vs_ai", seed) for seed in _SEEDS)
        if store.get(sid).coin_flip_winner == 1
    )
    _assert_one_seat_first(sid, "human_vs_ai, the AI first")
    _refused_priority(_act(sid, 0, "pass_priority"), "the human, on the AI's turn 1")
    game = store.get(sid).game
    turn_one = len(game.log)

    for _ in range(24):
        if store.get(sid).current_turn == 0:
            break
        action = "pass_priority" if game.priority_player_index == 0 else "ai_step"
        stepped = _act(sid, 0, action)
        assert stepped.status_code == 200, (action, stepped.text)

    session = store.get(sid)
    assert session.current_turn == 0, game.log[-8:]
    assert game.turn == 2 and game.seat_turn_counts == {1: 1, 0: 1}, game.seat_turn_counts
    assert game.active_player_index == 0
    name = game.players[0].name
    assert f"{name} drew 1 card(s) in draw step" in game.log[turn_one:], (
        "the human's first turn is the game's second: CR 103.8a skips no draw of it"
    )
    assert _act(sid, 0, "pass_priority").status_code == 200
