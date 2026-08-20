"""The reveal-event feed: ``Game.record_reveal`` (CR 701.20).

A structured record beside the prose log, read by the web layer so a client
can float the revealed faces over the board. It is an event stream a client
diffs by id, not a history: ids stay monotonic across the whole game while the
list keeps only the newest few entries, so trimming never renumbers what a
client has already seen.
"""

from __future__ import annotations

from engine import Game
from engine.models import PlayerState


def _game() -> Game:
    return Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])


def test_ids_stay_monotonic_while_the_feed_is_trimmed():
    game = _game()

    for i in range(12):
        game.record_reveal(i % 2, [f"Card {i}"])

    assert len(game.reveal_events) == 10
    assert [event["id"] for event in game.reveal_events] == list(range(3, 13))
    assert game.reveal_events[-1]["cards"] == ["Card 11"]


def test_an_empty_reveal_is_not_an_event():
    """Revealing nothing shows nothing — a handler that found no card to
    reveal must not tick the feed, or clients would animate an empty showing."""
    game = _game()

    game.record_reveal(0, [])

    assert game.reveal_events == []
    assert game.reveal_event_seq == 0
