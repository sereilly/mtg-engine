"""Tests for the per-step turn-structure rules (CR 500–514).

Covers the individual steps of the turn that the engine implements as phase
mixins in ``engine/phases/``: the beginning phase and its untap/upkeep/draw
steps (501–504), the main phase (505), the beginning-of-combat and
end-of-combat steps (507, 511), and the ending phase with its end and cleanup
steps (512–514), plus the general step/phase rules they exercise (500.3,
500.5, 500.6).

Phase-level combat structure (506) lives in ``test_combat_phase.py``; declare
attackers/blockers and combat damage (508–510) in their own files; extra
turns/phases/steps (500.7–500.11) in ``test_turn_phases.py``.

Not covered here because the engine doesn't implement the behavior:
- 502.1/502.2 (phasing, day/night — mechanics outside the Alpha-era pool),
- 503.2 ("cast only after upkeep" spells),
- 505.3/505.4/505.5 (Archenemy schemes, Sagas, Attractions),
- 507.1 (a single pre-chosen defending player; the engine uses per-attacker
  defender choices, CR 802),
- 513.2 (permanents entering after the end step began waiting a full turn),
- 103.8a (first-turn draw skip: ``start_turn`` always runs the draw step).
"""

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


def _mk_land(name: str = "Test Forest") -> CardDefinition:
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line="Basic Land — Forest",
        oracle_text="",
        colors=(),
        color_identity=(),
        keywords=(),
        produced_mana=("G",),
        raw={"name": name, "type_line": "Basic Land — Forest"},
    )


def _mk_enchantment(name: str, oracle_text: str) -> CardDefinition:
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line="Enchantment",
        oracle_text=oracle_text,
        colors=(),
        color_identity=(),
        keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Enchantment"},
    )


# ---------------------------------------------------------------------------
# 501 — Beginning Phase
# ---------------------------------------------------------------------------


@pytest.mark.cr("501.1")
def test_beginning_phase_consists_of_untap_upkeep_and_draw_steps():
    """The beginning phase has exactly three steps, in order: untap, upkeep,
    draw (501.1)."""
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])

    assert game._phase_steps("beginning") == ("untap", "upkeep", "draw")


# ---------------------------------------------------------------------------
# 502 — Untap Step
# ---------------------------------------------------------------------------


@pytest.mark.cr("502.3")
def test_untap_step_untaps_only_the_active_players_permanents():
    """The active player untaps the permanents they control (502.3); the
    non-active player's permanents stay tapped."""
    own_creature = Permanent(card=_mk_creature("Own Creature", 2, 2), tapped=True)
    own_land = Permanent(card=_mk_land("Own Land"), tapped=True)
    foe_creature = Permanent(card=_mk_creature("Foe Creature", 2, 2), tapped=True)
    p1 = PlayerState(name="P1", battlefield=[own_creature, own_land])
    p2 = PlayerState(name="P2", battlefield=[foe_creature])
    game = Game(players=[p1, p2])
    game.begin_turn_bookkeeping(0)

    untapped = game.resolve_untap_step(0)

    assert untapped == 2
    assert not own_creature.tapped
    assert not own_land.tapped
    assert foe_creature.tapped  # not the active player's permanent


@pytest.mark.cr("502.3")
def test_untap_step_effects_can_keep_a_permanent_from_untapping():
    """Normally all of a player's permanents untap, but effects can keep one
    from untapping (502.3): a permanent whose own text says it doesn't untap
    during its controller's untap step stays tapped."""
    stuck = Permanent(
        card=_mk_creature(
            "Stuck", 2, 2, "This creature doesn't untap during your untap step."
        ),
        tapped=True,
    )
    normal = Permanent(card=_mk_creature("Normal", 2, 2), tapped=True)
    p1 = PlayerState(name="P1", battlefield=[stuck, normal])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.begin_turn_bookkeeping(0)

    game.resolve_untap_step(0)

    assert stuck.tapped
    assert not normal.tapped


@pytest.mark.cr("502.4", "500.3")
def test_no_player_receives_priority_during_the_untap_step():
    """No player receives priority during the untap step (502.4); it is a step
    with no priority that ends once its turn-based actions complete (500.3)."""
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=_mk_creature("C", 2, 2), tapped=True)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.begin_turn_bookkeeping(0)
    game.clear_priority_window()

    assert game._receives_priority("untap") is False

    game.resolve_untap_step(0)

    # The step completed its actions without ever opening a priority window.
    assert game.priority_player_index is None
    assert game.stack == []


# ---------------------------------------------------------------------------
# 503 — Upkeep Step
# ---------------------------------------------------------------------------


@pytest.mark.cr("503.1")
def test_upkeep_step_has_no_turn_based_action_and_gives_active_player_priority():
    """The upkeep step has no turn-based actions; once it begins, the active
    player gets priority (503.1)."""
    p1 = PlayerState(name="P1", life=20, hand=[], library=[_mk_land()])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    game.begin_turn_bookkeeping(0)
    game.resolve_untap_step(0)

    game.resolve_upkeep(0, defer_priority=True)

    assert game.current_step == "upkeep"
    assert game.has_priority(0)
    # No turn-based action: nothing was drawn, no life changed, nothing moved.
    assert len(p1.hand) == 0
    assert len(p1.library) == 1
    assert p1.life == 20


@pytest.mark.cr("500.6", "503.1")
def test_upkeep_trigger_goes_on_the_stack_and_resolves_through_priority():
    """An ability that triggers at the beginning of the upkeep step is put on
    the stack when the step begins (500.6) and resolves through the upkeep
    priority window (503.1)."""
    pain = _mk_enchantment(
        "Pain Source", "At the beginning of each upkeep, Pain Source deals 1 damage to you."
    )
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=pain)], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    game.begin_turn_bookkeeping(0)
    game.resolve_untap_step(0)

    game.resolve_upkeep(0, defer_priority=True)

    # The trigger is held on the stack, unresolved, while players hold priority.
    assert len(game.stack) == 1
    assert p1.life == 20
    assert game.has_priority(0)

    assert game.pass_priority(0) == "passed"
    assert game.pass_priority(1) == "resolved_top"

    assert len(game.stack) == 0
    assert p1.life == 19


# ---------------------------------------------------------------------------
# 504 — Draw Step
# ---------------------------------------------------------------------------


@pytest.mark.cr("504.1")
def test_draw_step_active_player_draws_a_card_without_using_the_stack():
    """First, the active player draws a card as a turn-based action that
    doesn't use the stack (504.1)."""
    p1 = PlayerState(name="P1", library=[_mk_land("L1"), _mk_land("L2")])
    p2 = PlayerState(name="P2", library=[_mk_land("L3")])
    game = Game(players=[p1, p2])
    game.begin_turn_bookkeeping(0)
    game.resolve_untap_step(0)
    game.resolve_upkeep(0)

    drawn = game.resolve_draw_step(0, defer_priority=True)

    assert drawn == 1
    assert len(p1.hand) == 1
    assert len(p1.library) == 1
    assert game.stack == []  # the draw never went on the stack
    assert len(p2.hand) == 0  # only the active player draws


@pytest.mark.cr("504.2")
def test_draw_step_gives_active_player_priority_after_the_draw():
    """Second, the active player gets priority (504.2)."""
    p1 = PlayerState(name="P1", library=[_mk_land()])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.begin_turn_bookkeeping(0)
    game.resolve_untap_step(0)
    game.resolve_upkeep(0)

    game.resolve_draw_step(0, defer_priority=True)

    assert game.current_step == "draw"
    assert game.has_priority(0)


# ---------------------------------------------------------------------------
# 505 — Main Phase
# ---------------------------------------------------------------------------


@pytest.mark.cr("505.2")
def test_main_phase_has_no_steps():
    """The main phase has no steps (505.2): each main phase is a single
    undivided unit."""
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])

    assert game._phase_steps("precombat_main") == ("precombat_main",)
    assert game._phase_steps("postcombat_main") == ("postcombat_main",)


@pytest.mark.cr("505.6")
def test_active_player_gets_priority_when_main_phase_begins():
    """The active player gets priority when the main phase begins (505.6)."""
    p1 = PlayerState(name="P1", library=[_mk_land()])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.start_turn(0)

    assert game.current_phase == "main"
    assert game.has_priority(0)
    assert not game.has_priority(1)


@pytest.mark.cr("505.6b")
def test_active_player_may_play_only_one_land_per_turn():
    """The active player may play one land during their main phase; a second
    land play the same turn is illegal absent an effect allowing it (505.6b)."""
    p1 = PlayerState(name="P1", hand=[_mk_land(), _mk_land()])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = True
    game.start_turn(0)

    first = game.cast_from_hand(0, "Test Forest")
    assert first.supported
    assert len(p1.battlefield) == 1

    second = game.cast_from_hand(0, "Test Forest")
    assert not second.supported
    assert "already played a land this turn" in second.details
    assert len(p1.battlefield) == 1


# ---------------------------------------------------------------------------
# 507 — Beginning of Combat Step
# ---------------------------------------------------------------------------


@pytest.mark.cr("507.2")
def test_beginning_of_combat_step_gives_active_player_priority():
    """The active player gets priority during the beginning of combat step
    (507.2)."""
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=_mk_creature("Attacker", 2, 2))])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()

    game.advance_combat_phase()

    assert game.current_turn_phase == "combat"
    assert game.current_step == "beginning_of_combat"
    assert game.has_priority(0)


# ---------------------------------------------------------------------------
# 511 — End of Combat Step
# ---------------------------------------------------------------------------


def _advance_to_end_of_combat(game: Game) -> None:
    """Walk a fresh game (player 0 active) through combat with no attackers
    declared, stopping at the end of combat step."""
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    ok, _ = game.declare_attackers(0, [])
    assert ok
    game.advance_combat_phase()  # declare_blockers
    ok, _ = game.declare_blockers(1, {})
    assert ok
    game.advance_combat_phase()  # end_of_combat
    assert game.current_step == "end_of_combat"


@pytest.mark.cr("511.1")
def test_end_of_combat_step_gives_active_player_priority():
    """The end of combat step has no turn-based actions; once it begins, the
    active player gets priority (511.1)."""
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    _advance_to_end_of_combat(game)

    assert game.has_priority(0)


@pytest.mark.cr("511.2")
def test_until_end_of_combat_effects_expire_at_end_of_combat(cards):
    """Effects that last "until end of combat" expire at the end of the combat
    phase (511.2). Jade Statue's animation ends when combat does — before the
    turn is over."""
    statue = Permanent(card=cards["Jade Statue"])
    p1 = PlayerState(name="P1", battlefield=[statue])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    assert game.current_step == "beginning_of_combat"

    result = game.activate_permanent_ability(0, "Jade Statue")
    assert result.supported
    assert statue.is_creature
    assert statue.effective_power == 3
    assert statue.effective_toughness == 6

    game.end_combat()

    # The animation expired with the combat phase, not at end of turn.
    assert not statue.is_creature
    assert game.current_turn_phase == "combat"  # still the same turn


@pytest.mark.cr("511.3")
def test_creatures_are_removed_from_combat_when_end_of_combat_step_ends():
    """As soon as the end of combat step ends, all creatures are removed from
    combat, and the postcombat main phase begins (511.3)."""
    attacker = Permanent(card=_mk_creature("Attacker", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    ok, _ = game.declare_attackers(0, [0])
    assert ok
    game.advance_combat_phase()  # declare_blockers
    game.advance_combat_phase()  # auto-skips blocks (none legal); damage auto-resolves
    assert game.current_step == "end_of_combat"
    assert p2.life == 18  # unblocked attacker connected

    game.advance_combat_phase()  # ends the end of combat step

    assert not attacker.attacking
    assert attacker.defending_player_index is None
    assert game.combat_attackers == {}
    assert game.current_turn_phase == "postcombat_main"


# ---------------------------------------------------------------------------
# 512 — Ending Phase
# ---------------------------------------------------------------------------


@pytest.mark.cr("512.1")
def test_ending_phase_consists_of_end_and_cleanup_steps():
    """The ending phase consists of two steps: end and cleanup (512.1)."""
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])

    assert game._phase_steps("ending") == ("end", "cleanup")


# ---------------------------------------------------------------------------
# 513 — End Step
# ---------------------------------------------------------------------------


@pytest.mark.cr("513.1")
def test_end_step_has_no_turn_based_action_and_gives_active_player_priority():
    """The end step has no turn-based actions; once it begins, the active
    player gets priority (513.1)."""
    p1 = PlayerState(name="P1", hand=[_mk_land()], library=[_mk_land()], life=20)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.begin_turn_bookkeeping(0)

    game.resolve_end_step(0)

    assert game.current_turn_phase == "ending"
    assert game.current_step == "end"
    assert game.has_priority(0)
    # No turn-based action happened: no draw, no discard, no life change.
    assert len(p1.hand) == 1
    assert len(p1.library) == 1
    assert p1.life == 20


# ---------------------------------------------------------------------------
# 514 — Cleanup Step
# ---------------------------------------------------------------------------


@pytest.mark.cr("514.1")
def test_cleanup_discards_down_to_maximum_hand_size():
    """If the active player's hand exceeds their maximum hand size (normally
    seven), they discard down to it during cleanup (514.1)."""
    p1 = PlayerState(name="P1", hand=[_mk_land(f"L{i}") for i in range(9)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.begin_turn_bookkeeping(0)

    completed = game.resolve_cleanup_step(0)

    assert completed
    assert len(p1.hand) == 7
    assert len(p1.graveyard) == 2


@pytest.mark.cr("514.1")
def test_cleanup_discard_honors_the_players_chosen_cards():
    """The discarding player chooses which cards bring their hand down to
    maximum hand size (514.1)."""
    hand = [_mk_land(f"L{i}") for i in range(8)]
    p1 = PlayerState(name="P1", hand=list(hand))
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.begin_turn_bookkeeping(0)

    game.resolve_cleanup_step(0, discard_hand_indices=[3])

    assert len(p1.hand) == 7
    assert [c.name for c in p1.graveyard] == ["L3"]
    assert all(c.name != "L3" for c in p1.hand)


@pytest.mark.cr("514.1")
def test_cleanup_discards_nothing_at_or_below_maximum_hand_size():
    """A player whose hand is at or below maximum hand size discards nothing
    (514.1)."""
    p1 = PlayerState(name="P1", hand=[_mk_land(f"L{i}") for i in range(7)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.begin_turn_bookkeeping(0)

    game.resolve_cleanup_step(0)

    assert len(p1.hand) == 7
    assert len(p1.graveyard) == 0


@pytest.mark.cr("514.2")
def test_cleanup_removes_marked_damage_and_ends_until_end_of_turn_effects():
    """During cleanup, all damage marked on permanents is removed and "until
    end of turn" effects end simultaneously (514.2)."""
    bruiser = Permanent(card=_mk_creature("Bruiser", 2, 4))
    bruiser.damage_marked = 3
    bruiser.power_bonus += 2
    bruiser.metadata["temporary_power_bonus_until_eot"] = 2
    p1 = PlayerState(name="P1", battlefield=[bruiser])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.begin_turn_bookkeeping(0)
    assert bruiser.effective_power == 4

    game.resolve_cleanup_step(0)

    assert bruiser.damage_marked == 0
    assert bruiser.effective_power == 2  # the until-end-of-turn buff ended


@pytest.mark.cr("514.3", "500.3")
def test_no_player_receives_priority_during_a_normal_cleanup_step():
    """Normally no player receives priority during the cleanup step (514.3);
    like the untap step it ends when its actions complete (500.3)."""
    p1 = PlayerState(name="P1", hand=[_mk_land(f"L{i}") for i in range(8)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.begin_turn_bookkeeping(0)
    game.clear_priority_window()

    assert game._receives_priority("cleanup") is False

    game.resolve_cleanup_step(0)

    # The discard happened, but no priority window ever opened.
    assert len(p1.hand) == 7
    assert game.priority_player_index is None


# ---------------------------------------------------------------------------
# 500 — General (step/phase mechanics exercised by the steps above)
# ---------------------------------------------------------------------------


@pytest.mark.cr("500.5")
def test_unspent_mana_empties_when_a_step_ends():
    """As a step ends, any unspent mana left in a player's mana pool empties
    (500.5)."""
    p1 = PlayerState(name="P1", library=[_mk_land()])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.begin_turn_bookkeeping(0)
    game.resolve_untap_step(0)
    game.resolve_upkeep(0)
    p1.mana_pool["G"] = 3

    game.resolve_draw_step(0)  # draw step closes at the end of this call

    assert p1.mana_pool.get("G", 0) == 0
