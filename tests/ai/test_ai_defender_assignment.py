"""A defending seat nobody asks assigns the damage that is its to assign — as
a defender would.

Where the **defending** player assigns an attacker's combat damage (CR
702.22j: a creature with banding is blocking it; Defensive Formation's
"rather than the attacking player, you assign…"), two answers are that
player's: how the damage is divided among the creatures blocking, and — for
an attacker that "may … assign its combat damage as though it weren't
blocked" — whether it is (the cards' ruling of 2018-04-27 gives the choice to
whoever assigns). A person is asked both. A seat nobody is sitting at was
given the engine's defaults: the division that kills as many of its own
blockers as the power allows, which is the *attacker's* division, and the
offer always declined — its blocker died in front of a Thorn Elemental at
twenty life.

``ai_combat.choose_defender_damage_assignment`` is the attacker's valuation
from the other chair, announced by the damage step itself
(``Game.resolve_combat_damage`` -> ``ai_combat.announce_defender_assignments``)
so that it is there however the step came to be resolved.

Every assertion is on the board after the damage is dealt.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_combat import (announce_defender_assignments,
                              choose_defender_damage_assignment,
                              run_ai_combat_phase)
from engine.card_loader import load_cards, manifest_set_paths
from engine.combat_assignment import AS_THOUGH_UNBLOCKED_LOG
from engine.faces import compilation_units
from engine.models import Permanent
from tests.helpers import _mk_creature_card

ME, OPP = 0, 1


@pytest.fixture(scope="module")
def pool() -> dict:
    cards: dict = {}
    for card in compilation_units(load_cards(manifest_set_paths())):
        cards.setdefault(card.name, card)
    return cards


def _bander(name="Their Bander", power=1, toughness=1):
    card = _mk_creature_card(name, power, toughness)
    from dataclasses import replace

    return replace(card, oracle_text="Banding", keywords=("Banding",))


def _combat(attacker_card, blocker_cards, *, life: int = 20, interactive=()):
    """*attacker_card* attacking for seat 0 into every one of *blocker_cards*,
    stopped with the blocks declared and combat damage not yet entered."""
    game = Game(players=[PlayerState(name="Me"), PlayerState(name="Opp")])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.players[OPP].life = life
    attacker = Permanent(card=attacker_card)
    game._put_permanent_onto_battlefield(ME, attacker, None)
    attacker.metadata["summoning_sickness_turn"] = -99
    blockers = []
    for card in blocker_cards:
        blocker = Permanent(card=card)
        game._put_permanent_onto_battlefield(OPP, blocker, None)
        blockers.append(blocker)
    game.active_player_index = ME
    for _ in range(4):
        game.advance_combat_phase()
        if game.current_step == "declare_attackers":
            break
    ok, why = game.declare_attackers(ME, [0], defending_player_index=OPP)
    assert ok, why
    game.advance_combat_phase()
    ok, why = game.declare_blockers(OPP, {slot: 0 for slot in range(len(blockers))})
    assert ok, why
    return game, attacker, blockers


def _deal(game, site: str) -> None:
    """Deal the combat damage by one of the roads that reach the step."""
    if site == "driver":
        # The simulator's: advance, and supply what the engine waits for.
        run_ai_combat_phase(game, ME)
    else:
        # A resolution called for directly — a person's own assignment in the
        # web app, the engine's rail for a second step.
        while game.current_step != "combat_damage" and game.current_turn_phase == "combat":
            game.advance_combat_phase()
        if game.current_turn_phase == "combat" and not game.combat_damage_resolved:
            ok, why = game.resolve_all_combat_damage(ME)
            assert ok, why
    assert game.combat_damage_resolved or game.current_turn_phase != "combat"


def _alive(game, permanent) -> bool:
    return any(found is permanent for found in game.controlled_by(OPP))


@pytest.mark.parametrize("site", ["driver", "direct"])
def test_the_damage_goes_on_the_blocker_worth_least(site):
    """A 6/4 blocked by a 1/1 with banding and a 4/4. Six damage cannot be
    spread without a death, so one creature takes all of it — the 1/1. The
    default assigned lethal damage to each in turn: both died."""
    game, _attacker, (bander, angel) = _combat(
        _mk_creature_card("My Wurm", 6, 4),
        [_bander(), _mk_creature_card("Their Angel", 4, 4)],
    )
    _deal(game, site)
    assert _alive(game, angel)
    assert not _alive(game, bander)
    assert game.players[OPP].life == 20


@pytest.mark.parametrize("site", ["driver", "direct"])
def test_nobody_dies_where_the_damage_fits_under_what_each_can_take(site):
    """A 3/3 blocked by a 1/1 with banding and a 0/4: three damage on the
    0/4 kills nothing. The default put the first point on the 1/1."""
    game, _attacker, (bander, wall) = _combat(
        _mk_creature_card("My Ogre", 3, 3),
        [_bander(), _mk_creature_card("Their Wall", 0, 4)],
    )
    _deal(game, site)
    assert _alive(game, bander) and _alive(game, wall)
    assert wall.damage_marked == 3 or game.current_turn_phase != "combat"


@pytest.mark.parametrize("site", ["driver", "direct"])
def test_the_defender_takes_a_thorn_elementals_damage_itself_at_twenty_life(pool, site):
    """Thorn Elemental (7/7, "You may have this creature assign its combat
    damage as though it weren't blocked") blocked by one creature with
    banding: the choice is the defending player's. At twenty life seven
    damage is worth less than the creature it would kill. It was never taken:
    the blocker died."""
    game, _attacker, (bander,) = _combat(pool["Thorn Elemental"], [_bander()])
    _deal(game, site)
    assert _alive(game, bander)
    assert game.players[OPP].life == 13
    assert any(AS_THOUGH_UNBLOCKED_LOG in line for line in game.log)


@pytest.mark.parametrize("site", ["driver", "direct"])
def test_and_keeps_it_on_the_blocker_when_it_would_be_the_game(pool, site):
    game, _attacker, (bander,) = _combat(pool["Thorn Elemental"], [_bander()], life=7)
    _deal(game, site)
    assert not _alive(game, bander)
    assert game.players[OPP].life == 7
    assert not any(AS_THOUGH_UNBLOCKED_LOG in line for line in game.log)


def test_it_is_kept_on_a_blocker_that_would_not_die(pool):
    """A 0/8 with banding in front of the Elemental: nothing is lost by
    leaving the damage where it is."""
    game, _attacker, (wall,) = _combat(
        pool["Thorn Elemental"], [_bander("Their Bulwark", 0, 8)],
    )
    divisions, taken = choose_defender_damage_assignment(game, OPP)
    assert taken == [] and divisions == {0: {0: 7}}
    _deal(game, "direct")
    assert _alive(game, wall) and game.players[OPP].life == 20


def test_a_person_defending_is_not_answered_for(pool):
    """The seam answers for a seat nobody is sitting at. A person's dialog
    asks them, and until they answer nothing is announced in their name."""
    game, attacker, _blockers = _combat(
        pool["Thorn Elemental"], [_bander()], interactive={OPP},
    )
    while game.current_step != "combat_damage":
        game.advance_combat_phase()
    assert game.defender_assignments_owed(OPP) == [0]
    assert announce_defender_assignments(game) == 0
    assert game.defender_assignments_owed(OPP) == [0]
    assert not attacker.metadata.get("defender_announced_assignment_this_step")


def test_an_attacker_the_active_player_assigns_is_left_to_them():
    """No banding, no substitution: the division is the attacking player's
    (CR 510.1c) and the defending seat announces nothing."""
    game, _attacker, _blockers = _combat(
        _mk_creature_card("My Wurm", 6, 4),
        [_mk_creature_card("Their Bear", 2, 2), _mk_creature_card("Their Angel", 4, 4)],
    )
    while game.current_step != "combat_damage":
        game.advance_combat_phase()
    assert choose_defender_damage_assignment(game, OPP) == ({}, [])
    assert announce_defender_assignments(game) == 0
