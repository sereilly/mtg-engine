import pytest

from engine import Game
from engine.mixins._constants import _PHASE_STEPS, _TURN_PHASES
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


@pytest.mark.cr("500.1", "505.1")
def test_start_turn_runs_beginning_phase_and_enters_precombat_main():
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.start_turn(0)

    assert game.current_turn_phase == "precombat_main"
    assert game.current_step == "precombat_main"
    assert game.current_phase == "main"


@pytest.mark.cr("500.1", "506.1")
def test_advance_combat_moves_to_postcombat_main():
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    assert game.current_turn_phase == "combat"
    assert game.current_step == "beginning_of_combat"

    game.advance_combat_phase()
    assert game.current_step == "declare_attackers"

    ok, _ = game.declare_attackers(0, [])
    assert ok

    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"

    ok, _ = game.declare_blockers(1, {})
    assert ok

    game.advance_combat_phase()
    assert game.current_step == "end_of_combat"

    game.advance_combat_phase()
    assert game.current_turn_phase == "postcombat_main"
    assert game.current_step == "postcombat_main"
    assert game.current_phase == "main"


@pytest.mark.cr("500.7")
def test_extra_turn_queue_is_lifo():
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.active_player_index = 0

    game.add_extra_turn(0)
    game.add_extra_turn(1)

    assert game.start_next_turn() == 1
    assert game.start_next_turn() == 0


@pytest.mark.cr("500.7")
def test_extra_turn_for_opponent_is_inserted_not_substituted():
    # 500.7: an extra turn is *inserted* after the current turn; the normal
    # rotation resumes afterward. P0 (active) gives P1 an extra turn, so P1
    # takes the extra turn AND then their normal turn before P0 acts again.
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.active_player_index = 0

    game.add_extra_turn(1)

    assert game.start_next_turn() == 1  # inserted extra turn
    assert game.current_turn_is_extra
    assert game.start_next_turn() == 1  # P1's normal turn (rotation resumes)
    assert not game.current_turn_is_extra
    assert game.start_next_turn() == 0  # back to P0


@pytest.mark.cr("500.7")
def test_extra_turn_does_not_disturb_normal_rotation():
    # P0 takes an extra turn, then the rotation continues to P1, not back to P0.
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.active_player_index = 0

    game.add_extra_turn(0)

    assert game.start_next_turn() == 0  # extra turn
    assert game.start_next_turn() == 1  # normal rotation resumes
    assert game.start_next_turn() == 0


@pytest.mark.cr("614.10")
def test_skip_turn_is_applied():
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.active_player_index = 0

    game.skip_next_turn(1)
    assert game.start_next_turn() == 0


# ---------------------------------------------------------------------------
# The turn's phase plan (CR 500.1's order, CR 500.8's extras)
#
# These replaced `test_additional_step_after_phase_creates_single_step_phase`,
# which asserted that `add_extra_phase` returned True. It did, and nothing in
# the engine ever entered the phase it recorded: `next_unskipped_phase_after`
# had no caller outside that test, and all three turn drivers named their own
# successor. A test of a recording API is blind to that by construction, so
# what is asserted here is the *sequence a turn actually takes*.
# ---------------------------------------------------------------------------


def _phase_plan_game():
    """A game standing where a real turn stands after its untap step begins."""
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.begin_turn_bookkeeping(0)
    game._set_phase_and_step("beginning", "untap")
    return game


@pytest.mark.cr("500.1")
def test_the_plan_a_turn_starts_with_is_exactly_the_five_phases():
    """The loop's equivalence proof, stated as an invariant.

    With nothing added, the plan is CR 500.1's five phases in order, so every
    `next_unskipped_phase_after` answer is the successor the hard-coded chains
    used to compute. A turn that departs from this list departs from the rules.
    """
    game = _phase_plan_game()

    assert list(_TURN_PHASES) == [
        "beginning", "precombat_main", "combat", "postcombat_main", "ending",
    ]
    assert game.turn_phases_remaining == [
        "precombat_main", "combat", "postcombat_main", "ending",
    ]
    for phase, expected in zip(_TURN_PHASES, list(_TURN_PHASES[1:]) + [None]):
        assert game.next_unskipped_phase_after(phase) == expected


@pytest.mark.cr("500.1")
def test_every_phase_a_plan_can_hold_has_an_entry_point():
    """The completeness assertion the plan needs.

    `turn_phases_remaining` is a hand-maintained list of phase names, and
    `enter_turn_phase` is a hand-maintained dispatch over them. A phase in one
    and not the other is a phase recorded, chosen, and then silently not
    entered - which is precisely what the extra-phase machinery did before it
    was wired up, so the guard has to name every entry rather than the ones
    somebody remembered.
    """
    for phase in _TURN_PHASES:
        assert phase in _PHASE_STEPS, f"{phase} has no steps"
        game = _phase_plan_game()
        game.begin_turn_bookkeeping(0)
        if phase == "beginning":
            # Deliberately not enterable: a turn opens with it, no phase hands
            # over to it, and `enter_turn_phase` says so out loud rather than
            # silently doing nothing.
            with pytest.raises(ValueError):
                game.enter_turn_phase(phase)
            continue
        game.enter_turn_phase(phase)
        assert game.current_turn_phase == phase, phase
        assert game.current_step in _PHASE_STEPS[phase], (phase, game.current_step)


@pytest.mark.cr("500.8")
def test_an_extra_phase_is_taken_directly_after_the_one_it_names():
    game = _phase_plan_game()
    game._enter_main_phase(precombat=True)

    assert game.add_extra_phase(after_phase="precombat_main", phase_name="combat")

    assert game.turn_phases_remaining == [
        "combat", "combat", "postcombat_main", "ending",
    ]
    assert game.next_unskipped_phase_after("precombat_main") == "combat"


@pytest.mark.cr("500.8")
def test_the_most_recently_created_extra_phase_occurs_first():
    """CR 500.8's last sentence, which is why `add_extra_phase` inserts."""
    game = _phase_plan_game()
    game._enter_main_phase(precombat=False)

    game.add_extra_phase(after_phase="postcombat_main", phase_name="postcombat_main")
    game.add_extra_phase(after_phase="postcombat_main", phase_name="combat")

    assert game.turn_phases_remaining == ["combat", "postcombat_main", "ending"]


@pytest.mark.cr("500.8")
def test_an_extra_phase_naming_a_phase_this_turn_has_taken_adds_nothing():
    game = _phase_plan_game()
    game._enter_main_phase(precombat=False)

    assert not game.add_extra_phase(after_phase="precombat_main", phase_name="combat")
    assert game.turn_phases_remaining == ["ending"]


@pytest.mark.cr("500.10a")
def test_an_extra_phase_is_not_added_on_another_players_turn():
    game = _phase_plan_game()
    game._enter_main_phase(precombat=True)

    assert not game.add_extra_phase(
        after_phase="precombat_main", phase_name="combat",
        controller_index=1, only_on_controllers_turn=True,
    )
    assert game.turn_phases_remaining == ["combat", "postcombat_main", "ending"]


@pytest.mark.cr("500.1", "500.8")
def test_an_out_of_band_phase_entry_re_derives_the_plan():
    """A test (or CR 724.1) jumping straight into a phase gets CR 500.1's order.

    The plan is only ever ahead of the game by construction, so an entry it did
    not predict means nobody planned this turn - and the honest answer is the
    fixed order, which is exactly what the engine did before a plan existed.
    """
    game = _phase_plan_game()
    game._enter_main_phase(precombat=True)
    game.add_extra_phase(after_phase="precombat_main", phase_name="combat")

    game._set_phase_and_step("ending", "end")

    assert game.turn_phases_remaining == []
    assert game.next_unskipped_phase_after("ending") is None


@pytest.mark.cr("500.1", "500.2")
def test_an_ordinary_turn_takes_the_same_steps_in_the_same_order():
    """The equivalence evidence for the turn-advance loop, as a recorded run.

    Every step of an ordinary turn, in order, driven through the real drivers -
    ``start_turn`` for the beginning phase, ``advance_combat_phase`` for combat,
    the end and cleanup steps for the ending phase. This sequence was captured
    from the engine *before* the phase sequence moved into
    ``turn_phases_remaining`` and is byte-identical after, which is the claim
    that the loop went in behind the existing behaviour: with nothing added, the
    plan is CR 500.1's order and the loop returns what each driver used to name.
    """
    attacker = Permanent(card=_mk_creature("Attacker", 2, 2))
    attacker.metadata["summoning_sickness_turn"] = -99
    game = Game(players=[
        PlayerState(name="P1", battlefield=[attacker]),
        PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False

    seen = []

    def note():
        entry = (game.current_turn_phase, game.current_step)
        if not seen or seen[-1] != entry:
            seen.append(entry)

    game.start_turn(0)
    note()
    for _ in range(40):
        phase, step = game.current_turn_phase, game.current_step
        if phase in ("precombat_main", "postcombat_main"):
            game._close_current_priority_step()
            game.enter_next_turn_phase(phase)
        elif phase == "combat":
            if step == "declare_attackers" and not game.combat_attackers_locked:
                game.declare_attackers(0, [0], 1)
            game.advance_combat_phase()
        elif phase == "ending":
            if step != "end":
                break
            game.close_end_step()
            game.resolve_cleanup_step(0)
        else:
            break
        note()
        if (game.current_turn_phase, game.current_step) == (phase, step):
            break

    assert seen == [
        ("precombat_main", "precombat_main"),
        ("combat", "beginning_of_combat"),
        ("combat", "declare_attackers"),
        ("combat", "declare_blockers"),
        ("combat", "end_of_combat"),
        ("postcombat_main", "postcombat_main"),
        ("ending", "end"),
        ("ending", "cleanup"),
    ]
    assert game.turn_phases_remaining == []


@pytest.mark.cr("505.1a", "500.8")
def test_an_additional_main_phase_is_a_postcombat_one(set_pool):
    """CR 505.1a names this exact card's shape: "only the first main phase of
    the turn is a precombat main phase ... It is also true of a turn in which an
    effect has caused an additional combat phase and an additional main phase to
    be created."

    So the phase Relentless Assault creates must not fire "at the beginning of
    your first main phase" a second time. Observed rather than asserted about
    the spelling: a Shrine drains once for the turn's own first main phase and
    not again for the created one.
    """
    shrine = Permanent(card=set_pool("M21")["Sanctum of Stone Fangs"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[shrine],
                    hand=[set_pool("VIS")["Relentless Assault"]]),
        PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game.begin_turn_bookkeeping(0)
    game._set_phase_and_step("beginning", "untap")

    game.enter_next_turn_phase("beginning")
    game._settle()
    drained_once = (game.players[0].life, game.players[1].life)
    assert drained_once != (20, 20), "the Shrine's first-main trigger did not fire"

    assert game.cast_from_hand(0, "Relentless Assault").supported, game.log
    game._resolve_priority_window()
    assert game.turn_phases_remaining[:2] == ["combat", "postcombat_main"]

    game.enter_turn_phase("postcombat_main")
    game._settle()

    assert game.current_turn_phase == "postcombat_main"
    assert (game.players[0].life, game.players[1].life) == drained_once


@pytest.mark.cr("500.11")
def test_a_skipped_phase_is_proceeded_past():
    game = _phase_plan_game()
    game._enter_main_phase(precombat=True)
    game.skip_phase_counts["combat"] = 1

    assert game.next_unskipped_phase_after("precombat_main") == "postcombat_main"
    assert game.turn_phases_remaining == ["postcombat_main", "ending"]


@pytest.mark.cr("510.1", "510.2")
def test_combat_declare_and_damage_resolution():
    attacker = Permanent(card=_mk_creature("Attacker", 3, 3))
    blocker = Permanent(card=_mk_creature("Blocker", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[blocker], life=20)
    game = Game(players=[p1, p2])

    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers

    ok, _ = game.declare_attackers(0, [0])
    assert ok

    game.advance_combat_phase()  # declare_blockers
    ok, _ = game.declare_blockers(1, {0: 0})
    assert ok

    game.advance_combat_phase()  # combat_damage
    assert len(p2.battlefield) == 0
    assert len(p1.battlefield) == 1


@pytest.mark.cr("702.7b")
def test_first_strike_combat_damage_two_passes():
    first_striker = Permanent(card=_mk_creature("First", 2, 2, "First strike"))
    blocker = Permanent(card=_mk_creature("Blocker", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[first_striker])
    p2 = PlayerState(name="P2", battlefield=[blocker], life=20)
    game = Game(players=[p1, p2])

    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    game.declare_attackers(0, [0])
    game.advance_combat_phase()
    game.declare_blockers(1, {0: 0})
    game.advance_combat_phase()

    assert game.combat_first_strike_done is True
    assert len(p2.battlefield) == 0

    assert game.combat_damage_resolved is True
    assert len(p1.battlefield) == 1


@pytest.mark.cr("702.19b")
def test_trample_overflow_hits_defender():
    trampler = Permanent(card=_mk_creature("Trampler", 5, 5, "Trample"))
    blocker = Permanent(card=_mk_creature("Blocker", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[trampler])
    p2 = PlayerState(name="P2", battlefield=[blocker], life=20)
    game = Game(players=[p1, p2])

    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    game.declare_attackers(0, [0])
    game.advance_combat_phase()
    game.declare_blockers(1, {0: 0})
    game.advance_combat_phase()

    assert p2.life == 17


@pytest.mark.cr("508.1")
def test_declare_attackers_requires_confirmation_before_phase_advance():
    attacker = Permanent(card=_mk_creature("Attacker", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    assert game.current_step == "declare_attackers"

    game.advance_combat_phase()
    assert game.current_step == "declare_attackers"

    ok, _ = game.declare_attackers(0, [0])
    assert ok
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"




@pytest.mark.cr("508.8")
def test_declare_attackers_auto_skips_when_no_legal_attackers_exist():
    noncreature = CardDefinition(
        name="Test Relic",
        mana_cost="",
        cmc=0.0,
        type_line="Artifact",
        oracle_text="",
        colors=(),
        color_identity=(),
        keywords=(),
        produced_mana=(),
        raw={"name": "Test Relic", "type_line": "Artifact"},
    )
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=noncreature)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.current_step == "declare_attackers"
    assert game.combat_attackers_locked is False

    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"

    game.advance_combat_phase()
    assert game.current_step == "end_of_combat"
    assert game.combat_attackers_locked is True
    assert any("has no valid attackers; declare attackers step skipped" in entry for entry in game.log)
    assert any("has no valid blockers; declare blockers step skipped" in entry for entry in game.log)


@pytest.mark.cr("509.1")
def test_declare_blockers_requires_confirmation_before_phase_advance():
    attacker = Permanent(card=_mk_creature("Attacker", 2, 2))
    blocker = Permanent(card=_mk_creature("Blocker", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[blocker])
    game = Game(players=[p1, p2])

    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    game.declare_attackers(0, [0])
    game.advance_combat_phase()  # declare_blockers
    assert game.current_step == "declare_blockers"

    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"

    ok, _ = game.declare_blockers(1, {0: 0})
    assert ok
    game.advance_combat_phase()
    assert game.current_step == "end_of_combat"


@pytest.mark.cr("509.1a")
def test_declare_blockers_auto_advances_when_no_legal_blocks_exist():
    attacker = Permanent(card=_mk_creature("Attacker", 3, 3))
    tapped_blocker = Permanent(card=_mk_creature("Tired Blocker", 2, 2), tapped=True)
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[tapped_blocker])
    game = Game(players=[p1, p2])

    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    ok, _ = game.declare_attackers(0, [0])
    assert ok

    game.advance_combat_phase()  # declare_blockers
    assert game.current_step == "declare_blockers"
    assert game.combat_blockers_locked is False

    game.advance_combat_phase()
    assert game.current_step == "end_of_combat"
    assert game.combat_blockers_locked is True
    assert any("has no valid blockers; declare blockers step skipped" in entry for entry in game.log)


@pytest.mark.cr("508.1", "509.1")
def test_combat_step_advancement_logs_attacker_and_blocker_counts():
    attacker = Permanent(card=_mk_creature("Attacker", 2, 2))
    blocker = Permanent(card=_mk_creature("Blocker", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[blocker])
    game = Game(players=[p1, p2])

    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()

    ok, _ = game.declare_attackers(0, [0])
    assert ok
    game.advance_combat_phase()
    assert any("Declare attackers step complete: 1 attacker(s) declared" in entry for entry in game.log)

    ok, _ = game.declare_blockers(1, {0: 0})
    assert ok
    game.advance_combat_phase()
    assert any("Declare blockers step complete: 1 blocker(s) declared" in entry for entry in game.log)


# --- CR 724.1: ending the turn (round 110) ----------------------------------


def _ending_board(pool):
    """A mid-combat board with an opponent's spell waiting under the one that
    ends the turn."""
    from engine.game_types import StackItem

    p1 = PlayerState(name="P1", hand=[pool["Discontinuity"]],
                     library=[pool["Mountain"]] * 4)
    p2 = PlayerState(name="P2", library=[pool["Mountain"]] * 4)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    attacker = Permanent(card=pool["Alpine Watchdog"])
    game._put_permanent_onto_battlefield(0, attacker, None)
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    game.combat_attackers = {0: 1}
    game.stack.append(StackItem(
        card=pool["Shock"], caster_index=1, target_player_index=0,
        target_permanent_index=None, x_value=None,
    ))
    return game, p1, p2, attacker


@pytest.mark.cr("724.1b")
def test_ending_the_turn_exiles_the_rest_of_the_stack(set_pool):
    """Exiled, not countered and not resolved: the waiting Shock never deals
    its damage and its card goes to exile rather than to a graveyard."""
    game, p1, p2, _ = _ending_board(set_pool("M21"))

    game.cast_from_hand(0, "Discontinuity")
    game._settle()

    assert game.stack == []
    assert p1.life == 20
    assert [c.name for c in p2.exile] == ["Shock"]
    assert p2.graveyard == []


@pytest.mark.cr("724.1b")
def test_the_spell_that_ends_the_turn_exiles_itself(set_pool):
    """"…including the object that's resolving." The resolving item is popped
    before its handler runs, so it is not in the list the process exiles — and
    binning it to the graveyard is the reading that leaves it recastable."""
    game, p1, _, _ = _ending_board(set_pool("M21"))

    game.cast_from_hand(0, "Discontinuity")
    game._settle()

    assert [c.name for c in p1.exile] == ["Discontinuity"]
    assert p1.graveyard == []


@pytest.mark.cr("724.1d")
def test_ending_the_turn_removes_everything_from_combat(set_pool):
    game, _, _, _ = _ending_board(set_pool("M21"))

    game.cast_from_hand(0, "Discontinuity")
    game._settle()

    assert game.combat_attackers == {}
    assert game.combat_blockers == {}


@pytest.mark.cr("724.1d", "514.2")
def test_ending_the_turn_skips_to_cleanup_without_clearing_damage(set_pool):
    """The game skips straight to the cleanup step — so the position is the end
    of the end step, and the next advance resolves cleanup. Marked damage is
    *not* cleared here: CR 514.2 does that in the cleanup step this is heading
    for, and doing it twice would wipe damage dealt during the process."""
    game, _, _, attacker = _ending_board(set_pool("M21"))
    attacker.metadata["damage_marked"] = 1

    game.cast_from_hand(0, "Discontinuity")
    game._settle()

    assert (game.current_turn_phase, game.current_step) == ("ending", "end")
    assert attacker.metadata["damage_marked"] == 1


@pytest.mark.cr("724.1e")
def test_ending_the_turn_skips_end_step_triggers(set_pool):
    """"At the beginning of the end step" abilities don't trigger, because the
    end step is skipped. Furious Rise would otherwise exile a card and grant a
    permission — both observable, which is why it is the witness here."""
    pool = set_pool("M21")
    p1 = PlayerState(
        name="P1", hand=[pool["Discontinuity"]],
        battlefield=[Permanent(card=pool["Furious Rise"]),
                     Permanent(card=pool["Baneslayer Angel"])],
        library=[pool["Concordia Pegasus"], pool["Mountain"]],
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._set_phase_and_step("postcombat_main", "postcombat_main")

    game.cast_from_hand(0, "Discontinuity")
    game._settle()

    assert [c.name for c in p1.exile] == ["Discontinuity"]
    assert game.cast_permissions == []


@pytest.mark.cr("724.1c")
def test_ending_the_turn_leaves_no_player_with_priority(set_pool):
    """No player gets priority during the process — so the window is cleared
    before state-based actions are checked, not after."""
    game, _, _, _ = _ending_board(set_pool("M21"))

    game.cast_from_hand(0, "Discontinuity")
    game._settle()

    assert not any(game.has_priority(seat) for seat in range(len(game.players)))
