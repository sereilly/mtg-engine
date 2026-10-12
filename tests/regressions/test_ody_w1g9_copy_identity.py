"""Regression: a copy of a spell keeps a target that was announced by id.

CR 707.10: "a copy of a spell ... copies ... all decisions made when casting
it, including modes, **targets**, the value of X". The web layer announces
every target by ``permanent_id`` alone (``target_permanent_id=[id]``, no
slot), and two of the three roads to a copy lost it:

* ``copy_triggering_spell`` (Double Vision, Mirari) built the copy from the
  original's seat and *slot* and left the id behind - Fork's bug, fixed in
  ``copy_top_stack_spell`` and never carried one handler up. The copy arrived
  holding a seat and no object, and a copied Lightning Bolt aimed at a
  creature dealt its 3 to that creature's controller.
* ``copy_this_spell`` (Chain Lightning) carried the id, and then the answer
  that *changes nothing* moved the copy: ``_default_copy_spell_target`` -
  "decline, keep the original's target" - read the missing slot as a player
  target and re-aimed the copy at the seat.

Found driving Mirari, whose own defect was a third thing (its cast event
froze no spell at all, so it took {3} and copied nothing). Before the fix: 2
of the 3 readers that reached a copy were wrong, and Mirari reached none.

The population is read off the compiled programs of both manifest roles, so
the next card printed with one of these kinds joins it unnamed.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.oracle_types import OracleInstruction
from engine.stack_targets import chosen_targets

_COPY_KINDS = frozenset({
    "copy_triggering_spell", "copy_this_spell", "copy_top_stack_spell",
})
_BASICS = ("Mountain", "Plains", "Forest", "Island", "Swamp")


def _walk(value):
    if isinstance(value, OracleInstruction):
        yield value
        yield from _walk(value.payload)
    elif isinstance(value, dict):
        for inner in value.values():
            yield from _walk(inner)
    elif isinstance(value, (list, tuple)):
        for inner in value:
            yield from _walk(inner)


@pytest.fixture(scope="module")
def by_name():
    names: dict = {}
    for card in compilation_units(
        load_cards(manifest_set_paths(include_measured=True))
    ):
        names.setdefault(card.name, card)
    return names


def copiers(by_name) -> list[tuple]:
    """``(card, kinds)`` for every supported card whose program copies a spell."""
    found = []
    for card in by_name.values():
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        roots = list(program.instructions)
        roots += [t.instruction for t in program.triggered_abilities]
        roots += [a.instruction for a in program.activated_abilities]
        kinds = {step.kind for root in roots for step in _walk(root)} & _COPY_KINDS
        if kinds:
            found.append((card, kinds))
    return found


def _table(by_name, copier, is_spell):
    """Seat 0 holds a Bolt (or the copier, when the copier is the spell) and
    seat 1 two look-alike creatures; both seats can pay any printed price."""
    bolt = by_name["Lightning Bolt"]
    game = Game(players=[
        PlayerState("A", hand=[copier if is_spell else bolt],
                    library=[by_name["Forest"]] * 6),
        PlayerState("B", library=[by_name["Forest"]] * 6),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    if not is_spell:
        game._put_permanent_onto_battlefield(0, Permanent(card=copier), None)
    first = Permanent(card=by_name["Craw Wurm"])
    second = Permanent(card=by_name["Craw Wurm"])
    for creature in (first, second):
        game._put_permanent_onto_battlefield(1, creature, None)
    for seat in (0, 1):
        for name in _BASICS * 2:
            game._put_permanent_onto_battlefield(
                seat, Permanent(card=by_name[name]), None
            )
    game.start_turn(0)
    game._settle()
    return game, first, second


def _answer(game) -> None:
    """Pay every price offered (a copy is what is being measured) and give
    every other prompt its registry default - which for the copy's own
    "choose new targets" is CR 707.10c's decline."""
    for _ in range(30):
        if not game.pending_choices:
            return
        choice = game.pending_choices[0]
        if choice.kind == "optional_pay":
            game.confirm_optional_pay(choice.player_index, accept=True)
        else:
            game.take_choice_default(choice)
    raise AssertionError(f"prompts still owed: {[c.kind for c in game.pending_choices]}")


def copy_keeps_its_target(by_name, copier, kinds) -> "bool | None":
    """Whether the first copy made is still aimed at the creature the original
    named by id, once every prompt has been answered - or None when this
    table makes no copy."""
    is_spell = any(word in copier.type_line for word in ("Instant", "Sorcery"))
    game, first, second = _table(by_name, copier, is_spell)
    aimed = {"target_permanent_ids": [second.permanent_id]}
    if "copy_top_stack_spell" in kinds and is_spell:
        # Fork: a Bolt first, then the copier aimed at that Bolt.
        game.players[0].hand.append(by_name["Lightning Bolt"])
        if not game.queue_from_hand(0, "Lightning Bolt", **aimed).supported:
            return None
        cast = game.queue_from_hand(0, copier.name, target_stack_index=0)
    else:
        cast = game.queue_from_hand(
            0, copier.name if is_spell else "Lightning Bolt", **aimed
        )
    if not cast.supported:
        return None
    for _ in range(40):
        if not game.stack:
            return None
        game.resolve_top_of_stack(pause_for_choices=True)
        _answer(game)
        copy = next((item for item in game.stack if item.is_copy), None)
        if copy is not None:
            targets = chosen_targets(game, copy) or ()
            return (
                len(targets) == 1
                and targets[0].kind == "permanent"
                and targets[0].permanent_id == second.permanent_id
            )
    return None


def test_a_copy_keeps_a_target_announced_by_id(by_name):
    found = copiers(by_name)
    verdicts = {
        card.name: copy_keeps_its_target(by_name, card, kinds)
        for card, kinds in found
    }
    reached = {name: kept for name, kept in verdicts.items() if kept is not None}
    # The floor: Fork, Chain Lightning, Chain Stasis, Double Vision and Mirari
    # on the day this was written. A walk that reached none passes anywhere.
    assert len(reached) >= 5, verdicts
    assert [name for name, kept in reached.items() if not kept] == []


def test_the_copy_is_offered_new_targets_and_takes_the_one_named(by_name):
    """"You may choose new targets for the copy." (CR 707.10c.) The offer a
    cast trigger's copy never made: it is asked of the copy's controller, and
    an answer naming the other creature moves the copy and not the original."""
    game, first, second = _table(by_name, by_name["Mirari"], is_spell=False)
    assert game.queue_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[second.permanent_id]
    ).supported
    game.resolve_top_of_stack(pause_for_choices=True)
    offer = game.pending_choices[0]
    assert offer.kind == "optional_pay" and offer.player_index == 0
    assert game.confirm_optional_pay(0, accept=True)
    prompt = game.pending_choice_of("copy_spell_target")
    assert prompt is not None and prompt.player_index == 0
    assert game.confirm_copy_spell_target(0, permanent_id=first.permanent_id)
    from tests.helpers import resolve_stack

    resolve_stack(game)
    assert (first.damage_marked, second.damage_marked) == (3, 3)
    assert [p.life for p in game.players] == [20, 20]
