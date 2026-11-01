"""An AI seat at the web table decides whether to keep its opening hand.

Until the ``kg2`` round every AI seat kept what it was dealt: the pregame's
AI branches went straight to keep (sequential and simultaneous), and the
no-pregame deal — every ``ai_vs_ai`` game — kept every seat. Each now asks
``engine/ai_mulligan.py``, the decision the simulator asks.

Each test sets the AI seat's opening seven **before** its decision runs, by
dealing through a wrapper of ``Game.deal_opening_hands`` that arranges the
seat's hand out of its own deck, then reads what each seat is served.
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest import mock

from fastapi.testclient import TestClient

from engine.ai_mulligan import ALWAYS_KEEP_AT, deck_land_share, keep_window
from engine.game import Game
from engine.search_filters import card_has_type
from web.app import app, store

client = TestClient(app)
_REAL_DEAL = Game.deal_opening_hands


def _is_land(card) -> bool:
    return card_has_type(card, "land")


def _arrange(game: Game, seat: int, lands: int) -> None:
    """Give *seat* an opening seven of *lands* lands out of its own deck."""
    player = game.players[seat]
    pool = list(player.hand) + list(player.library)
    land_cards = [card for card in pool if _is_land(card)]
    spells = [card for card in pool if not _is_land(card)]
    hand = land_cards[:lands] + spells[: 7 - lands]
    rest = list(pool)
    for card in hand:
        for index, held in enumerate(rest):
            if held is card:
                del rest[index]
                break
    player.hand = hand
    player.library = rest


@contextmanager
def _dealt(seat: int, lands: int):
    """Deal as the game does, then arrange *seat*'s seven. Yields the seat's
    deck size as dealt, read back once the deal has happened."""
    deck: dict[str, int] = {}

    def deal(game, starting_player):
        _REAL_DEAL(game, starting_player)
        _arrange(game, seat, lands)
        player = game.players[seat]
        deck["size"] = len(player.hand) + len(player.library)

    with mock.patch.object(Game, "deal_opening_hands", deal):
        yield deck


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


def _create(**body) -> str:
    created = client.post("/api/sessions", json=body)
    assert created.status_code == 200, created.text
    return created.json()["session_id"]


def _human_vs_ai(*, simultaneous: bool = False, pregame: bool = True) -> str:
    return _create(
        mode="human_vs_ai", host_name="Host", host_colors=2, guest_colors=2,
        seed=777, enable_pregame=pregame, simultaneous_mulligan=simultaneous,
    )


def _human_settles(sid: str, seat: int = 0) -> None:
    """The person's half of the pregame: go first if they won the flip, and
    keep whenever they are asked."""
    session = store.get(sid)
    if session.pregame_phase == "coin_flip" and session.coin_flip_winner == seat:
        _action(sid, seat, "coin_flip_choose", hand_index=0)
    for _ in range(4):
        info = _state(sid, seat).get("pregame")
        if not info or not info.get("is_my_turn") or info["phase"] != "mulligan":
            break
        _action(sid, seat, "mulligan_keep")


def _assert_mulliganed_and_kept_a_window_hand(sid: str, seat: int, deck_size: int) -> None:
    session = store.get(sid)
    game = session.game
    player = game.players[seat]
    assert player.mulligans_taken >= 1
    assert len(player.hand) == 7 - game.mulligan_effective_count(seat)
    assert len(player.hand) + len(player.library) == deck_size
    assert any(f"{player.name} took mulligan #1" in line for line in game.log)
    if len(player.hand) > ALWAYS_KEEP_AT:
        low, high = keep_window(len(player.hand), deck_land_share(game, seat))
        assert low <= sum(1 for card in player.hand if _is_land(card)) <= high


class TestHumanVsAi:
    def test_the_ai_mulligans_a_dealt_one_lander(self):
        with _dealt(1, lands=1) as deck:
            sid = _human_vs_ai()
            _human_settles(sid)
        session = store.get(sid)
        assert session.pregame_phase is None, "the game never started"
        _assert_mulliganed_and_kept_a_window_hand(sid, 1, deck["size"])
        # What the person is served: the AI's hand as a count, its mulligans
        # in the shared log, and none of the cards it put on the bottom.
        served = _state(sid, 0)
        ai = served["players"][1]
        assert ai["hand_count"] == len(session.game.players[1].hand)
        assert any("took mulligan #1" in line for line in served["log"])

    def test_the_ai_keeps_a_dealt_three_lander(self):
        with _dealt(1, lands=3):
            sid = _human_vs_ai()
            dealt = None
            session = store.get(sid)
            if session.pregame_phase == "mulligan":  # the AI won the flip
                dealt = list(session.game.players[1].hand)
            _human_settles(sid)
        session = store.get(sid)
        assert session.pregame_phase is None
        ai = session.game.players[1]
        assert ai.mulligans_taken == 0
        assert len(ai.hand) == 7
        assert sum(1 for card in ai.hand if _is_land(card)) == 3
        if dealt is not None:
            assert ai.hand == dealt
        assert not any("AI took mulligan" in line for line in session.game.log)

    def test_a_simultaneous_table_s_ai_mulligans_and_bottoms_its_card(self):
        """The simultaneous table had no AI bottom path at all: no AI seat had
        ever owed a card. A two-player AI's mulligan owes one, and the game
        starts once the person keeps."""
        with _dealt(1, lands=1) as deck:
            sid = _human_vs_ai(simultaneous=True)
            _human_settles(sid)
        session = store.get(sid)
        assert session.pregame_phase is None, "the game never started"
        assert 1 not in session.mulligan_bottom_required_by_seat
        _assert_mulliganed_and_kept_a_window_hand(sid, 1, deck["size"])
        assert len(session.game.players[1].hand) < 7

    def test_a_table_with_no_pregame_still_asks_the_ai(self):
        with _dealt(1, lands=0) as deck:
            sid = _human_vs_ai(pregame=False)
        session = store.get(sid)
        _assert_mulliganed_and_kept_a_window_hand(sid, 1, deck["size"])
        # The person's seat is asked nothing and keeps its seven.
        assert session.game.players[0].mulligans_taken == 0
        assert len(session.game.players[0].hand) == 7


def test_an_ai_vs_ai_game_mulligans_a_dealt_one_lander():
    """Every ai_vs_ai game is dealt with no pregame, so before the kg2 round
    no AI seat in one had ever mulliganed."""
    with _dealt(0, lands=1) as deck:
        sid = _create(mode="ai_vs_ai", host_colors=2, guest_colors=2, seed=31)
    _assert_mulliganed_and_kept_a_window_hand(sid, 0, deck["size"])


def test_a_free_for_all_ai_seat_mulligans_and_its_first_is_free():
    """A three-seat table (CR 103.5c): the AI seat's first mulligan costs no
    card, so whatever it keeps is seven minus its mulligans after the first."""
    seats = [
        {"name": "Host", "is_ai": False, "colors": 2},
        {"name": "Bot One", "is_ai": True, "colors": 2},
        {"name": "Bot Two", "is_ai": True, "colors": 2},
    ]
    with _dealt(2, lands=1) as deck:
        sid = _create(mode="free_for_all", seats=seats, seed=4242, enable_pregame=True)
        _human_settles(sid)
    session = store.get(sid)
    assert session.pregame_phase is None, "the game never started"
    bot = session.game.players[2]
    _assert_mulliganed_and_kept_a_window_hand(sid, 2, deck["size"])
    assert len(bot.hand) == 7 - max(0, bot.mulligans_taken - 1)
