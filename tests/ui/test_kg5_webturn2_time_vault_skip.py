"""Time Vault's skip is decided as the turn would begin, and the skipped turn
is passed as though it didn't exist (CR 500.11, 614.10).

Time Vault: "If you would begin your turn while this artifact is tapped, you
may skip that turn instead. If you do, untap this artifact." Its ruling: "The
choice of whether or not to skip a turn is made as that turn would begin."

The web asked the skip after ``Game.begin_turn_bookkeeping`` and skipped by
starting the next turn, so the skipped turn was *counted*: it took a turn
number, raised the seat's ``seat_turn_counts`` (Giant Turtle's "your last
turn", Wall of Dust's "its controller's next turn"), folded the turn before's
records as the skipped seat's last turn (Arboria), and started a control
waiting for the seat's next turn — so the control's controller was the one
asked, and an AI controller never offered the skip at all. The question is
now asked in ``turn_steps._begin_turn`` before the bookkeeping, and the skip
begins the next seat's turn (``Game.seat_after_skipped_turn``) without it.
"""

from __future__ import annotations

from collections import Counter

import pytest

from engine.card_loader import load_catalog
from engine.game import Game
from engine.models import Permanent
from engine.player_control import record_player_control
from tests.helpers import client, seat_plays_first

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


def _clear_board(session) -> None:
    for player in session.game.players:
        player.battlefield = []
        player.hand = []
        player.graveyard = []
        player.library = [_CARDS["Plains"]] * 20


def _table(mode: str, *, seats=None):
    body = {"mode": mode, "seed": 51021, "host_colors": 2, "guest_colors": 2}
    if seats is not None:
        body["seats"] = seats
    sid = client.post("/api/sessions", json=body).json()["session_id"]
    if mode == "human_vs_human":
        client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = seat_plays_first(sid, 0)
    _clear_board(session)
    return sid, session


def _drive(sid: str, session, *, until, attacks=None, limit: int = 160) -> None:
    """Every seat of the table until *until(state)*: whoever holds priority
    passes (an AI seat's turn is stepped), seat 0 declares *attacks* (ids,
    at the next seat) and nobody else attacks or blocks, a cleanup discard
    discards the first card, and the active person moves the turn on
    otherwise. A Time Vault question is never answered here."""
    game = session.game
    for _ in range(limit):
        state = _state(sid, 0)
        if until(state):
            return
        assert not session.time_vault_pending, "an unplanned Time Vault question"
        active = state["current_turn"]
        ai_turn = state["seat_types"][str(active)] == "ai"
        combat = state.get("combat") or {}
        holder = state["priority_player"]
        if state["current_step"] == "declare_attackers" and not combat.get("attackers_locked") and not ai_turn:
            ids = list(attacks or []) if active == 0 else []
            _ok(sid, active, action="declare_attackers", attacker_ids=ids,
                target_seat=(active + 1) % len(game.players))
        elif state["current_step"] == "declare_blockers" and not combat.get("blockers_locked"):
            defender = next(
                s for s in range(len(game.players))
                if s != active and s not in game.combat_blockers_declared_by
            )
            _ok(sid, defender, action="declare_blockers", blocker_pairs_by_id={})
        elif not ai_turn and _state(sid, active).get("cleanup_discard"):
            _ok(sid, active, action="cleanup_select", hand_index=0)
        elif holder is not None and state["seat_types"][str(holder)] != "ai":
            _ok(sid, holder, action="pass_priority")
        elif ai_turn:
            _ok(sid, 0, action="ai_step")
        else:
            _ok(sid, active, action="next_phase")
    raise AssertionError(f"never got there: {game.log[-12:]}")


def _asked(seat: int):
    return lambda s: s["current_turn"] == seat and bool(s.get("time_vault"))


@pytest.mark.cr("500.11", "614.10", "506.4")
def test_the_skipped_turn_is_passed_as_though_it_did_not_exist():
    """Two people. Turn 1: the host plays a land and attacks with Giant
    Turtle. Turn 2: the guest; Arboria arrives. Turn 3 would be the host's:
    asked Time Vault's skip, they skip it. The guest's turn begins under that
    number — and the guest's Bears may attack the host under Arboria, who put
    a nontoken permanent onto the battlefield during their last turn (turn
    1). Then the host's turn: the Turtle attacked during their last turn and
    can't attack. The skipped turn had been counted: the Turtle attacked, and
    Arboria read the skipped turn's empty records as the host's last turn."""
    sid, session = _table("human_vs_human")
    game = session.game
    vault = _put(game, 0, "Time Vault", tapped=True)
    turtle = _put(game, 0, "Giant Turtle")
    game.players[0].hand = [_CARDS["Plains"]]
    bears = _put(game, 1, "Grizzly Bears")

    _ok(sid, 0, action="cast", card_name="Plains")
    _drive(sid, session, until=lambda s: s["current_turn"] == 1, attacks=[turtle.permanent_id])
    assert game.players[1].life == 18, game.log[-12:]   # the Turtle attacked
    _put(game, 1, "Arboria")
    counts_before = dict(game.seat_turn_counts)
    _drive(sid, session, until=_asked(0))
    assert game.turn == 3
    # Nothing of the turn has begun while the question is asked.
    assert game.seat_turn_counts == counts_before
    assert game.active_player_index == 1

    _ok(sid, 0, action="time_vault_skip", card_name="Time Vault")
    assert vault.tapped is False
    assert (session.current_turn, game.active_player_index, game.turn) == (1, 1, 3)
    assert game.seat_turn_counts[0] == counts_before[0]
    assert game.seat_turn_counts[1] == counts_before[1] + 1
    assert game.last_own_turn_activity[0] is True

    _drive(sid, session, until=lambda s: s["current_step"] == "declare_attackers")
    _ok(sid, 1, action="declare_attackers", attacker_ids=[bears.permanent_id], target_seat=0)
    assert bears.attacking, game.log[-6:]

    _drive(sid, session, until=lambda s: s["current_turn"] == 0 and s["current_step"] == "declare_attackers")
    assert game.turn == 4
    refused = _act(sid, 0, action="declare_attackers",
                   attacker_ids=[turtle.permanent_id], target_seat=1)
    assert refused.status_code == 400, (refused.json(), game.log[-6:])
    assert "cannot attack" in refused.json()["detail"]
    assert not turtle.attacking


@pytest.mark.cr("723.1b", "614.10")
def test_the_seat_itself_is_asked_when_a_control_waits_for_its_turn():
    """A person whose next turn an AI's Mindslaver waits for holds a tapped
    Time Vault. The control has not started as the turn would begin, so the
    person is asked — the bookkeeping started the control first, and the AI
    deciding for them never skipped. They skip; the control still waits, and
    starts with the next turn they actually take (CR 723.1b)."""
    sid, session = _table("human_vs_ai")
    game = session.game
    vault = _put(game, 0, "Time Vault", tapped=True)
    _drive(sid, session, until=lambda s: s["current_turn"] == 1)
    record_player_control(game, 0, 1)
    _drive(sid, session, until=_asked(0))
    assert game.player_controls == {}
    _ok(sid, 0, action="time_vault_skip", card_name="Time Vault")
    assert vault.tapped is False
    assert game.active_player_index == 1
    assert game.player_controls_waiting == {0: 1}
    _drive(sid, session, until=lambda s: s["current_turn"] == 0)
    assert game.decider_of(0) == 1
    assert game.player_controls_waiting == {}


def _skip(sid, session, seat, skips):
    """*seat* skips the turn it is asked about; recorded with the turn number
    and the seat's turn count as it was asked."""
    game = session.game
    skips.append((game.turn, seat, game.seat_turn_counts.get(seat, 0)))
    _ok(sid, seat, action="time_vault_skip", card_name="Time Vault")


def _census_two_people(sid, session, skips):
    game = session.game
    _put(game, 0, "Time Vault", tapped=True)
    _drive(sid, session, until=lambda s: s["current_turn"] == 1)
    _put(game, 1, "Time Vault", tapped=True)
    _drive(sid, session, until=_asked(0))
    _skip(sid, session, 0, skips)
    # The guest's turn would begin in the host's place — and asks the
    # guest's own Vault first.
    assert _asked(1)(_state(sid, 1))
    _skip(sid, session, 1, skips)
    _drive(sid, session, until=lambda s: s["current_turn"] == 1)


def _census_free_for_all(sid, session, skips):
    game = session.game
    _put(game, 0, "Time Vault", tapped=True)
    _drive(sid, session, until=_asked(0))
    _skip(sid, session, 0, skips)
    _drive(sid, session, until=lambda s: s["current_turn"] == 0)


def _census_extra_turn(sid, session, skips):
    game = session.game
    _put(game, 0, "Time Vault", tapped=True)
    game.add_extra_turn(0)
    # Turn 1 ends; the host's extra turn would begin.
    _ok(sid, 0, action="end_turn")
    assert _asked(0)(_state(sid, 0)), game.log[-8:]
    _skip(sid, session, 0, skips)
    _drive(sid, session, until=lambda s: s["current_turn"] == 0)


def _census_decline(sid, session, skips):
    game = session.game
    _put(game, 0, "Time Vault", tapped=True)
    _drive(sid, session, until=_asked(0))
    _ok(sid, 0, action="time_vault_decline")
    _drive(sid, session, until=lambda s: s["current_turn"] == 1)


_FREE_FOR_ALL = [{"name": f"P{i}", "is_ai": i != 0, "colors": 2} for i in range(3)]

#: Each road: the table, the walk, and the seats whose turns begin after
#: turn 1, in order (each taking the next number).
_ROADS = {
    # T2 guest; T3 asks the host, then the guest: both skip; T3 host; T4 guest.
    "two people, each skipping": ("human_vs_human", None, _census_two_people, [1, 0, 1]),
    # T2 and T3 the AIs; T4 asks the host, who skips; T4 P1, T5 P2, T6 host.
    "a free-for-all, an AI next": ("free_for_all", _FREE_FOR_ALL, _census_free_for_all, [1, 2, 1, 2, 0]),
    # The host's extra turn (CR 500.7) is skipped: T2 the AI, T3 the host.
    "an extra turn skipped": ("human_vs_ai", None, _census_extra_turn, [1, 0]),
    # T2 the AI; T3 the host declines; T4 the AI.
    "a skip declined": ("human_vs_ai", None, _census_decline, [1, 0, 1]),
}


@pytest.mark.cr("500.11", "614.10a", "500.7")
@pytest.mark.parametrize("road", sorted(_ROADS))
def test_census_every_turn_begun_is_a_turn_taken(monkeypatch, road):
    """Census over the roads through Time Vault's question — two people
    skipping in a row, a free-for-all with an AI next, an extra turn (CR
    500.7) skipped, a decline — of every ``begin_turn_bookkeeping`` call,
    recorded with the turn number, the seat and the seat whose turn had
    ended (the active player as it is called). Each turn begun takes the
    next number and the rotation's next seat; nothing of a skipped turn has
    begun when it is skipped; each turn's records are folded as the seat
    whose turn they were; and each seat's turn count is the number of turns
    it began."""
    mode, seats, walk, expected_seats = _ROADS[road]
    begun: list[tuple[int, int, int]] = []
    real = Game.begin_turn_bookkeeping

    def recording(self, player_index):
        if self is session.game:
            begun.append((self.turn, player_index, self.active_player_index))
        return real(self, player_index)

    sid, session = _table(mode, seats=seats)
    game = session.game
    counts_at_start = Counter(game.seat_turn_counts)
    first_turn, first_seat = game.turn, game.active_player_index
    assert (first_turn, first_seat) == (1, 0)
    monkeypatch.setattr(Game, "begin_turn_bookkeeping", recording)
    skips: list[tuple[int, int, int]] = []
    walk(sid, session, skips)

    assert [seat for _turn, seat, _ended in begun] == expected_seats, begun
    assert [turn for turn, _seat, _ended in begun] == list(
        range(first_turn + 1, first_turn + 1 + len(begun))
    ), begun
    for (_turn, _seat, ended), previous in zip(begun, [first_seat] + expected_seats):
        assert ended == previous, ("the records folded were not that turn's", begun)
    for seat in range(len(game.players)):
        assert game.seat_turn_counts.get(seat, 0) - counts_at_start.get(seat, 0) == sum(
            1 for _t, s, _e in begun if s == seat
        ), (game.seat_turn_counts, counts_at_start, begun)
    assert (len(skips) > 0) == (road != "a skip declined")
    for turn, seat, count in skips:
        # As it was asked, the turn had not begun: the seat's last turn
        # begun was an earlier one, and its count is the turns before.
        assert count == counts_at_start.get(seat, 0) + sum(
            1 for t, s, _e in begun if s == seat and t < turn
        ), (skips, begun)
