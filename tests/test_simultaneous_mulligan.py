"""Tests for the host-game "Simultaneous mulligans" setting.

With ``simultaneous_mulligan=True`` (and pregame enabled) every player decides
keep/mulligan at the same time instead of in turn order: each undecided seat
sees its own keep/mulligan prompt immediately (``is_my_turn`` for several
viewers at once), bottom-card selection runs per-seat while others are still
deciding, and the game starts once every seat has kept (and bottomed).
"""

from fastapi.testclient import TestClient

from web.app import app, store

client = TestClient(app)


def _action(sid: str, seat: int, action: str, **extra) -> dict:
    resp = client.post(
        f"/api/sessions/{sid}/action", json={"seat": seat, "action": action, **extra}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _state(sid: str, seat: int) -> dict:
    resp = client.get(f"/api/sessions/{sid}/state", params={"seat": seat})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _enter_mulligan_as_host(sid: str) -> None:
    """Resolve the coin flip so the mulligan phase begins. If an AI seat won
    the flip, the server auto-advanced into the mulligan phase already."""
    session = store.get(sid)
    if session.pregame_phase == "coin_flip":
        assert session.coin_flip_winner == 0
        _action(sid, 0, "coin_flip_choose", hand_index=0)
    assert store.get(sid).pregame_phase == "mulligan"


def _create_ffa_simultaneous(seat_count: int = 4) -> str:
    seats = [
        {"name": f"Player {i + 1}", "is_ai": i != 0, "colors": 2}
        for i in range(seat_count)
    ]
    created = client.post(
        "/api/sessions",
        json={
            "mode": "free_for_all",
            "seats": seats,
            "seed": 4242,
            "enable_pregame": True,
            "simultaneous_mulligan": True,
        },
    )
    assert created.status_code == 200, created.text
    return created.json()["session_id"]


class TestSimultaneousMulliganVsAi:
    def test_ai_seats_keep_instantly_and_host_decides_alone(self):
        sid = _create_ffa_simultaneous(4)
        _enter_mulligan_as_host(sid)
        session = store.get(sid)

        # Every AI seat already kept; only the host (seat 0) is pending.
        assert session.mulligan_kept_seats == {1, 2, 3}
        info = _state(sid, 0)["pregame"]
        assert info["phase"] == "mulligan"
        assert info["simultaneous"] is True
        assert info["is_my_turn"] is True

        _action(sid, 0, "mulligan_keep")
        session = store.get(sid)
        assert session.pregame_phase is None  # game started
        assert len(session.game.players[0].hand) == 7

    def test_mulligan_then_bottom_flow(self):
        sid = _create_ffa_simultaneous(4)
        _enter_mulligan_as_host(sid)

        _action(sid, 0, "mulligan_take")
        info = _state(sid, 0)["pregame"]
        assert info["phase"] == "mulligan"
        assert info["is_my_turn"] is True
        assert info["mulligans_taken"] == 1
        assert len(store.get(sid).game.players[0].hand) == 7

        # Keeping after a mulligan enters this seat's own bottom selection —
        # the shared phase stays "mulligan" (per-seat progress, no global stall).
        _action(sid, 0, "mulligan_keep")
        assert store.get(sid).pregame_phase == "mulligan"
        info = _state(sid, 0)["pregame"]
        assert info["phase"] == "bottom_select"
        assert info["is_my_turn"] is True
        assert info["required_count"] == 1

        _action(sid, 0, "mulligan_bottom_select", hand_index=2)
        info = _state(sid, 0)["pregame"]
        assert info["selected_indices"] == [2]

        _action(sid, 0, "mulligan_bottom_confirm")
        session = store.get(sid)
        assert session.pregame_phase is None
        assert len(session.game.players[0].hand) == 6

    def test_take_and_keep_rejected_after_keeping(self):
        sid = _create_ffa_simultaneous(3)
        _enter_mulligan_as_host(sid)
        _action(sid, 0, "mulligan_take")
        _action(sid, 0, "mulligan_keep")

        for action in ("mulligan_take", "mulligan_keep"):
            resp = client.post(
                f"/api/sessions/{sid}/action", json={"seat": 0, "action": action}
            )
            assert resp.status_code == 400
            assert "already kept" in resp.json()["detail"]


class TestSimultaneousMulliganTwoHumans:
    def _create_two_human_game(self) -> str:
        created = client.post(
            "/api/sessions",
            json={
                "mode": "human_vs_human",
                "host_name": "Alice",
                "guest_name": "Bob",
                "host_colors": 2,
                "guest_colors": 2,
                "seed": 99,
                "enable_pregame": True,
                "simultaneous_mulligan": True,
            },
        )
        assert created.status_code == 200, created.text
        sid = created.json()["session_id"]
        joined = client.post(
            f"/api/sessions/{sid}/join", json={"guest_name": "Bob", "guest_colors": 2}
        )
        assert joined.status_code == 200, joined.text
        started = client.post(f"/api/sessions/{sid}/start", json={"seat": 0})
        assert started.status_code == 200, started.text
        # Whichever human won the flip chooses to go first.
        winner = store.get(sid).coin_flip_winner
        _action(sid, winner, "coin_flip_choose", hand_index=0)
        assert store.get(sid).pregame_phase == "mulligan"
        return sid

    def test_both_players_prompted_at_once(self):
        sid = self._create_two_human_game()

        # THE point of the setting: both seats see their own prompt at once.
        for seat in (0, 1):
            info = _state(sid, seat)["pregame"]
            assert info["phase"] == "mulligan"
            assert info["simultaneous"] is True
            assert info["is_my_turn"] is True, f"seat {seat} should be deciding"

    def test_decisions_resolve_independently_and_game_starts(self):
        sid = self._create_two_human_game()

        # Seat 1 keeps first (out of turn order — impossible sequentially).
        _action(sid, 1, "mulligan_keep")
        assert store.get(sid).pregame_phase == "mulligan"

        # Seat 1 now waits on seat 0, named in waiting_for.
        info = _state(sid, 1)["pregame"]
        assert info["is_my_turn"] is False
        assert info["waiting_for"] == "Alice"

        # Seat 0 mulligans, keeps, bottoms one card; then the game starts.
        _action(sid, 0, "mulligan_take")
        _action(sid, 0, "mulligan_keep")
        info = _state(sid, 0)["pregame"]
        assert info["phase"] == "bottom_select"
        assert info["required_count"] == 1
        _action(sid, 0, "mulligan_bottom_select", hand_index=0)
        _action(sid, 0, "mulligan_bottom_confirm")

        session = store.get(sid)
        assert session.pregame_phase is None
        assert len(session.game.players[0].hand) == 6
        assert len(session.game.players[1].hand) == 7

    def test_bottom_selection_runs_while_other_seat_still_deciding(self):
        sid = self._create_two_human_game()

        # Seat 1 mulligans and keeps while seat 0 hasn't decided at all.
        _action(sid, 1, "mulligan_take")
        _action(sid, 1, "mulligan_keep")

        # Seat 1 is picking bottom cards WHILE seat 0 still holds its prompt.
        info1 = _state(sid, 1)["pregame"]
        assert info1["phase"] == "bottom_select"
        assert info1["is_my_turn"] is True
        info0 = _state(sid, 0)["pregame"]
        assert info0["phase"] == "mulligan"
        assert info0["is_my_turn"] is True

        _action(sid, 1, "mulligan_bottom_select", hand_index=1)
        _action(sid, 1, "mulligan_bottom_confirm")
        # Still waiting on seat 0.
        assert store.get(sid).pregame_phase == "mulligan"

        _action(sid, 0, "mulligan_keep")
        assert store.get(sid).pregame_phase is None


class TestSequentialDefaultUnchanged:
    def test_default_flow_still_offers_in_turn_order(self):
        created = client.post(
            "/api/sessions",
            json={
                "mode": "human_vs_human",
                "host_name": "Alice",
                "guest_name": "Bob",
                "seed": 99,
                "enable_pregame": True,
            },
        )
        sid = created.json()["session_id"]
        client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Bob", "guest_colors": 2})
        client.post(f"/api/sessions/{sid}/start", json={"seat": 0})
        winner = store.get(sid).coin_flip_winner
        _action(sid, winner, "coin_flip_choose", hand_index=0)

        session = store.get(sid)
        assert session.simultaneous_mulligan is False
        assert session.mulligan_offer_seat == winner
        # Only the offered seat may act; the other is told to wait.
        other = 1 - winner
        blocked = client.post(
            f"/api/sessions/{sid}/action", json={"seat": other, "action": "mulligan_keep"}
        )
        assert blocked.status_code == 400
        info = _state(sid, other)["pregame"]
        assert info["is_my_turn"] is False
