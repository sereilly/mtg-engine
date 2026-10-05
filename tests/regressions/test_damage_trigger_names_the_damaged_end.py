"""Regressions: "that creature's controller" under a damage trigger whose
damager is the source itself names the **damaged** creature's controller.

Found at Prophecy wave 1 (W1G6) and fixed at wave 2 (W2G1). Death Charmer
prints "Whenever this creature deals combat damage to a creature, that
creature's controller loses 2 life unless they pay {2}." The offer went to the
right seat — the toll's "they" was already read off the damaged player — but the
life loss lowered to ``event_subject_controller``, which a `damage_dealt` event
freezes as the **damager's** seat: the Charmer's own controller lost 2 life and
the player whose creature it hit lost nothing, while the card reported
supported and every census was green.

The damage family had already answered the same phrase the right way for
Bellowing Fiend (``lowering/_recipients.py``, through
``damage_trigger_names_damaged_end``); the life-loss lowering had never been
handed the trigger's subject, so it could not ask. A damager spelled "this
creature" cannot be the creature "that creature" names (CR 201.5: text naming
the object it is on means that object, and Oracle spells the name "this
creature"), so under such a trigger a seat key naming the
damager's controller is always a misreading — "you" is how the card would have
said it.

The census below is that sentence as an invariant over both manifest roles,
validated backwards: on the tree before the fix it names exactly Death Charmer.
"""

from __future__ import annotations

import pytest

from engine.faces import compilation_units
from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card, resolve_stack


def _instructions(instruction):
    if instruction is None:
        return
    yield instruction
    for value in (instruction.payload or {}).values():
        nested = value if isinstance(value, (list, tuple)) else (value,)
        for item in nested:
            if hasattr(item, "kind") and hasattr(item, "payload"):
                yield from _instructions(item)


def test_no_self_damager_trigger_reads_the_damagers_controller():
    """Every `damage_dealt` trigger whose damager is the source: no step of its
    effect names the damager's controller through the event's frozen seat."""
    examined = 0
    wrong: list[str] = []
    seen: set[str] = set()
    for path in manifest_set_paths(include_measured=True):
        for card in compilation_units(load_cards(path)):
            if card.name in seen:
                continue
            seen.add(card.name)
            for trigger in compile_card_oracle(card).triggered_abilities:
                condition = trigger.condition
                if condition is None or condition.kind != "damage_dealt":
                    continue
                if "damager_self" not in (condition.payload or {}):
                    continue
                examined += 1
                for step in _instructions(trigger.instruction):
                    if "event_subject_controller" in (step.payload or {}).values():
                        wrong.append(f"{card.name}: {trigger.source_line}")
    # A floor on what was examined: a census that silently stopped seeing the
    # triggers (a renamed condition key) would pass on an empty pool.
    assert examined >= 30, examined
    assert wrong == []


@pytest.mark.parametrize("pays", [False, True])
def test_death_charmer_charges_the_damaged_creatures_controller(set_pool, pays):
    """The drive: the Charmer attacks into a 0/5 Wall. Its controller's life
    never moves; the Wall's controller either pays {2} or loses 2."""
    island = set_pool("LEA")["Island"]
    game = Game(players=[
        PlayerState(name="A"),
        PlayerState(name="B", battlefield=[Permanent(card=island) for _ in range(2)]),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    charmer = Permanent(card=set_pool("PCY")["Death Charmer"])
    game._put_permanent_onto_battlefield(0, charmer, None)
    charmer.metadata["summoning_sickness_turn"] = -99
    wall = Permanent(card=_mk_card("Wall", "Creature — Wall", power=0, toughness=5))
    game._put_permanent_onto_battlefield(1, wall, None)

    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [game.players[0].battlefield.index(charmer)])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {game.players[1].battlefield.index(wall): 0})[0]
    offered = False
    for _ in range(4):
        game.advance_combat_phase()
        resolve_stack(game)
        if game.pending_choices and not offered:
            assert [c.player_index for c in game.pending_choices] == [1]
            assert game.confirm_optional_pay(1, accept=pays)
            offered = True
        resolve_stack(game)

    assert offered
    assert game.players[0].life == 20
    assert game.players[1].life == (20 if pays else 18)
