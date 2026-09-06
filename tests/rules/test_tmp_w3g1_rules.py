"""Tempest wave 3, group 1 — the rules behind the end step's delayed removals.

The end step swept four metadata flags with one call, regeneration and
indestructibility both switched off, and its own comment named both the reason
and the fix: three of the flags say *destroy* and the fourth says *sacrifice*,
"separating them is a rules feature, not cleanup".

Separated, the destruction half is an ordinary destruction. Every card on it
printed the word "destroy" — Nettling Imp, Norritt, Arcum's Whistle, Siren's
Call, Maddening Imp, Berserk, Dragon Whelp — and none of them was getting
CR 701.8's meaning of it: an indestructible creature that stayed home was
destroyed, and a regeneration shield was ignored.

The sacrifice half keeps both switched off, which is CR 701.21a saying so
rather than a shortcut: a sacrifice is not a destruction, so nothing that
replaces destruction can reach it.
"""

from __future__ import annotations

import dataclasses

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import _mk_creature_card, _nosick


def _board(cards):
    """One battlefield, no summoning sickness, ready for an end step."""
    player = PlayerState(name="P0")
    other = PlayerState(name="P1")
    for card in cards:
        player.battlefield.append(_nosick(Permanent(card=card)))
    game = Game(players=[player, other])
    game.enforce_mana_costs = False
    game._sync_control()
    game.start_turn(0)
    return game, player


def _sweep(game):
    game.resolve_end_step(0)
    game.check_state_based_actions()


@pytest.mark.cr("701.8a", "702.12b")
def test_a_delayed_end_step_destruction_spares_an_indestructible_permanent():
    """CR 702.12b: "a permanent with indestructible can't be destroyed".

    The flag is Dragon Whelp's, Berserk's and the whole attack-requirement
    family's, and all of them print "destroy" — so the sweep that carries them
    out must be a destruction, which this one was not.
    """
    rock = dataclasses.replace(
        _mk_creature_card("Rock", 2, 2),
        keywords=("Indestructible",), oracle_text="Indestructible",
    )
    game, player = _board([rock, _mk_creature_card("Bear", 2, 2)])
    for perm in player.battlefield:
        perm.metadata["destroy_at_next_end_step"] = True
    _sweep(game)
    assert [perm.card.name for perm in player.battlefield] == ["Rock"]


@pytest.mark.cr("701.8c", "701.19a")
def test_a_delayed_end_step_destruction_is_replaced_by_a_regeneration_shield():
    """CR 701.8c: a regeneration effect replaces a destruction event.

    The shield is consumed and the creature stays, exactly as it would against
    any other printed "destroy" — and it is the *next* destruction the shield
    protects against (CR 701.19a), so a second end step finds it unshielded.
    """
    game, player = _board([_mk_creature_card("Bear", 2, 2)])
    bear = player.battlefield[0]
    bear.regeneration_shield = 1
    bear.metadata["destroy_at_next_end_step"] = True
    _sweep(game)
    assert [perm.card.name for perm in player.battlefield] == ["Bear"]
    assert bear.regeneration_shield == 0


@pytest.mark.cr("701.21a")
def test_a_delayed_end_step_sacrifice_ignores_both():
    """CR 701.21a: "sacrificing a permanent doesn't destroy it, so regeneration
    or other effects that replace destruction can't affect this action".

    The half of the old sweep whose flags were right, asserted so that
    separating the two cannot quietly hand a sacrifice the protections the
    destruction half now gets.
    """
    rock = dataclasses.replace(
        _mk_creature_card("Rock", 2, 2),
        keywords=("Indestructible",), oracle_text="Indestructible",
    )
    game, player = _board([rock, _mk_creature_card("Bear", 2, 2)])
    for perm in player.battlefield:
        perm.metadata["sacrifice_at_next_end_step"] = True
    player.battlefield[1].regeneration_shield = 1
    _sweep(game)
    assert [perm.card.name for perm in player.battlefield] == []


@pytest.mark.cr("508.1a", "701.8a")
def test_the_attack_requirements_delayed_destruction_is_a_destruction_too():
    """CR 508.1a's requirement and the destruction printed behind it are two
    different things, and only the second one is a destroy.

    The mark is the one Nettling Imp, Siren's Call and Maddening Imp all set;
    the creature that stayed home is destroyed and an indestructible one is
    not.
    """
    rock = dataclasses.replace(
        _mk_creature_card("Rock", 2, 2),
        keywords=("Indestructible",), oracle_text="Indestructible",
    )
    game, player = _board([rock, _mk_creature_card("Bear", 2, 2)])
    for perm in player.battlefield:
        perm.metadata["must_attack_until_eot"] = True
        perm.metadata["destroy_if_did_not_attack_eot"] = True
    _sweep(game)
    assert [perm.card.name for perm in player.battlefield] == ["Rock"]
