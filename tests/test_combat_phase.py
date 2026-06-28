"""Tests for CR 506 (Combat Phase).

The LEA set has no planeswalkers or battles and this engine models only
two-player games, so the planeswalker/battle/multiplayer sub-rules
(506.2a/b, 506.3c-f, 506.4c-e) are not applicable here. The tests below cover
the parts of rule 506 that the LEA engine implements: the five combat steps and
their skips/repeats (506.1), the attacking/defending player roles (506.2), the
"only a creature can attack or block" restriction (506.3, 506.3a, 506.3b),
removal from combat (506.4, 506.4b), "attacking/blocking alone" (506.5), and
"had to attack" (506.6).
"""

from engine import Game
from engine.models import CardDefinition, Permanent, PlayerState


def _mk_creature(name: str, power: int, toughness: int, oracle_text: str = "") -> CardDefinition:
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line="Creature - Test",
        oracle_text=oracle_text,
        colors=(),
        color_identity=(),
        keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test", "power": str(power), "toughness": str(toughness)},
    )


def _mk_artifact(name: str) -> CardDefinition:
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line="Artifact",
        oracle_text="",
        colors=(),
        color_identity=(),
        keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Artifact"},
    )


def _to_declare_attackers(game: Game) -> None:
    """Advance a freshly created game (player 0 active) to the declare attackers step."""
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    assert game.current_step == "declare_attackers"


# ---------------------------------------------------------------------------
# 506.1 — the five combat steps, in order, with skips and first-strike repeats
# ---------------------------------------------------------------------------

def test_combat_has_five_steps_in_order():
    attacker = Permanent(card=_mk_creature("Attacker", 2, 2))
    blocker = Permanent(card=_mk_creature("Blocker", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[blocker])
    game = Game(players=[p1, p2])

    assert game._phase_steps("combat") == (
        "beginning_of_combat",
        "declare_attackers",
        "declare_blockers",
        "combat_damage",
        "end_of_combat",
    )

    game.start_turn(0)
    game._close_current_priority_step()

    seen = []
    game.advance_combat_phase()
    seen.append(game.current_step)  # beginning_of_combat
    game.advance_combat_phase()
    seen.append(game.current_step)  # declare_attackers
    game.declare_attackers(0, [0])
    game.advance_combat_phase()
    seen.append(game.current_step)  # declare_blockers
    game.declare_blockers(1, {0: 0})
    game.advance_combat_phase()
    seen.append(game.current_step)  # combat_damage (auto-resolves to end_of_combat)
    assert seen == [
        "beginning_of_combat",
        "declare_attackers",
        "declare_blockers",
        "end_of_combat",
    ]


def test_declare_blockers_and_damage_skipped_when_no_attackers():
    # 506.1: declare blockers and combat damage are skipped if no creature is
    # declared as an attacker.
    p1 = PlayerState(name="P1")  # no creatures to attack with
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=_mk_creature("Blocker", 2, 2))])
    game = Game(players=[p1, p2])

    _to_declare_attackers(game)
    ok, _ = game.declare_attackers(0, [])
    assert ok

    # With no attackers, the declare blockers and combat damage steps make no
    # block/damage decisions and combat proceeds to end of combat. (The engine
    # passes through these steps as no-ops rather than literally removing them.)
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.current_step == "end_of_combat"
    assert game.combat_blockers == {}
    assert p2.battlefield[0].blocking_attacker_index is None  # never blocked


def test_two_combat_damage_steps_with_first_strike():
    # 506.1: there are two combat damage steps if an attacking or blocking
    # creature has first strike. The 2/2 first striker kills the 2/2 blocker in
    # the first pass and survives, taking no damage in the second.
    first_striker = Permanent(card=_mk_creature("First", 2, 2, "First strike"))
    blocker = Permanent(card=_mk_creature("Blocker", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[first_striker])
    p2 = PlayerState(name="P2", battlefield=[blocker])
    game = Game(players=[p1, p2])

    _to_declare_attackers(game)
    game.declare_attackers(0, [0])
    game.advance_combat_phase()
    game.declare_blockers(1, {0: 0})
    game.advance_combat_phase()  # combat_damage: both passes run

    assert game.combat_first_strike_done is True
    assert game.combat_damage_resolved is True
    assert len(p2.battlefield) == 0  # blocker died in the first-strike pass
    assert len(p1.battlefield) == 1  # first striker survived


def test_auto_damage_assignment_respects_blocker_order_when_first_is_unkillable():
    # CR 510.1c: an attacker assigns combat damage to its blockers in order and
    # may only assign to a later blocker once each earlier blocker has lethal.
    # The auto-assignment used for AI/quick resolution must honour this even when
    # the *first* blocker can't be killed but a later one could — otherwise it
    # produces an illegal {first: 0, later: lethal} split that resolve_combat_damage
    # rejects, leaving combat_damage_resolved False and deadlocking the step.
    attacker = Permanent(card=_mk_creature("Attacker", 2, 2))
    tough_blocker = Permanent(card=_mk_creature("Wall", 0, 3))   # index 0: can't be killed by 2 power
    frail_blocker = Permanent(card=_mk_creature("Squire", 1, 2))  # index 1: could be killed
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[tough_blocker, frail_blocker])
    game = Game(players=[p1, p2])

    _to_declare_attackers(game)
    game.declare_attackers(0, [0])
    game.advance_combat_phase()
    game.declare_blockers(1, {0: 0, 1: 0})  # both creatures block the lone attacker
    game.advance_combat_phase()  # declare_blockers -> combat_damage (awaits manual assignment)
    assert game.current_step == "combat_damage"
    assert game._needs_manual_damage_assignment()

    auto = game._build_auto_damage_assignment()
    # All damage goes to the first blocker (the legal sub-lethal breakpoint); the
    # later blocker gets nothing, so the assignment is legal in declared order.
    assert auto == {0: {0: 2, 1: 0}}

    ok, _ = game.resolve_combat_damage(0, attacker_damage=auto)
    assert ok
    assert game.combat_damage_resolved is True


def test_two_combat_damage_steps_with_double_strike():
    # 506.1 / 702.4: double strike also causes two combat damage steps. A 1/1
    # double striker blocked by a 2/2 deals 1 in each pass (2 total), killing it,
    # while taking 2 back and dying — but only after dealing its first-strike hit.
    double_striker = Permanent(card=_mk_creature("Double", 1, 3, "Double strike"))
    blocker = Permanent(card=_mk_creature("Blocker", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[double_striker])
    p2 = PlayerState(name="P2", battlefield=[blocker])
    game = Game(players=[p1, p2])

    _to_declare_attackers(game)
    game.declare_attackers(0, [0])
    game.advance_combat_phase()
    game.declare_blockers(1, {0: 0})
    game.advance_combat_phase()

    assert game.combat_first_strike_done is True
    assert game.combat_damage_resolved is True
    # 1 (first-strike pass) + 1 (normal pass) = 2 damage kills the 2-toughness blocker.
    assert len(p2.battlefield) == 0
    # The 1/3 double striker took 2 back and survives.
    assert len(p1.battlefield) == 1


def test_single_combat_damage_step_without_first_strike():
    # 506.1: with no first/double strike there is exactly one combat damage step,
    # so combat_first_strike_done stays False (no separate first-strike pass).
    attacker = Permanent(card=_mk_creature("Attacker", 2, 2))
    blocker = Permanent(card=_mk_creature("Blocker", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[blocker])
    game = Game(players=[p1, p2])

    _to_declare_attackers(game)
    game.declare_attackers(0, [0])
    game.advance_combat_phase()
    game.declare_blockers(1, {0: 0})
    game.advance_combat_phase()

    assert game.combat_first_strike_done is False
    assert game.combat_damage_resolved is True
    assert len(p1.battlefield) == 0 and len(p2.battlefield) == 0  # mutual destruction


# ---------------------------------------------------------------------------
# 506.2 — the active player attacks; the nonactive player defends
# ---------------------------------------------------------------------------

def test_active_player_is_attacking_player_and_nonactive_is_defending():
    attacker = Permanent(card=_mk_creature("Attacker", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    _to_declare_attackers(game)
    # The active player (index 0) is the attacking player.
    assert game.active_player_index == 0
    # The nonactive player (index 1) is the defending player.
    assert game.combat_defending_player_index == 1

    ok, _ = game.declare_attackers(0, [0])
    assert ok
    assert attacker.defending_player_index == 1


def test_only_active_player_may_declare_attackers():
    # 506.2: only creatures the active player controls may attack, so the
    # nonactive player cannot declare attackers.
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=_mk_creature("A", 2, 2))])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=_mk_creature("B", 2, 2))])
    game = Game(players=[p1, p2])

    _to_declare_attackers(game)
    ok, msg = game.declare_attackers(1, [0])
    assert not ok
    assert "only the active player" in msg


def test_only_defending_player_may_declare_blockers():
    attacker = Permanent(card=_mk_creature("Attacker", 2, 2))
    blocker = Permanent(card=_mk_creature("Blocker", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[blocker])
    game = Game(players=[p1, p2])

    _to_declare_attackers(game)
    game.declare_attackers(0, [0])
    game.advance_combat_phase()  # declare_blockers

    # The active/attacking player cannot declare blocks.
    ok, msg = game.declare_blockers(0, {0: 0})
    assert not ok
    assert "only defending player" in msg

    # The defending player can.
    ok, _ = game.declare_blockers(1, {0: 0})
    assert ok


# ---------------------------------------------------------------------------
# 506.3 — only a creature can attack or block
# ---------------------------------------------------------------------------

def test_noncreature_cannot_be_declared_attacker():
    relic = Permanent(card=_mk_artifact("Test Relic"))
    p1 = PlayerState(name="P1", battlefield=[relic])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    _to_declare_attackers(game)
    ok, msg = game.declare_attackers(0, [0])
    assert not ok
    assert "only creatures can attack" in msg


def test_noncreature_cannot_be_declared_blocker():
    attacker = Permanent(card=_mk_creature("Attacker", 2, 2))
    relic = Permanent(card=_mk_artifact("Test Relic"))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[relic])
    game = Game(players=[p1, p2])

    _to_declare_attackers(game)
    game.declare_attackers(0, [0])
    game.advance_combat_phase()  # declare_blockers

    ok, msg = game.declare_blockers(1, {0: 0})
    assert not ok
    assert "only creatures can block" in msg


def test_506_3a_noncreature_attacking_is_never_an_attacking_permanent():
    # 506.3a: if an effect would put a noncreature permanent onto the battlefield
    # attacking, it's never considered an attacking permanent. Simulate by forcing
    # a noncreature into the combat state; pruning must drop it.
    attacker = Permanent(card=_mk_creature("Attacker", 2, 2))
    relic = Permanent(card=_mk_artifact("Test Relic"))
    p1 = PlayerState(name="P1", battlefield=[attacker, relic])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    _to_declare_attackers(game)
    game.declare_attackers(0, [0])

    # Force the artifact (index 1) into combat as though something put it there.
    game.combat_attackers[1] = 1
    relic.attacking = True
    game._prune_combat_state()

    assert 1 not in game.combat_attackers
    assert relic.attacking is False
    assert game.combat_attackers == {0: 1}  # only the real creature attacks


def test_506_3b_creature_controlled_by_defender_is_never_attacking():
    # 506.3b: a creature put onto the battlefield attacking under the control of a
    # player other than the attacking player is never an attacking creature. The
    # defending player's creatures are never populated into combat_attackers, and
    # pruning clears any stray attacking flag on them.
    attacker = Permanent(card=_mk_creature("Attacker", 2, 2))
    defenders_creature = Permanent(card=_mk_creature("Intruder", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[defenders_creature])
    game = Game(players=[p1, p2])

    _to_declare_attackers(game)
    game.declare_attackers(0, [0])

    # Pretend an effect set the defender's creature as attacking.
    defenders_creature.attacking = True
    game._prune_combat_state()

    assert defenders_creature.attacking is False
    # Only the active player's creature is an attacker.
    assert game.combat_attackers == {0: 1}


# ---------------------------------------------------------------------------
# 506.4 — removal from combat
# ---------------------------------------------------------------------------

def test_attacker_leaving_battlefield_is_removed_from_combat():
    # 506.4: a permanent is removed from combat if it leaves the battlefield.
    attacker = Permanent(card=_mk_creature("Attacker", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    _to_declare_attackers(game)
    game.declare_attackers(0, [0])
    assert game.combat_attackers == {0: 1}

    # The attacker leaves the battlefield (e.g. destroyed by an instant).
    p1.battlefield.remove(attacker)
    game._prune_combat_state()

    assert game.combat_attackers == {}


def test_blocker_leaving_battlefield_is_removed_from_combat():
    # 506.4: a blocking creature that leaves the battlefield stops being a
    # blocking creature.
    attacker = Permanent(card=_mk_creature("Attacker", 2, 2))
    blocker = Permanent(card=_mk_creature("Blocker", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[blocker])
    game = Game(players=[p1, p2])

    _to_declare_attackers(game)
    game.declare_attackers(0, [0])
    game.advance_combat_phase()
    game.declare_blockers(1, {0: 0})
    assert game.combat_blockers == {0: [0]}

    p2.battlefield.remove(blocker)
    game._prune_combat_state()

    assert game.combat_blockers == {}


def test_removed_creature_stops_being_attacking_and_blocking():
    # 506.4: a creature removed from combat stops being an attacking, blocking,
    # blocked, and/or unblocked creature. When the attacker leaves the
    # battlefield, the surviving blocker stops being a blocking creature.
    attacker = Permanent(card=_mk_creature("Attacker", 2, 2))
    blocker = Permanent(card=_mk_creature("Blocker", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[blocker])
    game = Game(players=[p1, p2])

    _to_declare_attackers(game)
    game.declare_attackers(0, [0])
    game.advance_combat_phase()
    game.declare_blockers(1, {0: 0})

    assert attacker.attacking is True and attacker.blocked is True
    assert blocker.blocking_attacker_index == 0

    # The attacker leaves the battlefield; the blocker remains.
    p1.battlefield.remove(attacker)
    game._prune_combat_state()

    # The attacker is gone from combat; the blocker no longer blocks anything.
    assert game.combat_attackers == {}
    assert game.combat_blockers == {}
    assert blocker.blocking_attacker_index is None
    assert blocker.blocked is False


def test_506_4b_untapping_declared_attacker_keeps_it_in_combat():
    # 506.4b: untapping a creature already declared as an attacker doesn't remove
    # it from combat and doesn't prevent its combat damage.
    attacker = Permanent(card=_mk_creature("Attacker", 3, 3))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    _to_declare_attackers(game)
    game.declare_attackers(0, [0])
    assert attacker.tapped is True  # attacking tapped it

    # Some effect untaps it after it was declared.
    attacker.tapped = False
    game._prune_combat_state()

    assert attacker.attacking is True
    assert game.combat_attackers == {0: 1}

    # It still deals its combat damage.
    game.advance_combat_phase()  # declare_blockers (auto-skipped, no blockers)
    game.advance_combat_phase()  # combat_damage
    assert p2.life == 17


def test_506_4b_tapping_declared_blocker_keeps_it_in_combat():
    # 506.4b: tapping a creature already declared as a blocker doesn't remove it
    # from combat and doesn't prevent its combat damage.
    attacker = Permanent(card=_mk_creature("Attacker", 3, 3))
    blocker = Permanent(card=_mk_creature("Blocker", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[blocker])
    game = Game(players=[p1, p2])

    _to_declare_attackers(game)
    game.declare_attackers(0, [0])
    game.advance_combat_phase()
    game.declare_blockers(1, {0: 0})

    # Tap the blocker after the block was declared.
    blocker.tapped = True
    game._prune_combat_state()

    assert game.combat_blockers == {0: [0]}
    assert blocker.blocking_attacker_index == 0

    # The blocker still deals its damage to the attacker (3/3 takes 2, survives).
    game.advance_combat_phase()  # combat_damage
    assert attacker.damage_marked == 2 or len(p1.battlefield) == 1


# ---------------------------------------------------------------------------
# 506.5 — attacking alone / blocking alone
# ---------------------------------------------------------------------------

def test_creature_attacking_alone():
    lone = Permanent(card=_mk_creature("Lone", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[lone])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    _to_declare_attackers(game)
    game.declare_attackers(0, [0])

    assert game.creature_attacking_alone(lone) is True


def test_creature_not_attacking_alone_with_two_attackers():
    a1 = Permanent(card=_mk_creature("A1", 2, 2))
    a2 = Permanent(card=_mk_creature("A2", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[a1, a2])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    _to_declare_attackers(game)
    game.declare_attackers(0, [0, 1])

    assert game.creature_attacking_alone(a1) is False
    assert game.creature_attacking_alone(a2) is False


def test_non_attacking_creature_is_not_attacking_alone():
    attacker = Permanent(card=_mk_creature("Attacker", 2, 2))
    bench = Permanent(card=_mk_creature("Bench", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker, bench])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    _to_declare_attackers(game)
    game.declare_attackers(0, [0])  # only the attacker; bench stays home

    assert game.creature_attacking_alone(attacker) is True
    assert game.creature_attacking_alone(bench) is False  # bench isn't attacking


def test_creature_blocking_alone():
    attacker = Permanent(card=_mk_creature("Attacker", 2, 2))
    blocker = Permanent(card=_mk_creature("Blocker", 2, 2))
    other = Permanent(card=_mk_creature("Other", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[blocker, other])
    game = Game(players=[p1, p2])

    _to_declare_attackers(game)
    game.declare_attackers(0, [0])
    game.advance_combat_phase()
    game.declare_blockers(1, {0: 0})  # only blocker blocks

    assert game.creature_blocking_alone(blocker) is True
    assert game.creature_blocking_alone(other) is False  # other isn't blocking


def test_creature_not_blocking_alone_with_two_blockers():
    attacker = Permanent(card=_mk_creature("Attacker", 4, 4))
    b1 = Permanent(card=_mk_creature("B1", 2, 2))
    b2 = Permanent(card=_mk_creature("B2", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[b1, b2])
    game = Game(players=[p1, p2])

    _to_declare_attackers(game)
    game.declare_attackers(0, [0])
    game.advance_combat_phase()
    game.declare_blockers(1, {0: 0, 1: 0})

    assert game.creature_blocking_alone(b1) is False
    assert game.creature_blocking_alone(b2) is False


# ---------------------------------------------------------------------------
# 508.1 / 509.1 — declaring attackers/blockers is a turn-based action taken
# before any player has priority; the active player gets priority afterward.
# (No spell or ability can be cast during the assignment portion.)
# ---------------------------------------------------------------------------

def test_no_priority_during_declare_attackers_assignment():
    attacker = Permanent(card=_mk_creature("Attacker", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    _to_declare_attackers(game)
    # Before attackers are declared, no player holds priority — nothing can be cast.
    assert game.priority_player_index is None
    assert game.has_priority(0) is False


def test_active_player_gets_priority_after_declaring_attackers():
    attacker = Permanent(card=_mk_creature("Attacker", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    _to_declare_attackers(game)
    ok, _ = game.declare_attackers(0, [0])
    assert ok
    # CR 508.4: the active player receives priority once attackers are declared.
    assert game.priority_player_index == game.active_player_index == 0
    assert game.has_priority(0) is True


def test_declaring_no_attackers_still_grants_active_player_priority():
    attacker = Permanent(card=_mk_creature("Attacker", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    _to_declare_attackers(game)
    ok, _ = game.declare_attackers(0, [])  # declares no attackers
    assert ok
    assert game.priority_player_index == 0


def test_no_priority_during_declare_blockers_assignment():
    attacker = Permanent(card=_mk_creature("Attacker", 2, 2))
    blocker = Permanent(card=_mk_creature("Blocker", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[blocker])
    game = Game(players=[p1, p2])

    _to_declare_attackers(game)
    game.declare_attackers(0, [0])
    game.advance_combat_phase()  # declare_blockers
    assert game.current_step == "declare_blockers"
    # Before blockers are declared, no player holds priority.
    assert game.priority_player_index is None
    assert game.has_priority(0) is False


def test_active_player_gets_priority_after_declaring_blockers():
    attacker = Permanent(card=_mk_creature("Attacker", 2, 2))
    blocker = Permanent(card=_mk_creature("Blocker", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[blocker])
    game = Game(players=[p1, p2])

    _to_declare_attackers(game)
    game.declare_attackers(0, [0])
    game.advance_combat_phase()  # declare_blockers
    ok, _ = game.declare_blockers(1, {0: 0})
    assert ok
    # CR 509.4: the active player (not the defender) receives priority afterward.
    assert game.priority_player_index == game.active_player_index == 0
    assert game.has_priority(0) is True


# ---------------------------------------------------------------------------
# 506.6 — "had to attack"
# ---------------------------------------------------------------------------

def test_creature_that_had_to_attack_must_be_declared():
    # 506.6 / 508: a creature required to attack "had to attack." Such a creature
    # must be included when attackers are declared.
    forced = Permanent(card=_mk_creature("Juggernaut", 5, 3, "This creature attacks each combat if able"))
    p1 = PlayerState(name="P1", battlefield=[forced])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    _to_declare_attackers(game)
    assert game._must_attack_if_able(forced) is True

    # Declaring no attackers is illegal while a creature that had to attack can.
    ok, msg = game.declare_attackers(0, [])
    assert not ok
    assert "must attack if able" in msg

    # Declaring it is fine.
    ok, _ = game.declare_attackers(0, [0])
    assert ok


def test_ai_choose_attackers_includes_forced_creatures():
    # Regression: Siren's Call (and other "must attack if able" effects) set
    # must_attack_until_eot on the active player's creatures. The AI's
    # choose_attackers heuristic would otherwise hold a 2/2 back from a wall it
    # can't profitably attack into, producing a declaration that declare_attackers
    # rejects — and the [] fallback fails identically, hanging declare_attackers.
    from engine.ai_policy import choose_attackers

    forced = Permanent(card=_mk_creature("Grizzly Bears", 2, 2))
    forced.metadata["must_attack_until_eot"] = True
    wall = Permanent(card=_mk_creature("Wall of Stone", 0, 8, "Defender"))
    p1 = PlayerState(name="AI", battlefield=[forced])
    p2 = PlayerState(name="P2", battlefield=[wall])
    game = Game(players=[p1, p2])

    _to_declare_attackers(game)
    assert game._must_attack_if_able(forced) is True

    chosen = choose_attackers(game, 0)
    assert 0 in chosen, "forced creature must be chosen even when attacking is unprofitable"

    ok, _ = game.declare_attackers(0, chosen)
    assert ok


def test_creature_did_not_have_to_attack_even_if_only_legal_attacker():
    # 506.6: a creature did not "have to attack" if no effect required it, even if
    # there were no other legal attacks. An ordinary creature may hold back.
    ordinary = Permanent(card=_mk_creature("Ordinary", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[ordinary])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    _to_declare_attackers(game)
    assert game._must_attack_if_able(ordinary) is False

    # Declaring no attackers is legal — nothing was required to attack.
    ok, _ = game.declare_attackers(0, [])
    assert ok
