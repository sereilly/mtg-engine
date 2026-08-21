"""Regression: the opening hand is not "drawn this turn" on turn 1.

CR 103.4's seven cards (and every mulligan redraw, CR 103.5) are dealt before
the game's first turn exists, but they go through ``PlayerState.draw`` like any
draw and so onto ``cards_drawn_this_turn``. The headless ``start_turn`` happens
to reset that record; the web layer's pregame starts turn 1 without it. So in
the browser a "whenever you draw a card" permanent that reached the battlefield
on turn 1 — a Tolarian Kraken put there by the Debug Menu, or a
Lorescale-Coatl-style creature cast off a Sol Ring — announced the whole
opening hand the next time state was checked: nine triggers for one card drawn.

``keep_hand`` now wipes the record (and the sweep memories that compare against
it). These drive both flows that reach turn 1 and assert the record is empty.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine import Game
from engine.models import PlayerState
from tests.helpers import CARDS_BY_NAME
from web.app import app, store

client = TestClient(app)


def test_keeping_an_opening_hand_clears_the_per_turn_draw_record():
    library = [CARDS_BY_NAME["Forest"]] * 12
    p1 = PlayerState(name="P1", library=list(library))
    p2 = PlayerState(name="P2", library=list(library))
    game = Game(players=[p1, p2])

    game.deal_opening_hands(0)
    assert len(p1.cards_drawn_this_turn) == 7, "the deal goes through the draw op"
    game.take_mulligan(1)
    assert len(p2.cards_drawn_this_turn) == 14

    game.keep_hand(0)
    game.keep_hand(1)

    assert p1.cards_drawn_this_turn == []
    assert p2.cards_drawn_this_turn == []
    assert game.draws_announced_this_turn == {}
    assert game.second_draw_fired_this_turn == set()


def test_the_web_pregame_reaches_turn_one_with_an_empty_draw_record():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 31337,
            "enable_pregame": True,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    started = client.post(f"/api/sessions/{sid}/start", json={"seat": 0})
    assert started.status_code == 200, started.json()
    session = store.get(sid)
    game = session.game

    def state(seat):
        return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()

    winner = session.coin_flip_winner
    assert winner is not None
    r = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": winner, "action": "coin_flip_choose", "hand_index": 0},
    )
    assert r.status_code == 200, r.json()
    # Hands are dealt once the flip is decided: every seat now has seven
    # opening-hand draws on the per-turn record, before any turn exists.
    assert all(len(p.cards_drawn_this_turn) >= 7 for p in game.players)
    # Keep with whichever seat is being offered until the game starts.
    for _ in range(6):
        if session.pregame_phase is None:
            break
        offered = [s for s in range(len(game.players)) if state(s).get("pregame")]
        for seat in range(len(game.players)):
            r = client.post(
                f"/api/sessions/{sid}/action",
                json={"seat": seat, "action": "mulligan_keep"},
            )
            if r.status_code == 200:
                break
        else:
            raise AssertionError(f"nobody could keep; offered={offered}")
    assert session.pregame_phase is None, "the game started"

    for player in game.players:
        assert player.cards_drawn_this_turn == [], (
            f"{player.name}'s opening hand is still on the turn-1 draw record"
        )
    assert game.draws_announced_this_turn == {}
