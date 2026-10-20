"""CR 603.3b — each player puts the triggered abilities they control on the
stack "in any order they choose", the active player's first.

This engine never asked: a seat's simultaneous triggers kept the order its fire
sites collected them in. Now a seat that is asked gets ``order_triggers`` when a
window closes (``engine/trigger_order.py``), and nothing resolves until it has
answered; a seat nobody asks keeps that order, exactly as before. The cards
here are built in the test, so each sentence is the one under test. Tangle Wire
— the card that showed it — is in ``tests/sets/test_nem_artifacts.py``, and
the pool-wide census is ``tests/engine/test_trigger_order_census.py``.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import _mk_card, resolve_stack

_R4_TWIN = _mk_card(
    name="R4 Twin", mana_cost="{2}{W}", type_line="Creature — Cleric",
    oracle_text=(
        "When this creature enters, you gain 3 life.\n"
        "When this creature enters, draw a card."
    ),
    colors=("W",), power=2, toughness=2,
)
_R4_BOLT = _mk_card(
    name="R4 Bolt", mana_cost="{R}", type_line="Instant",
    oracle_text="R4 Bolt deals 3 damage to any target.", colors=("R",),
)
_R4_WATCHER = _mk_card(
    name="R4 Watcher", mana_cost="{1}", type_line="Artifact",
    oracle_text="Whenever a creature dies, you gain 1 life.",
)
_R4_WARDEN = _mk_card(
    name="R4 Warden", mana_cost="{W}", type_line="Creature — Cleric",
    oracle_text="Whenever another creature enters, you gain 1 life.",
    colors=("W",), power=1, toughness=1,
)
_R4_BEAR = _mk_card(
    name="R4 Bear", mana_cost="{1}{G}", type_line="Creature — Bear",
    oracle_text="", colors=("G",), power=2, toughness=2,
)
_R4_WRATH = _mk_card(
    name="R4 Wrath", mana_cost="{2}{W}{W}", type_line="Sorcery",
    oracle_text="Destroy all creatures.", colors=("W",),
)
_R4_FILLER = _mk_card(name="R4 Filler", type_line="Land")


def _r4_table(*, interactive=(0, 1), hand=(), mine=(), theirs=()) -> Game:
    """Seat 0's main phase, seat 0 holding priority."""
    game = Game(players=[
        PlayerState("A", library=[_R4_FILLER] * 10, hand=list(hand)),
        PlayerState("B", library=[_R4_FILLER] * 10),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    for seat, cards in ((0, mine), (1, theirs)):
        for card in cards:
            game._put_permanent_onto_battlefield(seat, Permanent(card=card), None)
    game.stack.clear()
    game.interactive_seats = set(interactive)
    game.start_priority_window(0)
    return game


def _r4_all_pass(game) -> str:
    result = "passed"
    for _ in range(len(game.players)):
        result = game.pass_priority(game.priority_player_index)
        if result != "passed":
            return result
    return result


def _r4_abilities_top_first(game) -> list[str]:
    return [item.ability_text for item in reversed(game.stack) if item.is_ability]


def _r4_cast_twin(game) -> None:
    result = game.queue_from_hand(0, "R4 Twin")
    assert result.supported, result
    game.note_priority_action_taken(0)
    # The creature spell resolves; its two triggers go on the stack together.
    assert _r4_all_pass(game) == "awaiting_choice"


@pytest.mark.cr("603.3b")
def test_r4_603_3b_a_seat_is_asked_and_nothing_resolves_until_it_answers():
    """Two entry triggers of one permanent trigger together. The seat is asked
    their order, offered top first, and until it answers the stack stands
    still: no object resolves and the seat that owes the answer is the one
    the game waits on."""
    game = _r4_table(hand=[_R4_TWIN])
    _r4_cast_twin(game)

    [owed] = game.pending_choices_of("order_triggers")
    assert owed.player_index == 0
    assert [entry["text"] for entry in owed.data["triggers"]] == [
        "When this creature enters, you gain 3 life.",
        "When this creature enters, draw a card.",
    ], "offered top first, in the order a seat nobody asks would keep"
    assert game.waiting_prompt() is owed
    assert game.priority_player_index == 0
    assert game.resolve_top_of_stack() is False
    assert (game.players[0].life, len(game.players[0].hand)) == (20, 0)
    assert len(game.stack) == 2


@pytest.mark.cr("603.3b", "608.1")
@pytest.mark.parametrize(
    "order, first",
    [([0, 1], (23, 0)), ([1, 0], (20, 1))],
    ids=["life-first", "draw-first"],
)
def test_r4_603_3b_the_order_chosen_is_the_order_they_resolve_in(order, first):
    """Either order may be chosen, and the stack is put in that order: the
    first one listed resolves first, then the other."""
    game = _r4_table(hand=[_R4_TWIN])
    _r4_cast_twin(game)

    assert game.confirm_order_triggers(0, order)
    assert game.pending_choices_of("order_triggers") == []
    assert "ordered their triggered abilities (603.3b)" in game.log[-1]

    assert _r4_all_pass(game) == "resolved_top"
    assert (game.players[0].life, len(game.players[0].hand)) == first
    assert _r4_all_pass(game) == "resolved_top"
    assert (game.players[0].life, len(game.players[0].hand)) == (23, 1)
    assert game.stack == []


@pytest.mark.cr("603.3b")
@pytest.mark.parametrize("order", [[0], [0, 0], [0, 2], [], ["x", 1]])
def test_r4_603_3b_an_order_of_some_other_set_is_refused(order):
    """A short, repeated, out-of-range or malformed list is not an order of
    these abilities: refused, with the prompt still owed and the stack as it
    was."""
    game = _r4_table(hand=[_R4_TWIN])
    _r4_cast_twin(game)
    before = list(game.stack)

    assert not game.confirm_order_triggers(0, order)
    assert len(game.pending_choices_of("order_triggers")) == 1
    assert all(a is b for a, b in zip(game.stack, before))


@pytest.mark.cr("603.3b")
def test_r4_603_3b_a_seat_nobody_asks_keeps_the_pushed_order():
    """An AI or headless seat is not asked: the registry's default is taken as
    the prompt is armed, and it is the order every game had before — the
    first printed on top, resolving first. Nothing is logged."""
    game = _r4_table(interactive=(), hand=[_R4_TWIN])
    assert game.queue_from_hand(0, "R4 Twin").supported
    game.note_priority_action_taken(0)
    assert _r4_all_pass(game) == "resolved_top"

    assert game.pending_choices == []
    assert _r4_abilities_top_first(game) == [
        "When this creature enters, you gain 3 life.",
        "When this creature enters, draw a card.",
    ]
    assert not any("603.3b" in line for line in game.log)


@pytest.mark.cr("603.3b", "405.5")
def test_r4_603_3b_the_object_below_waits_for_the_order_too():
    """The headless "do it all now" path resolves the stack in a loop. The
    triggers on top are held for their order, so the spell beneath them must
    not resolve first: a Bolt cast before the creature is still on the stack
    when the seat is asked."""
    game = _r4_table(hand=[_R4_BOLT, _R4_TWIN])
    assert game.queue_from_hand(0, "R4 Bolt", target_player_index=1).supported
    assert game.cast_from_hand(0, "R4 Twin").supported

    assert [item.card.name for item in game.stack] == ["R4 Bolt", "R4 Twin", "R4 Twin"]
    assert game.players[1].life == 20
    assert len(game.pending_choices_of("order_triggers")) == 1

    assert game.confirm_order_triggers(0, [1, 0])
    resolve_stack(game)
    assert game.players[1].life == 17
    assert (game.players[0].life, len(game.players[0].hand)) == (23, 1)


@pytest.mark.cr("603.3b", "603.2c")
def test_r4_603_3b_instances_of_one_ability_of_one_source_are_not_asked():
    """One "whenever a creature dies" watcher sees two creatures die to one
    sweeper: two instances of one ability of one source, which no order can
    tell apart. Both go on the stack and nobody is asked."""
    game = _r4_table(hand=[_R4_WRATH], mine=[_R4_WATCHER, _R4_BEAR, _R4_BEAR])
    assert game.queue_from_hand(0, "R4 Wrath").supported
    game.note_priority_action_taken(0)
    assert _r4_all_pass(game) == "resolved_top"

    assert [item.card.name for item in game.stack] == ["R4 Watcher", "R4 Watcher"]
    assert game.pending_choices_of("order_triggers") == []
    resolve_stack(game)
    assert game.players[0].life == 22


@pytest.mark.cr("603.3b")
def test_r4_603_3b_two_copies_set_off_by_one_event_are_not_asked():
    """Two copies of one card each see the same creature enter: the same
    printed ability, the same event, the same (absent) target. Not asked."""
    game = _r4_table(mine=[_R4_WARDEN, _R4_WARDEN])
    game._put_permanent_onto_battlefield(0, Permanent(card=_R4_BEAR), None)

    assert [item.card.name for item in game.stack] == ["R4 Warden", "R4 Warden"]
    assert game.pending_choices_of("order_triggers") == []


@pytest.mark.cr("603.3b", "101.4")
def test_r4_603_3b_the_active_players_go_on_first_across_several_events():
    """Both players control a death watcher and two creatures die to one
    sweeper. Each death is its own announcement, so the four triggers came
    from two batches and went on A, B, A, B — the active player's second
    resolving before the other player's first. CR 603.3b puts every one of
    the active player's on the stack first: A, A, then B, B, so B's resolve
    first."""
    game = _r4_table(
        interactive=(), hand=[_R4_WRATH],
        mine=[_R4_WATCHER, _R4_BEAR], theirs=[_R4_WATCHER, _R4_BEAR],
    )
    assert game.queue_from_hand(0, "R4 Wrath").supported
    game.note_priority_action_taken(0)
    assert _r4_all_pass(game) == "resolved_top"

    assert [item.caster_index for item in game.stack] == [0, 0, 1, 1]


@pytest.mark.cr("603.3b")
def test_r4_603_3b_a_prompt_with_one_object_left_is_not_owed():
    """The prompt is owed while two of its abilities are on the stack to be
    ordered. One that has left (a trigger removed for want of a target, CR
    603.3d) leaves nothing to order, and the one left resolves."""
    game = _r4_table(hand=[_R4_TWIN])
    _r4_cast_twin(game)
    [owed] = game.pending_choices_of("order_triggers")

    game.stack.pop()

    assert game.waiting_prompt() is None
    assert game.announcement_choice_for(game.stack[-1]) is None
    resolve_stack(game)
    assert len(game.players[0].hand) == 1
