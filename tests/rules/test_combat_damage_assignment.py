"""CR 510.1 — who assigns a blocked attacker's combat damage, and what a
legal assignment of it is, for both seats.

    510.1c  A blocked creature assigns its combat damage to the creatures
            blocking it. … If exactly one creature is blocking it, it assigns
            all its combat damage to that creature. If two or more creatures
            are blocking it, it assigns its combat damage to those creatures
            divided as its controller chooses among them.
    510.1e  Once a player has assigned combat damage … the total damage
            assignment … is checked to see if it complies with the above
            rules. If it doesn't, the combat damage assignment is illegal; the
            game returns to the moment before that player began to assign
            combat damage.
    702.22j … if an attacking creature is being blocked by a creature with
            banding … the defending player (rather than the active player)
            chooses how the attacking creature's damage is assigned.

Four defects, one seam (``Game._attacker_division_refusal`` and the two
announcements that read it):

* **An under-assignment was accepted.** A creature with three power blocked
  by two could announce one and none, and two points of combat damage went
  nowhere. The browser's dialog would not send it; the engine took it from
  anything that did. The defending player's copy of the check asked for the
  whole and never asked about trample's lethal damage; the active player's
  asked about trample and no total at all.
* **An attacker the announcement did not name assigned nothing**, where
  CR 510.1c leaves a creature with one blocker no choice.
* **The defending player was never asked** "as though it weren't blocked"
  for an attacker whose damage they assign, though the cards' ruling gives
  them the choice: "If blocked by a creature with banding, the defending
  player decides whether or not the damage is assigned 'as though it weren't
  blocked'." (Thorn Elemental / Lone Wolf / Rhox / Pride of Lions,
  2018-04-27.) "Damage assignment choices from Trample and other things which
  allow alternative damage assignments for attacking creatures are all made
  by you." (Defensive Formation, 2004-10-04.)
* **A second combat damage step** (CR 510.4) replayed the first step's
  slot-keyed assignment over a board the first strike had changed, or — when
  the step was resolved one pass at a time and nothing was left to divide —
  was never dealt at all.

``tests/ui/test_combat_assignment_ui_api.py`` holds the wire and the dialog;
``tests/engine/test_combat_assignment_census.py`` holds the pool.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.combat_assignment import (AS_THOUGH_UNBLOCKED_LOG,
                                      DEFENDER_ANNOUNCED_THIS_STEP,
                                      DEFENDER_ASSIGNS_AS_UNBLOCKED)
from engine.models import Permanent

from tests.helpers import _mk_card, _mk_creature_card

OFFER = "You may have this creature assign its combat damage as though it weren't blocked."
FORMATION = (
    "Rather than the attacking player, you assign the combat damage of each "
    "creature attacking you. You can divide that creature's combat damage as "
    "you choose among any of the creatures blocking it."
)


def _creature(name: str, power: int, toughness: int, text: str = ""):
    return _mk_creature_card(name, power, toughness, text)


def _wall(name: str = "Probe Wall", power: int = 0, toughness: int = 9, text: str = ""):
    return _mk_creature_card(name, power, toughness, text)


def _combat(attackers, blockers, *, interactive=(), blocks=None, extra_defender=(),
            bands=None):
    """Seat 0 attacks seat 1 with *attackers*; *blockers* block as *blocks*
    says (default: every one blocks attacker 0), through the engine's own
    steps, stopping once combat damage has been **entered**.

    ``extra_defender`` are noncreature permanents put on seat 1 first, so the
    blockers' slots follow them.
    """
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

    mine = [put(0, card) for card in attackers]
    extras = [put(1, card) for card in extra_defender]
    theirs = [put(1, card) for card in blockers]
    offset = len(extras)

    game.active_player_index = 0
    for _ in range(4):
        game.advance_combat_phase()
        if game.current_step == "declare_attackers":
            break
    assert game.current_step == "declare_attackers"
    ok, why = game.declare_attackers(
        0, list(range(len(mine))), defending_player_index=1, bands=bands
    )
    assert ok, why
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers", game.current_step
    pairs = blocks if blocks is not None else {i: 0 for i in range(len(theirs))}
    ok, why = game.declare_blockers(1, {slot + offset: a for slot, a in pairs.items()})
    assert ok, why
    game.advance_combat_phase()
    return game, mine, theirs, offset


def _stopped(game) -> bool:
    return game.current_step == "combat_damage" and not game.combat_damage_resolved


def _nothing_dealt(game, permanents) -> bool:
    return (
        [p.life for p in game.players] == [20, 20]
        and all(perm.damage_marked == 0 for perm in permanents)
    )


# ---------------------------------------------------------------------------
# All of its combat damage, among the creatures blocking it
# ---------------------------------------------------------------------------


@pytest.mark.cr("510.1c", "510.1e")
def test_an_ordinary_attacker_announcing_less_than_its_power_is_refused():
    """The brief's defect, to the letter: three power, two blockers, one and
    none. It was accepted, and two points of combat damage went nowhere."""
    game, (ogre,), (a, b), _ = _combat(
        [_creature("Plain Ogre", 3, 3)], [_wall("Wall A"), _wall("Wall B")]
    )
    assert _stopped(game)

    ok, why = game.resolve_combat_damage(0, attacker_damage={0: {0: 1, 1: 0}})

    assert not ok
    assert "all of its combat damage" in why and "Plain Ogre" in why
    # CR 510.1e: the game returns to the moment before the assignment.
    assert _stopped(game) and _nothing_dealt(game, [ogre, a, b])


@pytest.mark.cr("510.1c", "510.1e")
@pytest.mark.parametrize("division", [{0: 0, 1: 0}, {0: 2}, {1: 2}, {}])
def test_every_way_of_holding_damage_back_is_refused(division):
    """Zeroes, one blocker named and short, and the entry left empty: an
    attacker the announcement *names* has said how it assigns, and what it
    said has to be all of it."""
    game, (ogre,), walls, _ = _combat(
        [_creature("Plain Ogre", 3, 3)], [_wall("Wall A"), _wall("Wall B")]
    )

    ok, why = game.resolve_combat_damage(0, attacker_damage={0: division})

    assert not ok and "all of its combat damage" in why
    assert _stopped(game) and _nothing_dealt(game, [ogre, *walls])


@pytest.mark.cr("510.1c")
@pytest.mark.parametrize("division", [{0: 3, 1: 0}, {0: 0, 1: 3}, {0: 2, 1: 1}, {0: 1, 1: 2}])
def test_every_division_of_the_whole_stays_legal(division):
    """"Divided as its controller chooses among them" — the shares are the
    controller's, with no order and no lethal damage owed to anybody. The
    check holds the total and nothing about how it is cut."""
    game, _mine, (a, b), _ = _combat(
        [_creature("Plain Ogre", 3, 3)], [_wall("Wall A"), _wall("Wall B")]
    )

    ok, why = game.resolve_combat_damage(0, attacker_damage={0: division})

    assert ok, why
    assert (a.damage_marked, b.damage_marked) == (division[0], division[1])
    assert game.players[1].life == 20


@pytest.mark.cr("510.1a", "510.1e")
def test_more_than_its_power_is_still_refused():
    game, (ogre,), walls, _ = _combat(
        [_creature("Plain Ogre", 3, 3)], [_wall("Wall A"), _wall("Wall B")]
    )

    ok, why = game.resolve_combat_damage(0, attacker_damage={0: {0: 2, 1: 2}})

    assert not ok and "exceeds attacker power" in why
    assert _nothing_dealt(game, [ogre, *walls])


@pytest.mark.cr("510.1c", "510.1e")
def test_damage_announced_onto_a_creature_that_is_not_blocking_it_is_refused():
    """"To the creatures blocking it." The amount used to be dropped in
    silence, which made {blocker: 1, bystander: 2} a legal-looking way to
    assign one of three."""
    game, (ogre,), (a, bystander), _ = _combat(
        [_creature("Plain Ogre", 3, 3)],
        [_wall("Wall A"), _wall("Bystander")],
        blocks={0: 0},
    )
    assert game.combat_damage_resolved, "a single ordinary block resolves unasked"
    assert a.damage_marked == 3

    game, (ogre,), (a, b, bystander), _ = _combat(
        [_creature("Plain Ogre", 3, 3)],
        [_wall("Wall A"), _wall("Wall B"), _wall("Bystander")],
        blocks={0: 0, 1: 0},
    )
    ok, why = game.resolve_combat_damage(0, attacker_damage={0: {0: 1, 1: 0, 2: 2}})

    assert not ok and "only to the creatures blocking it" in why
    assert _nothing_dealt(game, [ogre, a, b, bystander])


@pytest.mark.cr("510.1c", "510.1e")
def test_a_negative_amount_is_refused_wherever_it_is_put():
    game, (ogre,), walls, _ = _combat(
        [_creature("Plain Ogre", 3, 3)], [_wall("Wall A"), _wall("Wall B")]
    )

    ok, why = game.resolve_combat_damage(0, attacker_damage={0: {0: 4, 1: -1}})

    assert not ok and "cannot be negative" in why
    assert _nothing_dealt(game, [ogre, *walls])


# ---------------------------------------------------------------------------
# An attacker the announcement does not name
# ---------------------------------------------------------------------------


@pytest.mark.cr("510.1c")
def test_an_attacker_the_announcement_does_not_name_keeps_the_default():
    """CR 510.1c leaves a creature with exactly one blocker no choice — "it
    assigns all its combat damage to that creature" — so an announcement that
    names only the attacker with a decision in it has said everything there is
    to say. The unnamed one used to assign *nothing*."""
    game, _mine, (a, b, c), _ = _combat(
        [_creature("Plain Ogre", 3, 3), _creature("Plain Bear", 2, 2)],
        [_wall("Wall A"), _wall("Wall B"), _wall("Wall C")],
        blocks={0: 0, 1: 0, 2: 1},
    )
    assert _stopped(game)

    ok, why = game.resolve_combat_damage(0, attacker_damage={0: {0: 3, 1: 0}})

    assert ok, why
    assert (a.damage_marked, b.damage_marked, c.damage_marked) == (3, 0, 2)


@pytest.mark.cr("510.1c")
def test_an_empty_announcement_is_the_default_and_not_nothing():
    """``{}`` used to mean "every blocked attacker assigns no combat damage",
    which no rule lets a blocked creature with a creature in front of it do.
    It is "nothing to add" now, the same announcement as ``None``."""
    for announced in ({}, None):
        game, _mine, (a, b), _ = _combat(
            [_creature("Plain Ogre", 3, 3)],
            [_wall("Wall A", toughness=1), _wall("Wall B", toughness=9)],
        )

        ok, why = game.resolve_combat_damage(0, attacker_damage=announced)

        assert ok, why
        assert a.damage_marked + b.damage_marked == 3, announced
        assert game.players[1].life == 20


# ---------------------------------------------------------------------------
# Trample has its own arithmetic (CR 702.19b)
# ---------------------------------------------------------------------------


@pytest.mark.cr("702.19b", "510.1c")
def test_a_trampler_may_hold_back_only_what_tramples_over():
    """Lethal damage to each blocker, and the excess to the player. The
    remainder is not "unassigned": CR 702.19b says where it goes."""
    game, _mine, (a, b), _ = _combat(
        [_creature("Trampling Wurm", 6, 6, "Trample")],
        [_wall("Wall A", toughness=1), _wall("Wall B", toughness=2)],
    )

    ok, why = game.resolve_combat_damage(0, attacker_damage={0: {0: 1, 1: 2}})

    assert ok, why
    assert (a.damage_marked, b.damage_marked) == (1, 2)
    assert game.players[1].life == 17, "three trampled over"


@pytest.mark.cr("702.19b", "510.1e")
def test_a_trampler_holding_back_before_lethal_damage_is_refused():
    game, (wurm,), walls, _ = _combat(
        [_creature("Trampling Wurm", 6, 6, "Trample")],
        [_wall("Wall A", toughness=1), _wall("Wall B", toughness=4)],
    )

    ok, why = game.resolve_combat_damage(0, attacker_damage={0: {0: 1, 1: 2}})

    assert not ok and "trample requires lethal damage" in why
    assert _stopped(game) and _nothing_dealt(game, [wurm, *walls])


@pytest.mark.cr("702.19b")
def test_a_trampler_may_put_all_of_it_on_its_blockers_however_it_likes():
    """"The attacking creature's controller need not assign lethal damage to
    all those blocking creatures but in that case can't assign any damage to
    the player." All six on one of two blockers is legal; nothing is over."""
    game, _mine, (a, b), _ = _combat(
        [_creature("Trampling Wurm", 6, 6, "Trample")],
        [_wall("Wall A", toughness=1), _wall("Wall B", toughness=4)],
    )

    ok, why = game.resolve_combat_damage(0, attacker_damage={0: {0: 6, 1: 0}})

    assert ok, why
    assert (a.damage_marked, b.damage_marked) == (6, 0)
    assert game.players[1].life == 20


@pytest.mark.cr("702.19b", "702.2c")
def test_deathtouch_makes_one_damage_lethal_for_a_trampler():
    game, _mine, (a, b), _ = _combat(
        [_creature("Venomous Wurm", 4, 4, "Trample\nDeathtouch")],
        [_wall("Wall A", toughness=5), _wall("Wall B", toughness=5)],
    )

    ok, why = game.resolve_combat_damage(0, attacker_damage={0: {0: 1, 1: 1}})

    assert ok, why
    assert game.players[1].life == 18


# ---------------------------------------------------------------------------
# Two combat damage steps (CR 510.4)
# ---------------------------------------------------------------------------


@pytest.mark.cr("510.4", "510.1c")
def test_a_creature_that_does_not_strike_in_a_step_has_announced_nothing_in_it():
    """"The only creatures that assign combat damage in that step are those
    with first strike or double strike." An ordinary attacker's entry in the
    first-strike step is not an assignment yet, so nothing about it is
    examined there — and the second step holds it to the rule."""
    game, (ogre,), (striker, wall), _ = _combat(
        [_creature("Plain Ogre", 3, 9)],
        [_wall("First Striker", power=1, text="First strike"), _wall("Wall B")],
    )

    ok, why = game.resolve_combat_damage(0, attacker_damage={0: {0: 1, 1: 0}})
    assert ok, why
    assert game.combat_first_strike_done and not game.combat_damage_resolved
    assert ogre.damage_marked == 1 and (striker.damage_marked, wall.damage_marked) == (0, 0)

    ok, why = game.resolve_combat_damage(0, attacker_damage={0: {0: 1, 1: 0}})
    assert not ok and "all of its combat damage" in why
    ok, why = game.resolve_combat_damage(0, attacker_damage={0: {0: 1, 1: 2}})
    assert ok, why
    assert (striker.damage_marked, wall.damage_marked) == (1, 2)


@pytest.mark.cr("510.4", "510.1e")
def test_one_call_for_both_steps_checks_the_whole_announcement_first():
    """``resolve_all_combat_damage`` is one announcement used for two steps.
    An illegal division for an attacker that only strikes in the second must
    be refused before the first strikers have dealt anything — CR 510.1e
    checks an assignment whole."""
    game, (ogre,), (striker, wall), _ = _combat(
        [_creature("Plain Ogre", 3, 9)],
        [_wall("First Striker", power=1, text="First strike"), _wall("Wall B")],
    )

    ok, why = game.resolve_all_combat_damage(0, attacker_damage={0: {0: 1, 1: 0}})

    assert not ok and "all of its combat damage" in why
    assert not game.combat_first_strike_done, "the first strike was dealt anyway"
    assert _nothing_dealt(game, [ogre, striker, wall])


@pytest.mark.cr("510.4", "510.1c")
def test_the_second_step_is_assigned_over_the_board_the_first_strike_left():
    """A double striker kills one of its two blockers in the first step. The
    announcement was keyed by slot and said "two to the first, one to the
    second"; replayed, the survivor (now in the first slot) took two and a
    point vanished. The second step restates it: what still divides all of
    the damage among the creatures still blocking stands, and where it does
    not, the default among them does."""
    game, (fencer,), (pup, wall), _ = _combat(
        [_creature("Fencer", 3, 3, "Double strike")],
        [_wall("Pup", toughness=2), _wall("Wall B", toughness=9)],
    )

    ok, why = game.resolve_all_combat_damage(0, attacker_damage={0: {0: 2, 1: 1}})

    assert ok, why
    assert game.combat_damage_resolved
    assert [card.name for card in game.players[1].graveyard] == ["Pup"]
    assert wall.damage_marked == 1 + 3, "one in the first step, all three in the second"
    assert game.players[1].life == 20


@pytest.mark.cr("510.4", "510.1c")
def test_a_division_that_still_holds_is_what_the_second_step_deals():
    """The other half of the restatement: nothing left, nothing moved, so the
    caller's own division is dealt twice rather than replaced by a default."""
    game, _mine, (a, b), _ = _combat(
        [_creature("Fencer", 3, 3, "Double strike")],
        [_wall("Wall A"), _wall("Wall B")],
    )

    ok, why = game.resolve_all_combat_damage(0, attacker_damage={0: {0: 0, 1: 3}})

    assert ok, why
    assert (a.damage_marked, b.damage_marked) == (0, 6)


@pytest.mark.cr("510.4", "510.1c")
def test_a_second_step_with_nothing_to_announce_is_dealt_when_play_moves_on():
    """Resolved one pass at a time — which is how a person assigns — the
    first-strike step leaves the regular one owed. Where a division is still
    owed the game waits for it. Where none is (one of two blockers died:
    CR 510.1c, "it assigns all its combat damage to that creature") nothing
    asked, ``advance_combat_phase`` returned without moving, and the combat
    damage step could be neither assigned nor left."""
    game, (fencer,), (pup, wall), _ = _combat(
        [_creature("Fencer", 3, 3, "Double strike")],
        [_wall("Pup", toughness=2), _wall("Wall B", toughness=9)],
        interactive=(0,),
    )
    ok, why = game.resolve_combat_damage(0, attacker_damage={0: {0: 3, 1: 0}})
    assert ok, why
    assert game.combat_first_strike_done and not game.combat_damage_resolved
    assert not game._needs_manual_damage_assignment(), "one blocker is left"

    game.advance_combat_phase()

    assert game.combat_damage_resolved, "the second step was never dealt"
    assert game.current_step == "combat_damage", "and its own window follows it"
    assert wall.damage_marked == 3

    # The other shape: the first strike killed the attacker itself.
    game, _mine, (striker, wall), _ = _combat(
        [_creature("Plain Bear", 2, 2)],
        [_wall("First Striker", power=2, text="First strike"), _wall("Wall B")],
        interactive=(0,),
    )
    ok, why = game.resolve_combat_damage(0, attacker_damage={0: {0: 2, 1: 0}})
    assert ok, why
    assert [card.name for card in game.players[0].graveyard] == ["Plain Bear"]
    game.advance_combat_phase()
    assert game.combat_damage_resolved


@pytest.mark.cr("510.4", "510.1c")
def test_a_second_step_with_a_division_in_it_still_waits():
    """The control for the test above: advancing must not deal a step that
    somebody still has to divide."""
    game, _mine, (a, b), _ = _combat(
        [_creature("Fencer", 3, 3, "Double strike")],
        [_wall("Wall A"), _wall("Wall B")],
        interactive=(0,),
    )
    ok, why = game.resolve_combat_damage(0, attacker_damage={0: {0: 3, 1: 0}})
    assert ok, why

    game.advance_combat_phase()

    assert _stopped(game) and game.combat_first_strike_done
    assert (a.damage_marked, b.damage_marked) == (3, 0)


# ---------------------------------------------------------------------------
# Who assigns (CR 702.22j, and a printed substitution)
# ---------------------------------------------------------------------------


@pytest.mark.cr("510.1", "702.22j")
def test_the_engine_says_which_seat_assigns_each_attacker():
    """The answer the client is sent. It decided from one blocker's keyword
    line; the engine also counts a "bands with other" pair among the blockers
    and a permanent that says the defending player assigns."""
    plain = _creature("Plain Ogre", 3, 3)

    game, _m, _t, _ = _combat([plain], [_wall("Wall A"), _wall("Wall B")])
    assert game.combat_damage_assigner(0) == 0
    assert game.get_combat_state()["damage_assigned_by"] == {0: 0}

    game, _m, _t, _ = _combat([plain], [_wall("Bander", text="Banding"), _wall("Wall B")])
    assert game.get_combat_state()["damage_assigned_by"] == {0: 1}

    legends = [
        _mk_card("Wolf One", "Legendary Creature — Wolf", "Bands with other legendary creatures"),
        _mk_card("Wolf Two", "Legendary Creature — Wolf", ""),
    ]
    for card in legends:
        card.raw.update({"power": "1", "toughness": "5"})
    game, _m, _t, _ = _combat([plain], legends)
    assert game.get_combat_state()["damage_assigned_by"] == {0: 1}, (
        "a 'bands with other' pair blocking moves the assignment too"
    )

    formation = _mk_card("Probe Formation", "Enchantment", FORMATION)
    game, _m, _t, _ = _combat(
        [plain], [_wall("Wall A"), _wall("Wall B")], extra_defender=[formation]
    )
    assert game.get_combat_state()["damage_assigned_by"] == {0: 1}

    assert game.combat_damage_assigner(7) is None, "not an attacker"


@pytest.mark.cr("702.22j", "510.1c", "510.1e")
def test_the_defending_players_division_is_held_to_the_same_rule():
    """One check for either seat. The defending player's copy never asked
    about trample's lethal damage, so they could record a division the damage
    step then refused the *active* player for — with nothing either of them
    could do about it."""
    bander = _wall("Bander", toughness=4, text="Banding")
    game, (wurm,), (sentry, wall), _ = _combat(
        [_creature("Trampling Wurm", 6, 6, "Trample")], [bander, _wall("Wall B", toughness=1)]
    )

    ok, why = game.assign_banding_combat_damage(1, {0: {0: 2, 1: 1}})
    assert not ok and "trample requires lethal damage" in why
    ok, why = game.assign_banding_combat_damage(1, {0: {0: 4, 1: 1}})
    assert ok, why
    assert game.resolve_combat_damage(0)[0]
    assert (sentry.damage_marked, wall.damage_marked) == (4, 1)
    assert game.players[1].life == 19

    game, (ogre,), walls, _ = _combat(
        [_creature("Plain Ogre", 3, 3)], [_wall("Bander", text="Banding"), _wall("Wall B")]
    )
    ok, why = game.assign_banding_combat_damage(1, {0: {0: 1, 1: 0}})
    assert not ok and "all of its combat damage" in why
    ok, why = game.assign_banding_combat_damage(1, {0: {0: 1, 1: 0, 5: 2}})
    assert not ok
    assert game.defender_assignments_owed(1) == [0], "a refused division is not on record"


@pytest.mark.cr("702.22j", "510.1c")
def test_the_attacking_player_is_refused_what_the_defender_assigns_only_when_announced():
    """A defending player who has announced is whose division is dealt; the
    active player's entry for that attacker is not read."""
    game, _mine, (sentry, wall), _ = _combat(
        [_creature("Plain Ogre", 3, 3)], [_wall("Bander", text="Banding"), _wall("Wall B")]
    )
    assert game.assign_banding_combat_damage(1, {0: {0: 0, 1: 3}})[0]

    ok, why = game.resolve_combat_damage(0, attacker_damage={0: {0: 3, 1: 0}})

    assert ok, why
    assert (sentry.damage_marked, wall.damage_marked) == (0, 3)


# ---------------------------------------------------------------------------
# The defending player's "as though it weren't blocked"
# ---------------------------------------------------------------------------


@pytest.mark.cr("702.22j", "510.1b", "510.1c")
def test_one_banding_blocker_stops_the_step_for_an_interactive_defender():
    """The ruling's case exactly: a creature with banding blocks a Thorn
    Elemental. The defending player decides — and is a person, so the game
    stops and asks. It resolved as the step was entered, onto the blocker."""
    bander = _wall("Banding Sentry", power=1, toughness=6, text="Banding")
    game, (beast,), (sentry,), _ = _combat(
        [_creature("Slipping Beast", 5, 5, OFFER)], [bander], interactive=(1,)
    )

    assert _stopped(game), "the defender's choice was made for them"
    assert game.unblocked_assignment_chooser(0) == 1
    assert game.unblocked_assignments_to_ask() == [0]
    assert game.unblocked_assignments_to_ask(1) == [0]
    assert game.unblocked_assignments_to_ask(0) == [], "not the attacker's question"
    assert game.defender_assignments_owed(1) == [0]
    assert _nothing_dealt(game, [beast, sentry])

    game.advance_combat_phase()
    assert _stopped(game), "advancing ran past the question"


@pytest.mark.cr("702.22j", "510.1b")
def test_the_defending_player_may_take_the_offer_and_be_dealt_the_damage():
    """The answer that keeps the banding creature alive: all five to the
    defending player. Announced by the attacker's id, as the active player
    announces their own."""
    bander = _wall("Banding Sentry", power=1, toughness=4, text="Banding")
    game, (beast,), (sentry,), _ = _combat(
        [_creature("Slipping Beast", 5, 5, OFFER)], [bander], interactive=(1,)
    )

    ok, why = game.assign_banding_combat_damage(
        1, {}, as_though_unblocked=[beast.permanent_id]
    )
    assert ok, why
    assert game.unblocked_assignments_to_ask() == [], "answered"
    assert game.defender_assignments_owed(1) == []
    assert beast.metadata.get(DEFENDER_ASSIGNS_AS_UNBLOCKED)
    assert _nothing_dealt(game, [beast, sentry]), "an announcement deals nothing"

    ok, why = game.resolve_combat_damage(0)
    assert ok, why

    assert game.players[1].life == 15
    assert sentry.damage_marked == 0
    assert beast.damage_marked == 1, "the blocker still dealt its own"
    line = f"Slipping Beast assigns its combat damage {AS_THOUGH_UNBLOCKED_LOG}"
    assert game.log.count(line) == 1


@pytest.mark.cr("702.22j", "510.1c")
def test_the_defending_player_may_keep_it_on_the_blocker():
    bander = _wall("Banding Sentry", power=1, toughness=4, text="Banding")
    game, (beast,), (sentry,), _ = _combat(
        [_creature("Slipping Beast", 5, 5, OFFER)], [bander], interactive=(1,)
    )

    ok, why = game.assign_banding_combat_damage(1, {0: {0: 5}})
    assert ok, why
    assert game.unblocked_assignments_to_ask() == []
    assert game.resolve_combat_damage(0)[0]
    game.check_state_based_actions()

    assert game.players[1].life == 20
    assert [card.name for card in game.players[1].graveyard] == ["Banding Sentry"]


@pytest.mark.cr("702.22j", "510.1e")
def test_the_defending_players_answer_is_all_of_it_one_way_or_the_other():
    """"You can't split the damage assignment between them." — for whichever
    seat is assigning."""
    bander = _wall("Banding Sentry", power=1, toughness=4, text="Banding")
    game, (beast,), (sentry, wall), _ = _combat(
        [_creature("Slipping Beast", 5, 5, OFFER)], [bander, _wall("Wall B")],
        interactive=(1,),
    )
    assert game.defender_assignments_owed(1) == [0]

    ok, why = game.assign_banding_combat_damage(
        1, {0: {0: 2, 1: 0}}, as_though_unblocked=[beast.permanent_id]
    )
    assert not ok and "not some of each" in why
    ok, why = game.assign_banding_combat_damage(1, {0: {0: 2, 1: 0}})
    assert not ok and "all of its combat damage" in why
    assert game.defender_assignments_owed(1) == [0]
    assert DEFENDER_ASSIGNS_AS_UNBLOCKED not in beast.metadata

    # Zeroes beside the id say nothing against it.
    ok, why = game.assign_banding_combat_damage(
        1, {0: {0: 0, 1: 0}}, as_though_unblocked=[beast.permanent_id]
    )
    assert ok, why
    assert game.resolve_combat_damage(0)[0]
    assert game.players[1].life == 15
    assert (sentry.damage_marked, wall.damage_marked) == (0, 0)


@pytest.mark.cr("702.22j", "510.1e")
def test_what_the_defending_player_cannot_announce():
    """An id can be wrong four ways for a defender: not an attacker, not
    attacking them, a creature with no such sentence, and an offer that is the
    attacking player's own (no banding blocker in front of it)."""
    plain = _creature("Plain Ogre", 3, 3)
    bander = _wall("Banding Sentry", power=1, toughness=4, text="Banding")
    game, (ogre,), (sentry, wall), _ = _combat([plain], [bander, _wall("Wall B")])

    ok, why = game.assign_banding_combat_damage(1, {}, as_though_unblocked=[ogre.permanent_id])
    assert not ok and "can't assign its combat damage as though it weren't blocked" in why
    ok, why = game.assign_banding_combat_damage(1, {}, as_though_unblocked=[sentry.permanent_id])
    assert not ok and why == "that creature is not attacking"
    ok, why = game.assign_banding_combat_damage(0, {}, as_though_unblocked=[ogre.permanent_id])
    assert not ok and "only the defending player" in why

    game, (beast,), _walls, _ = _combat(
        [_creature("Slipping Beast", 5, 5, OFFER)], [_wall("Wall A"), _wall("Wall B")]
    )
    ok, why = game.assign_banding_combat_damage(1, {}, as_though_unblocked=[beast.permanent_id])
    assert not ok and "the attacking player assigns" in why
    assert DEFENDER_ASSIGNS_AS_UNBLOCKED not in beast.metadata


@pytest.mark.cr("702.22j", "510.1c")
def test_the_attacking_player_still_cannot_take_an_offer_that_is_the_defenders():
    bander = _wall("Banding Sentry", power=1, toughness=6, text="Banding")
    game, (beast,), (sentry,), _ = _combat(
        [_creature("Slipping Beast", 5, 5, OFFER)], [bander], interactive=(0, 1)
    )
    assert _stopped(game)

    ok, why = game.resolve_combat_damage(
        0, attacker_damage={}, as_though_unblocked=[beast.permanent_id]
    )

    assert not ok and "the defending player assigns" in why


@pytest.mark.cr("702.22j", "510.1c")
def test_a_defender_nobody_sits_in_keeps_the_damage_on_the_blockers():
    """The stated default for a seat that is not asked, unchanged: an AI or
    headless defender is not stopped for, and the damage stays where CR 510.1c
    puts it."""
    bander = _wall("Banding Sentry", power=1, toughness=6, text="Banding")
    game, (beast,), (sentry,), _ = _combat(
        [_creature("Slipping Beast", 5, 5, OFFER)], [bander], interactive=(0,)
    )

    assert game.combat_damage_resolved
    assert game.players[1].life == 20 and sentry.damage_marked == 5
    assert game.unblocked_assignments_to_ask() == []


@pytest.mark.cr("510.1", "510.1b")
def test_a_printed_substitution_gives_the_defender_the_same_choice():
    """Defensive Formation's sentence, on an invented enchantment: no banding
    anywhere, an ordinary blocker, and the defending player assigns. "Damage
    assignment choices from Trample and other things which allow alternative
    damage assignments for attacking creatures are all made by you."
    (2004-10-04.)"""
    formation = _mk_card("Probe Formation", "Enchantment", FORMATION)
    game, (beast,), (wall,), offset = _combat(
        [_creature("Slipping Beast", 5, 5, OFFER)], [_wall("Wall A", power=1)],
        interactive=(1,), extra_defender=[formation],
    )
    assert _stopped(game)
    assert game.unblocked_assignments_to_ask(1) == [0]

    ok, why = game.assign_banding_combat_damage(
        1, {}, as_though_unblocked=[beast.permanent_id]
    )
    assert ok, why
    assert game.resolve_combat_damage(0)[0]
    assert game.players[1].life == 15 and wall.damage_marked == 0

    game, (beast,), (wall,), offset = _combat(
        [_creature("Slipping Beast", 5, 5, OFFER)], [_wall("Wall A", power=1)],
        interactive=(1,), extra_defender=[formation],
    )
    ok, why = game.assign_banding_combat_damage(1, {0: {offset: 5}})
    assert ok, why
    assert game.resolve_combat_damage(0)[0]
    assert game.players[1].life == 20 and wall.damage_marked == 5


@pytest.mark.cr("510.4", "702.22j")
def test_the_defender_is_asked_again_for_a_second_combat_damage_step():
    """CR 510.4: a double striker has two combat damage steps and CR 510.1 is
    an announcement in each. The defending player's is held for one step — the
    step that deals the attacker's damage marks it unannounced — so a person
    is asked again, and may answer differently."""
    bander = _wall("Banding Sentry", power=0, toughness=9, text="Banding")
    game, (beast,), (sentry,), _ = _combat(
        [_creature("Slipping Fencer", 3, 3, f"Double strike\n{OFFER}")], [bander],
        interactive=(1,),
    )
    assert game.unblocked_assignments_to_ask(1) == [0]

    assert game.assign_banding_combat_damage(1, {}, as_though_unblocked=[beast.permanent_id])[0]
    assert beast.metadata.get(DEFENDER_ANNOUNCED_THIS_STEP)
    ok, why = game.resolve_combat_damage(0)
    assert ok, why
    assert game.combat_first_strike_done and not game.combat_damage_resolved
    assert (game.players[1].life, sentry.damage_marked) == (17, 0)

    assert DEFENDER_ANNOUNCED_THIS_STEP not in beast.metadata
    assert game.unblocked_assignments_to_ask(1) == [0], "not asked for the second step"
    assert game.assign_banding_combat_damage(1, {0: {0: 3}})[0]
    assert DEFENDER_ASSIGNS_AS_UNBLOCKED not in beast.metadata, "the new answer replaces the old"
    assert game.resolve_combat_damage(0)[0]

    assert game.combat_damage_resolved
    assert (game.players[1].life, sentry.damage_marked) == (17, 3)


@pytest.mark.cr("510.4", "702.22j")
def test_an_attacker_that_has_not_struck_yet_is_not_asked_about_twice():
    """The other attacker in a first-strike combat: its damage is assigned in
    the second step only, so the announcement made for it has not been used by
    the first and stands."""
    bander = _wall("Banding Sentry", power=1, toughness=9, text="Banding\nFirst strike")
    game, (ogre,), (sentry, wall), _ = _combat(
        [_creature("Plain Ogre", 3, 9)], [bander, _wall("Wall B")], interactive=(1,)
    )
    assert game.defender_assignments_owed(1) == [0]
    assert game.assign_banding_combat_damage(1, {0: {0: 0, 1: 3}})[0]

    assert game.resolve_combat_damage(0)[0]
    assert game.combat_first_strike_done and ogre.damage_marked == 1
    assert game.defender_assignments_owed(1) == [], "asked twice about one assignment"

    assert game.resolve_combat_damage(0)[0]
    assert (sentry.damage_marked, wall.damage_marked) == (0, 3)


@pytest.mark.cr("511.3", "702.22j")
def test_the_defenders_answer_ends_with_the_combat():
    """Both marks are about this combat. A turn may hold a second combat
    phase, and an answer left on the creature would send its damage past a
    blocker there on the strength of what was said about this one."""
    bander = _wall("Banding Sentry", power=1, toughness=9, text="Banding")
    game, (beast,), _walls, _ = _combat(
        [_creature("Slipping Beast", 5, 5, OFFER)], [bander], interactive=(1,)
    )
    assert game.assign_banding_combat_damage(1, {}, as_though_unblocked=[beast.permanent_id])[0]
    assert game.resolve_combat_damage(0)[0]
    beast.metadata[DEFENDER_ANNOUNCED_THIS_STEP] = True  # as if the step never cleared it

    game.end_combat()

    assert DEFENDER_ASSIGNS_AS_UNBLOCKED not in beast.metadata
    assert DEFENDER_ANNOUNCED_THIS_STEP not in beast.metadata
