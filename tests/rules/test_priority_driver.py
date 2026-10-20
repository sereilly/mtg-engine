"""CR 117.3-117.4 at a table whose seats a driver plays (`Game.priority_driver`).

The headless window was "500.2 simplified: both players pass in succession",
so on the simulated path nobody ever received priority: the stack drained and
no seat was asked. These hold the seam the AI simulator now answers through —
who is asked, in which order, how often, and what happens to what they cast —
with a driver that records the questions, so the order is the engine's and not
a policy's.
"""
import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import CARDS_BY_NAME, _game, _nosick


def _table(*, hands=((), ()), boards=((), ())):
    players = [
        PlayerState(name=name, hand=[CARDS_BY_NAME[card] for card in hand])
        for name, hand in zip(("P0", "P1"), hands)
    ]
    game = _game(*players)
    for seat, board in enumerate(boards):
        for name in board:
            game._put_permanent_onto_battlefield(
                seat, _nosick(Permanent(card=CARDS_BY_NAME[name])), None,
            )
    return game


def _recording(game, act=None):
    """A driver that writes down ``(seat, the stack's names)`` each time it is
    asked, and acts where *act* says so (``act(table, seat) -> bool``)."""
    calls: list[tuple[int, list[str]]] = []

    def driver(table, seat):
        calls.append((seat, [item.card.name for item in table.stack]))
        return bool(act and act(table, seat))

    game.priority_driver = driver
    return calls


@pytest.mark.cr("117.3b", "117.3d", "117.4")
def test_each_player_is_given_priority_before_the_top_object_resolves():
    """The caster first, then the next player in turn order; once both have
    passed in succession the Bolt resolves and nobody is asked again."""
    game = _table(hands=(("Lightning Bolt",), ()))
    calls = _recording(game)

    result = game.cast_from_hand(0, "Lightning Bolt", target_player_index=1)

    assert result.supported, result.details
    assert calls == [(0, ["Lightning Bolt"]), (1, ["Lightning Bolt"])]
    assert game.players[1].life == 17
    assert game.stack == []


@pytest.mark.cr("117.3c", "117.7", "117.4")
def test_a_player_who_acts_receives_priority_again_and_their_response_resolves_first():
    """P1 answers the Bolt with Giant Growth: P1 is asked again at once
    (117.3c), the Growth resolves first because it is on top (117.7), and
    priority goes round again before the Bolt — which then deals its 3 to a
    5/5 that survives it."""
    game = _table(
        hands=(("Lightning Bolt",), ("Giant Growth",)),
        boards=((), ("Grizzly Bears",)),
    )
    bears = game.players[1].battlefield[0]

    def act(table, seat):
        if seat != 1 or not table.players[1].hand:
            return False
        return table.queue_from_hand(
            1, "Giant Growth", target_permanent_ids=[bears.permanent_id],
        ).supported

    calls = _recording(game, act)
    result = game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
    )

    assert result.supported, result.details
    assert calls == [
        (0, ["Lightning Bolt"]),
        (1, ["Lightning Bolt"]),
        (1, ["Lightning Bolt", "Giant Growth"]),
        (0, ["Lightning Bolt", "Giant Growth"]),
        (0, ["Lightning Bolt"]),
        (1, ["Lightning Bolt"]),
    ]
    assert any(p is bears for p in game.all_permanents())
    assert bears.damage_marked == 3
    assert [card.name for card in game.players[1].graveyard] == ["Giant Growth"]
    assert [card.name for card in game.players[0].graveyard] == ["Lightning Bolt"]
    growth = next(i for i, line in enumerate(game.log) if "Giant Growth resolved" in line)
    bolt = next(i for i, line in enumerate(game.log) if "Lightning Bolt resolved" in line)
    assert growth < bolt, game.log[-10:]


@pytest.mark.cr("500.2", "117.4")
def test_a_step_ends_only_after_everyone_passes_with_the_stack_empty():
    """At an empty stack each player is asked once and the step's window
    closes; a player who casts there puts the spell on the stack, it resolves,
    and the window goes round again before the step can end."""
    game = _table(hands=((), ("Lightning Bolt",)))
    game.active_player_index = 0
    game._set_phase_and_step("ending", "end")

    def act(table, seat):
        if seat != 1 or not table.players[1].hand:
            return False
        return table.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported

    calls = _recording(game, act)
    game._resolve_priority_window()

    assert calls == [
        (0, []),
        (1, []),                       # casts the Bolt
        (1, ["Lightning Bolt"]),
        (0, ["Lightning Bolt"]),       # both passed: it resolves
        (0, []),
        (1, []),                       # both passed with nothing on the stack
    ]
    assert game.players[0].life == 17
    assert game.stack == []


@pytest.mark.cr("117.1", "502.4")
def test_nobody_is_asked_without_a_driver_at_an_interactive_table_or_in_the_untap_step():
    """The seam is inert where it does not apply: a bare headless game drains
    its stack as it always did, a table with a person at it is the web
    layer's priority exchange to run, and the untap step gives nobody
    priority."""
    bare = _table(hands=(("Lightning Bolt",), ()))
    assert bare.cast_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    assert bare.players[1].life == 17

    for setup in ("interactive", "untap"):
        game = _table(hands=(("Lightning Bolt",), ()))
        calls = _recording(game)
        if setup == "interactive":
            game.interactive_seats = {1}
            game.queue_from_hand(0, "Lightning Bolt", target_player_index=1)
            game._settle()
        else:
            game._set_phase_and_step("beginning", "untap")
            game.cast_from_hand(0, "Lightning Bolt", target_player_index=1)
        assert calls == [], setup
        assert game.players[1].life == 17, setup


@pytest.mark.cr("117.3c", "117.4")
def test_a_driver_that_keeps_reporting_an_action_is_bounded():
    """A driver that answers "acted" without putting anything on the stack
    cannot spin the window: one offer takes at most ``MAX_PRIORITY_ACTIONS``
    actions and then the top resolves."""
    game = _table(hands=(("Lightning Bolt",), ()))
    calls = _recording(game, lambda table, seat: True)

    assert game.cast_from_hand(0, "Lightning Bolt", target_player_index=1).supported

    assert len(calls) == Game.MAX_PRIORITY_ACTIONS
    assert game.players[1].life == 17
