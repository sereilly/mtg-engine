"""How a band's blocks are kept when a creature leaves combat (CR 702.22f,
702.22h, 506.4).

"If an attacking creature becomes blocked by a creature, each other creature
in the same band as the attacking creature becomes blocked by that same
blocking creature." (CR 702.22h.) "An attacking creature that's removed from
combat is also removed from the band it was in." (CR 702.22f.)

The engine records a block as the declared pair (``combat_blockers``) and
spreads it across the band (``combat_band_blocks``) by recomputing from the
pairs. The Known gap this answers ("``_remove_blocker_from_combat`` pops
``combat_band_blocks`` by blocker index, but that map is keyed by attacker")
measured as no defect — the map is rebuilt from the pairs at the end of the
same function, so the pop by the wrong key never survived it (the last test
here drives that board, and passes on the base too). Beside it, two that
did, both on the attacker's side:

* a band member **removed from combat** dissolved its whole band
  (``Game.remove_from_combat``, then in ``handlers/combat``, dropped every band the
  creature was in): a band of three that lost one member before blocks no
  longer spread a block to the other two, and the unspread one dealt its
  damage to the defending player;
* the member a blocker was **declared on** leaving combat — removed, or
  killed — took the spread with it: the blocker was left blocking nothing,
  and the band member it had become blocked by was blocked by nobody, so
  neither dealt the other any damage.

Each board is driven through the engine's own entry points (Reconnaissance's
ability, Lightning Bolt, False Orders) and finished by the simulator's combat
driver; every assertion is on the board after combat damage. Measured
backwards: the first three fail on the base.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_combat import run_ai_combat_phase
from engine.models import Permanent
from tests.helpers import _mk_creature_card, _nosick, resolve_stack


def _board(attackers, defenders, *, extra=(), hands=((), ())):
    p1 = PlayerState(name="P1", hand=list(hands[0]))
    p2 = PlayerState(name="P2", hand=list(hands[1]))
    made = ([], [])
    for seat, cards in ((0, attackers), (1, defenders)):
        for card in cards:
            permanent = Permanent(card=card)
            _nosick(permanent)
            (p1, p2)[seat].battlefield.append(permanent)
            made[seat].append(permanent)
    for card in extra:
        p1.battlefield.append(Permanent(card=card))
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._sync_control()
    game.start_turn(0)
    game._close_current_priority_step()
    for _ in range(3):
        if game.current_step == "declare_attackers":
            break
        game.advance_combat_phase()
    assert game.current_step == "declare_attackers"
    return game, made[0], made[1]


def _reconnaissance(game, attacker) -> None:
    """"{0}: Remove target attacking creature you control from combat and
    untap it." """
    result = game.activate_permanent_ability(
        0, "Reconnaissance", target_player_index=0,
        permanent_index=next(
            slot for slot, permanent in enumerate(game.players[0].battlefield)
            if permanent.card.name == "Reconnaissance"
        ),
        target_permanent_index=game.battlefield_index_of(attacker),
    )
    assert result.supported, result.details
    resolve_stack(game)


def _alive(game, permanent) -> bool:
    return game.is_on_battlefield(permanent)


@pytest.mark.cr("702.22f", "702.22h")
def test_a_band_that_loses_a_member_before_blocks_is_still_a_band(set_pool):
    """Two Benalish Heroes and a Grizzly Bears attack as one band; the Bears
    is removed from combat. The Heroes are still a band, so the Wall that
    blocks one blocks both, and neither Hero's damage reaches the player. The
    whole band was dropped: the second Hero went unblocked for one."""
    lea, exo = set_pool("LEA"), set_pool("EXO")
    game, (first, second, bears), (wall,) = _board(
        [lea["Benalish Hero"], lea["Benalish Hero"], lea["Grizzly Bears"]],
        [_mk_creature_card("Their Wall", 0, 4)],
        extra=[exo["Reconnaissance"]],
    )
    ok, why = game.declare_attackers(0, [0, 1, 2], bands=[[0, 1, 2]])
    assert ok, why
    _reconnaissance(game, bears)
    assert not bears.attacking

    game.advance_combat_phase()
    ok, why = game.declare_blockers(1, {0: 0})
    assert ok, why
    assert second.blocked, "CR 702.22h: the Wall blocks the whole band"
    run_ai_combat_phase(game, 0)

    assert game.players[1].life == 20, game.log[-8:]
    assert wall.damage_marked == 2, "both Heroes' damage went to the Wall blocking them"
    assert not any(line.startswith("P2 took") for line in game.log), game.log[-8:]


@pytest.mark.cr("702.22h", "506.4")
def test_a_blocker_keeps_blocking_the_band_when_its_declared_attacker_is_removed(set_pool):
    """Benalish Hero and Grizzly Bears attack as a band and an Ogre blocks the
    Hero, so the Bears is blocked by the Ogre too. Reconnaissance takes the
    Hero out of combat: the Ogre is still blocking the Bears, and the two
    trade. Both lived — the Ogre blocking nothing, the Bears blocked by
    nobody."""
    lea, exo = set_pool("LEA"), set_pool("EXO")
    game, (hero, bears), (ogre,) = _board(
        [lea["Benalish Hero"], lea["Grizzly Bears"]],
        [_mk_creature_card("Their Ogre", 2, 2)],
        extra=[exo["Reconnaissance"]],
    )
    ok, why = game.declare_attackers(0, [0, 1], bands=[[0, 1]])
    assert ok, why
    game.advance_combat_phase()
    ok, why = game.declare_blockers(1, {0: 0})
    assert ok, why
    assert bears.blocked

    _reconnaissance(game, hero)
    assert not hero.attacking
    run_ai_combat_phase(game, 0)

    assert not _alive(game, bears), game.log[-8:]
    assert not _alive(game, ogre), game.log[-8:]
    assert _alive(game, hero)
    assert game.players[1].life == 20


@pytest.mark.cr("702.22h", "506.4")
def test_a_blocker_keeps_blocking_the_band_when_its_declared_attacker_dies(set_pool):
    """The same band and block, and the defending player bolts the Hero
    after blocks. The Ogre was blocking the Bears as well (CR 702.22h), and
    nothing removed it from combat: the Bears and the Ogre trade."""
    lea = set_pool("LEA")
    game, (hero, bears), (ogre,) = _board(
        [lea["Benalish Hero"], lea["Grizzly Bears"]],
        [_mk_creature_card("Their Ogre", 2, 2)],
        hands=((), (lea["Lightning Bolt"],)),
    )
    ok, why = game.declare_attackers(0, [0, 1], bands=[[0, 1]])
    assert ok, why
    game.advance_combat_phase()
    ok, why = game.declare_blockers(1, {0: 0})
    assert ok, why

    result = game.cast_from_hand(1, "Lightning Bolt", target_player_index=0, target_permanent_index=0)
    assert result.supported, result.details
    resolve_stack(game)
    assert not _alive(game, hero)
    run_ai_combat_phase(game, 0)

    assert not _alive(game, bears), game.log[-8:]
    assert not _alive(game, ogre), game.log[-8:]


@pytest.mark.cr("702.22h", "506.4")
def test_a_blocker_removed_from_combat_takes_only_its_own_blocks_with_it(set_pool):
    """The Known gap's own board, and no defect: two Benalish Heroes banded,
    a Wall declared on each — so each Hero is blocked by both. False Orders
    takes the second Wall out of combat; the first is still blocking both
    Heroes (the second Hero was not blocked by only the removed Wall, so it
    stays blocked), and takes both Heroes' damage. The pop by the blocker's
    slot named the first Hero's entry in an attacker-keyed map, and the map
    was rebuilt from the pairs at the end of the same call."""
    lea = set_pool("LEA")
    game, (first, second), (wall, other_wall) = _board(
        [lea["Benalish Hero"], lea["Benalish Hero"]],
        [_mk_creature_card("Their Wall", 0, 4), _mk_creature_card("Their Other Wall", 0, 4)],
        hands=((lea["False Orders"],), ()),
    )
    ok, why = game.declare_attackers(0, [0, 1], bands=[[0, 1]])
    assert ok, why
    game.advance_combat_phase()
    ok, why = game.declare_blockers(1, {0: 0, 1: 1})
    assert ok, why

    result = game.cast_from_hand(0, "False Orders", target_player_index=1, target_permanent_index=1)
    assert result.supported, result.details
    resolve_stack(game)
    assert first.blocked and second.blocked
    run_ai_combat_phase(game, 0)

    assert wall.damage_marked == 2, game.log[-8:]
    assert other_wall.damage_marked == 0
    assert game.players[1].life == 20
