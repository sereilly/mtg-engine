"""A rehearsal copy taken while an each-seat offer's event waits between
answers is not part of that event (CR 603.6a, ``entering_together_through``).

Show and Tell's event outlives its offers: each seat's answer re-joins it and
the last one closes it. A copy of the table (``ai_rehearsal.scratch_copy``)
taken between two answers carries the prompts that would re-join it — and the
card the first seat already handed in, whose caller's continuation is a
closure over the original game. So the copy's prompts carry no event (its
answers enter what they put, at once) and, while the event holds a card, no
copy may be cut loose from the table at all (``held_for_an_answer``).
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_scratch_copy import held_for_an_answer, scratch_copy
from engine.card_loader import load_catalog
from engine.entry_awaiting import ENTRY_EVENT

_CARDS = {card.name: card for card in load_catalog()}


def _show_and_tell_waiting_on_seat_one() -> Game:
    """Seat 0 (a person) has taken Show and Tell's offer and picked its card;
    seat 1's offer is owed."""
    game = Game(players=[
        PlayerState(name=f"P{i}", library=[_CARDS["Plains"]] * 10) for i in range(2)
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game.interactive_seats = {0, 1}
    game._sync_control()
    game.players[0].hand = [_CARDS["Grizzly Bears"], _CARDS["Show and Tell"]]
    game.players[1].hand = [_CARDS["Llanowar Elves"]]
    assert game.cast_from_hand(0, "Show and Tell").supported
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_optional_pay(0, accept=True)
    assert game.confirm_put_from_hand_choice(0, 0)
    owed = game.waiting_prompt()
    assert owed is not None and owed.player_index == 1, game.log[-6:]
    return game


def test_the_event_holding_a_card_keeps_the_table_from_being_copied():
    game = _show_and_tell_waiting_on_seat_one()
    assert [event for event in game.open_entry_events if event.puts]
    assert held_for_an_answer(game)


def test_a_copy_carries_no_event_and_enters_what_its_answers_put():
    game = _show_and_tell_waiting_on_seat_one()
    copy = scratch_copy(game)
    assert copy.open_entry_events == []
    assert copy.entry_batch is None
    assert not any(ENTRY_EVENT in choice.data for choice in copy.pending_choices)
    # The original still waits on seat 1, with seat 0's card handed in.
    assert any(ENTRY_EVENT in choice.data for choice in game.pending_choices)
    assert not list(game.controlled_by(0))
    # And the original finishes the event at seat 1's answer: both enter.
    assert game.confirm_optional_pay(1, accept=True)
    assert game.confirm_put_from_hand_choice(1, 0)
    assert [p.card.name for p in game.controlled_by(0)] == ["Grizzly Bears"]
    assert [p.card.name for p in game.controlled_by(1)] == ["Llanowar Elves"]
    assert not game.open_entry_events
