"""A card derived from another card is that card's, whatever address it lives at.

``Permanent.effective_card`` folds granted, struck and stripped lines onto the
printed card, and memoises each fold because it is read on nearly every rules
query. Four of those memos, in ``engine/models.py``, were keyed by
``id(card)``. CPython hands a dead object's address to the next allocation, so
after one card object had been granted an ability and freed, the *next* card
object given the same words could be handed the first one's fold: a different
card, with a different name, power and toughness.

Found at Apocalypse's wave-2 gate, where it looked like a flaky test. One
group's test put Foul Presence ('Enchanted creature gets -1/-1 and has
"{T}: Target creature gets -1/-1 until end of turn."') on a 1/1 it built for
the purpose, and its next test put the same Aura on a 3/3 — which, when the
two ran in one worker in that order, was a 1/1 named after the first, and
died. A token, a token copy and a card invented by a test are all objects that
come and go; the catalog's never do, which is why this shipped for two months.

The memos are keyed by ``copies.card_identity`` now — the card's printed
fields, the key ``copies.py`` and ``text_changes.py`` already used and already
said why ("never ``id()``, which a freed temporary could hand to something
else").
"""

from __future__ import annotations

import ast
import gc
from pathlib import Path

import pytest

from engine import Game, PlayerState
from engine import models
from engine.models import CardDefinition, Permanent

from tests.helpers import resolve_stack

ENGINE = Path(models.__file__).resolve().parent


def _creature(name: str, power: int, toughness: int) -> CardDefinition:
    type_line = "Creature - Test"
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line,
             "power": str(power), "toughness": str(toughness)},
    )


def _enchanted(aura_card: CardDefinition, name: str, power: int, toughness: int):
    """A fresh game in which *aura_card* has just been cast on a new creature."""
    host = Permanent(card=_creature(name, power, toughness))
    host.metadata["summoning_sickness_turn"] = -99
    game = Game(players=[
        PlayerState(name="P1", battlefield=[host], hand=[aura_card]),
        PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    cast = game.cast_from_hand(
        0, aura_card.name, target_permanent_ids=[host.permanent_id]
    )
    assert cast.supported, cast.details
    resolve_stack(game)
    game._settle()
    return game, host


@pytest.mark.parametrize("second_name", ["First", "Second"])
def test_a_creature_granted_an_ability_is_not_an_earlier_games_creature(
    set_pool, second_name,
):
    """Hermetic Study ('Enchanted creature has "{T}: This creature deals 1
    damage to any target."') on a 1/1 in one game and on a 3/3 in the next.

    The second creature is itself: its own name, its own size, and the granted
    ability. Before, with the first game's objects freed, it could read as
    "First", a 1/1 — under either name, because the memo knew an address and
    not a card.
    """
    study = set_pool("USG")["Hermetic Study"]

    game, first = _enchanted(study, "First", 1, 1)
    assert (first.effective_power, first.effective_toughness) == (1, 1)
    assert first.effective_card.name == "First"
    del game, first
    gc.collect()

    game, second = _enchanted(study, second_name, 3, 3)
    assert game.is_on_battlefield(second)
    assert second.effective_card.name == second_name
    assert (second.effective_power, second.effective_toughness) == (3, 3)
    assert [ability.source_line for ability in game.usable_abilities_of(second)] == [
        "{t}: this creature deals 1 damage to any target."
    ]


def test_the_fold_follows_the_card_through_a_reused_address():
    """The mechanism itself, with no game around it: fold a line onto a card,
    free the card, and allocate cards until one lands on the freed address.
    What that card folds to is derived from *it*.

    Skipped where no allocation lands there — the reuse is CPython's habit,
    not a promise — and the test above holds the behaviour either way.
    """
    granted = ("{t}: draw a card.",)
    first = _creature("First", 1, 1)
    address = id(first)
    assert models._with_granted_abilities(first, granted).name == "First"
    del first
    gc.collect()

    for attempt in range(20_000):
        later = _creature(f"Later {attempt}", 3, 3)
        if id(later) == address:
            folded = models._with_granted_abilities(later, granted)
            assert folded.name == later.name
            assert folded.printed_power == "3"
            return
    pytest.skip("no later card was allocated at the freed address")


def test_cards_equal_in_every_printed_field_share_a_fold_and_others_do_not():
    """What the key is: the printed fields. Two objects that are the same card
    share one folded object (which is what keeps a deck's forty copies
    compiling once), and a card differing only in its size does not."""
    granted = ("flying",)
    one, same, bigger = _creature("Bear", 2, 2), _creature("Bear", 2, 2), _creature("Bear", 4, 4)
    assert one is not same
    folded = models._with_granted_abilities(one, granted)
    assert models._with_granted_abilities(same, granted) is folded
    other = models._with_granted_abilities(bigger, granted)
    assert other is not folded and other.printed_power == "4"

    assert models._without_any_abilities(bigger).printed_power == "4"
    assert models._without_any_abilities(one) is models._without_any_abilities(same)


def test_no_engine_memo_is_keyed_by_an_objects_address():
    """The guard: nowhere under ``engine/`` is a module-level dict read or
    written under a key built from ``id(...)``.

    A scratchpad that lives for one call (a set of ``id()``s of the cards a
    handler is moving) is fine and is not what this finds: the object it
    names is alive for as long as the set is. A *module-level* dict outlives
    every object, and that is the whole defect.
    """
    offenders = []
    for path in sorted(ENGINE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        memos = set()
        for node in tree.body:
            targets = []
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            else:
                continue
            if isinstance(value, ast.Dict) and not value.keys:
                memos.update(t.id for t in targets if isinstance(t, ast.Name))
        if not memos:
            continue
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            keyed_by_address = {
                target.id
                for node in ast.walk(function) if isinstance(node, ast.Assign)
                for target in node.targets if isinstance(target, ast.Name)
                if any(
                    isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                    and call.func.id == "id"
                    for call in ast.walk(node.value)
                )
            }
            for node in ast.walk(function):
                memo, key = None, None
                if (
                    isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
                    and node.value.id in memos
                ):
                    memo, key = node.value.id, node.slice
                elif (
                    isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in memos
                    and node.func.attr in ("get", "setdefault", "pop") and node.args
                ):
                    memo, key = node.func.value.id, node.args[0]
                if memo is None:
                    continue
                direct = any(
                    isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                    and call.func.id == "id"
                    for call in ast.walk(key)
                )
                by_name = isinstance(key, ast.Name) and key.id in keyed_by_address
                if direct or by_name:
                    offenders.append(
                        f"{path.relative_to(ENGINE.parent)}:{node.lineno} {memo}"
                    )
    assert not offenders, (
        "module-level memo keyed by id(): a freed object's address is reused, "
        "so key it by what the object *is* (copies.card_identity for a card)\n"
        + "\n".join(sorted(set(offenders)))
    )
