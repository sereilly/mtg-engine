"""Each turn's bookkeeping runs once, on every web road that begins a turn —
Time Vault's decline included.

``action_turn._action_time_vault_decline`` called ``turn_steps._begin_turn``,
which runs ``Game.begin_turn_bookkeeping`` before anything else, so a person
declining the skip began their turn a second time: ``seat_turn_counts`` rose by
two, and every "your last turn" / "its controller's next turn" ordinal against
it (``engine/turn_state.py``: Giant Turtle, Wall of Dust) named the wrong turn.
The decline now resumes the turn after its bookkeeping
(``turn_steps._turn_after_its_bookkeeping``), and is refused when no skip is
being asked (it began the whole turn again, untap step and all).
"""

from __future__ import annotations

from collections import Counter

import pytest

from engine.card_loader import load_catalog
from engine.game import Game
from engine.models import Permanent
from tests.helpers import client, seat_plays_first
from web.app import store

_CARDS = {card.name: card for card in load_catalog()}


def _put(game, seat: int, name: str, *, tapped: bool = False) -> Permanent:
    permanent = Permanent(card=_CARDS[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    permanent.tapped = tapped
    return permanent


def _state(sid: str, seat: int) -> dict:
    return client.get(f"/api/sessions/{sid}/state?seat={seat}").json()


def _act(sid: str, seat: int, **body):
    return client.post(f"/api/sessions/{sid}/action", json={"seat": seat, **body})


def _ok(sid: str, seat: int, **body) -> dict:
    response = _act(sid, seat, **body)
    assert response.status_code == 200, (body, response.json())
    return response.json()


def _drive(sid: str, *, until, attacks=None, blocks=None, limit: int = 120) -> None:
    """Both browsers of a two-person table until *until(state)*: seat 0
    declares *attacks* (attacker ids, at seat 1) and seat 1 *blocks*
    ({blocker id: attacker id}) — nothing when None, or the other way round —
    whoever holds
    priority passes, a cleanup discard discards the first card, and the
    active seat moves the turn on otherwise."""
    for _ in range(limit):
        state = _state(sid, 0)
        if until(state):
            return
        active = state["current_turn"]
        other = 1 - active
        combat = state.get("combat") or {}
        if state["current_step"] == "declare_attackers" and not combat.get("attackers_locked"):
            _ok(sid, active, action="declare_attackers",
                attacker_ids=list(attacks or []) if active == 0 else [], target_seat=other)
        elif state["current_step"] == "declare_blockers" and not combat.get("blockers_locked"):
            pairs = (blocks or {}) if other == 1 else {}
            _ok(sid, other, action="declare_blockers",
                blocker_pairs_by_id={str(b): a for b, a in pairs.items()})
        elif _state(sid, active).get("cleanup_discard"):
            _ok(sid, active, action="cleanup_select", hand_index=0)
        elif state["priority_player"] is not None:
            _ok(sid, state["priority_player"], action="pass_priority")
        else:
            _ok(sid, active, action="next_phase")
    raise AssertionError(f"never got there: {_state(sid, 0)['log'][-12:]}")


def _people_table():
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 51021,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = seat_plays_first(sid, 0)
    for player in session.game.players:
        player.battlefield = []
        player.hand = []
        player.graveyard = []
        player.library = [_CARDS["Plains"]] * 20
    return sid, session


@pytest.mark.cr("614.10", "506.4")
def test_declining_time_vaults_skip_keeps_last_turn_and_next_turn_honest():
    """Two people. Turn 1: the host attacks with Giant Turtle and Grizzly
    Bears; the guest's Wall of Dust blocks the Bears. Turn 3: the host is
    asked Time Vault's skip and declines it. The Turtle attacked during the
    host's last turn, and the Bears' controller's next turn is this one —
    neither may attack (Giant Turtle; Wall of Dust). The decline began the
    turn again, the host's turn count rose by two, and both attacked."""
    sid, session = _people_table()
    game = session.game
    _put(game, 0, "Time Vault", tapped=True)
    turtle = _put(game, 0, "Giant Turtle")
    bears = _put(game, 0, "Grizzly Bears")
    wall = _put(game, 1, "Wall of Dust")

    _drive(
        sid,
        until=lambda s: s["current_turn"] == 0 and s["turn_number"] > 1 and s.get("time_vault"),
        attacks=[turtle.permanent_id, bears.permanent_id],
        blocks={wall.permanent_id: bears.permanent_id},
    )
    assert any("Wall of Dust" in line and "block" in line.lower() for line in game.log), game.log
    assert game.seat_turn_counts[0] == 2

    _ok(sid, 0, action="time_vault_decline")
    assert game.seat_turn_counts[0] == 2, game.seat_turn_counts
    assert turtle.tapped is False and game.permanent_by_id(turtle.permanent_id) is turtle

    _drive(sid, until=lambda s: s["current_step"] == "declare_attackers" and s["current_turn"] == 0)
    for attacker in (turtle, bears):
        refused = _act(sid, 0, action="declare_attackers",
                       attacker_ids=[attacker.permanent_id], target_seat=1)
        assert refused.status_code == 400 or not attacker.attacking, (
            attacker.card.name, refused.json(), game.log[-6:],
        )
        assert not game.combat_attackers_locked or not attacker.attacking


def test_a_decline_with_no_skip_asked_is_refused():
    """Sent while no skip is being asked, the decline began the seat's turn
    over again — its untap step and its bookkeeping. It is refused, as the
    skip is."""
    sid, session = _people_table()
    game = session.game
    counts = dict(game.seat_turn_counts)
    response = _act(sid, 0, action="time_vault_decline")
    assert response.status_code == 400
    assert game.seat_turn_counts == counts


@pytest.mark.cr("500.1")
def test_every_web_road_into_a_turn_begins_it_once(monkeypatch):
    """Census: every call of ``begin_turn_bookkeeping`` across a web game
    that reaches each road into a turn — turn 1's beginning, a person's End
    Turn and their pass at the end step, a cleanup discard, the AI's
    ``ai_step``, Time Vault's skip and its decline — recorded with the turn
    number and the seat. No turn is begun twice, and each seat's turn count is
    the number of turns it began."""
    begun: list[tuple[int, int, str]] = []
    road = ["create"]
    real = Game.begin_turn_bookkeeping

    def recording(self, player_index):
        begun.append((self.turn, player_index, road[0]))
        return real(self, player_index)

    monkeypatch.setattr(Game, "begin_turn_bookkeeping", recording)

    sent: set[str] = set()

    def send(seat, **body):
        road[0] = body["action"]
        sent.add(body["action"])
        return _ok(sid, seat, **body)

    def ai_turn():
        # The AI's turn by its steps, the person passing whenever it hands
        # them priority (after its land, CR 116.3 / 117.3d), until the
        # person's turn begins and asks the skip.
        for _ in range(60):
            if game.active_player_index == 0 and session.time_vault_pending:
                return
            if game.priority_player_index == 0:
                send(0, action="pass_priority")
            else:
                send(0, action="ai_step")
        raise AssertionError(f"the AI's turn never ended: {game.log[-12:]}")

    created = client.post("/api/sessions", json={"mode": "human_vs_ai", "seed": 5}).json()
    sid = created["session_id"]
    session = seat_plays_first(sid, 0)
    game = session.game
    # Turn 1's beginning (the road that dealt, and `seat_plays_first`'s, which
    # clears the counts when the flip named the other seat) is read apart.
    assert begun and {road for _t, _s, road in begun} == {"create"}
    begun.clear()
    counts_at_start = dict(game.seat_turn_counts)
    for player in game.players:
        player.battlefield = []
        player.graveyard = []
        player.library = [_CARDS["Plains"]] * 20
    game.players[0].hand = [_CARDS["Plains"]] * 8
    game.players[1].hand = []
    _put(game, 0, "Time Vault", tapped=True)

    # Turn 1 (the person): End Turn with eight cards — the cleanup discard
    # begins turn 2.
    send(0, action="end_turn")
    assert store.get(sid).cleanup_required_discards == 1
    send(0, action="cleanup_select", hand_index=0)
    # Turn 2 (the AI); turn 3 (the person) asks the skip, and is declined.
    ai_turn()
    send(0, action="time_vault_decline")
    game.players[0].hand = game.players[0].hand[:3]
    # Turn 3 ends by the person's passes, the last at their end step.
    for _ in range(40):
        if game.active_player_index != 0:
            break
        state = _state(sid, 0)
        if state["priority_player"] == 0:
            send(0, action="pass_priority")
        else:
            send(0, action="next_phase")
    ai_turn()
    # Turn 5 is skipped: turn 6 (the AI) begins.
    send(0, action="time_vault_skip", card_name="Time Vault")
    assert game.active_player_index == 1

    roads = Counter(road for _turn, _seat, road in begun)
    assert {"cleanup_select", "time_vault_skip"} <= set(roads), begun
    assert set(roads) & {"pass_priority", "next_phase", "ai_step"}, begun
    assert "time_vault_decline" in sent
    twice = [key for key, n in Counter((t, s) for t, s, _r in begun).items() if n > 1]
    assert not twice, begun
    for seat in (0, 1):
        assert game.seat_turn_counts[seat] - counts_at_start.get(seat, 0) == sum(
            1 for _t, s, _r in begun if s == seat
        ), (game.seat_turn_counts, counts_at_start, begun)
