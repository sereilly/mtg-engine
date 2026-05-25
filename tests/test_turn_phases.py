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


def test_start_turn_runs_beginning_phase_and_enters_precombat_main():
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.start_turn(0)

    assert game.current_turn_phase == "precombat_main"
    assert game.current_step == "precombat_main"
    assert game.current_phase == "main"


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


def test_extra_turn_queue_is_lifo():
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.active_player_index = 0

    game.add_extra_turn(0)
    game.add_extra_turn(1)

    assert game.start_next_turn() == 1
    assert game.start_next_turn() == 0


def test_skip_turn_is_applied():
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.active_player_index = 0

    game.skip_next_turn(1)
    assert game.start_next_turn() == 0


def test_additional_step_after_phase_creates_single_step_phase():
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    ok = game.add_additional_step_after_phase("combat", "upkeep", controller_index=0, only_on_controllers_turn=False)

    assert ok
    inserted_phase = game.next_unskipped_phase_after("combat")
    assert inserted_phase is not None
    assert game._phase_steps(inserted_phase) == ("upkeep",)


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
