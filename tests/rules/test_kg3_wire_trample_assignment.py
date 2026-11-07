"""CR 702.19b — a trampler blocked by one creature is a choice for whoever
assigns its combat damage.

"The controller of an attacking creature with trample first assigns damage to
the creature(s) blocking it. Once all those blocking creatures are assigned
lethal damage, any excess damage is assigned as its controller chooses among
those blocking creatures and the player, planeswalker, or battle the creature
is attacking." (CR 702.19b.)

The damage step resolved a single block as it was entered — lethal to the
blocker, the rest to the player — so a person attacking with a 6/6 trampler
into a 1/1 could put one point on the blocker and no more (Known gap "Trample
damage is assigned without asking a human attacker", Scion of Darkness's 3/3
split). The gate always accepted the other answers
(``_attacker_division_refusal``); nothing asked. Now an **interactive**
assigner with a choice stops the step (``Game.trample_assignments_to_ask``),
the active player's through the ordinary assignment and a defending player's
(CR 702.22j) through theirs, and every other seat keeps the stated default.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent

from tests.helpers import _mk_creature_card


def _trampler(power: int = 6, toughness: int = 6, extra: str = ""):
    """An invented trampler — behaviour, not a name."""
    text = "Trample" if not extra else f"Trample\n{extra}"
    return _mk_creature_card("Stomping Beast", power, toughness, text)


def _creature(name: str, power: int, toughness: int, text: str = ""):
    return _mk_creature_card(name, power, toughness, text)


def _combat(attacker_card, blocker_cards, *, interactive=()):
    """Declare *attacker_card* (seat 0) into *blocker_cards* (seat 1) through
    the engine's own steps, stopping once combat damage has been entered."""
    me = PlayerState(name="Me")
    opp = PlayerState(name="Opp")
    game = Game(players=[me, opp])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    me.life = opp.life = 20

    def put(seat, card):
        perm = Permanent(card=card)
        game._put_permanent_onto_battlefield(seat, perm, None)
        perm.metadata["summoning_sickness_turn"] = -99
        return perm

    attacker = put(0, attacker_card)
    blockers = [put(1, card) for card in blocker_cards]
    game.active_player_index = 0
    for _ in range(4):
        game.advance_combat_phase()
        if game.current_step == "declare_attackers":
            break
    ok, why = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok, why
    game.advance_combat_phase()
    ok, why = game.declare_blockers(1, {i: 0 for i in range(len(blockers))})
    assert ok, why
    game.advance_combat_phase()
    return game, attacker, blockers


def _stopped(game) -> bool:
    return game.current_step == "combat_damage" and not game.combat_damage_resolved


@pytest.mark.cr("702.19b", "510.1c")
def test_one_blocker_stops_the_step_for_an_interactive_attacker():
    game, beast, (chump,) = _combat(_trampler(), [_creature("Chump", 1, 1)], interactive=(0,))

    assert _stopped(game), "the step resolved without asking"
    assert game.trample_assignments_to_ask() == [0]
    assert game.trample_assignments_to_ask(0) == [0]
    assert game.trample_assignments_to_ask(1) == []
    assert game._needs_manual_damage_assignment()
    assert game._manual_assignment_has_declared_multiblock(), "the dialog can surface it"
    assert (game.players[1].life, chump.damage_marked) == (20, 0)
    game.advance_combat_phase()
    assert _stopped(game), "advancing does not run past the question"


@pytest.mark.cr("702.19b")
@pytest.mark.parametrize(
    ("to_blocker", "life"),
    [(6, 20), (4, 18), (3, 17)],
    ids=["all-on-the-blocker", "some-of-each", "lethal-then-the-rest"],
)
def test_each_legal_answer_is_dealt_as_announced(to_blocker, life):
    game, _beast, (guard,) = _combat(_trampler(), [_creature("Guard", 1, 3)], interactive=(0,))

    ok, why = game.resolve_combat_damage(0, attacker_damage={0: {0: to_blocker}})

    assert ok, why
    assert game.combat_damage_resolved
    assert game.players[1].life == life
    took = f"Opp took {20 - life} combat damage"
    assert any(took in line for line in game.log) == (life < 20)
    assert not game.is_on_battlefield(guard), "lethal or more, every answer"


@pytest.mark.cr("702.19b", "510.1e")
def test_less_than_lethal_to_the_blocker_is_refused_and_still_owed():
    game, _beast, (wall,) = _combat(_trampler(), [_creature("Wall", 0, 3)], interactive=(0,))

    ok, why = game.resolve_combat_damage(0, attacker_damage={0: {0: 2}})

    assert not ok and "lethal" in why
    assert _stopped(game)
    assert (game.players[1].life, wall.damage_marked) == (20, 0)


@pytest.mark.cr("702.19b", "510.1c")
def test_a_seat_nobody_sits_in_keeps_the_lethal_then_rest_default():
    """The default every non-interactive seat (an AI, a headless table) takes,
    unchanged: lethal to the blocker and the rest past it."""
    game, _beast, (chump,) = _combat(_trampler(), [_creature("Chump", 1, 1)])

    assert game.combat_damage_resolved, "a headless single block must resolve"
    assert game.trample_assignments_to_ask() == []
    assert game.players[1].life == 15
    assert not game.is_on_battlefield(chump)


@pytest.mark.cr("510.1", "702.19b")
def test_an_interactive_defender_is_not_asked_about_the_attackers_trample():
    game, _beast, _blockers = _combat(_trampler(), [_creature("Chump", 1, 1)], interactive=(1,))

    assert game.combat_damage_resolved
    assert game.players[1].life == 15


@pytest.mark.cr("510.1c", "702.19b")
def test_no_excess_over_lethal_is_no_choice():
    """Power at or under the blocker's lethal damage: all of it to the
    blocker (CR 510.1c), and nobody is stopped."""
    game, _beast, (wall,) = _combat(_trampler(3, 3), [_creature("Wall", 0, 4)], interactive=(0,))

    assert game.combat_damage_resolved
    assert game.trample_assignments_to_ask() == []
    assert (game.players[1].life, wall.damage_marked) == (20, 3)


@pytest.mark.cr("702.2c", "702.19b")
def test_deathtouch_makes_one_point_lethal_so_the_rest_is_a_choice():
    game, _beast, (wall,) = _combat(
        _trampler(3, 3, extra="Deathtouch"), [_creature("Wall", 0, 4)], interactive=(0,),
    )

    assert _stopped(game)
    assert game.trample_assignments_to_ask() == [0]
    ok, why = game.resolve_combat_damage(0, attacker_damage={0: {0: 1}})
    assert ok, why
    assert game.players[1].life == 18


@pytest.mark.cr("702.19b", "510.1c")
def test_two_blockers_are_the_division_they_always_were():
    """The arm that already stopped every seat, unchanged — and not
    double-counted as a trample question."""
    game, _beast, _walls = _combat(
        _trampler(), [_creature("Chump A", 1, 1), _creature("Chump B", 1, 1)], interactive=(0,),
    )

    assert _stopped(game)
    assert game.trample_assignments_to_ask() == []
    ok, why = game.resolve_combat_damage(0, attacker_damage={0: {0: 1, 1: 1}})
    assert ok, why
    assert game.players[1].life == 16


@pytest.mark.cr("702.22j", "702.19b")
def test_a_defending_player_who_assigns_is_asked_and_their_answer_is_held():
    """Banding: the defending player assigns the trampler's damage (CR
    702.22j), and may keep all of it on their blocker."""
    game, _beast, (bander,) = _combat(
        _trampler(), [_creature("Bander", 1, 2, "Banding")], interactive=(0, 1),
    )

    assert _stopped(game)
    assert game.combat_damage_assigner(0) == 1
    assert game.trample_assignments_to_ask(1) == [0]
    assert game.trample_assignments_to_ask(0) == [], "not the attacking player's"
    assert game.defender_assignments_owed(1) == [0]

    ok, why = game.assign_banding_combat_damage(1, {0: {0: 6}})
    assert ok, why
    assert game.trample_assignments_to_ask() == [], "answered for this step"
    assert game.defender_assignments_owed(1) == []

    ok, why = game.resolve_combat_damage(0)
    assert ok, why
    assert game.players[1].life == 20
    assert not game.is_on_battlefield(bander)


@pytest.mark.cr("702.22j", "702.19b")
def test_a_defender_nobody_sits_in_is_not_asked_and_keeps_it_on_the_blocker():
    """Nobody sits in the defending seat, so the step is not stopped for it
    (``trample_assignments_to_ask``); that seat's own chooser answers as the
    step is dealt, and keeps all six on the bander — which dies of the two it
    would have been dealt anyway — rather than taking four (kg4: it kept the
    engine's default, the attacker's split)."""
    game, _beast, (bander,) = _combat(
        _trampler(), [_creature("Bander", 1, 2, "Banding")], interactive=(0,),
    )

    assert game.trample_assignments_to_ask() == []
    assert game.combat_damage_resolved
    assert game.players[1].life == 20
    assert not game.is_on_battlefield(bander)


@pytest.mark.cr("510.4", "702.19b")
def test_a_first_striker_is_not_asked_again_once_it_has_dealt_its_damage():
    game, beast, (wall,) = _combat(
        _trampler(4, 4, extra="First strike"), [_creature("Wall", 0, 2)], interactive=(0,),
    )

    assert _stopped(game) and game.trample_assignments_to_ask() == [0]
    ok, why = game.resolve_combat_damage(0, attacker_damage={0: {0: 2}})
    assert ok, why
    assert game.combat_first_strike_done
    assert game.players[1].life == 18
    assert game.trample_assignments_to_ask() == [], "it struck in the first step"
