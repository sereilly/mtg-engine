"""CR 616.1's last sentence: "If two or more players have to make these
choices at the same time, choices are made in APNAP order (see rule 101.4)."

One effect dealing damage to several recipients deals it at once, so every
affected player's CR 616.1e choice is made at the same time — the active
player's first (about themself and the permanents they control), then each
other player's in turn order. The engine deals the events one at a time and
each asks as it is dealt, so the order a loop deals in is the order the seats
are asked in. The loops walked ``game.players`` (or the order targets were
named), which asked seat 0 first whoever's turn it was.

Each board makes a seat other than seat 0 the active player and gives every
asked recipient two applicable prevention effects, with every seat
interactive, so the first question must be the active player's — and the
next the next seat's in turn order — and answering them all finishes the
effect.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.game_types import OracleExecutionContext
from engine.models import Permanent
from engine.oracle import OracleInstruction, compile_card_oracle
from engine.shields import add_shield, make_counting_pool, make_numeric_pool
from tests.helpers import resolve_stack

_POOL = {card.name: card for card in load_catalog()}


def _instruction(name: str, kind: str) -> OracleInstruction:
    program = compile_card_oracle(_POOL[name])
    roots = list(program.instructions)
    roots += [a.instruction for a in program.activated_abilities if a.instruction]
    roots += [t.instruction for t in program.triggered_abilities if t.instruction]
    stack = list(roots)
    while stack:
        found = stack.pop(0)
        if found.kind == kind:
            return found
        for value in (found.payload or {}).values():
            if isinstance(value, OracleInstruction):
                stack.append(value)
            elif isinstance(value, (list, tuple)):
                stack.extend(v for v in value if isinstance(v, OracleInstruction))
    raise AssertionError(f"{name} compiles to no {kind!r}")


def _game(seats: int, active: int) -> Game:
    game = Game(players=[
        PlayerState(f"P{index}", library=[_POOL["Island"]] * 8) for index in range(seats)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(range(seats))
    game.begin_turn_bookkeeping(active)
    game.resolve_untap_step(active)
    return game


def _put(game: Game, seat: int, name: str) -> Permanent:
    permanent = Permanent(card=_POOL[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    resolve_stack(game)
    game.pending_choices.clear()
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _arm_two(recipient) -> None:
    add_shield(recipient, make_numeric_pool(10, source_name="Plain Pool"))
    add_shield(recipient, make_counting_pool(10, "+1/+1", source_name="Counting Pool"))


def _asked_in_order(game: Game) -> list[int]:
    """Answer every CR 616.1e question with the default, oldest first, and
    return the seats in the order they were asked."""
    seats = []
    for _ in range(20):
        choice = game.pending_choice_of("effect_order")
        if choice is None:
            break
        # Only one question at a time: the loop stops behind the one it asked.
        assert len([c for c in game.pending_choices if c.kind == "effect_order"]) == 1
        seats.append(choice.player_index)
        assert game.resolve_pending_choice(
            "effect_order", choice.player_index, option_index=0,
        )
    assert not game.pending_choices and not game.resume_stack
    return seats


@pytest.mark.cr("616.1", "101.4")
def test_a_sweep_asks_the_active_player_first():
    """Earthquake on seat 1's turn, cast by seat 0: seat 1 is asked about
    itself and its creature before seat 0 is asked about anything."""
    game = _game(2, active=1)
    mine = _put(game, 0, "Grizzly Bears")
    theirs = _put(game, 1, "Grizzly Bears")
    for recipient in (game.players[0], game.players[1], mine, theirs):
        _arm_two(recipient)
    game._execute_oracle_instruction(
        _instruction("Earthquake", "earthquake_damage"),
        OracleExecutionContext(
            card=_POOL["Earthquake"], caster=game.players[0], target=game.players[1],
            x_value=1,
        ),
    )
    assert _asked_in_order(game) == [1, 1, 0, 0]
    assert any("earthquake damage" in line for line in game.log)


@pytest.mark.cr("616.1", "101.4")
def test_each_opponent_is_asked_in_turn_order_from_the_active_player():
    """Sizzle cast by seat 0 on seat 2's turn in a three-player game: seat 2
    (the active player) before seat 1."""
    game = _game(3, active=2)
    for seat in (1, 2):
        _arm_two(game.players[seat])
    game._execute_oracle_instruction(
        _instruction("Sizzle", "deal_damage"),
        OracleExecutionContext(
            card=_POOL["Sizzle"], caster=game.players[0], target=game.players[1],
        ),
    )
    assert _asked_in_order(game) == [2, 1]
    assert game.players[1].life == game.players[2].life == 20


@pytest.mark.cr("616.1", "101.4", "701.14a")
def test_a_fights_two_halves_ask_the_active_player_first():
    """Seat 0's Brash Taunter fights seat 1's creature on seat 1's turn: the
    half dealt to seat 1's creature is asked first."""
    game = _game(2, active=1)
    taunter = _put(game, 0, "Brash Taunter")
    bears = _put(game, 1, "Grizzly Bears")
    _arm_two(taunter)
    _arm_two(bears)
    game._execute_oracle_instruction(
        _instruction("Brash Taunter", "source_fights_target"),
        OracleExecutionContext(
            card=_POOL["Brash Taunter"], caster=game.players[0], target=game.players[1],
            source_permanent=taunter, target_permanent_id=[bears.permanent_id],
        ),
    )
    assert _asked_in_order(game) == [1, 0]


@pytest.mark.cr("616.1", "101.4")
def test_cyclones_sweep_asks_the_active_player_first():
    """Seat 1's Cyclone, paid in seat 1's upkeep: seat 1 and its creature are
    asked before seat 0 and its creature."""
    game = _game(2, active=1)
    cyclone = _put(game, 1, "Cyclone")
    _put(game, 1, "Forest")
    mine = _put(game, 0, "Grizzly Bears")
    theirs = _put(game, 1, "Grizzly Bears")
    for recipient in (game.players[0], game.players[1], mine, theirs):
        _arm_two(recipient)
    game.resolve_upkeep(1, human_choices={cyclone.permanent_id: True})
    assert _asked_in_order(game) == [1, 1, 0, 0]
    assert any("each creature and each player" in line for line in game.log)
