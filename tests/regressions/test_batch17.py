"""Regression tests for the seventeenth batch of bugs reported in playtesting.

Clusters covered in this batch:
- Aspect of Wolf stacking: two Aspect of Wolf auras on the same creature
  under-recorded their combined bonus in ``aspect_of_wolf_bonus`` (only the
  last aura's share), so the clear-and-reapply refresh under-subtracted and the
  creature's power/toughness compounded upward on every state reevaluation.
- Free-For-All game end: ``_winner`` only inspected seats 0 and 1, so in a 3-4
  player game the first elimination could prematurely "finish" the game (seat 0
  dying declared seat 1 the winner even with seats 2/3 alive). The winner is
  now the last seat standing, and each serialized player carries a ``lost``
  flag so eliminated players drop into spectator mode client-side.
"""
from __future__ import annotations

import pytest

from engine import PlayerState
from engine.models import Permanent
from tests.helpers import _game
from tests.helpers import CARDS_BY_NAME as _C


class TestAspectOfWolfStacking:
    def test_two_aspects_on_same_creature_stay_stable_across_refreshes(self):
        bear = Permanent(card=_C["Grizzly Bears"])  # 2/2
        forests = [Permanent(card=_C["Forest"]) for _ in range(3)]
        p1 = PlayerState(
            name="P1",
            hand=[_C["Aspect of Wolf"], _C["Aspect of Wolf"]],
            battlefield=[bear, *forests],
        )
        game = _game(p1, PlayerState(name="P2"))
        game.cast_from_hand(0, "Aspect of Wolf", target_player_index=0, target_permanent_index=0)
        game.cast_from_hand(0, "Aspect of Wolf", target_player_index=0, target_permanent_index=0)

        # 3 Forests -> each Aspect grants +1/+2 -> 2/2 + 2/4 = 4/6.
        assert (bear.effective_power, bear.effective_toughness) == (4, 6)

        # Repeated continuous-effect refreshes must not compound the bonus.
        for _ in range(5):
            game._recompute_continuous_effects()
        assert (bear.effective_power, bear.effective_toughness) == (4, 6)

    def test_two_aspects_track_forest_count_changes(self):
        bear = Permanent(card=_C["Grizzly Bears"])  # 2/2
        forests = [Permanent(card=_C["Forest"]) for _ in range(3)]
        p1 = PlayerState(
            name="P1",
            hand=[_C["Aspect of Wolf"], _C["Aspect of Wolf"]],
            battlefield=[bear, *forests],
        )
        game = _game(p1, PlayerState(name="P2"))
        game.cast_from_hand(0, "Aspect of Wolf", target_player_index=0, target_permanent_index=0)
        game.cast_from_hand(0, "Aspect of Wolf", target_player_index=0, target_permanent_index=0)

        # A 4th Forest enters -> each Aspect grants +2/+2 -> 6/6.
        game._put_permanent_onto_battlefield(0, Permanent(card=_C["Forest"]), None)
        assert (bear.effective_power, bear.effective_toughness) == (6, 6)


class TestFreeForAllElimination:
    def _ffa_session(self, seat_count: int = 4):
        from fastapi.testclient import TestClient

        from web.app import app, store

        client = TestClient(app)
        seats = [
            {"name": f"Player {i + 1}", "is_ai": i != 0, "colors": 2}
            for i in range(seat_count)
        ]
        created = client.post(
            "/api/sessions",
            json={"mode": "free_for_all", "seats": seats, "seed": 4242},
        ).json()
        return client, store.get(created["session_id"])

    def test_first_elimination_does_not_finish_the_game(self):
        from web.app import _winner

        client, session = self._ffa_session(4)
        session.game.players[0].lost = True
        assert _winner(session) is None

        state = client.get(f"/api/sessions/{session.id}/state", params={"seat": 0}).json()
        assert state["winner"] is None
        assert state["players"][0]["lost"] is True
        assert [p["lost"] for p in state["players"][1:]] == [False, False, False]
        assert session.status != "finished"

    def test_last_seat_standing_wins(self):
        from web.app import _winner

        _, session = self._ffa_session(3)
        session.game.players[0].lost = True
        session.game.players[2].lost = True
        assert _winner(session) == 1

    def test_all_seats_lost_is_a_draw(self):
        from web.app import _winner

        _, session = self._ffa_session(3)
        for player in session.game.players:
            player.lost = True
        assert _winner(session) == -1

    def test_two_player_winner_semantics_unchanged(self):
        from fastapi.testclient import TestClient

        from web.app import app, store, _winner

        client = TestClient(app)
        created = client.post(
            "/api/sessions",
            json={"mode": "human_vs_ai", "host_name": "H", "host_colors": 2, "seed": 7},
        ).json()
        session = store.get(created["session_id"])
        assert _winner(session) is None
        session.game.players[1].lost = True
        assert _winner(session) == 0
