"""The delayed abilities a step carries out from a **mark** are stack objects
(CR 603.7, 603.3) — and "sacrifice it" is not "its controller sacrifices it"
(CR 701.21a).

"Sacrifice this creature at the beginning of the next end step" (Dragon
Whelp), "destroy that creature at end of combat" (Cockatrice), Berserk's and
Nettling Imp's conditional destructions and Rakalite's return are recorded as a
mark on the permanent they are about. The end step and the end of combat step
used to carry them out inline, as sweeps, before anybody had priority: nothing
could answer them, every one happened before the step's printed triggers
whatever the seats' order (CR 603.3b), and the sacrifice was made by whoever
controlled the permanent then. Each is now announced as its own delayed
triggered ability as the step begins, controlled by whoever created it
(CR 603.7d–e).

And the bare imperative's actor is that controller: "Sacrifice it" cannot be
done to a permanent that changed hands (CR 701.21a; Sneak Attack's ruling,
2020-08-07: "You sacrifice the creature only if you still control it"; Time
Elemental's, 2007-09-16), where "Its controller sacrifices it" is whoever has
it then (Goblin Ski Patrol's, 2008-10-01).
"""

import pytest

from engine import Game, PlayerState
from engine.control import change_control
from engine.models import Permanent
from tests.helpers import declare_attack, settle


def _table(set_pool, *, interactive=()) -> Game:
    island = set_pool("LEA")["Island"]
    game = Game(players=[
        PlayerState("P1", library=[island] * 20),
        PlayerState("P2", library=[island] * 20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    return game


def _put(game, seat, card) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _activate(game, seat, name, target=None, *, ability_index=0) -> None:
    kwargs = {"ability_index": ability_index, "target_player_index": seat}
    if target is not None:
        kwargs["target_permanent_ids"] = [target.permanent_id]
    result = game.activate_permanent_ability(seat, name, **kwargs)
    assert result.supported, result
    settle(game)


def _steal(game, permanent, seat, source) -> None:
    change_control(permanent, seat, source=source)
    game._sync_control()
    assert game.controller_index_of(permanent) == seat


INTERACTIVE = pytest.mark.parametrize(
    "interactive", [(), (0, 1)], ids=["default", "interactive"]
)


@pytest.mark.cr("603.7", "603.3")
@INTERACTIVE
def test_dragon_whelps_sacrifice_is_on_the_stack_as_the_end_step_begins(
    set_pool, interactive
):
    """Four activations arm the sacrifice. The end step begins with it on the
    stack, under the Whelp's controller and the Whelp's name, and an Unsummon
    in response saves the Whelp: the ability resolves with nothing to
    sacrifice. The sweep sacrificed it before anybody could answer."""
    game = _table(set_pool, interactive=interactive)
    whelp = _put(game, 0, set_pool("LEA")["Dragon Whelp"])
    game.players[1].hand = [set_pool("LEA")["Unsummon"]]
    for _ in range(4):
        _activate(game, 0, "Dragon Whelp")

    game.resolve_end_step(0)
    assert game.is_on_battlefield(whelp)
    assert [(item.card.name, item.caster_index) for item in game.stack] == [
        ("Dragon Whelp", 0)
    ]
    if interactive:
        assert game.pass_priority(0) == "passed"
    assert game.queue_from_hand(
        1, "Unsummon", target_permanent_ids=[whelp.permanent_id]
    ).supported
    settle(game)

    assert [card.name for card in game.players[0].hand] == ["Dragon Whelp"]
    assert game.players[0].graveyard == []
    assert any("nothing to sacrifice at end step" in line for line in game.log)


@pytest.mark.cr("511.2", "603.7e")
@INTERACTIVE
def test_cockatrices_destruction_waits_on_the_stack_at_end_of_combat(
    set_pool, interactive
):
    """"Whenever this creature blocks or becomes blocked by a non-Wall
    creature, destroy that creature at end of combat." The block trigger
    records the destruction; the end of combat step begins with it on the
    stack under Cockatrice's controller, and the Hill Giant's controller
    bounces it in response. Unanswered, the Giant is destroyed there."""
    for answered in (True, False):
        game = _table(set_pool, interactive=interactive)
        giant = _put(game, 0, set_pool("LEA")["Hill Giant"])
        _put(game, 1, set_pool("LEA")["Cockatrice"])
        game.players[0].hand = [set_pool("LEA")["Unsummon"]]
        declare_attack(game, 0, blocks={0: 0})
        settle(game)
        for _ in range(3):
            if game.current_step == "end_of_combat":
                break
            game.advance_combat_phase()
            if game.current_step != "end_of_combat":
                settle(game)

        assert game.current_step == "end_of_combat"
        assert game.is_on_battlefield(giant), "3/3 against a 2/4: the fight kills nothing"
        assert [(item.card.name, item.caster_index) for item in game.stack] == [
            ("Cockatrice", 1)
        ]
        if answered:
            assert game.queue_from_hand(
                0, "Unsummon", target_permanent_ids=[giant.permanent_id]
            ).supported
        settle(game)

        if answered:
            assert [card.name for card in game.players[0].hand] == ["Hill Giant"]
            assert [card.name for card in game.players[0].graveyard] == ["Unsummon"]
        else:
            assert not game.is_on_battlefield(giant)
            assert [card.name for card in game.players[0].graveyard] == ["Hill Giant"]
            assert "Hill Giant was destroyed at end of combat" in game.log


@pytest.mark.cr("603.3b")
def test_a_marks_ability_takes_its_place_in_apnap_order(set_pool):
    """The active player's Ball Lightning ("At the beginning of the end step,
    sacrifice this creature") and the other player's Krovikan Elementalist
    sacrifice, armed during this turn: both triggered as the step began, so
    the active player's goes on the stack first and the other's resolves
    first (CR 603.3b). The sweep made the sacrifice before either."""
    game = _table(set_pool)
    lightning = _put(game, 0, set_pool("DRK")["Ball Lightning"])
    _put(game, 1, set_pool("ICE")["Krovikan Elementalist"])
    bears = _put(game, 1, set_pool("LEA")["Grizzly Bears"])
    _activate(game, 1, "Krovikan Elementalist", bears, ability_index=1)

    game.resolve_end_step(0)
    assert game.is_on_battlefield(bears)
    assert [(item.card.name, item.caster_index) for item in game.stack] == [
        ("Ball Lightning", 0), ("Krovikan Elementalist", 1),
    ]
    settle(game)
    assert not game.is_on_battlefield(bears) and not game.is_on_battlefield(lightning)
    assert "P2 sacrificed Grizzly Bears at end step" in game.log


@pytest.mark.cr("701.21a", "603.7e")
def test_sacrifice_it_cannot_take_what_changed_hands(set_pool):
    """Krovikan Elementalist: "Target creature you control gains flying until
    end of turn. **Sacrifice it** at the beginning of the next end step." The
    Bears are stolen before the end step: their old controller controls the
    delayed ability and cannot sacrifice what they no longer control, so the
    Bears stay with the thief."""
    game = _table(set_pool)
    _put(game, 0, set_pool("ICE")["Krovikan Elementalist"])
    bears = _put(game, 0, set_pool("LEA")["Grizzly Bears"])
    thief = _put(game, 1, set_pool("LEA")["Grizzly Bears"])
    _activate(game, 0, "Krovikan Elementalist", bears, ability_index=1)
    _steal(game, bears, 1, thief)

    game.resolve_end_step(0)
    settle(game)

    assert game.is_on_battlefield(bears)
    assert game.controller_index_of(bears) == 1
    assert any("doesn't control Grizzly Bears and can't sacrifice it" in line
               for line in game.log)


@pytest.mark.cr("701.21a")
def test_its_controller_sacrifices_it_is_whoever_has_it(set_pool):
    """Celestial Sword: "Target creature you control gets +3/+3 until end of
    turn. **Its controller** sacrifices it at the beginning of the next end
    step." Stolen before the end step, the Bears are sacrificed by the thief
    (Goblin Ski Patrol's ruling: "its new controller will still have to
    sacrifice it")."""
    game = _table(set_pool)
    _put(game, 0, set_pool("ICE")["Celestial Sword"])
    bears = _put(game, 0, set_pool("LEA")["Grizzly Bears"])
    thief = _put(game, 1, set_pool("LEA")["Grizzly Bears"])
    _activate(game, 0, "Celestial Sword", bears)
    _steal(game, bears, 1, thief)

    game.resolve_end_step(0)
    settle(game)

    assert not game.is_on_battlefield(bears)
    assert "P2 sacrificed Grizzly Bears at end step" in game.log


@pytest.mark.cr("701.21a", "603.7e")
def test_time_elemental_stolen_before_end_of_combat_stays_and_still_deals_its_damage(
    set_pool,
):
    """"When this creature attacks or blocks, at end of combat, sacrifice it
    and it deals 5 damage to you." Its ruling (2007-09-16): "If Time Elemental
    attacks or blocks, but you no longer control it at end of combat, you
    can't sacrifice it. However, it will still deal 5 damage to you." It was
    sacrificed by its new controller."""
    game = _table(set_pool)
    elemental = _put(game, 0, set_pool("LEG")["Time Elemental"])
    thief = _put(game, 1, set_pool("LEA")["Grizzly Bears"])
    declare_attack(game, 0)
    settle(game)
    _steal(game, elemental, 1, thief)

    for _ in range(3):
        game.advance_combat_phase()
        settle(game)
        if game.current_turn_phase != "combat":
            break

    assert game.is_on_battlefield(elemental)
    assert game.controller_index_of(elemental) == 1
    assert game.players[0].life == 15
    assert any("doesn't control Time Elemental and can't sacrifice it" in line
               for line in game.log)


@pytest.mark.cr("603.7", "603.10a")
def test_one_effects_set_is_one_ability(set_pool):
    """Siren's Call: "At the beginning of the next end step, destroy all
    non-Wall creatures that player controls that didn't attack this turn."
    One delayed ability over the set — one stack object, both creatures
    destroyed in it — where two Krovikan Elementalist activations are two
    (``tests/rules/test_kg4_departures2_delayed_sacrifice.py``)."""
    game = _table(set_pool)
    first = _put(game, 0, set_pool("LEA")["Grizzly Bears"])
    second = _put(game, 0, set_pool("LEA")["Hill Giant"])
    first.tapped = second.tapped = True          # neither can attack
    game.players[1].hand = [set_pool("LEA")["Siren's Call"]]
    game._set_phase_and_step("combat", "beginning_of_combat")
    assert game.queue_from_hand(1, "Siren's Call", target_player_index=0).supported
    settle(game)

    game.resolve_end_step(0)
    assert [(item.card.name, item.caster_index) for item in game.stack] == [
        ("Siren's Call", 1)
    ]
    settle(game)
    assert not game.is_on_battlefield(first) and not game.is_on_battlefield(second)
