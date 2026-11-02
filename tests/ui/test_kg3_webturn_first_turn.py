"""The web's first turn has its beginning phase (CR 103.8, 500.1).

"103.8. The starting player takes their first turn" — a turn of CR 500.1's five
phases, "each of these phases takes place every turn", and the first of them is
the beginning phase: untap, upkeep and draw (CR 501.1). "103.8a In a two-player
game, the player who plays first skips the draw step … of their first turn";
"103.8c In all other multiplayer games, no player skips the draw step of their
first turn."

Until the kg3 round every web game opened turn 1 straight in its precombat
main phase (``pregame._pregame_start_game`` and the no-pregame deal in
``SessionStore._begin_pregame`` both set the seat and stopped): a
Free-For-All's starting player kept seven cards, and nothing that happens in
an untap or an upkeep step happened on turn 1. Now the end of the pregame owes
the first turn (``Session.first_turn_owed``) and the route or pregame action
that ended it runs the beginning phase (``turn_steps._settle_pregame`` →
``_begin_first_turn``) through the same resumable pieces as every later turn.

The census drives each mode × pregame setting through the routes a client
calls and reads every seat's payload. **Left out, by name:** the legacy
no-pregame first deal of ``human_vs_ai`` / ``human_vs_human`` (no rematch),
whose engine actor is seat 0 whatever the flip said — beginning a turn there
would settle that split one way or the other, which is its own entry.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from fastapi.testclient import TestClient

from engine.models import Permanent
from web.app import app, store
from web.pregame import _round_undecided
from web.seats import _seat_type

client = TestClient(app)

_WEB = Path(__file__).resolve().parents[2] / "web"


def _create(body: dict) -> str:
    created = client.post("/api/sessions", json=body)
    assert created.status_code == 200, created.text
    return created.json()["session_id"]


def _act(sid: str, seat: int, action: str, **extra) -> dict:
    response = client.post(
        f"/api/sessions/{sid}/action", json={"seat": seat, "action": action, **extra}
    )
    assert response.status_code == 200, (action, response.text)
    return response.json()


def _state(sid: str, seat: int) -> dict:
    response = client.get(f"/api/sessions/{sid}/state", params={"seat": seat})
    assert response.status_code == 200, response.text
    return response.json()


def _drive_pregame(sid: str, *, first: int | None = None) -> None:
    """Answer the pregame as the human seats' clients would: the flip's
    winner names who plays first (*first*, in a two-seat game, else itself)
    and every human seat keeps its hand."""
    for _ in range(60):
        session = store.get(sid)
        phase = session.pregame_phase
        if phase is None:
            return
        if phase == "coin_flip":
            winner = session.coin_flip_winner
            assert _seat_type(session, winner) == "human", "an AI chooser is answered by the server"
            choice = 0 if first is None or first == winner else 1
            _act(sid, winner, "coin_flip_choose", hand_index=choice)
        elif phase == "mulligan":
            seats = (
                _round_undecided(session)
                if session.simultaneous_mulligan
                else [session.mulligan_offer_seat]
            )
            human = [seat for seat in seats if _seat_type(session, seat) == "human"]
            assert human, f"the pregame waits on no human seat: {seats}"
            _act(sid, human[0], "mulligan_keep")
        else:
            raise AssertionError(f"a kept hand owes no bottom choice: {phase}")
    raise AssertionError("the pregame never ended")


def _assert_first_turn_begun(sid: str, label: str) -> int:
    """Turn 1 is the starting player's, and it began with its beginning
    phase: the untap step ran, the draw step skipped its draw at a two-seat
    table and took it at a larger one, and no other seat's turn has begun.
    Read off every seat's payload. Returns the starting seat."""
    session = store.get(sid)
    game = session.game
    seats = len(game.players)
    start = session.current_turn
    assert session.pregame_phase is None, label
    assert game.turn == 1, label
    assert game.active_player_index == start, label
    assert game.seat_turn_counts == {start: 1}, (label, game.seat_turn_counts)
    # CR 103.5 (with 103.5c's free first mulligan at a multiplayer table):
    # each opening hand is seven less the mulligans that count.
    kept = [7 - game.mulligan_effective_count(seat) for seat in range(seats)]
    name = game.players[start].name
    for viewer in range(seats):
        served = _state(sid, viewer)
        assert served["pregame"] is None, label
        assert served["current_turn"] == start, label
        assert served["turn_number"] == 1, label
        assert served["current_step"] == "precombat_main", (label, served["current_step"])
        hands = [player["hand_count"] for player in served["players"]]
        drawn = 0 if seats == 2 else 1
        expected = [kept[seat] + (drawn if seat == start else 0) for seat in range(seats)]
        assert hands == expected, (label, hands, expected)
        log = served["log"]
        assert any(line.startswith(f"{name} untapped ") for line in log), (label, log[-6:])
        if seats == 2:
            assert f"{name} skips the first turn's draw step (CR 103.8a)" in log, label
        else:
            assert f"{name} drew 1 card(s) in draw step" in log, label
    return start


def _seat_zero_starts_human_vs_ai() -> str:
    """A human_vs_ai pregame table whose flip the human won, still at the
    keep: the human has chosen to play first."""
    for seed in range(1, 60):
        sid = _create({"mode": "human_vs_ai", "seed": seed, "enable_pregame": True})
        if store.get(sid).coin_flip_winner == 0:
            _act(sid, 0, "coin_flip_choose", hand_index=0)
            assert store.get(sid).pregame_phase == "mulligan"
            return sid
    raise AssertionError("no seed in range gave the human the flip")


def test_every_mode_s_first_turn_begins_with_its_beginning_phase():
    seen: list[tuple[str, int, int, str]] = []

    def record(sid: str, label: str) -> None:
        start = _assert_first_turn_begun(sid, label)
        session = store.get(sid)
        seen.append((label, len(session.game.players), start, _seat_type(session, start)))

    # Two seats, with the pregame: each seat of human_vs_ai starts once — the
    # human by winning the flip and choosing to, the AI by being chosen (or by
    # winning the flip, when its policy plays first).
    sid = _seat_zero_starts_human_vs_ai()
    _drive_pregame(sid)
    record(sid, "human_vs_ai pregame, the human first")
    sid = _create({"mode": "human_vs_ai", "seed": 5, "enable_pregame": True})
    _drive_pregame(sid, first=1)
    record(sid, "human_vs_ai pregame, the AI first")
    assert store.get(sid).current_turn == 1
    # human_vs_human through the lobby: join, start, the flip, the keeps.
    sid = _create({"mode": "human_vs_human", "seed": 41, "enable_pregame": True})
    assert client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Guest"}).status_code == 200
    assert client.post(f"/api/sessions/{sid}/start", json={"seat": 1}).status_code == 200
    _drive_pregame(sid, first=1)
    record(sid, "human_vs_human pregame (lobby)")
    # ai_vs_ai has no pregame: the flip's winner plays first.
    for seed in (3, 4):
        record(_create({"mode": "ai_vs_ai", "seed": seed}), f"ai_vs_ai seed={seed}")
    # Free-For-All, with the pregame (sequential and simultaneous) and without.
    three = [
        {"name": "Host", "is_ai": False},
        {"name": "Bot1", "is_ai": True},
        {"name": "Bot2", "is_ai": True},
    ]
    for seed in (11, 12):
        sid = _create({"mode": "free_for_all", "seats": three, "seed": seed, "enable_pregame": True})
        _drive_pregame(sid)
        record(sid, f"free_for_all pregame seed={seed}")
    sid = _create({
        "mode": "free_for_all", "seats": three, "seed": 13,
        "enable_pregame": True, "simultaneous_mulligan": True,
    })
    _drive_pregame(sid)
    record(sid, "free_for_all simultaneous pregame")
    four = three + [{"name": "Guest", "is_ai": False}]
    for seed in (21, 22):
        record(
            _create({"mode": "free_for_all", "seats": four, "seed": seed}),
            f"free_for_all no pregame seed={seed}",
        )

    # The next game of the match (CR 103.1: the loser chooses), with and
    # without the pregame, and the Settings panel's restart.
    for pregame in (False, True):
        sid = _create({"mode": "human_vs_ai", "seed": 7, "enable_pregame": pregame})
        _drive_pregame(sid)
        store.get(sid).game.players[1].life = 0
        assert _state(sid, 0)["status"] == "finished"
        assert client.post(f"/api/sessions/{sid}/rematch", json={"seat": 0}).status_code == 200
        _drive_pregame(sid)
        record(sid, f"human_vs_ai rematch pregame={pregame}")
    sid = _create({"mode": "human_vs_ai", "seed": 8, "enable_pregame": True})
    _drive_pregame(sid)
    assert client.post(f"/api/sessions/{sid}/restart", json={"seat": 0}).status_code == 200
    _drive_pregame(sid)
    record(sid, "human_vs_ai restart")

    # Floors: the census examined every table it names, and both of CR
    # 103.8's outcomes on a human starting seat and an AI one.
    assert len(seen) == 13, seen
    two_seat_starts = {kind for _l, seats, _s, kind in seen if seats == 2}
    multi_starts = {kind for _l, seats, _s, kind in seen if seats > 2}
    assert two_seat_starts == {"human", "ai"}, seen
    assert multi_starts == {"human", "ai"}, seen


def test_turn_one_untaps_and_runs_the_starting_player_s_upkeep(set_pool):
    """A board already there when the pregame ends (the Debug Menu works
    during the pregame) is treated as turn 1's: the starting player's tapped
    permanent untaps (CR 502.3) and its "at the beginning of your upkeep"
    trigger resolves (CR 503.1) — Ivory Tower, with the seven cards of the
    kept hand, gains 3 life."""
    sid = _seat_zero_starts_human_vs_ai()
    game = store.get(sid).game
    tower = Permanent(card=set_pool("ATQ")["Ivory Tower"])
    forest = Permanent(card=set_pool("LEA")["Forest"], tapped=True)
    game.players[0].battlefield.extend([tower, forest])
    game._sync_control()

    _drive_pregame(sid)

    served = _state(sid, 0)
    assert served["current_turn"] == 0
    assert served["current_step"] == "precombat_main"
    assert served["players"][0]["hand_count"] == 7
    assert served["players"][0]["life"] == 23, served["log"][-6:]
    assert forest.tapped is False
    assert "Player 1 skips the first turn's draw step (CR 103.8a)" in served["log"]


def test_turn_one_s_upkeep_waits_on_the_starting_player_s_answer(set_pool):
    """A decision turn 1's upkeep owes a person stops the beginning phase there
    (CR 117.3b), exactly as on any later turn: Phantasmal Forces asks its
    controller to pay {U} or sacrifice it, the payload carries the prompt to
    that seat alone, and answering it finishes the beginning phase."""
    sid = _seat_zero_starts_human_vs_ai()
    game = store.get(sid).game
    forces = Permanent(card=set_pool("LEA")["Phantasmal Forces"])
    game.players[0].battlefield.append(forces)
    game._sync_control()

    _drive_pregame(sid)

    mine = _state(sid, 0)
    assert mine["current_step"] == "upkeep"
    pending = mine["upkeep_pay"]["pending"]
    assert [choice["card_name"] for choice in pending] == ["Phantasmal Forces"]
    assert _state(sid, 1)["upkeep_pay"] is None
    refused = client.post(
        f"/api/sessions/{sid}/action", json={"seat": 0, "action": "next_phase"}
    )
    assert refused.status_code == 400

    answered = _act(
        sid, 0, "sacrifice_upkeep",
        card_name="Phantasmal Forces", prompt_permanent_id=forces.permanent_id,
    )
    assert answered["current_step"] == "precombat_main"
    assert answered["upkeep_pay"] is None
    assert not list(game.controlled_by(0))
    assert [card.name for card in game.players[0].graveyard] == ["Phantasmal Forces"]
    assert "Player 1 skips the first turn's draw step (CR 103.8a)" in answered["log"]


def test_only_the_settle_step_advances_the_pregame():
    """Every caller outside ``web/pregame.py`` moves the pregame through
    ``turn_steps._settle_pregame``, which begins turn 1 once the pregame is
    over — a route that called ``_pregame_auto_advance`` itself could end a
    pregame and leave its first turn unbegun (the five routes and four
    pregame actions all did)."""
    callers: list[str] = []
    examined = 0
    for path in sorted(_WEB.glob("*.py")):
        examined += 1
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
                if name == "_pregame_auto_advance":
                    callers.append(f"{path.name}:{node.lineno}")
    assert examined >= 30
    assert [re.sub(r":\d+$", "", caller) for caller in callers] == ["turn_steps.py"], callers
