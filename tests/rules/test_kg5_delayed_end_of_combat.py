"""CR 511.2: "Abilities that trigger 'at end of combat' trigger as the end of
combat step begins. Effects that last 'until end of combat' expire at the end
of the combat phase."

Both halves were the wrong way round. The step's triggers — printed (Wall of
Nets), delayed (Time Elemental's "at end of combat, sacrifice it") — fired as
the step was **left** (``end_combat``), after the active player had already had
priority in it (CR 117.3a gives it only once they are on the stack): an Unsummon
cast in that window resolved before Time Elemental's trigger existed, and a
Wall of Nets removed there never triggered at all. And the until-end-of-combat
sweep ran *before* the step's window, so what resolved there saw Glyph of
Destruction's +10/+0 already gone.

Each board below is driven through the engine's own stepping
(``advance_combat_phase``), at an interactive table and at a default one.
"""

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import declare_attack, drive_combat, settle


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


def _arrive_at_end_of_combat(game) -> None:
    """From the declare blockers step, through the combat damage step, to the
    end of combat step's arrival — without settling there."""
    for _ in range(4):
        if game.current_step == "end_of_combat":
            return
        game.advance_combat_phase()
        if game.current_step != "end_of_combat":
            settle(game)
    assert game.current_step == "end_of_combat", game.current_step


INTERACTIVE = pytest.mark.parametrize(
    "interactive", [(), (0, 1)], ids=["default", "interactive"]
)


@pytest.mark.cr("511.2", "117.3a")
@INTERACTIVE
def test_time_elementals_trigger_is_on_the_stack_before_anyone_has_priority(
    set_pool, interactive
):
    """"When this creature attacks or blocks, at end of combat, sacrifice it
    and it deals 5 damage to you." The delayed trigger is on the stack as the
    step begins, so an Unsummon cast in the step answers it: the Unsummon
    resolves first, the Elemental goes home, and the trigger then has nothing
    to sacrifice but still deals its 5 damage (the card's 2007-09-16 ruling:
    "you can't sacrifice it. However, it will still deal 5 damage to you")."""
    game = _table(set_pool, interactive=interactive)
    elemental = _put(game, 0, set_pool("LEG")["Time Elemental"])
    game.players[1].hand = [set_pool("LEA")["Unsummon"]]
    declare_attack(game, 0)

    _arrive_at_end_of_combat(game)
    assert [item.card.name for item in game.stack] == ["Time Elemental"], (
        "CR 511.2: the trigger exists as the step begins"
    )
    assert game.priority_player_index == 0, "CR 117.3a: the active player, after it"

    if interactive:
        assert game.pass_priority(0) == "passed"
    result = game.queue_from_hand(
        1, "Unsummon", target_permanent_ids=[elemental.permanent_id]
    )
    assert result.supported
    assert [item.card.name for item in game.stack] == ["Time Elemental", "Unsummon"]

    settle(game)
    assert not game.is_on_battlefield(elemental)
    assert [card.name for card in game.players[0].hand] == ["Time Elemental"]
    assert game.players[0].life == 15
    assert any("nothing left to sacrifice" in line for line in game.log)


@pytest.mark.cr("511.2", "113.7a")
@INTERACTIVE
def test_wall_of_nets_removed_after_its_trigger_still_exiles(set_pool, interactive):
    """"At end of combat, exile all creatures blocked by this creature." A
    Wall of Nets bounced in the end of combat step has already triggered, and
    the ability exists independently of its source (CR 113.7a): the creature
    it blocked is exiled. Its leaves-the-battlefield return has resolved by
    then with nothing to return, so the creature stays exiled."""
    game = _table(set_pool, interactive=interactive)
    bears = _put(game, 0, set_pool("LEA")["Grizzly Bears"])
    wall = _put(game, 1, set_pool("EXO")["Wall of Nets"])
    game.players[1].hand = [set_pool("LEA")["Unsummon"]]
    declare_attack(game, 0, blocks={0: 0})

    _arrive_at_end_of_combat(game)
    assert [item.card.name for item in game.stack] == ["Wall of Nets"]
    if interactive:
        assert game.pass_priority(0) == "passed"
    assert game.queue_from_hand(
        1, "Unsummon", target_permanent_ids=[wall.permanent_id]
    ).supported

    settle(game)
    assert not game.is_on_battlefield(wall)
    assert not game.is_on_battlefield(bears)
    assert [card.name for card in game.players[0].exile] == ["Grizzly Bears"]


@pytest.mark.cr("511.2")
def test_wall_of_nets_removed_before_the_step_begins_never_triggers(set_pool):
    """The other side of the same moment (the card's ruling: "It only exiles
    creatures if this card is still on the battlefield at the end of
    combat"). Bounced in the combat damage step's window, it is gone when the
    end of combat step begins, nothing triggers, and the Bears stay."""
    game = _table(set_pool)
    bears = _put(game, 0, set_pool("LEA")["Grizzly Bears"])
    wall = _put(game, 1, set_pool("EXO")["Wall of Nets"])
    game.players[1].hand = [set_pool("LEA")["Unsummon"]]
    declare_attack(game, 0, blocks={0: 0})
    game.advance_combat_phase(allow_damage_skip=False)
    assert game.current_step == "combat_damage"
    assert game.queue_from_hand(
        1, "Unsummon", target_permanent_ids=[wall.permanent_id]
    ).supported
    settle(game)
    assert not game.is_on_battlefield(wall)

    game.advance_combat_phase()
    assert game.current_step == "end_of_combat"
    assert game.stack == []
    drive_combat(game)
    assert game.is_on_battlefield(bears)
    assert game.players[0].exile == []


@pytest.mark.cr("511.2")
def test_until_end_of_combat_lasts_through_the_steps_window(set_pool):
    """"Target blocking Wall you control gets +10/+0 until end of combat."
    (Glyph of Destruction.) Asked in the end of combat step's window — the
    simulator's priority driver is offered priority there before the step
    ends — the Wall is still 10 power; once the step has ended, it is 0."""
    game = _table(set_pool)
    _put(game, 0, set_pool("LEA")["Grizzly Bears"])
    wall = _put(game, 1, set_pool("LEA")["Wall of Stone"])
    game.players[1].hand = [set_pool("LEG")["Glyph of Destruction"]]
    declare_attack(game, 0, blocks={0: 0})
    assert game.queue_from_hand(
        1, "Glyph of Destruction", target_permanent_ids=[wall.permanent_id]
    ).supported
    settle(game)
    assert wall.effective_power == 10

    seen = []

    def driver(table, seat):
        if table.current_step == "end_of_combat":
            seen.append(wall.effective_power)
        return False

    game.priority_driver = driver
    drive_combat(game)
    assert seen and set(seen) == {10}, seen
    assert game.current_turn_phase == "postcombat_main"
    assert wall.effective_power == 0


@pytest.mark.cr("511.2")
def test_the_step_fires_once_whichever_road_begins_it(set_pool):
    """"At end of combat, if this creature attacked or blocked this combat,
    remove a +1/+0 counter from it." (Clockwork Beast.) Arriving by the
    stepping fires it; the End Turn road (``end_combat`` called while the step
    is already under way) finds it fired and does not fire it again. And the
    End Turn road from an earlier combat step begins the step itself, and
    fires it there."""
    beast_card = set_pool("LEA")["Clockwork Beast"]

    game = _table(set_pool)
    beast = _put(game, 0, beast_card)
    before = beast.effective_power
    declare_attack(game, 0)
    _arrive_at_end_of_combat(game)
    assert len(game.stack) == 1
    assert game.end_combat()
    settle(game)
    assert game.combat_attackers == {}, "the End Turn road ended the step"
    assert beast.effective_power == before - 1, (before, beast.effective_power)

    game = _table(set_pool)
    beast = _put(game, 0, beast_card)
    before = beast.effective_power
    declare_attack(game, 0)
    assert game.current_step == "declare_blockers"
    assert game.end_combat()
    settle(game)
    assert game.combat_attackers == {}
    assert beast.effective_power == before - 1, (before, beast.effective_power)
