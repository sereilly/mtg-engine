"""The battlefield-slot channel (``target_permanent_index``) has one shape.

kg4 / ``ids`` part 1. The field rode the four target holders — ``StackItem``,
``ChosenMode``, ``OracleExecutionContext`` and
``exiled_records.StackAnnouncement`` — beside the id channel, and kept the
shape the id channel had shed: an ``int`` for one slot, a list for several.
Each reader answered the arity question for itself (an ``isinstance(…,
list)`` on a holder's field, a ``_one_choice`` here, an ``_as_slots`` there),
and one written for one arity silently missed the other.

Now every holder refuses any value but None or a list of slots as it is
written (``game_types.check_target_slots``), writers hand a value of either
arity through ``as_target_slots``, and readers ask ``target_slots`` /
``single_slot`` / ``first_slot``. These tests hold:

* the guard, on every holder, at construction and at assignment;
* the accessors' answers;
* no shape check on a holder's slot field left anywhere in ``engine/`` or
  ``web/`` (a static census with a floor on what it read);
* a driven game: a one-target spell announced by slot resolves on the
  permanent it named.
"""

from __future__ import annotations

import ast
import dataclasses
import pathlib

import pytest

from engine.exiled_records import StackAnnouncement
from engine.game_types import (ChosenMode, OracleExecutionContext, StackItem,
                               as_target_slots, check_target_slots,
                               first_slot, single_slot, target_slots)
from tests.helpers import CARDS_BY_NAME, resolve_stack

_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _card():
    return CARDS_BY_NAME["Lightning Bolt"]


def _holders():
    from engine.models import PlayerState

    seat = PlayerState(name="A")
    return {
        "StackItem": lambda value: StackItem(
            _card(), 0, None, value, None,
        ),
        "ChosenMode": lambda value: ChosenMode(index=0, target_permanent_index=value),
        "OracleExecutionContext": lambda value: OracleExecutionContext(
            caster=seat, target=seat, card=_card(), target_permanent_index=value,
        ),
        "StackAnnouncement": lambda value: StackAnnouncement(
            caster_index=0, target_permanent_index=value,
        ),
    }


@pytest.mark.parametrize("holder", sorted(_holders()))
@pytest.mark.parametrize("value", [3, (3,), "3", [3.0], [True]])
def test_every_holder_refuses_a_slot_of_another_shape(holder, value):
    """A bare slot, a tuple, a string, a float or a bool is not the channel's
    shape: written at construction, it raises as it is written."""
    with pytest.raises(TypeError, match="target_permanent_index"):
        _holders()[holder](value)


@pytest.mark.parametrize("holder", sorted(_holders()))
@pytest.mark.parametrize("value", [None, [], [3], [None, 1], [0, 0]])
def test_every_holder_takes_none_or_a_list_of_slots(holder, value):
    made = _holders()[holder](value)
    assert made.target_permanent_index == value


@pytest.mark.parametrize("holder", ["StackItem", "ChosenMode", "OracleExecutionContext"])
def test_a_mutable_holder_refuses_a_bare_slot_assigned_later(holder):
    made = _holders()[holder]([1])
    with pytest.raises(TypeError, match="target_permanent_index"):
        made.target_permanent_index = 1
    made.target_permanent_index = [2, None]
    assert made.target_permanent_index == [2, None]


def test_a_replace_of_a_context_goes_through_the_guard():
    context = _holders()["OracleExecutionContext"]([0])
    with pytest.raises(TypeError, match="target_permanent_index"):
        dataclasses.replace(context, target_permanent_index=4)
    assert dataclasses.replace(context, target_permanent_index=[4]).target_permanent_index == [4]


def test_the_accessors():
    assert as_target_slots(None) is None
    assert as_target_slots(2) == [2]
    assert as_target_slots((1, 2)) == [1, 2]
    held = [1, 2]
    assert as_target_slots(held) == held and as_target_slots(held) is not held
    assert target_slots(None) == [] and target_slots([None, 4]) == [None, 4]
    # One slot is one slot, whichever arity it arrives in; several are not one.
    assert single_slot([5]) == 5 and single_slot(5) == 5
    assert single_slot([5, 6]) is None and single_slot([None]) is None
    assert single_slot(None) is None
    # Slot zero, for a single-target handler a several-slot sentence reaches.
    assert first_slot([5, 6]) == 5 and first_slot([None, 6]) is None
    check_target_slots(None)
    check_target_slots([0, None])
    with pytest.raises(TypeError):
        check_target_slots(0)


# ---------------------------------------------------------------------------
# Static census: no reader asks a holder's slot field for its arity
# ---------------------------------------------------------------------------


def _shape_checks_on_the_slot_field():
    """Every ``isinstance(<x>.target_permanent_index, …)`` in engine/ and web/,
    and how many files reading the field were examined."""
    found, examined = [], 0
    for folder in ("engine", "web"):
        for path in sorted((_ROOT / folder).rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            if ".target_permanent_index" not in text:
                continue
            examined += 1
            for node in ast.walk(ast.parse(text)):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "isinstance"
                    and node.args
                    and isinstance(node.args[0], ast.Attribute)
                    and node.args[0].attr == "target_permanent_index"
                ):
                    found.append(f"{path.relative_to(_ROOT)}:{node.lineno}")
    return found, examined


def test_no_reader_asks_a_holders_slot_field_for_its_shape():
    """The holder's field has one shape, so asking it which one is dead code
    at best — and at worst a branch that reads a one-slot list as no slot."""
    found, examined = _shape_checks_on_the_slot_field()
    # The floor is the readers' count less the margin a refactor that drains
    # some is owed: kg5's ``ids`` took the AI's and the wire's reads off the
    # field (31 files before, 24 after), each one a reader gone, not missed.
    assert examined >= 20, f"the census read only {examined} files"
    assert not found, "shape checks on a holder's slot field: " + ", ".join(found)


# ---------------------------------------------------------------------------
# A driven game
# ---------------------------------------------------------------------------


def test_a_one_slot_announcement_is_stamped_as_an_id_and_lands():
    """``target_permanent_index=1`` named at the cast is consumed into the id
    of the creature in that slot as the Bolt is pushed (part 3: the stack
    object keeps no slot), and the Bolt resolves on that creature — not its
    neighbour, not the player."""
    from engine import Game, PlayerState
    from engine.models import Permanent

    catalog = CARDS_BY_NAME
    p1 = PlayerState(name="P1", hand=[catalog["Lightning Bolt"]])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    bears = Permanent(card=catalog["Grizzly Bears"])
    giant = Permanent(card=catalog["Hill Giant"])
    game._put_permanent_onto_battlefield(1, bears, None)
    game._put_permanent_onto_battlefield(1, giant, None)
    result = game.queue_from_hand(
        0, "Lightning Bolt", target_player_index=1, target_permanent_index=1,
    )
    assert result.supported, result.details
    item = game.stack[-1]
    assert item.target_permanent_index is None
    assert item.target_permanent_id == [giant.permanent_id]
    resolve_stack(game)
    assert giant.damage_marked == 3
    assert bears.damage_marked == 0
    assert p2.life == 20
