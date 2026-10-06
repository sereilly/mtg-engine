"""CR 510.1 — "You may have this creature assign its combat damage as though
it weren't blocked."

One printed sentence (Lone Wolf, Thorn Elemental, Rhox, Pride of Lions) and
one granted copy of it (Garruk, Savage Herald's −7). It replaces CR 510.1c's
assignment to the creatures blocking with CR 510.1b's assignment to the player
or planeswalker being attacked — **at the option of whoever assigns that
creature's damage, and all of it one way or the other**:

    "When assigning combat damage, you choose whether you want to assign all
    damage to blocking creatures, or if you want to assign all of it to the
    player or planeswalker this creature is attacking. You can't split the
    damage assignment between them."
        — Thorn Elemental / Lone Wolf / Pride of Lions, rulings of 2018-04-27

    "If blocked by a creature with banding, the defending player decides
    whether or not the damage is assigned 'as though it weren't blocked'."
        — the same three cards, 2018-04-27

The engine always supported both answers. What it did not have was a way to be
*told* the first one — the offer was taken exactly when nothing was said — and
no point at which a person was asked: one blocker resolved on entering the
step with the offer taken for them, and two blockers stopped for a division
that had to add up to the attacker's power. So a human had one of the two
printed answers in each arrangement, and which one turned on the number of
blockers. These tests hold the rule; ``tests/ui`` holds the wire and the
dialog; ``tests/engine/test_unblocked_assignment_census.py`` holds the pool.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.combat_assignment import (AS_THOUGH_UNBLOCKED_LOG,
                                      MAY_ASSIGN_AS_UNBLOCKED,
                                      MUST_ASSIGN_AS_UNBLOCKED,
                                      may_assign_as_unblocked)
from engine.models import Permanent

from tests.helpers import _mk_card, _mk_creature_card, resolve_stack

OFFER = "You may have this creature assign its combat damage as though it weren't blocked."


def _offered(power: int = 5, toughness: int = 5, extra: str = "") -> object:
    """An invented creature printing the sentence — behaviour, not a name."""
    text = OFFER if not extra else f"{extra}\n{OFFER}"
    return _mk_creature_card("Slipping Beast", power, toughness, text)


def _wall(name: str = "Probe Wall", power: int = 1, toughness: int = 4):
    return _mk_creature_card(name, power, toughness)


def _combat(attacker_card, blocker_cards, *, interactive=(), walker=None,
            more_attackers=(), blocks=None):
    """Declare *attacker_card* (seat 0) into *blocker_cards* (seat 1) through
    the engine's own steps, and stop having **entered** combat damage.

    ``blocks`` maps a blocker's slot to the attacker slot it blocks (default:
    every blocker blocks attacker 0). ``walker`` puts a planeswalker on seat 1
    and aims attacker 0 at it.
    """
    me = PlayerState(name="Me")
    opp = PlayerState(name="Opp")
    game = Game(players=[me, opp])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    me.life = opp.life = 20

    def put(seat, card, **metadata):
        perm = Permanent(card=card)
        game._put_permanent_onto_battlefield(seat, perm, None)
        perm.metadata["summoning_sickness_turn"] = -99
        perm.metadata.update(metadata)
        return perm

    attackers = [put(0, attacker_card)] + [put(0, card) for card in more_attackers]
    blockers = [put(1, card) for card in blocker_cards]
    walker_perm = None
    if walker is not None:
        walker_perm = put(1, walker, loyalty_counters=9)

    game.active_player_index = 0
    for _ in range(4):
        game.advance_combat_phase()
        if game.current_step == "declare_attackers":
            break
    assert game.current_step == "declare_attackers"
    ok, why = game.declare_attackers(
        0, list(range(len(attackers))), defending_player_index=1,
        attacker_planeswalker_ids=(
            {0: walker_perm.permanent_id} if walker_perm is not None else None
        ),
    )
    assert ok, why
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers", game.current_step
    pairs = blocks if blocks is not None else {i: 0 for i in range(len(blockers))}
    ok, why = game.declare_blockers(1, pairs)
    assert ok, why
    game.advance_combat_phase()
    return game, attackers, blockers, walker_perm


def _stopped(game) -> bool:
    return game.current_step == "combat_damage" and not game.combat_damage_resolved


# ---------------------------------------------------------------------------
# The game stops and asks — for a person, with one blocker and with several
# ---------------------------------------------------------------------------


@pytest.mark.cr("510.1", "510.1c")
def test_one_blocker_stops_the_damage_step_for_an_interactive_attacker():
    """The defect's first half. A single block used to resolve as the step was
    entered, the offer taken on the attacker's behalf. CR 510.1 has the active
    player *announce* how each attacking creature assigns; nobody had."""
    game, (beast,), (wall,), _ = _combat(_offered(), [_wall()], interactive=(0,))

    assert _stopped(game), "the step resolved without asking"
    assert game.unblocked_assignments_to_ask() == [0]
    assert game.unblocked_assignment_chooser(0) == 0
    assert game._needs_manual_damage_assignment()
    assert (game.players[1].life, wall.damage_marked, beast.damage_marked) == (20, 0, 0)

    # Advancing again does not run past the question.
    game.advance_combat_phase()
    assert _stopped(game)


@pytest.mark.cr("510.1", "510.1c")
def test_several_blockers_stop_it_for_the_same_question():
    game, _attackers, _blockers, _ = _combat(
        _offered(), [_wall("Wall A"), _wall("Wall B")], interactive=(0,)
    )

    assert _stopped(game)
    assert game.unblocked_assignments_to_ask() == [0]


@pytest.mark.cr("510.1b", "510.1c")
def test_a_seat_nobody_sits_in_keeps_the_default_and_is_not_stopped():
    """The stated default for a non-interactive seat: the offer **taken**, as
    it has been since Garruk's grant was first read. An AI or headless combat
    must not stop at a prompt nobody will answer."""
    game, (beast,), (wall,), _ = _combat(_offered(), [_wall()], interactive=())

    assert game.combat_damage_resolved, "a headless single block must resolve"
    assert game.unblocked_assignments_to_ask() == []
    assert game.players[1].life == 15
    assert wall.damage_marked == 0
    assert beast.damage_marked == 1, "the blocker still dealt its own damage"


@pytest.mark.cr("510.1b", "510.1c")
def test_only_the_seat_that_owns_the_choice_being_interactive_stops_it():
    """A human *defender* facing an AI's Thorn Elemental is not the one who
    chooses (CR 510.1: the active player announces), so nothing waits on them
    and the attacker's default stands."""
    game, _a, (wall,), _ = _combat(_offered(), [_wall()], interactive=(1,))

    assert game.combat_damage_resolved
    assert game.players[1].life == 15 and wall.damage_marked == 0


@pytest.mark.cr("510.1c")
def test_an_ordinary_attacker_is_asked_nothing_new():
    """The control, and the promise to the paths beside this one: a creature
    without the sentence resolves a single block unasked exactly as before, and
    a double block stops for the old reason and no new one."""
    plain = _mk_creature_card("Plain Bear", 3, 3)

    game, _a, (wall,), _ = _combat(plain, [_wall()], interactive=(0,))
    assert game.combat_damage_resolved
    assert wall.damage_marked == 3 and game.players[1].life == 20

    game, _a, _b, _ = _combat(plain, [_wall("A"), _wall("B")], interactive=(0,))
    assert _stopped(game)
    assert game.unblocked_assignments_to_ask() == []
    assert game.unblocked_assignment_chooser(0) is None


# ---------------------------------------------------------------------------
# Both answers, both arrangements
# ---------------------------------------------------------------------------


@pytest.mark.cr("510.1b")
def test_one_blocker_the_offer_taken_goes_past_it():
    game, (beast,), (wall,), _ = _combat(_offered(), [_wall()], interactive=(0,))

    ok, why = game.resolve_combat_damage(
        0, attacker_damage={}, as_though_unblocked=[beast.permanent_id]
    )
    assert ok, why

    assert game.players[1].life == 15, "all five to the player"
    assert wall.damage_marked == 0
    assert beast.damage_marked == 1


@pytest.mark.cr("510.1c")
def test_one_blocker_the_offer_declined_kills_the_blocker():
    """The answer a human could not give with one blocker."""
    game, (beast,), (wall,), _ = _combat(_offered(), [_wall()], interactive=(0,))

    ok, why = game.resolve_combat_damage(0, attacker_damage={0: {0: 5}})
    assert ok, why
    game.check_state_based_actions()

    assert game.players[1].life == 20, "none of it reached the player"
    assert wall not in list(game.controlled_by(1)), "five into a 1/4"
    assert [card.name for card in game.players[1].graveyard] == ["Probe Wall"]


@pytest.mark.cr("510.1b")
def test_several_blockers_the_offer_taken_goes_past_all_of_them():
    """The answer a human could not give with two blockers: the dialog asked
    for the whole of the attacker's power among them."""
    game, (beast,), (a, b), _ = _combat(
        _offered(), [_wall("Wall A"), _wall("Wall B")], interactive=(0,)
    )

    ok, why = game.resolve_combat_damage(
        0, attacker_damage={}, as_though_unblocked=[beast.permanent_id]
    )
    assert ok, why

    assert game.players[1].life == 15
    assert (a.damage_marked, b.damage_marked) == (0, 0)
    assert beast.damage_marked == 2, "both blockers dealt theirs"


@pytest.mark.cr("510.1c")
def test_several_blockers_the_offer_declined_divides_as_the_controller_chooses():
    game, (beast,), (a, b), _ = _combat(
        _offered(), [_wall("Wall A"), _wall("Wall B")], interactive=(0,)
    )

    ok, why = game.resolve_combat_damage(0, attacker_damage={0: {0: 1, 1: 4}})
    assert ok, why

    assert game.players[1].life == 20
    assert (a.damage_marked, b.damage_marked) == (1, 4)


@pytest.mark.cr("510.1b")
def test_saying_nothing_is_still_the_offer_taken():
    """``attacker_damage=None`` is "the engine's default assignment", and for
    this creature the default has always been the offer. The explicit channel
    is an addition, not a change to what silence means."""
    game, (beast,), (wall,), _ = _combat(_offered(), [_wall()], interactive=(0,))

    ok, why = game.resolve_combat_damage(0)
    assert ok, why
    assert game.players[1].life == 15 and wall.damage_marked == 0


@pytest.mark.cr("510.1b")
def test_as_though_unblocked_reaches_the_planeswalker_it_attacks():
    """CR 510.1b names "the player, planeswalker, or battle it's attacking".
    "Assigning its damage as though it weren't blocked means the damage is
    assigned to the planeswalker, not to the defending player." (Outmaneuver
    ruling, 2008-04-01 — the same sentence without the "may".)"""
    walker_card = _mk_card("Probe Walker", "Legendary Planeswalker — Probe")
    game, (beast,), (wall,), walker = _combat(
        _offered(), [_wall()], interactive=(0,), walker=walker_card
    )
    assert _stopped(game)

    ok, why = game.resolve_combat_damage(
        0, attacker_damage={}, as_though_unblocked=[beast.permanent_id]
    )
    assert ok, why

    assert walker.metadata["loyalty_counters"] == 4, "five off nine"
    assert game.players[1].life == 20, "and none to its controller"
    assert wall.damage_marked == 0


@pytest.mark.cr("510.1b", "510.1e")
def test_the_log_says_when_damage_went_past_the_blockers_and_only_then():
    """A blocked creature's damage landing on a player is the one thing in
    the step a table cannot read off the board, so the engine says it — once
    the assignment is accepted, and not for an assignment it refused or for
    the offer declined. (The client's damage animation reads this line; see
    ``tests/ui/test_unblocked_assignment_ui_api.py``.)"""
    line = f"Slipping Beast assigns its combat damage {AS_THOUGH_UNBLOCKED_LOG}"

    game, (beast,), _walls, _ = _combat(_offered(), [_wall()], interactive=(0,))
    ok, _why = game.resolve_combat_damage(
        0, attacker_damage={0: {0: 2}}, as_though_unblocked=[beast.permanent_id]
    )
    assert not ok and line not in game.log, "a refused assignment announced itself"
    ok, why = game.resolve_combat_damage(
        0, attacker_damage={}, as_though_unblocked=[beast.permanent_id]
    )
    assert ok, why
    assert game.log.count(line) == 1
    assert game.log.index(line) < game.log.index("Resolved combat damage")

    game, _attackers, _walls, _ = _combat(_offered(), [_wall()], interactive=(0,))
    assert game.resolve_combat_damage(0, attacker_damage={0: {0: 5}})[0]
    assert line not in game.log, "the offer declined is an ordinary assignment"


# ---------------------------------------------------------------------------
# All of it one way or the other — what the engine refuses
# ---------------------------------------------------------------------------


@pytest.mark.cr("510.1e")
def test_some_of_each_is_refused_and_nothing_is_dealt():
    """"You can't split the damage assignment between them." (2018-04-27.)
    CR 510.1e: an illegal assignment returns the game to the moment before it
    was announced — so the step is still waiting, and still unresolved."""
    game, (beast,), (wall,), _ = _combat(_offered(), [_wall()], interactive=(0,))

    ok, why = game.resolve_combat_damage(
        0, attacker_damage={0: {0: 2}}, as_though_unblocked=[beast.permanent_id]
    )

    assert not ok
    assert "not some of each" in why
    assert _stopped(game)
    assert (game.players[1].life, wall.damage_marked, beast.damage_marked) == (20, 0, 0)


@pytest.mark.cr("510.1a", "510.1e")
def test_declining_with_less_than_all_of_it_is_refused():
    """The offer declined is CR 510.1c in full. Two of five to the blocker and
    three nowhere is a third answer the card does not print."""
    game, (beast,), (wall,), _ = _combat(_offered(), [_wall()], interactive=(0,))

    for partial in ({0: {0: 2}}, {0: {0: 0}}, {0: {}}):
        ok, why = game.resolve_combat_damage(0, attacker_damage=partial)
        assert not ok, partial
        assert "all of its combat damage" in why
        assert _stopped(game)
    assert (game.players[1].life, wall.damage_marked) == (20, 0)


@pytest.mark.cr("510.1c", "510.1e")
def test_a_creature_without_the_sentence_cannot_announce_it():
    """An ordinary blocked creature sent past its blockers would be trample
    with none of trample's lethal damage."""
    plain = _mk_creature_card("Plain Bear", 3, 3)
    game, (bear,), _blockers, _ = _combat(
        plain, [_wall("A"), _wall("B")], interactive=(0,)
    )

    ok, why = game.resolve_combat_damage(
        0, attacker_damage={}, as_though_unblocked=[bear.permanent_id]
    )

    assert not ok
    assert "can't assign its combat damage as though it weren't blocked" in why
    assert _stopped(game) and game.players[1].life == 20


@pytest.mark.cr("510.1b", "510.1e")
def test_an_unblocked_or_absent_creature_cannot_announce_it():
    """Two more things an id can be wrong about: an attacker nobody blocked
    (it has no blockers to go past), and a permanent that is not attacking."""
    game, (beast, runner), (wall,), _ = _combat(
        _offered(), [_wall()], interactive=(0,),
        more_attackers=[_offered(2, 2)],
    )

    ok, why = game.resolve_combat_damage(
        0, attacker_damage={}, as_though_unblocked=[runner.permanent_id]
    )
    assert not ok and "can't assign" in why

    ok, why = game.resolve_combat_damage(
        0, attacker_damage={}, as_though_unblocked=[wall.permanent_id]
    )
    assert not ok and why == "that creature is not attacking"
    assert _stopped(game)


@pytest.mark.cr("702.19b", "510.1c")
def test_a_trampler_that_declines_still_tramples():
    """The under-assignment refusal is not trample's business: a trampler that
    declines assigns lethal to its blocker and the rest goes over, by its own
    rule. Trample's behaviour is exactly what it was."""
    game, (beast,), (wall,), _ = _combat(
        _offered(6, 6, extra="Trample"), [_wall()], interactive=(0,)
    )
    assert _stopped(game)

    ok, why = game.resolve_combat_damage(0, attacker_damage={0: {0: 4}})
    assert ok, why

    assert wall.damage_marked == 4
    assert game.players[1].life == 18, "two trampled over"


# ---------------------------------------------------------------------------
# The granted form is the same offer
# ---------------------------------------------------------------------------


@pytest.mark.cr("510.1b", "510.1c")
def test_the_granted_sentence_asks_and_answers_like_the_printed_one(catalog_by_name):
    """Garruk, Savage Herald's −7, activated for real: "Until end of turn,
    creatures you control gain 'You may have this creature assign its combat
    damage as though it weren't blocked.'" A creature with no such line of its
    own is then asked the same question and may give either answer."""
    walker_card = catalog_by_name["Garruk, Savage Herald"]
    plain = _mk_creature_card("Plain Bear", 3, 3)

    def granted_combat(blockers):
        me = PlayerState(name="Me")
        opp = PlayerState(name="Opp")
        game = Game(players=[me, opp])
        game.enforce_mana_costs = False
        game.interactive_seats = {0}
        me.life = opp.life = 20
        garruk = Permanent(card=walker_card)
        bear = Permanent(card=plain)
        for seat, perm in ((0, bear), (0, garruk)):
            game._put_permanent_onto_battlefield(seat, perm, None)
            perm.metadata["summoning_sickness_turn"] = -99
        # Entering set its printed loyalty; the ultimate costs seven.
        garruk.metadata["loyalty_counters"] = 7
        walls = []
        for card in blockers:
            perm = Permanent(card=card)
            game._put_permanent_onto_battlefield(1, perm, None)
            walls.append(perm)
        game.active_player_index = 0
        result = game.activate_permanent_ability(
            0, "Garruk, Savage Herald", ability_index=2
        )
        assert result.supported, result.details
        resolve_stack(game)
        assert bear.metadata.get(MAY_ASSIGN_AS_UNBLOCKED)
        assert may_assign_as_unblocked(bear)
        for _ in range(4):
            game.advance_combat_phase()
            if game.current_step == "declare_attackers":
                break
        assert game.declare_attackers(0, [0], defending_player_index=1)[0]
        game.advance_combat_phase()
        assert game.declare_blockers(1, {i: 0 for i in range(len(walls))})[0]
        game.advance_combat_phase()
        return game, bear, walls

    for blockers in ([_wall()], [_wall("A"), _wall("B")]):
        game, bear, walls = granted_combat(blockers)
        assert _stopped(game) and game.unblocked_assignments_to_ask() == [0]
        ok, why = game.resolve_combat_damage(
            0, attacker_damage={}, as_though_unblocked=[bear.permanent_id]
        )
        assert ok, why
        assert game.players[1].life == 17
        assert all(wall.damage_marked == 0 for wall in walls)

    game, bear, (wall,) = granted_combat([_wall()])
    ok, why = game.resolve_combat_damage(0, attacker_damage={0: {0: 3}})
    assert ok, why
    assert game.players[1].life == 20 and wall.damage_marked == 3


@pytest.mark.cr("514.2")
def test_the_grant_ends_with_the_turn_and_the_question_with_it():
    """The granted half is a mark the cleanup step sweeps (CR 514.2: "until
    end of turn" effects end), so a creature that had only the grant is offered
    nothing afterwards; the printed half is no mark and survives the sweep."""
    me = PlayerState(name="Me")
    game = Game(players=[me, PlayerState(name="Opp")])
    game.enforce_mana_costs = False
    granted = Permanent(card=_mk_creature_card("Plain Bear", 3, 3))
    printed = Permanent(card=_offered())
    marked = Permanent(card=_mk_creature_card("Marked Bear", 3, 3))
    for perm in (granted, printed, marked):
        game._put_permanent_onto_battlefield(0, perm, None)
    granted.metadata[MAY_ASSIGN_AS_UNBLOCKED] = True
    marked.metadata[MUST_ASSIGN_AS_UNBLOCKED] = True
    assert may_assign_as_unblocked(granted) and may_assign_as_unblocked(printed)

    game.resolve_cleanup_step(0)

    assert not may_assign_as_unblocked(granted)
    assert MUST_ASSIGN_AS_UNBLOCKED not in marked.metadata
    assert may_assign_as_unblocked(printed)


# ---------------------------------------------------------------------------
# Whose choice it is
# ---------------------------------------------------------------------------


@pytest.mark.cr("702.22j", "510.1c")
def test_a_banding_blocker_makes_it_the_defending_players_choice():
    """"If blocked by a creature with banding, the defending player decides
    whether or not the damage is assigned 'as though it weren't blocked'."
    (2018-04-27.) CR 702.22j hands the *assignment* to the defending player,
    and the offer is a way of assigning.

    The engine took the offer here on the attacker's say-so. A defender who is
    not asked keeps the damage on the blockers, so the attacker is no longer
    stopped for a choice that is not theirs, and cannot announce it."""
    bander = _mk_creature_card("Banding Sentry", 1, 6, "Banding")
    game, (beast,), (sentry,), _ = _combat(_offered(), [bander], interactive=(0,))

    assert game.combat_damage_resolved, "the attacker has nothing to answer"
    assert game.players[1].life == 20, "the offer was not taken for the defender"
    assert sentry.damage_marked == 5

    game, (beast,), (sentry, wall), _ = _combat(
        _offered(), [bander, _wall()], interactive=(0,)
    )
    assert _stopped(game), "two blockers still owe a division"
    assert game.unblocked_assignment_chooser(0) == 1
    assert game.unblocked_assignments_to_ask() == []
    ok, why = game.resolve_combat_damage(
        0, attacker_damage={}, as_though_unblocked=[beast.permanent_id]
    )
    assert not ok and "the defending player assigns" in why


@pytest.mark.cr("702.22j")
def test_the_defenders_banding_division_is_what_is_dealt():
    """What the old reading cost a defender: they divided five damage among a
    band of blockers and were then dealt all five themselves, the division
    discarded. Their announcement stands now."""
    bander = _mk_creature_card("Banding Sentry", 1, 6, "Banding")
    game, (beast,), (sentry, wall), _ = _combat(
        _offered(), [bander, _wall()], interactive=()
    )
    assert _stopped(game)

    ok, why = game.assign_banding_combat_damage(1, {0: {0: 5, 1: 0}})
    assert ok, why
    ok, why = game.resolve_all_combat_damage(
        0, attacker_damage=game._build_auto_damage_assignment()
    )
    assert ok, why

    assert game.players[1].life == 20
    assert (sentry.damage_marked, wall.damage_marked) == (5, 0)


# ---------------------------------------------------------------------------
# Blocked, with nothing left blocking it
# ---------------------------------------------------------------------------


@pytest.mark.cr("509.1h", "510.1b")
def test_a_blocked_creature_whose_blocker_left_may_still_go_past():
    """CR 509.1h: "A creature remains blocked even if all the creatures
    blocking it are removed from combat." CR 510.1c would then have it assign
    nothing — unless it may assign as though it weren't blocked, which is what
    the sentence is for. Both readers asked for a live blocker and the
    creature dealt no damage at all."""
    game, (beast,), (wall,), _ = _combat(_offered(), [_wall()], interactive=(0,))
    assert _stopped(game)
    game.remove_from_battlefield(wall)
    game._prune_combat_state()
    assert beast.blocked and game._attacker_all_blockers(0) == []

    assert game.unblocked_assignment_chooser(0) == 0, "still its controller's offer"
    assert game.unblocked_assignments_to_ask() == [], (
        "but the other answer is 'assign nothing', which nobody is stopped for"
    )
    ok, why = game.resolve_combat_damage(0)
    assert ok, why
    assert game.players[1].life == 15


@pytest.mark.cr("509.1h", "510.1b")
def test_the_mandatory_twin_also_survives_its_blocker_leaving():
    """Outmaneuver's mark, no "may": "Creatures damage the defending player or
    planeswalker even if the blocking creatures are no longer there at that
    time." (Outmaneuver ruling, 2008-04-01.) And with the blocker still there
    it is not a question — whatever is announced, the damage goes past."""
    plain = _mk_creature_card("Plain Bear", 3, 3)
    game, (bear,), (a, b), _ = _combat(plain, [_wall("A"), _wall("B")])
    bear.metadata[MUST_ASSIGN_AS_UNBLOCKED] = True
    assert game.unblocked_assignment_chooser(0) is None, "nothing to decide"
    for wall in (a, b):
        game.remove_from_battlefield(wall)
    game._prune_combat_state()

    ok, why = game.resolve_combat_damage(0, attacker_damage={})
    assert ok, why
    assert game.players[1].life == 17

    game, (bear,), (wall, _other), _ = _combat(plain, [_wall("A"), _wall("B")])
    bear.metadata[MUST_ASSIGN_AS_UNBLOCKED] = True
    ok, why = game.resolve_combat_damage(0, attacker_damage={0: {0: 3, 1: 0}})
    assert ok, why
    assert game.players[1].life == 17 and wall.damage_marked == 0
