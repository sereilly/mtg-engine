"""A rematch of a session with no pregame honours CR 103.1's chooser.

"In a match of several games, the loser of the previous game chooses who
takes the first turn. If the previous game was a draw, the player who made
the choice in that game makes the choice in this game." Legions' Phase 5 gave
the rematch its chooser, but only a session with the pregame read it: with
``use_pregame=False`` ``SessionStore._begin_pregame`` flipped a coin for every
game, so the previous game's loser never chose. Nobody is asked anything at a
table with no pregame, so the chooser plays first — the AI's policy at a
pregame table, and what the no-pregame flip's winner does.

Each test finishes a game, asks for the rematch through the route and reads
the payload and the log. Validated backwards: on the tree before the fix every
rematch log here holds a "Coin flip:" line and no chooser line.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from web.app import app, store

client = TestClient(app)


def _state(sid: str, seat: int) -> dict:
    resp = client.get(f"/api/sessions/{sid}/state", params={"seat": seat})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _finished(mode: str, seed: int, losers: tuple[int, ...]) -> str:
    body = {"mode": mode, "host_name": "Solo", "seed": seed}
    if mode == "human_vs_human":
        body["guest_name"] = "Rival"  # an AI seat is named "AI"
    created = client.post("/api/sessions", json=body)
    assert created.status_code == 200, created.text
    sid = created.json()["session_id"]
    session = store.get(sid)
    assert session.use_pregame is False and session.pregame_phase is None
    for seat in losers:
        session.game.players[seat].life = 0
    assert _state(sid, 0)["status"] == "finished"
    return sid


def _rematch(sid: str) -> dict:
    again = client.post(f"/api/sessions/{sid}/rematch", json={"seat": 0})
    assert again.status_code == 200, again.text
    return again.json()


def _assert_starts(sid: str, seat: int) -> None:
    session = store.get(sid)
    served = _state(sid, 0)
    assert served["pregame"] is None
    assert served["status"] == "active"
    assert served["current_turn"] == seat
    assert session.game.active_player_index == seat
    assert session.game.priority_player_index == seat
    assert not any(line.startswith("Coin flip:") for line in session.game.log)


def test_the_human_who_lost_chooses_and_plays_first():
    sid = _finished("human_vs_ai", 8101, losers=(0,))
    _rematch(sid)
    log = store.get(sid).game.log
    assert "Solo lost the last game and chooses who plays first" in log
    assert "Solo chooses to go first" in log
    _assert_starts(sid, 0)


def test_the_ai_that_lost_chooses_and_takes_the_first_turn():
    sid = _finished("human_vs_ai", 8102, losers=(1,))
    _rematch(sid)
    log = store.get(sid).game.log
    assert "AI lost the last game and chooses who plays first" in log
    assert "AI chooses to go first" in log
    _assert_starts(sid, 1)
    # It is the AI's turn in the engine as well as on the wire, so the AI
    # plays it — driven as the client drives it — and hands the human the
    # next one.
    for _ in range(60):
        served = _state(sid, 0)
        if served["current_turn"] == 0:
            break
        action = "pass_priority" if served["priority_player"] == 0 else "ai_step"
        stepped = client.post(
            f"/api/sessions/{sid}/action", json={"seat": 0, "action": action}
        )
        assert stepped.status_code == 200, stepped.text
    else:
        raise AssertionError("the AI's first turn never ended")
    assert store.get(sid).game.turn == 2  # the AI's turn one, then the human's


def test_after_a_draw_the_seat_that_chose_chooses_again():
    sid = _finished("human_vs_ai", 8103, losers=(0, 1))
    first_chooser = store.get(sid).coin_flip_winner
    assert first_chooser is not None  # the no-pregame flip records its winner
    _rematch(sid)
    session = store.get(sid)
    name = session.game.players[first_chooser].name
    assert (
        f"The last game was a draw: {name} chose who played first then and chooses again"
        in session.game.log
    )
    _assert_starts(sid, first_chooser)
    # The choice is recorded again for the game after this one.
    assert session.coin_flip_winner == first_chooser


def test_a_two_human_table_with_no_pregame_hands_the_loser_the_choice():
    sid = _finished("human_vs_human", 8104, losers=(1,))
    _rematch(sid)
    log = store.get(sid).game.log
    assert "Rival lost the last game and chooses who plays first" in log
    assert "Rival chooses to go first" in log
    _assert_starts(sid, 1)
