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

    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"

    game.advance_combat_phase()
    assert game.current_step == "combat_damage"

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
    ok, _ = game.resolve_combat_damage(0, {0: {0: 3}})
    assert ok
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

    ok, _ = game.resolve_combat_damage(0, {0: {0: 2}})
    assert ok
    assert game.combat_first_strike_done is True
    assert len(p2.battlefield) == 0

    ok, _ = game.resolve_combat_damage(0, {0: {0: 0}})
    assert ok
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

    ok, _ = game.resolve_combat_damage(0, {0: {0: 2}})
    assert ok
    assert p2.life == 17
