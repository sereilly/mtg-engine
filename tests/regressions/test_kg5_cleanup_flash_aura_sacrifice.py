"""Mirage's and Visions' flash-enchantment rider is a delayed triggered ability
on the stack in the cleanup step (CR 603.7g, 514.3a).

"You may cast this spell as though it had flash. If you cast it any time a
sorcery couldn't have been cast, the controller of the permanent it becomes
sacrifices it at the beginning of the next cleanup step." The static ability
that lets the spell be cast as though it had flash creates a delayed triggered
ability when the player does so — CR 603.7g: its source is the card, its
controller the caster. It triggers as the next cleanup step begins and is put
on the stack once the step's discard and sweeps are done, and then the active
player gets priority (CR 514.3a) — so it can be answered.

**The census.** Every card in the pool printing the rider (asked of
``cast_timing.sacrifices_at_cleanup_if_cast_at_instant_speed``, the reader the
cast path stamps by — never a name list) is cast at instant speed onto a board
that can host it, and its cleanup step is read where the active player first
gets priority: one ``carry_out_delayed_mark`` object, the card's, controlled
by the caster, with the permanent still on the battlefield, no sacrificer
recorded ("the controller of the permanent it becomes" is whoever controls it
then, CR 701.21a); and once it resolves, the permanent is in its owner's
graveyard. Backwards: on e245e624c a sweep sacrificed it as the step began, so
no object was ever on the stack and nobody was offered priority — every row
fails. Floor: the ten cards measured at kg5/cleanup.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.cast_timing import (CAST_AT_INSTANT_SPEED,
                                sacrifices_at_cleanup_if_cast_at_instant_speed)
from engine.control import change_control
from engine.delayed_triggers import CARRY_OUT_DELAYED_MARK
from engine.faces import compilation_units
from engine.models import Permanent

from tests.helpers import settle


@pytest.fixture(scope="module")
def pool():
    return {card.name: card for card in load_catalog()}


def _rider_cards() -> list:
    return sorted(
        {
            unit.name: unit for unit in compilation_units(load_catalog())
            if sacrifices_at_cleanup_if_cast_at_instant_speed(unit.oracle_text or "")
        }.values(),
        key=lambda card: card.name,
    )


_RIDERS = _rider_cards()


def _delayed_marks(game) -> list:
    return [
        item for item in game.stack
        if item.ability_instruction is not None
        and item.ability_instruction.kind == CARRY_OUT_DELAYED_MARK
    ]


def _table(pool, card, *, active: int, caster: int, interactive=()):
    """*card* in *caster*'s hand on *active*'s turn, with a host every enchant
    clause the census meets can take (an artifact creature, colourless) and a
    creature card in the caster's graveyard for Necromancy."""
    island = pool["Island"]
    game = Game(players=[
        PlayerState("P1", library=[island] * 10),
        PlayerState("P2", library=[island] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(active)
    host = Permanent(card=pool["Ornithopter"])
    game._put_permanent_onto_battlefield(caster, host, None)
    game.players[caster].graveyard.append(pool["Grizzly Bears"])
    game.players[caster].hand.append(card)
    return game, host


def _cast(game, card, caster: int, host) -> Permanent:
    kwargs = {}
    if "Aura" in card.type_line:
        kwargs = {
            "target_player_index": caster,
            "target_permanent_index": game.players[caster].battlefield.index(host),
        }
    result = game.cast_from_hand(caster, card.name, **kwargs)
    assert result.supported, (card.name, result.details)
    settle(game)
    found = [
        permanent for permanent in game.players[caster].battlefield
        if permanent.card.name == card.name
    ]
    assert found, (card.name, game.log[-8:])
    return found[0]


def _cleanup_seen_at_first_priority(game, active: int, permanent):
    """Run *active*'s cleanup step and return what the first player given
    priority in it saw: ``(seat, delayed-mark objects, permanent present)`` —
    or None when nobody was given priority."""
    offered = []

    def first_offer(table, seat):
        if not offered:
            offered.append((seat, _delayed_marks(table), table.is_on_battlefield(permanent)))
        return False

    game.priority_driver = first_offer
    game.resolve_cleanup_step(active)
    game.priority_driver = None
    return offered[0] if offered else None


def test_the_census_finds_every_printing_of_the_rider():
    # Measured at kg5/cleanup: Mirage's five Auras and Visions' four and
    # Parapet.
    assert len(_RIDERS) >= 10, [card.name for card in _RIDERS]


@pytest.mark.parametrize("card", _RIDERS, ids=[card.name for card in _RIDERS])
def test_a_flashed_in_permanent_is_sacrificed_by_a_delayed_ability_in_cleanup(pool, card):
    game, host = _table(pool, card, active=0, caster=0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    assert game.current_turn_phase == "combat"
    permanent = _cast(game, card, 0, host)

    seen = _cleanup_seen_at_first_priority(game, 0, permanent)

    assert seen is not None, f"{card.name}: nobody was given priority in cleanup"
    seat, objects, present = seen
    assert seat == 0, "CR 514.3a: the active player gets priority first"
    assert present, f"{card.name}: sacrificed before the ability was on the stack"
    assert [
        (item.card.name, item.caster_index, item.ability_instruction.payload.get("mark"))
        for item in objects
    ] == [(card.name, 0, CAST_AT_INSTANT_SPEED)], game.log[-8:]
    payload = objects[0].ability_instruction.payload
    assert payload.get("action") == "sacrifice"
    assert "sacrificed_by" not in payload, "the controller of the permanent sacrifices it"
    assert not game.is_on_battlefield(permanent)
    assert any(graveyard_card is card for graveyard_card in game.players[0].graveyard)
    assert f"P1 sacrificed {card.name} at cleanup" in game.log


@pytest.mark.parametrize("card", _RIDERS, ids=[card.name for card in _RIDERS])
def test_cast_when_a_sorcery_could_have_been_it_stays(pool, card):
    game, host = _table(pool, card, active=0, caster=0)
    assert game.current_turn_phase == "precombat_main" and not game.stack
    permanent = _cast(game, card, 0, host)
    assert not permanent.metadata.get(CAST_AT_INSTANT_SPEED)

    seen = _cleanup_seen_at_first_priority(game, 0, permanent)

    assert seen is None or not seen[1], seen
    assert game.is_on_battlefield(permanent)


@pytest.mark.parametrize("interactive", [(), (0, 1)], ids=["default", "interactive"])
def test_flashed_in_on_an_opponents_turn_it_goes_at_that_turns_cleanup(pool, interactive):
    """"…at the beginning of **the next** cleanup step": CR 514.1 gives every
    turn one, so an Aura P1 flashes in on P2's turn is sacrificed at the end of
    P2's turn. The delayed ability is P1's (CR 603.7g), and P1 — the Aura's
    controller — sacrifices it."""
    soar = pool["Soar"]
    game, host = _table(pool, soar, active=1, caster=0, interactive=interactive)
    permanent = _cast(game, soar, 0, host)
    assert permanent.metadata.get(CAST_AT_INSTANT_SPEED) is True

    game.resolve_cleanup_step(1)
    settle(game)

    assert not game.is_on_battlefield(permanent)
    assert "P1 sacrificed Soar at cleanup" in game.log


def test_the_controller_of_the_permanent_it_becomes_sacrifices_it(pool):
    """"**The controller of the permanent it becomes** sacrifices it", not "you
    sacrifice it": a flashed-in Aura that changed hands before the cleanup
    step is sacrificed by the player who controls it then (CR 701.21a), though
    the delayed ability is still its caster's (CR 603.7g)."""
    soar = pool["Soar"]
    game, host = _table(pool, soar, active=0, caster=0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    permanent = _cast(game, soar, 0, host)
    change_control(permanent, 1, source=pool["Grizzly Bears"])
    game._sync_control()
    assert game.controller_index_of(permanent) == 1

    seen = _cleanup_seen_at_first_priority(game, 0, permanent)

    assert seen is not None and [item.caster_index for item in seen[1]] == [0]
    assert not game.is_on_battlefield(permanent)
    assert "P2 sacrificed Soar at cleanup" in game.log


#: Every card in the pool printing a static timing permission an enchantment
#: in the census can be cast by, with which of the census's cards it covers.
_OTHER_PERMISSIONS = [
    # "Any player may cast creature and enchantment spells as though they had
    # flash." Every one of them, and for the opponent too.
    ("Vernal Equinox", 1, lambda card: True),
    # "You may cast Aura spells with enchant creature as though they had
    # flash." Not Relic Ward (enchant artifact), Parapet or Necromancy (not
    # Auras as they are cast).
    ("Rootwater Shaman", 0, lambda card: "Aura" in card.type_line
     and "Enchant artifact" not in (card.oracle_text or "")),
]


@pytest.mark.parametrize("permission,controller,covers", _OTHER_PERMISSIONS,
                         ids=[row[0] for row in _OTHER_PERMISSIONS])
@pytest.mark.parametrize("card", _RIDERS, ids=[card.name for card in _RIDERS])
def test_cast_by_another_effects_permission_it_is_not_sacrificed(
    pool, card, permission, controller, covers,
):
    """"The sacrifice occurs only if you cast it using its own ability. If you
    cast it using some other effect (for example, if another effect allowed
    you to cast it as though it had flash), then it won't be sacrificed." (the
    cycle's rulings, 2022-12-08.) With another permission open the caster uses
    it — the one with no price, derived as Invasion's flash surcharge is — so
    a covered card is not marked and stays; a card the permission does not
    cover is still cast by its own sentence and still goes. Backwards: on
    9627a81eb every covered row was marked and sacrificed."""
    game, host = _table(pool, card, active=0, caster=0)
    granter = Permanent(card=pool[permission])
    game._put_permanent_onto_battlefield(controller, granter, None)
    game._close_current_priority_step()
    game.advance_combat_phase()
    permanent = _cast(game, card, 0, host)

    covered = covers(card)
    assert bool(permanent.metadata.get(CAST_AT_INSTANT_SPEED)) is not covered
    game.resolve_cleanup_step(0)
    settle(game)
    assert game.is_on_battlefield(permanent) is covered, game.log[-6:]
