"""Two effects imposing one requirement are two requirements (CR 508.1d,
CR 509.1c).

"If the number of requirements that are being obeyed is fewer than the maximum
possible number of requirements that could be obeyed without disobeying any
restrictions, the declaration … is illegal." The one-turn marks a resolved
spell leaves — "target creature attacks this turn if able" (Boiling Blood),
"that creature blocks this turn if able" (Provoke), "it blocks each attacking
creature this turn if able" (Blaze of Glory), and Oracle en-Vec's stamp for a
later turn — were each ``True``, so a second copy cast at the same creature did
nothing: under Dueling Grounds a creature with two Boiling Bloods on it and one
with one were each one requirement, and either could attack alone. Each mark
is now a count (``combat_permissions.add_turn_requirement``,
``turn_state.add_seat_turn_stamp``), read by the requirement lists.

The censuses carry the two-mark boards
(``tests/engine/test_kg3_attacks_requirement_census.py``,
``tests/regressions/test_kg_blocks_requirement_census.py``); these put the
marks there by casting the cards.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.combat_permissions import (MUST_BLOCK_ALL_UNTIL_EOT,
                                       add_turn_requirement, turn_requirements)
from engine.models import Permanent
from engine.turn_state import (MUST_ATTACK_ON_SEAT_TURN_KEY,
                               add_seat_turn_stamp, stamps_for_this_turn)

from tests.helpers import _mk_card, _mk_creature_card, _nosick, resolve_stack

_CARDS = {card.name: card for card in load_catalog()}


def _bear(name: str) -> Permanent:
    return _nosick(Permanent(card=_mk_creature_card(name, 2, 2)))


def _game(mine, theirs, hand0=(), hand1=()) -> Game:
    game = Game(players=[
        PlayerState(name="P0", battlefield=list(mine), hand=list(hand0),
                    library=[_mk_card("Top", "Land")] * 5),
        PlayerState(name="P1", battlefield=list(theirs), hand=list(hand1),
                    library=[_mk_card("Top", "Land")] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._sync_control()
    game.start_turn(0)
    for perm in [*mine, *theirs]:
        _nosick(perm)
    game._close_current_priority_step()
    return game


def _cast_at(game: Game, seat: int, name: str, target: Permanent) -> None:
    result = game.cast_from_hand(
        seat, name, target_player_index=game.controller_index_of(target),
        target_permanent_index=game.battlefield_index_of(target),
    )
    assert result.supported, result.details
    resolve_stack(game)


@pytest.mark.cr("508.1d")
def test_two_boiling_bloods_outweigh_one_under_dueling_grounds():
    twice, once = _bear("Twice Bear"), _bear("Once Bear")
    blood = _CARDS["Boiling Blood"]
    game = _game([twice, once, Permanent(card=_CARDS["Dueling Grounds"])], [],
                 hand0=[blood, blood, blood])
    _cast_at(game, 0, "Boiling Blood", twice)
    _cast_at(game, 0, "Boiling Blood", twice)
    _cast_at(game, 0, "Boiling Blood", once)
    assert game._attack_requirement_count(twice) == 2
    assert game._attack_requirement_count(once) == 1
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.current_step == "declare_attackers"
    ok, why = game.declare_attackers(0, [game.battlefield_index_of(once)], 1)
    assert not ok, game.log
    assert why == (
        "Twice Bear must attack if able (this declaration obeys 1 of the 2 "
        "attack requirements that can be obeyed together)"
    ), why
    assert game.declare_attackers(0, [game.battlefield_index_of(twice)], 1)[0]


@pytest.mark.cr("509.1c")
def test_two_provokes_outweigh_one_under_dueling_grounds():
    raider = _bear("Raider")
    twice, once = _bear("Twice Bear"), _bear("Once Bear")
    provoke = _CARDS["Provoke"]
    game = _game([raider, Permanent(card=_CARDS["Dueling Grounds"])], [twice, once],
                 hand0=[provoke, provoke, provoke])
    _cast_at(game, 0, "Provoke", twice)
    _cast_at(game, 0, "Provoke", twice)
    _cast_at(game, 0, "Provoke", once)
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [game.battlefield_index_of(raider)], 1)[0]
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"
    counted = [r for r in game.block_requirements(1) if r.attacker is None]
    assert sorted(r.blocker for r in counted) == sorted([
        game.battlefield_index_of(twice), game.battlefield_index_of(twice),
        game.battlefield_index_of(once),
    ])
    raider_slot = game.battlefield_index_of(raider)
    ok, _why = game.declare_blockers(
        1, {game.battlefield_index_of(once): raider_slot},
        acting_index=game.block_chooser_index(1),
    )
    assert not ok, game.log
    ok, why = game.declare_blockers(
        1, {game.battlefield_index_of(twice): raider_slot},
        acting_index=game.block_chooser_index(1),
    )
    assert ok, why


@pytest.mark.cr("509.1c")
def test_each_blaze_of_glory_is_a_requirement_for_each_attacker():
    hero = _bear("Hero")
    add_turn_requirement(hero, MUST_BLOCK_ALL_UNTIL_EOT)
    add_turn_requirement(hero, MUST_BLOCK_ALL_UNTIL_EOT)
    assert turn_requirements(hero, MUST_BLOCK_ALL_UNTIL_EOT) == 2
    # The shape the mark had is one requirement.
    hero.metadata[MUST_BLOCK_ALL_UNTIL_EOT] = True
    assert turn_requirements(hero, MUST_BLOCK_ALL_UNTIL_EOT) == 1


@pytest.mark.cr("508.1d")
def test_two_seat_turn_stamps_are_two_requirements_on_that_turn():
    """Oracle en-Vec's "during that player's next turn, the chosen creatures
    attack if able", twice over one creature: two stamps for the turn, and a
    stamp written for a later turn does not erase one still owed."""
    bear = _bear("Chosen Bear")
    game = _game([bear, _bear("Other Bear")], [])
    stamp = {"seat": 0, "seat_turn": game.seat_turn_counts.get(0, 0)}
    add_seat_turn_stamp(bear, MUST_ATTACK_ON_SEAT_TURN_KEY, stamp)
    add_seat_turn_stamp(bear, MUST_ATTACK_ON_SEAT_TURN_KEY, stamp)
    add_seat_turn_stamp(bear, MUST_ATTACK_ON_SEAT_TURN_KEY,
                        {"seat": 0, "seat_turn": stamp["seat_turn"] + 1})
    assert stamps_for_this_turn(game, bear, MUST_ATTACK_ON_SEAT_TURN_KEY) == 2
    assert game._attack_requirement_count(bear) == 2
