"""Awe Strike: "The next time target creature would deal damage this turn,
prevent that damage. You gain life equal to the damage prevented this way."

CR 615.8's source-keyed shield with its source named by **announcement** and
no recipient printed: the targeted creature's next instance of damage, to
whoever it was headed for, and the instance is everything it deals in one
simultaneous dealing (the project owner's ruling, 2026-11-07; the census in
``tests/regressions/test_kg4_615_next_instance_census.py`` names this board).
CR 615.5's additional effect pays the caster ("you", CR 109.5) once, with the
total, as the dealing finishes.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


_SEATS = [pytest.param(set(), id="nobody-asked"), pytest.param({0, 1}, id="interactive")]


def _card(set_pool, name):
    mrd = set_pool("MRD")
    return mrd[name] if name in mrd else set_pool("LEA")[name]


def _table(set_pool, interactive, *, mine=(), theirs=()):
    game = Game(players=[
        PlayerState(
            name="Alice", hand=[_card(set_pool, "Awe Strike")],
            library=[_card(set_pool, "Island")] * 20,
        ),
        PlayerState(name="Bob", library=[_card(set_pool, "Island")] * 20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = Permanent(card=_card(set_pool, name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    game.start_turn(0)
    game._settle()
    return game, placed[0], placed[1]


def _attack_into_blocks(game, blocks):
    """Bob's first creature attacks Alice, who declares *blocks*."""
    game.active_player_index = 1
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(1, [0], defending_player_index=0)
    assert ok, why
    game.advance_combat_phase()
    ok, why = game.declare_blockers(0, blocks)
    assert ok, why


@pytest.mark.cr("615.8", "615.5", "510.2")
@pytest.mark.parametrize("interactive", _SEATS)
def test_awe_strike_prevents_a_double_blocked_attackers_whole_dealing(
    set_pool, interactive,
):
    """A Craw Wurm blocked by two Grizzly Bears assigns 3 and 3: one combat
    damage step is one dealing (CR 510.2), so both chunks are prevented and
    Alice gains 6 once."""
    game, (first, second), (wurm,) = _table(
        set_pool, interactive,
        mine=["Grizzly Bears", "Grizzly Bears"], theirs=["Craw Wurm"],
    )
    _attack_into_blocks(game, {0: 0, 1: 0})
    assert game.queue_from_hand(
        0, "Awe Strike", target_permanent_ids=[wurm.permanent_id],
    ).supported
    resolve_stack(game)
    game.advance_combat_phase()
    assert game.resolve_all_combat_damage(1, attacker_damage={0: {0: 3, 1: 3}})[0]
    assert [first.damage_marked, second.damage_marked] == [0, 0]
    assert game.players[0].life == 26
    assert sum("gained 6 life from Awe Strike" in line for line in game.log) == 1
    # The Bears' own damage went through: the shield is keyed on the Wurm.
    assert wurm not in game.players[1].battlefield


@pytest.mark.cr("615.8", "615.5")
@pytest.mark.parametrize("interactive", _SEATS)
def test_awe_strike_stops_one_instance_and_the_next_is_dealt(set_pool, interactive):
    """A pinger's first ping at Alice is prevented and gained; its second, the
    same turn, is dealt normally."""
    game, _, (sorcerer,) = _table(set_pool, interactive, theirs=["Prodigal Sorcerer"])
    assert game.queue_from_hand(
        0, "Awe Strike", target_permanent_ids=[sorcerer.permanent_id],
    ).supported
    resolve_stack(game)
    for _ in range(2):
        sorcerer.tapped = False
        assert game.activate_permanent_ability(
            1, "Prodigal Sorcerer", target_player_index=0,
        ).supported
        resolve_stack(game)
    assert game.players[0].life == 20  # +1 gained, then -1 dealt


@pytest.mark.cr("615.8", "615.5", "109.5")
def test_awe_strike_on_your_own_creature_pays_you_for_damage_to_theirs(set_pool):
    """No recipient is printed: the targeted creature's damage to an opponent's
    creature is prevented too, and "you" — the caster — gains the life."""
    game, (sorcerer,), (elves,) = _table(
        set_pool, set(), mine=["Prodigal Sorcerer"], theirs=["Llanowar Elves"],
    )
    assert game.queue_from_hand(
        0, "Awe Strike", target_permanent_ids=[sorcerer.permanent_id],
    ).supported
    resolve_stack(game)
    assert game.activate_permanent_ability(
        0, "Prodigal Sorcerer", target_permanent_ids=[elves.permanent_id],
    ).supported
    resolve_stack(game)
    assert elves in game.players[1].battlefield
    assert [player.life for player in game.players] == [21, 20]


@pytest.mark.cr("615.8", "400.7")
def test_awe_strike_names_one_object_not_a_look_alike(set_pool):
    """The shield is keyed on the targeted permanent by identity: a second
    Prodigal Sorcerer's ping is dealt, and the named one's is still prevented
    afterwards."""
    game, _, (named, other) = _table(
        set_pool, set(), theirs=["Prodigal Sorcerer", "Prodigal Sorcerer"],
    )
    assert game.queue_from_hand(
        0, "Awe Strike", target_permanent_ids=[named.permanent_id],
    ).supported
    resolve_stack(game)
    for pinger, life in ((other, 19), (named, 20)):
        assert game.activate_permanent_ability(
            1, "Prodigal Sorcerer", target_player_index=0,
            permanent_index=game.battlefield_index_of(pinger),
        ).supported
        resolve_stack(game)
        assert game.players[0].life == life, game.log[-4:]
