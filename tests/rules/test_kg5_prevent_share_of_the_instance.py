"""A "next time" shield that prevents a **share** — Dark Sphere's half,
Forcefield's all but 1 — takes it of CR 615.8's whole instance.

Dark Sphere: "{T}, Sacrifice this artifact: The next time a source of your
choice would deal damage to you this turn, prevent half that damage, rounded
down." CR 615.8's instance is everything that source deals in one
simultaneous dealing (the project owner's ruling, 2026-11-07), so a split
sentence naming you for both halves — Cuombajj Witches, the opponent picking
you for the second point — is one instance of 2, and half of it is 1. The
shield halved each chunk (0 and 0) until kg5; it now keeps an account of the
instance (``Shield.share_seen`` / ``share_taken``) and reads the sentence's
chunks still to be dealt there (``simultaneous_damage.still_to_come``). Two
Dark Spheres on one event still apply one after the other (its ruling,
2013-04-15: 5 damage, the first prevents 2, the second 1).

Forcefield: "{1}: The next time an unblocked creature of your choice would
deal combat damage to you this turn, prevent all but 1 of that damage." The
same share arithmetic — but the census found a larger defect beside it: the
shield answered **any** damage. The charge an AI or headless activation arms
(no attacker named) capped a Lightning Bolt to 1, and the chosen attacker's
noncombat damage was capped too. Both now answer combat damage only, and the
charge an unblocked creature's alone (its ruling, 2004-10-04: "This can't be
used to prevent damage caused by a blocked creature with Trample ability").
A combat damage step deals a player one chunk per attacker, so Forcefield's
share never spans two chunks; it is driven against combat damage.

Validated backwards: on the base (``59f133e6``) the Witches board, the Bolt
board and the noncombat ping board fail; the combat boards pass on both.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import declare_attack, drive_combat, settle

_SEATS = [pytest.param(set(), id="nobody-asked"), pytest.param({0, 1}, id="interactive")]


def _table(catalog_by_name, interactive, *, hand1=()):
    game = Game(players=[
        PlayerState(name="Alice", library=[catalog_by_name["Island"]] * 20),
        PlayerState(name="Bob", library=[catalog_by_name["Island"]] * 20,
                    hand=[catalog_by_name[name] for name in hand1]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    game.current_turn_phase = "main1"
    return game


def _put(game, catalog_by_name, seat, name):
    permanent = Permanent(card=catalog_by_name[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _sphere(game, seat, source):
    armed = game.activate_permanent_ability(
        seat, "Dark Sphere", target_player_index=1 - seat,
        target_permanent_ids=[source.permanent_id],
    )
    assert armed.supported, armed.details
    settle(game)


# ---------------------------------------------------------------------------
# Dark Sphere
# ---------------------------------------------------------------------------


@pytest.mark.cr("615.8", "608.2f")
def test_dark_sphere_halves_a_split_sentence_s_instance_at_you(catalog_by_name):
    """Bob's Witches name Alice for both halves (she answers the second): one
    instance of 2 from one source, half of it prevented — she loses 1."""
    game = _table(catalog_by_name, {0})
    _put(game, catalog_by_name, 0, "Dark Sphere")
    witches = _put(game, catalog_by_name, 1, "Cuombajj Witches")
    _sphere(game, 0, witches)
    game.active_player_index = 1
    assert game.activate_permanent_ability(1, "Cuombajj Witches", target_player_index=0).supported
    for _ in range(6):
        if game.pending_choices or not game.stack:
            break
        game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_opponent_damage_choice(0, target_seat=0)
    settle(game)
    assert game.players[0].life == 19, game.log

    # The instance is over: the Witches' next dealing is dealt normally.
    witches.tapped = False
    assert game.activate_permanent_ability(1, "Cuombajj Witches", target_player_index=0).supported
    for _ in range(6):
        if game.pending_choices or not game.stack:
            break
        game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_opponent_damage_choice(0, target_seat=0)
    settle(game)
    assert game.players[0].life == 17, game.log


@pytest.mark.cr("615.8", "510.2")
@pytest.mark.parametrize("interactive", _SEATS)
@pytest.mark.parametrize("spheres, dealt", [(1, 3), (2, 2)], ids=["one", "two"])
def test_dark_sphere_against_combat_damage(catalog_by_name, interactive, spheres, dealt):
    """Alice's Craw Wurm (6/4) attacks unblocked; Bob's Dark Sphere names it.
    One prevents half of the 6 (3 dealt); two apply in turn to what the first
    left, 3 and then 1 (Dark Sphere's ruling; 2 dealt)."""
    game = _table(catalog_by_name, interactive)
    attacker = _put(game, catalog_by_name, 0, "Craw Wurm")
    for _ in range(spheres):
        _put(game, catalog_by_name, 1, "Dark Sphere")
    declare_attack(game, 0)
    for _ in range(spheres):
        _sphere(game, 1, attacker)
    drive_combat(game, through="combat_damage")
    assert game.players[1].life == 20 - dealt, game.log


# ---------------------------------------------------------------------------
# Forcefield
# ---------------------------------------------------------------------------


@pytest.mark.cr("615.8", "510.2")
@pytest.mark.parametrize("interactive", _SEATS)
def test_forcefield_without_an_attacker_named_lets_a_bolt_through(catalog_by_name, interactive):
    """The charge with no attacker named answers combat damage from an
    unblocked creature: Bob's Lightning Bolt at Alice is dealt whole."""
    game = _table(catalog_by_name, interactive, hand1=["Lightning Bolt"])
    _put(game, catalog_by_name, 0, "Forcefield")
    assert game.activate_permanent_ability(0, "Forcefield").supported
    settle(game)
    game.active_player_index = 1
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    settle(game)
    assert game.players[0].life == 17, game.log


@pytest.mark.cr("615.8", "510.2")
@pytest.mark.parametrize("interactive", _SEATS)
@pytest.mark.parametrize("named", [True, False], ids=["attacker-named", "no-attacker-named"])
def test_forcefield_caps_an_unblocked_attacker_s_combat_damage_to_one(
    catalog_by_name, interactive, named,
):
    """Alice's unblocked Craw Wurm (6/4) attacks Bob, whose Forcefield names
    it (or names nothing): he is dealt 1."""
    game = _table(catalog_by_name, interactive)
    wurm = _put(game, catalog_by_name, 0, "Craw Wurm")
    _put(game, catalog_by_name, 1, "Forcefield")
    declare_attack(game, 0)
    kwargs = {"target_permanent_ids": [wurm.permanent_id]} if named else {}
    assert game.activate_permanent_ability(1, "Forcefield", **kwargs).supported
    settle(game)
    drive_combat(game, through="combat_damage")
    assert game.players[1].life == 19, game.log


@pytest.mark.cr("702.19b", "615.8")
def test_forcefield_without_an_attacker_named_leaves_a_blocked_trampler(catalog_by_name):
    """Crash of Rhinos (8/4 trample) blocked by Grizzly Bears assigns 2 and 6;
    the 6 to Bob is a blocked creature's, which the charge does not cap."""
    game = _table(catalog_by_name, set())
    _put(game, catalog_by_name, 0, "Crash of Rhinos")
    _put(game, catalog_by_name, 1, "Grizzly Bears")
    _put(game, catalog_by_name, 1, "Forcefield")
    declare_attack(game, 0, blocks={0: 0})
    assert game.activate_permanent_ability(1, "Forcefield").supported
    settle(game)
    drive_combat(game, through="combat_damage")
    assert game.players[1].life == 14, game.log


@pytest.mark.cr("615.8", "510.2")
def test_forcefield_leaves_the_named_attacker_s_noncombat_damage(catalog_by_name):
    """Alice's Leafkin Avenger (4/3: "{7}{R}: This creature deals damage equal
    to its power to target player or planeswalker") attacks unblocked and
    Bob's Forcefield names it. Before damage she activates it at Bob: 4
    noncombat damage, dealt whole. Its combat damage is then capped to 1."""
    game = _table(catalog_by_name, set())
    avenger = _put(game, catalog_by_name, 0, "Leafkin Avenger")
    _put(game, catalog_by_name, 1, "Forcefield")
    declare_attack(game, 0)
    assert game.activate_permanent_ability(
        1, "Forcefield", target_permanent_ids=[avenger.permanent_id],
    ).supported
    settle(game)
    game.active_player_index = 0
    shot = game.activate_permanent_ability(0, "Leafkin Avenger", target_player_index=1)
    assert shot.supported, shot.details
    settle(game)
    assert game.players[1].life == 16, game.log
    drive_combat(game, through="combat_damage")
    assert game.players[1].life == 15, game.log
