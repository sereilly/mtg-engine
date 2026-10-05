"""'Put a <kind> counter on **it**' under a trigger targets nothing (found at
INV W1G8, driving Temporal Distortion).

"Whenever a permanent becomes tapped, put a wind counter on it." (Freyalise's
Winds.) The lowering marks the instruction ``on_event_subject`` and the handler
reads the id the fire site froze — but ``targeting._from_instruction`` still
answered the kind table's ``{"kind": "creature"}`` for it, so the trigger was
announced as one that chooses a target creature:

* on a board with **no creature**, CR 603.3c removed the trigger from the
  stack, so tapping a land put no counter on it and the land untapped as usual;
* on a board with one, an interactive seat was asked to pick a target the
  resolution then ignored.

The card reported supported with every sentence claimed, and its existing tests
all had a creature on the table.
"""

from engine import Game, PlayerState
from engine.models import Permanent
from engine.named_counters import counters_on
from engine.oracle import compile_card_oracle
from engine.targeting import derive_instruction_spec
from tests.helpers import resolve_stack


def test_freyalises_winds_marks_a_land_with_no_creature_on_the_board(set_pool):
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = False
    winds = Permanent(card=set_pool("ICE")["Freyalise's Winds"])
    forest = Permanent(card=set_pool("LEA")["Forest"])
    game._put_permanent_onto_battlefield(0, winds, None)
    game._put_permanent_onto_battlefield(1, forest, None)

    game.become_tapped(forest)
    assert game.pending_choices == [], "nothing is chosen: the event named the object"
    resolve_stack(game)

    assert counters_on(forest, "wind") == 1


def test_an_event_subject_instruction_derives_no_target_spec(set_pool):
    """The cause, asked of every card that carries the marker: the pool must
    hold at least the two that print the sentence, and none may derive a
    picker for it."""
    examined = 0
    for code in ("ICE", "INV"):
        for card in set_pool(code).values():
            for ability in compile_card_oracle(card).triggered_abilities:
                instruction = ability.instruction
                if instruction is None or not instruction.payload.get("on_event_subject"):
                    continue
                examined += 1
                assert derive_instruction_spec([instruction]) is None, card.name
    assert examined >= 2
