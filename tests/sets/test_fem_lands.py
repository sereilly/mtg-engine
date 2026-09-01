"""Per-card tests for Fallen Empires' lands.

See tests/sets/README.md for the convention: get cards through
``set_pool("FEM")`` / ``set_cards("FEM")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** The wave that implemented FEM
split by grammar family rather than by printed type, so several groups land
tests in this one file. Each group appends a single delimited block:

    # --- G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared
header loses it in exactly that move -- a ``NameError`` at collection, found
only after the merge is committed. A self-contained block cannot lose one.
"""

from __future__ import annotations


# --- G5: prices offered to a player, prevention and control ---
from engine import Game, PlayerState
from engine.models import Permanent


def _g5_game(*rows) -> Game:
    game = Game(players=[PlayerState(name=f"P{i + 1}", battlefield=list(row))
                         for i, row in enumerate(rows)])
    game.enforce_mana_costs = False
    return game


def test_rainbow_vale_hands_itself_to_an_opponent_at_the_next_end_step(set_pool):
    """"{T}: Add one mana of any color. An opponent gains control of this land
    at the beginning of the next end step."

    Both halves in one activation: the mana arrives now and the control change
    is a CR 603.7 delayed ability that fires in the end step. Who gets it is a
    choice the ability's controller announces while applying the effect
    (CR 608.2c/d) — in a duel there is one answer, and the seat is recorded
    rather than assumed so a three-seat game asks.
    """
    vale = Permanent(card=set_pool("FEM")["Rainbow Vale"])
    game = _g5_game([vale], [])
    game.start_turn(0)

    assert game.activate_permanent_ability(0, "Rainbow Vale", mana_color="U").supported
    while game.stack:
        game.resolve_top_of_stack()
    assert game.players[0].mana_pool["U"] == 1
    assert game.controller_index_of(vale) == 0, "it is still yours until the end step"

    game.resolve_end_step(0)
    while game.stack:
        game.resolve_top_of_stack()

    assert game.controller_index_of(vale) == 1, game.log
    # CR 613 layer 2 is a contribution, not a move: the seat it entered under
    # is untouched, which is what CR 108.3 ownership still reads.
    assert vale.metadata.get("base_controller_index") in (0, None)


def test_rainbow_vale_does_not_change_hands_before_the_end_step(set_pool):
    """The delay is the card. Nothing fires until an end step, so the land is
    still producing mana for its own controller in the meantime."""
    vale = Permanent(card=set_pool("FEM")["Rainbow Vale"])
    game = _g5_game([vale], [])
    game.start_turn(0)
    game.activate_permanent_ability(0, "Rainbow Vale", mana_color="G")
    while game.stack:
        game.resolve_top_of_stack()

    game.resolve_upkeep(0)
    assert game.controller_index_of(vale) == 0, game.log
# --- end G5 ---
