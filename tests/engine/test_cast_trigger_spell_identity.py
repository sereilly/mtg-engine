"""Census: a cast trigger's "it" is the spell that fired it, not the first
spell on the stack printed on the same card.

"Whenever a player casts a spell, counter it unless that player pays {3}."
(Nether Void.) The trigger is a stack object above the spell it is about
(CR 603.3), and by the time it resolves anything may sit between them — so the
event has to carry *which* spell. It carried the ``CardDefinition``, and a deck
repeats one immutable definition per copy: two Lightning Bolts on the stack are
two objects with one card, and "find the stack item whose card is this" finds
whichever comes first. Nether Void's trigger for the second Bolt armed its
payment against the first.

The fire sites now carry the ``StackItem`` (``cast_item``), and the three
readers ask one function, ``handlers._common.triggering_spell``. This census
puts two spells of one card on the stack under **every** cast trigger in both
manifest roles whose effect acts on its spell — a counter bound to the trigger,
a price read off the spell, a copy of it — and asks two questions:

* resolve the trigger of the **later** spell: it must act on the later spell;
* take that spell off the stack first: it must then act on **nothing**
  (CR 608.2b's shape — the object is gone), not on its look-alike.

Before the change: 8 of 9 readers acted on the earlier spell, and 9 of 9 acted
on the look-alike once their own spell had gone. The ninth, Double Vision,
searched from the top and so got the first question right by position.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.oracle_types import EVENT_SPELL_MANA_COST, OracleInstruction
from tests.helpers import _nosick

#: Spells to try under each reader, in order: an instant, an enchantment, a
#: creature. One of them answers every printed narrowing in the population
#: ("an instant spell", "an enchantment spell", "a creature spell").
_SPELLS = ("Lightning Bolt", "Crusade", "Grizzly Bears")

#: Who casts the earlier and the later spell, tried in order. Seat 0 controls
#: the reader, so the three rows are "you … you", "an opponent … an opponent"
#: and "an opponent, then you" — the last is what "your **first** instant or
#: sorcery spell each turn" needs to have a look-alike underneath it.
_CASTERS = ((0, 0), (1, 1), (1, 0))


def _pool() -> list:
    """Every unit of text that compiles, in both manifest roles."""
    return list(compilation_units(load_cards(manifest_set_paths(include_measured=True))))


@pytest.fixture(scope="module")
def pool():
    return _pool()


@pytest.fixture(scope="module")
def by_name(pool):
    names: dict = {}
    for card in pool:
        names.setdefault(card.name, card)
    return names


def _walk(value):
    """Every instruction in a compiled tree, nested payloads included."""
    if isinstance(value, OracleInstruction):
        yield value
        yield from _walk(value.payload)
    elif isinstance(value, dict):
        for inner in value.values():
            yield from _walk(inner)
    elif isinstance(value, (list, tuple)):
        for inner in value:
            yield from _walk(inner)


def _acts_on_its_spell(instruction) -> bool:
    """Whether a trigger's effect needs the *object* its event was about: a
    counter bound to the trigger, a price read off the spell, a copy of it.

    Read off the compiled program, so a tenth card printed with any of these
    joins the census without being named here. A trigger that only reads the
    spell's characteristics ("where X is its mana value") is not in it: two
    spells of one card have one mana value, and no look-alike can mislead it.
    """
    for step in _walk(instruction):
        payload = step.payload or {}
        if step.kind == "copy_triggering_spell":
            return True
        if step.kind == "counter_top_stack_spell" and payload.get("bound_to_trigger"):
            return True
        cost = payload.get("cost")
        if isinstance(cost, dict) and cost.get("cost_from") == EVENT_SPELL_MANA_COST:
            return True
    return False


def readers(pool) -> list[tuple]:
    """``(card, condition kind)`` for every supported card with such a trigger."""
    found = []
    for card in pool:
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for trigger in program.triggered_abilities:
            if trigger.instruction is not None and _acts_on_its_spell(trigger.instruction):
                found.append((card, trigger.condition.kind))
                break
    return found


def _aimed(spell, at: int) -> dict:
    """A Bolt names a player; the two casts name different ones, so a copy of
    one is told from a copy of the other."""
    return {"target_player_index": at} if spell.name == "Lightning Bolt" else {}


def _stacked(by_name, reader, kind):
    """Two spells of one card on the stack with *reader*'s trigger for the
    later one on top, or None when no row of the tables above produces that.

    Returns ``(game, earlier, later, trigger)``. Both seats are interactive,
    so a price is a prompt and :func:`_answer` decides it. The seat that did
    not cast the later spell holds one of each basic land, for the one price
    somebody *else* pays (Ice Cave), and a card of the spell's name is in a
    graveyard for the one reader that asks (Bazaar of Wonders).

    The later spell's **caster** holds floating mana, for the one price that
    is theirs to pay *for* the effect: "you may pay {3}. If you do, copy that
    spell" (Mirari), whose trigger read "nothing" here whatever the engine
    did while nobody on its side could pay. Mana in the pool and not lands,
    because a land in that seat is also what Mana Vortex's caster would
    sacrifice to keep the spell - a price this census declines.
    """
    spells = [reader] if kind == "self_cast" else [by_name[name] for name in _SPELLS]
    for spell in spells:
        for first_seat, second_seat in _CASTERS:
            boards: list[list] = [[], []]
            if kind != "self_cast":
                boards[0].append(_nosick(Permanent(card=reader)))
            boards[1 - second_seat] += [
                _nosick(Permanent(card=by_name[name]))
                for name in ("Mountain", "Plains", "Forest", "Island", "Swamp")
            ]
            hands: list[list] = [[], []]
            hands[first_seat].append(spell)
            hands[second_seat].append(spell)
            game = Game(players=[
                PlayerState(name=f"P{seat}", hand=hands[seat], battlefield=boards[seat],
                            graveyard=[spell], library=[by_name["Forest"]] * 6)
                for seat in (0, 1)
            ])
            game.enforce_mana_costs = False
            game.interactive_seats = {0, 1}
            game.start_turn(0)
            game._settle()
            if not game.queue_from_hand(first_seat, spell.name, **_aimed(spell, 1)).supported:
                continue
            earlier = game.stack[0]
            before = len(game.stack)
            if not game.queue_from_hand(second_seat, spell.name, **_aimed(spell, 0)).supported:
                continue
            arrived = game.stack[before:]
            later = next((item for item in arrived if not item.is_ability), None)
            fired = [
                item for item in arrived
                if item.is_ability and item.card.name == reader.name
            ]
            if later is None or len(fired) != 1 or game.stack[-1] is not fired[0]:
                continue
            assert earlier.card is later.card, "the look-alike is the point"
            game.players[second_seat].mana_pool["C"] = 5
            return game, earlier, later, fired[0]
    return None


def _on_stack(game, item) -> bool:
    return any(held is item for held in game.stack)


def _answer(game) -> None:
    """Answer every prompt the resolving trigger armed, so that it ends in its
    counter: a price the spell's caster owes to **keep** the spell is declined
    ("counter it unless that player pays {3}"), and a price another player may
    pay to **counter** it is paid (Ice Cave). Anything else takes the
    registry's default."""
    for _ in range(20):
        if not game.pending_choices:
            return
        choice = game.pending_choices[0]
        if choice.kind == "mana_payment":
            game.confirm_mana_payment(choice.player_index, pay=False)
        elif choice.kind == "optional_pay":
            game.confirm_optional_pay(choice.player_index, accept=True)
        else:
            game.take_choice_default(choice)
    raise AssertionError(f"prompts still owed: {[c.kind for c in game.pending_choices]}")


def _resolve_and_see(game, earlier, later, trigger) -> str:
    """Resolve *trigger* and say which spell it acted on.

    ``"its own"`` / ``"the look-alike"`` / ``"nothing"``. A spell countered has
    left the stack; a spell copied has a copy above it carrying its targets.
    """
    held = list(game.stack)
    game.resolve_top_of_stack(pause_for_choices=True)
    _answer(game)
    assert not _on_stack(game, trigger), "the trigger resolved"
    copies = [item for item in game.stack if not any(item is old for old in held)]
    if copies:
        (copy,) = copies
        assert copy.is_copy
        return (
            "its own" if copy.target_player_index == later.target_player_index
            else "the look-alike"
        )
    gone_later = _on_stack_before_and_not_after(held, game, later)
    gone_earlier = _on_stack_before_and_not_after(held, game, earlier)
    if gone_earlier:
        return "the look-alike"
    return "its own" if gone_later else "nothing"


def _on_stack_before_and_not_after(held, game, item) -> bool:
    return any(old is item for old in held) and not _on_stack(game, item)


def run_census(pool, by_name) -> dict:
    """Both questions asked of every reader.

    Returns ``{"readers": [names], "unreached": [names], "later": {name:
    verdict}, "gone": {name: verdict}}``.
    """
    result = {"readers": [], "unreached": [], "later": {}, "gone": {}}
    for reader, kind in readers(pool):
        result["readers"].append(reader.name)
        table = _stacked(by_name, reader, kind)
        if table is None:
            result["unreached"].append(reader.name)
            continue
        result["later"][reader.name] = _resolve_and_see(*table)

        game, earlier, later, trigger = _stacked(by_name, reader, kind)
        # The spell leaves the stack while its trigger waits — countered in
        # response, through the seam every counter uses.
        game.counter_stack_object(later)
        result["gone"][reader.name] = _resolve_and_see(game, earlier, later, trigger)
    return result


def test_a_cast_trigger_acts_on_the_spell_that_fired_it(pool, by_name):
    """Every reader, both questions. The floor is the population the walk
    found on the day this was written — nine cards, Ice Cave the measured one;
    a walk that found none would pass on any engine."""
    census = run_census(pool, by_name)

    assert len(census["readers"]) >= 9, census["readers"]
    assert census["unreached"] == []
    wrong_later = {name: saw for name, saw in census["later"].items() if saw != "its own"}
    wrong_gone = {name: saw for name, saw in census["gone"].items() if saw != "nothing"}
    assert wrong_later == {}, "resolved for the later of two spells of one card"
    assert wrong_gone == {}, "resolved after its own spell had left the stack"
    assert len(census["later"]) == len(census["gone"]) == len(census["readers"])
