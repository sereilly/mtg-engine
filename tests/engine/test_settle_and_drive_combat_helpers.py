"""``tests.helpers.settle`` and ``tests.helpers.drive_combat`` — what each is
for, shown on the trap it removes.

Three Mirrodin groups each lost a debugging round to one of these, with real
cards, and every test below plays one of them on a shipped card twice: the way
the test was written (``resolve_stack``, or ``advance_combat_phase`` until the
end of combat step), which reads a board that is not at rest, and the helper,
which reads the board the rules give.

1. **A step's trigger leaves its offer queued with an empty stack.** At a
   headless table the step's window resolves the trigger and pops it; the
   "you may" stays owed, ``resolve_stack`` has nothing to resolve, and the step
   machinery walks on past it (Hystrodon).
2. **``resolve_stack`` performs no state-based actions** — not after the stack
   is empty and not between two resolutions (Lightning Bolt over Giant Growth).
3. **A combat drive that stops on arriving in the end of combat step has not
   ended combat.** The "at end of combat" triggers fire as that step begins
   (CR 511.2) and the arrival's settle resolves them (Time Elemental), but the
   creatures are still in combat until the step ends (CR 511.3).

``resolve_stack``'s own contract — it answers only what blocks the stack — is
``test_stack_drain_helper.py``; nothing here changes it.
"""

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import declare_attack, drive_combat, resolve_stack, settle


def _table(set_pool, *, interactive=()) -> Game:
    island = set_pool("LEA")["Island"]
    game = Game(players=[
        PlayerState("P1", library=[island] * 20),
        PlayerState("P2", library=[island] * 20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    return game


def _put(game, seat, card) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _hystrodon_connects(set_pool, **table) -> Game:
    """Hystrodon attacking with no blocker: "Whenever this creature deals
    combat damage to a player, you may draw a card." The declare blockers
    step, the damage still to be dealt."""
    game = _table(set_pool, **table)
    _put(game, 0, set_pool("ONS")["Hystrodon"])
    declare_attack(game, 0)
    return game


def test_settle_answers_the_offer_a_step_left_on_an_empty_stack(set_pool):
    """Trap 1. The damage step's window resolves the trigger and pops it; the
    "you may draw" is queued with nothing on the stack, and a second advance
    takes the game into the postcombat main phase with it still owed.
    ``resolve_stack`` resolves nothing; ``settle`` answers it (the registry's
    default draws)."""
    game = _hystrodon_connects(set_pool)
    game.advance_combat_phase()
    game.advance_combat_phase()

    assert game.current_turn_phase == "postcombat_main"
    assert game.stack == [] and [c.kind for c in game.pending_choices] == ["optional_pay"], (
        "the rig must reproduce the trap: an offer owed past its step, with an empty stack"
    )
    assert resolve_stack(game) == 0
    assert len(game.players[0].hand) == 0, "resolve_stack answered nothing"

    assert settle(game) is None
    assert game.pending_choices == []
    assert len(game.players[0].hand) == 1, game.log[-4:]


@pytest.mark.parametrize("interactive", [(), (0,)], ids=["headless", "interactive"])
def test_drive_combat_answers_a_steps_offer_in_that_step(set_pool, interactive):
    """The same offer, driven by the helper: ``defaults=False`` stops at it
    *in the combat damage step* — where the trigger was — at a headless table
    as at an interactive one, and the drive then finishes combat with it
    answered."""
    game = _hystrodon_connects(set_pool, interactive=interactive)

    owed = drive_combat(game, defaults=False)

    assert owed is not None and owed.kind == "optional_pay"
    assert (game.current_turn_phase, game.current_step) == ("combat", "combat_damage")
    assert game.players[1].life == 17, "Hystrodon (3/3) connected"

    assert drive_combat(game) is None
    assert game.current_turn_phase == "postcombat_main"
    assert len(game.players[0].hand) == 1
    assert game.pending_choices == []


def test_settle_takes_a_given_answer_and_fails_a_refused_one(set_pool):
    """*answers* replaces the default for its kind — here, declining the draw
    through the prompt's own funnel — and an answer that leaves the prompt
    owed is a failure naming it, not a second default taken behind the
    test's back."""
    game = _hystrodon_connects(set_pool)
    game.advance_combat_phase()

    settle(game, answers={
        "optional_pay": lambda g, c: g.confirm_optional_pay(c.player_index, accept=False),
    })
    assert game.pending_choices == [] and len(game.players[0].hand) == 0

    game = _hystrodon_connects(set_pool)
    game.advance_combat_phase()
    with pytest.raises(AssertionError, match="left it owed"):
        settle(game, answers={"optional_pay": lambda g, c: None})


def test_settle_makes_the_state_based_check_resolve_stack_skips(set_pool):
    """Trap 2, both halves. Lightning Bolt cast over a Giant Growth at the same
    Grizzly Bears: the Bolt resolves first, and CR 704.3's check before the
    next object resolves puts the Bears in the graveyard, so the Growth has no
    target. ``resolve_stack`` makes no check at all — the Bears take the Bolt,
    then the Growth, and live as a 5/5 with 3 damage, which no later check
    undoes."""
    lea = set_pool("LEA")

    def bolt_over_growth():
        game = _table(set_pool)
        bears = _put(game, 1, lea["Grizzly Bears"])
        game.players[0].hand = [lea["Giant Growth"], lea["Lightning Bolt"]]
        for name in ("Giant Growth", "Lightning Bolt"):
            assert game.queue_from_hand(
                0, name, target_permanent_ids=[bears.permanent_id]
            ).supported
        assert [item.card.name for item in game.stack] == ["Giant Growth", "Lightning Bolt"]
        return game, bears

    game, bears = bolt_over_growth()
    resolve_stack(game)
    game.check_state_based_actions()
    assert game.is_on_battlefield(bears) and bears.damage_marked == 3, (
        "the rig must reproduce the trap: the Growth resolved onto a creature "
        "the Bolt had already killed"
    )

    game, bears = bolt_over_growth()
    settle(game)
    assert not game.is_on_battlefield(bears)
    assert [card.name for card in game.players[1].graveyard] == ["Grizzly Bears"]
    assert game.stack == []


def test_settle_puts_a_creature_dealt_lethal_damage_in_the_graveyard(set_pool):
    """Trap 2's plainer form: one Bolt, and a test that reads the board after
    ``resolve_stack`` finds the Bears alive with 3 damage marked."""
    lea = set_pool("LEA")
    game = _table(set_pool)
    bears = _put(game, 1, lea["Grizzly Bears"])
    game.players[0].hand = [lea["Lightning Bolt"]]
    assert game.queue_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id]
    ).supported

    resolve_stack(game)
    assert game.is_on_battlefield(bears) and bears.damage_marked == 3

    settle(game)
    assert not game.is_on_battlefield(bears)


def test_drive_combat_carries_through_the_end_of_combat_step(set_pool):
    """Trap 3. "When this creature attacks or blocks, at end of combat,
    sacrifice it and it deals 5 damage to you." (Time Elemental.) The delayed
    trigger fires **as the end of combat step begins** (CR 511.2), so a drive
    that advances until the step reads ``end_of_combat`` — one advance from
    declare blockers, at a headless table, which deals the damage and leaves
    that step too — finds it on the stack, and the settle resolves it there:
    the Elemental is gone and its controller at 15. So does
    ``through="combat_damage"``, which stops in the same place.

    What neither has done is end combat: the Grizzly Bears beside it are still
    attacking, because creatures leave combat only as the step *ends*
    (CR 511.3). The default drive leaves the step, and combat is over."""
    elemental = set_pool("LEG")["Time Elemental"]
    bears = set_pool("LEA")["Grizzly Bears"]

    game = _table(set_pool)
    attacker = _put(game, 0, elemental)
    partner = _put(game, 0, bears)
    declare_attack(game, 0)
    game.advance_combat_phase()
    assert game.current_step == "end_of_combat"
    assert [item.card.name for item in game.stack] == ["Time Elemental"], (
        "CR 511.2: the trigger is on the stack as the step begins"
    )
    settle(game)
    assert game.current_step == "end_of_combat"
    assert not game.is_on_battlefield(attacker) and game.players[0].life == 15
    assert partner.attacking and game.combat_attackers, (
        "the rig must reproduce the trap: a drive stopped in end of combat "
        "is still in combat"
    )

    game = _table(set_pool)
    attacker = _put(game, 0, elemental)
    partner = _put(game, 0, bears)
    declare_attack(game, 0)
    drive_combat(game, through="combat_damage")
    assert game.current_step == "end_of_combat"
    assert not game.is_on_battlefield(attacker) and game.players[0].life == 15
    assert partner.attacking and game.combat_attackers

    drive_combat(game)
    assert game.current_turn_phase == "postcombat_main"
    assert not partner.attacking
    assert game.combat_attackers == {}, "CR 511.3: combat is over"
    with pytest.raises(ValueError, match="no combat phase next"):
        drive_combat(game)   # the turn's one combat is spent; this would begin another


def test_drive_combat_names_the_declaration_it_waits_on(set_pool):
    """The declarations are the test's to make. A drive that reaches a step
    waiting on one fails naming it, rather than walking past or declaring
    something itself."""
    bears = set_pool("LEA")["Grizzly Bears"]
    game = _table(set_pool)
    _put(game, 0, bears)
    _put(game, 1, bears)
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok, why

    with pytest.raises(AssertionError, match="seat 1's block declaration"):
        drive_combat(game)

    with pytest.raises(ValueError, match="not a combat step"):
        drive_combat(game, through="end")
