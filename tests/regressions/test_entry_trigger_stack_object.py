"""Regressions found by moving entry triggers onto the stack (PLS W2G6).

A permanent's own "when this enters" trigger used to be executed inline, in a
context the entry site built for itself, and is now a stack object resolved in
the context every other triggered ability gets (CR 603.3). Run both ways over
every entry trigger in the pool, the two disagreed on a handful of cards — and
each disagreement was one of the two paths being wrong about **who** or **what**
the trigger was aimed at:

* **The seat nobody named.** Inline, "the target player" of a trigger that
  names none defaulted to the trigger's own *controller*; every other trigger
  defaults it to an opponent. The three Rishadan creatures ("each opponent
  sacrifices a permanent of their choice unless they pay {N}") offered their
  toll to that seat, so their controller paid it.
* **A target announced twice.** This engine names an entry trigger's target as
  the permanent is cast, so the stack object carries what the cast announced.
  Announced again at the push, "becomes the target of a spell or ability" was
  heard twice — and by a Sleeping Potion about the creature it had just been
  cast on, which made it sacrifice itself to its own "tap enchanted creature".
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack

_RISHADAN = [("Rishadan Cutpurse", 1), ("Rishadan Footpad", 2), ("Rishadan Brigand", 3)]


def _w2g6_duel(catalog_by_name, hand, *, humans=()) -> Game:
    forest = catalog_by_name["Forest"]
    game = Game(players=[
        PlayerState("Caster", library=[forest] * 10, hand=list(hand)),
        PlayerState("Rival", library=[forest] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(humans)
    return game


def _w2g6_put(game, seat, card) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return permanent


@pytest.mark.parametrize("name,toll", _RISHADAN)
def test_w2g6_a_rishadan_toll_is_the_opponents_to_pay(catalog_by_name, name, toll):
    """"Each opponent sacrifices a permanent of their choice unless they pay
    {N}": the opponent is asked, and it is the opponent's mana that goes."""
    game = _w2g6_duel(catalog_by_name, [catalog_by_name[name]], humans=(0, 1))
    for seat in (0, 1):
        game.players[seat].mana_pool["W"] = 5
        _w2g6_put(game, seat, catalog_by_name["Grizzly Bears"])

    assert game.queue_from_hand(0, name).supported
    assert game.resolve_top_of_stack(pause_for_choices=True), "the creature spell"
    assert game.resolve_top_of_stack(pause_for_choices=True), "its entry trigger"

    (asked,) = game.pending_choices
    assert (asked.kind, asked.player_index) == ("optional_pay", 1)
    assert asked.data["cost"] == {"generic": toll}
    assert game.confirm_optional_pay(1, accept=True) is True

    assert game.players[0].mana_pool["W"] == 5, "the controller pays nothing"
    assert game.players[1].mana_pool["W"] == 5 - toll
    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]
    assert sorted(p.card.name for p in game.controlled_by(0)) == sorted(
        ["Grizzly Bears", name]
    )


@pytest.mark.parametrize("name,toll", _RISHADAN)
def test_w2g6_an_opponent_who_cannot_pay_the_rishadan_toll_sacrifices(
    catalog_by_name, name, toll
):
    """With nothing to pay it with, the opponent gives up a permanent — and
    the controller, whose pool could have covered the toll, gives up nothing."""
    game = _w2g6_duel(catalog_by_name, [catalog_by_name[name]])
    game.players[0].mana_pool["W"] = 5
    for seat in (0, 1):
        _w2g6_put(game, seat, catalog_by_name["Grizzly Bears"])

    assert game.queue_from_hand(0, name).supported
    resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert game.players[0].mana_pool["W"] == 5
    assert list(game.controlled_by(1)) == []
    assert [card.name for card in game.players[1].graveyard] == ["Grizzly Bears"]
    assert sorted(p.card.name for p in game.controlled_by(0)) == sorted(
        ["Grizzly Bears", name]
    )


def test_w2g6_sleeping_potion_is_not_sacrificed_to_its_own_entry_trigger(
    set_pool, catalog_by_name
):
    """"When this Aura enters, tap enchanted creature. … When enchanted
    creature becomes the target of a spell or ability, sacrifice this Aura."
    The entry trigger's stack object carries the creature the Aura was cast on;
    that is a reference the cast already announced, not a new targeting."""
    potion = set_pool("PLS")["Sleeping Potion"]
    game = _w2g6_duel(catalog_by_name, [potion])
    bears = _w2g6_put(game, 1, catalog_by_name["Grizzly Bears"])

    assert game.queue_from_hand(
        0, "Sleeping Potion", target_permanent_ids=[bears.permanent_id]
    ).supported
    assert game.resolve_top_of_stack()
    (trigger,) = game.stack
    assert trigger.ability_text == "When this Aura enters, tap enchanted creature."
    assert not bears.tapped, "on the stack, not yet resolved"
    resolve_stack(game)

    assert bears.tapped
    assert [p.card.name for p in game.controlled_by(0)] == ["Sleeping Potion"]
    assert game.players[0].graveyard == []

    # ...and the sentence still does what it prints when something *does*
    # target the creature.
    bolt = catalog_by_name["Lightning Bolt"]
    game.players[1].hand.append(bolt)
    assert game.queue_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id]
    ).supported
    resolve_stack(game)
    assert [card.name for card in game.players[0].graveyard] == ["Sleeping Potion"]


def test_w2g6_an_entry_triggers_cast_time_target_is_announced_once(catalog_by_name):
    """Rayne, Academy Chancellor draws when a permanent its controller controls
    "becomes the target of a spell or ability an opponent controls". A
    Man-o'-War cast at Rayne's controller's creature is that once — as it is
    cast, in this engine's convention — and not a second time when the trigger
    carrying the same target is put on the stack."""
    game = _w2g6_duel(catalog_by_name, [catalog_by_name["Man-o'-War"]])
    _w2g6_put(game, 1, catalog_by_name["Rayne, Academy Chancellor"])
    bears = _w2g6_put(game, 1, catalog_by_name["Grizzly Bears"])

    assert game.queue_from_hand(
        0, "Man-o'-War", target_permanent_ids=[bears.permanent_id]
    ).supported
    assert [item.card.name for item in game.stack] == [
        "Man-o'-War", "Rayne, Academy Chancellor",
    ]
    assert game.resolve_top_of_stack()
    game.auto_resolve_pending_choices()
    assert len(game.players[1].hand) == 1, "Rayne drew for the cast"

    assert game.resolve_top_of_stack(), "the creature spell"
    (trigger,) = game.stack
    assert trigger.is_ability and trigger.card.name == "Man-o'-War"
    assert trigger.target_permanent_id == [bears.permanent_id]

    resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert sorted(card.name for card in game.players[1].hand) == [
        "Forest", "Grizzly Bears",
    ], "one draw, and the creature Man-o'-War returned"
