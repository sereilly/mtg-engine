"""CR 401.4 at the top of a library: the owner arranges what an effect puts there.

"If an effect puts two or more cards in a specific position in a library at
the same time, the **owner** of those cards may arrange them in any order."

The graveyard-to-library effects (Reinforcements, Bone Harvest, Drafna's
Restoration, Misinformation, Lodestone Bauble) laid their cards down in the
order the targets were named and asked nobody — on the ground that the naming
order *is* a choice of order. It is the controller's, made in a target picker
that never said the order of the clicks was the order of the next draws; and
for "a player's graveyard" the arranger the rule names is somebody else.

``Game.offer_library_top_order`` is the top twin of the bottom-order offer the
look-and-pick family makes: an interactive owner is asked through the
``reorder_library`` prompt, every other seat keeps the naming order.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_paths
from engine.faces import compilation_units
from engine.game_types import OracleExecutionContext
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card, resolve_stack

#: A floor, because a sweep that reaches nothing passes. Five on the day.
_MIN_CARDS = 5


def _creature(name: str):
    return _mk_card(name=name, type_line="Creature — Bear", power=2, toughness=2)


def _duel(interactive=()) -> tuple[Game, PlayerState, PlayerState]:
    deck = _mk_card(name="Deck", type_line="Artifact")
    me = PlayerState(name="P0", life=20, library=[deck] * 4)
    you = PlayerState(name="P1", life=20, library=[deck] * 4)
    game = Game(players=[me, you])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game, me, you


@pytest.mark.cr("401.4")
def test_401_4_the_owner_arranges_the_cards_put_on_top(set_pool):
    game, me, _you = _duel(interactive={0})
    me.hand = [set_pool("ALL")["Reinforcements"]]
    me.graveyard = [_creature("First"), _creature("Second"), _creature("Third")]

    assert game.queue_from_hand(
        0, "Reinforcements", target_player_index=0, target_permanent_index=[0, 1, 2],
    ).supported
    resolve_stack(game)

    # Laid down as named — and the order is asked, of the owner.
    assert [card.name for card in me.library][:3] == ["First", "Second", "Third"]
    (order,) = game.pending_choices_of("reorder_library")
    assert order.player_index == 0
    assert order.data["target_index"] == 0 and order.data["top_count"] == 3
    assert order.data.get("position", "top") == "top"
    assert [card.name for card in game.reorder_library_pile(order)] == [
        "First", "Second", "Third",
    ]

    assert game.confirm_reorder_library(0, [2, 0, 1])
    assert [card.name for card in me.library][:4] == ["Third", "First", "Second", "Deck"]
    assert not game.pending_choices


@pytest.mark.cr("401.4")
def test_401_4_it_is_the_library_s_owner_who_is_asked_not_the_one_who_named_them(
    set_pool,
):
    """Lodestone Bauble: "…from **a player's** graveyard on top of **their**
    library in any order." Aimed across the table, the order is the other
    player's — and the draw the next sentence arms waits for it."""
    game, me, you = _duel(interactive={0, 1})
    bauble = Permanent(card=set_pool("ALL")["Lodestone Bauble"])
    bauble.metadata["summoning_sickness_turn"] = -99
    me.battlefield.append(bauble)
    you.graveyard = [
        _mk_card(name="Mountain", type_line="Basic Land — Mountain"),
        _mk_card(name="Island", type_line="Basic Land — Island"),
    ]

    assert game.activate_permanent_ability(
        0, "Lodestone Bauble", target_player_index=1, target_permanent_index=[0, 1],
    ).supported

    (order,) = game.pending_choices_of("reorder_library")
    assert order.player_index == 1 and order.data["target_index"] == 1
    assert not game.delayed_triggers, "the next sentence has not run yet"

    assert game.confirm_reorder_library(1, [1, 0])
    assert [card.name for card in you.library][:2] == ["Island", "Mountain"]
    assert [entry.event for entry in game.delayed_triggers] == ["next_turns_upkeep"]


@pytest.mark.cr("401.4")
def test_401_4_a_seat_nobody_asks_keeps_the_order_they_were_named_in(set_pool):
    game, me, _you = _duel()
    me.hand = [set_pool("ALL")["Reinforcements"]]
    me.graveyard = [_creature("First"), _creature("Second"), _creature("Third")]

    assert game.queue_from_hand(
        0, "Reinforcements", target_player_index=0, target_permanent_index=[2, 0],
    ).supported
    resolve_stack(game)

    assert [card.name for card in me.library][:3] == ["Third", "First", "Deck"]
    assert not game.pending_choices


def _walk(value):
    if hasattr(value, "kind") and hasattr(value, "payload"):
        yield value
        yield from _walk(value.payload)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk(item)


@pytest.mark.cr("401.4")
def test_every_effect_that_puts_several_graveyard_cards_on_top_asks_the_owner():
    """The pool, both manifest roles: every program step that can put two or
    more cards from a graveyard on top of a library, run for an interactive
    owner over two cards its own description admits."""
    pool = load_cards(manifest_set_paths(include_measured=True))
    examined: list[str] = []
    for unit in compilation_units(pool):
        program = compile_card_oracle(unit)
        if not program.supported:
            continue
        roots = list(program.instructions)
        roots += [ability.instruction for ability in program.activated_abilities]
        for root in roots:
            for step in _walk(root):
                if step.kind != "put_graveyard_cards_on_library_top":
                    continue
                described = step.payload.get("targets") or {}
                if not described.get("unbounded") and int(described.get("count") or 1) < 2:
                    continue
                game, me, _you = _duel(interactive={0})
                type_word = str(step.payload.get("card_type") or "artifact").title()
                supertype = "Basic " if "basic" in (step.payload.get("supertypes") or ()) else ""
                line = f"{supertype}{type_word}" + (" — Bear" if type_word == "Creature" else "")
                me.graveyard = [
                    _mk_card(name="One", type_line=line),
                    _mk_card(name="Two", type_line=line),
                ]
                handler_context = OracleExecutionContext(
                    caster=me, target=me, card=unit,
                    target_permanent_index=[0, 1],
                )
                game._execute_oracle_instruction(step, handler_context)

                assert [card.name for card in me.library][:2] == ["One", "Two"], unit.name
                orders = game.pending_choices_of("reorder_library")
                assert len(orders) == 1, unit.name
                assert orders[0].player_index == 0, unit.name
                assert orders[0].data["top_count"] == 2, unit.name
                assert orders[0].data.get("position", "top") == "top", unit.name
                examined.append(unit.name)

    assert len(set(examined)) >= _MIN_CARDS, sorted(set(examined))
