"""CR 723 — controlling another player (Mindslaver, Mirrodin W2G1).

"{4}, {T}, Sacrifice Mindslaver: You control target player during that
player's next turn." The control is a record (``engine/player_control.py``)
and one question, ``Game.decider_of(seat)``, asked wherever a decision is
handed to a seat — ``Game.asks_a_person(seat)`` for whether a person is asked
it, and the AI's choosers for what an AI deciding for another seat plays.

The Scryfall rulings (2024-04-12) quoted here: "The player you're controlling
is still the active player during that turn." / "While controlling another
player, you also continue to make your own choices and decisions." / "If the
targeted player skips their next turn, you'll control the next turn the
affected player actually takes." / "Multiple player-controlling effects that
affect the same player overwrite each other." / "You could gain control of
yourself using Mindslaver, but gaining control of yourself doesn't really do
anything." / "You only control the player. You don't control any of that
player's permanents, spells, or abilities."
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _table(set_pool, seats: int = 2, hands=None) -> Game:
    forest = set_pool("LEA")["Forest"]
    hands = hands or {}
    game = Game(players=[
        PlayerState(f"P{seat + 1}", library=[forest] * 20, hand=list(hands.get(seat, ())))
        for seat in range(seats)
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.turn = 1
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game


def _put(game: Game, seat: int, card) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _slave(game: Game, set_pool, controller: int, target: int) -> None:
    """*controller* activates a Mindslaver at *target* and it resolves."""
    _put(game, controller, set_pool("MRD")["Mindslaver"])
    result = game.activate_permanent_ability(
        controller, "Mindslaver", target_player_index=target,
    )
    assert result.supported, result.details
    resolve_stack(game)


@pytest.mark.cr("723.1")
def test_the_control_is_the_next_turn_taken_and_ends_as_the_next_one_begins(set_pool):
    game = _table(set_pool)
    _slave(game, set_pool, 0, 1)
    # Sacrificed as a cost, and nothing is controlled yet: P1's own turn goes on.
    assert not any(p.card.name == "Mindslaver" for p in game.players[0].battlefield)
    assert game.decider_of(1) == 1
    assert game.player_controls_waiting == {1: 0}

    game.start_next_turn()            # P2's turn: P1 controls it, whole
    resolve_stack(game)
    assert game.active_player_index == 1
    assert game.decider_of(1) == 0
    assert "P1 controls P2 during this turn (CR 723)" in game.log
    game.resolve_end_step(1)
    assert game.decider_of(1) == 0    # through its end step

    game.start_next_turn()            # P1's turn: the effect is over
    resolve_stack(game)
    assert game.decider_of(1) == 1
    assert game.player_controls == {}
    assert "P1 no longer controls P2 (CR 723.1)" in game.log


@pytest.mark.cr("723.1a")
def test_a_later_control_of_the_same_player_overwrites_the_earlier(set_pool):
    game = _table(set_pool, seats=3)
    _slave(game, set_pool, 0, 1)
    _slave(game, set_pool, 2, 1)      # created last: the one that works
    game.start_next_turn()            # P2's turn
    resolve_stack(game)
    assert game.decider_of(1) == 2
    assert "P3 controls P2 during this turn (CR 723)" in game.log
    assert "P1 controls P2 during this turn (CR 723)" not in game.log


@pytest.mark.cr("723.1b")
def test_a_skipped_turn_does_not_spend_the_control(set_pool):
    game = _table(set_pool, seats=3)
    _slave(game, set_pool, 0, 1)
    game.skip_turn_counts[1] = 1      # P2 skips their next turn
    game.start_next_turn()            # P2's turn is skipped: P3 goes
    resolve_stack(game)
    assert game.active_player_index == 2
    assert game.decider_of(1) == 1
    assert game.player_controls_waiting == {1: 0}
    game.start_next_turn()            # P1
    resolve_stack(game)
    game.start_next_turn()            # P2's next turn actually taken
    resolve_stack(game)
    assert game.active_player_index == 1
    assert game.decider_of(1) == 0


@pytest.mark.cr("723.1b")
def test_a_turn_skipped_once_begun_hands_the_control_on(set_pool):
    """Time Vault's skip is decided as the turn begins — after the control
    started with it. The control waits for the next turn actually taken."""
    game = _table(set_pool)
    vault = _put(game, 1, set_pool("LEA")["Time Vault"])
    vault.tapped = True
    _slave(game, set_pool, 0, 1)
    game.turn += 1
    game.begin_turn_bookkeeping(1)
    assert game.decider_of(1) == 0
    assert game.untap_for_skip(1, "Time Vault")
    assert game.decider_of(1) == 1
    assert game.player_controls_waiting == {1: 0}


@pytest.mark.cr("723.3")
def test_the_controlled_player_stays_active_and_keeps_its_permanents(set_pool):
    game = _table(set_pool)
    bears = _put(game, 1, set_pool("LEA")["Grizzly Bears"])
    _slave(game, set_pool, 0, 1)
    game.start_next_turn()
    resolve_stack(game)
    assert game.active_player_index == 1
    assert bears in list(game.controlled_by(1))
    assert bears not in list(game.controlled_by(0))


def _scepter_turn(set_pool, persons: set[int]) -> Game:
    """P2's turn, controlled by P1, with P2's Disrupting Scepter and two
    cards in P2's hand. The controller has P2 activate it at P2 itself."""
    lea = set_pool("LEA")
    game = _table(set_pool, hands={1: [lea["Lightning Bolt"], lea["Giant Growth"]]})
    _put(game, 1, lea["Disrupting Scepter"])
    _slave(game, set_pool, 0, 1)
    game.start_next_turn()
    resolve_stack(game)
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.interactive_seats = set(persons)
    return game


@pytest.mark.cr("723.5")
@pytest.mark.parametrize("persons, asked", [({0}, True), ({1}, False)])
def test_the_controlled_seats_decision_goes_to_its_controller(set_pool, persons, asked):
    """The controller decides what P2 activates and its target (P2 itself),
    and the discard P2 owes as it resolves is the controller's to make: a
    person controlling P2 is asked it, and a person controlled by an AI is
    not (the AI's default answers it)."""
    game = _scepter_turn(set_pool, persons=persons)
    result = game.activate_permanent_ability(
        1, "Disrupting Scepter", target_player_index=1,
    )
    assert result.supported, result.details
    held = len(game.players[1].hand)
    game.resolve_top_of_stack()
    owed = [choice for choice in game.pending_choices if choice.player_index == 1]
    assert [choice.kind for choice in owed] == ["discard"]
    assert game.asks_a_person(owed[0].player_index) is asked
    assert len(game.players[1].hand) == held
    if not asked:
        game.auto_resolve_choice(owed[0])
        assert len(game.players[1].hand) == held - 1


@pytest.mark.cr("723.5")
def test_an_ai_deciding_for_another_seat_plays_nothing_optional(set_pool):
    """The AI controller's measured policy (``engine/ai_player_control.py``):
    no land, no cast, no activation, no attack for the seat it controls."""
    from engine.ai_abilities import choose_activation_action
    from engine.ai_declarations import choose_attackers
    from engine.ai_policy import choose_cast_action, choose_land_drop
    from engine.ai_priority import act_at_priority

    lea = set_pool("LEA")
    game = _table(set_pool, hands={1: [lea["Forest"], lea["Grizzly Bears"]]})
    _put(game, 1, lea["Grizzly Bears"])
    for _ in range(3):
        _put(game, 1, lea["Forest"])
    _slave(game, set_pool, 0, 1)
    game.start_next_turn()
    resolve_stack(game)
    assert game.decider_of(1) == 0
    assert choose_land_drop(game, 1) is None
    assert choose_cast_action(game, 1) is None
    assert choose_activation_action(game, 1) is None
    assert act_at_priority(game, 1) is None
    assert choose_attackers(game, 1) == []
    # Uncontrolled, the same seat would play its land.
    game.player_controls.clear()
    assert choose_land_drop(game, 1) is not None


@pytest.mark.cr("723.8")
def test_the_controller_still_decides_for_itself(set_pool):
    game = _table(set_pool)
    _slave(game, set_pool, 0, 1)
    game.start_next_turn()
    resolve_stack(game)
    game.interactive_seats = {0}
    assert game.decider_of(0) == 0
    assert game.asks_a_person(0) and game.asks_a_person(1)


@pytest.mark.cr("723.9")
def test_control_of_yourself_does_nothing(set_pool):
    game = _table(set_pool)
    _slave(game, set_pool, 0, 0)
    game.start_next_turn()            # P2
    resolve_stack(game)
    assert game.decider_of(1) == 1
    game.start_next_turn()            # P1's next turn
    resolve_stack(game)
    assert game.decider_of(0) == 0
    assert "P1 controls themselves this turn (CR 723.9)" in game.log
