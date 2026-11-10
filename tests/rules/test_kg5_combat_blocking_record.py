"""CR 509.1g: a blocking creature "remains a blocking creature until it's
removed from combat or the combat phase ends, whichever comes first".

The attackers it blocks leaving combat is neither. ``_prune_combat_state`` and
the removal renumbering (``_renumber_combat_after_removal``) used to drop a
blocker the moment its last attacker left by any road — died, bounced,
regenerated, phased out, stolen, stopped being a creature, or removed by an
effect — so every reader of the state word "blocking" ("target blocking
creature", "attacking or blocking", "as long as it's blocking", "blocking
creatures get …") stopped seeing it at the next prune, and before that prune
the per-permanent projection and the combat maps disagreed.

The record outlives its attackers now: ``Game.combat_blockers`` keeps the
blocker *with none* (``{seat: {slot: []}}``), and ``Permanent.is_blocking`` is
the state every reader asks. The damage passes are unchanged (CR 510.1d: a
blocker blocking no creatures assigns no combat damage; CR 509.1h: its
attacker stays blocked), and the blocker's own removal (CR 506.4) still ends
the block.
"""

from __future__ import annotations

import pytest

from engine import PlayerState
from engine.handlers._filters import permanent_state_holds, state_holds
from engine.layer_bridge import qualifier_holds
from engine.models import Permanent
from tests.helpers import _game, _nosick, declare_attack, drive_combat, settle


def _table(by_name, *, attackers, blockers, blocks, mine=(), theirs=(),
           hand=(), opponent_hand=()):
    """Seat 0 attacks with *attackers* (slots 0…); seat 1 holds *blockers*
    (slots 0…) and declares *blocks* (``{blocker slot: attacker slot}``).
    *mine* / *theirs* are further permanents, put after those and kept out of
    the attack (tapped if seat 0's creatures). The declare blockers step, blocks
    made and settled."""
    game = _game(
        PlayerState(name="A", hand=[by_name[n] for n in hand]),
        PlayerState(name="D", hand=[by_name[n] for n in opponent_hand]),
    )
    placed = {0: [], 1: []}
    for seat, names in ((0, attackers), (1, blockers), (0, mine), (1, theirs)):
        for name in names:
            permanent = Permanent(card=by_name[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            _nosick(permanent)
            placed[seat].append(permanent)
    game._sync_control()
    game._settle()
    for extra in placed[0][len(attackers):]:
        if extra.is_creature:
            extra.tapped = True
    declare_attack(game, 0, blocks=blocks)
    settle(game)
    return game, placed[0], placed[1]


def _readers(game, blocker) -> dict[str, bool]:
    """Every reader of the state word, asked of *blocker*."""
    return {
        "filter state word (state_holds)": state_holds(blocker, "blocking"),
        "condition (permanent_state_holds)": permanent_state_holds(blocker, "blocking"),
        "static qualifier (qualifier_holds)": qualifier_holds(blocker, "blocking", 1),
        "combat record (_is_blocking_creature)": game._is_blocking_creature(blocker),
        "blocking alone (CR 506.5)": game.creature_blocking_alone(blocker),
    }


def _cast(game, seat: int, name: str, target) -> None:
    result = game.queue_from_hand(seat, name, target_permanent_ids=[target.permanent_id])
    assert result.supported, result.details
    settle(game)


def _activate(game, seat: int, name: str, target=None) -> None:
    ids = [target.permanent_id] if target is not None else None
    result = game.queue_permanent_ability(seat, name, target_permanent_ids=ids)
    assert result.supported, result.details
    settle(game)


# ---------------------------------------------------------------------------
# Every road out of combat for the *attacker*: the blocker goes on blocking.
# ---------------------------------------------------------------------------

def _attacker_dies(game, by_name, attacker, blocker):
    _cast(game, 1, "Lightning Bolt", attacker)
    assert not game.is_on_battlefield(attacker)


def _attacker_bounced(game, by_name, attacker, blocker):
    _cast(game, 1, "Unsummon", attacker)
    assert not game.is_on_battlefield(attacker)


def _attacker_regenerates(game, by_name, attacker, blocker):
    _activate(game, 0, "Drudge Skeletons")
    _cast(game, 1, "Lightning Bolt", attacker)
    assert game.is_on_battlefield(attacker) and not attacker.attacking


def _attacker_phases_out(game, by_name, attacker, blocker):
    _cast(game, 1, "Reality Ripple", attacker)
    assert attacker.metadata.get("phased_out")


def _attacker_stolen(game, by_name, attacker, blocker):
    _cast(game, 1, "Ray of Command", attacker)
    assert game.controller_index_of(attacker) == 1 and not attacker.attacking


def _attacker_stops_being_a_creature(game, by_name, attacker, blocker):
    bell = next(p for p in game.players[0].battlefield if p.card.name == "Kormus Bell")
    _cast(game, 1, "Shatter", bell)
    assert game.is_on_battlefield(attacker) and not attacker.is_creature


def _attacker_removed_by_an_effect(game, by_name, attacker, blocker):
    _activate(game, 0, "Reconnaissance", attacker)
    assert game.is_on_battlefield(attacker) and not attacker.attacking


ATTACKER_ROADS = {
    "dies": ("Grizzly Bears", (), ("Lightning Bolt",), _attacker_dies),
    "bounced": ("Grizzly Bears", (), ("Unsummon",), _attacker_bounced),
    "regenerates": ("Drudge Skeletons", (), ("Lightning Bolt",), _attacker_regenerates),
    "phases out": ("Grizzly Bears", (), ("Reality Ripple",), _attacker_phases_out),
    "changes control": ("Grizzly Bears", (), ("Ray of Command",), _attacker_stolen),
    "stops being a creature": ("Swamp", ("Kormus Bell",), ("Shatter",), _attacker_stops_being_a_creature),
    "removed by an effect": ("Grizzly Bears", ("Reconnaissance",), (), _attacker_removed_by_an_effect),
}


@pytest.mark.cr("509.1g", "506.4")
@pytest.mark.parametrize("road", sorted(ATTACKER_ROADS))
def test_a_blocker_stays_blocking_whichever_road_its_attacker_leaves_by(catalog_by_name, road):
    attacker_name, mine, opponent_hand, leave = ATTACKER_ROADS[road]
    game, (attacker, *_), (wall,) = _table(
        catalog_by_name, attackers=[attacker_name], blockers=["Wall of Stone"],
        blocks={0: 0}, mine=mine, opponent_hand=opponent_hand,
    )
    assert all(_readers(game, wall).values())

    leave(game, catalog_by_name, attacker, wall)

    # The projection before a prune and the record after one say the same.
    before = _readers(game, wall)
    game.get_combat_state()  # a prune: what every web payload and step does
    after = _readers(game, wall)
    assert before == after, (road, before, after)
    assert all(after.values()), (road, after)
    assert game.combat_attackers == {}
    assert game.combat_blockers == {1: {0: []}}
    assert game.creatures_blocked_by(wall) == []


# ---------------------------------------------------------------------------
# The blocker's own removal still ends the block (CR 506.4), and its attacker
# stays blocked (CR 509.1h).
# ---------------------------------------------------------------------------

def _blocker_dies(game, blocker):
    _cast(game, 0, "Lightning Bolt", blocker)
    assert not game.is_on_battlefield(blocker)


def _blocker_regenerates(game, blocker):
    _activate(game, 1, "Drudge Skeletons")
    _cast(game, 0, "Lightning Bolt", blocker)
    assert game.is_on_battlefield(blocker)


def _blocker_phases_out(game, blocker):
    _cast(game, 0, "Reality Ripple", blocker)
    assert blocker.metadata.get("phased_out")


def _blocker_stolen(game, blocker):
    _cast(game, 0, "Ray of Command", blocker)
    assert game.controller_index_of(blocker) == 0


def _blocker_stops_being_a_creature(game, blocker):
    bell = next(p for p in game.players[1].battlefield if p.card.name == "Kormus Bell")
    _cast(game, 0, "Shatter", bell)
    assert game.is_on_battlefield(blocker) and not blocker.is_creature


BLOCKER_ROADS = {
    "dies": ("Grizzly Bears", (), ("Lightning Bolt",), _blocker_dies),
    "regenerates": ("Drudge Skeletons", (), ("Lightning Bolt",), _blocker_regenerates),
    "phases out": ("Grizzly Bears", (), ("Reality Ripple",), _blocker_phases_out),
    "changes control": ("Grizzly Bears", (), ("Ray of Command",), _blocker_stolen),
    "stops being a creature": ("Swamp", ("Kormus Bell",), ("Shatter",), _blocker_stops_being_a_creature),
}


@pytest.mark.cr("506.4", "509.1h")
@pytest.mark.parametrize("road", sorted(BLOCKER_ROADS))
def test_a_blocker_removed_from_combat_stops_blocking_and_its_attacker_stays_blocked(
    catalog_by_name, road,
):
    blocker_name, theirs, hand, leave = BLOCKER_ROADS[road]
    game, (giant,), (blocker, *_) = _table(
        catalog_by_name, attackers=["Hill Giant"], blockers=[blocker_name],
        blocks={0: 0}, theirs=theirs, hand=hand,
    )
    leave(game, blocker)
    game.get_combat_state()

    if game.is_on_battlefield(blocker):
        assert not any(_readers(game, blocker).values()), road
    assert game.combat_blockers == {}
    assert giant.attacking and giant.blocked
    drive_combat(game)
    assert game.players[1].life == 20, "509.1h: a blocked attacker deals the player nothing"


# ---------------------------------------------------------------------------
# The damage passes are unchanged (CR 510.1d) and the record ends with the
# combat phase.
# ---------------------------------------------------------------------------

@pytest.mark.cr("510.1d", "509.1g")
def test_a_blocker_whose_attacker_left_assigns_no_combat_damage(catalog_by_name):
    """Two Hill Giants attack; a Grizzly Bears blocks each. The first Giant is
    bolted: its Bears is still blocking, blocking nothing, and deals and takes
    no combat damage — the other pair trades as usual."""
    game, (first, second), (bears_one, bears_two) = _table(
        catalog_by_name, attackers=["Hill Giant", "Hill Giant"],
        blockers=["Grizzly Bears", "Grizzly Bears"], blocks={0: 0, 1: 1},
        opponent_hand=["Lightning Bolt"],
    )
    _cast(game, 1, "Lightning Bolt", first)
    assert bears_one.is_blocking and game.creatures_blocked_by(bears_one) == []

    drive_combat(game, through="combat_damage")

    assert game.is_on_battlefield(bears_one) and bears_one.damage_marked == 0
    assert bears_one.is_blocking, "still blocking until the combat phase ends"
    assert not game.is_on_battlefield(bears_two)
    assert second.damage_marked == 2
    assert game.players[1].life == 20
    assert "Declare blockers step complete: 2 creature(s) blocking" in game.log

    drive_combat(game)
    assert game.current_turn_phase != "combat"
    assert not bears_one.is_blocking and game.combat_blockers == {}


# ---------------------------------------------------------------------------
# The cards: a blocker whose attacker died is still "target blocking creature".
# ---------------------------------------------------------------------------

@pytest.mark.cr("509.1g")
def test_destroy_target_blocking_creature_after_the_blocked_attacker_died(catalog_by_name):
    """Dauthi Jackal: "{B}{B}, Sacrifice this creature: Destroy target blocking
    creature." The Grizzly Bears the Wall blocked is bolted; the Wall is still
    blocking, so the Jackal's ability takes it as its target and destroys it."""
    game, (bears, jackal), (wall,) = _table(
        catalog_by_name, attackers=["Grizzly Bears"], blockers=["Wall of Stone"],
        blocks={0: 0}, mine=["Dauthi Jackal"], opponent_hand=["Lightning Bolt"],
    )
    _cast(game, 1, "Lightning Bolt", bears)
    game.get_combat_state()
    jackal.tapped = False

    _activate(game, 0, "Dauthi Jackal", wall)

    assert not game.is_on_battlefield(wall)
    assert "Dauthi Jackal destroyed Wall of Stone" in game.log


@pytest.mark.cr("509.1g")
def test_a_blocking_pump_reaches_a_blocker_whose_attacker_left(catalog_by_name):
    """Righteousness ("Target blocking creature gets +7/+7") and Piety
    ("Blocking creatures get +0/+3") — the two readers, a target and a mass
    pump — after the attacker the Wall blocked was bounced."""
    game, (bears,), (wall,) = _table(
        catalog_by_name, attackers=["Grizzly Bears"], blockers=["Wall of Stone"],
        blocks={0: 0}, opponent_hand=["Unsummon", "Righteousness", "Piety"],
    )
    _cast(game, 1, "Unsummon", bears)
    game.get_combat_state()

    _cast(game, 1, "Righteousness", wall)
    assert (wall.effective_power, wall.effective_toughness) == (7, 15)
    assert game.queue_from_hand(1, "Piety").supported
    settle(game)
    assert (wall.effective_power, wall.effective_toughness) == (7, 18)


@pytest.mark.cr("509.1g", "602.1b")
def test_activate_only_if_this_creature_is_blocking_after_its_attacker_died(catalog_by_name):
    """Sawback Manticore: "{1}: This creature deals 2 damage to target
    attacking or blocking creature. Activate only if this creature is
    attacking or blocking." It blocks a Grizzly Bears that is then bolted; it
    is still blocking, so the ability may be activated — at itself, the one
    blocking creature left."""
    game, (bears,), (manticore,) = _table(
        catalog_by_name, attackers=["Grizzly Bears"], blockers=["Sawback Manticore"],
        blocks={0: 0}, opponent_hand=["Lightning Bolt"],
    )
    _cast(game, 1, "Lightning Bolt", bears)
    game.get_combat_state()

    result = game.queue_permanent_ability(
        1, "Sawback Manticore", ability_index=1,
        target_permanent_ids=[manticore.permanent_id],
    )
    assert result.supported, result.details
    settle(game)
    assert manticore.damage_marked == 2


@pytest.mark.cr("509.1g")
def test_destroy_each_creature_that_blocked_at_end_of_combat_after_the_attacker_died(catalog_by_name):
    """Heat Stroke: "At end of combat, destroy each creature that blocked or
    was blocked this turn." The Bears the Wall blocked is bolted before
    damage; the Wall blocked, and is destroyed at end of combat."""
    game, (bears,), (wall, _stroke) = _table(
        catalog_by_name, attackers=["Grizzly Bears"], blockers=["Wall of Stone"],
        blocks={0: 0}, theirs=["Heat Stroke"], opponent_hand=["Lightning Bolt"],
    )
    _cast(game, 1, "Lightning Bolt", bears)

    drive_combat(game)

    assert not game.is_on_battlefield(wall)


@pytest.mark.cr("509.1g", "506.4")
def test_sorrows_path_with_a_blocker_whose_attacker_left(catalog_by_name):
    """Sorrow's Path: "Choose two target blocking creatures controlled by the
    same opponent. If each of those creatures could block all creatures that
    the other is blocking, remove both of them from combat. Each one then
    blocks all creatures the other was blocking." The first Hill Giant is
    bolted, so the Bears that blocked it is blocking nothing — still a legal
    target. The 2009-10-01 ruling: "if all the creatures that one of the
    targeted creatures was blocking have left combat, then the other targeted
    creature is considered to be able to block all creatures the first
    creature is blocking. If the ability has its full effect, the second
    creature will be removed from combat but not returned to combat; it
    doesn't block anything." """
    game, (first, second, _path), (orphan, partner) = _table(
        catalog_by_name, attackers=["Hill Giant", "Hill Giant"],
        blockers=["Grizzly Bears", "Grizzly Bears"], blocks={0: 0, 1: 1},
        mine=["Sorrow's Path"], opponent_hand=["Lightning Bolt"],
    )
    _cast(game, 1, "Lightning Bolt", first)
    game.get_combat_state()
    assert orphan.is_blocking and game.creatures_blocked_by(orphan) == []

    result = game.queue_permanent_ability(
        0, "Sorrow's Path", target_permanent_ids=[orphan.permanent_id, partner.permanent_id],
    )
    assert result.supported, result.details
    settle(game)

    assert game.creatures_blocked_by(orphan) == [second]
    assert not partner.is_blocking, "removed from combat and not returned"
    assert second.blocked


@pytest.mark.cr("510.4", "509.1g")
def test_a_first_striker_blocking_nothing_still_gives_the_combat_a_first_strike_step(catalog_by_name):
    """CR 510.4: "If at least one attacking or blocking creature has first
    strike … as the combat damage step begins", there are two combat damage
    steps. White Knight (first strike) blocked a Grizzly Bears that was
    bolted; it is still a blocking creature, so the unblocked Bears beside it
    deals its damage in the second step, not the first."""
    game, (doomed, unblocked), (knight,) = _table(
        catalog_by_name, attackers=["Grizzly Bears", "Grizzly Bears"],
        blockers=["White Knight"], blocks={0: 0}, opponent_hand=["Lightning Bolt"],
    )
    _cast(game, 1, "Lightning Bolt", doomed)
    assert knight.is_blocking and game.creatures_blocked_by(knight) == []

    drive_combat(game, through="combat_damage")

    assert game.players[1].life == 18
    log = game.log
    assert log.index("Resolved first strike combat damage") < log.index(
        "D took 2 combat damage (life: 20 → 18)"
    ), "the unblocked Bears struck in the second step"
