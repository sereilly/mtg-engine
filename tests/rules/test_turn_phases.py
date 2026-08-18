import pytest

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


@pytest.mark.cr("500.10")
def test_additional_step_after_phase_creates_single_step_phase():
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    ok = game.add_additional_step_after_phase("combat", "upkeep", controller_index=0, only_on_controllers_turn=False)

    assert ok
    inserted_phase = game.next_unskipped_phase_after("combat")
    assert inserted_phase is not None
    assert game._phase_steps(inserted_phase) == ("upkeep",)


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
